"""
workers.py
----------
El análisis de un stream de 3+ horas y la exportación de clips con FFmpeg
tardan segundos/minutos: TODO eso debe ir en QThread para no congelar la
interfaz. Estos workers emiten señales de progreso que la ventana principal
conecta a la barra de progreso y a los logs.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..core.moment_detector import run_full_analysis, AnalysisResult
from ..core.clip_exporter import export_clip, ExportOptions


class AnalysisWorker(QThread):
    progress = Signal(str, float)     # (etapa, 0..1)
    finished_ok = Signal(object)      # AnalysisResult
    failed = Signal(str)

    def __init__(self, video_path: str, work_dir: str,
                 clip_len_options: tuple, max_moments: int, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.work_dir = work_dir
        self.clip_len_options = clip_len_options
        self.max_moments = max_moments

    def run(self):
        try:
            result: AnalysisResult = run_full_analysis(
                self.video_path, self.work_dir,
                clip_len_options=self.clip_len_options,
                max_moments=self.max_moments,
                progress_cb=lambda stage, frac: self.progress.emit(stage, frac),
            )
            self.finished_ok.emit(result)
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
            self.progress.emit("Exportando clip con FFmpeg", 0.4)
            out = export_clip(
                self.source_video, self.out_path, self.clip_start, self.clip_end,
                self.options, self.src_width, self.src_height,
            )
            self.progress.emit("Completado", 1.0)
            self.finished_ok.emit(out)
        except Exception as e:
            import traceback
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")
