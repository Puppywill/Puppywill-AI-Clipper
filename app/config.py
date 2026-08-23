"""
config.py
---------
Guarda y carga los ajustes persistentes del usuario en un JSON dentro de
su carpeta de datos de aplicación local (%LOCALAPPDATA%\\PuppywillAIClipper
en Windows, ~/.config/PuppywillAIClipper en Linux/Mac para desarrollo/
pruebas) - LOCAL y no Roaming a propósito: son ajustes/caché de esta
máquina (rutas de export, caché de análisis), no algo que deba
sincronizarse entre equipos de un dominio. Nunca dentro de Program
Files: el instalador no necesita permisos de administrador para que la
app pueda escribir aquí.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict, field, fields
from pathlib import Path


def get_app_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    d = Path(base) / "PuppywillAIClipper"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_default_export_dir() -> str:
    """Carpeta sugerida por defecto para los clips exportados (el usuario
    siempre puede cambiarla, esto es solo el punto de partida). A
    propósito NO usa "Documents/Pictures/Videos/Desktop" del perfil: en
    Windows, OneDrive puede redirigir cualquiera de esas carpetas
    "conocidas" a `...\\OneDrive\\<Carpeta>` sin que se note a simple
    vista (confirmado en esta misma máquina: Desktop y Pictures están
    redirigidas, Videos no - varía por PC y por configuración de
    OneDrive). Para no arriesgarse a subir videos/clips a la nube sin
    que el usuario lo pida, el valor por defecto es una carpeta plana
    directamente bajo el perfil (`%USERPROFILE%\\PuppywillClips`), que
    OneDrive nunca redirige."""
    return str(Path.home() / "PuppywillClips")


CONFIG_PATH = get_app_data_dir() / "settings.json"


@dataclass
class AppSettings:
    last_export_dir: str = field(default_factory=get_default_export_dir)
    default_clip_length: int = 30
    default_aspect_ratio: str = "9:16"
    normalize_audio: bool = True
    prefer_gpu: bool = True
    max_moments_per_video: int = 15
    recent_projects: list = field(default_factory=list)
    language: str = "es"  # "es" | "en" | "pt" - ver app/i18n.py

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
