@echo off
chcp 65001 >nul
setlocal

echo ============================================
echo   Сборка xls2mxf.exe
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
if not exist "xls2mxf\" (
    echo [!] Рядом с батником нет папки пакета xls2mxf\
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
python -m PyInstaller --onefile --console --name xls2mxf ^
    --collect-submodules xls2mxf ^
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
echo   Экзешник: dist\xls2mxf.exe
echo ============================================
echo.
echo Дальше: скопируйте dist\xls2mxf.exe куда удобно,
echo положите рядом xls2mxf.conf и (по желанию) ffmpeg.exe/ffprobe.exe.
echo.
pause
