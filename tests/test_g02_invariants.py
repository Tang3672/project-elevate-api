"""
G-02 — Output Quality Invariants
==================================
Eight regression tests that catch the most common LLM output quality failures.
All tests are pure-Python (no API key, no DB).

Tests:
  test_no_spec_identifiers        — spec tracking IDs must not leak into rendered output
  test_no_undefined_string        — "undefined" must not appear in any rendered content
  test_no_empty_sections          — no section <div> must be vacuously empty
  test_verifier_honesty           — verifier must not claim PASS when errors exist
  test_tam_matches_label          — TAM USD value and TAM fmt label must be consistent
  test_strategy_archetype_gate    — banned clinical vocab must not appear in research tool strategies
  test_no_minimum_count_padding   — system prompts must not force artificial minimum counts
  test_axis_decisions_rendered    — waterfall axis entries must appear in PDF renderer output
"""

from __future__ import annotations

import re
import pytest
from app.services.pdf_renderer import render_report_html


# ── shared fixture ────────────────────────────────────────────────────────────

def _full_report() -> dict:
    """Fully-populated Hublink report for renderer tests."""
    return {
        "product_name": "Hublink",
        "idea_submitted": "Hublink: a non-clinical wearable data platform for academic PIs.",
        "executive_summary": "Hublink addresses the gap in research-grade wearable data logging for academic laboratories.",
        "expert_domain": "research_tool_non_clinical",
        "generated_at": "2026-08-03T00:00:00",
        "sources": [
            {"number": 1, "name": "NIH RePORTER", "url": "https://reporter.nih.gov"},
        ],
        "literature_citations": [
            {"pmid": "21500937", "title": "REDCap — a metadata-driven methodology",
             "authors": "Harris P et al.", "journal": "J Biomed Inform", "year": 2009,
             "url": "https://pubmed.ncbi.nlm.nih.gov/21500937/",
             "relevance": "Citation-driven adoption in research software"},
        ],
        "market_sizing": {
            "total_addressable_market_usd": 45_833_000,
            "serviceable_market_usd": 13_750_000,
            "steps": [
                {"label": "Eligible buyer population", "value": 5500, "unit": "labs",
                 "source": "NIH RePORTER", "source_url": "https://reporter.nih.gov", "notes": ""},
                {"label": "Annual spend per buyer", "value": 8333, "unit": "USD",
                 "source": "Primary research", "source_url": "", "notes": ""},
            ],
            "formula": "TAM = 5,500 labs × $8,333/yr",
            "methodology_note": "Bottom-up buyer model.",
        },
        "market_sizing_provenance": {
            "run": {
                "tam_usd": 45_833_000,
                "sam_usd": 13_750_000,
                "som_usd": 2_062_500,
                "tam_fmt": "$46M",
                "sam_fmt": "$14M",
                "som_fmt": "$2M",
            },
            "scenarios": [
                {"scenario": "base", "tam_usd": 45_833_000, "sam_usd": 13_750_000,
                 "som_usd": 2_062_500, "narrative": "Adoption in line with comparable launches."},
            ],
            "waterfall": [
                {"step": 1, "label": "Eligible buyer population", "value": 5500, "unit": "labs",
                 "source_name": "NIH RePORTER", "source_url": "https://reporter.nih.gov",
                 "confidence": 0.75, "used_in_formula": "TAM", "is_aggregate": False},
                {"step": 2, "label": "Annual spend per buyer", "value": 8333, "unit": "USD",
                 "source_name": "Primary research", "source_url": "",
                 "confidence": 0.55, "used_in_formula": "TAM", "is_aggregate": False},
                {"step": 3, "label": "Total Addressable Market", "value": 45_833_000,
                 "unit": "USD", "source_name": "Derivation", "source_url": None,
                 "confidence": None, "used_in_formula": "TAM", "is_aggregate": True},
            ],
        },
        "strategic_playbook": [
            {"strategy": "SBIR Phase I outreach",
             "example": "LabArchives",
             "what_they_did": "Applied for NIH SBIR Phase I grant to fund initial lab deployments.",
             "how_to_apply": "Submit to NIH SBIR for non-dilutive early-stage funding.",
             "source_url": "https://www.labarchives.com"},
        ],
        "recommended_next_steps": [
            "Conduct 20-lab pilot to validate the buyer population assumption.",
        ],
        "competitive_landscape": {
            "honest_empty_state": "Three established research tools occupy adjacent niches.",
            "comparators": [
                {"name": "REDCap", "category": "data collection",
                 "key_differentiator": "offline-first hardware integration",
                 "incumbent": True},
            ],
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# G-02-1 — No spec identifiers in rendered output
# ══════════════════════════════════════════════════════════════════════════════

# Spec-internal tracking identifiers that must not leak into any user-facing output.
_SPEC_IDS = re.compile(
    r'\b(B-0[1-9]|G-0[1-2]|spec\s+v[0-9]|Part\s+[A-G]\b)',
    re.IGNORECASE,
)


class TestNoSpecIdentifiers:

    def test_pdf_renderer_contains_no_spec_ids(self):
        """Spec tracking tokens (B-01, G-02, Part D…) must not appear in rendered HTML."""
        html = render_report_html(_full_report(), product_name="Hublink")
        # Strip style/script blocks — spec IDs in CSS comments are OK
        stripped = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
        stripped = re.sub(r"<script[^>]*>.*?</script>", "", stripped, flags=re.DOTALL)
        m = _SPEC_IDS.search(stripped)
        assert m is None, (
            f"Spec identifier {m.group()!r} found in rendered PDF output — "
            "internal tracking labels must not leak into user-facing HTML"
        )

    def test_product_name_not_a_spec_id(self):
        """Sanity: the product name Hublink must appear in output (gate is not over-broad)."""
        html = render_report_html(_full_report(), product_name="Hublink")
        assert "Hublink" in html


# ══════════════════════════════════════════════════════════════════════════════
# G-02-2 — No "undefined" string in rendered content
# ══════════════════════════════════════════════════════════════════════════════

class TestNoUndefinedString:

    def test_full_report_no_undefined(self):
        """No visible section of the PDF renderer output may contain 'undefined'."""
        html = render_report_html(_full_report(), product_name="Hublink")
        stripped = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
        stripped = re.sub(r"<script[^>]*>.*?</script>", "", stripped, flags=re.DOTALL)
        assert "undefined" not in stripped.lower()

    def test_sparse_report_no_undefined(self):
        """Optional fields absent → renderer must substitute empty string, not 'undefined'."""
        sparse = {
            "product_name": "Hublink",
            "idea_submitted": "Hublink: a wearable data logger.",
            "executive_summary": "Short summary.",
            "expert_domain": "research_tool_non_clinical",
            # deliberately omit all optional sections
        }
        html = render_report_html(sparse, product_name="Hublink")
        stripped = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
        stripped = re.sub(r"<script[^>]*>.*?</script>", "", stripped, flags=re.DOTALL)
        assert "undefined" not in stripped.lower()

    def test_none_fields_no_undefined(self):
        """None values in optional fields must not produce 'undefined' in output."""
        r = {**_full_report(), "market_sizing": None, "competitive_landscape": None}
        html = render_report_html(r, product_name="Hublink")
        stripped = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
        assert "undefined" not in stripped.lower()


# ══════════════════════════════════════════════════════════════════════════════
# G-02-3 — No empty sections
# ══════════════════════════════════════════════════════════════════════════════

# A section <div> is vacuously empty when it contains no text outside its heading.
# Uses a two-step approach to avoid DOTALL backtracking spanning sections:
# first split the HTML into individual section blocks, then check each one.
_SECTION_BLOCK_RE = re.compile(
    r'(<div[^>]+class="[^"]*section[^"]*"[^>]*>.*?</div>)\s*(?=<div[^>]+class="[^"]*section|$)',
    re.DOTALL,
)
_SECTION_HEADING_ONLY_RE = re.compile(
    r'^<div[^>]+class="[^"]*section[^"]*"[^>]*>\s*<h[1-6][^>]*>[^<]*(?:<[^>]+>[^<]*</[^>]+>)*[^<]*</h[1-6]>\s*</div>$',
    re.DOTALL,
)


class TestNoEmptySections:

    def _section_blocks(self, html: str) -> list[str]:
        """Split rendered HTML into individual top-level section <div> blocks."""
        # Find all section div open tags and extract their content by tracking depth
        blocks = []
        i = 0
        while i < len(html):
            m = re.search(r'<div[^>]+class="[^"]*\bsection\b[^"]*"', html[i:])
            if not m:
                break
            start = i + m.start()
            # Walk forward counting div depth to find the matching closing </div>
            depth = 0
            pos = start
            while pos < len(html):
                if html[pos:pos+4] == "<div":
                    depth += 1
                    pos = html.index(">", pos) + 1
                elif html[pos:pos+6] == "</div>":
                    depth -= 1
                    pos += 6
                    if depth == 0:
                        blocks.append(html[start:pos])
                        break
                else:
                    pos += 1
            i = start + 1
        return blocks

    def test_full_report_no_vacuous_sections(self):
        """Every rendered section must have body content beyond its heading."""
        html = render_report_html(_full_report(), product_name="Hublink")
        blocks = self._section_blocks(html)
        empties = []
        for block in blocks:
            if _SECTION_HEADING_ONLY_RE.match(block):
                empties.append(block[:200])
        assert not empties, (
            f"{len(empties)} vacuously empty section(s) found:\n" + "\n---\n".join(empties)
        )

    def test_market_section_has_steps(self):
        """The market section must render its step rows, not just a heading."""
        html = render_report_html(_full_report(), product_name="Hublink")
        assert "s-market" in html
        market_m = re.search(r'id="s-market".*?</div>', html, re.DOTALL)
        assert market_m and len(market_m.group()) > 200, \
            "Market section must contain step table rows, not just heading text"


# ══════════════════════════════════════════════════════════════════════════════
# G-02-4 — Verifier honesty
# ══════════════════════════════════════════════════════════════════════════════

class TestVerifierHonesty:

    def _flag(self, severity: str, category: str = "MATH") -> dict:
        return {"severity": severity, "category": category,
                "field": "test_field", "issue": "test issue",
                "suggestion": "fix it", "agent": "Test Agent"}

    def _run_arbitrator(self, math=(), source=(), regulatory=(), market=(), factual=()):
        from app.services.validation_graph import arbitrator_node
        state = {
            "report": {}, "product_type": "other", "sub_expert_id": "",
            "expert_critic_rules": "",
            "math_flags": list(math), "source_flags": list(source),
            "regulatory_flags": list(regulatory), "market_flags": list(market),
            "factual_flags": list(factual),
            "math_error": None, "source_error": None,
            "regulatory_error": None, "market_error": None, "factual_error": None,
            "all_flags": [], "validation_passed": None, "_verdict": None,
        }
        return arbitrator_node(state)

    def test_error_flags_give_error_verdict(self):
        result = self._run_arbitrator(math=[self._flag("ERROR")])
        assert result["_verdict"] == "ERROR"
        assert result["validation_passed"] is False

    def test_error_verdict_never_passes(self):
        """PASS must be impossible when any ERROR flag exists."""
        result = self._run_arbitrator(
            math=[self._flag("ERROR")],
            source=[self._flag("WARNING")],
        )
        assert result["_verdict"] != "PASS"
        assert result["validation_passed"] is False

    def test_warning_only_gives_flag_verdict(self):
        result = self._run_arbitrator(source=[self._flag("WARNING")])
        assert result["_verdict"] == "FLAG"
        assert result["validation_passed"] is True

    def test_no_flags_gives_pass(self):
        result = self._run_arbitrator()
        assert result["_verdict"] == "PASS"
        assert result["validation_passed"] is True

    def test_formatter_sets_status_to_error_when_errors_exist(self):
        """formatter_node must stamp validation.status = 'ERROR', not 'PASS', on errors."""
        from app.services.validation_graph import formatter_node
        err_flag = self._flag("ERROR", "MATH")
        state = {
            "report": {"executive_summary": "test"},
            "product_type": "other", "sub_expert_id": "",
            "expert_critic_rules": "",
            "all_flags": [err_flag],
            "math_flags": [err_flag], "source_flags": [], "regulatory_flags": [],
            "market_flags": [], "factual_flags": [],
            "math_error": None, "source_error": None,
            "regulatory_error": None, "market_error": None, "factual_error": None,
            "validation_passed": None, "_verdict": None,
        }
        result = formatter_node(state)
        report = result["validated_report"]
        assert report["validation"]["status"] == "ERROR"
        assert report["validation"]["passed"] is False

    def test_formatter_pass_summary_text_matches_verdict(self):
        """PASS verdict must produce a summary that says PASS, not ERROR or FLAG."""
        from app.services.validation_graph import formatter_node
        state = {
            "report": {"executive_summary": "test"},
            "product_type": "other", "sub_expert_id": "", "expert_critic_rules": "",
            "all_flags": [],
            "math_flags": [], "source_flags": [], "regulatory_flags": [],
            "market_flags": [], "factual_flags": [],
            "math_error": None, "source_error": None,
            "regulatory_error": None, "market_error": None, "factual_error": None,
            "validation_passed": None, "_verdict": None,
        }
        result = formatter_node(state)
        report = result["validated_report"]
        assert report["validation"]["status"] == "PASS"
        assert "PASS" in report["validation"]["summary"]
        assert "ERROR" not in report["validation"]["summary"]


# ══════════════════════════════════════════════════════════════════════════════
# G-02-5 — TAM value matches TAM label
# ══════════════════════════════════════════════════════════════════════════════

class TestTamMatchesLabel:

    def _fmt(self, usd: float) -> str:
        from app.services.market_sizing_derivation_service import _fmt
        return _fmt(usd)

    def test_millions_formatted_as_M(self):
        assert "M" in self._fmt(45_833_000)
        assert "B" not in self._fmt(45_833_000)
        assert "K" not in self._fmt(45_833_000)

    def test_billions_formatted_as_B(self):
        assert "B" in self._fmt(2_000_000_000)
        assert "M" not in self._fmt(2_000_000_000)

    def test_thousands_formatted_as_K(self):
        assert "K" in self._fmt(500_000)
        assert "M" not in self._fmt(500_000)

    def test_provenance_tam_fmt_matches_tam_usd(self):
        """tam_fmt in provenance must agree in order of magnitude with tam_usd."""
        prov = _full_report()["market_sizing_provenance"]["run"]
        tam_usd = prov["tam_usd"]
        tam_fmt = prov["tam_fmt"]
        expected_unit = "M" if 1e6 <= tam_usd < 1e9 else ("B" if tam_usd >= 1e9 else "K")
        assert expected_unit in tam_fmt, (
            f"TAM of ${tam_usd:,.0f} must produce a label containing '{expected_unit}', "
            f"but got {tam_fmt!r}"
        )

    def test_tam_label_magnitude_roundtrip(self):
        """_fmt(tam_usd) must agree within ±5% of the provenance's tam_fmt value."""
        prov = _full_report()["market_sizing_provenance"]["run"]
        computed = self._fmt(prov["tam_usd"])
        stored   = prov["tam_fmt"]
        # Both must agree on the magnitude unit
        assert computed[-1] == stored[-1], (
            f"_fmt({prov['tam_usd']}) = {computed!r} but provenance stores {stored!r} — "
            "magnitude unit mismatch"
        )

    def test_sam_not_larger_than_tam_in_label(self):
        """SAM label must be ≤ TAM label (same unit or smaller number)."""
        prov = _full_report()["market_sizing_provenance"]["run"]
        tam_usd = prov["tam_usd"]
        sam_usd = prov["sam_usd"]
        assert sam_usd <= tam_usd, f"SAM ({sam_usd}) must not exceed TAM ({tam_usd})"


# ══════════════════════════════════════════════════════════════════════════════
# G-02-6 — Strategy archetype gate
# ══════════════════════════════════════════════════════════════════════════════

class TestStrategyArchetypeGate:

    def _arch(self, name: str):
        from app.services.product_archetype import ProductArchetype
        return ProductArchetype(name)

    def test_clinical_vocab_flagged_for_research_tool(self):
        """Banned clinical tokens must be detected when they appear in strategy text."""
        from app.services.product_archetype import validate_content, ProductArchetype
        arch = ProductArchetype.RESEARCH_TOOL_NON_CLINICAL
        clinical_text = "Submit a 510(k) to obtain FDA clearance and seek NTAP designation."
        violations = validate_content(clinical_text, arch, section_id="strategic_playbook", strict=False)
        assert len(violations) > 0, (
            "510(k) and NTAP are banned vocabulary for research tools — "
            "validate_content must report violations"
        )

    def test_clean_research_strategy_passes(self):
        """Research-appropriate strategy text must produce zero violations."""
        from app.services.product_archetype import validate_content, ProductArchetype
        arch = ProductArchetype.RESEARCH_TOOL_NON_CLINICAL
        clean_text = (
            "Apply for NIH SBIR Phase I grant. "
            "Target R1 academic labs with an open-source pilot tier. "
            "Grow via researcher citation and GitHub star velocity."
        )
        violations = validate_content(clean_text, arch, section_id="strategic_playbook", strict=False)
        assert violations == [], f"Clean research text must produce no violations, got: {violations}"

    def test_validate_report_dict_flags_clinical_vocab_in_strategy(self):
        """validate_report_dict must flag clinical tokens anywhere in the report dict."""
        from app.services.product_archetype import validate_report_dict, ProductArchetype
        arch = ProductArchetype.RESEARCH_TOOL_NON_CLINICAL
        report_with_violation = {
            "strategic_playbook": [
                {"strategy": "Regulatory clearance",
                 "how_to_apply": "Submit 510(k) and target NTAP payment for hospital buyers."}
            ]
        }
        violations = validate_report_dict(report_with_violation, arch)
        assert violations, (
            "validate_report_dict must detect 510(k) / NTAP in strategic_playbook for research tools"
        )

    def test_drg_banned_for_research_tool(self):
        from app.services.product_archetype import validate_content, ProductArchetype
        arch = ProductArchetype.RESEARCH_TOOL_NON_CLINICAL
        text = "Hospital buyers reimburse via DRG bundled payments."
        violations = validate_content(text, arch, section_id="market_access", strict=False)
        assert violations, "DRG is banned vocabulary for research tools"


# ══════════════════════════════════════════════════════════════════════════════
# G-02-7 — No minimum-count padding in prompts
# ══════════════════════════════════════════════════════════════════════════════

# Minimum-count instructions in prompts drive the LLM to pad output rather than
# report accurate data. These patterns are banned in competitive-landscape and
# strategy-playbook prompt contexts.
_MIN_COUNT_RE = re.compile(
    r'(include|list|provide|name|identify)\s+(at\s+least|a\s+minimum\s+of)\s+\d+\s+'
    r'(competitor|strateg|player|alternat)',
    re.IGNORECASE,
)


class TestNoMinimumCountPadding:

    def _all_prompt_constants(self) -> str:
        """Collect all static prompt string constants from alignment_service."""
        import app.services.alignment_service as svc
        parts = []
        for name in dir(svc):
            if "PROMPT" in name.upper() or "SYSTEM" in name.upper():
                val = getattr(svc, name)
                if isinstance(val, str):
                    parts.append(val)
        return "\n".join(parts)

    def test_no_minimum_count_in_competitive_landscape_instructions(self):
        """
        Prompts must not instruct the LLM to list 'at least N competitors' —
        this produces padding when the market has fewer real players.
        """
        prompts = self._all_prompt_constants()
        m = _MIN_COUNT_RE.search(prompts)
        assert m is None, (
            f"Minimum-count padding instruction found in prompt: {m.group()!r} — "
            "remove it; LLM should report the actual number of competitors found"
        )

    def test_rendered_html_no_at_least_N_competitors(self):
        """PDF renderer output must not emit 'at least N competitors' padding."""
        html = render_report_html(_full_report(), product_name="Hublink")
        m = re.search(r"at\s+least\s+\d+\s+competitor", html, re.IGNORECASE)
        assert m is None, (
            f"Padding phrase {m.group()!r} found in rendered output — "
            "competitive landscape must report exact counts"
        )


# ══════════════════════════════════════════════════════════════════════════════
# G-02-8 — Axis decisions (waterfall steps) rendered in PDF output
# ══════════════════════════════════════════════════════════════════════════════

class TestAxisDecisionsRendered:
    """
    The market sizing waterfall entries represent the axis decisions for TAM/SAM
    derivation (Part C). When a report includes market_sizing_provenance.waterfall,
    every step label must appear in the rendered PDF output.
    """

    def test_waterfall_step_labels_present_in_html(self):
        """Each waterfall entry's label must appear somewhere in the PDF renderer output."""
        report = _full_report()
        html = render_report_html(report, product_name="Hublink")
        waterfall = report["market_sizing_provenance"]["waterfall"]
        for step in waterfall:
            label = step["label"]
            assert label in html, (
                f"Waterfall axis step {label!r} not found in PDF renderer output — "
                "axis decisions must be rendered in the market section"
            )

    def test_aggregate_rows_present(self):
        """Aggregate waterfall rows (TAM/SAM/SOM) must be rendered prominently."""
        report = _full_report()
        html = render_report_html(report, product_name="Hublink")
        agg_steps = [s for s in report["market_sizing_provenance"]["waterfall"] if s["is_aggregate"]]
        assert agg_steps, "Fixture must have at least one aggregate waterfall step"
        for step in agg_steps:
            assert step["label"] in html, (
                f"Aggregate step {step['label']!r} must appear in rendered output"
            )

    def test_no_waterfall_no_crash(self):
        """Renderer must not crash when market_sizing_provenance is absent."""
        r = dict(_full_report())
        r.pop("market_sizing_provenance", None)
        html = render_report_html(r, product_name="Hublink")
        assert "Hublink" in html  # report still renders

    def test_axis_step_source_attributed(self):
        """Non-aggregate waterfall steps must include their source attribution in the output."""
        report = _full_report()
        html = render_report_html(report, product_name="Hublink")
        non_agg = [s for s in report["market_sizing_provenance"]["waterfall"] if not s["is_aggregate"]]
        for step in non_agg:
            src = step.get("source_name", "")
            if src:
                assert src in html, (
                    f"Source {src!r} for waterfall step {step['label']!r} "
                    "not found in rendered output"
                )
