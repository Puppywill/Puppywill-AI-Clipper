#!/usr/bin/env python3
"""
test_i18n.py
------------
Prueba rápida (sin video, sin FFmpeg) de la localización de la
interfaz: que los 3 catálogos (es/en/pt) tengan exactamente las mismas
claves, que el español sea el idioma por defecto, que cambiar de
idioma actualice widgets reales de MainWindow sin reconstruir la
ventana, que las etiquetas fijas (Kill/Multikill/etc.) nunca se
traduzcan, y que la selección de idioma se guarde en los ajustes
persistentes (%LOCALAPPDATA%\\PuppywillAIClipper en Windows).

Necesita PySide6 (a diferencia de test_pipeline.py/test_kill_detection.py/
test_batch_export.py) y corre con QT_QPA_PLATFORM=offscreen para no
necesitar una pantalla real.

Ejecutar con:  python tests/test_i18n.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import i18n  # noqa: E402


def test_catalog_completeness():
    problem = i18n.all_keys_present()
    assert problem is None, f"catálogos de idioma desincronizados: {problem}"
    assert len(i18n._ES) > 50, "el catálogo parece demasiado corto"
    print(f"✅ Los 3 catálogos (es/en/pt) tienen las mismas {len(i18n._ES)} claves")


def test_default_language():
    assert i18n.DEFAULT_LANGUAGE == "es", "el español debe ser el idioma predeterminado"
    assert set(i18n.LANGUAGES.keys()) == {"es", "en", "pt"}
    assert i18n.LANGUAGES["es"] == "Español"
    assert i18n.LANGUAGES["en"] == "English"
    assert i18n.LANGUAGES["pt"] == "Português"
    print("✅ Español es el idioma predeterminado; los 3 idiomas están registrados")


def test_translations_differ():
    sample_keys = ["btn.analyze", "btn.export_selected", "status.video_loaded", "section.moments"]
    seen = {}
    for lang in ("es", "en", "pt"):
        i18n.set_language(lang)
        seen[lang] = [i18n.t(k) for k in sample_keys]
        for text in seen[lang]:
            assert text and not text.startswith("btn.") and not text.startswith("status."), (
                f"clave sin traducir devuelta tal cual en {lang}: {text}"
            )
    assert seen["es"] != seen["en"] != seen["pt"] and seen["es"] != seen["pt"], (
        "los 3 idiomas deberían producir textos distintos para las mismas claves"
    )
    i18n.set_language("es")
    print("✅ Las 3 traducciones producen texto distinto y no dejan claves sin traducir")


def test_format_placeholders():
    for lang in ("es", "en", "pt"):
        i18n.set_language(lang)
        text = i18n.t("status.moments_found", n=7)
        assert "7" in text, f"placeholder {{n}} no se sustituyó en {lang}: {text}"
        text2 = i18n.t("label.partial_selected", n=2, total=5)
        assert "2" in text2 and "5" in text2, f"placeholders no sustituidos en {lang}: {text2}"
    i18n.set_language("es")
    print("✅ Los placeholders ({n}, {total}, ...) se sustituyen igual en los 3 idiomas")


def test_mainwindow_live_switch():
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    from app.core.scoring import Moment

    app = QApplication.instance() or QApplication(sys.argv)
    w = MainWindow()
    assert i18n.current_language() == "es", "MainWindow debe arrancar en español si no hay ajuste previo"
    assert w.btn_analyze.text() == "⚡  Analizar Stream"

    class FakeResult:
        moments = [
            Moment(start=1, end=4, score=70, peak_time=3, reasons=["Kill", "Multikill", "Reaction"]),
            Moment(start=8, end=11, score=50, peak_time=9, reasons=["Generic"]),
        ]
        video_info = None
        action_grid = None
        action_score = None
        from_cache = False

    w.on_analysis_finished(FakeResult())

    for code, expected_analyze in (("en", "⚡  Analyze Stream"), ("pt", "⚡  Analisar Stream"), ("es", "⚡  Analizar Stream")):
        idx = w.combo_language.findData(code)
        assert idx >= 0, f"falta el idioma {code} en el selector"
        w.combo_language.setCurrentIndex(idx)
        assert i18n.current_language() == code
        assert w.btn_analyze.text() == expected_analyze, f"{code}: {w.btn_analyze.text()}"
        assert w.settings.language == code, "el cambio de idioma debe guardarse en los ajustes"
        # las etiquetas fijas nunca se traducen
        assert w._moment_widgets[0].reasons_label.text() == "Kill · Multikill · Reaction", (
            f"{code}: las etiquetas Kill/Multikill/Reaction no deben traducirse: "
            f"{w._moment_widgets[0].reasons_label.text()}"
        )
        # el marcador "Generic" sí se traduce
        generic_text = w._moment_widgets[1].reasons_label.text()
        assert generic_text != "Generic", f"{code}: 'Generic' debería traducirse, no mostrarse literal"

    print("✅ MainWindow cambia de idioma en caliente: botones, ajustes guardados y "
          "etiquetas Kill/Multikill/Reaction sin traducir, 'Generic' sí traducido")


def test_export_dir_not_onedrive():
    from app.config import get_default_export_dir
    d = get_default_export_dir()
    assert "onedrive" not in d.lower(), f"la carpeta de exportación por defecto no debe caer en OneDrive: {d}"
    print(f"✅ Carpeta de exportación por defecto fuera de OneDrive: {d}")


def main():
    test_catalog_completeness()
    test_default_language()
    test_translations_differ()
    test_format_placeholders()
    test_mainwindow_live_switch()
    test_export_dir_not_onedrive()
    print("\n🎉 Todos los tests de idiomas pasaron.")


if __name__ == "__main__":
    main()
