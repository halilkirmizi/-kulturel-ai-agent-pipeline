"""Tests for closing the learning loop: applying learned weights to scoring.

Covers the deterministic wiring (weighted total, ranking flip, latest-weights
loader). The LLM call itself is not exercised here.

Run:  python tests/test_apply_weights.py
"""

import json
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
print("APPLY-WEIGHTS (learning loop) TEST SUITE")
print("=" * 60)

results = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  {status}: {name}" + (f" ({detail})" if detail else ""))
    results.append((name, status))


from analysis.clip_scoring import _weighted_total

# ── weighted total ──────────────────────────────────────────────────────────
print("\n[TEST 1] _weighted_total")
scores = {"curiosity": 8, "educational_value": 4}
check("no weights -> plain sum", _weighted_total(scores, None) == 12)
check("empty weights -> plain sum", _weighted_total(scores, {}) == 12)
# emphasise curiosity (1.5), damp educational (0.5): 8*1.5 + 4*0.5 = 14
check("weights re-weight sum", _weighted_total(scores, {"curiosity": 1.5, "educational_value": 0.5}) == 14)
check("missing dim defaults to 1.0",
      _weighted_total(scores, {"curiosity": 1.5}) == 8 * 1.5 + 4)

# ── ranking flips with weights ──────────────────────────────────────────────
print("\n[TEST 2] ranking can flip with learned weights")
# clip A: high educational; clip B: high curiosity. Equal plain totals.
A = {"curiosity": 2, "educational_value": 10}   # plain 12
B = {"curiosity": 10, "educational_value": 2}    # plain 12
check("equal under no weights", _weighted_total(A, None) == _weighted_total(B, None))
w = {"curiosity": 1.5, "educational_value": 0.5}
check("curiosity-weighting favours B", _weighted_total(B, w) > _weighted_total(A, w),
      f"A={_weighted_total(A, w)} B={_weighted_total(B, w)}")

# ── load_latest_weights ─────────────────────────────────────────────────────
print("\n[TEST 3] load_latest_weights")
from core.learning_engine import load_latest_weights

with tempfile.TemporaryDirectory() as d:
    wd = Path(d) / "weights"
    wd.mkdir()
    check("missing dir -> {}", load_latest_weights(Path(d) / "nope") == {})
    (wd / "weights_v1.json").write_text(json.dumps(
        {"version": 1, "low_confidence": False, "dimension_weights": {"curiosity": 1.2}}))
    (wd / "weights_v2.json").write_text(json.dumps(
        {"version": 2, "low_confidence": True, "dimension_weights": {"curiosity": 9.9}}))
    # v2 is low_confidence -> should fall back to v1 (highest CONFIDENT)
    check("skips low_confidence, picks confident v1",
          load_latest_weights(wd) == {"curiosity": 1.2}, str(load_latest_weights(wd)))
    (wd / "weights_v3.json").write_text(json.dumps(
        {"version": 3, "low_confidence": False, "dimension_weights": {"curiosity": 1.4}}))
    check("picks highest confident (v3)", load_latest_weights(wd) == {"curiosity": 1.4})

# ── config wiring ───────────────────────────────────────────────────────────
print("\n[TEST 4] config wiring")
from core.config import build_config
check("default apply_weights False", build_config().apply_weights is False)
check("override apply_weights", build_config(apply_weights=True).apply_weights is True)

print("\n" + "=" * 60)
passed = sum(1 for _, s in results if s == "PASS")
print(f"RESULT: {passed}/{len(results)} passed")
print("=" * 60)
sys.exit(0 if passed == len(results) else 1)
