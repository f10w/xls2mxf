# xls2mxf.conf reference

The config file lives next to the program. If it does not exist it is created
automatically on first run with default values. Format: INI (sections in square
brackets, parameters as `key = value`, comments with `;`).

## Path rules (Windows)

- Write paths the normal Windows way with backslashes: `D:\Broadcast\Clips`.
- **No quotes**, even when the path contains spaces: `C:\My Files\clips` is fine.
- Forward slashes also work: `D:/Broadcast/Clips`.
- UNC network paths are supported: `\\server\share\Clips`.
- **Do not double** backslashes (`\\`) — write just one.
- If a path contains `%`, double it: `%%` (INI format limitation).
- Non-ASCII characters in paths work (the conf file is UTF-8).

---

## [paths] — working folders

```ini
[paths]
xlsx = D:\Broadcast\Traffic sheets
src  = D:\Broadcast\Clips
dst  = D:\Broadcast\Output
```

| Parameter | Purpose |
|-----------|---------|
| `xlsx` | Folder with traffic-sheet `.xlsx` files. The program picks files whose name ends with the requested date. |
| `src` | Folder containing source clips `.mxf` (filename = clip ID). Recovered backup clips are also placed here. |
| `dst` | Base destination folder. `clips DDMMYY` (manual) and `broadcast DDMMYY` (auto) are created inside it. |

A single `.` means the current folder.

---

## [clipboard] — labels for manual mode

```ini
[clipboard]
customline1 = customline1
customline2 = customline2
customline3 = customline3
```

Used only in manual mode when copying the ID list to the clipboard.
Every gap between blocks in the table is replaced with exactly these three lines
(in order 1, 2, 3). These are text labels for pasting into Excel, **not file paths**.

---

## [ffmpeg] — binary paths

```ini
[ffmpeg]
ffmpeg =
ffprobe =
```

| Parameter | Purpose |
|-----------|---------|
| `ffmpeg` | Path to `ffmpeg.exe`. Empty = look next to the program, then in `PATH`. |
| `ffprobe` | Path to `ffprobe.exe`. Same search order. |

Search order when the value is empty: **conf path → folder next to the program → PATH**.

---

## [assembly] — auto-assembly settings

```ini
[assembly]
middle = Reklama_RTR
opener = D:\Broadcast\Wrappers\opener.mxf
closer = D:\Broadcast\Wrappers\closer.mxf
backup_source = D:\Broadcast\Backup
output_dir =
video_mode = copy
audio_layout = 2mono
output_format = mxf
h264_bitrate = 16m
workers = 1
```

### middle
Middle part of the output filename. The name is built as
`{DD-MM-YY}_{middle}_{HH-MM}.mxf`. Underscores are added automatically —
specify only the part itself, e.g. `Reklama_RTR`.
Result: `17-06-26_Reklama_RTR_05-25.mxf`.

### opener / closer
Paths to wrapper files (opener and closer). Must be in broadcast XDCAM HD422
format (2 mono or 1 stereo audio). The opener is prepended to the block's clips,
the closer appended. Wrappers are not fixed automatically: non-standard audio in a
wrapper is a critical error that stops assembly.

### backup_source
Fallback source for missing clips. If a `<ID>.mxf` is not found in `src`, the
program looks for `<ID>.avi` here, transcodes it to broadcast XDCAM, and places the
result in `src`. Empty = recovery disabled (missing files cause a critical stop).
Expected backup format: AVI PAL DV widescreen.

### output_dir
Base folder for output. Assembled files are **always** placed in a subfolder
`broadcast DDMMYY`. If `output_dir` is empty, the subfolder is created inside `dst`.
If set, it is created inside `output_dir`. Either way each session date gets its own
subfolder, not a shared root.

### video_mode
Video processing strategy during assembly:

| Value | Behaviour |
|-------|-----------|
| `copy` | Video is copied bit-for-bit, audio is remixed. Two-pass. Faster, no video quality loss. **Recommended.** |
| `reencode` | Single pass, video and audio are re-encoded. Slower, video is not bit-for-bit. |

### audio_layout
Target audio layout in the assembled file:

| Value | Result |
|-------|--------|
| `2mono` | Two mono tracks (broadcast standard). **Default.** |
| `stereo` | One stereo track. |

All clips are normalised to this layout during assembly (stereo is split into 2 mono
and vice versa).

### output_format
Container and codec for the assembled files:

| Value | Format |
|-------|--------|
| `mxf` | MXF OP1a, XDCAM HD422: mpeg2video 50 Mbit + pcm_s24le 48 kHz. **Default, broadcast.** |
| `mp4` | MP4: H.264 + AAC 192k. Video is always re-encoded regardless of `video_mode`. |
| `avi` | AVI: mpeg2video 50 Mbit + pcm_s24le. Video copy when `video_mode=copy`. |

### h264_bitrate
Target bitrate for H.264 when `output_format=mp4`.
Format: `16m` (16 Mbit/s), `500k` (500 kbit/s). `bufsize` is set automatically as 2×
bitrate. Has no effect for `mxf` or `avi`.

### workers
Number of parallel block assemblies:

| Value | Behaviour |
|-------|-----------|
| `1` | Sequential. On a duration mismatch, asks whether to continue. |
| `>1` | Parallel (N blocks at once). No prompts — all errors go to the final report. |
| `0` | Automatically set to the CPU core count. |

For `reencode` the typical optimum is 2–4 (CPU-bound). For `copy` more workers are
feasible (disk-bound). Tune by watching system load.

---

## Minimal working example

```ini
[paths]
xlsx = D:\Broadcast\Traffic sheets
src  = D:\Broadcast\Clips
dst  = D:\Broadcast\Output

[clipboard]
customline1 = customline1
customline2 = customline2
customline3 = customline3

[ffmpeg]
ffmpeg =
ffprobe =

[assembly]
middle = Reklama_RTR
opener = D:\Broadcast\Wrappers\opener.mxf
closer = D:\Broadcast\Wrappers\closer.mxf
backup_source = D:\Broadcast\Backup
output_dir =
video_mode = copy
audio_layout = 2mono
output_format = mxf
h264_bitrate = 16m
workers = 4
```
