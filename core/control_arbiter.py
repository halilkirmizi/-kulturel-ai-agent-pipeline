"""Global Control Arbitration Layer — resolves conflicts between all runtime
influence sources and produces a unified, normalized runtime config.

Priority order (1 = highest, never overridden):
  1. DAG / ContractValidator (hard constraints)
  2. Safety guards (AOR invariants)
  3. MemoryInfluenceEngine (adaptive layer)
  4. StepTracker heuristics (local trace)
  5. ClipScoring bias (weakest)

Every resolved value carries provenance: which layer proposed what,
which layer won, and why.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ── Threshold bounds per step type ──────────────────────────────

_STEP_THRESHOLD_BOUNDS: Dict[str, Tuple[float, float]] = {
    "download_video": (15.0, 120.0),
    "transcribe":     (10.0, 120.0),
    "clip_scoring":   (5.0, 60.0),
    "compose":        (10.0, 180.0),
    "phase_1":        (30.0, 600.0),
    "phase_2":        (30.0, 600.0),
}
_DEFAULT_THRESHOLD_BOUNDS = (5.0, 300.0)
_BIAS_CLAMP = (-0.5, 0.5)

# Priority labels (1 = highest)
_LAYER_PRIORITY = {
    "dag_contract":     1,
    "aor_invariant":    2,
    "memory_influence": 3,
    "steptracker":      4,
    "clip_scoring":     5,
}


# ── Types ───────────────────────────────────────────────────────

@dataclass
class ResolvedValue:
    """A single resolved configuration value with provenance."""
    value: Any
    source: str          # which layer won
    reason: str          # why this value was chosen
    candidates: Dict[str, Any] = field(default_factory=dict)  # layer → proposed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "source": self.source,
            "reason": self.reason,
            "candidates": dict(self.candidates),
        }


@dataclass
class UnifiedRuntimeConfig:
    """Final runtime configuration after arbitration.

    Every field carries provenance via ResolvedValue.
    """
    threshold_adjustments: Dict[str, ResolvedValue] = field(default_factory=dict)
    scoring_bias: Dict[str, ResolvedValue] = field(default_factory=dict)
    pipeline_routing: Dict[str, ResolvedValue] = field(default_factory=dict)

    def to_flat_dict(self) -> Dict[str, Any]:
        """Return plain {key: value} for direct consumption by pipeline modules."""
        flat: Dict[str, Any] = {}
        if self.threshold_adjustments:
            flat["threshold_adjustments"] = {
                k: v.value for k, v in self.threshold_adjustments.items()
            }
        if self.scoring_bias:
            flat["scoring_bias"] = {
                k: v.value for k, v in self.scoring_bias.items()
            }
        if self.pipeline_routing:
            flat["pipeline_routing"] = {
                k: v.value for k, v in self.pipeline_routing.items()
            }
        return flat


@dataclass
class ArbitrationInput:
    """All inputs to the arbitration process."""
    # Layer 3: MemoryInfluenceEngine
    memory_threshold_adjustments: Dict[str, float] = field(default_factory=dict)
    memory_scoring_bias: Dict[str, Any] = field(default_factory=dict)
    memory_routing: Dict[str, Any] = field(default_factory=dict)

    # Layer 4: StepTracker heuristics (from local trace)
    step_threshold_adjustments: Dict[str, float] = field(default_factory=dict)

    # Layer 5: Clip scoring feedback
    clip_scoring_bias: Dict[str, Any] = field(default_factory=dict)


# ── Arbiter ─────────────────────────────────────────────────────

class ControlArbiter:
    """Resolves conflicts between runtime influence sources.

    Usage:
        arbiter = ControlArbiter(trace_enabled=True)
        unified = arbiter.resolve(input_data)
        flat = unified.to_flat_dict()
        arbiter.print_trace()  # if trace_enabled
    """

    def __init__(self, trace_enabled: bool = False) -> None:
        self._trace_enabled = trace_enabled
        self._trace: List[Dict[str, Any]] = []
        self._last_unified: Optional[UnifiedRuntimeConfig] = None

    @property
    def trace_enabled(self) -> bool:
        return self._trace_enabled

    @trace_enabled.setter
    def trace_enabled(self, value: bool) -> None:
        self._trace_enabled = value

    # ── Resolution ─────────────────────────────────────────────

    def resolve(self, inp: ArbitrationInput) -> UnifiedRuntimeConfig:
        """Resolve all inputs into a unified runtime config.

        Priority: DAG/Contract > AOR > Memory > StepTracker > ClipScoring
        Each field type uses its own resolution strategy.
        """
        self._trace = []
        config = UnifiedRuntimeConfig()

        # ── Threshold adjustments ────────────────────────────────
        config.threshold_adjustments = self._resolve_thresholds(
            memory=inp.memory_threshold_adjustments,
            steptracker=inp.step_threshold_adjustments,
        )

        # ── Scoring bias ─────────────────────────────────────────
        config.scoring_bias = self._resolve_scoring_bias(
            memory=inp.memory_scoring_bias,
            clip=inp.clip_scoring_bias,
        )

        # ── Pipeline routing ─────────────────────────────────────
        config.pipeline_routing = self._resolve_routing(
            memory=inp.memory_routing,
        )

        self._last_unified = config
        return config

    # ── Per-field resolution ────────────────────────────────────

    def _resolve_thresholds(
        self,
        memory: Dict[str, float],
        steptracker: Dict[str, float],
    ) -> Dict[str, ResolvedValue]:
        """Resolve threshold adjustments by priority + normalization.

        Layer 1 (DAG) and Layer 2 (AOR) do not produce thresholds.
        Layer 3 (memory) beats Layer 4 (steptracker) for conflicts.
        """
        all_steps = set(memory.keys()) | set(steptracker.keys())
        resolved: Dict[str, ResolvedValue] = {}

        for step in sorted(all_steps):
            candidates: Dict[str, Any] = {}
            if step in memory:
                candidates["memory_influence"] = memory[step]
            if step in steptracker:
                candidates["steptracker"] = steptracker[step]

            # Priority: memory (3) > steptracker (4)
            if step in memory:
                winner_value = memory[step]
                source = "memory_influence"
                reason = "MemoryInfluenceEngine (priority 3) overrides StepTracker heuristics"
                if step in steptracker:
                    reason += f"; StepTracker suggested {steptracker[step]}"
            else:
                winner_value = steptracker[step]
                source = "steptracker"
                reason = "StepTracker heuristics (priority 4) — no memory influence for this step"

            # Normalize: clamp to step bounds
            bounds = _STEP_THRESHOLD_BOUNDS.get(step, _DEFAULT_THRESHOLD_BOUNDS)
            clamped = max(bounds[0], min(bounds[1], winner_value))
            if clamped != winner_value:
                reason += f"; clamped to [{bounds[0]}, {bounds[1]}] (was {winner_value})"
                winner_value = clamped

            resolved[step] = ResolvedValue(
                value=round(winner_value, 1),
                source=source,
                reason=reason,
                candidates=candidates,
            )

            self._trace.append({
                "field": f"threshold.{step}",
                "value": round(winner_value, 1),
                "source": source,
                "reason": reason,
                "candidates": dict(candidates),
            })

        return resolved

    def _resolve_scoring_bias(
        self,
        memory: Dict[str, Any],
        clip: Dict[str, Any],
    ) -> Dict[str, ResolvedValue]:
        """Resolve scoring bias by priority + normalization.

        Layer 3 (memory) beats Layer 5 (clip) for all keys.
        Bias values clamped to [-0.5, +0.5].
        """
        all_keys = set(memory.keys()) | set(clip.keys())
        resolved: Dict[str, ResolvedValue] = {}

        for key in sorted(all_keys):
            candidates: Dict[str, Any] = {}
            if key in memory:
                candidates["memory_influence"] = memory[key]
            if key in clip:
                candidates["clip_scoring"] = clip[key]

            # Priority: memory (3) > clip (5)
            if key in memory:
                winner_value = memory[key]
                source = "memory_influence"
                reason = "MemoryInfluenceEngine (priority 3) overrides ClipScoring feedback"
                if key in clip:
                    reason += f"; ClipScoring suggested {clip[key]}"
            else:
                winner_value = clip[key]
                source = "clip_scoring"
                reason = "ClipScoring feedback (priority 5) — no memory influence for this key"

            # Normalize: clamp numeric bias values
            if isinstance(winner_value, (int, float)):
                clamped = max(_BIAS_CLAMP[0], min(_BIAS_CLAMP[1], winner_value))
                if clamped != winner_value:
                    reason += f"; clamped to [{_BIAS_CLAMP[0]}, {_BIAS_CLAMP[1]}] (was {winner_value})"
                    winner_value = clamped

            resolved[key] = ResolvedValue(
                value=winner_value,
                source=source,
                reason=reason,
                candidates=candidates,
            )

            self._trace.append({
                "field": f"bias.{key}",
                "value": winner_value,
                "source": source,
                "reason": reason,
                "candidates": dict(candidates),
            })

        return resolved

    def _resolve_routing(
        self,
        memory: Dict[str, Any],
    ) -> Dict[str, ResolvedValue]:
        """Resolve pipeline routing. Only MemoryInfluenceEngine
        produces routing hints; no conflict resolution needed.
        """
        resolved: Dict[str, ResolvedValue] = {}

        for key, value in memory.items():
            resolved[key] = ResolvedValue(
                value=value,
                source="memory_influence",
                reason="MemoryInfluenceEngine (priority 3) — no competing layer for this routing key",
                candidates={"memory_influence": value},
            )

            self._trace.append({
                "field": f"routing.{key}",
                "value": value,
                "source": "memory_influence",
                "reason": "Only MemoryInfluenceEngine produces routing hints",
                "candidates": {"memory_influence": value},
            })

        return resolved

    # ── Trace ───────────────────────────────────────────────────

    def print_trace(self) -> None:
        """Print the full arbitration decision chain."""
        if not self._trace:
            print("[ARBITER] No decisions recorded.")
            return

        print("=" * 70)
        print("ARBITER DECISION CHAIN")
        print("=" * 70)
        print(f"{'Field':<28} {'Value':<10} {'Source':<20} {'Reason'}")
        print("-" * 70)
        for entry in self._trace:
            field = entry["field"]
            value = str(entry["value"])[:8]
            source = entry["source"][:18]
            reason = entry["reason"][:50]
            print(f"{field:<28} {value:<10} {source:<20} {reason}")
        print("-" * 70)

    def trace_report(self) -> List[Dict[str, Any]]:
        """Return trace as structured data."""
        return list(self._trace)

    def report(self) -> Dict[str, Any]:
        """Full arbitration report with flat config + trace."""
        flat = self._last_unified.to_flat_dict() if self._last_unified else {}
        return {
            "unified_config": flat,
            "trace": self._trace,
            "trace_count": len(self._trace),
        }
