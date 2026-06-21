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


def _write_ass(segments, ass_path, fontsize, margin_bottom, clip_dur, start_offset):
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: None",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Caption,Arial,{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H00404040,0,0,0,0,100,100,0,0,1,2,1,2,10,10,{margin_bottom},1",
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
            display = chunk.replace("{", "\\{").replace("}", "\\}")
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
) -> Path:
    """Generate ASS subtitle file from transcript segments.

    Pure function. No FFmpeg. No subprocess. Returns ass_path.
    All durations must be pre-probed and passed explicitly.
    """
    valid = [
        s for s in segments
        if s.start >= start_offset and s.end <= start_offset + clip_duration + 5 and s.text.strip()
    ]
    _write_ass(valid, ass_path, fontsize, margin_bottom, clip_duration, start_offset)
    AOR.register_write("captions_ass", ass_path, __name__)
    return ass_path
