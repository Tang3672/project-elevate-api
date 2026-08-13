"""B-06 — Grant deadline table: replace past-date placeholders with real upcoming dates.

Spec reference: v7 B-06 — "next cycle deadline ~[date removed — update to future
milestone] at sbir.nih.gov. Third spec on grant deadlines. Build the deadline table."

Root cause: the R-04 past-date scrubber correctly identifies and removes past dates
from recommended_next_steps, replacing them with '[date removed — update to future
milestone]'. That placeholder is an internal marker — it must never reach the user.

Fix (B-06): After R-04, call _resolve_date_placeholders() which substitutes each
[date removed...] marker with the next upcoming NIH SBIR Phase I deadline
(April 5, August 5, or December 5, whichever is soonest after the report date).

All tests are pure-Python (no API key, no DB).
"""
from __future__ import annotations

from datetime import datetime

import pytest


# ── helpers ────────────────────────────────────────────────────────────────────

def _next_sbir(from_date: datetime) -> str:
    from app.services.alignment_service import _next_sbir_deadline
    return _next_sbir_deadline(from_date)


def _resolve(text: str, from_date: datetime) -> str:
    from app.services.alignment_service import _resolve_date_placeholders
    return _resolve_date_placeholders(text, from_date)


# ══════════════════════════════════════════════════════════════════════════════
# _next_sbir_deadline — returns a real future date
# ══════════════════════════════════════════════════════════════════════════════

class TestNextSbirDeadline:

    def test_returns_string(self):
        result = _next_sbir(datetime(2026, 8, 13))
        assert isinstance(result, str) and len(result) > 0

    def test_before_april_deadline_returns_april(self):
        # 2026-01-01 is before April 5 2026
        result = _next_sbir(datetime(2026, 1, 1))
        assert result == "April 2026"

    def test_after_april_but_before_august_returns_august(self):
        # 2026-05-01 is after April 5 but before August 5
        result = _next_sbir(datetime(2026, 5, 1))
        assert result == "August 2026"

    def test_after_august_but_before_december_returns_december(self):
        result = _next_sbir(datetime(2026, 9, 1))
        assert result == "December 2026"

    def test_after_all_this_year_returns_april_next_year(self):
        # 2026-12-10 is after December 5
        result = _next_sbir(datetime(2026, 12, 10))
        assert result == "April 2027"

    def test_on_deadline_day_itself_returns_next(self):
        # Exactly April 5 2026 — should return August 2026
        result = _next_sbir(datetime(2026, 4, 5))
        assert result == "August 2026"

    def test_result_is_always_in_future(self):
        now = datetime.utcnow()
        result = _next_sbir(now)
        # Parse the returned "Month YYYY" string
        next_dt = datetime.strptime(result, "%B %Y")
        assert next_dt > now, f"_next_sbir_deadline returned {result!r} which is not in the future"


# ══════════════════════════════════════════════════════════════════════════════
# _resolve_date_placeholders — replaces [date removed...] with a real date
# ══════════════════════════════════════════════════════════════════════════════

class TestResolveDatePlaceholders:

    _FROM = datetime(2026, 8, 13)   # between August 5 and December 5 → next is December 2026

    def test_placeholder_replaced(self):
        text = "Apply to NIH SBIR Phase I, next deadline [date removed — update to future milestone] at sbir.nih.gov."
        result = _resolve(text, self._FROM)
        assert "[date removed" not in result.lower(), f"Placeholder not removed: {result!r}"
        assert "December 2026" in result, f"Expected 'December 2026' in {result!r}"

    def test_short_placeholder_replaced(self):
        """[date removed] (without extra text) must also be replaced."""
        text = "Submit by [date removed] to the next cycle."
        result = _resolve(text, self._FROM)
        assert "[date removed" not in result.lower()

    def test_clean_text_unchanged(self):
        text = "Apply to NIH SBIR Phase I, next deadline December 2026."
        result = _resolve(text, self._FROM)
        assert result == text

    def test_multiple_placeholders_all_replaced(self):
        text = (
            "Submit by [date removed — update to future milestone]. "
            "Late applications by [date removed] are also accepted."
        )
        result = _resolve(text, self._FROM)
        assert "[date removed" not in result.lower(), f"Remaining placeholder in: {result!r}"

    def test_empty_string(self):
        assert _resolve("", self._FROM) == ""

    def test_replacement_is_future_date(self):
        text = "Apply by [date removed — update to future milestone]."
        result = _resolve(text, datetime.utcnow())
        assert "[date removed" not in result.lower()
        # Verify the replacement looks like a date
        import re
        months = r"January|February|March|April|May|June|July|August|September|October|November|December"
        assert re.search(fr"(?:{months}) \d{{4}}", result), f"No Month YYYY in: {result!r}"


# ══════════════════════════════════════════════════════════════════════════════
# Integration: _resolve_date_placeholders wired into alignment_service
# ══════════════════════════════════════════════════════════════════════════════

class TestB06Wiring:

    def test_resolve_function_exported(self):
        from app.services.alignment_service import _resolve_date_placeholders
        assert callable(_resolve_date_placeholders)

    def test_next_sbir_deadline_exported(self):
        from app.services.alignment_service import _next_sbir_deadline
        assert callable(_next_sbir_deadline)

    def test_banned_output_strings_includes_date_removed(self):
        from app.services.alignment_service import _BANNED_OUTPUT_STRINGS
        assert any("[date removed" in b for b in _BANNED_OUTPUT_STRINGS), (
            "_BANNED_OUTPUT_STRINGS must include '[date removed' so the output guard "
            "catches any placeholder that slipped through B-06 resolution."
        )

    def test_date_placeholder_re_matches_both_variants(self):
        from app.services.alignment_service import _DATE_PLACEHOLDER_RE
        assert _DATE_PLACEHOLDER_RE.search("[date removed — update to future milestone]")
        assert _DATE_PLACEHOLDER_RE.search("[date removed]")
        assert _DATE_PLACEHOLDER_RE.search("[date removed: specific deadline]")

    def test_has_banned_output_catches_date_removed(self):
        from app.services.alignment_service import _has_banned_output
        found = _has_banned_output("Apply by [date removed — update to future milestone].")
        assert found, "Output guard must flag [date removed...] as a banned string"

    def test_has_banned_output_clean_text_passes(self):
        from app.services.alignment_service import _has_banned_output
        found = _has_banned_output("Apply to NIH SBIR Phase I, next deadline December 2026.")
        assert not found, f"Clean text must not trigger output guard: {found}"

    def test_resolve_before_r04_guard_chain(self):
        """Verify R-04 → B-06 chain: past date → placeholder → real date."""
        # Simulate R-04 output (placeholder already in place)
        r04_output = "Next SBIR deadline: [date removed — update to future milestone] at sbir.nih.gov."
        from_date = datetime(2026, 8, 13)
        b06_output = _resolve(r04_output, from_date)
        # Placeholder is gone
        assert "[date removed" not in b06_output.lower()
        # A real date is present
        assert "December 2026" in b06_output


# ══════════════════════════════════════════════════════════════════════════════
# _next_recurring_deadline — generic helper
# ══════════════════════════════════════════════════════════════════════════════

class TestNextRecurringDeadline:

    def test_r01_pattern_february_before_first_cycle(self):
        from app.services.alignment_service import _next_recurring_deadline, _R01_MONTHS
        result = _next_recurring_deadline(_R01_MONTHS, datetime(2026, 1, 1))
        assert result == "February 2026"

    def test_r01_pattern_october_after_june(self):
        from app.services.alignment_service import _next_recurring_deadline, _R01_MONTHS
        result = _next_recurring_deadline(_R01_MONTHS, datetime(2026, 7, 1))
        assert result == "October 2026"

    def test_sbir_pattern_exported(self):
        from app.services.alignment_service import _SBIR_MONTHS, _R01_MONTHS
        assert 4 in _SBIR_MONTHS and 8 in _SBIR_MONTHS and 12 in _SBIR_MONTHS
        assert 2 in _R01_MONTHS and 6 in _R01_MONTHS and 10 in _R01_MONTHS
