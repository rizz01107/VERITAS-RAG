"""Heading detection, section tracking and title-candidate detection."""

from __future__ import annotations

import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from app.core.config import IngestionConfig
from app.ingestion.raw import RawBlock, RawPage

TITLE_RATIO = (
    1.5  # text this much larger than body text is a title/display text, not a section heading
)
TITLE_MIN_RATIO = 1.25  # page-1 text this much larger than body text is a title candidate
TITLE_TOP_FRACTION = 0.4
TITLE_MAX_LEADING_BLOCKS = 3  # the title is among the first few blocks in reading order
_MAX_HEADING_LINES = 2
_MAX_HEADING_WORDS = 15
_MAX_HEADING_CHARS = 150
_MAX_UNNUMBERED_BOLD_WORDS = 8
_MAX_LEVEL = 4

_DIGIT_NUMBERED = re.compile(r"^\d+(?:\.\d+)*\.?\s+\S")
_NUMBERED = re.compile(r"^(\d+(?:\.\d+){0,3}|[A-Z](?:\.\d+){0,3})\.?\s+\S")
_NUM_PREFIX = re.compile(r"^(\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)\.?\s+")
_CAPTION = re.compile(r"^(table|figure|fig\.)\s*\d", re.IGNORECASE)
_APPENDIX = re.compile(r"^(appendix|appendices|supplementary|supplemental)\b", re.IGNORECASE)
_LETTER_SECTION = re.compile(r"^[A-Z](?:\.\d+)*\.?\s+[A-Z]")
KNOWN_HEADINGS = frozenset(
    {
        "abstract",
        "introduction",
        "background",
        "related work",
        "preliminaries",
        "method",
        "methods",
        "methodology",
        "approach",
        "experiments",
        "experimental setup",
        "results",
        "discussion",
        "analysis",
        "conclusion",
        "conclusions",
        "limitations",
        "acknowledgments",
        "acknowledgements",
        "references",
        "bibliography",
        "literature cited",
        "appendix",
    }
)
REFERENCE_TITLES = frozenset({"references", "bibliography", "literature cited"})


@dataclass(frozen=True)
class HeadingInfo:
    """A detected heading."""

    title: str
    level: int
    structured: bool = False  # numbered or a well-known section name (vs. style-only)


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _strip_numbering(title: str) -> str:
    return _NUM_PREFIX.sub("", title).strip().lower()


def block_font_size(block: RawBlock) -> float | None:
    """Character-weighted median span size of a text block."""
    sizes: list[float] = []
    for line in block.lines:
        for span in line.spans:
            sizes.extend([span.size] * len(span.text.strip()))
    return statistics.median(sizes) if sizes else None


def body_font_size(pages: Sequence[RawPage]) -> float:
    """Character-weighted median font size across all text blocks (the 'body' size)."""
    sizes: list[float] = []
    for page in pages:
        for block in page.blocks:
            if block.kind != "text":
                continue
            for line in block.lines:
                for span in line.spans:
                    sizes.extend([span.size] * len(span.text.strip()))
    return statistics.median(sizes) if sizes else 10.0


def classify_heading(
    block: RawBlock, body_size: float, cfg: IngestionConfig, loose_ok: bool = True
) -> HeadingInfo | None:
    """Decide whether ``block`` is a section heading (None if not).

    Style-only headings (large/bold text that is neither numbered nor a well-known section
    name) are accepted only when ``loose_ok``; the pipeline sets it once a structured
    heading has been seen, so front matter such as author lines is not mistaken for a
    section (observed on a real pdfTeX paper).
    """
    if block.kind != "text" or not block.lines or len(block.lines) > _MAX_HEADING_LINES:
        return None
    title = _collapse(block.text)
    words = title.split()
    if not title or len(words) > _MAX_HEADING_WORDS or len(title) > _MAX_HEADING_CHARS:
        return None
    if _CAPTION.match(title) or title.endswith((".", ",", ";")):
        return None
    size = block_font_size(block)
    if size is None or size > TITLE_RATIO * body_size:
        return None
    spans = [s for line in block.lines for s in line.spans if s.text.strip()]
    all_bold = bool(spans) and all(s.bold for s in spans)
    larger = size >= cfg.heading_size_ratio * body_size
    numbered = bool(_NUMBERED.match(title))
    known = _strip_numbering(title) in KNOWN_HEADINGS or title.lower() in KNOWN_HEADINGS
    unnumbered_bold = (
        all_bold
        and len(words) <= _MAX_UNNUMBERED_BOLD_WORDS
        and title[0].isupper()
        and size >= 0.98 * body_size
    )
    structured = (larger or all_bold) and (numbered or known)
    loose = loose_ok and (unnumbered_bold or (larger and title[0].isupper()))
    if structured or loose:
        level = min(title.split()[0].count(".") + 1, _MAX_LEVEL) if numbered else 1
        return HeadingInfo(title=title, level=level, structured=bool(structured))
    return None


def is_reference_heading(title: str) -> bool:
    """True for 'References'-style headings (numbering ignored)."""
    return _strip_numbering(title) in REFERENCE_TITLES or title.lower() in REFERENCE_TITLES


def ends_references(title: str) -> bool:
    """True if a heading seen inside the reference list starts an appendix/supplement."""
    return bool(_APPENDIX.match(title) or _LETTER_SECTION.match(title))


def find_title_block(
    first_page_blocks: Sequence[RawBlock], body_size: float, page_height: float
) -> RawBlock | None:
    """The page-1 block with the largest font if it is clearly display text near the top.

    Requires size >= ``TITLE_MIN_RATIO`` x body size and a position in the top
    ``TITLE_TOP_FRACTION`` of the page. Such a block is the document title, not a section.
    """
    best: tuple[float, RawBlock] | None = None
    for block in first_page_blocks[:TITLE_MAX_LEADING_BLOCKS]:
        size = block_font_size(block) if block.kind == "text" else None
        if size is None or size < TITLE_MIN_RATIO * body_size:
            continue
        text = _collapse(block.text)
        if block.bbox[1] > TITLE_TOP_FRACTION * page_height or not text:
            continue
        if (
            _DIGIT_NUMBERED.match(text)
            or _strip_numbering(text) in KNOWN_HEADINGS
            or _APPENDIX.match(text)
        ):
            continue  # a numbered or well-known section heading is never the document title
        if best is None or size > best[0]:
            best = (size, block)
    return best[1] if best else None
