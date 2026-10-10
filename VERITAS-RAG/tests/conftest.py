"""Shared fixtures. All papers/ids used in tests are synthetic placeholders."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core.config import PROJECT_ROOT
from app.core.logconfig import reset_logging
from tests.idguard import MAX_NODEID_CHARS, find_oversized_ids


@pytest.fixture(autouse=True)
def _clean_logging() -> Iterator[None]:
    reset_logging()
    yield
    reset_logging()
    logging.getLogger("veritas").setLevel(logging.NOTSET)


@pytest.fixture
def repo_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def write_yaml(tmp_path: Path) -> Callable[[str, dict[str, Any]], Path]:
    def _write(name: str, data: dict[str, Any]) -> Path:
        path = tmp_path / name
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        return path

    return _write


def make_paper(**overrides: Any) -> dict[str, Any]:
    """A fully valid *included* synthetic paper entry; override fields per test."""
    base: dict[str, Any] = {
        "paper_id": "synthetic-0001v1",
        "title": "Synthetic Paper One",
        "source": "other",
        "version": "v1",
        "source_url": "https://example.invalid/one",
        "license": "TEST-LICENSE",
        "license_source": "https://example.invalid/licence",
        "access_status": "freely_accessible",
        "license_verified_on": "2026-01-01",
        "access_checked_on": "2026-01-01",
        "local_path": "one.pdf",
        "sha256": "a" * 64,
        "status": "included",
        "split": "dev",
    }
    base.update(overrides)
    return base


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Abort collection on any OS if a test id is long enough to break Windows."""
    oversized = find_oversized_ids(items)
    if oversized:
        raise pytest.UsageError(
            f"test ids longer than {MAX_NODEID_CHARS} characters (do not pass binary data or "
            "large objects to parametrize; use short ids/factories): " + "; ".join(oversized)
        )
