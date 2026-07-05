"""Tests for sentence-boundary snapping of clip cut points.

Run:  python tests/test_sentence_snap.py
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

from analysis.clip_scoring import _snap_to_sentences, _expand_to_boundaries, _ends_sentence

print("=" * 60)
print("SENTENCE SNAP TEST SUITE")
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


# whisper-style segments that break mid-sentence (VAD ~5-6s chunks)
SEGS = [
    Seg(0, 5, "We were talking about the defence."),        # ends sentence -> next starts clean
    Seg(5, 11, "Germany looked shaky at the back"),          # no punct -> next NOT a clean start
    Seg(11, 17, "and conceded a soft goal early on."),       # ends sentence
    Seg(17, 23, "But going forward they created chances"),   # no punct
    Seg(23, 29, "and finished them well in the end."),       # ends sentence
]

# ── _ends_sentence ──────────────────────────────────────────────────────────
print("\n[TEST 1] _ends_sentence")
check("period ends", _ends_sentence("hello world."))
check("question ends", _ends_sentence("really?"))
check("exclaim ends", _ends_sentence("wow!"))
check("closing quote ok", _ends_sentence('he said "yes."'))
check("no punct -> False", not _ends_sentence("germany looked shaky"))

# ── snapping fixes mid-sentence cut ─────────────────────────────────────────
print("\n[TEST 2] snap mid-sentence request to clean sentence bounds")
s, e = _snap_to_sentences(6.0, 20.0, SEGS)   # start mid-seg1, end mid-seg3
check("start snaps to a clean sentence start", s in (0.0, 5.0, 17.0), f"start={s}")
check("start is 5 (nearest clean start to 6)", s == 5.0, f"start={s}")
check("end snaps to a sentence end", e in (5.0, 17.0, 29.0), f"end={e}")
check("duration >= MIN_CLIP", (e - s) >= 12, f"dur={e - s}")

# ── does not start mid-thought (regression on the real bug) ─────────────────
print("\n[TEST 3] chosen start is a real sentence start")
# the segment starting at s must be preceded by a sentence-ending segment (or be first)
idx = next((i for i, seg in enumerate(SEGS) if seg.start == s), None)
clean = idx == 0 or _ends_sentence(SEGS[idx - 1].text)
check("start segment follows a completed sentence", clean, f"idx={idx}")

# ── fallback when transcript has no punctuation ─────────────────────────────
print("\n[TEST 4] no punctuation -> falls back to segment expansion")
NOPUNCT = [Seg(0, 5, "one two three"), Seg(5, 11, "four five six"), Seg(11, 17, "seven eight")]
snap = _snap_to_sentences(6.0, 12.0, NOPUNCT)
expand = _expand_to_boundaries(6.0, 12.0, NOPUNCT)
check("fallback equals segment expansion", snap == expand, f"{snap} vs {expand}")

# ── empty segments safe ─────────────────────────────────────────────────────
print("\n[TEST 5] empty segments returns input unchanged")
check("empty -> passthrough", _snap_to_sentences(3.0, 9.0, []) == (3.0, 9.0))

# ── never exceeds MAX_CLIP when an in-range end exists ──────────────────────
print("\n[TEST 6] prefers in-range duration")
s2, e2 = _snap_to_sentences(0.0, 15.0, SEGS)
check("duration within [12,35]", 12 <= (e2 - s2) <= 35, f"dur={e2 - s2}")

print("\n" + "=" * 60)
passed = sum(1 for _, s in results if s == "PASS")
print(f"RESULT: {passed}/{len(results)} passed")
print("=" * 60)
sys.exit(0 if passed == len(results) else 1)
