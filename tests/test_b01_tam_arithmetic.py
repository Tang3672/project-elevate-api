"""
B-01 — TAM arithmetic invariants
=================================
The research-tool TAM must be the midpoint (pop_mid × sp_mid ≈ $45.8M),
never the pessimistic endpoint (pop_lo × sp_lo = $20M). Scenarios must
share the same TAM ceiling; only SAM/SOM vary. SOM label must say
"5-yr horizon", not "Year-1". No duplicate sensitivity ranges.

All tests are pure-Python (no API key, no DB).
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace


# ── helpers ───────────────────────────────────────────────────────────────────

def _research_tool_derivation():
    from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
    return generate_market_sizing_derivation(
        idea="Hublink: a non-clinical wearable data platform for academic PIs.",
        disease_name="neuroscience",
        sub_expert_id="research_tool_non_clinical",
    )


def _research_tool_provenance():
    from app.services.market_provenance_service import build_provenance
    return build_provenance(_research_tool_derivation())


# ══════════════════════════════════════════════════════════════════════════════
# TAM arithmetic
# ══════════════════════════════════════════════════════════════════════════════

class TestResearchToolTamArithmetic:

    def test_tam_is_midpoint_not_pessimistic(self):
        """
        TAM must be pop_mid × sp_mid ≈ $45.8M.
        The pessimistic case (pop_lo × sp_lo = 3,000 × $6,667 = $20M) must NOT
        be the headline — it is the conservative floor of the range.
        """
        deriv = _research_tool_derivation()
        assert deriv.us_tam_usd > 40_000_000, (
            f"TAM {deriv.us_tam_usd:,.0f} is at or below the pessimistic floor ($20M). "
            "Must use the midpoint (~$45.8M), not the conservative endpoint."
        )

    def test_tam_is_not_optimistic(self):
        """TAM must not use the optimistic ceiling (pop_hi × sp_hi = 8,000 × $10,000 = $80M)."""
        deriv = _research_tool_derivation()
        assert deriv.us_tam_usd < 75_000_000, (
            f"TAM {deriv.us_tam_usd:,.0f} is at or above the optimistic ceiling ($80M). "
            "Must use the midpoint (~$45.8M)."
        )

    def test_midpoint_step_title_value_is_midpoint(self):
        """
        The derivation step whose title contains 'midpoint' must carry the midpoint
        value — not the pessimistic or optimistic endpoint.
        """
        deriv = _research_tool_derivation()
        mid_steps = [s for s in deriv.steps if "midpoint" in (s.title or "").lower()]
        assert mid_steps, "No derivation step with 'midpoint' in its title found."
        for step in mid_steps:
            assert step.value > 40_000_000, (
                f"Step '{step.title}' says midpoint but value is {step.value:,.0f} — "
                "must be ~$45.8M."
            )
            # Must also match the derivation's headline TAM
            assert abs(step.value - deriv.us_tam_usd) / deriv.us_tam_usd < 0.001, (
                f"Step '{step.title}' value {step.value:,.0f} ≠ "
                f"deriv.us_tam_usd {deriv.us_tam_usd:,.0f}"
            )

    def test_sam_is_fraction_of_tam(self):
        """SAM must be strictly less than TAM."""
        deriv = _research_tool_derivation()
        assert deriv.us_sam_usd < deriv.us_tam_usd, (
            f"SAM {deriv.us_sam_usd:,.0f} must be less than TAM {deriv.us_tam_usd:,.0f}"
        )

    def test_som_is_fraction_of_sam(self):
        """SOM must be strictly less than SAM."""
        deriv = _research_tool_derivation()
        assert deriv.us_som_usd < deriv.us_sam_usd, (
            f"SOM {deriv.us_som_usd:,.0f} must be less than SAM {deriv.us_sam_usd:,.0f}"
        )

    def test_tam_fmt_unit_is_M(self):
        """TAM at ~$45.8M must format as 'M', not 'B' or 'K'."""
        deriv = _research_tool_derivation()
        assert "M" in deriv.tam_fmt, f"TAM {deriv.us_tam_usd:,.0f} formatted as {deriv.tam_fmt!r}"
        assert "B" not in deriv.tam_fmt, f"TAM must not be formatted as billions: {deriv.tam_fmt!r}"


# ══════════════════════════════════════════════════════════════════════════════
# Scenarios: TAM ceiling is constant
# ══════════════════════════════════════════════════════════════════════════════

class TestScenarioTamCeiling:
    """
    TAM (addressable ceiling) must not vary across scenarios — only SAM and SOM
    vary based on adoption assumptions. B-10 showed aggressive SOM/SAM capture rate
    falling below base, caused by a stale pessimistic TAM being used as input.
    """

    def test_all_scenarios_share_base_tam(self):
        prov = _research_tool_provenance()
        base_tam = prov["run"]["tam_usd"]
        for s in prov["scenarios"]:
            # build_scenarios stores round(tam) so compare within 1 USD of each other
            assert abs(s["tam_usd"] - base_tam) <= 1, (
                f"Scenario '{s['scenario']}': TAM {s['tam_usd']:,.0f} ≠ "
                f"base TAM {base_tam:,.0f} — TAM must not vary across scenarios"
            )

    def test_scenario_sam_monotonically_increases(self):
        """Conservative SAM < Base SAM < Aggressive SAM."""
        prov = _research_tool_provenance()
        scns = {s["scenario"]: s for s in prov["scenarios"]}
        assert scns["conservative"]["sam_usd"] < scns["base"]["sam_usd"] < scns["aggressive"]["sam_usd"], (
            f"SAMs must be ordered: {scns['conservative']['sam_usd']:,.0f} < "
            f"{scns['base']['sam_usd']:,.0f} < {scns['aggressive']['sam_usd']:,.0f}"
        )

    def test_scenario_som_monotonically_increases(self):
        """Conservative SOM < Base SOM < Aggressive SOM."""
        prov = _research_tool_provenance()
        scns = {s["scenario"]: s for s in prov["scenarios"]}
        assert scns["conservative"]["som_usd"] < scns["base"]["som_usd"] < scns["aggressive"]["som_usd"], (
            f"SOMs must be ordered: {scns['conservative']['som_usd']:,.0f} < "
            f"{scns['base']['som_usd']:,.0f} < {scns['aggressive']['som_usd']:,.0f}"
        )

    def test_scenario_capture_rates_monotonically_increase(self):
        """
        SOM/SAM capture rate must increase from conservative → base → aggressive.
        B-10: aggressive capture rate was *lower* than base due to stale pessimistic TAM.
        """
        prov = _research_tool_provenance()
        scns = {s["scenario"]: s for s in prov["scenarios"]}
        cap_consv = scns["conservative"]["som_usd"] / scns["conservative"]["sam_usd"]
        cap_base  = scns["base"]["som_usd"]         / scns["base"]["sam_usd"]
        cap_aggr  = scns["aggressive"]["som_usd"]   / scns["aggressive"]["sam_usd"]
        assert cap_consv < cap_base < cap_aggr, (
            f"SOM/SAM rates must increase: "
            f"conservative={cap_consv:.1%}, base={cap_base:.1%}, aggressive={cap_aggr:.1%}"
        )

    def test_sam_never_exceeds_tam_in_any_scenario(self):
        prov = _research_tool_provenance()
        tam = prov["run"]["tam_usd"]
        for s in prov["scenarios"]:
            assert s["sam_usd"] <= tam, (
                f"Scenario '{s['scenario']}': SAM {s['sam_usd']:,.0f} > TAM {tam:,.0f}"
            )

    def test_som_never_exceeds_sam_in_any_scenario(self):
        prov = _research_tool_provenance()
        for s in prov["scenarios"]:
            assert s["som_usd"] <= s["sam_usd"], (
                f"Scenario '{s['scenario']}': SOM {s['som_usd']:,.0f} > SAM {s['sam_usd']:,.0f}"
            )

    def test_research_tool_scenarios_use_research_vocabulary(self):
        """Scenario narratives must not use clinical vocabulary (payer, guideline, label)."""
        prov = _research_tool_provenance()
        clinical_terms = {"guideline", "payer", "label", "formulary", "reimbursement",
                          "clinical", "indication", "fda", "approval"}
        for s in prov["scenarios"]:
            narrative = (s.get("narrative") or "").lower()
            hits = clinical_terms & set(narrative.split())
            assert not hits, (
                f"Scenario '{s['scenario']}' narrative uses clinical vocabulary {hits!r} "
                "— must use research-tool vocabulary (adoption, citation, lab, etc.)"
            )


# ══════════════════════════════════════════════════════════════════════════════
# SOM label consistency
# ══════════════════════════════════════════════════════════════════════════════

class TestSomLabelConsistency:
    """
    SOM horizon must be described consistently as "5-yr horizon" across all
    places it appears: derivation Step 5 title, key_assumptions, and the
    formula string stamped by _stamp_market_consistency.
    B-10: "Year-1 capture" (formula box) vs "5 yrs" (Step 5) — fourth run.
    """

    def test_som_step_title_says_5yr(self):
        deriv = _research_tool_derivation()
        som_step = next((s for s in deriv.steps if "SOM" in (s.title or "")), None)
        assert som_step, "No SOM step found in research tool derivation."
        title_lower = som_step.title.lower()
        assert "5-yr" in title_lower or "5 yr" in title_lower or "5 year" in title_lower, (
            f"SOM step title {som_step.title!r} must reference a 5-year horizon."
        )
        assert "year-1" not in title_lower and "year 1" not in title_lower, (
            f"SOM step title {som_step.title!r} must not say 'Year-1' — this is a 5-yr horizon."
        )

    def test_som_step_explanation_says_5yr(self):
        deriv = _research_tool_derivation()
        som_step = next((s for s in deriv.steps if "SOM" in (s.title or "")), None)
        assert som_step, "No SOM step found."
        exp_lower = (som_step.explanation or "").lower()
        assert "5 year" in exp_lower or "5-year" in exp_lower or "5 yr" in exp_lower, (
            f"SOM explanation must mention 5-year horizon."
        )

    def test_stamp_formula_says_5yr_not_year1(self):
        """
        _enforce_market_consistency must write '5-yr horizon capture' in the formula string,
        not 'Year-1 capture'.
        """
        from app.services.alignment_service import _enforce_market_consistency

        class _MS:
            total_addressable_market_usd = 0.0
            serviceable_market_usd = 0.0
            formula = ""

        class _Report:
            market_sizing = _MS()

        deriv = _research_tool_derivation()
        report = _Report()
        _enforce_market_consistency(report, deriv)
        formula = report.market_sizing.formula
        assert "year-1" not in formula.lower(), (
            f"Formula box must not say 'Year-1 capture'. Got: {formula!r}"
        )
        assert "5-yr" in formula.lower() or "5 yr" in formula.lower() or "5 year" in formula.lower(), (
            f"Formula box must reference 5-yr horizon. Got: {formula!r}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# No duplicate sensitivity range
# ══════════════════════════════════════════════════════════════════════════════

class TestNoDuplicateSensitivityRange:
    """
    B-01 / B-10: Two different sensitivity ranges appeared in one section.
    - formula_overview: $20M–$80M (exact parameter extremes)
    - confidence_note: $10M–$120M (±50% of extremes)
    These are contradictory and confuse the reader. Only one range must appear.
    """

    def test_confidence_note_no_extended_sensitivity_range(self):
        """confidence_note must not contain a separate 'sensitivity range' sentence
        that differs from the formula_overview's parameter range."""
        deriv = _research_tool_derivation()
        cn = (deriv.confidence_note or "").lower()
        # "sensitivity range" was the offending phrase from the spec
        assert "sensitivity range" not in cn, (
            f"confidence_note must not add a second sensitivity range. "
            f"formula_overview already provides the parameter range. "
            f"Got: {deriv.confidence_note!r}"
        )

    def test_formula_overview_contains_range(self):
        """The parameter range ($low–$high) belongs in formula_overview, not confidence_note."""
        deriv = _research_tool_derivation()
        overview = deriv.formula_overview or ""
        # Should show e.g. "$20M–$80M" or some range with a dash
        assert "–" in overview or "-" in overview, (
            f"formula_overview must show the TAM parameter range. Got: {overview!r}"
        )

    def test_confidence_note_no_contradictory_usd_range(self):
        """confidence_note must not contain its own USD range that contradicts formula_overview."""
        deriv = _research_tool_derivation()
        cn = deriv.confidence_note or ""
        # Count USD-formatted ranges (e.g. "$10M–$120M")
        import re
        usd_ranges = re.findall(r'\$\d+[MBK]?–\$\d+[MBK]?', cn)
        assert len(usd_ranges) <= 1, (
            f"confidence_note has {len(usd_ranges)} USD ranges {usd_ranges!r}; "
            "at most one is allowed (the parameter range, if present)"
        )
