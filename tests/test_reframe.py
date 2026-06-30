"""Tests for subject-aware reframe (analysis/reframe.py + crop wiring).

Plain-script style to match test_refactor.py. Run:
    python tests/test_reframe.py
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
print("REFRAME TEST SUITE")
print("=" * 60)

results = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  {status}: {name}" + (f" ({detail})" if detail else ""))
    results.append((name, status))


# ── compute_crop_x geometry (pure, deterministic) ──────────────────────────
print("\n[TEST 1] compute_crop_x geometry")
from analysis.reframe import compute_crop_x

W, H = 1920, 1080
crop_w = H * 9 / 16          # 607.5
centre_x = round((W - crop_w) / 2)   # what the old centre crop produced (656)

# A face dead-centre must reproduce the centre crop (no regression in spirit).
check("centre face == centre crop", compute_crop_x(W / 2, W, H) == centre_x,
      f"{compute_crop_x(W/2, W, H)} vs {centre_x}")

# Far-left subject clamps to 0 (never leaves the frame).
check("far-left clamps to 0", compute_crop_x(50, W, H) == 0)

# Far-right subject clamps to the max offset.
max_x = int(round(W - crop_w))
check("far-right clamps to max", compute_crop_x(W - 10, W, H) == max_x,
      f"{compute_crop_x(W-10, W, H)} vs {max_x}")

# A left-of-centre subject shifts the window left of the centre offset.
left_subj = compute_crop_x(W * 0.35, W, H)
check("left subject shifts left", 0 < left_subj < centre_x, f"x={left_subj}")

# Already-portrait source (window wider than frame) → no shift.
check("portrait source returns 0", compute_crop_x(300, 1080, 1920) == 0)


# ── detect_crop_x graceful degradation ─────────────────────────────────────
print("\n[TEST 2] detect_crop_x graceful degradation")
from analysis.reframe import detect_crop_x

check("missing file -> None",
      detect_crop_x(Path("____nope____.mp4"), 0.0, 5.0) is None)
check("zero-length window -> None",
      detect_crop_x(Path("____nope____.mp4"), 5.0, 5.0) is None)


# ── build_crop_command honours crop_x ──────────────────────────────────────
print("\n[TEST 3] build_crop_command wiring")
from core.config import build_config
from editing.render_core import build_crop_command

cfg = build_config()  # general content type

cmd_default = build_crop_command(Path("in.mp4"), 0.0, 5.0, Path("out.mp4"), cfg)
vf_default = cmd_default[cmd_default.index("-vf") + 1]
check("default crop is centred", "(iw-ih*9/16)/2" in vf_default, vf_default)

cmd_reframe = build_crop_command(Path("in.mp4"), 0.0, 5.0, Path("out.mp4"), cfg, crop_x=123)
vf_reframe = cmd_reframe[cmd_reframe.index("-vf") + 1]
check("crop_x honoured", "crop=ih*9/16:ih:123:0" in vf_reframe, vf_reframe)

cfg_fb = build_config(content_type="football")
cmd_fb = build_crop_command(Path("in.mp4"), 0.0, 5.0, Path("out.mp4"), cfg_fb, crop_x=123)
vf_fb = cmd_fb[cmd_fb.index("-vf") + 1]
check("football ignores crop_x", "123" not in vf_fb and "ih-160" in vf_fb, vf_fb)


# ── summary ────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
passed = sum(1 for _, s in results if s == "PASS")
print(f"RESULT: {passed}/{len(results)} passed")
print("=" * 60)
sys.exit(0 if passed == len(results) else 1)
