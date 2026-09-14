"""
main_window.py
---------------
Ventana principal de Puppywill AI Clipper.

Puppywill AI Clipper solo encuentra los mejores momentos (por audio +
video) y los recorta en limpio; la edición final (subtítulos, efectos,
títulos, música) se hace fuera de la app, p.ej. en CapCut. No hay
transcripción ni modelos de lenguaje involucrados.

Interfaz disponible en español/English/português (ver ../i18n.py):
todo el texto se obtiene con `i18n.t("clave")` en vez de estar escrito
literal aquí, y `retranslate_ui()` vuelve a aplicarlo sobre los mismos
widgets cuando el usuario cambia el selector de idioma, sin reiniciar
la app. Los nombres propios (Puppywill AI Clipper, FFmpeg, CapCut...),
los formatos (9:16, 16:9, 1:1) y las etiquetas de calidad de un clip
(Kill, Multikill, Best Play, Reaction, Intense Fight) nunca se traducen.

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
    QGroupBox, QFormLayout, QSpinBox, QLineEdit,
)

try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PySide6.QtMultimediaWidgets import QVideoWidget
    HAVE_MULTIMEDIA = True
except ImportError:
    HAVE_MULTIMEDIA = False

from .. import config
from .. import i18n
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
    score y razones detectadas (audio/movimiento/escena). Suficiente
    alto/espaciado para que nada quede cortado ni amontonado, y un
    resaltado propio (borde+fondo dorado) cuando está marcado con la
    casilla - distinto del resaltado morado que usa la lista al hacer
    clic para previsualizar, para no confundir ambos estados."""

    def __init__(self, moment, index: int, on_toggle=None):
        super().__init__()
        self.moment = moment
        self.index = index
        self.setObjectName("MomentCard")
        self.setMinimumHeight(78)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 12, 10)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        self.checkbox = QCheckBox()
        self.checkbox.setObjectName("MomentCheckbox")
        self.checkbox.setToolTip(i18n.t("tooltip.select_clip"))
        if on_toggle is not None:
            self.checkbox.toggled.connect(self._on_toggled)
            self.checkbox.toggled.connect(lambda checked: on_toggle(index, checked))
        top_row.addWidget(self.checkbox)

        self.time_label = QLabel(f"#{index+1}  {format_time(moment.start)} – {format_time(moment.end)}")
        self.time_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        top_row.addWidget(self.time_label)
        top_row.addStretch()

        score_label = QLabel(f"{moment.score:.0f}")
        score_label.setObjectName("ScoreBadge")
        top_row.addWidget(score_label)
        layout.addLayout(top_row)

        self.reasons_label = QLabel()
        self.reasons_label.setWordWrap(True)
        self.reasons_label.setStyleSheet(f"color: {ACCENT_2}; font-size: 11px; padding-left: 28px;")
        layout.addWidget(self.reasons_label)
        self._render_reasons()

    def _render_reasons(self):
        # "Generic" es el único marcador traducible en moment.reasons; el
        # resto (Kill/Multikill/Best Play/Reaction/Intense Fight) es
        # vocabulario fijo en inglés, se muestra tal cual - ver scoring.py
        parts = [i18n.t("moment.reason_generic") if r == "Generic" else r for r in self.moment.reasons]
        self.reasons_label.setText(" · ".join(parts))

    def retranslate(self):
        self.checkbox.setToolTip(i18n.t("tooltip.select_clip"))
        self._render_reasons()

    def _on_toggled(self, checked: bool):
        # dispara el re-cálculo del QSS con el nuevo valor de la property
        # dinámica "checkedState" (ver #MomentCard[checkedState="true"] en
        # styles.py) - unpolish/polish es lo que Qt requiere para que un
        # cambio de property en tiempo de ejecución se refleje sin reabrir
        # la ventana.
        self.setProperty("checkedState", "true" if checked else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 860)
        self.setAcceptDrops(True)

        self.settings = config.AppSettings.load()
        i18n.set_language(self.settings.language)

        self.video_path: str | None = None
        self.video_info = None
        self.analysis_result = None
        self.displayed_moments: list = []
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
        self._loaded_video_name: str | None = None
        self._status_key = "status.waiting_video"
        self._status_kwargs: dict = {}
        # registro genérico para retraducir en el acto: (widget, método, clave)
        self._i18n_widgets: list[tuple] = []

        self._build_ui()
        self.setStyleSheet(DARK_QSS)

    # -------------------------------------------------------------- i18n
    def _reg(self, widget, key: str, method: str = "setText", **kwargs):
        """Registra `widget` para retraducción automática y le aplica el
        texto ya, en el idioma actual."""
        self._i18n_widgets.append((widget, method, key, kwargs))
        getattr(widget, method)(i18n.t(key, **kwargs))
        return widget

    def retranslate_ui(self):
        for widget, method, key, kwargs in self._i18n_widgets:
            getattr(widget, method)(i18n.t(key, **kwargs))
        self._retranslate_mode_combo()
        self._refresh_dropzone_text()
        self._update_export_selected_button()
        self._set_status(self._status_key, **self._status_kwargs)
        for w in self._moment_widgets:
            w.retranslate()

    def on_language_changed(self, _index: int = -1):
        lang = self.combo_language.currentData()
        if not lang or lang == i18n.current_language():
            return
        i18n.set_language(lang)
        self.settings.language = lang
        self.settings.save()
        self.retranslate_ui()

    def _set_status(self, key: str, **kwargs):
        self._status_key = key
        self._status_kwargs = kwargs
        self.log_label.setText(i18n.t(key, **kwargs))

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
        sub = self._reg(QLabel(), "brand.sub")
        sub.setObjectName("BrandSubLabel")
        lay.addWidget(brand)
        lay.addWidget(sub)

        lay.addWidget(self._section_title("section.project"))
        btn_open = self._reg(QPushButton(), "btn.open_video")
        btn_open.clicked.connect(self.on_open_video)
        lay.addWidget(btn_open)

        btn_load_proj = self._reg(QPushButton(), "btn.load_project")
        btn_load_proj.clicked.connect(self.on_load_project)
        lay.addWidget(btn_load_proj)

        btn_save_proj = self._reg(QPushButton(), "btn.save_project")
        btn_save_proj.clicked.connect(self.on_save_project)
        lay.addWidget(btn_save_proj)

        lay.addWidget(self._section_title("section.analysis"))

        form = QFormLayout()
        self.spin_max_moments = QSpinBox()
        self.spin_max_moments.setRange(3, 40)
        self.spin_max_moments.setValue(self.settings.max_moments_per_video)
        lbl_max_moments = self._reg(QLabel(), "label.max_moments")
        form.addRow(lbl_max_moments, self.spin_max_moments)

        self.combo_mode = QComboBox()
        self.combo_mode.addItem(i18n.t("mode.fast"), FAST_MODE.key)
        self.combo_mode.addItem(i18n.t("mode.precise"), PRECISE_MODE.key)
        self.combo_mode.setCurrentIndex(0)
        self._reg(self.combo_mode, "tooltip.speed_mode", method="setToolTip")
        lbl_speed_mode = self._reg(QLabel(), "label.speed_mode")
        form.addRow(lbl_speed_mode, self.combo_mode)

        # Modo de detección (General/Gaming) - independiente de Rápido/Preciso
        # arriba (eso es velocidad de muestreo, esto es QUÉ se detecta).
        self.combo_detection_mode = QComboBox()
        self.combo_detection_mode.addItem(i18n.t("mode.general"), "general")
        self.combo_detection_mode.addItem(i18n.t("mode.gaming"), "gaming")
        self.combo_detection_mode.setCurrentIndex(0)
        self._reg(self.combo_detection_mode, "tooltip.detection_mode", method="setToolTip")
        self.combo_detection_mode.currentIndexChanged.connect(self.on_detection_mode_changed)
        lbl_detection_mode = self._reg(QLabel(), "label.mode")
        form.addRow(lbl_detection_mode, self.combo_detection_mode)

        # Solo visibles con Gaming - ver on_detection_mode_changed()
        self.combo_game = QComboBox()
        self.combo_game.addItem(i18n.t("game.auto"), "auto")
        self.combo_game.addItem(i18n.t("game.marvel_rivals"), "marvel_rivals")
        self.combo_game.addItem(i18n.t("game.other"), "other")
        self.combo_game.setCurrentIndex(0)
        self.lbl_game = self._reg(QLabel(), "label.game")
        form.addRow(self.lbl_game, self.combo_game)

        self.edit_find_specific = QLineEdit()
        self._reg(self.edit_find_specific, "placeholder.find_specific", method="setPlaceholderText")
        self._reg(self.edit_find_specific, "tooltip.find_specific", method="setToolTip")
        self.lbl_find_specific = self._reg(QLabel(), "label.find_specific")
        form.addRow(self.lbl_find_specific, self.edit_find_specific)

        lay.addLayout(form)
        self._update_gaming_controls_visibility()

        # "Idioma / Language" queda igual en los 3 idiomas a propósito
        # (es el propio selector de idioma, debe ser autoexplicativo sin
        # importar cuál esté activo).
        lang_form = QFormLayout()
        lbl_language = QLabel("Idioma / Language")
        self.combo_language = QComboBox()
        for code, native_name in i18n.LANGUAGES.items():
            self.combo_language.addItem(native_name, code)
        idx = self.combo_language.findData(self.settings.language)
        self.combo_language.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_language.currentIndexChanged.connect(self.on_language_changed)
        lang_form.addRow(lbl_language, self.combo_language)
        lay.addLayout(lang_form)

        self.btn_analyze = self._reg(QPushButton(), "btn.analyze")
        self.btn_analyze.setObjectName("PrimaryButton")
        self.btn_analyze.setEnabled(False)
        self.btn_analyze.clicked.connect(self.on_analyze_clicked)
        lay.addWidget(self.btn_analyze)

        self.btn_cancel_analysis = self._reg(QPushButton(), "btn.cancel_analysis")
        self.btn_cancel_analysis.setVisible(False)
        self.btn_cancel_analysis.clicked.connect(self.on_cancel_analysis_clicked)
        lay.addWidget(self.btn_cancel_analysis)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        lay.addWidget(self.progress_bar)

        self.log_label = QLabel(i18n.t(self._status_key))
        self.log_label.setWordWrap(True)
        self.log_label.setStyleSheet("color: #8E8EA0; font-size: 11px; padding: 4px 4px;")
        lay.addWidget(self.log_label)

        lay.addStretch()

        gpu_note = self._reg(QLabel(), "label.gpu_note")
        gpu_note.setStyleSheet("color: #6E6E80; font-size: 10px; padding: 8px;")
        gpu_note.setWordWrap(True)
        lay.addWidget(gpu_note)

        return sidebar

    def _retranslate_mode_combo(self):
        self.combo_mode.blockSignals(True)
        self.combo_mode.setItemText(0, i18n.t("mode.fast"))
        self.combo_mode.setItemText(1, i18n.t("mode.precise"))
        self.combo_mode.blockSignals(False)

        self.combo_detection_mode.blockSignals(True)
        self.combo_detection_mode.setItemText(0, i18n.t("mode.general"))
        self.combo_detection_mode.setItemText(1, i18n.t("mode.gaming"))
        self.combo_detection_mode.blockSignals(False)

        self.combo_game.blockSignals(True)
        self.combo_game.setItemText(0, i18n.t("game.auto"))
        self.combo_game.setItemText(1, i18n.t("game.marvel_rivals"))
        self.combo_game.setItemText(2, i18n.t("game.other"))
        self.combo_game.blockSignals(False)

    def on_detection_mode_changed(self, _index: int = -1):
        self._update_gaming_controls_visibility()

    def _update_gaming_controls_visibility(self):
        is_gaming = self.combo_detection_mode.currentData() == "gaming"
        self.lbl_game.setVisible(is_gaming)
        self.combo_game.setVisible(is_gaming)
        self.lbl_find_specific.setVisible(is_gaming)
        self.edit_find_specific.setVisible(is_gaming)

    def _section_title(self, key: str) -> QLabel:
        lbl = self._reg(QLabel(), key)
        lbl.setObjectName("SectionTitle")
        lbl.setContentsMargins(16, 0, 16, 0)
        return lbl

    def _build_center_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 16, 16, 16)

        self.drop_zone = QPushButton()
        self.drop_zone.setObjectName("DropZone")
        self.drop_zone.clicked.connect(self.on_open_video)
        self._refresh_dropzone_text()
        lay.addWidget(self.drop_zone)

        self.video_info_label = QLabel("")
        self.video_info_label.setStyleSheet("color: #8E8EA0; font-size: 12px;")
        lay.addWidget(self.video_info_label)

        header_row = QHBoxLayout()
        header_row.addWidget(self._section_title("section.moments"))
        header_row.addStretch()
        self.selection_count_label = self._reg(QLabel(), "label.no_selection")
        self.selection_count_label.setStyleSheet(
            "color: #8E8EA0; font-size: 11px; padding: 10px 4px 4px 4px;"
        )
        header_row.addWidget(self.selection_count_label)
        lay.addLayout(header_row)

        self.moment_list = QListWidget()
        self.moment_list.itemClicked.connect(self.on_moment_selected)
        lay.addWidget(self.moment_list, 1)

        selection_row = QHBoxLayout()
        selection_row.setSpacing(8)
        self.btn_select_all = self._reg(QPushButton(), "btn.select_all")
        self.btn_deselect_all = self._reg(QPushButton(), "btn.deselect_all")
        self.btn_select_all.clicked.connect(self.on_select_all_clicked)
        self.btn_deselect_all.clicked.connect(self.on_deselect_all_clicked)
        selection_row.addWidget(self.btn_select_all, 1)
        selection_row.addWidget(self.btn_deselect_all, 1)
        lay.addLayout(selection_row)

        self.btn_export_selected = QPushButton(i18n.t("btn.export_selected"))
        self.btn_export_selected.setObjectName("PrimaryButton")
        self.btn_export_selected.setEnabled(False)
        self.btn_export_selected.clicked.connect(self.on_export_selected_clicked)
        lay.addWidget(self.btn_export_selected)

        self.batch_progress = QProgressBar()
        self.batch_progress.setVisible(False)
        lay.addWidget(self.batch_progress)

        return panel

    def _refresh_dropzone_text(self):
        if self._loaded_video_name:
            self.drop_zone.setText(i18n.t("dropzone.loaded", name=self._loaded_video_name))
        else:
            self.drop_zone.setText(i18n.t("dropzone.default"))

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 16, 16, 16)

        lay.addWidget(self._section_title("section.preview"))

        if HAVE_MULTIMEDIA:
            self.video_widget = QVideoWidget()
            self.video_widget.setMinimumHeight(260)
            self.media_player = QMediaPlayer()
            self.audio_output = QAudioOutput()
            self.media_player.setAudioOutput(self.audio_output)
            self.media_player.setVideoOutput(self.video_widget)
            lay.addWidget(self.video_widget)
        else:
            self.video_widget = self._reg(QLabel(), "label.no_preview")
            self.video_widget.setAlignment(Qt.AlignCenter)
            self.video_widget.setMinimumHeight(200)
            lay.addWidget(self.video_widget)

        preview_controls = QHBoxLayout()
        self.btn_play = self._reg(QPushButton(), "btn.play")
        self.btn_play.clicked.connect(self.on_play_moment)
        self.btn_stop = QPushButton("⏹")
        self.btn_stop.clicked.connect(self.on_stop_preview)
        preview_controls.addWidget(self.btn_play)
        preview_controls.addWidget(self.btn_stop)
        lay.addLayout(preview_controls)

        lay.addWidget(self._section_title("section.trim"))
        self.slider_start = QSlider(Qt.Horizontal)
        self.slider_end = QSlider(Qt.Horizontal)
        self.label_trim = QLabel("00:00 – 00:00")
        for s in (self.slider_start, self.slider_end):
            s.valueChanged.connect(self.on_trim_changed)
        lay.addWidget(self._reg(QLabel(), "label.start"))
        lay.addWidget(self.slider_start)
        lay.addWidget(self._reg(QLabel(), "label.end"))
        lay.addWidget(self.slider_end)
        lay.addWidget(self.label_trim)

        lay.addWidget(self._section_title("section.export"))
        export_box = QGroupBox()
        export_form = QFormLayout(export_box)

        self.combo_length = QComboBox()
        self.combo_length.addItems(["15", "30", "45", "60"])
        self.combo_length.setCurrentText(str(self.settings.default_clip_length))
        self.combo_length.currentTextChanged.connect(self.on_length_changed)
        lbl_duration = self._reg(QLabel(), "label.duration")
        export_form.addRow(lbl_duration, self.combo_length)

        self.chk_vertical = self._reg(QCheckBox(), "chk.vertical")
        self.chk_horizontal = self._reg(QCheckBox(), "chk.horizontal")
        self.chk_square = self._reg(QCheckBox(), "chk.square")
        self.chk_vertical.setChecked(True)
        export_form.addRow(self.chk_vertical)
        export_form.addRow(self.chk_horizontal)
        export_form.addRow(self.chk_square)

        self.chk_normalize = self._reg(QCheckBox(), "chk.normalize")
        self.chk_normalize.setChecked(True)
        export_form.addRow(self.chk_normalize)

        lay.addWidget(export_box)

        self.btn_export = self._reg(QPushButton(), "btn.export_clip")
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
            QMessageBox.warning(self, APP_NAME, i18n.t("warn.unsupported_format"))

    # ------------------------------------------------------------- Acciones
    def on_open_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("dialog.select_recording"), str(Path.home()),
            i18n.t("filter.videos")
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
        self._loaded_video_name = Path(path).name
        self._refresh_dropzone_text()
        self.btn_analyze.setEnabled(True)
        self.moment_list.clear()
        self._set_status("status.video_loaded")

        if HAVE_MULTIMEDIA:
            self.media_player.setSource(QUrl.fromLocalFile(path))

    def on_analyze_clicked(self):
        if not self.video_path:
            return
        self.btn_analyze.setEnabled(False)
        self.btn_cancel_analysis.setVisible(True)
        self.progress_bar.setValue(0)
        self._analysis_start_time = time.monotonic()

        mode = MODES.get(self.combo_mode.currentData(), FAST_MODE)
        detection_mode = self.combo_detection_mode.currentData() or "general"
        game_key = self.combo_game.currentData() if detection_mode == "gaming" else "auto"
        self.worker = AnalysisWorker(
            video_path=self.video_path,
            work_dir=self.work_dir,
            clip_len_options=(15, 30, 45, 60),
            max_moments=self.spin_max_moments.value(),
            mode=mode,
            detection_mode=detection_mode,
            game_key=game_key or "auto",
        )
        self.worker.progress.connect(self.on_analysis_progress)
        self.worker.finished_ok.connect(self.on_analysis_finished)
        self.worker.failed.connect(self.on_analysis_failed)
        self.worker.cancelled.connect(self.on_analysis_cancelled)
        self.worker.start()

    def on_cancel_analysis_clicked(self):
        if hasattr(self, "worker") and self.worker.isRunning():
            self.btn_cancel_analysis.setEnabled(False)
            self._set_status("status.cancelling")
            self.worker.request_cancel()

    def on_analysis_progress(self, stage_key: str, frac: float):
        self.progress_bar.setValue(int(frac * 100))
        elapsed = time.monotonic() - self._analysis_start_time
        if 0.03 < frac < 0.995 and elapsed > 1.0:
            remaining = elapsed * (1.0 - frac) / frac
            eta_text = i18n.t("eta.remaining", t=format_time(max(0.0, remaining)))
        else:
            eta_text = ""
        self.log_label.setText(f"{i18n.t(stage_key)}{eta_text}")
        self._status_key, self._status_kwargs = stage_key, {}

    def _analysis_ui_reset(self):
        self.btn_analyze.setEnabled(True)
        self.btn_cancel_analysis.setVisible(False)
        self.btn_cancel_analysis.setEnabled(True)

    def _filter_moments_by_query(self, moments: list, query: str) -> list:
        """v1 sin NLP: filtro simple de palabras clave contra las etiquetas
        (`reasons`) ya asignadas a cada momento - no interpreta lenguaje
        natural. Si el filtro no deja nada (p.ej. la query no coincide con
        ningún tag conocido), se muestran todos los momentos igual, para no
        dejar al usuario con la lista vacía por una consulta demasiado
        específica."""
        keywords = [w for w in query.lower().split() if len(w) >= 3]
        if not keywords:
            return moments
        filtered = [
            m for m in moments
            if any(
                kw in reason.lower() or reason.lower() in kw
                for reason in m.reasons for kw in keywords
            )
        ]
        return filtered if filtered else moments

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
        moments = result.moments
        if self.combo_detection_mode.currentData() == "gaming":
            query = self.edit_find_specific.text().strip()
            if query:
                moments = self._filter_moments_by_query(moments, query)
        for i, m in enumerate(moments):
            item = QListWidgetItem()
            widget = MomentListItemWidget(m, i, on_toggle=self._on_moment_checkbox_toggled)
            item.setSizeHint(widget.sizeHint())
            self.moment_list.addItem(item)
            self.moment_list.setItemWidget(item, widget)
            self._moment_widgets.append(widget)
        self.displayed_moments = moments
        self._update_export_selected_button()
        status_key = "status.moments_found_cached" if getattr(result, "from_cache", False) else "status.moments_found"
        self._set_status(status_key, n=len(moments))
        if not moments:
            QMessageBox.information(self, APP_NAME, i18n.t("status.no_moments_found"))

    def on_analysis_failed(self, error: str):
        self._analysis_ui_reset()
        self._set_status("status.analysis_error")
        QMessageBox.critical(self, APP_NAME, i18n.t("error.analysis_failed", error=error))

    def on_analysis_cancelled(self):
        self._analysis_ui_reset()
        self.progress_bar.setValue(0)
        self._set_status("status.analysis_cancelled")

    # -------------------------------------------------- Selección múltiple
    def _on_moment_checkbox_toggled(self, index: int, checked: bool):
        if checked:
            self.selected_moment_indices.add(index)
        else:
            self.selected_moment_indices.discard(index)
        self._update_export_selected_button()

    def _update_export_selected_button(self):
        n = len(self.selected_moment_indices)
        self.btn_export_selected.setText(i18n.t("btn.export_selected_n", n=n) if n else i18n.t("btn.export_selected"))
        self.btn_export_selected.setEnabled(n > 0)
        total = len(self._moment_widgets)
        if n == 0:
            self.selection_count_label.setText(i18n.t("label.no_selection"))
        elif n == total:
            self.selection_count_label.setText(i18n.t("label.all_selected", n=n))
        else:
            self.selection_count_label.setText(i18n.t("label.partial_selected", n=n, total=total))

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
        moment = self.displayed_moments[index]

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
            QMessageBox.warning(self, APP_NAME, i18n.t("warn.select_moment_first"))
            return

        aspects = []
        if self.chk_vertical.isChecked():
            aspects.append("9:16")
        if self.chk_horizontal.isChecked():
            aspects.append("16:9")
        if self.chk_square.isChecked():
            aspects.append("1:1")
        if not aspects:
            QMessageBox.warning(self, APP_NAME, i18n.t("warn.select_format"))
            return

        self._export_queue = aspects
        self._exported_count = 0
        self.btn_export.setEnabled(False)
        self._run_next_export()

    def _run_next_export(self):
        if not self._export_queue:
            self.btn_export.setEnabled(True)
            if self._exported_count > 0:
                QMessageBox.information(self, APP_NAME, i18n.t("info.export_complete"))
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
            self, i18n.t("dialog.save_clip", ratio=ratio), suggested_path, i18n.t("filter.mp4")
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
            lambda stage_key, frac: (self.export_progress.setValue(int(frac * 100)), self._set_status(stage_key))
        )
        self.export_worker.finished_ok.connect(self._on_single_export_done)
        self.export_worker.failed.connect(self._on_export_failed)
        self.export_worker.start()

    def _on_single_export_done(self, out_path: str):
        self._exported_count += 1
        self._set_status("status.exported", path=out_path)
        self._run_next_export()

    def _on_export_failed(self, error: str):
        self.btn_export.setEnabled(True)
        QMessageBox.critical(self, APP_NAME, i18n.t("error.export_failed", error=error))

    # --------------------------------------------------- Exportación por lotes
    def on_export_selected_clicked(self):
        if not self.selected_moment_indices:
            QMessageBox.warning(self, APP_NAME, i18n.t("warn.select_at_least_one_moment"))
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
            QMessageBox.warning(self, APP_NAME, i18n.t("warn.select_format"))
            return

        dest_dir = QFileDialog.getExistingDirectory(
            self, i18n.t("dialog.batch_dest_folder"), self.settings.last_export_dir
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
            moment = self.displayed_moments[idx]
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
                    label=i18n.t("moment.label", n=idx + 1, ratio=ratio),
                ))
        return jobs

    def on_batch_progress(self, i: int, total: int, label: str):
        self.batch_progress.setValue(int((i - 1) / total * 100))
        self._set_status("status.exporting_n_of_m", i=i, total=total, label=label)

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

        if failed_results:
            self._set_status("status.batch_done_with_fails", ok=len(ok_results), total=total, failed=len(failed_results))
        else:
            self._set_status("status.batch_done", ok=len(ok_results), total=total)

        if failed_results:
            failed_lines = "\n".join(f"• {r.job.label}: {r.error[:200]}" for r in failed_results)
            QMessageBox.warning(
                self, APP_NAME,
                i18n.t("msg.batch_warning_body", ok=len(ok_results), total=total, dest=dest_dir,
                       failed=len(failed_results), lines=failed_lines)
            )
        else:
            QMessageBox.information(
                self, APP_NAME,
                i18n.t("msg.batch_info_body", ok=len(ok_results), total=total, dest=dest_dir)
            )
        # el video, los resultados del análisis y la selección de casillas
        # quedan intactos: se puede seguir reproduciendo, ajustando y
        # exportando más sin volver a analizar

    # ------------------------------------------------------------- Proyecto
    def on_save_project(self):
        if not self.video_path or not self.analysis_result:
            QMessageBox.information(self, APP_NAME, i18n.t("info.analyze_before_save"))
            return
        path, _ = QFileDialog.getSaveFileName(self, i18n.t("dialog.save_project"), str(Path.home()), i18n.t("filter.project"))
        if not path:
            return
        data = project_mod.ProjectData(
            video_path=self.video_path,
            video_duration_sec=self.video_info.duration_sec,
            moments=[project_mod.moment_to_dict(m) for m in self.displayed_moments],
        )
        project_mod.save_project(data, path)
        QMessageBox.information(self, APP_NAME, i18n.t("info.project_saved"))

    def on_load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, i18n.t("dialog.load_project"), str(Path.home()), i18n.t("filter.project"))
        if not path:
            return
        data = project_mod.load_project(path)
        self._load_video(data.video_path)
        QMessageBox.information(self, APP_NAME, i18n.t("info.project_loaded"))

    def closeEvent(self, event):
        self.settings.default_clip_length = int(self.combo_length.currentText())
        self.settings.max_moments_per_video = self.spin_max_moments.value()
        self.settings.save()
        super().closeEvent(event)
