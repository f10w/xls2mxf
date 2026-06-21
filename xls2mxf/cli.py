"""CLI: разбор аргументов, выбор режима, ручной режим, точка main()."""
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
    ap = argparse.ArgumentParser(description="Сбор роликов .mxf по ID из траффик-листов.")
    ap.add_argument("--date", help="дата ДДММГГ (по умолчанию — завтра)")
    ap.add_argument("--mode", choices=["manual", "auto"],
                    help="режим: manual (копирование) | auto (сборка эфира). "
                         "Без флага — авто (или спросит при --manual).")
    ap.add_argument("--check", action="store_true",
                    help="dry-run: проверить смену без сборки и перекодов.")
    ap.add_argument("--manual", action="store_true",
                    help="интерактивный режим: спрашивает дату, режим и прочие вопросы.")
    ap.add_argument("--doctor", action="store_true",
                    help="диагностика конфигурации: пути, ffmpeg, обёртки.")
    ap.add_argument("--open", action="store_true",
                    help="открыть папку с результатом в Проводнике после успешной сборки.")
    ap.add_argument("--xlsx", default=conf["xlsx"])
    ap.add_argument("--src", default=conf["src"])
    ap.add_argument("--dst", default=conf["dst"])
    args = ap.parse_args()

    if args.doctor:
        return _run_doctor(conf)

    log = Logger()

    # дата
    if args.date:
        try:
            parse_ddmmyy(args.date)
            ddmmyy = args.date
        except ValueError as e:
            print(f"[!] Некорректная дата в --date: {e}")
            return 1
    elif args.manual:
        ddmmyy = ask_date()
    else:
        tomorrow = dt.date.today() + dt.timedelta(days=1)
        ddmmyy = tomorrow.strftime("%d%m%y")

    xlsx_dir = Path(args.xlsx)
    src_dir = Path(args.src)
    dst_root = Path(args.dst)

    # режим (при --check режим не спрашиваем — это всегда проверка авто-сборки)
    if args.check:
        mode = "auto"
    elif args.mode:
        mode = args.mode
    elif args.manual:
        mode = ask_mode()
    else:
        mode = "auto"

    log.log(f"=== Сбор роликов на {ddmmyy} (режим: {mode}) ===")
    log.log(f"Запуск: {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    log.log("")

    if not xlsx_dir.is_dir():
        log.log(f"[!] Папка с эксель-файлами не найдена: {xlsx_dir}")
        _finish_log(log, app_dir(), ddmmyy)
        return 1
    if not src_dir.is_dir():
        log.log(f"[!] Папка с роликами не найдена: {src_dir}")
        _finish_log(log, app_dir(), ddmmyy)
        return 1

    # lock-файл: не даём двум копиям работать на одну дату одновременно
    lock_path = None
    if not args.check:
        lock_path = app_dir() / f"{ddmmyy}.lock"
        if lock_path.exists():
            print(f"[!] Уже выполняется сборка на {ddmmyy} (найден {lock_path.name}).")
            print(f"    Если прошлый запуск завис — удалите файл вручную и повторите.")
            return 1
        lock_path.touch()

    try:
        # ===== DRY-RUN (проверка без сборки) =====
        if args.check:
            try:
                rc = run_dry_check(conf, ddmmyy, xlsx_dir, src_dir, dst_root, log,
                                   interactive=args.manual)
            except AssemblyError as e:
                log.log(f"[ОШИБКА] {e}")
                print(_red(f"[ОШИБКА] {e}"))
                _finish_log(log, app_dir(), ddmmyy)
                return 1
            _finish_log(log, app_dir(), ddmmyy)
            return rc

        # ===== АВТО-РЕЖИМ =====
        if mode == "auto":
            # preflight: сначала dry-run, при критических проблемах — стоп
            try:
                rc_pre = run_dry_check(conf, ddmmyy, xlsx_dir, src_dir, dst_root, log,
                                       interactive=args.manual)
            except AssemblyError as e:
                log.log(f"[ОШИБКА preflight] {e}")
                print(_red(f"[ОШИБКА] {e}"))
                _finish_log(log, app_dir(), ddmmyy)
                notify_windows("xls2mxf — ошибка", str(e)[:120])
                return 1
            if rc_pre != 0:
                log.log("Сборка не запущена: preflight выявил критические проблемы.")
                _finish_log(log, app_dir(), ddmmyy)
                notify_windows("xls2mxf — ошибка", f"Проверка {ddmmyy} не пройдена.")
                return 1

            log.log("")
            log.log("--- Запуск сборки ---")
            print("\n--- Запуск сборки ---\n")
            try:
                rc = run_auto_mode(conf, ddmmyy, xlsx_dir, src_dir, dst_root, log,
                                   interactive=args.manual)
            except AssemblyError as e:
                log.log("")
                log.log(f"[ОШИБКА] {e}")
                if e.handler == 1:
                    log.log("  -> Обработчик 1 (поиск/добор недостающих файлов) "
                            "будет добавлен позже.")
                _finish_log(log, app_dir(), ddmmyy)
                notify_windows("xls2mxf — ошибка", str(e)[:120])
                return 1
            _finish_log(log, app_dir(), ddmmyy)
            if rc == 0:
                notify_windows("xls2mxf", f"Сборка {ddmmyy} завершена успешно.")
                if args.open:
                    out_base = Path(conf["output_dir"]) if conf["output_dir"] else dst_root
                    out_dir = out_base / f"эфир на {ddmmyy}"
                    if out_dir.is_dir():
                        os.startfile(out_dir)
            else:
                notify_windows("xls2mxf — ошибка", f"Сборка {ddmmyy}: есть ошибки (см. лог).")
            return rc

        # ===== РУЧНОЙ РЕЖИМ =====
        xlsx_files = find_xlsx_for_date(xlsx_dir, ddmmyy)
        if not xlsx_files:
            log.log(f"[!] В {xlsx_dir} не найдено .xlsx с датой {ddmmyy} в имени.")
            _finish_log(log, app_dir(), ddmmyy)
            return 1

        log.log(f"Папка-источник эксель: {xlsx_dir.resolve()}")
        log.log("Обрабатываемые траффик-листы:")
        all_ids = set()
        for x in xlsx_files:
            got = extract_ids(x)
            all_ids |= got
            log.log(f"  - {x.name}: {len(got)} ID")
        log.log(f"Всего уникальных ID: {len(all_ids)}")
        log.log("")

        # папка назначения
        dst_dir = dst_root / f"ролики на {ddmmyy}"
        dst_dir.mkdir(parents=True, exist_ok=True)
        log.log(f"Папка-источник роликов: {src_dir.resolve()}")
        log.log(f"Папка назначения:       {dst_dir.resolve()}")
        log.log("")

        # копирование с прогресс-баром
        ids_sorted = sorted(all_ids)
        copied_files = []
        missing = []
        print()  # отступ перед баром
        bar = Progress(total=len(ids_sorted))
        for i in ids_sorted:
            f = src_dir / f"{i}{EXT}"
            name = f.name
            if not f.is_file():
                missing.append(i)
                bar.update(f"нет файла: {name}")
                continue
            target = dst_dir / name
            if not target.exists():
                try:
                    shutil.copy2(f, target)
                    copied_files.append(name)
                    bar.update(name)
                except OSError as e:
                    missing.append(i)
                    bar.update(f"ошибка: {name}")
                    log.log(f"[!] Ошибка копирования {name}: {e}", to_console=False)
            else:
                copied_files.append(name)  # уже на месте — считаем доставленным
                bar.update(f"уже есть: {name}")
        bar.finish()

        # листинг в лог
        log.log("Скопированные файлы:")
        if copied_files:
            for n in copied_files:
                log.log(f"  + {n}", to_console=False)
        else:
            log.log("  (нет)", to_console=False)
        if missing:
            log.log("", to_console=False)
            log.log(f"Не найдено {EXT} для {len(missing)} ID:", to_console=False)
            log.log("  " + ", ".join(map(str, missing)), to_console=False)

        # итог
        print()
        if missing:
            msg = (f"Готово. Скопировано {len(copied_files)} файлов, "
                   f"не найдено {len(missing)} (см. лог).")
        else:
            msg = f"Успешно скопировано {len(copied_files)} файлов, ошибок не найдено."
        log.log(msg)

        # --- копирование итогового списка ID в буфер обмена (только в --manual) ---
        print()
        if args.manual:
            try:
                ans = input("Скопировать итоговый список в буфер обмена? (y/n): ").strip().lower()
            except EOFError:
                ans = "n"
        else:
            ans = "n"
        if ans in ("y", "yes", "д", "да"):
            source = xlsx_files[0]  # читаем одну таблицу (первая по алфавиту)
            lines = read_id_column_raw(source, conf["customlines"])
            if not lines:
                print("[!] Не удалось прочитать столбец ID для буфера.")
                log.log(f"Буфер обмена: не удалось прочитать столбец из {source.name}",
                        to_console=False)
            else:
                # один-в-один как Excel: значения через перевод строки
                clip_text = "\r\n".join(lines)
                if copy_to_clipboard(clip_text):
                    print(f"[+] В буфер скопировано строк: {len(lines)} "
                          f"(источник: {source.name})")
                    log.log("", to_console=False)
                    log.log(f"Буфер обмена: {len(lines)} строк из {source.name}",
                            to_console=False)
                else:
                    print("[!] Не удалось получить доступ к буферу обмена.")
                    log.log("Буфер обмена: ошибка доступа", to_console=False)

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

    print("=== Диагностика конфигурации ===\n")

    print("Пути:")
    for key, label in (("xlsx", "xlsx (траффик-листы)"),
                       ("src",  "src  (ролики .mxf)"),
                       ("dst",  "dst  (назначение)")):
        p = Path(conf[key])
        if p.is_dir():
            _ok(label, str(p.resolve()))
        else:
            _fail(label, f"не найдена: {conf[key]!r}")

    print("\nffmpeg:")
    for tool in ("ffmpeg", "ffprobe"):
        try:
            path = _resolve_tool(tool, conf[tool])
            r = subprocess.run([path, "-version"], capture_output=True, timeout=5)
            if r.returncode == 0:
                ver = r.stdout.decode(errors="replace").splitlines()[0]
                _ok(tool, f"{path}  [{ver}]")
            else:
                _fail(tool, f"найден, но не запускается: {path}")
        except AssemblyError as e:
            _fail(tool, str(e))
        except Exception as e:
            _fail(tool, str(e))

    print("\nОбёртки:")
    for key, label in (("opener", "opener"), ("closer", "closer")):
        v = conf[key]
        if not v:
            _fail(label, "не задана в конфиге")
        elif Path(v).is_file():
            _ok(label, str(Path(v).resolve()))
        else:
            _fail(label, f"файл не найден: {v!r}")

    print("\nПараметры сборки:")
    m = conf.get("middle", "")
    if m:
        _ok("middle", m)
    else:
        _fail("middle", "не задано — имена выходных файлов будут некорректными")

    try:
        w = int(conf.get("workers", "1"))
        if w == 1:
            _ok("workers", "1 (последовательно)")
        elif w == 0:
            _ok("workers", f"0 (авто → {os.cpu_count() or 1} ядер)")
        else:
            _ok("workers", f"{w} (параллельно)")
    except (ValueError, TypeError):
        _fail("workers", f"некорректное значение: {conf.get('workers')!r}")

    bs = conf.get("backup_source", "")
    if bs:
        if Path(bs).is_dir():
            _ok("backup_source", str(Path(bs).resolve()))
        else:
            _fail("backup_source", f"папка не найдена: {bs!r}")
    else:
        _info("backup_source", "не задан (добор из резерва недоступен)")

    od = conf.get("output_dir", "")
    if od:
        if Path(od).is_dir():
            _ok("output_dir", str(Path(od).resolve()))
        else:
            _fail("output_dir", f"папка не найдена: {od!r}")
    else:
        _info("output_dir", "не задан (папка вывода создаётся внутри dst)")

    print()
    if all_ok:
        print("Всё в порядке — конфигурация готова к работе.")
        return 0
    else:
        print("Есть проблемы — исправьте отмеченные [!] пункты перед запуском.")
        return 1


def _finish_log(log: Logger, where: Path, ddmmyy: str):
    log_path = where / f"{ddmmyy}.log"
    try:
        log.save(log_path)
        print(f"Лог: {log_path}")
    except OSError as e:
        print(f"[!] Не удалось записать лог: {e}")


if __name__ == "__main__":
    code = main()
    try:
        input("\nНажми Enter для выхода...")
    except EOFError:
        pass
    sys.exit(code)
