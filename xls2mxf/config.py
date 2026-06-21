"""Configuration loading and app directory resolution."""
import configparser
import sys
from pathlib import Path

from .constants import CONF_NAME, DEFAULT_CONF


def app_dir() -> Path:
    """Directory where conf and log files are stored.
    - Frozen exe (PyInstaller onefile): folder containing the exe.
    - Running from source: folder of the entry script (run.py / -m), not the
      package folder, so conf/log stay next to the launch point."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    main_mod = sys.modules.get("__main__")
    main_file = getattr(main_mod, "__file__", None)
    if main_file:
        d = Path(main_file).resolve().parent
        # when run as `python -m xls2mxf`, __main__ lives INSIDE the package —
        # in that case keep conf/log in the working directory, not inside the package.
        if d == Path(__file__).resolve().parent:
            return Path.cwd()
        return d
    return Path.cwd()


def load_conf() -> dict:
    conf_path = app_dir() / CONF_NAME
    if not conf_path.exists():
        conf_path.write_text(DEFAULT_CONF, encoding="utf-8")
        print(f"[i] Created {conf_path.name} with default values.")
        print( "[i] Block assembly runs SEQUENTIALLY (workers=1).")
        print( "    Safe mode: errors stop assembly and prompt for confirmation.")
        print(f"    For parallel assembly set workers=N in [{conf_path.name}] under [assembly].")
        print()
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
        "output_format": a.get("output_format", "mxf").strip().lower(),
        "h264_bitrate": a.get("h264_bitrate", "16m").strip(),
        "temp_dir": a.get("temp_dir", "").strip(),
        "workers": a.get("workers", "1").strip(),
    }
