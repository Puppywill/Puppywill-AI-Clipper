#!/usr/bin/env python3
"""
test_pipeline.py
-----------------
Prueba de humo end-to-end que NO depende de PySide6, solo de FFmpeg +
OpenCV + NumPy (siempre disponibles). Verifica que:

  1. Se puede generar/leer un video de prueba.
  2. El análisis de audio detecta correctamente picos de volumen simulados.
  3. El análisis visual produce señales válidas.
  4. El scoring combinado encuentra los momentos correctos (dentro de una
     tolerancia razonable respecto a dónde sabemos que están los picos).
  5. La exportación de clips reales (9:16, 16:9, 1:1) produce archivos MP4
     válidos con las dimensiones correctas.

Ejecutar con:  python tests/test_pipeline.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import audio_analysis, visual_analysis, scoring
from app.core.clip_exporter import export_clip, ExportOptions, TARGET_DIMENSIONS
from app.core.video_io import validate_and_probe


KNOWN_PEAKS = [11.5, 42.0, 71.5]  # centros de los picos simulados en el video de prueba
TOLERANCE_S = 5.0


def make_test_video(path: str, duration: int = 90):
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=size=1280x720:rate=30:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=200:duration={duration}",
        "-filter_complex",
        "[1:a]volume='if(between(t,10,13),3.5, if(between(t,40,44),4.0, "
        "if(between(t,70,73),3.0, 0.3)))':eval=frame[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", path,
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.returncode == 0, proc.stderr.decode(errors="ignore")


def test_audio_visual_scoring(tmp_dir: Path):
    video_path = str(tmp_dir / "test_stream.mp4")
    make_test_video(video_path)

    wav_path = str(tmp_dir / "audio.wav")
    audio_analysis.extract_audio_wav(video_path, wav_path)
    af = audio_analysis.analyze_audio(wav_path)
    assert af.duration_sec > 85, "duración de audio inesperada"

    vf = visual_analysis.analyze_visual(video_path)
    assert len(vf.times) > 0, "el análisis visual no produjo muestras"

    grid, score = scoring.build_unified_score(af, vf)
    moments = scoring.find_top_moments(grid, score, clip_len_options=(15, 30), max_moments=6, min_gap_seconds=15.0)

    # Al menos los 3 picos conocidos deben aparecer, y deben ser los de MAYOR
    # puntuación (no solo "aparecer en algún lado"): distintos backends de
    # decode (GPU/CPU/OpenCV) pueden diferir en un candidato adicional de
    # puntuación baja cerca del ruido (p.ej. el patrón sintético de testsrc
    # generando un scene-cut borde de video ligeramente distinto según qué
    # build de FFmpeg decodificó el frame) sin que eso indique una regresión
    # real: lo que importa es que los picos de verdad sigan siendo los mejor
    # puntuados.
    assert len(moments) >= 3, f"se esperaban al menos 3 momentos, se encontraron {len(moments)}"
    top3 = sorted(moments, key=lambda m: -m.score)[:3]

    for expected_peak in KNOWN_PEAKS:
        closest = min(top3, key=lambda m: abs(m.peak_time - expected_peak))
        diff = abs(closest.peak_time - expected_peak)
        assert diff <= TOLERANCE_S, (
            f"pico esperado en t={expected_peak}s, el más cercano detectado fue "
            f"t={closest.peak_time}s (diff={diff}s > tolerancia {TOLERANCE_S}s)"
        )

    print(f"✅ Detección de momentos OK: {[round(m.peak_time,1) for m in moments]} "
          f"(esperados ~{KNOWN_PEAKS})")
    return video_path, moments


def test_export(tmp_dir: Path, video_path: str, moments):
    info = validate_and_probe(video_path)
    moment = moments[0]

    for ratio in ("9:16", "16:9", "1:1"):
        out_path = str(tmp_dir / f"clip_{ratio.replace(':','x')}.mp4")
        opts = ExportOptions(aspect_ratio=ratio, fps=30, crf=28, use_gpu=False)
        export_clip(video_path, out_path, moment.start, moment.end, opts, info.width, info.height)

        assert Path(out_path).exists() and Path(out_path).stat().st_size > 1000, f"{out_path} no se generó correctamente"

        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", out_path],
            stdout=subprocess.PIPE,
        )
        w, h = map(int, probe.stdout.decode().strip().split(","))
        expected_w, expected_h = TARGET_DIMENSIONS[ratio]
        assert (w, h) == (expected_w, expected_h), f"{ratio}: esperado {expected_w}x{expected_h}, obtenido {w}x{h}"
        print(f"✅ Exportación {ratio} OK -> {w}x{h}")


def main():
    with tempfile.TemporaryDirectory(prefix="puppywill_test_") as tmp:
        tmp_dir = Path(tmp)
        print("=== Test 1/2: audio + visual + scoring ===")
        video_path, moments = test_audio_visual_scoring(tmp_dir)

        print("\n=== Test 2/2: exportación real de clips (9:16, 16:9, 1:1) ===")
        test_export(tmp_dir, video_path, moments)

    print("\n🎉 Todos los tests pasaron.")


if __name__ == "__main__":
    main()
