"""PyMuPDF backend (AGPL-3.0 / commercial dual licence; see docs/LICENSING.md).

All PyMuPDF specifics live here. Documents are opened from in-memory bytes so no file
handle is held (important on Windows) and the parsed bytes are exactly the hashed bytes.
"""

from __future__ import annotations

import os
from typing import Any

# PyMuPDF prints an advisory to stdout unless this is set before import; stdout carries CLI JSON.
os.environ.setdefault("PYMUPDF_SUGGEST_LAYOUT_ANALYZER", "0")

import pymupdf  # noqa: E402

from app.core.config import IngestionConfig
from app.core.errors import IngestionFailureError
from app.ingestion.raw import RawBlock, RawDocument, RawLine, RawPage, RawSpan

# PyMuPDF prints advisory messages to stdout, which would corrupt the CLI JSON output.
pymupdf.set_messages(pylogging=True)

_FALLBACK_WIDTH = 612.0
_FALLBACK_HEIGHT = 792.0
_BOLD_FLAG = 16
_TEXT_BLOCK = 0
_MIN_TABLE_ROWS = 2
_MIN_TABLE_COLS = 2
_ROW_TOLERANCE = 0.5
_MAX_DRAWINGS = 20000
_RULE_THICKNESS = 2.0
_MIN_RULE_WIDTH = 30.0
_RULE_EXTENT_TOL = 3.0
_MIN_TABLE_RULES = 2
_CELL_GAP_FACTOR = 0.8  # a gap wider than 0.8 x word height separates table cells


class PyMuPdfBackend:
    """Extract backend-neutral pages from PDF bytes."""

    name = "pymupdf"

    @property
    def version(self) -> str:
        return str(pymupdf.__version__)

    def extract(self, data: bytes, cfg: IngestionConfig) -> RawDocument:
        """Open ``data`` and extract all pages.

        Raises:
            IngestionFailureError: corrupted, encrypted, empty or too large documents.
        """
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:  # C library raises several unrelated error types
            raise IngestionFailureError(
                "corrupted", "PDF could not be opened", "open", error_type=type(exc).__name__
            ) from exc
        try:
            return self._extract_open(doc, cfg)
        except IngestionFailureError:
            raise
        except Exception as exc:  # foreign library: any error type is possible
            raise IngestionFailureError(
                "parse_error", "unexpected parser error", "extract", error_type=type(exc).__name__
            ) from exc
        finally:
            doc.close()

    def _extract_open(self, doc: Any, cfg: IngestionConfig) -> RawDocument:
        if doc.needs_pass:
            raise IngestionFailureError(
                "encrypted", "PDF requires a password; passwords are never guessed", "open"
            )
        if doc.page_count == 0:
            raise IngestionFailureError("empty_document", "PDF contains no pages", "open")
        if doc.page_count > cfg.max_pages:
            raise IngestionFailureError(
                "too_many_pages",
                "PDF exceeds max_pages",
                "open",
                pages=doc.page_count,
                limit=cfg.max_pages,
            )
        pages = tuple(self._extract_page(doc, i, cfg) for i in range(doc.page_count))
        return RawDocument(
            pages=pages,
            info={k: str(v) for k, v in (doc.metadata or {}).items() if v},
            repaired=bool(getattr(doc, "is_repaired", False)),
            owner_restricted=bool(doc.is_encrypted),
        )

    def _extract_page(self, doc: Any, index: int, cfg: IngestionConfig) -> RawPage:
        """Extract one page; a damaged page becomes an empty page plus a warning, not a crash."""
        try:
            return self._extract_page_unsafe(doc[index], index + 1, cfg)
        except Exception as exc:
            message = f"page could not be processed: {type(exc).__name__}"
            return RawPage(
                index + 1,
                _FALLBACK_WIDTH,
                _FALLBACK_HEIGHT,
                0,
                (),
                0,
                (("page_load_failed", message),),
            )

    def _extract_page_unsafe(self, page: Any, number: int, cfg: IngestionConfig) -> RawPage:
        warnings: list[tuple[str, str]] = []
        rect = page.rect
        try:
            raw = page.get_text("dict")
        except Exception as exc:
            warnings.append(
                ("page_extraction_failed", f"text extraction failed: {type(exc).__name__}")
            )
            return RawPage(
                number,
                float(rect.width),
                float(rect.height),
                int(page.rotation),
                (),
                0,
                tuple(warnings),
            )
        n_images = 0
        text_blocks: list[RawBlock] = []
        for block in raw.get("blocks", []):
            if block.get("type") != _TEXT_BLOCK:
                n_images += 1
                continue
            lines = []
            for line in block.get("lines", []):
                spans = tuple(
                    RawSpan(
                        s["text"],
                        float(s["size"]),
                        bool(s["flags"] & _BOLD_FLAG) or "bold" in s["font"].lower(),
                    )
                    for s in line.get("spans", [])
                    if s.get("text")
                )
                if spans and "".join(s.text for s in spans).strip():
                    lines.append(RawLine(spans, tuple(float(v) for v in line["bbox"])))  # type: ignore[arg-type]
            if lines:
                text_blocks.append(RawBlock(tuple(float(v) for v in block["bbox"]), tuple(lines)))  # type: ignore[arg-type]
        try:
            n_images = max(n_images, len(page.get_images()))
        except Exception:
            warnings.append(("image_count_failed", "could not count images"))
        blocks = text_blocks
        n_lines = sum(len(b.lines) for b in text_blocks)
        if cfg.detect_tables and n_lines > cfg.table_detection_max_lines:
            warnings.append(
                (
                    "table_detection_skipped",
                    f"{n_lines} lines exceed table_detection_max_lines; tables not detected",
                )
            )
        elif cfg.detect_tables:
            blocks, table_warning = self._with_tables(page, text_blocks, cfg)
            if table_warning:
                warnings.append(table_warning)
        return RawPage(
            number,
            float(rect.width),
            float(rect.height),
            int(page.rotation),
            tuple(blocks),
            n_images,
            tuple(warnings),
        )

    @staticmethod
    def _rows_from_words(words: list[tuple[Any, ...]]) -> tuple[tuple[str, ...], ...]:
        """Rebuild table rows from words: cluster by vertical position, split cells at gaps.

        The library's column guess for rule-only (booktabs-style) tables cut words in two
        on real pdfTeX output, and TeX emits each cell as its own text line, so only the
        bounding box is trusted. Words whose vertical centres differ by less than half a
        word height share a row; a horizontal gap wider than ``_CELL_GAP_FACTOR`` x the
        word height starts a new cell.
        """
        ordered = sorted(words, key=lambda w: (float(w[1]) + float(w[3])) / 2)
        clusters: list[list[tuple[Any, ...]]] = []
        for word in ordered:
            centre = (float(word[1]) + float(word[3])) / 2
            height = float(word[3]) - float(word[1])
            if clusters:
                last = clusters[-1]
                last_centre = sum((float(w[1]) + float(w[3])) / 2 for w in last) / len(last)
                if abs(centre - last_centre) < _ROW_TOLERANCE * height:
                    last.append(word)
                    continue
            clusters.append([word])
        rows: list[tuple[str, ...]] = []
        for line in clusters:
            line.sort(key=lambda w: float(w[0]))
            height = max(float(w[3]) - float(w[1]) for w in line)
            cells: list[list[str]] = [[str(line[0][4])]]
            for prev, cur in zip(line, line[1:], strict=False):
                if float(cur[0]) - float(prev[2]) > _CELL_GAP_FACTOR * height:
                    cells.append([])
                cells[-1].append(str(cur[4]))
            rows.append(tuple(" ".join(c) for c in cells))
        return tuple(rows)

    @staticmethod
    def _horizontal_rules(page: Any) -> list[tuple[float, float, float]]:
        """Thin horizontal strokes as ``(y, x0, x1)``: line items and hairline filled rects."""
        rules: list[tuple[float, float, float]] = []
        for drawing in page.get_drawings()[:_MAX_DRAWINGS]:
            for item in drawing.get("items", []):
                if item[0] == "l" and abs(item[1].y - item[2].y) < _RULE_THICKNESS:
                    x0, x1 = sorted((float(item[1].x), float(item[2].x)))
                    rules.append((float(item[1].y), x0, x1))
                elif item[0] == "re" and item[1].height <= _RULE_THICKNESS:
                    rect = item[1]
                    rules.append(
                        ((float(rect.y0) + float(rect.y1)) / 2, float(rect.x0), float(rect.x1))
                    )
        return [r for r in rules if r[2] - r[1] >= _MIN_RULE_WIDTH]

    @classmethod
    def _rule_tables(cls, page: Any, cfg: IngestionConfig) -> list[RawBlock]:
        """Detect rule-only (booktabs-style) tables from equal-width horizontal rules.

        Consecutive rules with the same x-extent form one table; its bounding box is
        top rule to bottom rule. Text inside is rebuilt row by row (see ``_rows_from_words``).
        The library's own column guess is not used: it cut words in two on real pdfTeX output
        and missed tables altogether in other layouts.
        """
        limit = cfg.table_max_page_fraction * float(page.rect.height)
        groups: list[list[tuple[float, float, float]]] = []
        for rule in sorted(cls._horizontal_rules(page)):
            for group in groups:
                last = group[-1]
                same_extent = (
                    abs(last[1] - rule[1]) < _RULE_EXTENT_TOL
                    and abs(last[2] - rule[2]) < _RULE_EXTENT_TOL
                )
                if same_extent and rule[0] - group[0][0] <= limit:
                    group.append(rule)
                    break
            else:
                groups.append([rule])
        found: list[RawBlock] = []
        for group in groups:
            if len(group) < _MIN_TABLE_RULES:
                continue
            bbox = (min(r[1] for r in group), group[0][0], max(r[2] for r in group), group[-1][0])
            clip = pymupdf.Rect(bbox[0], bbox[1] + 0.5, bbox[2], bbox[3] - 0.5)
            rows = cls._rows_from_words(page.get_text("words", clip=clip))
            if len(rows) >= _MIN_TABLE_ROWS and any(len(r) >= _MIN_TABLE_COLS for r in rows):
                found.append(RawBlock(bbox, (), "table", rows))
        return found

    @classmethod
    def _find_table_blocks(cls, page: Any, cfg: IngestionConfig) -> list[RawBlock]:
        tables: list[RawBlock] = []

        def collect(found: Any, max_height: float) -> None:
            for table in found:
                rows = tuple(
                    tuple((c or "").replace("\n", " ").strip() for c in row)
                    for row in table.extract()
                )
                bbox = tuple(float(v) for v in table.bbox)
                if bbox[3] - bbox[1] > max_height:
                    continue
                ok = len(rows) >= _MIN_TABLE_ROWS and rows and len(rows[0]) >= _MIN_TABLE_COLS
                if ok and any(any(r) for r in rows):
                    tables.append(RawBlock(bbox, (), "table", rows))  # type: ignore[arg-type]

        collect(page.find_tables().tables, float("inf"))
        if not tables and cfg.detect_unruled_tables:
            tables.extend(cls._rule_tables(page, cfg))
        return tables

    @classmethod
    def _with_tables(
        cls, page: Any, blocks: list[RawBlock], cfg: IngestionConfig
    ) -> tuple[list[RawBlock], tuple[str, str] | None]:
        try:
            tables = cls._find_table_blocks(page, cfg)
        except Exception as exc:
            return blocks, (
                "table_detection_failed",
                f"table detection failed: {type(exc).__name__}",
            )
        if not tables:
            return blocks, None

        def inside_table(block: RawBlock) -> bool:
            cx = (block.bbox[0] + block.bbox[2]) / 2
            cy = (block.bbox[1] + block.bbox[3]) / 2
            return any(
                t.bbox[0] <= cx <= t.bbox[2] and t.bbox[1] <= cy <= t.bbox[3] for t in tables
            )

        return [b for b in blocks if not inside_table(b)] + tables, None
