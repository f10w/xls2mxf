# Architecture and technical decisions

Developer reference. Describes the package structure, data flow, input table format,
and non-obvious ffmpeg decisions — each of which exists because of a specific real
problem, not "just in case".

---

## Package structure

```
run.py                  Thin launcher. PyInstaller entry point (→ xls2mxf.exe).
xls2mxf/
  __init__.py           ANSI console setup for Windows, version.
  __main__.py           Entry point for `python -m xls2mxf`.
  constants.py          EXT, FPS, HEADER_TEXT, DATE_RE, DEFAULT_CONF.
  errors.py             AssemblyError (with handler field: 1/2/3).
  config.py             load_conf(), app_dir().
  ui.py                 Logger, Progress, _red(), dialogs, clipboard.
  tables.py             Traffic-sheet parsing, blocks, IDs, dates, filenames.
  ffmpeg_tools.py       ffmpeg/ffprobe lookup/execution, duration, audio layouts.
  assembly.py           Block assembly, audio fix, AVI->XDCAM transcode.
  handlers.py           Backup recovery, duration check and diagnosis.
  auto.py               Auto mode: dry-run, assembly orchestrator, report.
  cli.py                Argument parsing, mode selection, manual mode, main().
```

### Dependency graph (strictly one-way, no cycles)

```
constants ─┬─> config ──> ffmpeg_tools ──> assembly ──> handlers ──> auto ──> cli
           ├─> errors  ──────────────────────^                        ^
           └─> ui ──────────────────────────────────────────────────-┘
```

Low-level modules have no knowledge of high-level ones. This allows `tables` and
`ffmpeg_tools` to be tested in isolation.

---

## Building the exe

PyInstaller `--onefile` packages the whole package into a single `.exe`. Key flags
in `build.bat`: `--collect-submodules xls2mxf` (to pull in all package modules) and
`--collect-all openpyxl`.

`app_dir()` in `config.py` determines where the conf and log live:
- in a frozen exe (`sys.frozen`) — the folder containing the exe;
- when running from source — the folder containing `run.py`;
- with `python -m` — the working directory (CWD), not the package folder.

This matters: conf and log are always next to the launch point, not in PyInstaller's
temp extraction folder.

---

## Input table format (traffic sheet)

`.xlsx` file, date `DDMMYY` at the end of the filename. Inside:

- Header in row 4. The ID column is identified by the header text **"ID ролика"** —
  searched by text, not by a hard-coded column number (column F in "Траффик-лист",
  column J in "Эфирка").
- **Block** = consecutive rows with an integer in the ID column. Blocks are separated
  by empty rows and a row with "ИТОГО" in column D.
- **Block time** — column A of the first row of the block (`datetime.time`), format
  `H:MM`. Identical across all rows of the block.
- **Clip duration** — column E ("Хрон."), in seconds.
- **Block total (ИТОГО)** — column E of the row where D == "ИТОГО". Sum of clip
  durations in the block, excluding wrappers.

`parse_blocks()` returns a list of dicts:
```python
{"time": "05:25", "ids": [3072716, ...], "chron": {id: sec, ...}, "itogo": 60}
```
IDs are stored in table order, with duplicates. `chron` is key-value (one duration
per unique ID).

---

## Two modes

### Manual (`cli.py`)
Extracts IDs for the date, copies `<ID>.mxf` into `clips DDMMYY`, optionally writes
the list to clipboard. The clipboard list is read top-to-bottom as-is (with
duplicates and gaps preserved); gaps are filled with `customline1/2/3`.

### Auto (`auto.py`)
Slices blocks, runs three handlers, assembles each block via ffmpeg.

---

## Three error handlers

### Handler 1 — missing files (`handlers.recover_missing_from_backup`)
Before assembly: all `<ID>.mxf` in `src` are checked for presence. Missing ones are
looked up as `<ID>.avi` in `backup_source`, transcoded to broadcast XDCAM, and placed
in `src`. Not found in backup either → critical stop.

### Handler 2 — duration check (`handlers.verify_block_duration` + `diagnose_block_duration`)
After each block is assembled: `(file duration − opener − closer)` is compared to
ИТОГО **in frames** (× FPS=25; rounding makes this robust against ffprobe jitter).
On mismatch `diagnose_block_duration` re-reads the table and walks the block's clips,
identifying which one has the wrong length. If all clips are correct, the problem is
in the ИТОГО value or the wrapper durations.

### Handler 3 — non-standard audio (`assembly.fix_audio_to_2mono`)
Target format: 2 mono pcm_s24le 48k. Layout classification (`classify_audio_layout`):
`2mono`/`1stereo` — OK; `none` (0 tracks) — critical stop; anything else (1 mono,
3+, 4 tracks) — `fixable`. Fixable files are converted on user confirmation into a
`_audiofix` subfolder (src is not modified). Normalisation rule: first two audio
channels → two mono tracks (a single channel is duplicated).

---

## Non-obvious ffmpeg decisions

Each is a consequence of a real problem found during debugging. Do not change without
understanding the reason.

### Video copy, audio remix (two-pass)
All XDCAM HD422 clips share the same video parameters but **differ in audio layout**
(some have 2 mono, some 1 stereo). Concat demuxer with full `-c copy` breaks on
heterogeneous audio. Solution (`video_mode=copy`): first pass normalises audio of
each file to the target layout (video copy); second pass runs the concat demuxer with
`-c copy`.

### Explicit `-map` for the second mono track
Concat demuxer **without explicit mapping picks only one track of each type**,
silently dropping the second mono. The final concat therefore uses
`-map 0:v:0 -map 0:a:0 -map 0:a:1`. Without this the output has a single audio track.

### Absolute paths in the concat list
Concat demuxer interprets relative paths **relative to the list file's location**.
With nested temp folders this produced doubled path segments.
`build_concat_demuxer_list` always writes absolute paths.

### asplit when normalising audio
An ffmpeg filter output cannot be used more than once. When splitting into 2 mono the
stream is duplicated via `asplit=2`; without this, 3/4-track files fail with
"stream matches no streams".

### stdin=DEVNULL for ffmpeg/ffprobe
ffmpeg reads stdin by default and **consumes the user's keystrokes** (y/n answers).
All invocations use `stdin=subprocess.DEVNULL`; without this interactive prompts
break.

### AVI PAL DV → XDCAM transcode (handler 1)
Source: 720×576, anamorphic SAR 64:45, bottom field first, stereo pcm_s16le.
Target: 1920×1080, square pixel, top field first, mpeg2 4:2:2 50 Mbit, 2 mono
pcm_s24le. **Interlace is preserved** (no deinterlace): `scale=...:interl=1` scales
fields separately, `setfield=tff` + `-flags +ilme+ildct -top 1` marks top-field-first.
25→25 fps, frame count unchanged (duration is preserved).

> ⚠️ Reversing field order BFF→TFF during SD→HD upscale is technically correct, but
> the result **must be visually checked on moving footage**. This is the only operation
> in the project that automation cannot fully guarantee.

---

## Parallel assembly (`workers` in conf)

- `workers=1` — sequential, with interactive prompts on error.
- `workers>1` — ThreadPoolExecutor, no prompts, errors collected into the final report.
- `workers=0` — number of CPU cores.

Each block is assembled in its own temp subfolder (`_tmp/{HH-MM}`) so workers do not
conflict on `concat_list.txt` and `norm_NNN.mxf` filenames. Progress in parallel mode
is a thread-safe counter under `threading.Lock`, without an animated progress bar.

The mode is determined by the worker count: sequential preserves the old interactive
logic, parallel uses a batch "assemble everything, then report" approach.

---

## Dry-run (`--check`, `auto.run_dry_check`)

All checks run without a single transcode or file write: table parsing, duration
arithmetic from the sheet (table math, not real file durations), file presence +
what would be recovered from backup, audio layouts (what is fixable, what is
critical), wrappers and ffmpeg availability. Returns a verdict: clean / with warnings /
not ready. Uses the same functions as the real assembly, so it cannot diverge in logic.

---

## Target broadcast format (reference)

- Video: mpeg2video 4:2:2, 1920×1080, 25 fps, top field first, 50 Mbit,
  `-flags +ilme+ildct -top 1`, square pixel (SAR 1:1, DAR 16:9).
- Audio: pcm_s24le, 48000 Hz, 2 mono tracks (default).
- Container: MXF (OP1a).
