# build_installer.ps1 (rama feature/gaming-mode: variante BETA)
# --------------------
# Compila el instalador de Windows BETA para Puppywill AI Clipper
# (Gaming Mode):
#   1. PyInstaller empaqueta main.py + PySide6/OpenCV/NumPy en un .exe.
#   2. Copia FFmpeg/FFprobe portables junto al .exe (para que la app
#      funcione sin que el usuario instale FFmpeg aparte).
#   3. Deja un archivo marcador BETA_BUILD junto al .exe - app/config.py
#      lo detecta (_is_beta_build) y usa
#      %LOCALAPPDATA%\PuppywillAIClipperBeta en vez de la carpeta de la
#      versión estable, para que ajustes/caché no se mezclen entre
#      ambas versiones instaladas a la vez.
#   4. Inno Setup (packaging\installer.iss, en esta rama configurado con
#      AppId/nombre/carpeta propios de la beta) compila todo eso en un
#      único instalador .exe que puede convivir instalado junto al de
#      la versión estable v1.0.0 sin pisarlo ni desinstalarlo.
#
# Requisitos (no se instalan automáticamente, ver setup_check.py):
#   - Python 3.10-3.12 con las dependencias de requirements.txt + pyinstaller
#     (pip install pyinstaller)
#   - Inno Setup 6 (https://jrsoftware.org/isdl.php, o
#     'winget install JRSoftware.InnoSetup')
#   - Un build portable de FFmpeg "essentials" para Windows x64 (GPLv3,
#     incluye NVENC/NVDEC), descargado de
#     https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
#     y extraído en -FfmpegBinDir (por defecto build_deps\ffmpeg\bin).
#
# Uso:
#   .\packaging\build_installer.ps1
#
# Resultado: dist_installer\Puppywill-AI-Clipper-Setup-v1.1.0-beta.1.exe

param(
    [string]$FfmpegBinDir = "$PSScriptRoot\..\build_deps\ffmpeg\bin",
    [string]$IsccPath = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..").Path

if (-not (Test-Path "$FfmpegBinDir\ffmpeg.exe")) {
    throw "No se encontró ffmpeg.exe en $FfmpegBinDir. Descarga el build 'essentials' de " +
          "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip y extráelo ahí " +
          "(o pasa -FfmpegBinDir con la ruta correcta)."
}
if (-not (Test-Path $IsccPath)) {
    throw "No se encontró ISCC.exe (Inno Setup) en $IsccPath. Instálalo con " +
          "'winget install JRSoftware.InnoSetup' o pasa -IsccPath."
}

Write-Host "== 1/3: PyInstaller ==" -ForegroundColor Cyan
Push-Location $root
try {
    pyinstaller --name PuppywillAIClipper --windowed --icon assets\puppywill_icon.ico `
        --add-data "assets;assets" --noconfirm --clean main.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller falló (código $LASTEXITCODE)" }
} finally {
    Pop-Location
}

Write-Host "== 2/3: Copiando FFmpeg/FFprobe portables ==" -ForegroundColor Cyan
$ffmpegDest = Join-Path $root "dist\PuppywillAIClipper\ffmpeg"
New-Item -ItemType Directory -Force -Path $ffmpegDest | Out-Null
Copy-Item (Join-Path $FfmpegBinDir "ffmpeg.exe") $ffmpegDest -Force
Copy-Item (Join-Path $FfmpegBinDir "ffprobe.exe") $ffmpegDest -Force
$ffmpegRoot = Split-Path $FfmpegBinDir -Parent
foreach ($f in @("LICENSE", "README.txt")) {
    $src = Join-Path $ffmpegRoot $f
    if (Test-Path $src) { Copy-Item $src $ffmpegDest -Force }
}

Write-Host "== 3/4: Marcando build como BETA ==" -ForegroundColor Cyan
$betaMarker = Join-Path $root "dist\PuppywillAIClipper\BETA_BUILD"
Set-Content -Path $betaMarker -Value "Puppywill AI Clipper Beta - ver app/config.py:_is_beta_build" -Encoding utf8

Write-Host "== 4/4: Compilando instalador con Inno Setup ==" -ForegroundColor Cyan
& $IsccPath (Join-Path $PSScriptRoot "installer.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC falló (código $LASTEXITCODE)" }

Write-Host "Listo: dist_installer\Puppywill-AI-Clipper-Setup-v1.1.0-beta.1.exe" -ForegroundColor Green
