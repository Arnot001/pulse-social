#define MyAppName "Pulse Social"
#define MyAppVersion "0.1.0-beta.1"
#define MyAppPublisher "Pulse"
#define MyAppExeName "Pulse Social.exe"

[Setup]
AppId={{B095E8B1-CC57-4C58-B91E-4D5DBFF5E3B4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} Beta {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Pulse Social
DefaultGroupName=Pulse Social
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=output\installer
OutputBaseFilename=Pulse-Social-Beta-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=Pulse Social Beta
SetupLogging=yes
SetupIconFile=..\platforms\tiktok\favicon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "output\Pulse Social\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Pulse Social"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; IconIndex: 0
Name: "{autodesktop}\Pulse Social"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; IconIndex: 0; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Pulse Social"; Flags: nowait postinstall skipifsilent
