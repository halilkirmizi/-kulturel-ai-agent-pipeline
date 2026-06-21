"""Video download via yt-dlp (Python API).

Usage:
    from ingest.downloader import download_video
    path = download_video("https://youtube.com/watch?v=XXX", Path("./temp"))
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from yt_dlp import YoutubeDL

from core.artifact_registry import AOR
from core.logger import get_logger

log = get_logger(__name__)


class DownloadError(Exception):
    """Raised when video download fails."""


def download_video(url: str, output_dir: Path, output_template: Optional[str] = None) -> Path:
    """Download best-quality video+audio from YouTube using yt-dlp Python API.

    Args:
        url: YouTube watch URL.
        output_dir: Directory to save into.
        output_template: yt-dlp output template (default: '%(id)s.%(ext)s').

    Returns:
        Path to the downloaded MP4 file.

    Raises:
        DownloadError: if download fails or no file produced.
    """
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    template = output_template or "%(id)s.%(ext)s"
    out_template = str(output_dir / template)

    log.info("Downloading %s -> %s", url, out_template)

    ydl_opts = {
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "outtmpl": out_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        raise DownloadError(f"yt-dlp failed: {exc}") from exc

    video_id = info.get("id")
    if not video_id:
        raise DownloadError("Could not determine video ID from response")

    video_path = output_dir / f"{video_id}.mp4"
    if not video_path.exists():
        raise DownloadError(f"Expected output file not found: {video_path}")
    size_mb = video_path.stat().st_size / (1024 * 1024)
    log.info("Downloaded %s (%.1f MB)", video_path.name, size_mb)
    AOR.register_write("source_video", video_path, __name__)
    return video_path
