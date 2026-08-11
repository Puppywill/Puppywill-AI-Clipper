"""
visual_analysis.py
-------------------
Analiza la pista de video con OpenCV para detectar "actividad visual":
movimiento brusco de cámara/acción (útil para eliminaciones/jugadas en
Marvel Rivals, mates/robos en baloncesto) y cambios fuertes de escena
(cortes, kill-cams, replays).

Para que sea viable en streams de 3+ horas, NO decodificamos cada frame:
muestreamos a un frame rate bajo (por defecto 2 fps) y a baja resolución.
Esto es intencionalmente ligero en CPU; si hay GPU NVENC/CUDA disponible
se usa solo para el decode acelerado (ver decode_hint), el cálculo de
diferencia de frames en sí es trivial en CPU.
"""
from __future__ import annotations

import cv2
import numpy as np
from dataclasses import dataclass


@dataclass
class VisualFeatures:
    times: np.ndarray          # tiempos (s) de cada muestra
    motion_score: np.ndarray   # 0..1 movimiento/actividad entre frames consecutivos
    scene_cut_score: np.ndarray  # 0..1 probabilidad de corte de escena/replay
    duration_sec: float


def analyze_visual(video_path: str, sample_fps: float = 2.0, resize_w: int = 160) -> VisualFeatures:
    """Muestrea el video a `sample_fps` y calcula diferencia de frames.

    - motion_score: diferencia absoluta promedio entre frames consecutivos
      (normalizado). Picos = acción rápida, peleas, jugadas.
    - scene_cut_score: diferencia de histograma de color entre frames
      consecutivos. Picos fuertes = cortes de escena/kill-cam/replay,
      que suelen marcar el clímax de un momento destacado.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"No se pudo abrir el video para análisis visual: {video_path}")

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration_sec = frame_count / src_fps if src_fps > 0 else 0.0

    step = max(1, int(round(src_fps / sample_fps)))

    prev_gray = None
    prev_hist = None
    times = []
    motion_vals = []
    scene_vals = []

    frame_idx = 0
    sampled_idx = 0
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

            prev_gray = gray
            prev_hist = hist
            sampled_idx += 1
        frame_idx += 1

    cap.release()

    if len(times) == 0:
        return VisualFeatures(times=np.array([]), motion_score=np.array([]),
                               scene_cut_score=np.array([]), duration_sec=duration_sec)

    times = np.array(times, dtype=np.float32)
    motion = np.array(motion_vals, dtype=np.float32)
    scene = np.array(scene_vals, dtype=np.float32)

    def _norm01(x: np.ndarray) -> np.ndarray:
        if len(x) == 0:
            return x
        lo, hi = np.percentile(x, 5), np.percentile(x, 97)
        if hi - lo < 1e-9:
            return np.zeros_like(x)
        return np.clip((x - lo) / (hi - lo), 0.0, 1.0)

    return VisualFeatures(
        times=times,
        motion_score=_norm01(motion),
        scene_cut_score=_norm01(scene),
        duration_sec=duration_sec,
    )
