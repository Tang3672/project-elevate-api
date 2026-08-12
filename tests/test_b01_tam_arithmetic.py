"""
B-01 — TAM arithmetic invariants
=================================
The research-tool TAM must be the midpoint (pop_mid × sp_mid ≈ $45.8M),
never the pessimistic endpoint (pop_lo × sp_lo = $20M). Scenarios must
share the same TAM ceiling; only SAM/SOM vary. The formula box must say
"Year-1 capture" (authoritative horizon label). No duplicate sensitivity ranges.

All tests are pure-Python (no API key, no DB).
"""

from __future__ import annotations

import re
import pytest
from types import SimpleNamespace


# ── helpers ───────────────────────────────────────────────────────────────────

def _research_tool_derivation():
    from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
    return generate_market_sizing_derivation(
        idea="Hublink: a non-clinical wearable data platform for academic PIs.",
        disease_name="neuroscience",
        therapeutic_area="neuroscience",
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
        The TAM step titled '... midpoint estimate' must carry the midpoint TAM value
        — not the pessimistic or optimistic endpoint.  F-14 added 'midpoint' to Step 4
        and Step 5 titles too (SAM/SOM midpoints), so we filter specifically for the
        TAM midpoint step via 'midpoint estimate'.
        """
        deriv = _research_tool_derivation()
        mid_steps = [s for s in deriv.steps if "midpoint estimate" in (s.title or "").lower()]
        assert mid_steps, "No derivation step with 'midpoint estimate' in its title found."
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
    G.10 / B-08: the formula string stamped by _enforce_market_consistency must use
    the HORIZON_YEARS canonical form (e.g. "5-yr penetration midpoint"), not "Year-1
    capture". The SOM_HORIZON_MISMATCH regex normalises any LLM prose that contradicts
    it ("Year-1 capture", "year-1 SOM") in executive_summary / recommended_next_steps.

    Step titles from the derivation service already use HORIZON_YEARS via the constant.
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
        assert "5 year" in exp_lower or "5-year" in exp_lower or "5 yr" in exp_lower or "5-yr" in exp_lower, (
            f"SOM explanation must mention 5-year horizon."
        )

    def test_stamp_formula_says_canonical_horizon_not_year1(self):
        """
        G.10: _enforce_market_consistency must write the HORIZON_YEARS canonical
        phrasing in the formula string (e.g. '5-yr penetration midpoint'), NOT
        'Year-1 capture'. Year-1 was the old wrong canonical form.
        """
        from app.services.alignment_service import _enforce_market_consistency
        from app.services.buyer_model import HORIZON_YEARS

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
        assert f"{HORIZON_YEARS}-yr" in formula.lower() or f"{HORIZON_YEARS} yr" in formula.lower(), (
            f"Formula box must use canonical {HORIZON_YEARS}-yr horizon (G.10). Got: {formula!r}"
        )
        assert "year-1 capture" not in formula.lower() and "year 1 capture" not in formula.lower(), (
            f"Formula box must not say 'Year-1 capture' (G.10 reversed this). Got: {formula!r}"
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
        """
        confidence_note must not contain a sprawling set of contradictory USD ranges.
        F-14 legitimately adds Monte Carlo P5-P95 (TAM) and P25-P75 (SOM) ranges,
        so up to 4 USD ranges are now acceptable (parameter range + 2 MC ranges + headroom).
        The original defect — a duplicated 'sensitivity range' phrase with different numbers
        — is covered by test_confidence_note_no_extended_sensitivity_range.
        """
        deriv = _research_tool_derivation()
        cn = deriv.confidence_note or ""
        import re
        usd_ranges = re.findall(r'\$\d+[MBK]?–\$\d+[MBK]?', cn)
        assert len(usd_ranges) <= 4, (
            f"confidence_note has {len(usd_ranges)} USD ranges {usd_ranges!r}; "
            "at most 4 are allowed (parameter range + Monte Carlo TAM P5-P95 + SOM P25-P75)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Step-level enforcement — TAM/SAM/SOM steps must match headline after fix
# ══════════════════════════════════════════════════════════════════════════════

def _make_ms(tam=20_000_000, sam=6_000_000, som=900_000):
    steps = [
        SimpleNamespace(label="Step 1 — Eligible buyer population",                              value=3_000.0, unit="labs"),
        SimpleNamespace(label="Step 2 — Annualised spend per lab",                               value=6_667.0, unit="USD/lab/yr"),
        SimpleNamespace(label="Step 3 — Total Addressable Market (TAM — midpoint estimate)",     value=float(tam), unit="USD"),
        SimpleNamespace(label="Step 4 — Serviceable Addressable Market (SAM = 30% of TAM)",     value=float(sam), unit="USD"),
        SimpleNamespace(label="Step 5 — Serviceable Obtainable Market (SOM = 15% of SAM, 5-yr)", value=float(som), unit="USD"),
    ]
    ms = SimpleNamespace(
        steps=steps,
        total_addressable_market_usd=float(tam),
        serviceable_market_usd=float(sam),
        formula="placeholder",
        methodology_note="",
    )
    return SimpleNamespace(market_sizing=ms), ms


def _make_deriv_ns(tam=45_833_333, sam=13_750_000, som=2_062_500):
    return SimpleNamespace(
        us_tam_usd=float(tam),
        us_sam_usd=float(sam),
        us_som_usd=float(som),
        archetype="research_tool_non_clinical",
    )


class TestEnforceStepLevelPropagation:
    """_enforce_market_consistency must update individual step values, not just headline."""

    def _run(self):
        from app.services.alignment_service import _enforce_market_consistency
        report, ms = _make_ms(tam=20_000_000)     # pessimistic (the B-01 bug value)
        _enforce_market_consistency(report, _make_deriv_ns())
        return ms

    def test_tam_step_updated_from_pessimistic_to_midpoint(self):
        ms = self._run()
        tam_step = next(s for s in ms.steps if "total addressable" in s.label.lower())
        assert tam_step.value == pytest.approx(ms.total_addressable_market_usd, rel=0.001), (
            f"After enforcement the TAM step must equal the headline. "
            f"step={tam_step.value:,.0f}, headline={ms.total_addressable_market_usd:,.0f}"
        )

    def test_tam_step_not_20m_after_enforcement(self):
        ms = self._run()
        tam_step = next(s for s in ms.steps if "total addressable" in s.label.lower())
        assert tam_step.value > 30_000_000, (
            "TAM step must no longer show the pessimistic $20M after enforcement"
        )

    def test_sam_step_updated(self):
        ms = self._run()
        sam_step = next((s for s in ms.steps if "serviceable addressable" in s.label.lower()), None)
        if sam_step:
            assert sam_step.value == pytest.approx(ms.serviceable_market_usd, rel=0.001)

    def test_som_step_updated(self):
        ms = self._run()
        som_step = next((s for s in ms.steps if "obtainable" in s.label.lower()), None)
        if som_step:
            cap = round(2_062_500 / 13_750_000 * 100, 1)
            expected = round(ms.serviceable_market_usd * cap / 100)
            assert som_step.value == pytest.approx(expected, rel=0.001)

    def test_formula_reflects_midpoint_tam(self):
        ms = self._run()
        assert "45,833,333" in ms.formula or "45.8M" in ms.formula or "45.8" in ms.formula


class TestMidpointLabelMatchesMidpointValue:
    """A step labelled 'midpoint' must carry the midpoint value — not the pessimistic one."""

    def test_midpoint_step_matches_headline_after_enforcement(self):
        from app.services.alignment_service import _enforce_market_consistency
        report, ms = _make_ms(tam=20_000_000)    # pessimistic start
        _enforce_market_consistency(report, _make_deriv_ns(tam=45_833_333))
        for step in ms.steps:
            if "midpoint" in step.label.lower():
                assert step.value == pytest.approx(ms.total_addressable_market_usd, rel=0.001), (
                    f"Step labelled 'midpoint' shows {step.value:,.0f}, "
                    f"headline is {ms.total_addressable_market_usd:,.0f} — must match"
                )

    def test_b01_specific_bug_fixed(self):
        """The exact B-01 bug: step says 'midpoint', value was 20M (pessimistic)."""
        from app.services.alignment_service import _enforce_market_consistency
        from app.services.buyer_model import academic_neurotech_lab_buyer
        bm = academic_neurotech_lab_buyer()
        pessimistic = bm.buyer_population_lo * bm.annualised_spend_lo()  # ~$20M

        report, ms = _make_ms(tam=pessimistic)
        _enforce_market_consistency(report, _make_deriv_ns())
        for step in ms.steps:
            if "midpoint" in step.label.lower() and "addressable" in step.label.lower():
                assert step.value != pytest.approx(pessimistic, rel=0.01), (
                    "B-01 bug not fixed: 'midpoint' TAM step still shows $20M (pessimistic)"
                )


class TestStepLabelDedup:
    """B-10: 'Step 1 - Step 1 - …' duplicate prefix must be stripped by enforcement."""

    def _dedup(self, label: str) -> str:
        from app.services.alignment_service import _enforce_market_consistency
        step = SimpleNamespace(label=label, value=0.0, unit="")
        ms = SimpleNamespace(
            steps=[step],
            total_addressable_market_usd=45_000_000.0,
            serviceable_market_usd=13_500_000.0,
            formula="", methodology_note="",
        )
        _enforce_market_consistency(SimpleNamespace(market_sizing=ms), _make_deriv_ns())
        return step.label

    def test_hyphen_duplicate_removed(self):
        result = self._dedup("Step 1 - Step 1 - Eligible buyer population")
        assert result.count("Step 1") <= 1, f"Duplicate not removed: {result!r}"

    def test_em_dash_duplicate_removed(self):
        result = self._dedup("Step 3 — Step 3 — Total Addressable Market")
        assert result.count("Step 3") <= 1

    def test_en_dash_duplicate_removed(self):
        result = self._dedup("Step 2 – Step 2 – Annualised spend per lab")
        assert result.count("Step 2") <= 1

    def test_clean_label_not_mangled(self):
        result = self._dedup("Step 1 — Eligible buyer population")
        assert "Eligible buyer population" in result

    def test_non_step_label_unchanged(self):
        result = self._dedup("Eligible buyer population")
        assert result == "Eligible buyer population"
