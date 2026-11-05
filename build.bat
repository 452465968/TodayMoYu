@echo off
REM ============================================================
REM  One-click Windows build. ASCII-only to avoid codepage issues.
REM  Output: dist\ today-mo-yu EXE  (Chinese name) + TodayMoYu.exe
REM ============================================================
setlocal
cd /d "%~dp0"

echo ==========================================================
echo   Build [ Jin Tian Mo Le Ma ] for Windows
echo ==========================================================

where python >nul 2>nul
if %errorlevel% NEQ 0 (
  echo [ERROR] Python 3.10+ not found. https://www.python.org/downloads/
  pause
  exit /b 1
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if %errorlevel% NEQ 0 (
  echo [ERROR] Python 3.10 or newer is required.
  pause
  exit /b 1
)

echo [1/4] Installing dependencies ...
python -m pip install --disable-pip-version-check -r requirements.txt
if %errorlevel% NEQ 0 goto FAIL
python -m pip install --disable-pip-version-check "pyinstaller>=6.0"
if %errorlevel% NEQ 0 goto FAIL

echo [2/4] Checking icon resources ...
if not exist "resources\app.ico" python make_assets.py

echo [3/4] Building single-file EXE ...
python -m PyInstaller --noconfirm --clean app.spec
if %errorlevel% NEQ 0 goto FAIL

echo [4/4] Creating an ASCII-named copy ...
if exist "dist\TodayMoYu.exe" del /Q "dist\TodayMoYu.exe"
for %%f in (dist\*.exe) do copy /Y "%%f" "dist\TodayMoYu.exe" >nul

echo.
echo [OK] Build finished. Look in the dist folder:
echo      Chinese-named EXE : the first .exe in dist\
echo      ASCII-named EXE   : dist\TodayMoYu.exe
echo.
echo Tip: right click the EXE ^> Pin to Start / Send to Desktop.
pause
exit /b 0

:FAIL
echo [ERROR] Build failed. Please read the messages above.
pause
exit /b 1
