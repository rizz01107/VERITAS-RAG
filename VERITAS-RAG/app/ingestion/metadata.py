"""Title/author/year resolution with explicit provenance of each value."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.manifest import PaperEntry

_JUNK_TITLE = re.compile(
    r"^(untitled|microsoft word\b|microsoft powerpoint\b)|\.(docx?|tex|dvi|pdf|pptx?)$",
    re.IGNORECASE,
)
_MIN_TITLE_CHARS = 4
_AUTHOR_SPLIT = re.compile(r"\s*(?:;|,|\band\b|&)\s*", re.IGNORECASE)


@dataclass(frozen=True)
class ResolvedMetadata:
    """Resolved values and where each came from."""

    title: str
    title_source: str
    authors: tuple[str, ...]
    authors_source: str
    year: int | None


def resolve_metadata(
    info: dict[str, str],
    layout_title: str | None,
    paper: PaperEntry | None,
    file_stem: str,
) -> ResolvedMetadata:
    """Pick metadata by trust order: manifest > PDF metadata > page-1 layout > file name.

    Authors come only from the manifest or the PDF info dict (layout-based author
    extraction is too error-prone). The publication year comes only from the manifest;
    the PDF creation date is *not* a publication year and is never used.
    """
    pdf_title = (info.get("title") or "").strip()
    if paper is not None:
        title, title_source = paper.title, "manifest"
    elif len(pdf_title) >= _MIN_TITLE_CHARS and not _JUNK_TITLE.search(pdf_title):
        title, title_source = pdf_title, "pdf_metadata"
    elif layout_title:
        title, title_source = layout_title, "layout"
    else:
        title, title_source = (file_stem or "untitled"), "filename"

    if paper is not None and paper.authors:
        authors, authors_source = paper.authors, "manifest"
    else:
        pdf_author = (info.get("author") or "").strip()
        parts = tuple(p.strip() for p in _AUTHOR_SPLIT.split(pdf_author) if p.strip())
        authors, authors_source = (parts, "pdf_metadata") if parts else ((), "unknown")
    return ResolvedMetadata(
        title, title_source, authors, authors_source, paper.year if paper else None
    )
