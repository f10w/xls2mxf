"""Сборка блоков через ffmpeg и перекоды (аудио-фикс, AVI->XDCAM)."""
from pathlib import Path

from .constants import FPS
from .errors import AssemblyError
from .ffmpeg_tools import _run_ffmpeg

# Кодеки и контейнер для финального выходного файла по формату.
# enc_v / enc_a  — аргументы при reencode-режиме и при финальном concat в copy-режиме.
# copy_final     — если True, финальный concat использует -c copy; иначе — enc_v + enc_a.
_FMT: dict = {
    "mxf": dict(
        enc_v=["-c:v", "mpeg2video", "-b:v", "50M", "-minrate", "50M", "-maxrate", "50M",
               "-bufsize", "17825792", "-flags", "+ilme+ildct", "-top", "1",
               "-pix_fmt", "yuv422p", "-aspect", "16:9", "-r", str(FPS)],
        enc_a=["-c:a", "pcm_s24le", "-ar", "48000"],
        f_arg=["-f", "mxf"],
        copy_final=True,
    ),
    "mp4": dict(
        enc_v=["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p"],
        enc_a=["-c:a", "aac", "-b:a", "192k", "-ar", "48000"],
        f_arg=["-movflags", "+faststart"],
        copy_final=False,  # mpeg2→mp4 без перекода не работает
    ),
    "avi": dict(
        enc_v=["-c:v", "mpeg2video", "-b:v", "50M", "-minrate", "50M", "-maxrate", "50M",
               "-bufsize", "17825792", "-flags", "+ilme+ildct", "-top", "1",
               "-pix_fmt", "yuv422p", "-aspect", "16:9", "-r", str(FPS)],
        enc_a=["-c:a", "pcm_s24le", "-ar", "48000"],
        f_arg=[],
        copy_final=True,  # mpeg2+pcm в AVI — копируем как есть
    ),
}


def _fmt(out_format: str) -> dict:
    return _FMT.get(out_format, _FMT["mxf"])


def _audio_filter_for_input(layout: str, target: str, in_index: int):
    """Возвращает (filter_parts, out_labels) для приведения аудио одного входа
    к целевой раскладке. target: '2mono' | 'stereo'."""
    # layout — что у входа ('2mono'|'1stereo'); target — что хотим на выходе.
    # Здесь обрабатываются только валидные layout (2mono/1stereo), 'other'
    # отсеивается раньше с обработчиком 3.
    parts = []
    if target == "2mono":
        if layout == "2mono":
            # уже две моно — берём как есть
            return [], [f"{in_index}:a:0", f"{in_index}:a:1"]
        else:  # 1stereo -> split на 2 моно
            parts.append(f"[{in_index}:a:0]channelsplit=channel_layout=stereo[{in_index}L][{in_index}R]")
            return parts, [f"[{in_index}L]", f"[{in_index}R]"]
    else:  # target stereo
        if layout == "1stereo":
            return [], [f"{in_index}:a:0"]
        else:  # 2mono -> merge в стерео
            parts.append(f"[{in_index}:a:0][{in_index}:a:1]amerge=inputs=2[{in_index}S]")
            return parts, [f"[{in_index}S]"]



def build_concat_demuxer_list(files: list, list_path: Path):
    """Пишет файл-список для concat demuxer.
    Пути абсолютные: concat demuxer трактует относительные пути относительно
    расположения самого list-файла, что ломается при вложенных папках.
    На Windows используем прямые слеши: ffmpeg их принимает, и UNC-пути вида
    \\\\server\\share\\... превращаются в //server/share/... без риска
    потерять ведущий слеш при парсинге concat-листа."""
    import os
    lines = []
    for f in files:
        ap = str(Path(f).resolve())
        if os.name == "nt":
            ap = ap.replace("\\", "/")
        # экранирование одинарных кавычек по правилам ffmpeg concat
        p = ap.replace("'", "'\\''")
        lines.append(f"file '{p}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")



def assemble_block_reencode(inputs: list, layouts: list, out_path: Path,
                            ffmpeg: str, audio_layout: str, log,
                            out_format: str = "mxf") -> None:
    """Один проход: concat-фильтр, видео и аудио перекодируются.
    inputs — полный список файлов (opener + ролики + closer)."""
    cmd = [ffmpeg, "-y"]
    for f in inputs:
        cmd += ["-i", str(f)]

    n = len(inputs)
    filt = []
    # видео-сегменты
    for i in range(n):
        filt.append(f"[{i}:v:0]setsar=1[v{i}]")
    # аудио по каждому входу к целевой раскладке
    a_streams_per_input = []
    for i in range(n):
        parts, labels = _audio_filter_for_input(layouts[i], audio_layout, i)
        filt += parts
        a_streams_per_input.append(labels)

    if audio_layout == "2mono":
        # concat с v=1 a=2: каждый сегмент даёт video + 2 mono
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

    fmt = _fmt(out_format)
    cmd += fmt["enc_v"] + fmt["enc_a"] + fmt["f_arg"] + [str(out_path)]
    _run_ffmpeg(cmd, ffmpeg, out_path, log)



def _lbl(s: str) -> str:
    """Оборачивает поток в [..] если это сырой индекс вида '0:a:0'."""
    return s if s.startswith("[") else f"[{s}]"



def assemble_block_copy(inputs: list, layouts: list, out_path: Path,
                        ffmpeg: str, audio_layout: str, tmp_dir: Path, log,
                        out_format: str = "mxf") -> list:
    """Двухпроходно: каждый вход -> временный MXF с видео COPY и аудио,
    приведённым к целевой раскладке; затем concat demuxer в финальный формат.
    Для MP4 финальный шаг перекодирует видео в H.264 + AAC.
    Возвращает список временных файлов для последующей очистки."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    normalized = []
    tmp_files = []
    for i, f in enumerate(inputs):
        tmpf = tmp_dir / f"norm_{i:03d}.mxf"
        tmp_files.append(tmpf)
        cmd = [ffmpeg, "-y", "-i", str(f)]
        if audio_layout == "2mono":
            if layouts[i] == "2mono":
                # видео copy, обе моно-дорожки copy
                cmd += ["-map", "0:v:0", "-map", "0:a:0", "-map", "0:a:1",
                        "-c:v", "copy", "-c:a", "copy"]
            else:  # 1stereo -> 2 mono (видео copy, аудио перекод в pcm)
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

    # concat demuxer. ВАЖНО: без явного -map берёт только ОДНУ дорожку каждого
    # типа, теряя вторую моно. Поэтому маппим явно.
    list_path = tmp_dir / "concat_list.txt"
    build_concat_demuxer_list(normalized, list_path)
    cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
           "-map", "0:v:0", "-map", "0:a:0"]
    if audio_layout == "2mono":
        cmd += ["-map", "0:a:1"]
    fmt = _fmt(out_format)
    if fmt["copy_final"]:
        cmd += ["-c", "copy"] + fmt["f_arg"] + [str(out_path)]
    else:
        cmd += fmt["enc_v"] + fmt["enc_a"] + fmt["f_arg"] + [str(out_path)]
    _run_ffmpeg(cmd, ffmpeg, out_path, log)
    tmp_files.append(list_path)
    return tmp_files



def fix_audio_to_2mono(src_file: Path, out_file: Path, chans: list,
                       ffmpeg: str, log) -> None:
    """Приводит аудио файла к двум моно-дорожкам (pcm_s24le 48k), видео COPY.
    Правило: берём первые два аудиоканала всего потока -> две моно-дорожки.
    Если канал один — дублируем его в обе дорожки.
    chans — список каналов по дорожкам (из probe_audio_streams)."""
    out_file.parent.mkdir(parents=True, exist_ok=True)
    total_channels = sum(chans) if chans else 0
    if total_channels <= 0:
        raise AssemblyError(
            f"У файла {src_file.name} нет аудиодорожек — починка невозможна.",
            handler=3, payload={"file": str(src_file)})

    # Собираем все аудиовходы в один поток, затем берём первые 1-2 канала.
    # amerge сводит все дорожки в один многоканальный поток (по порядку каналов).
    # Выход фильтра нельзя использовать дважды — поэтому размножаем через asplit.
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
        # первый канал -> дор.1, второй канал -> дор.2
        parts.append(f"{b0}pan=mono|c0=c0[a0]")
        parts.append(f"{b1}pan=mono|c0=c1[a1]")
    else:
        # один канал -> дублируем в обе дорожки
        parts.append(f"{b0}pan=mono|c0=c0[a0]")
        parts.append(f"{b1}pan=mono|c0=c0[a1]")

    filt = ";".join(parts)

    cmd = [ffmpeg, "-y", "-i", str(src_file),
           "-filter_complex", filt,
           "-map", "0:v:0", "-map", "[a0]", "-map", "[a1]",
           "-c:v", "copy", "-c:a", "pcm_s24le", "-ar", "48000",
           "-f", "mxf", str(out_file)]
    _run_ffmpeg(cmd, ffmpeg, out_file, log)


# ---------- ОБРАБОТЧИК 1: добор из резерва (AVI PAL DV -> XDCAM HD422) ----------


def transcode_avi_to_xdcam(avi_file: Path, out_mxf: Path, ffmpeg: str, log) -> None:
    """Перекодирует AVI PAL DV widescreen (576i25 BFF, анаморф SAR 64:45, стерео)
    в эфирный XDCAM HD422 (1080i25 TFF, 50 Мбит, 2 моно pcm_s24le 48k).
    Интерлейс СОХРАНЯЕТСЯ: масштабирование интерлейс-aware (поля раздельно),
    выход помечается верхним полем (TFF), число кадров не меняется (25->25 fps)."""
    out_mxf.parent.mkdir(parents=True, exist_ok=True)

    # видео: интерлейс-aware масштаб 720x576 -> 1920x1080, квадратный пиксель,
    #        пометка верхнего поля, формат 4:2:2.
    vf = ("scale=1920:1080:interl=1:flags=lanczos,"
          "setsar=1,setfield=tff,format=yuv422p")

    # аудио: стерео -> 2 моно, поднимаем до 24 бит / 48 кГц.
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

