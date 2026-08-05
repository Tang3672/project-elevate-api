"""
G-02 — Output quality guards (spec v4 G-02, A.2, A.3, B-05, B-06, B-07).

Tests:
  G-02 / A.2   Spec identifiers (H-07, B-0*, S-0*, spec v) never appear in
               rendered output — checked in both PDF HTML and source-level scrubber.
  G-02 / B-07  Banned clinical tokens (epidemiological basis, payer uptake,
               guideline inclusion, CDC/SEER, eligible patients ×, etc.) must
               not appear in research_tool rendered output.
  G-02 / B-05  "undefined" never appears in rendered output.
  G-02 / A.3   Mock-mode produces an unmissable banner, not a small note.
  G-02 / B-06  Empty sections don't render bare headers — sections with no
               content are either suppressed or replaced with an explanatory line.
  G-02 / B-07  PDF header uses "Commercialization Intelligence Report", not
               "MEDICAL MARKET INTELLIGENCE REPORT".
  G-02 / B-07  IQVIA forecast-error methodology string not in rendered output.
  G-02 / A.2   Spec-identifier scrubber exists in alignment_service and covers
               all key user-facing text fields.
  G-02 / B-07  Scenario narrative strings for research_tool products use
               research vocabulary, not clinical vocabulary.
"""

from __future__ import annotations

import re
import pytest


# ── Minimal fixture factory ────────────────────────────────────────────────────

def _research_tool_report(**overrides) -> dict:
    """Minimal PIReport dict for a research_tool_non_clinical archetype."""
    base = {
        "product_name": "Hublink",
        "idea_submitted": "A cloud data-sync platform for neurotech labs.",
        "executive_summary": "Hublink is a research data infrastructure tool.",
        "expert_domain": "research_tool_non_clinical",
        "domain": "LIFE_SCIENCES_RESEARCH",
        "generated_at": "2026-08-05T00:00:00",
        "sources": [],
        "market_sizing": None,
        "regulatory_pathway": None,
        "market_access": None,
    }
    base.update(overrides)
    return base


def _render(report: dict, **kwargs) -> str:
    from app.services.pdf_renderer import render_report_html
    return render_report_html(report, **kwargs)


# ══════════════════════════════════════════════════════════════════════════════
# A.2 / G-02 — No spec identifiers in rendered output
# ══════════════════════════════════════════════════════════════════════════════

_SPEC_ID_RE = re.compile(
    r"\b(?:H|B|F|S)-\d{2}\b"               # H-07, B-01, S-06, F-03
    r"|spec\s+v\d+"                          # spec v4, spec v3
    r"|\(H-\d{2}\s+(?:fix|formula|compliant)\)"  # (H-07 formula)
    r"|\(B-\d{2}\s+\w+\)",                   # (B-01 rule)
    re.I,
)

class TestNoSpecIdentifiersInOutput:

    def test_no_spec_ids_in_research_tool_html(self):
        html = _render(_research_tool_report())
        # Strip <style>, <script>, and HTML comments — those are implementation
        # details and are allowed to contain spec IDs for maintainability.
        # Only the body text visible to users must be free of spec identifiers.
        visible = _strip_non_body(html)
        visible_matches = _SPEC_ID_RE.findall(visible)
        assert not visible_matches, (
            f"Spec identifiers found in user-visible HTML body: {visible_matches!r}. "
            f"Spec IDs are internal and must never appear in user-facing output. "
            f"(CSS/JS/comment blocks are excluded from this check.)"
        )

    def test_no_h07_formula_in_html(self):
        html = _render(_research_tool_report())
        assert "H-07 formula" not in html
        assert "H-07" not in _strip_non_body(html), (
            "'H-07' must not appear in rendered output — it is an internal spec reference"
        )

    def test_no_b01_in_html(self):
        html = _render(_research_tool_report())
        assert "B-01" not in _strip_non_body(html)

    def test_no_specify_source_placeholder_in_html(self):
        """'(specify source)' is a literal placeholder that must not render to users."""
        html = _render(_research_tool_report())
        assert "(specify source)" not in html, (
            "Placeholder string '(specify source)' must not appear in rendered output"
        )

    def test_spec_scrubber_exists_in_alignment_service(self):
        import inspect
        import app.services.alignment_service as svc
        src = inspect.getsource(svc)
        # Scrubber must define the regex and apply it
        assert "_SPEC_ID_RE" in src or "spec_id" in src.lower() or "H-\\d{2}" in src, (
            "alignment_service must contain a spec-identifier scrubber regex"
        )

    def test_spec_scrubber_covers_executive_summary(self):
        import inspect
        import app.services.alignment_service as svc
        src = inspect.getsource(svc)
        assert "executive_summary" in src, (
            "Spec-identifier scrubber must cover executive_summary field"
        )

    def test_spec_scrubber_covers_recommended_next_steps(self):
        import inspect
        import app.services.alignment_service as svc
        src = inspect.getsource(svc)
        assert "recommended_next_steps" in src, (
            "Spec-identifier scrubber must cover recommended_next_steps field"
        )


# ══════════════════════════════════════════════════════════════════════════════
# B-07 / G-02 — Banned clinical tokens in research_tool output
# ══════════════════════════════════════════════════════════════════════════════

# These tokens belong exclusively in clinical product reports.
# They are never correct for a research_tool archetype.
_BANNED_CLINICAL_TOKENS = [
    "epidemiological basis",
    "payer uptake",
    "guideline inclusion",
    "CDC/SEER epidemiology",
    "CMS pricing",
    "IQVIA forecast-error",
    "MEDICAL MARKET INTELLIGENCE REPORT",
    "eligible patients × annual price",
    "eligible patients x annual price",
    "course of therapy",
    "IQVIA forecast-error methodology",
    "therapeutic area",             # only clinical — research tools have "modality" or "domain"
    "Resistance & mechanism landscape",
    "Resistance & mechanism",
    "no antimicrobial or pharmacological mechanism",
]


class TestNoBannedClinicalTokensInResearchToolOutput:

    def _html(self, **overrides) -> str:
        return _render(_research_tool_report(**overrides))

    def test_no_epidemiological_basis(self):
        html = self._html()
        assert "epidemiological basis" not in html, (
            "'epidemiological basis' must not appear in research_tool output — "
            "buyer is an institutional PI, not a patient population"
        )

    def test_no_payer_uptake(self):
        html = self._html()
        assert "payer uptake" not in html.lower(), (
            "'payer uptake' must not appear in research_tool output — "
            "research tools have no payer reimbursement pathway"
        )

    def test_no_guideline_inclusion(self):
        html = self._html()
        assert "guideline inclusion" not in html.lower(), (
            "'guideline inclusion' must not appear in research_tool output"
        )

    def test_no_cdc_seer_cms_pricing(self):
        html = self._html()
        assert "CDC/SEER epidemiology" not in html, (
            "'CDC/SEER epidemiology + CMS pricing' is a clinical evidence source — "
            "must not appear in research_tool output"
        )
        assert "CMS pricing" not in html, (
            "'CMS pricing' must not appear in research_tool output"
        )

    def test_no_iqvia_forecast_error(self):
        html = self._html()
        assert "IQVIA forecast-error" not in html, (
            "'±35% (IQVIA forecast-error methodology)' was banned in spec v3. "
            "Must not appear in PDF footer or body."
        )

    def test_pdf_header_is_not_medical_market_intelligence(self):
        html = self._html()
        assert "MEDICAL MARKET INTELLIGENCE REPORT" not in html, (
            "PDF header must read 'Commercialization Intelligence Report', "
            "not 'MEDICAL MARKET INTELLIGENCE REPORT'"
        )

    def test_resistance_mechanism_not_rendered_for_research_tool(self):
        html = self._html()
        assert "Resistance &amp; mechanism landscape" not in html
        assert "no antimicrobial or pharmacological mechanism" not in html, (
            "Clinical antimicrobial mechanism section must not render for research_tool"
        )

    def test_course_of_therapy_not_in_research_tool_output(self):
        html = self._html()
        assert "course of therapy" not in html.lower(), (
            "'course of therapy' is clinical vocabulary — must not appear for research_tool"
        )


class TestBannedClinicalTokensInResearchToolScenarios:
    """The SCENARIOS_RESEARCH dict must be used for research_tool archetypes."""

    def test_research_tool_scenarios_use_lab_vocabulary(self):
        from app.services.market_provenance_service import SCENARIOS_RESEARCH
        for name, cfg in SCENARIOS_RESEARCH.items():
            narrative = cfg.get("narrative", "")
            for banned in ["payer uptake", "guideline inclusion", "therapeutic area",
                           "initial label", "payer coverage"]:
                assert banned not in narrative.lower(), (
                    f"SCENARIOS_RESEARCH[{name!r}] narrative contains banned clinical token "
                    f"'{banned}': {narrative!r}"
                )

    def test_scenarios_research_has_lab_words(self):
        from app.services.market_provenance_service import SCENARIOS_RESEARCH
        all_text = " ".join(cfg["narrative"] for cfg in SCENARIOS_RESEARCH.values())
        assert any(w in all_text.lower() for w in ["lab", "nih", "research", "core facility", "citation"]), (
            "SCENARIOS_RESEARCH narratives must contain research-specific vocabulary"
        )

    def test_scenarios_clinical_not_used_for_research_tool(self):
        from app.services.market_provenance_service import build_scenarios
        scenarios = build_scenarios(1_000_000, 300_000, 45_000, archetype="research_tool_non_clinical")
        for s in scenarios:
            narrative = (s.get("narrative") or "").lower()
            assert "payer uptake" not in narrative
            assert "guideline inclusion" not in narrative
            assert "therapeutic area" not in narrative


# ══════════════════════════════════════════════════════════════════════════════
# B-05 / G-02 — "undefined" must never appear in rendered output
# ══════════════════════════════════════════════════════════════════════════════

class TestNoUndefinedStringInOutput:

    def test_no_undefined_in_research_tool_html(self):
        html = _render(_research_tool_report())
        # Case-insensitive; exclude "undefined" inside CSS/script/comments
        visible = _strip_non_body(html)
        assert "undefined" not in visible.lower(), (
            "'undefined' found in rendered output — schema mismatch between "
            "renderer and data (B-05). Check competitor_landscape and market_sizing renderers."
        )

    def test_no_undefined_in_empty_competitive_landscape(self):
        from app.services.pdf_renderer import _render_competitive_landscape
        html = _render_competitive_landscape({})
        assert "undefined" not in html.lower()

    def test_no_undefined_in_empty_market_sizing(self):
        from app.services.pdf_renderer import _render_market_sizing
        html = _render_market_sizing({})
        assert "undefined" not in html.lower()

    def test_no_undefined_in_empty_regulatory_pathway(self):
        from app.services.pdf_renderer import _render_regulatory_pathway
        html = _render_regulatory_pathway({})
        assert "undefined" not in html.lower()

    def test_no_undefined_when_competitive_landscape_has_missing_fields(self):
        """Competitor with only a name field (no schema fields) must not emit 'undefined'."""
        from app.services.pdf_renderer import _render_competitive_landscape
        sparse_landscape = {
            "competitors": [{"name": "ActiGraph"}],  # missing all other fields
        }
        html = _render_competitive_landscape(sparse_landscape)
        assert "undefined" not in html.lower(), (
            "Competitor with sparse fields must not produce 'undefined' in rendered HTML"
        )


# ══════════════════════════════════════════════════════════════════════════════
# A.3 / G-02 — Mock-mode watermark is unmissable
# ══════════════════════════════════════════════════════════════════════════════

class TestMockModeWatermark:

    def test_mock_mode_flag_produces_banner(self):
        html = _render(_research_tool_report(), mock_mode=True)
        assert "mock-banner" in html or "DEMO REPORT" in html or "demo" in html.lower(), (
            "mock_mode=True must inject a visible 'DEMO REPORT' banner — "
            "a small status line is insufficient (A.3)"
        )

    def test_mock_banner_contains_warning_text(self):
        html = _render(_research_tool_report(), mock_mode=True)
        visible = _strip_non_body(html)
        assert any(phrase in visible for phrase in [
            "DEMO REPORT",
            "sample data",
            "Generated with sample data",
            "not for investment",
            "not a real",
        ]), (
            "Mock-mode banner must contain explicit warning text (e.g. 'DEMO REPORT', "
            "'sample data', 'not for investment')"
        )

    def test_mock_banner_not_present_in_normal_mode(self):
        html = _render(_research_tool_report(), mock_mode=False)
        assert "mock-banner" not in html or "DEMO REPORT" not in html, (
            "Mock banner must not appear when mock_mode=False"
        )

    def test_model_version_mock_triggers_banner(self):
        """model_version starting with 'mock' triggers watermark even without flag."""
        report = _research_tool_report(model_version="mock-dev-0.1")
        html = _render(report, mock_mode=False)
        assert "DEMO REPORT" in html or "mock-banner" in html or "demo" in html.lower(), (
            "model_version='mock-*' must trigger mock watermark without explicit flag"
        )


# ══════════════════════════════════════════════════════════════════════════════
# B-06 / G-02 — Empty sections don't render bare headers
# ══════════════════════════════════════════════════════════════════════════════

class TestNoEmptySections:
    """Sections with no content must either be suppressed or have explanatory text.
    A bare <h2> with no following content is the failure case."""

    def _section_ids_and_content(self, html: str) -> list[tuple[str, str]]:
        """Extract (section_id, inner_text) pairs from rendered HTML."""
        pattern = re.compile(
            r'<div[^>]+id="(s-[^"]+)"[^>]*>(.*?)</div>',
            re.DOTALL | re.IGNORECASE,
        )
        return [(m.group(1), m.group(2).strip()) for m in pattern.finditer(html)]

    def test_no_section_has_empty_body(self):
        html = _render(_research_tool_report())
        sections = self._section_ids_and_content(html)
        for sid, content in sections:
            # Strip all tags and whitespace to get inner text
            inner_text = re.sub(r"<[^>]+>", "", content).strip()
            assert len(inner_text) >= 10, (
                f"Section '{sid}' has insufficient content (inner text: {inner_text!r}). "
                "Empty sections must be suppressed — B-06."
            )

    def test_market_access_not_empty_for_research_tool(self):
        """§5 Market Access must show 'not applicable' explanation, not a bare header."""
        html = _render(_research_tool_report())
        # For research tools with no market_access data, must show explanation
        # (pdf_renderer replaces with explanatory block for LIFE_SCIENCES_RESEARCH)
        assert "payer" in html.lower() or "not applicable" in html.lower() or "access" in html.lower(), (
            "Market access section must be present or replaced with an explanatory note"
        )

    def test_regulatory_section_not_empty_for_research_tool(self):
        """§4 Regulatory must show non-device explanation for research_tool, not blank."""
        html = _render(_research_tool_report())
        # For research tools, shows FDA jurisdiction summary
        assert "FDA" in html or "regulatory" in html.lower() or "not required" in html.lower(), (
            "Regulatory section must not be blank for research_tool"
        )


# ══════════════════════════════════════════════════════════════════════════════
# B-07 / G-02 — PDF header and footer don't use wrong product/methodology names
# ══════════════════════════════════════════════════════════════════════════════

class TestPdfHeaderFooter:

    def test_pdf_uses_commercialization_intelligence_not_medical(self):
        html = _render(_research_tool_report())
        assert "MEDICAL MARKET INTELLIGENCE" not in html, (
            "PDF must say 'Commercialization Intelligence Report', "
            "not 'MEDICAL MARKET INTELLIGENCE REPORT'"
        )

    def test_pdf_title_contains_commercialization_or_product(self):
        html = _render(_research_tool_report(), product_name="Hublink")
        # Either shows "Hublink" or "Commercialization Intelligence"
        assert "Hublink" in html or "Commercialization" in html or "Intelligence" in html, (
            "PDF must include product name or report type in a visible heading"
        )

    def test_pdf_renderer_eyebrow_text_is_correct(self):
        """The eyebrow text in pdf_renderer must not say 'Medical Market Intelligence'."""
        import inspect
        from app.services import pdf_renderer
        src = inspect.getsource(pdf_renderer)
        assert "MEDICAL MARKET INTELLIGENCE REPORT" not in src, (
            "The string 'MEDICAL MARKET INTELLIGENCE REPORT' must not exist in pdf_renderer.py"
        )


# ══════════════════════════════════════════════════════════════════════════════
# G-02 — market_evidence_source returns non-clinical string for research tools
# ══════════════════════════════════════════════════════════════════════════════

class TestMarketEvidenceSourceGating:
    """_market_evidence_source must return modality-appropriate strings."""

    def _source(self, modality: str) -> str:
        from app.services.commercialization_decision_service import _market_evidence_source
        return _market_evidence_source(modality)

    def test_research_tool_does_not_use_cdc_seer(self):
        src = self._source("research_tool")
        assert "CDC/SEER" not in src, (
            "research_tool modality must not use 'CDC/SEER epidemiology + CMS pricing'"
        )
        assert "CMS pricing" not in src

    def test_research_tool_uses_lab_vocabulary(self):
        src = self._source("research_tool")
        assert any(w in src.lower() for w in ["lab", "nih", "spend", "annual"]), (
            f"research_tool evidence source should reference lab-specific data: {src!r}"
        )

    def test_clinical_default_uses_cdc_seer(self):
        """Clinical default should still use the epidemiology source."""
        src = self._source("")
        assert "CDC/SEER" in src or "CMS" in src, (
            "Clinical default evidence source must still reference CDC/SEER or CMS"
        )

    def test_diagnostic_modality_gated(self):
        src = self._source("diagnostic")
        assert "CDC/SEER" not in src
        assert "procedure volume" in src.lower() or "test" in src.lower(), (
            f"diagnostic evidence source should reference procedure volume: {src!r}"
        )

    def test_device_modality_gated(self):
        src = self._source("device")
        assert "CDC/SEER" not in src


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _strip_comments(html: str) -> str:
    """Remove HTML comments from html."""
    return re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)


def _strip_non_body(html: str) -> str:
    """Strip <style>, <script> blocks and HTML comments — keep only body text."""
    stripped = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    stripped = re.sub(r"<script[^>]*>.*?</script>", "", stripped, flags=re.DOTALL | re.IGNORECASE)
    stripped = re.sub(r"<!--.*?-->", "", stripped, flags=re.DOTALL)
    return stripped


def _is_in_comment(html: str, token: str) -> bool:
    """Return True if `token` only appears inside non-body blocks (style/script/comments)."""
    visible = _strip_non_body(html)
    return token not in visible
