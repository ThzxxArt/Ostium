#!/usr/bin/env python3
"""Enforce Ostium's coverage policy from coverage.py's JSON report.

Policy (PLAN.md v0.1.0):
* overall statement coverage >= 85% and branch coverage >= 85%;
* every non-generated Python module >= 85% statements and >= 85% branches;
* the api/core/services/engine packages >= 90% statements and >= 90% branches.

Generated protobuf modules and the hatch-vcs version file are the only
excluded sources; they are validated by their import/use in tests instead.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OVERALL_MIN = 85.0
MODULE_MIN = 85.0
CRITICAL_MIN = 90.0
CRITICAL_PACKAGES = ("api", "core", "services", "engine")
GENERATED = ("_version.py", "v2ray_stats_pb2.py", "v2ray_stats_pb2_grpc.py")


def _pct(covered: int, total: int) -> float:
    return 100.0 if total == 0 else covered * 100.0 / total


def _is_generated(path: str) -> bool:
    return any(path.endswith(name) for name in GENERATED)


def _module(rows: list[dict[str, object]]) -> dict[str, float]:
    statements = sum(int(row["statements"]) for row in rows)
    covered = sum(int(row["covered"]) for row in rows)
    branches = sum(int(row["branches"]) for row in rows)
    branches_covered = sum(int(row["branches_covered"]) for row in rows)
    return {
        "statements": _pct(covered, statements),
        "branches": _pct(branches_covered, branches),
        "statement_total": float(statements),
        "branch_total": float(branches),
    }


def main(path: Path) -> int:
    report = json.loads(path.read_text(encoding="utf-8"))
    files = report["files"]
    rows: list[dict[str, object]] = []
    failures: list[str] = []

    for name, info in sorted(files.items()):
        if _is_generated(name):
            continue
        summary = info["summary"]
        statements = int(summary["num_statements"])
        covered = int(summary["covered_lines"])
        branches = int(summary["num_branches"])
        branches_covered = int(summary["covered_branches"])
        row = {
            "path": name,
            "statements": statements,
            "covered": covered,
            "branches": branches,
            "branches_covered": branches_covered,
        }
        rows.append(row)
        statement_pct = _pct(covered, statements)
        branch_pct = _pct(branches_covered, branches)
        if statements and statement_pct + 1e-9 < MODULE_MIN:
            failures.append(
                f"{name}: statement coverage {statement_pct:.2f}% < {MODULE_MIN:.0f}% "
                f"({covered}/{statements})"
            )
        if branches and branch_pct + 1e-9 < MODULE_MIN:
            failures.append(
                f"{name}: branch coverage {branch_pct:.2f}% < {MODULE_MIN:.0f}% "
                f"({branches_covered}/{branches})"
            )

    overall = _module(rows)
    if overall["statements"] + 1e-9 < OVERALL_MIN:
        failures.append(
            f"overall statement coverage {overall['statements']:.2f}% < {OVERALL_MIN:.0f}%"
        )
    if overall["branches"] + 1e-9 < OVERALL_MIN:
        failures.append(f"overall branch coverage {overall['branches']:.2f}% < {OVERALL_MIN:.0f}%")

    for package in CRITICAL_PACKAGES:
        prefix = f"src/ostium/{package}/"
        package_rows = [row for row in rows if str(row["path"]).startswith(prefix)]
        if not package_rows:
            continue
        result = _module(package_rows)
        if result["statements"] + 1e-9 < CRITICAL_MIN:
            failures.append(
                f"{package}/: statement coverage {result['statements']:.2f}% < {CRITICAL_MIN:.0f}%"
            )
        if result["branches"] + 1e-9 < CRITICAL_MIN:
            failures.append(
                f"{package}/: branch coverage {result['branches']:.2f}% < {CRITICAL_MIN:.0f}%"
            )

    print(
        f"overall: statements {overall['statements']:.2f}% "
        f"({int(sum(r['covered'] for r in rows))}/{int(sum(r['statements'] for r in rows))}), "
        f"branches {overall['branches']:.2f}% "
        f"({int(sum(r['branches_covered'] for r in rows))}/"
        f"{int(sum(r['branches'] for r in rows))})"
    )
    for package in CRITICAL_PACKAGES:
        prefix = f"src/ostium/{package}/"
        package_rows = [row for row in rows if str(row["path"]).startswith(prefix)]
        if package_rows:
            result = _module(package_rows)
            print(
                f"{package}/: statements {result['statements']:.2f}%, "
                f"branches {result['branches']:.2f}%"
            )

    if failures:
        print("\nCoverage gate failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\nCoverage gate passed.")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("coverage.json")
    raise SystemExit(main(target))
