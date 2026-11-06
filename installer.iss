#ifndef APP_VERSION
  #define APP_VERSION "1.1.1"
#endif

#define MyAppName "Orbit"
#define MyAppFolder "Orbit"
#define MyAppExe "Orbit.exe"

[Setup]
AppId={{D0E61B04-C58C-4D44-A833-E867AB3813DE}
AppName={#MyAppName}
AppVersion={#APP_VERSION}
AppPublisher=D6VAlex
AppPublisherURL=https://github.com/D6VAlex/orbit-launcher
AppUpdatesURL=https://github.com/D6VAlex/orbit-launcher/releases/latest
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExe}
SetupIconFile=assets\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
CloseApplications=yes
RestartApplications=no
OutputDir=dist
OutputBaseFilename=Orbit-Setup-{#APP_VERSION}

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "Start {#MyAppName} when Windows starts"; GroupDescription: "Windows startup:"; Flags: unchecked

[Files]
Source: "dist\{#MyAppFolder}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExe}"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nIt installs the launcher, adds shortcuts, and registers an uninstaller - so the app stays installed even if the downloaded file is deleted.
