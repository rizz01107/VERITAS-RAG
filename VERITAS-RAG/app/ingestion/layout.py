"""Layout heuristics: duplicate removal, running-header removal and reading order."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

from app.core.config import IngestionConfig
from app.ingestion.raw import BBox, RawBlock, RawLine, RawPage

_PAGE_NUMBER = re.compile(r"^\W*(page\s+)?\d{1,4}(\s*(of|/)\s*\d{1,4})?\W*$", re.IGNORECASE)
_MIN_COLUMN_BLOCKS = 2
_MIN_VERTICAL_OVERLAP = 0.3
_MAX_BOILERPLATE_LINES = 2


def _normalize(text: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", text.lower())).strip()


def _iou(a: BBox, b: BBox) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def dedupe_blocks(blocks: Sequence[RawBlock]) -> tuple[list[RawBlock], int]:
    """Drop blocks with identical text at (almost) the same position (overprinted text).

    Blocks are bucketed by normalised text, so the cost is linear in practice.
    """
    kept: list[RawBlock] = []
    by_text: dict[str, list[RawBlock]] = {}
    removed = 0
    for block in blocks:
        text = _normalize(block.text)
        bucket = by_text.setdefault(text, [])
        if any(_iou(k.bbox, block.bbox) >= 0.8 for k in bucket):
            removed += 1
        else:
            bucket.append(block)
            kept.append(block)
    return kept, removed


def find_boilerplate(pages: Sequence[RawPage], cfg: IngestionConfig) -> dict[int, set[int]]:
    """Locate running headers/footers and bare page numbers.

    A block is boilerplate if it lies in the top/bottom margin band, has at most two
    lines, and either looks like a page number or repeats (digits normalised) on at
    least ``max(boilerplate_min_pages, fraction * n_pages)`` pages. Returns
    ``{page_number: {block_index, ...}}``.
    """
    band = cfg.margin_band_fraction
    candidates: dict[tuple[int, int], str] = {}
    seen_on: dict[str, set[int]] = {}
    for page in pages:
        for index, block in enumerate(page.blocks):
            if block.kind != "text" or len(block.lines) > _MAX_BOILERPLATE_LINES:
                continue
            centre = (block.bbox[1] + block.bbox[3]) / 2
            if not (centre < band * page.height or centre > (1 - band) * page.height):
                continue
            key = _normalize(block.text)
            candidates[(page.number, index)] = key
            seen_on.setdefault(key, set()).add(page.number)
    needed = max(cfg.boilerplate_min_pages, math.ceil(cfg.boilerplate_page_fraction * len(pages)))
    result: dict[int, set[int]] = {}
    for (page_no, index), key in candidates.items():
        text = pages[page_no - 1].blocks[index].text
        repeated = len(seen_on[key]) >= needed
        if _PAGE_NUMBER.match(text) or repeated:
            result.setdefault(page_no, set()).add(index)
    return result


def _vertical_overlap(a: BBox, b: BBox) -> float:
    overlap = min(a[3], b[3]) - max(a[1], b[1])
    shorter = min(a[3] - a[1], b[3] - b[1])
    return overlap / shorter if shorter > 0 and overlap > 0 else 0.0


def order_blocks(
    blocks: Sequence[RawBlock], width: float, cfg: IngestionConfig
) -> tuple[list[tuple[RawBlock, int | None]], int]:
    """Return blocks in reading order with their column index and the page's column count.

    Single-column pages are sorted top-to-bottom. A page is treated as two-column only
    when at least two blocks lie in each half *and* a left and a right block overlap
    vertically. Full-width ("spanning") blocks split the page into segments; inside a
    segment the left column is read before the right one. Three or more columns are not
    detected (documented limitation).
    """
    if not blocks:
        return [], 1
    mid = width / 2
    gutter = cfg.column_gutter_fraction * width

    def side(block: RawBlock) -> str:
        x0, _, x1, _ = block.bbox
        if x0 < mid - gutter and x1 > mid + gutter:
            return "span"
        return "left" if (x0 + x1) / 2 < mid else "right"

    by_y = sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))
    left = [b for b in by_y if side(b) == "left"]
    right = [b for b in by_y if side(b) == "right"]
    two_column = (
        cfg.detect_columns
        and len(left) >= _MIN_COLUMN_BLOCKS
        and len(right) >= _MIN_COLUMN_BLOCKS
        and any(
            _vertical_overlap(lb.bbox, rb.bbox) >= _MIN_VERTICAL_OVERLAP
            for lb in left
            for rb in right
        )
    )
    if not two_column:
        return [(b, None) for b in by_y], 1

    ordered: list[tuple[RawBlock, int | None]] = []
    seg_left: list[RawBlock] = []
    seg_right: list[RawBlock] = []

    def flush() -> None:
        ordered.extend((b, 0) for b in sorted(seg_left, key=lambda x: x.bbox[1]))
        ordered.extend((b, 1) for b in sorted(seg_right, key=lambda x: x.bbox[1]))
        seg_left.clear()
        seg_right.clear()

    for block in by_y:
        kind = side(block)
        if kind == "span":
            flush()
            ordered.append((block, None))
        elif kind == "left":
            seg_left.append(block)
        else:
            seg_right.append(block)
    flush()
    return ordered, 2


_SIZE_CHANGE = 0.15


def _line_style(line: RawLine) -> tuple[float, bool]:
    spans = [s for s in line.spans if s.text.strip()]
    if not spans:
        return 0.0, False
    sizes = sorted(s.size for s in spans)
    return sizes[len(sizes) // 2], all(s.bold for s in spans)


def split_on_style_change(blocks: Sequence[RawBlock]) -> list[RawBlock]:
    """Split blocks where consecutive lines change font size or boldness.

    PyMuPDF groups lines by proximity, so a heading directly above a paragraph often ends
    up in the same block. Splitting at style changes lets heading detection work per line
    group. A split needs a size change above 15% or a switch of the all-bold property.
    """
    result: list[RawBlock] = []
    for block in blocks:
        if block.kind != "text" or len(block.lines) < 2:
            result.append(block)
            continue
        groups: list[list[RawLine]] = [[block.lines[0]]]
        prev_size, prev_bold = _line_style(block.lines[0])
        for line in block.lines[1:]:
            size, bold = _line_style(line)
            changed = bold != prev_bold or (
                prev_size > 0 and abs(size - prev_size) / prev_size > _SIZE_CHANGE
            )
            if changed:
                groups.append([line])
            else:
                groups[-1].append(line)
            prev_size, prev_bold = size, bold
        for group in groups:
            x0 = min(ln.bbox[0] for ln in group)
            y0 = min(ln.bbox[1] for ln in group)
            x1 = max(ln.bbox[2] for ln in group)
            y1 = max(ln.bbox[3] for ln in group)
            result.append(RawBlock((x0, y0, x1, y1), tuple(group)))
    return result
