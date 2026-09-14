"""
gaming_events.py
-----------------
Generaliza `kill_events.py` para el modo Gaming: además del "kill" (el
mismo detector de audio ya validado, sin tocarlo), detecta:

  - **Ultimates/habilidades**: a diferencia del "ding" de kill (pico
    corto que CAE en 1-3 ventanas de 0.5s), la línea de voz/sonido de
    activar una ultimate se SOSTIENE alto varias ventanas (~1.5-3s)
    antes de bajar. Se corrobora con un cambio grande de brillo o de
    escena a pantalla completa en el mismo instante (las ultimates en
    shooters estilo Overwatch suelen ir con un flash o cambio de color
    de pantalla completa) - exigir ambas señales reduce falsos
    positivos de gritos/risas normales que también son "sostenidos".
  - **Fin de ronda (Round End)**: usa la MISMA firma de audio de
    transición corta y aguda que hoy `kill_events.py` descarta como
    falso-positivo de kill - aquí, en cambio, se conserva como su
    propio evento positivo (el usuario quiere ver el fin de ronda,
    victoria/derrota). Un intento best-effort por OCR de distinguir
    Victory/Defeat (baja confianza: Tesseract no lee bien la fuente
    estilizada de Marvel Rivals, confirmado empíricamente - si no lee
    nada, el evento queda como "round_end" genérico, no se pierde).
  - **Rachas (Killstreak)**: agrupa los eventos de kill ya detectados
    por densidad temporal - varios kills MUY juntos (team wipe/ace) se
    quedan como "Multikill", varios kills repartidos en una ventana más
    larga (pero sin pausas grandes entre ellos) se etiquetan aparte
    como "Killstreak". No cambia el conteo ya validado, solo cómo se
    interpreta.

Todo heurístico y best-effort, igual que kill_events.py: un fallo en
cualquier detector no debe romper el resto del análisis (moment_detector
llama a todo esto envuelto en try/except).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .audio_analysis import AudioFeatures
from .games import GameProfile
from .kill_events import (
    MAX_OCR_CANDIDATES,
    OCR_WORKERS,
    KillEvent,
    _crop_frac,
    _detect_audio_kill_cues,
    _grab_frame_ffmpeg,
    _norm01,
    _tesseract_ocr,
    tesseract_binary,
)
from .proc_utils import CancelCheck, check_cancel
from .visual_analysis import VisualFeatures


@dataclass
class GamingEvent:
    time: float
    kind: str          # "kill" | "multikill_moment" | "ultimate" | "round_end"
    confidence: float
    source: str         # "audio" | "audio+visual" | "ocr"


@dataclass
class GamingFeatures:
    times: np.ndarray
    kill_activity: np.ndarray         # 0..1, igual que KillFeedFeatures.kill_activity
    ultimate_activity: np.ndarray      # 0..1
    round_end_activity: np.ndarray     # 0..1
    kill_events: list[KillEvent] = field(default_factory=list)
    ultimate_events: list[GamingEvent] = field(default_factory=list)
    round_end_events: list[GamingEvent] = field(default_factory=list)
    ocr_used: bool = False


def _detect_ultimate_cues(audio: AudioFeatures, visual: Optional[VisualFeatures]) -> tuple[np.ndarray, list[GamingEvent]]:
    n = len(audio.rms)
    if n < 8:
        return np.zeros(n, dtype=np.float32), []

    rms = audio.rms.astype(np.float64)
    delta = audio.delta.astype(np.float64)
    rms_n = _norm01(rms)
    delta_n = _norm01(delta)

    is_local_peak = np.zeros(n, dtype=bool)
    is_local_peak[1:-1] = (rms[1:-1] > rms[:-2]) & (rms[1:-1] > rms[2:])

    # "huella" de sostenimiento: fracción de ventanas ELEVADAS (por encima de
    # un umbral moderado, no solo el pico) en un entorno de +/- `radius`
    # ventanas alrededor de cada punto. Un kill es un pico aislado de UNA
    # ventana (huella angosta, ~1/9); una ultimate se mantiene alta varias
    # ventanas seguidas antes/después del pico (huella ancha) - esto separa
    # mejor "sostenido" de "corto" que solo mirar hacia adelante desde el
    # pico exacto (que puede caer justo cuando el sonido empieza a bajar).
    radius = 4
    elevated = (rms_n > 0.35).astype(np.float64)
    kernel = np.ones(2 * radius + 1)
    footprint = np.convolve(elevated, kernel, mode="same") / (2 * radius + 1)

    audio_score = np.where(is_local_peak, rms_n * 0.25 + delta_n * 0.05 + footprint * 0.70, 0.0)

    vis_score = np.zeros(n, dtype=np.float64)
    if visual is not None and len(getattr(visual, "times", [])) > 0:
        for attr in ("brightness_spike", "scene_cut_score"):
            curve = getattr(visual, attr, None)
            if curve is not None and len(curve) > 0:
                on_grid = np.interp(audio.times, visual.times, curve, left=0.0, right=0.0)
                vis_score = np.maximum(vis_score, on_grid)

    combined = np.clip(audio_score * 0.70 + vis_score * 0.30, 0.0, 1.0).astype(np.float32)

    threshold = 0.55
    events = [
        GamingEvent(
            time=float(audio.times[i]), kind="ultimate", confidence=float(combined[i]),
            source="audio+visual" if vis_score[i] > 0.2 else "audio",
        )
        for i in np.where(combined >= threshold)[0]
    ]
    return combined, events


def _detect_round_end_cues(
    video_path: str, kill_like_events: list[KillEvent], profile: GameProfile,
    cancel_check: CancelCheck = None,
) -> tuple[list[GamingEvent], set]:
    """Reclasifica (no descarta) eventos de kill cuyo instante en realidad
    corresponde a una pantalla de fin de ronda: misma firma de audio corta y
    aguda que un kill real, distinguible solo por lo que aparece en pantalla.
    Devuelve (eventos de round_end, tiempos reclasificados a excluir de la
    lista de kills). Cada candidato es un frame + OCR independientes (igual
    que kill_events.refine_with_ocr), así que corren en un pool de hilos
    pequeño en vez de uno por uno."""
    if not kill_like_events or not profile.transition_text_roi:
        return [], set()
    tess_bin = tesseract_binary()
    if not tess_bin:
        return [], set()

    to_check = sorted(kill_like_events, key=lambda e: -e.confidence)[:MAX_OCR_CANDIDATES]

    def _check_one(e: KillEvent) -> Optional[float]:
        frame = _grab_frame_ffmpeg(video_path, e.time)
        if frame is None:
            return None
        text = _tesseract_ocr(tess_bin, _crop_frac(frame, profile.transition_text_roi))
        lowered = text.lower()
        return e.time if any(kw in lowered for kw in profile.transition_keywords) else None

    reclassified: set = set()
    with ThreadPoolExecutor(max_workers=OCR_WORKERS) as pool:
        futures = [pool.submit(_check_one, e) for e in to_check]
        for i, fut in enumerate(futures):
            if i % 4 == 0:
                check_cancel(cancel_check)
            t = fut.result()
            if t is not None:
                reclassified.add(t)

    conf_by_time = {e.time: e.confidence for e in to_check}
    round_events = [
        GamingEvent(time=t, kind="round_end", confidence=conf_by_time[t], source="ocr")
        for t in sorted(reclassified)
    ]
    return round_events, reclassified


def group_kill_streaks(kill_times: list[float], simultaneous_span: float = 4.0) -> dict[float, str]:
    """Agrupa una lista de tiempos de kill (dentro de un mismo clip, ya
    filtrada por el llamador) en 'multikill_moment' (todos muy juntos, un
    team wipe/ace) o 'killstreak' (repartidos en una ventana más amplia,
    varias eliminaciones seguidas sin pausas largas). Devuelve un dict
    tiempo->etiqueta, no cambia el conteo total de kills."""
    if not kill_times:
        return {}
    times = sorted(kill_times)
    span = times[-1] - times[0]
    label = "multikill_moment" if span <= simultaneous_span else "killstreak"
    return {t: label for t in times}


def build_gaming_features(
    video_path: str,
    audio: AudioFeatures,
    visual: Optional[VisualFeatures],
    profile: GameProfile,
    cancel_check: CancelCheck = None,
) -> GamingFeatures:
    """Combina kill (reutilizado tal cual de kill_events.py) + ultimate +
    fin de ronda en una sola estructura, sobre la rejilla temporal del
    audio - análogo a `KillFeedFeatures` pero con más tipos de evento."""
    kill_cue, kill_like_events = _detect_audio_kill_cues(audio)
    check_cancel(cancel_check)
    ultimate_cue, ultimate_events = _detect_ultimate_cues(audio, visual)
    check_cancel(cancel_check)

    round_events, reclassified = _detect_round_end_cues(video_path, kill_like_events, profile,
                                                          cancel_check=cancel_check)
    kill_events_final = [e for e in kill_like_events if e.time not in reclassified]

    times = audio.times
    kill_activity = kill_cue.astype(np.float64)
    if reclassified:
        reject_mask = np.isin(times, np.array(sorted(reclassified), dtype=times.dtype))
        kill_activity = np.where(reject_mask, 0.0, kill_activity)

    round_end_activity = np.zeros_like(kill_activity)
    if reclassified:
        accept_mask = np.isin(times, np.array(sorted(reclassified), dtype=times.dtype))
        round_end_activity = np.where(accept_mask, kill_cue.astype(np.float64), 0.0)

    return GamingFeatures(
        times=times,
        kill_activity=kill_activity.astype(np.float32),
        ultimate_activity=ultimate_cue,
        round_end_activity=round_end_activity.astype(np.float32),
        kill_events=kill_events_final,
        ultimate_events=ultimate_events,
        round_end_events=round_events,
        ocr_used=bool(round_events),
    )
