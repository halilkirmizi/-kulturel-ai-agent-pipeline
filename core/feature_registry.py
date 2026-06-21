"""Feature Registry — tracks runtime usage of all pipeline features.

Observation layer only. No execution, no state changes, no side effects
beyond the registry itself.

Usage:
    from core.feature_registry import registry
    registry.declare("my_feature", "core", "description")
    registry.use("my_feature")  # on success
    registry.fail("my_feature") # on failure
    registry.print_report()     # at end of pipeline
"""

from __future__ import annotations

import sys
import time
from typing import Dict, List


class FeatureRegistry:
    """Tracks declared features and their runtime usage."""

    def __init__(self) -> None:
        self._features: Dict[str, dict] = {}
        self._start_time: float = time.time()

    def declare(
        self,
        name: str,
        type: str = "core",
        description: str = "",
    ) -> None:
        """Declare a feature. Idempotent — second call is a no-op."""
        if name not in self._features:
            self._features[name] = {
                "name": name,
                "type": type,
                "description": description,
                "used": False,
                "failed": False,
                "last_used": None,
                "call_count": 0,
            }

    def use(self, name: str) -> None:
        self._mark(name, used=True, failed=False)

    def fail(self, name: str) -> None:
        self._mark(name, used=True, failed=True)

    def _mark(self, name: str, used: bool, failed: bool) -> None:
        if name not in self._features:
            self._features[name] = {
                "name": name,
                "type": "unknown",
                "description": "",
                "used": False,
                "failed": False,
                "last_used": None,
                "call_count": 0,
            }
        self._features[name]["used"] = True
        self._features[name]["failed"] = failed
        self._features[name]["last_used"] = time.time()
        self._features[name]["call_count"] += 1

    def report(self) -> Dict:
        """Full report: used, unused, failure counts."""
        all_f = sorted(self._features.values(), key=lambda x: x["name"])
        used = [f for f in all_f if f["used"]]
        unused = [f for f in all_f if not f["used"]]
        failed = [f for f in all_f if f["failed"]]
        return {
            "total": len(all_f),
            "used_count": len(used),
            "unused_count": len(unused),
            "failed_count": len(failed),
            "used": used,
            "unused": unused,
            "failed": failed,
            "elapsed_seconds": round(time.time() - self._start_time, 2),
        }

    def print_report(self, file=None) -> None:
        """Print human-readable report to stderr (or given file)."""
        if file is None:
            file = sys.stderr
        r = self.report()
        sep = "=" * 64
        print(file=file)
        print(sep, file=file)
        print("  FEATURE REGISTRY REPORT".ljust(58), "|", f"  {r['elapsed_seconds']:>6.1f}s", file=file)
        print(sep, file=file)
        pct = f"{r['used_count']}/{r['total']}"
        print(f"  Used: {r['used_count']}  Unused: {r['unused_count']}  "
              f"Failed: {r['failed_count']}  Coverage: {pct}", file=file)
        print(file=file)
        for f in r["used"]:
            flag = "X" if f["failed"] else " "
            print(f"  [{f['type']:>10}] [{'ok' if not f['failed'] else 'FAIL':>4}] "
                  f"{f['name']}  (calls={f['call_count']})", file=file)
        if r["unused"]:
            print(file=file)
            print("  -- NOT REACHED --", file=file)
            for f in r["unused"]:
                print(f"  [{f['type']:>10}] {f['name']}  {f['description']}", file=file)
        print(sep, file=file)
        print(file=file)


# Module-level singleton
registry = FeatureRegistry()
