@echo off
REM ============================================================
REM  Run from source on Windows. ASCII-only to avoid codepage issues.
REM  Usage: run.bat           normal start
REM         run.bat --minimized   start in tray
REM ============================================================
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" goto VENV
where pythonw >nul 2>nul
if %errorlevel%==0 goto SYS_PYW
where python >nul 2>nul
if %errorlevel%==0 goto SYS_PY

echo [ERROR] Python 3.10+ not found.
echo         Install Python from https://www.python.org/downloads/
echo         or run build.bat to create a standalone EXE.
pause
exit /b 1

:VENV
start "" ".venv\Scripts\pythonw.exe" "main.py" %*
exit /b 0

:SYS_PYW
start "" pythonw "main.py" %*
exit /b 0

:SYS_PY
start "" python "main.py" %*
exit /b 0
