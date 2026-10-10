"""Reading and writing parsed documents (deterministic JSON, atomic, path-safe)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.core.errors import IngestionFailureError
from app.ingestion.paths import ensure_within, sanitize_filename
from app.schemas.ingestion import ParsedDocument


def parsed_document_path(out_dir: Path, document_id: str) -> Path:
    """Where the parsed JSON for ``document_id`` lives (name sanitised, inside ``out_dir``)."""
    safe = sanitize_filename(document_id)
    if safe != document_id:  # sanitising can merge distinct ids; a hash suffix keeps them apart
        safe = f"{safe}-{hashlib.sha256(document_id.encode('utf-8')).hexdigest()[:8]}"
    return ensure_within(out_dir, out_dir / (safe + ".json"))


def write_parsed_document(doc: ParsedDocument, out_dir: Path) -> Path:
    """Write ``doc`` as UTF-8 JSON via a temp file + atomic replace. Derived data only."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = parsed_document_path(out_dir, doc.metadata.document_id)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, target)
    return target


def read_parsed_document(path: Path) -> ParsedDocument:
    """Load and re-validate a parsed document (provenance invariants are re-checked)."""
    try:
        return ParsedDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise IngestionFailureError(
            "parse_error", "cannot read parsed document", "io", path=path.name
        ) from exc
