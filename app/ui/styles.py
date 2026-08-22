"""
styles.py
---------
Hoja de estilos QSS para el tema oscuro de Puppywill AI Clipper:
moderno, minimalista, con acentos morados/dorados.
"""

ACCENT = "#8B5CF6"       # morado (marca)
ACCENT_2 = "#F5B942"     # dorado (highlight de subtítulos / CTA)
BG_DARK = "#0F0F14"
BG_PANEL = "#17171F"
BG_CARD = "#1E1E29"
BORDER = "#2A2A38"
TEXT = "#E8E8F0"
TEXT_DIM = "#8E8EA0"

DARK_QSS = f"""
QWidget {{
    background-color: {BG_DARK};
    color: {TEXT};
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}}

QMainWindow {{
    background-color: {BG_DARK};
}}

#Sidebar {{
    background-color: {BG_PANEL};
    border-right: 1px solid {BORDER};
}}

#BrandLabel {{
    color: {TEXT};
    font-size: 18px;
    font-weight: 800;
    padding: 18px 16px 4px 16px;
}}

#BrandSubLabel {{
    color: {TEXT_DIM};
    font-size: 11px;
    padding: 0px 16px 16px 16px;
}}

QPushButton {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 14px;
    color: {TEXT};
}}
QPushButton:hover {{
    background-color: #26263380;
    border-color: {ACCENT};
}}
QPushButton:pressed {{
    background-color: {ACCENT};
}}
QPushButton:disabled {{
    color: {TEXT_DIM};
    border-color: {BORDER};
}}

QPushButton#PrimaryButton {{
    background-color: {ACCENT};
    border: none;
    color: white;
    font-weight: 600;
}}
QPushButton#PrimaryButton:hover {{
    background-color: #9D6FF5;
}}

QPushButton#DropZone {{
    background-color: {BG_PANEL};
    border: 2px dashed {BORDER};
    border-radius: 14px;
    color: {TEXT_DIM};
    font-size: 15px;
    padding: 60px;
}}
QPushButton#DropZone:hover {{
    border-color: {ACCENT};
    color: {TEXT};
}}

QListWidget {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 6px;
    outline: none;
}}
QListWidget::item {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
    margin: 5px 2px;
}}
QListWidget::item:selected {{
    border-color: {ACCENT};
    background-color: #2A2140;
}}

/* Tarjeta de cada momento (dentro de un QListWidget::item, ver arriba).
   Transparente por defecto - hereda el fondo/borde del item; cuando se
   marca la casilla, se resalta con un tinte y borde dorados (mismo
   acento que ya se usa en el badge de puntuación y las etiquetas),
   distinto del morado que usa el item al hacer clic para previsualizar,
   para no confundir "marcado para exportar" con "en vista previa". */
#MomentCard {{
    background-color: transparent;
    border-radius: 6px;
    border: 1px solid transparent;
}}
#MomentCard[checkedState="true"] {{
    background-color: rgba(245, 185, 66, 0.14);
    border: 1px solid {ACCENT_2};
}}

QCheckBox#MomentCheckbox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 2px solid {BORDER};
    background-color: {BG_DARK};
}}
QCheckBox#MomentCheckbox::indicator:hover {{
    border-color: {ACCENT_2};
}}
QCheckBox#MomentCheckbox::indicator:checked {{
    border-color: {ACCENT_2};
    background-color: {ACCENT_2};
}}

QProgressBar {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    text-align: center;
    color: {TEXT};
    height: 18px;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 6px;
}}

QSlider::groove:horizontal {{
    height: 6px;
    background: {BG_CARD};
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT_2};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}

QComboBox, QLineEdit, QSpinBox, QTextEdit {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px;
    color: {TEXT};
}}
QComboBox:hover, QLineEdit:hover {{
    border-color: {ACCENT};
}}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QTabBar::tab {{
    background: {BG_PANEL};
    padding: 8px 16px;
    color: {TEXT_DIM};
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}
QTabBar::tab:selected {{
    background: {BG_CARD};
    color: {TEXT};
    border-bottom: 2px solid {ACCENT};
}}

QLabel#ScoreBadge {{
    background-color: {ACCENT_2};
    color: #1A1A1A;
    border-radius: 10px;
    padding: 2px 8px;
    font-weight: 700;
}}

QLabel#SectionTitle {{
    color: {TEXT_DIM};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    padding: 10px 0 4px 0;
}}

QCheckBox {{
    spacing: 8px;
}}

QScrollBar:vertical {{
    background: {BG_DARK};
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {ACCENT};
}}
"""
