"""Performance feedback layer — the ground truth for the learning loop.

This is the missing link between "we made a clip" and "did it actually
perform". Each uploaded video gets a provenance record (what produced it:
hook, LLM scores, which features were on). Later, real YouTube statistics are
attached and distilled into a single deterministic ``performance_score`` that
a future learning_engine can consume.

Design rules (mirrors ROADMAP):
- Deterministic scoring only — NO LLM in this layer.
- Append/update store keyed by video_id; never lose provenance.
- Pure functions are unit-testable without any API/credentials.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def compute_performance_score(stats: Dict[str, Any]) -> float:
    """Distil raw YouTube statistics into a single 0..1 performance signal.

    Deterministic blend of reach (log-scaled views) and engagement
    ((likes+comments)/views). Returns 0.0 for empty/unknown stats.

    Anchors: ~10k views → reach≈1.0; ~5% engagement → engagement≈1.0.
    """
    views = _to_int(stats.get("viewCount"))
    likes = _to_int(stats.get("likeCount"))
    comments = _to_int(stats.get("commentCount"))

    if views <= 0:
        return 0.0

    reach = min(1.0, math.log10(views + 1) / 4.0)            # 10^4 = 10k → 1.0
    engagement_rate = (likes + comments) / views
    engagement = min(1.0, engagement_rate * 20.0)            # 0.05 → 1.0

    score = 0.6 * reach + 0.4 * engagement
    return round(max(0.0, min(1.0, score)), 4)


def _to_int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def build_record(
    video_id: str,
    state: Dict[str, Any],
    features: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
    """Build a provenance record linking an upload to what produced it."""
    clip = (state.get("clips") or [{}])[0]
    meta = clip.get("metadata", {})
    return {
        "video_id": video_id,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "source_video_url": state.get("source_video_url", ""),
        "hook_text": clip.get("hook_text", ""),
        "llm_score": clip.get("score"),
        "dim_scores": meta.get("scores", {}),
        "features": features or {},
        "stats": None,          # filled by fetch-analytics
        "performance_score": None,
    }


class PerformanceStore:
    """JSON-backed store of upload provenance + performance, keyed by video_id."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.records: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self.records = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.records = {}

    def save(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.records, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(self.path)

    def upsert(self, record: Dict[str, Any]) -> None:
        vid = record["video_id"]
        existing = self.records.get(vid, {})
        existing.update(record)
        self.records[vid] = existing

    def pending_ids(self) -> List[str]:
        """video_ids that have no stats attached yet."""
        return [vid for vid, r in self.records.items() if not r.get("stats")]

    def attach_stats(self, video_id: str, stats: Dict[str, Any]) -> None:
        r = self.records.get(video_id)
        if r is None:
            return
        r["stats"] = stats
        r["performance_score"] = compute_performance_score(stats)

    def attach_analytics(self, video_id: str, data: Dict[str, Any]) -> None:
        """Attach rich Analytics-API data (metrics + traffic + diagnosis).

        Separate from ``attach_stats`` so the existing Data-API-based
        performance_score/learning loop is untouched; this only enriches the
        record with retention + traffic-source diagnosis.
        """
        r = self.records.get(video_id)
        if r is None:
            return
        r["analytics"] = data

    def analytics_pending_ids(self) -> List[str]:
        """video_ids that have no rich analytics attached yet."""
        return [vid for vid, r in self.records.items() if not r.get("analytics")]

    def summary(self) -> Dict[str, Any]:
        scored = [r for r in self.records.values() if r.get("performance_score") is not None]
        avg = round(sum(r["performance_score"] for r in scored) / len(scored), 4) if scored else None
        return {
            "total": len(self.records),
            "pending": len(self.pending_ids()),
            "scored": len(scored),
            "analyzed": sum(1 for r in self.records.values() if r.get("analytics")),
            "avg_performance": avg,
        }
