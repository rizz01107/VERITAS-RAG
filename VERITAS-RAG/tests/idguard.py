"""Guard against over-long pytest node ids (breaks PYTEST_CURRENT_TEST on Windows)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

MAX_NODEID_CHARS = 1000  # far below the 32767 Windows limit; real ids here are < 200


class _HasNodeId(Protocol):
    @property
    def nodeid(self) -> str: ...


def find_oversized_ids(items: Iterable[_HasNodeId], limit: int = MAX_NODEID_CHARS) -> list[str]:
    """Return ``"<length>: <first 80 chars>"`` for every id longer than ``limit``."""
    return [f"{len(i.nodeid)}: {i.nodeid[:80]}..." for i in items if len(i.nodeid) > limit]
