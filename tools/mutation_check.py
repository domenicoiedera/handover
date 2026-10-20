"""Mutation guard: prove that the tests actually defend the fail-closed rules.

Each mutant breaks one rule that the tool publicly promises. A mutant that
survives - the suite still green - means that rule is documented, not enforced.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MUTANTS = [
    (
        "absent claim stops being checked",
        "handover/claims.py",
        '        if path.exists():\n            result.update(status=STALE, detail="path exists and must not")',
        '        if False:\n            result.update(status=STALE, detail="path exists and must not")',
    ),
    (
        "file hash comparison dropped",
        "handover/claims.py",
        '                if actual != expected:\n                    result.update(status=STALE, detail=f"bytes changed',
        '                if False:\n                    result.update(status=STALE, detail=f"bytes changed',
    ),
    (
        "text presence check dropped",
        "handover/claims.py",
        '            if needle not in text:',
        '            if False:',
    ),
    (
        "seal verification dropped",
        "handover/packet.py",
        '    if actual != stored["value"]:',
        '    if False:',
    ),
    (
        "path escape guard dropped",
        "handover/claims.py",
        '        candidate.relative_to(root.resolve())\n    except ValueError as exc:',
        '        candidate.relative_to(root.resolve())\n    except ZeroDivisionError as exc:',
    ),
    (
        "a packet with no claims counts as verified",
        "handover/claims.py",
        '    verified = total > 0 and counts[OK] == total',
        '    verified = counts[OK] == total',
    ),
    (
        "capture seals claims without evaluating them",
        "handover/packet.py",
        '            verdict = evaluate(root, claim)\n            if verdict["status"] != "OK":',
        '            verdict = evaluate(root, claim)\n            if False:',
    ),
    (
        "resume no longer refuses a stale brief",
        "handover/cli.py",
        '    if not summary["verified"]:\n        if summary["total"] == 0:',
        '    if False:\n        if summary["total"] == 0:',
    ),
]


def run_suite(directory: Path) -> bool:
    """True when the suite passes."""
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
        cwd=str(directory), capture_output=True, text=True,
    )
    return result.returncode == 0


def main() -> int:
    if not run_suite(ROOT):
        print("baseline suite is red: fix that before mutating anything", file=sys.stderr)
        return 2

    print(f"{'mutant':<48} {'killed by':>10}")
    print("-" * 60)
    survivors = []
    with tempfile.TemporaryDirectory() as tmp:
        for index, (label, rel, old, new) in enumerate(MUTANTS):
            work = Path(tmp, f"m{index}")
            shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "__pycache__", "build", "dist", "*.egg-info"))
            target = work / rel
            source = target.read_text(encoding="utf-8")
            if old not in source:
                print(f"{label:<48} {'NO MATCH':>10}")
                survivors.append(label)
                continue
            target.write_text(source.replace(old, new, 1), encoding="utf-8")
            if run_suite(work):
                print(f"{label:<48} {'SURVIVED':>10}")
                survivors.append(label)
            else:
                print(f"{label:<48} {'test':>10}")

    print("-" * 60)
    if survivors:
        print(f"{len(survivors)} mutant(s) survived: {survivors}", file=sys.stderr)
        return 1
    print(f"all {len(MUTANTS)} mutants killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
