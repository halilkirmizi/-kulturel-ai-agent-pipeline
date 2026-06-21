"""Step Execution Tracker — strict gating layer.

Each step records explicit status, verification, artifacts, and duration.
No implicit completion allowed. Tracks independently from state.json.
Survives process restart via JSON persistence in log_dir.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.artifact_registry import AOR


@dataclass
class StepRecord:
    step_id: int
    name: str
    status: str  # "executed" | "partial" | "failed" | "skipped"
    verified: bool
    artifacts: List[str]
    notes: str
    timestamp: str  # ISO-8601 when record was last updated
    duration_seconds: Optional[float] = None


class StepTracker:
    """Deterministic step execution gating, persists across restarts.

    Gating is enforced BEFORE creating a new step record.
    If previous step is not executed+verified, begin() raises.
    Step history is saved to execution_trace.json after every mutation,
    and restored on init if the file exists — enabling cross-run gating.

    Supports optional memory influence: threshold_adjustments and
    failure_sensitivity from MemoryInfluenceEngine are applied when
    `apply_influence()` is called after init.

    Usage:
        tracker = StepTracker(log_dir)
        tracker.apply_influence(patch)  # optional, before gate()
        tracker.gate()                   # raises if previous step failed
        sid = tracker.begin("download")
        # ... do work ...
        tracker.complete(sid, artifacts=["video.mp4"])
    """

    def __init__(self, log_dir: Path) -> None:
        self._log_dir = Path(log_dir)
        self._loaded_from_disk = False
        self._log_dir.mkdir(parents=True, exist_ok=True)
        run_id = os.getenv("RUN_ID")
        if not run_id:
            run_id = str(uuid.uuid4())
        self._path = self._log_dir / f"execution_trace_{run_id}.json"
        self._steps: List[StepRecord] = []
        self._clean_orphan_tmp()
        self._load()

        # Memory influence fields — set via apply_influence()
        self._threshold_adjustments: Dict[str, float] = {}
        self._failure_sensitivity: float = 1.0
        self._max_retries: int = 0

    # ── Public API ────────────────────────────────────────────

    def gate(self) -> None:
        """Raise RuntimeError if previous step did not complete successfully.

        Called BEFORE begin(). This is the gating mechanism — if this raises,
        no new step record is created and execution stops.
        """
        last = self.last
        if last is not None and last.verified is not True:
            raise RuntimeError(
                f"Step gating blocked: step {last.step_id} '{last.name}' "
                f"status={last.status!r} verified={last.verified}"
            )

    def apply_influence(self, patch: Any = None) -> None:
        """Apply memory influence patch to step tracking thresholds.

        Reads threshold_adjustments and failure_sensitivity from the
        patch and stores them for use during gate() / complete() / fail().

        Args:
            patch: RuntimeConfigPatch, UnifiedRuntimeConfig, or a plain dict
                   with threshold_adjustments, scoring_bias, pipeline_routing keys.
                   If None, resets to defaults.
        """
        if patch is None:
            self._threshold_adjustments = {}
            self._failure_sensitivity = 1.0
            self._max_retries = 0
            return

        if isinstance(patch, dict):
            self._threshold_adjustments = patch.get("threshold_adjustments", {})
            routing = patch.get("pipeline_routing", {})
        else:
            self._threshold_adjustments = getattr(patch, "threshold_adjustments", {})
            routing = getattr(patch, "pipeline_routing", {})
        self._failure_sensitivity = routing.get("failure_sensitivity", 1.0)
        self._max_retries = routing.get("max_retries", 0)

    def get_adjusted_threshold(self, step_name: str, default: float = 60.0) -> float:
        """Return the memory-adjusted slow-step threshold for a step."""
        return self._threshold_adjustments.get(step_name, default)

    def heuristic_adjustments(self) -> Dict[str, float]:
        """Return threshold suggestions based on local step trace.

        Analyzes completed steps in the current session and suggests
        adjusted thresholds for future runs.

        Returns:
            {step_name: suggested_threshold_seconds}
        """
        suggestions: Dict[str, float] = {}
        for s in self._steps:
            if s.status == "executed" and s.duration_seconds is not None:
                if s.duration_seconds > 60:
                    name = s.name
                    current = suggestions.get(name, 60.0)
                    suggestions[name] = round(current * 0.85, 1)
                elif s.duration_seconds < 10 and s.verified:
                    name = s.name
                    current = suggestions.get(name, 60.0)
                    suggestions[name] = round(current * 1.1, 1)
        return suggestions

    def begin(self, name: str) -> int:
        """Open a new step. Returns step_id (1-indexed).

        Does NOT gate — call gate() before begin() to enforce gating.
        """
        sid = len(self._steps) + 1
        record = StepRecord(
            step_id=sid,
            name=name,
            status="partial",
            verified=False,
            artifacts=[],
            notes="started",
            timestamp=_now(),
        )
        self._steps.append(record)
        self._save()
        return sid

    def complete(
        self,
        step_id: int,
        artifacts: Optional[List[str]] = None,
        notes: str = "",
    ) -> None:
        """Mark step as fully executed and verified."""
        self._update(
            step_id,
            status="executed",
            verified=True,
            artifacts=artifacts or [],
            notes=notes or "completed",
        )

    def fail(self, step_id: int, reason: str = "") -> None:
        """Mark step as failed (verified=False)."""
        self._update(step_id, status="failed", verified=False, notes=reason or "failed")

    # ── Queries ───────────────────────────────────────────────

    @property
    def last(self) -> Optional[StepRecord]:
        return self._steps[-1] if self._steps else None

    @property
    def can_proceed(self) -> bool:
        """Read-only check: would gate() raise?"""
        try:
            self.gate()
            return True
        except RuntimeError:
            return False

    @property
    def resumed(self) -> bool:
        """True if steps were loaded from disk (i.e. this is a resumed run)."""
        return self._loaded_from_disk

    @property
    def step_count(self) -> int:
        return len(self._steps)

    # ── Report ────────────────────────────────────────────────

    def report(self) -> Dict:
        """Full execution trace with duration and aggregate stats."""
        durations: List[float] = []
        for s in self._steps:
            if s.duration_seconds is not None:
                durations.append(s.duration_seconds)

        counts: Dict[str, int] = {"executed": 0, "failed": 0, "partial": 0, "skipped": 0}
        for s in self._steps:
            counts[s.status] = counts.get(s.status, 0) + 1

        return {
            "pipeline": "execution_trace",
            "step_count": len(self._steps),
            "gate_status": "blocked" if not self.can_proceed else "open",
            "summary": {
                "total": len(self._steps),
                "executed": counts["executed"],
                "failed": counts["failed"],
                "partial": counts["partial"],
                "skipped": counts["skipped"],
            },
            "duration": {
                "total_seconds": round(sum(durations), 3) if durations else None,
                "per_step": [round(d, 3) for d in durations] if durations else [],
            },
            "failed_path": [
                asdict(s) for s in self._steps if s.status == "failed"
            ],
            "partial_transitions": [
                asdict(s) for s in self._steps if s.status == "partial"
            ],
            "skipped_steps": [
                asdict(s) for s in self._steps if s.status == "skipped"
            ],
            "steps": [asdict(s) for s in self._steps],
        }

    def summary(self) -> str:
        """One-liner for log output."""
        r = self.report()["summary"]
        g = self.report()["gate_status"]
        parts = [
            f"steps: {r['executed']}/{r['total']} ok",
            f"f:{r['failed']} p:{r['partial']} s:{r['skipped']}",
        ]
        if g == "blocked":
            parts.append("BLOCKED")
        return " | ".join(parts)

    # ── Internal ──────────────────────────────────────────────

    def _clean_orphan_tmp(self) -> None:
        """Remove orphan .tmp.json from a previously crashed save()."""
        tmp = self._path.with_suffix(".tmp.json")
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception as exc:
                self._warn("cleanup", f"could not remove orphan {tmp.name}: {exc}")

    def _warn(self, context: str, message: str) -> None:
        """Write a warning to stderr. No external dependencies."""
        print(
            f"[steptracker] WARNING: {context}: {message}",
            file=sys.stderr,
            flush=True,
        )

    def _update(self, step_id: int, **kwargs) -> None:
        now_ts = _now()
        for s in self._steps:
            if s.step_id == step_id:
                # Compute duration from the step's original timestamp
                if s.duration_seconds is None:
                    try:
                        start = datetime.fromisoformat(s.timestamp)
                        end = datetime.fromisoformat(now_ts)
                        s.duration_seconds = (end - start).total_seconds()
                    except Exception as exc:
                        self._warn("_update.duration", str(exc))
                        s.duration_seconds = 0.0
                for k, v in kwargs.items():
                    setattr(s, k, v)
                s.timestamp = now_ts
                self._save()
                return
        raise ValueError(f"Step {step_id} not found")

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            raw_steps = raw.get("steps", [])
            if not isinstance(raw_steps, list):
                raise ValueError("corrupt trace: 'steps' is not a list")
            self._steps = [StepRecord(**s) for s in raw_steps]
            self._loaded_from_disk = True
        except Exception as exc:
            self._warn("_load", str(exc))
            self._steps = []

    def _save(self) -> None:
        data = {"steps": [asdict(s) for s in self._steps]}
        tmp = self._path.with_suffix(".tmp.json")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            tmp.replace(self._path)
        except Exception as exc:
            self._warn("_save.rename", str(exc))
            raise
        AOR.register_write("execution_trace", self._path, __name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
