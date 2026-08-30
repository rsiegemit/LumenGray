; Inno Setup script for LumenGray — a one-click Windows installer.
;
; Wraps the PyInstaller one-folder build (dist\LumenGray\) into LumenGray-Setup.exe:
; double-click installs LumenGray per-user (no admin prompt), adds Start Menu +
; optional Desktop shortcuts, and registers an uninstaller. Compiled in CI by
; ISCC.exe after the PyInstaller step (see .github/workflows/build.yml).
;
; Build locally (on Windows, with Inno Setup 6 installed):
;   pyinstaller --noconfirm packaging/LumenGray.spec
;   ISCC packaging/lumengray.iss        ->  dist/LumenGray-Setup.exe

#define MyAppName "LumenGray"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.19"
#endif
#define MyAppPublisher "rsiegemit"
#define MyAppURL "https://github.com/rsiegemit/LumenGray"
#define MyAppExeName "LumenGray.exe"

[Setup]
AppId={{59250D50-273C-4C3B-923C-5A4FAEE23DB1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
; Per-user install → no admin prompt → true one-click.
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=..\dist
OutputBaseFilename=LumenGray-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; The PyInstaller one-folder output — every file, preserving subfolders.
Source: "..\dist\LumenGray\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
