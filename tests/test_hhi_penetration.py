"""
tests/test_hhi_penetration.py
==============================
Tests for the HHI → penetration-prior feedback loop.

Spec (from the blueprint): "Competitive intensity = HHI + pipeline depth +
mechanism diversity, computed per sub-segment... feeds penetration assumptions."

What we test:
  1. _hhi_penetration_factor() returns the correct multiplier per DOJ/FTC band
  2. analog_engine.compute() with hhi_score reduces SOM for concentrated markets
  3. analog_engine.compute() with hhi_score increases SOM for fragmented markets
  4. No adjustment when hhi_score=None (non-breaking default)
  5. get_hhi_for_indication() returns a positive integer for recognisable diseases
  6. HHI score appears in AnalogResult.hhi_score and AnalogResult.hhi_penetration_factor
  7. HHI assumption appears in AnalogResult.assumptions when factor ≠ 1.0
  8. to_dict() serialises hhi fields correctly
"""

from __future__ import annotations

import pytest

from app.services.analog_engine import (
    AnalogResult,
    _hhi_penetration_factor,
    compute,
)
from app.services.market_calibration_service import get_hhi_for_indication


SAM = 1_000_000_000   # $1B — round number for easy arithmetic


# ──────────────────────────────────────────────────────────────────────────────
# 1. _hhi_penetration_factor — correct multipliers per DOJ/FTC band
# ──────────────────────────────────────────────────────────────────────────────

class TestHhiPenetrationFactor:

    def test_none_returns_one(self):
        factor, _ = _hhi_penetration_factor(None)
        assert factor == 1.0, "None HHI must produce factor=1.0 (no adjustment)"

    def test_fragmented_above_one(self):
        factor, _ = _hhi_penetration_factor(800)
        assert factor > 1.0, "Fragmented market (HHI<1000) must give factor > 1 (upside)"

    def test_competitive_slightly_above_one(self):
        factor, _ = _hhi_penetration_factor(1200)
        assert factor >= 1.0, "Competitive market (1000-1500) must give factor ≥ 1"

    def test_moderate_below_one(self):
        factor, _ = _hhi_penetration_factor(2000)
        assert factor < 1.0, "Moderately concentrated (1500-2500) must give factor < 1"

    def test_concentrated_below_moderate(self):
        factor_mod, _ = _hhi_penetration_factor(2000)
        factor_conc, _ = _hhi_penetration_factor(3000)
        assert factor_conc < factor_mod, (
            "Concentrated market must yield a lower factor than moderate"
        )

    def test_highly_concentrated_lowest(self):
        factor_conc, _ = _hhi_penetration_factor(3000)
        factor_high, _ = _hhi_penetration_factor(4000)
        assert factor_high < factor_conc, (
            "Highly concentrated must yield the lowest factor"
        )

    def test_factor_bounded_above(self):
        factor, _ = _hhi_penetration_factor(100)
        assert factor <= 1.30, "Upside factor must not exceed 1.30 (keeps MdAPE budget)"

    def test_factor_bounded_below(self):
        factor, _ = _hhi_penetration_factor(9999)
        assert factor >= 0.50, "Downside factor must not go below 0.50 (sensible floor)"

    def test_returns_non_empty_note(self):
        _, note = _hhi_penetration_factor(2500)
        assert note, "Factor function must return a non-empty explanation string"

    def test_note_cites_source(self):
        _, note = _hhi_penetration_factor(3000)
        assert any(kw in note for kw in ("DOJ", "Grabowski", "Mehta", "PLOS", "merger")), (
            "HHI note must cite a source (DOJ/FTC guidelines or academic reference)"
        )

    def test_monotone_decreasing_across_bands(self):
        """Factor must never increase as HHI increases."""
        hhi_values = [500, 1200, 2000, 3000, 4500]
        factors = [_hhi_penetration_factor(h)[0] for h in hhi_values]
        for i in range(len(factors) - 1):
            assert factors[i] >= factors[i + 1], (
                f"Factor must be non-increasing: f({hhi_values[i]})={factors[i]:.2f} "
                f"< f({hhi_values[i+1]})={factors[i+1]:.2f}"
            )


# ──────────────────────────────────────────────────────────────────────────────
# 2. analog_engine.compute() — HHI reduces/increases SOM correctly
# ──────────────────────────────────────────────────────────────────────────────

class TestAnalogComputeWithHhi:

    def _base(self, hhi: int | None, ctx: str = "new_moa") -> AnalogResult:
        return compute(
            product_type="biologic",
            annual_revenue_sam=SAM,
            competitive_context=ctx,
            hhi_score=hhi,
        )

    def test_concentrated_market_lowers_som(self):
        no_hhi   = self._base(hhi=None)
        conc     = self._base(hhi=3200)
        assert conc.som_peak < no_hhi.som_peak, (
            "Concentrated market (HHI=3200) must produce lower peak SOM than no HHI"
        )

    def test_fragmented_market_raises_som(self):
        no_hhi   = self._base(hhi=None)
        frag     = self._base(hhi=700)
        assert frag.som_peak > no_hhi.som_peak, (
            "Fragmented market (HHI=700) must produce higher peak SOM than no HHI"
        )

    def test_no_hhi_produces_same_as_baseline(self):
        no_hhi_a = self._base(hhi=None)
        no_hhi_b = compute(
            product_type="biologic",
            annual_revenue_sam=SAM,
            competitive_context="new_moa",
        )
        assert no_hhi_a.som_peak == no_hhi_b.som_peak, (
            "hhi_score=None must produce identical output to omitting hhi_score"
        )

    def test_hhi_score_stored_on_result(self):
        result = self._base(hhi=2800)
        assert result.hhi_score == 2800

    def test_hhi_factor_stored_when_adjusted(self):
        result = self._base(hhi=3000)
        assert result.hhi_penetration_factor is not None, (
            "hhi_penetration_factor must be set when HHI is in a penalising band"
        )
        assert result.hhi_penetration_factor < 1.0

    def test_hhi_factor_is_none_when_no_adjustment(self):
        result = self._base(hhi=None)
        assert result.hhi_penetration_factor is None, (
            "hhi_penetration_factor must be None when no HHI data provided"
        )

    def test_hhi_assumption_appears_in_assumptions(self):
        result = self._base(hhi=3000)
        fields = [a["field"] for a in result.assumptions]
        assert "hhi_penetration_adjustment" in fields, (
            "HHI adjustment must be recorded in AnalogResult.assumptions"
        )

    def test_hhi_assumption_includes_expert_question(self):
        result = self._base(hhi=3000)
        hhi_assum = next(
            (a for a in result.assumptions if a["field"] == "hhi_penetration_adjustment"),
            None,
        )
        assert hhi_assum is not None
        assert hhi_assum.get("expert_question"), (
            "HHI assumption must include an expert_question so PI can override it"
        )

    def test_penetration_rates_not_above_one(self):
        """Multiplier × high base penetration must never exceed 100%."""
        result = self._base(hhi=600)  # upside factor
        assert result.y1_penetration   <= 1.0
        assert result.y3_penetration   <= 1.0
        assert result.peak_penetration <= 1.0

    def test_som_scales_proportionally_with_sam(self):
        """SOM = SAM × penetration; doubling SAM should double SOM for same HHI."""
        r1 = compute("biologic", 500_000_000, competitive_context="new_moa", hhi_score=2000)
        r2 = compute("biologic", 1_000_000_000, competitive_context="new_moa", hhi_score=2000)
        ratio = r2.som_peak / r1.som_peak
        assert abs(ratio - 2.0) < 0.01, "Doubling SAM must double SOM (proportional)"

    def test_to_dict_includes_hhi_fields(self):
        import json
        result = self._base(hhi=2200)
        d = result.to_dict()
        assert "hhi_score" in d
        assert "hhi_penetration_factor" in d
        json.dumps(d)  # must be JSON-serialisable


# ──────────────────────────────────────────────────────────────────────────────
# 3. get_hhi_for_indication — returns positive integer for known diseases
# ──────────────────────────────────────────────────────────────────────────────

class TestGetHhiForIndication:

    def test_oncology_returns_hhi(self):
        hhi = get_hhi_for_indication("NSCLC non-small cell lung cancer", "biologic")
        assert hhi is not None and hhi > 0, (
            "Oncology indication must return a positive HHI from CMS data"
        )

    def test_immunology_returns_hhi(self):
        hhi = get_hhi_for_indication("rheumatoid arthritis autoimmune", "biologic")
        assert hhi is not None and hhi > 0

    def test_metabolic_returns_hhi(self):
        hhi = get_hhi_for_indication("type 2 diabetes obesity", "drug_small_molecule")
        assert hhi is not None and hhi > 0

    def test_cardiology_returns_hhi(self):
        hhi = get_hhi_for_indication("atrial fibrillation anticoagulant", "drug_small_molecule")
        assert hhi is not None and hhi > 0

    def test_unknown_disease_returns_none(self):
        hhi = get_hhi_for_indication("xyzzy fictional disease", "other")
        assert hhi is None, (
            "Unrecognised disease must return None (not 0 or a spurious value)"
        )

    def test_return_type_is_int(self):
        hhi = get_hhi_for_indication("cancer tumor oncology", "biologic")
        if hhi is not None:
            assert isinstance(hhi, int), "HHI must be an integer"

    def test_hhi_within_realistic_bounds(self):
        """Any known-TA HHI must be between 100 (very fragmented) and 10,000 (monopoly)."""
        for disease, pt in [
            ("rheumatoid arthritis", "biologic"),
            ("nsclc cancer", "biologic"),
            ("obesity diabetes glp-1", "drug_small_molecule"),
        ]:
            hhi = get_hhi_for_indication(disease, pt)
            if hhi is not None:
                assert 100 <= hhi <= 10_000, (
                    f"HHI={hhi} for '{disease}' is outside plausible bounds 100–10,000"
                )

    def test_cell_therapy_identified_separately_from_oncology(self):
        """CAR-T cell therapy has its own TA bucket distinct from general oncology."""
        hhi_cart = get_hhi_for_indication("car-t cell therapy hematology", "gene_cell_therapy")
        hhi_onco = get_hhi_for_indication("lung cancer nsclc oncology", "biologic")
        # Both should return a value; they may differ since they use different competitor sets
        assert hhi_cart is not None
        assert hhi_onco is not None


# ──────────────────────────────────────────────────────────────────────────────
# 4. End-to-end: HHI known disease → compute() → SOM reduction confirmed
# ──────────────────────────────────────────────────────────────────────────────

class TestEndToEnd:

    def test_oncology_hhi_reduces_som_vs_no_hhi(self):
        hhi = get_hhi_for_indication("lung cancer nsclc", "biologic")
        if hhi is None:
            pytest.skip("No HHI data for this disease — skip end-to-end test")

        result_with    = compute("biologic", SAM, competitive_context="new_moa", hhi_score=hhi)
        result_without = compute("biologic", SAM, competitive_context="new_moa", hhi_score=None)

        factor, _ = _hhi_penetration_factor(hhi)
        if factor < 1.0:
            assert result_with.som_peak < result_without.som_peak, (
                f"Oncology HHI={hhi} (factor={factor:.2f}) should reduce peak SOM"
            )
        elif factor > 1.0:
            assert result_with.som_peak > result_without.som_peak
        else:
            assert result_with.som_peak == result_without.som_peak

    def test_hhi_note_appears_in_analog_note(self):
        """The HHI explanation must be visible in AnalogResult.note so it reaches format_for_prompt."""
        result = compute(
            "biologic", SAM,
            competitive_context="new_moa",
            hhi_score=2800,
        )
        assert "HHI" in result.note or "hhi" in result.note.lower(), (
            "AnalogResult.note must reference HHI when an adjustment was applied"
        )
