"""Minimal ``.env`` loader. Explicit (called by the CLI), never run at import time."""

from __future__ import annotations

import os
import re
from collections.abc import MutableMapping
from pathlib import Path

from app.core.errors import ConfigError

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def load_dotenv(
    path: Path,
    environ: MutableMapping[str, str] | None = None,
    override: bool = False,
) -> list[str]:
    """Load ``KEY=VALUE`` lines into ``environ``; return the variable *names* set.

    Existing variables win unless ``override`` is true. Error messages contain line
    numbers only, never line content (it may be a secret).

    Raises:
        ConfigError: if the file is missing or a line is not ``KEY=VALUE``.
    """
    target = os.environ if environ is None else environ
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError("cannot read env file", path=str(path), reason=str(exc)) from exc
    loaded: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :]
        key, sep, raw = stripped.partition("=")
        key = key.strip()
        if not sep or not _KEY.match(key):
            raise ConfigError("malformed env file line", path=str(path), line=lineno)
        if key in target and not override:
            continue
        target[key] = _parse_value(raw)
        loaded.append(key)
    return loaded
