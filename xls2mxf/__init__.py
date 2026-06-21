"""xls2mxf — collecting and assembling broadcast clips from traffic sheets."""
import os
import sys

# Enables ANSI-escape processing on Windows 10+ (for progress bar / colour output).
# Safe on other OSes and in terminals that already support ANSI.
if os.name == "nt":
    os.system("")

# Line-buffered output: in a frozen exe the Windows console otherwise buffers
# text in chunks (especially progress lines in parallel mode). With line-buffering
# each line is flushed immediately.
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except (AttributeError, ValueError):
    pass  # non-standard stdout (piped to file, etc.)

__version__ = "1.0.0"
