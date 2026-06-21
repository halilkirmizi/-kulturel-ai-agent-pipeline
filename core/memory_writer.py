"""Memory Write-Back System — post-pipeline signal distillation.

Collects signals from StepTracker, AOR, and auditor; compresses into
distilled memory candidates; gates for promotion; persists to memory_store.json.

Usage:
    from core.memory_writer import MemoryWriter
    mw = MemoryWriter(project_root)
    mw.collect(tracker, aor_path)     # gather signals
    mw.compress()                      # dedup + merge
    mw.promote()                       # learning gate
    mw.save()                          # persist
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# ── Constants ───────────────────────────────────────────────────

_STORE_NAME = "memory_store.json"
_MAX_ENTRIES_PER_CATEGORY = 50
_MAX_AGE_DAYS = 30  # compaction removes entries older than this with no new refs

# Categories for memory candidates
CAT_FAILURE = "failure"
CAT_INSIGHT = "insight"
CAT_INVARIANT = "invariant"
CAT_ARCH_CHANGE = "architecture_change"

# Semantic classification for signals
SEMANTIC_SEMANTIC = "semantic"
SEMANTIC_LIFECYCLE_NOISE = "lifecycle_noise"
SEMANTIC_STRUCTURAL = "structural"
SEMANTIC_INVARIANT = "invariant"

# Gate decisions
GATE_PROMOTE = "PROMOTE"
GATE_REJECT = "REJECT"
GATE_DOWNGRADE = "DOWNGRADE"


# ── Data types ──────────────────────────────────────────────────

@dataclass
class MemoryCandidate:
    category: str         # failure | insight | invariant | architecture_change
    source: str           # steptracker | artifact_registry | auditor | contract_validator
    title: str
    body: str
    signature: str = ""
    artifact_refs: List[str] = field(default_factory=list)
    verified: bool = False
    execution_count: int = 0
    first_seen: str = ""
    last_seen: str = ""
    semantic_class: str = SEMANTIC_SEMANTIC  # semantic | lifecycle_noise | structural | invariant

    def __post_init__(self):
        if not self.signature:
            raw = f"{self.category}|{self.source}|{self.title}"
            self.signature = hashlib.md5(raw.encode()).hexdigest()[:16]
        if not self.first_seen:
            self.first_seen = _now()

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> MemoryCandidate:
        return MemoryCandidate(**d)


# ── Memory store ────────────────────────────────────────────────

class MemoryStore:
    """Persistent memory store with bounded growth and compaction."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._entries: List[MemoryCandidate] = []
        self._load()

    # ── Persistence ─────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            entries_raw = raw.get("entries", [])
            self._entries = [MemoryCandidate.from_dict(e) for e in entries_raw]
        except Exception as exc:
            print(f"[MEMORY] WARNING: failed to load store: {exc}", file=sys.stderr)
            self._entries = []

    def save(self) -> None:
        data = {
            "entries": [e.to_dict() for e in self._entries],
            "updated_at": _now(),
            "version": 1,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp.json")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

    # ── Queries ─────────────────────────────────────────────────

    @property
    def entries(self) -> List[MemoryCandidate]:
        return list(self._entries)

    def by_category(self, category: str) -> List[MemoryCandidate]:
        return [e for e in self._entries if e.category == category]

    def find_by_signature(self, sig: str) -> Optional[MemoryCandidate]:
        for e in self._entries:
            if e.signature == sig:
                return e
        return None

    def has_signature(self, sig: str) -> bool:
        return self.find_by_signature(sig) is not None

    # ── Mutation ────────────────────────────────────────────────

    def add(self, candidate: MemoryCandidate) -> None:
        existing = self.find_by_signature(candidate.signature)
        if existing:
            existing.last_seen = _now()
            existing.execution_count += 1
            if candidate.verified:
                existing.verified = True
            # Merge artifact refs
            for ref in candidate.artifact_refs:
                if ref not in existing.artifact_refs:
                    existing.artifact_refs.append(ref)
            return
        candidate.last_seen = candidate.first_seen
        self._entries.append(candidate)
        self._bounded(candidate.category)

    def remove(self, candidate: MemoryCandidate) -> None:
        self._entries = [e for e in self._entries if e.signature != candidate.signature]

    def _bounded(self, category: str) -> None:
        """Keep at most _MAX_ENTRIES_PER_CATEGORY per category."""
        cat_entries = self.by_category(category)
        if len(cat_entries) > _MAX_ENTRIES_PER_CATEGORY:
            # Remove oldest (by last_seen)
            sorted_entries = sorted(cat_entries, key=lambda e: e.last_seen or "")
            to_remove = sorted_entries[:len(cat_entries) - _MAX_ENTRIES_PER_CATEGORY]
            for e in to_remove:
                self.remove(e)

    # ── Compaction ──────────────────────────────────────────────

    def compact(self, dry_run: bool = False) -> int:
        """Remove entries older than _MAX_AGE_DAYS with no recent execution."""
        cutoff = _now_dt() - timedelta(days=_MAX_AGE_DAYS)
        cutoff_str = cutoff.isoformat()
        removed = 0
        to_remove: List[MemoryCandidate] = []
        for e in self._entries:
            # Keep entries with recent activity
            last = e.last_seen or e.first_seen
            if last >= cutoff_str:
                continue
            # Keep entries with multiple executions (proven value)
            if e.execution_count >= 3:
                continue
            to_remove.append(e)

        for e in to_remove:
            if not dry_run:
                self.remove(e)
            removed += 1

        if not dry_run:
            self.save()
        return removed

    def report(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {
            CAT_FAILURE: 0, CAT_INSIGHT: 0, CAT_INVARIANT: 0, CAT_ARCH_CHANGE: 0,
        }
        for e in self._entries:
            counts[e.category] = counts.get(e.category, 0) + 1
        return {
            "total": len(self._entries),
            "counts": counts,
            "path": str(self._path),
            "updated_at": _now(),
        }

    # ── Behavior hints (for MemoryInfluenceEngine) ─────────────

    def behavior_hints(self) -> Dict[str, Any]:
        """Emit behavior hints from stored memory entries.

        Returns:
            threshold_hints: {step_name: suggested_threshold_seconds}
            failure_rate:     ratio of failures to total entries
            top_insights:     most-executed insight titles with counts
            recent_failures:  count of failures in last 24h
        """
        total = len(self._entries)
        failures = self.by_category(CAT_FAILURE)
        insights = self.by_category(CAT_INSIGHT)
        failure_count = len(failures)

        # Top insights by execution count
        sorted_insights = sorted(insights, key=lambda e: e.execution_count, reverse=True)[:5]

        # Recent failures (last 24h)
        cutoff = (_now_dt() - timedelta(hours=24)).isoformat()
        recent_failures = [
            f for f in failures
            if (f.last_seen or f.first_seen) >= cutoff
        ]

        # Threshold hints: build from slow step insights
        threshold_hints: Dict[str, float] = {}
        for ins in insights:
            if ins.title.startswith("Slow step:"):
                rest = ins.title[len("Slow step: "):]
                if " (" in rest:
                    step_name = rest.split(" (")[0]
                    threshold_hints[step_name] = 60.0  # suggest 60s baseline

        return {
            "threshold_hints": threshold_hints,
            "failure_rate": round(failure_count / total, 3) if total else 0.0,
            "top_insights": [
                {"title": e.title, "count": e.execution_count, "source": e.source}
                for e in sorted_insights
            ],
            "recent_failures_24h": len(recent_failures),
        }


# ── Signal sources ──────────────────────────────────────────────

def _from_steptracker(execution_trace_path: Path) -> List[MemoryCandidate]:
    """Extract memory candidates from StepTracker execution trace."""
    candidates: List[MemoryCandidate] = []
    if not execution_trace_path.exists():
        return candidates

    try:
        trace = json.loads(execution_trace_path.read_text(encoding="utf-8"))
        steps = trace.get("steps", [])
    except Exception:
        return candidates

    for step in steps:
        status = step.get("status", "")
        name = step.get("name", "unknown")
        notes = step.get("notes", "")
        duration = step.get("duration_seconds")

        if status == "failed":
            candidates.append(MemoryCandidate(
                category=CAT_FAILURE,
                source="steptracker",
                title=f"Step failed: {name}",
                body=notes or f"Step '{name}' failed without details",
                artifact_refs=step.get("artifacts", []),
                verified=True,
                execution_count=1,
            ))

        if status == "executed" and duration is not None and duration > 60:
            candidates.append(MemoryCandidate(
                category=CAT_INSIGHT,
                source="steptracker",
                title=f"Slow step: {name} ({duration:.0f}s)",
                body=f"Step '{name}' took {duration:.0f}s, "
                     f"above expected threshold",
                artifact_refs=step.get("artifacts", []),
                verified=True,
                execution_count=1,
            ))

    return candidates


def _from_aor(aor_state_path: Path) -> List[MemoryCandidate]:
    """Extract memory candidates from AOR state."""
    candidates: List[MemoryCandidate] = []
    if not aor_state_path.exists():
        return candidates

    try:
        data = json.loads(aor_state_path.read_text(encoding="utf-8"))
        records = data.get("records", {})
        events = data.get("events", [])
    except Exception:
        return candidates

    # Detect duplicate writers
    writer_map: Dict[str, Set[str]] = {}
    for evt in events:
        if evt.get("action") == "write":
            writer_map.setdefault(evt["artifact"], set()).add(evt["caller"])
    for art, callers in writer_map.items():
        if len(callers) > 1:
            candidates.append(MemoryCandidate(
                category=CAT_INVARIANT,
                source="artifact_registry",
                title=f"Duplicate writer: {art}",
                body=f"Artifact '{art}' written by {', '.join(sorted(callers))}. "
                     "AOR single-writer rule violated.",
                verified=True,
                execution_count=1,
            ))

    # Detect ghost artifacts (legacy lifecycle)
    ghost_count = sum(
        1 for r in records.values()
        if r.get("lifecycle") == "legacy"
    )
    if ghost_count > 0:
        candidates.append(MemoryCandidate(
            category=CAT_INSIGHT,
            source="artifact_registry",
            title=f"Legacy artifacts: {ghost_count}",
            body=f"{ghost_count} legacy artifacts from pre-AOR runs registered. "
                 "These should be cleaned up over time.",
            execution_count=1,
            verified=True,
        ))

    return candidates


def _from_auditor_findings(findings: List[dict]) -> List[MemoryCandidate]:
    """Extract memory candidates from auditor drift findings."""
    candidates: List[MemoryCandidate] = []
    for f in findings:
        sev = f.get("severity", "")
        cat = f.get("category", "")
        msg = f.get("message", "")
        path = f.get("file_path", "")

        if cat == "GHOST":
            candidates.append(MemoryCandidate(
                category=CAT_INSIGHT,
                source="auditor",
                title=f"Ghost file: {path}",
                body=msg,
                artifact_refs=[path] if path else [],
                verified=True,
                execution_count=1,
            ))
        elif cat == "MISSING":
            candidates.append(MemoryCandidate(
                category=CAT_FAILURE,
                source="auditor",
                title=f"Missing artifact: {path}",
                body=msg,
                artifact_refs=[path] if path else [],
                verified=True,
                execution_count=1,
            ))
        elif cat == "DUPLICATE_WRITER":
            candidates.append(MemoryCandidate(
                category=CAT_INVARIANT,
                source="auditor",
                title=f"Duplicate writer: {msg}",
                body=msg,
                verified=True,
                execution_count=1,
            ))

    return candidates


# ── Compression layer ───────────────────────────────────────────

class CompressionLayer:
    """Deduplicate and merge semantically similar memory candidates.

    Merge rules:
      - Same signature → always merge (dedup).
      - Different semantic_class → NEVER merge.
      - lifecycle_noise → never merged into semantic/structural/insight.
    """

    def compress(self, candidates: List[MemoryCandidate]) -> List[MemoryCandidate]:
        if not candidates:
            return []

        # Dedup by (signature, semantic_class)
        seen: Dict[str, MemoryCandidate] = {}
        for c in candidates:
            key = f"{c.signature}|{c.semantic_class}"
            if key in seen:
                existing = seen[key]
                existing.execution_count += 1
                existing.verified = existing.verified or c.verified
                for ref in c.artifact_refs:
                    if ref not in existing.artifact_refs:
                        existing.artifact_refs.append(ref)
                if c.last_seen > existing.last_seen:
                    existing.last_seen = c.last_seen
            else:
                seen[key] = c

        return list(seen.values())


# ── Semantic signal filter ──────────────────────────────────────

_NON_SEMANTIC_PATH_PATTERNS = [
    "temp/",
    "retry_",
    ".tmp",
    "ffmpeg",
    "output_",
    "intermediate_",
]

_SEMANTIC_PATH_PATTERNS = [
    "shorts_output/",
    "state.json",
    "memory_store.json",
    ".artifact_registry.json",
]

_AUDITOR_CLASSIFICATION_TABLE = {
    ("GHOST", True):   (SEMANTIC_LIFECYCLE_NOISE, GATE_REJECT),    # GHOST in temp/
    ("GHOST", False):  (SEMANTIC_STRUCTURAL,      GATE_PROMOTE),   # GHOST outside temp/
    ("MISSING", True): (SEMANTIC_LIFECYCLE_NOISE, GATE_REJECT),    # MISSING in temp/
    ("MISSING", False):(SEMANTIC_STRUCTURAL,      GATE_PROMOTE),   # MISSING outside temp/
    ("DUPLICATE_WRITER", False):(SEMANTIC_INVARIANT, GATE_PROMOTE),
}


def _path_is_lifecycle_noise(path: str) -> bool:
    """Return True if path matches a non-semantic pattern."""
    for pat in _NON_SEMANTIC_PATH_PATTERNS:
        if pat in path:
            return True
    return False


def _path_is_semantic(path: str) -> bool:
    """Return True if path matches a semantic (persistent) pattern."""
    for pat in _SEMANTIC_PATH_PATTERNS:
        if pat in path:
            return True
    return False


class SemanticSignalFilter:
    """Classifies and filters memory signals by semantic relevance.

    Rules:
      - temp/, retry_, .tmp, ffmpeg intermediates → lifecycle_noise → REJECT
      - shorts_output/, state.json, AOR files → semantic → PROMOTE
      - Auditor GHOST in temp/ → lifecycle_noise → REJECT
      - Auditor GHOST in persistent → structural → PROMOTE
      - Auditor MISSING in temp/ → lifecycle_noise → REJECT
      - Auditor MISSING in persistent → structural → PROMOTE
      - Duplicate writer → invariant → PROMOTE
      - StepTracker failures on semantic artifacts → semantic → PROMOTE
      - StepTracker failures on temp artifacts → reject (no stable consumer)
      - AOR legacy insight → lifecycle_noise → DOWNGRADE
    """

    def classify_signal(
        self, candidate: MemoryCandidate
    ) -> str:
        """Classify a candidate and return the gate decision.

        Returns PROMOTE, REJECT, or DOWNGRADE.
        Side effect: sets candidate.semantic_class.
        """
        ctx = candidate.source
        path = candidate.artifact_refs[0] if candidate.artifact_refs else ""
        is_noise = _path_is_lifecycle_noise(path)
        is_sem = _path_is_semantic(path)

        # ── Auditor signals ──────────────────────────────────────
        if ctx == "auditor":
            # Derive auditor category from title
            if candidate.title.startswith("Ghost file:"):
                key = ("GHOST", is_noise)
            elif candidate.title.startswith("Missing artifact:"):
                key = ("MISSING", is_noise)
            elif candidate.title.startswith("Duplicate writer:"):
                key = ("DUPLICATE_WRITER", False)
            else:
                key = None

            if key and key in _AUDITOR_CLASSIFICATION_TABLE:
                sem_class, decision = _AUDITOR_CLASSIFICATION_TABLE[key]
                candidate.semantic_class = sem_class
                return decision

        # ── AOR signals ──────────────────────────────────────────
        if ctx == "artifact_registry":
            if candidate.title.startswith("Legacy artifacts:"):
                candidate.semantic_class = SEMANTIC_LIFECYCLE_NOISE
                return GATE_DOWNGRADE
            if candidate.title.startswith("Duplicate writer:"):
                candidate.semantic_class = SEMANTIC_INVARIANT
                return GATE_PROMOTE

        # ── StepTracker signals ──────────────────────────────────
        if ctx == "steptracker":
            # Step failed on lifecycle_noise path → reject
            if candidate.category == CAT_FAILURE:
                if not path or is_noise:
                    candidate.semantic_class = SEMANTIC_LIFECYCLE_NOISE
                    return GATE_REJECT
                candidate.semantic_class = SEMANTIC_SEMANTIC
                if is_sem:
                    return GATE_PROMOTE
                # Failure on non-temp but non-semantic path → still promote
                # (e.g. a step that produces a persistent-sidecar file)
                return GATE_PROMOTE

            # Slow step insight
            if candidate.category == CAT_INSIGHT:
                if not path or is_noise:
                    # Slow step touching only temp files → downgrade
                    candidate.semantic_class = SEMANTIC_LIFECYCLE_NOISE
                    return GATE_DOWNGRADE
                candidate.semantic_class = SEMANTIC_SEMANTIC
                return GATE_PROMOTE

        # ── Default: promote as semantic ─────────────────────────
        candidate.semantic_class = SEMANTIC_SEMANTIC
        return GATE_PROMOTE

    def filter(
        self, candidates: List[MemoryCandidate]
    ) -> List[MemoryCandidate]:
        """Filter candidates, applying classification and debug output.

        Returns candidates that are PROMOTE or DOWNGRADE
        (DOWNGRADE candidates are kept but tagged).
        """
        kept: List[MemoryCandidate] = []
        for c in candidates:
            decision = self.classify_signal(c)
            reason = self._reason(c, decision)
            print(f"  [MEMORY FILTER] {c.title} classified as {decision} "
                  f"(class={c.semantic_class}) because {reason}")
            if decision == GATE_REJECT:
                continue
            kept.append(c)
        return kept

    @staticmethod
    def _reason(candidate: MemoryCandidate, decision: str) -> str:
        if decision == GATE_REJECT:
            if candidate.source == "auditor":
                return "auditor finding on lifecycle_noise path"
            if candidate.source == "steptracker" and candidate.category == CAT_FAILURE:
                return "step failure produced no semantic artifacts"
            return "non-semantic path with no stable downstream consumer"
        if decision == GATE_DOWNGRADE:
            if candidate.source == "artifact_registry":
                return "legacy artifact count is lifecycle metadata, not learning signal"
            if candidate.category == CAT_INSIGHT:
                return "slow step on temp-only path, not cross-run relevant"
            return "signal has semantic value but zero cross-run relevance"
        if decision == GATE_PROMOTE:
            if candidate.semantic_class == SEMANTIC_STRUCTURAL:
                return "structural artifact anomaly in persistent path"
            if candidate.semantic_class == SEMANTIC_INVARIANT:
                return "AOR invariant violation detected"
            return "semantic signal with persistent consumer or cross-run relevance"
        return "unknown"


# ── Learning loop gate ──────────────────────────────────────────

class LearningLoopGate:
    """Determines whether a candidate is promoted to persistent memory."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def should_promote(self, candidate: MemoryCandidate) -> bool:
        """Return True if candidate passes all promotion conditions."""
        # 1. Must be verified at runtime
        if not candidate.verified:
            return False

        # 2. Must have at least 1 successful execution trace
        if candidate.execution_count < 1:
            return False

        # 3. Must not conflict with existing memory
        existing = self._store.find_by_signature(candidate.signature)
        if existing:
            # Already in store; update count instead of re-adding
            return False

        # 4. Must be referenced in at least 1 artifact OR log event
        #    (artifact_refs is our proxy for "referenced in artifact")
        if not candidate.artifact_refs and candidate.source == "steptracker":
            return False

        return True


# ── Memory writer ───────────────────────────────────────────────

class MemoryWriter:
    """Orchestrates signal collection, compression, semantic filtering, gating, and persistence."""

    def __init__(self, project_root: Optional[Path] = None) -> None:
        root = project_root or Path.cwd()
        self._store_path = root / _STORE_NAME
        self._store = MemoryStore(self._store_path)
        self._gate = LearningLoopGate(self._store)
        self._compressor = CompressionLayer()
        self._semantic_filter = SemanticSignalFilter()
        self._candidates: List[MemoryCandidate] = []
        self._dry_run: bool = False

    @property
    def store(self) -> MemoryStore:
        return self._store

    # ── Collection ──────────────────────────────────────────────

    def collect(
        self,
        execution_trace_path: Optional[Path] = None,
        aor_state_path: Optional[Path] = None,
        auditor_findings: Optional[List[dict]] = None,
    ) -> List[MemoryCandidate]:
        """Gather memory candidates from all available signal sources.

        Args:
            execution_trace_path: Path to execution_trace.json (StepTracker).
            aor_state_path: Path to .artifact_registry.json (AOR).
            auditor_findings: List of auditor drift findings (optional).

        Returns:
            Raw candidates before compression.
        """
        candidates: List[MemoryCandidate] = []

        if execution_trace_path:
            candidates.extend(_from_steptracker(execution_trace_path))

        if aor_state_path:
            candidates.extend(_from_aor(aor_state_path))

        if auditor_findings:
            candidates.extend(_from_auditor_findings(auditor_findings))

        self._candidates = candidates
        return candidates

    # ── Compression ─────────────────────────────────────────────

    def compress(self) -> List[MemoryCandidate]:
        """Deduplicate and merge current candidates.

        Returns compressed candidates.
        """
        self._candidates = self._compressor.compress(self._candidates)
        return self._candidates

    # ── Semantic filter ─────────────────────────────────────────

    def filter_semantic(self) -> List[MemoryCandidate]:
        """Classify and filter candidates by semantic relevance.

        Removes lifecycle_noise; tags DOWNGRADE candidates.
        Prints [MEMORY FILTER] debug output for each signal.

        Returns filtered candidates.
        """
        self._candidates = self._semantic_filter.filter(self._candidates)
        return self._candidates

    # ── Promotion ───────────────────────────────────────────────

    def promote(self) -> List[MemoryCandidate]:
        """Run learning loop gate on candidates; return promoted set.

        Promoted candidates are written to the store
        (unless dry_run mode is active).
        """
        promoted: List[MemoryCandidate] = []
        for c in self._candidates:
            if self._gate.should_promote(c):
                promoted.append(c)
                if not self._dry_run:
                    self._store.add(c)

        if not self._dry_run and promoted:
            self._store.save()

        return promoted

    # ── Full pipeline ───────────────────────────────────────────

    def run(
        self,
        execution_trace_path: Optional[Path] = None,
        aor_state_path: Optional[Path] = None,
        auditor_findings: Optional[List[dict]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """End-to-end: collect → compress → filter → promote.

        Args:
            execution_trace_path: Path to execution_trace.json.
            aor_state_path: Path to .artifact_registry.json.
            auditor_findings: Optional list of audit findings.
            dry_run: If True, promotes in memory only (no save).

        Returns:
            Summary dict with counts of candidates/promoted/rejected/filtered.
        """
        self._dry_run = dry_run

        raw = self.collect(execution_trace_path, aor_state_path, auditor_findings)
        compressed = self.compress()
        filtered = self.filter_semantic()
        promoted = self.promote()

        total_before_gate = len(filtered)
        rejected = total_before_gate - len(promoted)
        report = self._store.report()

        return {
            "raw_candidates": len(raw),
            "after_compression": len(compressed),
            "after_semantic_filter": len(filtered),
            "promoted": len(promoted),
            "promoted_after_gate": len(promoted),
            "rejected_by_gate": rejected,
            "store_total": report["total"],
            "store_counts": report["counts"],
            "dry_run": dry_run,
        }

    # ── Save (explicit) ─────────────────────────────────────────

    def save(self) -> None:
        self._store.save()


# ── Helpers ─────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)
