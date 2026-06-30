"""Tests for improved clip selection (analysis/clip_scoring.py).

Covers the deterministic parts of the fix: full-text window listing,
mid-thought detection, legacy fallback, harsher prompt. The actual LLM call
needs GROQ + a real transcript and is exercised separately.

Run:  python tests/test_clip_selection.py
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
print("CLIP SELECTION TEST SUITE")
print("=" * 60)

results = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  {status}: {name}" + (f" ({detail})" if detail else ""))
    results.append((name, status))


from analysis.clip_scoring import (
    _opens_mid_thought, _build_window_listing, _Window, CLIP_SYSTEM_PROMPT,
    _overlap_ratio, _dedupe_overlapping, ScoredClip,
    _fallback_window_score, _fallback_clip, MIN_CLIP, MAX_CLIP,
    _build_windows, MAX_WINDOWS, TARGET_WINS,
)


def _clip(start, end, score):
    return ScoredClip(start=start, end=end, duration=end - start, hook_text="h",
                      intro_script="", outro_script="", reason="", scores={},
                      score_total=score)


class Seg:
    def __init__(self, s, e, t):
        self.start, self.end, self.text = s, e, t


# ── mid-thought detection ───────────────────────────────────────────────────
print("\n[TEST 1] _opens_mid_thought")
check("'And so the...' -> mid-thought", _opens_mid_thought("And so the empire fell."))
check("'This is why...' -> mid-thought", _opens_mid_thought("This is why it matters."))
check("'Napoleon was...' -> clean", not _opens_mid_thought("Napoleon was a brilliant tactician."))
check("empty -> not mid-thought", not _opens_mid_thought(""))


# ── rich listing shows FULL text (the core fix) ─────────────────────────────
print("\n[TEST 2] rich listing shows full window text")
segs = [Seg(0, 3, "The Roman empire"), Seg(3, 6, "collapsed because of"),
        Seg(6, 9, "a unique combination of factors")]
wins = [_Window(wid=0, start=0.0, end=9.0,
                text="The Roman empire collapsed because of a unique combination of factors")]
rich = _build_window_listing(wins, segs, rich=True)
check("rich contains middle text", "collapsed because of a unique" in rich, "")
check("rich labels TEXT:", "TEXT:" in rich)

legacy = _build_window_listing(wins, segs, rich=False)
check("legacy is preview-only (STARTS WITH)", "STARTS WITH" in legacy and "TEXT:" not in legacy)


# ── mid-thought flag surfaces in listing ────────────────────────────────────
print("\n[TEST 3] mid-thought flag in listing")
mw = [_Window(wid=1, start=10.0, end=20.0, text="So anyway that was the whole point really")]
listing = _build_window_listing(mw, [], rich=True)
check("flag shown for mid-thought window", "starts mid-thought" in listing, "")


# ── harsher prompt content ──────────────────────────────────────────────────
print("\n[TEST 4] prompt strengthened")
check("prompt says read full text", "FULL text" in CLIP_SYSTEM_PROMPT)
check("prompt defines REJECT rules", "REJECT" in CLIP_SYSTEM_PROMPT)
check("prompt asks to be harsh", "HARSH" in CLIP_SYSTEM_PROMPT)
check("prompt keeps JSON contract", '"selections"' in CLIP_SYSTEM_PROMPT and "window_id" in CLIP_SYSTEM_PROMPT)


# ── overlap dedupe ──────────────────────────────────────────────────────────
print("\n[TEST 5] overlap dedupe")
a = _clip(0, 20, 30)      # highest score
b = _clip(2, 22, 28)      # overlaps a by 18/20 = 0.9 -> redundant, dropped
c = _clip(50, 70, 25)     # disjoint from a -> kept
d = _clip(52, 72, 20)     # overlaps c by 0.9 but lower score -> dropped
check("heavy overlap ratio ~0.9", abs(_overlap_ratio(a, b) - 0.9) < 1e-6, str(_overlap_ratio(a, b)))
check("disjoint ratio 0", _overlap_ratio(a, c) == 0.0)

kept = _dedupe_overlapping([a, b, c, d])
ids = {(k.start, k.end) for k in kept}
check("keeps highest of each overlap group (a,c)", (0, 20) in ids and (50, 70) in ids)
check("drops lower overlappers (b,d)", (2, 22) not in ids and (52, 72) not in ids)
check("exactly two kept", len(kept) == 2, str(len(kept)))
check("disjoint set untouched",
      len(_dedupe_overlapping([_clip(0, 10, 5), _clip(50, 60, 4)])) == 2)


# ── fallback quality ────────────────────────────────────────────────────────
print("\n[TEST 6] fallback quality")
fsegs = [
    Seg(0, 6, "Napoleon conquered most of Europe before his downfall in the brutal Russian winter"),
    Seg(6, 12, "his armies marched across the entire continent winning a long series of decisive battles"),
    Seg(12, 30, "and so that was basically the end of it"),
]
clean_dense = _Window(wid=0, start=0.0, end=12.0,
                      text=fsegs[0].text + " " + fsegs[1].text)
midthought_sparse = _Window(wid=1, start=12.0, end=30.0, text=fsegs[2].text)
check("clean+dense scores above mid-thought+sparse",
      _fallback_window_score(clean_dense, fsegs) > _fallback_window_score(midthought_sparse, fsegs))

fb = _fallback_clip(fsegs)
check("fallback returns a clip", fb is not None)
check("fallback duration valid", fb is not None and MIN_CLIP <= fb.duration <= MAX_CLIP, f"{fb.duration:.1f}")
check("fallback prefers dense window (starts at 0)", fb is not None and fb.start == 0.0)
check("empty -> None", _fallback_clip([]) is None)


# ── multi-length windows ────────────────────────────────────────────────────
print("\n[TEST 7] multi-length windows")
# 60s of 3s segments -> windows at multiple target lengths.
msegs = [Seg(i * 3.0, i * 3.0 + 3.0, f"sentence number {i} with several words here") for i in range(20)]
ws = _build_windows(msegs)
durs = {round(w.end - w.start) for w in ws}
check("produces multiple distinct lengths", len(durs) >= 2, str(sorted(durs)))
check("all windows >= MIN_CLIP", all((w.end - w.start) >= MIN_CLIP for w in ws))
check("count capped at MAX_WINDOWS", len(ws) <= MAX_WINDOWS, str(len(ws)))
check("wids are sequential", [w.wid for w in ws] == list(range(len(ws))))
check("empty segments -> no windows", _build_windows([]) == [])


# ── config wiring ───────────────────────────────────────────────────────────
print("\n[TEST 8] config wiring")
from core.config import build_config
check("default rich (legacy_select False)", build_config().legacy_select is False)
check("override legacy_select", build_config(legacy_select=True).legacy_select is True)


print("\n" + "=" * 60)
passed = sum(1 for _, s in results if s == "PASS")
print(f"RESULT: {passed}/{len(results)} passed")
print("=" * 60)
sys.exit(0 if passed == len(results) else 1)
