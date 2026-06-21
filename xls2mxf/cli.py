"""CLI: argument parsing, mode selection, manual mode, main() entry point."""
import argparse
import datetime as dt
import os
import shutil
import sys
from pathlib import Path

from .constants import EXT
from .errors import AssemblyError
from .config import app_dir, load_conf
from .ui import (Logger, Progress, _red, parse_ddmmyy, ask_date, ask_mode,
                 copy_to_clipboard, notify_windows)
from .tables import find_xlsx_for_date, extract_ids, read_id_column_raw
from .auto import run_auto_mode, run_dry_check


def main() -> int:
    conf = load_conf()
    ap = argparse.ArgumentParser(description="Collect .mxf clips by ID from traffic sheets.")
    ap.add_argument("--date", help="date DDMMYY (default: tomorrow)")
    ap.add_argument("--mode", choices=["manual", "auto"],
                    help="mode: manual (copy clips) | auto (assemble broadcast). "
                         "Default: auto (or prompts with --manual).")
    ap.add_argument("--check", action="store_true",
                    help="dry-run: verify the session without assembly or transcoding.")
    ap.add_argument("--manual", action="store_true",
                    help="interactive mode: prompts for date, mode and other questions.")
    ap.add_argument("--doctor", action="store_true",
                    help="configuration diagnostics: paths, ffmpeg, wrappers.")
    ap.add_argument("--open", action="store_true",
                    help="open the output folder in Explorer after successful assembly.")
    ap.add_argument("--xlsx", default=conf["xlsx"])
    ap.add_argument("--src", default=conf["src"])
    ap.add_argument("--dst", default=conf["dst"])
    args = ap.parse_args()

    if args.doctor:
        return _run_doctor(conf)

    log = Logger()

    # date
    if args.date:
        try:
            parse_ddmmyy(args.date)
            ddmmyy = args.date
        except ValueError as e:
            print(f"[!] Invalid date in --date: {e}")
            return 1
    elif args.manual:
        ddmmyy = ask_date()
    else:
        tomorrow = dt.date.today() + dt.timedelta(days=1)
        ddmmyy = tomorrow.strftime("%d%m%y")

    xlsx_dir = Path(args.xlsx)
    src_dir = Path(args.src)
    dst_root = Path(args.dst)

    # mode (--check always implies auto; no prompt needed)
    if args.check:
        mode = "auto"
    elif args.mode:
        mode = args.mode
    elif args.manual:
        mode = ask_mode()
    else:
        mode = "auto"

    log.log(f"=== Collecting clips for {ddmmyy} (mode: {mode}) ===")
    log.log(f"Started: {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    log.log("")

    if not xlsx_dir.is_dir():
        log.log(f"[!] Excel folder not found: {xlsx_dir}")
        _finish_log(log, app_dir(), ddmmyy)
        return 1
    if not src_dir.is_dir():
        log.log(f"[!] Clips folder not found: {src_dir}")
        _finish_log(log, app_dir(), ddmmyy)
        return 1

    # lock file: prevents two instances from running for the same date simultaneously
    lock_path = None
    if not args.check:
        lock_path = app_dir() / f"{ddmmyy}.lock"
        if lock_path.exists():
            print(f"[!] Assembly for {ddmmyy} is already running (found {lock_path.name}).")
            print(f"    If the previous run is stuck — delete the file manually and retry.")
            return 1
        lock_path.touch()

    try:
        # ===== DRY-RUN (check without assembly) =====
        if args.check:
            try:
                rc = run_dry_check(conf, ddmmyy, xlsx_dir, src_dir, dst_root, log,
                                   interactive=args.manual)
            except AssemblyError as e:
                log.log(f"[ERROR] {e}")
                print(_red(f"[ERROR] {e}"))
                _finish_log(log, app_dir(), ddmmyy)
                return 1
            _finish_log(log, app_dir(), ddmmyy)
            return rc

        # ===== AUTO MODE =====
        if mode == "auto":
            # preflight: dry-run first; stop on critical issues
            try:
                rc_pre = run_dry_check(conf, ddmmyy, xlsx_dir, src_dir, dst_root, log,
                                       interactive=args.manual)
            except AssemblyError as e:
                log.log(f"[ERROR preflight] {e}")
                print(_red(f"[ERROR] {e}"))
                _finish_log(log, app_dir(), ddmmyy)
                notify_windows("xls2mxf — error", str(e)[:120])
                return 1
            if rc_pre != 0:
                log.log("Assembly not started: preflight found critical issues.")
                _finish_log(log, app_dir(), ddmmyy)
                notify_windows("xls2mxf — error", f"Check for {ddmmyy} failed.")
                return 1

            log.log("")
            log.log("--- Starting assembly ---")
            print("\n--- Starting assembly ---\n")
            try:
                rc = run_auto_mode(conf, ddmmyy, xlsx_dir, src_dir, dst_root, log,
                                   interactive=args.manual)
            except AssemblyError as e:
                log.log("")
                log.log(f"[ERROR] {e}")
                if e.handler == 1:
                    log.log("  -> Handler 1 (missing file search/recovery) to be added later.")
                _finish_log(log, app_dir(), ddmmyy)
                notify_windows("xls2mxf — error", str(e)[:120])
                return 1
            _finish_log(log, app_dir(), ddmmyy)
            if rc == 0:
                notify_windows("xls2mxf", f"Assembly for {ddmmyy} completed successfully.")
                if args.open:
                    out_base = Path(conf["output_dir"]) if conf["output_dir"] else dst_root
                    out_dir = out_base / f"broadcast {ddmmyy}"
                    if out_dir.is_dir():
                        os.startfile(out_dir)
            else:
                notify_windows("xls2mxf — error", f"Assembly for {ddmmyy}: errors found (see log).")
            return rc

        # ===== MANUAL MODE =====
        xlsx_files = find_xlsx_for_date(xlsx_dir, ddmmyy)
        if not xlsx_files:
            log.log(f"[!] No .xlsx files with date {ddmmyy} in name found in {xlsx_dir}.")
            _finish_log(log, app_dir(), ddmmyy)
            return 1

        log.log(f"Excel source folder: {xlsx_dir.resolve()}")
        log.log("Processing traffic sheets:")
        all_ids = set()
        for x in xlsx_files:
            got = extract_ids(x)
            all_ids |= got
            log.log(f"  - {x.name}: {len(got)} IDs")
        log.log(f"Total unique IDs: {len(all_ids)}")
        log.log("")

        # destination folder
        dst_dir = dst_root / f"clips {ddmmyy}"
        dst_dir.mkdir(parents=True, exist_ok=True)
        log.log(f"Clips source folder: {src_dir.resolve()}")
        log.log(f"Destination folder:  {dst_dir.resolve()}")
        log.log("")

        # copy with progress bar
        ids_sorted = sorted(all_ids)
        copied_files = []
        missing = []
        print()  # blank line before bar
        bar = Progress(total=len(ids_sorted))
        for i in ids_sorted:
            f = src_dir / f"{i}{EXT}"
            name = f.name
            if not f.is_file():
                missing.append(i)
                bar.update(f"missing: {name}")
                continue
            target = dst_dir / name
            if not target.exists():
                try:
                    shutil.copy2(f, target)
                    copied_files.append(name)
                    bar.update(name)
                except OSError as e:
                    missing.append(i)
                    bar.update(f"error: {name}")
                    log.log(f"[!] Copy error {name}: {e}", to_console=False)
            else:
                copied_files.append(name)  # already present — count as delivered
                bar.update(f"already exists: {name}")
        bar.finish()

        # listing to log
        log.log("Copied files:")
        if copied_files:
            for n in copied_files:
                log.log(f"  + {n}", to_console=False)
        else:
            log.log("  (none)", to_console=False)
        if missing:
            log.log("", to_console=False)
            log.log(f"No {EXT} found for {len(missing)} IDs:", to_console=False)
            log.log("  " + ", ".join(map(str, missing)), to_console=False)

        # summary
        print()
        if missing:
            msg = (f"Done. Copied {len(copied_files)} files, "
                   f"{len(missing)} not found (see log).")
        else:
            msg = f"Successfully copied {len(copied_files)} files, no errors."
        log.log(msg)

        # --- copy final ID list to clipboard (--manual only) ---
        print()
        if args.manual:
            try:
                ans = input("Copy final ID list to clipboard? (y/n): ").strip().lower()
            except EOFError:
                ans = "n"
        else:
            ans = "n"
        if ans in ("y", "yes", "д", "да"):
            source = xlsx_files[0]  # read first table (alphabetical order)
            lines = read_id_column_raw(source, conf["customlines"])
            if not lines:
                print("[!] Could not read ID column for clipboard.")
                log.log(f"Clipboard: could not read column from {source.name}",
                        to_console=False)
            else:
                # one-to-one as Excel: values separated by newlines
                clip_text = "\r\n".join(lines)
                if copy_to_clipboard(clip_text):
                    print(f"[+] Copied to clipboard: {len(lines)} lines "
                          f"(source: {source.name})")
                    log.log("", to_console=False)
                    log.log(f"Clipboard: {len(lines)} lines from {source.name}",
                            to_console=False)
                else:
                    print("[!] Could not access clipboard.")
                    log.log("Clipboard: access error", to_console=False)

        _finish_log(log, app_dir(), ddmmyy)
        return 0

    finally:
        if lock_path:
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass



def _run_doctor(conf: dict) -> int:
    import subprocess
    from .ffmpeg_tools import _resolve_tool

    all_ok = True

    def _ok(label, detail=""):
        print(f"  [+] {label}" + (f": {detail}" if detail else ""))

    def _fail(label, detail=""):
        nonlocal all_ok
        all_ok = False
        print(f"  [!] {label}" + (f": {detail}" if detail else ""))

    def _info(label, detail=""):
        print(f"  [-] {label}" + (f": {detail}" if detail else ""))

    print("=== Configuration diagnostics ===\n")

    print("Paths:")
    for key, label in (("xlsx", "xlsx (traffic sheets)"),
                       ("src",  "src  (source clips .mxf)"),
                       ("dst",  "dst  (destination)")):
        p = Path(conf[key])
        if p.is_dir():
            _ok(label, str(p.resolve()))
        else:
            _fail(label, f"not found: {conf[key]!r}")

    print("\nffmpeg:")
    for tool in ("ffmpeg", "ffprobe"):
        try:
            path = _resolve_tool(tool, conf[tool])
            r = subprocess.run([path, "-version"], capture_output=True, timeout=5)
            if r.returncode == 0:
                ver = r.stdout.decode(errors="replace").splitlines()[0]
                _ok(tool, f"{path}  [{ver}]")
            else:
                _fail(tool, f"found but failed to run: {path}")
        except AssemblyError as e:
            _fail(tool, str(e))
        except Exception as e:
            _fail(tool, str(e))

    print("\nWrappers:")
    for key, label in (("opener", "opener"), ("closer", "closer")):
        v = conf[key]
        if not v:
            _fail(label, "not set in config")
        elif Path(v).is_file():
            _ok(label, str(Path(v).resolve()))
        else:
            _fail(label, f"file not found: {v!r}")

    print("\nAssembly parameters:")
    m = conf.get("middle", "")
    if m:
        _ok("middle", m)
    else:
        _fail("middle", "not set — output filenames will be incorrect")

    try:
        w = int(conf.get("workers", "1"))
        if w == 1:
            _ok("workers", "1 (sequential)")
        elif w == 0:
            _ok("workers", f"0 (auto -> {os.cpu_count() or 1} cores)")
        else:
            _ok("workers", f"{w} (parallel)")
    except (ValueError, TypeError):
        _fail("workers", f"invalid value: {conf.get('workers')!r}")

    td = conf.get("temp_dir", "")
    if td:
        if Path(td).is_dir():
            _ok("temp_dir", str(Path(td).resolve()))
        else:
            _fail("temp_dir", f"folder not found: {td!r}")
    else:
        _info("temp_dir", "not set (temp created alongside output files)")

    bs = conf.get("backup_source", "")
    if bs:
        if Path(bs).is_dir():
            _ok("backup_source", str(Path(bs).resolve()))
        else:
            _fail("backup_source", f"folder not found: {bs!r}")
    else:
        _info("backup_source", "not set (fallback recovery unavailable)")

    od = conf.get("output_dir", "")
    if od:
        if Path(od).is_dir():
            _ok("output_dir", str(Path(od).resolve()))
        else:
            _fail("output_dir", f"folder not found: {od!r}")
    else:
        _info("output_dir", "not set (output folder created inside dst)")

    print()
    if all_ok:
        print("All good — configuration is ready.")
        return 0
    else:
        print("Issues found — fix the [!] items above before running.")
        return 1


def _finish_log(log: Logger, where: Path, ddmmyy: str):
    log_path = where / f"{ddmmyy}.log"
    try:
        log.save(log_path)
        print(f"Log: {log_path}")
    except OSError as e:
        print(f"[!] Failed to write log: {e}")


if __name__ == "__main__":
    code = main()
    try:
        input("\nPress Enter to exit...")
    except EOFError:
        pass
    sys.exit(code)
