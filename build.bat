@echo off
chcp 65001 >nul
setlocal

echo ============================================
echo   Building xls2mxf.exe
echo ============================================
echo.

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [!] Python not found in PATH.
    echo     Install Python from https://www.python.org/downloads/
    echo     and check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

if not exist "run.py" (
    echo [!] run.py not found next to this script.
    echo.
    pause
    exit /b 1
)
if not exist "xls2mxf\" (
    echo [!] Package folder xls2mxf\ not found next to this script.
    echo.
    pause
    exit /b 1
)

echo [1/2] Installing dependencies (pyinstaller, openpyxl)...
python -m pip install --upgrade pip >nul 2>nul
python -m pip install pyinstaller openpyxl
if errorlevel 1 (
    echo.
    echo [!] Failed to install dependencies. Check your internet connection and PATH.
    pause
    exit /b 1
)
echo.

echo [2/2] Building exe...
python -m PyInstaller --onefile --console --name xls2mxf ^
    --collect-submodules xls2mxf ^
    --collect-all openpyxl ^
    run.py
if errorlevel 1 (
    echo.
    echo [!] Build failed.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Done!
echo   Executable: dist\xls2mxf.exe
echo ============================================
echo.
echo Next: copy dist\xls2mxf.exe wherever convenient,
echo place xls2mxf.conf next to it and optionally ffmpeg.exe/ffprobe.exe.
echo.
pause
