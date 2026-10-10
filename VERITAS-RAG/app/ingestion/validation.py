"""File-level validation before any parser touches the bytes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.core.config import IngestionConfig
from app.core.errors import IngestionFailureError

PDF_MAGIC = b"%PDF-"
_MAGIC_WINDOW = 1024  # the PDF spec tolerates junk before the header within this window
_BYTES_PER_MB = 1024 * 1024


@dataclass(frozen=True)
class ValidatedFile:
    """Bytes of a file that passed validation (read once; parsers never reopen the path)."""

    path: Path
    data: bytes
    sha256: str


def validate_pdf_file(path: Path, cfg: IngestionConfig) -> ValidatedFile:
    """Validate type, size and header, then read the file fully into memory.

    Reading into memory (instead of handing a path to the parser) avoids Windows file
    locks and guarantees the hash describes exactly the bytes that were parsed.

    Raises:
        IngestionFailureError: with a specific ``failure_code`` for every rejection.
    """
    stage = "validation"
    if not path.exists():
        raise IngestionFailureError("file_not_found", "file does not exist", stage, path=path.name)
    if not path.is_file():
        raise IngestionFailureError(
            "not_a_file", "path is not a regular file", stage, path=path.name
        )
    if path.suffix.lower() not in cfg.allowed_extensions:
        raise IngestionFailureError(
            "unsupported_type", "file extension is not allowed", stage, suffix=path.suffix
        )
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise IngestionFailureError(
            "not_a_file", "cannot stat file", stage, reason=str(exc)
        ) from exc
    if size == 0:
        raise IngestionFailureError("empty_file", "file is empty (0 bytes)", stage)
    if size > cfg.max_file_size_mb * _BYTES_PER_MB:
        raise IngestionFailureError(
            "file_too_large",
            "file exceeds max_file_size_mb",
            stage,
            size=size,
            limit_mb=cfg.max_file_size_mb,
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise IngestionFailureError(
            "not_a_file", "cannot read file", stage, reason=str(exc)
        ) from exc
    if PDF_MAGIC not in data[:_MAGIC_WINDOW]:
        raise IngestionFailureError("not_a_pdf", "missing %PDF- header", stage)
    return ValidatedFile(path=path, data=data, sha256=hashlib.sha256(data).hexdigest())
