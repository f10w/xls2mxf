# Broadcast session runbook

Step-by-step guide for the operator. Assumes `xls2mxf.exe` and `xls2mxf.conf`
are already configured (see CONFIG.md).

---

## 1. Preparation

Verify that for the target date the following are in place:

- Traffic sheet in the `xlsx` folder (filename ends with date `DDMMYY`, e.g.
  `Traffic-sheet_City_Channel_170626.xlsx`).
- Clips in the `src` folder.

Date format is **DDMMYY**: 17 June 2026 → `170626`.

---

## 2. Readiness check (mandatory)

Always run the check before assembly — it shows in seconds whether the session
will proceed, without triggering any heavy processing:

```
xls2mxf.exe --check --date 170626
```

### Reading the result

- **"all clear, session is fully ready for assembly"** — safe to assemble.
- **"session will proceed with auto-handling"** + list of warnings — assembly can
  start, but the program will resolve some issues automatically:
  - *"Will be recovered from backup"* — some clips are missing from `src` but exist
    in the backup as `.avi` and will be transcoded.
  - *"Require audio fix"* — some clips have non-standard audio that will be
    normalised to broadcast format.
- **"session NOT ready"** + red lines — critical issues exist; assembly will not
  start until they are fixed:
  - *"Not in src or backup"* — the clip is nowhere. Find it and place it manually.
  - *"No audio tracks"* — the file has no audio; manual preparation required.

---

## 3. Assembly

Once the check is green (or shows only auto-handleable warnings) — start assembly:

```
xls2mxf.exe --mode auto --date 170626
```

What happens in order:

1. **Recovery** — if any clips are missing from `src`, the program takes the `.avi`
   from the backup, transcodes it to broadcast format, and places it in `src`.
2. **Audio fix** — if clips with non-standard audio are found, the program asks once:
   "Convert all to broadcast format (2 mono 24/48)? (y/n)". Answer `y`.
3. **Block assembly** — each ad block is assembled into a file
   `DD-MM-YY_Reklama_RTR_HH-MM.mxf`.
4. **Duration check** — each assembled file is verified: its duration (excluding
   opener and closer) must match the ИТОГО value from the table.

### With parallel mode enabled (workers > 1)

Assembly runs without prompts. Blocks are assembled concurrently; at the end a
summary shows how many succeeded and which blocks had errors. Audio fix in this mode
is still confirmed once before the parallel part begins.

---

## 4. Result

Finished files are in folder `broadcast DDMMYY` (inside `dst` or `output_dir`).
One file per ad block; the filename contains the block's air time.

**Always** review at least the clips recovered from backup (transcoded from AVI) —
check on moving footage that there is no judder or combing. This is the one operation
the program cannot fully guarantee automatically.

---

## 5. Troubleshooting

### "Duration mismatch"
The program will identify which specific clip has the wrong length (expected/got in
frames), or report that all clips are correct — in which case the issue is the ИТОГО
value in the table or the wrapper durations. See the log `DDMMYY.log` for details.

In sequential mode (workers=1) the program asks whether to continue with remaining
blocks. In parallel mode it assembles everything possible and lists the failed blocks
at the end.

### "Not in src or backup"
The file is missing everywhere. Find it and place it in `src` (as `<ID>.mxf`) or in
the backup folder (as `<ID>.avi`), then re-run.

### "No audio tracks"
The clip has no audio. Prepare the file manually and place it in `src`.

### Files not found / wrong folder
Check the paths in `xls2mxf.conf` under `[paths]`. They can be overridden for a
single run with `--xlsx`, `--src`, `--dst`.

### ffmpeg not found
Place `ffmpeg.exe` and `ffprobe.exe` next to the program, or set the paths in conf
under `[ffmpeg]`, or add them to `PATH`.

---

## Where to look for details

Log `DDMMYY.log` next to the program contains the full run history: which tables were
processed, what was recovered, what was fixed, which paths were used, and which blocks
failed the duration check and why.
