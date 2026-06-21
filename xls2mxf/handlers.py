"""Error handlers: fallback recovery, duration check and diagnosis."""
from pathlib import Path

from .constants import FPS, EXT
from .errors import AssemblyError
from .ffmpeg_tools import get_duration
from .assembly import transcode_avi_to_xdcam
from .ui import _red


def recover_missing_from_backup(missing_ids: list, backup_dir: Path, src_dir: Path,
                                ffmpeg: str, log) -> tuple:
    """For each missing ID, looks for <ID>.avi in backup_dir, transcodes it to
    broadcast <ID>.mxf, and places it in src_dir. Returns (recovered, still_missing)."""
    recovered = []
    still_missing = []
    # .avi filenames may have any case — build an index keyed by lowercase stem
    index = {}
    if backup_dir.is_dir():
        for f in backup_dir.iterdir():
            if f.is_file() and f.suffix.lower() == ".avi":
                index[f.stem] = f
    for fid in missing_ids:
        avi = index.get(str(fid))
        if not avi:
            still_missing.append(fid)
            continue
        out_mxf = src_dir / f"{fid}{EXT}"
        try:
            transcode_avi_to_xdcam(avi, out_mxf, ffmpeg, log)
            recovered.append(fid)
            log.log(f"  recovered: {avi.name} -> {out_mxf.name}", to_console=False)
        except AssemblyError as e:
            still_missing.append(fid)
            log.log(f"  [!] failed to transcode {avi.name}: {e}", to_console=False)
    return recovered, still_missing


# ---------- duration check (handler 2) ----------


def verify_block_duration(out_path: Path, itogo: int, d_open: float,
                          d_close: float, ffprobe: str) -> tuple:
    """Frame-accurate comparison: (d_total - d_open - d_close) vs itogo.
    Returns (ok, expected_frames, got_frames)."""
    d_total = get_duration(out_path, ffprobe)
    d_blocks = d_total - d_open - d_close
    got_frames = round(d_blocks * FPS)
    expected_frames = round(itogo * FPS)
    return (got_frames == expected_frames, expected_frames, got_frames)



def diagnose_block_duration(block: dict, src_dir: Path, ffprobe: str, log) -> dict:
    """HANDLER 2. Called when a block duration mismatch is detected.
    Walks the unique clips of the block and compares their real duration (ffprobe)
    against the table chron (block['chron']) in frames. Prints mismatches in red.
    Returns {'mismatched': [...], 'all_match': bool}."""
    chron = block.get("chron", {})
    mismatched = []
    checked = set()
    for fid in block["ids"]:
        if fid in checked:
            continue
        checked.add(fid)
        f = src_dir / f"{fid}{EXT}"
        expected_sec = chron.get(fid)
        if expected_sec is None:
            mismatched.append((fid, None, None, "no duration in table"))
            continue
        if not f.is_file():
            mismatched.append((fid, expected_sec, None, "file missing"))
            continue
        try:
            dur = get_duration(f, ffprobe)
        except AssemblyError:
            mismatched.append((fid, expected_sec, None, "ffprobe failed to read"))
            continue
        got_frames = round(dur * FPS)
        exp_frames = round(expected_sec * FPS)
        if got_frames != exp_frames:
            mismatched.append((fid, exp_frames, got_frames, "duration mismatch"))

    all_match = not mismatched
    # output
    log.log("", to_console=False)
    log.log(f"[HANDLER 2] Diagnosing block {block['time']}:", to_console=False)
    if mismatched:
        print(_red(f"  Mismatched clips in block {block['time']}:"))
        for fid, exp, got, why in mismatched:
            if exp is not None and got is not None:
                line = f"    {fid}{EXT}: expected {exp} frames, got {got} ({why})"
            else:
                line = f"    {fid}{EXT}: {why} (expected {exp} frames)"
            print(_red(line))
            log.log("  " + line.strip(), to_console=False)
    else:
        msg = (f"  All clips in block {block['time']} match their individual durations, "
               f"but the total does not. Check ИТОГО in the table and wrapper durations.")
        print(_red(msg))
        log.log(msg.strip(), to_console=False)
    return {"mismatched": mismatched, "all_match": all_match}
