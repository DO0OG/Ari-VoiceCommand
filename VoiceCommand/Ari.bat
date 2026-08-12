@echo off
rem Normal use: run Ari.vbs. Use Ari.bat only when you need to see errors.
rem NOTE: keep this file ASCII-only. cmd.exe reads .bat as the OEM codepage
rem (cp949 on Korean Windows), so UTF-8 comments break parsing.

rem Work from the folder holding this file instead of a hardcoded path,
rem so moving or renaming the repository does not silently break the launcher.
cd /d "%~dp0"

rem Force UTF-8 so logs and child-process I/O are not mangled by cp949.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

rem The diagnostic launcher uses python.exe so startup output remains visible.
set "ARI_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%ARI_PYTHON%" goto :no_venv

"%ARI_PYTHON%" Main.py
if errorlevel 1 goto :failed
exit /b 0

:no_venv
echo [Ari] venv not found: %ARI_PYTHON%
echo [Ari] Run setup.bat from the VoiceCommand folder, then try again.
pause
exit /b 1

:failed
echo [Ari] The app stopped with an error. Review the output above.
pause
exit /b 1
