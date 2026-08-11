"""
scoring.py
----------
Combina las señales de audio_analysis y visual_analysis en una sola
curva de "score" a lo largo de todo el stream, encuentra los picos de
mayor intensidad (la "jugada"), y construye alrededor de cada uno un
clip con estructura: preparación breve -> jugada principal -> cierre/
reacción, en vez de una ventana centrada a ciegas en el pico.

La idea general:
  score(t) = w_audio_peak   * peak_score(t)
           + w_laughter     * laughter_score(t)
           + w_motion       * motion_score(t)
           + w_scene_cut    * scene_cut_score(t)

A partir de score(t):
  1. Se detectan los picos (segundo exacto de mayor intensidad), más
     candidatos de los que finalmente se entregan.
  2. Para cada pico y cada duración candidata, se calcula una ventana
     con el pico posicionado ~60-75% del clip (más preparación/jugada
     antes que cierre después), probando variantes de proporción y de
     desplazamiento del ancla para que los bordes caigan en tramos
     tranquilos (evita cortar a mitad de una acción sin resolución).
  3. Cada ventana recibe una puntuación de calidad 0..100 que premia
     forma "sube -> pico -> baja" (jugada + resultado) y penaliza bordes
     con acción sin resolver y solapamiento con tramos estáticos
     (menús, respawn, espera).
  4. Se agrupan picos cercanos (misma jugada) y se entregan solo los
     mejores y más distintos.

`tag_reasons` añade después las etiquetas legibles ("Pico de audio",
"Acción alta", "Reacción", "Cierre detectado") inspeccionando las
señales de audio/video crudas alrededor de cada momento aceptado.
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Optional

from .audio_analysis import AudioFeatures
from .visual_analysis import VisualFeatures


@dataclass
class ScoreWeights:
    audio_peak: float = 1.0
    laughter: float = 0.8
    motion: float = 0.7
    scene_cut: float = 0.5


@dataclass
class Moment:
    start: float
    end: float
    score: float                          # 0..100, calidad general del clip (no solo intensidad del pico)
    peak_time: float                      # segundo exacto de mayor intensidad detectada
    reasons: list[str] = field(default_factory=list)


# El pico cae ~67% del clip: preparación + jugada antes, cierre/reacción
# después. Las variantes de proporción cubren exactamente el rango
# 60-75% pedido; NUNCA se desplaza el ancla por separado del pico real,
# porque eso movería el pico fuera de esa banda (ej. ancla+3s en un
# clip de 15s ya es un 20% del clip). La duración final es siempre
# exactamente la pedida (los dos bordes se mueven juntos).
PRE_ROLL_RATIO = 2.0 / 3.0
_RATIO_VARIANTS = (0.60, 0.65, 0.70, 0.75)


def _resample_to_grid(times: np.ndarray, values: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Interpola linealmente `values(times)` sobre una rejilla temporal común `grid`."""
    if len(times) == 0:
        return np.zeros_like(grid)
    return np.interp(grid, times, values, left=values[0], right=values[-1])


def build_unified_score(
    audio: AudioFeatures,
    visual: Optional[VisualFeatures] = None,
    weights: ScoreWeights = ScoreWeights(),
    grid_step: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    """Devuelve (grid_times, score) con score en la misma rejilla temporal.

    grid_step debe coincidir (o ser múltiplo) de WINDOW_SECONDS de audio_analysis
    para máxima fidelidad, pero funciona igual si no coincide gracias a la
    interpolación.
    """
    duration = audio.duration_sec
    if visual is not None and visual.duration_sec > 0:
        duration = max(duration, visual.duration_sec)

    grid = np.arange(0, duration, grid_step, dtype=np.float32)
    if len(grid) == 0:
        grid = np.array([0.0], dtype=np.float32)

    peak = _resample_to_grid(audio.times, audio.peak_score, grid)
    laugh = _resample_to_grid(audio.times, audio.laughter_score, grid)

    score = weights.audio_peak * peak + weights.laughter * laugh

    if visual is not None and len(visual.times) > 0:
        motion = _resample_to_grid(visual.times, visual.motion_score, grid)
        scene = _resample_to_grid(visual.times, visual.scene_cut_score, grid)
        score = score + weights.motion * motion + weights.scene_cut * scene

    # normalizar a 0..100 para que sea legible en la UI
    if score.max() > 0:
        score = 100.0 * score / (score.max() + 1e-9)

    return grid, score


def compute_clip_window(
    peak_time: float,
    length_sec: float,
    video_duration: float,
    grid: Optional[np.ndarray] = None,
    score: Optional[np.ndarray] = None,
) -> tuple[float, float]:
    """Calcula [start, end] de duración EXACTA `length_sec` anclada en
    `peak_time`, con el pico cayendo ~60-75% del clip (preparación breve
    -> jugada -> cierre/reacción), en vez de centrarlo simétricamente.

    Si se pasa la curva de intensidad (grid, score), prueba las
    proporciones pre/post-roll dentro de esa misma banda 60-75% y elige
    la que corta en los puntos más tranquilos (menor intensidad
    exactamente en los bordes) para no cortar a mitad de una acción sin
    resolución - el pico SIEMPRE queda dentro de 60-75%, nunca se
    desplaza el ancla por separado (eso lo sacaría de la banda). Los dos
    bordes siempre se mueven juntos, así que la duración final es
    siempre exactamente `length_sec`.
    """
    video_duration = max(0.1, float(video_duration))
    length_sec = max(1.0, min(float(length_sec), video_duration))

    def _clamped(start: float) -> tuple[float, float]:
        start = max(0.0, min(start, video_duration - length_sec))
        return start, start + length_sec

    if grid is None or score is None or len(grid) < 3:
        return _clamped(peak_time - length_sec * PRE_ROLL_RATIO)

    best_key = None
    best_window = None
    for ratio in _RATIO_VARIANTS:
        start, end = _clamped(peak_time - length_sec * ratio)
        tension = float(np.interp(start, grid, score)) + float(np.interp(end, grid, score))
        # empatando en tensión, preferir la proporción nominal (2/3)
        key = (round(tension, 3), abs(ratio - PRE_ROLL_RATIO))
        if best_key is None or key < best_key:
            best_key = key
            best_window = (start, end)

    return best_window


def _static_mask(grid: np.ndarray, score: np.ndarray, min_run_seconds: float = 3.0,
                  percentile: float = 20.0) -> np.ndarray:
    """Marca tramos SOSTENIDOS de intensidad muy baja: candidatos a
    menús, pantallas de espera, respawn o tiempo muerto. Heurística de
    energía únicamente (no clasifica la imagen), pero un tramo corto y
    aislado de baja intensidad no cuenta (para no penalizar respiros
    normales dentro de una jugada)."""
    if len(score) == 0:
        return np.zeros(0, dtype=bool)
    threshold = np.percentile(score, percentile)
    low = score <= threshold
    step = float(grid[1] - grid[0]) if len(grid) > 1 else 1.0
    run_len = max(1, int(round(min_run_seconds / step)))

    mask = np.zeros_like(low)
    run_start = None
    for i, v in enumerate(low):
        if v:
            if run_start is None:
                run_start = i
        elif run_start is not None:
            if i - run_start >= run_len:
                mask[run_start:i] = True
            run_start = None
    if run_start is not None and len(low) - run_start >= run_len:
        mask[run_start:] = True
    return mask


def _find_peak_times(
    grid: np.ndarray, score: np.ndarray, min_gap_seconds: float, max_candidates: int,
) -> list[tuple[float, float]]:
    """Encuentra el segundo EXACTO de mayor intensidad repetidamente
    (supresión de no-máximos sobre la curva punto a punto, no sobre un
    promedio de ventana), generando más candidatos de los que se van a
    entregar finalmente."""
    if len(grid) < 2:
        return []
    step = float(grid[1] - grid[0])
    sep = max(1, int(round(min_gap_seconds / step)))
    work = score.astype(np.float64).copy()
    peaks: list[tuple[float, float]] = []

    for _ in range(max_candidates):
        idx = int(np.argmax(work))
        val = work[idx]
        if not np.isfinite(val) or val <= 0:
            break
        peaks.append((float(grid[idx]), float(val)))
        lo = max(0, idx - sep)
        hi = min(len(work), idx + sep + 1)
        work[lo:hi] = -np.inf

    return peaks


def _window_quality(
    grid: np.ndarray, score: np.ndarray, static_mask: np.ndarray,
    start: float, end: float, peak_val: float,
) -> float:
    """Puntuación de calidad 0..100 de una ventana concreta: fuerza del
    pico + forma "sube -> pico -> baja" (jugada + resultado), menos
    penalización por cortar los bordes en medio de acción sin resolver
    y por solapar con tramos estáticos (menús/espera/respawn)."""
    mask = (grid >= start) & (grid <= end)
    if not np.any(mask):
        return 0.0
    w = score[mask]
    n = len(w)
    third = max(1, n // 3)
    pre_avg = float(np.mean(w[:third]))
    mid_avg = float(np.mean(w[third:2 * third])) if n >= 2 else peak_val
    post_avg = float(np.mean(w[-third:]))

    # premia subida hacia el pico y caída posterior (jugada + cierre)
    shape_bonus = max(0.0, mid_avg - pre_avg) * 0.25 + max(0.0, mid_avg - post_avg) * 0.25
    if mid_avg >= pre_avg and mid_avg >= post_avg:
        shape_bonus += 8.0  # forma de "campana" completa

    # penaliza bordes que caen en medio de acción sin resolver
    edge_tension = float(np.interp(start, grid, score)) + float(np.interp(end, grid, score))
    boundary_penalty = 0.30 * edge_tension

    # penaliza solapar con menús / pantallas estáticas / tiempo muerto
    static_frac = float(np.mean(static_mask[mask])) if np.any(mask) else 0.0
    static_penalty = static_frac * 35.0

    quality = peak_val * 0.55 + shape_bonus - boundary_penalty - static_penalty
    return float(np.clip(quality, 0.0, 100.0))


def find_top_moments(
    grid: np.ndarray,
    score: np.ndarray,
    clip_len_options: tuple[int, ...] = (15, 30, 45, 60),
    max_moments: int = 15,
    min_gap_seconds: float = 20.0,
) -> list[Moment]:
    """Encuentra los mejores momentos: detecta picos de intensidad
    (más candidatos de los que se entregan), construye para cada uno la
    mejor ventana entre las duraciones candidatas (pico ~60-75% del
    clip, bordes en tramos tranquilos), puntúa su calidad 0..100, y
    entrega solo los mejores y más distintos (picos cercanos = misma
    jugada, se quedan con uno solo)."""
    if len(grid) < 2:
        return []

    video_duration = float(grid[-1])
    static_mask = _static_mask(grid, score)

    n_peak_candidates = max(max_moments * 4, 20)
    peak_candidates = _find_peak_times(
        grid, score, min_gap_seconds=min_gap_seconds / 2.0, max_candidates=n_peak_candidates,
    )

    scored: list[Moment] = []
    for peak_time, peak_val in peak_candidates:
        best = None
        for length_sec in clip_len_options:
            start, end = compute_clip_window(peak_time, length_sec, video_duration, grid, score)
            quality = _window_quality(grid, score, static_mask, start, end, peak_val)
            if best is None or quality > best[0]:
                best = (quality, start, end)
        quality, start, end = best
        scored.append(Moment(start=start, end=end, score=quality, peak_time=peak_time))

    # ordenar por calidad y agrupar picos cercanos (misma jugada): solo
    # el segundo exacto del pico decide si dos candidatos son "la misma
    # jugada", igual que antes - las ventanas en sí pueden solaparse un
    # poco por el pre-roll generoso, eso es normal y esperado
    scored.sort(key=lambda m: m.score, reverse=True)

    accepted: list[Moment] = []
    for cand in scored:
        too_close = any(abs(cand.peak_time - acc.peak_time) < min_gap_seconds for acc in accepted)
        if not too_close:
            accepted.append(cand)
        if len(accepted) >= max_moments:
            break

    accepted.sort(key=lambda m: m.start)
    return accepted


def tag_reasons(moment: Moment, audio: AudioFeatures, visual: Optional[VisualFeatures]) -> None:
    """Etiquetas legibles para explicar la puntuación de calidad:
    'Pico de audio' (grito/pico de volumen justo en la jugada),
    'Acción alta' (movimiento visual intenso en la jugada), 'Reacción'
    (subida de energía de voz/movimiento justo después del pico, típica
    de la reacción del streamer) y 'Cierre detectado' (la intensidad
    baja hacia el final del clip: hay resolución, no corta a mitad de
    acción)."""
    def _avg(times, values, s, e):
        if times is None or len(times) == 0:
            return 0.0
        mask = (times >= s) & (times <= e)
        return float(np.mean(values[mask])) if np.any(mask) else 0.0

    win_s, win_e = moment.peak_time - 2.0, moment.peak_time + 2.0
    reasons: list[str] = []

    peak_audio = _avg(audio.times, audio.peak_score, win_s, win_e)
    if peak_audio > 0.35:
        reasons.append("Pico de audio")

    peak_motion = _avg(visual.times, visual.motion_score, win_s, win_e) if visual is not None else 0.0
    if peak_motion > 0.35:
        reasons.append("Acción alta")

    # reacción: energía de voz/movimiento elevada justo DESPUÉS del pico
    reaction_s = moment.peak_time + 0.5
    reaction_e = min(moment.end, moment.peak_time + 6.0)
    reaction_audio = _avg(audio.times, audio.peak_score, reaction_s, reaction_e)
    reaction_laugh = _avg(audio.times, audio.laughter_score, reaction_s, reaction_e)
    reaction_motion = _avg(visual.times, visual.motion_score, reaction_s, reaction_e) if visual is not None else 0.0
    if max(reaction_audio, reaction_laugh) > 0.30 or reaction_motion > 0.30:
        reasons.append("Reacción")

    # cierre: la intensidad baja hacia el final del clip respecto al pico
    tail_s = max(moment.peak_time + 2.0, moment.end - 5.0)
    tail_audio = _avg(audio.times, audio.peak_score, tail_s, moment.end)
    if tail_audio < 0.30 and peak_audio > tail_audio:
        reasons.append("Cierre detectado")

    if not reasons:
        reasons.append("Combinación moderada de señales")
    moment.reasons = reasons
