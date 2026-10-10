"""Regression tests for the Windows environment-variable limit that broke two test phases."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.idguard import MAX_NODEID_CHARS, find_oversized_ids
from tests.plugins.winlimit import (
    WINDOWS_ENV_VALUE_LIMIT,
    LimitedEnviron,
    check_env_value_length,
)

pytestmark = pytest.mark.unit


@dataclass
class _Item:
    nodeid: str


def test_guard_flags_binary_payload_ids_and_accepts_normal_ids() -> None:
    huge = _Item("t.py::test_x[" + "\\xc2\\xb5" * 50_000 + "]")  # what bytes in parametrize produce
    assert len(find_oversized_ids([_Item("t.py::test_x[ok]"), huge])) == 1
    assert find_oversized_ids([_Item("t.py::test_x[" + "a" * (MAX_NODEID_CHARS - 20) + "]")]) == []


def test_no_collected_test_id_is_oversized(request: pytest.FixtureRequest) -> None:
    assert find_oversized_ids(request.session.items) == []
    assert max(len(i.nodeid) for i in request.session.items) < WINDOWS_ENV_VALUE_LIMIT


@pytest.mark.edge
def test_limit_check_boundary_is_exact() -> None:
    check_env_value_length("x" * WINDOWS_ENV_VALUE_LIMIT)  # 32767 characters: accepted
    check_env_value_length("")
    with pytest.raises(
        ValueError, match="the environment variable is longer than 32767 characters"
    ):
        check_env_value_length("x" * (WINDOWS_ENV_VALUE_LIMIT + 1))  # 32768: rejected


def _identity(text: str) -> str:
    return text


@pytest.mark.edge
def test_emulation_layer_boundary_without_touching_the_real_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise ``LimitedEnviron`` on in-memory storage with a fake ``putenv``.

    The real ``os.environ`` is never written, so this is valid on actual Windows, where a
    real 32767-character value (plus the variable name) is itself rejected by the OS.
    """
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(os, "putenv", lambda key, value: calls.append((key, value)))
    storage: dict[str, str] = {}
    env = LimitedEnviron(storage, _identity, _identity, _identity, _identity)

    env["VERITAS_FAKE_AT_LIMIT"] = "x" * WINDOWS_ENV_VALUE_LIMIT
    assert len(storage["VERITAS_FAKE_AT_LIMIT"]) == WINDOWS_ENV_VALUE_LIMIT
    assert len(calls) == 1

    with pytest.raises(ValueError, match="longer than 32767 characters"):
        env["VERITAS_FAKE_OVER_LIMIT"] = "x" * (WINDOWS_ENV_VALUE_LIMIT + 1)
    assert "VERITAS_FAKE_OVER_LIMIT" not in storage and len(calls) == 1  # rejected before putenv

    assert "VERITAS_FAKE_AT_LIMIT" not in os.environ  # the real environment was never touched
    assert "VERITAS_FAKE_OVER_LIMIT" not in os.environ


@pytest.mark.integration
def test_binary_fixture_tests_run_under_the_windows_env_limit(repo_root: Path) -> None:
    """Structured-failure tests (encrypted/scanned PDFs) must pass under the env limit."""
    done = subprocess.run(  # noqa: S603 - fixed argv
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.plugins.winlimit",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/integration/test_ingestion_pipeline.py",
            "-k",
            "test_failures_are_structured",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    assert done.returncode == 0, done.stdout[-1500:] + done.stderr[-500:]
    assert "7 passed" in done.stdout
