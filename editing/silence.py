"""Silence trimming — pure helpers. No subprocess, no execution.

Strategy (safe-by-construction):
    Silence is trimmed from the *source* video in Phase 1, BEFORE transcription.
    Because Whisper then runs on the trimmed media, every downstream timestamp
    (clip scoring, crop, captions) is computed on the trimmed timeline — so
    captions never desync. The orchestrator (phase1) calls:
        ffmpeg_builder.run_silencedetect()  -> stderr text   (execution)
        parse_silencedetect(stderr)         -> silence spans  (pure, here)
        compute_keep_segments(...)          -> speech spans   (pure, here)
        build_trim_command(...)             -> ffmpeg cmd     (pure, here)
    Any failure / no silence found → caller keeps the original media untouched.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

from core.config import PipelineConfig
from editing.ffmpeg_builder import ffmpeg_path, gpu_encode_args

_START_RE = re.compile(r"silence_start:\s*(-?[\d.]+)")
_END_RE = re.compile(r"silence_end:\s*(-?[\d.]+)")


def build_silencedetect_command(video_path: Path, noise_db: str, min_silence: float) -> list:
    """FFmpeg command that logs silent spans to stderr (no output file)."""
    return [
        ffmpeg_path(), "-i", str(video_path),
        "-af", f"silencedetect=noise={noise_db}:d={min_silence}",
        "-f", "null", "-",
    ]


def parse_silencedetect(stderr: str) -> List[Tuple[float, float]]:
    """Parse ffmpeg silencedetect stderr into (start, end) silence spans.

    Pairs each ``silence_start`` with the following ``silence_end`` in order.
    A dangling start (file ends in silence without an end line) is ignored.
    """
    starts = [float(m) for m in _START_RE.findall(stderr)]
    ends = [float(m) for m in _END_RE.findall(stderr)]
    spans = []
    for s, e in zip(starts, ends):
        if e > s:
            spans.append((max(0.0, s), e))
    return spans


def compute_keep_segments(
    silences: List[Tuple[float, float]],
    total_duration: float,
    pad: float = 0.05,
) -> List[Tuple[float, float]]:
    """Invert silence spans into speech ("keep") spans over ``[0, total]``.

    Each silence is shrunk by ``pad`` on both sides so we never clip the
    consonants right next to a pause; silences that vanish after padding are
    dropped (treated as speech). Returns merged, ordered keep spans.
    """
    if total_duration <= 0:
        return []

    effective = []
    for s, e in silences:
        s2, e2 = s + pad, e - pad
        if e2 > s2:
            effective.append((max(0.0, s2), min(total_duration, e2)))
    effective.sort()

    keeps: List[Tuple[float, float]] = []
    cursor = 0.0
    for s, e in effective:
        if s > cursor:
            keeps.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < total_duration:
        keeps.append((cursor, total_duration))

    # Drop degenerate spans.
    return [(a, b) for a, b in keeps if b - a > 0.01]


def kept_fraction(keeps: List[Tuple[float, float]], total_duration: float) -> float:
    """Fraction of the timeline retained (1.0 = nothing trimmed)."""
    if total_duration <= 0:
        return 1.0
    return sum(b - a for a, b in keeps) / total_duration


def build_trim_command(
    video_path: Path,
    keeps: List[Tuple[float, float]],
    output_path: Path,
    config: PipelineConfig,
) -> list:
    """Single-pass select/concat that keeps only the speech spans, A/V in sync.

    Uses ``select`` + ``setpts=N/FRAME_RATE/TB`` (and the audio equivalents) to
    drop silent frames and re-base timestamps to a continuous timeline.
    """
    cond = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in keeps)
    vf = f"select='{cond}',setpts=N/FRAME_RATE/TB"
    af = f"aselect='{cond}',asetpts=N/SR/TB"

    cmd = [
        ffmpeg_path(), "-y",
        "-i", str(video_path),
        "-vf", vf,
        "-af", af,
        "-c:a", "aac",
        "-b:a", "128k",
        "-vsync", "0",
    ]
    cmd.extend(gpu_encode_args(config))
    cmd.append(str(output_path))
    return cmd
