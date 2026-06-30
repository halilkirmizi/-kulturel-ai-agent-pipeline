"""Thin YouTube statistics fetcher (Data API v3, read-only).

Fetches viewCount / likeCount / commentCount for uploaded videos so the
performance layer has real ground truth. Gracefully degrades to ``{}`` when
credentials are missing or the API errors — analytics is opt-in and must
never break anything.

The ``service`` argument is injectable so the parsing path is unit-testable
with a mock (no real OAuth/network).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.logger import get_logger

log = get_logger(__name__)


def _default_service():
    """Reuse the upload OAuth credentials to build a read-only YouTube client.

    Returns None (caller degrades gracefully) if anything is unavailable.
    """
    try:
        import pickle
        from pathlib import Path
        from googleapiclient.discovery import build

        token = Path.home() / ".youtube_upload_token.pickle"
        if not token.exists():
            log.warning("[analytics] no OAuth token — skipping stats fetch")
            return None
        with open(token, "rb") as f:
            creds = pickle.load(f)
        return build("youtube", "v3", credentials=creds)
    except Exception as exc:
        log.warning("[analytics] could not build YouTube client: %s", exc)
        return None


def parse_stats_response(response: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Pure: turn a videos.list(part=statistics) response into {id: stats}."""
    out: Dict[str, Dict[str, Any]] = {}
    for item in response.get("items", []):
        vid = item.get("id")
        if vid:
            out[vid] = item.get("statistics", {})
    return out


def fetch_stats(video_ids: List[str], service: Optional[Any] = None) -> Dict[str, Dict[str, Any]]:
    """Fetch statistics for the given video_ids. Returns {id: stats}, or {} on failure.

    Batches in groups of 50 (Data API limit). ``service`` may be injected for tests.
    """
    ids = [v for v in video_ids if v]
    if not ids:
        return {}
    if service is None:
        service = _default_service()
    if service is None:
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    try:
        for i in range(0, len(ids), 50):
            batch = ids[i:i + 50]
            resp = service.videos().list(part="statistics", id=",".join(batch)).execute()
            out.update(parse_stats_response(resp))
    except Exception as exc:
        log.warning("[analytics] stats fetch failed: %s", exc)
        return {}
    return out
