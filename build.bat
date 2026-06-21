@echo off
chcp 65001 >nul
setlocal

echo ============================================
echo   Сборка copy_rollers.exe
echo ============================================
echo.

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [!] Python не найден в PATH.
    echo     Установите Python с https://www.python.org/downloads/
    echo     и при установке отметьте "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

if not exist "run.py" (
    echo [!] Рядом с батником нет файла run.py
    echo.
    pause
    exit /b 1
)
if not exist "copy_rollers\" (
    echo [!] Рядом с батником нет папки пакета copy_rollers\
    echo.
    pause
    exit /b 1
)

echo [1/2] Установка зависимостей (pyinstaller, openpyxl)...
python -m pip install --upgrade pip >nul 2>nul
python -m pip install pyinstaller openpyxl
if errorlevel 1 (
    echo.
    echo [!] Не удалось установить зависимости. Проверьте интернет/PATH.
    pause
    exit /b 1
)
echo.

echo [2/2] Сборка exe...
python -m PyInstaller --onefile --console --name copy_rollers ^
    --collect-submodules copy_rollers ^
    --collect-all openpyxl ^
    run.py
if errorlevel 1 (
    echo.
    echo [!] Сборка завершилась с ошибкой.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Готово!
echo   Экзешник: dist\copy_rollers.exe
echo ============================================
echo.
echo Дальше: скопируйте dist\copy_rollers.exe куда удобно,
echo положите рядом copy_rollers.conf и (по желанию) ffmpeg.exe/ffprobe.exe.
echo.
pause
