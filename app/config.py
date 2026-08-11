"""
config.py
---------
Guarda y carga los ajustes persistentes del usuario en un JSON dentro de
su carpeta de datos de aplicación (%APPDATA%\\PuppywillAIClipper en
Windows, ~/.config/PuppywillAIClipper en Linux/Mac para desarrollo/pruebas).
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict, field, fields
from pathlib import Path


def get_app_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    d = Path(base) / "PuppywillAIClipper"
    d.mkdir(parents=True, exist_ok=True)
    return d


CONFIG_PATH = get_app_data_dir() / "settings.json"


@dataclass
class AppSettings:
    last_export_dir: str = str(Path.home() / "Videos" / "PuppywillClips")
    default_clip_length: int = 30
    default_aspect_ratio: str = "9:16"
    normalize_audio: bool = True
    prefer_gpu: bool = True
    max_moments_per_video: int = 15
    recent_projects: list = field(default_factory=list)

    def save(self):
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def load() -> "AppSettings":
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                # filtra claves de versiones viejas del settings.json que ya
                # no existen, para no romper la carga
                known_fields = {f.name for f in fields(AppSettings)}
                data = {k: v for k, v in data.items() if k in known_fields}
                return AppSettings(**{**asdict(AppSettings()), **data})
            except Exception:
                pass
        return AppSettings()
