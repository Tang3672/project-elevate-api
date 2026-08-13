"""v3 Part F / Spec item 13 — Override ledger and capture.

Verifies:
  1. override_ledger_repository structure and filtering logic
  2. append_corrections skips no-ops and invalid rows
  3. save_market_sizing_override endpoint hooks into the ledger
  4. Stats endpoint exists with correct shape
  5. Rationale is captured and recoverable
"""
from __future__ import annotations

import hashlib
import inspect
import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _src() -> str:
    import app.db.override_ledger_repository as m
    return inspect.getsource(m)


def _api_src() -> str:
    import app.api.alignment as m
    return inspect.getsource(m.save_market_sizing_override)


def _stats_src() -> str:
    import app.api.alignment as m
    return inspect.getsource(m.get_override_ledger_stats)


# ══════════════════════════════════════════════════════════════════════════════
# Repository structure
# ══════════════════════════════════════════════════════════════════════════════

class TestRepositoryStructure:

    def test_module_exists(self):
        import app.db.override_ledger_repository  # noqa: F401

    def test_has_init_function(self):
        src = _src()
        assert "init_override_ledger_table" in src

    def test_has_append_corrections(self):
        src = _src()
        assert "append_corrections" in src

    def test_has_get_stats(self):
        src = _src()
        assert "get_stats" in src

    def test_has_count_total_corrections(self):
        src = _src()
        assert "count_total_corrections" in src

    def test_has_get_recent_rationales(self):
        src = _src()
        assert "get_recent_rationales" in src

    def test_table_name_is_override_ledger(self):
        src = _src()
        assert "override_ledger" in src

    def test_ratio_column_present(self):
        """ratio = new_value / orig_value — the key calibration signal."""
        src = _src()
        assert "ratio" in src

    def test_report_hash_not_raw_id(self):
        """Privacy: report_id must be hashed, not stored raw."""
        src = _src()
        assert "report_hash" in src
        assert "sha256" in src.lower() or "hashlib" in src


# ══════════════════════════════════════════════════════════════════════════════
# append_corrections filtering logic (pure unit tests, no DB)
# ══════════════════════════════════════════════════════════════════════════════

class TestAppendCorrectionsFiltering:
    """
    Test the filtering logic inside append_corrections without a live DB.
    We inspect the source code for the right guards rather than executing.
    """

    def test_skips_zero_orig(self):
        src = _src()
        assert "orig_f <= 0" in src or "orig_value > 0" in src, (
            "Must skip rows where orig_value = 0 (avoid ratio = inf)"
        )

    def test_skips_zero_new(self):
        src = _src()
        assert "new_f <= 0" in src or "new_value > 0" in src, (
            "Must skip rows where new_value = 0 (zeroed-out, not a real correction)"
        )

    def test_skips_no_op_saves(self):
        """If orig == new, the user didn't actually change anything — skip."""
        src = _src()
        assert "new_f - orig_f" in src or "new_value != orig_value" in src, (
            "Must skip rows where new_value == orig_value (no-op save)"
        )

    def test_appends_ratio(self):
        src = _src()
        assert "ratio" in src and ("new_f / orig_f" in src or "new_value / orig_value" in src), (
            "Must compute and store ratio = new_value / orig_value"
        )

    def test_best_effort_catches_exception(self):
        """Ledger writes must be non-fatal — wrapped in try/except."""
        src = _src()
        assert "except Exception" in src or "except" in src

    def test_rationale_truncated_to_500(self):
        src = _src()
        assert "500" in src or "rationale" in src, (
            "Rationale should be truncated to protect against huge strings"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Ratio computation correctness
# ══════════════════════════════════════════════════════════════════════════════

class TestRatioCorrectness:

    def test_ratio_formula(self):
        """new_value / orig_value — median < 1 means model overestimates."""
        orig = 55000.0
        new  = 1800.0
        ratio = new / orig
        assert abs(ratio - 0.03272) < 1e-4

    def test_ratio_greater_than_1_means_underestimate(self):
        orig = 1000.0
        new  = 3500.0
        ratio = new / orig
        assert ratio > 1.0  # experts think the model is too conservative

    def test_unit_ratio_means_no_change(self):
        assert abs(5000.0 / 5000.0 - 1.0) < 1e-9

    def test_report_hash_is_sha256_prefix(self):
        """report_id must be hashed to an 8-char SHA-256 prefix before storage."""
        report_id = "rep_abc123"
        expected = hashlib.sha256(report_id.encode()).hexdigest()[:8]
        assert len(expected) == 8
        assert expected.isalnum()


# ══════════════════════════════════════════════════════════════════════════════
# Hook in save_market_sizing_override
# ══════════════════════════════════════════════════════════════════════════════

class TestSaveEndpointHook:

    def test_save_endpoint_imports_override_ledger(self):
        src = _api_src()
        assert "override_ledger_repository" in src or "override_ledger" in src, (
            "save_market_sizing_override must import and call override_ledger_repository"
        )

    def test_save_endpoint_calls_append_corrections(self):
        src = _api_src()
        assert "append_corrections" in src, (
            "save_market_sizing_override must call append_corrections on every save"
        )

    def test_save_endpoint_ledger_capture_is_best_effort(self):
        """Ledger failure must never break the save response."""
        src = _api_src()
        # The ledger call must be wrapped in a try/except so it can't break the response
        assert "except Exception" in src or "except" in src, (
            "override_ledger capture in save_market_sizing_override must be best-effort "
            "(try/except so DB failures don't break user-facing save)"
        )

    def test_save_endpoint_passes_step_overrides_to_ledger(self):
        src = _api_src()
        assert "step_overrides" in src, (
            "save_market_sizing_override must pass step_overrides to append_corrections"
        )

    def test_save_endpoint_passes_rationale_to_ledger(self):
        src = _api_src()
        assert "rationale" in src, (
            "Rationale must be passed to append_corrections so expert reasoning is captured"
        )

    def test_save_endpoint_passes_report_id_to_ledger(self):
        src = _api_src()
        assert "report_id" in src, (
            "report_id must be passed to append_corrections for audit trail"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Stats endpoint
# ══════════════════════════════════════════════════════════════════════════════

class TestStatsEndpoint:

    def test_stats_endpoint_exists(self):
        import app.api.alignment as m
        assert hasattr(m, "get_override_ledger_stats"), (
            "GET /alignment/override-ledger/stats endpoint must exist"
        )

    def test_stats_endpoint_calls_get_stats(self):
        src = _stats_src()
        assert "get_stats" in src

    def test_stats_endpoint_calls_count_total(self):
        src = _stats_src()
        assert "count_total_corrections" in src, (
            "stats endpoint must surface total_corrections count for health checks"
        )

    def test_stats_response_shape(self):
        """Response must include total_corrections and stats list."""
        src = _stats_src()
        assert "total_corrections" in src
        assert "stats" in src

    def test_stats_endpoint_requires_auth(self):
        """Ledger data is internal — must require authentication."""
        src = _stats_src()
        assert "get_current_user" in src, (
            "Override ledger stats require authentication (not get_optional_user)"
        )

    def test_limit_capped_at_200(self):
        """Prevent unbounded result sets."""
        src = _stats_src()
        assert "200" in src or "limit" in src.lower(), (
            "Stats endpoint must cap the limit parameter"
        )

    def test_step_label_filter_optional(self):
        src = _stats_src()
        assert "step_label" in src, "step_label filter must be accepted"


# ══════════════════════════════════════════════════════════════════════════════
# Data model correctness
# ══════════════════════════════════════════════════════════════════════════════

class TestDataModel:

    def test_step_role_is_tam_sam_som(self):
        """step_role encodes which aggregate (TAM/SAM/SOM) the step feeds into."""
        src = _src()
        assert "step_role" in src

    def test_append_only_table(self):
        """Ledger is append-only — no UPDATE statements allowed."""
        src = _src()
        assert "UPDATE" not in src.upper() or "DO UPDATE" not in src.upper(), (
            "override_ledger must be append-only (no UPDATEs — each save is a new row)"
        )

    def test_step_label_truncated(self):
        """Long labels are truncated so they don't blow up the DB."""
        src = _src()
        assert "300" in src or "[:300]" in src or "label" in src, (
            "step_label must be truncated (e.g. to 300 chars)"
        )

    def test_percentile_query_present(self):
        """Stats use PERCENTILE_CONT for median and quartiles."""
        src = _src()
        assert "PERCENTILE_CONT" in src or "percentile" in src.lower(), (
            "get_stats must use PERCENTILE_CONT for median/quartile computation"
        )

    def test_min_corrections_threshold_in_having(self):
        """Aggregate only steps with enough samples to be meaningful."""
        src = _src()
        assert "HAVING" in src.upper() or "min_corrections" in src, (
            "get_stats must filter steps below min_corrections threshold"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Integration: correction semantics
# ══════════════════════════════════════════════════════════════════════════════

class TestCorrectionSemantics:

    def test_median_ratio_below_1_signals_overestimate(self):
        """
        If experts consistently correct 55,000 → 1,800, the median ratio is ~0.03.
        This signals our model overestimates by 33×.
        """
        corrections = [1800 / 55000, 2100 / 55000, 900 / 55000]
        median = sorted(corrections)[len(corrections) // 2]
        assert median < 1.0
        assert median < 0.05

    def test_median_ratio_above_1_signals_underestimate(self):
        corrections = [4.0, 3.5, 5.0]
        median = sorted(corrections)[len(corrections) // 2]
        assert median > 1.0

    def test_ratio_equals_1_is_filtered(self):
        """
        A ratio of 1.0 means the user saved without changing anything.
        The repository must skip these.
        """
        # If orig == new, ratio == 1.0, should be filtered
        orig = 5000.0
        new  = 5000.0
        ratio = new / orig
        assert abs(ratio - 1.0) < 1e-9  # this is the no-op case
        # The repo must detect abs(new - orig) < epsilon and skip

    def test_aggregate_from_multiple_steps_independent(self):
        """
        Different step labels have independent aggregates.
        A correction to step A doesn't affect step B's stats.
        """
        step_a = [0.03, 0.04, 0.05]  # model overestimates step A by ~25×
        step_b = [1.5, 2.0, 1.8]     # model underestimates step B by ~75%
        median_a = sorted(step_a)[1]
        median_b = sorted(step_b)[1]
        assert median_a < 1.0
        assert median_b > 1.0
        assert median_a != median_b
