"""Structured document representation produced by ingestion (Phase 3).

Every :class:`TextUnit` keeps page, section, bounding box, extraction method and
character offsets into ``ParsedDocument.full_text`` so that any later chunk or
citation can be traced back to an exact place in the source PDF.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from app.schemas.base import IdStr, Sha256Str, StrictModel
from app.schemas.documents import DocumentMetadata
from app.schemas.enums import ParseStatus

UNIT_SEPARATOR = "\n\n"


class IngestionErrorCode(str, Enum):
    """Machine-readable reason a document could not be ingested."""

    FILE_NOT_FOUND = "file_not_found"
    NOT_A_FILE = "not_a_file"
    UNSUPPORTED_TYPE = "unsupported_type"
    EMPTY_FILE = "empty_file"
    FILE_TOO_LARGE = "file_too_large"
    NOT_A_PDF = "not_a_pdf"
    CORRUPTED = "corrupted"
    ENCRYPTED = "encrypted"
    EMPTY_DOCUMENT = "empty_document"
    TOO_MANY_PAGES = "too_many_pages"
    NO_TEXT_LAYER = "no_text_layer"
    OCR_NOT_IMPLEMENTED = "ocr_not_implemented"
    PARSE_ERROR = "parse_error"
    UNSAFE_PATH = "unsafe_path"


class UnitKind(str, Enum):
    """Role of a text unit in the document."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"


class ExtractionMethod(str, Enum):
    """How the text was obtained. OCR text carries extra uncertainty."""

    TEXT_LAYER = "text_layer"
    OCR = "ocr"


class IngestionFailure(StrictModel):
    """Structured, user-presentable failure (never a bare traceback)."""

    code: IngestionErrorCode
    message: str
    stage: str
    page_number: int | None = Field(default=None, ge=1)
    details: dict[str, Any] = Field(default_factory=dict)


class IngestionWarning(StrictModel):
    """Non-fatal problem that may reduce extraction reliability."""

    code: str
    message: str
    page_number: int | None = Field(default=None, ge=1)


class PageRecord(StrictModel):
    """Per-page extraction facts."""

    page_number: int = Field(ge=1)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    rotation: int
    n_chars: int = Field(ge=0)
    has_text_layer: bool
    n_images: int = Field(ge=0)
    n_columns: int = Field(ge=1)
    extraction_method: ExtractionMethod = ExtractionMethod.TEXT_LAYER


class TextUnit(StrictModel):
    """A paragraph, heading or table with full provenance."""

    unit_id: str
    document_id: IdStr
    page_number: int = Field(ge=1)
    page_end: int | None = Field(default=None, ge=1)
    kind: UnitKind
    text: str = Field(min_length=1)
    section: str | None = None
    section_level: int | None = Field(default=None, ge=1)
    is_reference: bool = False
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    bbox: tuple[float, float, float, float]
    column: int | None = Field(default=None, ge=0)
    extraction_method: ExtractionMethod = ExtractionMethod.TEXT_LAYER

    @model_validator(mode="after")
    def _offsets(self) -> TextUnit:
        if self.char_end - self.char_start != len(self.text):
            raise ValueError("char offsets do not match text length")
        if self.page_end is not None and self.page_end < self.page_number:
            raise ValueError("page_end must be >= page_number")
        return self


class ParsedDocument(StrictModel):
    """Chunk-ready structured document.

    ``full_text`` is the concatenation of unit texts joined by ``UNIT_SEPARATOR``;
    ``full_text[u.char_start:u.char_end] == u.text`` holds for every unit (validated).
    """

    metadata: DocumentMetadata
    pages: tuple[PageRecord, ...]
    units: tuple[TextUnit, ...]
    full_text: str
    warnings: tuple[IngestionWarning, ...] = ()
    stats: dict[str, int] = Field(default_factory=dict)
    title_source: str = "unknown"
    authors_source: str = "unknown"

    @model_validator(mode="after")
    def _provenance_invariants(self) -> ParsedDocument:
        known_pages = {p.page_number for p in self.pages}
        expected_start = 0
        for unit in self.units:
            if unit.document_id != self.metadata.document_id:
                raise ValueError("unit document_id differs from metadata.document_id")
            if unit.page_end is not None and unit.page_end not in known_pages:
                raise ValueError(f"unit {unit.unit_id} references unknown page_end")
            if unit.page_number not in known_pages:
                raise ValueError(f"unit {unit.unit_id} references unknown page {unit.page_number}")
            if unit.char_start != expected_start:
                raise ValueError(f"unit {unit.unit_id} offsets are not contiguous")
            if self.full_text[unit.char_start : unit.char_end] != unit.text:
                raise ValueError(f"unit {unit.unit_id} text does not match full_text offsets")
            expected_start = unit.char_end + len(UNIT_SEPARATOR)
        return self

    def chunk_units(
        self, include_references: bool = False, include_tables: bool = True
    ) -> tuple[TextUnit, ...]:
        """Units a chunker should consume (references excluded by default)."""
        return tuple(
            u
            for u in self.units
            if (include_references or not u.is_reference)
            and (include_tables or u.kind != UnitKind.TABLE)
        )


class IngestionResult(StrictModel):
    """Outcome of ingesting one file. Document-level problems never raise."""

    status: ParseStatus
    sha256: Sha256Str | None = None
    document: ParsedDocument | None = None
    failure: IngestionFailure | None = None

    @model_validator(mode="after")
    def _consistent(self) -> IngestionResult:
        if self.status == ParseStatus.FAILED:
            if self.failure is None or self.document is not None:
                raise ValueError("failed result needs a failure and no document")
        elif self.document is None or self.failure is not None:
            raise ValueError("successful result needs a document and no failure")
        return self
