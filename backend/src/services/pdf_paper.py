"""Paper sizes a PDF can be laid out for, and the one place PDFs are rendered.

A4 and A5 are cut sheets: the template sets the page size with ``page_css`` and
WeasyPrint paginates as usual. A thermal roll has no page length, so a thermal
document is laid out on a very tall page, measured, and laid out again at exactly
the height its content needs. Each copy becomes one page, and the printer cuts
between pages.
"""

from __future__ import annotations

from typing import Literal, get_args

import weasyprint

from src.services.pdf_render import safe_url_fetcher

Paper = Literal["a4", "a5", "thermal80", "thermal58"]
# Reports are wide tables; on a thermal roll they would be unreadable.
ReportPaper = Literal["a4", "a5"]

PAPERS: tuple[str, ...] = get_args(Paper)
REPORT_PAPERS: tuple[str, ...] = get_args(ReportPaper)
DEFAULT_PAPER: Paper = "a4"

THERMAL_WIDTH_MM: dict[str, int] = {"thermal80": 80, "thermal58": 58}

# Long enough for any receipt: 40 line items lay out in well under a metre.
_THERMAL_LAYOUT_HEIGHT_MM = 5000
_PX_PER_MM = 96 / 25.4


def is_thermal(paper: str | None) -> bool:
    return paper in THERMAL_WIDTH_MM


def thermal_width_mm(paper: str) -> int:
    return THERMAL_WIDTH_MM[paper]


def page_css(
    paper: Paper,
    *,
    landscape: bool = False,
    a4_margin: str = "15mm 18mm",
    a5_margin: str = "8mm",
) -> str:
    """The ``@page`` rule a template embeds for a cut sheet.

    ``a4_margin`` is the template's own A4 margin, so A4 output does not change.
    A thermal template sets only its margin; ``render_pdf`` supplies the size.
    """
    orientation = " landscape" if landscape else ""
    if paper == "a5":
        return f"@page {{ size: A5{orientation}; margin: {a5_margin}; }}"
    if is_thermal(paper):
        return "@page { margin: 0; }"
    return f"@page {{ size: A4{orientation}; margin: {a4_margin}; }}"


def resolve_paper(requested: str | None, company, *, report: bool = False) -> Paper:
    """The paper to print on: the request, then the company default, then A4.

    A report cannot go on a thermal roll, so a thermal company default falls back to
    A4 for one. A thermal *request* for a report never reaches here: the report
    routes type their query parameter as ``ReportPaper`` and FastAPI rejects it.
    """
    allowed = REPORT_PAPERS if report else PAPERS
    if requested in allowed:
        return requested  # type: ignore[return-value]
    default = getattr(company, "default_pdf_paper", None) if company is not None else None
    if default in allowed:
        return default  # type: ignore[return-value]
    return DEFAULT_PAPER


def _html(html: str) -> weasyprint.HTML:
    return weasyprint.HTML(string=html, url_fetcher=safe_url_fetcher)


def _roll_page(width_mm: int, height_mm: float) -> weasyprint.CSS:
    return weasyprint.CSS(string=f"@page {{ size: {width_mm}mm {height_mm:.2f}mm; }}")


def _content_height_mm(document) -> float:
    """How tall the laid-out content of a one-page roll document is.

    WeasyPrint 63.1 is pinned, so reading the page's root box is acceptable; a test
    in tests/services/test_pdf_paper.py pins the behaviour.
    """
    total_px = 0.0
    for page in document.pages:
        root = page._page_box.children[0]
        total_px += root.position_y + root.margin_height()
    return total_px / _PX_PER_MM


def _render_roll(html: str, width_mm: int):
    tall = _html(html).render(stylesheets=[_roll_page(width_mm, _THERMAL_LAYOUT_HEIGHT_MM)])
    # 1mm of slack so rounding can never push the last line onto a second page.
    height_mm = _content_height_mm(tall) + 1
    return _html(html).render(stylesheets=[_roll_page(width_mm, height_mm)])


def render_pdf(html: str | list[str], paper: Paper = DEFAULT_PAPER) -> bytes:
    """Render document HTML to PDF bytes for ``paper``.

    For a cut sheet ``html`` is one document (copies are already page-broken inside
    it). For a thermal roll it is one HTML string per copy, and each copy comes out
    as one page of exactly the length its content needs.
    """
    if is_thermal(paper):
        htmls = [html] if isinstance(html, str) else list(html)
        width_mm = thermal_width_mm(paper)
        documents = [_render_roll(h, width_mm) for h in htmls]
        pages = [page for document in documents for page in document.pages]
        return documents[0].copy(pages).write_pdf()

    if isinstance(html, str):
        return _html(html).write_pdf()
    documents = [_html(h).render() for h in html]
    pages = [page for document in documents for page in document.pages]
    return documents[0].copy(pages).write_pdf()
