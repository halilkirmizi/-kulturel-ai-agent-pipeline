"""State layer — read/write state.json with strict schema validation.

No business logic. No execution. Pure declarative state management.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.artifact_registry import AOR


SCHEMA_VERSION = 1

REQUIRED_CLIP_FIELDS = {"start", "end", "hook_text", "score", "metadata"}
REQUIRED_TRANSCRIPT_FIELDS = {"start", "end", "text"}


class StateError(Exception):
    """Raised when state.json validation fails."""


def _validate(state: dict, path: Path) -> None:
    if not isinstance(state, dict):
        raise StateError(f"state.json: root must be object, got {type(state).__name__}")

    if state.get("version") != SCHEMA_VERSION:
        raise StateError(f"state.json: version mismatch (got {state.get('version')}, expected {SCHEMA_VERSION})")

    if not state.get("immutable"):
        raise StateError("state.json: immutable flag must be true")

    stage = state.get("pipeline_stage")
    if not isinstance(stage, str) or not stage:
        raise StateError(f"state.json: pipeline_stage must be non-empty string, got {stage!r}")

    clips = state.get("clips")
    if not isinstance(clips, list):
        raise StateError(f"state.json: clips must be array, got {type(clips).__name__}")
    if len(clips) == 0:
        raise StateError("state.json: clips array is empty")
    for i, clip in enumerate(clips):
        missing = REQUIRED_CLIP_FIELDS - set(clip.keys())
        if missing:
            raise StateError(f"state.json: clips[{i}] missing fields: {missing}")

    transcript = state.get("transcript")
    if not isinstance(transcript, list):
        raise StateError(f"state.json: transcript must be array, got {type(transcript).__name__}")
    if len(transcript) == 0:
        raise StateError("state.json: transcript is empty")
    for i, seg in enumerate(transcript):
        missing = REQUIRED_TRANSCRIPT_FIELDS - set(seg.keys())
        if missing:
            raise StateError(f"state.json: transcript[{i}] missing fields: {missing}")


def read_state(path: Path) -> dict:
    """Read and validate state.json. Raises StateError on any failure."""
    if not path.exists():
        raise StateError(f"state.json not found: {path}")

    try:
        raw = path.read_text(encoding="utf-8")
        state = json.loads(raw)
    except json.JSONDecodeError as e:
        raise StateError(f"state.json: invalid JSON — {e}") from e

    _validate(state, path)
    AOR.register_read("state_json", path, __name__)
    return state


def write_state(path: Path, data: dict) -> None:
    """Write state.json atomically with version, immutable and timestamp set."""
    data["version"] = SCHEMA_VERSION
    data["immutable"] = True
    data["updated_at"] = datetime.now(timezone.utc).isoformat()

    content = json.dumps(data, indent=2, ensure_ascii=False)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
    AOR.register_write("state_json", path, __name__)
