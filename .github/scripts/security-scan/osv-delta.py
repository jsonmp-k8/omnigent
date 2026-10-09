#!/usr/bin/env python3
"""Judge a PR's uv.lock by the advisories it INTRODUCES, not by every open one.

Part of the single contributor Security Scan (.github/workflows/security-scan.yml).
The OSV step runs pip-audit over the full locked resolution of both the PR head
and its base branch; this script diffs the two reports. A PR fails only when
the head carries a (package, advisory) pair the base does not -- it pinned a
vulnerable version that main did not already have. Advisories already open on
the base are reported as warnings so they stay visible, but they are not the
PR's to fix: a one-advisory security bump must be able to merge while the other
open advisories still sit in the lockfile, otherwise every such PR deadlocks
against the ones it did not touch.

Env in:  BASE_REPORTS  whitespace-separated pip-audit ``--format json`` files for the base
         HEAD_REPORTS  whitespace-separated pip-audit ``--format json`` files for the head
Exit:    non-zero if the head introduces any advisory the base lacks; 0 otherwise.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

Finding = tuple[str, str]  # (package name, advisory id)


def load_findings(paths: list[str]) -> dict[Finding, tuple[str, list[str]]]:
    """Collect ``(name, advisory) -> (version, fix_versions)`` across pip-audit reports.

    :param paths: pip-audit JSON report files; a missing or empty file counts
        as no findings so a report pip-audit never wrote does not crash the gate.
    :returns: Every finding keyed by package name and advisory id.
    """
    findings: dict[Finding, tuple[str, list[str]]] = {}
    for raw in paths:
        path = Path(raw)
        if not path.is_file() or path.stat().st_size == 0:
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        for dep in report.get("dependencies", []):
            name = str(dep.get("name", "")).lower()
            for vuln in dep.get("vulns", []) or []:
                key = (name, str(vuln.get("id", "")))
                findings[key] = (str(dep.get("version", "")), list(vuln.get("fix_versions") or []))
    return findings


def _table(findings: dict[Finding, tuple[str, list[str]]]) -> str:
    rows = sorted(findings.items())
    width = max((len(name) for (name, _), _ in rows), default=4)
    lines = [f"{'Name':<{width}}  Version  ID                 Fix Versions"]
    for (name, vuln_id), (version, fixes) in rows:
        lines.append(f"{name:<{width}}  {version:<8} {vuln_id:<18} {','.join(fixes)}")
    return "\n".join(lines)


def main() -> int:
    base = load_findings(os.environ.get("BASE_REPORTS", "").split())
    head = load_findings(os.environ.get("HEAD_REPORTS", "").split())

    introduced = {k: v for k, v in head.items() if k not in base}
    resolved = {k: v for k, v in base.items() if k not in head}
    carried = {k: v for k, v in head.items() if k in base}

    summary: list[str] = []
    if resolved:
        print(f"Resolved by this PR ({len(resolved)}):\n{_table(resolved)}\n")
        summary.append(f"- Resolved {len(resolved)} advisory/advisories.")
    if carried:
        print(f"Already open on the base branch, not this PR's to fix ({len(carried)}):")
        print(_table(carried) + "\n")
        print(
            f"::warning::{len(carried)} advisory/advisories remain open on the base "
            "branch's uv.lock; they do not block this PR."
        )
        summary.append(f"- {len(carried)} advisory/advisories still open on the base branch.")
    if introduced:
        print(f"INTRODUCED by this PR ({len(introduced)}):\n{_table(introduced)}\n")
        print(
            f"::error::This PR pins {len(introduced)} package version(s) with advisories the "
            "base branch does not have. Bump to a fixed version (see Fix Versions above)."
        )
        summary.append(f"- **Introduced {len(introduced)} new advisory/advisories (blocking).**")
    else:
        print("No new advisories introduced by this PR.")

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary and summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write("### OSV advisory delta\n\n" + "\n".join(summary) + "\n")
    return 1 if introduced else 0


if __name__ == "__main__":
    sys.exit(main())
