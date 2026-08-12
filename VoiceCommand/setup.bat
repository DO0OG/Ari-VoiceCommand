@echo off
rem NOTE: keep this file ASCII-only. cmd.exe reads .bat as the OEM codepage.
rem The bootstrap Python only creates the project venv by default. Packages
rem are installed into that venv, not into the system Python.

for /f "tokens=2 delims=:" %%A in ('chcp') do set "ARI_ORIGINAL_CODEPAGE=%%A"
for /f "tokens=*" %%A in ("%ARI_ORIGINAL_CODEPAGE%") do set "ARI_ORIGINAL_CODEPAGE=%%A"
chcp 65001 >nul

cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "ARI_BOOTSTRAP=py -3.11"
    goto :install
)

python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "ARI_BOOTSTRAP=python"
    goto :install
)

echo [Ari] Python 3.11 was not found.
echo [Ari] Install Python 3.11 and enable the py launcher or PATH entry.
pause
set "ARI_EXIT_CODE=1"
goto :restore_codepage

:install
echo [Ari] Installing project dependencies...
%ARI_BOOTSTRAP% install_dependencies.py %*
if errorlevel 1 goto :failed

echo [Ari] Setup completed successfully.
pause
set "ARI_EXIT_CODE=0"
goto :restore_codepage

:failed
echo [Ari] Setup failed. Review the output above.
pause
set "ARI_EXIT_CODE=1"

:restore_codepage
if defined ARI_ORIGINAL_CODEPAGE chcp %ARI_ORIGINAL_CODEPAGE% >nul
exit /b %ARI_EXIT_CODE%
