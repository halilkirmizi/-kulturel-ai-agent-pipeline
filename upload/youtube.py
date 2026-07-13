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

# OAuth 2.0 scopes.
# - youtube.upload: publish videos (Data API v3)
# - youtube.readonly: read statistics (videos.list part=statistics) for --fetch-analytics
# - yt-analytics.readonly: retention + traffic-source reports (Analytics API v2)
#   Adding this scope invalidates any older token via the scope-subset check
#   below, forcing one fresh browser consent so analytics reports work.
_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
_TOKEN_FILE = Path.home() / ".youtube_upload_token.pickle"
_CLIENT_SECRETS = Path(__file__).resolve().parent / "client_secret.json"
_QUOTA_FILE = Path(__file__).resolve().parent / ".upload_quota.json"
_UPLOAD_LOG = Path(__file__).resolve().parent / ".upload_log.json"

# Default daily upload limit (YouTube Data API: ~6 full uploads/day)
_DAILY_UPLOAD_LIMIT = int(os.getenv("YOUTUBE_DAILY_UPLOAD_LIMIT", "6"))


def _get_credentials():
    """Authenticate via OAuth 2.0 and return valid credentials.

    Uses local token caching. First run (or a token missing a required scope)
    opens the browser for consent. Shared by every Google API client we build
    (Data API v3 for upload/stats, Analytics API v2 for reports) so token
    refresh, the scope-subset check, and re-consent live in one place.
    """
    AOR.register_read("client_secret", _CLIENT_SECRETS, __name__)
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
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

    # Force re-auth if the cached token is missing any required scope.
    # A refresh_token keeps whatever scopes it was granted, so an old
    # upload-only token (predating youtube.readonly) would otherwise refresh
    # forever and never gain read access — silently 403-ing --fetch-analytics.
    if creds is not None:
        granted = set(getattr(creds, "scopes", None) or [])
        if not set(_SCOPES).issubset(granted):
            log.info(
                "Cached token missing required scope(s) %s (has %s) — re-authenticating",
                sorted(set(_SCOPES) - granted), sorted(granted),
            )
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

    return creds


def _get_authenticated_service():
    """YouTube Data API v3 client (upload + statistics)."""
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=_get_credentials())


def get_analytics_service():
    """YouTube Analytics API v2 client (reports.query — retention + traffic).

    Returns None on any failure so --fetch-analytics degrades gracefully
    instead of crashing when credentials/deps are unavailable.
    """
    try:
        from googleapiclient.discovery import build

        return build("youtubeAnalytics", "v2", credentials=_get_credentials())
    except Exception as exc:
        log.warning("[analytics] could not build Analytics client: %s", exc)
        return None


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
    publish_at: Optional[str] = None,
    category_id: str = "22",
    language: str = "en",
) -> Optional[str]:
    """Upload a video to YouTube.

    Args:
        video_path: Path to the final MP4.
        title: Video title.
        description: Video description.
        tags: List of tags.
        privacy_status: 'public', 'unlisted', or 'private'.
        schedule_days: -1 = immediate, 0 = next business day, N = N days later.

    Returns:
        The YouTube video_id (truthy) on success, else None. (A non-empty
        string is truthy, so existing ``if upload_video(...)`` checks still work.)
    """
    from googleapiclient.http import MediaFileUpload

    video_path = Path(video_path)
    if not video_path.exists():
        log.error("Video not found: %s", video_path)
        return None

    # Duplicate check
    sig = _get_video_signature(video_path)
    if _check_duplicate(sig):
        return None

    # Quota check
    if not _check_quota():
        return None

    log.info("Uploading %s (%d MB)", video_path.name, video_path.stat().st_size // (1024 * 1024))

    try:
        youtube = _get_authenticated_service()
    except Exception as exc:
        log.error("Authentication failed: %s", exc)
        return None

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": (tags or [])[:15],
            "categoryId": category_id,
            "defaultLanguage": language,
            "defaultAudioLanguage": language,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    if publish_at:
        # Exact scheduled release — the video must be private until publishAt.
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = publish_at
        log.info("Scheduled public release at %s", publish_at)
    elif schedule_days >= 0:
        from datetime import datetime, timedelta, timezone
        pub = datetime.now(timezone.utc) + timedelta(days=schedule_days)
        body["status"]["publishAt"] = pub.isoformat()
        log.info("Scheduled for %s", pub.isoformat())

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
        return video_id
    except Exception as exc:
        log.error("Upload failed: %s", exc)
        return None


def upload_with_retry(
    video_path: str | Path,
    title: str = "",
    description: str = "",
    max_retries: int = 3,
    **kwargs,
) -> Optional[str]:
    """Upload with exponential backoff retry. Returns video_id or None."""
    import time

    for attempt in range(max_retries):
        vid = upload_video(video_path, title=title, description=description, **kwargs)
        if vid:
            return vid
        if attempt < max_retries - 1:
            wait = 2 ** (attempt + 1)
            log.warning("Retrying upload in %ds (attempt %d/%d)", wait, attempt + 1, max_retries)
            time.sleep(wait)
    log.error("Upload failed after %d retries", max_retries)
    return None
