"""
visual_analysis.py
-------------------
Analiza la pista de video para detectar "actividad visual": movimiento
brusco de cámara/acción (útil para eliminaciones/jugadas en Marvel
Rivals, mates/robos en baloncesto) y cambios fuertes de escena (cortes,
kill-cams, replays).

Para que sea viable en streams de 3+ horas, NO trabajamos a los 60fps
originales: le pedimos a FFmpeg que reduzca a `sample_fps` (por defecto
2fps) durante el propio decode, y solo entonces corremos el análisis en
Python/NumPy sobre esas muestras.

El decode en sí (el paso caro, sobre todo con AV1: el decoder de
software es mucho más lento que H.264) se intenta primero por GPU vía
NVDEC (`ffmpeg -hwaccel cuda`, soporta H.264/HEVC/AV1 en RTX serie 40+ /
50+), y si no está disponible cae a CPU con el decoder de AV1 más rápido
que tengamos (libdav1d) y, como último recurso, al loop antiguo con
OpenCV. Cada nivel de la cadena solo se prueba si el anterior falla o no
está disponible - nunca se pierde precisión, solo velocidad.

En el mismo paso de muestreo (sin decodificar el video una segunda vez)
también se mide actividad en una región candidata donde el HUD del juego
suele mostrar el kill feed (ver KILL_FEED_ROI_FRAC). Es una posición por
defecto, best-effort: si el encuadre del usuario no deja ver esa zona
(p.ej. un recorte vertical centrado en el gameplay), la señal
simplemente aporta ~0 y no afecta al resto del análisis - ver
`kill_events.py`, que la combina con la señal de audio (siempre
disponible) para detectar kills.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

from .proc_utils import CancelCheck, ProgressCB1, check_cancel, ffmpeg_bin, gpu_decode_available, popen_hidden
from .video_io import validate_and_probe

# Región candidata del kill feed, como fracción (x0, y0, x1, y1) del frame
# completo. Por defecto apunta a la franja superior-derecha del área de
# juego, asumiendo un HUD nativo típico (top-right) y dejando margen para
# encuadres verticales con cámara web en la parte de arriba. Ajustable si
# se conoce el layout exacto de una grabación.
KILL_FEED_ROI_FRAC = (0.55, 0.34, 1.0, 0.46)

DEFAULT_SAMPLE_FPS = 2.0
DEFAULT_RESIZE_W = 192


@dataclass
class VisualFeatures:
    times: np.ndarray          # tiempos (s) de cada muestra
    motion_score: np.ndarray   # 0..1 movimiento/actividad entre frames consecutivos
    scene_cut_score: np.ndarray  # 0..1 probabilidad de corte de escena/replay
    duration_sec: float
    # 0..1 actividad en la región candidata del kill feed (best-effort, ver
    # KILL_FEED_ROI_FRAC); puede quedar en ~0 si esa zona no muestra HUD
    kill_roi_activity: np.ndarray = field(default_factory=lambda: np.array([]))
    decode_method: str = ""    # "gpu" | "cpu" | "cpu_cv2" - informativo, para logs/diagnóstico


def _norm01(x: np.ndarray) -> np.ndarray:
    if len(x) == 0:
        return x
    lo, hi = np.percentile(x, 5), np.percentile(x, 97)
    if hi - lo < 1e-9:
        return np.zeros_like(x)
    return np.clip((x - lo) / (hi - lo), 0.0, 1.0)


def _read_exact(stream, n: int) -> Optional[bytes]:
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def _sample_frames_ffmpeg(
    video_path: str, sample_fps: float, resize_w: int, resize_h: int,
    use_gpu: bool, av1_fast_cpu_decoder: bool,
    expected_frames: Optional[int],
    progress_cb: ProgressCB1, cancel_check: CancelCheck,
):
    """Generador: decodifica `video_path` con FFmpeg (GPU si `use_gpu`) y
    va entregando frames BGR24 ya reducidos a `resize_w`x`resize_h` y
    muestreados a `sample_fps`, sin pasar por Python frame a frame a la
    tasa original."""
    ffmpeg = ffmpeg_bin()
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostats"]
    if use_gpu:
        cmd += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
    elif av1_fast_cpu_decoder:
        cmd += ["-c:v", "libdav1d"]
    cmd += ["-i", str(video_path)]
    # flags=bilinear: mismo algoritmo de escalado que cv2.resize() por
    # defecto (INTER_LINEAR) - así la señal de motion/scene_cut sale
    # numéricamente equivalente a la del loop antiguo con OpenCV, sin
    # importar qué decoder (GPU/CPU) haya entregado el frame.
    if use_gpu:
        vf = f"fps={sample_fps},hwdownload,format=nv12,scale={resize_w}:{resize_h}:flags=bilinear,format=bgr24"
    else:
        vf = f"fps={sample_fps},scale={resize_w}:{resize_h}:flags=bilinear,format=bgr24"
    cmd += ["-vf", vf, "-pix_fmt", "bgr24", "-f", "rawvideo", "-"]

    proc = popen_hidden(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frame_bytes = resize_w * resize_h * 3
    n_read = 0
    last_report = 0.0
    try:
        while True:
            check_cancel(cancel_check, proc)
            chunk = _read_exact(proc.stdout, frame_bytes)
            if chunk is None:
                break
            frame = np.frombuffer(chunk, dtype=np.uint8).reshape(resize_h, resize_w, 3)
            yield frame
            n_read += 1
            now = time.monotonic()
            if progress_cb and expected_frames and (now - last_report) > 0.15:
                progress_cb(min(0.99, n_read / expected_frames))
                last_report = now
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
        proc.wait(timeout=15)

    if n_read == 0:
        stderr = ""
        try:
            stderr = proc.stderr.read().decode(errors="ignore")[-2000:]
        except Exception:
            pass
        raise RuntimeError(f"FFmpeg no entregó ningún frame (decode {'GPU' if use_gpu else 'CPU'}):\n{stderr}")


def _analyze_from_frame_stream(frame_iter, sample_fps: float, duration_sec: float,
                                decode_method: str) -> VisualFeatures:
    roi_x0f, roi_y0f, roi_x1f, roi_y1f = KILL_FEED_ROI_FRAC

    prev_gray = None
    prev_hist = None
    prev_roi_gray = None
    times = []
    motion_vals = []
    scene_vals = []
    kill_roi_vals = []

    idx = 0
    for frame in frame_iter:
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([frame], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
        hist = cv2.normalize(hist, hist).flatten()

        rx0, rx1 = int(roi_x0f * w), int(roi_x1f * w)
        ry0, ry1 = int(roi_y0f * h), int(roi_y1f * h)
        roi_gray = gray[ry0:ry1, rx0:rx1]

        times.append(idx / sample_fps)

        if prev_gray is not None:
            diff = cv2.absdiff(gray, prev_gray).astype(np.float32) / 255.0
            motion_vals.append(float(diff.mean()))
            hist_diff = cv2.compareHist(hist.astype(np.float32), prev_hist.astype(np.float32), cv2.HISTCMP_BHATTACHARYYA)
            scene_vals.append(float(hist_diff))
        else:
            motion_vals.append(0.0)
            scene_vals.append(0.0)

        if roi_gray.size and prev_roi_gray is not None and roi_gray.shape == prev_roi_gray.shape:
            roi_diff = cv2.absdiff(roi_gray, prev_roi_gray).astype(np.float32) / 255.0
            kill_roi_vals.append(float(roi_diff.mean()))
        else:
            kill_roi_vals.append(0.0)

        prev_gray = gray
        prev_hist = hist
        prev_roi_gray = roi_gray if roi_gray.size else None
        idx += 1

    if idx == 0:
        return VisualFeatures(times=np.array([]), motion_score=np.array([]),
                               scene_cut_score=np.array([]), duration_sec=duration_sec,
                               kill_roi_activity=np.array([]), decode_method=decode_method)

    return VisualFeatures(
        times=np.array(times, dtype=np.float32),
        motion_score=_norm01(np.array(motion_vals, dtype=np.float32)),
        scene_cut_score=_norm01(np.array(scene_vals, dtype=np.float32)),
        duration_sec=duration_sec,
        kill_roi_activity=_norm01(np.array(kill_roi_vals, dtype=np.float32)),
        decode_method=decode_method,
    )


def analyze_visual(
    video_path: str,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
    resize_w: int = DEFAULT_RESIZE_W,
    use_gpu: bool = True,
    video_info=None,
    progress_cb: ProgressCB1 = None,
    cancel_check: CancelCheck = None,
) -> VisualFeatures:
    """Muestrea el video a `sample_fps` (decodificado y reducido por
    FFmpeg, GPU si está disponible) y calcula diferencia de frames.

    - motion_score: diferencia absoluta promedio entre frames consecutivos
      (normalizado). Picos = acción rápida, peleas, jugadas.
    - scene_cut_score: diferencia de histograma de color entre frames
      consecutivos. Picos fuertes = cortes de escena/kill-cam/replay,
      que suelen marcar el clímax de un momento destacado.

    Intenta, en orden, decode GPU (NVDEC) -> decode CPU rápido (libdav1d
    para AV1) -> decode CPU por defecto -> loop OpenCV clásico. Cada paso
    solo se usa si el anterior falla; nunca cambia el resultado, solo
    cuánto tarda en llegar.
    """
    info = video_info or validate_and_probe(video_path)
    src_w, src_h = info.width, info.height
    if src_w <= 0 or src_h <= 0:
        return _analyze_visual_cv2(video_path, sample_fps=sample_fps, resize_w=resize_w)

    resize_h = max(2, int(round(resize_w * src_h / src_w / 2)) * 2)
    expected_frames = int(info.duration_sec * sample_fps) + 1 if info.duration_sec > 0 else None
    codec = (info.video_codec or "").lower()

    attempts = []
    if use_gpu and gpu_decode_available(video_path, codec):
        attempts.append(dict(use_gpu=True, av1_fast_cpu_decoder=False))
    attempts.append(dict(use_gpu=False, av1_fast_cpu_decoder=(codec == "av1")))
    attempts.append(dict(use_gpu=False, av1_fast_cpu_decoder=False))

    last_error: Optional[Exception] = None
    for attempt in attempts:
        try:
            frame_iter = _sample_frames_ffmpeg(
                video_path, sample_fps, resize_w, resize_h,
                use_gpu=attempt["use_gpu"], av1_fast_cpu_decoder=attempt["av1_fast_cpu_decoder"],
                expected_frames=expected_frames, progress_cb=progress_cb, cancel_check=cancel_check,
            )
            method = "gpu" if attempt["use_gpu"] else "cpu"
            result = _analyze_from_frame_stream(frame_iter, sample_fps, info.duration_sec, method)
            if progress_cb:
                progress_cb(1.0)
            return result
        except Exception as e:
            from .proc_utils import AnalysisCancelled
            if isinstance(e, AnalysisCancelled):
                raise
            last_error = e
            continue

    # último recurso: el loop clásico con OpenCV (más lento, pero siempre
    # ha funcionado, incluso si algo raro pasa con el pipe de FFmpeg)
    try:
        result = _analyze_visual_cv2(video_path, sample_fps=sample_fps, resize_w=resize_w)
        if progress_cb:
            progress_cb(1.0)
        return result
    except Exception:
        if last_error is not None:
            raise last_error
        raise


def _analyze_visual_cv2(video_path: str, sample_fps: float = DEFAULT_SAMPLE_FPS,
                         resize_w: int = DEFAULT_RESIZE_W) -> VisualFeatures:
    """Implementación original basada en OpenCV VideoCapture: decodifica
    TODOS los frames originales (grab() por cada uno) y solo procesa 1 de
    cada `step`. Correcta pero mucho más lenta que `_sample_frames_ffmpeg`
    en videos largos o en códecs pesados de decodificar en software como
    AV1 - se mantiene como último recurso si FFmpeg por pipe falla."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"No se pudo abrir el video para análisis visual: {video_path}")

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration_sec = frame_count / src_fps if src_fps > 0 else 0.0

    step = max(1, int(round(src_fps / sample_fps)))

    roi_x0f, roi_y0f, roi_x1f, roi_y1f = KILL_FEED_ROI_FRAC

    prev_gray = None
    prev_hist = None
    prev_roi_gray = None
    times = []
    motion_vals = []
    scene_vals = []
    kill_roi_vals = []

    frame_idx = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if frame_idx % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            h, w = frame.shape[:2]
            scale = resize_w / float(w)
            small = cv2.resize(frame, (resize_w, max(1, int(h * scale))))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

            hist = cv2.calcHist([small], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
            hist = cv2.normalize(hist, hist).flatten()

            rx0, rx1 = int(roi_x0f * w), int(roi_x1f * w)
            ry0, ry1 = int(roi_y0f * h), int(roi_y1f * h)
            roi = frame[ry0:ry1, rx0:rx1]
            roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.size else None

            t = frame_idx / src_fps
            times.append(t)

            if prev_gray is not None:
                diff = cv2.absdiff(gray, prev_gray).astype(np.float32) / 255.0
                motion_vals.append(float(diff.mean()))
                hist_diff = cv2.compareHist(hist.astype(np.float32), prev_hist.astype(np.float32), cv2.HISTCMP_BHATTACHARYYA)
                scene_vals.append(float(hist_diff))
            else:
                motion_vals.append(0.0)
                scene_vals.append(0.0)

            if roi_gray is not None and prev_roi_gray is not None and roi_gray.shape == prev_roi_gray.shape:
                roi_diff = cv2.absdiff(roi_gray, prev_roi_gray).astype(np.float32) / 255.0
                kill_roi_vals.append(float(roi_diff.mean()))
            else:
                kill_roi_vals.append(0.0)

            prev_gray = gray
            prev_hist = hist
            prev_roi_gray = roi_gray
        frame_idx += 1

    cap.release()

    if len(times) == 0:
        return VisualFeatures(times=np.array([]), motion_score=np.array([]),
                               scene_cut_score=np.array([]), duration_sec=duration_sec,
                               kill_roi_activity=np.array([]), decode_method="cpu_cv2")

    return VisualFeatures(
        times=np.array(times, dtype=np.float32),
        motion_score=_norm01(np.array(motion_vals, dtype=np.float32)),
        scene_cut_score=_norm01(np.array(scene_vals, dtype=np.float32)),
        duration_sec=duration_sec,
        kill_roi_activity=_norm01(np.array(kill_roi_vals, dtype=np.float32)),
        decode_method="cpu_cv2",
    )
