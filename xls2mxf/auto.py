"""Auto mode: table selection, dry-run check, broadcast assembly, report."""
import os
from pathlib import Path

from .constants import FPS, EXT, FORMAT_EXT
from .errors import AssemblyError
from .config import app_dir
from .ui import Logger, Progress, _red, ask_continue_after_error
from .tables import (parse_blocks, find_xlsx_for_date, time_to_filepart,
                     ddmmyy_to_dashed, check_all_files_exist)
from .ffmpeg_tools import (_resolve_tool, get_duration, probe_audio_streams,
                           classify_audio_layout, probe_audio_layout)
from .assembly import (assemble_block_copy, assemble_block_reencode,
                       fix_audio_to_2mono)
from .handlers import (recover_missing_from_backup, verify_block_duration,
                       diagnose_block_duration)


def pick_table_for_assembly(xlsx_dir: Path, ddmmyy: str, log,
                             interactive: bool = True) -> Path:
    """1) Traffic sheet matching the date -> use it.
       2) No traffic sheet but another xlsx found -> warn and ask y/n (or auto-accept).
       3) Nothing found -> error."""
    candidates = find_xlsx_for_date(xlsx_dir, ddmmyy)
    if not candidates:
        raise AssemblyError(f"No tables found matching date {ddmmyy}.")
    traffic = [x for x in candidates if x.name.lower().startswith("траффик-лист")]
    if traffic:
        return traffic[0]
    # non-standard file
    other = candidates[0]
    print(f"[!] Standard table 'Траффик-лист_*' for {ddmmyy} not found.")
    print(f"    Found non-standard file: {other.name}")
    if interactive:
        try:
            ans = input("    Use it for assembly? (y/n): ").strip().lower()
        except EOFError:
            ans = "n"
    else:
        print("    Using automatically (running without --manual).")
        ans = "y"
    if ans in ("y", "yes", "д", "да"):
        log.log(f"[!] WARNING: using NON-STANDARD file {other.name}", to_console=False)
        return other
    raise AssemblyError("Assembly cancelled: no suitable table selected.")


# ---------- auto mode orchestrator ----------


def run_dry_check(conf: dict, ddmmyy: str, xlsx_dir: Path, src_dir: Path,
                  dst_root: Path, log, interactive: bool = True) -> int:
    """DRY-RUN: all checks without any transcode or file writes.
    Shows whether the session is ready for assembly."""
    print(f"\n=== CHECK (dry-run) for {ddmmyy} ===\n")
    problems = []   # critical blockers
    warnings = []   # non-critical (require action but won't stop assembly)

    # tools
    try:
        ffmpeg = _resolve_tool("ffmpeg", conf["ffmpeg"])
        ffprobe = _resolve_tool("ffprobe", conf["ffprobe"])
        print(f"ffmpeg:  {ffmpeg}")
        print(f"ffprobe: {ffprobe}")
    except AssemblyError as e:
        print(_red(f"[CRITICAL] {e}"))
        return 1

    # wrappers
    opener = Path(conf["opener"]) if conf["opener"] else None
    closer = Path(conf["closer"]) if conf["closer"] else None
    for nm, w in (("opener", opener), ("closer", closer)):
        if not w or not w.is_file():
            problems.append(f"Wrapper {nm} not found: {conf.get(nm)!r}")
        else:
            try:
                lay = probe_audio_layout(w, ffprobe)
                if lay not in ("2mono", "1stereo"):
                    problems.append(f"Wrapper {w.name}: unsuitable audio layout ({lay})")
            except AssemblyError as e:
                problems.append(str(e))

    # table
    try:
        table = pick_table_for_assembly(xlsx_dir, ddmmyy, log, interactive=interactive)
        print(f"Table: {table.name}")
        blocks = parse_blocks(table)
        print(f"Blocks: {len(blocks)}")
    except AssemblyError as e:
        print(_red(f"[CRITICAL] {e}"))
        return 1

    # table arithmetic duration sums
    bad_sums = []
    for b in blocks:
        # row-by-row sum compared to ИТОГО (with duplicates, sum per row)
        row_sum = 0
        for fid in b["ids"]:
            row_sum += b["chron"].get(fid, 0)
        if b["itogo"] is not None and row_sum != b["itogo"]:
            bad_sums.append((b["time"], row_sum, b["itogo"]))
    if bad_sums:
        for tm, got, exp in bad_sums:
            warnings.append(f"Block {tm}: table chron sum {got} != ИТОГО {exp}")

    # file presence + fallback check
    missing = check_all_files_exist(blocks, src_dir)
    need_recovery = []
    not_anywhere = []
    if missing:
        missing_ids = sorted({fid for _, fid in missing})
        backup_dir = Path(conf["backup_source"]) if conf["backup_source"] else None
        avi_index = set()
        if backup_dir and backup_dir.is_dir():
            for f in backup_dir.iterdir():
                if f.is_file() and f.suffix.lower() == ".avi":
                    avi_index.add(f.stem)
        for fid in missing_ids:
            if str(fid) in avi_index:
                need_recovery.append(fid)
            else:
                not_anywhere.append(fid)
        if need_recovery:
            warnings.append(f"Will be recovered from backup (AVI->XDCAM): {len(need_recovery)} — "
                            + ", ".join(map(str, need_recovery[:20]))
                            + (" ..." if len(need_recovery) > 20 else ""))
        if not_anywhere:
            problems.append(f"Not in src or backup: {len(not_anywhere)} — "
                            + ", ".join(map(str, not_anywhere[:20]))
                            + (" ..." if len(not_anywhere) > 20 else ""))

    # audio layouts of existing clips
    seen = set()
    fixable = []
    none_audio = []
    for b in blocks:
        for fid in b["ids"]:
            if fid in seen:
                continue
            seen.add(fid)
            f = src_dir / f"{fid}{EXT}"
            if not f.is_file():
                continue  # missing files already accounted for above
            try:
                lay = classify_audio_layout(probe_audio_streams(f, ffprobe))
            except AssemblyError:
                problems.append(f"Could not read audio: {f.name}")
                continue
            if lay == "none":
                none_audio.append(fid)
            elif lay == "fixable":
                fixable.append(fid)
    if none_audio:
        problems.append(f"No audio tracks (critical): {len(none_audio)} — "
                        + ", ".join(map(str, none_audio[:20])))
    if fixable:
        warnings.append(f"Require audio fix (->2 mono): {len(fixable)} — "
                        + ", ".join(map(str, fixable[:20]))
                        + (" ..." if len(fixable) > 20 else ""))

    # summary report
    print("\n--- CHECK RESULT ---")
    if warnings:
        print("\nWarnings (non-blocking, but require action):")
        for w in warnings:
            print(f"  * {w}")
            log.log(f"[DRY-RUN warning] {w}", to_console=False)
    if problems:
        print(_red("\nCritical issues (assembly will not start):"))
        for p in problems:
            print(_red(f"  x {p}"))
            log.log(f"[DRY-RUN critical] {p}", to_console=False)
        print(_red(f"\nRESULT: session NOT ready — {len(problems)} critical, "
                   f"{len(warnings)} warning(s)."))
        return 1
    else:
        if warnings:
            print(f"\nRESULT: session will proceed with auto-handling "
                  f"({len(warnings)} warning(s), no critical issues).")
        else:
            print("\nRESULT: all clear, session is fully ready for assembly.")
        return 0



def run_auto_mode(conf: dict, ddmmyy: str, xlsx_dir: Path, src_dir: Path,
                  dst_root: Path, log, interactive: bool = True) -> int:
    # tools
    ffmpeg = _resolve_tool("ffmpeg", conf["ffmpeg"])
    ffprobe = _resolve_tool("ffprobe", conf["ffprobe"])

    # wrappers
    opener = Path(conf["opener"]) if conf["opener"] else None
    closer = Path(conf["closer"]) if conf["closer"] else None
    if not opener or not opener.is_file():
        raise AssemblyError(f"Opener not found (conf [assembly] opener): {conf['opener']!r}")
    if not closer or not closer.is_file():
        raise AssemblyError(f"Closer not found (conf [assembly] closer): {conf['closer']!r}")

    audio_layout = "stereo" if conf["audio_layout"] == "stereo" else "2mono"
    video_mode = "reencode" if conf["video_mode"] == "reencode" else "copy"
    out_format = conf.get("output_format", "mxf")
    if out_format not in FORMAT_EXT:
        log.log(f"[!] Unknown output_format {out_format!r}, falling back to mxf.")
        out_format = "mxf"
    out_ext = FORMAT_EXT[out_format]
    h264_bitrate = conf.get("h264_bitrate", "16m") or "16m"

    # wrapper durations (probed once)
    d_open = get_duration(opener, ffprobe)
    d_close = get_duration(closer, ffprobe)
    log.log(f"Opener: {opener.name} ({d_open:.2f}s)")
    log.log(f"Closer: {closer.name} ({d_close:.2f}s)")

    # wrapper audio layout check (wrappers are not fixed — must be canonical)
    for w in (opener, closer):
        lay = probe_audio_layout(w, ffprobe)
        if lay not in ("2mono", "1stereo"):
            raise AssemblyError(
                f"Wrapper {w.name} has unsuitable audio layout ({lay}). "
                f"Expected 2 mono or 1 stereo. Wrappers are not fixed automatically.",
                handler=3, payload={"file": str(w)})

    # table
    table = pick_table_for_assembly(xlsx_dir, ddmmyy, log, interactive=interactive)
    log.log(f"Table: {table.name}")
    blocks = parse_blocks(table)
    log.log(f"Blocks: {len(blocks)}")

    # HANDLER 1: all files present? Missing ones recovered from backup.
    missing = check_all_files_exist(blocks, src_dir)
    if missing:
        missing_ids = sorted({fid for _, fid in missing})
        log.log(f"Files missing from src: {len(missing_ids)} unique IDs")
        backup_dir = Path(conf["backup_source"]) if conf["backup_source"] else None

        if not backup_dir or not backup_dir.is_dir():
            log.log(f"[ERROR] Backup source not set/not found "
                    f"(conf [assembly] backup_source): {conf['backup_source']!r}")
            for bi, fid in missing[:50]:
                log.log(f"  block {blocks[bi]['time']}: {fid}{EXT}", to_console=False)
            raise AssemblyError(
                f"{len(missing_ids)} files missing, backup source unavailable.",
                handler=1, payload={"missing": missing_ids})

        print(f"\nMissing clips: {len(missing_ids)}. "
              f"Searching and transcoding from backup ({backup_dir})...")
        log.log(f"Backup source: {backup_dir.resolve()}")
        recovered, still_missing = recover_missing_from_backup(
            missing_ids, backup_dir, src_dir, ffmpeg, log)
        log.log(f"Recovered and transcoded: {len(recovered)}")
        print(f"Recovered from backup: {len(recovered)} of {len(missing_ids)}")

        if still_missing:
            log.log(f"[ERROR] Not found in src or backup: {len(still_missing)}")
            for fid in still_missing:
                log.log(f"  {fid}.avi", to_console=False)
            print(_red(f"\n[CRITICAL ERROR] {len(still_missing)} clips "
                       f"not found in src or backup (see log)."))
            raise AssemblyError(
                f"{len(still_missing)} clips are missing everywhere — assembly impossible.",
                handler=1, payload={"still_missing": still_missing})

    # output folder: always a subfolder named "broadcast DDMMYY".
    # base = output_dir from conf if set, otherwise dst.
    out_base = Path(conf["output_dir"]) if conf["output_dir"] else dst_root
    out_dir = out_base / f"broadcast {ddmmyy}"
    out_dir.mkdir(parents=True, exist_ok=True)
    log.log(f"Output folder: {out_dir.resolve()}")

    # temp base for intermediate files (norm_NNN.mxf, audiofix)
    _td = conf.get("temp_dir", "").strip()
    tmp_base = (Path(_td) / ddmmyy) if _td else out_dir
    if _td:
        tmp_base.mkdir(parents=True, exist_ok=True)
        log.log(f"Temp folder:  {tmp_base.resolve()}")
    log.log("")

    # HANDLER 3: single audio scan across all unique clips BEFORE assembly.
    # none -> critical stop; fixable -> collect, ask once, fix.
    audiofix_dir = tmp_base / "_audiofix"
    fix_map = {}            # {original path -> path to fixed file}
    layout_cache = {}       # {path -> layout} to avoid re-probing
    unique_ids = []
    seen = set()
    for b in blocks:
        for fid in b["ids"]:
            if fid not in seen:
                seen.add(fid)
                unique_ids.append(fid)

    fixable = []   # [(path, chans)]
    for fid in unique_ids:
        f = src_dir / f"{fid}{EXT}"
        chans = probe_audio_streams(f, ffprobe)
        lay = classify_audio_layout(chans)
        layout_cache[f] = lay
        if lay == "none":
            raise AssemblyError(
                f"{f.name} has no audio tracks. This is a critical error — "
                f"the file must be prepared manually.",
                handler=3, payload={"file": str(f)})
        if lay == "fixable":
            fixable.append((f, chans))

    if fixable:
        print(_red(f"\nFiles with non-standard audio: {len(fixable)}"))
        for f, chans in fixable:
            print(_red(f"  {f.name}: tracks/channels = {chans}"))
            log.log(f"[HANDLER 3] non-standard audio: {f.name} (channels {chans})",
                    to_console=False)
        if interactive:
            try:
                ans = input("Convert all to broadcast format (2 mono 24/48)? (y/n): ").strip().lower()
            except EOFError:
                ans = "n"
        else:
            print("Auto-converting (running without --manual).")
            ans = "y"
        if ans not in ("y", "yes", "д", "да"):
            raise AssemblyError(
                "Assembly cancelled: non-standard audio files present, "
                "conversion not confirmed.",
                handler=3, payload={"files": [str(f) for f, _ in fixable]})
        # fix each file into _audiofix
        audiofix_dir.mkdir(parents=True, exist_ok=True)
        print("Converting audio...")
        for f, chans in fixable:
            fixed = audiofix_dir / f.name
            fix_audio_to_2mono(f, fixed, chans, ffmpeg, log)
            fix_map[f] = fixed
            # fixed file has the target 2-mono layout
            layout_cache[fixed] = "2mono"
            log.log(f"  fixed: {f.name} -> {fixed}", to_console=False)
        log.log(f"Fixed files: {len(fix_map)}")

    date_part = ddmmyy_to_dashed(ddmmyy)

    # resolve worker count
    try:
        workers = int(conf.get("workers", "1"))
    except (ValueError, TypeError):
        workers = 1
    if workers <= 0:
        workers = os.cpu_count() or 1

    if workers == 1:
        log.log("Assembly mode: sequential (workers=1).")
        print("[i] Assembly mode: sequential (workers=1).")
    else:
        log.log(f"Assembly mode: parallel ({workers} workers).")
        print(f"[i] Assembly mode: parallel ({workers} workers).")

    def build_one(b):
        """Assembles one block. Returns a result dict.
        Does not ask questions — suitable for both sequential and parallel modes."""
        tpart = time_to_filepart(b["time"])
        out_name = f"{date_part}_{conf['middle']}_{tpart}{out_ext}"
        out_path = out_dir / out_name

        roller_paths = []
        for fid in b["ids"]:
            f = src_dir / f"{fid}{EXT}"
            roller_paths.append(fix_map.get(f, f))
        inputs = [opener] + roller_paths + [closer]

        layouts = []
        for f in inputs:
            lay = layout_cache.get(f)
            if lay is None:
                lay = probe_audio_layout(f, ffprobe)
                layout_cache[f] = lay
            layouts.append("1stereo" if lay == "1stereo" else "2mono")

        tmp_files = []
        # unique temp subfolder per block (critical for parallel mode — avoid name collisions)
        block_tmp = tmp_base / "_tmp" / tpart
        if video_mode == "reencode":
            assemble_block_reencode(inputs, layouts, out_path, ffmpeg, audio_layout, log,
                                    out_format=out_format, h264_bitrate=h264_bitrate)
        else:
            tmp_files = assemble_block_copy(inputs, layouts, out_path, ffmpeg,
                                            audio_layout, block_tmp, log,
                                            out_format=out_format, h264_bitrate=h264_bitrate)

        ok, exp_f, got_f = verify_block_duration(out_path, b["itogo"], d_open, d_close, ffprobe)
        return {"block": b, "out_name": out_name, "ok": ok,
                "exp": exp_f, "got": got_f, "tmp_files": tmp_files}

    def cleanup_tmp(tmp_files):
        for tf in tmp_files:
            try:
                if tf.exists():
                    tf.unlink()
            except OSError:
                pass

    built = 0
    failed_blocks = []

    # ===== SEQUENTIAL (workers=1): asks on error =====
    if workers == 1:
        bar = Progress(total=len(blocks))
        for b in blocks:
            res = build_one(b)
            if not res["ok"]:
                bar.finish()
                print(_red(f"\n[CRITICAL ERROR] Block {b['time']} ({res['out_name']}): "
                           f"expected {res['exp']} frames ({b['itogo']}s), got {res['got']}."))
                log.log(f"[CRITICAL DURATION ERROR] {res['out_name']}: "
                        f"expected {res['exp']} frames ({b['itogo']}s), got {res['got']}",
                        to_console=False)
                try:
                    fresh_blocks = parse_blocks(table)
                    fresh = next((fb for fb in fresh_blocks if fb["time"] == b["time"]), b)
                except AssemblyError:
                    fresh = b
                diagnose_block_duration(fresh, src_dir, ffprobe, log)
                failed_blocks.append((b["time"], res["out_name"], res["exp"], res["got"]))
                if not (ask_continue_after_error() if interactive else True):
                    log.log("")
                    log.log("Assembly stopped by user after duration error.")
                    print("\nAssembly stopped.")
                    _report_assembly(log, built, failed_blocks, len(blocks), out_dir)
                    return 1
                print()
                bar = Progress(total=len(blocks))
                bar.n = built + len(failed_blocks)
                continue
            cleanup_tmp(res["tmp_files"])
            built += 1
            bar.update(res["out_name"])
        bar.finish()

    # ===== PARALLEL (workers>1): no prompts, all errors go to the report =====
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading
        print(f"Parallel assembly: {workers} workers, {len(blocks)} blocks\n")
        lock = threading.Lock()
        done = 0
        total = len(blocks)
        results = []

        def worker(b):
            try:
                return build_one(b)
            except AssemblyError as e:
                return {"block": b, "error": str(e),
                        "out_name": f"{date_part}_{conf['middle']}_"
                                    f"{time_to_filepart(b['time'])}{out_ext}"}

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(worker, b): b for b in blocks}
            for fut in as_completed(futures):
                res = fut.result()
                results.append(res)
                with lock:
                    done += 1
                    status = "ok" if res.get("ok") else "ERROR"
                    print(f"  [{done}/{total}] {res['out_name']}: {status}", flush=True)

        # process results
        for res in results:
            if res.get("error"):
                failed_blocks.append((res["block"]["time"], res["out_name"],
                                      None, None))
                log.log(f"[ASSEMBLY ERROR] {res['out_name']}: {res['error']}",
                        to_console=False)
            elif not res.get("ok"):
                b = res["block"]
                log.log(f"[CRITICAL DURATION ERROR] {res['out_name']}: "
                        f"expected {res['exp']} frames ({b['itogo']}s), got {res['got']}",
                        to_console=False)
                try:
                    fresh_blocks = parse_blocks(table)
                    fresh = next((fb for fb in fresh_blocks if fb["time"] == b["time"]), b)
                except AssemblyError:
                    fresh = b
                diagnose_block_duration(fresh, src_dir, ffprobe, log)
                failed_blocks.append((b["time"], res["out_name"], res["exp"], res["got"]))
            else:
                cleanup_tmp(res["tmp_files"])
                built += 1

    # clean up _tmp
    import shutil as _sh
    tmp_root = tmp_base / "_tmp"
    if tmp_root.exists():
        try:
            _sh.rmtree(tmp_root, ignore_errors=True)
        except OSError:
            pass
    # clean up _audiofix on full success
    if not failed_blocks and fix_map:
        try:
            _sh.rmtree(audiofix_dir, ignore_errors=True)
        except OSError:
            pass
    # if an external temp_dir was used and is now empty — remove the date subfolder
    if _td:
        try:
            tmp_base.rmdir()
        except OSError:
            pass

    _report_assembly(log, built, failed_blocks, len(blocks), out_dir)
    return 0 if not failed_blocks else 1



def _report_assembly(log, built: int, failed_blocks: list, total: int, out_dir: Path):
    """Final report for auto-mode assembly."""
    log.log("")
    log.log(f"Blocks assembled: {built} of {total}")
    if failed_blocks:
        log.log(f"Blocks with duration errors: {len(failed_blocks)}")
        for tm, name, exp_f, got_f in failed_blocks:
            log.log(f"  - {tm} ({name}): expected {exp_f}, got {got_f}",
                    to_console=False)
        print(_red(f"\nAssembled {built} of {total}. "
                   f"Blocks with errors: {len(failed_blocks)} (see log)."))
    else:
        print(f"\nSuccessfully assembled {built} broadcast files in: {out_dir.resolve()}")
