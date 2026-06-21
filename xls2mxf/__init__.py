"""xls2mxf — сбор и сборка эфирных роликов из траффик-листов."""
import os
import sys

# На Windows 10+ включает обработку ANSI-escape в консоли (для прогресс-бара/цвета).
# Безвредно на других ОС и в уже-ANSI-совместимых терминалах.
if os.name == "nt":
    os.system("")

# Линейная буферизация вывода: в собранном exe Windows-консоль иначе показывает
# текст пачками (особенно строки прогресса в параллельном режиме). С line-buffering
# каждая строка выводится сразу по готовности.
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except (AttributeError, ValueError):
    pass  # на случай нестандартного stdout (перенаправление в файл и т.п.)

__version__ = "1.0.0"

