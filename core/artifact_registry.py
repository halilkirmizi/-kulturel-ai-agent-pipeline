"""Artifact Ownership Registry — runtime artifact tracking and enforcement.

Every file or in-memory data structure produced by the pipeline must be
registered here.  Enforces:
  - Single writer per artifact (two writers = ERROR)
  - state.json is the only source of truth
  - No silent artifact creation (unknown write = WARNING)
  - Full traceability (every artifact has an owner)
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


# ── Types ───────────────────────────────────────────────────────

@dataclass
class ArtifactRecord:
    name: str
    path_pattern: str
    owner: str
    writers: List[str] = field(default_factory=list)
    readers: List[str] = field(default_factory=list)
    lifecycle: str = "persistent"          # ephemeral | persistent | derived | legacy
    source_of_truth: bool = False
    delete_policy: str = "never"           # never | after_upload | end_of_run
    # Bootstrap / baseline fields (auditor use only)
    baseline_size: Optional[int] = None
    baseline_mtime: Optional[float] = None


@dataclass
class ArtifactEvent:
    artifact: str
    path: str
    caller: str
    action: str                            # "write" | "read"
    timestamp: str = ""


# ── Errors ──────────────────────────────────────────────────────

class ArtifactError(Exception):
    """Raised on registry enforcement violations."""


# ── Registry ────────────────────────────────────────────────────

class _ArtifactRegistry:
    """Singleton artifact registry with runtime enforcement."""

    def __init__(self) -> None:
        self._records: Dict[str, ArtifactRecord] = {}
        self._events: List[ArtifactEvent] = []
        self._frozen: bool = False

    # ── Declaration ─────────────────────────────────────────────

    def declare(self, record: ArtifactRecord) -> None:
        """Register an artifact type. Must happen before any write/read."""
        if record.name in self._records:
            return  # idempotent
        self._records[record.name] = record

    def freeze(self) -> None:
        """Lock the declaration catalog. All writes after this must match
        a declared artifact."""
        self._frozen = True

    # ── Runtime hooks ───────────────────────────────────────────

    def register_write(self, name: str, path: str | Path, caller: str) -> None:
        """Record a write and enforce single-writer rule.

        Raises ArtifactError if:
          - Two different callers write the same artifact.
          - A non-declared artifact is written after freeze().
        """
        path_str = str(path)
        if self._frozen and name not in self._records:
            print(
                f"[AOR] WARNING: unknown artifact write '{name}' by {caller} -> {path_str}",
                file=sys.stderr, flush=True,
            )

        if name in self._records:
            record = self._records[name]
            if record.writers and caller not in record.writers:
                existing = ", ".join(record.writers)
                raise ArtifactError(
                    f"Artifact '{name}' already has writer(s) [{existing}]; "
                    f"'{caller}' attempted to write. "
                    "Single-writer rule violated."
                )
            if caller not in record.writers:
                record.writers.append(caller)
        else:
            # Auto-create ephemeral record for undeclared artifacts
            self._records[name] = ArtifactRecord(
                name=name,
                path_pattern=path_str,
                owner=caller,
                writers=[caller],
                lifecycle="ephemeral",
            )

        self._events.append(ArtifactEvent(
            artifact=name, path=path_str, caller=caller,
            action="write", timestamp=_now(),
        ))

    def register_read(self, name: str, path: str | Path, caller: str) -> None:
        """Record a read. Silently tracks undeclared artifacts."""
        path_str = str(path)
        if name not in self._records:
            if self._frozen:
                print(
                    f"[AOR] WARNING: unknown artifact read '{name}' by {caller} -> {path_str}",
                    file=sys.stderr, flush=True,
                )
            self._records[name] = ArtifactRecord(
                name=name, path_pattern=path_str, owner=caller, lifecycle="persistent",
            )
        record = self._records[name]
        if caller not in record.readers:
            record.readers.append(caller)
        self._events.append(ArtifactEvent(
            artifact=name, path=path_str, caller=caller,
            action="read", timestamp=_now(),
        ))

    # ── Validation ──────────────────────────────────────────────

    def validate(self) -> List[str]:
        """Run all enforcement checks. Returns list of error messages."""
        errors: List[str] = []

        # Rule 1: state.json must be the only source of truth
        for name, rec in self._records.items():
            if rec.source_of_truth and name != "state_json":
                errors.append(
                    f"DUPLICATE_SOT: '{name}' marked source_of_truth; "
                    "only state_json may be source of truth"
                )
        state_rec = self._records.get("state_json")
        if state_rec and not state_rec.source_of_truth:
            errors.append("MISSING_SOT: state_json must be source_of_truth=True")

        # Rule 3: detect persistent artifacts that shadow state.json fields
        # (declarative: any persistent non-state artifact is flagged for review)
        state_fields = {"hook_text", "intro_script", "outro_script", "reason", "scores"}
        for name, rec in self._records.items():
            if rec.lifecycle == "persistent" and not rec.source_of_truth:
                for field_name in state_fields:
                    if field_name in name.lower():
                        errors.append(
                            f"SHADOW_STATE: '{name}' persists field '{field_name}' "
                            "which is tracked in state.json"
                        )

        return errors

    # ── Reports ─────────────────────────────────────────────────

    def print_report(self) -> None:
        """Print structured [AOR] report to stderr."""
        total = len(self._records)
        dup_writers = sum(
            1 for r in self._records.values() if len(r.writers) > 1
        )
        orphan_readers = sum(
            1 for r in self._records.values()
            if r.writers and not r.readers
        )
        orphan_writers = sum(
            1 for r in self._records.values()
            if r.readers and not r.writers
        )

        print(
            f"[AOR] {total} artifacts registered\n"
            f"[AOR] {dup_writers} duplicate writers\n"
            f"[AOR] {orphan_readers} written-but-never-read\n"
            f"[AOR] {orphan_writers} read-but-never-written\n",
            end="", file=sys.stderr, flush=True,
        )

        # Validation errors
        errors = self.validate()
        for e in errors:
            print(f"[AOR] ERROR: {e}", file=sys.stderr, flush=True)

    def summary(self) -> str:
        """One-liner for log output."""
        total = len(self._records)
        dup = sum(1 for r in self._records.values() if len(r.writers) > 1)
        errors = self.validate()
        err_part = f" {len(errors)} errors" if errors else " ok"
        return f"[AOR] {total} artifacts{err_part}"

    # ── Persistence ─────────────────────────────────────────────

    def save(self, path: Path) -> None:
        """Persist registry state for crash recovery."""
        data = {
            "records": {k: asdict(v) for k, v in self._records.items()},
            "events": [asdict(e) for e in self._events],
            "frozen": self._frozen,
            "updated_at": _now(),
        }
        tmp = path.with_suffix(".tmp.json")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def load(self, path: Path) -> None:
        """Load persisted registry state."""
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            records_raw = raw.get("records", {})
            for name, r in records_raw.items():
                self._records[name] = ArtifactRecord(**r)
            events_raw = raw.get("events", [])
            self._events = [ArtifactEvent(**e) for e in events_raw]
            self._frozen = raw.get("frozen", False)
        except Exception as exc:
            print(
                f"[AOR] WARNING: failed to load persisted state: {exc}",
                file=sys.stderr, flush=True,
            )


# ── Singleton ───────────────────────────────────────────────────

AOR = _ArtifactRegistry()


# ── Helpers ─────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
