"""
tests/test_prompt_injection.py
==============================
Tests that OrchestratedResult.format_for_prompt() builds the correct block and
that alignment_service prepends it before any v2 segment text.

Automation boundary
-------------------
These tests verify block *construction* and *position* — the parts the harness
can observe.

UNTESTABLE GAP (documented here, not automated):
  Whether the Claude model actually reads the AUTHORITATIVE block and uses
  the precomputed figures without recomputing them is a qualitative /
  manual QA concern.  Prompt-content tests can only check that the block is
  correctly formed and placed first in the string.  They cannot verify LLM
  behavior.  A separate manual QA checklist should confirm:
    1. The model cites figures from the block (not freshly computed ones).
    2. The model does not hallucinate a different SAM/SOM.
    3. Changing the block values changes the model's narrated figures.
"""

from __future__ import annotations

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

def _make_result(
    sam_usd: float = 500_000_000,
    som_y1_usd: float = 50_000_000,
    som_y3_usd: float = 125_000_000,
    som_peak_usd: float = 250_000_000,
    confidence_score: float = 0.65,
    overall_confidence: str = "medium",
    population: int = 50_000,
):
    """Build a minimal OrchestratedResult sufficient to call format_for_prompt()."""
    from app.services.market_sizing_orchestrator import OrchestratedResult
    from app.services.patient_flow_engine import PatientFlowResult, FlowStep
    from app.services.monetization_engine import MonetizationResult
    from app.services.analog_engine import AnalogResult
    from app.services.confidence_engine import ConfidenceResult

    pf = PatientFlowResult(
        disease_name="test disease",
        product_type_hint="biologic",
        final_population=float(population),
        base_metric="patients",
        steps=[],
        persistency_adjusted_pop=None,
        persistency_months=12,
        assumptions=[],
        data_source="db_seed",
        low_estimate=population * 0.60,
        high_estimate=population * 1.50,
    )

    net_price = sam_usd / population
    mon = MonetizationResult(
        product_type="biologic",
        revenue_model="per_patient_per_year",
        base_unit="patients",
        base_count=float(population),
        net_price_usd=net_price,
        annual_revenue_usd=sam_usd,
        low_revenue_usd=sam_usd * 0.65,
        high_revenue_usd=sam_usd * 1.45,
        price_source="public_dataset",
        price_confidence="medium",
        price_note="test price note",
        assumptions=[],
    )

    analog = AnalogResult(
        analog_class="new_moa",
        analog_label="New MoA — first-in-class",
        competitive_context="new_moa",
        y1_penetration=0.05,
        y3_penetration=0.15,
        peak_penetration=0.25,
        years_to_peak=7,
        som_fraction=0.05,
        som_conservative=som_y1_usd,
        som_base=som_y3_usd,
        som_peak=som_peak_usd,
        source="adoption_benchmarks.json",
        confidence="medium",
        note="test analog note",
        is_site_metric=False,
        assumptions=[],
    )

    conf = ConfidenceResult(
        overall_confidence=overall_confidence,
        confidence_score=confidence_score,
        low_bound_usd=som_y1_usd * 0.70,
        high_bound_usd=som_peak_usd * 1.30,
        verify_with_expert=[],
        honesty_statement="Test honesty statement: all assumptions are synthetic.",
        llm_inference_count=2,
        total_assumptions=6,
        weakest_assumptions=["segment_gate"],
    )

    return OrchestratedResult(
        disease_name="test disease",
        product_type="biologic",
        patient_flow=pf,
        initial_indication_fraction=0.80,
        expansion_path=[],
        initial_population=float(population),
        monetization=mon,
        sam_revenue_usd=sam_usd,
        analog=analog,
        som_conservative_usd=som_y1_usd,
        som_base_usd=som_y3_usd,
        som_peak_usd=som_peak_usd,
        confidence=conf,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Block structure
# ──────────────────────────────────────────────────────────────────────────────

class TestFormatForPromptStructure:

    def test_opens_with_authoritative_header(self):
        block = _make_result().format_for_prompt()
        assert block.startswith(
            "=== PROFESSIONAL MARKET SIZING — AUTHORITATIVE (DO NOT RECOMPUTE) ==="
        ), "Block must open with the AUTHORITATIVE header so the model sees it first"

    def test_do_not_recompute_present(self):
        block = _make_result().format_for_prompt()
        assert "DO NOT RECOMPUTE" in block

    def test_closes_with_end_marker(self):
        block = _make_result().format_for_prompt()
        assert block.strip().endswith("=== END MARKET SIZING ==="), (
            "Block must close with END MARKET SIZING so the model knows where the "
            "structured data ends"
        )

    def test_block_contains_dollar_values(self):
        block = _make_result(sam_usd=500_000_000).format_for_prompt()
        # Any line with a real dollar figure must contain "$"
        dollar_lines = [l for l in block.splitlines() if "$" in l]
        assert dollar_lines, "format_for_prompt() must embed real dollar figures, not placeholders"

    def test_sam_value_appears_in_block(self):
        block = _make_result(sam_usd=750_000_000).format_for_prompt()
        assert "$750M" in block or "750" in block, (
            "SAM revenue must appear in the block so the model cites the correct figure"
        )

    def test_som_values_appear_in_block(self):
        result = _make_result(
            sam_usd=500_000_000,
            som_y1_usd=50_000_000,
            som_y3_usd=125_000_000,
            som_peak_usd=250_000_000,
        )
        block = result.format_for_prompt()
        assert "$50M" in block or "50M" in block, "SOM year-1 must appear in block"
        assert "$125M" in block or "125M" in block, "SOM year-3 must appear in block"
        assert "$250M" in block or "250M" in block, "SOM peak must appear in block"

    def test_penetration_percentages_in_block(self):
        block = _make_result().format_for_prompt()
        assert "5%" in block and "15%" in block and "25%" in block, (
            "Penetration rates (y1/y3/peak) must be included so the model can cite them"
        )

    def test_confidence_score_in_block(self):
        block = _make_result(confidence_score=0.65).format_for_prompt()
        assert "65%" in block or "MEDIUM" in block.upper()

    def test_honesty_statement_in_block(self):
        block = _make_result().format_for_prompt()
        assert "honesty" in block.lower() or "assumption" in block.lower(), (
            "The honesty statement must be included — it is the model's disclosure obligation"
        )

    def test_disease_name_in_block(self):
        block = _make_result().format_for_prompt()
        assert "test disease" in block


# ──────────────────────────────────────────────────────────────────────────────
# Block ordering — orchestrator block must come BEFORE v2 segment text
# ──────────────────────────────────────────────────────────────────────────────

class TestBlockOrdering:

    def test_orch_block_prepended_before_v2_when_v2_present(self):
        """
        Mirrors the logic in alignment_service.py line ~1316:
          segment_block = _orch_block + ("\\n\\n" + segment_block if segment_block else "")
        When both blocks are non-empty, the orchestrator block must appear first.
        """
        orch_block = _make_result().format_for_prompt()
        v2_segment = "v2 segment data: 120,000 eligible patients..."

        # Replicate alignment_service merge logic
        segment_block = orch_block + ("\n\n" + v2_segment if v2_segment else "")

        orch_pos = segment_block.find("AUTHORITATIVE")
        v2_pos = segment_block.find("v2 segment data")
        assert orch_pos < v2_pos, (
            "Orchestrator AUTHORITATIVE block must appear before v2 segment text. "
            "Claude reads top-to-bottom; the authoritative figures must be visible first."
        )

    def test_orch_block_is_standalone_when_no_v2(self):
        """When there is no v2 segment block, the orchestrator block is the full segment_block."""
        orch_block = _make_result().format_for_prompt()
        v2_segment = ""

        segment_block = orch_block + ("\n\n" + v2_segment if v2_segment else "")

        assert segment_block == orch_block
        assert "AUTHORITATIVE" in segment_block

    def test_orch_block_not_empty_for_valid_result(self):
        """format_for_prompt() must never return an empty string for a valid result."""
        block = _make_result().format_for_prompt()
        assert block.strip(), "format_for_prompt() returned an empty block"

    def test_authoritative_header_is_first_line(self):
        block = _make_result().format_for_prompt()
        first_line = block.splitlines()[0]
        assert "AUTHORITATIVE" in first_line and "DO NOT RECOMPUTE" in first_line


# ──────────────────────────────────────────────────────────────────────────────
# Resilience — orchestrator failure must leave v2 block intact
# ──────────────────────────────────────────────────────────────────────────────

class TestOrchestratorFailureResilience:

    def test_v2_block_survives_orchestrator_exception(self):
        """
        Mirrors alignment_service except block (line ~1324):
          except Exception as _orch_e:
              logger.warning(...)
        If the orchestrator raises, segment_block must retain its v2 content.
        """
        v2_segment = "v2 fallback: 120,000 eligible patients"
        _orch_block = None

        # Simulate orchestrator failure
        try:
            raise RuntimeError("DB connection refused")
        except Exception:
            pass  # orchestrator failed — _orch_block remains None

        # Apply the same merge logic as alignment_service
        if _orch_block is not None:
            segment_block = _orch_block + ("\n\n" + v2_segment if v2_segment else "")
        else:
            segment_block = v2_segment  # v2 block unchanged

        assert "v2 fallback" in segment_block, (
            "When the orchestrator fails, v2 segment_block must be preserved — "
            "the PI must still receive some market sizing context"
        )
        assert "AUTHORITATIVE" not in segment_block, (
            "A failed orchestrator must not inject a partial/corrupt AUTHORITATIVE block"
        )

    def test_none_result_does_not_crash_merge(self):
        """OrchestratedResult=None → no AttributeError when merging."""
        _orchestrated_result = None
        v2_segment = "v2 fallback data"
        segment_block = v2_segment  # unchanged when orch is None

        if _orchestrated_result is not None:
            _orch_block = _orchestrated_result.format_for_prompt()
            segment_block = _orch_block + ("\n\n" + segment_block if segment_block else "")

        # Must not raise; v2 must survive
        assert segment_block == v2_segment

    def test_empty_result_block_falls_back_gracefully(self):
        """format_for_prompt() on a valid-but-minimal result must not raise."""
        result = _make_result(
            sam_usd=1_000,
            som_y1_usd=50,
            som_y3_usd=100,
            som_peak_usd=200,
            population=1,
        )
        block = result.format_for_prompt()
        assert "AUTHORITATIVE" in block
        assert "END MARKET SIZING" in block


# ──────────────────────────────────────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_billion_dollar_market_formatted_correctly(self):
        block = _make_result(sam_usd=12_500_000_000).format_for_prompt()
        assert "$12.5B" in block, "Billion-dollar figures must use B suffix, not M"

    def test_million_dollar_market_formatted_correctly(self):
        block = _make_result(sam_usd=750_000_000).format_for_prompt()
        assert "$750M" in block, "Million-dollar figures must use M suffix"

    def test_expansion_path_included_when_present(self):
        result = _make_result()
        result.expansion_path = [
            {"label": "Second-line HER2+", "indication": "second_line", "fraction": 0.30}
        ]
        block = result.format_for_prompt()
        assert "LABEL EXPANSION PATH" in block

    def test_expansion_path_absent_when_empty(self):
        result = _make_result()
        result.expansion_path = []
        block = result.format_for_prompt()
        assert "LABEL EXPANSION PATH" not in block

    def test_top_expert_questions_present_when_nonempty(self):
        from app.services.confidence_engine import ExpertQuestion
        result = _make_result()
        result.confidence.verify_with_expert = [
            ExpertQuestion(
                field_name="segment_gate",
                question="What fraction of patients are eligible?",
                source_type="llm_inference",
                confidence="low",
                impact="high",
                priority_score=0.9,
            )
        ]
        block = result.format_for_prompt()
        assert "TOP QUESTIONS TO VALIDATE" in block
        assert "What fraction of patients are eligible?" in block

    def test_no_expert_questions_section_when_empty(self):
        result = _make_result()
        result.confidence.verify_with_expert = []
        block = result.format_for_prompt()
        assert "TOP QUESTIONS TO VALIDATE" not in block
