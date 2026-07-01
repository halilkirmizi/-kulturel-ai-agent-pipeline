"""ASS subtitle generation only. No FFmpeg. No subprocess. No execution."""

from __future__ import annotations

from pathlib import Path
from typing import List

from core.artifact_registry import AOR


def _chunk_text(text: str, max_chars: int = 70) -> List[str]:
    if len(text) <= max_chars:
        return [text]

    chunks = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining.strip())
            break
        split_at = -1
        search_window = remaining[:max_chars]
        for sep in [". ", "? ", "! ", ", ", "; ", " — ", " – ", "  "]:
            pos = search_window.rfind(sep)
            if pos > max_chars * 0.4:
                split_at = pos + len(sep)
                break
        if split_at < 0:
            split_at = search_window.rfind(" ")
            if split_at < max_chars * 0.3:
                split_at = max_chars
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    return chunks


def _to_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("{", "\\{").replace("}", "\\}")


def _karaoke_text(chunk: str, duration_s: float) -> str:
    """Build an ASS karaoke line: each word gets a `\\k<cs>` tag so it lights
    up (PrimaryColour) progressively as the line plays.

    Word durations are distributed evenly across the chunk and rounded to
    centiseconds; any rounding remainder is added to the last word so the
    karaoke timing sums exactly to the chunk duration.
    """
    words = chunk.split()
    if not words:
        return _escape(chunk)
    total_cs = max(0, int(round(duration_s * 100)))
    base = total_cs // len(words)
    remainder = total_cs - base * len(words)
    parts = []
    for i, w in enumerate(words):
        cs = base + (remainder if i == len(words) - 1 else 0)
        parts.append(f"{{\\k{cs}}}{_escape(w)}")
    return " ".join(parts)


def _style_line(fontsize, margin_bottom, karaoke, highlight_color):
    """V4+ style. Plain captions keep the original colours exactly.

    Karaoke: PrimaryColour = highlight (sung words), SecondaryColour = white
    (not-yet-sung words) so words sweep from white to the highlight colour.
    """
    if karaoke:
        primary = highlight_color    # sung
        secondary = "&H00FFFFFF"     # white (upcoming)
    else:
        primary = "&H00FFFFFF"       # white (original behaviour)
        secondary = "&H000000FF"     # original (unused without karaoke)
    return (
        f"Style: Caption,Arial,{fontsize},{primary},{secondary},"
        f"&H00000000,&H00404040,0,0,0,0,100,100,0,0,1,2,1,2,10,10,{margin_bottom},1"
    )


def _write_ass(segments, ass_path, fontsize, margin_bottom, clip_dur, start_offset,
               karaoke=False, highlight_color="&H0000FFFF"):
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        # Pin the coordinate space to the real 9:16 frame so MarginV / positions
        # are in actual pixels (without this, libass defaults to 384x288 and
        # pixel values land off-screen).
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: None",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        _style_line(fontsize, margin_bottom, karaoke, highlight_color),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    event_count = 0
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        seg_start = max(0, seg.start - start_offset)
        seg_end = min(seg.end - start_offset, clip_dur)
        if seg_start >= clip_dur:
            continue

        chunks = _chunk_text(text)
        chunk_dur = max(0.8, (seg_end - seg_start) / max(len(chunks), 1))
        for c_idx, chunk in enumerate(chunks):
            c_start = seg_start + c_idx * chunk_dur
            c_end = min(c_start + chunk_dur, seg_end)
            if c_start >= clip_dur:
                break
            start_ts = _to_ass_time(c_start)
            end_ts = _to_ass_time(c_end)
            if karaoke:
                display = _karaoke_text(chunk, c_end - c_start)
            else:
                display = _escape(chunk)
            lines.append(f"Dialogue: 0,{start_ts},{end_ts},Caption,,0,0,0,,{display}")
            event_count += 1

    ass_path.write_text("\n".join(lines), encoding="utf-8-sig")


def write_ass(
    segments: list,
    ass_path: Path,
    clip_duration: float,
    start_offset: float = 0.0,
    fontsize: int = 16,
    margin_bottom: int = 40,
    karaoke: bool = False,
    highlight_color: str = "&H0000FFFF",
) -> Path:
    """Generate ASS subtitle file from transcript segments.

    Pure function. No FFmpeg. No subprocess. Returns ass_path.
    All durations must be pre-probed and passed explicitly.

    Args:
        karaoke: when True, emit per-word `\\k` karaoke highlighting (opt-in).
            When False the output is identical to the original static captions.
        highlight_color: ASS BBGGRR colour for sung words (default yellow).
    """
    valid = [
        s for s in segments
        if s.start >= start_offset and s.end <= start_offset + clip_duration + 5 and s.text.strip()
    ]
    _write_ass(valid, ass_path, fontsize, margin_bottom, clip_duration, start_offset,
               karaoke=karaoke, highlight_color=highlight_color)
    AOR.register_write("captions_ass", ass_path, __name__)
    return ass_path
