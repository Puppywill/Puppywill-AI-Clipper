#!/usr/bin/env python3
"""
test_gaming_mode.py
---------------------
Pruebas rápidas del modo Gaming (ver app/core/gaming_events.py,
app/core/scoring.py: GamingScoreWeights/build_gaming_score/
find_top_gaming_moments, app/core/games/).

Dos niveles, a propósito:
  1. Unitarias con señales construidas directamente en NumPy (rms/delta/
     brillo ya calculados) en vez de generar audio real con ffmpeg -
     mucho más simple y confiable para verificar la FORMA de la señal
     (kill = pico corto que cae rápido, ultimate = pico que se sostiene)
     sin depender de que ffmpeg produzca exactamente esa envolvente
     acústica.
  2. Una integración corta con un video sintético real (como
     test_kill_detection.py) corriendo `moment_detector.run_full_analysis`
     completo en modo Gaming, para confirmar que todo el cableado
     (moment_detector -> gaming_events -> scoring -> UI) no rompe nada.

Nunca se analiza un video largo/real - solo clips sintéticos de segundos.

Ejecutar con:  python tests/test_gaming_mode.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from app.core.audio_analysis import AudioFeatures
from app.core.gaming_events import _detect_ultimate_cues, group_kill_streaks
from app.core.kill_events import _detect_audio_kill_cues
from app.core.scoring import GamingScoreWeights, build_gaming_score
from app.core import moment_detector


def _make_audio_features(rms_values: list[float], window_seconds: float = 0.5) -> AudioFeatures:
    """Construye un AudioFeatures sintético directamente desde una lista de
    RMS por ventana (evita depender de que ffmpeg produzca una envolvente
    acústica exacta - más simple y confiable para probar la FORMA de la
    señal)."""
    rms = np.array(rms_values, dtype=np.float32)
    delta = np.zeros_like(rms)
    delta[1:] = np.abs(rms[1:] - rms[:-1])

    def _norm01(x):
        lo, hi = np.percentile(x, 5), np.percentile(x, 97)
        if hi - lo < 1e-9:
            return np.zeros_like(x)
        return np.clip((x - lo) / (hi - lo), 0.0, 1.0)

    rms_n = _norm01(rms)
    delta_n = _norm01(delta)
    peak_score = np.clip(0.6 * rms_n + 0.4 * delta_n, 0.0, 1.0)
    times = (np.arange(len(rms)) * window_seconds + window_seconds / 2.0).astype(np.float32)
    return AudioFeatures(
        times=times, rms=rms, rms_db=20 * np.log10(np.maximum(rms, 1e-6)), delta=delta,
        peak_score=peak_score, laughter_score=np.zeros_like(rms), duration_sec=len(rms) * window_seconds,
    )


def test_kill_signature_is_short_and_decays():
    """Un 'ding' de kill: sube y CAE dentro de 1-3 ventanas - la firma que
    ya usa kill_events.py, aquí solo confirmamos que sigue disparando con
    valores típicos (referencia para comparar contra la firma de ultimate)."""
    baseline = [0.1] * 10
    kill_pulse = [0.1, 0.1, 0.9, 0.1, 0.1]  # pico de 1 sola ventana, cae inmediatamente
    rms_values = baseline + kill_pulse + baseline
    audio = _make_audio_features(rms_values)
    cue_score, events = _detect_audio_kill_cues(audio)
    assert len(events) >= 1, "el 'ding' corto de kill debería disparar al menos un evento"
    print(f"✅ Firma de kill (pico corto que cae) detectada: {len(events)} evento(s)")
    return audio


def test_ultimate_signature_is_sustained():
    """Una ultimate: el mismo tipo de pico, pero se SOSTIENE varias
    ventanas (una voz/sonido de ~3-5s, no un "ding" de 0.5s) - eso es lo
    que la distingue de un kill en `_detect_ultimate_cues` (huella de
    sostenimiento ancha vs. angosta)."""
    baseline = [0.1] * 10
    # sube, se sostiene ANCHO (varias ventanas elevadas alrededor del pico),
    # baja gradual - a diferencia del kill, que cae a baseline de inmediato
    ultimate_pulse = [0.1, 0.4, 0.7, 0.9, 0.85, 0.75, 0.65, 0.5, 0.3, 0.15, 0.1]
    rms_values = baseline + ultimate_pulse + baseline
    audio = _make_audio_features(rms_values)

    ultimate_cue, ultimate_events = _detect_ultimate_cues(audio, visual=None)

    assert len(ultimate_events) >= 1, "la firma sostenida (ancha) debería disparar al menos un evento de ultimate por audio solo"
    print(f"✅ Firma de ultimate (pico sostenido y ancho) detectada por audio solo: {len(ultimate_events)} evento(s), "
          f"confianza máx={max(e.confidence for e in ultimate_events):.2f}")


def test_ultimate_boosted_by_visual_corroboration():
    """La corroboración visual (brillo/corte de escena a pantalla completa)
    debe subir el puntaje de una firma AMBIGUA (sostenida pero angosta) lo
    suficiente para cruzar el umbral de detección - sola, por audio, no
    alcanza; con el cambio de pantalla completa coincidiendo, sí."""
    baseline = [0.1] * 10
    ambiguous_pulse = [0.1, 0.5, 0.85, 0.9, 0.8, 0.6, 0.3, 0.1]  # sostenimiento angosto, insuficiente solo
    rms_values = baseline + ambiguous_pulse + baseline
    audio = _make_audio_features(rms_values)
    peak_idx = int(np.argmax(audio.rms))

    class FakeVisual:
        times = audio.times
        brightness_spike = np.where(
            (audio.times >= audio.times[peak_idx] - 1.0) & (audio.times <= audio.times[peak_idx] + 1.0), 1.0, 0.0
        ).astype(np.float32)
        scene_cut_score = np.zeros_like(brightness_spike)

    curve_no_visual, events_no_visual = _detect_ultimate_cues(audio, visual=None)
    curve_with_visual, events_with_visual = _detect_ultimate_cues(audio, visual=FakeVisual())

    assert curve_with_visual[peak_idx] > curve_no_visual[peak_idx], (
        f"la corroboración visual debería subir el puntaje en el pico "
        f"(sin video={curve_no_visual[peak_idx]:.2f}, con video={curve_with_visual[peak_idx]:.2f})"
    )
    assert len(events_no_visual) == 0, "la firma angosta sola (sin video) no debería alcanzar el umbral todavía"
    assert len(events_with_visual) >= 1, "con la corroboración visual, sí debería cruzar el umbral"
    print(f"✅ Corroboración visual sube el puntaje de ultimate lo suficiente para cruzar el umbral "
          f"({curve_no_visual[peak_idx]:.2f} -> {curve_with_visual[peak_idx]:.2f})")


def test_group_kill_streaks():
    """2-3 kills muy juntos (team wipe/ace) = 'multikill_moment'; varios
    kills repartidos en una ventana más amplia = 'killstreak'."""
    multikill = group_kill_streaks([70.0, 71.2, 72.5])  # span=2.5s
    assert set(multikill.values()) == {"multikill_moment"}, multikill

    streak = group_kill_streaks([40.0, 47.0, 54.0])  # span=14s
    assert set(streak.values()) == {"killstreak"}, streak

    single = group_kill_streaks([100.0])
    assert single == {100.0: "multikill_moment"}, "un solo kill no forma racha, pero no debe fallar"

    empty = group_kill_streaks([])
    assert empty == {}

    print("✅ group_kill_streaks distingue Multikill (juntos) de Killstreak (repartidos)")


def test_coincidence_bonus_rewards_overlapping_signals():
    """Un instante donde coinciden 2+ señales (kill + pico de audio + corte
    de escena) debe puntuar más alto que uno con una sola señal fuerte
    aislada de la misma magnitud - pide el usuario explícitamente 'varias
    señales juntas = bonus'."""
    n = 20
    baseline_audio = [0.1] * n
    audio = _make_audio_features(baseline_audio)
    # dos picos de audio de la MISMA magnitud en índices distintos
    audio.peak_score[5] = 0.9
    audio.peak_score[15] = 0.9

    class FakeVisualCoincidence:
        times = audio.times
        duration_sec = float(audio.duration_sec)
        motion_score = np.zeros(n, dtype=np.float32)
        scene_cut_score = np.zeros(n, dtype=np.float32)
        optical_flow_score = np.array([])
        brightness_spike = np.array([])

    # en el índice 5 SOLO coincide el pico de audio; en el índice 15 TAMBIÉN
    # coincide un corte de escena fuerte - misma señal de audio, más una señal extra
    vis = FakeVisualCoincidence()
    vis.scene_cut_score[15] = 0.9

    grid, score = build_gaming_score(audio, vis, gaming_feats=None, weights=GamingScoreWeights())
    assert score[15] > score[5], (
        f"el punto con señales coincidentes (idx 15, score={score[15]:.1f}) debería puntuar más "
        f"que el que solo tiene una señal (idx 5, score={score[5]:.1f})"
    )
    print(f"✅ Bonus de coincidencia funciona: score[solo audio]={score[5]:.1f} "
          f"< score[audio+escena juntos]={score[15]:.1f}")


# --- integración corta con video sintético real ---

KILL_TIME = 15.0
STREAK_TIMES = (40.0, 47.0, 54.0)     # repartidos - debería salir "Killstreak"
MULTIKILL_TIMES = (80.0, 81.2, 82.5)  # muy juntos - debería salir "Multikill"
VIDEO_DURATION = 110  # margen amplio tras el último evento para no chocar con el borde del video


def make_gaming_test_video(path: str, duration: int = VIDEO_DURATION):
    """Color sólido (no `testsrc`) a propósito: `testsrc` tiene un patrón
    que se mueve todo el tiempo, y el modo Gaming pesa mucho más las
    señales visuales (motion/scene_cut/optical flow/brillo) + un bonus de
    coincidencia entre ellas - sobre `testsrc` ese "ruido" visual sintético
    puede competir con la señal real de audio y mover el pico a otro
    lado. Con un fondo estático, el único evento real es el de audio,
    que es justo lo que esta prueba de integración quiere validar (las
    señales visuales del modo Gaming ya se prueban por separado, arriba,
    con datos sintéticos controlados)."""
    pulses = [KILL_TIME] + list(STREAK_TIMES) + list(MULTIKILL_TIMES)
    conditions = "".join(f"if(between(t,{t:.2f},{t + 0.3:.2f}),4.0," for t in pulses)
    closing = "0.3" + ")" * len(pulses)
    volume_expr = conditions + closing

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=gray:size=640x360:rate=30:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=220:duration={duration}",
        "-filter_complex", f"[1:a]volume='{volume_expr}':eval=frame[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", path,
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.returncode == 0, proc.stderr.decode(errors="ignore")


def test_gaming_mode_end_to_end(tmp_dir: Path):
    video_path = str(tmp_dir / "test_gaming.mp4")
    print("=== Generando video sintético para modo Gaming ===")
    make_gaming_test_video(video_path)

    print("=== Corriendo el pipeline completo en modo Gaming ===")
    # clip_len_options empieza en 30s (no 15s): la racha (STREAK_TIMES) se
    # reparte en ~14s, y un clip de 15s con el pico bien puesto en la banda
    # 60-75% no siempre alcanza a cubrir sus dos extremos - 30s+ sí, con
    # margen de sobra.
    result = moment_detector.run_full_analysis(
        video_path, str(tmp_dir), clip_len_options=(30, 45), max_moments=10,
        detection_mode="gaming", game_key="marvel_rivals", use_cache=False,
    )
    moments = result.moments
    print(f"{len(moments)} momentos encontrados:")
    for m in moments:
        print(f"  start={m.start:.1f} end={m.end:.1f} peak={m.peak_time:.1f} "
              f"score={m.score:.1f} kill_count={m.kill_count} razones={m.reasons}")

    assert len(moments) > 0, "no se detectó ningún momento en modo Gaming"

    # búsqueda por CONTENCIÓN (todos los tiempos del evento caen dentro de
    # [start, end]) en vez de por cercanía de `peak_time`: con el bonus de
    # coincidencia y señales visuales nuevas (optical flow/brillo, aún sin
    # calibrar con footage real - eso es la Fase 3 del plan), el pico de
    # score dentro de la ventana puede no coincidir exactamente con el
    # instante del kill si hay otra señal fuerte cerca; lo que importa aquí
    # es que el CLIP resultante cubra el evento y tenga la etiqueta correcta
    streak_candidates = [m for m in moments if all(m.start <= t <= m.end for t in STREAK_TIMES)]
    assert len(streak_candidates) == 1, (
        f"se esperaba un solo clip cubriendo la racha repartida, se encontraron {len(streak_candidates)}"
    )
    assert "Killstreak" in streak_candidates[0].reasons, (
        f"se esperaba la etiqueta 'Killstreak' para kills repartidos en ~14s, razones={streak_candidates[0].reasons}"
    )
    print(f"✅ Racha repartida (~14s) etiquetada 'Killstreak': {streak_candidates[0].reasons}")

    multikill_candidates = [m for m in moments if all(m.start <= t <= m.end for t in MULTIKILL_TIMES)]
    assert len(multikill_candidates) == 1, (
        f"se esperaba un solo clip cubriendo el multikill, se encontraron {len(multikill_candidates)}"
    )
    assert "Multikill" in multikill_candidates[0].reasons, (
        f"se esperaba la etiqueta 'Multikill' para kills muy juntos (~2.5s), razones={multikill_candidates[0].reasons}"
    )
    print(f"✅ Kills muy juntos (~2.5s) etiquetados 'Multikill': {multikill_candidates[0].reasons}")

    assert result.visual_features is not None
    assert set(result.visual_features.hud_regions_activity.keys()) == {"kill_feed", "ultimate_bar", "round_banner"}
    assert len(result.visual_features.optical_flow_score) > 0, "el modo Gaming debe calcular optical flow"
    print("✅ Señales de modo Gaming presentes: hud_regions_activity (perfil Marvel Rivals) + optical_flow_score")


def main():
    test_kill_signature_is_short_and_decays()
    test_ultimate_signature_is_sustained()
    test_ultimate_boosted_by_visual_corroboration()
    test_group_kill_streaks()
    test_coincidence_bonus_rewards_overlapping_signals()

    with tempfile.TemporaryDirectory(prefix="puppywill_gamingtest_") as tmp:
        test_gaming_mode_end_to_end(Path(tmp))

    print("\n🎉 Todos los tests del modo Gaming pasaron.")


if __name__ == "__main__":
    main()
