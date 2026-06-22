#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "============================================"
echo "  Building xls2mxf (Linux)"
echo "============================================"
echo

if ! command -v python3 &>/dev/null; then
    echo "[!] python3 not found in PATH."
    echo "    Install it with your package manager, e.g.:"
    echo "      sudo apt install python3 python3-pip"
    echo "      sudo dnf install python3 python3-pip"
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
echo "ffmpeg/ffprobe must be in PATH or placed next to the binary."
echo
