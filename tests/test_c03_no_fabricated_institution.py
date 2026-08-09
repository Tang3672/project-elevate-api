"""
C-03 — Fabricated institution guard.

Spec: "institution, like person, is an entity type. It comes from intake
or retrieval, or the item renders generically ('your institution's TTO').
Never generated."

All tests are pure-Python (no API key, no DB).
The scrubber is tested directly against the institution_scrubber module.
"""

from __future__ import annotations

import pytest

from app.services.institution_scrubber import (
    _GENERIC,
    scrub_institution_refs,
    scrub_institution_fields,
)


# ── 1. Core scrubber: single string ──────────────────────────────────────────

class TestScrubInstitutionRefs:
    """scrub_institution_refs(text, intake_lower) → (cleaned, count)"""

    def test_replaces_mit_tto_when_not_in_intake(self):
        text = "Submit IP disclosure to MIT TTO within 30 days."
        cleaned, n = scrub_institution_refs(text, intake_lower="")
        assert "MIT TTO" not in cleaned
        assert _GENERIC in cleaned
        assert n == 1

    def test_replaces_stanford_otl_when_not_in_intake(self):
        text = "Contact Stanford OTL to negotiate licensing terms."
        cleaned, n = scrub_institution_refs(text, intake_lower="")
        assert "Stanford OTL" not in cleaned
        assert _GENERIC in cleaned
        assert n == 1

    def test_replaces_harvard_tto_when_not_in_intake(self):
        text = "File a provisional patent through Harvard TTO."
        cleaned, n = scrub_institution_refs(text, intake_lower="")
        assert "Harvard TTO" not in cleaned
        assert _GENERIC in cleaned
        assert n == 1

    def test_replaces_long_form_office_of_technology(self):
        text = "Approach the Johns Hopkins Office of Technology Licensing."
        cleaned, n = scrub_institution_refs(text, intake_lower="")
        assert "Johns Hopkins" not in cleaned or _GENERIC in cleaned
        assert n >= 1

    def test_replaces_technology_transfer_office(self):
        text = "Schedule a meeting with Duke Technology Transfer Office."
        cleaned, n = scrub_institution_refs(text, intake_lower="")
        assert _GENERIC in cleaned
        assert n == 1

    def test_keeps_institution_when_present_in_idea(self):
        """If the user's idea mentions MIT, 'MIT TTO' is grounded — keep it."""
        idea = "This platform is being developed at MIT for neuroscience research."
        text = "File a provisional patent through MIT TTO."
        cleaned, n = scrub_institution_refs(text, intake_lower=idea.lower())
        assert "MIT TTO" in cleaned
        assert n == 0

    def test_keeps_institution_when_provided_as_intake_param(self):
        """institution='Stanford' from intake makes 'Stanford OTL' grounded."""
        intake = "stanford"  # institution parameter lowercased
        text = "Contact Stanford OTL to discuss licensing."
        cleaned, n = scrub_institution_refs(text, intake_lower=intake)
        assert "Stanford OTL" in cleaned
        assert n == 0

    def test_no_replacement_when_no_tto_pattern(self):
        """A plain university name without a TTO suffix must not be touched."""
        text = "Explore partnerships with academic labs at Stanford and MIT."
        cleaned, n = scrub_institution_refs(text, intake_lower="")
        assert cleaned == text
        assert n == 0

    def test_generic_form_replaces_correctly(self):
        text = "Submit through MIT TTO today."
        cleaned, _ = scrub_institution_refs(text, intake_lower="")
        assert cleaned == f"Submit through {_GENERIC} today."

    def test_no_replacement_already_generic(self):
        """Already-generic text must pass through unchanged."""
        text = f"Submit through {_GENERIC}."
        cleaned, n = scrub_institution_refs(text, intake_lower="")
        assert cleaned == text
        assert n == 0

    def test_multiple_replacements_in_one_string(self):
        text = "Contact MIT TTO then follow up with Stanford OTL."
        cleaned, n = scrub_institution_refs(text, intake_lower="")
        assert n == 2
        assert "MIT TTO" not in cleaned
        assert "Stanford OTL" not in cleaned

    def test_case_sensitivity_institution_name(self):
        """All-caps abbreviations like UCSF must be caught."""
        text = "File disclosure with UCSF TTO."
        cleaned, n = scrub_institution_refs(text, intake_lower="")
        assert n == 1
        assert _GENERIC in cleaned


# ── 2. Multi-field scrubber ───────────────────────────────────────────────────

class TestScrubInstitutionFields:
    """scrub_institution_fields(fields, intake_lower) → (cleaned_dict, count)"""

    def test_scrubs_list_of_strings(self):
        fields = {
            "recommended_next_steps": [
                "Apply to NIAID SBIR Phase I by next deadline.",
                "Submit IP disclosure to MIT TTO within 30 days.",
                "Run a 28-day murine PK/PD study.",
            ]
        }
        cleaned, n = scrub_institution_fields(fields, intake_lower="")
        steps = cleaned["recommended_next_steps"]
        assert n == 1
        assert "MIT TTO" not in steps[1]
        assert _GENERIC in steps[1]
        assert steps[0] == "Apply to NIAID SBIR Phase I by next deadline."
        assert steps[2] == "Run a 28-day murine PK/PD study."

    def test_scrubs_string_value(self):
        fields = {"executive_summary": "Work with Harvard TTO on IP strategy."}
        cleaned, n = scrub_institution_fields(fields, intake_lower="")
        assert n == 1
        assert "Harvard TTO" not in cleaned["executive_summary"]

    def test_preserves_grounded_institution_in_list(self):
        fields = {
            "recommended_next_steps": [
                "File provisional patent through MIT TTO.",
            ]
        }
        intake = "this research is conducted at mit in cambridge"
        cleaned, n = scrub_institution_fields(fields, intake_lower=intake)
        assert n == 0
        assert "MIT TTO" in cleaned["recommended_next_steps"][0]

    def test_empty_fields_no_error(self):
        cleaned, n = scrub_institution_fields({}, intake_lower="")
        assert cleaned == {}
        assert n == 0

    def test_non_string_items_in_list_pass_through(self):
        fields = {"recommended_next_steps": [{"nested": "MIT TTO contact"}]}
        cleaned, n = scrub_institution_fields(fields, intake_lower="")
        # dicts inside a list are left untouched (only str items are scrubbed)
        assert cleaned["recommended_next_steps"][0] == {"nested": "MIT TTO contact"}
        assert n == 0


# ── 3. Grounding logic ────────────────────────────────────────────────────────

class TestGroundingLogic:
    """_is_grounded checks whether ANY significant word of the name is in intake."""

    def test_partial_word_match_grounds_institution(self):
        """'neuroscience' in idea contains 'neuro' but not 'Northwestern'; confirm no match."""
        text = "Submit to Northwestern TTO."
        cleaned, n = scrub_institution_refs(text, intake_lower="neuroscience imaging")
        # 'northwestern' is not in 'neuroscience imaging' — should replace
        assert n == 1

    def test_exact_name_grounds_institution(self):
        text = "Contact Northwestern TTO for licensing."
        cleaned, n = scrub_institution_refs(text, intake_lower="platform built at northwestern university")
        assert n == 0
        assert "Northwestern TTO" in cleaned
