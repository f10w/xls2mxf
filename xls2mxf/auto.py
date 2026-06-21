"""Авто-режим: выбор таблицы, dry-run проверка, сборка эфира, отчёт."""
import os
from pathlib import Path

from .constants import FPS, EXT
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


def pick_table_for_assembly(xlsx_dir: Path, ddmmyy: str, log) -> Path:
    """1) Траффик-лист_* за дату -> берём.
       2) нет траффика, но есть другой xlsx -> предупреждаем, спрашиваем y/n.
       3) ничего -> ошибка."""
    candidates = find_xlsx_for_date(xlsx_dir, ddmmyy)
    if not candidates:
        raise AssemblyError(f"Не найдено таблиц, соответствующих дате {ddmmyy}.")
    traffic = [x for x in candidates if x.name.lower().startswith("траффик-лист")]
    if traffic:
        return traffic[0]
    # нетипичный файл
    other = candidates[0]
    print(f"[!] Типичная таблица 'Траффик-лист_*' на {ddmmyy} не найдена.")
    print(f"    Найден нетипичный файл: {other.name}")
    try:
        ans = input("    Использовать его для сборки? (y/n): ").strip().lower()
    except EOFError:
        ans = "n"
    if ans in ("y", "yes", "д", "да"):
        log.log(f"[!] ВНИМАНИЕ: используется НЕТИПИЧНЫЙ файл {other.name}", to_console=False)
        return other
    raise AssemblyError("Сборка отменена: подходящая таблица не выбрана.")


# ---------- оркестратор авто-режима ----------


def run_dry_check(conf: dict, ddmmyy: str, xlsx_dir: Path, src_dir: Path,
                  dst_root: Path, log) -> int:
    """DRY-RUN: все проверки без единого перекода и без записи файлов.
    Показывает, пойдёт ли смена в сборку."""
    print(f"\n=== ПРОВЕРКА (dry-run) на {ddmmyy} ===\n")
    problems = []   # критические
    warnings = []   # некритические (потребуют действий, но не блокеры)

    # инструменты
    try:
        ffmpeg = _resolve_tool("ffmpeg", conf["ffmpeg"])
        ffprobe = _resolve_tool("ffprobe", conf["ffprobe"])
        print(f"ffmpeg:  {ffmpeg}")
        print(f"ffprobe: {ffprobe}")
    except AssemblyError as e:
        print(_red(f"[КРИТИЧНО] {e}"))
        return 1

    # обёртки
    opener = Path(conf["opener"]) if conf["opener"] else None
    closer = Path(conf["closer"]) if conf["closer"] else None
    for nm, w in (("opener", opener), ("closer", closer)):
        if not w or not w.is_file():
            problems.append(f"Обёртка {nm} не найдена: {conf.get(nm)!r}")
        else:
            try:
                lay = probe_audio_layout(w, ffprobe)
                if lay not in ("2mono", "1stereo"):
                    problems.append(f"Обёртка {w.name}: неподходящее аудио ({lay})")
            except AssemblyError as e:
                problems.append(str(e))

    # таблица
    try:
        table = pick_table_for_assembly(xlsx_dir, ddmmyy, log)
        print(f"Таблица: {table.name}")
        blocks = parse_blocks(table)
        print(f"Блоков: {len(blocks)}")
    except AssemblyError as e:
        print(_red(f"[КРИТИЧНО] {e}"))
        return 1

    # суммы хронометража по таблице (арифметика вёрстки)
    bad_sums = []
    for b in blocks:
        s = sum(b["chron"].get(fid, 0) for fid in b["ids"])
        # сумма по строкам сверяется с ИТОГО (внимание: при дублях ID суммируем по строкам)
        row_sum = 0
        for fid in b["ids"]:
            row_sum += b["chron"].get(fid, 0)
        if b["itogo"] is not None and row_sum != b["itogo"]:
            bad_sums.append((b["time"], row_sum, b["itogo"]))
    if bad_sums:
        for tm, got, exp in bad_sums:
            warnings.append(f"Блок {tm}: сумма хрон по таблице {got} ≠ ИТОГО {exp}")

    # наличие файлов + резерв
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
            warnings.append(f"Будут добраны из резерва (AVI→XDCAM): {len(need_recovery)} — "
                            + ", ".join(map(str, need_recovery[:20]))
                            + (" ..." if len(need_recovery) > 20 else ""))
        if not_anywhere:
            problems.append(f"Нет ни в src, ни в резерве: {len(not_anywhere)} — "
                            + ", ".join(map(str, not_anywhere[:20]))
                            + (" ..." if len(not_anywhere) > 20 else ""))

    # аудио-раскладки имеющихся роликов
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
                continue  # отсутствующие уже учтены выше
            try:
                lay = classify_audio_layout(probe_audio_streams(f, ffprobe))
            except AssemblyError:
                problems.append(f"Не удалось прочитать аудио: {f.name}")
                continue
            if lay == "none":
                none_audio.append(fid)
            elif lay == "fixable":
                fixable.append(fid)
    if none_audio:
        problems.append(f"Без аудиодорожек (критично): {len(none_audio)} — "
                        + ", ".join(map(str, none_audio[:20])))
    if fixable:
        warnings.append(f"Потребуют аудио-фикса (→2 моно): {len(fixable)} — "
                        + ", ".join(map(str, fixable[:20]))
                        + (" ..." if len(fixable) > 20 else ""))

    # итоговый отчёт
    print("\n--- РЕЗУЛЬТАТ ПРОВЕРКИ ---")
    if warnings:
        print("\nПредупреждения (не блокируют, но потребуют действий):")
        for w in warnings:
            print(f"  • {w}")
            log.log(f"[DRY-RUN warning] {w}", to_console=False)
    if problems:
        print(_red("\nКритические проблемы (сборка не пойдёт):"))
        for p in problems:
            print(_red(f"  ✗ {p}"))
            log.log(f"[DRY-RUN critical] {p}", to_console=False)
        print(_red(f"\nИТОГ: смена НЕ готова к сборке — {len(problems)} критич., "
                   f"{len(warnings)} предупр."))
        return 1
    else:
        if warnings:
            print(f"\nИТОГ: смена пойдёт в сборку с авто-обработкой "
                  f"({len(warnings)} предупр., критич. нет).")
        else:
            print("\nИТОГ: всё чисто, смена полностью готова к сборке.")
        return 0



def run_auto_mode(conf: dict, ddmmyy: str, xlsx_dir: Path, src_dir: Path,
                  dst_root: Path, log) -> int:
    # инструменты
    ffmpeg = _resolve_tool("ffmpeg", conf["ffmpeg"])
    ffprobe = _resolve_tool("ffprobe", conf["ffprobe"])

    # обёртки
    opener = Path(conf["opener"]) if conf["opener"] else None
    closer = Path(conf["closer"]) if conf["closer"] else None
    if not opener or not opener.is_file():
        raise AssemblyError(f"Открывашка не найдена (conf [assembly] opener): {conf['opener']!r}")
    if not closer or not closer.is_file():
        raise AssemblyError(f"Закрывашка не найдена (conf [assembly] closer): {conf['closer']!r}")

    audio_layout = "stereo" if conf["audio_layout"] == "stereo" else "2mono"
    video_mode = "reencode" if conf["video_mode"] == "reencode" else "copy"

    # длительности обёрток (один раз)
    d_open = get_duration(opener, ffprobe)
    d_close = get_duration(closer, ffprobe)
    log.log(f"Открывашка: {opener.name} ({d_open:.2f}s)")
    log.log(f"Закрывашка: {closer.name} ({d_close:.2f}s)")

    # проверка раскладки обёрток (их не чиним — должны быть эталонными)
    for w in (opener, closer):
        lay = probe_audio_layout(w, ffprobe)
        if lay not in ("2mono", "1stereo"):
            raise AssemblyError(
                f"У обёртки {w.name} неподходящая аудио-раскладка ({lay}). "
                f"Ожидается 2 моно или 1 стерео. Обёртки не правятся автоматически.",
                handler=3, payload={"file": str(w)})

    # таблица
    table = pick_table_for_assembly(xlsx_dir, ddmmyy, log)
    log.log(f"Таблица: {table.name}")
    blocks = parse_blocks(table)
    log.log(f"Блоков: {len(blocks)}")

    # ОБРАБОТЧИК 1: все файлы на месте? Чего нет — добираем из резерва.
    missing = check_all_files_exist(blocks, src_dir)
    if missing:
        missing_ids = sorted({fid for _, fid in missing})
        log.log(f"Не найдено в src файлов: {len(missing_ids)} уникальных ID")
        backup_dir = Path(conf["backup_source"]) if conf["backup_source"] else None

        if not backup_dir or not backup_dir.is_dir():
            log.log(f"[ОШИБКА] Резервный источник не задан/не найден "
                    f"(conf [assembly] backup_source): {conf['backup_source']!r}")
            for bi, fid in missing[:50]:
                log.log(f"  блок {blocks[bi]['time']}: {fid}{EXT}", to_console=False)
            raise AssemblyError(
                f"Не хватает {len(missing_ids)} файлов, резервный источник недоступен.",
                handler=1, payload={"missing": missing_ids})

        print(f"\nНедостающих роликов: {len(missing_ids)}. "
              f"Поиск и перекодирование из резерва ({backup_dir})...")
        log.log(f"Добор из резерва: {backup_dir.resolve()}")
        recovered, still_missing = recover_missing_from_backup(
            missing_ids, backup_dir, src_dir, ffmpeg, log)
        log.log(f"Добрано и перекодировано: {len(recovered)}")
        print(f"Добрано из резерва: {len(recovered)} из {len(missing_ids)}")

        if still_missing:
            log.log(f"[ОШИБКА] Не найдено ни в src, ни в резерве: {len(still_missing)}")
            for fid in still_missing:
                log.log(f"  {fid}.avi", to_console=False)
            print(_red(f"\n[КРИТИЧЕСКАЯ ОШИБКА] {len(still_missing)} роликов "
                       f"нет ни в src, ни в резерве (см. лог)."))
            raise AssemblyError(
                f"{len(still_missing)} роликов отсутствуют везде — сборка невозможна.",
                handler=1, payload={"still_missing": still_missing})

    # выходная папка: всегда подпапка "эфир на ДДММГГ".
    # база = output_dir из conf, если задан, иначе dst.
    out_base = Path(conf["output_dir"]) if conf["output_dir"] else dst_root
    out_dir = out_base / f"эфир на {ddmmyy}"
    out_dir.mkdir(parents=True, exist_ok=True)
    log.log(f"Папка вывода: {out_dir.resolve()}")
    log.log("")

    # ОБРАБОТЧИК 3: единый аудио-проход по всем уникальным роликам ДО сборки.
    # none -> критическая остановка; fixable -> копим, спрашиваем один раз, чиним.
    audiofix_dir = out_dir / "_audiofix"
    fix_map = {}            # {исходный путь -> путь исправленного файла}
    layout_cache = {}       # {путь -> раскладка} чтобы не probe-ить повторно
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
                f"У файла {f.name} нет аудиодорожек. Это критическая ошибка — "
                f"файл нужно подготовить вручную.",
                handler=3, payload={"file": str(f)})
        if lay == "fixable":
            fixable.append((f, chans))

    if fixable:
        print(_red(f"\nНайдено файлов с нестандартным аудио: {len(fixable)}"))
        for f, chans in fixable:
            print(_red(f"  {f.name}: дорожки/каналы = {chans}"))
            log.log(f"[ОБРАБОТЧИК 3] нестандартное аудио: {f.name} (каналы {chans})",
                    to_console=False)
        try:
            ans = input("Сконвертировать все к эфирному формату (2 моно 24/48)? (y/n): ").strip().lower()
        except EOFError:
            ans = "n"
        if ans not in ("y", "yes", "д", "да"):
            raise AssemblyError(
                "Сборка отменена: есть файлы с нестандартным аудио, "
                "конвертация не подтверждена.",
                handler=3, payload={"files": [str(f) for f, _ in fixable]})
        # чиним каждый в _audiofix
        audiofix_dir.mkdir(parents=True, exist_ok=True)
        print("Конвертация аудио...")
        for f, chans in fixable:
            fixed = audiofix_dir / f.name
            fix_audio_to_2mono(f, fixed, chans, ffmpeg, log)
            fix_map[f] = fixed
            # исправленный файл имеет целевые 2 моно
            layout_cache[fixed] = "2mono"
            log.log(f"  исправлен: {f.name} -> {fixed}", to_console=False)
        log.log(f"Исправлено файлов: {len(fix_map)}")

    date_part = ddmmyy_to_dashed(ddmmyy)

    # резолвим число воркеров
    try:
        workers = int(conf.get("workers", "1"))
    except (ValueError, TypeError):
        workers = 1
    if workers <= 0:
        workers = os.cpu_count() or 1

    def build_one(b):
        """Собирает один блок. Возвращает dict с результатом.
        Не задаёт вопросов — годится и для параллельного, и для последовательного."""
        tpart = time_to_filepart(b["time"])
        out_name = f"{date_part}_{conf['middle']}_{tpart}{EXT}"
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
        # уникальная temp-подпапка на блок (важно для параллельности — не пересекаться)
        block_tmp = out_dir / "_tmp" / tpart
        if video_mode == "reencode":
            assemble_block_reencode(inputs, layouts, out_path, ffmpeg, audio_layout, log)
        else:
            tmp_files = assemble_block_copy(inputs, layouts, out_path, ffmpeg,
                                            audio_layout, block_tmp, log)

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

    # ===== ПОСЛЕДОВАТЕЛЬНО (workers=1): с вопросами при ошибке =====
    if workers == 1:
        bar = Progress(total=len(blocks))
        for b in blocks:
            res = build_one(b)
            if not res["ok"]:
                bar.finish()
                print(_red(f"\n[КРИТИЧЕСКАЯ ОШИБКА] Блок {b['time']} ({res['out_name']}): "
                           f"ожидалось {res['exp']} кадров ({b['itogo']}с), получено {res['got']}."))
                log.log(f"[КРИТИЧЕСКАЯ ОШИБКА ХРОНОМЕТРАЖА] {res['out_name']}: "
                        f"ожидалось {res['exp']} кадров ({b['itogo']}с), получено {res['got']}",
                        to_console=False)
                try:
                    fresh_blocks = parse_blocks(table)
                    fresh = next((fb for fb in fresh_blocks if fb["time"] == b["time"]), b)
                except AssemblyError:
                    fresh = b
                diagnose_block_duration(fresh, src_dir, ffprobe, log)
                failed_blocks.append((b["time"], res["out_name"], res["exp"], res["got"]))
                if not ask_continue_after_error():
                    log.log("")
                    log.log("Сборка остановлена пользователем после ошибки хронометража.")
                    print("\nСборка остановлена.")
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

    # ===== ПАРАЛЛЕЛЬНО (workers>1): без вопросов, всё в отчёт =====
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading
        print(f"Параллельная сборка: {workers} воркеров, блоков {len(blocks)}\n")
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
                                    f"{time_to_filepart(b['time'])}{EXT}"}

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(worker, b): b for b in blocks}
            for fut in as_completed(futures):
                res = fut.result()
                results.append(res)
                with lock:
                    done += 1
                    status = "ok" if res.get("ok") else "ОШИБКА"
                    print(f"  [{done}/{total}] {res['out_name']}: {status}", flush=True)

        # разбор результатов
        for res in results:
            if res.get("error"):
                failed_blocks.append((res["block"]["time"], res["out_name"],
                                      None, None))
                log.log(f"[ОШИБКА СБОРКИ] {res['out_name']}: {res['error']}",
                        to_console=False)
            elif not res.get("ok"):
                b = res["block"]
                log.log(f"[КРИТИЧЕСКАЯ ОШИБКА ХРОНОМЕТРАЖА] {res['out_name']}: "
                        f"ожидалось {res['exp']} кадров ({b['itogo']}с), получено {res['got']}",
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

    # подчистить _tmp
    tmp_root = out_dir / "_tmp"
    if tmp_root.exists():
        import shutil as _sh
        try:
            _sh.rmtree(tmp_root, ignore_errors=True)
        except OSError:
            pass
    # подчистить _audiofix при полном успехе
    if not failed_blocks and fix_map:
        import shutil as _sh
        try:
            _sh.rmtree(audiofix_dir, ignore_errors=True)
        except OSError:
            pass

    _report_assembly(log, built, failed_blocks, len(blocks), out_dir)
    return 0 if not failed_blocks else 1



def _report_assembly(log, built: int, failed_blocks: list, total: int, out_dir: Path):
    """Итоговый отчёт по авто-сборке."""
    log.log("")
    log.log(f"Собрано блоков: {built} из {total}")
    if failed_blocks:
        log.log(f"Блоков с ошибкой хронометража: {len(failed_blocks)}")
        for tm, name, exp_f, got_f in failed_blocks:
            log.log(f"  - {tm} ({name}): ожидалось {exp_f}, получено {got_f}",
                    to_console=False)
        print(_red(f"\nСобрано {built} из {total}. "
                   f"Блоков с ошибкой: {len(failed_blocks)} (см. лог)."))
    else:
        print(f"\nУспешно собрано {built} эфирных файлов в: {out_dir.resolve()}")

