"""
moment_detector.py
-------------------
Orquesta el pipeline completo del MVP:
  video -> extraer audio -> analizar audio -> analizar video ->
  detectar kills (best-effort) -> score combinado -> top momentos.

Puppywill AI Clipper solo encuentra y recorta los mejores momentos
(intensidad de audio, gritos/picos, risas, movimiento, acción visual,
cambios de escena, kills/multikills); la edición final (subtítulos,
efectos, títulos, música) se hace fuera de la app (p.ej. en CapCut). No
hay transcripción ni carga de modelos de lenguaje en este pipeline (el
OCR opcional del kill feed lee texto en pantalla, no transcribe voz).

Diseñado para reportar progreso (para la barra de progreso de la UI) y
para poder saltarse pasos (p.ej. si el video no se puede leer con
OpenCV, sigue funcionando solo con audio; si falla la detección de
kills, sigue funcionando con las señales genéricas de antes).
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import audio_analysis, visual_analysis, scoring, kill_events
from .video_io import VideoInfo, validate_and_probe
from .scoring import Moment, ScoreWeights

ProgressCB = Optional[Callable[[str, float], None]]  # (etapa, 0..1)


@dataclass
class AnalysisResult:
    video_info: VideoInfo
    moments: list[Moment]
    audio_features: object = None
    visual_features: object = None
    wav_path: str = ""
    # curva de intensidad combinada (grid de tiempos + score 0..100), para
    # que la UI pueda recalcular la ventana [start, end] con el mismo
    # posicionamiento dinámico si el usuario cambia la duración elegida
    action_grid: np.ndarray = field(default_factory=lambda: np.array([]))
    action_score: np.ndarray = field(default_factory=lambda: np.array([]))


def run_full_analysis(
    video_path: str,
    work_dir: str,
    clip_len_options: tuple[int, ...] = (15, 30, 45, 60),
    max_moments: int = 15,
    progress_cb: ProgressCB = None,
) -> AnalysisResult:
    def report(stage, frac):
        if progress_cb:
            progress_cb(stage, frac)

    report("Validando video", 0.0)
    info = validate_and_probe(video_path)

    work_dir_p = Path(work_dir)
    work_dir_p.mkdir(parents=True, exist_ok=True)
    wav_path = str(work_dir_p / "audio_16k_mono.wav")

    report("Extrayendo audio", 0.10)
    audio_analysis.extract_audio_wav(video_path, wav_path)

    report("Analizando energía de audio (gritos, risas, picos)", 0.35)
    audio_feats = audio_analysis.analyze_audio(wav_path)

    report("Analizando actividad visual (movimiento, cortes de escena)", 0.65)
    try:
        visual_feats = visual_analysis.analyze_visual(video_path)
    except Exception:
        visual_feats = None  # no bloquea el pipeline si el video no se puede leer con OpenCV

    report("Detectando kills", 0.80)
    kill_feats = None
    try:
        kill_feats = kill_events.build_kill_feed_features(video_path, audio_feats, visual_feats)
    except Exception:
        kill_feats = None  # best-effort: si falla, el análisis sigue con las señales genéricas

    report("Calculando puntuación combinada", 0.90)
    kill_times = kill_feats.times if kill_feats is not None else None
    kill_activity = kill_feats.kill_activity if kill_feats is not None else None
    grid, score = scoring.build_unified_score(
        audio_feats, visual_feats, kill_times=kill_times, kill_activity=kill_activity,
        weights=ScoreWeights(),
    )

    kill_event_times = [e.time for e in kill_feats.events] if kill_feats is not None else None

    report("Seleccionando mejores momentos", 0.96)
    moments = scoring.find_top_moments(
        grid, score, clip_len_options=clip_len_options, max_moments=max_moments,
        kill_event_times=kill_event_times,
    )
    for m in moments:
        scoring.tag_reasons(m, audio_feats, visual_feats)

    report("Análisis completo", 1.0)

    return AnalysisResult(
        video_info=info,
        moments=moments,
        audio_features=audio_feats,
        visual_features=visual_feats,
        wav_path=wav_path,
        action_grid=grid,
        action_score=score,
    )
