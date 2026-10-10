"""Backend-neutral page structures so heuristics are testable without any PDF library."""

from __future__ import annotations

from dataclasses import dataclass, field

BBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class RawSpan:
    """Run of text with uniform styling."""

    text: str
    size: float
    bold: bool = False


@dataclass(frozen=True)
class RawLine:
    """One visual line."""

    spans: tuple[RawSpan, ...]
    bbox: BBox

    @property
    def text(self) -> str:
        return "".join(span.text for span in self.spans)


@dataclass(frozen=True)
class RawBlock:
    """A paragraph-like block (``kind='text'``) or a detected table (``kind='table'``)."""

    bbox: BBox
    lines: tuple[RawLine, ...] = ()
    kind: str = "text"
    table_rows: tuple[tuple[str, ...], ...] = ()

    @property
    def text(self) -> str:
        if self.kind == "table":
            return "\n".join(" | ".join(row) for row in self.table_rows)
        return "\n".join(line.text for line in self.lines)


@dataclass(frozen=True)
class RawPage:
    """One physical page (1-based ``number``)."""

    number: int
    width: float
    height: float
    rotation: int
    blocks: tuple[RawBlock, ...]
    n_images: int = 0
    warnings: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class RawDocument:
    """Backend output: pages plus the PDF's own (untrusted) metadata."""

    pages: tuple[RawPage, ...]
    info: dict[str, str] = field(default_factory=dict)
    repaired: bool = False
    owner_restricted: bool = False
