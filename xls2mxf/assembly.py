"""Block assembly via ffmpeg and transcodes (audio fix, AVI->XDCAM)."""
from pathlib import Path

from .constants import FPS
from .errors import AssemblyError
from .ffmpeg_tools import _run_ffmpeg

# Codec and container settings for the final output file, keyed by format.
# enc_v / enc_a  — arguments used in reencode mode and in the final concat of copy mode.
# copy_final     — if True, the final concat uses -c copy; otherwise enc_v + enc_a.
_FMT: dict = {
    "mxf": dict(
        enc_v=["-c:v", "mpeg2video", "-b:v", "50M", "-minrate", "50M", "-maxrate", "50M",
               "-bufsize", "17825792", "-flags", "+ilme+ildct", "-top", "1",
               "-pix_fmt", "yuv422p", "-aspect", "16:9", "-r", str(FPS)],
        enc_a=["-c:a", "pcm_s24le", "-ar", "48000"],
        f_arg=["-f", "mxf"],
        copy_final=True,
    ),
    # mp4 is built dynamically in _fmt() — bitrate comes from config

    "avi": dict(
        enc_v=["-c:v", "mpeg2video", "-b:v", "50M", "-minrate", "50M", "-maxrate", "50M",
               "-bufsize", "17825792", "-flags", "+ilme+ildct", "-top", "1",
               "-pix_fmt", "yuv422p", "-aspect", "16:9", "-r", str(FPS)],
        enc_a=["-c:a", "pcm_s24le", "-ar", "48000"],
        f_arg=[],
        copy_final=True,  # mpeg2+pcm in AVI — copy as-is
    ),
}


def _fmt(out_format: str, h264_bitrate: str = "16m") -> dict:
    if out_format == "mp4":
        return dict(
            enc_v=["-c:v", "libx264", "-b:v", h264_bitrate,
                   "-maxrate", h264_bitrate, "-bufsize", _bufsize(h264_bitrate),
                   "-preset", "medium", "-pix_fmt", "yuv420p"],
            enc_a=["-c:a", "aac", "-b:a", "192k", "-ar", "48000"],
            f_arg=["-movflags", "+faststart"],
            copy_final=False,
        )
    return _FMT.get(out_format, _FMT["mxf"])


def _bufsize(bitrate: str) -> str:
    """Doubles bitrate for bufsize: '16m' -> '32m', '500k' -> '1000k'."""
    s = bitrate.strip().lower()
    if s.endswith("m"):
        return str(int(float(s[:-1]) * 2)) + "m"
    if s.endswith("k"):
        return str(int(float(s[:-1]) * 2)) + "k"
    return str(int(float(s) * 2))


def _audio_filter_for_input(layout: str, target: str, in_index: int):
    """Returns (filter_parts, out_labels) to normalise audio of one input
    to the target layout. target: '2mono' | 'stereo'."""
    # layout — what the input has ('2mono'|'1stereo'); target — what we want.
    # Only valid layouts (2mono/1stereo) reach here; 'fixable' is handled earlier
    # by handler 3.
    parts = []
    if target == "2mono":
        if layout == "2mono":
            # already two mono tracks — use as-is
            return [], [f"{in_index}:a:0", f"{in_index}:a:1"]
        else:  # 1stereo -> split into 2 mono
            parts.append(f"[{in_index}:a:0]channelsplit=channel_layout=stereo[{in_index}L][{in_index}R]")
            return parts, [f"[{in_index}L]", f"[{in_index}R]"]
    else:  # target stereo
        if layout == "1stereo":
            return [], [f"{in_index}:a:0"]
        else:  # 2mono -> merge into stereo
            parts.append(f"[{in_index}:a:0][{in_index}:a:1]amerge=inputs=2[{in_index}S]")
            return parts, [f"[{in_index}S]"]



def build_concat_demuxer_list(files: list, list_path: Path):
    """Writes a file list for the concat demuxer.
    Paths are absolute: the concat demuxer resolves relative paths relative to
    the list file itself, which breaks with nested temp folders.
    On Windows forward slashes are used: ffmpeg accepts them, and UNC paths like
    \\\\server\\share\\... become //server/share/... without losing the leading
    slash during concat-list parsing."""
    import os
    lines = []
    for f in files:
        ap = str(Path(f).resolve())
        if os.name == "nt":
            ap = ap.replace("\\", "/")
        # escape single quotes per ffmpeg concat rules
        p = ap.replace("'", "'\\''")
        lines.append(f"file '{p}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")



def assemble_block_reencode(inputs: list, layouts: list, out_path: Path,
                            ffmpeg: str, audio_layout: str, log,
                            out_format: str = "mxf",
                            h264_bitrate: str = "16m") -> None:
    """Single-pass assembly: concat filter, video and audio are re-encoded.
    inputs — full file list (opener + clips + closer)."""
    cmd = [ffmpeg, "-y"]
    for f in inputs:
        cmd += ["-i", str(f)]

    n = len(inputs)
    filt = []
    # video segments
    for i in range(n):
        filt.append(f"[{i}:v:0]setsar=1[v{i}]")
    # audio per input normalised to the target layout
    a_streams_per_input = []
    for i in range(n):
        parts, labels = _audio_filter_for_input(layouts[i], audio_layout, i)
        filt += parts
        a_streams_per_input.append(labels)

    if audio_layout == "2mono":
        # concat with v=1 a=2: each segment contributes video + 2 mono tracks
        concat_in = "".join(
            f"[v{i}]" + _lbl(a_streams_per_input[i][0]) + _lbl(a_streams_per_input[i][1])
            for i in range(n)
        )
        filt.append(f"{concat_in}concat=n={n}:v=1:a=2[vout][aout0][aout1]")
        cmd += ["-filter_complex", ";".join(filt),
                "-map", "[vout]", "-map", "[aout0]", "-map", "[aout1]"]
    else:
        concat_in = "".join(
            f"[v{i}]" + _lbl(a_streams_per_input[i][0]) for i in range(n)
        )
        filt.append(f"{concat_in}concat=n={n}:v=1:a=1[vout][aout]")
        cmd += ["-filter_complex", ";".join(filt),
                "-map", "[vout]", "-map", "[aout]"]

    fmt = _fmt(out_format, h264_bitrate)
    cmd += fmt["enc_v"] + fmt["enc_a"] + fmt["f_arg"] + [str(out_path)]
    _run_ffmpeg(cmd, ffmpeg, out_path, log)



def _lbl(s: str) -> str:
    """Wraps a stream specifier in [...] if it's a raw index like '0:a:0'."""
    return s if s.startswith("[") else f"[{s}]"



def assemble_block_copy(inputs: list, layouts: list, out_path: Path,
                        ffmpeg: str, audio_layout: str, tmp_dir: Path, log,
                        out_format: str = "mxf",
                        h264_bitrate: str = "16m") -> list:
    """Two-pass assembly: each input -> temp MXF with video COPY and audio
    normalised to the target layout; then concat demuxer into the final format.
    For MP4 the final pass re-encodes video to H.264 + AAC.
    Returns a list of temp files for subsequent cleanup."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    normalized = []
    tmp_files = []
    for i, f in enumerate(inputs):
        tmpf = tmp_dir / f"norm_{i:03d}.mxf"
        tmp_files.append(tmpf)
        cmd = [ffmpeg, "-y", "-i", str(f)]
        if audio_layout == "2mono":
            if layouts[i] == "2mono":
                # video copy, both mono tracks copy
                cmd += ["-map", "0:v:0", "-map", "0:a:0", "-map", "0:a:1",
                        "-c:v", "copy", "-c:a", "copy"]
            else:  # 1stereo -> 2 mono (video copy, audio transcode to pcm)
                cmd += ["-filter_complex",
                        "[0:a:0]channelsplit=channel_layout=stereo[L][R]",
                        "-map", "0:v:0", "-map", "[L]", "-map", "[R]",
                        "-c:v", "copy", "-c:a", "pcm_s24le", "-ar", "48000"]
        else:  # target stereo
            if layouts[i] == "1stereo":
                cmd += ["-map", "0:v:0", "-map", "0:a:0",
                        "-c:v", "copy", "-c:a", "copy"]
            else:  # 2mono -> stereo
                cmd += ["-filter_complex",
                        "[0:a:0][0:a:1]amerge=inputs=2[S]",
                        "-map", "0:v:0", "-map", "[S]",
                        "-c:v", "copy", "-c:a", "pcm_s24le", "-ar", "48000"]
        cmd += ["-f", "mxf", str(tmpf)]
        _run_ffmpeg(cmd, ffmpeg, tmpf, log)
        normalized.append(tmpf)

    # concat demuxer. NOTE: without explicit -map it picks only ONE track of each
    # type, losing the second mono. Map explicitly.
    list_path = tmp_dir / "concat_list.txt"
    build_concat_demuxer_list(normalized, list_path)
    cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
           "-map", "0:v:0", "-map", "0:a:0"]
    if audio_layout == "2mono":
        cmd += ["-map", "0:a:1"]
    fmt = _fmt(out_format, h264_bitrate)
    if fmt["copy_final"]:
        cmd += ["-c", "copy"] + fmt["f_arg"] + [str(out_path)]
    else:
        cmd += fmt["enc_v"] + fmt["enc_a"] + fmt["f_arg"] + [str(out_path)]
    _run_ffmpeg(cmd, ffmpeg, out_path, log)
    tmp_files.append(list_path)
    return tmp_files



def fix_audio_to_2mono(src_file: Path, out_file: Path, chans: list,
                       ffmpeg: str, log) -> None:
    """Normalises a file's audio to two mono tracks (pcm_s24le 48k), video COPY.
    Rule: take the first two audio channels of the merged stream -> two mono tracks.
    If there is only one channel — duplicate it into both tracks.
    chans — channel counts per stream (from probe_audio_streams)."""
    out_file.parent.mkdir(parents=True, exist_ok=True)
    total_channels = sum(chans) if chans else 0
    if total_channels <= 0:
        raise AssemblyError(
            f"{src_file.name} has no audio tracks — cannot fix.",
            handler=3, payload={"file": str(src_file)})

    # Merge all audio inputs into one stream, then take the first 1-2 channels.
    # amerge combines all tracks into one multi-channel stream (channel order preserved).
    # A filter output cannot be used twice — duplicate via asplit.
    n_audio = len(chans)
    parts = []
    if n_audio > 1:
        merge = "".join(f"[0:a:{i}]" for i in range(n_audio)) + \
                f"amerge=inputs={n_audio}[m]"
        parts.append(merge)
        parts.append("[m]asplit=2[m0][m1]")
        b0, b1 = "[m0]", "[m1]"
    else:
        parts.append("[0:a:0]asplit=2[m0][m1]")
        b0, b1 = "[m0]", "[m1]"

    if total_channels >= 2:
        # first channel -> track 1, second channel -> track 2
        parts.append(f"{b0}pan=mono|c0=c0[a0]")
        parts.append(f"{b1}pan=mono|c0=c1[a1]")
    else:
        # single channel — duplicate into both tracks
        parts.append(f"{b0}pan=mono|c0=c0[a0]")
        parts.append(f"{b1}pan=mono|c0=c0[a1]")

    filt = ";".join(parts)

    cmd = [ffmpeg, "-y", "-i", str(src_file),
           "-filter_complex", filt,
           "-map", "0:v:0", "-map", "[a0]", "-map", "[a1]",
           "-c:v", "copy", "-c:a", "pcm_s24le", "-ar", "48000",
           "-f", "mxf", str(out_file)]
    _run_ffmpeg(cmd, ffmpeg, out_file, log)


# ---------- HANDLER 1: fallback recovery (AVI PAL DV -> XDCAM HD422) ----------


def transcode_avi_to_xdcam(avi_file: Path, out_mxf: Path, ffmpeg: str, log) -> None:
    """Transcodes AVI PAL DV widescreen (576i25 BFF, anamorphic SAR 64:45, stereo)
    to broadcast XDCAM HD422 (1080i25 TFF, 50 Mbit, 2 mono pcm_s24le 48k).
    Interlace is PRESERVED: scaling is interlace-aware (fields processed separately),
    output is tagged as top-field-first (TFF), frame count unchanged (25->25 fps)."""
    out_mxf.parent.mkdir(parents=True, exist_ok=True)

    # video: interlace-aware scale 720x576 -> 1920x1080, square pixel,
    #        top-field tag, 4:2:2 format.
    vf = ("scale=1920:1080:interl=1:flags=lanczos,"
          "setsar=1,setfield=tff,format=yuv422p")

    # audio: stereo -> 2 mono, upsample to 24-bit / 48 kHz.
    af = "[0:a:0]channelsplit=channel_layout=stereo[aL][aR]"

    cmd = [ffmpeg, "-y", "-i", str(avi_file),
           "-filter_complex", f"[0:v:0]{vf}[v];{af}",
           "-map", "[v]", "-map", "[aL]", "-map", "[aR]",
           "-c:v", "mpeg2video", "-b:v", "50M", "-minrate", "50M", "-maxrate", "50M",
           "-bufsize", "17825792",
           "-flags", "+ilme+ildct", "-top", "1",
           "-aspect", "16:9", "-r", str(FPS),
           "-c:a", "pcm_s24le", "-ar", "48000",
           "-f", "mxf", str(out_mxf)]
    _run_ffmpeg(cmd, ffmpeg, out_mxf, log)
