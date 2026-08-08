"""
B-06 — Suppress empty sections at implementation level; derive title from product_name
=======================================================================================
Failure modes guarded:

  1. Empty section HTML still produces a TOC entry — user sees a dead link.
  2. A section with data is accidentally suppressed from the TOC.
  3. `derive_product_name` returns a negation-prefixed string instead of the
     real product name.
  4. The HTML <title> tag uses a fallback instead of the actual product name.

All tests are pure-Python (no API key, no DB).
"""

from __future__ import annotations

import re

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _render(report: dict, product_name: str = "") -> str:
    from app.services.pdf_renderer import render_report_html
    return render_report_html(report, product_name=product_name)


def _toc_links(html: str) -> list[str]:
    """Return all href anchors listed in the TOC <nav> block."""
    m = re.search(r'<nav class="toc".*?</nav>', html, re.DOTALL)
    if not m:
        return []
    return re.findall(r'href="(#[^"]+)"', m.group(0))


def _section_ids(html: str) -> list[str]:
    """Return all id= attributes on <div class="section"> elements."""
    return re.findall(r'<div class="section[^"]*" id="([^"]+)"', html)


def _html_title(html: str) -> str:
    m = re.search(r"<title>([^<]+)</title>", html)
    return m.group(1) if m else ""


# Minimal populated report for specific sections
def _report(**kwargs) -> dict:
    return kwargs


# ══════════════════════════════════════════════════════════════════════════════
# TOC suppression — TOC entries mirror rendered sections
# ══════════════════════════════════════════════════════════════════════════════

class TestTocSuppression:

    def test_empty_report_has_no_toc_entries(self):
        """A completely empty report dict must produce a TOC with no entries."""
        html = _render({})
        links = _toc_links(html)
        assert links == [], (
            f"Empty report must produce empty TOC but got entries: {links}"
        )

    def test_exec_summary_produces_toc_entry(self):
        html = _render({"executive_summary": "Strong opportunity."})
        assert "#s-executive" in _toc_links(html)

    def test_no_exec_summary_no_toc_entry(self):
        html = _render({"market_sizing": {"steps": [], "total_addressable_market_usd": 1e9}})
        assert "#s-executive" not in _toc_links(html)

    def test_market_sizing_produces_toc_entry(self):
        ms = {
            "steps": [{"label": "US hospitals", "value": "6000", "unit": "sites"}],
            "total_addressable_market_usd": 180_000_000,
        }
        html = _render({"market_sizing": ms})
        assert "#s-market" in _toc_links(html)

    def test_empty_market_sizing_suppresses_toc_entry(self):
        html = _render({"market_sizing": {}})
        assert "#s-market" not in _toc_links(html)

    def test_none_market_sizing_suppresses_toc_entry(self):
        html = _render({"market_sizing": None})
        assert "#s-market" not in _toc_links(html)

    def test_regulatory_pathway_produces_toc_entry(self):
        rp = {"recommended_pathway": "510(k)", "pathway_rationale": "Class II predicate exists."}
        html = _render({"regulatory_pathway": rp})
        assert "#s-regulatory" in _toc_links(html)

    def test_empty_regulatory_suppresses_toc_entry(self):
        html = _render({"regulatory_pathway": {}})
        assert "#s-regulatory" not in _toc_links(html)

    def test_research_domain_regulatory_stub_produces_toc_entry(self):
        """The hardcoded research-domain regulatory stub counts as populated."""
        html = _render({"domain": "LIFE_SCIENCES_RESEARCH", "regulatory_pathway": None})
        assert "#s-regulatory" in _toc_links(html)

    def test_competitive_landscape_produces_toc_entry(self):
        ci = {"research_tool_comparators": [{"name": "ActiGraph", "category": "Wearable",
                                              "description": "Gold standard."}]}
        html = _render({"competitive_landscape": ci})
        assert "#s-competitive" in _toc_links(html)

    def test_empty_competitive_landscape_suppresses_toc_entry(self):
        html = _render({"competitive_landscape": {}})
        assert "#s-competitive" not in _toc_links(html)

    def test_value_driver_ranking_produces_toc_entry(self):
        html = _render({"value_driver_ranking": [{"driver": "Data quality",
                                                   "relative_importance": "High",
                                                   "product_implication": "Build calibration."}]})
        assert "#s-value-drivers" in _toc_links(html)

    def test_empty_value_driver_ranking_suppresses_toc_entry(self):
        html = _render({"value_driver_ranking": []})
        assert "#s-value-drivers" not in _toc_links(html)

    def test_positioning_statement_produces_toc_entry(self):
        html = _render({"positioning_statement": "For PIs who need reliable actigraphy…"})
        assert "#s-positioning" in _toc_links(html)

    def test_no_positioning_statement_suppresses_toc_entry(self):
        html = _render({"positioning_statement": None})
        assert "#s-positioning" not in _toc_links(html)

    def test_strategic_risks_produces_toc_entry(self):
        html = _render({"strategic_risks": ["Risk of commoditization."]})
        assert "#s-risks" in _toc_links(html)

    def test_guiding_question_produces_toc_entry(self):
        html = _render({"guiding_question": "Can we displace ActiGraph in 3 years?"})
        assert "#s-guiding" in _toc_links(html)

    def test_recommended_steps_produces_toc_entry(self):
        html = _render({"recommended_next_steps": ["File provisional patent."]})
        assert "#s-next-steps" in _toc_links(html)

    def test_sources_produces_citations_toc_entry(self):
        html = _render({"sources": [{"name": "NIH grant database",
                                     "url": "https://reporter.nih.gov"}]})
        assert "#s-citations" in _toc_links(html)

    def test_empty_sources_suppresses_citations_toc_entry(self):
        html = _render({"sources": []})
        assert "#s-citations" not in _toc_links(html)


# ══════════════════════════════════════════════════════════════════════════════
# TOC ↔ section content parity — every TOC link has a matching section id
# ══════════════════════════════════════════════════════════════════════════════

class TestTocContentParity:

    def _full_report(self) -> dict:
        return {
            "executive_summary": "Strong opportunity in research wearables.",
            "evidence_base": {"quality_summary": "Moderate", "key_gaps": "Sparse RCTs."},
            "market_sizing": {
                "steps": [{"label": "US labs", "value": "12000", "unit": "sites"}],
                "total_addressable_market_usd": 240_000_000,
            },
            "regulatory_pathway": {
                "recommended_pathway": "FDA-exempt (non-clinical research tool)",
                "pathway_rationale": "No diagnostic claim.",
            },
            "market_access": {
                "primary_channel": "Direct academic sales",
                "buyer_segments": [],
            },
            "competitive_landscape": {
                "research_tool_comparators": [{"name": "ActiGraph", "category": "Wearable",
                                               "description": "Incumbent."}]
            },
            "value_driver_ranking": [{"driver": "Data continuity", "relative_importance": "High",
                                      "product_implication": "Multi-day battery."}],
            "segment_fit_table": [{"segment": "Neuroscience PIs", "fit": "Primary target",
                                   "rationale": "High volume."}],
            "positioning_statement": "For PIs who need reliable actigraphy without data gaps.",
            "strategic_risks": ["Commoditization risk from commodity sensors."],
            "guiding_question": "Can we displace ActiGraph in NIH-funded labs within 3 years?",
            "recommended_next_steps": ["File provisional patent.", "Pilot with 3 labs."],
            "sources": [{"name": "NIH database", "url": "https://reporter.nih.gov"}],
        }

    def test_every_toc_link_has_matching_section(self):
        """Every anchor in the TOC must match a section id in the document body."""
        html = _render(self._full_report())
        toc_anchors = {a.lstrip("#") for a in _toc_links(html)}
        body_ids = set(_section_ids(html))
        orphaned = toc_anchors - body_ids
        assert not orphaned, (
            f"TOC links with no matching section id: {orphaned!r}\n"
            "This would cause dead links in the PDF."
        )

    def test_every_populated_section_is_in_toc(self):
        """Every rendered section must have a corresponding TOC entry."""
        html = _render(self._full_report())
        body_ids = set(_section_ids(html))
        toc_anchors = {a.lstrip("#") for a in _toc_links(html)}
        # Citations section uses class citations-section — include it
        missing = body_ids - toc_anchors
        assert not missing, (
            f"Rendered sections missing from TOC: {missing!r}\n"
            "Users can't navigate to these sections."
        )

    def test_partially_populated_report_parity(self):
        """Subset of sections: TOC anchors must still match body section ids."""
        report = {
            "executive_summary": "Promising.",
            "competitive_landscape": {"research_tool_comparators": [
                {"name": "DIY", "category": "Status quo", "description": "Manual scripts."}
            ]},
        }
        html = _render(report)
        toc_anchors = {a.lstrip("#") for a in _toc_links(html)}
        body_ids = set(_section_ids(html))
        assert toc_anchors == body_ids, (
            f"TOC/body mismatch. TOC: {toc_anchors}, Body: {body_ids}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# derive_product_name — priority chain and negation stripping
# ══════════════════════════════════════════════════════════════════════════════

class TestDeriveProductName:

    def _derive(self, report: dict) -> str:
        from app.services.pdf_renderer import derive_product_name
        return derive_product_name(report)

    def test_product_name_field_takes_priority(self):
        report = {"product_name": "WristLog Pro", "idea_submitted": "Not applicable: a research tool"}
        assert self._derive(report) == "WristLog Pro"

    def test_product_name_strips_whitespace(self):
        assert self._derive({"product_name": "  WristLog Pro  "}) == "WristLog Pro"

    def test_idea_submitted_colon_split(self):
        """First segment before ':' in idea_submitted used when no product_name."""
        report = {"idea_submitted": "WristLog Pro: A research wearable for NIH-funded trials"}
        assert self._derive(report) == "WristLog Pro"

    def test_idea_submitted_negation_stripped(self):
        """Negation prefixes in idea_submitted must be stripped before use."""
        report = {"idea_submitted": "Not applicable — research wearable logger"}
        name = self._derive(report)
        assert not name.lower().startswith("not"), (
            f"derive_product_name must strip negation prefix, got: {name!r}"
        )

    def test_fallback_when_no_fields(self):
        name = self._derive({})
        assert name == "Medlevate Report"

    def test_empty_product_name_falls_through_to_idea(self):
        report = {"product_name": "", "idea_submitted": "WristLog Pro: Research tool"}
        assert self._derive(report) == "WristLog Pro"

    def test_none_product_name_falls_through_to_idea(self):
        report = {"product_name": None, "idea_submitted": "WristLog Pro: Research tool"}
        assert self._derive(report) == "WristLog Pro"


# ══════════════════════════════════════════════════════════════════════════════
# HTML <title> tag uses product_name
# ══════════════════════════════════════════════════════════════════════════════

class TestHtmlTitle:

    def test_title_uses_product_name_param(self):
        html = _render({}, product_name="WristLog Pro")
        title = _html_title(html)
        assert "WristLog Pro" in title

    def test_title_uses_report_product_name_when_param_empty(self):
        html = _render({"product_name": "WristLog Pro"})
        title = _html_title(html)
        assert "WristLog Pro" in title

    def test_title_falls_back_to_idea_submitted(self):
        html = _render({"idea_submitted": "WristLog Pro: A research wearable"})
        title = _html_title(html)
        assert "WristLog Pro" in title

    def test_title_does_not_contain_negation(self):
        """The HTML title must never start with 'Not applicable' or similar."""
        html = _render({"idea_submitted": "Not applicable — research wearable"})
        title = _html_title(html)
        assert not title.lower().startswith("not applicable"), (
            f"HTML <title> must not have negation prefix: {title!r}"
        )

    def test_title_never_empty(self):
        html = _render({})
        title = _html_title(html)
        assert title.strip(), "HTML <title> must never be empty"

    def test_title_html_entities_escaped(self):
        html = _render({}, product_name="WristLog <Pro> & Co")
        title = _html_title(html)
        assert "<Pro>" not in title
        assert "&lt;Pro&gt;" in title


# ══════════════════════════════════════════════════════════════════════════════
# Section content suppression — render functions return "" for empty data
# ══════════════════════════════════════════════════════════════════════════════

class TestSectionRenderersReturnEmptyForNoData:

    def test_market_sizing_empty_dict(self):
        from app.services.pdf_renderer import _render_market_sizing
        assert _render_market_sizing({}) == ""

    def test_market_sizing_none(self):
        from app.services.pdf_renderer import _render_market_sizing
        assert _render_market_sizing(None) == ""

    def test_regulatory_pathway_empty_dict(self):
        from app.services.pdf_renderer import _render_regulatory_pathway
        assert _render_regulatory_pathway({}) == ""

    def test_market_access_empty_dict(self):
        from app.services.pdf_renderer import _render_market_access
        assert _render_market_access({}) == ""

    def test_competitive_landscape_empty_dict(self):
        from app.services.pdf_renderer import _render_competitive_landscape
        assert _render_competitive_landscape({}) == ""

    def test_competitive_landscape_none(self):
        from app.services.pdf_renderer import _render_competitive_landscape
        assert _render_competitive_landscape(None) == ""

    def test_citations_empty_list(self):
        from app.services.pdf_renderer import _render_citations
        assert _render_citations([]) == ""

    def test_recommended_steps_empty_list(self):
        from app.services.pdf_renderer import _render_recommended_steps
        assert _render_recommended_steps([]) == ""

    def test_p1_sections_all_empty(self):
        from app.services.pdf_renderer import _render_p1_sections
        result = _render_p1_sections({})
        assert result == "", f"_render_p1_sections must return '' when all sub-sections empty, got: {result!r}"

    def test_p1_sections_sparse_report(self):
        """Only positioning_statement present → only s-positioning section in output."""
        from app.services.pdf_renderer import _render_p1_sections
        result = _render_p1_sections({"positioning_statement": "For PIs who need X."})
        assert "s-positioning" in result
        assert "s-value-drivers" not in result
        assert "s-segments" not in result
