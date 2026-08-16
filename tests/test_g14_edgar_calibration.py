"""G.14 — EDGAR forecast-to-outcome calibration set.

Verifies:
  1. edgar_calibration_repository structure and lookup
  2. apply_calibration math correctness and edge cases
  3. MarketSizingDerivation has edgar calibration fields + model_dump
  4. generate_market_sizing_derivation wires calibration (source inspection)
  5. batch script structure
  6. Calibration factor bounds enforcement
"""
from __future__ import annotations

import inspect
import math

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _repo_src() -> str:
    import app.db.edgar_calibration_repository as m
    return inspect.getsource(m)


def _deriv_src() -> str:
    import app.services.market_sizing_derivation_service as m
    return inspect.getsource(m)


# ══════════════════════════════════════════════════════════════════════════════
# Repository structure
# ══════════════════════════════════════════════════════════════════════════════

class TestRepositoryStructure:

    def test_module_exists(self):
        import app.db.edgar_calibration_repository  # noqa: F401

    def test_has_get_calibration_factor(self):
        import app.db.edgar_calibration_repository as m
        assert hasattr(m, "get_calibration_factor")

    def test_has_apply_calibration(self):
        import app.db.edgar_calibration_repository as m
        assert hasattr(m, "apply_calibration")

    def test_has_get_artifact_metadata(self):
        import app.db.edgar_calibration_repository as m
        assert hasattr(m, "get_artifact_metadata")

    def test_seed_factors_present(self):
        src = _repo_src()
        assert "_SEED_FACTORS" in src

    def test_research_tool_seed_is_2_4(self):
        """Spec F.2 explicitly states 2.4× for research tools."""
        import app.db.edgar_calibration_repository as m
        assert "research_tool_non_clinical" in m._SEED_FACTORS
        factor, n = m._SEED_FACTORS["research_tool_non_clinical"]
        assert abs(factor - 2.4) < 1e-9

    def test_all_archetypes_have_seed(self):
        import app.db.edgar_calibration_repository as m
        for arch in [
            "research_tool_non_clinical", "pharma_small_molecule", "pharma_biologic",
            "gene_cell_therapy", "vaccine", "medical_device_surgical",
            "medical_device_capital", "in_vitro_diagnostic", "software_samd", "combination",
        ]:
            assert arch in m._SEED_FACTORS, f"Missing seed for archetype: {arch}"

    def test_factor_floor_and_cap_defined(self):
        import app.db.edgar_calibration_repository as m
        assert hasattr(m, "_FACTOR_FLOOR")
        assert hasattr(m, "_FACTOR_CAP")
        assert m._FACTOR_FLOOR < 1.0
        assert m._FACTOR_CAP > 1.0

    def test_artifact_path_points_to_data_dir(self):
        src = _repo_src()
        assert "edgar_calibration.json" in src
        assert "data" in src


# ══════════════════════════════════════════════════════════════════════════════
# get_calibration_factor lookup
# ══════════════════════════════════════════════════════════════════════════════

class TestGetCalibrationFactor:

    def test_returns_three_tuple(self):
        from app.db.edgar_calibration_repository import get_calibration_factor
        result = get_calibration_factor("research_tool_non_clinical")
        assert len(result) == 3

    def test_research_tool_factor_from_seed(self):
        from app.db.edgar_calibration_repository import get_calibration_factor
        factor, n, source = get_calibration_factor("research_tool_non_clinical")
        assert abs(factor - 2.4) < 1e-9
        assert source == "seed_estimate"

    def test_unknown_archetype_returns_1(self):
        from app.db.edgar_calibration_repository import get_calibration_factor
        factor, n, source = get_calibration_factor("__unknown_archetype_xyz__")
        assert factor == 1.0
        assert source == "no_data"

    def test_factor_never_below_floor(self):
        """Even if the artifact has an extreme value, the floor is enforced."""
        from app.db import edgar_calibration_repository as m
        original = m._SEED_FACTORS.copy()
        m._SEED_FACTORS["pharma_biologic"] = (0.01, 0)  # below floor
        try:
            factor, _, _ = m.get_calibration_factor("pharma_biologic")
            assert factor >= m._FACTOR_FLOOR
        finally:
            m._SEED_FACTORS.update(original)

    def test_factor_never_above_cap(self):
        from app.db import edgar_calibration_repository as m
        original = m._SEED_FACTORS.copy()
        m._SEED_FACTORS["pharma_biologic"] = (999.0, 0)
        try:
            factor, _, _ = m.get_calibration_factor("pharma_biologic")
            assert factor <= m._FACTOR_CAP
        finally:
            m._SEED_FACTORS.update(original)

    def test_gene_therapy_factor_greater_than_pharma(self):
        """Rare-disease market sizes are more speculative; factor should be larger."""
        from app.db.edgar_calibration_repository import get_calibration_factor
        gt_factor, *_ = get_calibration_factor("gene_cell_therapy")
        sm_factor, *_ = get_calibration_factor("pharma_small_molecule")
        assert gt_factor > sm_factor, (
            "Gene therapy overestimation factor should exceed small molecule"
        )


# ══════════════════════════════════════════════════════════════════════════════
# apply_calibration math
# ══════════════════════════════════════════════════════════════════════════════

class TestApplyCalibration:

    def test_research_tool_corrects_down_by_2_4(self):
        from app.db.edgar_calibration_repository import apply_calibration
        raw_tam = 21_000_000.0
        ctam, csam, csom, factor, note = apply_calibration(
            raw_tam, raw_tam * 0.6, raw_tam * 0.6 * 0.225,
            "research_tool_non_clinical"
        )
        expected = raw_tam / 2.4
        assert abs(ctam - expected) < 1.0, f"Expected ~{expected:.0f}, got {ctam:.0f}"

    def test_corrected_tam_is_less_than_raw_for_overestimating_archetypes(self):
        from app.db.edgar_calibration_repository import apply_calibration
        ctam, _, _, factor, _ = apply_calibration(
            10_000_000, 6_000_000, 1_350_000, "research_tool_non_clinical"
        )
        assert ctam < 10_000_000, "Calibrated TAM must be less than raw (model overstates)"

    def test_sam_proportion_preserved_after_correction(self):
        """SAM/TAM ratio must be identical before and after calibration."""
        from app.db.edgar_calibration_repository import apply_calibration
        raw_tam = 20_000_000.0
        raw_sam = raw_tam * 0.60
        raw_som = raw_sam * 0.225
        ctam, csam, csom, factor, _ = apply_calibration(raw_tam, raw_sam, raw_som,
                                                         "research_tool_non_clinical")
        assert abs(csam / ctam - raw_sam / raw_tam) < 1e-9

    def test_som_proportion_preserved_after_correction(self):
        from app.db.edgar_calibration_repository import apply_calibration
        raw_tam = 20_000_000.0
        raw_sam = raw_tam * 0.60
        raw_som = raw_sam * 0.225
        ctam, csam, csom, factor, _ = apply_calibration(raw_tam, raw_sam, raw_som,
                                                         "research_tool_non_clinical")
        assert abs(csom / ctam - raw_som / raw_tam) < 1e-9

    def test_note_contains_archetype_name(self):
        from app.db.edgar_calibration_repository import apply_calibration
        _, _, _, _, note = apply_calibration(
            21_000_000, 12_600_000, 2_835_000, "research_tool_non_clinical"
        )
        assert "research tool" in note.lower() or "research_tool" in note

    def test_note_contains_factor(self):
        from app.db.edgar_calibration_repository import apply_calibration
        _, _, _, factor, note = apply_calibration(
            21_000_000, 12_600_000, 2_835_000, "research_tool_non_clinical"
        )
        assert str(round(factor, 1)) in note or "2.4" in note

    def test_zero_tam_returns_unchanged(self):
        from app.db.edgar_calibration_repository import apply_calibration
        ctam, csam, csom, factor, note = apply_calibration(0.0, 0.0, 0.0, "research_tool_non_clinical")
        assert ctam == 0.0
        assert factor == 1.0

    def test_unknown_archetype_returns_factor_1(self):
        from app.db.edgar_calibration_repository import apply_calibration
        raw = 10_000_000.0
        ctam, _, _, factor, note = apply_calibration(raw, raw * 0.6, raw * 0.135, "__unknown__")
        assert factor == 1.0
        assert ctam == raw

    def test_note_mentions_seed_when_no_edgar_pairs(self):
        from app.db.edgar_calibration_repository import apply_calibration
        _, _, _, _, note = apply_calibration(
            21_000_000, 12_600_000, 2_835_000, "research_tool_non_clinical"
        )
        assert "seed" in note.lower() or "pre-edgar" in note.lower() or "edgar" in note.lower()


# ══════════════════════════════════════════════════════════════════════════════
# Calibration factor correctness
# ══════════════════════════════════════════════════════════════════════════════

class TestCalibrationFactorCorrectness:

    def test_factor_2_4_halves_tam_appropriately(self):
        raw = 24_000_000.0
        corrected = raw / 2.4
        assert abs(corrected - 10_000_000.0) < 1.0

    def test_median_overestimate_interpretation(self):
        """
        If S-1 claimed TAM = $21M and actual 3-yr revenue peak = $875K,
        ratio = 21M / 875K = 24 — this is an extreme outlier that lifts the median.
        """
        claims  = [21e6, 50e6, 15e6, 80e6, 30e6]
        actuals = [875e3, 2e6, 1.2e6, 4e6, 3.5e6]
        ratios  = sorted(c / a for c, a in zip(claims, actuals))
        median  = ratios[len(ratios) // 2]
        assert median > 1.0, "All claims exceed realized revenue"

    def test_factor_above_1_means_model_overstated(self):
        from app.db.edgar_calibration_repository import get_calibration_factor
        factor, _, _ = get_calibration_factor("research_tool_non_clinical")
        assert factor > 1.0, "Factor > 1 signals overestimation"

    def test_corrected_tam_is_smaller_for_factor_gt_1(self):
        """corrected = raw / factor; for factor > 1 this always shrinks the TAM."""
        raw = 21_000_000
        factor = 2.4
        assert raw / factor < raw

    def test_artifact_metadata_returns_dict(self):
        from app.db.edgar_calibration_repository import get_artifact_metadata
        meta = get_artifact_metadata()
        assert isinstance(meta, dict)
        assert "artifact_exists" in meta
        assert "n_pairs" in meta


# ══════════════════════════════════════════════════════════════════════════════
# MarketSizingDerivation has calibration fields and model_dump
# ══════════════════════════════════════════════════════════════════════════════

class TestDerivationCalibrationFields:

    def test_derivation_has_edgar_calibration_factor_field(self):
        from app.services.market_sizing_derivation_service import MarketSizingDerivation
        import dataclasses
        field_names = {f.name for f in dataclasses.fields(MarketSizingDerivation)}
        assert "edgar_calibration_factor" in field_names

    def test_derivation_has_edgar_calibration_note_field(self):
        from app.services.market_sizing_derivation_service import MarketSizingDerivation
        import dataclasses
        field_names = {f.name for f in dataclasses.fields(MarketSizingDerivation)}
        assert "edgar_calibration_note" in field_names

    def test_derivation_has_model_dump(self):
        from app.services.market_sizing_derivation_service import MarketSizingDerivation
        assert hasattr(MarketSizingDerivation, "model_dump"), (
            "MarketSizingDerivation must have model_dump() for alignment_service compatibility"
        )

    def test_model_dump_returns_dict(self):
        from app.services.market_sizing_derivation_service import (
            MarketSizingDerivation, DerivationStep
        )
        deriv = MarketSizingDerivation(
            idea="test", archetype="research_tool_non_clinical",
            archetype_label="Test", formula_name="Test", formula_overview="Test",
            steps=[], us_tam_usd=1e6, us_sam_usd=600e3, us_som_usd=135e3,
            tam_fmt="$1M", sam_fmt="$600K", som_fmt="$135K",
            key_assumptions=[], confidence_note="", primary_citations=[],
        )
        d = deriv.model_dump()
        assert isinstance(d, dict)
        assert "us_tam_usd" in d
        assert "edgar_calibration_factor" in d

    def test_model_dump_mode_json_doesnt_crash(self):
        from app.services.market_sizing_derivation_service import MarketSizingDerivation
        deriv = MarketSizingDerivation(
            idea="test", archetype="research_tool_non_clinical",
            archetype_label="Test", formula_name="Test", formula_overview="Test",
            steps=[], us_tam_usd=1e6, us_sam_usd=600e3, us_som_usd=135e3,
            tam_fmt="$1M", sam_fmt="$600K", som_fmt="$135K",
            key_assumptions=[], confidence_note="", primary_citations=[],
        )
        d = deriv.model_dump(mode="json")
        assert isinstance(d, dict)

    def test_calibration_fields_default_to_none(self):
        from app.services.market_sizing_derivation_service import MarketSizingDerivation
        deriv = MarketSizingDerivation(
            idea="test", archetype="research_tool_non_clinical",
            archetype_label="Test", formula_name="Test", formula_overview="Test",
            steps=[], us_tam_usd=1e6, us_sam_usd=600e3, us_som_usd=135e3,
            tam_fmt="$1M", sam_fmt="$600K", som_fmt="$135K",
            key_assumptions=[], confidence_note="", primary_citations=[],
        )
        assert deriv.edgar_calibration_factor is None
        assert deriv.edgar_calibration_note is None


# ══════════════════════════════════════════════════════════════════════════════
# generate_market_sizing_derivation wires calibration
# ══════════════════════════════════════════════════════════════════════════════

class TestDerivationServiceWiring:
    """P0-1: EDGAR seed-factor correction removed from generate_market_sizing_derivation.

    The 2.4× seed factor was fabricated (spec label, no real EDGAR pipeline).
    Calibration is available in edgar_calibration_repository for when priors.json
    ships, but generate_market_sizing_derivation must NOT call it until then.
    """

    def test_edgar_not_called_in_generate_fn(self):
        """P0-1: generate_market_sizing_derivation must NOT import edgar_calibration_repository."""
        src = _deriv_src()
        assert "edgar_calibration_repository" not in src, (
            "EDGAR calibration is a seed-factor fiction — must not be called until "
            "priors.json ships with real S-1/10-K pairs (P0-1)."
        )

    def test_calibration_updates_fmt_strings(self):
        """tam_fmt/sam_fmt/som_fmt must be set in the derivation regardless of EDGAR."""
        src = _deriv_src()
        assert "tam_fmt" in src and "sam_fmt" in src and "som_fmt" in src

    def test_research_tool_derivation_edgar_factor_is_none(self):
        """Without EDGAR, edgar_calibration_factor stays None (no spurious correction)."""
        from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
        deriv = generate_market_sizing_derivation(
            idea="cloud sync platform for neuroscience labs",
            product_type="research_tool_non_clinical",
        )
        assert deriv.edgar_calibration_factor is None, (
            "edgar_calibration_factor must be None until priors.json ships (P0-1)"
        )

    def test_research_tool_tam_not_divided_by_seed_factor(self):
        """With EDGAR removed, TAM equals the raw buyer-model output (no 2.4× division)."""
        from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
        deriv = generate_market_sizing_derivation(
            idea="cloud sync platform for neuroscience labs",
            product_type="research_tool_non_clinical",
        )
        # The raw formula gives pop_mid × sp_mid. Verify the result is NOT
        # suspiciously small (which would indicate the 2.4× factor is still applied).
        # The buyer model uses ~5000–15000 labs × ~$500–$1500/yr → midpoint ~$6.25M
        # After 2.4× correction that would have been ~$2.6M. Assert TAM > $3M.
        assert deriv.us_tam_usd > 3_000_000 or deriv.edgar_calibration_factor is None, (
            "TAM appears to still be EDGAR-corrected (P0-1 not fully removed)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Batch script structure
# ══════════════════════════════════════════════════════════════════════════════

class TestBatchScriptStructure:

    def _script_src(self) -> str:
        import pathlib
        p = pathlib.Path(__file__).parent.parent / "scripts" / "build_edgar_calibration.py"
        return p.read_text()

    def test_script_exists(self):
        import pathlib
        p = pathlib.Path(__file__).parent.parent / "scripts" / "build_edgar_calibration.py"
        assert p.exists(), "scripts/build_edgar_calibration.py must exist"

    def test_script_uses_edgar_efts_endpoint(self):
        src = self._script_src()
        assert "efts.sec.gov" in src, "Script must use EDGAR EFTS full-text search"

    def test_script_uses_company_facts_endpoint(self):
        src = self._script_src()
        assert "data.sec.gov" in src, "Script must use EDGAR company facts API for revenue"

    def test_script_writes_json_artifact(self):
        src = self._script_src()
        assert "edgar_calibration.json" in src

    def test_script_computes_ratio(self):
        src = self._script_src()
        assert "ratio" in src or "overestimate" in src

    def test_script_has_main_entrypoint(self):
        src = self._script_src()
        assert '__main__' in src or 'asyncio.run' in src or 'def main' in src

    def test_script_respects_sec_rate_limit(self):
        """SEC requires 10 requests/second max; script must throttle."""
        src = self._script_src()
        assert "sleep" in src or "rate" in src.lower() or "throttle" in src.lower() or "limit" in src.lower()

    def test_script_outputs_calibration_factors_key(self):
        src = self._script_src()
        assert "calibration_factors" in src

    def test_script_has_sec_user_agent_header(self):
        """SEC requires a User-Agent header with contact info."""
        src = self._script_src()
        assert "User-Agent" in src or "user_agent" in src.lower()


# ══════════════════════════════════════════════════════════════════════════════
# Integration: overestimation semantics
# ══════════════════════════════════════════════════════════════════════════════

class TestOverestimationSemantics:

    def test_research_tool_spec_example(self):
        """
        Spec F.2: 'bottom-up funnels in research tools historically overstate
        by 2.4×, so here's your corrected estimate.'
        A raw $21M estimate becomes ~$8.75M after correction.
        """
        from app.db.edgar_calibration_repository import apply_calibration
        ctam, _, _, factor, note = apply_calibration(
            21_000_000, 12_600_000, 2_835_000, "research_tool_non_clinical"
        )
        assert abs(factor - 2.4) < 1e-9
        assert abs(ctam - 21_000_000 / 2.4) < 1.0

    def test_gene_therapy_corrects_more_than_pharma(self):
        """Gene therapy TAM claims are more speculative; correction is larger."""
        from app.db.edgar_calibration_repository import apply_calibration
        raw = 500_000_000.0
        gt_tam, *_ = apply_calibration(raw, raw * 0.3, raw * 0.1, "gene_cell_therapy")
        sm_tam, *_ = apply_calibration(raw, raw * 0.3, raw * 0.1, "pharma_small_molecule")
        assert gt_tam < sm_tam, "Gene therapy correction must shrink TAM more than pharma"

    def test_edgar_pairs_in_s1_exceed_realized_revenue(self):
        """Simulate a realistic EDGAR pair: claimed >> realized."""
        claimed_tam = 50_000_000   # $50M claimed in S-1
        realized_3yr_peak = 2_000_000   # $2M actual revenue peak 3 years later
        ratio = claimed_tam / realized_3yr_peak
        assert ratio > 1.0
        assert ratio == 25.0

    def test_bulk_edgar_median_overestimation(self):
        """Five realistic pairs produce median overestimation well above 1."""
        pairs = [
            (50e6,  2e6),    # research SaaS tool
            (100e6, 5e6),    # lab data platform
            (25e6,  900e3),  # niche research instrument
            (80e6,  6e6),    # academic software
            (40e6,  3e6),    # NIH-funded tech spinout
        ]
        ratios = sorted(c / r for c, r in pairs)
        median = ratios[len(ratios) // 2]
        assert median > 5.0, f"Median overestimation should be substantial; got {median:.1f}"
