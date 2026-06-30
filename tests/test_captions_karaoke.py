"""Tests for karaoke captions (editing/captions.py).

Plain-script style to match test_refactor.py. Run:
    python tests/test_captions_karaoke.py
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
print("KARAOKE CAPTIONS TEST SUITE")
print("=" * 60)

results = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  {status}: {name}" + (f" ({detail})" if detail else ""))
    results.append((name, status))


class Seg:
    def __init__(self, start, end, text):
        self.start, self.end, self.text = start, end, text


# ── _karaoke_text helper ───────────────────────────────────────────────────
print("\n[TEST 1] _karaoke_text")
from editing.captions import _karaoke_text
import re

txt = _karaoke_text("hello brave new world", 2.0)  # 200 cs over 4 words
ks = [int(x) for x in re.findall(r"\\k(\d+)", txt)]
check("one \\k per word", len(ks) == 4, str(ks))
check("\\k sums to duration", sum(ks) == 200, f"sum={sum(ks)}")
check("all words present", all(w in txt for w in ["hello", "brave", "new", "world"]))
check("empty chunk safe", _karaoke_text("", 1.0) == "")


# ── write_ass: static mode unchanged (regression) ──────────────────────────
print("\n[TEST 2] static mode has no karaoke tags")
from editing.captions import write_ass

segs = [Seg(0.0, 2.0, "hello world"), Seg(2.0, 4.0, "second line here")]
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "static.ass"
    write_ass(segs, p, clip_duration=5.0, fontsize=38, margin_bottom=160)
    static = p.read_text(encoding="utf-8-sig")
check("no \\k in static output", "\\k" not in static)
check("static primary is white", "Caption,Arial,38,&H00FFFFFF,&H000000FF" in static, "style")


# ── write_ass: karaoke mode ────────────────────────────────────────────────
print("\n[TEST 3] karaoke mode")
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "kara.ass"
    write_ass(segs, p, clip_duration=5.0, fontsize=38, margin_bottom=160,
              karaoke=True, highlight_color="&H0000FFFF")
    kara = p.read_text(encoding="utf-8-sig")
check("karaoke output has \\k tags", "\\k" in kara)
check("primary=highlight, secondary=white",
      "Caption,Arial,38,&H0000FFFF,&H00FFFFFF" in kara, "style")
check("dialogue lines present", kara.count("Dialogue:") >= 2,
      f"count={kara.count('Dialogue:')}")


# ── summary ────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
passed = sum(1 for _, s in results if s == "PASS")
print(f"RESULT: {passed}/{len(results)} passed")
print("=" * 60)
sys.exit(0 if passed == len(results) else 1)
