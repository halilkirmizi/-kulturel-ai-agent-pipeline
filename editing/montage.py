"""News-mode montage: fast-cut stock b-roll + player photos + kinetic captions.

Builds a vertical 1080x1920 Short from a voiceover, its VTT timings, and an
ordered list of media (videos + photos). Each visual gets an equal slice of the
voiceover duration; photos get a Ken-Burns zoom, videos are cover-cropped. Then
the VTT is burned as big bold captions and the voiceover (+ low music) is mixed.

All FFmpeg runs through ffmpeg_builder.execute with cwd=out_dir so filter paths
(subtitles) stay relative and dodge Windows drive-letter colon escaping.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

from core.logger import get_logger
from editing.ffmpeg_builder import execute, ffmpeg_path, probe_duration

log = get_logger(__name__)

_W, _H, _FPS = 1080, 1920, 30


class MontageError(Exception):
    pass


# ---------------- captions (.ass from .vtt) ----------------
def _parse_vtt(path: Path) -> List[tuple]:
    cues = []
    txt = Path(path).read_text(encoding="utf-8")
    pat = r"(\d\d):(\d\d):(\d\d)[.,](\d\d\d)\s*-->\s*(\d\d):(\d\d):(\d\d)[.,](\d\d\d)\s*\n(.+)"
    for m in re.finditer(pat, txt):
        g = m.groups()
        st = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000
        en = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 1000
        cues.append((st, en, g[8].strip()))
    return cues


def _chunk_cues(cues: List[tuple], maxw: int = 4) -> List[tuple]:
    out = []
    for st, en, text in cues:
        words = text.split()
        if len(words) <= maxw:
            out.append((st, en, text))
            continue
        n = (len(words) + maxw - 1) // maxw
        per = (en - st) / n
        for i in range(n):
            seg = " ".join(words[i * maxw:(i + 1) * maxw])
            if seg:
                out.append((st + i * per, st + (i + 1) * per, seg))
    return out


def _ass_time(t: float) -> str:
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _write_ass(cues: List[tuple], dest: Path) -> None:
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {_W}
PlayResY: {_H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: News,Impact,110,&H00FFFFFF,&H00000000,&H00000000,-1,1,7,3,2,60,60,720,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [f"Dialogue: 0,{_ass_time(st)},{_ass_time(en)},News,,0,0,0,,{text.upper()}"
             for st, en, text in cues]
    Path(dest).write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


# ---------------- montage ----------------
def build_montage(
    out_dir: Path,
    voice_rel: str,
    vtt_rel: str,
    media: List[Dict],
    out_rel: str,
    config,
    music_abs: Optional[str] = None,
) -> Path:
    """Assemble the final news Short. Returns the output path.

    Args:
        out_dir: working directory (absolute); all rel paths resolve here.
        voice_rel/vtt_rel: voiceover mp3 + vtt, relative to out_dir.
        media: ordered [{"path": rel, "is_photo": bool}, ...].
        out_rel: output filename relative to out_dir.
    """
    out_dir = Path(out_dir)
    cwd = str(out_dir)
    ff = ffmpeg_path()

    total = probe_duration(out_dir / voice_rel)
    if total <= 0:
        raise MontageError("could not probe voiceover duration")
    n = len(media)
    if n < 2:
        raise MontageError(f"need >=2 media items, got {n}")
    seg_dur = total / n
    frames = round(seg_dur * _FPS)
    log.info("[montage] %.2fs voiceover, %d visuals x %.2fs", total, n, seg_dur)

    # captions
    cues = _chunk_cues(_parse_vtt(out_dir / vtt_rel), maxw=4)
    _write_ass(cues, out_dir / "captions.ass")

    # 1. normalize each visual to a 1080x1920/30fps clip
    seg_dir = out_dir / "seg"
    seg_dir.mkdir(exist_ok=True)
    seg_files: List[str] = []
    for i, m in enumerate(media):
        src = m["path"]
        out = f"seg/s{i:02d}.mp4"
        if m["is_photo"]:
            vf = (f"scale={_W}:{_H}:force_original_aspect_ratio=increase,crop={_W}:{_H},"
                  f"zoompan=z='min(zoom+0.0018,1.22)':d={frames}:x='iw/2-(iw/zoom/2)':"
                  f"y='ih/2-(ih/zoom/2)':s={_W}x{_H},fps={_FPS},setsar=1,format=yuv420p")
            cmd = [ff, "-y", "-i", src, "-vf", vf, "-frames:v", str(frames),
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", out]
        else:
            start = m.get("start", 1)
            vf = (f"scale={_W}:{_H}:force_original_aspect_ratio=increase,crop={_W}:{_H},"
                  f"fps={_FPS},setsar=1,format=yuv420p")
            cmd = [ff, "-y", "-ss", str(start), "-i", src, "-t", f"{seg_dur:.3f}",
                   "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", out]
        if execute(cmd, cwd=cwd) != 0:
            raise MontageError(f"segment render failed: {src}")
        seg_files.append(out)

    # 2. concat (demuxer — robust, no CFR-matching issues)
    (out_dir / "concat.txt").write_text("".join(f"file '{s}'\n" for s in seg_files), encoding="utf-8")
    if execute([ff, "-y", "-f", "concat", "-safe", "0", "-i", "concat.txt",
                "-c", "copy", "montage.mp4"], cwd=cwd) != 0:
        raise MontageError("concat failed")

    # 3. burn captions + mix voice (+ optional low music)
    if music_abs and Path(music_abs).exists():
        cmd = [ff, "-y", "-i", "montage.mp4", "-i", voice_rel, "-i", music_abs,
               "-filter_complex",
               "[0:v]subtitles=captions.ass[v];"
               "[1:a]volume=1.0[a1];[2:a]volume=0.10[a2];"
               "[a1][a2]amix=inputs=2:duration=first:dropout_transition=0[a]",
               "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
               "-c:v", "libx264", "-preset", "medium", "-crf", "20",
               "-c:a", "aac", "-b:a", "160k", out_rel]
    else:
        cmd = [ff, "-y", "-i", "montage.mp4", "-i", voice_rel,
               "-filter_complex", "[0:v]subtitles=captions.ass[v]",
               "-map", "[v]", "-map", "1:a", "-t", f"{total:.3f}",
               "-c:v", "libx264", "-preset", "medium", "-crf", "20",
               "-c:a", "aac", "-b:a", "160k", out_rel]
    if execute(cmd, cwd=cwd) != 0:
        raise MontageError("final compose failed")

    final = out_dir / out_rel
    if not final.exists() or final.stat().st_size < 10000:
        raise MontageError("final output missing/too small")
    log.info("[montage] -> %s (%.1f MB)", out_rel, final.stat().st_size / 1048576)
    return final
