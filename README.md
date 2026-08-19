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
de voz ni modelos de lenguaje involucrados, así que es rápida y no
necesita GPU. **Analiza grabaciones que ya tienes; no graba tu pantalla.**

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
- **"Guardar como"** en cada exportación: recuerda la última carpeta usada,
  pero puedes cambiar carpeta y nombre libremente cada vez.
- **Aceleración por GPU (NVENC)** automática si hay una GPU NVIDIA
  disponible; si no, exporta con CPU (libx264) sin que tengas que configurar
  nada.
- **Guardar/cargar proyecto** (`.pwproj`) para retomar el trabajo después.

## 📋 Requisitos

- Windows 10/11
- Python 3.10 - 3.12
- [FFmpeg](https://ffmpeg.org/download.html) (con `ffmpeg`/`ffprobe` en el PATH)
- GPU NVIDIA (opcional, solo acelera la exportación vía NVENC)
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) (opcional,
  solo mejora el conteo de multikills leyendo el kill feed en pantalla)

No hace falta PyTorch, CUDA ni ningún framework de IA: la detección de
momentos usa solo `numpy` (audio) y `opencv-python` (video).

## 📦 Instalación

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

## 🖱️ Acceso directo de escritorio (opcional)

El proyecto incluye un launcher de doble clic que no abre ventana de
consola y verifica dependencias antes de arrancar:

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
6. Pulsa **Exportar Clip**. Por cada formato se abre "Guardar como" (con la
   última carpeta usada por defecto, pero puedes cambiarla). El resultado es
   un MP4 limpio, listo para importar en CapCut y editar ahí título,
   subtítulos, efectos y música.
7. Guarda el proyecto para retomar el trabajo más tarde sin perder los
   momentos detectados.

## 🧪 Tests

```powershell
python tests/test_pipeline.py
python tests/test_kill_detection.py
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
│   └── test_kill_detection.py   # prueba de kill/multikill/best play
└── app/
    ├── config.py                 # ajustes persistentes del usuario
    ├── core/
    │   ├── video_io.py           # validación/metadata de video (ffprobe)
    │   ├── audio_analysis.py     # energía, picos, risas (numpy)
    │   ├── visual_analysis.py    # movimiento, cortes de escena, ROI de kill feed (opencv)
    │   ├── kill_events.py        # detección de kills: audio + visual + OCR opcional
    │   ├── scoring.py            # detección de momentos + estructura de highlight
    │   ├── moment_detector.py    # orquesta el pipeline de análisis
    │   ├── clip_exporter.py      # exporta con FFmpeg (crop/normalize/GPU)
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
