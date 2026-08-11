"""
project.py
----------
Un "proyecto" de Puppywill AI Clipper es un archivo .pwproj (JSON) que
guarda:
  - la ruta del video original,
  - los momentos detectados (con su score y razones),
  - los ajustes de exportación elegidos para cada clip (inicio/fin
    ajustados manualmente, duración, aspecto),
  - metadata general (fecha de análisis).

Así el usuario puede cerrar la app y retomar el proyecto más tarde sin
tener que re-analizar el video de 3 horas de nuevo.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict, fields
from pathlib import Path
from typing import Optional

PROJECT_EXTENSION = ".pwproj"
PROJECT_VERSION = 1


@dataclass
class ClipEditState:
    moment_index: int
    start: float
    end: float
    clip_length: int = 30
    aspect_ratio: str = "9:16"
    title: str = ""
    description: str = ""
    hashtags: list = field(default_factory=list)
    exported_path: Optional[str] = None


@dataclass
class ProjectData:
    version: int = PROJECT_VERSION
    video_path: str = ""
    video_duration_sec: float = 0.0
    moments: list = field(default_factory=list)   # lista de dicts (Moment serializado)
    clip_edits: list = field(default_factory=list)  # lista de dicts (ClipEditState serializado)
    analyzed_at: str = ""


def save_project(data: ProjectData, path: str) -> str:
    path = str(path)
    if not path.endswith(PROJECT_EXTENSION):
        path += PROJECT_EXTENSION
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(asdict(data), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_project(path: str) -> ProjectData:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    # filtra campos de versiones viejas del proyecto que ya no existen,
    # para no romper la carga
    known_fields = {f.name for f in fields(ProjectData)}
    raw = {k: v for k, v in raw.items() if k in known_fields}
    return ProjectData(**{**asdict(ProjectData()), **raw})


def moment_to_dict(m) -> dict:
    return {
        "start": m.start, "end": m.end, "score": m.score,
        "peak_time": m.peak_time, "reasons": m.reasons,
    }
