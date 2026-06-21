#!/usr/bin/env python3
"""Тонкий лаунчер для PyInstaller: собирается в xls2mxf.exe."""
import sys
import os

if os.name == "nt":
    import ctypes
    ctypes.windll.kernel32.SetConsoleMode(ctypes.windll.kernel32.GetStdHandle(-11), 7)

sys.stdout.reconfigure(line_buffering=True)

from xls2mxf.cli import main

if __name__ == "__main__":
    sys.exit(main())
