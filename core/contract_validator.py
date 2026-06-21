"""Runtime contract validation for pipeline data structures.

Fails loudly on invalid structure — no silent fallbacks, no pass/ignore.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional


class ContractError(Exception):
    """Raised when a runtime contract is violated."""


# ── State.json schema ──────────────────────────────────────────

VALID_STAGES = {
    None,
    "analysis_complete",
    "render",
    "render_complete",
    "render_failed",
    "ready_for_upload",
    "upload",
    "upload_failed",
    "uploaded",
    "upload_blocked",
}

REQUIRED_CLIP_FIELDS = {"start", "end", "hook_text", "score", "metadata"}
REQUIRED_TRANSCRIPT_FIELDS = {"start", "end", "text"}
REQUIRED_METADATA_FIELDS = {"intro_script", "outro_script", "reason", "scores"}
REQUIRED_SCORE_FIELDS = {"curiosity", "emotional_relevance", "educational_value", "narrative_completeness"}


def validate_state(state: Any, source: str = "state.json") -> Dict:
    """Validate complete state.json structure. Returns validated dict on success.

    Raises ContractError on any violation.
    """
    if not isinstance(state, dict):
        raise ContractError(f"{source}: root must be a dict, got {type(state).__name__}")

    # pipeline_stage
    stage = state.get("pipeline_stage")
    if stage is not None and not isinstance(stage, str):
        raise ContractError(f"{source}: pipeline_stage must be string or None, got {type(stage).__name__}")
    if stage not in VALID_STAGES:
        raise ContractError(f"{source}: invalid pipeline_stage {stage!r}")

    # clips
    clips = state.get("clips")
    if clips is not None:
        if not isinstance(clips, list):
            raise ContractError(f"{source}: clips must be a list, got {type(clips).__name__}")
        if len(clips) == 0:
            raise ContractError(f"{source}: clips list is empty")
        for i, clip in enumerate(clips):
            _validate_clip_entry(clip, i, source)

    # transcript
    transcript = state.get("transcript")
    if transcript is not None:
        if not isinstance(transcript, list):
            raise ContractError(f"{source}: transcript must be a list, got {type(transcript).__name__}")
        if len(transcript) == 0:
            raise ContractError(f"{source}: transcript list is empty")
        for i, seg in enumerate(transcript):
            _validate_transcript_segment(seg, i, source)

    return state


def _validate_clip_entry(clip: Any, idx: int, source: str) -> None:
    if not isinstance(clip, dict):
        raise ContractError(f"{source}: clips[{idx}] must be a dict, got {type(clip).__name__}")
    missing = REQUIRED_CLIP_FIELDS - set(clip.keys())
    if missing:
        raise ContractError(f"{source}: clips[{idx}] missing fields: {sorted(missing)}")
    start = clip.get("start")
    end = clip.get("end")
    if not isinstance(start, (int, float)):
        raise ContractError(f"{source}: clips[{idx}].start must be numeric, got {type(start).__name__}")
    if not isinstance(end, (int, float)):
        raise ContractError(f"{source}: clips[{idx}].end must be numeric, got {type(end).__name__}")
    if start >= end:
        raise ContractError(f"{source}: clips[{idx}].start ({start}) >= end ({end})")
    score = clip.get("score")
    if not isinstance(score, (int, float)):
        raise ContractError(f"{source}: clips[{idx}].score must be numeric, got {type(score).__name__}")
    meta = clip.get("metadata", {})
    if not isinstance(meta, dict):
        raise ContractError(f"{source}: clips[{idx}].metadata must be dict, got {type(meta).__name__}")
    _validate_metadata(meta, idx, source)


def _validate_metadata(meta: Dict, clip_idx: int, source: str) -> None:
    missing = REQUIRED_METADATA_FIELDS - set(meta.keys())
    if missing:
        raise ContractError(f"{source}: clips[{clip_idx}].metadata missing: {sorted(missing)}")
    scores = meta.get("scores", {})
    if not isinstance(scores, dict):
        raise ContractError(f"{source}: clips[{clip_idx}].metadata.scores must be dict")
    for dim in REQUIRED_SCORE_FIELDS:
        val = scores.get(dim)
        if not isinstance(val, (int, float)):
            raise ContractError(
                f"{source}: clips[{clip_idx}].metadata.scores.{dim} missing or non-numeric"
            )
        if val < 0 or val > 10:
            raise ContractError(
                f"{source}: clips[{clip_idx}].metadata.scores.{dim}={val} out of range [0,10]"
            )


def _validate_transcript_segment(seg: Any, idx: int, source: str) -> None:
    if not isinstance(seg, dict):
        raise ContractError(f"{source}: transcript[{idx}] must be a dict, got {type(seg).__name__}")
    missing = REQUIRED_TRANSCRIPT_FIELDS - set(seg.keys())
    if missing:
        raise ContractError(f"{source}: transcript[{idx}] missing fields: {sorted(missing)}")
    start = seg.get("start")
    end = seg.get("end")
    if not isinstance(start, (int, float)):
        raise ContractError(f"{source}: transcript[{idx}].start must be numeric")
    if not isinstance(end, (int, float)):
        raise ContractError(f"{source}: transcript[{idx}].end must be numeric")
    if start >= end:
        raise ContractError(f"{source}: transcript[{idx}].start ({start}) >= end ({end})")


# ── ScoredClip output ──────────────────────────────────────────


def validate_scored_clip(clip: Any, idx: int = 0) -> None:
    """Validate a single ScoredClip instance from clip_scoring.py.

    Raises ContractError on violation.
    """
    if not hasattr(clip, "start") or not hasattr(clip, "end"):
        raise ContractError(f"ScoredClip[{idx}]: missing start/end attributes")
    start = float(clip.start)
    end = float(clip.end)
    if start >= end:
        raise ContractError(f"ScoredClip[{idx}]: start ({start}) >= end ({end})")
    dur = end - start
    if dur < 12 or dur > 35:
        raise ContractError(f"ScoredClip[{idx}]: duration {dur:.1f}s out of range [12, 35]")
    if not hasattr(clip, "score_total"):
        raise ContractError(f"ScoredClip[{idx}]: missing score_total")
    total = float(clip.score_total)
    if total < 0 or total > 40:
        raise ContractError(f"ScoredClip[{idx}]: score_total {total} out of range [0, 40]")
    if hasattr(clip, "scores") and clip.scores:
        for dim, val in clip.scores.items():
            if not isinstance(val, (int, float)) or val < 0 or val > 10:
                raise ContractError(f"ScoredClip[{idx}].scores.{dim}={val} out of range [0,10]")


# ── FFmpeg command structure ───────────────────────────────────


def validate_ffmpeg_command(cmd: Any, label: str = "ffmpeg") -> None:
    """Validate that an ffmpeg command is structurally sound.

    Checks:
      - must be a list
      - each element must be a string
      - must contain -i (input)
      - must not end with an option flag
      - must contain -y (overwrite)

    Raises ContractError on violation.
    """
    if not isinstance(cmd, list):
        raise ContractError(f"{label}: command must be a list, got {type(cmd).__name__}")
    if len(cmd) < 3:
        raise ContractError(f"{label}: command too short ({len(cmd)} elements)")
    for i, item in enumerate(cmd):
        if not isinstance(item, str):
            raise ContractError(
                f"{label}: element [{i}] must be str, got {type(item).__name__} ({item!r})"
            )
    if "-i" not in cmd:
        raise ContractError(f"{label}: missing -i (input)")
    last = cmd[-1]
    if last.startswith("-"):
        raise ContractError(f"{label}: last element is a flag ({last!r}), not an output path")
    if cmd[0] == "-y" or "-y" in cmd:
        pass
    else:
        raise ContractError(f"{label}: missing -y (overwrite flag)")


# ── DAG transition validation ──────────────────────────────────


def validate_dag_transition(
    current_stage: Optional[str],
    next_stage: Optional[str],
    clip_dir: Optional[Path] = None,
) -> None:
    """Validate a DAG state transition.

    Raises ContractError on invalid transition.
    """
    valid_transitions = {
        None: "analysis",
        "analysis_complete": "render",
        "render_complete": "upload",
        "render_failed": "render",
        "ready_for_upload": "upload",
        "upload_failed": "upload",
    }
    terminal = {"uploaded"}
    blocked = {"upload_blocked"}

    if current_stage in terminal:
        if next_stage is not None:
            raise ContractError(f"DAG: terminal stage {current_stage!r} cannot transition to {next_stage!r}")
        return

    if current_stage in blocked:
        if next_stage is not None:
            raise ContractError(f"DAG: blocked stage {current_stage!r} cannot transition to {next_stage!r}")
        return

    expected = valid_transitions.get(current_stage)
    if expected is None:
        raise ContractError(f"DAG: unknown stage {current_stage!r}")
    if next_stage != expected:
        raise ContractError(
            f"DAG: invalid transition {current_stage!r} -> {next_stage!r}, "
            f"expected {expected!r}"
        )

    # Validate required artifacts for known transitions
    if current_stage is not None and next_stage is not None:
        required_patterns = {
            ("analysis_complete", "render"): ["state.json", "clip.mp4"],
            ("render_complete", "upload"): ["final.mp4"],
            ("ready_for_upload", "upload"): ["final.mp4"],
        }
        patterns = required_patterns.get((current_stage, next_stage), [])
    else:
        patterns = []
    if clip_dir is not None and patterns:
        for pattern in patterns:
            matches = list(clip_dir.glob(pattern))
            if not matches:
                raise ContractError(
                    f"DAG: {current_stage!r} -> {next_stage!r} requires {pattern!r} "
                    f"in {clip_dir}, not found"
                )
