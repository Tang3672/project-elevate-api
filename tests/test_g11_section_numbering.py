"""G.11 — Section numbering after suppression.

When a section is suppressed (empty list / None → not rendered), the TOC
and section headings must renumber sequentially so there are no gaps.

The CSS counter handles section heading numbers automatically (counter-increment
on .section). The TOC is built by _build_toc() with sequential Python numbering.
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
