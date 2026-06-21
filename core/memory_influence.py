"""Memory Influence Engine — feeds stored signals back into pipeline execution.

Adaptive mode: analyzes memory_store.json entries and produces a
runtime_config_patch that adjusts thresholds, biases, and routing.
Observation-only mode: returns empty patch (no execution influence).

Guards:
  - DAG constraints: never changes step ordering or topology
  - AOR invariants: never changes artifact ownership or single-writer rules
  - Contract validator: never changes data contract validation rules
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.memory_writer import MemoryStore, CAT_FAILURE, CAT_INSIGHT, CAT_INVARIANT


# ── Constants ───────────────────────────────────────────────────

_DEFAULT_SLOW_THRESHOLD = 60.0          # seconds
_DEFAULT_FAILURE_SENSITIVITY = 1.0      # multiplier (1.0 = normal)
_DEFAULT_MAX_RETRIES = 0               # no retries by default
_MAX_FAILURE_PENALTY = 0.3             # cap on failure history penalty
_MAX_SUCCESS_REINFORCEMENT = 0.15      # cap on success reinforcement
_THRESHOLD_ADJUST_FACTOR = 0.8         # 20% reduction per signal


# ── Types ───────────────────────────────────────────────────────

@dataclass
class RuntimeConfigPatch:
    """Patch applied to pipeline runtime configuration.

    All fields are optional — empty values mean "no change".
    Guards ensure this never touches DAG topology, AOR ownership,
    or contract validation rules.
    """
    threshold_adjustments: Dict[str, float] = field(default_factory=dict)
    scoring_bias: Dict[str, Any] = field(default_factory=dict)
    pipeline_routing: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not (self.threshold_adjustments or self.scoring_bias or self.pipeline_routing)

    def __bool__(self) -> bool:
        return not self.is_empty


# ── Behavior hint emission (from MemoryStore) ───────────────────

def threshold_hints_from_store(store: MemoryStore) -> Dict[str, float]:
    """Analyze store entries and return suggested threshold adjustments.

    Returns dict mapping step_name → adjusted_threshold_seconds.

    Looks for:
      - "Slow step: <name> (Ns)" insights → lower threshold by factor
      - Repeated failures on same step → lower threshold further
    """
    hints: Dict[str, float] = {}

    for e in store.entries:
        if e.category == CAT_INSIGHT and e.title.startswith("Slow step:"):
            # Title format: "Slow step: compose (120s)"
            rest = e.title[len("Slow step: "):]
            if " (" in rest:
                step_name = rest.split(" (")[0]
                current = hints.get(step_name, _DEFAULT_SLOW_THRESHOLD)
                hints[step_name] = current * _THRESHOLD_ADJUST_FACTOR

        if e.category == CAT_FAILURE and e.source == "steptracker":
            # Title format: "Step failed: transcribe"
            if e.title.startswith("Step failed: "):
                step_name = e.title[len("Step failed: "):]
                current = hints.get(step_name, _DEFAULT_SLOW_THRESHOLD)
                hints[step_name] = current * (_THRESHOLD_ADJUST_FACTOR ** e.execution_count)

    return hints


def scoring_bias_from_store(store: MemoryStore) -> Dict[str, Any]:
    """Analyze store entries and return scoring bias vector.

    Returns:
      {
        "topic_weighting": {"topic1": 1.2, ...},
        "failure_history_penalty": 0.15,
        "success_reinforcement": 0.05,
      }

    Looks for:
      - Failure count → penalty
      - Insight entries with artifact refs → success reinforcement
      - Repeated invariant violations → topic weighting
    """
    failures = store.by_category(CAT_FAILURE)
    insights = store.by_category(CAT_INSIGHT)
    invariants = store.by_category(CAT_INVARIANT)

    f_count = len(failures)
    penalty = min(_MAX_FAILURE_PENALTY, f_count * 0.05)

    # Success reinforcement: entries that appeared multiple times
    multi_run = [e for e in insights if e.execution_count >= 2]
    reinforcement = min(_MAX_SUCCESS_REINFORCEMENT, len(multi_run) * 0.02)

    # Topic weighting from invariant violations mentioning specific artifacts
    topic_weights: Dict[str, float] = {}
    for inv in invariants:
        for ref in inv.artifact_refs:
            if "transcribe" in ref.lower():
                topic_weights.setdefault("transcription", 1.0)
                topic_weights["transcription"] *= 1.1
            if "score" in ref.lower():
                topic_weights.setdefault("scoring", 1.0)
                topic_weights["scoring"] *= 1.1

    return {
        "topic_weighting": topic_weights,
        "failure_history_penalty": round(penalty, 3),
        "success_reinforcement": round(reinforcement, 3),
    }


def routing_hints_from_store(store: MemoryStore) -> Dict[str, Any]:
    """Analyze store entries and return pipeline routing hints.

    Returns:
      {
        "suggest_retry_delay": False,
        "max_retries": 0,
        "skip_steps_if_healthy": False,
        "failure_sensitivity": 1.0,
      }
    """
    failures = store.by_category(CAT_FAILURE)

    # Count failures in last 24h
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    recent_failures = [f for f in failures if (f.last_seen or f.first_seen) >= cutoff]

    f_sensitivity = _DEFAULT_FAILURE_SENSITIVITY
    max_retries = _DEFAULT_MAX_RETRIES
    suggest_retry_delay = False
    skip_if_healthy = False

    if len(recent_failures) >= 3:
        suggest_retry_delay = True
        max_retries = 1
        f_sensitivity = 1.5
    elif len(recent_failures) >= 1:
        f_sensitivity = 1.2

    # If most recent runs succeeded, suggest skipping redundant checks
    successes = [f for f in failures if f.execution_count >= 3]
    if len(successes) >= 3 and len(recent_failures) == 0:
        skip_if_healthy = True

    return {
        "suggest_retry_delay": suggest_retry_delay,
        "max_retries": max_retries,
        "skip_steps_if_healthy": skip_if_healthy,
        "failure_sensitivity": round(f_sensitivity, 2),
    }


# ── Guards ──────────────────────────────────────────────────────

def enforce_guards(patch: RuntimeConfigPatch) -> RuntimeConfigPatch:
    """Strip any patch fields that would violate system invariants.

    Guard 1 — DAG constraints:
      Only shallow string→float adjustments are allowed.
      No step reordering, no step addition/removal.

    Guard 2 — AOR invariants:
      No artifact ownership changes, no single-writer rule overrides.

    Guard 3 — Contract validator:
      No data contract validation changes.

    Returns sanitized patch (same object, mutated in place).
    """
    # Guard 1: threshold_adjustments must be shallow {str: float}
    sanitized_thresholds = {}
    for step_name, value in patch.threshold_adjustments.items():
        if isinstance(step_name, str) and isinstance(value, (int, float)):
            sanitized_thresholds[step_name] = float(value)
    patch.threshold_adjustments = sanitized_thresholds

    # Guard 2: scoring_bias must only contain safe keys
    SAFE_BIAS_KEYS = {"topic_weighting", "failure_history_penalty", "success_reinforcement"}
    sanitized_bias = {}
    for key, value in patch.scoring_bias.items():
        if key in SAFE_BIAS_KEYS:
            sanitized_bias[key] = value
    patch.scoring_bias = sanitized_bias

    # Guard 3: routing must not include structural changes
    SAFE_ROUTING_KEYS = {
        "suggest_retry_delay", "max_retries",
        "skip_steps_if_healthy", "failure_sensitivity",
    }
    sanitized_routing = {}
    for key, value in patch.pipeline_routing.items():
        if key in SAFE_ROUTING_KEYS:
            sanitized_routing[key] = value
    patch.pipeline_routing = sanitized_routing

    return patch


# ── Engine ──────────────────────────────────────────────────────

class MemoryInfluenceEngine:
    """Reads memory_store.json and produces a runtime_config_patch.

    Two modes:
      - "observation_only": always returns empty patch (no influence).
      - "adaptive_mode": analyzes store entries and adjusts execution.
    """

    def __init__(self, store_path: Path, mode: str = "observation_only") -> None:
        self._mode = mode
        self._store_path = store_path
        self._store: Optional[MemoryStore] = None
        self._last_patch: RuntimeConfigPatch = RuntimeConfigPatch()

        if store_path.exists():
            try:
                self._store = MemoryStore(store_path)
            except Exception as exc:
                print(
                    f"[MEMORY INFLUENCE] WARNING: failed to load store: {exc}",
                    file=sys.stderr,
                )

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def last_patch(self) -> RuntimeConfigPatch:
        return self._last_patch

    @property
    def has_store(self) -> bool:
        return self._store is not None

    def compute_patch(self) -> RuntimeConfigPatch:
        """Analyze store and return a runtime config patch.

        Returns empty patch in observation_only mode.
        Applies guards before returning.
        """
        if self._mode == "observation_only" or not self._store:
            patch = RuntimeConfigPatch()
            self._last_patch = patch
            return patch

        entries = self._store.entries
        if not entries:
            patch = RuntimeConfigPatch()
            self._last_patch = patch
            return patch

        patch = RuntimeConfigPatch(
            threshold_adjustments=threshold_hints_from_store(self._store),
            scoring_bias=scoring_bias_from_store(self._store),
            pipeline_routing=routing_hints_from_store(self._store),
        )

        enforce_guards(patch)
        self._last_patch = patch
        return patch

    def report(self) -> Dict[str, Any]:
        """Return a summary of the current engine state."""
        patch = self._last_patch
        return {
            "mode": self._mode,
            "store_path": str(self._store_path),
            "store_loaded": self._store is not None,
            "patch": {
                "threshold_adjustments": patch.threshold_adjustments,
                "scoring_bias": patch.scoring_bias,
                "pipeline_routing": patch.pipeline_routing,
            },
        }
