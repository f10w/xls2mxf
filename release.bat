@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

:: ---- read version from xls2mxf/__init__.py ----
for /f "delims=" %%v in ('python -c "from xls2mxf import __version__; print(__version__)"') do set VERSION=%%v
if "%VERSION%"=="" (
    echo [!] Could not read version from xls2mxf/__init__.py
    pause
    exit /b 1
)

echo ============================================
echo   Building xls2mxf.exe  v%VERSION%
echo ============================================
echo.

:: ---- checks ----
where python >nul 2>nul
if errorlevel 1 (
    echo [!] Python not found in PATH.
    pause
    exit /b 1
)
if not exist "run.py" (
    echo [!] run.py not found next to this script.
    pause
    exit /b 1
)
if not exist "xls2mxf\" (
    echo [!] Package folder xls2mxf\ not found next to this script.
    pause
    exit /b 1
)

:: ---- dependencies ----
echo [1/3] Installing dependencies (pyinstaller, openpyxl)...
python -m pip install --upgrade pip >nul 2>nul
python -m pip install pyinstaller openpyxl
if errorlevel 1 (
    echo.
    echo [!] Failed to install dependencies.
    pause
    exit /b 1
)
echo.

:: ---- build ----
echo [2/3] Building exe...
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

:: ---- package into releases\ ----
echo [3/3] Packaging release...
set OUT=releases\xls2mxf_v%VERSION%
if exist "%OUT%\" rmdir /s /q "%OUT%"
mkdir "%OUT%"

copy /y "dist\xls2mxf.exe"  "%OUT%\xls2mxf.exe"  >nul
copy /y "build.txt"          "%OUT%\README.txt"    >nul

:: zip via PowerShell (available on Windows 10+)
set ZIP=releases\xls2mxf_v%VERSION%.zip
if exist "%ZIP%" del /q "%ZIP%"
powershell -NoProfile -Command ^
    "Compress-Archive -Path '%OUT%\*' -DestinationPath '%ZIP%'"
if errorlevel 1 (
    echo [!] Zip failed — folder is ready but no archive was created.
) else (
    echo     Archive: %ZIP%
)

echo.
echo ============================================
echo   Done!  v%VERSION%
echo   Folder:  %OUT%\
echo   Archive: releases\xls2mxf_v%VERSION%.zip
echo ============================================
echo.
pause
