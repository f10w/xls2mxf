"""Console UI: logger, progress bar, colour, dialogs, clipboard."""
import datetime as dt
import os
import re
import sys
from pathlib import Path


class Logger:
    """Mirrors messages to the console and accumulates lines for the log file."""
    def __init__(self):
        self.lines = []

    def log(self, msg="", to_console=True):
        self.lines.append(msg)
        if to_console:
            print(msg)

    def save(self, path: Path):
        path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


# ---------- date ----------


def _red(text: str) -> str:
    """Red text for the console (ANSI). Log files receive the raw string."""
    return f"\x1b[31m{text}\x1b[0m"



def parse_ddmmyy(s: str) -> dt.date:
    """DDMMYY -> date. Raises ValueError on invalid input."""
    if not re.fullmatch(r"\d{6}", s):
        raise ValueError("exactly 6 digits required")
    d, m, y = int(s[:2]), int(s[2:4]), int(s[4:6])
    return dt.date(2000 + y, m, d)



def ask_date() -> str:
    tomorrow = dt.date.today() + dt.timedelta(days=1)
    default = tomorrow.strftime("%d%m%y")
    while True:
        raw = input(f"Enter date DDMMYY (Enter = {default}): ").strip()
        if raw == "":
            return default
        try:
            parse_ddmmyy(raw)
            return raw
        except ValueError as e:
            print(f"  [!] Invalid date ({e}). Try again.")



def ask_mode() -> str:
    """Asks the user for a run mode. Returns 'manual' | 'auto'."""
    print("Select run mode:")
    print("  1 — manual (copy clips to folder)")
    print("  2 — auto (assemble broadcast blocks via ffmpeg)")
    while True:
        raw = input("Mode (1/2): ").strip()
        if raw == "1":
            return "manual"
        if raw == "2":
            return "auto"
        print("  [!] Enter 1 or 2.")


# ---------- progress bar (two-line, stdlib) ----------


class Progress:
    """Bar line + current-file line below. Redrawn in place with ANSI escape codes."""
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
        # truncate second line to prevent wrapping
        line2 = line2[:78]
        if self._started:
            sys.stdout.write("\x1b[2A")  # move cursor up 2 lines
        sys.stdout.write("\x1b[2K" + line1 + "\n")  # clear line, bar
        sys.stdout.write("\x1b[2K" + line2 + "\n")  # clear line, file
        sys.stdout.flush()
        self._started = True

    def update(self, current: str):
        self.n += 1
        self._render(current)

    def finish(self):
        if self._started:
            sys.stdout.write("\n")
            sys.stdout.flush()


# ---------- main logic ----------


def ask_continue_after_error() -> bool:
    """Asks whether to continue assembling remaining blocks. EOF -> False (stop)."""
    try:
        ans = input(_red("Continue assembling remaining blocks? (y/n): ")).strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes", "д", "да")


# ---------- table selection for auto mode ----------


def copy_to_clipboard(text: str) -> bool:
    """Puts text into the clipboard. On Windows uses clip.exe (no dependencies).
    On other OSes tries xclip/pbcopy — for compatibility during development."""
    import subprocess
    try:
        if os.name == "nt":
            # clip.exe expects input in the console code page; utf-16-le is safer for Cyrillic
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


def notify_windows(title: str, body: str) -> None:
    """Balloon-tip notification via PowerShell. Non-blocking, silently ignores errors."""
    import subprocess
    if os.name != "nt":
        return
    t = title.replace("'", "")
    b = body.replace("'", "")
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$n = New-Object System.Windows.Forms.NotifyIcon; "
        "$n.Icon = [System.Drawing.SystemIcons]::Information; "
        "$n.Visible = $true; "
        f"$n.ShowBalloonTip(8000, '{t}', '{b}', "
        "[System.Windows.Forms.ToolTipIcon]::Info); "
        "Start-Sleep -Seconds 9; $n.Dispose()"
    )
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-WindowStyle", "Hidden", "-Command", ps],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    except Exception:
        pass


# ======================= AUTO MODE: BROADCAST ASSEMBLY =======================
