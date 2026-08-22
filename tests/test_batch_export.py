#!/usr/bin/env python3
"""
test_batch_export.py
---------------------
Prueba rápida (video sintético corto, sin re-analizar nada) de la
exportación por lotes: varios momentos x formatos en una sola pasada,
nombres únicos que no se sobrescriben, y que un clip que falla no
detiene a los demás.

Ejecutar con:  python tests/test_batch_export.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.batch_export import BatchExportJob, run_batch_export, unique_path
from app.core.clip_exporter import ExportOptions, TARGET_DIMENSIONS
from app.core.video_io import validate_and_probe


def make_short_video(path: str, duration: int = 20):
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=size=640x360:rate=30:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=220:duration={duration}",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", path,
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.returncode == 0, proc.stderr.decode(errors="ignore")


def test_unique_path(tmp_dir: Path):
    (tmp_dir / "clip_top01_9x16.mp4").write_bytes(b"x")
    p1 = unique_path(tmp_dir, "clip_top01_9x16.mp4")
    assert p1.name == "clip_top01_9x16_2.mp4", f"se esperaba sufijo _2, se obtuvo {p1.name}"
    p1.write_bytes(b"x")
    p2 = unique_path(tmp_dir, "clip_top01_9x16.mp4")
    assert p2.name == "clip_top01_9x16_3.mp4", f"se esperaba sufijo _3, se obtuvo {p2.name}"
    print("✅ unique_path genera nombres sin sobrescribir")


def test_batch_export_success(tmp_dir: Path, video_path: str):
    info = validate_and_probe(video_path)
    dest = tmp_dir / "export_batch"
    dest.mkdir()

    # 2 "momentos" (top01 en t=3s, top02 en t=10s) x 2 formatos = 4 jobs,
    # simulando marcar 2 casillas y exportar en 9:16 + 1:1 a la vez
    jobs = []
    for rank, start in [(1, 3.0), (2, 10.0)]:
        for ratio in ("9:16", "1:1"):
            safe_ratio = ratio.replace(":", "x")
            out_path = unique_path(dest, f"test_top{rank:02d}_{safe_ratio}.mp4")
            jobs.append(BatchExportJob(
                source_video=video_path, out_path=str(out_path),
                start=start, end=start + 3.0,
                options=ExportOptions(aspect_ratio=ratio, fps=30, crf=28, use_gpu=False),
                src_width=info.width, src_height=info.height,
                label=f"Momento #{rank} ({ratio})",
            ))

    progress_calls = []
    results = run_batch_export(jobs, progress_cb=lambda i, total, label: progress_calls.append((i, total, label)))

    assert len(results) == 4, f"se esperaban 4 resultados, se obtuvieron {len(results)}"
    assert all(r.ok for r in results), [r.error for r in results if not r.ok]
    assert progress_calls == [(i, 4, jobs[i - 1].label) for i in range(1, 5)], \
        f"progreso inesperado: {progress_calls}"

    for r, job in zip(results, jobs):
        out = Path(r.out_path)
        assert out.exists() and out.stat().st_size > 1000, f"{out} no se generó correctamente"
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(out)],
            stdout=subprocess.PIPE,
        )
        w, h = map(int, probe.stdout.decode().strip().split(","))
        expected_w, expected_h = TARGET_DIMENSIONS[job.options.aspect_ratio]
        assert (w, h) == (expected_w, expected_h), f"{job.label}: esperado {expected_w}x{expected_h}, obtenido {w}x{h}"

    print(f"✅ Exportación por lotes OK: {len(results)}/4 clips en {dest} (progreso reportado correctamente)")


def test_batch_export_partial_failure(tmp_dir: Path, video_path: str):
    info = validate_and_probe(video_path)
    dest = tmp_dir / "export_partial"
    dest.mkdir()

    good_job = BatchExportJob(
        source_video=video_path, out_path=str(dest / "ok_9x16.mp4"),
        start=2.0, end=5.0, options=ExportOptions(aspect_ratio="9:16", fps=30, crf=28, use_gpu=False),
        src_width=info.width, src_height=info.height, label="Momento #1 (9:16)",
    )
    bad_job = BatchExportJob(
        source_video=str(tmp_dir / "no_existe.mp4"), out_path=str(dest / "falla_9x16.mp4"),
        start=2.0, end=5.0, options=ExportOptions(aspect_ratio="9:16", fps=30, crf=28, use_gpu=False),
        src_width=1080, src_height=1920, label="Momento #2 (9:16, video inexistente)",
    )
    good_job2 = BatchExportJob(
        source_video=video_path, out_path=str(dest / "ok2_1x1.mp4"),
        start=8.0, end=11.0, options=ExportOptions(aspect_ratio="1:1", fps=30, crf=28, use_gpu=False),
        src_width=info.width, src_height=info.height, label="Momento #3 (1:1)",
    )

    results = run_batch_export([good_job, bad_job, good_job2])

    assert len(results) == 3
    assert results[0].ok and Path(results[0].out_path).exists(), "el primer clip (válido) debió exportarse"
    assert not results[1].ok and results[1].error, "el segundo clip (video inexistente) debió fallar y reportar error"
    assert results[2].ok and Path(results[2].out_path).exists(), (
        "el tercer clip (válido) debió exportarse igual, aunque el segundo haya fallado"
    )
    print(f"✅ Un clip fallido no detiene a los demás: OK={results[0].ok}, "
          f"FALLA={not results[1].ok} ({results[1].error[:60]}...), OK={results[2].ok}")


def main():
    with tempfile.TemporaryDirectory(prefix="puppywill_batch_test_") as tmp:
        tmp_dir = Path(tmp)
        video_path = str(tmp_dir / "short_test.mp4")
        make_short_video(video_path)

        print("=== Test 1/3: unique_path no sobrescribe ===")
        test_unique_path(tmp_dir)

        print("\n=== Test 2/3: exportación por lotes (2 momentos x 2 formatos) ===")
        test_batch_export_success(tmp_dir, video_path)

        print("\n=== Test 3/3: un clip fallido no detiene el resto ===")
        test_batch_export_partial_failure(tmp_dir, video_path)

    print("\n🎉 Todos los tests de exportación por lotes pasaron.")


if __name__ == "__main__":
    main()
