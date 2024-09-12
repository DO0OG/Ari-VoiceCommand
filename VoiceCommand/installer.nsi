; VoiceCommand Installer
!include "MUI2.nsh"
!include "LogicLib.nsh"

Name "Ari Voice Command Installer"
OutFile "AriVoiceCommandSetup.exe"
InstallDir "$PROGRAMFILES\Ari Voice Command"

!define MUI_ABORTWARNING
!define MUI_ICON "icon.ico"
!define MUI_UNICON "icon.ico"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_LANGUAGE "Korean"

Section "Python 3.11.4" SEC_PYTHON
  ; Python 3.11 설치 여부 확인
  ${If} ${FileExists} "$LOCALAPPDATA\Programs\Python\Python311\python.exe"
    MessageBox MB_OK "Python 3.11이 이미 설치되어 있습니다."
  ${Else}
    MessageBox MB_YESNO "Python 3.11.4를 설치해야 합니다. 지금 설치하시겠습니까?" IDYES installPython IDNO endPython
    installPython:
      ; Python 설치 파일 다운로드
      SetOutPath $TEMP
      File "python-3.11.4-amd64.exe"
      ExecWait '"$TEMP\python-3.11.4-amd64.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0'
      Delete "$TEMP\python-3.11.4-amd64.exe"
    endPython:
  ${EndIf}
SectionEnd

Section "Install Dependencies" SEC_DEPENDENCIES
  SetOutPath $INSTDIR
  File "install_dependencies.py"
  File "requirements.txt"

  MessageBox MB_OK "필요한 패키지들을 설치합니다. 이 과정은 몇 분 정도 소요될 수 있습니다."

  ; install_dependencies.py 실행
  nsExec::ExecToLog '"$LOCALAPPDATA\Programs\Python\Python311\python.exe" "$INSTDIR\install_dependencies.py"'

  Pop $0
  ${If} $0 != 0
    MessageBox MB_OK "패키지 설치 중 오류가 발생했습니다. 로그를 확인해 주세요."
  ${EndIf}
SectionEnd

Section "Ari Voice Command" SEC_VOICECOMMAND
  SetOutPath $INSTDIR
  File "Ari.exe"
  File "Ari.bat"
  File "Main.py"
  File "Config.py"
  File "CharacterWidget.py"
  File "VoiceCommand.py"
  File "ai_assistant.py"
  File "icon.png"
  File "icon.ico"
  File "DNFBitBitv2.ttf"
  File "아리야아_ko_windows_v3_0_0.ppn"
  File "porcupine_params_ko.pv"
  File /r "images"
  
  CreateShortCut "$DESKTOP\Ari.lnk" "$INSTDIR\Ari.exe" "" "$INSTDIR\icon.ico"
  CreateDirectory "$SMPROGRAMS\VoiceCommand"
  CreateShortCut "$SMPROGRAMS\VoiceCommand\Ari.lnk" "$INSTDIR\Ari.exe" "" "$INSTDIR\icon.ico"

  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VoiceCommand" "DisplayName" "Ari Voice Command"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VoiceCommand" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VoiceCommand" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VoiceCommand" "NoRepair" 1
  WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\Ari.exe"
  Delete "$INSTDIR\Ari.bat"
  Delete "$INSTDIR\VoiceCommand.py"
  Delete "$INSTDIR\ai_assistant.py"
  Delete "$INSTDIR\Main.py"
  Delete "$INSTDIR\Config.py"
  Delete "$INSTDIR\CharacterWidget.py"
  Delete "$INSTDIR\icon.png"
  Delete "$INSTDIR\icon.ico"
  Delete "$INSTDIR\logfile.log"
  Delete "$INSTDIR\DNFBitBitv2.ttf"
  Delete "$INSTDIR\아리야아_ko_windows_v3_0_0.ppn"
  Delete "$INSTDIR\porcupine_params_ko.pv"
  Delete "$INSTDIR\install_dependencies.py"
  RMDir /r "$INSTDIR\logs"
  RMDir /r "$INSTDIR\images"
  RMDir /r "$INSTDIR\saved_model"
  Delete "$INSTDIR\requirements.txt"
  RMDir /r "$INSTDIR\__pycache__"
  Delete "$INSTDIR\uninstall.exe"
  RMDir "$INSTDIR"

  Delete "$DESKTOP\Ari.lnk"
  Delete "$SMPROGRAMS\VoiceCommand\Ari.lnk"
  RMDir "$SMPROGRAMS\VoiceCommand"

  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VoiceCommand"
SectionEnd