"""Document and chunk contracts. Provenance fields must survive to the final citation."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.base import IdStr, Sha256Str, StrictModel
from app.schemas.enums import ParseStatus

ChunkStrategy = Literal["fixed", "sentence", "section"]
StoreScalar = str | int | float | bool


def make_chunk_id(document_id: str, index: int) -> str:
    """Build the canonical chunk id ``<document_id>::c<5-digit index>``."""
    if index < 0:
        raise ValueError("chunk index must be >= 0")
    return f"{document_id}::c{index:05d}"


class DocumentMetadata(StrictModel):
    """Metadata describing one parsed source document."""

    document_id: IdStr
    paper_title: str = Field(min_length=1)
    authors: tuple[str, ...] = ()
    year: int | None = Field(default=None, ge=1950, le=2100)
    source_file: str = Field(min_length=1)
    source_url: str | None = None
    sha256: Sha256Str
    num_pages: int | None = Field(default=None, ge=0)
    parse_status: ParseStatus
    parser: str = Field(min_length=1)
    parser_version: str | None = None
    warnings: tuple[str, ...] = ()


class ChunkRecord(StrictModel):
    """One retrievable passage with full provenance.

    ``section`` and ``page_number`` are ``None`` when unknown; they are never guessed.
    """

    document_id: IdStr
    paper_title: str = Field(min_length=1)
    authors: tuple[str, ...] = ()
    year: int | None = Field(default=None, ge=1950, le=2100)
    section: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    chunk_id: str
    text: str
    source_file: str = Field(min_length=1)
    source_url: str | None = None
    chunk_strategy: ChunkStrategy
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    page_end: int | None = Field(default=None, ge=1)
    extraction_method: Literal["text_layer", "ocr"] = "text_layer"

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("chunk text must not be blank")
        return value

    @model_validator(mode="after")
    def _check_consistency(self) -> ChunkRecord:
        if not self.chunk_id.startswith(f"{self.document_id}::"):
            raise ValueError("chunk_id must start with '<document_id>::'")
        if self.page_end is not None and (
            self.page_number is None or self.page_end < self.page_number
        ):
            raise ValueError("page_end requires page_number and must be >= it")
        if (
            self.char_start is not None
            and self.char_end is not None
            and self.char_end < self.char_start
        ):
            raise ValueError("char_end must be >= char_start")
        return self

    def to_store_metadata(self) -> dict[str, StoreScalar]:
        """Flatten provenance for vector stores that only accept scalar metadata.

        ``None`` values are omitted (absent means unknown); authors are joined
        with ``"; "``. The chunk text itself is stored separately by the store.
        """
        flat: dict[str, StoreScalar | None] = {
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "paper_title": self.paper_title,
            "authors": "; ".join(self.authors) if self.authors else None,
            "year": self.year,
            "section": self.section,
            "page_number": self.page_number,
            "source_file": self.source_file,
            "source_url": self.source_url,
            "chunk_strategy": self.chunk_strategy,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "page_end": self.page_end,
            "extraction_method": self.extraction_method,
        }
        return {key: value for key, value in flat.items() if value is not None}
