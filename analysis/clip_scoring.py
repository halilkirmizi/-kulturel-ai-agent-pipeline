"""Window-based clip scoring engine for analytical YouTube Shorts.

Key change from v1:
- Replaces sentence-level scoring with WINDOW-BASED segmentation
- Pre-built overlapping windows (18-30s) are scored, not raw segments
- All durations clamped to 12-35s, expanded to sentence boundaries
- Includes output validation and fallback logic

Usage:
    from analysis.clip_scoring import score_clips
    results = score_clips(segments, config)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.config import PipelineConfig
from core.logger import get_logger

log = get_logger(__name__)


@dataclass
class ScoredClip:
    start: float
    end: float
    duration: float
    hook_text: str
    intro_script: str
    outro_script: str
    reason: str
    scores: Dict[str, float] = field(default_factory=dict)
    score_total: float = 0.0


# ── Constants ──────────────────────────────────
MIN_CLIP = 12
MAX_CLIP = 35
TARGET_WIN = 22
TARGET_WINS = (15, 22, 30)   # multiple candidate lengths so a thought is not forced into one size
WIN_OVERLAP = 7
MAX_WINDOWS = 30             # cap candidate count to keep the prompt bounded
_REQUIRED_SCORE_DIMS = ["curiosity", "emotional_relevance", "educational_value", "narrative_completeness"]


# ── Window building ────────────────────────────


@dataclass
class _Window:
    wid: int
    start: float
    end: float
    text: str


def _window_text(segments: list, start: float, end: float) -> str:
    """Concatenated transcript text for the segments inside [start, end]."""
    parts = []
    for s in segments:
        if s.end <= start:
            continue
        if s.start >= end:
            break
        if s.text and s.text.strip():
            parts.append(s.text.strip())
    return " ".join(parts)


def _build_windows(
    segments: list, targets=TARGET_WINS, overlap: float = WIN_OVERLAP
) -> List[_Window]:
    """Build overlapping candidate windows at MULTIPLE target lengths.

    Generating short/medium/long windows at each position lets the selector
    pick the duration that best fits a complete thought, instead of forcing
    every candidate into one fixed size. Windows snap to segment boundaries,
    duplicates are merged, and the count is capped (MAX_WINDOWS) so the prompt
    stays bounded.
    """
    if not segments:
        return []

    total_dur = max(s.end for s in segments)
    all_starts = sorted({s.start for s in segments})
    all_ends = sorted({s.end for s in segments})

    def _snap_to_start(t: float) -> float:
        for st in reversed(all_starts):
            if st <= t:
                return st
        return all_starts[0]

    def _snap_to_end(t: float) -> float:
        for ed in all_ends:
            if ed >= t:
                return ed
        return all_ends[-1]

    raw: List[Tuple[float, float]] = []
    for target in targets:
        step = max(5.0, target - overlap)
        cur = 0.0
        while cur < total_dur - 2:
            ss = _snap_to_start(cur)
            se = _snap_to_end(min(cur + target, total_dur))
            if se - ss >= MIN_CLIP:
                raw.append((ss, se))
            cur += step

    # Merge duplicate spans (different targets snap to the same bounds).
    seen = set()
    uniq: List[Tuple[float, float]] = []
    for ss, se in sorted(raw):
        key = (round(ss, 1), round(se, 1))
        if key not in seen:
            seen.add(key)
            uniq.append((ss, se))

    # Cap candidate count: subsample evenly across the video if needed.
    if len(uniq) > MAX_WINDOWS:
        idx = sorted({round(i * (len(uniq) - 1) / (MAX_WINDOWS - 1)) for i in range(MAX_WINDOWS)})
        uniq = [uniq[i] for i in idx]

    windows = [_Window(wid=i, start=ss, end=se, text=_window_text(segments, ss, se))
               for i, (ss, se) in enumerate(uniq)]
    log.info("Built %d windows (targets=%s, overlap=%.0fs)", len(windows), tuple(targets), overlap)
    return windows


# ── Sentence boundary expansion ────────────────


def _expand_to_boundaries(start: float, end: float, segments: list) -> Tuple[float, float]:
    """Expand start/end to nearest segment boundaries for clean audio cuts."""
    seg_starts = sorted({s.start for s in segments})
    seg_ends = sorted({s.end for s in segments})

    expanded_start = start
    for st in reversed(seg_starts):
        if st <= start:
            expanded_start = st
            break

    expanded_end = end
    for ed in seg_ends:
        if ed >= end:
            expanded_end = ed
            break

    return expanded_start, expanded_end


# ── Transcript builders ────────────────────────


def _build_transcript_snippet(segments: list, max_chars: int = 30000) -> str:
    """Build timestamped transcript string from all segments."""
    total_dur = max((s.end for s in segments), default=0)
    lines = [f"Total duration: {int(total_dur // 60)}m{total_dur % 60:.0f}s"]
    for s in segments:
        if not s.text.strip():
            continue
        start = f"{int(s.start // 60):02d}:{s.start % 60:05.2f}"
        end = f"{int(s.end // 60):02d}:{s.end % 60:05.2f}"
        lines.append(f"[{start} -> {end}] {s.text.strip()}")
    full = "\n".join(lines)
    if len(full) > max_chars:
        full = full[:max_chars]
        log.warning("Transcript capped at %d chars", max_chars)
    return full


# Openers that usually signal the window starts mid-thought (references unseen context).
_MID_THOUGHT_OPENERS = {
    "and", "but", "so", "because", "which", "that", "this", "these", "those",
    "it", "they", "also", "then", "however", "therefore", "yeah", "ok", "okay",
    "well", "plus", "anyway", "actually", "again", "still", "thus", "hence",
}


def _opens_mid_thought(text: str) -> bool:
    """Heuristic: does this text open by referencing something unseen?"""
    t = (text or "").strip()
    if not t:
        return False
    first = re.split(r"[\s,]+", t, 1)[0].lower().strip(".,!?;:\"'")
    return first in _MID_THOUGHT_OPENERS


def _build_window_listing(
    windows: List[_Window], segments: list, max_chars: int = 15000, rich: bool = True
) -> str:
    """Build a listing of all candidate windows for the LLM prompt.

    rich=True (default): shows each window's FULL text so the model can actually
    judge content quality (the previous preview-only listing made it select
    blind). rich=False keeps the legacy start/end preview behaviour.
    """
    lines = ["=== SCORING CANDIDATES (overlapping windows) ===", ""]
    if rich:
        lines += [
            "Each window shows its FULL text. Read it and judge it on its own merits:",
            "does it stand alone, open with a hook, and finish a complete thought?",
            "A \"!! starts mid-thought\" flag means the opening references unseen context.",
            "",
        ]
    else:
        lines += [
            "Each window shows its start/end segments so you can see if",
            "sentences begin and end cleanly. Prefer windows where the first",
            "and last segments are COMPLETE sentences (not cut off mid-sentence).",
            "",
        ]

    for w in windows:
        start_s = f"{int(w.start // 60):02d}:{w.start % 60:04.1f}"
        end_s = f"{int(w.end // 60):02d}:{w.end % 60:04.1f}"
        flag = "  !! starts mid-thought" if _opens_mid_thought(w.text) else ""
        lines.append(f"WIN-{w.wid:03d} [{start_s} -> {end_s}] ({w.end-w.start:.0f}s){flag}")

        if rich:
            body = (w.text or "").strip().replace("\n", " ")
            if len(body) > 450:
                body = body[:450] + "…"
            lines.append(f'  TEXT: "{body}"')
        else:
            first_segs = [s for s in segments if abs(s.start - w.start) < 0.5]
            last_segs = [s for s in segments if abs(s.end - w.end) < 0.5]
            first_text = first_segs[0].text.strip() if first_segs else "..."
            last_text = last_segs[-1].text.strip() if last_segs else "..."
            lines.append(f"  STARTS WITH: \"{first_text[:80].replace(chr(10), ' ')}...\"")
            lines.append(f"  ENDS WITH:   \"{last_text[:80].replace(chr(10), ' ')}...\"")
        lines.append("")

    full = "\n".join(lines)
    if len(full) > max_chars:
        full = full[:max_chars]
    return full


# ── Validation ─────────────────────────────────


def _validate_clip(start: float, end: float, segments: list) -> Tuple[bool, str]:
    """Validate clip meets all constraints. Returns (ok, reason)."""
    dur = end - start

    if dur < MIN_CLIP:
        return False, f"too short ({dur:.1f}s < {MIN_CLIP}s)"
    if dur > MAX_CLIP:
        return False, f"too long ({dur:.1f}s > {MAX_CLIP}s)"
    if start >= end:
        return False, "start >= end"

    seg_texts = [s.text.strip() for s in segments if s.start >= start and s.end <= end and s.text]
    word_count = sum(len(t.split()) for t in seg_texts)
    if word_count < 5:
        return False, f"only {word_count} words in segment"

    return True, "ok"


# ── Score helpers ──────────────────────────────


def _validate_and_fix_scores(scores: dict) -> dict:
    """Ensure all 4 scoring dimensions exist, default missing to 0."""
    fixed = {}
    for dim in _REQUIRED_SCORE_DIMS:
        val = scores.get(dim)
        if not isinstance(val, (int, float)):
            log.warning("Missing/invalid score '%s', defaulting to 0", dim)
            fixed[dim] = 0.0
        else:
            fixed[dim] = max(0.0, min(10.0, float(val)))
    return fixed


def _parse_llm_json(text: str) -> dict:
    """Parse LLM JSON output safely."""
    json_match = re.search(r"(\{.*\})", text, re.DOTALL)
    clean = json_match.group(1) if json_match else text
    return json.loads(clean)


def _call_claude(config, system_prompt: str, user_prompt: str, client=None) -> dict:
    """Call Anthropic Claude for clip selection; return parsed JSON dict.

    `client` is injectable for testing. Reads ANTHROPIC_API_KEY from env unless
    an explicit key is set in config.
    """
    if client is None:
        import anthropic
        client = (anthropic.Anthropic(api_key=config.anthropic_api_key)
                  if config.anthropic_api_key else anthropic.Anthropic())
    resp = client.messages.create(
        model=config.anthropic_model,
        max_tokens=8000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "".join(
        getattr(b, "text", "") for b in resp.content
        if getattr(b, "type", None) == "text"
    )
    log.info("Claude selection response: %d chars", len(text))
    return _parse_llm_json(text)


def _weighted_total(scores: dict, dim_weights: Optional[dict]) -> float:
    """Sum of dimension scores, optionally re-weighted by learned multipliers.

    With no weights this is the plain sum (unchanged behaviour). Weights are
    bounded multipliers (learning_engine clamps to 0.5..1.5) so a learned bias
    re-ranks clips without dominating.
    """
    if not dim_weights:
        return sum(scores.values())
    return sum(v * float(dim_weights.get(d, 1.0)) for d, v in scores.items())


# ── Overlap dedupe ─────────────────────────────


def _overlap_ratio(a: "ScoredClip", b: "ScoredClip") -> float:
    """Time-overlap of two clips as a fraction of the shorter clip (0..1)."""
    lo = max(a.start, b.start)
    hi = min(a.end, b.end)
    overlap = max(0.0, hi - lo)
    shorter = min(a.end - a.start, b.end - b.start)
    return overlap / shorter if shorter > 0 else 0.0


def _dedupe_overlapping(clips: List["ScoredClip"], max_overlap: float = 0.5) -> List["ScoredClip"]:
    """Drop redundant overlapping clips, keeping the higher-scored one.

    Greedy: take clips by score (desc); accept a clip only if it does not
    overlap an already-accepted clip by more than ``max_overlap``.
    """
    accepted: List["ScoredClip"] = []
    for c in sorted(clips, key=lambda x: x.score_total, reverse=True):
        if all(_overlap_ratio(c, a) <= max_overlap for a in accepted):
            accepted.append(c)
    return accepted


# ── Fallback ───────────────────────────────────


def _fallback_window_score(win: "_Window", segments: list) -> float:
    """Deterministic quality heuristic for a fallback window (no LLM).

    Rewards information density (word count), penalises windows that open
    mid-thought, and prefers durations near TARGET_WIN.
    """
    start, end = _expand_to_boundaries(win.start, win.end, segments)
    words = sum(len(s.text.split()) for s in segments
                if s.start >= start and s.end <= end and s.text.strip())
    score = float(words)
    if _opens_mid_thought(win.text):
        score *= 0.5
    score -= abs((end - start) - TARGET_WIN) * 0.5
    return score


def _fallback_clip(segments: list) -> Optional[ScoredClip]:
    """Fallback when the LLM picks nothing: best candidate window by a
    deterministic density/cleanliness heuristic (not just the longest span)."""
    if not segments:
        return None

    best = None  # (score, start, end)
    for w in _build_windows(segments):
        start, end = _expand_to_boundaries(w.start, w.end, segments)
        ok, _reason = _validate_clip(start, end, segments)
        if not ok:
            continue
        sc = _fallback_window_score(w, segments)
        if best is None or sc > best[0]:
            best = (sc, start, end)

    if best is not None:
        _, b_start, b_end = best
        reason = "Fallback: best window by density"
    else:
        # Last resort: a single bounded span from the start.
        b_start = segments[0].start
        b_end = min(segments[0].start + MAX_CLIP, segments[-1].end)
        reason = "Fallback: opening span"

    return ScoredClip(
        start=b_start,
        end=b_end,
        duration=b_end - b_start,
        hook_text="Highlight",
        intro_script="",
        outro_script="",
        reason=reason,
        scores={"curiosity": 5, "emotional_relevance": 5, "educational_value": 5, "narrative_completeness": 5},
        score_total=20.0,
    )


# ── Main scoring function ──────────────────────


CLIP_SYSTEM_PROMPT = """You are a clip selection engine for YouTube Shorts.
Select the 2-4 BEST windows from the candidate list that work as standalone Shorts.

You are shown each window's FULL text. READ IT — judge content, not just the edges.

A great Short clip:
- Opens with a HOOK in its first sentence (a question, bold claim, or surprising statement).
- Is SELF-CONTAINED: a viewer with ZERO context understands it.
- Has a complete arc (setup -> payoff). It does not stop mid-thought.
- Delivers a specific idea, fact, or story — not filler.

REJECT a window if it:
- Is flagged "!! starts mid-thought", or opens with and/so/but/this/it/that/because...
- References unseen context ("as I mentioned", "like I said", "going back to...").
- Is a greeting, intro, outro, transition, housekeeping, or vague small talk.
- Is an enumeration/list with no payoff.

Scoring criteria (each 0-10):
- curiosity: sparks curiosity or presents a surprising idea?
- emotional_relevance: connects on a human level (anger, awe, wonder)?
- educational_value: specific, factual information density?
- narrative_completeness: stands alone with context + payoff?

Be HARSH: give 7+ ONLY to windows you would personally watch to the end.
Pick diverse moments across the full video (WIN-IDs far apart are better).
Return ONLY valid JSON with this exact structure:
{
  "selections": [
    {
      "window_id": 3,
      "hook_text": "2-4 word attention-grabbing summary that makes people want to watch",
      "intro_script": "5-8 second spoken hook (1-2 sentences to grab attention)",
      "outro_script": "5-10 second closing thought or context",
      "reason": "why this works as a short (max 20 words)",
      "scores": {
        "curiosity": 8,
        "emotional_relevance": 6,
        "educational_value": 9,
        "narrative_completeness": 7
      }
    }
  ]
}
IMPORTANT: Use window_id from the candidate list. Do NOT invent timestamps."""


def score_clips(
    segments: list,
    config: PipelineConfig,
    topics: Optional[List[str]] = None,
    memory_bias: Optional[Dict[str, Any]] = None,
    dim_weights: Optional[Dict[str, float]] = None,
) -> List[ScoredClip]:
    """Run LLM-based clip scoring and selection using window-based segmentation.

    Args:
        segments: Whisper segment list (with .start, .end, .text).
        config: PipelineConfig (API key, model, temperature).
        topics: Optional list of topic keywords.
        memory_bias: Optional dict with failure_history_penalty,
                     success_reinforcement, topic_weighting from
                     MemoryInfluenceEngine.

    Returns:
        List of ScoredClip objects, sorted by total score descending.
    """
    provider = getattr(config, "select_provider", "groq")
    if provider != "claude" and not config.groq_api_key:
        raise ValueError("GROQ_API_KEY not set — cannot run clip scoring")

    if dim_weights:
        log.info("Applying learned dimension weights: %s", dim_weights)

    # Build windows and transcript
    windows = _build_windows(segments)
    if not windows:
        log.warning("No windows could be built from segments")
        fb = _fallback_clip(segments)
        return [fb] if fb else []

    transcript = _build_transcript_snippet(segments, max_chars=config.llm_max_chars)
    window_listing = _build_window_listing(
        windows, segments, max_chars=config.llm_max_chars // 2,
        rich=not getattr(config, "legacy_select", False),
    )

    # Inject memory bias into the prompt
    bias_lines = []
    if memory_bias:
        penalty = memory_bias.get("failure_history_penalty", 0.0)
        reinforcement = memory_bias.get("success_reinforcement", 0.0)
        topic_weights = memory_bias.get("topic_weighting", {})
        if penalty > 0:
            bias_lines.append(f"Failure history penalty: {penalty:.1f} (penalize risky segments)")
        if reinforcement > 0:
            bias_lines.append(f"Success reinforcement: {reinforcement:.1f} (prefer segments similar to past successes)")
        if topic_weights:
            bias_lines.append("Topic weight bias: " + ", ".join(f"{t}={w:.1f}" for t, w in topic_weights.items()))

    user_prompt = f"Full transcript:\n{transcript}\n\n{window_listing}"
    if bias_lines:
        user_prompt = "Memory bias:\n" + "\n".join(bias_lines) + "\n\n" + user_prompt
    if topics:
        user_prompt = (
            f"Key topics in this video: {', '.join(topics[:10])}.\n\n"
            f"{user_prompt}"
        )

    if provider == "claude":
        log.info("Clip selection via Claude (%s)", config.anthropic_model)

        def _call_llm() -> dict:
            return _call_claude(config, CLIP_SYSTEM_PROMPT, user_prompt)
    else:
        from groq import Groq
        client = Groq(api_key=config.groq_api_key)

        def _call_llm() -> dict:
            response = client.chat.completions.create(
                model=config.groq_model,
                messages=[
                    {"role": "system", "content": CLIP_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=config.llm_temperature,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            log.info("LLM response: %d chars", len(raw))
            return _parse_llm_json(raw)

    try:
        analysis = _call_llm()
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("LLM JSON parse failed: %s — retrying once", exc)
        try:
            analysis = _call_llm()
        except (json.JSONDecodeError, ValueError) as exc2:
            raise RuntimeError(f"LLM returned malformed JSON after retry: {exc2}") from exc2

    selections = analysis.get("selections", analysis.get("clips", []))
    if not selections:
        log.warning("LLM returned 0 selections — using fallback")
        fb = _fallback_clip(segments)
        return [fb] if fb else []

    # Map window IDs → windows
    win_map = {w.wid: w for w in windows}

    results: List[ScoredClip] = []
    for sel in selections:
        wid = sel.get("window_id")
        if wid is None:
            log.warning("Selection missing window_id, skipping")
            continue

        win = win_map.get(wid)
        if win is None:
            log.warning("Invalid window_id %s, skipping", wid)
            continue

        start, end = _expand_to_boundaries(win.start, win.end, segments)

        ok, reason = _validate_clip(start, end, segments)
        if not ok:
            log.warning("Skipping WIN-%03d [%.1f-%.1fs]: %s", wid, start, end, reason)
            continue

        scores = _validate_and_fix_scores(sel.get("scores", {}))
        total = _weighted_total(scores, dim_weights)

        sc = ScoredClip(
            start=start,
            end=end,
            duration=end - start,
            hook_text=sel.get("hook_text", ""),
            intro_script=sel.get("intro_script", ""),
            outro_script=sel.get("outro_script", ""),
            reason=sel.get("reason", ""),
            scores=scores,
            score_total=total,
        )
        results.append(sc)

    if not results:
        log.warning("No valid selections after validation — using fallback")
        fb = _fallback_clip(segments)
        if fb:
            results.append(fb)

    # Drop redundant overlapping selections (keeps higher score). Skipped in legacy.
    if not getattr(config, "legacy_select", False) and len(results) > 1:
        before = len(results)
        results = _dedupe_overlapping(results)
        if len(results) < before:
            log.info("Deduped %d overlapping clip(s)", before - len(results))

    results.sort(key=lambda x: x.score_total, reverse=True)

    log.info("Selected %d clips:", len(results))
    for sc in results:
        log.info(
            "  WIN %05.1f-%05.1f  dur=%.1fs  score=%.1f  hook='%s'  reason=%s",
            sc.start, sc.end, sc.duration, sc.score_total, sc.hook_text, sc.reason,
        )

    return results
