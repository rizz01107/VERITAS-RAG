"""Ground-truth validation on a REAL pdfTeX-produced two-column PDF (invented text).

Skipped when pdflatex is unavailable (e.g. most Windows machines). These tests came from
defects measured on real TeX output: title taken from the file name, author line parsed
as a heading, \\Delta extracted as U+2206, words split across column/page breaks, and a
booktabs table collapsed into one paragraph.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pymupdf
import pytest

from app.core.config import IngestionConfig
from app.ingestion.pipeline import ingest_file
from app.schemas.ingestion import ParsedDocument, UnitKind
from tests.texgen.paper import (
    HYPHEN_WORDS,
    LIGATURE_WORDS,
    TITLE,
    Marker,
    build_tex,
    compile_tex,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not installed"),
]


@pytest.fixture(scope="module")
def paper(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str, list[Marker]]:
    tex, markers = build_tex()
    workdir = tmp_path_factory.mktemp("tex")
    pdf = compile_tex(tex, workdir)
    assert pdf is not None
    return pdf, tex, markers


@pytest.fixture(scope="module")
def doc(paper: tuple[Path, str, list[Marker]]) -> ParsedDocument:
    result = ingest_file(paper[0], IngestionConfig())
    assert result.document is not None, result.failure
    return result.document


def _marker_units(doc: ParsedDocument) -> list[tuple[str, int, str | None, bool]]:
    return [
        (m, u.page_number, u.section, u.is_reference)
        for u in doc.units
        for m in re.findall(r"MK\d{3}", u.text)
    ]


def test_reading_order_matches_source_order(
    doc: ParsedDocument, paper: tuple[Path, str, list[Marker]]
) -> None:
    found = [m for m, *_ in _marker_units(doc)]
    assert found == [m.marker for m in paper[2]]  # all markers, in source order
    assert all(p.n_columns == 2 for p in doc.pages[:4])


def test_page_numbers_match_independent_search(
    doc: ParsedDocument, paper: tuple[Path, str, list[Marker]]
) -> None:
    source = pymupdf.open(paper[0])
    truth = {
        mk.marker: pno + 1
        for pno in range(source.page_count)
        for mk in paper[2]
        if source[pno].search_for(mk.marker)
    }
    assert [(m, p) for m, p, _, _ in _marker_units(doc)] == [
        (m, truth[m]) for m, *_ in _marker_units(doc)
    ]


def test_sections_and_references_match_source(
    doc: ParsedDocument, paper: tuple[Path, str, list[Marker]]
) -> None:
    expected = {mk.marker: (mk.section, mk.reference) for mk in paper[2]}
    actual = {m: (s, r) for m, _, s, r in _marker_units(doc)}
    assert actual == expected
    refs = " ".join(u.text for u in doc.units if u.is_reference)
    assert "Invented Title Two" in refs
    assert "Invented Title" not in " ".join(u.text for u in doc.chunk_units())


def test_running_header_and_page_numbers_removed(doc: ParsedDocument) -> None:
    assert "Synthetic Running Title" not in doc.full_text
    assert doc.stats["boilerplate_blocks_removed"] >= 9


def test_title_from_layout_and_authors_not_a_heading(doc: ParsedDocument) -> None:
    assert doc.title_source == "layout" and doc.metadata.paper_title == TITLE
    headings = [u.text for u in doc.units if u.kind == UnitKind.HEADING]
    assert not any("Ada Example" in h for h in headings)
    assert headings[0] == "Abstract" and "1 Introduction" in headings


def test_hyphenated_words_repaired_exactly(
    doc: ParsedDocument, paper: tuple[Path, str, list[Marker]]
) -> None:
    tex = paper[1]
    for word in HYPHEN_WORDS:
        assert doc.full_text.count(word) == tex.count(word), word
    assert doc.stats["blocks_merged_across_breaks"] >= 1  # column/page-break splits repaired


def test_ligature_words_intact(doc: ParsedDocument, paper: tuple[Path, str, list[Marker]]) -> None:
    for word in LIGATURE_WORDS:
        assert doc.full_text.count(word) == paper[1].count(word), word


def test_delta_is_normalised_and_math_preserved(doc: ParsedDocument) -> None:
    assert "\u2206" not in doc.full_text and "\u0394" in doc.full_text
    equation = next(u.text for u in doc.units if "ΔW" in u.text)
    assert "BA" in equation and "∈" in equation  # symbols survive; sub/superscripts are flattened


def test_booktabs_table_rows_and_cells(doc: ParsedDocument) -> None:
    tables = [u for u in doc.units if u.kind == UnitKind.TABLE]
    assert len(tables) == 1
    assert tables[0].text.split("\n") == [
        "Method | Params | Score",
        "alphamethod | 0.1 | 71.5",
        "betamethod | 3.6 | 88.2",
    ]
    assert sum(u.text.count("alphamethod") for u in doc.units) == 1  # not duplicated in body


def test_no_false_tables_on_text_pages(doc: ParsedDocument) -> None:
    table_pages = {u.page_number for u in doc.units if u.kind == UnitKind.TABLE}
    assert table_pages == {4}


def test_real_tex_ingestion_is_deterministic(paper: tuple[Path, str, list[Marker]]) -> None:
    a = ingest_file(paper[0], IngestionConfig())
    b = ingest_file(paper[0], IngestionConfig())
    assert a.model_dump_json() == b.model_dump_json()


@pytest.mark.parametrize(("twocolumn", "fontsize"), [(False, 10), (True, 12), (False, 12)])
def test_layout_variants_keep_ground_truth(tmp_path: Path, twocolumn: bool, fontsize: int) -> None:
    tex, markers = build_tex(twocolumn=twocolumn, fontsize=fontsize)
    pdf = compile_tex(tex, tmp_path)
    assert pdf is not None
    result = ingest_file(pdf, IngestionConfig())
    assert result.document is not None, result.failure
    found = _marker_units(result.document)
    assert [m for m, *_ in found] == [m.marker for m in markers]
    assert {m: (s, r) for m, _, s, r in found} == {
        m.marker: (m.section, m.reference) for m in markers
    }
    assert "Synthetic Running Title" not in result.document.full_text
    for word in HYPHEN_WORDS:
        assert result.document.full_text.count(word) == tex.count(word), word
    assert result.document.metadata.paper_title == TITLE
    tables = [u.text for u in result.document.units if u.kind == UnitKind.TABLE]
    assert tables == ["Method | Params | Score\nalphamethod | 0.1 | 71.5\nbetamethod | 3.6 | 88.2"]
