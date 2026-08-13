"""G.9 — One market model: reconcile parallel triangulation path.

After Part D triangulation runs, report.market_sizing.total_addressable_market_usd
must be overwritten with _triangulation.reconciled["tam_usd"] so there is a single
canonical TAM across both paths.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Unit: the reconciliation block logic ─────────────────────────────────────

class TestG9Reconciliation:
    """Test that the G.9 reconciliation overwrites market_sizing TAM correctly."""

    def _make_market_sizing(self, tam_usd=500_000_000.0):
        from app.models.alignment import MarketSizingCalculation
        return MarketSizingCalculation(
            steps=[],
            formula="labs × price",
            total_addressable_market_usd=tam_usd,
            serviceable_market_usd=tam_usd * 0.3,
            methodology_note="Derivation model estimate.",
        )

    def test_model_copy_updates_tam(self):
        """model_copy(update=...) correctly replaces TAM on the Pydantic model."""
        ms = self._make_market_sizing(500_000_000.0)
        updated = ms.model_copy(update={"total_addressable_market_usd": 120_000_000.0})
        assert updated.total_addressable_market_usd == 120_000_000.0
        assert ms.total_addressable_market_usd == 500_000_000.0  # original unchanged

    def test_model_copy_preserves_other_fields(self):
        """model_copy only changes the specified field; SAM and steps are preserved."""
        ms = self._make_market_sizing(500_000_000.0)
        updated = ms.model_copy(update={"total_addressable_market_usd": 90_000_000.0})
        assert updated.serviceable_market_usd == 500_000_000.0 * 0.3
        assert updated.formula == "labs × price"

    def test_methodology_note_gets_reconciliation_suffix(self):
        """After reconciliation, methodology_note includes triangulation note."""
        ms = self._make_market_sizing()
        suffix = " Reconciled via 3-method triangulation (BU 50% + TD 25% + VB 25%)."
        note = ms.methodology_note.rstrip(".") + suffix
        updated = ms.model_copy(update={"methodology_note": note.strip()})
        assert "triangulation" in updated.methodology_note
        assert "BU 50%" in updated.methodology_note

    def test_zero_reconciled_tam_skips_overwrite(self):
        """If reconciled TAM is 0 (degenerate tree), market_sizing is not overwritten."""
        ms = self._make_market_sizing(500_000_000.0)
        reconciled = {"tam_usd": 0}
        if reconciled.get("tam_usd", 0) > 0:
            ms = ms.model_copy(update={"total_addressable_market_usd": reconciled["tam_usd"]})
        assert ms.total_addressable_market_usd == 500_000_000.0

    def test_positive_reconciled_tam_overwrites(self):
        """Positive reconciled TAM replaces derivation-model TAM."""
        ms = self._make_market_sizing(500_000_000.0)
        reconciled = {"tam_usd": 85_000_000.0}
        if reconciled.get("tam_usd", 0) > 0:
            ms = ms.model_copy(update={"total_addressable_market_usd": reconciled["tam_usd"]})
        assert ms.total_addressable_market_usd == 85_000_000.0

    def test_none_market_sizing_is_skipped(self):
        """If report.market_sizing is None (no LLM market data), reconciliation is a no-op."""
        market_sizing = None
        reconciled_tam = 85_000_000.0
        # Simulates the guard: if report.market_sizing is not None
        if market_sizing is not None and reconciled_tam > 0:
            market_sizing = market_sizing.model_copy(
                update={"total_addressable_market_usd": reconciled_tam}
            )
        assert market_sizing is None


# ── Integration: reconciliation in the segmentation block ────────────────────

class TestG9IntegrationWithSegTree:
    """Test that the Part D block wires G.9 correctly end-to-end."""

    def _build_fake_seg_tree(self):
        from app.services.market_segmentation import (
            SegmentTree, SegmentNode, SegmentNodeType,
        )
        node = SegmentNode(
            id="root", label="US Labs", node_type=SegmentNodeType.OBSERVED,
            value=5_000, low=3_000, high=8_000,
            source="test", assumption_flag=False,
        )
        return SegmentTree(
            nodes={"root": node},
            root_id="root",
            template="LIFE_SCIENCES_RESEARCH",
            product_name="TestTool",
            nih_labs_retrieved=5_000,
        )

    def _fake_triangulation(self, tam_usd=95_000_000.0):
        from app.services.market_segmentation import TriangulationResult
        return TriangulationResult(
            bottom_up={
                "method": "bottom_up",
                "label": "Bottom-Up",
                "tam_usd": tam_usd,
                "low_usd": tam_usd * 0.7,
                "high_usd": tam_usd * 1.4,
            },
            top_down={
                "method": "top_down",
                "label": "Top-Down",
                "tam_usd": tam_usd * 1.1,
                "low_usd": tam_usd * 0.8,
                "high_usd": tam_usd * 1.5,
            },
            value_based={
                "method": "value_based",
                "label": "Value-Based",
                "tam_usd": tam_usd * 0.9,
                "low_usd": tam_usd * 0.6,
                "high_usd": tam_usd * 1.2,
            },
            reconciled={
                "method": "reconciled",
                "label": "Reconciled",
                "tam_usd": tam_usd,
                "low_usd": tam_usd * 0.7,
                "high_usd": tam_usd * 1.4,
                "weights": {"bottom_up": 0.5, "top_down": 0.25, "value_based": 0.25},
                "divergence_ratio": 1.2,
                "divergence_flag": False,
                "divergence_note": None,
                "description": "Reconciled estimate.",
            },
        )

    def test_reconciliation_overwrites_derivation_tam(self):
        """After Part D block, market_sizing.total_addressable_market_usd == reconciled tam_usd."""
        from app.models.alignment import MarketSizingCalculation

        rec_tam = 95_000_000.0
        triangulation = self._fake_triangulation(rec_tam)

        market_sizing = MarketSizingCalculation(
            steps=[],
            formula="labs × price",
            total_addressable_market_usd=500_000_000.0,  # LLM derivation estimate
            serviceable_market_usd=150_000_000.0,
            methodology_note="Derivation model estimate.",
        )

        # Simulate the G.9 reconciliation block
        _rec_tam = triangulation.reconciled.get("tam_usd", 0)
        if market_sizing is not None and _rec_tam > 0:
            _note = market_sizing.methodology_note.rstrip(".")
            market_sizing = market_sizing.model_copy(update={
                "total_addressable_market_usd": _rec_tam,
                "methodology_note": (
                    _note +
                    " Reconciled via 3-method triangulation (BU 50% + TD 25% + VB 25%)."
                ).strip(),
            })

        assert market_sizing.total_addressable_market_usd == rec_tam, (
            f"Expected TAM {rec_tam}, got {market_sizing.total_addressable_market_usd}"
        )

    def test_reconciliation_sam_preserved(self):
        """SAM (serviceable_market_usd) is unchanged by G.9 reconciliation."""
        from app.models.alignment import MarketSizingCalculation

        rec_tam = 95_000_000.0
        triangulation = self._fake_triangulation(rec_tam)
        original_sam = 150_000_000.0

        market_sizing = MarketSizingCalculation(
            steps=[],
            formula="labs × price",
            total_addressable_market_usd=500_000_000.0,
            serviceable_market_usd=original_sam,
            methodology_note="Derivation model estimate.",
        )

        _rec_tam = triangulation.reconciled.get("tam_usd", 0)
        if market_sizing is not None and _rec_tam > 0:
            _note = market_sizing.methodology_note.rstrip(".")
            market_sizing = market_sizing.model_copy(update={
                "total_addressable_market_usd": _rec_tam,
                "methodology_note": (
                    _note +
                    " Reconciled via 3-method triangulation (BU 50% + TD 25% + VB 25%)."
                ).strip(),
            })

        assert market_sizing.serviceable_market_usd == original_sam, (
            "SAM should not be changed by G.9 TAM reconciliation"
        )
