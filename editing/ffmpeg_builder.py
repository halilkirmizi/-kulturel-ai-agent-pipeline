"""FFmpeg execution gateway — the ONLY module allowed to call subprocess.

Single responsibility: execute FFmpeg commands. No business logic.
All other modules build command lists and pass them to execute().
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import PipelineConfig
from core.logger import get_logger

log = get_logger(__name__)


def ffmpeg_path() -> str:
    try:
        import imageio_ffmpeg
        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        return "ffmpeg"


def ffprobe_path() -> str:
    """Derive ffprobe path from ffmpeg path (same directory).

    Falls back to 'ffprobe' (system PATH) if the derived path doesn't exist.
    """
    base = ffmpeg_path()
    base_dir = str(Path(base).parent)
    candidates = [
        str(Path(base_dir) / "ffprobe.exe"),
        str(Path(base_dir) / "ffprobe"),
        str(Path(base_dir) / "ffprobe-win-x86_64-v7.1.exe"),
        "ffprobe",
    ]
    for c in candidates:
        if Path(c).is_file():
            return c
    return "ffprobe"


def _run_ffmpeg_capture(cmd: List[str], timeout: Optional[float] = None) -> "subprocess.CompletedProcess[str]":
    """Run ffmpeg and capture output. Single internal subprocess.run call site."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def probe_duration(path: Path) -> float:
    """Probe video/audio duration via ffmpeg. Returns seconds, 0.0 on failure."""
    r = _run_ffmpeg_capture([ffmpeg_path(), "-i", str(path), "-f", "null", "-"])
    m = re.search(r"Duration: (\d+):(\d+):(\d+)\.(\d+)", r.stderr)
    if not m:
        m = re.search(r"Duration: (\d+):(\d+):(\d+)\.(\d+)", r.stdout)
    if m:
        return float(m.group(1)) * 3600 + float(m.group(2)) * 60 + float(m.group(3)) + float(m.group(4)) / 100
    return 0.0


def probe_file(path: Path) -> Dict[str, Any]:
    """Probe video file via ffprobe. Returns parsed JSON with streams + format info.

    Returns empty dict on failure (caller must handle).
    """
    try:
        r = _run_ffmpeg_capture(
            [ffprobe_path(), "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", str(path)],
            timeout=30,
        )
        return json.loads(r.stdout)
    except Exception:
        return {}


_NVENC_CACHE: Optional[bool] = None


def nvenc_available() -> bool:
    global _NVENC_CACHE
    if _NVENC_CACHE is not None:
        return _NVENC_CACHE
    try:
        r = _run_ffmpeg_capture([ffmpeg_path(), "-encoders"], timeout=15)
        _NVENC_CACHE = "h264_nvenc" in r.stdout or "h264_nvenc" in r.stderr
    except Exception:
        _NVENC_CACHE = False
    if not _NVENC_CACHE:
        log.warning("h264_nvenc not available — falling back to libx264")
    return _NVENC_CACHE


def gpu_encode_args(config: PipelineConfig) -> list:
    if not config.gpu_enabled or not nvenc_available():
        return ["-c:v", "libx264", "-preset", config.compose.preset, "-crf", str(config.compose.crf)]
    return [
        "-c:v", "h264_nvenc",
        "-preset", "p4",
        "-cq", "22",
        "-rc", "vbr",
        "-b:v", "5M",
        "-maxrate", "8M",
        "-bufsize", "10M",
        "-pix_fmt", "yuv420p",
    ]


def execute(cmd: List[str]) -> int:
    """Execute an FFmpeg command. Returns exit code. This is the ONLY execution function.

    Args:
        cmd: Complete FFmpeg command as list of strings.

    Returns:
        Exit code (0 = success).

    Raises:
        FileNotFoundError: if ffmpeg binary not found.
    """
    log.debug("ffmpeg execute: %s", " ".join(str(c) for c in cmd[:12]) + ("..." if len(cmd) > 12 else ""))
    result = _run_ffmpeg_capture(cmd)
    if result.returncode != 0:
        log.error("ffmpeg failed (rc=%d): %s", result.returncode, result.stderr[-500:])
    return result.returncode
