"""YouTube Analytics API fetcher (youtubeAnalytics v2, read-only).

Pulls per-video retention + traffic-source metrics that the Data API cannot
provide, so the performance layer can auto-diagnose *why* a video under- or
over-performed: is the first-seconds hook holding viewers, and is the Shorts
feed distributing the video at all.

NOTE — thumbnail impressions and impression CTR are intentionally absent:
the public Analytics API does not expose them (Studio-only). We rely instead
on ``averageViewPercentage`` (retention) + the traffic-source mix, which are
exactly the signals that answer "is the feed pushing this / is it being held".

The ``service`` argument is injectable so parsing is unit-testable with a mock
(no OAuth/network). Everything degrades to ``{}`` on missing creds/errors —
analytics is opt-in and must never break the pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.logger import get_logger

log = get_logger(__name__)

# Per-video metrics available from the public Analytics API (no dimensions).
_VIDEO_METRICS = (
    "views,estimatedMinutesWatched,averageViewDuration,"
    "averageViewPercentage,subscribersGained,likes,shares,comments"
)

# Deterministic diagnosis thresholds (tunable in one place).
_RETENTION_GOOD = 50.0      # averageViewPercentage >= -> holding viewers well
_RETENTION_POOR = 35.0      # below -> first-seconds retention problem
_FEED_HEALTHY_SHARE = 0.5   # >= half of views from the Shorts feed -> distributing
_MIN_REACH = 100            # views below this -> not enough reach to judge feed

# "Lifetime" lower bound (YouTube launch date) so reports cover a video's
# whole life regardless of upload date. endDate defaults to today (UTC).
_LIFETIME_START = "2005-02-14"


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _default_service():
    """Build the Analytics client via the shared upload OAuth flow.

    Reuses ``upload.youtube.get_analytics_service`` so analytics benefits from
    the same token refresh / scope-subset check / browser re-consent. Returns
    None (caller degrades gracefully) if anything is unavailable.
    """
    try:
        from upload.youtube import get_analytics_service

        return get_analytics_service()
    except Exception as exc:
        log.warning("[analytics] could not import Analytics client: %s", exc)
        return None


def rows_as_dicts(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pure: turn a reports.query response into a list of {column: value} dicts."""
    headers = [h.get("name") for h in response.get("columnHeaders", [])]
    out: List[Dict[str, Any]] = []
    for row in response.get("rows", []) or []:
        out.append({headers[i]: row[i] for i in range(min(len(headers), len(row)))})
    return out


def _query(service, *, metrics: str, dimensions: Optional[str] = None,
           filters: Optional[str] = None, start_date: str = _LIFETIME_START,
           end_date: Optional[str] = None, sort: Optional[str] = None) -> Dict[str, Any]:
    """Issue one reports.query call. Raises on API error (callers catch)."""
    kwargs: Dict[str, Any] = {
        "ids": "channel==MINE",
        "startDate": start_date,
        "endDate": end_date or _today(),
        "metrics": metrics,
    }
    if dimensions:
        kwargs["dimensions"] = dimensions
    if filters:
        kwargs["filters"] = filters
    if sort:
        kwargs["sort"] = sort
    return service.reports().query(**kwargs).execute()


def fetch_video_metrics(video_id: str, service: Any, **dates) -> Dict[str, Any]:
    """Lifetime totals for one video as {metric: value}. {} on error."""
    try:
        resp = _query(service, metrics=_VIDEO_METRICS,
                      filters=f"video=={video_id}", **dates)
        rows = rows_as_dicts(resp)
        return rows[0] if rows else {}
    except Exception as exc:
        log.warning("[analytics] video metrics failed for %s: %s", video_id, exc)
        return {}


def fetch_traffic_sources(video_id: str, service: Any, **dates) -> Dict[str, Dict[str, Any]]:
    """{traffic_source_type: {views, estimatedMinutesWatched}} for one video."""
    try:
        resp = _query(service, metrics="views,estimatedMinutesWatched",
                      dimensions="insightTrafficSourceType",
                      filters=f"video=={video_id}", **dates)
        out: Dict[str, Dict[str, Any]] = {}
        for r in rows_as_dicts(resp):
            key = r.get("insightTrafficSourceType")
            if key:
                out[key] = {
                    "views": _to_int(r.get("views")),
                    "estimatedMinutesWatched": _to_num(r.get("estimatedMinutesWatched")),
                }
        return out
    except Exception as exc:
        log.warning("[analytics] traffic sources failed for %s: %s", video_id, exc)
        return {}


def diagnose(metrics: Dict[str, Any], traffic: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Deterministic verdict from metrics + traffic mix. Pure, no network.

    Verdicts:
      no_data                    -> zero views (too early / never distributed)
      retention_problem          -> first seconds not holding viewers
      good_retention_low_reach   -> holds viewers but feed isn't pushing it
                                    (packaging / audience-fit, NOT a hook issue)
      low_reach                  -> few views and unremarkable retention
      healthy_feed_distribution  -> most views come from the Shorts feed
      distributed_no_feed        -> reach exists but not from the Shorts feed
    """
    views = _to_int(metrics.get("views"))
    retention = _to_num(metrics.get("averageViewPercentage"))
    avg_seconds = _to_num(metrics.get("averageViewDuration"))
    feed_views = _to_int((traffic.get("SHORTS") or {}).get("views"))
    feed_share = round(feed_views / views, 3) if views > 0 else 0.0

    flags: List[str] = []
    if views <= 0:
        verdict = "no_data"
    elif retention and retention < _RETENTION_POOR:
        verdict = "retention_problem"
        flags.append(f"first-seconds drop (avg view {retention:.0f}% / {avg_seconds:.0f}s)")
    elif views < _MIN_REACH:
        if retention and retention >= _RETENTION_GOOD:
            verdict = "good_retention_low_reach"
            flags.append("holds viewers but feed isn't pushing it — packaging/audience-fit")
        else:
            verdict = "low_reach"
    elif feed_share >= _FEED_HEALTHY_SHARE:
        verdict = "healthy_feed_distribution"
    else:
        verdict = "distributed_no_feed"
        flags.append(f"only {feed_share:.0%} of views from the Shorts feed")

    return {
        "views": views,
        "retention_pct": retention,
        "avg_view_seconds": avg_seconds,
        "shorts_feed_views": feed_views,
        "shorts_feed_share": feed_share,
        "top_traffic": _top_traffic(traffic),
        "verdict": verdict,
        "flags": flags,
    }


def _top_traffic(traffic: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    ranked = sorted(traffic.items(), key=lambda kv: kv[1].get("views", 0), reverse=True)
    return [{"source": k, "views": v.get("views", 0)} for k, v in ranked[:3]]


def fetch_analytics(video_ids: List[str], service: Optional[Any] = None,
                    **dates) -> Dict[str, Dict[str, Any]]:
    """Fetch metrics + traffic + diagnosis for each video_id.

    Returns {video_id: {"metrics": ..., "traffic": ..., "diagnosis": ...}}.
    Returns {} only when there is nothing to do or no client is available;
    individual per-video failures degrade to empty sub-dicts (verdict no_data).
    """
    ids = [v for v in video_ids if v]
    if not ids:
        return {}
    if service is None:
        service = _default_service()
    if service is None:
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for vid in ids:
        metrics = fetch_video_metrics(vid, service, **dates)
        traffic = fetch_traffic_sources(vid, service, **dates)
        out[vid] = {
            "metrics": metrics,
            "traffic": traffic,
            "diagnosis": diagnose(metrics, traffic),
        }
    return out


def _to_int(v: Any) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _to_num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
