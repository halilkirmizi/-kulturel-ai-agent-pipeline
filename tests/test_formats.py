"""Tests for format profiles — especially the 'subtitled' profile that turns on
fit framing + disables our captions, without affecting the default format.

Run:  python tests/test_formats.py
"""

import sys
from pathlib import Path

_PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PIPELINE_ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

print("=" * 60)
print("FORMAT PROFILE TEST SUITE")
print("=" * 60)

results = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  {status}: {name}" + (f" ({detail})" if detail else ""))
    results.append((name, status))


from core.config import build_config

# ── default format unchanged ────────────────────────────────────────────────
print("\n[TEST 1] default (format1) unchanged")
d = build_config()
check("default framing crop", d.framing == "crop", d.framing)
check("default captions enabled", d.captions.enabled is True)

# ── subtitled profile ───────────────────────────────────────────────────────
print("\n[TEST 2] format_subtitled profile")
s = build_config(format_name="format_subtitled")
check("subtitled framing fit", s.framing == "fit", s.framing)
check("subtitled captions disabled", s.captions.enabled is False)

# ── flag still overrides ────────────────────────────────────────────────────
print("\n[TEST 3] flags interact correctly")
check("--no-captions disables on format1",
      build_config(no_captions=True).captions.enabled is False)
check("--framing fit works on format1",
      build_config(framing="fit").framing == "fit")
# format enables captions by default even if file omits the key
check("format1 omits 'enabled' -> defaults True", build_config().captions.enabled is True)

print("\n" + "=" * 60)
passed = sum(1 for _, st in results if st == "PASS")
print(f"RESULT: {passed}/{len(results)} passed")
print("=" * 60)
sys.exit(0 if passed == len(results) else 1)
