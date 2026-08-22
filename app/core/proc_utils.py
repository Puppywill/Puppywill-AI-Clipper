"""
proc_utils.py
--------------
Helpers compartidos para lanzar FFmpeg/FFprobe/Tesseract como subproceso:

  - En Windows, un proceso de consola lanzado desde una app sin consola
    (pythonw.exe) abre su propia ventana negra visible por defecto. Todas
    las llamadas a subprocess en este proyecto deben pasar por
    `run_hidden`/`popen_hidden` para evitarlo.
  - `AnalysisCancelled` + `CancelCheck` son el mecanismo cooperativo de
    cancelación: las etapas largas (decode de video, OCR) llaman a
    `cancel_check()` periódicamente y matan el subproceso en curso antes
    de lanzar la excepción, para que "Cancelar" corte de inmediato en vez
    de esperar a que termine la etapa.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Callable, Optional

CancelCheck = Optional[Callable[[], bool]]
ProgressCB1 = Optional[Callable[[float], None]]  # progreso 0..1 dentro de una sola etapa

_CREATIONFLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class AnalysisCancelled(Exception):
    """Se lanza cuando el usuario cancela un análisis en curso."""


def run_hidden(cmd, **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.PIPE)
    return subprocess.run(cmd, creationflags=_CREATIONFLAGS, **kwargs)


def popen_hidden(cmd, **kwargs) -> subprocess.Popen:
    return subprocess.Popen(cmd, creationflags=_CREATIONFLAGS, **kwargs)


def ffmpeg_bin() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError(
            "No se encontró FFmpeg en el PATH. Instálalo desde https://ffmpeg.org/download.html "
            "o con 'winget install ffmpeg' en Windows."
        )
    return exe


def ffprobe_bin() -> str:
    exe = shutil.which("ffprobe")
    if not exe:
        raise RuntimeError(
            "No se encontró FFprobe (parte de FFmpeg) en el PATH. Instala FFmpeg completo."
        )
    return exe


# codec -> disponible sí/no, cacheado en memoria (una sola prueba real por
# codec y proceso; evita repetir la prueba en cada video)
_GPU_DECODE_CACHE: dict[str, bool] = {}


def gpu_decode_available(video_path: str, codec: str) -> bool:
    """Prueba UNA VEZ por códec (resultado cacheado) si FFmpeg puede
    decodificar este video por GPU (NVDEC vía `-hwaccel cuda`), incluyendo
    AV1/HEVC/H.264 si el driver NVIDIA los soporta. Decodifica de verdad
    1 segundo real del archivo (no un video sintético) para no dar falsos
    positivos si el build de FFmpeg anuncia el hwaccel pero no funciona en
    la práctica con ESTE códec (como pasaba con NVENC a baja resolución)."""
    key = (codec or "").lower()
    if key in _GPU_DECODE_CACHE:
        return _GPU_DECODE_CACHE[key]
    try:
        ffmpeg = ffmpeg_bin()
        proc = run_hidden(
            [ffmpeg, "-hide_banner", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
             "-t", "1", "-i", str(video_path), "-frames:v", "1", "-f", "null", "-"],
            timeout=20,
        )
        ok = proc.returncode == 0
    except Exception:
        ok = False
    _GPU_DECODE_CACHE[key] = ok
    return ok


def check_cancel(cancel_check: CancelCheck, proc: Optional[subprocess.Popen] = None) -> None:
    """Si `cancel_check()` devuelve True, mata `proc` (si se pasó) y lanza
    AnalysisCancelled. Llamar periódicamente dentro de bucles largos."""
    if cancel_check is not None and cancel_check():
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        raise AnalysisCancelled("Análisis cancelado por el usuario")
