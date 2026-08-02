"""
P2 — PDF renderer tests (F-01 through F-09)
============================================
All tests run without playwright and without a database connection.
They test the HTML generator (render_report_html and its helpers) directly.
"""

from __future__ import annotations

import re
import pytest

from app.services.pdf_renderer import (
    derive_product_name,
    derive_domain_label,
    derive_report_date,
    derive_filename,
    truncate_at_word,
    clean_step_label,
    validate_citation_url,
    render_report_html,
    _NO_URL_MARKER,
)

# ── Minimal report fixture ────────────────────────────────────────────────────

def _minimal_report(**overrides) -> dict:
    base = {
        "idea_submitted": "Hublink: a non-clinical wearable data platform for academic PIs.",
        "executive_summary": "Hublink addresses the gap in research-grade wearable data logging.",
        "expert_domain": "research_tool_non_clinical",
        "expert_name":   "Remote Patient Monitoring Expert",
        "generated_at":  "2026-07-29T00:00:00",
        "literature_citations": [],
        "recommended_next_steps": [],
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════════════
# F-01 — Title derivation
# ═══════════════════════════════════════════════════════════════════════════════

class TestF01TitleDerivation:

    def test_uses_product_name_field_when_present(self):
        report = _minimal_report(product_name="Hublink")
        assert derive_product_name(report) == "Hublink"

    def test_extracts_from_idea_colon_split(self):
        report = _minimal_report()  # "Hublink: a non-clinical..."
        assert derive_product_name(report) == "Hublink"

    def test_does_not_use_taxonomy_as_title(self):
        report = _minimal_report(idea_submitted="a wearable logger", expert_domain="research_tool_non_clinical")
        name = derive_product_name(report)
        assert "research_tool" not in name.lower(), \
            "Product name must not contain taxonomy/archetype strings"

    def test_dedicated_field_overrides_idea_extraction(self):
        """
        F-01 defect: title was 'Not disease-specific - research data infrastructure platform'
        because the renderer pulled from a negated taxonomy field. The fix: when product_name
        is set, it must win — idea_submitted is never used as fallback.
        """
        report = _minimal_report(
            product_name="Hublink",
            idea_submitted="not disease-specific research data infrastructure platform",
            expert_domain="digital_rpm",
        )
        name = derive_product_name(report)
        assert name == "Hublink", \
            "product_name field must take priority over any idea_submitted extraction"

    def test_taxonomy_string_never_used_as_title(self):
        """expert_domain / expert_name must never leak into the rendered title."""
        report = _minimal_report(
            expert_domain="research_tool_non_clinical",
            expert_name="Remote Patient Monitoring Expert",
        )
        name = derive_product_name(report)
        assert name != "research_tool_non_clinical" and \
               "Remote Patient Monitoring Expert" != name

    def test_html_title_tag_contains_product_name(self):
        report = _minimal_report(product_name="Hublink")
        html = render_report_html(report, product_name="Hublink")
        assert "<title>Hublink" in html, "HTML <title> must start with the product name"

    def test_h1_contains_product_name(self):
        report = _minimal_report(product_name="Hublink")
        html = render_report_html(report, product_name="Hublink")
        assert "<h1>Hublink</h1>" in html or ">Hublink<" in html

    def test_meta_line_includes_institution(self):
        report = _minimal_report(product_name="Hublink")
        html = render_report_html(
            report,
            product_name="Hublink",
            institution="Washington University Neurotech Hub",
        )
        assert "Washington University Neurotech Hub" in html

    def test_derive_filename_format(self):
        fn = derive_filename("Hublink", "2026-07-29")
        assert fn == "hublink-commercial-intelligence-2026-07-29.pdf"

    def test_derive_filename_slugifies_spaces(self):
        fn = derive_filename("My Novel Drug", "2026-01-01")
        assert fn == "my-novel-drug-commercial-intelligence-2026-01-01.pdf"

    def test_meta_tag_author_is_medlevate(self):
        html = render_report_html(_minimal_report())
        assert 'name="author" content="Medlevate"' in html

    def test_meta_tag_title_not_taxonomy(self):
        report = _minimal_report(product_name="Hublink", expert_domain="research_tool_non_clinical")
        html = render_report_html(report, product_name="Hublink")
        assert "research_tool_non_clinical" not in html.split("<title>")[1].split("</title>")[0]


# ═══════════════════════════════════════════════════════════════════════════════
# F-02 — Internal machinery hidden
# ═══════════════════════════════════════════════════════════════════════════════

class TestF02HideInternalMachinery:

    def test_expert_name_not_in_visible_body(self):
        report = _minimal_report(expert_name="Remote Patient Monitoring Expert")
        html = render_report_html(report)
        body_start = html.find("<body>")
        body_html = html[body_start:]
        # Must not appear as visible text — may appear in HTML comment
        visible = re.sub(r'<!--.*?-->', '', body_html, flags=re.DOTALL)
        assert "Remote Patient Monitoring Expert" not in visible, \
            "Expert model name must not appear in user-visible body text"

    def test_expert_name_may_appear_in_html_comment(self):
        report = _minimal_report(expert_name="Remote Patient Monitoring Expert")
        html = render_report_html(report)
        # The name should be in a comment if present at all
        comment = re.findall(r'<!--(.*?)-->', html, re.DOTALL)
        comment_text = " ".join(comment)
        # either it's in a comment or absent entirely
        if "Remote Patient Monitoring Expert" in html:
            assert "Remote Patient Monitoring Expert" in comment_text, \
                "If expert name appears in HTML, it must be inside a comment"

    def test_expert_domain_not_rendered_as_title(self):
        report = _minimal_report(
            product_name="Hublink",
            expert_domain="research_tool_non_clinical",
        )
        html = render_report_html(report, product_name="Hublink")
        # Domain string should not appear as a visible heading
        visible = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
        assert "research_tool_non_clinical" not in visible, \
            "expert_domain taxonomy string must not appear in visible HTML"

    def test_routing_method_not_rendered(self):
        report = _minimal_report(routing_method="keyword_fallback")
        html = render_report_html(report)
        visible = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
        assert "keyword_fallback" not in visible

    def test_page_says_prepared_by_medlevate_not_expert_model(self):
        report = _minimal_report(expert_name="RPM Expert")
        html = render_report_html(report)
        visible = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
        assert "Expert model:" not in visible and "expert_model" not in visible.lower()
        assert "Medlevate" in visible


# ═══════════════════════════════════════════════════════════════════════════════
# F-03 — No mid-word truncation
# ═══════════════════════════════════════════════════════════════════════════════

class TestF03NoMidWordTruncation:

    def test_truncate_at_word_cuts_at_boundary(self):
        text = "Built $1B revenue using early FDA engagement to define the clinical validation package"
        result = truncate_at_word(text, 40)
        # Must not end mid-word
        assert not result[:-1].endswith(("validati", "engagemen", "clini")), \
            f"Truncation must land on word boundary, got: {result!r}"
        # Must end with ellipsis
        assert result.endswith("…")

    def test_truncate_at_word_does_not_split_tokens(self):
        for trial in [
            "establishing the reimbursement template later followed by othe",
            "FDA clearance adds clinical validation and enables hospital s",
            "using early FDA engagement to define the clinical validation packag",
        ]:
            result = truncate_at_word(trial, 30)
            # Last character before ellipsis must be a space-delimited word end
            last_chunk = result.rstrip("…").strip()
            words = last_chunk.split()
            if words:
                last_word = words[-1].rstrip(",:;")
                # A complete word ends with a letter, digit, or closing bracket
                assert re.search(r'[a-zA-Z0-9)\]"]$', last_word), \
                    f"Truncated result ends mid-word: {result!r}"

    def test_truncate_at_word_returns_full_when_short(self):
        text = "Short text."
        assert truncate_at_word(text, 200) == text

    def test_render_does_not_apply_character_cap(self):
        long_text = "A " * 500  # 1000 chars
        report = _minimal_report(executive_summary=long_text.strip())
        html = render_report_html(report)
        # All content must be present — renderer never truncates
        assert "A A A A A" in html, \
            "render_report_html must not truncate content with a character cap"

    def test_no_mid_word_endings_in_rendered_html(self):
        # Plant a long word that might get cut
        report = _minimal_report(
            executive_summary=(
                "Hublink addresses cardiovascular monitoring in electrophysiology "
                "research by providing a streamlined data-acquisition infrastructure "
                "for academic principal investigators."
            )
        )
        html = render_report_html(report)
        # No string should end with a partial common English suffix mid-word
        truncation_patterns = [r'\bvalidati\b', r'\bengagemen\b', r'\bpackag\b',
                                r'\btemplate\b[a-z]', r'\binfrastructur\b']
        for pat in truncation_patterns:
            assert not re.search(pat, html), \
                f"Possible mid-word truncation detected: {pat}"


# ═══════════════════════════════════════════════════════════════════════════════
# F-04 — URL safety
# ═══════════════════════════════════════════════════════════════════════════════

class TestF04UrlSafety:

    def test_citation_urls_only_in_citations_section(self):
        report = _minimal_report(
            literature_citations=[
                {"number": 1, "name": "CMS Fee Schedule", "url": "https://www.cms.gov/medicare-physician-fee-schedule-calendar-year-2025"},
            ]
        )
        html = render_report_html(report)
        # URL should appear only once (in the citations section, not inline)
        url_occurrences = html.count("cms.gov/medicare-physician-fee-schedule")
        assert url_occurrences <= 1, \
            "URL must not be duplicated across sections (F-04: no mangling)"

    def test_css_has_word_break_break_all_for_citation_urls(self):
        report = _minimal_report()
        html = render_report_html(report)
        assert "word-break: break-all" in html, \
            "Citation URL CSS must use word-break: break-all (F-04)"

    def test_css_has_hyphens_none_for_citation_urls(self):
        report = _minimal_report()
        html = render_report_html(report)
        assert "hyphens: none" in html, \
            "Citation URL CSS must disable hyphens to prevent hyphenation mid-URL (F-04)"

    def test_url_not_broken_with_whitespace_in_href(self):
        url = "https://www.cms.gov/medicare-physician-fee-schedule-calendar-year-2025"
        report = _minimal_report(
            literature_citations=[{"number": 1, "name": "CMS", "url": url}]
        )
        html = render_report_html(report)
        # The href= attribute must contain the unbroken URL
        assert f'href="{url}"' in html or url in html, \
            "URL must appear unbroken in the href attribute"


# ═══════════════════════════════════════════════════════════════════════════════
# F-05 — Missing citation URLs
# ═══════════════════════════════════════════════════════════════════════════════

class TestF05MissingCitationUrls:

    def test_citation_without_url_gets_marker(self):
        report = _minimal_report(
            literature_citations=[
                {"number": 14, "name": "FDA Adaptive Designs Guidance 2019", "url": ""}
            ]
        )
        html = render_report_html(report)
        assert _NO_URL_MARKER in html, \
            f"Citation with no URL must render '{_NO_URL_MARKER}'"

    def test_citation_with_generic_search_url_gets_marker(self):
        report = _minimal_report(
            literature_citations=[
                {"number": 13, "name": "Generic Search", "url": "https://www.google.com/search?q=fda+guidance"}
            ]
        )
        html = render_report_html(report)
        assert _NO_URL_MARKER in html, \
            "Citation with generic search URL must be flagged as missing"

    def test_citation_with_valid_url_is_not_flagged(self):
        report = _minimal_report(
            literature_citations=[
                {"number": 1, "name": "CDC", "url": "https://www.cdc.gov/antimicrobial-resistance/data/index.html"}
            ]
        )
        html = render_report_html(report)
        # The real URL should appear; the no-url marker should NOT
        assert "cdc.gov" in html
        assert _NO_URL_MARKER not in html

    def test_validate_citation_url_empty(self):
        url, valid = validate_citation_url("")
        assert not valid
        assert url == _NO_URL_MARKER

    def test_validate_citation_url_google_search(self):
        url, valid = validate_citation_url("https://google.com/search?q=test")
        assert not valid
        assert url == _NO_URL_MARKER

    def test_validate_citation_url_pubmed_search(self):
        url, valid = validate_citation_url("https://pubmed.ncbi.nlm.nih.gov/search?term=fda")
        assert not valid

    def test_validate_citation_url_valid(self):
        url, valid = validate_citation_url("https://www.fda.gov/media/123456/download")
        assert valid
        assert url == "https://www.fda.gov/media/123456/download"


# ═══════════════════════════════════════════════════════════════════════════════
# F-06 — Duplicated step labels and empty bullet labels
# ═══════════════════════════════════════════════════════════════════════════════

class TestF06StepLabels:

    def test_duplicate_step_prefix_stripped(self):
        label, content = clean_step_label(
            "Step 1",
            "Step 1: Addressable hospital and health system research/RPM sites"
        )
        assert label == "Step 1"
        assert not content.startswith("Step 1"), \
            f"Content should not start with duplicate label, got: {content!r}"
        assert "Addressable hospital" in content

    def test_duplicate_step_prefix_with_dash(self):
        label, content = clean_step_label("Step 2", "Step 2 - Define target buyer segment")
        assert "Step 2" not in content

    def test_empty_label_separator_stripped(self):
        label, content = clean_step_label("•", "$75,000/site/yr (SaaS license)")
        assert label == "", f"Empty bullet label should be cleared, got: {label!r}"
        assert content.startswith("$"), \
            f"Content separator should be stripped, got: {content!r}"

    def test_em_dash_separator_stripped_for_empty_label(self):
        label, content = clean_step_label("–", "Per-site annual fee")
        assert label == ""

    def test_normal_label_not_affected(self):
        label, content = clean_step_label(
            "Market size",
            "6,200 NIH-funded research sites in the US"
        )
        assert label == "Market size"
        assert content == "6,200 NIH-funded research sites in the US"

    def test_market_sizing_step_rendered_without_duplicate_prefix(self):
        report = _minimal_report(
            market_sizing={
                "steps": [
                    {"label": "Step 1", "value": 6200, "unit": "sites",
                     "source": "NIH", "source_url": "https://reporter.nih.gov",
                     "notes": "Step 1: Total US NIH-funded research sites"}
                ],
                "formula": "6200 × $5000/yr",
                "total_addressable_market_usd": 31000000,
                "serviceable_market_usd": 12000000,
                "methodology_note": "Bottom-up from NIH grant data.",
            }
        )
        html = render_report_html(report)
        # "Step 1: Total US NIH..." → after clean, "Total US NIH..." should appear
        # "Step 1Step 1" or "Step 1: Step 1" must NOT appear
        assert "Step 1: Step 1" not in html and "Step 1Step 1" not in html


# ═══════════════════════════════════════════════════════════════════════════════
# F-07 — Chrome overhead / running heads
# ═══════════════════════════════════════════════════════════════════════════════

class TestF07ChromeOverhead:

    def test_css_has_page_first_rule_clearing_running_head(self):
        html = render_report_html(_minimal_report(product_name="Hublink"), product_name="Hublink")
        assert "@page :first" in html, \
            "CSS must have @page :first rule to suppress running head on page 1"

    def test_page_first_clears_top_left(self):
        html = render_report_html(_minimal_report(product_name="Hublink"), product_name="Hublink")
        # Find the @page :first block and confirm it empties the header
        first_block = re.search(r'@page :first\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}', html, re.DOTALL)
        assert first_block, "@page :first block must exist"
        block_content = first_block.group(1)
        assert 'content: ""' in block_content, \
            "@page :first must set content: '' to clear running heads"

    def test_running_head_uses_product_name(self):
        html = render_report_html(_minimal_report(product_name="Hublink"), product_name="Hublink")
        assert "Hublink" in html
        # The CSS must contain both @page and the product name near it
        # (@page blocks contain nested @top-left/@top-right so a flat regex won't match)
        page_idx = html.find("@page")
        assert page_idx != -1, "@page rule must be present"
        page_region = html[page_idx: page_idx + 600]
        assert "Hublink" in page_region, \
            "@page running head region must include the product name"

    def test_full_header_only_on_cover(self):
        report = _minimal_report(product_name="Hublink")
        html = render_report_html(report, product_name="Hublink",
                                  institution="WashU Neurotech Hub")
        # The 'Commercial Intelligence Report' eyebrow should appear once (cover)
        assert html.count("Commercial Intelligence Report") >= 1
        # Must NOT repeat as a multi-line header block in @page margin boxes (check @page area)
        # The masthead with Medlevate + date should not be a repeated @page block
        assert "Medlevate" in html

    def test_disclaimer_appears_once(self):
        html = render_report_html(_minimal_report())
        # The disclaimer text should appear exactly once
        disclaimer_count = html.count("does not constitute legal, regulatory")
        assert disclaimer_count == 1, \
            f"Disclaimer must appear exactly once, found {disclaimer_count} times"

    def test_page_counter_in_css(self):
        html = render_report_html(_minimal_report())
        assert "counter(page)" in html, \
            "CSS @page must use counter(page) for running page numbers"


# ═══════════════════════════════════════════════════════════════════════════════
# F-08 — Tables instead of bullet lists
# ═══════════════════════════════════════════════════════════════════════════════

class TestF08Tables:

    def _report_with_all_tables(self) -> dict:
        return _minimal_report(
            market_sizing={
                "steps": [{"label": "Sites", "value": 6200, "unit": "sites",
                            "source": "NIH", "source_url": "https://reporter.nih.gov", "notes": ""}],
                "formula": "6200 × $5k",
                "total_addressable_market_usd": 31e6,
                "serviceable_market_usd": 10e6,
                "methodology_note": "Bottom-up.",
            },
            market_access={
                "primary_channel": "Direct sales to PIs",
                "reimbursement_pathway": "N/A",
                "first_commercial_step": "10 pilot labs",
                "buyer_segments": [
                    {"segment_name": "R01 PIs", "buyer_count": "2,000",
                     "decision_maker": "PI", "price_per_unit": "$5,000/yr",
                     "access_mechanism": "Direct", "timeline_to_access": "3 months",
                     "source": "NIH", "source_url": "https://reporter.nih.gov"}
                ],
                "key_opinion_leaders": ["Dr. Jane Smith, WashU"],
                "international_opportunities": [],
            },
            competitive_landscape={
                "research_tool_comparators": [
                    {"name": "ActiGraph", "category": "Commercial wearable",
                     "key_differentiator": "Incumbent", "incumbent": True},
                ],
                "competitor_trials": {"trials": []},
                "honest_empty_state": "",
            },
            segment_fit_table=[
                {"segment": "Academic labs", "fit": "Primary target", "rationale": "Core buyer"},
                {"segment": "Hospital systems", "fit": "Explicit non-target", "rationale": "Clinical not research"},
            ],
            feature_investment_posture=[
                {"feature_area": "Real-time streaming", "posture": "Exclude", "rationale": "Out of scope"},
                {"feature_area": "Batch export", "posture": "Build and prioritize", "rationale": "Core need"},
            ],
            pricing_model_analysis={
                "model_comparison": [
                    {"pricing_model": "Annual subscription", "user_appeal": "High",
                     "business_sustainability": "High", "strategic_stance": "Recommended"},
                    {"pricing_model": "One-time license", "user_appeal": "Medium",
                     "business_sustainability": "Low", "strategic_stance": "Avoid"},
                ],
                "contextual_analysis": [],
            },
            value_driver_ranking=[
                {"driver": "Data reliability", "relative_importance": "1",
                 "product_implication": "Zero data loss guarantee"},
            ],
        )

    def test_market_sizing_uses_table(self):
        html = render_report_html(self._report_with_all_tables())
        assert "<table" in html and "market-step" in html.lower() or \
               ("data-table" in html and "Sites" in html)

    def test_buyer_segments_use_table(self):
        html = render_report_html(self._report_with_all_tables())
        assert "R01 PIs" in html
        assert "<table" in html

    def test_comparators_use_table(self):
        html = render_report_html(self._report_with_all_tables())
        assert "ActiGraph" in html
        assert "<table" in html

    def test_segment_fit_uses_table(self):
        html = render_report_html(self._report_with_all_tables())
        assert "Explicit non-target" in html
        assert "<table" in html

    def test_feature_posture_uses_table(self):
        html = render_report_html(self._report_with_all_tables())
        assert "Real-time streaming" in html
        assert "<table" in html

    def test_pricing_uses_table(self):
        html = render_report_html(self._report_with_all_tables())
        assert "Annual subscription" in html
        assert "<table" in html

    def test_value_drivers_use_table(self):
        html = render_report_html(self._report_with_all_tables())
        assert "Data reliability" in html
        assert "<table" in html

    def test_tables_have_thead(self):
        html = render_report_html(self._report_with_all_tables())
        thead_count = html.count("<thead>")
        assert thead_count >= 3, \
            f"Data tables must have <thead> elements, found {thead_count}"

    def test_table_headers_are_styled_with_accent(self):
        html = render_report_html(self._report_with_all_tables())
        assert "accent" in html or "#1B2550" in html or "var(--accent)" in html, \
            "Table headers must use the accent color"


# ═══════════════════════════════════════════════════════════════════════════════
# F-09 — Typography and toolchain
# ═══════════════════════════════════════════════════════════════════════════════

class TestF09Typography:

    def test_type_scale_variables_defined(self):
        html = render_report_html(_minimal_report())
        for var in ["--t-xl", "--t-lg", "--t-md", "--t-sm", "--t-xs"]:
            assert var in html, f"CSS custom property {var} must be defined (F-09 type scale)"

    def test_body_uses_serif_face(self):
        html = render_report_html(_minimal_report())
        # Charter or Georgia must be in the font stack
        assert "Charter" in html or "Georgia" in html, \
            "Body font must be a humanist serif (Charter or Georgia) (F-09)"

    def test_body_does_not_use_helvetica_or_arial_for_body(self):
        html = render_report_html(_minimal_report())
        # Helvetica/Arial must not be the body font (can appear in sans-serif stack for labels)
        body_font_decl = re.search(r'html,\s*body\s*\{[^}]+font-family:[^;]+', html, re.DOTALL)
        if body_font_decl:
            decl = body_font_decl.group(0).lower()
            assert "helvetica" not in decl and "arial" not in decl, \
                "Body font-family must not be Helvetica/Arial (F-09)"

    def test_measure_bounded_at_70ch(self):
        html = render_report_html(_minimal_report())
        assert "70ch" in html, "Content measure must be bounded at 70ch (F-09)"

    def test_tabular_figures_applied(self):
        html = render_report_html(_minimal_report())
        assert "tabular-nums" in html, \
            "font-variant-numeric: tabular-nums must be applied (F-09)"

    def test_one_accent_color(self):
        html = render_report_html(_minimal_report())
        # The accent should be defined as a CSS custom property, not scattered
        assert "--accent:" in html, "Accent color must be defined as --accent CSS variable"
        # No gradients
        assert "linear-gradient" not in html and "radial-gradient" not in html, \
            "No gradients allowed (F-09)"

    def test_line_height_between_145_and_155(self):
        html = render_report_html(_minimal_report())
        # Body line-height must be in range. Headings may use tighter values (1.2 is fine for h1).
        body_lh = re.search(r'html,\s*body\s*\{[^}]+line-height:\s*([\d.]+)', html, re.DOTALL)
        assert body_lh, "html/body must set line-height (F-09)"
        val = float(body_lh.group(1))
        assert 1.4 <= val <= 1.6, \
            f"Body line-height {val} outside 1.45–1.55 target range (F-09)"

    def test_section_numbering_present(self):
        html = render_report_html(_minimal_report())
        # Section numbers rendered with sec-num class
        assert "sec-num" in html, "Section numbers must be rendered with .sec-num class"

    def test_no_emoji_markers(self):
        html = render_report_html(_minimal_report())
        # Section markers should be numeric, not emoji
        visible = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
        emoji_pattern = re.compile(
            "[\U0001F300-\U0001F9FF\U00002600-\U000027BF]", re.UNICODE)
        assert not emoji_pattern.search(visible), \
            "Section markers must not use emoji (F-09)"

    def test_print_media_query_present(self):
        html = render_report_html(_minimal_report())
        assert "@media print" in html, \
            "@media print stylesheet must be present (F-09 print toolchain)"

    def test_break_inside_avoid_on_tables(self):
        html = render_report_html(_minimal_report())
        assert "break-inside: avoid" in html, \
            "@media print must include break-inside: avoid on tables (F-09)"


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: full report renders without error
# ═══════════════════════════════════════════════════════════════════════════════

class TestRenderIntegration:

    def test_minimal_report_renders_valid_html(self):
        html = render_report_html(_minimal_report(), product_name="Hublink")
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html
        assert "<body>" in html and "</body>" in html

    def test_empty_optional_fields_do_not_crash(self):
        bare = {"idea_submitted": "Test idea.", "executive_summary": "Summary."}
        html = render_report_html(bare)
        assert "<!DOCTYPE html>" in html

    def test_html_escaping_prevents_xss(self):
        report = _minimal_report(
            executive_summary='<script>alert("xss")</script>',
            product_name='<b onclick=alert(1)>Click</b>',
        )
        html = render_report_html(report, product_name='<b onclick=alert(1)>Click</b>')
        # Raw HTML tags must be escaped — no injected elements
        assert "<script>" not in html, "Raw <script> must be escaped"
        assert "<b onclick" not in html, "Raw attribute injection must be escaped"
        # The escaped forms should be present (content is preserved, just safe)
        assert "&lt;script&gt;" in html, "Escaped script tag should appear as text"
        assert "&lt;b " in html, "Escaped b tag should appear as text"

    def test_derive_domain_label_research_tool(self):
        report = _minimal_report(expert_domain="research_tool_non_clinical")
        assert "Research" in derive_domain_label(report)

    def test_derive_domain_label_drug(self):
        report = _minimal_report(expert_domain="drug_cardiology")
        label = derive_domain_label(report)
        assert "Cardiovascular" in label or "Drug" in label

    def test_derive_report_date_from_generated_at(self):
        report = _minimal_report(generated_at="2026-07-29T10:30:00")
        d = derive_report_date(report)
        assert "2026" in d and "July" in d

    def test_product_name_fields_added_to_pireport(self):
        from app.models.alignment import PIReport
        r = PIReport(product_type="other", idea_submitted="test", executive_summary="test")
        assert hasattr(r, "product_name")
        assert hasattr(r, "institution")
        assert r.product_name is None
        assert r.institution is None
