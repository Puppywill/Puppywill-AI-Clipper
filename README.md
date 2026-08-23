# 🐾 Puppywill AI Clipper

App de escritorio para Windows que analiza grabaciones largas de gameplay/
stream (3+ horas) y encuentra automáticamente tus mejores kills, multikills
y jugadas — pensado especialmente para Marvel Rivals, aunque la detección
genérica de audio/video funciona con cualquier juego — recortándolos en
clips limpios listos para editar en CapCut (o cualquier otro editor):
título, subtítulos, efectos y música los agregas tú después.

La detección usa **audio y video** (intensidad de audio, el sonido de
confirmación de eliminación, risas, movimiento de cámara, cambios de
escena, y opcionalmente el kill feed en pantalla) — no hay transcripción
de voz ni modelos de lenguaje involucrados. **Analiza grabaciones que ya
tienes; no graba tu pantalla.**

## Windows Desktop Application

Puppywill AI Clipper es una **aplicación de escritorio nativa para
Windows** (interfaz gráfica con PySide6/Qt, no una web app ni un
servicio en la nube), pensada para correr localmente sobre tus propias
grabaciones. Incluye:

- **Interfaz gráfica profesional**, con tema oscuro, vista previa
  integrada y una ventana única para analizar, revisar y exportar.
- **Análisis acelerado con NVIDIA GPU/NVDEC** (`ffmpeg -hwaccel cuda`,
  incluye AV1 además de H.264/HEVC) para decodificar el video mucho más
  rápido que por CPU; si no hay GPU NVIDIA disponible, cae a CPU
  automáticamente sin que tengas que configurar nada.
- **Modos Rápido y Preciso**, elegibles desde la barra lateral: Rápido
  (predeterminado) para streams largos, Preciso para un muestreo más
  denso.
- **Detección de mejores momentos, kills, multikills y reacciones**,
  combinando audio, video y (opcionalmente) OCR del kill feed en una
  sola puntuación de calidad con etiquetas legibles.
- **Vista previa y ajuste manual** del inicio/fin de cada clip antes de
  exportar.
- **Selección y exportación de varios clips a la vez**: marca los que
  quieras, elige una carpeta de destino una sola vez, y se exportan
  todos con nombres únicos.
- **Exportación en 9:16, 16:9 y 1:1**, lista para subir a redes o seguir
  editando en CapCut.
- **Interfaz en Español, English y Português**: selector "Idioma /
  Language" en la barra lateral, español por defecto. El cambio se
  aplica al instante, sin reiniciar la app, y se recuerda la próxima
  vez que la abras.

## Download for Windows

La forma más simple de usar Puppywill AI Clipper: descarga el instalador,
ábrelo e instala — no necesitas tener Python instalado.

1. Ve a la página de **[Releases](https://github.com/Puppywill/Puppywill-AI-Clipper/releases/latest)**
   del repositorio.
2. Descarga `Puppywill-AI-Clipper-Setup-v1.0.0.exe` (junto a su archivo
   `.sha256` para verificar la descarga si quieres).
3. Ábrelo y sigue el instalador (disponible en Español, English y
   Português): siempre crea entrada en el menú Inicio, y te deja elegir
   si además quieres acceso directo en el escritorio y en qué carpeta
   instalar (por defecto, una ubicación local, nunca OneDrive). Incluye
   desinstalador. No requiere privilegios de administrador ni configurar
   FFmpeg aparte — ya viene incluido.
4. Abre "Puppywill AI Clipper" desde el escritorio o el menú Inicio.
   Dentro de la app, la interfaz también se puede cambiar de idioma en
   cualquier momento desde la barra lateral.

**Si Windows SmartScreen muestra una advertencia** ("Windows protegió tu
PC" / editor no reconocido): el instalador todavía no está firmado
digitalmente (una firma de código cuesta dinero y no es viable aún para
este proyecto), así que esto es esperado, no un error. Antes de
continuar, verifica que lo descargaste desde la página oficial de
Releases de este repositorio (`github.com/Puppywill/Puppywill-AI-Clipper`)
y no de otro sitio. **No hay forma segura de "evitar" esta advertencia
que recomendemos** — solo continúa si confirmaste el origen del archivo
tú mismo.

¿Prefieres correrlo desde el código fuente con Python en vez del
instalador? Sigue la sección [📦 Instalación](#-instalación) más abajo.

## Vista de la aplicación

<p align="center">
  <img src="docs/images/puppywill-ai-clipper-interface.png" alt="Interfaz principal de Puppywill AI Clipper para analizar, previsualizar y exportar momentos destacados" width="100%">
</p>

## ✨ Funciones

- **Detección de kills/multikills**: el sonido de confirmación de
  eliminación (transitorio corto y agudo, distinto de un grito sostenido)
  es la señal principal — funciona aunque el kill feed del juego no sea
  visible en tu encuadre. Si además tienes Tesseract OCR instalado
  (opcional), lee el kill feed en pantalla para contar multikills con más
  precisión.
- **Detección de mejores momentos** combinando la señal de kills, picos de
  audio, risas, movimiento visual y cambios de escena en una sola
  puntuación de calidad (0-100), con etiquetas legibles: **Kill**,
  **Multikill**, **Best Play** (el momento de mayor puntuación),
  **Reaction** (reacción fuerte justo después de la jugada) e **Intense
  Fight** (pelea sostenida, no solo un instante).
- **Estructura de highlight**: cada clip se arma con el pico de intensidad
  cayendo ~60-75% de su duración (preparación breve → jugada → cierre o
  reacción), no centrado a ciegas, y el corte se ajusta dinámicamente para
  no cortar a mitad de una acción sin resolución.
- **Sin duplicados**: un multikill se agrupa en un solo clip (con la
  etiqueta "Multikill") en vez de generar varios clips casi idénticos de
  la misma pelea; jugadas distintas se mantienen separadas.
- **Momentos ordenados por puntuación**, de mejor a peor, con vista previa
  antes de exportar.
- **Vista previa** integrada del momento seleccionado.
- **Ajuste manual** de inicio/fin con sliders, si quieres afinar el corte.
- **Duraciones predefinidas** de 15/30/45/60s (recalculan la ventana al
  vuelo, siempre con duración exacta).
- **Exportación multi-formato**: 9:16 (TikTok/Reels/Shorts), 16:9 (YouTube),
  1:1 (feed), en H.264/1080p/60fps, sin subtítulos ni marca de agua — el
  clip queda limpio para que edites en CapCut.
- **Normalización de audio** (loudnorm EBU R128) opcional.
- **"Guardar como"** en cada exportación individual: recuerda la última
  carpeta usada, pero puedes cambiar carpeta y nombre libremente cada vez.
- **Exportación por lotes**: marca la casilla de varios momentos (o usa
  "Seleccionar todos"), elige carpeta de destino UNA sola vez, y se exportan
  todos en los formatos marcados con nombres únicos y descriptivos
  (`video_top01_00m12s_9x16.mp4`, ...) que nunca sobrescriben un clip
  existente. Muestra "Exportando N de M"; si un clip falla, los demás
  siguen y al final se indica cuál falló. La app sigue abierta y con el
  video/resultados/selección intactos, lista para seguir exportando.
- **Aceleración por GPU tanto al analizar como al exportar**: el decode del
  video de entrada usa NVDEC (`ffmpeg -hwaccel cuda`) cuando está
  disponible — incluye AV1, no solo H.264/HEVC — y la exportación usa NVENC;
  si no hay GPU NVIDIA, todo cae a CPU automáticamente, sin configurar nada.
- **Modo Rápido (predeterminado) / Preciso**: Rápido decodifica menos
  muestras por segundo y revisa menos candidatos de OCR — pensado para
  streams de horas; Preciso muestrea más denso para mayor detalle. La
  aceleración por GPU se usa igual en ambos modos.
- **Análisis en paralelo**: el audio y el video se leen y analizan en dos
  hilos simultáneos (son dos pasadas independientes del mismo archivo), y el
  OCR de candidatos a kill corre en un pequeño pool de hilos en vez de uno
  por uno.
- **Progreso real con tiempo estimado restante** y **botón para cancelar**
  el análisis en cualquier momento sin congelar ni cerrar la app (mata el
  proceso de FFmpeg en curso al instante).
- **Caché de resultados**: si vuelves a analizar el mismo archivo con los
  mismos ajustes (mismo modo, misma duración/cantidad de momentos), el
  resultado se carga al instante en vez de repetir el análisis completo.
- **Guardar/cargar proyecto** (`.pwproj`) para retomar el trabajo después.

## 📋 Requisitos

Si usas el [instalador](#download-for-windows) no necesitas nada de esto
(FFmpeg ya viene incluido) - esta lista es solo para correr desde el
código fuente con Python.

- Windows 10/11
- Python 3.10 - 3.12
- [FFmpeg](https://ffmpeg.org/download.html) (con `ffmpeg`/`ffprobe` en el PATH)
- GPU NVIDIA (opcional; acelera tanto el análisis vía NVDEC como la
  exportación vía NVENC - sin ella todo funciona igual, solo más lento,
  por CPU)
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) (opcional,
  solo mejora el conteo de multikills leyendo el kill feed en pantalla)

No hace falta PyTorch, CUDA ni ningún framework de IA: la detección de
momentos usa solo `numpy` (audio) y `opencv-python` (video).

## 📦 Instalación

Esta sección es para correr **desde el código fuente** con Python. Si
solo quieres usar la app, descarga el [instalador para Windows](#download-for-windows)
en vez de esto.

### 1. Clona el repositorio

```powershell
git clone https://github.com/Puppywill/Puppywill-AI-Clipper.git
cd Puppywill-AI-Clipper
```

### 2. Verifica tu sistema (no instala nada, solo diagnostica)

```powershell
python setup_check.py
```

Te dice si falta FFmpeg, si tu GPU es detectada, si NVENC funciona, y qué
paquetes de Python faltan.

### 3. Instala FFmpeg (si `setup_check.py` lo marca como faltante)

```powershell
winget install ffmpeg
```
o descarga un build "full" desde https://www.gyan.dev/ffmpeg/builds/ y añade
la carpeta `bin` al PATH.

### 4. Instala las dependencias de Python

```powershell
pip install -r requirements.txt
```

### 4b. (Opcional) Instala Tesseract OCR para mejor conteo de multikills

```powershell
winget install UB-Mannheim.TesseractOCR
```

Sin esto, la detección de kills sigue funcionando igual (usa el sonido de
confirmación de eliminación como señal principal); Tesseract solo afina el
conteo cuando el kill feed del juego es visible en tu grabación.

### 5. Vuelve a correr la verificación

```powershell
python setup_check.py
```

Deberías ver ✅ en Python, FFmpeg y los tres paquetes (PySide6, opencv-python,
numpy). NVENC es opcional.

### 6. Ejecuta la app

```powershell
python main.py
```

## 🖱️ Acceso directo de escritorio (opcional, para correr desde el código fuente)

Si instalaste con el [instalador para Windows](#download-for-windows), ya
tienes acceso directo en el escritorio y en el menú Inicio - esta
sección es solo para quien corre la app desde el código fuente con
Python. El proyecto incluye un launcher de doble clic que no abre
ventana de consola y verifica dependencias antes de arrancar:

- `run_puppywill.pyw` — verifica FFmpeg/paquetes y abre la interfaz; si
  falta algo, muestra un mensaje claro en vez de fallar en silencio.
- `launch_puppywill.vbs` — punto de entrada del acceso directo; busca
  `pythonw.exe` en el PATH del sistema antes de intentar nada.

Para crear el acceso directo en tu escritorio: clic derecho sobre
`launch_puppywill.vbs` → **Crear acceso directo**, mueve el acceso directo
a tu escritorio, y cambia su icono (Propiedades → Cambiar icono) al de
`assets/puppywill_icon.ico`.

## 🎬 Cómo usarla

1. Arrastra tu grabación (MP4/MKV/MOV) a la ventana, o haz clic en la zona
   de arrastre para seleccionarla.
2. Pulsa **Analizar Stream**. La barra de progreso muestra cada etapa:
   extracción de audio, análisis de energía, análisis visual, scoring.
3. En la lista de la izquierda verás los momentos ordenados por puntuación
   de calidad, con las razones detectadas.
4. Selecciona un momento: se carga en la vista previa con el rango
   Inicio/Fin ya posicionado (pico ~60-75% del clip). Ajusta con los
   sliders si quieres afinar el corte manualmente.
5. Elige la duración (15/30/45/60s) y los formatos de salida (9:16 / 16:9 /
   1:1), y si quieres normalizar el audio.
6. Pulsa **Exportar Clip** para exportar solo el momento seleccionado (por
   cada formato se abre "Guardar como", con la última carpeta usada por
   defecto pero puedes cambiarla). O marca la casilla de varios momentos y
   pulsa **Exportar seleccionados** para exportarlos todos juntos a una
   carpeta que eliges una sola vez. El resultado es siempre un MP4 limpio,
   listo para importar en CapCut y editar ahí título, subtítulos, efectos y
   música.
7. Guarda el proyecto para retomar el trabajo más tarde sin perder los
   momentos detectados.

## 🧪 Tests

```powershell
python tests/test_pipeline.py
python tests/test_kill_detection.py
python tests/test_batch_export.py
```

Ninguna depende de PySide6, GPU, ni de tener Tesseract instalado.

- `test_pipeline.py`: genera un video sintético con picos de volumen
  simulados, corre el análisis real de audio+video+scoring, verifica que
  detecta los picos correctos, y exporta clips reales en los tres formatos
  verificando dimensiones con `ffprobe`.
- `test_kill_detection.py`: genera un video sintético con "dings" de kill
  cortos y agudos (tres muy juntos simulando un multikill, uno aislado),
  corre el pipeline completo, y verifica que el multikill se agrupa en un
  solo clip etiquetado "Multikill", el kill aislado queda en su propio
  clip etiquetado "Kill", y el de mayor puntuación queda marcado "Best
  Play".
- `test_batch_export.py`: verifica que los nombres de archivo nunca se
  sobrescriben, que exportar varios momentos x formatos a la vez produce
  todos los clips correctos con el progreso reportado bien, y que un clip
  que falla (video inexistente) no detiene a los demás.

## 🗂️ Estructura del proyecto

```
puppywill_ai_clipper/
├── main.py                      # punto de entrada (consola)
├── run_puppywill.pyw            # launcher de doble clic (sin consola)
├── launch_puppywill.vbs         # punto de entrada del acceso directo
├── setup_check.py               # diagnóstico de sistema (correr primero)
├── requirements.txt
├── assets/
│   ├── puppywill_icon.ico
│   └── puppywill_icon.png
├── tests/
│   ├── test_pipeline.py         # prueba end-to-end real (audio+video+export)
│   ├── test_kill_detection.py   # prueba de kill/multikill/best play
│   └── test_batch_export.py     # prueba de exportación por lotes
└── app/
    ├── config.py                 # ajustes persistentes del usuario
    ├── core/
    │   ├── video_io.py           # validación/metadata de video (ffprobe)
    │   ├── audio_analysis.py     # energía, picos, risas (numpy)
    │   ├── visual_analysis.py    # movimiento, cortes de escena, ROI de kill feed (opencv)
    │   ├── kill_events.py        # detección de kills: audio + visual + OCR opcional
    │   ├── scoring.py            # detección de momentos + estructura de highlight
    │   ├── moment_detector.py    # orquesta el pipeline de análisis (modos, paralelismo, cancelación)
    │   ├── analysis_cache.py     # caché en disco de resultados de análisis
    │   ├── proc_utils.py         # subprocesos FFmpeg sin ventana + probe de decode GPU
    │   ├── clip_exporter.py      # exporta con FFmpeg (crop/normalize/GPU)
    │   ├── batch_export.py       # exporta varios momentos x formatos en una pasada
    │   └── project.py            # guardar/cargar proyectos .pwproj
    └── ui/
        ├── styles.py              # tema oscuro QSS
        ├── workers.py             # QThreads para análisis/exportación
        └── main_window.py         # ventana principal PySide6
```

## 🔮 Posibles próximas fases

- Seguimiento de rostro (face tracking) para posicionar automáticamente la
  cámara dentro del encuadre vertical.
- Música de fondo con biblioteca integrada (el mezclador de audio ya está
  implementado en `clip_exporter`, falta la biblioteca/selector en la UI).
- Restaurar momentos guardados en un proyecto sin tener que re-analizar.
