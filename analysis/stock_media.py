"""License-safe stock media for news mode.

Pixabay videos (Pixabay License: commercial OK, no attribution) + Wikimedia
Commons photos (CC, real players). A tag-relevance gate rejects off-topic hits
(the search API returns concerts/ocean/tennis for football queries) and a
seen-id set prevents duplicate clips. Network I/O is isolated here; callers get
local file paths.
"""
from __future__ import annotations

import io
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List, Optional

from core.logger import get_logger

log = get_logger(__name__)

_UA = {"User-Agent": "kulturel-ai-agent/1.0 (news mode; stock media fetch)"}
_W, _H = 1080, 1920

# Reject words in tags → clip is off-topic even if the query was football.
_REJECT = {
    "american", "tennis", "basketball", "rugby", "hockey", "cricket", "baseball",
    "volleyball", "handball", "golf", "robot", "cgi", "3d", "render", "animation",
    "cartoon", "ocean", "wave", "sea", "water", "music", "concert", "guitar",
    "dance", "party", "beach", "abstract", "traffic", "gym", "fitness",
}


def _relevant(tags: str, require: List[str]) -> bool:
    """True if tags signal the topic (one of ``require`` substrings) and hit no reject word."""
    parts = [t.strip().lower() for t in tags.split(",")]
    if any(r in tag for tag in parts for r in _REJECT):
        return False
    return any(any(req in tag for req in require) for tag in parts)


def _get(url: str, timeout: int = 60) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=timeout).read()


def fetch_pixabay_videos(
    api_key: str,
    terms: List[str],
    out_dir: Path,
    count: int,
    require: Optional[List[str]] = None,
) -> List[Path]:
    """Download up to ``count`` unique, relevance-filtered stock videos.

    Iterates ``terms`` in order, taking the first non-AI, non-lowquality,
    tag-relevant, not-yet-seen hit per term. Returns saved file paths.
    """
    require = require or ["soccer", "football", "stadium", "pitch"]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    seen: set = set()
    saved: List[Path] = []
    for term in terms:
        if len(saved) >= count:
            break
        try:
            url = "https://pixabay.com/api/videos/?" + urllib.parse.urlencode(
                {"key": api_key, "q": term, "per_page": 20, "safesearch": "true"})
            data = json.loads(_get(url, timeout=30))
        except Exception as exc:
            log.warning("[stock] pixabay query '%s' failed: %s", term, exc)
            continue
        hit = None
        for h in data.get("hits", []):
            if h.get("isAiGenerated") or h.get("isLowQuality") or h["id"] in seen:
                continue
            if not _relevant(h.get("tags", ""), require):
                continue
            hit = h
            break
        if not hit:
            log.info("[stock] no new relevant clip for '%s'", term)
            continue
        seen.add(hit["id"])
        v = hit["videos"].get("medium") or hit["videos"].get("small")
        dest = out_dir / f"v{len(saved) + 1:02d}.mp4"
        try:
            dest.write_bytes(_get(v["url"]))
        except Exception as exc:
            log.warning("[stock] download failed for '%s': %s", term, exc)
            continue
        saved.append(dest)
        log.info("[stock] '%s' -> %s (%dx%d) tags[%s]",
                 term, dest.name, v["width"], v["height"], hit["tags"][:40])
    return saved


def fetch_wikimedia_photo(title: str, dest: Path) -> Optional[Path]:
    """Download a CC photo for ``title`` (e.g. a player) and cover-crop to 1080x1920.

    Returns the path, or None on failure (caller degrades gracefully).
    """
    try:
        from PIL import Image
    except Exception:
        log.warning("[stock] Pillow missing — cannot fetch photos")
        return None
    try:
        # redirects=1 follows accent-dropped titles ("Kylian Mbappe" -> "Kylian Mbappé");
        # thumbnail is the fallback when a page has no 'original' image.
        api = ("https://en.wikipedia.org/w/api.php?action=query&redirects=1&titles="
               + urllib.parse.quote(title)
               + "&prop=pageimages&piprop=original|thumbnail&pithumbsize=1200&format=json")
        data = json.loads(_get(api, timeout=30))
        page = next(iter(data["query"]["pages"].values()))
        info = page.get("original") or page.get("thumbnail")
        if not info:
            log.warning("[stock] no image on Wikipedia page for '%s'", title)
            return None
        src = info["source"]
        img = Image.open(io.BytesIO(_get(src, timeout=30))).convert("RGB")
        iw, ih = img.size
        s = max(_W / iw, _H / ih)
        img = img.resize((int(iw * s) + 1, int(ih * s) + 1), Image.LANCZOS)
        iw, ih = img.size
        left, top = (iw - _W) // 2, (ih - _H) // 2
        img = img.crop((left, top, left + _W, top + _H))
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, quality=90)
        log.info("[stock] photo '%s' -> %s", title, dest.name)
        return dest
    except Exception as exc:
        log.warning("[stock] wikimedia photo '%s' failed: %s", title, exc)
        return None
