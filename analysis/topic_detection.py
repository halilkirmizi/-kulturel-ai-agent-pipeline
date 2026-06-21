"""Topic detection from transcript.

Identifies key topics, themes, and named entities from a transcript
to guide clip scoring toward information-rich segments.

Usage:
    from analysis.topic_detection import extract_topics
    topics = extract_topics(transcript_text)
"""

from __future__ import annotations

import re
from collections import Counter
from typing import List


# Common filler words to exclude from topic extraction
_FILLER = {
    "yeah", "like", "well", "just", "actually", "basically", "really",
    "right", "okay", "so", "um", "uh", "ah", "you know", "i mean",
    "sort of", "kind of", "thing", "things", "stuff",
}


def extract_topics(text: str, top_n: int = 20) -> List[str]:
    """Extract significant topic keywords from transcript text.

    Uses simple frequency + TF heuristic. For production, swap with
    a proper NER/keyword extraction model.

    Args:
        text: Plain transcript text (timestamps stripped).
        top_n: Number of top keywords to return.

    Returns:
        List of topic keywords, most significant first.
    """
    cleaned = re.sub(r"\[\d+:\d+.*?\]", "", text)
    cleaned = cleaned.lower()
    cleaned = re.sub(r"[^a-z0-9\s'-]", "", cleaned)

    words = cleaned.split()
    words = [w.strip("'") for w in words if len(w.strip("'")) > 3 and w.strip("'") not in _FILLER]

    freq = Counter(words)
    return [word for word, _ in freq.most_common(top_n)]
