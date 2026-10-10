"""Canonical serialisation and hashing used for config hashes and fingerprints."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> str:
    """Serialise ``obj`` to deterministic JSON (sorted keys, no whitespace, no NaN).

    Raises:
        TypeError: if ``obj`` contains values JSON cannot represent (no silent ``str()``).
        ValueError: if ``obj`` contains NaN or infinity.
    """
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def sha256_hex(text: str) -> str:
    """Return the hex SHA-256 digest of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
