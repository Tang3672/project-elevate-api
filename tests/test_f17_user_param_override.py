"""
F-17: Tests for PI-provided intake answer → market sizing override pipeline.

Covers:
  - _parse_numeric_range: extracts (lo, hi) from labelled option text
  - _workflow_sam: SAM rate from workflow type keyword matching
  - _adoption_som: SOM rate from adoption pathway keyword matching
  - _apply_user_params: overrides pop / sp / SAM / SOM from clarify_answers dict
  - Full pipeline: TAM/SAM/SOM change when PI provides product-understanding answers

Run: pytest tests/test_f17_user_param_override.py -v
"""

import pytest
from app.services.market_sizing_derivation_service import (
    _parse_numeric_range,
    _workflow_sam,
    _adoption_som,
    _apply_user_params,
    _SAM_LO,
    _SAM_HI,
    _SOM_LO,
    _SOM_HI,
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
        assert lo == 20_000.0 and hi == 80_000.0

    def test_no_numbers_returns_none(self):
        assert _parse_numeric_range("None yet — free beta stage") is None

    def test_instrument_option_large_range(self):
        lo, hi = _parse_numeric_range(
            "Any internet-connected computer — no specialized instruments required (~30,000–80,000 US academic research labs)"
        )
        assert (lo, hi) == (30_000.0, 80_000.0)

    def test_instrument_option_narrow_range(self):
        lo, hi = _parse_numeric_range(
            "Labs running a particular instrument model or brand-specific workflow (~1,500–5,000 qualifying labs)"
        )
        assert (lo, hi) == (1_500.0, 5_000.0)

    def test_instrument_option_core_facility(self):
        lo, hi = _parse_numeric_range(
            "Core facilities or institutional shared-equipment deployments (~500–2,000 facilities)"
        )
        assert (lo, hi) == (500.0, 2_000.0)


# ---------------------------------------------------------------------------
# _workflow_sam
# ---------------------------------------------------------------------------

class TestWorkflowSam:
    def test_passive_sync_returns_high_sam(self):
        lo, hi = _workflow_sam(
            "Passive data sync or automated transfer — collects or moves data automatically, without researcher action"
        )
        assert lo >= 0.40 and hi >= 0.65

    def test_instrument_control_returns_low_sam(self):
        lo, hi = _workflow_sam(
            "Instrument integration or hardware control — connects instruments, automates equipment, or closes the feedback loop"
        )
        assert lo <= 0.25 and hi <= 0.50

    def test_active_analysis_returns_medium_sam(self):
        lo, hi = _workflow_sam(
            "Active data analysis or visualization — researcher initiates it to process each experiment"
        )
        assert 0.20 <= lo <= 0.35 and 0.45 <= hi <= 0.65

    def test_unrecognized_returns_none(self):
        assert _workflow_sam("Something completely unrelated") is None

    def test_high_sam_greater_than_low_sam(self):
        passive_lo, passive_hi = _workflow_sam("Passive data sync or automated transfer")
        control_lo, control_hi = _workflow_sam("Instrument integration or hardware control")
        assert passive_lo > control_lo
        assert passive_hi > control_hi


# ---------------------------------------------------------------------------
# _adoption_som
# ---------------------------------------------------------------------------

class TestAdoptionSom:
    def test_viral_peer_returns_high_som(self):
        lo, hi = _adoption_som(
            "Peer-to-peer among researchers — a grad student or postdoc finds it and recommends it within their network"
        )
        assert lo >= 0.12 and hi >= 0.25

    def test_publication_driven_returns_low_som(self):
        lo, hi = _adoption_som(
            "Conference or publication-driven — labs adopt after seeing it in a talk, paper, or preprint"
        )
        assert hi <= 0.18

    def test_facility_rollout_returns_medium_som(self):
        lo, hi = _adoption_som(
            "Core facility or IT roll-out — a facility director or university IT deploys it across multiple labs or departments"
        )
        assert 0.08 <= lo and hi <= 0.28

    def test_unrecognized_returns_none(self):
        assert _adoption_som("Something completely unrelated") is None

    def test_viral_som_greater_than_publication_som(self):
        v_lo, v_hi = _adoption_som("Peer-to-peer among researchers — grad student or postdoc recommends it")
        p_lo, p_hi = _adoption_som("Conference or publication-driven — paper or preprint")
        assert v_lo > p_lo
        assert v_hi > p_hi


# ---------------------------------------------------------------------------
# _apply_user_params — instrument requirement → population
# ---------------------------------------------------------------------------

class TestApplyUserParamsInstrumentRequirement:
    def _call(self, user_params):
        return _apply_user_params(
            user_params,
            pop_lo=3_000.0, pop_hi=10_000.0,
            sp_lo=1_000.0,  sp_hi=4_000.0,
        )

    def test_instrument_option_overrides_population(self):
        pop_lo, pop_hi, *_, notes = self._call({
            "seg.instrument_requirement": (
                "Labs with specific data-generating instruments "
                "(e.g., electrophysiology rigs, sequencers, imagers) (~5,000–20,000 qualifying labs)"
            )
        })
        assert pop_lo == 5_000.0
        assert pop_hi == 20_000.0
        assert "pop" in notes

    def test_any_computer_option_gives_broad_population(self):
        pop_lo, pop_hi, *_ = self._call({
            "seg.instrument_requirement": (
                "Any internet-connected computer — no specialized instruments required "
                "(~30,000–80,000 US academic research labs)"
            )
        })
        assert pop_lo == 30_000.0
        assert pop_hi == 80_000.0

    def test_core_facility_option_gives_narrow_population(self):
        pop_lo, pop_hi, *_ = self._call({
            "seg.instrument_requirement": (
                "Core facilities or institutional shared-equipment deployments (~500–2,000 facilities)"
            )
        })
        assert pop_lo == 500.0
        assert pop_hi == 2_000.0

    def test_no_instrument_answer_leaves_default(self):
        pop_lo, pop_hi, *_ = self._call({})
        assert pop_lo == 3_000.0 and pop_hi == 10_000.0

    def test_instrument_overrides_legacy_target_lab_count(self):
        # seg.instrument_requirement takes precedence over seg.target_lab_count
        pop_lo, pop_hi, *_ = self._call({
            "seg.instrument_requirement": "Labs running a particular instrument (~1,500–5,000 qualifying labs)",
            "seg.target_lab_count": "1,000–3,000 labs",
        })
        assert pop_lo == 1_500.0
        assert pop_hi == 5_000.0


# ---------------------------------------------------------------------------
# _apply_user_params — price
# ---------------------------------------------------------------------------

class TestApplyUserParamsPrice:
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

    def test_sp_not_overridden_when_absent(self):
        _, _, sp_lo, sp_hi, *_ = self._call({})
        assert sp_lo == 1_000.0 and sp_hi == 4_000.0


# ---------------------------------------------------------------------------
# _apply_user_params — workflow SAM and adoption SOM
# ---------------------------------------------------------------------------

class TestApplyUserParamsWorkflowAndAdoption:
    def _call(self, user_params):
        return _apply_user_params(
            user_params,
            pop_lo=5_000.0, pop_hi=20_000.0,
            sp_lo=2_000.0,  sp_hi=8_000.0,
        )

    def test_passive_workflow_raises_sam(self):
        _, _, _, _, sam_lo, sam_hi, notes = self._call({
            "seg.workflow_type": "Passive data sync or automated transfer — without researcher action"
        })
        assert sam_lo >= _SAM_HI  # must be higher than default max
        assert "sam" in notes

    def test_instrument_control_lowers_sam(self):
        _, _, _, _, sam_lo, sam_hi, notes = self._call({
            "seg.workflow_type": "Instrument integration or hardware control"
        })
        assert sam_hi <= _SAM_HI
        assert "sam" in notes

    def test_viral_adoption_sets_som_in_overrides(self):
        _, _, _, _, _, _, notes = self._call({
            "seg.adoption_pathway": "Peer-to-peer among researchers — grad student or postdoc recommends it"
        })
        assert "som" in notes
        som_lo, som_hi = notes["som"]
        assert som_hi > _SOM_HI   # peer viral pushes ceiling above default max SOM

    def test_publication_adoption_sets_low_som(self):
        _, _, _, _, _, _, notes = self._call({
            "seg.adoption_pathway": "Conference or publication-driven — paper or preprint"
        })
        assert "som" in notes
        som_lo, som_hi = notes["som"]
        assert som_hi <= _SOM_LO * 4  # conservative cap

    def test_unrecognized_workflow_leaves_sam_default(self):
        _, _, _, _, sam_lo, sam_hi, notes = self._call({
            "seg.workflow_type": "Something completely unexpected"
        })
        assert sam_lo == _SAM_LO and sam_hi == _SAM_HI
        assert "sam" not in notes


# ---------------------------------------------------------------------------
# Full pipeline: TAM changes when PI provides product-understanding answers
# ---------------------------------------------------------------------------

class TestFullPipelineTamChange:
    def _run(self, user_params):
        from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
        return generate_market_sizing_derivation(
            idea="Hublink — passive wireless data sync for unattended neuroscience instruments",
            product_type="research_tool_non_clinical",
            user_params=user_params,
        )

    def test_broad_instrument_requirement_increases_tam(self):
        narrow = self._run({
            "seg.instrument_requirement": "Core facilities or institutional shared-equipment deployments (~500–2,000 facilities)"
        })
        broad = self._run({
            "seg.instrument_requirement": "Any internet-connected computer (~30,000–80,000 US academic research labs)"
        })
        assert broad.us_tam_usd > narrow.us_tam_usd

    def test_high_price_answer_increases_tam(self):
        low_price = self._run({"price.annual_per_lab": "$500–$2,000/yr"})
        high_price = self._run({"price.annual_per_lab": "$8,000–$25,000/yr — core facility"})
        assert high_price.us_tam_usd > low_price.us_tam_usd

    def test_passive_workflow_increases_sam(self):
        low_sam = self._run({
            "seg.workflow_type": "Instrument integration or hardware control"
        })
        high_sam = self._run({
            "seg.workflow_type": "Passive data sync or automated transfer — without researcher action"
        })
        assert high_sam.us_sam_usd > low_sam.us_sam_usd

    def test_viral_adoption_increases_som(self):
        slow = self._run({
            "seg.adoption_pathway": "Conference or publication-driven — paper or preprint"
        })
        fast = self._run({
            "seg.adoption_pathway": "Peer-to-peer among researchers — grad student or postdoc recommends it"
        })
        assert fast.us_som_usd > slow.us_som_usd

    def test_empty_params_returns_valid_derivation(self):
        deriv = self._run({})
        assert deriv.us_tam_usd > 0
        assert deriv.us_sam_usd > 0
        assert deriv.us_som_usd > 0

    def test_combined_answers_change_all_three_metrics(self):
        default = self._run({})
        overridden = self._run({
            "seg.instrument_requirement": "Labs with specific data-generating instruments (~5,000–20,000 qualifying labs)",
            "price.annual_per_lab": "$2,000–$8,000/yr — mid-tier lab infrastructure tool",
            "seg.workflow_type": "Passive data sync or automated transfer — without researcher action",
            "seg.adoption_pathway": "Peer-to-peer among researchers — grad student or postdoc recommends it",
        })
        assert overridden.us_tam_usd != default.us_tam_usd
        assert overridden.us_sam_usd != default.us_sam_usd
        assert overridden.us_som_usd != default.us_som_usd
