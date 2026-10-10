"""Ingestion pipeline: validate -> extract -> layout -> sections -> clean -> offsets.

Document-level problems never raise: they are returned as structured
:class:`IngestionFailure` objects. Unexpected exceptions *inside our own code* do raise
(they are bugs); only the backend boundary converts foreign errors to failures.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.config import IngestionConfig
from app.core.errors import IngestionFailureError
from app.ingestion.cleaning import CleanStats, build_vocabulary_from_blocks, clean_text, join_lines
from app.ingestion.layout import (
    dedupe_blocks,
    find_boilerplate,
    order_blocks,
    split_on_style_change,
)
from app.ingestion.metadata import resolve_metadata
from app.ingestion.paths import portable_source_name
from app.ingestion.pymupdf_backend import PyMuPdfBackend
from app.ingestion.raw import BBox, RawDocument, RawPage
from app.ingestion.sections import (
    body_font_size,
    classify_heading,
    ends_references,
    find_title_block,
    is_reference_heading,
)
from app.ingestion.validation import validate_pdf_file
from app.schemas.documents import DocumentMetadata
from app.schemas.enums import ParseStatus
from app.schemas.ingestion import (
    UNIT_SEPARATOR,
    ExtractionMethod,
    IngestionErrorCode,
    IngestionFailure,
    IngestionResult,
    IngestionWarning,
    PageRecord,
    ParsedDocument,
    TextUnit,
    UnitKind,
)
from app.schemas.manifest import PaperEntry

_LOG = logging.getLogger("veritas.ingestion")


class PdfBackend(Protocol):
    """Interface a PDF backend must satisfy (allows swapping PyMuPDF for another parser)."""

    name: str

    @property
    def version(self) -> str: ...

    def extract(self, data: bytes, cfg: IngestionConfig) -> RawDocument: ...


@dataclass
class _Draft:
    page: int
    kind: UnitKind
    text: str
    section: str | None
    level: int | None
    is_reference: bool
    bbox: BBox
    column: int | None
    page_end: int | None = None


_SPLIT_WORD_END = re.compile(r"[^\W\d_]-$")


def _merge_split_words(
    drafts: list[_Draft], vocab: set[str]
) -> tuple[list[_Draft], int, CleanStats]:
    """Merge a paragraph into its predecessor when a hyphenated word spans the break.

    Triggers only when the previous paragraph ends in ``letter-`` and the next one (same
    section and reference state) starts lowercase. The merged unit keeps the first block's
    bbox/column and records ``page_end`` when the continuation is on a later page.
    """
    out: list[_Draft] = []
    merged = 0
    stats = CleanStats()
    for draft in drafts:
        prev = out[-1] if out else None
        if (
            prev is not None
            and prev.kind == UnitKind.PARAGRAPH == draft.kind
            and prev.section == draft.section
            and prev.is_reference == draft.is_reference
            and _SPLIT_WORD_END.search(prev.text)
            and draft.text[:1].islower()
        ):
            text, st = join_lines([prev.text, draft.text], vocab)
            last_page = draft.page_end or draft.page
            out[-1] = _Draft(
                prev.page,
                prev.kind,
                text,
                prev.section,
                prev.level,
                prev.is_reference,
                prev.bbox,
                prev.column,
                last_page if last_page != prev.page else None,
            )
            stats += CleanStats(dehyphenated=st.dehyphenated)
            merged += 1
        else:
            out.append(draft)
    return out, merged, stats


def _failure(exc: IngestionFailureError) -> IngestionFailure:
    page = exc.context.get("page_number")
    return IngestionFailure(
        code=IngestionErrorCode(exc.failure_code),
        message=exc.message,
        stage=exc.stage,
        page_number=page if isinstance(page, int) else None,
        details={k: v for k, v in exc.context.items() if k != "page_number"},
    )


def ingest_file(
    path: Path,
    cfg: IngestionConfig,
    paper: PaperEntry | None = None,
    raw_root: Path | None = None,
    backend: PdfBackend | None = None,
) -> IngestionResult:
    """Ingest one PDF. Never raises for document-level problems (see module docstring)."""
    backend = backend or PyMuPdfBackend()
    sha: str | None = None
    try:
        validated = validate_pdf_file(path, cfg)
        sha = validated.sha256
        raw = backend.extract(validated.data, cfg)
        return _build(path, sha, raw, cfg, paper, raw_root, backend)
    except IngestionFailureError as exc:
        _LOG.warning("ingestion failed: %s (%s)", exc.failure_code, path.name)
        return IngestionResult(status=ParseStatus.FAILED, sha256=sha, failure=_failure(exc))


def _build(
    path: Path,
    sha: str,
    raw: RawDocument,
    cfg: IngestionConfig,
    paper: PaperEntry | None,
    raw_root: Path | None,
    backend: PdfBackend,
) -> IngestionResult:
    document_id = paper.paper_id if paper else f"doc-{sha[:12]}"
    warnings: list[IngestionWarning] = []
    stats: dict[str, int] = {}

    def warn(code: str, message: str, page: int | None = None) -> None:
        warnings.append(IngestionWarning(code=code, message=message, page_number=page))

    if raw.repaired:
        warn("pdf_repaired", "the PDF structure was damaged and repaired by the parser")
    if raw.owner_restricted:
        warn("pdf_owner_restricted", "PDF has owner restrictions; opened without a password")

    # 1. per-page duplicate removal and warnings from the backend
    pages: list[RawPage] = []
    for page in raw.pages:
        for code, message in page.warnings:
            warn(code, message, page.number)
        if page.rotation:
            warn(
                "rotated_page",
                f"page rotated {page.rotation} degrees; reading order unverified",
                page.number,
            )
        blocks, removed = dedupe_blocks(split_on_style_change(page.blocks))
        if removed:
            stats["duplicate_blocks_removed"] = stats.get("duplicate_blocks_removed", 0) + removed
            warn(
                "duplicate_text_removed",
                f"{removed} overprinted duplicate block(s) removed",
                page.number,
            )
        pages.append(
            RawPage(
                page.number, page.width, page.height, page.rotation, tuple(blocks), page.n_images
            )
        )

    # 2. running headers / footers / page numbers
    boilerplate = find_boilerplate(pages, cfg) if cfg.strip_running_headers else {}
    stats["boilerplate_blocks_removed"] = sum(len(v) for v in boilerplate.values())
    kept_pages = [
        RawPage(
            p.number,
            p.width,
            p.height,
            p.rotation,
            tuple(b for i, b in enumerate(p.blocks) if i not in boilerplate.get(p.number, set())),
            p.n_images,
        )
        for p in pages
    ]

    # 3. vocabulary and body size
    vocab = build_vocabulary_from_blocks(
        [line.text for line in b.lines] for p in kept_pages for b in p.blocks if b.kind == "text"
    )
    body = body_font_size(kept_pages)
    first_ordered = order_blocks(kept_pages[0].blocks, kept_pages[0].width, cfg)[0]
    title_block = find_title_block([b for b, _ in first_ordered], body, kept_pages[0].height)

    # 4. ordering, cleaning, headings/sections
    # Style-only headings are trusted only after a numbered/well-known heading appeared
    # (keeps author lines out), unless the document has no structured heading at all
    # (measured on real PDFs: gating alone dropped every heading of such documents).
    has_structured = any(
        (h := classify_heading(b, body, cfg, loose_ok=False)) is not None and h.structured
        for pg in kept_pages
        for b in pg.blocks
        if b is not title_block
    )
    drafts: list[_Draft] = []
    saw_structured = not has_structured
    page_records: list[PageRecord] = []
    totals = CleanStats()
    section: str | None = None
    level: int | None = None
    in_refs = False
    saw_heading = saw_refs = False
    for page in kept_pages:
        ordered, n_cols = order_blocks(page.blocks, page.width, cfg)
        page_chars = 0
        page_stats = CleanStats()
        for block, column in ordered:
            if block.kind == "table":
                text, st = clean_text(block.text)
                kind = UnitKind.TABLE
                heading = None
            else:
                text, st = join_lines([line.text for line in block.lines], vocab)
                heading = (
                    None
                    if block is title_block
                    else classify_heading(block, body, cfg, loose_ok=saw_structured)
                )
                if heading is not None and heading.structured:
                    saw_structured = True
                kind = UnitKind.HEADING if heading else UnitKind.PARAGRAPH
            page_stats += st
            if not text:
                continue
            if heading:
                saw_heading = True
                text = section = re.sub(r"\s+", " ", text).strip()
                if is_reference_heading(text):
                    in_refs = saw_refs = True
                elif in_refs and ends_references(text):
                    in_refs = False
                level = heading.level
            page_chars += len(text)
            drafts.append(
                _Draft(page.number, kind, text, section, level, in_refs, block.bbox, column)
            )
        totals += page_stats
        has_text = page_chars >= cfg.min_chars_per_page
        if page_stats.replacement_chars:
            warn(
                "encoding_corruption_suspected",
                f"{page_stats.replacement_chars} U+FFFD character(s)",
                page.number,
            )
        if page_stats.private_use_chars:
            warn(
                "private_use_characters",
                f"{page_stats.private_use_chars} private-use character(s); custom font encoding?",
                page.number,
            )
        if page_chars > cfg.max_chars_per_page_warn:
            warn("very_long_page", f"{page_chars} characters on one page", page.number)
        if not has_text:
            code = "no_text_layer_page" if page.n_images > 0 else "low_text_page"
            warn(code, f"only {page_chars} characters extracted", page.number)
        page_records.append(
            PageRecord(
                page_number=page.number,
                width=page.width,
                height=page.height,
                rotation=page.rotation,
                n_chars=page_chars,
                has_text_layer=has_text,
                n_images=page.n_images,
                n_columns=n_cols,
            )
        )

    if not any(r.has_text_layer for r in page_records):
        code = (
            IngestionErrorCode.OCR_NOT_IMPLEMENTED
            if cfg.ocr_enabled
            else IngestionErrorCode.NO_TEXT_LAYER
        )
        message = (
            "no extractable text; OCR is requested but IMPLEMENTATION PENDING"
            if cfg.ocr_enabled
            else "no extractable text layer (image-only or empty PDF); OCR is not enabled"
        )
        return IngestionResult(
            status=ParseStatus.FAILED,
            sha256=sha,
            failure=IngestionFailure(
                code=code, message=message, stage="extraction", details={"pages": len(page_records)}
            ),
        )
    if cfg.ocr_enabled and not all(r.has_text_layer for r in page_records):
        warn(
            "ocr_requested_but_not_implemented",
            "some pages lack text; OCR is IMPLEMENTATION PENDING",
        )
    if not saw_heading:
        warn(
            "no_headings_detected", "no section headings were detected; section is None everywhere"
        )
    if not saw_refs:
        warn(
            "no_references_section",
            "no References heading found; reference text may be mixed into body units",
        )

    # 4b. repair words split by a hyphen across a column/page break (measured on real pdfTeX output)
    drafts, n_merged, merge_stats = _merge_split_words(drafts, vocab)
    totals += merge_stats

    # 5. offsets and final units
    units: list[TextUnit] = []
    parts: list[str] = []
    cursor = 0
    per_page: dict[int, int] = {}
    for draft in drafts:
        idx = per_page.get(draft.page, 0)
        per_page[draft.page] = idx + 1
        units.append(
            TextUnit(
                unit_id=f"{document_id}::p{draft.page:04d}u{idx:04d}",
                document_id=document_id,
                page_number=draft.page,
                page_end=draft.page_end,
                kind=draft.kind,
                text=draft.text,
                section=draft.section,
                section_level=draft.level,
                is_reference=draft.is_reference,
                char_start=cursor,
                char_end=cursor + len(draft.text),
                bbox=draft.bbox,
                column=draft.column,
                extraction_method=ExtractionMethod.TEXT_LAYER,
            )
        )
        parts.append(draft.text)
        cursor += len(draft.text) + len(UNIT_SEPARATOR)
    full_text = UNIT_SEPARATOR.join(parts)

    stats.update(
        units=len(units),
        headings=sum(u.kind == UnitKind.HEADING for u in units),
        tables=sum(u.kind == UnitKind.TABLE for u in units),
        reference_units=sum(u.is_reference for u in units),
        blocks_merged_across_breaks=n_merged,
        symbols_normalized=totals.symbols_normalized,
        ligatures_expanded=totals.ligatures,
        dehyphenated=totals.dehyphenated,
        replacement_chars=totals.replacement_chars,
        private_use_chars=totals.private_use_chars,
        pages_without_text=sum(not r.has_text_layer for r in page_records),
    )
    degraded = bool(stats["pages_without_text"] or totals.replacement_chars or raw.repaired)
    status = ParseStatus.PARTIAL if degraded else ParseStatus.OK

    layout_title = (
        clean_text(re.sub(r"\s+", " ", title_block.text))[0] if title_block is not None else None
    )
    resolved = resolve_metadata(raw.info, layout_title, paper, path.stem)
    metadata = DocumentMetadata(
        document_id=document_id,
        paper_title=resolved.title,
        authors=resolved.authors,
        year=resolved.year,
        source_file=portable_source_name(path, raw_root),
        source_url=paper.source_url if paper else None,
        sha256=sha,
        num_pages=len(page_records),
        parse_status=status,
        parser=backend.name,
        parser_version=backend.version,
        warnings=tuple(sorted({w.code for w in warnings})),
    )
    document = ParsedDocument(
        metadata=metadata,
        pages=tuple(page_records),
        units=tuple(units),
        full_text=full_text,
        warnings=tuple(warnings),
        stats=stats,
        title_source=resolved.title_source,
        authors_source=resolved.authors_source,
    )
    return IngestionResult(status=status, sha256=sha, document=document)
