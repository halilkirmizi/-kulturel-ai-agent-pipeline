"""External Artifact Auditor — independent filesystem vs AOR validation.

Modes:
  --verify     Full audit against persisted AOR state
  --bootstrap  Scan filesystem + register all outputs as LEGACY baseline
  --drift      Compare current filesystem against baseline (only deltas)

Usage:
    python -m core.artifact_auditor --bootstrap
    python -m core.artifact_auditor --drift
    python -m core.artifact_auditor --verify
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ── Constants ───────────────────────────────────────────────────

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent

# Files / dirs to skip during scan
_SKIP_DIRS = {"__pycache__", ".git", ".venv", "node_modules", "venv", "_archive"}
_SKIP_FILES = {".artifact_registry.json", ".artifact_registry.tmp.json"}

# Source code is not a pipeline artifact
_SOURCE_EXTS = {".py", ".md", ".txt", ".toml", ".cfg", ".ini", ".gitignore", ".gitkeep"}
_SOURCE_NAMES = {"requirements.txt", ".env.template", "preferences.md", "_CLAUDE.md",
                 "SESSION.md", "WORKFLOW.md", "ROADMAP.md", "REFACTOR_SEQUENCE.md",
                 "STATE_CONTRACT.md"}

# Only files in these directories are considered pipeline output artifacts
_OUTPUT_DIRS = {"temp", "shorts_output", "logs"}
_OUTPUT_FILES = {
    "upload/.upload_quota.json",
    "upload/.upload_log.json",
}

# AOR persistence path (relative to output dir)
_AOR_STATE_NAME = ".artifact_registry.json"
_AOR_DEFAULT_DIR = "shorts_output"


# ── Data types ──────────────────────────────────────────────────

@dataclass
class AuditFinding:
    severity: str       # CRITICAL | HIGH | MEDIUM | LOW
    category: str       # GHOST | MISSING | DUPLICATE_WRITER | SHADOW | WRITER_MISMATCH | MODIFIED
    message: str
    file_path: str = ""
    aor_name: str = ""


@dataclass
class AuditReport:
    findings: List[AuditFinding] = field(default_factory=list)
    total_files: int = 0
    total_aor: int = 0
    matched: int = 0
    timestamp: str = ""

    def by_severity(self) -> Dict[str, List[AuditFinding]]:
        result: Dict[str, List[AuditFinding]] = {}
        for f in self.findings:
            result.setdefault(f.severity, []).append(f)
        return result

    def print(self, file=sys.stderr) -> None:
        by_sev = self.by_severity()
        sev_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
        counts = {s: len(by_sev.get(s, [])) for s in sev_order}

        print("=" * 60, file=file)
        print("  ARTIFACT AUDITOR REPORT", file=file)
        print("=" * 60, file=file)
        print(f"  Files scanned : {self.total_files}", file=file)
        print(f"  AOR artifacts : {self.total_aor}", file=file)
        print(f"  Matched       : {self.matched}", file=file)
        print(f"  Findings      : {sum(counts.values())}", file=file)
        print(f"    CRITICAL    : {counts['CRITICAL']}", file=file)
        print(f"    HIGH        : {counts['HIGH']}", file=file)
        print(f"    MEDIUM      : {counts['MEDIUM']}", file=file)
        print(f"    LOW         : {counts['LOW']}", file=file)
        print("-" * 60, file=file)

        for sev in sev_order:
            items = by_sev.get(sev, [])
            if not items:
                continue
            print(f"  [{sev}]", file=file)
            for finding in items:
                if finding.file_path:
                    print(f"    {finding.file_path}", file=file)
                print(f"    -> {finding.message}", file=file)
                print(file=file)

        total = sum(counts.values())
        if total == 0:
            print("  No issues found.", file=file)
        print("=" * 60, file=file)


# ── Helpers ─────────────────────────────────────────────────────

def _is_source_file(f: Path) -> bool:
    """True if the file is project source code, not a pipeline artifact."""
    return f.suffix in _SOURCE_EXTS or f.name in _SOURCE_NAMES


def _is_output_file(rel: str) -> bool:
    """True if the relative path lives in an output directory."""
    first = rel.split("/", 1)[0]
    if first in _OUTPUT_DIRS:
        return True
    for of in _OUTPUT_FILES:
        if rel == of or rel.startswith(of):
            return True
    return False


def _path_to_glob(pattern: str) -> str:
    """Convert an AOR path_pattern to a simple glob.

    '...' matches zero or more directory levels.
    '<id>' / '<hash>' matches any single path component.
    """
    pattern = pattern.replace("...", "**")
    pattern = re.sub(r"<[^>]+>", "*", pattern)
    return pattern


def _file_matches_artifact(file_rel: str, pattern: str) -> bool:
    """Check if a relative file path matches an artifact path_pattern."""
    glob_pattern = _path_to_glob(pattern)
    p = Path(file_rel)
    return p.match(glob_pattern)


def _scan_directory(root: Path) -> List[Path]:
    """Recursively list all files under root, excluding junk dirs."""
    files: List[Path] = []
    for entry in root.rglob("*"):
        if entry.is_dir():
            continue
        parts = entry.relative_to(root).parts
        if any(part in _SKIP_DIRS for part in parts):
            continue
        if entry.name in _SKIP_FILES:
            continue
        files.append(entry)
    return files


def _load_aor_state(path: Path) -> Optional[dict]:
    """Load persisted AOR state from a JSON file."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[AUDITOR] WARNING: failed to parse AOR state: {exc}", file=sys.stderr)
        return None


def _find_aor_state(root: Path) -> Optional[Path]:
    """Locate .artifact_registry.json under root or its output dirs."""
    candidates = [
        root / _AOR_STATE_NAME,
        root / _AOR_DEFAULT_DIR / _AOR_STATE_NAME,
    ]
    for short_dir in sorted(root.glob(f"{_AOR_DEFAULT_DIR}/short_*")):
        candidates.append(short_dir / _AOR_STATE_NAME)
    for p in candidates:
        if p.exists():
            return p
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Auditor ─────────────────────────────────────────────────────

class ArtifactAuditor:
    """Independent external auditor. Does NOT rely on in-memory AOR state."""

    def __init__(self, project_root: Optional[Path] = None) -> None:
        self._root = (project_root or _PROJECT_ROOT).resolve()
        self._aor_data: Optional[dict] = None

    # ── Bootstrap ───────────────────────────────────────────────

    def bootstrap(self) -> Path:
        """Scan all output files and register as LEGACY baseline.

        Returns path to the saved bootstrap snapshot.
        """
        all_files = _scan_directory(self._root)
        records: Dict[str, dict] = {}
        events: List[dict] = []

        for f in all_files:
            rel = str(f.relative_to(self._root).as_posix())
            if _is_source_file(f):
                continue
            if not _is_output_file(rel):
                continue

            name = "legacy:" + rel.replace("/", "_").replace(".", "_").replace("-", "_")
            stat = f.stat()
            records[name] = {
                "name": name,
                "path_pattern": rel,
                "owner": "bootstrap",
                "writers": [],
                "readers": [],
                "lifecycle": "legacy",
                "source_of_truth": False,
                "delete_policy": "never",
                "baseline_size": stat.st_size,
                "baseline_mtime": stat.st_mtime,
            }
            events.append({
                "artifact": name,
                "path": rel,
                "caller": "bootstrap",
                "action": "baseline",
                "timestamp": _now(),
            })

        data = {
            "records": records,
            "events": events,
            "frozen": True,
            "updated_at": _now(),
            "bootstrap": True,
            "bootstrap_version": 1,
        }

        out_dir = self._root / _AOR_DEFAULT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / _AOR_STATE_NAME

        tmp = path.with_suffix(".tmp.json")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

        total = len(records)
        print(f"[AUDITOR] Bootstrap complete: {total} legacy artifacts registered -> {path}",
              file=sys.stderr)
        return path

    # ── Drift ───────────────────────────────────────────────────

    def run_drift(self) -> AuditReport:
        """Compare current filesystem against bootstrap baseline.

        Only reports:
          - NEW files (GHOST): exist on disk, not in baseline
          - MISSING files: in baseline but gone from disk
          - MODIFIED files: size changed since baseline
        No noise from pre-existing legacy files.
        """
        report = AuditReport(timestamp=_now())

        # Load baseline
        aor_path = _find_aor_state(self._root)
        if aor_path is None:
            report.findings.append(AuditFinding(
                severity="HIGH",
                category="MISSING",
                message="No .artifact_registry.json found. "
                        "Run --bootstrap first to create a baseline.",
            ))
            return report

        self._aor_data = _load_aor_state(aor_path)
        if self._aor_data is None:
            report.findings.append(AuditFinding(
                severity="HIGH",
                category="MISSING",
                message=f"Corrupt AOR state at {aor_path}",
            ))
            return report

        records: dict = self._aor_data.get("records", {})

        # Build baseline index: file rel -> record
        baseline: Dict[str, dict] = {}
        for name, rec in records.items():
            pattern = rec.get("path_pattern", "")
            if pattern and pattern != "memory":
                baseline[pattern] = rec

        # Scan current filesystem
        all_files = _scan_directory(self._root)
        report.total_files = len(all_files)
        report.total_aor = len(records)
        current_paths: Set[str] = set()
        baseline_matched: Set[str] = set()

        for f in all_files:
            rel = str(f.relative_to(self._root).as_posix())
            if _is_source_file(f):
                continue

            current_paths.add(rel)

            if rel in baseline:
                baseline_matched.add(rel)
                report.matched += 1

                # Check for size change (modification)
                bl = baseline[rel]
                bl_size = bl.get("baseline_size")
                if bl_size is not None:
                    cur_size = f.stat().st_size
                    if cur_size != bl_size:
                        report.findings.append(AuditFinding(
                            severity="MEDIUM",
                            category="MODIFIED",
                            message=f"File size changed: baseline={bl_size}, current={cur_size}",
                            file_path=rel,
                            aor_name=bl.get("name", ""),
                        ))
            elif _is_output_file(rel):
                # New file in output directory, not in baseline = GHOST
                report.findings.append(AuditFinding(
                    severity="HIGH",
                    category="GHOST",
                    message="New output file not in baseline AOR",
                    file_path=rel,
                ))

        # Detect deleted baseline files
        for rel in baseline:
            if rel not in current_paths and _is_output_file(rel):
                report.findings.append(AuditFinding(
                    severity="MEDIUM",
                    category="MISSING",
                    message="Baseline artifact missing from disk",
                    file_path=rel,
                    aor_name=baseline[rel].get("name", ""),
                ))

        # Detect duplicate writers (same as full mode)
        if self._aor_data and "events" in self._aor_data:
            writer_map: Dict[str, Set[str]] = {}
            for evt in self._aor_data["events"]:
                if evt.get("action") == "write":
                    writer_map.setdefault(evt["artifact"], set()).add(evt["caller"])
            for art, callers in writer_map.items():
                if len(callers) > 1:
                    report.findings.append(AuditFinding(
                        severity="CRITICAL",
                        category="DUPLICATE_WRITER",
                        message=f"Multiple writers: {', '.join(sorted(callers))}",
                        aor_name=art,
                    ))

        return report

    # ── Full verification ───────────────────────────────────────

    def run(self) -> AuditReport:
        """Full audit against persisted AOR state."""
        report = AuditReport(timestamp=_now())

        # 1. Load AOR persisted state
        aor_path = _find_aor_state(self._root)
        if aor_path is None:
            report.findings.append(AuditFinding(
                severity="HIGH",
                category="MISSING",
                message="No .artifact_registry.json found. "
                        "Run --bootstrap first or run the pipeline.",
            ))
        else:
            self._aor_data = _load_aor_state(aor_path)
            if self._aor_data is None:
                report.findings.append(AuditFinding(
                    severity="HIGH",
                    category="MISSING",
                    message=f"AOR state corrupt at {aor_path}",
                ))

        records: Dict[str, dict] = {}
        if self._aor_data:
            records = self._aor_data.get("records", {})
        report.total_aor = len(records)

        # 3. Walk filesystem
        all_files = _scan_directory(self._root)
        report.total_files = len(all_files)

        # 4. Build file -> AOR mapping
        file_to_aor: Dict[str, List[Tuple[str, dict]]] = {}
        for f in all_files:
            rel = str(f.relative_to(self._root).as_posix())
            matches: List[Tuple[str, dict]] = []
            for name, rec in records.items():
                pattern = rec.get("path_pattern", "")
                if pattern == "memory":
                    continue
                if _file_matches_artifact(rel, pattern):
                    matches.append((name, rec))
            if matches:
                file_to_aor[rel] = matches

        report.matched = len(file_to_aor)

        # 5. Ghost detection (output files not in AOR)
        matched_files = set(file_to_aor.keys())
        for f in all_files:
            rel = str(f.relative_to(self._root).as_posix())
            if rel in matched_files:
                continue
            if _is_source_file(f):
                continue
            if not _is_output_file(rel):
                continue
            if rel.startswith("shorts_output/") and rel.count("/") <= 1:
                continue
            report.findings.append(AuditFinding(
                severity="HIGH",
                category="GHOST",
                message="File exists on disk but is not registered in AOR",
                file_path=rel,
            ))

        # 6. Missing artifacts
        for name, rec in records.items():
            pattern = rec.get("path_pattern", "")
            if pattern == "memory":
                continue
            lifecycle = rec.get("lifecycle", "persistent")
            if lifecycle not in ("persistent", "legacy"):
                continue
            matched_any = False
            for rel, matches in file_to_aor.items():
                if any(m[0] == name for m in matches):
                    matched_any = True
                    break
            if not matched_any:
                report.findings.append(AuditFinding(
                    severity="MEDIUM" if lifecycle == "derived" else "HIGH",
                    category="MISSING",
                    message=f"Declared artifact '{name}' not found on disk",
                    aor_name=name,
                ))

        # 7. Duplicate writers
        if self._aor_data and "events" in self._aor_data:
            writer_map: Dict[str, Set[str]] = {}
            for evt in self._aor_data["events"]:
                if evt.get("action") == "write":
                    writer_map.setdefault(evt["artifact"], set()).add(evt["caller"])
            for art, callers in writer_map.items():
                if len(callers) > 1:
                    report.findings.append(AuditFinding(
                        severity="CRITICAL",
                        category="DUPLICATE_WRITER",
                        message=f"Multiple writers: {', '.join(sorted(callers))}",
                        aor_name=art,
                    ))

        # 8. Writer mismatches
        if self._aor_data and "events" in self._aor_data:
            write_events: Dict[str, Set[str]] = {}
            for evt in self._aor_data["events"]:
                if evt.get("action") == "write":
                    write_events.setdefault(evt["artifact"], set()).add(evt["caller"])
            for art, actual_callers in write_events.items():
                rec = records.get(art)
                if not rec:
                    continue
                declared = set(rec.get("writers", []))
                for caller in actual_callers:
                    if caller not in declared:
                        report.findings.append(AuditFinding(
                            severity="HIGH",
                            category="WRITER_MISMATCH",
                            message=f"Written by '{caller}' but declared: {', '.join(declared) or 'none'}",
                            aor_name=art,
                        ))

        # 9. Shadow persistence
        path_owners: Dict[str, Set[str]] = {}
        for rel, matches in file_to_aor.items():
            for name, rec in matches:
                owner = rec.get("owner", "unknown")
                path_owners.setdefault(rel, set()).add(owner)
        for rel, owners in path_owners.items():
            if len(owners) > 1:
                report.findings.append(AuditFinding(
                    severity="CRITICAL",
                    category="SHADOW",
                    message=f"Claimed by multiple owners: {', '.join(sorted(owners))}",
                    file_path=rel,
                ))

        return report


# ── CLI ─────────────────────────────────────────────────────────

def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="External Artifact Auditor — validate filesystem vs AOR",
    )
    parser.add_argument("--verify", action="store_true",
                        help="Run full audit against AOR state")
    parser.add_argument("--bootstrap", action="store_true",
                        help="Scan outputs + create LEGACY baseline snapshot")
    parser.add_argument("--drift", action="store_true",
                        help="Compare filesystem against baseline (only deltas)")
    parser.add_argument("--root", default=None,
                        help="Project root directory (default: auto-detect)")
    parser.add_argument("--json", action="store_true",
                        help="Output report as JSON")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    args = _parse_args(argv)
    root = Path(args.root).resolve() if args.root else None
    auditor = ArtifactAuditor(project_root=root)

    if args.bootstrap:
        auditor.bootstrap()
        return 0

    if args.drift:
        report = auditor.run_drift()
    else:
        report = auditor.run()

    if args.json:
        print(json.dumps(asdict(report), indent=2, ensure_ascii=False))
    else:
        report.print()

    if args.drift or args.verify:
        has_issues = any(
            f.severity in ("CRITICAL", "HIGH")
            for f in report.findings
        )
        return 1 if has_issues else 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
