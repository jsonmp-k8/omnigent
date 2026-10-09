"""Tests for the OSV advisory delta judge in the Security Scan."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / ".github/scripts/security-scan/osv-delta.py"


def _report(path: Path, deps: list[tuple[str, str, list[tuple[str, list[str]]]]]) -> Path:
    """Write a pip-audit ``--format json`` report.

    :param path: Destination file.
    :param deps: ``(name, version, [(advisory id, fix versions), ...])`` per package.
    :returns: ``path``, for convenience.
    """
    payload: dict[str, Any] = {
        "dependencies": [
            {
                "name": name,
                "version": version,
                "vulns": [
                    {"id": vid, "fix_versions": fixes, "aliases": []} for vid, fixes in vulns
                ],
            }
            for name, version, vulns in deps
        ],
        "fixes": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run(base: list[Path], head: list[Path], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    summary = tmp_path / "summary.md"
    env = {
        **os.environ,
        "BASE_REPORTS": " ".join(str(p) for p in base),
        "HEAD_REPORTS": " ".join(str(p) for p in head),
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    return subprocess.run(
        [sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True, check=False
    )


_OPEN = [
    ("urllib3", "2.7.0", [("PYSEC-2026-4177", ["2.8.0"])]),
    ("pyjwt", "2.13.0", [("PYSEC-2026-4145", ["2.14.0"]), ("CVE-2026-102275", ["2.15.0"])]),
]


def test_single_advisory_bump_passes_while_others_remain_open(tmp_path: Path) -> None:
    """The deadlock case: fixing urllib3 must pass even though pyjwt is still open."""
    base = _report(tmp_path / "base.json", _OPEN)
    head = _report(tmp_path / "head.json", _OPEN[1:])  # urllib3 fixed, pyjwt untouched

    result = _run([base], [head], tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Resolved by this PR (1)" in result.stdout
    assert "::warning::2 advisory/advisories remain open" in result.stdout
    assert "::error::" not in result.stdout
    assert "Resolved 1" in (tmp_path / "summary.md").read_text()


def test_introducing_a_vulnerable_pin_fails(tmp_path: Path) -> None:
    """A PR that pins a version with an advisory the base lacks is blocked."""
    base = _report(tmp_path / "base.json", _OPEN)
    head = _report(
        tmp_path / "head.json",
        [*_OPEN, ("werkzeug", "3.1.8", [("CVE-2026-102598", ["3.1.9"])])],
    )

    result = _run([base], [head], tmp_path)

    assert result.returncode == 1
    assert "INTRODUCED by this PR (1)" in result.stdout
    assert "werkzeug" in result.stdout
    assert "::error::This PR pins 1 package version(s)" in result.stdout


def test_new_advisory_on_an_existing_package_counts_as_introduced(tmp_path: Path) -> None:
    """Same package, different advisory id: the base never had it, so it blocks."""
    base = _report(tmp_path / "base.json", [("pyjwt", "2.13.0", [("PYSEC-2026-4145", [])])])
    head = _report(tmp_path / "head.json", [("pyjwt", "2.12.0", [("PYSEC-2026-0001", [])])])

    result = _run([base], [head], tmp_path)

    assert result.returncode == 1
    assert "PYSEC-2026-0001" in result.stdout


def test_clean_head_and_base_pass_quietly(tmp_path: Path) -> None:
    base = _report(tmp_path / "base.json", [])
    head = _report(tmp_path / "head.json", [])

    result = _run([base], [head], tmp_path)

    assert result.returncode == 0
    assert "No new advisories introduced" in result.stdout
    assert not (tmp_path / "summary.md").exists()


def test_findings_merge_across_multiple_reports_and_tolerate_missing_files(
    tmp_path: Path,
) -> None:
    """The scan audits two resolution sets per side; a report pip-audit never wrote is empty."""
    base_a = _report(tmp_path / "base-a.json", _OPEN[:1])
    base_b = _report(tmp_path / "base-b.json", _OPEN[1:])
    head_a = _report(tmp_path / "head-a.json", _OPEN)
    missing = tmp_path / "never-written.json"

    result = _run([base_a, base_b], [head_a, missing], tmp_path)

    assert result.returncode == 0, result.stdout
    assert "::error::" not in result.stdout


def test_package_names_compare_case_insensitively(tmp_path: Path) -> None:
    base = _report(tmp_path / "base.json", [("PyJWT", "2.13.0", [("PYSEC-2026-4145", [])])])
    head = _report(tmp_path / "head.json", [("pyjwt", "2.13.0", [("PYSEC-2026-4145", [])])])

    assert _run([base], [head], tmp_path).returncode == 0
