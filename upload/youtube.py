"""YouTube upload module using YouTube Data API v3 (OAuth).

Usage:
    from upload.youtube import upload_video
    upload_video("final.mp4", title="My Short", description="...", schedule_days=-1)
"""

from __future__ import annotations

import json
import os
import pickle
from pathlib import Path
from typing import Optional

from core.artifact_registry import AOR
from core.logger import get_logger

log = get_logger(__name__)

# OAuth 2.0 scopes for YouTube Data API v3
_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
_TOKEN_FILE = Path.home() / ".youtube_upload_token.pickle"
_CLIENT_SECRETS = Path(__file__).resolve().parent / "client_secret.json"
_QUOTA_FILE = Path(__file__).resolve().parent / ".upload_quota.json"
_UPLOAD_LOG = Path(__file__).resolve().parent / ".upload_log.json"

# Default daily upload limit (YouTube Data API: ~6 full uploads/day)
_DAILY_UPLOAD_LIMIT = int(os.getenv("YOUTUBE_DAILY_UPLOAD_LIMIT", "6"))


def _get_authenticated_service():
    """Authenticate and return a YouTube API service instance.

    Uses OAuth 2.0 with local token caching. First run opens browser for auth.
    """
    AOR.register_read("client_secret", _CLIENT_SECRETS, __name__)
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        log.error(
            "Missing Google API dependencies. Install:\n"
            "  pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client"
        )
        raise

    creds = None

    # Load cached token
    if _TOKEN_FILE.exists():
        AOR.register_read("oauth_token", _TOKEN_FILE, __name__)
        try:
            with open(_TOKEN_FILE, "rb") as f:
                creds = pickle.load(f)
        except Exception:
            creds = None

    # Refresh or re-auth
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if not _CLIENT_SECRETS.exists():
            raise FileNotFoundError(
                f"OAuth client secrets not found at {_CLIENT_SECRETS}\n"
                f"Download from Google Cloud Console → API & Services → Credentials → "
                f"OAuth 2.0 Client IDs → Download JSON → save as client_secret.json"
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(_CLIENT_SECRETS), _SCOPES)
        creds = flow.run_local_server(port=8080, open_browser=True)

        with open(_TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
        AOR.register_write("oauth_token", _TOKEN_FILE, __name__)
        log.info("OAuth token saved to %s", _TOKEN_FILE)

    return build("youtube", "v3", credentials=creds)


def _get_video_signature(video_path: Path) -> str:
    """Simple duplicate signature: filename + filesize."""
    return f"{video_path.name}|{video_path.stat().st_size}"


def _check_duplicate(sig: str) -> bool:
    """Check if this video signature was already uploaded. Logs warning."""
    if not _UPLOAD_LOG.exists():
        return False
    AOR.register_read("upload_log", _UPLOAD_LOG, __name__)
    try:
        log_data = json.loads(_UPLOAD_LOG.read_text(encoding="utf-8"))
        if sig in log_data.get("uploaded", []):
            log.warning("Duplicate upload detected: %s — skipping", sig)
            return True
    except Exception:
        pass
    return False


def _mark_uploaded(sig: str) -> None:
    """Record successful upload signature."""
    log_data = {"uploaded": []}
    if _UPLOAD_LOG.exists():
        try:
            log_data = json.loads(_UPLOAD_LOG.read_text(encoding="utf-8"))
        except Exception:
            log_data = {"uploaded": []}
    if sig not in log_data["uploaded"]:
        log_data["uploaded"].append(sig)
    _UPLOAD_LOG.write_text(json.dumps(log_data, indent=2), encoding="utf-8")
    AOR.register_write("upload_log", _UPLOAD_LOG, __name__)


def _check_quota() -> bool:
    """Check daily upload quota. Returns False if exceeded."""
    if not _QUOTA_FILE.exists():
        return True
    AOR.register_read("upload_quota", _QUOTA_FILE, __name__)
    try:
        quota = json.loads(_QUOTA_FILE.read_text(encoding="utf-8"))
        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        if quota.get("date") != today:
            return True
        if quota.get("count", 0) >= _DAILY_UPLOAD_LIMIT:
            log.warning("Daily upload quota reached (%d/%d)", quota["count"], _DAILY_UPLOAD_LIMIT)
            return False
        return True
    except Exception:
        return True


def _increment_quota() -> None:
    """Increment daily upload counter."""
    quota = {"date": __import__("datetime").datetime.now().strftime("%Y-%m-%d"), "count": 0}
    if _QUOTA_FILE.exists():
        try:
            quota = json.loads(_QUOTA_FILE.read_text(encoding="utf-8"))
        except Exception:
            quota = {"date": __import__("datetime").datetime.now().strftime("%Y-%m-%d"), "count": 0}
    if quota.get("date") != __import__("datetime").datetime.now().strftime("%Y-%m-%d"):
        quota = {"date": __import__("datetime").datetime.now().strftime("%Y-%m-%d"), "count": 0}
    quota["count"] = quota.get("count", 0) + 1
    _QUOTA_FILE.write_text(json.dumps(quota, indent=2), encoding="utf-8")
    AOR.register_write("upload_quota", _QUOTA_FILE, __name__)


def upload_video(
    video_path: str | Path,
    title: str = "Untitled Short",
    description: str = "",
    tags: Optional[list] = None,
    privacy_status: str = "unlisted",
    schedule_days: int = -1,
) -> bool:
    """Upload a video to YouTube.

    Args:
        video_path: Path to the final MP4.
        title: Video title.
        description: Video description.
        tags: List of tags.
        privacy_status: 'public', 'unlisted', or 'private'.
        schedule_days: -1 = immediate, 0 = next business day, N = N days later.

    Returns:
        True on success.
    """
    from googleapiclient.http import MediaFileUpload

    video_path = Path(video_path)
    if not video_path.exists():
        log.error("Video not found: %s", video_path)
        return False

    # Duplicate check
    sig = _get_video_signature(video_path)
    if _check_duplicate(sig):
        return False

    # Quota check
    if not _check_quota():
        return False

    log.info("Uploading %s (%d MB)", video_path.name, video_path.stat().st_size // (1024 * 1024))

    try:
        youtube = _get_authenticated_service()
    except Exception as exc:
        log.error("Authentication failed: %s", exc)
        return False

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags or [],
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    if schedule_days >= 0:
        from datetime import datetime, timedelta, timezone
        publish_at = datetime.now(timezone.utc) + timedelta(days=schedule_days)
        body["status"]["publishAt"] = publish_at.isoformat()
        log.info("Scheduled for %s", publish_at.isoformat())

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)

    try:
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )
        response = request.execute()
        video_id = response.get("id", "unknown")
        log.info("Upload successful! Video ID: %s", video_id)
        _mark_uploaded(sig)
        _increment_quota()
        return True
    except Exception as exc:
        log.error("Upload failed: %s", exc)
        return False


def upload_with_retry(
    video_path: str | Path,
    title: str = "",
    description: str = "",
    max_retries: int = 3,
    **kwargs,
) -> bool:
    """Upload with exponential backoff retry."""
    import time

    for attempt in range(max_retries):
        if upload_video(video_path, title=title, description=description, **kwargs):
            return True
        if attempt < max_retries - 1:
            wait = 2 ** (attempt + 1)
            log.warning("Retrying upload in %ds (attempt %d/%d)", wait, attempt + 1, max_retries)
            time.sleep(wait)
    log.error("Upload failed after %d retries", max_retries)
    return False
