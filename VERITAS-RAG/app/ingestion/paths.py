"""Windows-safe path helpers. Operate on ``PurePath`` so Windows rules are testable anywhere."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path, PurePath

from app.core.errors import IngestionFailureError

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Return a file name that is valid on Windows, macOS and Linux.

    Replaces illegal characters, strips trailing dots/spaces (Windows silently drops
    them), avoids reserved device names (CON, NUL, COM1 ...) and caps the length.
    """
    cleaned = _ILLEGAL.sub("_", unicodedata.normalize("NFC", name)).strip().rstrip(". ")
    if not cleaned:
        cleaned = "_"
    if cleaned.split(".")[0].upper() in _RESERVED:
        cleaned = "_" + cleaned
    if len(cleaned) > max_len:
        stem, dot, ext = cleaned.rpartition(".")
        if dot and len(ext) <= 10:
            cleaned = stem[: max_len - len(ext) - 1] + "." + ext
        else:
            cleaned = cleaned[:max_len]
    return cleaned


def portable_source_name(path: PurePath, base: PurePath | None) -> str:
    """POSIX-style relative name for provenance; never leaks absolute (user) paths.

    Falls back to the bare file name when ``path`` is not under ``base``.
    """
    if base is not None:
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            pass
    return path.name


def ensure_within(base: Path, candidate: Path) -> Path:
    """Resolve ``candidate``; require it inside ``base`` (blocks ``..`` and symlink escapes)."""
    resolved_base = base.resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(resolved_base)
    except ValueError as exc:
        raise IngestionFailureError(
            "unsafe_path", "path escapes the allowed directory", "path_check"
        ) from exc
    return resolved
