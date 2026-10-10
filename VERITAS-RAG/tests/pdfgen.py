"""Synthetic PDF generators. All text is invented test content (no copyrighted material)."""

from __future__ import annotations

from collections.abc import Sequence

import pymupdf

BODY = (
    "The quick brown fox studies synthetic gradient methods and reports results on an "
    "invented benchmark. " * 4
)


def _html_box(page: pymupdf.Page, rect: tuple[float, float, float, float], html: str) -> None:
    page.insert_htmlbox(pymupdf.Rect(*rect), html)


def heading(text: str, pt: int = 14) -> str:
    return f'<p style="font-size:{pt}pt;font-weight:bold;margin:0">{text}</p>'


def para(text: str, pt: int = 10) -> str:
    return f'<p style="font-size:{pt}pt;margin:0 0 6pt 0">{text}</p>'


def simple_pdf(pages_html: Sequence[str], size: tuple[float, float] = (612, 792)) -> bytes:
    """One full-width HTML box per page."""
    doc = pymupdf.open()
    for html in pages_html:
        page = doc.new_page(width=size[0], height=size[1])
        _html_box(page, (50, 60, size[0] - 50, size[1] - 60), html)
    return bytes(doc.tobytes())


def two_column_pdf(left: Sequence[str], right: Sequence[str], banner: str | None = None) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    top = 100.0
    if banner:
        _html_box(page, (50, 40, 562, 90), heading(banner, 16))
    _html_box(page, (50, top, 290, 700), "".join(para(t) for t in left))
    _html_box(page, (322, top, 562, 700), "".join(para(t) for t in right))
    return bytes(doc.tobytes())


def table_pdf(rows: Sequence[Sequence[str]]) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    x0, y0, cw, rh = 80.0, 100.0, 100.0, 24.0
    ncols = len(rows[0])
    for r in range(len(rows) + 1):
        page.draw_line((x0, y0 + r * rh), (x0 + ncols * cw, y0 + r * rh))
    for c in range(ncols + 1):
        page.draw_line((x0 + c * cw, y0), (x0 + c * cw, y0 + len(rows) * rh))
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            page.insert_text((x0 + c * cw + 5, y0 + r * rh + 16), cell, fontsize=10)
    return bytes(doc.tobytes())


def image_only_pdf(n_pages: int = 1) -> bytes:
    doc = pymupdf.open()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 120), False)
    pix.set_rect(pix.irect, (200, 200, 200))
    for _ in range(n_pages):
        page = doc.new_page()
        page.insert_image(pymupdf.Rect(50, 50, 400, 400), pixmap=pix)
    return bytes(doc.tobytes())


def header_footer_pdf(n_pages: int, header: str = "Running Title Of The Paper") -> bytes:
    doc = pymupdf.open()
    for i in range(n_pages):
        page = doc.new_page()
        page.insert_text((200, 30), header, fontsize=9)
        page.insert_text((300, 770), str(i + 1), fontsize=9)
        _html_box(page, (50, 80, 562, 700), para(f"UNIQUEPAGE{i + 1} " + BODY))
    return bytes(doc.tobytes())


def encrypted_pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 50), "secret text " * 10)
    aes256 = getattr(pymupdf, "PDF_ENCRYPT_AES_256")  # noqa: B009 - attribute is untyped
    return bytes(doc.tobytes(encryption=aes256, user_pw="u", owner_pw="o"))


ZERO_PAGE_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"
)


def metadata_pdf(title: str, author: str) -> bytes:
    doc = pymupdf.open()
    _html_box(doc.new_page(), (50, 60, 560, 700), para(BODY))
    doc.set_metadata({"title": title, "author": author})
    return bytes(doc.tobytes())
