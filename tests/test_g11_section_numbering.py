"""G.11 — Section numbering after suppression + HTML/PDF export parity.

When a section is suppressed (empty list / None → not rendered), the TOC
and section headings must renumber sequentially so there are no gaps.

The CSS counter handles section heading numbers automatically (counter-increment
on .section). The TOC is built by _build_toc() with sequential Python numbering.

Export parity (Item 11): every chapter rendered in the HTML view must also be
rendered in the PDF export, in the same order. Conditions that suppress a chapter
must be identical in both paths. This class catches the case where one path is
updated but the other is not.
"""
from __future__ import annotations

import pytest


# ── _build_toc() numbering ────────────────────────────────────────────────────

class TestBuildToc:
    def _toc(self, *args):
        from app.services.pdf_renderer import _build_toc
        return _build_toc(list(args))

    def test_all_present_sequential(self):
        result = self._toc(
            (True,  "s-executive",  "The Opportunity"),
            (True,  "s-evidence",   "Evidence Base"),
            (True,  "s-market",     "Market Sizing"),
        )
        assert "§1" in result
        assert "§2" in result
        assert "§3" in result

    def test_suppressed_middle_section_no_gap(self):
        """Section 2 suppressed → sections are renumbered §1 §2, not §1 §3."""
        result = self._toc(
            (True,  "s-executive",  "The Opportunity"),
            (False, "s-evidence",   "Evidence Base"),   # suppressed
            (True,  "s-market",     "Market Sizing"),
        )
        assert "§1" in result
        assert "§2" in result
        assert "§3" not in result, "Should be §1 §2 when middle section suppressed"
        assert "Evidence Base" not in result

    def test_suppressed_adversarial_no_gap(self):
        """Adversarial review suppressed (empty) → no §14 gap before next steps."""
        result = self._toc(
            (True,  "s-executive",   "The Opportunity"),
            (True,  "s-market",      "Market Sizing"),
            (False, "s-adversarial", "Adversarial Review"),  # suppressed — B-05
            (True,  "s-next-steps",  "Recommended Next Steps"),
        )
        lines = result.strip().split("\n")
        numbers = []
        for line in lines:
            import re
            m = re.search(r"§(\d+)", line)
            if m:
                numbers.append(int(m.group(1)))
        assert numbers == list(range(1, len(numbers) + 1)), (
            f"TOC numbers should be sequential, got {numbers}"
        )

    def test_citations_always_uses_symbol(self):
        """Citations always gets § (not a sequential number)."""
        result = self._toc(
            (True, "s-executive",  "The Opportunity"),
            (True, "s-citations",  "Citations"),
        )
        # The citations entry uses the § symbol, not a counter number
        assert "s-citations" in result
        import re
        cit_line = [l for l in result.split("\n") if "s-citations" in l][0]
        # Should have a bare § not followed by a digit
        assert re.search(r"§</span>", cit_line), (
            f"Citations should use bare § symbol; got: {cit_line}"
        )

    def test_empty_toc_returns_empty_string(self):
        result = self._toc(
            (False, "s-executive", "The Opportunity"),
            (False, "s-market",    "Market Sizing"),
        )
        assert result.strip() == ""

    def test_all_15_sections_present(self):
        """Full report: 15 numbered sections + Citations."""
        from app.services.pdf_renderer import _build_toc
        entries = [
            (True, "s-executive",    "The Opportunity"),
            (True, "s-evidence",     "Evidence Base"),
            (True, "s-market",       "Market Sizing"),
            (True, "s-regulatory",   "Regulatory"),
            (True, "s-access",       "Market Access"),
            (True, "s-competitive",  "Competitive Landscape"),
            (True, "s-value-drivers","Value Drivers"),
            (True, "s-segments",     "Segment Fit"),
            (True, "s-features",     "Feature Posture"),
            (True, "s-pricing",      "Pricing"),
            (True, "s-positioning",  "Positioning"),
            (True, "s-risks",        "Strategic Risks"),
            (True, "s-guiding",      "Guiding Question"),
            (True, "s-adversarial",  "Adversarial Review"),
            (True, "s-next-steps",   "Next Steps"),
            (True, "s-citations",    "Citations"),
        ]
        result = _build_toc(entries)
        import re
        numbers = [int(m.group(1)) for m in re.finditer(r"§(\d+)", result)]
        assert numbers == list(range(1, 16)), f"Expected 1-15, got {numbers}"


# ── CSS counter: sec-num spans must be empty ──────────────────────────────────

class TestSecNumSpansEmpty:
    """Verify all .sec-num spans carry no hardcoded number — CSS counter fills them."""

    def test_no_hardcoded_numbers_in_market_sizing(self):
        from app.services.pdf_renderer import _render_market_sizing
        html = _render_market_sizing({
            "steps": [{"label": "Labs", "value": "1000", "unit": "labs"}],
            "total_addressable_market_usd": 50_000_000,
        })
        import re
        # sec-num spans must be empty (CSS counter provides the number)
        hardcoded = re.findall(r'class="sec-num">(\d+)<', html)
        assert not hardcoded, f"Hardcoded numbers found in sec-num: {hardcoded}"

    def test_no_hardcoded_numbers_in_full_render(self):
        """Full report render must have no hardcoded sec-num content."""
        from app.services.pdf_renderer import render_report_html
        import re
        report = {
            "executive_summary": "A great product.",
            "market_sizing": {
                "total_addressable_market_usd": 100_000_000,
                "steps": [],
            },
            "adversarial_review": [],   # suppressed
            "recommended_next_steps": ["Step A"],
        }
        html = render_report_html(report)
        hardcoded = re.findall(r'class="sec-num">(\d+)<', html)
        assert not hardcoded, (
            f"Hardcoded numbers in sec-num spans: {hardcoded} — "
            "should be empty (CSS counter fills them)"
        )

    def test_counter_reset_in_css(self):
        """The rendered HTML must include counter-reset on .page-content."""
        from app.services.pdf_renderer import render_report_html
        html = render_report_html({"executive_summary": "Test"})
        assert "counter-reset: section" in html, (
            "CSS counter-reset not found — section numbering will be broken"
        )
        assert "counter-increment: section" in html, (
            "CSS counter-increment not found — sections won't increment counter"
        )


# ── Item 11: Export parity — HTML chapter order == PDF heading order ───────────

import os
import re as _re


def _app_html() -> str:
    path = os.path.normpath(
        os.path.join(
            os.path.dirname(__file__), "..", "..", "ProjectElevate-Frontend", "app.html"
        )
    )
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestExportParity:
    """Spec v8 Item 11: The HTML view and the jsPDF export must render the same
    chapter titles in the same order. This test extracts both lists from the
    source and flags any divergence so they can't silently drift apart.

    Extraction strategy:
      HTML side:  chapterHeader(++_sec,  '<title>', ...)  — inside renderPIReport()
      PDF side:   heading(++_pSec, '<title>')             — inside the exportPDF async block

    Because `heading` is a local function defined inside exportPDF, we isolate
    it by slicing from "async function downloadPDF" onward.
    """

    def _html_chapters(self, src: str) -> list[str]:
        """Extract chapter titles from chapterHeader(++_sec, '...') calls."""
        return _re.findall(
            r"chapterHeader\(\s*\+\+_sec\s*,\s*['\"]([^'\"]+)['\"]",
            src,
        )

    def _pdf_headings(self, src: str) -> list[str]:
        """Extract headings from heading(++_pSec, '...') calls in exportPDF."""
        # Isolate the exportPDF function body to avoid matching unrelated `heading` calls
        export_start = src.find("async function downloadPDF")
        assert export_start != -1, "exportPDF function not found in app.html"
        export_src = src[export_start:]
        return _re.findall(
            r"heading\(\s*\+\+_pSec\s*,\s*['\"]([^'\"]+)['\"]",
            export_src,
        )

    def test_chapter_count_matches(self):
        """HTML and PDF must have the same number of chapter declarations."""
        src = _app_html()
        html_ch = self._html_chapters(src)
        pdf_ch  = self._pdf_headings(src)
        assert len(html_ch) == len(pdf_ch), (
            f"Chapter count divergence: HTML has {len(html_ch)} chapters, "
            f"PDF has {len(pdf_ch)}.\n"
            f"  HTML: {html_ch}\n"
            f"  PDF:  {pdf_ch}"
        )

    def test_chapter_order_matches(self):
        """HTML and PDF chapter titles must appear in the same order."""
        src = _app_html()
        html_ch = self._html_chapters(src)
        pdf_ch  = self._pdf_headings(src)
        assert html_ch == pdf_ch, (
            f"Chapter order divergence between HTML view and PDF export:\n"
            f"  HTML: {html_ch}\n"
            f"  PDF:  {pdf_ch}\n"
            "Update whichever path is missing or out of order."
        )

    def test_competitive_landscape_unconditional_in_pdf(self):
        """Competitive Landscape must be rendered unconditionally in the PDF (parity
        with HTML which always renders it). The `if (hasCL)` guard must not wrap
        the heading(++_pSec, ...) call — only the content inside it."""
        src = _app_html()
        export_start = src.find("async function downloadPDF")
        export_src = src[export_start:]

        # Find the heading call for Competitive Landscape
        cl_heading_pos = export_src.find("heading(++_pSec,'Competitive Landscape')")
        if cl_heading_pos == -1:
            cl_heading_pos = export_src.find('heading(++_pSec, "Competitive Landscape")')
        assert cl_heading_pos != -1, "Competitive Landscape heading not found in exportPDF"

        # The 150 chars before the heading call must NOT contain "if (hasCL)"
        ctx_before = export_src[max(0, cl_heading_pos - 150):cl_heading_pos]
        assert "if (hasCL)" not in ctx_before and "if(hasCL)" not in ctx_before, (
            "Competitive Landscape heading is still wrapped in `if (hasCL)` — "
            "this causes the section number to diverge from the HTML view when no "
            "competitor data is available. Remove the outer `if (hasCL)` guard and "
            "render a brief note inside when competitors are absent."
        )

    def test_html_competitive_landscape_unconditional(self):
        """HTML must also render Competitive Landscape unconditionally (baseline)."""
        src = _app_html()
        # Isolate renderPIReport function
        render_start = src.find("function renderPIReport(")
        assert render_start != -1
        render_src = src[render_start:]

        # Find the chapterHeader call for Competitive Landscape
        pos = render_src.find("chapterHeader(++_sec, 'Competitive Landscape'")
        if pos == -1:
            pos = render_src.find('chapterHeader(++_sec, "Competitive Landscape"')
        assert pos != -1, "Competitive Landscape chapterHeader not found in renderPIReport"

        # 200 chars before must not be inside an `if` guard
        ctx_before = render_src[max(0, pos - 200):pos]
        # There should be no unclosed `if (...)` immediately before this call
        # (a simple check: no `if (` within 80 chars that hasn't been closed)
        nearby = render_src[max(0, pos - 80):pos]
        assert "if (" not in nearby and "if(" not in nearby, (
            "Competitive Landscape chapterHeader appears to be inside an `if` guard — "
            "it should always render (with a loading placeholder) for section number parity."
        )
