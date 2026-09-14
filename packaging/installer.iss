; installer.iss (rama feature/gaming-mode: variante BETA)
; --------------
; Script de Inno Setup para el instalador BETA de Puppywill AI Clipper
; (Gaming Mode). Empaqueta el build de PyInstaller (dist\PuppywillAIClipper\,
; generado por packaging\build_installer.ps1) en un instalador de un solo
; .exe.
;
; A propósito usa un AppId, nombre visible, carpeta de instalación y
; accesos directos DISTINTOS de la versión estable v1.0.0 (que usa
; AppId {{7C6C6D9B-9F1E-4B5A-9C0D-5E2F7A8B1C34}}, nombre "Puppywill AI
; Clipper" y carpeta ...\Programs\PuppywillAIClipper - ver el mismo
; archivo en la rama main) para que ambas puedan instalarse y convivir
; en la misma máquina sin pisarse ni desinstalarse entre sí. El .exe
; interno se sigue llamando PuppywillAIClipper.exe (vive dentro de su
; propia carpeta de instalación separada, no hay colisión posible).
;
; Instala por usuario (sin pedir privilegios de administrador). Por
; defecto sugiere %LOCALAPPDATA%\Programs\PuppywillAIClipperBeta - una
; ubicación local que OneDrive NUNCA sincroniza/redirige (a diferencia
; de Escritorio/Documentos/Imágenes/Videos, que sí pueden estarlo según
; la configuración de OneDrive de cada usuario) - pero el asistente
; SIEMPRE muestra la pantalla "Seleccionar ubicación de destino"
; (DisableDirPage=no, es el valor por defecto de Inno Setup, aquí
; explícito para que quede claro) donde el usuario puede elegir
; cualquier otra carpeta o disco con el botón "Examinar".
;
; Los datos/ajustes del usuario (caché de análisis, settings.json) van
; aparte, en %LOCALAPPDATA%\PuppywillAIClipperBeta (ver
; app/config.py:_is_beta_build - el build script deja un archivo
; marcador BETA_BUILD junto al .exe para que la app sepa usar esta
; carpeta separada en vez de la de la versión estable), nunca dentro de
; la carpeta de instalación. La carpeta de exportación de clips la sigue
; eligiendo el usuario como siempre (o la sugerencia por defecto de
; app/config.py, igual en ambas versiones - no afecta el aislamiento de
; ajustes/caché entre beta y estable).

#define MyAppName "Puppywill AI Clipper Beta"
#define MyAppVersion "1.1.0-beta.1"
#define MyAppPublisher "Puppywill"
#define MyAppURL "https://github.com/Puppywill/Puppywill-AI-Clipper"
#define MyAppExeName "PuppywillAIClipper.exe"

[Setup]
AppId={{5EC8EF75-641D-42CE-89F5-1E65F8631D6B}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\PuppywillAIClipperBeta
DisableDirPage=no
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist_installer
; Nombre de archivo FIJO (no derivado de {#MyAppVersion}) para que no
; cambie aunque se ajuste la versión interna del instalador.
OutputBaseFilename=Puppywill-AI-Clipper-Setup-v1.1.0-beta.1
SetupIconFile=..\assets\puppywill_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "portuguese"; MessagesFile: "compiler:Languages\Portuguese.isl"

[Tasks]
; casilla en la pantalla "Seleccionar tareas adicionales" - marcada por
; defecto, pero el usuario puede desmarcarla para NO crear el acceso
; directo de escritorio
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "..\dist\PuppywillAIClipper\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; entrada del menú Inicio: SIEMPRE se crea (sin Tasks:, no es opcional)
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
; acceso directo de escritorio: solo si se dejó marcada la casilla de arriba
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; el caché/ajustes de usuario NO se borra al desinstalar (viven fuera de
; {app}, en %LOCALAPPDATA%\PuppywillAIClipperBeta) - solo se limpian los
; archivos del programa en sí. Desinstalar la beta nunca toca la
; instalación de la versión estable (carpeta, AppId y registro de
; desinstalación completamente separados).
Type: filesandordirs; Name: "{app}"
