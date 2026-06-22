# XLS2MXF

Tool for preparing broadcast ad blocks from traffic sheets.

Works in two modes:

- **Auto** (default) — slices the traffic sheet into ad blocks, and for each block
  assembles an ffmpeg sequence "opener → clips → closer" into a ready broadcast file.
  Runs a preflight check automatically before assembly, and only proceeds on success.
  Verifies duration and resolves common issues automatically (non-standard audio,
  missing clips).
- **Manual** (`--mode manual`) — extracts clip IDs from the traffic sheet for the
  requested date, finds the corresponding `.mxf` files, and copies them to a folder.

> **Windows note:** the binary is named `xls2mxf.exe`; on Linux/macOS it is `xls2mxf`.
> All examples below use `xls2mxf` — add `.exe` on Windows.

---

## Quick start

1. Place `xls2mxf.conf` next to the binary (it is created automatically on first
   run — edit the paths to match your setup).
2. Make sure `ffmpeg` and `ffprobe` are available: next to the binary, in PATH,
   or set the paths in conf under `[ffmpeg]`.
3. Check configuration:

```
xls2mxf --doctor
```

4. Run — without arguments the program takes tomorrow's date and starts auto assembly:

```
xls2mxf
```

---

## Common commands

Check configuration (paths, ffmpeg, wrappers):
```
xls2mxf --doctor
```

Run auto assembly for a specific date:
```
xls2mxf --date 170626
```

Verify the session without assembly (dry-run):
```
xls2mxf --check --date 170626
```

Assemble and open the output folder immediately:
```
xls2mxf --date 170626 --open
```

Manual mode (copy clips to folder):
```
xls2mxf --mode manual --date 170626
```

Interactive mode (program prompts for date and mode):
```
xls2mxf --manual
```

---

## Command-line arguments

| Argument | Description |
|----------|-------------|
| `--date DDMMYY` | Session date. Defaults to tomorrow. |
| `--mode manual\|auto` | Run mode. Defaults to auto. With `--manual` — prompts. |
| `--check` | Dry-run: verify session readiness without assembly or transcoding. |
| `--manual` | Interactive mode: prompts for date, mode, and other questions. |
| `--doctor` | Diagnostics: checks paths, ffmpeg, wrappers, and config values. |
| `--open` | Open the output folder in the file manager after successful assembly. |
| `--xlsx PATH` | Traffic-sheet folder (overrides conf). |
| `--src PATH` | Source clips folder (overrides conf). |
| `--dst PATH` | Destination folder (overrides conf). |

---

## Output

- **Auto mode:** folder `broadcast DDMMYY` (inside `dst` or `output_dir`) with
  assembled files named `DD-MM-YY_Reklama_RTR_HH-MM.mxf` — one per ad block.
- **Manual mode:** folder `clips DDMMYY` (inside `dst`) with copied `.mxf` files.
- **Log** `DDMMYY.log` next to the binary — full run details.

---

## Double-run protection

On start a `DDMMYY.lock` file is created next to the binary. If a second instance
is launched for the same date it will print a warning and exit. The lock is deleted
on completion, including on error exit.

---

## Notifications

On Windows, a toast notification appears after assembly finishes (success or error).
This lets you start the program and do other work without watching the terminal.

---

## Parallel assembly

By default blocks are assembled sequentially (`workers=1`). For faster processing
set `workers=N` in `xls2mxf.conf` under `[assembly]`, where N is the number of
concurrent ffmpeg processes. In parallel mode duration errors do not interrupt work —
they are collected into the final report. Run `--check` before enabling parallel mode.

---

## Documentation

- **CONFIG.md** — reference for all `xls2mxf.conf` parameters.
- **RUNBOOK.md** — step-by-step broadcast session guide.
- **ARCHITECTURE.md** — internal design for developers.

---

## Requirements

- Windows 10+, Linux, or macOS.
- `ffmpeg` and `ffprobe` (for auto mode).
- Traffic sheets as `.xlsx` files with date `DDMMYY` at the end of the filename.
