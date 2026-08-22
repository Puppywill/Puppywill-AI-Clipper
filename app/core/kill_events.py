"""
kill_events.py
---------------
Detecta eventos de "kill" combinando:

  1. Señal PRIMARIA de audio: el sonido de confirmación de eliminación es
     un transitorio CORTO y AGUDO (un "ding"/hit-marker) - sube y cae en
     1-2 ventanas de ~0.5s, a diferencia de un grito sostenido o música,
     que se mantienen altos varias ventanas seguidas. Se detecta sobre
     `AudioFeatures.rms`/`delta`, ya calculados por audio_analysis.py (no
     se vuelve a decodificar audio).
  2. Señal SECUNDARIA visual, mejor esfuerzo: `visual_analysis.py` ya
     calcula (en el mismo paso de muestreo que motion/scene_cut, sin
     costo extra) una señal de actividad en una región candidata donde
     el HUD del juego suele mostrar el kill feed. Si el encuadre del
     usuario no deja ver esa región (p.ej. un recorte vertical centrado
     en el gameplay), esta señal simplemente aporta ~0 y la detección de
     audio sigue funcionando igual - el sonido de eliminación no depende
     del encuadre.
  3. Refuerzo OCR opcional: si hay un binario de Tesseract disponible, se
     relee esa región justo en los instantes donde la señal visual marcó
     una ráfaga (pocos frames, no todo el video) para contar líneas de
     texto reales -> conteo de multikill más preciso. Si Tesseract no
     está instalado, o no lee nada, se sigue usando el conteo por
     ráfagas como proxy.
  4. Filtro de pantallas de transición (OCR, si Tesseract está
     disponible): el chime de "Ronda completada"/"Derrota"/"Victoria" es
     un transitorio de audio tan corto y agudo como el de una
     eliminación real, así que sin este filtro se cuentan como kills. Se
     lee el texto en el centro del frame en cada instante candidato y se
     descarta si aparece alguna de esas palabras - verificado con
     grabación real: sin este filtro, los "kills" con más puntuación
     resultaron ser pantallas de "Round Complete"/"Defeat".

Todo aquí es heurístico y deliberadamente best-effort: un fallo en OCR o
en la señal visual nunca debe romper el análisis (ver moment_detector.py,
que llama a todo esto envuelto en try/except).
"""
from __future__ import annotations

import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

from .audio_analysis import AudioFeatures
from .proc_utils import CancelCheck, check_cancel, ffmpeg_bin, run_hidden
from .visual_analysis import VisualFeatures, KILL_FEED_ROI_FRAC

MAX_OCR_CANDIDATES = 80  # tope duro (modo Preciso): acota el costo de OCR en videos muy largos
MAX_OCR_CANDIDATES_FAST = 40  # modo Rápido: la mitad de candidatos, misma lógica
OCR_WORKERS = 4  # cada candidato es un subproceso independiente (ffmpeg + tesseract) - seguro en paralelo

# Franja central del frame donde aparecen los banners de "Round X Complete",
# "Defeat", "Victory" - ancha a propósito (todo el ancho, buena parte del
# alto) para no depender de la posición exacta del texto en distintos
# encuadres/idiomas.
TRANSITION_TEXT_ROI_FRAC = (0.0, 0.42, 1.0, 0.65)
TRANSITION_KEYWORDS = ("complete", "defeat", "victory", "draw")


@dataclass
class KillEvent:
    time: float
    confidence: float          # 0..1
    source: str                 # "audio" | "ocr"


@dataclass
class KillFeedFeatures:
    times: np.ndarray
    kill_activity: np.ndarray   # 0..1, señal combinada resampleada a `times` (grid de audio)
    events: list[KillEvent] = field(default_factory=list)
    ocr_used: bool = False


def _norm01(x: np.ndarray) -> np.ndarray:
    if len(x) == 0:
        return x
    lo, hi = np.percentile(x, 5), np.percentile(x, 97)
    if hi - lo < 1e-9:
        return np.zeros_like(x)
    return np.clip((x - lo) / (hi - lo), 0.0, 1.0)


def tesseract_binary() -> Optional[str]:
    """Busca el binario de tesseract: primero en el PATH, y si no aparece
    (frecuente justo después de instalarlo, antes de reiniciar el
    Explorer), en la ubicación estándar de instalación en Windows -
    ruta del sistema, no de un usuario en particular, así que es
    portátil entre máquinas."""
    found = shutil.which("tesseract")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        if os.path.isfile(candidate):
            return candidate
    return None


def _detect_audio_kill_cues(audio: AudioFeatures) -> tuple[np.ndarray, list[KillEvent]]:
    """Firma de "kill cue": un pico local de rms (mayor que ambos vecinos
    inmediatos) que además CAE rápido en las 1-3 ventanas siguientes (a
    diferencia de un grito, que se sostiene) y coincide con un salto
    brusco (delta alto). Devuelve la curva 0..1 de "qué tanto parece un
    kill cue" por ventana, y la lista de eventos que superan el umbral.
    """
    n = len(audio.rms)
    if n < 5:
        return np.zeros(n, dtype=np.float32), []

    rms = audio.rms.astype(np.float64)
    delta = audio.delta.astype(np.float64)

    is_local_peak = np.zeros(n, dtype=bool)
    is_local_peak[1:-1] = (rms[1:-1] > rms[:-2]) & (rms[1:-1] > rms[2:])

    # minimo de rms en las `look` ventanas siguientes a cada punto (vectorizado
    # con relleno al final para no salirse del arreglo)
    look = 3
    padded = np.concatenate([rms, np.full(look, rms[-1])])
    min_after = np.minimum.reduce([padded[k:k + n] for k in range(1, look + 1)])
    decay = np.maximum(0.0, rms - min_after)

    decay_n = _norm01(decay)
    delta_n = _norm01(delta)
    rms_n = _norm01(rms)

    cue_score = np.where(is_local_peak, decay_n * 0.5 + delta_n * 0.3 + rms_n * 0.2, 0.0)
    cue_score = np.clip(cue_score, 0.0, 1.0).astype(np.float32)

    threshold = 0.55
    events = [
        KillEvent(time=float(audio.times[i]), confidence=float(cue_score[i]), source="audio")
        for i in np.where(cue_score >= threshold)[0]
    ]
    return cue_score, events


def _select_ocr_candidates(visual: VisualFeatures, max_candidates: int) -> list[float]:
    """Elige instantes candidatos para OCR a partir de la señal visual del
    ROI: picos por encima del percentil 85, espaciados al menos 3s entre
    sí (para no gastar OCR en el mismo destello varias veces), acotado a
    `max_candidates`."""
    activity = getattr(visual, "kill_roi_activity", None)
    if activity is None or len(activity) == 0:
        return []
    threshold = np.percentile(activity, 85)
    idx = np.where(activity >= threshold)[0]
    if len(idx) == 0:
        return []

    times = visual.times
    order = idx[np.argsort(-activity[idx])]  # de mayor a menor actividad
    selected: list[float] = []
    for i in order:
        t = float(times[i])
        if any(abs(t - s) < 3.0 for s in selected):
            continue
        selected.append(t)
        if len(selected) >= max_candidates:
            break
    return sorted(selected)


def _crop_frac(frame, roi_frac: tuple[float, float, float, float]):
    h, w = frame.shape[:2]
    x0f, y0f, x1f, y1f = roi_frac
    return frame[int(y0f * h):int(y1f * h), int(x0f * w):int(x1f * w)]


def _grab_frame_ffmpeg(video_path: str, t: float) -> Optional[np.ndarray]:
    """Extrae UN solo frame en el instante `t` sin pasar por
    cv2.VideoCapture: `-ss` ANTES de `-i` le pide a FFmpeg un seek rápido
    por keyframe (mucho más barato que decodificar desde el inicio, sobre
    todo en códecs pesados de decodificar como AV1). Cada llamada es un
    subproceso corto e independiente, así que varias corren en paralelo
    sin pisarse (ver OCR_WORKERS)."""
    try:
        ffmpeg = ffmpeg_bin()
    except Exception:
        return None
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostats",
        "-ss", f"{max(0.0, t):.3f}", "-i", str(video_path),
        "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-",
    ]
    try:
        proc = run_hidden(cmd, timeout=15)
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    arr = np.frombuffer(proc.stdout, dtype=np.uint8)
    if arr.size == 0:
        return None
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _tesseract_ocr(tess_bin: str, crop: np.ndarray) -> str:
    """Corre tesseract.exe directamente sobre la imagen (stdin -> stdout,
    sin archivos temporales ni la dependencia de pytesseract, que lanza
    su propio subproceso sin ocultar la ventana de consola)."""
    if crop is None or crop.size == 0:
        return ""
    ok, buf = cv2.imencode(".png", crop)
    if not ok:
        return ""
    try:
        proc = run_hidden([tess_bin, "stdin", "stdout"], input=buf.tobytes(), timeout=10)
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode(errors="ignore")


def _is_transition_text(text: str) -> bool:
    lowered = text.lower()
    return any(kw in lowered for kw in TRANSITION_KEYWORDS)


def _ocr_candidate(video_path: str, t: float, tess_bin: str,
                    roi_frac: tuple[float, float, float, float]) -> Optional[KillEvent]:
    frame = _grab_frame_ffmpeg(video_path, t)
    if frame is None:
        return None
    if _is_transition_text(_tesseract_ocr(tess_bin, _crop_frac(frame, TRANSITION_TEXT_ROI_FRAC))):
        return None  # pantalla de "Round Complete"/"Defeat"/"Victory", no un kill
    text = _tesseract_ocr(tess_bin, _crop_frac(frame, roi_frac))
    lines = [ln for ln in text.splitlines() if len(ln.strip()) >= 3]
    if not lines:
        return None
    return KillEvent(time=t, confidence=min(1.0, 0.5 + 0.15 * len(lines)), source="ocr")


def refine_with_ocr(video_path: str, candidate_times: list[float],
                     roi_frac: tuple[float, float, float, float] = KILL_FEED_ROI_FRAC,
                     max_candidates: int = MAX_OCR_CANDIDATES,
                     cancel_check: CancelCheck = None) -> list[KillEvent]:
    """OCR barato: solo busca en los instantes ya señalados por la señal
    visual (nunca todo el video). Cuenta líneas de texto detectadas en la
    región del kill feed como proxy de cuántas eliminaciones aparecen
    listadas a la vez (multikill) - descartando instantes que resulten
    ser una pantalla de transición (ver TRANSITION_KEYWORDS). Cada
    candidato es un frame + OCR independientes, así que corren en un
    pool de hilos pequeño (todo el costo es de subproceso, no de CPU
    Python, así que el GIL no es un problema)."""
    if not candidate_times:
        return []
    tess_bin = tesseract_binary()
    if not tess_bin:
        return []

    times = candidate_times[:max_candidates]
    events: list[KillEvent] = []
    with ThreadPoolExecutor(max_workers=OCR_WORKERS) as pool:
        futures = [pool.submit(_ocr_candidate, video_path, t, tess_bin, roi_frac) for t in times]
        for i, fut in enumerate(futures):
            if i % 4 == 0:
                check_cancel(cancel_check)
            ev = fut.result()
            if ev is not None:
                events.append(ev)

    return events


def filter_transition_screens(video_path: str, events: list[KillEvent],
                               max_checks: int = MAX_OCR_CANDIDATES,
                               cancel_check: CancelCheck = None) -> list[KillEvent]:
    """Descarta eventos de kill cuyo instante en realidad corresponde a
    una pantalla de transición (fin de ronda, derrota, victoria) en vez
    de una eliminación real - el chime de esas pantallas tiene la misma
    firma de audio corta y aguda que una eliminación. Si Tesseract no
    está disponible, no filtra nada (mismo comportamiento best-effort de
    siempre; los eventos de audio quedan sin corroborar visualmente)."""
    if not events:
        return events
    tess_bin = tesseract_binary()
    if not tess_bin:
        return events

    # si hay demasiados eventos para un video muy largo, prioriza revisar
    # los de mayor confianza primero (los que más probablemente terminen
    # como "Kill"/"Multikill" visibles al usuario)
    to_check = sorted(events, key=lambda e: -e.confidence)[:max_checks]
    check_times = sorted({e.time for e in to_check})

    def _check_one(t: float) -> Optional[float]:
        frame = _grab_frame_ffmpeg(video_path, t)
        if frame is None:
            return None
        text = _tesseract_ocr(tess_bin, _crop_frac(frame, TRANSITION_TEXT_ROI_FRAC))
        return t if _is_transition_text(text) else None

    rejected: set[float] = set()
    with ThreadPoolExecutor(max_workers=OCR_WORKERS) as pool:
        futures = [pool.submit(_check_one, t) for t in check_times]
        for i, fut in enumerate(futures):
            if i % 4 == 0:
                check_cancel(cancel_check)
            t = fut.result()
            if t is not None:
                rejected.add(t)

    if not rejected:
        return events
    return [e for e in events if e.time not in rejected]


def build_kill_feed_features(
    video_path: str,
    audio: AudioFeatures,
    visual: Optional[VisualFeatures] = None,
    use_ocr: bool = True,
    max_ocr_candidates: int = MAX_OCR_CANDIDATES,
    cancel_check: CancelCheck = None,
) -> KillFeedFeatures:
    """Combina audio (siempre disponible) + señal visual del ROI (si
    `visual_analysis.py` la calculó) + OCR opcional, en una única curva
    `kill_activity` 0..1 sobre la rejilla temporal del audio."""
    audio_cue, events = _detect_audio_kill_cues(audio)
    check_cancel(cancel_check)

    if use_ocr and events:
        filtered = filter_transition_screens(video_path, events, max_checks=max_ocr_candidates,
                                              cancel_check=cancel_check)
        rejected_times = {e.time for e in events} - {e.time for e in filtered}
        if rejected_times:
            # tambien baja la curva continua en esos instantes: sin esto, el
            # chime de transicion seguiria inflando el score combinado aunque
            # ya no cuente como evento de kill
            reject_mask = np.isin(audio.times, np.array(sorted(rejected_times), dtype=audio.times.dtype))
            audio_cue = np.where(reject_mask, 0.0, audio_cue)
        events = filtered

    times = audio.times
    activity = audio_cue.astype(np.float64)
    ocr_used = False

    if visual is not None and len(getattr(visual, "times", [])) > 0:
        visual_activity = getattr(visual, "kill_roi_activity", None)
        if visual_activity is not None and len(visual_activity) > 0:
            visual_on_grid = np.interp(times, visual.times, visual_activity, left=0.0, right=0.0)
            activity = np.clip(activity + 0.4 * visual_on_grid, 0.0, 1.0)

            if use_ocr:
                candidates = _select_ocr_candidates(visual, max_ocr_candidates)
                ocr_events = refine_with_ocr(video_path, candidates, max_candidates=max_ocr_candidates,
                                              cancel_check=cancel_check)
                if ocr_events:
                    events.extend(ocr_events)
                    ocr_used = True

    events.sort(key=lambda e: e.time)
    return KillFeedFeatures(
        times=times,
        kill_activity=activity.astype(np.float32),
        events=events,
        ocr_used=ocr_used,
    )
