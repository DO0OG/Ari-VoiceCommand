; Ari Windows 설치 프로그램 (Inno Setup 6)
;
; 빌드 (VoiceCommand 폴더에서):
;   ISCC /DAppVersion=1.7.0 /DBuildDir=<build_exe.py 출력 폴더> installer\Ari.iss
;
; 사용자 설정과 기록은 %AppData%\Ari에 저장되므로 제거해도 남는다.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef BuildDir
  #define BuildDir "..\dist\Ari"
#endif

[Setup]
AppId={{34487F66-4F7F-472B-9FA8-1A7894373E74}
AppName=Ari
AppVersion={#AppVersion}
AppVerName=Ari {#AppVersion}
AppPublisher=DO0OG
AppPublisherURL=https://github.com/DO0OG/Ari-VoiceCommand
AppSupportURL=https://github.com/DO0OG/Ari-VoiceCommand/issues
DefaultDirName={autopf}\Ari
DisableProgramGroupPage=yes
; 기본은 모든 사용자용(Program Files) 설치. 명령줄 /CURRENTUSER는 자동 검사용이다.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=Ari-Setup-{#AppVersion}
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\Ari.exe
UninstallDisplayName=Ari
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 빌드 후 자체 검사가 남길 수 있는 실행 기록 폴더는 넣지 않는다.
Source: "{#BuildDir}\*"; DestDir: "{app}"; Excludes: ".ari_runtime"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Ari"; Filename: "{app}\Ari.exe"
Name: "{autodesktop}\Ari"; Filename: "{app}\Ari.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Ari.exe"; Description: "{cm:LaunchProgram,Ari}"; Flags: nowait postinstall skipifsilent
