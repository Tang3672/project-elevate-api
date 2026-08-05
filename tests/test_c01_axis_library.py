"""
Part C — Axis library and selection/rejection engine (spec v4 C.1, C.2).

Tests:
  C.1  AXIS_LIBRARY — coverage, family membership, completeness
  C.2  select_axes — correct selection for research tool vs clinical vs B2B
  C.2  Rejection list — patient-demographic axes rejected for research tool
       with a non-empty reason string
  C.2  AxisDecision contract — selected/rejected counts, field presence
  C.2  format_axis_decisions — serialization shape
  C.3  alignment_service wiring — axis_decisions attached after report assembly
  C.3  PIReport schema — axis_decisions field present
"""

from __future__ import annotations

import pytest

from app.market.axis_library import (
    AXIS_LIBRARY,
    AxisDecision,
    AxisDefinition,
    AxisFamily,
    format_axis_decisions,
    select_axes,
)


# ══════════════════════════════════════════════════════════════════════════════
# C.1 — AXIS_LIBRARY structure
# ══════════════════════════════════════════════════════════════════════════════

class TestAxisLibraryStructure:

    def test_library_non_empty(self):
        assert len(AXIS_LIBRARY) >= 10, (
            "AXIS_LIBRARY must contain at least 10 axis definitions"
        )

    def test_all_entries_are_axis_definitions(self):
        for ax in AXIS_LIBRARY:
            assert isinstance(ax, AxisDefinition), (
                f"AXIS_LIBRARY entry {ax!r} is not an AxisDefinition"
            )

    def test_ids_are_unique(self):
        ids = [ax.id for ax in AXIS_LIBRARY]
        assert len(ids) == len(set(ids)), "Axis IDs must be unique in AXIS_LIBRARY"

    def test_labels_non_empty(self):
        for ax in AXIS_LIBRARY:
            assert ax.label, f"Axis {ax.id!r} has an empty label"

    def test_families_are_valid(self):
        valid_families = {
            "patient_demographic", "geographic", "institutional",
            "firmographic", "payer", "clinical", "behavioral", "operational",
        }
        for ax in AXIS_LIBRARY:
            assert ax.family in valid_families, (
                f"Axis {ax.id!r} has invalid family {ax.family!r}"
            )

    def test_patient_demographic_axes_present(self):
        families = {ax.family for ax in AXIS_LIBRARY}
        assert "patient_demographic" in families, (
            "AXIS_LIBRARY must include patient-demographic axes"
        )

    def test_institutional_axes_present(self):
        families = {ax.family for ax in AXIS_LIBRARY}
        assert "institutional" in families, (
            "AXIS_LIBRARY must include institutional axes for research tools"
        )

    def test_applies_when_callable(self):
        for ax in AXIS_LIBRARY:
            # Must be callable with two str args
            result = ax.applies_when("LIFE_SCIENCES_CLINICAL", "drug_amr")
            assert isinstance(result, bool), (
                f"Axis {ax.id!r}.applies_when must return bool"
            )

    def test_rejection_reason_non_empty_for_conditional_axes(self):
        for ax in AXIS_LIBRARY:
            # A conditional axis (not _always) must have a rejection reason
            fires_for_all = (
                ax.applies_when("LIFE_SCIENCES_CLINICAL", "drug_amr") and
                ax.applies_when("LIFE_SCIENCES_RESEARCH", "research_tool_non_clinical") and
                ax.applies_when("ENGINEERING_HARDWARE", "")
            )
            if not fires_for_all:
                assert ax.rejection_reason, (
                    f"Axis {ax.id!r} is conditional but has no rejection_reason"
                )


# ══════════════════════════════════════════════════════════════════════════════
# C.2 — select_axes: research tool
# ══════════════════════════════════════════════════════════════════════════════

class TestSelectAxesResearchTool:

    def _select(self, expert="research_tool_non_clinical"):
        return select_axes("LIFE_SCIENCES_RESEARCH", expert)

    def test_returns_list_of_axis_decisions(self):
        decisions = self._select()
        assert isinstance(decisions, list)
        assert all(isinstance(d, AxisDecision) for d in decisions)

    def test_selected_before_rejected(self):
        decisions = self._select()
        seen_rejected = False
        for d in decisions:
            if not d.selected:
                seen_rejected = True
            else:
                assert not seen_rejected, (
                    "All selected axes must appear before any rejected axis"
                )

    def test_institutional_axes_selected(self):
        decisions = self._select()
        selected_ids = {d.axis_id for d in decisions if d.selected}
        institutional = {"carnegie_tier", "funding_agency", "award_band", "lab_size", "department"}
        overlap = selected_ids & institutional
        assert overlap, (
            f"At least one institutional axis must be selected for research_tool; "
            f"got selected_ids={selected_ids}"
        )

    def test_patient_demographic_axes_rejected(self):
        decisions = self._select()
        rejected_ids = {d.axis_id for d in decisions if not d.selected}
        patient_demo = {"age_band", "sex", "race_ethnicity", "income_quintile"}
        for pd_id in patient_demo:
            assert pd_id in rejected_ids, (
                f"Patient-demographic axis {pd_id!r} must be rejected for research tool"
            )

    def test_payer_axes_rejected(self):
        decisions = self._select()
        rejected_ids = {d.axis_id for d in decisions if not d.selected}
        assert "payer_mix" in rejected_ids or "insurance_status" in rejected_ids, (
            "Payer axes must be rejected for non-clinical research tool"
        )

    def test_rejection_reasons_non_empty(self):
        decisions = self._select()
        for d in decisions:
            if not d.selected:
                assert d.reason, (
                    f"Rejected axis {d.axis_id!r} must have a non-empty reason string"
                )

    def test_rejection_reasons_mention_institutional_buyer(self):
        decisions = self._select()
        pd_rejected = [d for d in decisions if not d.selected and d.family == "patient_demographic"]
        for d in pd_rejected:
            text = d.reason.lower()
            assert any(kw in text for kw in ("institutional", "buyer", "patient", "not applicable")), (
                f"Rejection reason for {d.axis_id!r} should explain why patient demographics "
                f"don't apply; got: {d.reason!r}"
            )

    def test_selected_axes_have_est_lift(self):
        decisions = self._select()
        for d in decisions:
            if d.selected:
                assert d.est_lift is not None, (
                    f"Selected axis {d.axis_id!r} must have est_lift set"
                )
                assert 0.0 <= d.est_lift <= 1.0, (
                    f"Selected axis {d.axis_id!r} est_lift must be in [0,1]; got {d.est_lift}"
                )

    def test_rejected_axes_have_none_lift(self):
        decisions = self._select()
        for d in decisions:
            if not d.selected:
                assert d.est_lift is None, (
                    f"Rejected axis {d.axis_id!r} should have est_lift=None"
                )

    def test_research_infrastructure_also_selects_institutional(self):
        decisions = select_axes("LIFE_SCIENCES_RESEARCH", "research_infrastructure_saas")
        selected_ids = {d.axis_id for d in decisions if d.selected}
        assert selected_ids & {"carnegie_tier", "funding_agency", "award_band"}, (
            "research_infrastructure_saas must also select institutional axes"
        )


# ══════════════════════════════════════════════════════════════════════════════
# C.2 — select_axes: clinical drug
# ══════════════════════════════════════════════════════════════════════════════

class TestSelectAxesClinical:

    def _select(self, expert="drug_amr"):
        return select_axes("LIFE_SCIENCES_CLINICAL", expert)

    def test_patient_demographic_axes_selected(self):
        decisions = self._select()
        selected_ids = {d.axis_id for d in decisions if d.selected}
        pd_axes = {"age_band", "sex", "race_ethnicity", "income_quintile"}
        overlap = selected_ids & pd_axes
        assert overlap, (
            f"At least one patient-demographic axis must be selected for clinical; "
            f"got selected_ids={selected_ids}"
        )

    def test_institutional_axes_rejected_for_clinical(self):
        decisions = self._select()
        rejected_ids = {d.axis_id for d in decisions if not d.selected}
        assert "carnegie_tier" in rejected_ids, (
            "carnegie_tier must be rejected for LIFE_SCIENCES_CLINICAL"
        )

    def test_clinical_axes_selected(self):
        decisions = self._select()
        selected_ids = {d.axis_id for d in decisions if d.selected}
        clinical_axes = {"line_of_therapy", "biomarker", "site_of_care"}
        assert selected_ids & clinical_axes, (
            f"At least one clinical axis must be selected for LIFE_SCIENCES_CLINICAL; "
            f"got selected_ids={selected_ids}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# C.2 — select_axes: selected ordering and universal axes
# ══════════════════════════════════════════════════════════════════════════════

class TestSelectAxesOrdering:

    def test_selected_sorted_by_descending_lift(self):
        decisions = select_axes("LIFE_SCIENCES_CLINICAL", "drug_amr")
        selected = [d for d in decisions if d.selected]
        lifts = [d.est_lift or 0.0 for d in selected]
        assert lifts == sorted(lifts, reverse=True), (
            "Selected axes must be sorted by descending est_lift"
        )

    def test_universal_axes_selected_for_all_domains(self):
        universal_ids = {"geography_us_region", "current_solution", "purchase_cadence"}
        for domain, expert in [
            ("LIFE_SCIENCES_CLINICAL", "drug_amr"),
            ("LIFE_SCIENCES_RESEARCH", "research_tool_non_clinical"),
            ("ENGINEERING_HARDWARE", ""),
        ]:
            decisions = select_axes(domain, expert)
            selected_ids = {d.axis_id for d in decisions if d.selected}
            overlap = selected_ids & universal_ids
            assert overlap, (
                f"At least one universal axis must be selected for domain={domain}; "
                f"selected_ids={selected_ids}"
            )

    def test_empty_domain_does_not_crash(self):
        decisions = select_axes("", "")
        assert isinstance(decisions, list)

    def test_unknown_domain_returns_universal_only(self):
        decisions = select_axes("UNKNOWN_DOMAIN", "unknown_expert")
        selected_ids = {d.axis_id for d in decisions if d.selected}
        # Universal axes should fire; no patient-demo or institutional axes
        assert "carnegie_tier" not in selected_ids
        assert "age_band" not in selected_ids


# ══════════════════════════════════════════════════════════════════════════════
# C.2 — format_axis_decisions serialization
# ══════════════════════════════════════════════════════════════════════════════

class TestFormatAxisDecisions:

    def _formatted(self, domain="LIFE_SCIENCES_RESEARCH", expert="research_tool_non_clinical"):
        decisions = select_axes(domain, expert)
        return format_axis_decisions(decisions)

    def test_returns_dict_with_selected_and_rejected(self):
        result = self._formatted()
        assert "selected" in result
        assert "rejected" in result

    def test_selected_is_list(self):
        result = self._formatted()
        assert isinstance(result["selected"], list)

    def test_rejected_is_list(self):
        result = self._formatted()
        assert isinstance(result["rejected"], list)

    def test_each_entry_has_required_keys(self):
        result = self._formatted()
        required = {"axis_id", "label", "family", "selected", "reason", "est_lift", "data_available"}
        for entry in result["selected"] + result["rejected"]:
            missing = required - entry.keys()
            assert not missing, f"Entry missing keys: {missing!r} in {entry}"

    def test_selected_entries_have_selected_true(self):
        result = self._formatted()
        for e in result["selected"]:
            assert e["selected"] is True

    def test_rejected_entries_have_selected_false(self):
        result = self._formatted()
        for e in result["rejected"]:
            assert e["selected"] is False

    def test_clinical_format_has_patient_demo_selected(self):
        result = format_axis_decisions(
            select_axes("LIFE_SCIENCES_CLINICAL", "drug_amr")
        )
        selected_ids = {e["axis_id"] for e in result["selected"]}
        assert selected_ids & {"age_band", "sex", "race_ethnicity"}, (
            "Clinical format must have at least one patient-demographic axis in 'selected'"
        )


# ══════════════════════════════════════════════════════════════════════════════
# C.3 — PIReport schema and alignment_service wiring
# ══════════════════════════════════════════════════════════════════════════════

class TestPIReportAxisDecisionsField:

    def test_axis_decisions_field_on_pireport(self):
        from app.models.alignment import PIReport
        fields = PIReport.model_fields
        assert "axis_decisions" in fields, (
            "PIReport must have an axis_decisions field (C.1/C.2)"
        )

    def test_axis_decisions_defaults_none(self):
        from app.models.alignment import PIReport
        f = PIReport.model_fields["axis_decisions"]
        assert f.default is None

    def test_alignment_service_calls_select_axes(self):
        import inspect
        import app.services.alignment_service as svc
        src = inspect.getsource(svc)
        assert "select_axes" in src, (
            "alignment_service must call select_axes() from axis_library (C.2)"
        )

    def test_alignment_service_calls_format_axis_decisions(self):
        import inspect
        import app.services.alignment_service as svc
        src = inspect.getsource(svc)
        assert "format_axis_decisions" in src, (
            "alignment_service must call format_axis_decisions() (C.2)"
        )

    def test_alignment_service_attaches_axis_decisions(self):
        import inspect
        import app.services.alignment_service as svc
        src = inspect.getsource(svc)
        assert "report.axis_decisions" in src, (
            "alignment_service must set report.axis_decisions (C.2)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# C.3 — pdf_renderer wiring
# ══════════════════════════════════════════════════════════════════════════════

class TestPdfRendererAxisDecisions:

    def test_render_axis_decisions_function_exists(self):
        from app.services.pdf_renderer import _render_axis_decisions
        assert callable(_render_axis_decisions)

    def test_render_axis_decisions_returns_html_with_selected_table(self):
        from app.services.pdf_renderer import _render_axis_decisions
        decisions = format_axis_decisions(
            select_axes("LIFE_SCIENCES_RESEARCH", "research_tool_non_clinical")
        )
        html = _render_axis_decisions(decisions)
        assert "selected" in html.lower() or "Segmentation" in html, (
            "_render_axis_decisions must produce HTML mentioning selected axes"
        )

    def test_render_axis_decisions_includes_rejected_section(self):
        from app.services.pdf_renderer import _render_axis_decisions
        decisions = format_axis_decisions(
            select_axes("LIFE_SCIENCES_RESEARCH", "research_tool_non_clinical")
        )
        html = _render_axis_decisions(decisions)
        assert "excluded" in html.lower() or "rejected" in html.lower(), (
            "_render_axis_decisions must render the rejected/excluded axes"
        )

    def test_render_axis_decisions_shows_patient_demo_rejection_reason(self):
        from app.services.pdf_renderer import _render_axis_decisions
        decisions = format_axis_decisions(
            select_axes("LIFE_SCIENCES_RESEARCH", "research_tool_non_clinical")
        )
        html = _render_axis_decisions(decisions)
        assert "institutional" in html.lower() or "buyer" in html.lower(), (
            "The rendered HTML must include the reason patient demographics were rejected"
        )

    def test_render_axis_decisions_empty_returns_empty(self):
        from app.services.pdf_renderer import _render_axis_decisions
        assert _render_axis_decisions({}) == ""
        assert _render_axis_decisions(None) == ""

    def test_render_report_html_includes_axis_section_when_decisions_present(self):
        from app.services.pdf_renderer import render_report_html
        from app.market.axis_library import select_axes, format_axis_decisions

        report = {
            "product_name": "Hublink",
            "idea_submitted": "A research data platform.",
            "expert_domain": "research_tool_non_clinical",
            "domain": "LIFE_SCIENCES_RESEARCH",
            "generated_at": "2026-08-05T00:00:00",
            "sources": [],
            "axis_decisions": format_axis_decisions(
                select_axes("LIFE_SCIENCES_RESEARCH", "research_tool_non_clinical")
            ),
        }
        html = render_report_html(report, product_name="Hublink")
        assert "Segmentation" in html, (
            "Full report HTML must include the axis segmentation section when axis_decisions is set"
        )
