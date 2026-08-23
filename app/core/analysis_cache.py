"""
analysis_cache.py
------------------
Cachea el resultado completo de `run_full_analysis` (features de audio,
video, kills y los momentos ya calculados) en disco, para no repetir un
análisis de horas si el usuario vuelve a analizar el mismo archivo con
los mismos ajustes (p.ej. cerró y volvió a abrir la app, o pulsó
"Analizar" dos veces).

La clave de caché depende del video (ruta + tamaño + fecha de
modificación, así que un archivo reemplazado con el mismo nombre no
reutiliza un resultado viejo) y de los ajustes de análisis (modo
Rápido/Preciso, cuántos momentos, duraciones); cambiar cualquiera de
esos invalida el caché automáticamente.
"""
from __future__ import annotations

import hashlib
import pickle
from pathlib import Path
from typing import Optional

from ..config import get_app_data_dir

CACHE_VERSION = 1
CACHE_DIR = get_app_data_dir() / "analysis_cache"


def _cache_key(video_path: str, size_bytes: int, mtime: float, mode_key: str,
               sample_fps: float, resize_w: int, clip_len_options: tuple, max_moments: int) -> str:
    raw = "|".join([
        str(Path(video_path).resolve()), str(size_bytes), str(mtime), mode_key,
        str(sample_fps), str(resize_w), str(clip_len_options), str(max_moments), f"v{CACHE_VERSION}",
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.pkl"


def load(video_path: str, mode, clip_len_options: tuple, max_moments: int):
    """Devuelve el AnalysisResult cacheado, o None si no hay caché válido
    para este archivo+ajustes (nunca lanza: un caché corrupto o de una
    versión vieja simplemente se ignora y se re-analiza)."""
    try:
        st = Path(video_path).stat()
        key = _cache_key(video_path, st.st_size, st.st_mtime, mode.key,
                          mode.sample_fps, mode.resize_w, clip_len_options, max_moments)
        path = _cache_path(key)
        if not path.is_file():
            return None
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def save(video_path: str, mode, clip_len_options: tuple, max_moments: int, result) -> None:
    """Guarda el resultado; si falla (disco lleno, permisos), no rompe el
    análisis - simplemente la próxima vez no habrá caché."""
    try:
        st = Path(video_path).stat()
        key = _cache_key(video_path, st.st_size, st.st_mtime, mode.key,
                          mode.sample_fps, mode.resize_w, clip_len_options, max_moments)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _cache_path(key)
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "wb") as f:
            pickle.dump(result, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp_path.replace(path)
    except Exception:
        pass


def clear() -> int:
    """Borra todo el caché (usado desde la UI, botón opcional). Devuelve
    cuántos archivos se borraron."""
    n = 0
    if not CACHE_DIR.is_dir():
        return 0
    for f in CACHE_DIR.glob("*.pkl"):
        try:
            f.unlink()
            n += 1
        except OSError:
            pass
    return n
