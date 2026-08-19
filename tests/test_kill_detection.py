#!/usr/bin/env python3
"""
test_kill_detection.py
------------------------
Prueba de humo de la detección de kills (ver app/core/kill_events.py):
genera un video sintético con "dings" de audio CORTOS Y AGUDOS (a
diferencia de los picos sostenidos de test_pipeline.py) en timestamps
conocidos - tres muy cercanos entre sí (simulando un multikill) y uno
aislado (un kill simple, bien separado) - y corre el pipeline real
completo (`moment_detector.run_full_analysis`) para verificar que:

  1. El multikill se agrupa en UN SOLO clip (no tres clips casi
     idénticos de la misma pelea) con kill_count >= 2 y la etiqueta
     "Multikill".
  2. El kill aislado produce un clip separado con kill_count == 1 y la
     etiqueta "Kill" (no "Multikill").
  3. El clip de mayor puntuación queda marcado "Best Play".

No depende de que Tesseract esté instalado: la señal principal aquí es
de audio, que siempre está disponible.

Ejecutar con:  python tests/test_kill_detection.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import moment_detector

# tres "dings" de kill separados por 2s (multikill) + uno aislado bien lejos
MULTIKILL_TIMES = (30.0, 32.0, 34.0)
SOLO_KILL_TIME = 65.0
VIDEO_DURATION = 90


def make_test_video(path: str, duration: int = VIDEO_DURATION):
    pulses = list(MULTIKILL_TIMES) + [SOLO_KILL_TIME]
    # cada "ding" es CORTO (0.3s) y agudo, a diferencia de un pico sostenido
    conditions = "".join(
        f"if(between(t,{t:.2f},{t + 0.3:.2f}),4.0," for t in pulses
    )
    closing = "0.3" + ")" * len(pulses)
    volume_expr = conditions + closing

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=size=1280x720:rate=30:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=220:duration={duration}",
        "-filter_complex", f"[1:a]volume='{volume_expr}':eval=frame[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", path,
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.returncode == 0, proc.stderr.decode(errors="ignore")


def main():
    with tempfile.TemporaryDirectory(prefix="puppywill_killtest_") as tmp:
        tmp_dir = Path(tmp)
        video_path = str(tmp_dir / "test_kills.mp4")
        print("=== Generando video sintético con dings de kill ===")
        make_test_video(video_path)

        print("=== Corriendo el pipeline completo (moment_detector.run_full_analysis) ===")
        result = moment_detector.run_full_analysis(
            video_path, str(tmp_dir), clip_len_options=(15, 30), max_moments=10,
        )
        moments = result.moments
        print(f"{len(moments)} momentos encontrados:")
        for m in moments:
            print(f"  start={m.start:.1f} end={m.end:.1f} peak={m.peak_time:.1f} "
                  f"score={m.score:.1f} kill_count={m.kill_count} razones={m.reasons}")

        assert len(moments) > 0, "no se detectó ningún momento"

        # --- el multikill debe agruparse en UN SOLO clip ---
        multikill_candidates = [
            m for m in moments
            if min(MULTIKILL_TIMES) - 5 <= m.peak_time <= max(MULTIKILL_TIMES) + 5
        ]
        assert len(multikill_candidates) == 1, (
            f"se esperaba UN solo clip cubriendo el multikill (t~30-34s), "
            f"se encontraron {len(multikill_candidates)}: "
            f"{[m.peak_time for m in multikill_candidates]}"
        )
        multikill_moment = multikill_candidates[0]
        assert multikill_moment.kill_count >= 2, (
            f"se esperaban >=2 kills contados en el clip del multikill, "
            f"se contaron {multikill_moment.kill_count}"
        )
        assert "Multikill" in multikill_moment.reasons, (
            f"se esperaba la etiqueta 'Multikill', razones={multikill_moment.reasons}"
        )
        print(f"✅ Multikill agrupado en un solo clip (kill_count={multikill_moment.kill_count}, "
              f"razones={multikill_moment.reasons})")

        # --- el kill aislado debe ser su propio clip, con kill_count == 1 ---
        solo_candidates = [m for m in moments if abs(m.peak_time - SOLO_KILL_TIME) <= 5]
        assert len(solo_candidates) == 1, (
            f"se esperaba un clip para el kill aislado (t~{SOLO_KILL_TIME}s), "
            f"se encontraron {len(solo_candidates)}"
        )
        solo_moment = solo_candidates[0]
        assert solo_moment.kill_count == 1, (
            f"se esperaba kill_count==1 en el kill aislado, se contó {solo_moment.kill_count}"
        )
        assert "Kill" in solo_moment.reasons and "Multikill" not in solo_moment.reasons, (
            f"se esperaba la etiqueta 'Kill' (no 'Multikill'), razones={solo_moment.reasons}"
        )
        print(f"✅ Kill aislado como clip separado (kill_count={solo_moment.kill_count}, "
              f"razones={solo_moment.reasons})")

        # --- el de mayor puntuación queda marcado "Best Play" ---
        best = max(moments, key=lambda m: m.score)
        assert "Best Play" in best.reasons, (
            f"se esperaba 'Best Play' en el momento de mayor puntuación, razones={best.reasons}"
        )
        assert moments[0] is best, "se esperaba que el primer momento sea el de mayor puntuación (orden por score)"
        print(f"✅ Momento de mayor puntuación marcado 'Best Play' (score={best.score:.1f})")

    print("\n🎉 Todos los tests de detección de kills pasaron.")


if __name__ == "__main__":
    main()
