; installer.iss
; --------------
; Script de Inno Setup para el instalador de Puppywill AI Clipper.
; Empaqueta el build de PyInstaller (dist\PuppywillAIClipper\, generado
; por packaging\build_installer.py) en un instalador de un solo .exe.
;
; Instala por usuario (sin pedir privilegios de administrador) en
; %LOCALAPPDATA%\Programs\PuppywillAIClipper - los datos/ajustes del
; usuario (caché de análisis, settings.json) van aparte, en
; %LOCALAPPDATA%\PuppywillAIClipper (ver app/config.py), nunca dentro de
; la carpeta de instalación.

#define MyAppName "Puppywill AI Clipper"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Puppywill"
#define MyAppURL "https://github.com/Puppywill/Puppywill-AI-Clipper"
#define MyAppExeName "PuppywillAIClipper.exe"

[Setup]
AppId={{7C6C6D9B-9F1E-4B5A-9C0D-5E2F7A8B1C34}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\PuppywillAIClipper
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist_installer
OutputBaseFilename=Puppywill-AI-Clipper-Setup-v{#MyAppVersion}
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

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\PuppywillAIClipper\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; el caché/ajustes de usuario NO se borra al desinstalar (viven fuera de
; {app}, en %LOCALAPPDATA%\PuppywillAIClipper) - solo se limpian los
; archivos del programa en sí
Type: filesandordirs; Name: "{app}"
