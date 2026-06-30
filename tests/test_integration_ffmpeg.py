"""Real-execution integration test for the new features.

Generates a synthetic 6s clip (tone / SILENCE / tone, 1280x720) and actually
runs ffmpeg/cv2 through the real builders — closing the "subprocess path not
E2E tested" caveat for reframe crop, karaoke captions and silence trim.

Needs ffmpeg (imageio_ffmpeg) + opencv. Does NOT need YouTube/Groq/GPU.
Run:  python tests/test_integration_ffmpeg.py
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

from editing.ffmpeg_builder import ffmpeg_path, execute, probe_duration, run_silencedetect

print("=" * 60)
print("FFMPEG INTEGRATION TEST (real execution)")
print("=" * 60)

results = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  {status}: {name}" + (f" ({detail})" if detail else ""))
    results.append((name, status))


def video_size(path):
    import cv2
    cap = cv2.VideoCapture(str(path))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return w, h


tmp = Path(tempfile.mkdtemp())
fixture = tmp / "fixture.mp4"

# ── fixture: 6s, audio tone[0-2] SILENCE[2-4] tone[4-6] ─────────────────────
# NOTE: commas inside the aevalsrc expression must be escaped (\,) or ffmpeg
# treats them as filtergraph separators. Tone[0-2] / SILENCE[2-4] / tone[4-6].
gen = [
    ffmpeg_path(), "-y",
    "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=6",
    "-f", "lavfi", "-i", r"aevalsrc=0.3*sin(2*PI*440*t)*lt(mod(t\,4)\,2):s=44100:d=6",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
    str(fixture),
]
genr = subprocess.run(gen, capture_output=True, text=True)
print("\n[SETUP] fixture")
if not fixture.exists():
    print("  fixture gen stderr:", genr.stderr[-400:])
check("fixture created ~6s", fixture.exists() and 5.5 < probe_duration(fixture) < 6.5,
      f"{probe_duration(fixture):.2f}s")

from core.config import build_config
cfg = build_config(gpu=False)  # CPU encode — no cuda hwaccel on this box

# ── 1) Silence detect + trim (real) ─────────────────────────────────────────
print("\n[TEST 1] silence detect + trim (real ffmpeg)")
from editing.silence import (
    build_silencedetect_command, parse_silencedetect,
    compute_keep_segments, kept_fraction, build_trim_command,
)
stderr = run_silencedetect(build_silencedetect_command(fixture, "-30dB", 0.5))
silences = parse_silencedetect(stderr)
overlaps = any(s < 4.0 and e > 2.0 for s, e in silences)
check("silence detected near [2,4]", len(silences) >= 1 and overlaps, str(silences))

keeps = compute_keep_segments(silences, probe_duration(fixture))
frac = kept_fraction(keeps, probe_duration(fixture))
check("kept fraction ~0.67 (<0.97)", 0.4 < frac < 0.97, f"{frac:.2f}")

trimmed = tmp / "trimmed.mp4"
rc = execute(build_trim_command(fixture, keeps, trimmed, cfg))
tdur = probe_duration(trimmed)
check("trim ran, output ~4s", rc == 0 and trimmed.exists() and 3.0 < tdur < 5.0,
      f"rc={rc} dur={tdur:.2f}")

# ── 2) Crop to 9:16 with crop_x (real) ──────────────────────────────────────
print("\n[TEST 2] crop 9:16 (real ffmpeg)")
from editing.render_core import build_crop_command
crop_out = tmp / "crop.mp4"
rc = execute(build_crop_command(fixture, 0.0, 3.0, crop_out, cfg, crop_x=100))
sz = video_size(crop_out) if crop_out.exists() else (0, 0)
check("crop_x output is 1080x1920", rc == 0 and sz == (1080, 1920), f"rc={rc} size={sz}")

crop_def = tmp / "crop_default.mp4"
rc = execute(build_crop_command(fixture, 0.0, 3.0, crop_def, cfg))
sz = video_size(crop_def) if crop_def.exists() else (0, 0)
check("default crop is 1080x1920", rc == 0 and sz == (1080, 1920), f"size={sz}")

# ── 3) Karaoke caption render (real ffmpeg subtitles) ───────────────────────
print("\n[TEST 3] karaoke caption render (real ffmpeg)")
from editing.captions import write_ass


class Seg:
    def __init__(self, s, e, t):
        self.start, self.end, self.text = s, e, t


segs = [Seg(0.0, 1.5, "hello brave new world"), Seg(1.5, 3.0, "this is a karaoke test")]
ass = tmp / "cap.ass"
write_ass(segs, ass, clip_duration=3.0, fontsize=38, margin_bottom=160,
          karaoke=True, highlight_color="&H0000FFFF")
cap_out = tmp / "captioned.mp4"
ass_escaped = ass.as_posix().replace(":", "\\:")
sub_cmd = [
    ffmpeg_path(), "-y", "-i", str(crop_out),
    "-vf", f"subtitles='{ass_escaped}':original_size=1080x1920",
    "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-c:a", "copy", "-vsync", "0",
    str(cap_out),
]
rc = execute(sub_cmd)
check("karaoke subtitles burned in", rc == 0 and cap_out.exists() and probe_duration(cap_out) > 0,
      f"rc={rc} dur={probe_duration(cap_out):.2f}")

# ── 4) reframe detect on real video (cv2 path, graceful) ────────────────────
print("\n[TEST 4] reframe detect (cv2 execution, graceful)")
from analysis.reframe import detect_crop_x
res = detect_crop_x(fixture, 0.0, 3.0)
# testsrc2 has no face → expect None (graceful); if something detected, must be in-range.
ok = res is None or (isinstance(res, int) and 0 <= res <= 1280)
check("detect runs without crash (None or in-range)", ok, f"result={res}")

# ── cleanup + summary ───────────────────────────────────────────────────────
import shutil
shutil.rmtree(tmp, ignore_errors=True)

print("\n" + "=" * 60)
passed = sum(1 for _, s in results if s == "PASS")
print(f"RESULT: {passed}/{len(results)} passed")
print("=" * 60)
sys.exit(0 if passed == len(results) else 1)
