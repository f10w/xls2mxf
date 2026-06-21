"""Обработчики ошибок: добор из резерва, чек и диагностика хронометража."""
from pathlib import Path

from .constants import FPS, EXT
from .errors import AssemblyError
from .ffmpeg_tools import get_duration
from .assembly import transcode_avi_to_xdcam
from .ui import _red


def recover_missing_from_backup(missing_ids: list, backup_dir: Path, src_dir: Path,
                                ffmpeg: str, log) -> tuple:
    """Для каждого недостающего ID ищет <ID>.avi в backup_dir, перекодирует в
    эфирный <ID>.mxf и кладёт в src_dir. Возвращает (recovered, still_missing)."""
    recovered = []
    still_missing = []
    # .avi регистр может быть любым — соберём индекс по нижнему регистру stem
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
            log.log(f"  добор: {avi.name} -> {out_mxf.name}", to_console=False)
        except AssemblyError as e:
            still_missing.append(fid)
            log.log(f"  [!] не удалось перекодировать {avi.name}: {e}", to_console=False)
    return recovered, still_missing


# ---------- проверка хронометража (обработчик 2) ----------


def verify_block_duration(out_path: Path, itogo: int, d_open: float,
                          d_close: float, ffprobe: str) -> tuple:
    """Сравнивает в кадрах: (d_total - d_open - d_close) с itogo.
    Возвращает (ok, expected_frames, got_frames)."""
    d_total = get_duration(out_path, ffprobe)
    d_blocks = d_total - d_open - d_close
    got_frames = round(d_blocks * FPS)
    expected_frames = round(itogo * FPS)
    return (got_frames == expected_frames, expected_frames, got_frames)



def diagnose_block_duration(block: dict, src_dir: Path, ffprobe: str, log) -> dict:
    """ОБРАБОТЧИК 2. Вызывается когда хронометраж блока не сошёлся.
    Проходит уникальные ролики блока, сверяет реальную длительность (ffprobe)
    с хрон из таблицы (block['chron']) в кадрах. Печатает красным несовпавшие.
    Возвращает {'mismatched': [...], 'all_match': bool}."""
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
            mismatched.append((fid, None, None, "нет хрон в таблице"))
            continue
        if not f.is_file():
            mismatched.append((fid, expected_sec, None, "файл отсутствует"))
            continue
        try:
            dur = get_duration(f, ffprobe)
        except AssemblyError:
            mismatched.append((fid, expected_sec, None, "ffprobe не прочитал"))
            continue
        got_frames = round(dur * FPS)
        exp_frames = round(expected_sec * FPS)
        if got_frames != exp_frames:
            mismatched.append((fid, exp_frames, got_frames, "длительность не совпала"))

    all_match = not mismatched
    # вывод
    log.log("", to_console=False)
    log.log(f"[ОБРАБОТЧИК 2] Диагностика блока {block['time']}:", to_console=False)
    if mismatched:
        print(_red(f"  Несовпадающие ролики в блоке {block['time']}:"))
        for fid, exp, got, why in mismatched:
            if exp is not None and got is not None:
                line = f"    {fid}{EXT}: ожидалось {exp} кадров, получено {got} ({why})"
            else:
                line = f"    {fid}{EXT}: {why} (ожидалось {exp} кадров)"
            print(_red(line))
            log.log("  " + line.strip(), to_console=False)
    else:
        msg = (f"  Все ролики блока {block['time']} совпадают по хронометражу, "
               f"а блок в сумме — нет. Проверьте ИТОГО в таблице и длительность обёрток.")
        print(_red(msg))
        log.log(msg.strip(), to_console=False)
    return {"mismatched": mismatched, "all_match": all_match}

