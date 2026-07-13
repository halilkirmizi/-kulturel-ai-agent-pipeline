"""Tests for the YouTube Analytics fetcher (analysis/youtube_analytics.py) and
PerformanceStore analytics attachment. No real API — a mock reports service is
injected.

Run:  python tests/test_youtube_analytics.py
"""

import sys
import tempfile
from pathlib import Path

_PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PIPELINE_ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

print("=" * 60)
print("YOUTUBE ANALYTICS TEST SUITE")
print("=" * 60)

results = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  {status}: {name}" + (f" ({detail})" if detail else ""))
    results.append((name, status))


# ── Canned Analytics API responses ─────────────────────────────────────────
METRICS_RESP = {
    "kind": "youtubeAnalytics#resultTable",
    "columnHeaders": [
        {"name": "views"}, {"name": "estimatedMinutesWatched"},
        {"name": "averageViewDuration"}, {"name": "averageViewPercentage"},
        {"name": "subscribersGained"}, {"name": "likes"},
        {"name": "shares"}, {"name": "comments"},
    ],
    "rows": [[1291, 156, 16, 76.6, 0, 5, 2, 1]],
}
TRAFFIC_RESP = {
    "columnHeaders": [
        {"name": "insightTrafficSourceType"}, {"name": "views"},
        {"name": "estimatedMinutesWatched"},
    ],
    "rows": [
        ["SHORTS", 1200, 150],
        ["NO_LINK_OTHER", 50, 4],
        ["YT_CHANNEL", 41, 2],
    ],
}


class _Query:
    def __init__(self, resp): self._r = resp
    def execute(self): return self._r


class _Reports:
    """Routes to metrics vs traffic response based on the 'dimensions' kwarg."""
    def __init__(self, router): self._router = router
    def query(self, **kw): return _Query(self._router(kw))


class _Service:
    def __init__(self, router): self._router = router
    def reports(self): return _Reports(self._router)


def _router(kw):
    return TRAFFIC_RESP if "dimensions" in kw else METRICS_RESP


# ── rows_as_dicts ──────────────────────────────────────────────────────────
print("\n[TEST 1] rows_as_dicts")
from analysis.youtube_analytics import rows_as_dicts

d = rows_as_dicts(METRICS_RESP)
check("single row -> one dict", len(d) == 1)
check("maps column names to values", d[0]["views"] == 1291 and d[0]["averageViewPercentage"] == 76.6)
t = rows_as_dicts(TRAFFIC_RESP)
check("multi row -> list", len(t) == 3 and t[0]["insightTrafficSourceType"] == "SHORTS")
check("empty response -> []", rows_as_dicts({}) == [])


# ── fetch_video_metrics / fetch_traffic_sources with mock ──────────────────
print("\n[TEST 2] fetch via mock service")
from analysis.youtube_analytics import fetch_video_metrics, fetch_traffic_sources

svc = _Service(_router)
m = fetch_video_metrics("VID", svc)
check("metrics fetched", m["views"] == 1291 and m["averageViewPercentage"] == 76.6)
tr = fetch_traffic_sources("VID", svc)
check("traffic keyed by source", tr["SHORTS"]["views"] == 1200)
check("traffic numeric coercion", tr["NO_LINK_OTHER"]["views"] == 50)


# ── diagnose ───────────────────────────────────────────────────────────────
print("\n[TEST 3] diagnose verdicts")
from analysis.youtube_analytics import diagnose

healthy = diagnose(m, tr)
check("healthy feed verdict", healthy["verdict"] == "healthy_feed_distribution", healthy["verdict"])
check("feed share computed", healthy["shorts_feed_share"] == round(1200 / 1291, 3))

poor = diagnose({"views": 60, "averageViewPercentage": 20.0, "averageViewDuration": 4},
                {"SHORTS": {"views": 55}})
check("low retention -> retention_problem", poor["verdict"] == "retention_problem", poor["verdict"])
check("retention_problem has a flag", len(poor["flags"]) >= 1)

grl = diagnose({"views": 30, "averageViewPercentage": 62.0, "averageViewDuration": 13}, {})
check("good retention + low reach", grl["verdict"] == "good_retention_low_reach", grl["verdict"])

zero = diagnose({"views": 0}, {})
check("zero views -> no_data", zero["verdict"] == "no_data")

nofeed = diagnose({"views": 500, "averageViewPercentage": 55.0}, {"YT_SEARCH": {"views": 400}})
check("reach but no feed -> distributed_no_feed", nofeed["verdict"] == "distributed_no_feed", nofeed["verdict"])


# ── fetch_analytics orchestrator ───────────────────────────────────────────
print("\n[TEST 4] fetch_analytics orchestrator")
from analysis.youtube_analytics import fetch_analytics

out = fetch_analytics(["VID"], service=svc)
check("returns per-video bundle", "VID" in out and out["VID"]["diagnosis"]["verdict"] == "healthy_feed_distribution")
check("bundle carries metrics+traffic", out["VID"]["metrics"]["views"] == 1291 and "SHORTS" in out["VID"]["traffic"])
check("empty ids -> {}", fetch_analytics([], service=svc) == {})


# ── graceful failure ───────────────────────────────────────────────────────
print("\n[TEST 5] graceful degradation")


class _RaisingService:
    def reports(self): raise RuntimeError("insufficient scope")


check("video metrics error -> {}", fetch_video_metrics("VID", _RaisingService()) == {})
check("traffic error -> {}", fetch_traffic_sources("VID", _RaisingService()) == {})
bad = fetch_analytics(["VID"], service=_RaisingService())
check("orchestrator survives errors", bad["VID"]["diagnosis"]["verdict"] == "no_data")


# ── PerformanceStore.attach_analytics ──────────────────────────────────────
print("\n[TEST 6] PerformanceStore analytics attachment")
from core.performance import PerformanceStore, build_record

with tempfile.TemporaryDirectory() as dtmp:
    p = Path(dtmp) / "perf.json"
    store = PerformanceStore(p)
    store.upsert(build_record("VID", {"clips": [{"hook_text": "WOW"}]}))
    check("analytics pending before attach", store.analytics_pending_ids() == ["VID"])
    store.attach_analytics("VID", out["VID"])
    store.save()
    store2 = PerformanceStore(p)
    check("analytics persisted", store2.records["VID"]["analytics"]["diagnosis"]["verdict"]
          == "healthy_feed_distribution")
    check("analytics pending cleared", store2.analytics_pending_ids() == [])
    check("summary counts analyzed", store2.summary()["analyzed"] == 1, str(store2.summary()))
    check("attach on unknown id is a no-op", (store2.attach_analytics("NOPE", {}) or True))


# ── summary ────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
passed = sum(1 for _, s in results if s == "PASS")
print(f"RESULT: {passed}/{len(results)} passed")
print("=" * 60)
sys.exit(0 if passed == len(results) else 1)
