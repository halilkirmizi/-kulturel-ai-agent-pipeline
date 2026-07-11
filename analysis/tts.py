"""Text-to-speech voiceover via edge-tts (Microsoft neural voices).

Free, no API key, natural. Emits an MP3 plus a WEBVTT with sentence timings
(used both to burn captions and to time the visual cuts). Synthetic narration
does not by itself trigger demonetization; content originality + license-safe
media are what keep news mode monetizable.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Tuple

from core.logger import get_logger

log = get_logger(__name__)


def synthesize(
    text: str,
    out_mp3: Path,
    out_vtt: Path,
    voice: str = "en-US-GuyNeural",
    rate: str = "+12%",
) -> Tuple[Path, Path]:
    """Generate voiceover audio + timed subtitles. Returns (mp3, vtt).

    Raises RuntimeError if edge-tts is unavailable or fails.
    """
    out_mp3 = Path(out_mp3)
    out_vtt = Path(out_vtt)
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "edge_tts",
        "--voice", voice,
        f"--rate={rate}",
        "--text", text,
        "--write-media", str(out_mp3),
        "--write-subtitles", str(out_vtt),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out_mp3.exists():
        raise RuntimeError(f"edge-tts failed (rc={r.returncode}): {r.stderr[-400:]}")
    log.info("[tts] voiceover -> %s (%d KB)", out_mp3.name, out_mp3.stat().st_size // 1024)
    return out_mp3, out_vtt
