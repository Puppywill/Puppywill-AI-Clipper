"""
moment_detector.py
-------------------
Orquesta el pipeline completo del MVP:
  video -> extraer audio + analizar video (en paralelo) ->
  analizar energía de audio -> detectar kills (best-effort) ->
  score combinado -> top momentos.

Puppywill AI Clipper solo encuentra y recorta los mejores momentos
(intensidad de audio, gritos/picos, risas, movimiento, acción visual,
cambios de escena, kills/multikills); la edición final (subtítulos,
efectos, títulos, música) se hace fuera de la app (p.ej. en CapCut). No
hay transcripción ni carga de modelos de lenguaje en este pipeline (el
OCR opcional del kill feed lee texto en pantalla, no transcribe voz).

Diseñado para reportar progreso real (para la barra de progreso de la
UI, incluyendo tiempo estimado restante calculado por la UI a partir de
frac/tiempo transcurrido), para poder cancelarse a mitad de camino sin
congelar la app (ver `cancel_check`/`AnalysisCancelled`), y para poder
saltarse pasos (p.ej. si el video no se puede leer con OpenCV, sigue
funcionando solo con audio; si falla la detección de kills, sigue
funcionando con las señales genéricas de antes).

Hay dos modos, elegidos por el usuario en la UI (Rápido es el
predeterminado): Rápido muestrea menos frames/candidatos OCR, Preciso
muestrea más. La decodificación acelerada por GPU se usa en ambos modos
por igual cuando está disponible - no es un trade-off de calidad, solo
de qué tan rápido decodifica FFmpeg.
"""
from __future__ import annotations

import numpy as np
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import audio_analysis, visual_analysis, scoring, kill_events, gaming_events, analysis_cache
from .games import get_profile
from .proc_utils import AnalysisCancelled, CancelCheck, check_cancel
from .video_io import VideoInfo, validate_and_probe
from .scoring import Moment, ScoreWeights, GamingScoreWeights

ProgressCB = Optional[Callable[[str, float], None]]  # (clave de etapa i18n, 0..1)


@dataclass(frozen=True)
class AnalysisMode:
    key: str    # "fast" | "precise" - estable, NO traducido (identificador interno,
                # usado para el caché en disco); el texto que ve el usuario sale de
                # i18n.t(f"mode.{key}") en la UI, nunca de este campo
    name: str   # nombre legible en español, solo para logs/debug fuera de la UI
    sample_fps: float
    resize_w: int
    max_ocr_candidates: int


# Rápido (predeterminado): menos muestras/segundo y menos candidatos OCR.
# La decodificación GPU ya hace la parte cara (el decode en sí) igual de
# rápida en los dos modos - lo que cambia es cuánto se analiza después.
FAST_MODE = AnalysisMode(key="fast", name="Rápido", sample_fps=1.5, resize_w=160,
                          max_ocr_candidates=kill_events.MAX_OCR_CANDIDATES_FAST)
PRECISE_MODE = AnalysisMode(key="precise", name="Preciso", sample_fps=3.0, resize_w=224,
                             max_ocr_candidates=kill_events.MAX_OCR_CANDIDATES)
MODES = {FAST_MODE.key: FAST_MODE, PRECISE_MODE.key: PRECISE_MODE}


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
    from_cache: bool = False


def run_full_analysis(
    video_path: str,
    work_dir: str,
    clip_len_options: tuple[int, ...] = (15, 30, 45, 60),
    max_moments: int = 15,
    mode: AnalysisMode = FAST_MODE,
    detection_mode: str = "general",   # "general" | "gaming"
    game_key: str = "auto",             # ver app/core/games/ - solo relevante si detection_mode="gaming"
    progress_cb: ProgressCB = None,
    cancel_check: CancelCheck = None,
    use_cache: bool = True,
) -> AnalysisResult:
    def report(stage, frac):
        if progress_cb:
            progress_cb(stage, frac)

    is_gaming = detection_mode == "gaming"
    game_profile = get_profile(game_key) if is_gaming else None

    check_cancel(cancel_check)
    report("stage.validating", 0.0)
    info = validate_and_probe(video_path)
    check_cancel(cancel_check)

    if use_cache:
        cached = analysis_cache.load(video_path, mode, clip_len_options, max_moments,
                                      detection_mode=detection_mode, game_key=game_key)
        if cached is not None:
            report("stage.loaded_from_cache", 1.0)
            cached.from_cache = True
            return cached

    work_dir_p = Path(work_dir)
    work_dir_p.mkdir(parents=True, exist_ok=True)
    wav_path = str(work_dir_p / "audio_16k_mono.wav")

    # audio y video se leen del mismo archivo pero son dos pasadas
    # independientes de FFmpeg (una sin video -vn, otra sin audio) - no hay
    # nada que las obligue a ser secuenciales, así que corren en paralelo.
    # El audio siempre es mucho más rápido; el tiempo total de esta etapa
    # lo domina el análisis visual, así que el progreso reportado sigue el
    # de `analyze_visual`.
    def _visual_progress(local_frac: float):
        report("stage.analyzing_av", 0.05 + 0.70 * local_frac)

    report("stage.extract_analyze", 0.02)
    audio_feats = None
    visual_feats = None
    with ThreadPoolExecutor(max_workers=2) as pool:
        def _do_audio():
            audio_analysis.extract_audio_wav(video_path, wav_path, cancel_check=cancel_check)
            return audio_analysis.analyze_audio(wav_path)

        f_audio = pool.submit(_do_audio)
        f_visual = pool.submit(
            visual_analysis.analyze_visual, video_path,
            sample_fps=mode.sample_fps, resize_w=mode.resize_w, use_gpu=True,
            video_info=info, progress_cb=_visual_progress, cancel_check=cancel_check,
            hud_regions=(game_profile.hud_regions if game_profile else None),
            compute_optical_flow=is_gaming,
        )

        # OJO: si cualquiera de los dos lanza AnalysisCancelled, se relanza
        # de inmediato; al salir del bloque `with` el pool espera (join) a
        # que el otro hilo también termine de abortar su propio subproceso
        # de FFmpeg vía el mismo `cancel_check` compartido - no se queda
        # ningún proceso de FFmpeg colgado en segundo plano.
        audio_error = None
        try:
            audio_feats = f_audio.result()
        except AnalysisCancelled:
            raise
        except Exception as e:
            audio_error = e

        try:
            visual_feats = f_visual.result()
        except AnalysisCancelled:
            raise
        except Exception:
            visual_feats = None  # no bloquea el pipeline si el video no se puede leer

        if audio_feats is None:
            raise audio_error  # el audio SÍ es obligatorio (es la señal primaria)

    check_cancel(cancel_check)

    report("stage.detecting_kills", 0.75)
    kill_feats = None
    gaming_feats = None
    try:
        if is_gaming:
            gaming_feats = gaming_events.build_gaming_features(
                video_path, audio_feats, visual_feats, game_profile, cancel_check=cancel_check,
            )
        else:
            kill_feats = kill_events.build_kill_feed_features(
                video_path, audio_feats, visual_feats,
                max_ocr_candidates=mode.max_ocr_candidates, cancel_check=cancel_check,
            )
    except AnalysisCancelled:
        raise
    except Exception:
        # best-effort: si falla, el análisis sigue con las señales genéricas
        kill_feats = None
        gaming_feats = None
    check_cancel(cancel_check)

    report("stage.scoring", 0.92)
    if is_gaming:
        grid, score = scoring.build_gaming_score(
            audio_feats, visual_feats, gaming_feats, weights=GamingScoreWeights(),
        )
    else:
        kill_times = kill_feats.times if kill_feats is not None else None
        kill_activity = kill_feats.kill_activity if kill_feats is not None else None
        grid, score = scoring.build_unified_score(
            audio_feats, visual_feats, kill_times=kill_times, kill_activity=kill_activity,
            weights=ScoreWeights(),
        )

    report("stage.selecting_moments", 0.96)
    if is_gaming:
        moments = scoring.find_top_gaming_moments(
            grid, score, gaming_feats=gaming_feats,
            clip_len_options=clip_len_options, max_moments=max_moments,
        )
    else:
        kill_event_times = [e.time for e in kill_feats.events] if kill_feats is not None else None
        moments = scoring.find_top_moments(
            grid, score, clip_len_options=clip_len_options, max_moments=max_moments,
            kill_event_times=kill_event_times,
        )
    for m in moments:
        scoring.tag_reasons(m, audio_feats, visual_feats)

    report("stage.complete", 1.0)

    result = AnalysisResult(
        video_info=info,
        moments=moments,
        audio_features=audio_feats,
        visual_features=visual_feats,
        wav_path=wav_path,
        action_grid=grid,
        action_score=score,
    )
    if use_cache:
        analysis_cache.save(video_path, mode, clip_len_options, max_moments, result,
                             detection_mode=detection_mode, game_key=game_key)
    return result
