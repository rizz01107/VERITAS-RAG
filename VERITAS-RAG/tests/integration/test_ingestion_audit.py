"""Second-pass audit regressions: each test pins a defect found by adversarial review."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import IngestionConfig
from app.core.errors import ManifestError
from app.ingestion.io import parsed_document_path
from app.ingestion.pipeline import ingest_file
from app.ingestion.pymupdf_backend import PyMuPdfBackend
from app.schemas.enums import ParseStatus
from app.schemas.ingestion import IngestionErrorCode, IngestionResult, ParsedDocument, UnitKind
from tests import pdfgen as g
from tests.conftest import make_paper

pytestmark = pytest.mark.integration
CFG = IngestionConfig(min_chars_per_page=20)


def _run(tmp_path: Path, data: bytes, cfg: IngestionConfig = CFG) -> IngestionResult:
    path = tmp_path / "a.pdf"
    path.write_bytes(data)
    return ingest_file(path, cfg)


def _doc(result: IngestionResult) -> ParsedDocument:
    assert result.document is not None, result.failure
    return result.document


def test_title_at_14pt_is_title_not_section(tmp_path: Path) -> None:
    html = (
        g.heading("An Invented Paper About Gradients", 14)
        + g.para(g.BODY)
        + g.heading("1 Introduction", 12)
    )
    html += g.para("Intro body. " + g.BODY)
    doc = _doc(_run(tmp_path, g.simple_pdf([html])))
    assert doc.title_source == "layout" and "Invented Paper" in doc.metadata.paper_title
    headings = [u.text for u in doc.units if u.kind == UnitKind.HEADING]
    assert headings == ["1 Introduction"]  # the title must not become a section heading
    intro = next(u for u in doc.units if "Intro body" in u.text)
    assert intro.section == "1 Introduction"


def test_heading_text_is_cleaned_like_body_text(tmp_path: Path) -> None:
    html = (
        g.para("x " * 10) + g.heading("2 Fine\u00adtuning with ﬁlters") + g.para("Body. " + g.BODY)
    )
    doc = _doc(_run(tmp_path, g.simple_pdf([html])))
    head = next(u for u in doc.units if u.kind == UnitKind.HEADING)
    assert "ﬁ" not in head.text and "\u00ad" not in head.text
    assert head.section == head.text


def test_damaged_page_becomes_warning_not_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = PyMuPdfBackend._extract_page_unsafe

    def flaky(self: PyMuPdfBackend, page: object, number: int, cfg: IngestionConfig):  # type: ignore[no-untyped-def]
        if number == 2:
            raise RuntimeError("simulated damaged page object")
        return original(self, page, number, cfg)

    monkeypatch.setattr(PyMuPdfBackend, "_extract_page_unsafe", flaky)
    result = _run(tmp_path, g.simple_pdf([g.para(g.BODY)] * 3))
    doc = _doc(result)
    assert result.status == ParseStatus.PARTIAL
    assert [p.has_text_layer for p in doc.pages] == [True, False, True]
    codes = {(w.code, w.page_number) for w in doc.warnings}
    assert ("page_load_failed", 2) in codes


def test_unexpected_parser_exception_is_structured_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(self: PyMuPdfBackend, doc: object, cfg: IngestionConfig):  # type: ignore[no-untyped-def]
        raise RuntimeError("native library exploded")

    monkeypatch.setattr(PyMuPdfBackend, "_extract_open", boom)
    result = _run(tmp_path, g.simple_pdf([g.para(g.BODY)]))
    assert result.failure is not None and result.failure.code == IngestionErrorCode.PARSE_ERROR
    assert "native library" not in result.failure.message  # no raw exception text leaks


def test_rotated_page_is_flagged_for_manual_review(tmp_path: Path) -> None:
    import pymupdf

    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 100), "rotated page content for the extractor " * 3, fontsize=11)
    page.set_rotation(90)
    doc = _doc(_run(tmp_path, bytes(pdf.tobytes())))
    assert "rotated_page" in {w.code for w in doc.warnings}


def test_output_filenames_never_collide_after_sanitising(tmp_path: Path) -> None:
    a = parsed_document_path(tmp_path, "paper.")
    b = parsed_document_path(tmp_path, "paper")
    c = parsed_document_path(tmp_path, "a<b")
    d = parsed_document_path(tmp_path, "a>b")
    assert a != b and c != d
    assert b.name == "paper.json"


def test_manifest_ids_are_case_insensitively_unique(tmp_path: Path) -> None:
    import yaml

    from app.ingestion.manifest import load_manifest

    papers = [
        make_paper(paper_id="Synthetic-0001v1"),
        make_paper(paper_id="synthetic-0001v1", title="Other", sha256="b" * 64),
    ]
    path = tmp_path / "m.yaml"
    path.write_text(yaml.safe_dump({"manifest_version": "1", "corpus_name": "t", "papers": papers}))
    with pytest.raises(ManifestError, match="case-insensitively"):
        load_manifest(path)
