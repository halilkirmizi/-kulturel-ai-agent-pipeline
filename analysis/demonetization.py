"""Demonetization risk estimator (pure, deterministic — no LLM, no I/O).

Runs at the end of the pipeline (after production, before feedback/memory) so we
know a clip's likelihood of being demonetized / age-restricted / limited-ads
BEFORE uploading. Scores the spoken text (+ title) against YouTube
advertiser-friendly guideline categories.

Design notes:
- Deterministic word/phrase matching with word boundaries (case-insensitive).
- Football-metaphor words ("kill", "attack", "shoot", "war", "death", "beat")
  are intentionally EXCLUDED — they dominate sports punditry and would produce
  constant false positives. Only unambiguous risk terms are listed.
- Probabilistic OR combination so multiple categories accumulate but stay in 0..1.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

# category -> (max_contribution, per_hit_saturation, [terms])
# max_contribution: ceiling this category can push the risk toward (0..1)
# per_hit_saturation: how fast repeated hits saturate that ceiling
_CATEGORIES: Dict[str, Tuple[float, float, List[str]]] = {
    "hate_slur": (0.95, 0.85, [
        "n1gger", "n1gga", "faggot", "f4ggot", "retard", "tranny", "spastic", "paki",
    ]),
    "profanity_strong": (0.75, 0.55, [
        "fuck", "fucking", "fucker", "motherfucker", "cunt", "wanker",
    ]),
    "adult_sexual": (0.70, 0.50, [
        "porn", "pornography", "nude", "naked", "masturbat", "orgasm", "horny",
        "blowjob", "boobs", "titties",
    ]),
    "graphic_violence": (0.60, 0.45, [
        "massacre", "genocide", "beheading", "decapitat", "mutilat", "gore",
        "terrorist", "terrorism", "stabbing", "gunman", "mass shooting", "rape",
    ]),
    "sensitive_tragedy": (0.60, 0.45, [
        "suicide", "self-harm", "self harm", "overdose", "molest", "pedophile",
    ]),
    "gambling": (0.40, 0.40, [
        "gambling", "casino", "bookmaker", "betting site", "free bet", "wager",
    ]),
    "profanity_mild": (0.30, 0.25, [
        "shit", "bullshit", "asshole", "arsehole", "bitch", "bastard", "dickhead",
        "prick", "piss", "twat", "bollocks",
    ]),
}

# Content ID / copyrighted-music risk when external (non-cleared) music is mixed in.
_EXTERNAL_MUSIC_CONTRIBUTION = 0.50

_LEVEL_THRESHOLDS = (0.25, 0.55)  # < .25 LOW, < .55 MEDIUM, else HIGH


@dataclass
class DemonetizationResult:
    risk_score: float
    risk_level: str
    flags: List[dict] = field(default_factory=list)   # {category, terms, count, contribution}
    notes: List[str] = field(default_factory=list)


def _count_terms(text_low: str, terms: List[str]) -> Tuple[int, List[str]]:
    """Count word-boundary matches of any term. Returns (total_hits, matched_terms)."""
    total = 0
    matched: List[str] = []
    for term in terms:
        # phrase (has space) -> substring on word boundary; single word -> \b match
        pat = r"\b" + re.escape(term).replace(r"\ ", r"\s+") + r"\b"
        n = len(re.findall(pat, text_low))
        if n:
            total += n
            matched.append(term)
    return total, matched


def _contribution(count: int, ceiling: float, saturation: float) -> float:
    """Saturating contribution for a category: 1 hit -> saturation*ceiling, more -> approaches ceiling."""
    if count <= 0:
        return 0.0
    return ceiling * (1.0 - (1.0 - saturation) ** count)


def _level(score: float) -> str:
    lo, hi = _LEVEL_THRESHOLDS
    if score < lo:
        return "LOW"
    if score < hi:
        return "MEDIUM"
    return "HIGH"


def assess_demonetization(
    text: str,
    title: str = "",
    early_text: str = "",
    has_external_music: bool = False,
) -> DemonetizationResult:
    """Estimate demonetization likelihood for a produced clip.

    Args:
        text: full spoken text of the clip.
        title: YouTube title (weighted the same as body; scanned together).
        early_text: text from the first ~8 seconds (strong hits here are worse
            per YouTube's "first 7 seconds" profanity rule) -> small boost.
        has_external_music: True if non-cleared/copyrighted music was mixed in
            (Content ID claim risk).

    Returns:
        DemonetizationResult(risk_score, risk_level, flags, notes).
    """
    body_low = f"{text or ''} {title or ''}".lower()
    early_low = (early_text or "").lower()

    flags: List[dict] = []
    contributions: List[float] = []

    for cat, (ceiling, saturation, terms) in _CATEGORIES.items():
        count, matched = _count_terms(body_low, terms)
        if count:
            contrib = _contribution(count, ceiling, saturation)
            contributions.append(contrib)
            flags.append({
                "category": cat,
                "terms": matched,
                "count": count,
                "contribution": round(contrib, 3),
            })

    notes: List[str] = []
    if has_external_music:
        contributions.append(_EXTERNAL_MUSIC_CONTRIBUTION)
        flags.append({
            "category": "content_id_music",
            "terms": ["external_music"],
            "count": 1,
            "contribution": _EXTERNAL_MUSIC_CONTRIBUTION,
        })
        notes.append("External music mixed in — Content ID claim may divert or block monetization.")

    # early strong profanity / slur -> small additive boost (first-7-seconds rule)
    early_boost = 0.0
    if early_low:
        for cat in ("hate_slur", "profanity_strong"):
            ceiling, saturation, terms = _CATEGORIES[cat]
            n, _ = _count_terms(early_low, terms)
            if n:
                early_boost = 0.15
                notes.append("Strong language in the first seconds — YouTube weights early profanity heavily.")
                break

    # probabilistic OR combine, then apply early boost (capped at 1.0)
    prod = 1.0
    for c in contributions:
        prod *= (1.0 - max(0.0, min(1.0, c)))
    score = 1.0 - prod
    score = min(1.0, score + early_boost)

    # sort flags by contribution desc for readability
    flags.sort(key=lambda f: f["contribution"], reverse=True)

    if not flags:
        notes.append("No advertiser-unfriendly signals detected in speech or title.")

    return DemonetizationResult(
        risk_score=round(score, 3),
        risk_level=_level(score),
        flags=flags,
        notes=notes,
    )


def format_report(result: DemonetizationResult, label: str = "") -> str:
    """Human-readable one-block report for logging at pipeline end."""
    head = f"DEMONETIZATION RISK: {result.risk_level} (score={result.risk_score:.2f})"
    if label:
        head += f"  [{label}]"
    lines = [head]
    if result.flags:
        for f in result.flags:
            terms = ", ".join(f["terms"][:6])
            lines.append(f"  - {f['category']}: {f['count']} hit(s) [{terms}] (+{f['contribution']:.2f})")
    for n in result.notes:
        lines.append(f"  · {n}")
    return "\n".join(lines)
