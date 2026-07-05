"""Tests for the demonetization risk estimator.

Run:  python tests/test_demonetization.py
"""

import sys
from pathlib import Path

_PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PIPELINE_ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from analysis.demonetization import assess_demonetization, format_report

print("=" * 60)
print("DEMONETIZATION RISK TEST SUITE")
print("=" * 60)

results = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  {status}: {name}" + (f" ({detail})" if detail else ""))
    results.append((name, status))


# ── clean content ───────────────────────────────────────────────────────────
print("\n[TEST 1] clean football punditry -> LOW, no flags")
r = assess_demonetization(
    "Lamin Yamal scored a brilliant goal on his World Cup debut and Spain look strong."
)
check("clean -> LOW", r.risk_level == "LOW", f"{r.risk_level} {r.risk_score}")
check("clean -> no flags", r.flags == [], str(r.flags))
check("score in 0..1", 0.0 <= r.risk_score <= 1.0, str(r.risk_score))

# ── football metaphors must NOT false-positive ──────────────────────────────
print("\n[TEST 2] football metaphors -> still LOW (no false positives)")
r = assess_demonetization(
    "They absolutely killed them, shooting from distance, a war of attrition. "
    "Spain attacked relentlessly and beat them to death in midfield. Sudden death looms."
)
check("metaphors -> LOW", r.risk_level == "LOW", f"{r.risk_level} {r.risk_score}")
check("metaphors -> no flags", r.flags == [], str([f['category'] for f in r.flags]))

# ── strong profanity ────────────────────────────────────────────────────────
print("\n[TEST 3] strong profanity -> elevated risk + flag")
r = assess_demonetization("That was a fucking disgrace, what the fuck was he doing.")
check("strong profanity flagged", any(f["category"] == "profanity_strong" for f in r.flags), str(r.flags))
check("not LOW", r.risk_level in ("MEDIUM", "HIGH"), f"{r.risk_level} {r.risk_score}")

# ── slur -> HIGH ────────────────────────────────────────────────────────────
print("\n[TEST 4] hate slur -> HIGH")
r = assess_demonetization("he called him a retard on air")
check("slur flagged", any(f["category"] == "hate_slur" for f in r.flags))
check("slur -> HIGH", r.risk_level == "HIGH", f"{r.risk_level} {r.risk_score}")

# ── mild profanity is milder than strong ────────────────────────────────────
print("\n[TEST 5] mild < strong monotonicity")
mild = assess_demonetization("that was a bit shit to be honest").risk_score
strong = assess_demonetization("that was fucking shit").risk_score
check("mild single hit low", mild < 0.25, str(mild))
check("strong >= mild", strong >= mild, f"{strong} >= {mild}")

# ── external music (Content ID) ─────────────────────────────────────────────
print("\n[TEST 6] external music adds Content ID risk")
base = assess_demonetization("clean analytical clip").risk_score
music = assess_demonetization("clean analytical clip", has_external_music=True)
check("music raises score", music.risk_score > base, f"{music.risk_score} > {base}")
check("content_id flag present", any(f["category"] == "content_id_music" for f in music.flags))

# ── early profanity boost ───────────────────────────────────────────────────
print("\n[TEST 7] early strong language weighted heavier")
late = assess_demonetization("great goal. later he said fuck once.", early_text="great goal").risk_score
early = assess_demonetization("fuck great goal. later he said fuck once.", early_text="fuck great goal").risk_score
check("early >= late", early >= late, f"{early} >= {late}")

# ── bounds + level thresholds ───────────────────────────────────────────────
print("\n[TEST 8] score always bounded, level consistent")
heavy = assess_demonetization("fuck fuck cunt retard rape porn suicide", has_external_music=True)
check("score <= 1.0", heavy.risk_score <= 1.0, str(heavy.risk_score))
check("heavy -> HIGH", heavy.risk_level == "HIGH", f"{heavy.risk_level} {heavy.risk_score}")

# ── report format ───────────────────────────────────────────────────────────
print("\n[TEST 9] format_report")
rep = format_report(assess_demonetization("fucking hell"), "clip_1")
check("report has level", "DEMONETIZATION RISK" in rep and ("LOW" in rep or "MEDIUM" in rep or "HIGH" in rep))
check("report has label", "clip_1" in rep)

print("\n" + "=" * 60)
passed = sum(1 for _, s in results if s == "PASS")
print(f"RESULT: {passed}/{len(results)} passed")
print("=" * 60)
sys.exit(0 if passed == len(results) else 1)
