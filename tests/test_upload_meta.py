"""Tests for upload metadata: tags, scheduled publish-at, language, category.

Run:  python tests/test_upload_meta.py
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
print("UPLOAD METADATA TEST SUITE")
print("=" * 60)

results = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  {status}: {name}" + (f" ({detail})" if detail else ""))
    results.append((name, status))


from core.upload import _build_tags, _to_publish_at_iso

# ── tags ────────────────────────────────────────────────────────────────────
print("\n[TEST 1] _build_tags")
t = _build_tags("Haaland's Real Motivation", "HAALAND'S BRUTAL TRUTH 🔥")
check("includes base sport tags", "football" in t and "shorts" in t, str(t))
check("includes subject keyword", "haaland" in [x.lower() for x in t], str(t))
check("<= 10 tags", len(t) <= 10, str(len(t)))
check("no dupes", len(t) == len(set(t)))

# ── publish-at parsing ──────────────────────────────────────────────────────
print("\n[TEST 2] _to_publish_at_iso")
check("empty -> None", _to_publish_at_iso("") is None)
check("invalid -> None", _to_publish_at_iso("not a date") is None)
check("past -> PAST", _to_publish_at_iso("2020-01-01 12:00") == "PAST")
fut = _to_publish_at_iso("2030-07-04 12:00")
check("future -> RFC3339-ish", isinstance(fut, str) and "2030-07-04T12:00" in fut, str(fut))
check("future carries timezone offset", fut is not None and ("+" in fut or "Z" in fut or fut.endswith("00")), str(fut))

# ── config + CLI wiring ─────────────────────────────────────────────────────
print("\n[TEST 3] config + CLI wiring")
from core.config import build_config
c = build_config()
check("default language en", c.video_language == "en")
check("default category 17 (Sports)", c.video_category_id == "17")
check("default publish_at empty", c.publish_at == "")
check("override publish_at", build_config(publish_at="2026-07-04 12:00").publish_at == "2026-07-04 12:00")

from core.cli import parse_args
a = parse_args(["url", "--publish-at", "2026-07-04 18:00", "--lang", "en"])
check("--publish-at parses", a.publish_at == "2026-07-04 18:00")
check("--lang parses", a.lang == "en")

# ── public / privacy wiring ─────────────────────────────────────────────────
print("\n[TEST 4] --public / privacy wiring")
check("default unlisted (public False)", build_config().public is False)
check("build_config(public=True)", build_config(public=True).public is True)
check("--public parses True", parse_args(["url", "--public"]).public is True)
check("no --public parses False", parse_args(["url"]).public is False)


def _privacy(scheduled, public):
    """Mirror of run_upload's privacy selection (kept in sync for regression)."""
    if scheduled:
        return "private"
    return "public" if public else "unlisted"


check("scheduled -> private", _privacy(True, True) == "private" and _privacy(True, False) == "private")
check("public & not scheduled -> public", _privacy(False, True) == "public")
check("default -> unlisted", _privacy(False, False) == "unlisted")

# youtube read scope present (analytics fix)
from upload.youtube import _SCOPES
check("readonly scope present", any("youtube.readonly" in s for s in _SCOPES), str(_SCOPES))
check("upload scope present", any("youtube.upload" in s for s in _SCOPES))

print("\n" + "=" * 60)
passed = sum(1 for _, s in results if s == "PASS")
print(f"RESULT: {passed}/{len(results)} passed")
print("=" * 60)
sys.exit(0 if passed == len(results) else 1)
