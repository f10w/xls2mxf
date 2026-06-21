"""ffmpeg/ffprobe wrappers: binary lookup, duration, audio probing, subprocess runner."""
import os
import subprocess
from pathlib import Path

from .errors import AssemblyError
from .config import app_dir


def _resolve_tool(name: str, conf_path: str) -> str:
    """Resolves a binary: explicit conf path -> next to the program -> PATH."""
    import shutil as _sh
    exe = name + (".exe" if os.name == "nt" else "")
    # 1) path from conf
    if conf_path:
        p = Path(conf_path)
        if p.is_file():
            return str(p)
    # 2) next to the program
    local = app_dir() / exe
    if local.is_file():
        return str(local)
    # 3) PATH
    found = _sh.which(name)
    if found:
        return found
    raise AssemblyError(
        f"{name} not found. Place {exe} next to the program, "
        f"set the path in conf [ffmpeg], or add it to PATH."
    )



def get_duration(path: Path, ffprobe: str) -> float:
    """Returns file duration in seconds via ffprobe."""
    import subprocess
    cmd = [ffprobe, "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    out = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if out.returncode != 0:
        raise AssemblyError(f"ffprobe could not read {path.name}: {out.stderr.strip()}")
    try:
        return float(out.stdout.strip())
    except ValueError:
        raise AssemblyError(f"ffprobe returned invalid duration for {path.name}")



def probe_audio_streams(path: Path, ffprobe: str) -> list:
    """Returns list of channel counts per audio stream, e.g. [1,1] or [2] or []."""
    import subprocess, json
    cmd = [ffprobe, "-v", "error", "-select_streams", "a",
           "-show_entries", "stream=index,channels", "-of", "json", str(path)]
    out = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if out.returncode != 0:
        raise AssemblyError(f"ffprobe could not read audio from {path.name}: {out.stderr.strip()}")
    try:
        streams = json.loads(out.stdout).get("streams", [])
    except json.JSONDecodeError:
        raise AssemblyError(f"ffprobe returned invalid JSON for {path.name}")
    return [s.get("channels") for s in streams]



def classify_audio_layout(chans: list) -> str:
    """Classifies audio layout from a channel list:
       '2mono'  — target layout (two mono tracks), no fix needed;
       '1stereo' — one stereo track, split to 2 mono during assembly;
       'none'   — no audio (critical error);
       'fixable' — everything else (1 mono, 3+ tracks, etc.): convertible to 2 mono."""
    if chans == [1, 1]:
        return "2mono"
    if chans == [2]:
        return "1stereo"
    if not chans:
        return "none"
    return "fixable"



def probe_audio_layout(path: Path, ffprobe: str) -> str:
    """Convenience wrapper: '2mono' | '1stereo' | 'none' | 'fixable'."""
    return classify_audio_layout(probe_audio_streams(path, ffprobe))


# ---------- block assembly helpers ----------


def _run_ffmpeg(cmd: list, ffmpeg: str, out_path: Path, log) -> None:
    import subprocess
    # stdin=DEVNULL: otherwise ffmpeg consumes stdin (e.g., user's y/n answers)
    res = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if res.returncode != 0:
        tail = "\n".join(res.stderr.strip().splitlines()[-12:])
        raise AssemblyError(
            f"ffmpeg failed to assemble {out_path.name}.\n{tail}"
        )


# ---------- HANDLER 3: normalize audio to broadcast format ----------
