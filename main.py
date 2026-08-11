#!/usr/bin/env python3
"""
Puppywill AI Clipper
=====================
Punto de entrada. Ejecuta:  python main.py
"""
import sys
import os

# Asegura que 'app' sea importable tanto en ejecución normal como empaquetada (PyInstaller)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow, APP_NAME

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
