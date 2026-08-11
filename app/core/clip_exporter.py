"""
clip_exporter.py
-----------------
Exporta un momento del video original a un clip final usando FFmpeg,
limpio (sin subtítulos, sin marca de agua) para editar después en CapCut
u otro editor:
  1. Recorta el intervalo [start, end].
  2. Encuadra/recorta a la relación de aspecto pedida (9:16, 16:9, 1:1).
     En vertical, por defecto centra el crop en el gameplay; si se pasa
     `face_box` (de un futuro módulo de detección de rostro), se ajusta
     el crop para mantener la cara visible dentro del encuadre.
  3. Normaliza el audio con el filtro `loudnorm` (EBU R128, estándar de
     plataformas como TikTok/YouTube).
  4. Codifica en H.264 1080p 60fps.

Usa NVENC (h264_nvenc) automáticamente si detecta una GPU NVIDIA
compatible; si no, cae a libx264 (CPU) sin que el usuario tenga que
configurar nada.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Literal

AspectRatio = Literal["9:16", "16:9", "1:1"]

TARGET_DIMENSIONS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}


def _ffmpeg_bin() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("No se encontró FFmpeg en el PATH.")
    return exe


_NVENC_AVAILABLE: Optional[bool] = None


def nvenc_available() -> bool:
    """Comprueba una sola vez (cachea el resultado) si FFmpeg tiene soporte
    NVENC compilado y hay una GPU NVIDIA que lo acepte, lanzando una
    codificación de prueba mínima."""
    global _NVENC_AVAILABLE
    if _NVENC_AVAILABLE is not None:
        return _NVENC_AVAILABLE
    ffmpeg = _ffmpeg_bin()
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-f", "lavfi", "-i", "color=black:s=1280x720:d=0.1",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
        )
        _NVENC_AVAILABLE = proc.returncode == 0
    except Exception:
        _NVENC_AVAILABLE = False
    return _NVENC_AVAILABLE


@dataclass
class ExportOptions:
    aspect_ratio: AspectRatio = "9:16"
    fps: int = 60
    crf: int = 18                 # calidad libx264 (menor = mejor, 18 es "visualmente sin pérdida")
    face_center_x_ratio: Optional[float] = None  # 0..1, posición horizontal de la cara en el frame original
    background_blur: bool = False   # para 16:9->9:16 sin crop agresivo: fondo difuminado + video centrado
    normalize_audio: bool = True
    music_path: Optional[str] = None
    music_volume_db: float = -18.0
    use_gpu: Optional[bool] = None  # None = autodetectar


def _build_crop_filter(src_w: int, src_h: int, target_w: int, target_h: int,
                        face_center_x_ratio: Optional[float]) -> str:
    """Genera el filtro de FFmpeg para recortar `src` a la relación de
    aspecto de `target`, centrando el crop horizontalmente en la cara si
    se conoce su posición (importante en vertical para no cortar al
    streamer si está a un lado del frame).
    """
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if abs(target_ratio - src_ratio) < 1e-3:
        return f"scale={target_w}:{target_h}"

    if target_ratio < src_ratio:
        # el target es más "alto" relativo -> recortamos ancho, mantenemos alto completo
        crop_h = src_h
        crop_w = int(round(src_h * target_ratio))
        if face_center_x_ratio is not None:
            center_x = int(face_center_x_ratio * src_w)
            x = int(max(0, min(src_w - crop_w, center_x - crop_w // 2)))
        else:
            x = (src_w - crop_w) // 2
        return f"crop={crop_w}:{crop_h}:{x}:0,scale={target_w}:{target_h}"
    else:
        # el target es más "ancho" relativo -> recortamos alto
        crop_w = src_w
        crop_h = int(round(src_w / target_ratio))
        y = (src_h - crop_h) // 2
        return f"crop={crop_w}:{crop_h}:0:{y},scale={target_w}:{target_h}"


def export_clip(
    source_video: str,
    out_path: str,
    start: float,
    end: float,
    options: ExportOptions,
    src_width: int,
    src_height: int,
) -> str:
    """Exporta un clip real desde `source_video` entre [start, end].

    Devuelve la ruta del archivo generado. Lanza RuntimeError con el
    stderr de FFmpeg si algo falla (no se traga errores en silencio).
    """
    ffmpeg = _ffmpeg_bin()
    out_path = str(out_path)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    target_w, target_h = TARGET_DIMENSIONS[options.aspect_ratio]
    duration = max(0.1, end - start)

    vf_parts = [_build_crop_filter(src_width, src_height, target_w, target_h, options.face_center_x_ratio)]
    vf_parts.append(f"fps={options.fps}")
    vf = ",".join(vf_parts)

    use_gpu = options.use_gpu if options.use_gpu is not None else nvenc_available()
    if use_gpu:
        vcodec_args = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", str(options.crf), "-b:v", "0"]
    else:
        vcodec_args = ["-c:v", "libx264", "-preset", "medium", "-crf", str(options.crf)]

    af_parts = []
    if options.normalize_audio:
        af_parts.append("loudnorm=I=-14:TP=-1.5:LRA=11")  # estándar de volumen para redes sociales

    cmd = [
        ffmpeg, "-y",
        "-ss", f"{start:.3f}", "-i", str(source_video),
    ]

    if options.music_path:
        cmd += ["-i", options.music_path]

    cmd += ["-t", f"{duration:.3f}", "-vf", vf]

    if options.music_path:
        # mezcla voz del stream + música de fondo a bajo volumen
        music_gain = f"volume={options.music_volume_db}dB"
        af_chain = f"[1:a]{music_gain}[music];[0:a]{','.join(af_parts) if af_parts else 'anull'}[voice];[voice][music]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        cmd += ["-filter_complex", af_chain, "-map", "0:v", "-map", "[aout]"]
    elif af_parts:
        cmd += ["-af", ",".join(af_parts)]

    cmd += vcodec_args
    cmd += ["-pix_fmt", "yuv420p", "-r", str(options.fps)]
    cmd += ["-c:a", "aac", "-b:a", "192k"]
    cmd += ["-movflags", "+faststart"]
    cmd += [out_path]

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(
            f"FFmpeg falló exportando el clip:\ncmd={' '.join(cmd)}\n\n{proc.stderr.decode(errors='ignore')[-3000:]}"
        )
    return out_path
