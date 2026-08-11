#!/usr/bin/env python3
"""
run_puppywill.pyw
------------------
Launcher para doble clic (pensado para ejecutarse con pythonw.exe, sin
consola). Verifica FFmpeg y los paquetes de Python necesarios; si falta
algo, muestra un cuadro de mensaje nativo de Windows con el detalle en
vez de fallar en silencio. Si todo está listo, abre la interfaz.
"""
import sys
import os
import glob
import shutil
import importlib.util
import ctypes
import traceback
import datetime

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_DIR)
sys.path.insert(0, PROJECT_DIR)

APP_TITLE = "Puppywill AI Clipper"
MB_ICONERROR = 0x10

# Ubicaciones típicas donde puede haber quedado un ffmpeg.exe instalado pero
# aún no visible en el PATH heredado (p. ej. porque Explorer no recargó el
# PATH justo después de instalarlo). Basadas en variables de entorno, no en
# una ruta de usuario fija, para que funcione en cualquier máquina.
_local_appdata = os.environ.get("LOCALAPPDATA", "")
_program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
FFMPEG_FALLBACK_GLOBS = [
    os.path.join(_local_appdata, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "ffmpeg-*", "bin"),
    os.path.join(_program_files, "ffmpeg", "bin"),
    os.path.join(_program_files, "ffmpeg-*", "bin"),
]

# Log temporal de diagnóstico: solo se escribe si algo falla.
LOG_PATH = os.path.join(PROJECT_DIR, "launcher_error.log")


def log_exception(context, exc_info=None):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n--- {datetime.datetime.now().isoformat()} ({context}) ---\n")
            if exc_info is not None:
                f.write("".join(traceback.format_exception(*exc_info)))
            else:
                f.write(traceback.format_exc())
    except Exception:
        pass  # el log es un extra de diagnóstico, no debe tapar el error original


def show_error(message):
    ctypes.windll.user32.MessageBoxW(0, message, APP_TITLE, MB_ICONERROR)


def qt_excepthook(exc_type, exc_value, exc_tb):
    # Captura errores que ocurren dentro del loop de eventos de Qt
    # (p. ej. en un slot llamado después de que la ventana ya se mostró),
    # que de otro modo pueden matar la app en silencio bajo pythonw.exe.
    log_exception("qt_excepthook", (exc_type, exc_value, exc_tb))
    show_error(
        "Puppywill AI Clipper encontró un error inesperado mientras corría:\n\n"
        f"{exc_type.__name__}: {exc_value}\n\n"
        f"Detalle guardado en:\n{LOG_PATH}"
    )


def ensure_ffmpeg_on_path():
    """Si ffmpeg no está en el PATH heredado, busca en un par de ubicaciones
    típicas de instalación (ver FFMPEG_FALLBACK_GLOBS) y, si lo encuentra,
    lo agrega al PATH de este proceso (y por lo tanto al de los subprocesos
    que la app lance, como ffmpeg mismo)."""
    if shutil.which("ffmpeg") is not None:
        return True
    for pattern in FFMPEG_FALLBACK_GLOBS:
        for bin_dir in glob.glob(pattern):
            if os.path.isfile(os.path.join(bin_dir, "ffmpeg.exe")):
                os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
                return shutil.which("ffmpeg") is not None
    return False


def check_dependencies():
    missing = []

    if sys.version_info < (3, 10):
        missing.append(f"Python {sys.version.split()[0]} es muy antiguo (se requiere 3.10 - 3.12).")

    if not ensure_ffmpeg_on_path():
        missing.append("FFmpeg no está instalado o no se encontró en el PATH.")

    for pkg, import_name in [
        ("PySide6", "PySide6"),
        ("opencv-python", "cv2"),
        ("numpy", "numpy"),
    ]:
        if importlib.util.find_spec(import_name) is None:
            missing.append(f"Falta el paquete de Python '{pkg}'.")

    return missing


def main():
    try:
        missing = check_dependencies()
        if missing:
            detail = "\n".join(f"  •  {m}" for m in missing)
            show_error(
                "No se pudo abrir Puppywill AI Clipper porque falta lo siguiente:\n\n"
                f"{detail}\n\n"
                "Abre una terminal en la carpeta del proyecto y ejecuta:\n"
                "    python setup_check.py\n\n"
                "para ver el diagnóstico completo antes de instalar lo que falte."
            )
            return

        from PySide6.QtWidgets import QApplication
        from app.ui.main_window import MainWindow, APP_NAME

        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME)
        # Cualquier excepción lanzada dentro de un slot/callback de Qt
        # (es decir, después de que la ventana ya se mostró) pasa por aquí
        # en vez de matar el proceso en silencio.
        sys.excepthook = qt_excepthook

        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except SystemExit:
        raise
    except Exception:
        log_exception("main")
        show_error(
            "Puppywill AI Clipper encontró un error inesperado al iniciar:\n\n"
            f"{traceback.format_exc(limit=1)}\n"
            f"Detalle completo guardado en:\n{LOG_PATH}"
        )


if __name__ == "__main__":
    main()
