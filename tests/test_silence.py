"""Tests for silence trimming helpers (editing/silence.py).

Plain-script style. Run:
    python tests/test_silence.py
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
print("SILENCE TRIM TEST SUITE")
print("=" * 60)

results = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  {status}: {name}" + (f" ({detail})" if detail else ""))
    results.append((name, status))


from editing.silence import (
    parse_silencedetect, compute_keep_segments, kept_fraction,
    build_trim_command, build_silencedetect_command,
)

# ── parse_silencedetect ────────────────────────────────────────────────────
print("\n[TEST 1] parse_silencedetect")
log = (
    "[silencedetect @ 0x1] silence_start: 2.0\n"
    "[silencedetect @ 0x1] silence_end: 4.0 | silence_duration: 2.0\n"
    "[silencedetect @ 0x1] silence_start: 7.5\n"
    "[silencedetect @ 0x1] silence_end: 9.0 | silence_duration: 1.5\n"
)
spans = parse_silencedetect(log)
check("two spans parsed", spans == [(2.0, 4.0), (7.5, 9.0)], str(spans))
check("dangling start ignored",
      parse_silencedetect("silence_start: 1.0\n") == [])

# ── compute_keep_segments ──────────────────────────────────────────────────
print("\n[TEST 2] compute_keep_segments")
# 10s total, silence [2,4] and [7.5,9]; pad 0.05 → keeps speech around them.
keeps = compute_keep_segments([(2.0, 4.0), (7.5, 9.0)], 10.0, pad=0.05)
# Expected keeps: [0,2.05], [3.95,7.55], [8.95,10]
check("three keep spans", len(keeps) == 3, str(keeps))
check("first starts at 0", abs(keeps[0][0]) < 1e-6)
check("last ends at total", abs(keeps[-1][1] - 10.0) < 1e-6)
check("ordered & non-overlapping",
      all(keeps[i][1] <= keeps[i + 1][0] + 1e-9 for i in range(len(keeps) - 1)))

# Padding erases a too-short silence (0.08s < 2*pad) → treated as speech.
keeps_short = compute_keep_segments([(5.0, 5.08)], 10.0, pad=0.05)
check("tiny silence vanishes -> one span", len(keeps_short) == 1, str(keeps_short))

# No silence → whole clip kept.
check("no silence keeps all",
      compute_keep_segments([], 10.0) == [(0.0, 10.0)])

# ── kept_fraction ──────────────────────────────────────────────────────────
print("\n[TEST 3] kept_fraction")
frac = kept_fraction(keeps, 10.0)
check("fraction in (0,1)", 0.0 < frac < 1.0, f"{frac:.3f}")
check("empty total safe", kept_fraction([], 0.0) == 1.0)

# ── build_trim_command ─────────────────────────────────────────────────────
print("\n[TEST 4] build_trim_command")
from core.config import build_config
cfg = build_config()
cmd = build_trim_command(Path("in.mp4"), [(0.0, 2.0), (4.0, 6.0)], Path("out.mp4"), cfg)
vf = cmd[cmd.index("-vf") + 1]
af = cmd[cmd.index("-af") + 1]
check("vf selects both spans",
      "between(t,0.000,2.000)" in vf and "between(t,4.000,6.000)" in vf, vf)
check("vf resets pts", "setpts=N/FRAME_RATE/TB" in vf)
check("af resets pts", "asetpts=N/SR/TB" in af)
check("output last arg", cmd[-1] == "out.mp4")

# ── build_silencedetect_command ────────────────────────────────────────────
print("\n[TEST 5] build_silencedetect_command")
dcmd = build_silencedetect_command(Path("in.mp4"), "-30dB", 0.5)
check("uses silencedetect filter",
      any("silencedetect=noise=-30dB:d=0.5" in str(x) for x in dcmd), str(dcmd))
check("null output", dcmd[-1] == "-" and "null" in dcmd)

# ── summary ────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
passed = sum(1 for _, s in results if s == "PASS")
print(f"RESULT: {passed}/{len(results)} passed")
print("=" * 60)
sys.exit(0 if passed == len(results) else 1)
