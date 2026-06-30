"""Tests for the simulation-first learning engine (core/learning_engine.py).

Run:  python tests/test_learning.py
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
print("LEARNING ENGINE TEST SUITE (simulation-first)")
print("=" * 60)

results = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  {status}: {name}" + (f" ({detail})" if detail else ""))
    results.append((name, status))


from core.learning_engine import (
    compute_dimension_weights, compute_feature_lift, propose_weights,
    save_proposal, MIN_SAMPLES,
)


def rec(vid, perf, dims, features=None):
    return {"video_id": vid, "performance_score": perf,
            "dim_scores": dims, "features": features or {}}


# ── dimension weights: a dim that tracks performance gets >1.0 ──────────────
print("\n[TEST 1] compute_dimension_weights")
# curiosity HIGH when performance HIGH, LOW when performance LOW → emphasised.
# educational flat across the board → ~neutral.
data = [
    rec("a", 0.9, {"curiosity": 9, "educational_value": 5}),
    rec("b", 0.8, {"curiosity": 8, "educational_value": 5}),
    rec("c", 0.2, {"curiosity": 2, "educational_value": 5}),
    rec("d", 0.1, {"curiosity": 1, "educational_value": 5}),
]
w = compute_dimension_weights(data)
check("curiosity weighted up (>1)", w["curiosity"] > 1.0, str(w))
check("flat educational ~neutral", abs(w["educational_value"] - 1.0) < 0.05, str(w))
check("weights clamped to [0.5,1.5]", all(0.5 <= v <= 1.5 for v in w.values()))

# ── min-samples guard ───────────────────────────────────────────────────────
print("\n[TEST 2] min-samples guard")
check("too few samples -> empty weights",
      compute_dimension_weights(data[:MIN_SAMPLES - 1]) == {})

# ── feature lift ────────────────────────────────────────────────────────────
print("\n[TEST 3] compute_feature_lift")
fdata = [
    rec("a", 0.9, {"curiosity": 9}, {"karaoke": True}),
    rec("b", 0.8, {"curiosity": 8}, {"karaoke": True}),
    rec("c", 0.3, {"curiosity": 3}, {"karaoke": False}),
    rec("d", 0.2, {"curiosity": 2}, {"karaoke": False}),
]
lift = compute_feature_lift(fdata)
check("karaoke positive lift", lift["karaoke"] is not None and lift["karaoke"] > 0, str(lift))
# only-one-side -> None
one_side = compute_feature_lift([rec("a", 0.9, {"c": 9}, {"x": True}),
                                 rec("b", 0.8, {"c": 8}, {"x": True}),
                                 rec("c", 0.7, {"c": 7}, {"x": True})])
check("single-group feature -> None", one_side["x"] is None)

# ── propose + versioning (never overwrites) ─────────────────────────────────
print("\n[TEST 4] propose_weights + versioning")
prop = propose_weights(data)
check("proposal not applied", prop["applied"] is False)
check("proposal has dim weights", bool(prop["dimension_weights"]))
check("proposal carries sample count", prop["n_samples"] == 4)

low = propose_weights(data[:1])
check("low sample flagged", low["low_confidence"] is True and low["dimension_weights"] == {})

with tempfile.TemporaryDirectory() as d:
    wd = Path(d) / "weights"
    p1 = save_proposal(prop, wd)
    p2 = save_proposal(prop, wd)
    check("first is v1", p1.name == "weights_v1.json")
    check("second is v2 (no overwrite)", p2.name == "weights_v2.json" and p1.exists())

# ── summary ────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
passed = sum(1 for _, s in results if s == "PASS")
print(f"RESULT: {passed}/{len(results)} passed")
print("=" * 60)
sys.exit(0 if passed == len(results) else 1)
