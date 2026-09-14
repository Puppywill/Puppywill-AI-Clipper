"""
scoring.py
----------
Combina las señales de audio_analysis, visual_analysis y (si está
disponible) kill_events en una sola curva de "score" a lo largo de todo
el stream, encuentra los picos de mayor intensidad (la "jugada"), y
construye alrededor de cada uno un clip con estructura: preparación
breve -> jugada principal -> cierre/reacción, en vez de una ventana
centrada a ciegas en el pico.

La idea general:
  score(t) = w_audio_peak     * peak_score(t)
           + w_laughter       * laughter_score(t)
           + w_motion         * motion_score(t)
           + w_scene_cut      * scene_cut_score(t)
           + w_kill_activity  * kill_activity(t)      (opcional)

A partir de score(t):
  1. Se detectan los picos (segundo exacto de mayor intensidad), más
     candidatos de los que finalmente se entregan.
  2. Para cada pico y cada duración candidata, se calcula una ventana
     con el pico posicionado ~60-75% del clip (más preparación/jugada
     antes que cierre después), probando variantes de proporción y de
     desplazamiento del ancla para que los bordes caigan en tramos
     tranquilos (evita cortar a mitad de una acción sin resolución).
  3. Cada ventana recibe una puntuación de calidad 0..100 que premia
     forma "sube -> pico -> baja" (jugada + resultado), reacción fuerte
     tras el pico y pelea sostenida, y penaliza bordes con acción sin
     resolver y solapamiento con tramos estáticos (menús, respawn,
     espera).
  4. Se agrupan picos cercanos (misma jugada/pelea) y se entregan solo
     los mejores y más distintos, ordenados de mayor a menor puntuación.
  5. Si hay señal de kills (ver kill_events.py), se cuentan los kills
     dentro de cada clip aceptado -> etiqueta "Kill" o "Multikill" (2+
     kills agrupados en un solo clip, no clips separados de la misma
     pelea). El clip de mayor puntuación se marca "Best Play".

`tag_reasons` complementa esas etiquetas con "Reaction" cuando hay
energía de voz/movimiento elevada justo después del pico.
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
    kill_activity: float = 1.2   # el sonido/HUD de eliminación es la señal más directa de "esto importa"


@dataclass
class GamingScoreWeights:
    """Pesos del modo Gaming: valores iniciales conservadores (Fase 2 del
    plan de Gaming Mode) - pendientes de calibrar con footage real de
    Marvel Rivals en la Fase 3, no hay forma de ajustarlos bien sin eso.
    Los eventos discretos (kill/ultimate/round_end) pesan más que en
    General porque son señales más específicas de "esto es un momento
    de juego", no solo "esto suena/se ve intenso"."""
    audio_peak: float = 0.6
    laughter: float = 0.5
    motion: float = 0.5
    scene_cut: float = 0.4
    optical_flow: float = 0.8       # movimiento de cámara/apuntado real, más específico que motion_score
    brightness_spike: float = 0.4  # flashes/explosiones/pantallas completas
    kill_activity: float = 1.3
    ultimate_activity: float = 1.1
    round_end_activity: float = 0.9
    # bonus (no multiplicador) por CADA señal adicional que coincide en el
    # mismo instante (kill + pico de audio + corte de escena a la vez, etc.)
    # - pide el usuario explícitamente: "varias señales juntas = bonus"
    coincidence_bonus: float = 15.0


@dataclass
class Moment:
    start: float
    end: float
    score: float                          # 0..100, calidad general del clip (no solo intensidad del pico)
    peak_time: float                      # segundo exacto de mayor intensidad detectada
    reasons: list[str] = field(default_factory=list)
    kill_count: int = 0                   # kills detectados dentro de [start, end] (ver kill_events.py)


# El pico cae ~67% del clip: preparación + jugada antes, cierre/reacción
# después. Las variantes de proporción cubren exactamente el rango
# 60-75% pedido; NUNCA se desplaza el ancla por separado del pico real,
# porque eso movería el pico fuera de esa banda (ej. ancla+3s en un
# clip de 15s ya es un 20% del clip). La duración final es siempre
# exactamente la pedida (los dos bordes se mueven juntos).
PRE_ROLL_RATIO = 2.0 / 3.0
_RATIO_VARIANTS = (0.60, 0.65, 0.70, 0.75)


def resample_to_grid(times: np.ndarray, values: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Interpola linealmente `values(times)` sobre una rejilla temporal común `grid`.
    Pública porque moment_detector.py también la usa para alinear la señal
    de kills (ver kill_events.py) a la misma rejilla que find_top_moments."""
    if len(times) == 0:
        return np.zeros_like(grid)
    return np.interp(grid, times, values, left=values[0], right=values[-1])


def build_unified_score(
    audio: AudioFeatures,
    visual: Optional[VisualFeatures] = None,
    kill_times: Optional[np.ndarray] = None,
    kill_activity: Optional[np.ndarray] = None,
    weights: ScoreWeights = ScoreWeights(),
    grid_step: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    """Devuelve (grid_times, score) con score en la misma rejilla temporal.

    grid_step debe coincidir (o ser múltiplo) de WINDOW_SECONDS de audio_analysis
    para máxima fidelidad, pero funciona igual si no coincide gracias a la
    interpolación.

    `kill_times`/`kill_activity` son opcionales (ver `kill_events.py`): si se
    pasan, la señal de kills se suma igual que motion/scene_cut. Si no hay
    detección de kills disponible (p.ej. video de otro juego), el score
    combinado sigue funcionando exactamente igual que antes.
    """
    duration = audio.duration_sec
    if visual is not None and visual.duration_sec > 0:
        duration = max(duration, visual.duration_sec)

    grid = np.arange(0, duration, grid_step, dtype=np.float32)
    if len(grid) == 0:
        grid = np.array([0.0], dtype=np.float32)

    peak = resample_to_grid(audio.times, audio.peak_score, grid)
    laugh = resample_to_grid(audio.times, audio.laughter_score, grid)

    score = weights.audio_peak * peak + weights.laughter * laugh

    if visual is not None and len(visual.times) > 0:
        motion = resample_to_grid(visual.times, visual.motion_score, grid)
        scene = resample_to_grid(visual.times, visual.scene_cut_score, grid)
        score = score + weights.motion * motion + weights.scene_cut * scene

    if kill_times is not None and kill_activity is not None and len(kill_activity) > 0:
        kill = resample_to_grid(kill_times, kill_activity, grid)
        score = score + weights.kill_activity * kill

    # normalizar a 0..100 para que sea legible en la UI
    if score.max() > 0:
        score = 100.0 * score / (score.max() + 1e-9)

    return grid, score


def build_gaming_score(
    audio: AudioFeatures,
    visual: Optional[VisualFeatures] = None,
    gaming_feats=None,
    weights: GamingScoreWeights = GamingScoreWeights(),
    grid_step: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    """Igual forma que `build_unified_score`, pero con las señales del
    modo Gaming (optical flow, brillo, ultimate, fin de ronda) y un bonus
    explícito de coincidencia: si 2+ tipos de señal superan su propio
    umbral en el mismo instante (p.ej. un kill que además coincide con
    un pico de audio y un corte de escena), se suma un bonus además de
    la suma ponderada normal - así un momento donde "pasan varias cosas
    a la vez" queda por encima de uno con una sola señal fuerte aislada,
    tal como se pidió.

    `gaming_feats` es un `gaming_events.GamingFeatures` (opcional). Sin
    él, el score sigue funcionando solo con audio/video genéricos del
    modo Gaming (optical flow, brillo), sin las señales de kill/ultimate/
    fin de ronda.
    """
    duration = audio.duration_sec
    if visual is not None and visual.duration_sec > 0:
        duration = max(duration, visual.duration_sec)

    grid = np.arange(0, duration, grid_step, dtype=np.float32)
    if len(grid) == 0:
        grid = np.array([0.0], dtype=np.float32)

    peak = resample_to_grid(audio.times, audio.peak_score, grid)
    laugh = resample_to_grid(audio.times, audio.laughter_score, grid)
    score = weights.audio_peak * peak + weights.laughter * laugh
    signal_layers = [peak > 0.5]

    if visual is not None and len(visual.times) > 0:
        motion = resample_to_grid(visual.times, visual.motion_score, grid)
        scene = resample_to_grid(visual.times, visual.scene_cut_score, grid)
        score = score + weights.motion * motion + weights.scene_cut * scene
        signal_layers.append(scene > 0.6)

        flow = getattr(visual, "optical_flow_score", None)
        if flow is not None and len(flow) > 0:
            flow_g = resample_to_grid(visual.times, flow, grid)
            score = score + weights.optical_flow * flow_g
            signal_layers.append(flow_g > 0.6)

        bright = getattr(visual, "brightness_spike", None)
        if bright is not None and len(bright) > 0:
            bright_g = resample_to_grid(visual.times, bright, grid)
            score = score + weights.brightness_spike * bright_g
            signal_layers.append(bright_g > 0.6)

    if gaming_feats is not None:
        kill_g = resample_to_grid(gaming_feats.times, gaming_feats.kill_activity, grid)
        score = score + weights.kill_activity * kill_g
        signal_layers.append(kill_g > 0.5)

        ult_g = resample_to_grid(gaming_feats.times, gaming_feats.ultimate_activity, grid)
        score = score + weights.ultimate_activity * ult_g
        signal_layers.append(ult_g > 0.5)

        round_g = resample_to_grid(gaming_feats.times, gaming_feats.round_end_activity, grid)
        score = score + weights.round_end_activity * round_g
        signal_layers.append(round_g > 0.5)

    if signal_layers:
        coincidence_count = np.vstack(signal_layers).astype(np.int32).sum(axis=0)
        score = score + np.clip(coincidence_count - 1, 0, None) * weights.coincidence_bonus

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
    start: float, end: float, peak_time: float, peak_val: float,
) -> float:
    """Puntuación de calidad 0..100 de una ventana concreta: fuerza del
    pico + forma "sube -> pico -> baja" (jugada + resultado), más bonus
    por reacción fuerte justo después del pico y por pelea sostenida
    (gran parte de la ventana con intensidad alta, no solo un instante),
    menos penalización por cortar los bordes en medio de acción sin
    resolver y por solapar con tramos estáticos (menús/espera/respawn)."""
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

    # premia reacción fuerte en los segundos justo después del pico (grito,
    # risa, movimiento de cámara) - no solo lo etiqueta, también puntúa
    reaction_s, reaction_e = peak_time + 0.5, min(end, peak_time + 6.0)
    rmask = (grid >= reaction_s) & (grid <= reaction_e)
    reaction_level = float(np.mean(score[rmask])) if np.any(rmask) else 0.0
    reaction_bonus = min(12.0, reaction_level * 0.15)

    # premia "pelea intensa": gran parte de la ventana (no solo el pico)
    # se mantiene en intensidad alta
    intense_frac = float(np.mean(w > 55.0))
    intense_bonus = intense_frac * 15.0

    quality = peak_val * 0.55 + shape_bonus - boundary_penalty - static_penalty + reaction_bonus + intense_bonus
    return float(np.clip(quality, 0.0, 100.0))


def _count_kills_in_window(kill_event_times: list[float], start: float, end: float) -> int:
    """Cuenta cuántos kills distintos caen dentro de [start, end].

    Cuenta directamente sobre los EVENTOS discretos ya detectados por
    `kill_events.py` (cada uno ya es un pico de audio confirmado, o una
    lectura de OCR) en vez de volver a buscar picos sobre la curva
    continua `kill_activity`: esa curva ya está reinterpolada a la
    rejilla de 0.5s y mezclada con la señal visual (más ruidosa), así
    que contar ahí puede perder eliminaciones muy juntas (un multikill
    real puede tener apenas 1-2s entre eliminaciones) o contar ruido
    visual como si fuera un kill. Los eventos ya vienen deduplicados
    desde el detector, así que no hace falta NMS aquí."""
    return sum(1 for t in kill_event_times if start <= t <= end)


def _build_moment_candidates(
    grid: np.ndarray,
    score: np.ndarray,
    clip_len_options: tuple[int, ...],
    max_moments: int,
    min_gap_seconds: float,
) -> list[Moment]:
    """Núcleo compartido por `find_top_moments` (modo General) y
    `find_top_gaming_moments` (modo Gaming): detecta picos de intensidad,
    construye para cada uno la mejor ventana entre las duraciones
    candidatas (pico ~60-75%, bordes en tramos tranquilos), puntúa su
    calidad 0..100, y agrupa picos cercanos (misma jugada -> un solo
    clip), ordenados de mayor a menor puntuación. No pone etiquetas
    (Kill/Multikill/Best Play/...) - eso lo hace cada llamador, porque el
    vocabulario difiere entre General y Gaming."""
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
            quality = _window_quality(grid, score, static_mask, start, end, peak_time, peak_val)
            if best is None or quality > best[0]:
                best = (quality, start, end)
        quality, start, end = best
        scored.append(Moment(start=start, end=end, score=quality, peak_time=peak_time))

    # agrupar picos cercanos (misma jugada): solo el segundo exacto del
    # pico decide si dos candidatos son "la misma jugada" - las ventanas
    # en sí pueden solaparse un poco por el pre-roll generoso, eso es
    # normal y esperado
    scored.sort(key=lambda m: m.score, reverse=True)

    accepted: list[Moment] = []
    for cand in scored:
        too_close = any(abs(cand.peak_time - acc.peak_time) < min_gap_seconds for acc in accepted)
        if not too_close:
            accepted.append(cand)
        if len(accepted) >= max_moments:
            break

    return accepted


def _tag_intense_fight(grid: np.ndarray, score: np.ndarray, accepted: list[Moment],
                        threshold: float = 55.0) -> None:
    for m in accepted:
        wmask = (grid >= m.start) & (grid <= m.end)
        if np.any(wmask) and float(np.mean(score[wmask] > threshold)) >= 0.5:
            m.reasons.append("Intense Fight")


def _finalize_best_play(accepted: list[Moment]) -> list[Moment]:
    # ordenar por puntuación (de mejor a peor) para mostrarlos así en la UI
    accepted.sort(key=lambda m: m.score, reverse=True)
    if accepted:
        accepted[0].reasons.insert(0, "Best Play")
    return accepted


def find_top_moments(
    grid: np.ndarray,
    score: np.ndarray,
    clip_len_options: tuple[int, ...] = (15, 30, 45, 60),
    max_moments: int = 15,
    min_gap_seconds: float = 20.0,
    kill_event_times: Optional[list[float]] = None,
) -> list[Moment]:
    """Modo General: encuentra los mejores momentos y entrega solo los
    mejores y más distintos, ordenados de mayor a menor puntuación.

    `kill_event_times` (opcional, ver kill_events.py: `[e.time for e in
    kill_feats.events]`) son los instantes exactos de kills ya detectados
    - se usan para contar kills por clip (Kill/Multikill) y para marcar
    el mejor momento como "Best Play". La señal continua de kills (para
    el score en sí) se suma antes, en build_unified_score.
    """
    accepted = _build_moment_candidates(grid, score, clip_len_options, max_moments, min_gap_seconds)
    if not accepted:
        return accepted

    if kill_event_times:
        for m in accepted:
            m.kill_count = _count_kills_in_window(kill_event_times, m.start, m.end)
            if m.kill_count >= 2:
                m.reasons.append("Multikill")
            elif m.kill_count == 1:
                m.reasons.append("Kill")

    _tag_intense_fight(grid, score, accepted)
    return _finalize_best_play(accepted)


def find_top_gaming_moments(
    grid: np.ndarray,
    score: np.ndarray,
    gaming_feats=None,
    clip_len_options: tuple[int, ...] = (15, 30, 45, 60),
    max_moments: int = 15,
    min_gap_seconds: float = 20.0,
) -> list[Moment]:
    """Modo Gaming: mismo núcleo de detección de picos/ventanas que el
    modo General (`_build_moment_candidates`), con vocabulario de
    etiquetas propio: Kill, Multikill (varias eliminaciones muy juntas,
    p.ej. team wipe/ace), Killstreak (varias eliminaciones repartidas en
    una ventana más amplia sin pausas grandes), Ultimate, Round End,
    Intense Fight, Best Play. `gaming_feats` es un
    `gaming_events.GamingFeatures` (opcional - si falta, el momento
    queda sin esas etiquetas pero la detección genérica sigue
    funcionando)."""
    from .gaming_events import group_kill_streaks  # import perezoso: evita ciclo de módulos en tiempo de carga

    accepted = _build_moment_candidates(grid, score, clip_len_options, max_moments, min_gap_seconds)
    if not accepted:
        return accepted

    if gaming_feats is not None:
        kill_times = [e.time for e in gaming_feats.kill_events]
        ultimate_times = [e.time for e in gaming_feats.ultimate_events]
        round_end_times = [e.time for e in gaming_feats.round_end_events]

        for m in accepted:
            kills_in_window = [t for t in kill_times if m.start <= t <= m.end]
            m.kill_count = len(kills_in_window)
            if m.kill_count >= 2:
                grouping = group_kill_streaks(kills_in_window)
                label = next(iter(grouping.values()), "multikill_moment")
                m.reasons.append("Multikill" if label == "multikill_moment" else "Killstreak")
            elif m.kill_count == 1:
                m.reasons.append("Kill")

            if any(m.start <= t <= m.end for t in ultimate_times):
                m.reasons.append("Ultimate")
            if any(m.start <= t <= m.end for t in round_end_times):
                m.reasons.append("Round End")

    _tag_intense_fight(grid, score, accepted)
    return _finalize_best_play(accepted)


def tag_reasons(moment: Moment, audio: AudioFeatures, visual: Optional[VisualFeatures]) -> None:
    """Añade 'Reaction' si hay energía de voz/movimiento elevada justo
    DESPUÉS del pico (típica de la reacción del streamer tras la jugada).
    Complementa (no reemplaza) las etiquetas que ya puso `find_top_moments`
    ('Kill'/'Multikill', 'Intense Fight', 'Best Play'); si al final no hay
    ninguna etiqueta, se añade un texto genérico para no dejar la lista
    vacía."""
    def _avg(times, values, s, e):
        if times is None or len(times) == 0:
            return 0.0
        mask = (times >= s) & (times <= e)
        return float(np.mean(values[mask])) if np.any(mask) else 0.0

    reaction_s = moment.peak_time + 0.5
    reaction_e = min(moment.end, moment.peak_time + 6.0)
    reaction_audio = _avg(audio.times, audio.peak_score, reaction_s, reaction_e)
    reaction_laugh = _avg(audio.times, audio.laughter_score, reaction_s, reaction_e)
    reaction_motion = _avg(visual.times, visual.motion_score, reaction_s, reaction_e) if visual is not None else 0.0
    if max(reaction_audio, reaction_laugh) > 0.30 or reaction_motion > 0.30:
        moment.reasons.append("Reaction")

    if not moment.reasons:
        # "Generic" es un marcador interno, no texto para mostrar: la UI lo
        # traduce vía i18n.t("moment.reason_generic") al idioma activo. Las
        # demás etiquetas (Kill/Multikill/Best Play/Reaction/Intense Fight)
        # son vocabulario fijo en inglés y se muestran tal cual.
        moment.reasons.append("Generic")
