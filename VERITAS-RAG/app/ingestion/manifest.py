"""Corpus manifest loading, fingerprinting and on-disk verification."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import ValidationError

from app.core.config import read_yaml_mapping
from app.core.errors import ConfigError, ManifestError
from app.core.hashing import canonical_json, sha256_hex
from app.schemas.enums import ManifestStatus
from app.schemas.manifest import CorpusManifest

_READ_BLOCK = 1 << 20


def sha256_file(path: Path) -> str:
    """Hex SHA-256 of a file, streamed."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(_READ_BLOCK), b""):
                digest.update(block)
    except OSError as exc:
        raise ManifestError("cannot read file for hashing", path=str(path)) from exc
    return digest.hexdigest()


def load_manifest(path: Path) -> CorpusManifest:
    """Load and validate a manifest YAML file.

    Raises:
        ManifestError: if the file is unreadable, malformed or violates any manifest rule.
    """
    try:
        data = read_yaml_mapping(path)
    except ConfigError as exc:
        raise ManifestError(exc.message, **exc.context) from exc
    try:
        return CorpusManifest.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ManifestError(f"invalid manifest: {problems}", path=str(path)) from exc


def corpus_fingerprint(manifest: CorpusManifest) -> str:
    """Stable dataset version id derived from included papers (``corpus-<12 hex>``).

    Depends on paper id, version, file hash and split only, so it is independent of
    ordering and of descriptive text edits, and changes if any included file changes.
    """
    included = sorted(
        (p.paper_id, p.version, p.sha256, p.split.value if p.split else None)
        for p in manifest.papers
        if p.status == ManifestStatus.INCLUDED
    )
    if not included:
        return "corpus-empty"
    return "corpus-" + sha256_hex(canonical_json(included))[:12]


def verify_files(manifest: CorpusManifest, raw_root: Path) -> list[str]:
    """Check included papers' files exist under ``raw_root`` and match the recorded hash."""
    problems: list[str] = []
    for paper in manifest.papers:
        if paper.status != ManifestStatus.INCLUDED or paper.local_path is None:
            continue
        file_path = (
            paper.local_path if paper.local_path.is_absolute() else raw_root / paper.local_path
        )
        if not file_path.is_file():
            problems.append(f"{paper.paper_id}: file missing at {file_path}")
        elif sha256_file(file_path) != paper.sha256:
            problems.append(f"{paper.paper_id}: sha256 mismatch for {file_path}")
    return problems
