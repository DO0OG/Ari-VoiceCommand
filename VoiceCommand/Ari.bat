@echo off
rem Runs Ari fully in the background - no console/terminal window stays open.
rem NOTE: keep this file ASCII-only. cmd.exe reads .bat as the OEM codepage
rem (cp949 on Korean Windows), so UTF-8 comments break parsing.

rem Work from the folder holding this file instead of a hardcoded path,
rem so moving or renaming the repository does not silently break the launcher.
cd /d "%~dp0"

rem Force UTF-8 so logs and child-process I/O are not mangled by cp949.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

rem pythonw.exe has no console of its own, so no window ever flashes or
rem stays minimized in the taskbar (unlike python.exe, which shares whatever
rem console launched this .bat and can't be fully hidden from a child process).
set "ARI_PYTHON=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%ARI_PYTHON%" goto :no_venv

if not exist "%~dp0.ari_runtime" mkdir "%~dp0.ari_runtime"
set "ARI_LOG=%~dp0.ari_runtime\launcher_error.log"

rem "start" launches pythonw detached from this cmd window, so this .bat
rem exits immediately afterward and its own window closes right away.
start "" /min "%ARI_PYTHON%" "%~dp0Main.py" 2>"%ARI_LOG%"
exit /b 0

:no_venv
echo [Ari] venv not found: %ARI_PYTHON%
echo [Ari] Run setup.bat from the VoiceCommand folder, then try again.
pause
exit /b 1
