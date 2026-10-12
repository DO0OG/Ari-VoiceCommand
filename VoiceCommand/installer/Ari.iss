; Ari Windows 설치 프로그램 (Inno Setup 6)
;
; 빌드 (VoiceCommand 폴더에서):
;   ISCC /DAppVersion=1.7.0 /DNumericVersion=1.7.0.0 /DBuildDir=<build_exe.py 출력 폴더> installer\Ari.iss
; NumericVersion은 Ari.exe의 파일 버전과 같은 숫자 네 자리 값이다(core.app_version.get_windows_version).
;
; 사용자 설정과 기록은 %AppData%\Ari에 저장되므로 제거해도 남는다.
; 개인정보 선택 항목은 {app}\install_options.ini에 기록되고, 앱이 시작할 때 한 번 읽어 끄는 방향으로만 반영한다.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef NumericVersion
  #define NumericVersion "0.0.0.0"
#endif
#ifndef BuildDir
  #define BuildDir "..\dist\Ari"
#endif

[Setup]
AppId={{34487F66-4F7F-472B-9FA8-1A7894373E74}
AppName=Ari
AppVersion={#AppVersion}
AppVerName=Ari {#AppVersion}
; 서명 대상 파일의 제품 이름과 제품 버전은 모두 같아야 한다. 제품 버전은 Ari.exe와 같은 숫자 값이고, 파일의 텍스트 버전만 AppVersion을 쓴다.
VersionInfoProductName=Ari VoiceCommand
VersionInfoVersion={#NumericVersion}
VersionInfoTextVersion={#AppVersion}
VersionInfoProductTextVersion={#NumericVersion}
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
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"; InfoBeforeFile: "privacy-ko.txt"
Name: "english"; MessagesFile: "compiler:Default.isl"; InfoBeforeFile: "privacy-en.txt"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"; InfoBeforeFile: "privacy-ja.txt"

[CustomMessages]
korean.PrivacyTasks=개인정보 관련 선택
korean.UpdateCheckTask=자동 업데이트 확인
korean.OnlineSpeechTask=온라인 음성 서비스(Google 음성 인식, Microsoft Edge TTS) 사용
english.PrivacyTasks=Privacy options
english.UpdateCheckTask=Check for updates automatically
english.OnlineSpeechTask=Use online speech services (Google speech recognition, Microsoft Edge TTS)
japanese.PrivacyTasks=プライバシーに関する選択
japanese.UpdateCheckTask=更新を自動的に確認する
japanese.OnlineSpeechTask=オンライン音声サービス(Google 音声認識、Microsoft Edge TTS)を使用する

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "updatecheck"; Description: "{cm:UpdateCheckTask}"; GroupDescription: "{cm:PrivacyTasks}"
Name: "onlinespeech"; Description: "{cm:OnlineSpeechTask}"; GroupDescription: "{cm:PrivacyTasks}"

[Files]
; 빌드 후 자체 검사가 남길 수 있는 실행 기록 폴더는 넣지 않는다.
Source: "{#BuildDir}\*"; DestDir: "{app}"; Excludes: ".ari_runtime"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Ari"; Filename: "{app}\Ari.exe"
Name: "{autodesktop}\Ari"; Filename: "{app}\Ari.exe"; Tasks: desktopicon

[INI]
; 항목별 1(켬)/0(끔)과 설치 식별 토큰. 같은 토큰은 앱이 한 번만 반영한다.
Filename: "{app}\install_options.ini"; Section: "Options"; Key: "token"; String: "{code:InstallToken}"
Filename: "{app}\install_options.ini"; Section: "Options"; Key: "update_check"; String: "1"; Tasks: updatecheck
Filename: "{app}\install_options.ini"; Section: "Options"; Key: "update_check"; String: "0"; Tasks: not updatecheck
Filename: "{app}\install_options.ini"; Section: "Options"; Key: "online_speech"; String: "1"; Tasks: onlinespeech
Filename: "{app}\install_options.ini"; Section: "Options"; Key: "online_speech"; String: "0"; Tasks: not onlinespeech

[UninstallDelete]
Type: files; Name: "{app}\install_options.ini"

[Run]
Filename: "{app}\Ari.exe"; Description: "{cm:LaunchProgram,Ari}"; Flags: nowait postinstall skipifsilent

[Code]
function InstallToken(Param: String): String;
begin
  Result := GetDateTimeString('yyyymmddhhnnss', #0, #0);
end;
