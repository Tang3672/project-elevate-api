"""
B-04 — Candidacy gate regression: clinical-family axes must never appear
in axis_decisions.selected for LIFE_SCIENCES_RESEARCH domain products.

Families blocked for research tools: patient_demographic, payer, clinical.

If any of these leak into the selected list it means:
  (a) an AxisDefinition's applies_when predicate is wrong, OR
  (b) _resolved_domain was mis-classified as LIFE_SCIENCES_CLINICAL.

These tests are pure-function checks against select_axes() — no API, no DB.
"""

from __future__ import annotations

import pytest

from app.market.axis_library import (
    AXIS_LIBRARY,
    AxisDecision,
    format_axis_decisions,
    select_axes,
)

# Families that must never appear in selected axes for research tool products.
_CLINICAL_FAMILIES: frozenset[str] = frozenset({
    "patient_demographic",
    "payer",
    "clinical",
})

_RESEARCH_CASES = [
    ("LIFE_SCIENCES_RESEARCH", "research_tool_agronomy"),
    ("LIFE_SCIENCES_RESEARCH", "research_tool_non_clinical"),
    ("LIFE_SCIENCES_RESEARCH", "research_infrastructure_saas"),
    ("LIFE_SCIENCES_RESEARCH", "research_tool_genomics"),
]


class TestCandidacyGateResearchDomain:

    @pytest.mark.parametrize("domain,expert", _RESEARCH_CASES)
    def test_no_clinical_family_axes_selected(self, domain: str, expert: str):
        decisions = select_axes(domain, expert)
        selected = [d for d in decisions if d.selected]
        contaminated = [d for d in selected if d.family in _CLINICAL_FAMILIES]
        assert contaminated == [], (
            f"[{expert}] Clinical-family axes must never be selected for LIFE_SCIENCES_RESEARCH. "
            f"Found: {[d.axis_id for d in contaminated]}"
        )

    @pytest.mark.parametrize("domain,expert", _RESEARCH_CASES)
    def test_patient_demographic_axes_are_rejected(self, domain: str, expert: str):
        decisions = select_axes(domain, expert)
        patient_axes_in_library = {
            ax.id for ax in AXIS_LIBRARY if ax.family == "patient_demographic"
        }
        selected_ids = {d.axis_id for d in decisions if d.selected}
        leaks = patient_axes_in_library & selected_ids
        assert leaks == set(), (
            f"[{expert}] Patient-demographic axis IDs must be rejected: {leaks}"
        )

    @pytest.mark.parametrize("domain,expert", _RESEARCH_CASES)
    def test_payer_axes_are_rejected(self, domain: str, expert: str):
        decisions = select_axes(domain, expert)
        payer_axes_in_library = {
            ax.id for ax in AXIS_LIBRARY if ax.family == "payer"
        }
        selected_ids = {d.axis_id for d in decisions if d.selected}
        leaks = payer_axes_in_library & selected_ids
        assert leaks == set(), (
            f"[{expert}] Payer-family axis IDs must be rejected: {leaks}"
        )

    @pytest.mark.parametrize("domain,expert", _RESEARCH_CASES)
    def test_rejected_axes_carry_reason(self, domain: str, expert: str):
        decisions = select_axes(domain, expert)
        clinical_rejected = [
            d for d in decisions
            if not d.selected and d.family in _CLINICAL_FAMILIES
        ]
        empty_reasons = [d.axis_id for d in clinical_rejected if not (d.reason or "").strip()]
        assert empty_reasons == [], (
            f"[{expert}] Clinical-family rejected axes must carry a non-empty reason: {empty_reasons}"
        )

    @pytest.mark.parametrize("domain,expert", _RESEARCH_CASES)
    def test_format_axis_decisions_no_clinical_in_selected_list(
        self, domain: str, expert: str
    ):
        """format_axis_decisions() serialization also must not embed clinical axes."""
        decisions = select_axes(domain, expert)
        formatted = format_axis_decisions(decisions)
        selected_families = {d["family"] for d in formatted.get("selected", [])}
        contamination = selected_families & _CLINICAL_FAMILIES
        assert contamination == set(), (
            f"[{expert}] Serialized selected list must not contain clinical families: {contamination}"
        )


class TestCandidacyGateClinicalDomain:
    """Sanity-check: clinical domain MUST have patient_demographic axes selected."""

    def test_clinical_domain_has_patient_axes(self):
        decisions = select_axes("LIFE_SCIENCES_CLINICAL", "drug_amr")
        selected_families = {d.family for d in decisions if d.selected}
        assert "patient_demographic" in selected_families, (
            "Clinical domain must select at least one patient_demographic axis — "
            "if this fails, the _is_clinical predicate is broken"
        )

    def test_clinical_domain_has_payer_axes(self):
        decisions = select_axes("LIFE_SCIENCES_CLINICAL", "drug_amr")
        selected_families = {d.family for d in decisions if d.selected}
        assert "payer" in selected_families, (
            "Clinical domain must select at least one payer axis"
        )
