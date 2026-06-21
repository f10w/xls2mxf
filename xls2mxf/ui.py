"""Консольный UI: логгер, прогресс-бар, цвет, диалоги, буфер обмена."""
import datetime as dt
import os
import re
import sys
from pathlib import Path


class Logger:
    """Дублирует сообщения в консоль и копит строки для файла лога."""
    def __init__(self):
        self.lines = []

    def log(self, msg="", to_console=True):
        self.lines.append(msg)
        if to_console:
            print(msg)

    def save(self, path: Path):
        path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


# ---------- дата ----------


def _red(text: str) -> str:
    """Красный текст для консоли (ANSI). В файл лога escape-коды не пишем."""
    return f"\x1b[31m{text}\x1b[0m"



def parse_ddmmyy(s: str) -> dt.date:
    """ДДММГГ -> date. Бросает ValueError при некорректной дате."""
    if not re.fullmatch(r"\d{6}", s):
        raise ValueError("нужно ровно 6 цифр")
    d, m, y = int(s[:2]), int(s[2:4]), int(s[4:6])
    return dt.date(2000 + y, m, d)



def ask_date() -> str:
    tomorrow = dt.date.today() + dt.timedelta(days=1)
    default = tomorrow.strftime("%d%m%y")
    while True:
        raw = input(f"Введите дату ДДММГГ (Enter = {default}): ").strip()
        if raw == "":
            return default
        try:
            parse_ddmmyy(raw)
            return raw
        except ValueError as e:
            print(f"  [!] Некорректная дата ({e}). Попробуйте ещё раз.")



def ask_mode() -> str:
    """Спрашивает режим работы. Возвращает 'manual' | 'auto'."""
    print("Выберите режим работы:")
    print("  1 — ручная сборка (копирование роликов в папку)")
    print("  2 — автоматическая сборка эфира (склейка блоков через ffmpeg)")
    while True:
        raw = input("Режим (1/2): ").strip()
        if raw == "1":
            return "manual"
        if raw == "2":
            return "auto"
        print("  [!] Введите 1 или 2.")


# ---------- прогресс-бар (две строки, stdlib) ----------


class Progress:
    """Строка с баром + строка снизу с текущим файлом. Перерисовка \\r."""
    def __init__(self, total: int, width: int = 36):
        self.total = max(total, 1)
        self.width = width
        self.n = 0
        self._started = False

    def _render(self, current: str):
        pct = self.n / self.total
        filled = int(self.width * pct)
        bar = "#" * filled + "-" * (self.width - filled)
        line1 = f"[{bar}] {pct*100:5.1f}%  ({self.n}/{self.total})"
        line2 = f"  -> {current}"
        # обрезаем вторую строку, чтобы не переносилась
        line2 = line2[:78]
        if self._started:
            sys.stdout.write("\x1b[2A")  # курсор на 2 строки вверх
        sys.stdout.write("\x1b[2K" + line1 + "\n")  # очистить строку, бар
        sys.stdout.write("\x1b[2K" + line2 + "\n")  # очистить строку, файл
        sys.stdout.flush()
        self._started = True

    def update(self, current: str):
        self.n += 1
        self._render(current)

    def finish(self):
        if self._started:
            sys.stdout.write("\n")
            sys.stdout.flush()


# ---------- основная логика ----------


def ask_continue_after_error() -> bool:
    """Спрашивает, продолжать ли сборку остальных блоков. EOF -> False (стоп)."""
    try:
        ans = input(_red("Продолжить сборку остальных блоков? (y/n): ")).strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes", "д", "да")


# ---------- выбор таблицы для авто-режима ----------


def copy_to_clipboard(text: str) -> bool:
    """Кладёт текст в буфер обмена. На Windows через clip.exe (без зависимостей).
    На других ОС пробует xclip/pbcopy — для совместимости при отладке."""
    import subprocess
    try:
        if os.name == "nt":
            # clip.exe ожидает ввод в кодировке консоли; utf-16-le надёжнее для кириллицы
            p = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
            p.communicate(input=text.encode("utf-16-le"))
            return p.returncode == 0
        else:
            for cmd in (["xclip", "-selection", "clipboard"], ["pbcopy"]):
                try:
                    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                    p.communicate(input=text.encode("utf-8"))
                    if p.returncode == 0:
                        return True
                except FileNotFoundError:
                    continue
            return False
    except Exception:
        return False


# ======================= АВТО-РЕЖИМ: СБОРКА ЭФИРА =======================
