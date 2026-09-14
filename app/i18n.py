"""
i18n.py
-------
Catálogo de traducciones de la interfaz (Español/English/Português) y el
estado del idioma actual. Es deliberadamente un diccionario propio, no
el sistema de traducción nativo de Qt (QTranslator/.ts/.qm): para una
interfaz construida a mano como esta (sin archivos .ui de Qt Designer),
ambos enfoques requieren re-aplicar el texto a cada widget a mano al
cambiar de idioma, así que un diccionario propio evita depender de las
herramientas de compilación de Qt Linguist (lupdate/lrelease) sin
perder nada.

Uso:
    from .. import i18n
    i18n.set_language("en")     # cambia el idioma actual
    texto = i18n.t("btn.analyze")
    texto_con_datos = i18n.t("status.moments_found", n=5)

Los nombres propios (Puppywill AI Clipper, FFmpeg, GPU, NVDEC, NVENC,
CapCut, Tesseract OCR), los formatos (9:16, 16:9, 1:1, MP4/MKV/MOV) y
las etiquetas de calidad de un clip (Kill, Multikill, Killstreak,
Ultimate, Round End, Best Play, Reaction, Intense Fight - vocabulario
fijo elegido a propósito en inglés) NUNCA se traducen: no tienen
entradas en este catálogo, se usan literales donde aparecen. Lo mismo
aplica a "General"/"Gaming" (el selector de modo de detección) y a
"Marvel Rivals" (nombre del juego), que sí tienen entrada en el
catálogo pero con el mismo texto en los 3 idiomas a propósito.
"""
from __future__ import annotations

from typing import Callable, Optional

LANGUAGES: dict[str, str] = {
    "es": "Español",
    "en": "English",
    "pt": "Português",
}
DEFAULT_LANGUAGE = "es"

_current_language = DEFAULT_LANGUAGE
_listeners: list[Callable[[str], None]] = []


def set_language(lang: str) -> None:
    """Cambia el idioma actual y avisa a quien se haya suscrito con
    `on_change` (la ventana principal, para re-aplicar los textos sin
    reiniciar la app)."""
    global _current_language
    if lang not in LANGUAGES:
        lang = DEFAULT_LANGUAGE
    if lang == _current_language:
        return
    _current_language = lang
    for cb in list(_listeners):
        cb(lang)


def current_language() -> str:
    return _current_language


def on_change(callback: Callable[[str], None]) -> None:
    """Registra `callback(lang)` para que se llame cada vez que cambie
    el idioma (además de la llamada explícita a `set_language`)."""
    _listeners.append(callback)


def t(key: str, **kwargs) -> str:
    """Traduce `key` al idioma actual. Si la clave no existe en el
    idioma actual o en absoluto, devuelve la propia clave (nunca lanza:
    un texto sin traducir en pantalla es preferible a un crash)."""
    catalog = _CATALOG.get(_current_language) or _CATALOG[DEFAULT_LANGUAGE]
    template = catalog.get(key) or _CATALOG[DEFAULT_LANGUAGE].get(key) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except Exception:
            return template
    return template


_ES: dict[str, str] = {
    "brand.sub": "AI Clipper",
    "section.project": "PROYECTO",
    "section.analysis": "ANÁLISIS",
    "section.moments": "MEJORES MOMENTOS DETECTADOS",
    "section.preview": "VISTA PREVIA",
    "section.trim": "AJUSTE MANUAL DE INICIO/FIN",
    "section.export": "EXPORTACIÓN",

    "btn.open_video": "📂  Abrir video…",
    "btn.load_project": "📁  Cargar proyecto…",
    "btn.save_project": "💾  Guardar proyecto",

    "label.max_moments": "Máx. momentos:",
    "label.mode": "Modo:",
    "label.language": "Idioma / Language",
    "tooltip.detection_mode": (
        "General: detecta picos de audio, risas, movimiento y cortes de escena.\n"
        "Gaming: además detecta kills, ultimates, rachas y fin de ronda en videojuegos."
    ),
    "mode.general": "General",
    "mode.gaming": "Gaming",

    "label.speed_mode": "Velocidad:",
    "tooltip.speed_mode": (
        "Rápido: decodificación GPU + menos muestras/candidatos OCR - recomendado.\n"
        "Preciso: más muestras por segundo y más candidatos OCR, más lento."
    ),
    "mode.fast": "Rápido",
    "mode.precise": "Preciso",

    "label.game": "Juego:",
    "game.auto": "Detectar automáticamente",
    "game.marvel_rivals": "Marvel Rivals",
    "game.other": "Otro",

    "label.find_specific": "Buscar momentos específicos (opcional):",
    "placeholder.find_specific": "Ej: mis mejores kills jugando Capitán América",
    "tooltip.find_specific": (
        "Filtra los momentos ya detectados por palabras clave (kills, ultimate, "
        "victory...). No es comprensión de lenguaje natural."
    ),

    "btn.analyze": "⚡  Analizar Stream",
    "btn.cancel_analysis": "✕  Cancelar análisis",
    "status.waiting_video": "Esperando video…",
    "label.gpu_note": "GPU: se detecta automáticamente\n(NVDEC decode + NVENC export si están disponibles)",

    "dropzone.default": "Arrastra aquí tu grabación (MP4 / MKV / MOV)\nde 3+ horas, o haz clic para seleccionar",
    "dropzone.loaded": "✅ Cargado: {name}\n(Haz clic para elegir otro video)",

    "label.no_selection": "Ningún clip seleccionado",
    "label.all_selected": "Los {n} clips seleccionados",
    "label.partial_selected": "{n} de {total} clips seleccionados",
    "btn.select_all": "☑  Seleccionar todos",
    "btn.deselect_all": "☐  Deseleccionar todos",
    "btn.export_selected": "⬇  Exportar seleccionados",
    "btn.export_selected_n": "⬇  Exportar seleccionados ({n})",

    "label.no_preview": "Vista previa no disponible\n(instala PySide6-Addons con QtMultimedia)",
    "btn.play": "▶ Reproducir momento",
    "label.start": "Inicio:",
    "label.end": "Fin:",

    "label.duration": "Duración (s):",
    "chk.vertical": "Vertical 9:16 (TikTok/Reels/Shorts)",
    "chk.horizontal": "Horizontal 16:9 (YouTube)",
    "chk.square": "Cuadrado 1:1 (Feed)",
    "chk.normalize": "Normalizar audio",
    "btn.export_clip": "⬇  Exportar Clip",

    "warn.unsupported_format": "Formato no soportado. Usa MP4, MKV o MOV.",
    "dialog.select_recording": "Selecciona una grabación",
    "filter.videos": "Videos (*.mp4 *.mkv *.mov)",
    "status.video_loaded": "Video cargado. Listo para analizar.",
    "status.cancelling": "Cancelando… (esperando a que FFmpeg termine el frame actual)",
    "eta.remaining": "  —  ~{t} restantes",
    "status.no_moments_found": "No se encontraron momentos destacados claros. Prueba bajando el umbral o revisando el audio del video.",
    "status.analysis_error": "Error en el análisis.",
    "error.analysis_failed": "El análisis falló:\n\n{error}",
    "status.analysis_cancelled": "Análisis cancelado.",
    "status.moments_found": "{n} momentos encontrados.",
    "status.moments_found_cached": "{n} momentos encontrados (cargado desde caché).",

    "warn.select_moment_first": "Selecciona un momento de la lista antes de exportar.",
    "warn.select_format": "Selecciona al menos un formato de exportación.",
    "info.export_complete": "Exportación completa. Revisa tu carpeta de clips.",
    "dialog.save_clip": "Guardar clip ({ratio})",
    "filter.mp4": "Video MP4 (*.mp4)",
    "status.exported": "Exportado: {path}",
    "error.export_failed": "La exportación falló:\n\n{error}",

    "warn.select_at_least_one_moment": "Marca la casilla de al menos un momento antes de exportar.",
    "dialog.batch_dest_folder": "Carpeta de destino para los clips seleccionados",
    "status.exporting_n_of_m": "Exportando {i} de {total}: {label}",
    "status.batch_done": "{ok} de {total} clips exportados correctamente.",
    "status.batch_done_with_fails": "{ok} de {total} clips exportados correctamente ({failed} fallaron).",
    "msg.batch_warning_body": "{ok} de {total} clips exportados correctamente en:\n{dest}\n\nFallaron {failed}:\n{lines}",
    "msg.batch_info_body": "{ok} de {total} clips exportados correctamente en:\n{dest}",

    "info.analyze_before_save": "Analiza un video antes de guardar el proyecto.",
    "dialog.save_project": "Guardar proyecto",
    "filter.project": "Proyecto (*.pwproj)",
    "info.project_saved": "Proyecto guardado.",
    "dialog.load_project": "Cargar proyecto",
    "info.project_loaded": (
        "Proyecto cargado. Vuelve a pulsar 'Analizar' si quieres regenerar los momentos "
        "(guardamos los datos, pero el MVP re-analiza para simplificar; en una fase futura "
        "restauraremos los momentos guardados sin reanalizar)."
    ),

    "moment.reason_generic": "Combinación moderada de señales",
    "moment.label": "Momento #{n} ({ratio})",
    "tooltip.select_clip": "Seleccionar para exportar junto a otros momentos marcados",

    "stage.validating": "Validando video",
    "stage.loaded_from_cache": "Cargado desde caché (mismo video y ajustes ya analizados)",
    "stage.extract_analyze": "Extrayendo y analizando audio + video",
    "stage.analyzing_av": "Analizando audio y video (GPU si está disponible)",
    "stage.detecting_kills": "Detectando kills",
    "stage.scoring": "Calculando puntuación combinada",
    "stage.selecting_moments": "Seleccionando mejores momentos",
    "stage.complete": "Análisis completo",
    "stage.exporting_ffmpeg": "Exportando clip con FFmpeg",
    "stage.export_complete": "Completado",

    "error.unexpected": "Ocurrió un error inesperado:\n\n{type}: {value}",
}

_EN: dict[str, str] = {
    "brand.sub": "AI Clipper",
    "section.project": "PROJECT",
    "section.analysis": "ANALYSIS",
    "section.moments": "BEST MOMENTS DETECTED",
    "section.preview": "PREVIEW",
    "section.trim": "MANUAL START/END ADJUSTMENT",
    "section.export": "EXPORT",

    "btn.open_video": "📂  Open video…",
    "btn.load_project": "📁  Load project…",
    "btn.save_project": "💾  Save project",

    "label.max_moments": "Max. moments:",
    "label.mode": "Mode:",
    "label.language": "Idioma / Language",
    "tooltip.detection_mode": (
        "General: detects audio peaks, laughter, motion and scene cuts.\n"
        "Gaming: also detects kills, ultimates, streaks and round endings in games."
    ),
    "mode.general": "General",
    "mode.gaming": "Gaming",

    "label.speed_mode": "Speed:",
    "tooltip.speed_mode": (
        "Fast: GPU decoding + fewer samples/OCR candidates - recommended.\n"
        "Precise: more samples per second and more OCR candidates, slower."
    ),
    "mode.fast": "Fast",
    "mode.precise": "Precise",

    "label.game": "Game:",
    "game.auto": "Auto Detect",
    "game.marvel_rivals": "Marvel Rivals",
    "game.other": "Other",

    "label.find_specific": "Find specific moments (optional):",
    "placeholder.find_specific": "E.g: my best kills while playing Captain America",
    "tooltip.find_specific": (
        "Filters already-detected moments by keyword (kills, ultimate, victory...). "
        "Not full natural-language understanding."
    ),

    "btn.analyze": "⚡  Analyze Stream",
    "btn.cancel_analysis": "✕  Cancel analysis",
    "status.waiting_video": "Waiting for video…",
    "label.gpu_note": "GPU: detected automatically\n(NVDEC decode + NVENC export when available)",

    "dropzone.default": "Drag your recording here (MP4 / MKV / MOV)\n3+ hours long, or click to select",
    "dropzone.loaded": "✅ Loaded: {name}\n(Click to choose another video)",

    "label.no_selection": "No clip selected",
    "label.all_selected": "All {n} clips selected",
    "label.partial_selected": "{n} of {total} clips selected",
    "btn.select_all": "☑  Select all",
    "btn.deselect_all": "☐  Deselect all",
    "btn.export_selected": "⬇  Export selected",
    "btn.export_selected_n": "⬇  Export selected ({n})",

    "label.no_preview": "Preview not available\n(install PySide6-Addons with QtMultimedia)",
    "btn.play": "▶ Play moment",
    "label.start": "Start:",
    "label.end": "End:",

    "label.duration": "Duration (s):",
    "chk.vertical": "Vertical 9:16 (TikTok/Reels/Shorts)",
    "chk.horizontal": "Horizontal 16:9 (YouTube)",
    "chk.square": "Square 1:1 (Feed)",
    "chk.normalize": "Normalize audio",
    "btn.export_clip": "⬇  Export Clip",

    "warn.unsupported_format": "Unsupported format. Use MP4, MKV or MOV.",
    "dialog.select_recording": "Select a recording",
    "filter.videos": "Videos (*.mp4 *.mkv *.mov)",
    "status.video_loaded": "Video loaded. Ready to analyze.",
    "status.cancelling": "Cancelling… (waiting for FFmpeg to finish the current frame)",
    "eta.remaining": "  —  ~{t} remaining",
    "status.no_moments_found": "No clear standout moments were found. Try lowering the threshold or checking the video's audio.",
    "status.analysis_error": "Analysis error.",
    "error.analysis_failed": "Analysis failed:\n\n{error}",
    "status.analysis_cancelled": "Analysis cancelled.",
    "status.moments_found": "{n} moments found.",
    "status.moments_found_cached": "{n} moments found (loaded from cache).",

    "warn.select_moment_first": "Select a moment from the list before exporting.",
    "warn.select_format": "Select at least one export format.",
    "info.export_complete": "Export complete. Check your clips folder.",
    "dialog.save_clip": "Save clip ({ratio})",
    "filter.mp4": "MP4 Video (*.mp4)",
    "status.exported": "Exported: {path}",
    "error.export_failed": "Export failed:\n\n{error}",

    "warn.select_at_least_one_moment": "Check the box on at least one moment before exporting.",
    "dialog.batch_dest_folder": "Destination folder for the selected clips",
    "status.exporting_n_of_m": "Exporting {i} of {total}: {label}",
    "status.batch_done": "{ok} of {total} clips exported successfully.",
    "status.batch_done_with_fails": "{ok} of {total} clips exported successfully ({failed} failed).",
    "msg.batch_warning_body": "{ok} of {total} clips exported successfully to:\n{dest}\n\n{failed} failed:\n{lines}",
    "msg.batch_info_body": "{ok} of {total} clips exported successfully to:\n{dest}",

    "info.analyze_before_save": "Analyze a video before saving the project.",
    "dialog.save_project": "Save project",
    "filter.project": "Project (*.pwproj)",
    "info.project_saved": "Project saved.",
    "dialog.load_project": "Load project",
    "info.project_loaded": (
        "Project loaded. Press 'Analyze' again if you want to regenerate the moments "
        "(we saved the data, but the MVP re-analyzes to keep things simple; a future "
        "phase will restore the saved moments without re-analyzing)."
    ),

    "moment.reason_generic": "Moderate combination of signals",
    "moment.label": "Moment #{n} ({ratio})",
    "tooltip.select_clip": "Select to export together with other marked moments",

    "stage.validating": "Validating video",
    "stage.loaded_from_cache": "Loaded from cache (same video and settings already analyzed)",
    "stage.extract_analyze": "Extracting and analyzing audio + video",
    "stage.analyzing_av": "Analyzing audio and video (GPU if available)",
    "stage.detecting_kills": "Detecting kills",
    "stage.scoring": "Calculating combined score",
    "stage.selecting_moments": "Selecting best moments",
    "stage.complete": "Analysis complete",
    "stage.exporting_ffmpeg": "Exporting clip with FFmpeg",
    "stage.export_complete": "Complete",

    "error.unexpected": "An unexpected error occurred:\n\n{type}: {value}",
}

_PT: dict[str, str] = {
    "brand.sub": "AI Clipper",
    "section.project": "PROJETO",
    "section.analysis": "ANÁLISE",
    "section.moments": "MELHORES MOMENTOS DETECTADOS",
    "section.preview": "PRÉVIA",
    "section.trim": "AJUSTE MANUAL DE INÍCIO/FIM",
    "section.export": "EXPORTAÇÃO",

    "btn.open_video": "📂  Abrir vídeo…",
    "btn.load_project": "📁  Carregar projeto…",
    "btn.save_project": "💾  Salvar projeto",

    "label.max_moments": "Máx. momentos:",
    "label.mode": "Modo:",
    "label.language": "Idioma / Language",
    "tooltip.detection_mode": (
        "Geral: detecta picos de áudio, risadas, movimento e cortes de cena.\n"
        "Gaming: também detecta abates, ultimates, sequências e fim de rodada em jogos."
    ),
    "mode.general": "General",
    "mode.gaming": "Gaming",

    "label.speed_mode": "Velocidade:",
    "tooltip.speed_mode": (
        "Rápido: decodificação por GPU + menos amostras/candidatos OCR - recomendado.\n"
        "Preciso: mais amostras por segundo e mais candidatos OCR, mais lento."
    ),
    "mode.fast": "Rápido",
    "mode.precise": "Preciso",

    "label.game": "Jogo:",
    "game.auto": "Detecção automática",
    "game.marvel_rivals": "Marvel Rivals",
    "game.other": "Outro",

    "label.find_specific": "Buscar momentos específicos (opcional):",
    "placeholder.find_specific": "Ex: meus melhores abates jogando Capitão América",
    "tooltip.find_specific": (
        "Filtra os momentos já detectados por palavra-chave (kills, ultimate, "
        "victory...). Não é compreensão de linguagem natural."
    ),

    "btn.analyze": "⚡  Analisar Stream",
    "btn.cancel_analysis": "✕  Cancelar análise",
    "status.waiting_video": "Aguardando vídeo…",
    "label.gpu_note": "GPU: detectada automaticamente\n(decodificação NVDEC + exportação NVENC quando disponíveis)",

    "dropzone.default": "Arraste aqui sua gravação (MP4 / MKV / MOV)\nde 3+ horas, ou clique para selecionar",
    "dropzone.loaded": "✅ Carregado: {name}\n(Clique para escolher outro vídeo)",

    "label.no_selection": "Nenhum clipe selecionado",
    "label.all_selected": "Os {n} clipes selecionados",
    "label.partial_selected": "{n} de {total} clipes selecionados",
    "btn.select_all": "☑  Selecionar todos",
    "btn.deselect_all": "☐  Desmarcar todos",
    "btn.export_selected": "⬇  Exportar selecionados",
    "btn.export_selected_n": "⬇  Exportar selecionados ({n})",

    "label.no_preview": "Prévia não disponível\n(instale o PySide6-Addons com QtMultimedia)",
    "btn.play": "▶ Reproduzir momento",
    "label.start": "Início:",
    "label.end": "Fim:",

    "label.duration": "Duração (s):",
    "chk.vertical": "Vertical 9:16 (TikTok/Reels/Shorts)",
    "chk.horizontal": "Horizontal 16:9 (YouTube)",
    "chk.square": "Quadrado 1:1 (Feed)",
    "chk.normalize": "Normalizar áudio",
    "btn.export_clip": "⬇  Exportar Clipe",

    "warn.unsupported_format": "Formato não suportado. Use MP4, MKV ou MOV.",
    "dialog.select_recording": "Selecione uma gravação",
    "filter.videos": "Vídeos (*.mp4 *.mkv *.mov)",
    "status.video_loaded": "Vídeo carregado. Pronto para analisar.",
    "status.cancelling": "Cancelando… (aguardando o FFmpeg terminar o quadro atual)",
    "eta.remaining": "  —  ~{t} restantes",
    "status.no_moments_found": "Nenhum momento de destaque claro foi encontrado. Tente diminuir o limite ou revisar o áudio do vídeo.",
    "status.analysis_error": "Erro na análise.",
    "error.analysis_failed": "A análise falhou:\n\n{error}",
    "status.analysis_cancelled": "Análise cancelada.",
    "status.moments_found": "{n} momentos encontrados.",
    "status.moments_found_cached": "{n} momentos encontrados (carregado do cache).",

    "warn.select_moment_first": "Selecione um momento da lista antes de exportar.",
    "warn.select_format": "Selecione ao menos um formato de exportação.",
    "info.export_complete": "Exportação concluída. Confira sua pasta de clipes.",
    "dialog.save_clip": "Salvar clipe ({ratio})",
    "filter.mp4": "Vídeo MP4 (*.mp4)",
    "status.exported": "Exportado: {path}",
    "error.export_failed": "A exportação falhou:\n\n{error}",

    "warn.select_at_least_one_moment": "Marque a caixa de ao menos um momento antes de exportar.",
    "dialog.batch_dest_folder": "Pasta de destino para os clipes selecionados",
    "status.exporting_n_of_m": "Exportando {i} de {total}: {label}",
    "status.batch_done": "{ok} de {total} clipes exportados com sucesso.",
    "status.batch_done_with_fails": "{ok} de {total} clipes exportados com sucesso ({failed} falharam).",
    "msg.batch_warning_body": "{ok} de {total} clipes exportados com sucesso em:\n{dest}\n\n{failed} falharam:\n{lines}",
    "msg.batch_info_body": "{ok} de {total} clipes exportados com sucesso em:\n{dest}",

    "info.analyze_before_save": "Analise um vídeo antes de salvar o projeto.",
    "dialog.save_project": "Salvar projeto",
    "filter.project": "Projeto (*.pwproj)",
    "info.project_saved": "Projeto salvo.",
    "dialog.load_project": "Carregar projeto",
    "info.project_loaded": (
        "Projeto carregado. Pressione 'Analisar' novamente se quiser gerar os momentos de novo "
        "(salvamos os dados, mas o MVP reanalisa para simplificar; uma fase futura vai "
        "restaurar os momentos salvos sem reanalisar)."
    ),

    "moment.reason_generic": "Combinação moderada de sinais",
    "moment.label": "Momento #{n} ({ratio})",
    "tooltip.select_clip": "Selecionar para exportar junto com outros momentos marcados",

    "stage.validating": "Validando vídeo",
    "stage.loaded_from_cache": "Carregado do cache (mesmo vídeo e configurações já analisados)",
    "stage.extract_analyze": "Extraindo e analisando áudio + vídeo",
    "stage.analyzing_av": "Analisando áudio e vídeo (GPU se disponível)",
    "stage.detecting_kills": "Detectando kills",
    "stage.scoring": "Calculando pontuação combinada",
    "stage.selecting_moments": "Selecionando melhores momentos",
    "stage.complete": "Análise concluída",
    "stage.exporting_ffmpeg": "Exportando clipe com FFmpeg",
    "stage.export_complete": "Concluído",

    "error.unexpected": "Ocorreu um erro inesperado:\n\n{type}: {value}",
}

_CATALOG: dict[str, dict[str, str]] = {"es": _ES, "en": _EN, "pt": _PT}


def all_keys_present() -> Optional[str]:
    """Chequeo de integridad: devuelve None si los 3 catálogos tienen
    exactamente las mismas claves, o un mensaje describiendo la
    diferencia si no (usado por los tests)."""
    key_sets = {lang: set(cat.keys()) for lang, cat in _CATALOG.items()}
    base_lang, base_keys = "es", key_sets["es"]
    for lang, keys in key_sets.items():
        if lang == base_lang:
            continue
        missing = base_keys - keys
        extra = keys - base_keys
        if missing or extra:
            return f"{lang}: faltan {sorted(missing)}, sobran {sorted(extra)}"
    return None
