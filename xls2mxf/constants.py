"""Project constants."""
import re

EXT = ".mxf"  # extension of source clips — always .mxf

# output file extensions by format
FORMAT_EXT = {"mxf": ".mxf", "mp4": ".mp4", "avi": ".avi"}
CONF_NAME = "xls2mxf.conf"
DATE_RE = re.compile(r"(\d{6})$")  # DDMMYY at the end of the filename stem
FPS = 25  # PAL — used for frame-accurate duration comparison

DEFAULT_CONF = """\
[paths]
; folder with Excel traffic sheets
xlsx = .
; folder containing source .mxf clips
src = .
; base folder where the output subfolder is created
dst = .

[clipboard]
; fill text for gaps between blocks when copying the ID list to clipboard.
; each gap is replaced with exactly these three lines.
customline1 = customline1
customline2 = customline2
customline3 = customline3

[ffmpeg]
; paths to binaries. Empty = search next to the program, then PATH.
ffmpeg =
ffprobe =

[assembly]
; middle part of the output filename: {DD-MM-YY}_{middle}_{HH-MM}.mxf
middle = Reklama_RTR
; paths to wrapper files (consistent XDCAM HD422 MXF)
opener =
closer =
; fallback source for missing clips (AVI PAL DV). Files are looked up as <ID>.avi
; and transcoded to broadcast XDCAM, then placed into the src folder.
backup_source =
; base for the output folder. Files always go into subfolder "broadcast on DDMMYY".
; empty = subfolder is created inside dst.
output_dir =
; video strategy: copy  (video untouched, audio remixed; two-pass)
;                reencode (single pass, video and audio re-encoded)
video_mode = copy
; audio layout in the output file: 2mono (default) | stereo
audio_layout = 2mono
; output file format:
;   mxf — MXF OP1a, XDCAM HD422, mpeg2 50M + pcm_s24le  [default, broadcast]
;   mp4 — MP4, H.264 + AAC 192k  (video always transcoded)
;   avi — AVI, mpeg2 50M + pcm_s24le  (video copy when video_mode=copy)
output_format = mxf
; H.264 bitrate for output_format=mp4. Format: 16m (16 Mbit), 500k (500 kbit).
; bufsize is set automatically as 2x bitrate.
h264_bitrate = 16m
; local folder for temporary files (norm_NNN.mxf, audiofix).
; Recommended for network share (SMB/UNC) workflows: temp files will be
; created locally, significantly speeding up assembly.
; A date-named subfolder (DDMMYY) is created and removed automatically.
; Empty = temp files are created alongside the output files (in output_dir/dst).
temp_dir =
[table]
; column header that identifies the clip ID column (text in the header row, any column)
header_id = ID ролика
; keyword in column D that marks the block totals row
header_total = ИТОГО
; filename prefix that identifies the standard traffic sheet
sheet_prefix = Траффик-лист

; Number of parallel ffmpeg processes during block assembly.
;
;   workers = 1   — SEQUENTIAL [default, recommended]
;                   Blocks are assembled one at a time. On a duration mismatch
;                   the program stops and asks whether to continue.
;                   System load is minimal.
;
;   workers = N   — PARALLEL (N concurrent ffmpeg processes)
;                   Faster on multi-core machines, but all duration errors
;                   accumulate into the final report — no interactive prompts.
;                   Recommended only after a successful --check.
;
;   workers = 0   — automatic, based on CPU core count (maximum load).
;
; WARNING: with workers > 1, if one block fails the remaining blocks continue
; assembling. Ensure the session has passed --check before enabling parallel mode.
workers = 1
"""
