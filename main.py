#!/usr/bin/env python3
"""
Puppywill AI Clipper
=====================
Punto de entrada. Ejecuta:  python main.py

También es el entry point que usa el build empaquetado con PyInstaller
(ver packaging/build_installer.py) - `_base_dir()` resuelve la carpeta
correcta tanto corriendo desde el código fuente como desde el .exe
congelado, para encontrar el ícono de la ventana.
"""
import sys
import os
import traceback

# Asegura que 'app' sea importable tanto en ejecución normal como empaquetada (PyInstaller)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

APP_TITLE = "Puppywill AI Clipper"


def _base_dir() -> str:
    # PyInstaller onedir: los datos empaquetados (--add-data) viven en
    # _internal/, no junto al .exe - sys._MEIPASS apunta ahí (y al
    # directorio de extracción temporal en modo onefile). En modo
    # desarrollo no existe, así que se usa la carpeta del propio main.py.
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def main():
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox
    from app.ui.main_window import MainWindow, APP_NAME

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    icon_path = os.path.join(_base_dir(), "assets", "puppywill_icon.ico")
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    def excepthook(exc_type, exc_value, exc_tb):
        # Un .exe empaquetado no tiene consola donde ver el traceback: sin
        # esto, un error dentro de un slot de Qt mataría la app en
        # silencio. Se muestra en un cuadro de mensaje nativo en su lugar.
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            QMessageBox.critical(None, APP_TITLE, f"Ocurrió un error inesperado:\n\n{exc_type.__name__}: {exc_value}")
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = excepthook

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
