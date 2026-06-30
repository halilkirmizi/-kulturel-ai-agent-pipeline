"""Comprehensive test runner — the "buyuk capli test" run after every feature.

Discovers and runs every tests/test_*.py suite in its own subprocess, parses
each suite's "RESULT: X/Y passed" line, and prints a consolidated summary.
Exit code 0 only if every suite passes.

Run:  python tests/run_all.py
"""

import re
import subprocess
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_ROOT = _TESTS_DIR.parent

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Deterministic order: fast/unit first, integration last.
_ORDER = [
    "test_refactor",
    "test_reframe",
    "test_captions_karaoke",
    "test_silence",
    "test_performance",
    "test_integration_ffmpeg",
]


def _discover():
    found = {p.stem for p in _TESTS_DIR.glob("test_*.py")}
    ordered = [n for n in _ORDER if n in found]
    ordered += sorted(found - set(ordered))  # any new suites, alphabetically
    return ordered


_RESULT_RE = re.compile(r"RESULT:\s*(\d+)/(\d+)\s+passed")


def main() -> int:
    print("=" * 64)
    print("FULL TEST MATRIX")
    print("=" * 64)

    suites = _discover()
    rows = []
    total_pass = total_all = 0
    all_green = True

    for name in suites:
        proc = subprocess.run(
            [sys.executable, str(_TESTS_DIR / f"{name}.py")],
            capture_output=True, text=True, cwd=str(_ROOT),
        )
        out = proc.stdout + proc.stderr
        m = _RESULT_RE.search(out)
        if m:
            p, a = int(m.group(1)), int(m.group(2))
            counts = f"{p}/{a}"
        else:
            # Suite without a RESULT line (e.g. test_refactor prints its own summary)
            m2 = re.search(r"(\d+)/(\d+)\s+tests passed", out)
            if m2:
                p, a = int(m2.group(1)), int(m2.group(2))
                counts = f"{p}/{a}"
            else:
                p = a = 0
                counts = "?"
        ok = proc.returncode == 0 and (a == 0 or p == a) and counts != "?"
        total_pass += p
        total_all += a
        all_green = all_green and ok
        status = "PASS" if ok else "FAIL"
        rows.append((name, counts, status))
        print(f"  {status:4}  {name:<28} {counts}")
        if not ok:
            print("  ---- failing suite output (tail) ----")
            print("\n".join(out.strip().splitlines()[-15:]))
            print("  -------------------------------------")

    print("=" * 64)
    print(f"SUITES: {sum(1 for _, _, s in rows if s == 'PASS')}/{len(rows)} green"
          f"   |   CHECKS: {total_pass}/{total_all} passed")
    print("=" * 64)
    return 0 if all_green else 1


if __name__ == "__main__":
    sys.exit(main())
