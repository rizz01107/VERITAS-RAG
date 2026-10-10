"""Automated quality indicators for real-PDF validation.

These are *indicators*, not accuracy: they catch classes of defects without ground
truth (residual hyphens, ligature code points, replacement characters, missing
sections, page-order regressions). Reading order and text fidelity still require the
manual spot-check sheet. No paper text is emitted by this module.
"""

from __future__ import annotations

import csv
import random
import re
import statistics
from pathlib import Path
from typing import Any

from app.ingestion.cleaning import LIGATURES
from app.schemas.ingestion import ParsedDocument, UnitKind

_TRAILING_HYPHEN = re.compile(r"[A-Za-z]-$")
_LONG_UNIT_CHARS = 3000
_TITLE_PREVIEW = 80
SHEET_COLUMNS = (
    "paper_id",
    "unit_id",
    "page",
    "kind",
    "section",
    "bbox",
    "check",
    "verdict",
    "failure_note",
)


def audit_document(doc: ParsedDocument) -> dict[str, Any]:
    """Compute indicators for one parsed document."""
    units = doc.units
    chars = [p.n_chars for p in doc.pages]
    texts = [u.text for u in units]
    seen: dict[str, int] = {}
    for text in texts:
        seen[text] = seen.get(text, 0) + 1
    pages_seq = [u.page_number for u in units]
    warning_counts: dict[str, int] = {}
    for w in doc.warnings:
        warning_counts[w.code] = warning_counts.get(w.code, 0) + 1
    headings = [u for u in units if u.kind == UnitKind.HEADING]
    return {
        "document_id": doc.metadata.document_id,
        "status": doc.metadata.parse_status.value,
        "pages": len(doc.pages),
        "text_layer_pages": sum(p.has_text_layer for p in doc.pages),
        "chars_per_page": {
            "min": min(chars),
            "median": int(statistics.median(chars)),
            "max": max(chars),
        },
        "column_pages": {
            str(n): sum(p.n_columns == n for p in doc.pages)
            for n in sorted({p.n_columns for p in doc.pages})
        },
        "units": len(units),
        "headings": len(headings),
        "heading_list": [
            {"page": h.page_number, "level": h.section_level, "title": h.text[:_TITLE_PREVIEW]}
            for h in headings
        ],
        "tables": sum(u.kind == UnitKind.TABLE for u in units),
        "units_without_section_fraction": (
            round(sum(u.section is None for u in units) / len(units), 3) if units else None
        ),
        "reference_unit_fraction": (
            round(sum(u.is_reference for u in units) / len(units), 3) if units else None
        ),
        "indicators": {
            "units_ending_in_hyphen": sum(bool(_TRAILING_HYPHEN.search(t)) for t in texts),
            "units_with_ligature_codepoints": sum(any(c in t for c in LIGATURES) for t in texts),
            "units_with_replacement_char": sum("\ufffd" in t for t in texts),
            "units_with_private_use_char": sum(
                any(0xE000 <= ord(c) < 0xF900 for c in t) for t in texts
            ),
            "very_short_units(<3 chars)": sum(len(t) < 3 for t in texts),
            f"very_long_units(>{_LONG_UNIT_CHARS})": sum(len(t) > _LONG_UNIT_CHARS for t in texts),
            "exact_duplicate_unit_texts": sum(n - 1 for n in seen.values() if n > 1),
            "page_order_regressions": sum(
                b < a for a, b in zip(pages_seq, pages_seq[1:], strict=False)
            ),
        },
        "warning_counts": dict(sorted(warning_counts.items())),
        "title_source": doc.title_source,
        "authors_source": doc.authors_source,
        "offset_invariant": "validated at construction",
    }


def write_spot_check_sheet(
    docs: list[ParsedDocument], path: Path, per_doc: int = 5, seed: int = 0
) -> int:
    """Write a CSV for manual review: seeded random units per document, *without* any text.

    Reviewers open the PDF at the given page/bbox and fill ``verdict`` (pass/fail) and
    ``failure_note``. Tables and headings are always listed in addition to the sample.
    """
    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not security
    rows = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(SHEET_COLUMNS)
        for doc in docs:
            body = [u for u in doc.units if u.kind == UnitKind.PARAGRAPH]
            sample = rng.sample(body, min(per_doc, len(body)))
            must = [u for u in doc.units if u.kind in {UnitKind.TABLE, UnitKind.HEADING}]
            for unit in sorted(
                {u.unit_id: u for u in [*sample, *must]}.values(), key=lambda u: u.unit_id
            ):
                check = {"table": "table cells/rows", "heading": "heading + level"}.get(
                    unit.kind.value, "text fidelity; reading order; page; section"
                )
                bbox = " ".join(f"{v:.0f}" for v in unit.bbox)
                writer.writerow(
                    [
                        doc.metadata.document_id,
                        unit.unit_id,
                        unit.page_number,
                        unit.kind.value,
                        unit.section_level if unit.kind == UnitKind.HEADING else "",
                        bbox,
                        check,
                        "",
                        "",
                    ]
                )
                rows += 1
    return rows
