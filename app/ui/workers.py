"""
workers.py
----------
El análisis de un stream de 3+ horas y la exportación de clips con FFmpeg
tardan segundos/minutos: TODO eso debe ir en QThread para no congelar la
interfaz. Estos workers emiten señales de progreso que la ventana principal
conecta a la barra de progreso y a los logs.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from ..core.moment_detector import run_full_analysis, AnalysisResult, FAST_MODE, AnalysisMode
from ..core.proc_utils import AnalysisCancelled
from ..core.clip_exporter import export_clip, ExportOptions
from ..core.batch_export import BatchExportJob, BatchExportResult, run_batch_export


class AnalysisWorker(QThread):
    progress = Signal(str, float)     # (etapa, 0..1)
    finished_ok = Signal(object)      # AnalysisResult
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, video_path: str, work_dir: str,
                 clip_len_options: tuple, max_moments: int,
                 mode: AnalysisMode = FAST_MODE, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.work_dir = work_dir
        self.clip_len_options = clip_len_options
        self.max_moments = max_moments
        self.mode = mode
        self._cancel_event = threading.Event()

    def request_cancel(self):
        self._cancel_event.set()

    def run(self):
        try:
            result: AnalysisResult = run_full_analysis(
                self.video_path, self.work_dir,
                clip_len_options=self.clip_len_options,
                max_moments=self.max_moments,
                mode=self.mode,
                progress_cb=lambda stage, frac: self.progress.emit(stage, frac),
                cancel_check=self._cancel_event.is_set,
            )
            self.finished_ok.emit(result)
        except AnalysisCancelled:
            self.cancelled.emit()
        except Exception as e:
            import traceback
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")


class ExportWorker(QThread):
    progress = Signal(str, float)
    finished_ok = Signal(str)   # ruta del clip exportado
    failed = Signal(str)

    def __init__(self, source_video: str, out_path: str, clip_start: float, clip_end: float,
                 options: ExportOptions, src_width: int, src_height: int,
                 work_dir: str = "", parent=None):
        super().__init__(parent)
        self.source_video = source_video
        self.out_path = out_path
        # OJO: nunca nombrar esto "self.start"/"self.end" - QThread ya tiene
        # un metodo start() y una asignacion asi lo pisa en silencio, causando
        # "TypeError: 'float' object is not callable" al llamar .start().
        self.clip_start = clip_start
        self.clip_end = clip_end
        self.options = options
        self.src_width = src_width
        self.src_height = src_height
        self.work_dir = work_dir

    def run(self):
        try:
            self.progress.emit("stage.exporting_ffmpeg", 0.4)
            out = export_clip(
                self.source_video, self.out_path, self.clip_start, self.clip_end,
                self.options, self.src_width, self.src_height,
            )
            self.progress.emit("stage.export_complete", 1.0)
            self.finished_ok.emit(out)
        except Exception as e:
            import traceback
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")


class BatchExportWorker(QThread):
    """Exporta varios clips (uno por cada momento x formato seleccionado)
    a una carpeta ya elegida por el usuario, uno tras otro, sin volver a
    preguntar nada. Un fallo en un clip no detiene a los demás - ver
    `batch_export.run_batch_export`."""
    progress = Signal(int, int, str)          # (índice 1-based, total, etiqueta del job actual)
    finished_all = Signal(list)               # list[BatchExportResult]

    def __init__(self, jobs: list[BatchExportJob], parent=None):
        super().__init__(parent)
        self.jobs = jobs

    def run(self):
        results: list[BatchExportResult] = run_batch_export(
            self.jobs,
            progress_cb=lambda i, total, label: self.progress.emit(i, total, label),
        )
        self.finished_all.emit(results)
