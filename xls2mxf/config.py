"""Конфигурация и расположение программы."""
import configparser
import sys
from pathlib import Path

from .constants import CONF_NAME, DEFAULT_CONF


def app_dir() -> Path:
    """Папка, рядом с которой лежат conf и пишется лог.
    - В собранном exe (PyInstaller onefile): папка самого exe.
    - При запуске из исходников: папка главного скрипта (run.py / -m), а не
      папка пакета, чтобы conf/лог лежали рядом с точкой запуска."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    main_mod = sys.modules.get("__main__")
    main_file = getattr(main_mod, "__file__", None)
    if main_file:
        d = Path(main_file).resolve().parent
        # если запущено как `python -m copy_rollers`, __main__ лежит ВНУТРИ пакета —
        # в этом случае conf/лог логичнее держать в рабочей папке, а не в пакете.
        if d == Path(__file__).resolve().parent:
            return Path.cwd()
        return d
    return Path.cwd()


def load_conf() -> dict:
    conf_path = app_dir() / CONF_NAME
    if not conf_path.exists():
        conf_path.write_text(DEFAULT_CONF, encoding="utf-8")
        print(f"[i] Создан {conf_path.name} со значениями по умолчанию.")
    cp = configparser.ConfigParser()
    cp.read(conf_path, encoding="utf-8")
    p = cp["paths"] if cp.has_section("paths") else {}
    c = cp["clipboard"] if cp.has_section("clipboard") else {}
    f = cp["ffmpeg"] if cp.has_section("ffmpeg") else {}
    a = cp["assembly"] if cp.has_section("assembly") else {}
    return {
        "xlsx": p.get("xlsx", "."),
        "src": p.get("src", "."),
        "dst": p.get("dst", "."),
        "customlines": [
            c.get("customline1", "customline1"),
            c.get("customline2", "customline2"),
            c.get("customline3", "customline3"),
        ],
        "ffmpeg": f.get("ffmpeg", "").strip(),
        "ffprobe": f.get("ffprobe", "").strip(),
        "middle": a.get("middle", "Reklama_RTR").strip(),
        "opener": a.get("opener", "").strip(),
        "closer": a.get("closer", "").strip(),
        "backup_source": a.get("backup_source", "").strip(),
        "output_dir": a.get("output_dir", "").strip(),
        "video_mode": a.get("video_mode", "copy").strip().lower(),
        "audio_layout": a.get("audio_layout", "2mono").strip().lower(),
        "workers": a.get("workers", "1").strip(),
    }

