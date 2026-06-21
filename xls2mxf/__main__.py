"""Точка входа для `python -m xls2mxf`."""
import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main())
