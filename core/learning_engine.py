"""Learning engine — SIMULATION-FIRST (ROADMAP STEP 3).

Takes the performance feedback records (provenance + real performance_score)
and PROPOSES adjusted clip-scoring dimension weights + feature insights.

Critical discipline (ROADMAP design rules):
- Rule 1: NO real-time mutation. This runs AFTER the pipeline; it only writes a
  versioned proposal (weights/weights_vN.json). NOTHING reads it back yet.
- Rule 2: NO LLM. Deterministic metrics only.
- Rule 4: weights are versioned, never overwritten.

A future step will connect a proposal → ControlArbiter scoring bias. Until then
this is observation/simulation: it tells you what it *would* learn, safely.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

MIN_SAMPLES = 3  # below this we don't pretend to have learned anything


def _scored(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in records if r.get("performance_score") is not None and r.get("dim_scores")]


def compute_dimension_weights(records: List[Dict[str, Any]]) -> Dict[str, float]:
    """Per-dimension weight multiplier in [0.5, 1.5] (1.0 = neutral).

    A dimension that scores *higher among better-performing videos* than it does
    on average gets a multiplier > 1.0 (emphasise it); the reverse gets < 1.0.
    Deterministic; returns {} when there is nothing to learn from.
    """
    rows = _scored(records)
    if len(rows) < MIN_SAMPLES:
        return {}

    dims = sorted({d for r in rows for d in r["dim_scores"].keys()})
    perf = [float(r["performance_score"]) for r in rows]
    perf_sum = sum(perf) or 1.0

    weights: Dict[str, float] = {}
    for d in dims:
        vals = [float(r["dim_scores"].get(d, 0)) for r in rows]
        plain_mean = sum(vals) / len(vals)
        if plain_mean <= 0:
            weights[d] = 1.0
            continue
        weighted_mean = sum(p * v for p, v in zip(perf, vals)) / perf_sum
        rel_lift = (weighted_mean - plain_mean) / plain_mean   # relative
        mult = 1.0 + rel_lift
        weights[d] = round(max(0.5, min(1.5, mult)), 4)
    return weights


def compute_feature_lift(records: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    """Avg performance with each feature ON minus OFF. None when a side is empty."""
    rows = _scored(records)
    feats = sorted({f for r in rows for f in (r.get("features") or {}).keys()})
    out: Dict[str, Optional[float]] = {}
    for f in feats:
        on = [r["performance_score"] for r in rows if (r.get("features") or {}).get(f)]
        off = [r["performance_score"] for r in rows if not (r.get("features") or {}).get(f)]
        if on and off:
            out[f] = round(sum(on) / len(on) - sum(off) / len(off), 4)
        else:
            out[f] = None
    return out


def propose_weights(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a deterministic, non-applied weight proposal from feedback records."""
    rows = _scored(records)
    dim_weights = compute_dimension_weights(records)
    low_conf = len(rows) < MIN_SAMPLES
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_samples": len(rows),
        "low_confidence": low_conf,
        "dimension_weights": dim_weights or {},   # empty => not enough data
        "feature_lift": compute_feature_lift(records),
        "applied": False,   # SIMULATION ONLY — never auto-applied
        "note": ("insufficient samples — neutral, nothing learned"
                 if low_conf else "simulation proposal; not applied"),
    }


def _next_version(weights_dir: Path) -> int:
    weights_dir.mkdir(parents=True, exist_ok=True)
    versions = [int(m.group(1)) for p in weights_dir.glob("weights_v*.json")
                if (m := re.match(r"weights_v(\d+)\.json$", p.name))]
    return (max(versions) + 1) if versions else 1


def save_proposal(proposal: Dict[str, Any], weights_dir: Path) -> Path:
    """Write the proposal to weights/weights_vN.json (never overwrites — Rule 4)."""
    n = _next_version(weights_dir)
    proposal = {**proposal, "version": n}
    path = weights_dir / f"weights_v{n}.json"
    path.write_text(json.dumps(proposal, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_latest_weights(weights_dir: Path) -> Dict[str, float]:
    """Return the dimension_weights of the highest-version, confident proposal.

    Returns {} when there is no usable proposal — so applying weights is a no-op
    until enough real data has produced a confident one.
    """
    weights_dir = Path(weights_dir)
    if not weights_dir.exists():
        return {}
    best = None  # (version, weights)
    for p in weights_dir.glob("weights_v*.json"):
        m = re.match(r"weights_v(\d+)\.json$", p.name)
        if not m:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("low_confidence") or not data.get("dimension_weights"):
            continue
        v = int(m.group(1))
        if best is None or v > best[0]:
            best = (v, data["dimension_weights"])
    return best[1] if best else {}
