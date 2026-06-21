#!/usr/bin/env python3
"""Тонкий лаунчер для PyInstaller: собирается в copy_rollers.exe."""
import sys
import os

if os.name == "nt":
    import ctypes
    ctypes.windll.kernel32.SetConsoleMode(ctypes.windll.kernel32.GetStdHandle(-11), 7)

sys.stdout.reconfigure(line_buffering=True)

from copy_rollers.cli import main

if __name__ == "__main__":
    sys.exit(main())
