"""Tests for the performance feedback layer (core/performance.py,
analysis/youtube_stats.py). No real API — a mock service is injected.

Run:  python tests/test_performance.py
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
print("PERFORMANCE FEEDBACK TEST SUITE")
print("=" * 60)

results = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  {status}: {name}" + (f" ({detail})" if detail else ""))
    results.append((name, status))


# ── compute_performance_score ──────────────────────────────────────────────
print("\n[TEST 1] compute_performance_score")
from core.performance import compute_performance_score as score

check("empty stats -> 0.0", score({}) == 0.0)
check("zero views -> 0.0", score({"viewCount": "0"}) == 0.0)
s_low = score({"viewCount": "100", "likeCount": "1", "commentCount": "0"})
s_high = score({"viewCount": "50000", "likeCount": "4000", "commentCount": "500"})
check("more reach+engagement scores higher", s_high > s_low, f"{s_high} > {s_low}")
check("clamped to [0,1]", 0.0 <= s_high <= 1.0 and 0.0 <= s_low <= 1.0)
check("viral clamps at 1.0",
      score({"viewCount": "10000000", "likeCount": "9000000", "commentCount": "1000000"}) == 1.0)
check("string/missing fields safe", score({"viewCount": "abc"}) == 0.0)


# ── build_record ───────────────────────────────────────────────────────────
print("\n[TEST 2] build_record")
from core.performance import build_record

state = {
    "source_video_url": "https://youtu.be/x",
    "clips": [{"hook_text": "WOW", "score": 8.5,
               "metadata": {"scores": {"curiosity": 9}}}],
}
rec = build_record("VID123", state, features={"karaoke": True})
check("record keyed fields", rec["video_id"] == "VID123" and rec["hook_text"] == "WOW")
check("llm + dim scores carried", rec["llm_score"] == 8.5 and rec["dim_scores"] == {"curiosity": 9})
check("features carried", rec["features"] == {"karaoke": True})
check("stats/score start empty", rec["stats"] is None and rec["performance_score"] is None)


# ── PerformanceStore round-trip ────────────────────────────────────────────
print("\n[TEST 3] PerformanceStore")
from core.performance import PerformanceStore

with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "perf.json"
    store = PerformanceStore(p)
    store.upsert(rec)
    store.save()
    check("pending lists unscored", store.pending_ids() == ["VID123"])

    # reload from disk
    store2 = PerformanceStore(p)
    check("persisted across reload", "VID123" in store2.records)
    store2.attach_stats("VID123", {"viewCount": "50000", "likeCount": "4000", "commentCount": "500"})
    check("attach clears pending", store2.pending_ids() == [])
    check("score computed on attach", store2.records["VID123"]["performance_score"] > 0)
    summ = store2.summary()
    check("summary counts", summ["total"] == 1 and summ["scored"] == 1, str(summ))


# ── youtube_stats parsing with MOCK service ────────────────────────────────
print("\n[TEST 4] fetch_stats with mock service")
from analysis.youtube_stats import fetch_stats, parse_stats_response

resp = {"items": [
    {"id": "A", "statistics": {"viewCount": "10", "likeCount": "2"}},
    {"id": "B", "statistics": {"viewCount": "99"}},
]}
parsed = parse_stats_response(resp)
check("parse maps id->stats", parsed["A"]["viewCount"] == "10" and parsed["B"]["viewCount"] == "99")


class _MockReq:
    def __init__(self, resp): self._r = resp
    def execute(self): return self._r


class _MockVideos:
    def __init__(self, resp): self._r = resp
    def list(self, part, id): return _MockReq(self._r)


class _MockService:
    def __init__(self, resp): self._r = resp
    def videos(self): return _MockVideos(self._r)


out = fetch_stats(["A", "B"], service=_MockService(resp))
check("fetch via mock returns parsed", out["A"]["viewCount"] == "10" and "B" in out)
check("empty ids -> {}", fetch_stats([], service=_MockService(resp)) == {})


class _RaisingService:
    def videos(self): raise RuntimeError("api down")


check("api error -> {} (graceful)", fetch_stats(["A"], service=_RaisingService()) == {})


# ── summary ────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
passed = sum(1 for _, s in results if s == "PASS")
print(f"RESULT: {passed}/{len(results)} passed")
print("=" * 60)
sys.exit(0 if passed == len(results) else 1)
