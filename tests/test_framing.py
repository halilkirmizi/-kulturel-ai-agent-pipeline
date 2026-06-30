"""Tests for 'fit' framing (full frame on blurred fill) — unit + real ffmpeg.

Run:  python tests/test_framing.py
"""

import subprocess
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
print("FRAMING (FIT) TEST SUITE")
print("=" * 60)

results = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  {status}: {name}" + (f" ({detail})" if detail else ""))
    results.append((name, status))


from core.config import build_config
from editing.render_core import build_crop_command
from editing.ffmpeg_builder import ffmpeg_path, execute, probe_duration

# ── unit: command shape ─────────────────────────────────────────────────────
print("\n[TEST 1] command shape")
cfg_crop = build_config(gpu=False)               # default framing=crop
cfg_fit = build_config(framing="fit", gpu=False)
cfg_fb_fit = build_config(content_type="football", framing="fit", gpu=False)

c_crop = build_crop_command(Path("in.mp4"), 0.0, 3.0, Path("o.mp4"), cfg_crop)
check("crop uses -vf centre crop", "-vf" in c_crop and
      "crop=ih*9/16:ih:(iw-ih*9/16)/2:0" in c_crop[c_crop.index("-vf") + 1])

c_fit = build_crop_command(Path("in.mp4"), 0.0, 3.0, Path("o.mp4"), cfg_fit)
fc = c_fit[c_fit.index("-filter_complex") + 1] if "-filter_complex" in c_fit else ""
check("fit uses filter_complex", "-filter_complex" in c_fit)
check("fit has blur background", "boxblur" in fc)
check("fit overlays full frame", "overlay=(W-w)/2:(H-h)/2" in fc)
check("fit keeps full width (decrease/fit)", "force_original_aspect_ratio=decrease" in fc)
check("fit maps optional audio", "0:a?" in c_fit)

c_fb = build_crop_command(Path("in.mp4"), 0.0, 3.0, Path("o.mp4"), cfg_fb_fit)
check("football ignores fit (keeps own crop)",
      "-vf" in c_fb and "ih-160" in c_fb[c_fb.index("-vf") + 1])

# ── config wiring ───────────────────────────────────────────────────────────
print("\n[TEST 2] config wiring")
check("default framing is crop", build_config().framing == "crop")
check("override sets fit", build_config(framing="fit").framing == "fit")

# ── integration: real fit render ────────────────────────────────────────────
print("\n[TEST 3] real fit render (ffmpeg)")
tmp = Path(tempfile.mkdtemp())
fixture = tmp / "land.mp4"
subprocess.run(
    [ffmpeg_path(), "-y", "-f", "lavfi",
     "-i", "testsrc2=size=1280x720:rate=30:duration=3",
     "-c:v", "libx264", "-pix_fmt", "yuv420p", str(fixture)],
    capture_output=True, text=True,
)
out = tmp / "fit.mp4"
rc = execute(build_crop_command(fixture, 0.0, 2.0, out, cfg_fit))


def size(p):
    import cv2
    c = cv2.VideoCapture(str(p))
    w, h = int(c.get(3)), int(c.get(4))
    c.release()
    return w, h


sz = size(out) if out.exists() else (0, 0)
check("fit render is 1080x1920", rc == 0 and sz == (1080, 1920), f"rc={rc} size={sz}")
check("fit render has duration", out.exists() and probe_duration(out) > 0)

import shutil
shutil.rmtree(tmp, ignore_errors=True)

print("\n" + "=" * 60)
passed = sum(1 for _, s in results if s == "PASS")
print(f"RESULT: {passed}/{len(results)} passed")
print("=" * 60)
sys.exit(0 if passed == len(results) else 1)
