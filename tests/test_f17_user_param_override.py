"""
F-17: Tests for PI-provided intake answer → market sizing override pipeline.

Covers:
  - _parse_numeric_range: extracts (lo, hi) from labelled option text
  - _apply_user_params: overrides pop / sp / SAM from clarify_answers dict
  - Full pipeline: TAM/SAM/SOM change when PI provides pop + sp answers

Run: pytest tests/test_f17_user_param_override.py -v
"""

import pytest
from app.services.market_sizing_derivation_service import (
    _parse_numeric_range,
    _apply_user_params,
    _SAM_LO,
    _SAM_HI,
    _SAM_MID,
    _SOM_MID,
)


# ---------------------------------------------------------------------------
# _parse_numeric_range
# ---------------------------------------------------------------------------

class TestParseNumericRange:
    def test_explicit_range_labs(self):
        assert _parse_numeric_range("1,000–5,000 labs — specific research domain") == (1000.0, 5000.0)

    def test_explicit_range_dollars(self):
        lo, hi = _parse_numeric_range("$2,000–$8,000/yr — mid-tier lab infrastructure")
        assert (lo, hi) == (2000.0, 8000.0)

    def test_fewer_than_keyword(self):
        lo, hi = _parse_numeric_range("Fewer than 1,000 labs — very specialized niche")
        assert lo == 0.0 and hi == 1000.0

    def test_under_keyword_dollars(self):
        lo, hi = _parse_numeric_range("Under $500/yr — grant-incidental spend")
        assert lo == 0.0 and hi == 500.0

    def test_over_keyword(self):
        lo, hi = _parse_numeric_range("Over 20,000 labs — any lab with SD card instruments")
        assert lo == 20_000.0 and hi == 80_000.0  # 20000 × 4

    def test_no_numbers_returns_none(self):
        assert _parse_numeric_range("None yet — free beta stage") is None

    def test_single_dollar_range(self):
        lo, hi = _parse_numeric_range("$8,000–$25,000/yr — core facility or site license")
        assert (lo, hi) == (8000.0, 25000.0)

    def test_five_thousand_twenty_thousand(self):
        lo, hi = _parse_numeric_range("5,000–20,000 labs — broad category")
        assert (lo, hi) == (5000.0, 20000.0)


# ---------------------------------------------------------------------------
# _apply_user_params — pop override
# ---------------------------------------------------------------------------

class TestApplyUserParamsPopOverride:
    def _call(self, user_params):
        return _apply_user_params(
            user_params,
            pop_lo=3_000.0, pop_hi=10_000.0,
            sp_lo=1_000.0,  sp_hi=4_000.0,
        )

    def test_pop_overridden_when_answer_provided(self):
        pop_lo, pop_hi, sp_lo, sp_hi, sam_lo, sam_hi, notes = self._call(
            {"seg.target_lab_count": "1,000–5,000 labs — specific research domain"}
        )
        assert pop_lo == 1_000.0
        assert pop_hi == 5_000.0
        assert "pop" in notes

    def test_pop_not_overridden_when_field_absent(self):
        pop_lo, pop_hi, *_ = self._call({})
        assert pop_lo == 3_000.0 and pop_hi == 10_000.0

    def test_pop_not_overridden_when_unparseable(self):
        pop_lo, pop_hi, *_, notes = self._call(
            {"seg.target_lab_count": "None yet — free beta stage"}
        )
        assert pop_lo == 3_000.0
        assert "pop" not in notes

    def test_fewer_than_keyword_sets_lo_to_zero(self):
        pop_lo, pop_hi, *_ = self._call(
            {"seg.target_lab_count": "Fewer than 1,000 labs — very specialized niche"}
        )
        assert pop_lo == 0.0 and pop_hi == 1_000.0


# ---------------------------------------------------------------------------
# _apply_user_params — sp override
# ---------------------------------------------------------------------------

class TestApplyUserParamsSpOverride:
    def _call(self, user_params):
        return _apply_user_params(
            user_params,
            pop_lo=3_000.0, pop_hi=10_000.0,
            sp_lo=1_000.0,  sp_hi=4_000.0,
        )

    def test_sp_overridden(self):
        _, _, sp_lo, sp_hi, _, _, notes = self._call(
            {"price.annual_per_lab": "$500–$2,000/yr — standard research software tier"}
        )
        assert sp_lo == 500.0 and sp_hi == 2_000.0
        assert "sp" in notes

    def test_sp_not_overridden_when_field_absent(self):
        _, _, sp_lo, sp_hi, *_ = self._call({})
        assert sp_lo == 1_000.0 and sp_hi == 4_000.0

    def test_under_keyword_for_sp(self):
        _, _, sp_lo, sp_hi, *_ = self._call(
            {"price.annual_per_lab": "Under $500/yr — grant-incidental spend"}
        )
        assert sp_lo == 0.0 and sp_hi == 500.0


# ---------------------------------------------------------------------------
# _apply_user_params — SAM rate override
# ---------------------------------------------------------------------------

class TestApplyUserParamsSamOverride:
    def _call(self, user_params):
        return _apply_user_params(
            user_params,
            pop_lo=5_000.0, pop_hi=20_000.0,
            sp_lo=2_000.0,  sp_hi=8_000.0,
        )

    def test_sam_range_overridden(self):
        _, _, _, _, sam_lo, sam_hi, notes = self._call(
            {"seg.addressable_fraction": "50–80% — near-universal for target labs"}
        )
        assert sam_lo == pytest.approx(0.50)
        assert sam_hi == pytest.approx(0.80)
        assert "sam" in notes

    def test_sam_not_overridden_when_absent(self):
        _, _, _, _, sam_lo, sam_hi, _ = self._call({})
        assert sam_lo == _SAM_LO
        assert sam_hi == _SAM_HI

    def test_sam_20_50_range(self):
        _, _, _, _, sam_lo, sam_hi, _ = self._call(
            {"seg.addressable_fraction": "20–50% — common friction, labs tolerate manual process"}
        )
        assert sam_lo == pytest.approx(0.20)
        assert sam_hi == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# Full pipeline: TAM changes when PI provides pop + sp
# ---------------------------------------------------------------------------

class TestFullPipelineTamChange:
    """Verify that passing clarify_answers through generate_market_sizing_derivation
    changes the TAM/SAM/SOM output for a research_tool_non_clinical product."""

    def _run(self, user_params):
        from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
        return generate_market_sizing_derivation(
            idea="Hublink — passive wireless data sync for unattended neuroscience instruments",
            product_type="research_tool_non_clinical",
            user_params=user_params,
        )

    def test_default_vs_pi_override_tam_differs(self):
        default = self._run({})
        overridden = self._run({
            "seg.target_lab_count": "1,000–5,000 labs — specific niche",
            "price.annual_per_lab": "$2,000–$8,000/yr — mid-tier lab infrastructure",
        })
        assert overridden.us_tam_usd != default.us_tam_usd

    def test_high_price_answer_increases_tam(self):
        low_price = self._run({"price.annual_per_lab": "$500–$2,000/yr"})
        high_price = self._run({"price.annual_per_lab": "$8,000–$25,000/yr — core facility"})
        assert high_price.us_tam_usd > low_price.us_tam_usd

    def test_larger_pop_answer_increases_tam(self):
        small_pop = self._run({"seg.target_lab_count": "Fewer than 1,000 labs — very specialized"})
        large_pop = self._run({"seg.target_lab_count": "5,000–20,000 labs — broad category"})
        assert large_pop.us_tam_usd > small_pop.us_tam_usd

    def test_higher_sam_rate_increases_sam(self):
        low_sam = self._run({"seg.addressable_fraction": "20–50% — common friction"})
        high_sam = self._run({"seg.addressable_fraction": "50–80% — near-universal"})
        assert high_sam.us_sam_usd > low_sam.us_sam_usd

    def test_empty_params_returns_valid_derivation(self):
        deriv = self._run({})
        assert deriv.us_tam_usd > 0
        assert deriv.us_sam_usd > 0
        assert deriv.us_som_usd > 0
