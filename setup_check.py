#!/usr/bin/env python3
"""
setup_check.py
---------------
Ejecuta este script ANTES de instalar dependencias pesadas o de correr la
app por primera vez:

    python setup_check.py

Revisa:
  - Versión de Python
  - FFmpeg / FFprobe en el PATH
  - GPU NVIDIA (vía nvidia-smi, opcional)
  - Soporte NVENC de FFmpeg (para exportación acelerada por GPU, opcional)
  - Tesseract OCR (opcional, mejora el conteo de multikills)
  - Paquetes de requirements.txt instalados o no

No instala nada por sí mismo: solo diagnostica, para que decidas con
información completa antes de lanzar instalaciones largas.
"""
import shutil
import subprocess
import sys
import importlib.util


def check(label, ok, detail=""):
    status = "✅" if ok else "❌"
    print(f"{status} {label}" + (f"  —  {detail}" if detail else ""))
    return ok


def main():
    print("=" * 60)
    print("Puppywill AI Clipper — Verificación de sistema")
    print("=" * 60)

    all_ok = True

    # Python
    py_ok = sys.version_info >= (3, 10)
    all_ok &= check(f"Python {sys.version.split()[0]}", py_ok, "se recomienda 3.10 - 3.12")

    # FFmpeg / FFprobe
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    all_ok &= check("FFmpeg en PATH", bool(ffmpeg_path), ffmpeg_path or "instala desde https://ffmpeg.org o 'winget install ffmpeg'")
    all_ok &= check("FFprobe en PATH", bool(ffprobe_path), ffprobe_path or "")

    # NVENC (exportación acelerada): probamos una codificación real de 0.1s,
    # no solo si el encoder aparece listado (listado != funcional sin GPU/driver)
    nvenc_ok = False
    if ffmpeg_path:
        try:
            proc = subprocess.run(
                [ffmpeg_path, "-hide_banner", "-f", "lavfi", "-i", "color=black:s=1280x720:d=0.1",
                 "-c:v", "h264_nvenc", "-f", "null", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
            )
            nvenc_ok = proc.returncode == 0
        except Exception:
            pass
    check("NVENC funcional (exportación acelerada por GPU)", nvenc_ok,
          "sin esto, la exportación usará CPU (libx264); normal si no hay GPU NVIDIA aquí")

    # nvidia-smi (opcional: solo informativo, no bloquea nada)
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            proc = subprocess.run([nvidia_smi, "--query-gpu=name,memory.total,driver_version",
                                    "--format=csv,noheader"], stdout=subprocess.PIPE, timeout=10)
            print(f"   ℹ️  GPU detectada por nvidia-smi: {proc.stdout.decode().strip()}")
        except Exception:
            pass
    else:
        check("nvidia-smi disponible", False, "revisa que los drivers NVIDIA estén instalados")

    # Tesseract OCR (opcional: solo informativo, no bloquea nada - ver
    # app/core/kill_events.py, que busca en PATH y en la ruta estándar de
    # instalación en Windows)
    tesseract_path = shutil.which("tesseract")
    if not tesseract_path:
        import os
        for candidate in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                          r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
            if os.path.isfile(candidate):
                tesseract_path = candidate
                break
    check("Tesseract OCR (opcional, mejora el conteo de multikills)", bool(tesseract_path),
          tesseract_path or "sin esto, la detección de kills usa solo audio + actividad visual, funciona igual")

    # Paquetes clave (estos SÍ son obligatorios para poder ejecutar la app)
    required_packages_ok = True
    for pkg, import_name in [
        ("PySide6", "PySide6"),
        ("opencv-python", "cv2"),
        ("numpy", "numpy"),
    ]:
        spec = importlib.util.find_spec(import_name)
        ok = spec is not None
        required_packages_ok &= ok
        check(f"Paquete {pkg}", ok, "no instalado, ver requirements.txt" if not ok else "")

    all_ok &= required_packages_ok

    print("=" * 60)
    if all_ok:
        print("Todo listo: FFmpeg y todas las dependencias de Python están instaladas.")
    else:
        print("Faltan elementos marcados con ❌ arriba antes de poder ejecutar 'python main.py'.")
        print("(NVENC es opcional: sin él la exportación usa CPU (libx264), más lenta pero funciona igual.)")
    print("=" * 60)


if __name__ == "__main__":
    main()
