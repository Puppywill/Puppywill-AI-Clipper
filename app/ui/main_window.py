"""
main_window.py
---------------
Ventana principal de Puppywill AI Clipper.

Puppywill AI Clipper solo encuentra los mejores momentos (por audio +
video) y los recorta en limpio; la edición final (subtítulos, efectos,
títulos, música) se hace fuera de la app, p.ej. en CapCut. No hay
transcripción ni modelos de lenguaje involucrados.

Flujo:
  1. El usuario arrastra o selecciona un video largo (MP4/MKV/MOV).
  2. Pulsa "Analizar" -> AnalysisWorker corre en background (audio +
     video) y reporta progreso.
  3. Al terminar, se listan los momentos ordenados por score.
  4. Al seleccionar un momento, se puede previsualizar y ajustar
     manualmente el inicio/fin con sliders.
  5. Se elige duración y aspecto(s), y se exporta el clip limpio con
     ExportWorker (también en background).
  6. Los ajustes y el proyecto se pueden guardar para retomar después.
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QDesktopServices
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QListWidget, QListWidgetItem, QProgressBar, QComboBox,
    QCheckBox, QSlider, QMessageBox, QSplitter,
    QGroupBox, QFormLayout, QSpinBox,
)

try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PySide6.QtMultimediaWidgets import QVideoWidget
    HAVE_MULTIMEDIA = True
except ImportError:
    HAVE_MULTIMEDIA = False

from .. import config
from ..core.video_io import validate_and_probe, VideoValidationError, SUPPORTED_EXTENSIONS
from ..core import project as project_mod
from ..core import scoring
from ..core.clip_exporter import ExportOptions
from ..core.moment_detector import FAST_MODE, PRECISE_MODE, MODES
from ..core.batch_export import BatchExportJob, unique_path
from .workers import AnalysisWorker, ExportWorker, BatchExportWorker
from .styles import DARK_QSS, ACCENT_2


APP_NAME = "Puppywill AI Clipper"


def format_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


class MomentListItemWidget(QWidget):
    """Widget custom para cada fila de la lista de momentos: casilla de
    selección (para exportar varios a la vez), rango de tiempo, badge de
    score y razones detectadas (audio/movimiento/escena)."""

    def __init__(self, moment, index: int, on_toggle=None):
        super().__init__()
        self.moment = moment
        self.index = index
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)

        top_row = QHBoxLayout()
        self.checkbox = QCheckBox()
        self.checkbox.setToolTip("Seleccionar para exportar junto a otros momentos marcados")
        if on_toggle is not None:
            self.checkbox.toggled.connect(lambda checked: on_toggle(index, checked))
        top_row.addWidget(self.checkbox)
        time_label = QLabel(f"#{index+1}  {format_time(moment.start)} – {format_time(moment.end)}")
        time_label.setStyleSheet("font-weight: 600;")
        score_label = QLabel(f"{moment.score:.0f}")
        score_label.setObjectName("ScoreBadge")
        top_row.addWidget(time_label)
        top_row.addStretch()
        top_row.addWidget(score_label)
        layout.addLayout(top_row)

        reasons_label = QLabel(" · ".join(moment.reasons))
        reasons_label.setStyleSheet(f"color: {ACCENT_2}; font-size: 11px;")
        layout.addWidget(reasons_label)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 860)
        self.setAcceptDrops(True)

        self.settings = config.AppSettings.load()

        self.video_path: str | None = None
        self.video_info = None
        self.analysis_result = None
        self.work_dir = tempfile.mkdtemp(prefix="puppywill_")
        self.current_moment_index: int | None = None
        self.trim_start = 0.0
        self.trim_end = 0.0
        self._moment_peak_time = 0.0
        self._action_grid = None
        self._action_score = None
        self._analysis_start_time = 0.0
        self.selected_moment_indices: set[int] = set()
        self._moment_widgets: list[MomentListItemWidget] = []

        self._build_ui()
        self.setStyleSheet(DARK_QSS)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_center_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([760, 480])
        root.addWidget(splitter, 1)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(230)
        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(0, 0, 0, 12)
        lay.setSpacing(4)

        brand = QLabel("🐾 Puppywill")
        brand.setObjectName("BrandLabel")
        sub = QLabel("AI Clipper")
        sub.setObjectName("BrandSubLabel")
        lay.addWidget(brand)
        lay.addWidget(sub)

        lay.addWidget(self._section_title("PROYECTO"))
        btn_open = QPushButton("📂  Abrir video…")
        btn_open.clicked.connect(self.on_open_video)
        lay.addWidget(btn_open)

        btn_load_proj = QPushButton("📁  Cargar proyecto…")
        btn_load_proj.clicked.connect(self.on_load_project)
        lay.addWidget(btn_load_proj)

        btn_save_proj = QPushButton("💾  Guardar proyecto")
        btn_save_proj.clicked.connect(self.on_save_project)
        lay.addWidget(btn_save_proj)

        lay.addWidget(self._section_title("ANÁLISIS"))

        form = QFormLayout()
        self.spin_max_moments = QSpinBox()
        self.spin_max_moments.setRange(3, 40)
        self.spin_max_moments.setValue(self.settings.max_moments_per_video)
        form.addRow("Máx. momentos:", self.spin_max_moments)

        self.combo_mode = QComboBox()
        self.combo_mode.addItems([FAST_MODE.name, PRECISE_MODE.name])
        self.combo_mode.setCurrentText(FAST_MODE.name)
        self.combo_mode.setToolTip(
            "Rápido: decodificación GPU + menos muestras/candidatos OCR - recomendado.\n"
            "Preciso: más muestras por segundo y más candidatos OCR, más lento."
        )
        form.addRow("Modo:", self.combo_mode)
        lay.addLayout(form)

        self.btn_analyze = QPushButton("⚡  Analizar Stream")
        self.btn_analyze.setObjectName("PrimaryButton")
        self.btn_analyze.setEnabled(False)
        self.btn_analyze.clicked.connect(self.on_analyze_clicked)
        lay.addWidget(self.btn_analyze)

        self.btn_cancel_analysis = QPushButton("✕  Cancelar análisis")
        self.btn_cancel_analysis.setVisible(False)
        self.btn_cancel_analysis.clicked.connect(self.on_cancel_analysis_clicked)
        lay.addWidget(self.btn_cancel_analysis)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        lay.addWidget(self.progress_bar)

        self.log_label = QLabel("Esperando video…")
        self.log_label.setWordWrap(True)
        self.log_label.setStyleSheet("color: #8E8EA0; font-size: 11px; padding: 4px 4px;")
        lay.addWidget(self.log_label)

        lay.addStretch()

        gpu_note = QLabel("GPU: se detecta automáticamente\n(NVDEC decode + NVENC export si están disponibles)")
        gpu_note.setStyleSheet("color: #6E6E80; font-size: 10px; padding: 8px;")
        gpu_note.setWordWrap(True)
        lay.addWidget(gpu_note)

        return sidebar

    def _section_title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("SectionTitle")
        lbl.setContentsMargins(16, 0, 16, 0)
        return lbl

    def _build_center_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 16, 16, 16)

        self.drop_zone = QPushButton(
            "Arrastra aquí tu grabación (MP4 / MKV / MOV)\nde 3+ horas, o haz clic para seleccionar"
        )
        self.drop_zone.setObjectName("DropZone")
        self.drop_zone.clicked.connect(self.on_open_video)
        lay.addWidget(self.drop_zone)

        self.video_info_label = QLabel("")
        self.video_info_label.setStyleSheet("color: #8E8EA0; font-size: 12px;")
        lay.addWidget(self.video_info_label)

        lay.addWidget(self._section_title("MEJORES MOMENTOS DETECTADOS"))
        self.moment_list = QListWidget()
        self.moment_list.itemClicked.connect(self.on_moment_selected)
        lay.addWidget(self.moment_list, 1)

        selection_row = QHBoxLayout()
        self.btn_select_all = QPushButton("☑ Seleccionar todos")
        self.btn_select_all.clicked.connect(self.on_select_all_clicked)
        self.btn_deselect_all = QPushButton("☐ Deseleccionar todos")
        self.btn_deselect_all.clicked.connect(self.on_deselect_all_clicked)
        selection_row.addWidget(self.btn_select_all)
        selection_row.addWidget(self.btn_deselect_all)
        lay.addLayout(selection_row)

        self.btn_export_selected = QPushButton("⬇  Exportar seleccionados")
        self.btn_export_selected.setObjectName("PrimaryButton")
        self.btn_export_selected.setEnabled(False)
        self.btn_export_selected.clicked.connect(self.on_export_selected_clicked)
        lay.addWidget(self.btn_export_selected)

        self.batch_progress = QProgressBar()
        self.batch_progress.setVisible(False)
        lay.addWidget(self.batch_progress)

        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 16, 16, 16)

        lay.addWidget(self._section_title("VISTA PREVIA"))

        if HAVE_MULTIMEDIA:
            self.video_widget = QVideoWidget()
            self.video_widget.setMinimumHeight(260)
            self.media_player = QMediaPlayer()
            self.audio_output = QAudioOutput()
            self.media_player.setAudioOutput(self.audio_output)
            self.media_player.setVideoOutput(self.video_widget)
            lay.addWidget(self.video_widget)
        else:
            self.video_widget = QLabel("Vista previa no disponible\n(instala PySide6-Addons con QtMultimedia)")
            self.video_widget.setAlignment(Qt.AlignCenter)
            self.video_widget.setMinimumHeight(200)
            lay.addWidget(self.video_widget)

        preview_controls = QHBoxLayout()
        self.btn_play = QPushButton("▶ Reproducir momento")
        self.btn_play.clicked.connect(self.on_play_moment)
        self.btn_stop = QPushButton("⏹")
        self.btn_stop.clicked.connect(self.on_stop_preview)
        preview_controls.addWidget(self.btn_play)
        preview_controls.addWidget(self.btn_stop)
        lay.addLayout(preview_controls)

        lay.addWidget(self._section_title("AJUSTE MANUAL DE INICIO/FIN"))
        self.slider_start = QSlider(Qt.Horizontal)
        self.slider_end = QSlider(Qt.Horizontal)
        self.label_trim = QLabel("00:00 – 00:00")
        for s in (self.slider_start, self.slider_end):
            s.valueChanged.connect(self.on_trim_changed)
        lay.addWidget(QLabel("Inicio:"))
        lay.addWidget(self.slider_start)
        lay.addWidget(QLabel("Fin:"))
        lay.addWidget(self.slider_end)
        lay.addWidget(self.label_trim)

        lay.addWidget(self._section_title("EXPORTACIÓN"))
        export_box = QGroupBox()
        export_form = QFormLayout(export_box)

        self.combo_length = QComboBox()
        self.combo_length.addItems(["15", "30", "45", "60"])
        self.combo_length.setCurrentText(str(self.settings.default_clip_length))
        self.combo_length.currentTextChanged.connect(self.on_length_changed)
        export_form.addRow("Duración (s):", self.combo_length)

        self.chk_vertical = QCheckBox("Vertical 9:16 (TikTok/Reels/Shorts)")
        self.chk_horizontal = QCheckBox("Horizontal 16:9 (YouTube)")
        self.chk_square = QCheckBox("Cuadrado 1:1 (Feed)")
        self.chk_vertical.setChecked(True)
        export_form.addRow(self.chk_vertical)
        export_form.addRow(self.chk_horizontal)
        export_form.addRow(self.chk_square)

        self.chk_normalize = QCheckBox("Normalizar audio")
        self.chk_normalize.setChecked(True)
        export_form.addRow(self.chk_normalize)

        lay.addWidget(export_box)

        self.btn_export = QPushButton("⬇  Exportar Clip")
        self.btn_export.setObjectName("PrimaryButton")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.on_export_clicked)
        lay.addWidget(self.btn_export)

        self.export_progress = QProgressBar()
        lay.addWidget(self.export_progress)

        lay.addStretch()
        return panel

    # ------------------------------------------------------------ Drag&Drop
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if Path(path).suffix.lower() in SUPPORTED_EXTENSIONS:
            self._load_video(path)
        else:
            QMessageBox.warning(self, APP_NAME, "Formato no soportado. Usa MP4, MKV o MOV.")

    # ------------------------------------------------------------- Acciones
    def on_open_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecciona una grabación", str(Path.home()),
            "Videos (*.mp4 *.mkv *.mov)"
        )
        if path:
            self._load_video(path)

    def _load_video(self, path: str):
        try:
            info = validate_and_probe(path)
        except VideoValidationError as e:
            QMessageBox.critical(self, APP_NAME, str(e))
            return

        self.video_path = path
        self.video_info = info
        hours = info.duration_sec / 3600
        self.video_info_label.setText(
            f"📹 {Path(path).name}  —  {info.width}x{info.height} @ {info.fps:.0f}fps  —  "
            f"{hours:.1f}h  —  {info.video_codec}/{info.audio_codec}"
        )
        self.drop_zone.setText(f"✅ Cargado: {Path(path).name}\n(Haz clic para elegir otro video)")
        self.btn_analyze.setEnabled(True)
        self.moment_list.clear()
        self.log_label.setText("Video cargado. Listo para analizar.")

        if HAVE_MULTIMEDIA:
            self.media_player.setSource(QUrl.fromLocalFile(path))

    def on_analyze_clicked(self):
        if not self.video_path:
            return
        self.btn_analyze.setEnabled(False)
        self.btn_cancel_analysis.setVisible(True)
        self.progress_bar.setValue(0)
        self._analysis_start_time = time.monotonic()

        mode = MODES.get(self.combo_mode.currentText(), FAST_MODE)
        self.worker = AnalysisWorker(
            video_path=self.video_path,
            work_dir=self.work_dir,
            clip_len_options=(15, 30, 45, 60),
            max_moments=self.spin_max_moments.value(),
            mode=mode,
        )
        self.worker.progress.connect(self.on_analysis_progress)
        self.worker.finished_ok.connect(self.on_analysis_finished)
        self.worker.failed.connect(self.on_analysis_failed)
        self.worker.cancelled.connect(self.on_analysis_cancelled)
        self.worker.start()

    def on_cancel_analysis_clicked(self):
        if hasattr(self, "worker") and self.worker.isRunning():
            self.btn_cancel_analysis.setEnabled(False)
            self.log_label.setText("Cancelando… (esperando a que FFmpeg termine el frame actual)")
            self.worker.request_cancel()

    def on_analysis_progress(self, stage: str, frac: float):
        self.progress_bar.setValue(int(frac * 100))
        eta_text = ""
        elapsed = time.monotonic() - self._analysis_start_time
        if 0.03 < frac < 0.995 and elapsed > 1.0:
            remaining = elapsed * (1.0 - frac) / frac
            eta_text = f"  —  ~{format_time(max(0.0, remaining))} restantes"
        self.log_label.setText(f"{stage}{eta_text}")

    def _analysis_ui_reset(self):
        self.btn_analyze.setEnabled(True)
        self.btn_cancel_analysis.setVisible(False)
        self.btn_cancel_analysis.setEnabled(True)

    def on_analysis_finished(self, result):
        self._analysis_ui_reset()
        self.analysis_result = result
        # curva de intensidad completa, para poder recolocar la ventana
        # dinámicamente si el usuario cambia la duración elegida
        self._action_grid = result.action_grid
        self._action_score = result.action_score
        self.selected_moment_indices = set()
        self._moment_widgets = []
        self.moment_list.clear()
        for i, m in enumerate(result.moments):
            item = QListWidgetItem()
            widget = MomentListItemWidget(m, i, on_toggle=self._on_moment_checkbox_toggled)
            item.setSizeHint(widget.sizeHint())
            self.moment_list.addItem(item)
            self.moment_list.setItemWidget(item, widget)
            self._moment_widgets.append(widget)
        self._update_export_selected_button()
        cache_note = " (cargado desde caché)" if getattr(result, "from_cache", False) else ""
        self.log_label.setText(f"{len(result.moments)} momentos encontrados{cache_note}.")
        if not result.moments:
            QMessageBox.information(self, APP_NAME, "No se encontraron momentos destacados claros. Prueba bajando el umbral o revisando el audio del video.")

    def on_analysis_failed(self, error: str):
        self._analysis_ui_reset()
        self.log_label.setText("Error en el análisis.")
        QMessageBox.critical(self, APP_NAME, f"El análisis falló:\n\n{error}")

    def on_analysis_cancelled(self):
        self._analysis_ui_reset()
        self.progress_bar.setValue(0)
        self.log_label.setText("Análisis cancelado.")

    # -------------------------------------------------- Selección múltiple
    def _on_moment_checkbox_toggled(self, index: int, checked: bool):
        if checked:
            self.selected_moment_indices.add(index)
        else:
            self.selected_moment_indices.discard(index)
        self._update_export_selected_button()

    def _update_export_selected_button(self):
        n = len(self.selected_moment_indices)
        self.btn_export_selected.setText(f"⬇  Exportar seleccionados ({n})" if n else "⬇  Exportar seleccionados")
        self.btn_export_selected.setEnabled(n > 0)

    def on_select_all_clicked(self):
        for w in self._moment_widgets:
            w.checkbox.setChecked(True)

    def on_deselect_all_clicked(self):
        for w in self._moment_widgets:
            w.checkbox.setChecked(False)

    def on_moment_selected(self, item: QListWidgetItem):
        if not self.analysis_result:
            return
        index = self.moment_list.row(item)
        self.current_moment_index = index
        moment = self.analysis_result.moments[index]

        dur = self.video_info.duration_sec if self.video_info else moment.end + 60
        self.slider_start.setRange(0, int(dur))
        self.slider_end.setRange(0, int(dur))

        # El segundo exacto del pico detectado es el punto de anclaje; la
        # duración real del rango la decide el combo "Duración (s)", y el
        # pico se posiciona ~60-75% del clip (preparación + jugada, luego
        # cierre/reacción), no centrado a ciegas.
        self._moment_peak_time = moment.peak_time
        self._apply_clip_length(int(self.combo_length.currentText()))

        self.btn_export.setEnabled(True)

    def on_length_changed(self, _text: str = ""):
        """Al cambiar la duración elegida, recentra el rango Inicio/Fin
        alrededor del momento detectado (no del rango actual del slider,
        para que el resultado sea predecible aunque el usuario ya lo haya
        ajustado manualmente antes)."""
        if self.current_moment_index is None or self.video_info is None:
            return
        self._apply_clip_length(int(self.combo_length.currentText()))

    def _apply_clip_length(self, length_sec: int):
        """Coloca [trim_start, trim_end] anclado en self._moment_peak_time
        (el segundo exacto del pico detectado), con el pico cayendo
        ~60-75% del clip -preparación + jugada antes, cierre/reacción
        después-, y una duración de exactamente length_sec segundos,
        recortada a los límites del video. Si hay una curva de intensidad
        disponible (tras analizar), el corte se ajusta a un tramo
        tranquilo cercano para no cortar a mitad de una acción sin
        resolución. Se trabaja en segundos enteros (los sliders son
        enteros) y trim_end se deriva de trim_start + length_sec para que
        la duración resultante sea siempre exacta."""
        if self.video_info is None:
            return
        video_duration = max(1, int(self.video_info.duration_sec))
        length_sec = max(1, min(int(length_sec), video_duration))

        peak_time = getattr(self, "_moment_peak_time", (self.trim_start + self.trim_end) / 2.0)
        grid = getattr(self, "_action_grid", None)
        action_score = getattr(self, "_action_score", None)
        start_f, _ = scoring.compute_clip_window(peak_time, length_sec, video_duration, grid, action_score)

        start = int(round(start_f))
        start = max(0, min(start, video_duration - length_sec))
        end = start + length_sec

        self.trim_start = float(start)
        self.trim_end = float(end)

        for slider in (self.slider_start, self.slider_end):
            slider.blockSignals(True)
            slider.setRange(0, video_duration)
        self.slider_start.setValue(start)
        self.slider_end.setValue(end)
        for slider in (self.slider_start, self.slider_end):
            slider.blockSignals(False)

        self._update_trim_label()

    def on_trim_changed(self):
        if self.slider_start.value() >= self.slider_end.value():
            self.slider_end.setValue(self.slider_start.value() + 1)
        self.trim_start = float(self.slider_start.value())
        self.trim_end = float(self.slider_end.value())
        self._update_trim_label()

    def _update_trim_label(self):
        self.label_trim.setText(
            f"{format_time(self.trim_start)} – {format_time(self.trim_end)} "
            f"({self.trim_end - self.trim_start:.0f}s)"
        )

    def on_play_moment(self):
        if not HAVE_MULTIMEDIA or self.video_path is None:
            return
        self.media_player.setPosition(int(self.trim_start * 1000))
        self.media_player.play()
        duration_ms = int((self.trim_end - self.trim_start) * 1000)
        QTimer.singleShot(max(0, duration_ms), self.media_player.pause)

    def on_stop_preview(self):
        if HAVE_MULTIMEDIA:
            self.media_player.pause()

    def on_export_clicked(self):
        if self.current_moment_index is None or not self.video_path or not self.video_info:
            QMessageBox.warning(self, APP_NAME, "Selecciona un momento de la lista antes de exportar.")
            return

        aspects = []
        if self.chk_vertical.isChecked():
            aspects.append("9:16")
        if self.chk_horizontal.isChecked():
            aspects.append("16:9")
        if self.chk_square.isChecked():
            aspects.append("1:1")
        if not aspects:
            QMessageBox.warning(self, APP_NAME, "Selecciona al menos un formato de exportación.")
            return

        self._export_queue = aspects
        self._exported_count = 0
        self.btn_export.setEnabled(False)
        self._run_next_export()

    def _run_next_export(self):
        if not self._export_queue:
            self.btn_export.setEnabled(True)
            if self._exported_count > 0:
                QMessageBox.information(self, APP_NAME, "Exportación completa. Revisa tu carpeta de clips.")
            return

        ratio = self._export_queue.pop(0)
        out_path = self._prompt_save_path(ratio)
        if not out_path:
            # el usuario canceló "Guardar como" para este formato; seguimos con los demás
            self._run_next_export()
            return

        self._start_export(ratio, out_path)

    def _prompt_save_path(self, ratio: str) -> str | None:
        """Abre 'Guardar como' en la última carpeta usada (por defecto la
        configurada en Ajustes), con un nombre sugerido, pero deja al
        usuario cambiar libremente carpeta y nombre. Recuerda la carpeta
        elegida para la próxima vez."""
        safe_ratio = ratio.replace(":", "x")
        base_name = Path(self.video_path).stem
        suggested_name = f"{base_name}_momento{self.current_moment_index + 1}_{safe_ratio}.mp4"

        default_dir = Path(self.settings.last_export_dir)
        default_dir.mkdir(parents=True, exist_ok=True)
        suggested_path = str(default_dir / suggested_name)

        out_path, _ = QFileDialog.getSaveFileName(
            self, f"Guardar clip ({ratio})", suggested_path, "Video MP4 (*.mp4)"
        )
        if not out_path:
            return None
        if not out_path.lower().endswith(".mp4"):
            out_path += ".mp4"

        self.settings.last_export_dir = str(Path(out_path).parent)
        self.settings.save()
        return out_path

    def _start_export(self, ratio: str, out_path: str):
        options = ExportOptions(
            aspect_ratio=ratio,
            fps=60,
            normalize_audio=self.chk_normalize.isChecked(),
        )

        self.export_worker = ExportWorker(
            source_video=self.video_path,
            out_path=out_path,
            clip_start=self.trim_start,
            clip_end=self.trim_end,
            options=options,
            src_width=self.video_info.width,
            src_height=self.video_info.height,
            work_dir=self.work_dir,
        )
        self.export_worker.progress.connect(
            lambda stage, frac: (self.export_progress.setValue(int(frac * 100)), self.log_label.setText(stage))
        )
        self.export_worker.finished_ok.connect(self._on_single_export_done)
        self.export_worker.failed.connect(self._on_export_failed)
        self.export_worker.start()

    def _on_single_export_done(self, out_path: str):
        self._exported_count += 1
        self.log_label.setText(f"Exportado: {out_path}")
        self._run_next_export()

    def _on_export_failed(self, error: str):
        self.btn_export.setEnabled(True)
        QMessageBox.critical(self, APP_NAME, f"La exportación falló:\n\n{error}")

    # --------------------------------------------------- Exportación por lotes
    def on_export_selected_clicked(self):
        if not self.selected_moment_indices:
            QMessageBox.warning(self, APP_NAME, "Marca la casilla de al menos un momento antes de exportar.")
            return
        if not self.video_path or not self.video_info or not self.analysis_result:
            return

        aspects = []
        if self.chk_vertical.isChecked():
            aspects.append("9:16")
        if self.chk_horizontal.isChecked():
            aspects.append("16:9")
        if self.chk_square.isChecked():
            aspects.append("1:1")
        if not aspects:
            QMessageBox.warning(self, APP_NAME, "Selecciona al menos un formato de exportación.")
            return

        dest_dir = QFileDialog.getExistingDirectory(
            self, "Carpeta de destino para los clips seleccionados", self.settings.last_export_dir
        )
        if not dest_dir:
            return  # el usuario canceló: no se exporta nada, el estado/selección queda intacto
        self.settings.last_export_dir = dest_dir
        self.settings.save()

        jobs = self._build_batch_jobs(sorted(self.selected_moment_indices), aspects, Path(dest_dir))
        if not jobs:
            return

        self._batch_dest_dir = dest_dir
        self._batch_failed_last = []
        self.btn_export.setEnabled(False)
        self.btn_export_selected.setEnabled(False)
        self.btn_select_all.setEnabled(False)
        self.btn_deselect_all.setEnabled(False)
        self.batch_progress.setVisible(True)
        self.batch_progress.setValue(0)

        self.batch_worker = BatchExportWorker(jobs)
        self.batch_worker.progress.connect(self.on_batch_progress)
        self.batch_worker.finished_all.connect(self.on_batch_finished)
        self.batch_worker.start()

    def _build_batch_jobs(self, indices: list[int], aspects: list[str], dest_dir: Path) -> list[BatchExportJob]:
        """Un job por cada combinación momento x formato. El inicio/fin de
        cada momento se calcula igual que al hacer clic en él individualmente
        (mismo `scoring.compute_clip_window`, misma duración elegida en el
        combo), así no hace falta clickear cada uno para exportarlo bien
        encuadrado."""
        length_sec = int(self.combo_length.currentText())
        video_duration = max(1, int(self.video_info.duration_sec))
        length_sec = max(1, min(length_sec, video_duration))
        base_name = Path(self.video_path).stem

        jobs: list[BatchExportJob] = []
        for idx in indices:
            moment = self.analysis_result.moments[idx]
            start_f, _ = scoring.compute_clip_window(
                moment.peak_time, length_sec, video_duration, self._action_grid, self._action_score
            )
            start = int(round(start_f))
            start = max(0, min(start, video_duration - length_sec))
            end = start + length_sec
            mmss_tag = format_time(start).replace(":", "m") + "s"

            for ratio in aspects:
                safe_ratio = ratio.replace(":", "x")
                filename = f"{base_name}_top{idx + 1:02d}_{mmss_tag}_{safe_ratio}.mp4"
                out_path = unique_path(dest_dir, filename)
                options = ExportOptions(
                    aspect_ratio=ratio, fps=60, normalize_audio=self.chk_normalize.isChecked(),
                )
                jobs.append(BatchExportJob(
                    source_video=self.video_path, out_path=str(out_path),
                    start=float(start), end=float(end), options=options,
                    src_width=self.video_info.width, src_height=self.video_info.height,
                    label=f"Momento #{idx + 1} ({ratio})",
                ))
        return jobs

    def on_batch_progress(self, i: int, total: int, label: str):
        self.batch_progress.setValue(int((i - 1) / total * 100))
        self.log_label.setText(f"Exportando {i} de {total}: {label}")

    def _batch_ui_reset(self):
        self.btn_export.setEnabled(True)
        self.btn_export_selected.setEnabled(len(self.selected_moment_indices) > 0)
        self.btn_select_all.setEnabled(True)
        self.btn_deselect_all.setEnabled(True)
        self.batch_progress.setVisible(False)

    def on_batch_finished(self, results: list):
        self._batch_ui_reset()
        total = len(results)
        ok_results = [r for r in results if r.ok]
        failed_results = [r for r in results if not r.ok]
        dest_dir = getattr(self, "_batch_dest_dir", "")

        self.log_label.setText(
            f"Exportación por lotes: {len(ok_results)}/{total} completados"
            + (f", {len(failed_results)} fallaron." if failed_results else ".")
        )

        if failed_results:
            failed_lines = "\n".join(f"• {r.job.label}: {r.error[:200]}" for r in failed_results)
            QMessageBox.warning(
                self, APP_NAME,
                f"Se exportaron {len(ok_results)} de {total} clips en:\n{dest_dir}\n\n"
                f"Fallaron {len(failed_results)}:\n{failed_lines}"
            )
        else:
            QMessageBox.information(
                self, APP_NAME,
                f"Se exportaron {len(ok_results)} clip(s) en:\n{dest_dir}"
            )
        # el video, los resultados del análisis y la selección de casillas
        # quedan intactos: se puede seguir reproduciendo, ajustando y
        # exportando más sin volver a analizar

    # ------------------------------------------------------------- Proyecto
    def on_save_project(self):
        if not self.video_path or not self.analysis_result:
            QMessageBox.information(self, APP_NAME, "Analiza un video antes de guardar el proyecto.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Guardar proyecto", str(Path.home()), "Proyecto (*.pwproj)")
        if not path:
            return
        data = project_mod.ProjectData(
            video_path=self.video_path,
            video_duration_sec=self.video_info.duration_sec,
            moments=[project_mod.moment_to_dict(m) for m in self.analysis_result.moments],
        )
        project_mod.save_project(data, path)
        QMessageBox.information(self, APP_NAME, "Proyecto guardado.")

    def on_load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Cargar proyecto", str(Path.home()), "Proyecto (*.pwproj)")
        if not path:
            return
        data = project_mod.load_project(path)
        self._load_video(data.video_path)
        QMessageBox.information(
            self, APP_NAME,
            "Proyecto cargado. Vuelve a pulsar 'Analizar' si quieres regenerar los momentos "
            "(guardamos los datos, pero el MVP re-analiza para simplificar; en una fase futura "
            "restauraremos los momentos guardados sin reanalizar)."
        )

    def closeEvent(self, event):
        self.settings.default_clip_length = int(self.combo_length.currentText())
        self.settings.max_moments_per_video = self.spin_max_moments.value()
        self.settings.save()
        super().closeEvent(event)
