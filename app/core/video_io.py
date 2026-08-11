"""
video_io.py
-----------
Validación de archivos de entrada (MP4/MKV/MOV) y extracción de metadata
(duración, resolución, fps, códecs) vía ffprobe, para poder avisar al
usuario de problemas antes de lanzar un análisis de 3 horas.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_EXTENSIONS = {".mp4", ".mkv", ".mov"}
MIN_DURATION_SECONDS_WARN = 3 * 60 * 60  # 3 horas: solo un aviso informativo, no bloqueante


@dataclass
class VideoInfo:
    path: str
    duration_sec: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str
    has_audio: bool
    size_bytes: int


class VideoValidationError(Exception):
    pass


def _ffprobe_bin() -> str:
    exe = shutil.which("ffprobe")
    if not exe:
        raise RuntimeError(
            "No se encontró FFprobe (parte de FFmpeg) en el PATH. Instala FFmpeg completo."
        )
    return exe


def validate_and_probe(path: str) -> VideoInfo:
    p = Path(path)
    if not p.exists():
        raise VideoValidationError(f"El archivo no existe: {path}")
    if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise VideoValidationError(
            f"Formato no soportado '{p.suffix}'. Usa MP4, MKV o MOV."
        )

    ffprobe = _ffprobe_bin()
    cmd = [
        ffprobe, "-v", "error", "-show_entries",
        "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate",
        "-of", "json", str(p),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise VideoValidationError(
            f"No se pudo leer el video (¿archivo corrupto?): {proc.stderr.decode(errors='ignore')}"
        )

    data = json.loads(proc.stdout.decode(errors="ignore"))
    fmt = data.get("format", {})
    streams = data.get("streams", [])

    duration = float(fmt.get("duration", 0.0) or 0.0)
    size_bytes = int(fmt.get("size", 0) or 0)

    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if v_stream is None:
        raise VideoValidationError("El archivo no contiene una pista de video válida.")

    width = int(v_stream.get("width", 0) or 0)
    height = int(v_stream.get("height", 0) or 0)

    fps_raw = v_stream.get("avg_frame_rate") or v_stream.get("r_frame_rate") or "30/1"
    try:
        num, den = fps_raw.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 0.0
    except Exception:
        fps = 30.0

    return VideoInfo(
        path=str(p),
        duration_sec=duration,
        width=width,
        height=height,
        fps=fps,
        video_codec=v_stream.get("codec_name", "desconocido"),
        audio_codec=(a_stream.get("codec_name") if a_stream else "sin audio"),
        has_audio=a_stream is not None,
        size_bytes=size_bytes,
    )


def is_long_form(info: VideoInfo) -> bool:
    return info.duration_sec >= MIN_DURATION_SECONDS_WARN
