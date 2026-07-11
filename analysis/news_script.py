"""LLM news-script generation for news mode.

Turns a topic into an original, punchy ~20-25s narration plus a visual plan
(ordered stock-video queries + real-player photo subjects) and sensational
YouTube metadata. Original commentary (not copied) keeps it clear of the
reused-content demonetization policy.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from core.logger import get_logger

log = get_logger(__name__)

_SYSTEM = """You are a viral sports-news Shorts writer. Given a football topic, \
write an ORIGINAL, punchy voiceover script for a 20-25 second vertical Short, \
plus a visual plan and YouTube metadata.

STRICT OUTPUT: a single JSON object, no prose, with keys:
- "narration": string. MUST be 60-80 words — this is critical: a 22-28 second \
Short needs 60-80 spoken words, a 23-word script is far too short and will be \
rejected. Spoken news style: a strong hook first line, then 3-4 sentences of key \
facts and context, then a provocative closing question. Natural to read aloud. \
Do NOT invent facts beyond the topic given. No hashtags inside narration.
- "visuals": array of 8-11 objects, ORDERED to follow the narration beat by beat. \
Each is either {"type":"photo","subject":"<real player full name>"} for a specific \
person mentioned, or {"type":"video","query":"<2-4 word football b-roll search>"} \
for scene shots. Use photo for named players; video for stadium/crowd/goal/pitch/ \
celebration/training shots. Vary the video queries. First visual should be a strong \
scene shot, not a photo.
- "title": string <=90 chars. Sensational, curiosity/'?' or bold caps hook, 1-2 emoji.
- "description": string. 1-2 sentences + a line of 5-7 hashtags.
- "tags": array of 8-10 short YouTube tags.

Keep video queries clearly soccer (e.g. "soccer stadium aerial", "football goal net", \
"soccer crowd fans", "football celebration"). Avoid ambiguous words like "slow motion" \
or "celebration party" that return non-football stock."""


def generate_news_script(topic: str, config) -> Dict[str, Any]:
    """Generate the news script + visual plan + metadata for ``topic``.

    Returns a validated dict. Raises RuntimeError if the LLM/JSON fails.
    """
    if not config.groq_api_key:
        raise RuntimeError("GROQ_API_KEY required for news script generation")
    from groq import Groq

    client = Groq(api_key=config.groq_api_key)

    def _ask(extra: str = "") -> dict:
        resp = client.chat.completions.create(
            model=config.groq_model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"Topic: {topic}{extra}"},
            ],
            temperature=0.7,
            response_format={"type": "json_object"},
        )
        return json.loads(resp.choices[0].message.content or "{}")

    try:
        data = _ask()
        # one retry if the model under-wrote the narration (too short = bad Short)
        if len((data.get("narration") or "").split()) < 45:
            log.info("[news] narration too short (%d words) — retrying",
                     len((data.get("narration") or "").split()))
            data = _ask("\n\nIMPORTANT: your narration MUST be 60-80 words. Write the "
                        "full 3-4 sentences plus hook and closing question.")
    except Exception as exc:
        raise RuntimeError(f"news script generation failed: {exc}")

    # ---- validate / normalize ----
    narration = (data.get("narration") or "").strip()
    visuals = data.get("visuals") or []
    if not narration or not visuals:
        raise RuntimeError("news script missing narration or visuals")
    clean_visuals = []
    for v in visuals:
        if not isinstance(v, dict):
            continue
        if v.get("type") == "photo" and v.get("subject"):
            clean_visuals.append({"type": "photo", "subject": str(v["subject"]).strip()})
        elif v.get("type") == "video" and v.get("query"):
            clean_visuals.append({"type": "video", "query": str(v["query"]).strip()})
    if len(clean_visuals) < 4:
        raise RuntimeError(f"news script has too few valid visuals ({len(clean_visuals)})")

    out = {
        "narration": narration,
        "visuals": clean_visuals,
        "title": (data.get("title") or topic).strip()[:100],
        "description": (data.get("description") or "").strip()[:5000],
        "tags": [str(t).strip() for t in (data.get("tags") or []) if str(t).strip()][:10],
    }
    log.info("[news] script: %d words, %d visuals, title=%r",
             len(narration.split()), len(clean_visuals), out["title"][:50])
    return out
