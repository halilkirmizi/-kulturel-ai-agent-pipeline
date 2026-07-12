"""Tests for bring-your-own-voice (--voice-file) VTT recovery.

Pure round-trip: whisper-style segments -> WEBVTT -> montage._parse_vtt.
No audio, no network, no whisper model (segments are faked).

Run:  python tests/test_voice_file.py
"""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

_PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PIPELINE_ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from analysis.tts import vtt_from_segments, _fmt_ts
from editing.montage import _parse_vtt

print("=" * 60)
print("VOICE-FILE (bring-your-own-voice) TEST SUITE")
print("=" * 60)

results = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  {status}: {name}" + (f" ({detail})" if detail else ""))
    results.append((name, status))


class _Seg:
    """Minimal stand-in for a faster-whisper segment."""
    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text


# ── timestamp formatting ──────────────────────────────────────────────────────
print("\n[TEST 1] _fmt_ts formatting")
check("zero", _fmt_ts(0) == "00:00:00.000", _fmt_ts(0))
check("sub-second", _fmt_ts(2.5) == "00:00:02.500", _fmt_ts(2.5))
check("minute rollover", _fmt_ts(65.25) == "00:01:05.250", _fmt_ts(65.25))
check("negative clamped", _fmt_ts(-3) == "00:00:00.000", _fmt_ts(-3))
check("montage regex shape (2-digit s, 3-digit ms)",
      len(_fmt_ts(5.5).split(":")[-1]) == 6, _fmt_ts(5.5))

# ── round-trip: segments -> VTT -> _parse_vtt ─────────────────────────────────
print("\n[TEST 2] segments -> VTT -> montage._parse_vtt round-trip")
segs = [
    _Seg(0.0, 2.4, "Norway were this close."),
    _Seg(2.4, 5.1, "  Then one man ruined it.  "),
    _Seg(5.1, 7.0, "Jude Bellingham."),
]
with TemporaryDirectory() as td:
    vtt = vtt_from_segments(segs, Path(td) / "voice.vtt")
    check("file written", vtt.exists())
    body = vtt.read_text(encoding="utf-8")
    check("starts with WEBVTT", body.startswith("WEBVTT"))
    cues = _parse_vtt(vtt)
    check("all 3 cues parse back", len(cues) == 3, f"{len(cues)} cues")
    check("first cue timing", abs(cues[0][0] - 0.0) < 0.001 and abs(cues[0][1] - 2.4) < 0.001)
    check("text stripped", cues[1][2] == "Then one man ruined it.", repr(cues[1][2]))

# ── empty / blank segments are skipped ────────────────────────────────────────
print("\n[TEST 3] blank and whitespace-only segments skipped")
segs2 = [
    _Seg(0.0, 1.0, "Hello"),
    _Seg(1.0, 2.0, "   "),
    _Seg(2.0, 3.0, ""),
    _Seg(3.0, 4.0, "World"),
]
with TemporaryDirectory() as td:
    vtt = vtt_from_segments(segs2, Path(td) / "v.vtt")
    cues = _parse_vtt(vtt)
    check("only 2 non-empty cues", len(cues) == 2, f"{len(cues)} cues")
    check("kept texts in order", [c[2] for c in cues] == ["Hello", "World"])


# ── summary ──────────────────────────────────────────────────────────────────
passed = sum(1 for _, s in results if s == "PASS")
total = len(results)
print("\n" + "=" * 60)
print(f"RESULT: {passed}/{total} passed")
print("=" * 60)
sys.exit(0 if passed == total else 1)
