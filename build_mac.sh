#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "============================================"
echo "  Building xls2mxf (macOS)"
echo "============================================"
echo

if ! command -v python3 &>/dev/null; then
    echo "[!] python3 not found in PATH."
    echo "    Install it from https://www.python.org/downloads/"
    echo "    or via Homebrew:  brew install python"
    exit 1
fi

if [ ! -f "run.py" ]; then
    echo "[!] run.py not found next to this script."
    exit 1
fi
if [ ! -d "xls2mxf" ]; then
    echo "[!] Package folder xls2mxf/ not found next to this script."
    exit 1
fi

echo "[1/2] Installing dependencies (pyinstaller, openpyxl)..."
python3 -m pip install --upgrade pip --quiet
python3 -m pip install pyinstaller openpyxl
echo

echo "[2/2] Building binary..."
python3 -m PyInstaller --onefile --console --name xls2mxf \
    --collect-submodules xls2mxf \
    --collect-all openpyxl \
    run.py

echo
echo "============================================"
echo "  Done!"
echo "  Binary: dist/xls2mxf"
echo "============================================"
echo
echo "Next: copy dist/xls2mxf wherever convenient,"
echo "place xls2mxf.conf next to it."
echo "ffmpeg/ffprobe must be in PATH (brew install ffmpeg)"
echo "or placed next to the binary."
echo
echo "Note: macOS may block unsigned binaries on first run."
echo "If you see a security warning, go to:"
echo "  System Settings -> Privacy & Security -> Allow Anyway"
echo
