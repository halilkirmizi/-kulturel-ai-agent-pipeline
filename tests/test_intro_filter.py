"""Tests for intro/housekeeping window filtering in clip selection.

Run:  python tests/test_intro_filter.py
"""

import sys
from dataclasses import dataclass
from pathlib import Path

_PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PIPELINE_ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from analysis.clip_scoring import _is_intro_text, _build_windows

print("=" * 60)
print("INTRO FILTER TEST SUITE")
print("=" * 60)

results = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  {status}: {name}" + (f" ({detail})" if detail else ""))
    results.append((name, status))


@dataclass
class Seg:
    start: float
    end: float
    text: str


# ── _is_intro_text precision ────────────────────────────────────────────────
print("\n[TEST 1] _is_intro_text detects intros, not real analysis")
check("welcome-to intro", _is_intro_text("Hello and welcome to the Athletic FC podcast with me, Emma."))
check("sponsor intro", _is_intro_text("This episode is brought to you by our sponsor."))
check("sign-off", _is_intro_text("Thanks for listening, see you next week."))
check("subscribe housekeeping", _is_intro_text("Make sure to subscribe for more."))
check("real analysis -> not intro", not _is_intro_text(
    "Germany conceded a soft goal and looked shaky defensively at the back."))
check("empty -> not intro", not _is_intro_text(""))

# ── _build_windows drops intro windows ──────────────────────────────────────
print("\n[TEST 2] _build_windows filters intro/housekeeping windows")
SEGS = [
    Seg(0, 6, "Hello and welcome to the podcast with me."),      # intro
    Seg(6, 12, "My name is Emma and today we talk football."),   # intro
    Seg(12, 18, "This is brought to you by our sponsor."),       # intro
    Seg(18, 24, "Germany looked shaky at the back defensively."),
    Seg(24, 30, "They conceded a soft goal early in the game."),
    Seg(30, 36, "But going forward they created several chances."),
    Seg(36, 42, "And finished them well to win the match late."),
    Seg(42, 48, "It was a strong response from the whole team."),
]
wins = _build_windows(SEGS)
check("windows produced", len(wins) >= 1, str(len(wins)))
check("no kept window is intro", all(not _is_intro_text(w.text) for w in wins),
      str([round(w.start) for w in wins if _is_intro_text(w.text)]))
check("earliest kept window past the intro (>=18s)", min(w.start for w in wins) >= 18,
      f"min_start={min(w.start for w in wins)}")

# ── safety: all-intro transcript keeps originals (never empty) ──────────────
print("\n[TEST 3] all-intro transcript -> not emptied")
ALL_INTRO = [
    Seg(0, 6, "Welcome to the show, my name is Emma."),
    Seg(6, 12, "Brought to you by our sponsor, thanks for listening."),
    Seg(12, 20, "Make sure to subscribe and see you next week."),
]
wins2 = _build_windows(ALL_INTRO)
check("not emptied when everything is intro", len(wins2) >= 1, str(len(wins2)))

print("\n" + "=" * 60)
passed = sum(1 for _, s in results if s == "PASS")
print(f"RESULT: {passed}/{len(results)} passed")
print("=" * 60)
sys.exit(0 if passed == len(results) else 1)
