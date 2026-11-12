; Inno Setup script for Prometheus Desktop (Windows x64). Built by .github/workflows/prometheus-desktop.yml:
;   iscc /DAppVersion=0.1.0 packaging\prometheus.iss
; Per-user install (no administrator rights). Uninstalling removes the program only: personal data in
; %APPDATA%\Prometheus and keys in Windows Credential Manager are kept unless the user deletes them.
; The installer is NOT code-signed; Windows SmartScreen will warn about an unknown publisher.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; A fixed AppId makes a newer installer upgrade the existing installation in place.
AppId={{D16A14D4-4255-4C0A-B45C-370C1D685919}
AppName=Prometheus
AppVersion={#AppVersion}
AppVerName=Prometheus {#AppVersion}
AppPublisher=Prometheus project (unsigned build)
DefaultDirName={localappdata}\Programs\Prometheus
DefaultGroupName=Prometheus
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Prometheus-Setup-{#AppVersion}-x64-unsigned
SetupIconFile=prometheus.ico
UninstallDisplayIcon={app}\Prometheus.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\Prometheus\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Remove files from an older version's program folder before copying the new ones (program files only).
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Prometheus"; Filename: "{app}\Prometheus.exe"
Name: "{autodesktop}\Prometheus"; Filename: "{app}\Prometheus.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Prometheus.exe"; Description: "Start Prometheus"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Remove the optional "start when I sign in" entry if the user turned it on.
Filename: "{sys}\reg.exe"; Parameters: "delete HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v Prometheus /f"; Flags: runhidden; RunOnceId: "RemoveRunKey"
