"""Explicit, polite download of manifest-listed PDFs (never an automatic corpus crawl).

Downloads only what the caller names, enforces https, a size cap and a %PDF- header,
writes atomically, refuses to overwrite, and never changes licence/verification fields.
"""

from __future__ import annotations

import hashlib
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from app.core.errors import IngestionFailureError
from app.ingestion.paths import ensure_within
from app.ingestion.validation import PDF_MAGIC

USER_AGENT = "veritas-rag-research/0.1 (personal research use; contact: see repository)"
_CHUNK = 1 << 16
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def download_pdf(
    url: str,
    dest: Path,
    raw_root: Path,
    max_bytes: int,
    timeout_s: float = 30.0,
    overwrite: bool = False,
) -> str:
    """Download ``url`` to ``dest`` (inside ``raw_root``) and return its SHA-256.

    Plain http is accepted only for localhost (used by tests).

    Raises:
        IngestionFailureError: unsafe URL/path, network failure, oversize or non-PDF content.
    """
    stage = "download"
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in _LOCAL_HOSTS
    ):
        raise IngestionFailureError(
            "unsupported_type", "only https URLs are allowed", stage, scheme=parsed.scheme
        )
    target = ensure_within(raw_root, dest)
    if target.exists() and not overwrite:
        raise IngestionFailureError(
            "unsafe_path", "destination exists; refusing to overwrite", stage, path=target.name
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    digest = hashlib.sha256()
    total = 0
    first = b""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 - scheme validated above
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response, tmp.open("wb") as out:  # noqa: S310
            while chunk := response.read(_CHUNK):
                total += len(chunk)
                if total > max_bytes:
                    raise IngestionFailureError(
                        "file_too_large", "download exceeds size limit", stage, limit=max_bytes
                    )
                if not first:
                    first = chunk[:1024]
                digest.update(chunk)
                out.write(chunk)
        if PDF_MAGIC not in first:
            raise IngestionFailureError("not_a_pdf", "downloaded content is not a PDF", stage)
        os.replace(tmp, target)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        tmp.unlink(missing_ok=True)
        raise IngestionFailureError(
            "parse_error", "download failed", stage, reason=type(exc).__name__
        ) from exc
    except IngestionFailureError:
        tmp.unlink(missing_ok=True)
        raise
    return digest.hexdigest()
