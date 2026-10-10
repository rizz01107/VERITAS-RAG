"""Environment + quality-gate report for validating the project on another machine.

Runs pytest, ruff (lint and format check) and mypy through ``sys.executable -m`` (no
shell, so it behaves the same on Windows PowerShell, cmd and Linux) and records exact
versions. The JSON it writes is meant to be pasted back for review; nothing is guessed.
"""

from __future__ import annotations

import importlib.metadata
import json
import platform
import shutil
import subprocess  # noqa: S404 - fixed argv, no shell
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TAIL_LINES = 25
PACKAGES = ("pymupdf", "pydantic", "PyYAML", "pytest", "ruff", "mypy")
GATES: dict[str, list[str]] = {
    "pytest": ["-m", "pytest", "-q", "-p", "no:cacheprovider"],
    "ruff_check": ["-m", "ruff", "check", "."],
    "ruff_format": ["-m", "ruff", "format", "--check", "."],
    "mypy_strict": ["-m", "mypy"],
}


def collect_environment() -> dict[str, Any]:
    """Exact interpreter, OS and package versions (absent packages are reported as null)."""
    versions: dict[str, str | None] = {}
    for name in PACKAGES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": sys.version,
        "python_executable": sys.executable,
        "os_platform": platform.platform(),
        "os_version": platform.version(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "packages": versions,
        "pdflatex_available": shutil.which("pdflatex") is not None,
        "git_available": shutil.which("git") is not None,
    }


def run_gate(name: str, argv: list[str], cwd: Path, timeout_s: float = 1800.0) -> dict[str, Any]:
    """Run one gate; capture exit code and the last output lines (UTF-8, errors replaced)."""
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv built from constants
            [sys.executable, *argv],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"gate": name, "returncode": None, "passed": False, "error": type(exc).__name__}
    lines = (done.stdout + "\n" + done.stderr).strip().splitlines()
    return {
        "gate": name,
        "returncode": done.returncode,
        "passed": done.returncode == 0,
        "tail": lines[-TAIL_LINES:],
    }


def run_report(root: Path, gates: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """Collect the environment and run every gate."""
    selected = GATES if gates is None else gates
    results = [run_gate(name, argv, root) for name, argv in selected.items()]
    return {
        "environment": collect_environment(),
        "gates": results,
        "all_passed": all(bool(r["passed"]) for r in results),
    }


def write_report(report: dict[str, Any], path: Path) -> None:
    """Write the report as UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
