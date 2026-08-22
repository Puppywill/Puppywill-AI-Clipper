"""
batch_export.py
----------------
Exporta varios momentos seleccionados en una sola pasada: uno o más
clips (uno por cada combinación momento x formato) a una única carpeta
de destino, sin volver a preguntar nada por archivo. Si un clip falla,
el resto sigue exportándose - `run_batch_export` nunca lanza por un solo
fallo, solo lo reporta en el resultado de ESE trabajo.

Esto es lógica pura (sin Qt), para poder probarla directamente en un
test rápido; `app/ui/workers.py` solo la envuelve en un QThread.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .clip_exporter import ExportOptions, export_clip

ProgressCB = Optional[Callable[[int, int, str], None]]  # (índice 1-based, total, etiqueta)


@dataclass
class BatchExportJob:
    source_video: str
    out_path: str
    start: float
    end: float
    options: ExportOptions
    src_width: int
    src_height: int
    label: str  # texto descriptivo para progreso/errores, p.ej. "Momento #2 (9:16)"


@dataclass
class BatchExportResult:
    job: BatchExportJob
    ok: bool
    out_path: str = ""
    error: str = ""


def unique_path(directory: Path, filename: str) -> Path:
    """Si `directory/filename` ya existe, agrega _2, _3... antes de la
    extensión hasta encontrar un nombre libre - nunca sobrescribe un clip
    existente (de una exportación anterior, individual o por lotes)."""
    directory = Path(directory)
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    n = 2
    while True:
        candidate = directory / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def run_batch_export(jobs: list[BatchExportJob], progress_cb: ProgressCB = None) -> list[BatchExportResult]:
    """Exporta cada job en orden. Un fallo en un job NO detiene a los
    demás - se reporta en su BatchExportResult y se sigue con el
    siguiente, para que un solo clip problemático no tire toda la
    exportación por lotes."""
    results: list[BatchExportResult] = []
    total = len(jobs)
    for i, job in enumerate(jobs, start=1):
        if progress_cb:
            progress_cb(i, total, job.label)
        try:
            out = export_clip(
                job.source_video, job.out_path, job.start, job.end,
                job.options, job.src_width, job.src_height,
            )
            results.append(BatchExportResult(job=job, ok=True, out_path=out))
        except Exception as e:
            results.append(BatchExportResult(job=job, ok=False, error=str(e)))
    return results
