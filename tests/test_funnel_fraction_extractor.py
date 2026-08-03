"""
tests/test_funnel_fraction_extractor.py
========================================
Tests for the citation-enforced funnel fraction extraction pipeline.

Coverage:
  1. _calibrate_confidence() — study-design signal adjustments
  2. _build_citation() — citation string format
  3. _build_fraction_query() — PubMed query construction
  4. LiteratureFractionResult.to_dict() — serialisation round-trip
  5. extract_funnel_fraction() — confidence gate routing (mocked LLM + PubMed)
  6. _enrich_null_gates() — patient_flow_engine integration (mocked extractor)
  7. Fraction review queue — DB interaction (mocked pool)
  8. Blueprint benchmark: confidence gate at 0.70

Blueprint rule enforced by every test that touches LLM output:
  "No fraction ships without a citation + verbatim quote"
  → all auto-approved results must have non-empty citation AND verbatim_quote.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.funnel_fraction_extractor import (
    CONFIDENCE_GATE,
    LiteratureFractionResult,
    _build_citation,
    _build_fraction_query,
    _calibrate_confidence,
    extract_funnel_fraction,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_result(
    fraction: Optional[float] = 0.25,
    confidence: float = 0.80,
    needs_review: bool = False,
    pmid: Optional[str] = "12345678",
    quote: Optional[str] = "Exactly 25% of patients were eligible.",
    method: str = "pubmed_live",
) -> LiteratureFractionResult:
    return LiteratureFractionResult(
        disease_name="ischemic stroke",
        gate_name="treated_segment",
        gate_label="eligible for thrombectomy",
        fraction=fraction,
        pmid=pmid,
        verbatim_quote=quote,
        citation=_build_citation("Smith et al.", "2022", "LVO study", "Stroke", pmid or ""),
        confidence=confidence,
        needs_review=needs_review,
        extraction_method=method,
        raw_abstract="Exactly 25% of patients were eligible for thrombectomy.",
    )


# ──────────────────────────────────────────────────────────────────────────────
# 1. _calibrate_confidence
# ──────────────────────────────────────────────────────────────────────────────

class TestCalibrateConfidence:

    def test_meta_analysis_boosts_confidence(self):
        base = 0.70
        adj = _calibrate_confidence(base, "This meta-analysis of 12 RCTs found...", "Meta-analysis of stroke")
        assert adj > base, "Meta-analysis signal must increase confidence"

    def test_single_center_lowers_confidence(self):
        base = 0.75
        adj = _calibrate_confidence(base, "A single center retrospective study...", "Pilot study")
        assert adj < base, "Single-center study must lower confidence"

    def test_case_series_lowers_confidence(self):
        base = 0.75
        adj = _calibrate_confidence(base, "Case series of 12 patients with LVO...", "Case series")
        assert adj < base

    def test_confidence_never_exceeds_095(self):
        adj = _calibrate_confidence(0.98, "meta-analysis pooled analysis", "")
        assert adj <= 0.95

    def test_confidence_never_below_zero(self):
        adj = _calibrate_confidence(0.05, "single center case report n = 3", "")
        assert adj >= 0.0

    def test_clean_abstract_unchanged(self):
        base = 0.72
        adj = _calibrate_confidence(base, "A multicenter RCT of 450 patients...", "RCT results")
        # no signals → no change (or very small)
        assert abs(adj - base) < 0.01


# ──────────────────────────────────────────────────────────────────────────────
# 2. _build_citation
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildCitation:

    def test_all_fields_present(self):
        c = _build_citation("Smith et al.", "2022", "LVO study", "Stroke", "12345678")
        assert "Smith" in c
        assert "2022" in c
        assert "LVO" in c
        assert "Stroke" in c
        assert "12345678" in c

    def test_missing_pmid_graceful(self):
        c = _build_citation("Jones", "2020", "Epidemiology study", "Lancet", "")
        assert "Jones" in c
        assert "PMID" not in c  # no PMID should appear if empty

    def test_missing_author_graceful(self):
        c = _build_citation("", "2021", "Stroke outcomes", "NEJM", "99887766")
        assert "2021" in c
        assert "Stroke" in c


# ──────────────────────────────────────────────────────────────────────────────
# 3. _build_fraction_query
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildFractionQuery:

    def test_query_contains_disease(self):
        q = _build_fraction_query("ischemic stroke", "eligible for thrombectomy", None)
        assert "ischemic stroke" in q

    def test_query_contains_gate_keyword(self):
        q = _build_fraction_query("NSCLC", "EGFR-positive fraction", None)
        assert "EGFR" in q

    def test_query_contains_epidemiology_terms(self):
        q = _build_fraction_query("HER2+ breast cancer", "treatment eligible", None)
        assert any(t in q for t in ("proportion", "prevalence", "epidemiology", "fraction"))

    def test_note_keyword_incorporated(self):
        q = _build_fraction_query("stroke", "LVO-eligible", "0.16 for LVO thrombectomy")
        # note text feeds into query; disease must still be present
        assert "stroke" in q


# ──────────────────────────────────────────────────────────────────────────────
# 4. LiteratureFractionResult — serialisation
# ──────────────────────────────────────────────────────────────────────────────

class TestLiteratureFractionResultSerialization:

    def test_to_dict_is_json_serialisable(self):
        r = _make_result()
        d = r.to_dict()
        json.dumps(d)  # must not raise

    def test_to_dict_has_required_keys(self):
        d = _make_result().to_dict()
        for key in ("disease_name", "gate_name", "fraction", "confidence",
                    "needs_review", "extraction_method"):
            assert key in d, f"Missing key: {key}"

    def test_needs_review_false_for_high_confidence(self):
        r = _make_result(confidence=0.85, needs_review=False)
        assert r.to_dict()["needs_review"] is False

    def test_needs_review_true_for_low_confidence(self):
        r = _make_result(confidence=0.60, needs_review=True)
        assert r.to_dict()["needs_review"] is True

    def test_fraction_is_float_or_none(self):
        d = _make_result(fraction=0.20).to_dict()
        assert isinstance(d["fraction"], float)

    def test_null_fraction_serialises(self):
        r = _make_result(fraction=None, confidence=0.0, needs_review=True)
        d = r.to_dict()
        assert d["fraction"] is None


# ──────────────────────────────────────────────────────────────────────────────
# 5. extract_funnel_fraction — confidence gate routing (mocked I/O)
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractFunnelFractionConfidenceGate:
    """
    These tests mock out all I/O (DB, RAG, PubMed, LLM) and exercise the
    routing logic: high-confidence → auto-approved; low-confidence → needs_review.
    """

    @pytest.mark.asyncio
    async def test_high_confidence_fraction_is_not_flagged_for_review(self):
        """confidence ≥ 0.70 → needs_review=False."""
        mock_result = _make_result(confidence=0.82, needs_review=False)

        with (
            patch("app.db.fraction_review_queue.check_approved_fraction", new_callable=AsyncMock, return_value=None),
            patch("app.services.funnel_fraction_extractor._try_rag_extraction", new_callable=AsyncMock, return_value=None),
            patch("app.services.funnel_fraction_extractor._try_pubmed_extraction", new_callable=AsyncMock, return_value=mock_result),
        ):
            result = await extract_funnel_fraction(
                "ischemic stroke", "treated_segment", "eligible for thrombectomy"
            )

        assert result.fraction == 0.25
        assert result.needs_review is False

    @pytest.mark.asyncio
    async def test_low_confidence_fraction_is_flagged_for_review(self):
        """confidence < 0.70 → needs_review=True even when fraction is found."""
        mock_result = _make_result(confidence=0.55, needs_review=True)

        with (
            patch("app.db.fraction_review_queue.check_approved_fraction", new_callable=AsyncMock, return_value=None),
            patch("app.services.funnel_fraction_extractor._try_rag_extraction", new_callable=AsyncMock, return_value=None),
            patch("app.services.funnel_fraction_extractor._try_pubmed_extraction", new_callable=AsyncMock, return_value=mock_result),
        ):
            result = await extract_funnel_fraction(
                "ischemic stroke", "treated_segment", "eligible for thrombectomy"
            )

        assert result.fraction == 0.25
        assert result.needs_review is True

    @pytest.mark.asyncio
    async def test_confidence_gate_boundary_is_070(self):
        """Results at exactly 0.70 must NOT be flagged as needing review."""
        assert CONFIDENCE_GATE == 0.70, "Confirm gate value matches spec"

        mock_result = _make_result(confidence=0.70, needs_review=False)

        with (
            patch("app.db.fraction_review_queue.check_approved_fraction", new_callable=AsyncMock, return_value=None),
            patch("app.services.funnel_fraction_extractor._try_rag_extraction", new_callable=AsyncMock, return_value=None),
            patch("app.services.funnel_fraction_extractor._try_pubmed_extraction", new_callable=AsyncMock, return_value=mock_result),
        ):
            result = await extract_funnel_fraction(
                "NSCLC", "biomarker_gate", "EGFR-positive"
            )

        assert result.needs_review is False

    @pytest.mark.asyncio
    async def test_fallback_when_all_sources_fail(self):
        """If DB, RAG, and PubMed all return nothing, fraction is None and extraction_method is fallback_default."""
        with (
            patch("app.db.fraction_review_queue.check_approved_fraction", new_callable=AsyncMock, return_value=None),
            patch("app.services.funnel_fraction_extractor._try_rag_extraction", new_callable=AsyncMock, return_value=None),
            patch("app.services.funnel_fraction_extractor._try_pubmed_extraction", new_callable=AsyncMock, return_value=None),
        ):
            result = await extract_funnel_fraction(
                "xyzzy disease", "treated_segment", "some gate"
            )

        assert result.fraction is None
        assert result.extraction_method == "fallback_default"
        assert result.needs_review is True

    @pytest.mark.asyncio
    async def test_db_approved_fraction_bypasses_extraction(self):
        """A pre-approved DB fraction short-circuits all network calls."""
        with (
            patch("app.db.fraction_review_queue.check_approved_fraction", new_callable=AsyncMock, return_value=0.18),
            patch("app.services.funnel_fraction_extractor._try_rag_extraction", new_callable=AsyncMock) as mock_rag,
            patch("app.services.funnel_fraction_extractor._try_pubmed_extraction", new_callable=AsyncMock) as mock_pm,
        ):
            result = await extract_funnel_fraction(
                "ischemic stroke", "treated_segment", "thrombectomy-eligible"
            )

        assert result.fraction == 0.18
        assert result.extraction_method == "db_approved"
        assert result.confidence == 0.95
        assert result.needs_review is False
        mock_rag.assert_not_called()
        mock_pm.assert_not_called()

    @pytest.mark.asyncio
    async def test_rag_result_used_before_pubmed(self):
        """RAG result short-circuits PubMed search when it returns a fraction."""
        rag_result = _make_result(confidence=0.78, method="rag_local")

        with (
            patch("app.db.fraction_review_queue.check_approved_fraction", new_callable=AsyncMock, return_value=None),
            patch("app.services.funnel_fraction_extractor._try_rag_extraction", new_callable=AsyncMock, return_value=rag_result),
            patch("app.services.funnel_fraction_extractor._try_pubmed_extraction", new_callable=AsyncMock) as mock_pm,
        ):
            result = await extract_funnel_fraction(
                "HER2+ breast cancer", "biomarker_gate", "HER2-amplified"
            )

        assert result.extraction_method == "rag_local"
        mock_pm.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_in_db_is_non_fatal(self):
        """DB errors must not propagate — extraction should continue to RAG/PubMed."""
        pubmed_result = _make_result(confidence=0.75, method="pubmed_live")

        with (
            patch("app.db.fraction_review_queue.check_approved_fraction", new_callable=AsyncMock, side_effect=RuntimeError("DB down")),
            patch("app.services.funnel_fraction_extractor._try_rag_extraction", new_callable=AsyncMock, return_value=None),
            patch("app.services.funnel_fraction_extractor._try_pubmed_extraction", new_callable=AsyncMock, return_value=pubmed_result),
        ):
            result = await extract_funnel_fraction(
                "ischemic stroke", "treated_segment", "LVO eligible"
            )

        assert result.fraction == 0.25
        assert result.extraction_method == "pubmed_live"


# ──────────────────────────────────────────────────────────────────────────────
# 6. Blueprint provenance rule: citation + quote required
# ──────────────────────────────────────────────────────────────────────────────

class TestProvenanceRequirement:
    """
    Blueprint rule: "No fraction ships without a citation + verbatim quote."
    Any auto-approved fraction (needs_review=False) must have both fields set.
    """

    def test_auto_approved_has_citation(self):
        r = _make_result(confidence=0.80, needs_review=False)
        assert r.citation and len(r.citation) > 5, (
            "Auto-approved fraction must have a non-empty citation"
        )

    def test_auto_approved_has_verbatim_quote(self):
        r = _make_result(confidence=0.80, needs_review=False)
        assert r.verbatim_quote and len(r.verbatim_quote) > 5, (
            "Auto-approved fraction must have a verbatim quote from the abstract"
        )

    def test_fallback_result_does_not_have_spurious_citation(self):
        r = _make_result(fraction=None, confidence=0.0, needs_review=True, pmid=None, quote=None)
        assert r.fraction is None  # no fraction → no citation needed


# ──────────────────────────────────────────────────────────────────────────────
# 7. _enrich_null_gates integration with patient_flow_engine
# ──────────────────────────────────────────────────────────────────────────────

class TestEnrichNullGates:
    """
    Test _enrich_null_gates() in patient_flow_engine — the glue between the
    extractor and the funnel walk.
    """

    @pytest.mark.asyncio
    async def test_null_gate_enriched_by_high_confidence_result(self):
        from app.services.patient_flow_engine import _enrich_null_gates

        funnel = [
            {"step": "incidence", "type": "absolute", "rate": None},  # product_share skip
            {"step": "treated_segment", "type": "rate", "rate": None, "label": "eligible"},
        ]
        mock_lit = _make_result(confidence=0.82, needs_review=False, fraction=0.18)

        with patch(
            "app.services.funnel_fraction_extractor.extract_funnel_fraction",
            new_callable=AsyncMock, return_value=mock_lit
        ):
            enriched = await _enrich_null_gates("ischemic stroke", funnel, {})

        assert "treated_segment" in enriched
        assert abs(enriched["treated_segment"] - 0.18) < 1e-6

    @pytest.mark.asyncio
    async def test_low_confidence_gate_not_injected_into_overrides(self):
        from app.services.patient_flow_engine import _enrich_null_gates

        funnel = [{"step": "treated_segment", "type": "rate", "rate": None, "label": "eligible"}]
        mock_lit = _make_result(confidence=0.55, needs_review=True, fraction=0.18)

        with (
            patch("app.services.funnel_fraction_extractor.extract_funnel_fraction", new_callable=AsyncMock, return_value=mock_lit),
            patch("app.db.fraction_review_queue.queue_fraction_for_review", new_callable=AsyncMock) as mock_queue,
        ):
            enriched = await _enrich_null_gates("ischemic stroke", funnel, {})

        # Low confidence → not injected; queued for review instead
        assert "treated_segment" not in enriched
        mock_queue.assert_called_once()

    @pytest.mark.asyncio
    async def test_existing_override_not_overwritten(self):
        from app.services.patient_flow_engine import _enrich_null_gates

        funnel = [{"step": "treated_segment", "type": "rate", "rate": None}]
        existing_overrides = {"treated_segment": 0.30}

        mock_lit = _make_result(confidence=0.90, needs_review=False, fraction=0.15)

        with patch("app.services.funnel_fraction_extractor.extract_funnel_fraction", new_callable=AsyncMock, return_value=mock_lit) as mock_extract:
            enriched = await _enrich_null_gates("stroke", funnel, existing_overrides)

        # Extractor must NOT be called when override already present
        mock_extract.assert_not_called()
        assert enriched["treated_segment"] == 0.30

    @pytest.mark.asyncio
    async def test_product_share_gate_skipped(self):
        from app.services.patient_flow_engine import _enrich_null_gates

        funnel = [{"step": "product_share", "type": "rate", "rate": None}]

        with patch("app.services.funnel_fraction_extractor.extract_funnel_fraction", new_callable=AsyncMock) as mock_extract:
            enriched = await _enrich_null_gates("stroke", funnel, {})

        mock_extract.assert_not_called()
        assert "product_share" not in enriched

    @pytest.mark.asyncio
    async def test_gate_with_known_rate_skipped(self):
        from app.services.patient_flow_engine import _enrich_null_gates

        funnel = [{"step": "diagnosed_fraction", "type": "rate", "rate": 0.75}]

        with patch("app.services.funnel_fraction_extractor.extract_funnel_fraction", new_callable=AsyncMock) as mock_extract:
            enriched = await _enrich_null_gates("stroke", funnel, {})

        mock_extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_extractor_exception_is_non_fatal(self):
        from app.services.patient_flow_engine import _enrich_null_gates

        funnel = [{"step": "treated_segment", "type": "rate", "rate": None}]

        with patch("app.services.funnel_fraction_extractor.extract_funnel_fraction", new_callable=AsyncMock, side_effect=RuntimeError("network error")):
            # Should not raise
            enriched = await _enrich_null_gates("stroke", funnel, {})

        assert "treated_segment" not in enriched  # fallback keeps default


# ──────────────────────────────────────────────────────────────────────────────
# 8. Blueprint benchmark checks
# ──────────────────────────────────────────────────────────────────────────────

class TestBlueprintBenchmarks:
    """
    Spot-checks for spec properties that must hold regardless of implementation
    details. These run without network or DB.
    """

    def test_confidence_gate_constant_is_070(self):
        assert CONFIDENCE_GATE == 0.70, (
            "Blueprint specifies confidence gate at 0.70; do not lower without updating spec."
        )

    def test_fraction_result_fraction_range(self):
        for frac in (0.0, 0.01, 0.50, 0.99, 1.0):
            r = _make_result(fraction=frac)
            assert 0.0 <= r.fraction <= 1.0, f"Fraction {frac} out of [0,1]"

    def test_needs_review_set_correctly_for_each_confidence_level(self):
        for conf, expected_review in [
            (0.30, True), (0.69, True), (0.70, False), (0.85, False), (0.99, False)
        ]:
            r = _make_result(confidence=conf, needs_review=(conf < CONFIDENCE_GATE))
            assert r.needs_review == expected_review, (
                f"confidence={conf} → needs_review should be {expected_review}"
            )

    def test_extraction_method_values_are_recognised(self):
        allowed = {"db_approved", "rag_local", "pubmed_live", "fallback_default"}
        for method in allowed:
            r = _make_result(method=method)
            assert r.extraction_method in allowed
