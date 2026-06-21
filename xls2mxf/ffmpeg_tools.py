"""Обёртки над ffmpeg/ffprobe: поиск бинарников, длительность, аудио, запуск."""
import os
import subprocess
from pathlib import Path

from .errors import AssemblyError
from .config import app_dir


def _resolve_tool(name: str, conf_path: str) -> str:
    """Ищет бинарник: явный путь из conf -> рядом с программой -> PATH."""
    import shutil as _sh
    exe = name + (".exe" if os.name == "nt" else "")
    # 1) путь из conf
    if conf_path:
        p = Path(conf_path)
        if p.is_file():
            return str(p)
    # 2) рядом с программой
    local = app_dir() / exe
    if local.is_file():
        return str(local)
    # 3) PATH
    found = _sh.which(name)
    if found:
        return found
    raise AssemblyError(
        f"Не найден {name}. Положите {exe} рядом с программой, "
        f"укажите путь в conf [ffmpeg] или добавьте в PATH."
    )



def get_duration(path: Path, ffprobe: str) -> float:
    """Длительность файла в секундах через ffprobe."""
    import subprocess
    cmd = [ffprobe, "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    out = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if out.returncode != 0:
        raise AssemblyError(f"ffprobe не смог прочитать {path.name}: {out.stderr.strip()}")
    try:
        return float(out.stdout.strip())
    except ValueError:
        raise AssemblyError(f"ffprobe вернул некорректную длительность для {path.name}")



def probe_audio_streams(path: Path, ffprobe: str) -> list:
    """Возвращает список каналов по аудиодорожкам, напр. [1,1] или [2] или []."""
    import subprocess, json
    cmd = [ffprobe, "-v", "error", "-select_streams", "a",
           "-show_entries", "stream=index,channels", "-of", "json", str(path)]
    out = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if out.returncode != 0:
        raise AssemblyError(f"ffprobe не смог прочитать аудио {path.name}: {out.stderr.strip()}")
    try:
        streams = json.loads(out.stdout).get("streams", [])
    except json.JSONDecodeError:
        raise AssemblyError(f"ffprobe вернул некорректный JSON для {path.name}")
    return [s.get("channels") for s in streams]



def classify_audio_layout(chans: list) -> str:
    """Классифицирует раскладку по списку каналов:
       '2mono'  — целевая (две моно), не требует правки;
       '1stereo'— одна стерео, раскладывается на 2 моно при сборке;
       'none'   — нет аудио (критическая ошибка);
       'fixable'— всё прочее (1 моно, 3+ дорожки и т.п.): приводимо к 2 моно."""
    if chans == [1, 1]:
        return "2mono"
    if chans == [2]:
        return "1stereo"
    if not chans:
        return "none"
    return "fixable"



def probe_audio_layout(path: Path, ffprobe: str) -> str:
    """Совместимость: '2mono' | '1stereo' | 'none' | 'fixable'."""
    return classify_audio_layout(probe_audio_streams(path, ffprobe))


# ---------- нарезка таблицы на блоки ----------


def _run_ffmpeg(cmd: list, ffmpeg: str, out_path: Path, log) -> None:
    import subprocess
    # stdin=DEVNULL: иначе ffmpeg съедает stdin (например ответ y/n пользователя)
    res = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if res.returncode != 0:
        tail = "\n".join(res.stderr.strip().splitlines()[-12:])
        raise AssemblyError(
            f"ffmpeg не смог собрать {out_path.name}.\n{tail}"
        )


# ---------- ОБРАБОТЧИК 3: приведение аудио к эфирному формату ----------
