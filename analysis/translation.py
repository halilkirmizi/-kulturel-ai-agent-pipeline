"""Transcript translation via Groq LLM. Analysis-layer only. No FFmpeg. No rendering."""

from __future__ import annotations

from core.logger import get_logger

log = get_logger(__name__)


def translate_segments(segments, config):
    """Translate segment text to English using Groq LLM."""
    from groq import Groq
    client = Groq(api_key=config.groq_api_key)

    lines = "\n".join(f"[{i}] {s.text}" for i, s in enumerate(segments))
    prompt = (
        "You are a professional sports translator. Translate the following Spanish "
        "interview segments about football (soccer) into natural, CONCISE English suitable for "
        "video subtitles.\n\n"
        "RULES:\n"
        "- Preserve proper nouns EXACTLY: player names (Mbappé, Messi, Ronaldo, etc.),\n"
        "  team names, country names, competition names, stadium names\n"
        "- Translate naturally as a full sentence, NOT word-by-word\n"
        "- Keep translations SHORT and readable (max ~80 chars per line)\n"
        "- Football terminology: 'gol' → 'goal', 'partido' → 'match', 'campeón' → 'champion',\n"
        "  'mundial' → 'World Cup', 'selección' → 'national team',\n"
        "  'arquero/portero' → 'goalkeeper', 'cancha' → 'pitch/field'\n"
        "- If unsure about a proper noun or name, KEEP the original Spanish word\n"
        "- Return one translation per line with the SAME numbering:\n\n"
        + lines
    )
    resp = client.chat.completions.create(
        model=config.groq_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    content = resp.choices[0].message.content or ""
    translated = content.strip().split("\n")
    import re
    from dataclasses import dataclass
    @dataclass
    class Segment:
        start: float
        end: float
        text: str
    new_segs = []
    for seg, line in zip(segments, translated):
        m = re.match(r"^\[\d+\]\s*(.*)", line.strip())
        text = m.group(1) if m else line.strip()
        new_segs.append(Segment(start=seg.start, end=seg.end, text=text))
    log.info("Translated %d segments: %s -> %s", len(segments), segments[0].text[:30] if segments else "", new_segs[0].text[:30] if new_segs else "")
    return new_segs
