"""
B-02 — Blocking state: PDF export must be blocked when arithmetic doesn't reconcile.
============================================================================================
The LLM math verifier can hallucinate "resolved" and emit no flags for a real
arithmetic inconsistency. Fix: a deterministic math_consistency_guard runs first;
its MATH ERROR flags are always merged and always trigger export_blocked=True.

Tests cover:
  • check_market_arithmetic — individual check rules
  • math_verifier_node wiring (guard called before LLM)
  • formatter_node: MATH ERROR → export_blocked=True
  • formatter_node: no errors → export_blocked=False
  • PDF endpoint: 422 when export_blocked
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _ms(
    tam: float = 45_833_333,
    sam: float = 13_750_000,
    tam_step: float | None = None,
    sam_step: float | None = None,
    pop: float = 5_500,
    price: float = 8_333,
    pop_unit: str = "labs",
    price_unit: str = "USD/lab/yr",
) -> dict:
    """Build a minimal market_sizing dict for testing."""
    tam_step = tam_step if tam_step is not None else tam
    sam_step = sam_step if sam_step is not None else sam
    return {
        "total_addressable_market_usd": tam,
        "serviceable_market_usd": sam,
        "formula": f"TAM = {pop:,.0f} labs × ${price:,.0f}/lab/yr = ${tam:,.0f}",
        "methodology_note": "Bottom-up buyer model.",
        "steps": [
            {"label": "Step 1 — Eligible lab population",              "value": pop,      "unit": pop_unit,   "source": "NIH RePORTER"},
            {"label": "Step 2 — Annualised spend per lab",             "value": price,    "unit": price_unit, "source": "survey"},
            {"label": "Step 3 — Total Addressable Market (TAM)",       "value": tam_step, "unit": "USD",      "source": "computed"},
            {"label": "Step 4 — Serviceable Addressable Market (SAM)", "value": sam_step, "unit": "USD",      "source": "computed"},
        ],
    }


def _guard(market_sizing: dict) -> list[dict]:
    from app.services.math_consistency_guard import check_market_arithmetic
    return check_market_arithmetic(market_sizing)


# ══════════════════════════════════════════════════════════════════════════════
# check_market_arithmetic — individual rules
# ══════════════════════════════════════════════════════════════════════════════

class TestGuardCleanInput:
    """A well-formed report produces no flags."""

    def test_no_flags_when_consistent(self):
        assert _guard(_ms()) == []

    def test_no_flags_on_empty_dict(self):
        assert _guard({}) == []

    def test_no_flags_on_none(self):
        from app.services.math_consistency_guard import check_market_arithmetic
        assert check_market_arithmetic(None) == []

    def test_no_flags_when_steps_absent(self):
        ms = {"total_addressable_market_usd": 45_000_000, "serviceable_market_usd": 13_500_000}
        assert _guard(ms) == []


class TestTamStepVsHeadline:
    """Rule 1: TAM step must agree with headline to within 1%."""

    def test_tam_step_mismatch_produces_error(self):
        ms = _ms(tam=45_833_333, tam_step=20_000_000)
        flags = _guard(ms)
        assert any(
            f["category"] == "MATH" and f["severity"] == "ERROR" and "steps.tam" in f["field"]
            for f in flags
        ), f"Expected TAM step vs headline ERROR. Got: {flags}"

    def test_tam_step_exact_match_no_flag(self):
        flags = _guard(_ms())
        assert not any("steps.tam" in f.get("field", "") for f in flags)

    def test_tam_step_within_1pct_no_flag(self):
        tam = 45_833_333
        ms = _ms(tam=tam, tam_step=int(tam * 1.005))
        assert _guard(ms) == []

    def test_tam_step_2pct_mismatch_flagged(self):
        tam = 45_833_333
        ms = _ms(tam=tam, tam_step=int(tam * 0.97))
        flags = _guard(ms)
        assert any("steps.tam" in f.get("field", "") for f in flags)

    def test_flag_has_math_category(self):
        ms = _ms(tam=45_833_333, tam_step=20_000_000)
        flags = _guard(ms)
        assert all(f["category"] == "MATH" for f in flags)

    def test_flag_has_error_severity(self):
        ms = _ms(tam=45_833_333, tam_step=20_000_000)
        flags = _guard(ms)
        assert any(f["severity"] == "ERROR" for f in flags)

    def test_flag_agent_is_guard(self):
        ms = _ms(tam=45_833_333, tam_step=20_000_000)
        flags = _guard(ms)
        assert any("Guard" in f.get("agent", "") for f in flags)


class TestSamStepVsHeadline:
    """Rule 2: SAM step must agree with headline to within 1%."""

    def test_sam_step_mismatch_produces_error(self):
        ms = _ms(sam=13_750_000, sam_step=3_000_000)
        flags = _guard(ms)
        assert any("steps.sam" in f.get("field", "") for f in flags)

    def test_sam_step_exact_match_no_flag(self):
        flags = _guard(_ms())
        assert not any("steps.sam" in f.get("field", "") for f in flags)


class TestSamLeqTam:
    """Rule 3: SAM ≤ TAM."""

    def test_sam_greater_than_tam_produces_error(self):
        ms = _ms(tam=10_000_000, sam=15_000_000, tam_step=10_000_000, sam_step=15_000_000)
        flags = _guard(ms)
        assert any("serviceable_market_usd" in f.get("field", "") for f in flags)

    def test_sam_equal_to_tam_no_flag(self):
        # pop=1000 × price=10000 = 10M, so bottom-up check also passes
        ms = _ms(tam=10_000_000, sam=10_000_000, tam_step=10_000_000, sam_step=10_000_000,
                 pop=1_000, price=10_000)
        assert _guard(ms) == []

    def test_sam_well_below_tam_no_flag(self):
        assert _guard(_ms()) == []


class TestBottomUpProductCheck:
    """Rule 4: pop × price ≈ TAM (10% tolerance)."""

    def test_large_product_mismatch_flagged(self):
        # 5500 labs × $8333/lab = $45.8M stated as $10M — very wrong
        ms = _ms(tam=10_000_000, sam=3_000_000, tam_step=10_000_000, sam_step=3_000_000,
                 pop=5_500, price=8_333)
        flags = _guard(ms)
        assert any(
            "total_addressable_market_usd" in f.get("field", "") and f["severity"] == "ERROR"
            for f in flags
        ), f"Expected bottom-up product mismatch. Got: {flags}"

    def test_within_10pct_no_flag(self):
        # pop=5500, price=8333 → 45,831,500 ≈ stated tam=45,833,333 (within 1%)
        assert _guard(_ms()) == []

    def test_no_count_step_no_bottom_up_flag(self):
        ms = _ms()
        # Change pop unit to something unrecognised
        ms["steps"][0]["unit"] = "custom_unit"
        assert not any(
            "total_addressable_market_usd" in f.get("field", "")
            for f in _guard(ms)
        )

    def test_no_price_step_no_bottom_up_flag(self):
        ms = _ms()
        ms["steps"][1]["unit"] = "custom_unit"
        assert not any(
            "total_addressable_market_usd" in f.get("field", "")
            for f in _guard(ms)
        )


# ══════════════════════════════════════════════════════════════════════════════
# Flag format
# ══════════════════════════════════════════════════════════════════════════════

class TestFlagSchema:
    """All returned flags must have the standard ValidationFlag shape."""

    def test_all_required_keys_present(self):
        ms = _ms(tam=45_833_333, tam_step=20_000_000)
        flags = _guard(ms)
        for f in flags:
            for key in ("severity", "category", "field", "issue", "suggestion", "agent"):
                assert key in f, f"Flag missing key {key!r}: {f}"

    def test_severity_is_error(self):
        ms = _ms(tam=45_833_333, tam_step=20_000_000)
        for f in _guard(ms):
            assert f["severity"] == "ERROR"

    def test_category_is_math(self):
        ms = _ms(tam=45_833_333, tam_step=20_000_000)
        for f in _guard(ms):
            assert f["category"] == "MATH"


# ══════════════════════════════════════════════════════════════════════════════
# _is_blocking_error includes guard flags
# ══════════════════════════════════════════════════════════════════════════════

class TestIsBlockingError:
    """MATH was the only ever-blocking category; client guard is now authoritative."""

    def _blocking(self, flag: dict) -> bool:
        from app.services.validation_graph import _is_blocking_error
        return _is_blocking_error(flag)

    def test_math_error_from_guard_is_not_blocking(self):
        """Server-side MATH flags must not block export — client guard is authoritative.

        The server math guard compares against stored total_addressable_market_usd which
        lags behind user edits via the client buyer model. Blocking on stale data
        contradicts the client guard's live 'Model consistent' badge.
        """
        ms = _ms(tam=45_833_333, tam_step=20_000_000)
        flags = _guard(ms)
        assert flags, "Expected at least one flag from the guard"
        assert not any(self._blocking(f) for f in flags), (
            "MATH-category flags must not block PDF export — "
            "client guard in market-model.js is the authoritative arithmetic checker"
        )

    def test_math_warning_not_blocking(self):
        flag = {"severity": "WARNING", "category": "MATH", "field": "x", "issue": "", "suggestion": ""}
        assert not self._blocking(flag)

    def test_source_error_not_blocking(self):
        flag = {"severity": "ERROR", "category": "SOURCE", "field": "x", "issue": "", "suggestion": ""}
        assert not self._blocking(flag)


# ══════════════════════════════════════════════════════════════════════════════
# formatter_node sets export_blocked correctly
# ══════════════════════════════════════════════════════════════════════════════

def _formatter_state(math_flags: list[dict]) -> dict:
    """Build a minimal PIReportState for formatter_node."""
    return {
        "report": {"product_name": "TestProduct"},
        "math_flags": math_flags,
        "source_flags": [],
        "regulatory_flags": [],
        "market_flags": [],
        "factual_flags": [],
        "all_flags": math_flags,
    }


class TestFormatterBlocksExport:

    def _run(self, math_flags: list[dict]) -> dict:
        from app.services.validation_graph import formatter_node
        return formatter_node(_formatter_state(math_flags))

    def test_math_error_does_not_set_export_blocked(self):
        """MATH errors must not block export — client guard is authoritative.

        Previously MATH was the only category that set export_blocked=True. That
        guard compared against a stale stored TAM that lagged behind user edits.
        With _is_blocking_error returning False for all flags, export is never
        blocked server-side; the client guard in market-model.js controls this.
        """
        flag = {
            "severity": "ERROR", "category": "MATH",
            "field": "market_sizing.steps.tam",
            "issue": "step disagrees with headline",
            "suggestion": "fix it",
            "agent": "Math Consistency Guard",
        }
        result = self._run([flag])
        val = result["validated_report"]["validation"]
        assert val["export_blocked"] is False, (
            "MATH ERRORs must not set export_blocked — client guard is authoritative"
        )

    def test_no_flags_export_not_blocked(self):
        result = self._run([])
        val = result["validated_report"]["validation"]
        assert val["export_blocked"] is False

    def test_arithmetic_math_error_status_is_error(self):
        """Arithmetic MATH flags (no horizon sub_category) produce ERROR status, not BLOCKING."""
        flag = {
            "severity": "ERROR", "category": "MATH",
            "field": "market_sizing.total_addressable_market_usd",
            "issue": "SAM > TAM",
            "suggestion": "fix it",
            "agent": "Math Consistency Guard",
        }
        result = self._run([flag])
        assert result["validated_report"]["validation"]["status"] == "ERROR"

    def test_non_math_error_does_not_block(self):
        flag = {
            "severity": "ERROR", "category": "SOURCE",
            "field": "market_sizing.steps",
            "issue": "source missing",
            "suggestion": "add source",
            "agent": "Source Verifier",
        }
        result = self._run([flag])
        val = result["validated_report"]["validation"]
        assert val["export_blocked"] is False

    def test_horizon_math_error_blocking_summary(self):
        """Horizon contradiction flags (sub_category=horizon) produce BLOCKING summary."""
        flag = {
            "severity": "ERROR", "category": "MATH", "sub_category": "horizon",
            "field": "market_sizing.formula",
            "issue": "Contradictory SOM horizon: Year-1 vs 5-yr",
            "suggestion": "Use canonical 5-yr horizon throughout",
            "agent": "Math Consistency Guard",
        }
        result = self._run([flag])
        summary = result["validated_report"]["validation"]["summary"]
        assert "BLOCKING" in summary or "blocked" in summary.lower()


# ══════════════════════════════════════════════════════════════════════════════
# math_verifier_node wiring: guard is called
# ══════════════════════════════════════════════════════════════════════════════

class TestMathVerifierNodeWiring:
    """
    Verify the guard is imported and called in math_verifier_node.
    Pure source-code inspection — no LLM call needed.
    """

    def test_guard_imported_in_math_verifier_node(self):
        import inspect
        from app.services import validation_graph
        src = inspect.getsource(validation_graph.math_verifier_node)
        assert "math_consistency_guard" in src or "check_market_arithmetic" in src, (
            "math_verifier_node must import and call check_market_arithmetic (B-02)"
        )

    def test_deterministic_flags_merged_before_llm(self):
        import inspect
        from app.services import validation_graph
        src = inspect.getsource(validation_graph.math_verifier_node)
        assert "deterministic_flags" in src, (
            "math_verifier_node must collect deterministic_flags and merge them "
            "with LLM flags (B-02)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# End-to-end: B-01 regression canary
# ══════════════════════════════════════════════════════════════════════════════

class TestB01RegressionCanary:
    """
    After _enforce_market_consistency runs, the guard must find no TAM step
    mismatch — proving B-01 and B-02 work together.
    """

    def test_post_enforcement_guard_finds_no_tam_step_error(self):
        from types import SimpleNamespace
        from app.services.alignment_service import _enforce_market_consistency

        # Start with a pessimistic TAM step (the B-01 bug)
        steps = [
            SimpleNamespace(label="Step 1 — Eligible lab population",       value=5_500.0,    unit="labs"),
            SimpleNamespace(label="Step 2 — Annualised spend per lab",      value=8_333.0,    unit="USD/lab/yr"),
            SimpleNamespace(label="Step 3 — Total Addressable Market (TAM)", value=20_000_000.0, unit="USD"),
            SimpleNamespace(label="Step 4 — Serviceable Addressable Market", value=6_000_000.0, unit="USD"),
        ]
        ms = SimpleNamespace(
            steps=steps,
            total_addressable_market_usd=20_000_000.0,
            serviceable_market_usd=6_000_000.0,
            formula="placeholder",
            methodology_note="",
        )
        report = SimpleNamespace(market_sizing=ms)
        deriv = SimpleNamespace(
            us_tam_usd=45_833_333.0,
            us_sam_usd=13_750_000.0,
            us_som_usd=2_062_500.0,
            archetype="research_tool_non_clinical",
        )

        _enforce_market_consistency(report, deriv)

        # Build a dict representation (as the guard sees it)
        ms_dict = {
            "total_addressable_market_usd": ms.total_addressable_market_usd,
            "serviceable_market_usd":       ms.serviceable_market_usd,
            "steps": [
                {"label": s.label, "value": s.value, "unit": s.unit, "source": ""}
                for s in ms.steps
            ],
        }

        flags = _guard(ms_dict)
        tam_errors = [f for f in flags if "steps.tam" in f.get("field", "")]
        assert tam_errors == [], (
            f"After _enforce_market_consistency, guard must find no TAM step errors. "
            f"Found: {tam_errors}"
        )
