"""
F-14 — Monte Carlo sensitivity analysis for the research-tool buyer model.

Spec: "actually sample the [pop_lo, pop_hi] × [sp_lo, sp_hi] space, rank which
assumptions move the TAM most, surface that as a proper sensitivity block instead
of the deleted ±35% IQVIA footer."

Also closes the SAM/SOM constant problem: 30% and 15% become explicit ranges
[15%–45%] and [8%–25%] so the model no longer has two silent constants.

All tests are pure-Python (no API key, no DB).
"""

from __future__ import annotations

import pytest

from app.services.market_sizing_derivation_service import (
    MonteCarloResult,
    SensitivityEntry,
    _SAM_HI,
    _SAM_LO,
    _SAM_MID,
    _SOM_HI,
    _SOM_LO,
    _SOM_MID,
    _run_research_tool_sensitivity,
    generate_market_sizing_derivation,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

_HUB_IDEA = (
    "Hublink: cloud-based wireless data sync for neuroscience PI labs. "
    "Passive sync from running wheels, force plates, and EEG amplifiers. No clinical use."
)
_SOIL_IDEA = (
    "Wireless soil moisture and nutrient sensor array for agronomy research. "
    "Target: university crop-science labs. No clinical or medical application."
)


def _derive(idea, ta, sub_expert):
    return generate_market_sizing_derivation(
        idea=idea, therapeutic_area=ta, sub_expert_id=sub_expert,
    )


# ── 1. _run_research_tool_sensitivity (unit tests, no full pipeline) ──────────

class TestRunResearchToolSensitivity:

    def setup_method(self):
        # Neuroscience domain params (from _RESEARCH_TOOL_DOMAIN_PARAMS)
        self.mc = _run_research_tool_sensitivity(
            pop_lo=3_000, pop_hi=8_000,
            sp_lo=20_000, sp_hi=30_000,
        )

    def test_returns_monte_carlo_result(self):
        assert isinstance(self.mc, MonteCarloResult)

    def test_sample_count(self):
        assert self.mc.n_samples == 10_000

    def test_tam_percentiles_ordered(self):
        mc = self.mc
        assert mc.tam_p5 < mc.tam_p25 < mc.tam_p50 < mc.tam_p75 < mc.tam_p95

    def test_sam_percentiles_ordered(self):
        mc = self.mc
        assert mc.sam_p25 < mc.sam_p50 < mc.sam_p75

    def test_som_percentiles_ordered(self):
        mc = self.mc
        assert mc.som_p25 < mc.som_p50 < mc.som_p75

    def test_tam_p50_near_midpoint(self):
        """P50 from uniform sampling ≈ midpoint of parameter space (within 10%)."""
        pop_mid = (3_000 + 8_000) / 2
        sp_mid  = (20_000 + 30_000) / 2
        expected_mid = pop_mid * sp_mid
        assert abs(self.mc.tam_p50 - expected_mid) / expected_mid < 0.10

    def test_tam_p95_greater_than_p50_times_1_4(self):
        """Wide uncertainty: P95 must be at least 1.4× P50."""
        assert self.mc.tam_p95 > self.mc.tam_p50 * 1.4

    def test_tam_p5_less_than_p50_times_0_7(self):
        """Wide uncertainty: P5 must be at most 0.70× P50."""
        assert self.mc.tam_p5 < self.mc.tam_p50 * 0.70

    def test_sensitivity_ranking_has_four_entries(self):
        assert len(self.mc.sensitivity_ranking) == 4

    def test_all_sensitivity_entries_positive_swing(self):
        for e in self.mc.sensitivity_ranking:
            assert e.swing_pct > 0, f"{e.parameter}: swing_pct={e.swing_pct}"

    def test_sensitivity_ranking_sorted_descending(self):
        swings = [e.swing_pct for e in self.mc.sensitivity_ranking]
        assert swings == sorted(swings, reverse=True)

    def test_som_rate_and_sam_rate_in_ranking(self):
        """The two assumed constants must appear in the ranking."""
        params = {e.parameter for e in self.mc.sensitivity_ranking}
        assert any("SOM" in p for p in params), "SOM penetration not in sensitivity ranking"
        assert any("SAM" in p for p in params), "SAM adoption not in sensitivity ranking"

    def test_spend_entry_has_lower_swing_than_rates(self):
        """For neuroscience (sp_hi/sp_lo = 1.5×), spend has less swing than SAM/SOM rates."""
        spend_entry = next(e for e in self.mc.sensitivity_ranking if "spend" in e.parameter.lower())
        som_entry   = next(e for e in self.mc.sensitivity_ranking if "SOM" in e.parameter)
        assert spend_entry.swing_pct < som_entry.swing_pct

    def test_deterministic_with_same_seed(self):
        """Two calls with the same seed must return identical P50."""
        mc1 = _run_research_tool_sensitivity(3_000, 8_000, 20_000, 30_000, seed=42)
        mc2 = _run_research_tool_sensitivity(3_000, 8_000, 20_000, 30_000, seed=42)
        assert mc1.tam_p50 == mc2.tam_p50

    def test_different_seed_different_result(self):
        mc1 = _run_research_tool_sensitivity(3_000, 8_000, 20_000, 30_000, seed=42)
        mc2 = _run_research_tool_sensitivity(3_000, 8_000, 20_000, 30_000, seed=99)
        # P50s may be very close but not identical
        assert mc1.tam_p50 != mc2.tam_p50

    def test_wider_population_range_gives_wider_spread(self):
        """A 5× population range must produce wider TAM spread than a 1.5× range."""
        narrow = _run_research_tool_sensitivity(4_000, 6_000, 20_000, 30_000, seed=42)
        wide   = _run_research_tool_sensitivity(1_000, 15_000, 20_000, 30_000, seed=42)
        narrow_spread = narrow.tam_p95 - narrow.tam_p5
        wide_spread   = wide.tam_p95   - wide.tam_p5
        assert wide_spread > narrow_spread


# ── 2. SAM/SOM rate constants are now ranges ──────────────────────────────────

class TestSAMSOMRanges:

    def test_sam_lo_lt_sam_mid_lt_sam_hi(self):
        assert _SAM_LO < _SAM_MID < _SAM_HI

    def test_som_lo_lt_som_mid_lt_som_hi(self):
        assert _SOM_LO < _SOM_MID < _SOM_HI

    def test_sam_mid_is_thirty_percent(self):
        assert _SAM_MID == pytest.approx(0.30)

    def test_som_mid_is_fifteen_percent(self):
        assert _SOM_MID == pytest.approx(0.15)

    def test_sam_range_wide_enough(self):
        """Range must span at least 2× to reflect genuine ignorance."""
        assert _SAM_HI / _SAM_LO >= 2.0

    def test_som_range_wide_enough(self):
        assert _SOM_HI / _SOM_LO >= 2.5


# ── 3. Full-pipeline integration ──────────────────────────────────────────────

class TestFullPipelineMonteCarlo:

    def test_hub_derivation_has_monte_carlo(self):
        d = _derive(_HUB_IDEA, "neuroscience", "research_tool_non_clinical")
        assert d.monte_carlo is not None

    def test_soil_derivation_has_monte_carlo(self):
        d = _derive(_SOIL_IDEA, "agronomy", "research_infrastructure_saas")
        assert d.monte_carlo is not None

    def test_hub_monte_carlo_p50_near_tam_midpoint(self):
        d = _derive(_HUB_IDEA, "neuroscience", "research_tool_non_clinical")
        assert abs(d.monte_carlo.tam_p50 - d.us_tam_usd) / d.us_tam_usd < 0.10

    def test_soil_monte_carlo_p50_near_tam_midpoint(self):
        d = _derive(_SOIL_IDEA, "agronomy", "research_infrastructure_saas")
        assert abs(d.monte_carlo.tam_p50 - d.us_tam_usd) / d.us_tam_usd < 0.10

    def test_hub_and_soil_mc_p50_differ(self):
        """Monte Carlo reflects domain-specific parameters — P50 must differ."""
        hub  = _derive(_HUB_IDEA,  "neuroscience", "research_tool_non_clinical")
        soil = _derive(_SOIL_IDEA, "agronomy",      "research_infrastructure_saas")
        assert hub.monte_carlo.tam_p50 != soil.monte_carlo.tam_p50

    def test_hub_mc_p50_greater_than_soil_mc_p50(self):
        """Neuroscience has a larger lab pool at higher spend — hub > soil."""
        hub  = _derive(_HUB_IDEA,  "neuroscience", "research_tool_non_clinical")
        soil = _derive(_SOIL_IDEA, "agronomy",      "research_infrastructure_saas")
        assert hub.monte_carlo.tam_p50 > soil.monte_carlo.tam_p50

    def test_hub_sensitivity_ranking_exposes_som_rate(self):
        d = _derive(_HUB_IDEA, "neuroscience", "research_tool_non_clinical")
        top_param = d.monte_carlo.sensitivity_ranking[0].parameter
        assert "SOM" in top_param or "SAM" in top_param, (
            f"Top sensitivity driver should be SOM/SAM rate, got: {top_param}"
        )

    def test_step4_title_shows_range(self):
        """Step 4 must expose the SAM range, not just a bare '30%' constant."""
        d = _derive(_HUB_IDEA, "neuroscience", "research_tool_non_clinical")
        step4 = next(s for s in d.steps if s.step_num == 4)
        assert "%" in step4.formula, "Step 4 formula must show the SAM rate range"
        assert "–" in step4.formula, "Step 4 formula must show lo–hi range"

    def test_step5_title_shows_range(self):
        d = _derive(_HUB_IDEA, "neuroscience", "research_tool_non_clinical")
        step5 = next(s for s in d.steps if s.step_num == 5)
        assert "–" in step5.formula, "Step 5 formula must show SOM rate range"

    def test_confidence_note_references_monte_carlo(self):
        d = _derive(_HUB_IDEA, "neuroscience", "research_tool_non_clinical")
        assert "Monte Carlo" in d.confidence_note or "P5" in d.confidence_note

    def test_pharma_derivation_monte_carlo_is_none(self):
        """Monte Carlo is only implemented for research tools for now."""
        d = generate_market_sizing_derivation(
            idea="Novel beta-lactam antibiotic for carbapenem-resistant Enterobacterales, IV formulation.",
            therapeutic_area="infectious_disease",
            sub_expert_id="drug_amr",
        )
        assert d.monte_carlo is None

    def test_key_assumptions_include_sam_range(self):
        d = _derive(_HUB_IDEA, "neuroscience", "research_tool_non_clinical")
        sam_assumption = next(
            (a for a in d.key_assumptions if "SAM" in a or "adoption" in a.lower()), None
        )
        assert sam_assumption is not None, "key_assumptions must include SAM range"
        assert "%" in sam_assumption

    def test_key_assumptions_include_som_range(self):
        d = _derive(_HUB_IDEA, "neuroscience", "research_tool_non_clinical")
        som_assumption = next(
            (a for a in d.key_assumptions if "SOM" in a or "penetration" in a.lower()), None
        )
        assert som_assumption is not None, "key_assumptions must include SOM range"
        assert "%" in som_assumption
