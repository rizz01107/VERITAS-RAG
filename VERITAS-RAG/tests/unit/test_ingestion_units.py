from __future__ import annotations

import http.server
import threading
from collections.abc import Iterator
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from app.core.config import IngestionConfig
from app.core.errors import IngestionFailureError
from app.ingestion.cleaning import build_vocabulary, clean_text, join_lines
from app.ingestion.download import download_pdf
from app.ingestion.layout import dedupe_blocks, find_boilerplate, order_blocks
from app.ingestion.metadata import resolve_metadata
from app.ingestion.paths import ensure_within, portable_source_name, sanitize_filename
from app.ingestion.raw import RawBlock, RawLine, RawPage, RawSpan
from app.ingestion.sections import (
    classify_heading,
    ends_references,
    is_reference_heading,
)
from app.ingestion.validation import validate_pdf_file

pytestmark = pytest.mark.unit
CFG = IngestionConfig()


def blk(
    x0: float, y0: float, x1: float, y1: float, text: str, size: float = 10, bold: bool = False
) -> RawBlock:
    line = RawLine((RawSpan(text, size, bold),), (x0, y0, x1, y1))
    return RawBlock((x0, y0, x1, y1), (line,))


# ---- Windows / path portability ------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CON", "_CON"),
        ("nul.pdf", "_nul.pdf"),
        ("COM1.txt", "_COM1.txt"),
        ('a<b>c:d"e|f?g*h.pdf', "a_b_c_d_e_f_g_h.pdf"),
        ("trailing dot.", "trailing dot"),
        ("trailing space ", "trailing space"),
        ("", "_"),
        ("a/b\\c.pdf", "a_b_c.pdf"),
    ],
)
def test_sanitize_filename_windows_rules(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_length_keeps_extension() -> None:
    out = sanitize_filename("x" * 300 + ".json", max_len=50)
    assert len(out) == 50 and out.endswith(".json")


def test_portable_source_name_windows_paths() -> None:
    base = PureWindowsPath("C:/Users/rizwan/proj/data/raw")
    inside = PureWindowsPath("C:\\Users\\rizwan\\proj\\data\\raw\\sub dir\\a.pdf")
    assert portable_source_name(inside, base) == "sub dir/a.pdf"
    outside = PureWindowsPath("D:\\elsewhere\\b.pdf")
    assert portable_source_name(outside, base) == "b.pdf"
    assert portable_source_name(PurePosixPath("/x/y/c.pdf"), None) == "c.pdf"
    assert "Users" not in portable_source_name(inside, base)


@pytest.mark.edge
def test_ensure_within_blocks_traversal_and_symlink(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    assert ensure_within(base, base / "ok.json") == (base / "ok.json").resolve()
    with pytest.raises(IngestionFailureError):
        ensure_within(base, base / ".." / "evil.json")
    outside = tmp_path / "outside"
    outside.mkdir()
    link = base / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted (common on Windows without developer mode)")
    with pytest.raises(IngestionFailureError):
        ensure_within(base, link / "x.json")


def test_unicode_and_spaces_in_paths(tmp_path: Path) -> None:
    d = tmp_path / "données papier ü"
    d.mkdir()
    f = d / "résumé α.pdf"
    f.write_bytes(b"%PDF-1.4 x")
    assert validate_pdf_file(f, CFG).path == f


# ---- validation ----
@pytest.mark.edge
def test_validation_codes(tmp_path: Path) -> None:
    f = tmp_path / "a.pdf"
    f.write_bytes(b"junk\n" * 10 + b"%PDF-1.7 body")
    assert validate_pdf_file(f, CFG).sha256  # header within the first KB is tolerated
    f.write_bytes(b"x" * 2000 + b"%PDF-1.7")
    with pytest.raises(IngestionFailureError) as info:
        validate_pdf_file(f, CFG)
    assert info.value.failure_code == "not_a_pdf"
    upper = tmp_path / "B.PDF"
    upper.write_bytes(b"%PDF-1.4 ok")
    assert validate_pdf_file(upper, CFG)  # extension check is case-insensitive


# ---- cleaning ----
def test_clean_text_conservative() -> None:
    text, st = clean_text("ﬁnd\u00a0the ﬂo\u200bw  of ∑ α² ℝ naïve\u0007 x")
    assert text == "find the flow of ∑ α² ℝ naïve x" and st.ligatures == 2
    corrupted, stats = clean_text("bad \ufffd char and \ue001 private")
    assert stats.replacement_chars == 1 and stats.private_use_chars == 1
    assert "\ufffd" in corrupted  # reported, never silently "fixed"


def test_clean_text_does_not_apply_nfkc() -> None:
    assert clean_text("x² ① ℓ")[0] == "x² ① ℓ"


def test_vocabulary_excludes_line_break_fragments() -> None:
    from app.ingestion.cleaning import build_vocabulary_from_blocks

    vocab = build_vocabulary_from_blocks([["an optimi-", "zation of low-rank maps"]])
    assert "optimi" not in vocab and "zation" not in vocab and "low-rank" in vocab


@pytest.mark.parametrize(
    ("lines", "vocab_text", "expected"),
    [
        (["an optimi-", "zation step"], "", "an optimization step"),
        (["state-of-", "the-art model"], "", "state-of-the-art model"),
        (["a low-", "rank map"], "low-rank low-rank", "a low-rank map"),
        (["the fine-", "tuning idea"], "fine-tuning finetuning", "the fine-tuning idea"),
        (["soft hy\u00ad", "phen here"], "", "soft hyphen here"),
        (["end of sentence -", "Next"], "", "end of sentence - Next"),
        (["plain line", "second line"], "", "plain line second line"),
    ],
)
def test_dehyphenation(lines: list[str], vocab_text: str, expected: str) -> None:
    out, _ = join_lines(lines, build_vocabulary([vocab_text]))
    assert out == expected


# ---- layout ----
def test_reading_order_two_columns_with_spanning_banner() -> None:
    blocks = [
        blk(50, 100, 290, 140, "L1"),
        blk(50, 150, 290, 190, "L2"),
        blk(322, 100, 562, 140, "R1"),
        blk(322, 150, 562, 190, "R2"),
        blk(50, 30, 562, 60, "BANNER"),
        blk(50, 220, 562, 250, "SPAN2"),
        blk(50, 260, 290, 300, "L3"),
        blk(322, 260, 562, 300, "R3"),
    ]
    ordered, cols = order_blocks(blocks, 612, CFG)
    assert cols == 2
    assert [b.text for b, _ in ordered] == ["BANNER", "L1", "L2", "R1", "R2", "SPAN2", "L3", "R3"]


def test_single_column_with_short_headings_is_not_two_column() -> None:
    blocks = [
        blk(50, 50, 200, 70, "1 Intro", 14, True),
        blk(50, 80, 562, 200, "Wide paragraph text"),
        blk(50, 210, 180, 230, "2 Method", 14, True),
        blk(50, 240, 562, 400, "More wide text"),
    ]
    ordered, cols = order_blocks(blocks, 612, CFG)
    assert cols == 1 and [b.text for b, _ in ordered][0] == "1 Intro"


def test_column_detection_can_be_disabled() -> None:
    blocks = [
        blk(50, 100, 290, 140, "L1"),
        blk(322, 100, 562, 140, "R1"),
        blk(50, 150, 290, 190, "L2"),
        blk(322, 150, 562, 190, "R2"),
    ]
    ordered, cols = order_blocks(blocks, 612, IngestionConfig(detect_columns=False))
    assert cols == 1 and [b.text for b, _ in ordered] == ["L1", "R1", "L2", "R2"]


def test_empty_page_ordering() -> None:
    assert order_blocks([], 612, CFG) == ([], 1)


def test_dedupe_overprinted_blocks_only() -> None:
    a = blk(50, 50, 200, 70, "Same text")
    b = blk(50.5, 50.2, 200.5, 70.2, "Same text")
    c = blk(50, 300, 200, 320, "Same text")  # same words, different place: kept
    kept, removed = dedupe_blocks([a, b, c])
    assert removed == 1 and len(kept) == 2


def _page(n: int, blocks: list[RawBlock]) -> RawPage:
    return RawPage(n, 612, 792, 0, tuple(blocks))


def test_boilerplate_needs_repetition_but_page_numbers_always_go() -> None:
    pages = [
        _page(
            i,
            [
                blk(200, 20, 400, 32, f"Short Title {i}"),
                blk(300, 760, 312, 772, str(i)),
                blk(50, 100, 560, 300, f"body {i}"),
            ],
        )
        for i in range(1, 6)
    ]
    found = find_boilerplate(pages, CFG)
    assert all(found[i] == {0, 1} for i in range(1, 6))
    single = [_page(1, [blk(200, 20, 400, 32, "Title Once"), blk(300, 760, 312, 772, "1")])]
    assert find_boilerplate(single, CFG) == {1: {1}}  # title kept, bare page number dropped


def test_body_text_in_margin_band_not_removed_when_unique() -> None:
    pages = [_page(1, [blk(50, 10, 560, 30, "Unique first-page title line")])]
    assert find_boilerplate(pages, CFG) == {}


# ---- sections ----
@pytest.mark.parametrize(
    ("text", "size", "bold", "expected"),
    [
        ("1 Introduction", 12, True, True),
        ("3.2 Low-Rank Update", 12, True, True),
        ("Abstract", 10, True, True),
        ("Related Work", 12, False, True),
        ("Table 2: Results on GLUE", 12, True, False),
        ("Figure 1 shows the pipeline", 10, True, False),
        ("This is a body sentence that ends with a period.", 10, False, False),
        ("A Very Large Paper Title", 20, True, False),  # title-sized text is not a section
        ("plain body words", 10, False, False),
    ],
)
def test_heading_classification(text: str, size: float, bold: bool, expected: bool) -> None:
    assert (
        classify_heading(blk(50, 50, 300, 70, text, size, bold), 10.0, CFG) is not None
    ) is expected


def test_heading_level_from_numbering() -> None:
    h = classify_heading(blk(50, 50, 300, 70, "3.2.1 Detail", 11.5, True), 10.0, CFG)
    assert h is not None and h.level == 3


def test_reference_helpers() -> None:
    assert is_reference_heading("References") and is_reference_heading("7 REFERENCES")
    assert not is_reference_heading("Reference frames")
    assert ends_references("Appendix B") and ends_references("A Additional results")
    assert not ends_references("Smith et al. 2020")


# ---- metadata ----
def test_resolve_metadata_trust_order() -> None:
    info = {"title": "PDF Title", "author": "A. One and B. Two"}
    assert resolve_metadata(info, "Layout", None, "stem").title == "PDF Title"
    assert resolve_metadata({}, "Layout", None, "stem").title == "Layout"
    assert resolve_metadata({}, None, None, "stem").title == "stem"
    assert resolve_metadata(info, None, None, "s").authors == ("A. One", "B. Two")
    assert resolve_metadata({"title": "x.pdf"}, None, None, "stem").title == "stem"
    assert resolve_metadata({"creationDate": "D:20200101"}, None, None, "s").year is None


# ---- download (local server only; no external network) ------------------------------------------
class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        bodies = {
            "/ok.pdf": b"%PDF-1.4 hello",
            "/html": b"<html>nope</html>",
            "/big.pdf": b"%PDF" + b"x" * 5000,
        }
        body = bodies.get(self.path)
        self.send_response(200 if body else 404)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return


@pytest.fixture
def server() -> Iterator[str]:
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()


def test_download_success_hash_and_atomic(server: str, tmp_path: Path) -> None:
    import hashlib

    digest = download_pdf(f"{server}/ok.pdf", tmp_path / "ok.pdf", tmp_path, 10_000)
    assert digest == hashlib.sha256(b"%PDF-1.4 hello").hexdigest()
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.edge
@pytest.mark.parametrize(
    ("path", "code"),
    [("/html", "not_a_pdf"), ("/big.pdf", "file_too_large"), ("/missing", "parse_error")],
)
def test_download_failures_leave_no_files(
    server: str, tmp_path: Path, path: str, code: str
) -> None:
    with pytest.raises(IngestionFailureError) as info:
        download_pdf(f"{server}{path}", tmp_path / "x.pdf", tmp_path, 1000)
    assert info.value.failure_code == code
    assert list(tmp_path.iterdir()) == []


@pytest.mark.edge
def test_download_refuses_unsafe_inputs(server: str, tmp_path: Path) -> None:
    with pytest.raises(IngestionFailureError, match="https"):
        download_pdf("http://example.com/a.pdf", tmp_path / "a.pdf", tmp_path, 1000)
    with pytest.raises(IngestionFailureError, match="https"):
        download_pdf("file:///etc/passwd", tmp_path / "a.pdf", tmp_path, 1000)
    with pytest.raises(IngestionFailureError):
        download_pdf(f"{server}/ok.pdf", tmp_path.parent / "escape.pdf", tmp_path, 1000)
    download_pdf(f"{server}/ok.pdf", tmp_path / "ok.pdf", tmp_path, 1000)
    with pytest.raises(IngestionFailureError, match="overwrite"):
        download_pdf(f"{server}/ok.pdf", tmp_path / "ok.pdf", tmp_path, 1000)


# ---- fixes driven by real pdfTeX output --------------------------------------------------------
def test_delta_increment_sign_normalised_and_counted() -> None:
    text, stats = clean_text("h = W + \u2206W")
    assert text == "h = W + \u0394W" and stats.symbols_normalized == 1


def test_title_starting_with_letter_a_is_not_a_numbered_heading() -> None:
    from app.ingestion.sections import find_title_block

    title = blk(60, 80, 500, 110, "A Synthetic Study of Efficient Low-Rank Frobnication", 17.2)
    body = blk(60, 300, 500, 400, "Body text here.", 10.0)
    assert find_title_block([title, body], 10.0, 792) is title


def test_style_only_headings_need_a_structured_heading_first() -> None:
    authors = blk(50, 120, 300, 140, "Ada Example", 12.0)
    assert classify_heading(authors, 10.0, CFG, loose_ok=False) is None  # front matter
    assert classify_heading(authors, 10.0, CFG, loose_ok=True) is not None
    numbered = classify_heading(blk(50, 50, 300, 70, "1 Introduction", 12, True), 10.0, CFG, False)
    assert numbered is not None and numbered.structured


def test_rows_from_words_splits_cells_by_gap_and_rows_by_height() -> None:
    from app.ingestion.pymupdf_backend import PyMuPdfBackend

    def w(x0: float, y0: float, text: str) -> tuple[float, float, float, float, str, int, int, int]:
        return (x0, y0, x0 + 6 * len(text), y0 + 8, text, 0, 0, 0)

    words = [
        w(10, 10, "Method"),
        w(80, 10, "Params"),
        w(10, 30, "two"),
        w(32, 30, "words"),
        w(80, 30, "0.1"),
    ]
    rows = PyMuPdfBackend._rows_from_words(words)
    assert rows == (("Method", "Params"), ("two words", "0.1"))


def test_split_word_merge_across_blocks_and_provenance() -> None:
    from app.ingestion.pipeline import _Draft, _merge_split_words
    from app.schemas.ingestion import UnitKind

    def d(page: int, text: str, section: str = "S", ref: bool = False) -> _Draft:
        return _Draft(page, UnitKind.PARAGRAPH, text, section, 1, ref, (0, 0, 1, 1), 0)

    drafts = [
        d(1, "the interpretabil-"),
        d(2, "ity of models"),
        d(2, "Next paragraph."),
        d(2, "ends with a dash -"),
        d(3, "lower case but dash is spaced"),
        d(3, "ref text a-", ref=True),
        d(3, "x continues", ref=False),
    ]
    merged, n, _ = _merge_split_words(drafts, set())
    assert n == 1 and merged[0].text == "the interpretability of models"
    assert (merged[0].page, merged[0].page_end) == (1, 2)  # provenance spans both pages
    assert len(merged) == 6  # only the genuine split word was merged


def test_document_without_structured_headings_keeps_style_headings(tmp_path: Path) -> None:
    from app.ingestion.pipeline import ingest_file
    from tests import pdfgen as g

    html = (
        g.heading("A Paper Title Without Numbering", 22)
        + g.para("Front matter. " + g.BODY)
        + g.heading("Overview Of Things", 13)
        + g.para("Body one. " + g.BODY)
        + g.heading("Another Part Here", 13)
        + g.para("Body two. " + g.BODY)
    )
    path = tmp_path / "loose.pdf"
    path.write_bytes(g.simple_pdf([html]))
    doc = ingest_file(path, IngestionConfig(min_chars_per_page=20)).document
    assert doc is not None
    titles = [u.text for u in doc.units if u.kind.value == "heading"]
    assert titles == ["Overview Of Things", "Another Part Here"]
    assert doc.metadata.paper_title == "A Paper Title Without Numbering"
