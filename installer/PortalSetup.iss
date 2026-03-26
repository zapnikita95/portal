; Inno Setup 6 — установщик Windows для сборки PyInstaller (dist\Portal\).
; Сборка из корня репозитория:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\PortalSetup.iss /DMyAppVersion=1.2.0
; Версия по умолчанию (если не передать /D):
#ifndef MyAppVersion
#define MyAppVersion "1.0.0"
#endif

#define MyAppName "Portal"
#define MyAppPublisher "Portal"
#define MyAppURL "https://github.com/zapnikita95/portal"
#define MyAppExeName "Portal.exe"

[Setup]
AppId={{E7B2F4A1-8C3D-4E5F-9B0A-1C2D3E4F5A6B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=..\dist
OutputBaseFilename=PortalSetup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}
LanguageDetectionMethod=locale

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Portal\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[InstallDelete]
; На всякий случай убрать мусор от старых портативных копий в каталоге установки (осторожно: только подпапки _internal старой структуры)
Type: filesandordirs; Name: "{app}\_internal"
