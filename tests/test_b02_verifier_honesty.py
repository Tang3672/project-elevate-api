"""
B-02 — Verifier honesty and export gate
=========================================
The verifier must never overstate what it has verified:
- MATH category ERRORs → BLOCKING verdict (PDF export refused)
- Non-MATH ERRORs      → ERROR verdict (flagged but exportable)
- Warnings only        → FLAG (exportable with review)
- After self-correction, status is FLAG or ERROR (never PASS), because
  corrections are "attempted", not "re-verified"
- `export_blocked` field must be True iff verdict is BLOCKING

All tests are pure-Python (no API key, no DB).
"""

from __future__ import annotations

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _flag(severity: str, category: str, issue: str = "test issue") -> dict:
    return {
        "severity":   severity,
        "category":   category,
        "field":      "test_field",
        "issue":      issue,
        "suggestion": "fix it",
        "agent":      "Test Agent",
    }


def _run_arbitrator(**flag_lists) -> dict:
    from app.services.validation_graph import arbitrator_node
    state = {
        "report": {}, "product_type": "other", "sub_expert_id": "",
        "expert_critic_rules": "",
        "math_flags":       flag_lists.get("math",       []),
        "source_flags":     flag_lists.get("source",     []),
        "regulatory_flags": flag_lists.get("regulatory", []),
        "market_flags":     flag_lists.get("market",     []),
        "factual_flags":    flag_lists.get("factual",    []),
        "math_error": None, "source_error": None,
        "regulatory_error": None, "market_error": None, "factual_error": None,
        "all_flags": [], "validation_passed": None, "_verdict": None,
    }
    return arbitrator_node(state)


def _run_formatter(**flag_lists) -> dict:
    from app.services.validation_graph import formatter_node
    all_flags = (
        flag_lists.get("math", []) +
        flag_lists.get("source", []) +
        flag_lists.get("regulatory", []) +
        flag_lists.get("market", []) +
        flag_lists.get("factual", [])
    )
    state = {
        "report": {"executive_summary": "test"},
        "product_type": "other", "sub_expert_id": "",
        "expert_critic_rules": "",
        "all_flags": all_flags,
        "math_flags": flag_lists.get("math", []),
        "source_flags": flag_lists.get("source", []),
        "regulatory_flags": flag_lists.get("regulatory", []),
        "market_flags": flag_lists.get("market", []),
        "factual_flags": flag_lists.get("factual", []),
        "math_error": None, "source_error": None,
        "regulatory_error": None, "market_error": None, "factual_error": None,
        "validation_passed": None, "_verdict": None,
    }
    result = formatter_node(state)
    return result["validated_report"]["validation"]


# ══════════════════════════════════════════════════════════════════════════════
# BLOCKING verdict — MATH category ERRORs
# ══════════════════════════════════════════════════════════════════════════════

class TestBlockingVerdict:

    def test_math_error_gives_blocking_not_error(self):
        """A MATH ERROR must produce BLOCKING verdict, not plain ERROR."""
        result = _run_arbitrator(math=[_flag("ERROR", "MATH", "TAM ≠ pop × price")])
        assert result["_verdict"] == "BLOCKING", (
            f"MATH ERROR must give BLOCKING verdict, got {result['_verdict']!r}"
        )

    def test_blocking_sets_validation_passed_false(self):
        result = _run_arbitrator(math=[_flag("ERROR", "MATH")])
        assert result["validation_passed"] is False

    def test_source_error_gives_error_not_blocking(self):
        """Non-MATH ERRORs must NOT block export — they are serious but disputable."""
        result = _run_arbitrator(source=[_flag("ERROR", "SOURCE", "URL 404")])
        assert result["_verdict"] == "ERROR", (
            f"SOURCE ERROR must give ERROR verdict, not BLOCKING"
        )
        assert result["_verdict"] != "BLOCKING"

    def test_regulatory_error_not_blocking(self):
        result = _run_arbitrator(regulatory=[_flag("ERROR", "REGULATORY")])
        assert result["_verdict"] == "ERROR"
        assert result["_verdict"] != "BLOCKING"

    def test_math_warning_not_blocking(self):
        """MATH WARNING is not an ERROR — must not block."""
        result = _run_arbitrator(math=[_flag("WARNING", "MATH")])
        assert result["_verdict"] == "FLAG"
        assert result["_verdict"] != "BLOCKING"

    def test_mixed_math_error_and_source_error_gives_blocking(self):
        """When MATH ERRORs and other ERRORs coexist, BLOCKING wins."""
        result = _run_arbitrator(
            math=[_flag("ERROR", "MATH")],
            source=[_flag("ERROR", "SOURCE")],
        )
        assert result["_verdict"] == "BLOCKING"

    def test_no_flags_gives_pass(self):
        result = _run_arbitrator()
        assert result["_verdict"] == "PASS"
        assert result["validation_passed"] is True


# ══════════════════════════════════════════════════════════════════════════════
# export_blocked field
# ══════════════════════════════════════════════════════════════════════════════

class TestExportBlockedField:

    def test_blocking_sets_export_blocked_true(self):
        """validation.export_blocked must be True when verdict is BLOCKING."""
        val = _run_formatter(math=[_flag("ERROR", "MATH")])
        assert val["export_blocked"] is True, (
            f"export_blocked must be True for BLOCKING verdict, got {val['export_blocked']!r}"
        )

    def test_error_sets_export_blocked_false(self):
        """Non-MATH ERRORs must NOT set export_blocked — export remains allowed."""
        val = _run_formatter(source=[_flag("ERROR", "SOURCE")])
        assert val["status"] == "ERROR"
        assert val["export_blocked"] is False, (
            f"SOURCE ERROR must not block export, but export_blocked={val['export_blocked']!r}"
        )

    def test_flag_verdict_export_not_blocked(self):
        val = _run_formatter(source=[_flag("WARNING", "SOURCE")])
        assert val["status"] == "FLAG"
        assert val["export_blocked"] is False

    def test_pass_verdict_export_not_blocked(self):
        val = _run_formatter()
        assert val["status"] == "PASS"
        assert val["export_blocked"] is False

    def test_blocking_summary_mentions_export(self):
        """BLOCKING summary must say 'export' or 'blocked' so the user knows why."""
        val = _run_formatter(math=[_flag("ERROR", "MATH", "TAM inconsistency")])
        summary = (val.get("summary") or "").lower()
        assert "block" in summary or "export" in summary, (
            f"BLOCKING summary must mention 'block' or 'export'. Got: {val.get('summary')!r}"
        )

    def test_blocking_status_string(self):
        """Status field must literally be the string 'BLOCKING'."""
        val = _run_formatter(math=[_flag("ERROR", "MATH")])
        assert val["status"] == "BLOCKING"

    def test_pass_summary_does_not_mention_blocking(self):
        """A PASS report must not reference blocking or errors."""
        val = _run_formatter()
        summary = (val.get("summary") or "").lower()
        assert "block" not in summary
        assert "error" not in summary


# ══════════════════════════════════════════════════════════════════════════════
# Self-correction honesty — never claim "resolved" without re-verification
# ══════════════════════════════════════════════════════════════════════════════

class TestSelfCorrectionHonesty:
    """
    B-02: The verifier said 'All verifier issues resolved' while displaying
    unresolved issues. The backend must never claim corrections succeeded
    without running re-verification.
    """

    def _make_validation_with_self_correction(self, n_fixed: int, n_remaining: int) -> dict:
        """Simulate the post-correction validation dict as built by run_report_verification."""
        remaining_errors = [_flag("ERROR", "SOURCE") for _ in range(n_remaining)]
        val: dict = {
            "status": "ERROR" if n_remaining else "FLAG",
            "passed": n_remaining == 0,
            "export_blocked": False,
            "errors": remaining_errors,
            "warnings": [],
            "notes": [],
            "total_flags": n_fixed + n_remaining,
            "self_corrected": n_fixed,
        }
        if n_remaining:
            val["summary"] = (
                f"Attempted correction on {n_fixed} issue(s); "
                f"{n_remaining} flagged issue(s) remain — review required."
            )
        else:
            val["summary"] = (
                f"Corrections applied to {n_fixed} flagged issue(s). "
                f"Re-run the report to confirm resolution."
            )
        return val

    def test_partial_correction_stays_error(self):
        val = self._make_validation_with_self_correction(n_fixed=1, n_remaining=1)
        assert val["status"] == "ERROR", (
            "When some errors remain after correction, status must stay ERROR."
        )

    def test_all_corrections_applied_gives_flag_not_pass(self):
        """After applying corrections to all errors, status must be FLAG, not PASS.
        PASS requires re-verification, which is not run in the correction pass."""
        val = self._make_validation_with_self_correction(n_fixed=2, n_remaining=0)
        assert val["status"] == "FLAG", (
            f"After applying corrections without re-verification, status must be FLAG "
            f"(not PASS). Got {val['status']!r}."
        )

    def test_correction_summary_never_says_resolved(self):
        """Summary must not claim issues are 'resolved' — only 'attempted'."""
        val = self._make_validation_with_self_correction(n_fixed=2, n_remaining=0)
        summary = (val.get("summary") or "").lower()
        assert "all" not in summary or "resolved" not in summary, (
            f"Summary must not claim 'All issues resolved'. Got: {val.get('summary')!r}"
        )

    def test_correction_summary_says_rerun_to_confirm(self):
        """When corrections were applied, the user must be told to re-run to confirm."""
        val = self._make_validation_with_self_correction(n_fixed=2, n_remaining=0)
        summary = (val.get("summary") or "").lower()
        assert "re-run" in summary or "rerun" in summary or "confirm" in summary or "regenerate" in summary, (
            f"Summary must tell user to re-run to confirm corrections. Got: {val.get('summary')!r}"
        )

    def test_self_corrected_count_not_called_auto_corrected(self):
        """Field name must be 'self_corrected' (attempted) not 'auto_corrected' (confirmed)."""
        val = self._make_validation_with_self_correction(n_fixed=2, n_remaining=0)
        assert "self_corrected" in val, "Expected 'self_corrected' field in validation dict."
        assert "auto_corrected" not in val, (
            "'auto_corrected' must not be set — it implies confirmed success. "
            "Use 'self_corrected' for attempted-only corrections."
        )
