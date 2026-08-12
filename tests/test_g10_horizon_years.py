"""G.10 / B-08 — Single canonical horizon_years; verifier blocks export on contradiction.

Requirements:
- HORIZON_YEARS constant in buyer_model.py is the single source of truth
- market_sizing_derivation_service.py Step 5 uses HORIZON_YEARS (not hardcoded 5)
- _enforce_market_consistency formula uses HORIZON_YEARS (not "Year-1 capture")
- math_consistency_guard detects contradictory horizon mentions → MATH ERROR → export_blocked
"""
from __future__ import annotations

import pytest


# ── Constant exists and is used everywhere ────────────────────────────────────

class TestHorizonYearsConstant:
    def test_constant_exists_in_buyer_model(self):
        from app.services.buyer_model import HORIZON_YEARS
        assert isinstance(HORIZON_YEARS, int), "HORIZON_YEARS must be an int"
        assert HORIZON_YEARS > 0, "HORIZON_YEARS must be positive"

    def test_market_sizing_derivation_imports_constant(self):
        import app.services.market_sizing_derivation_service as m
        assert hasattr(m, "HORIZON_YEARS"), (
            "market_sizing_derivation_service must import HORIZON_YEARS from buyer_model"
        )

    def test_constants_agree(self):
        from app.services.buyer_model import HORIZON_YEARS as BM_HY
        from app.services.market_sizing_derivation_service import HORIZON_YEARS as DS_HY
        assert BM_HY == DS_HY, (
            f"buyer_model.HORIZON_YEARS={BM_HY} disagrees with "
            f"market_sizing_derivation_service.HORIZON_YEARS={DS_HY}"
        )


# ── Horizon contradiction checker (unit tests) ────────────────────────────────

class TestHorizonContradictionChecker:
    def _check(self, formula="", note=""):
        from app.services.math_consistency_guard import _check_horizon_contradiction
        return _check_horizon_contradiction({
            "formula": formula,
            "methodology_note": note,
        })

    def test_no_horizon_mention_no_flag(self):
        flags = self._check(
            formula="TAM = 5000 × $400 = $2M. SAM = 60%. SOM = 22%.",
            note="Bottom-up buyer model.",
        )
        assert flags == [], f"No horizon mention should produce no flags; got {flags}"

    def test_single_canonical_horizon_no_flag(self):
        from app.services.buyer_model import HORIZON_YEARS
        flags = self._check(
            formula=f"SOM = SAM × 22.5% ({HORIZON_YEARS}-yr penetration midpoint).",
            note=f"5-yr ramp based on research-tool SaaS benchmarks.",
        )
        assert flags == [], f"Single canonical horizon should not flag; got {flags}"

    def test_year1_alongside_5yr_is_flagged(self):
        """'Year-1 capture' in formula and '5-yr' in note → MATH ERROR."""
        flags = self._check(
            formula="SOM = SAM × 22.5% (Year-1 capture).",
            note="5-yr penetration based on adoption pathway.",
        )
        assert len(flags) == 1, f"Expected 1 flag, got {flags}"
        assert flags[0]["severity"] == "ERROR"
        assert flags[0]["category"] == "MATH"

    def test_contradictory_year_numbers_flagged(self):
        """Year-1 in formula, Year-5 in note."""
        flags = self._check(
            formula="SOM = SAM × 22.5% (Year-1 capture).",
            note="Year-5 SOM of $3M based on penetration ramp.",
        )
        assert len(flags) >= 1, f"Contradictory horizons must produce a flag; got {flags}"
        assert any(f["severity"] == "ERROR" for f in flags)

    def test_consistent_year1_no_flag(self):
        """Year-1 used consistently (all mentions agree) → no flag from this check."""
        flags = self._check(
            formula="SOM = SAM × 22.5% (Year-1 capture) = $2.8M.",
            note="Year-1 SOM of $2.8M. Market is nascent.",
        )
        # Both mention Year-1 consistently — no contradiction
        assert flags == [], f"Consistent Year-1 should not flag; got {flags}"

    def test_flag_is_blocking_math_error(self):
        """A horizon contradiction flag must be MATH/ERROR so _is_blocking_error returns True."""
        from app.services.validation_graph import _is_blocking_error
        flags = self._check(
            formula="SOM = SAM × 22.5% (Year-1 capture).",
            note="5-yr penetration based on adoption pathway.",
        )
        if flags:
            assert _is_blocking_error(flags[0]), (
                "Horizon contradiction must be a blocking error (MATH + ERROR)"
            )

    def test_empty_market_sizing_no_flag(self):
        from app.services.math_consistency_guard import _check_horizon_contradiction
        assert _check_horizon_contradiction({}) == []
        assert _check_horizon_contradiction({"formula": ""}) == []


# ── check_market_arithmetic includes horizon check ────────────────────────────

class TestCheckMarketArithmeticIncludesHorizon:
    def test_contradictory_horizon_in_full_check(self):
        """check_market_arithmetic must surface horizon contradictions."""
        from app.services.math_consistency_guard import check_market_arithmetic
        market_sizing = {
            "total_addressable_market_usd": 20_000_000.0,
            "serviceable_market_usd": 12_000_000.0,
            "formula": "SOM = SAM × 22.5% (Year-1 capture) = $2.7M.",
            "methodology_note": "5-yr penetration midpoint based on research-tool benchmarks.",
            "steps": [],
        }
        flags = check_market_arithmetic(market_sizing)
        horizon_flags = [f for f in flags if "horizon" in f.get("issue", "").lower()
                         or "B-08" in f.get("issue", "")
                         or "Year-1" in f.get("issue", "")]
        assert horizon_flags, (
            f"check_market_arithmetic must include horizon contradiction flag; got {flags}"
        )

    def test_canonical_horizon_no_extra_flag(self):
        """A correctly-formed formula should not produce a horizon flag."""
        from app.services.math_consistency_guard import check_market_arithmetic
        from app.services.buyer_model import HORIZON_YEARS
        market_sizing = {
            "total_addressable_market_usd": 20_000_000.0,
            "serviceable_market_usd": 12_000_000.0,
            "formula": (
                f"TAM = $20M. SAM = TAM × 60% = $12M. "
                f"SOM = SAM × 22.5% ({HORIZON_YEARS}-yr penetration midpoint) = $2.7M."
            ),
            "methodology_note": f"Bottom-up buyer model; {HORIZON_YEARS}-yr horizon.",
            "steps": [],
        }
        flags = check_market_arithmetic(market_sizing)
        horizon_flags = [f for f in flags if "horizon" in f.get("issue", "").lower()]
        assert horizon_flags == [], (
            f"Canonical formula should not trigger horizon flag; got {horizon_flags}"
        )


# ── _extract_horizon_years utility ───────────────────────────────────────────

class TestExtractHorizonYears:
    def _extract(self, text):
        from app.services.math_consistency_guard import _extract_horizon_years
        return _extract_horizon_years(text)

    def test_year1_captured(self):
        assert 1 in self._extract("Year-1 capture")

    def test_5yr_captured(self):
        assert 5 in self._extract("5-yr penetration midpoint")

    def test_5year_captured(self):
        assert 5 in self._extract("5-year SOM")

    def test_empty_string_empty_set(self):
        assert self._extract("") == set()

    def test_no_horizon_language_empty(self):
        assert self._extract("TAM = patients × price") == set()
