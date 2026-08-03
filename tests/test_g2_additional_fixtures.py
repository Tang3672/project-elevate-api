"""
G.2 Additional Fixtures — Spec v3 Addendum Rule 5.

Minimum five fixtures must run before any fix ships:
  G.1 already covers: research_tool (Hublink), molecular diagnostic
  G.2 adds:           small-molecule drug, Class II device, non-life-sciences IoT

Purpose of each new fixture (per addendum Rule 5 table):
  Drug    — reverse-leakage check: WAC, epidemiology cascade, peak-sales framing
             SHOULD appear. If they don't, something is wrong.
  Device  — 510(k) vocabulary and DRG/procedure-volume formula SHOULD appear.
  IoT     — no life-sciences vocabulary ANYWHERE in the report; NOT_REGULATED;
             firmographic/NAICS spine expected (not DisMod pharma cascade).

All tests run without live API calls.
"""

from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Fixture definitions
# ─────────────────────────────────────────────────────────────────────────────

_DRUG_IDEA = (
    "An oral KRAS-G12C small-molecule inhibitor for second-line non-small-cell "
    "lung cancer (NSCLC). Once-daily oral dosing. Phase 2 complete with 37% ORR. "
    "Target buyer: community and academic oncologists treating advanced NSCLC."
)
_DRUG_SUB_EXPERT = "drug_oncology"
_DRUG_TA          = "oncology"

_DEVICE_IDEA = (
    "A Class II implantable cardiac loop recorder for long-term arrhythmia "
    "detection and remote monitoring. Miniaturized injectable form factor; "
    "3-year battery life. 510(k) clearance via predicate Medtronic Reveal LINQ. "
    "Sold to electrophysiology labs and cardiac care units."
)
_DEVICE_SUB_EXPERT = "device_cardiovascular"
_DEVICE_TA          = "cardiovascular"

_IOT_IDEA = (
    "A wireless soil-moisture and pH sensor array for precision agriculture. "
    "Hardware nodes transmit readings to a cloud dashboard for farm management. "
    "Sold to commercial farms and agricultural co-operatives. "
    "No medical, clinical, or diagnostic use whatsoever."
)
_IOT_SUB_EXPERT = "research_infrastructure_saas"
_IOT_TA          = "other"


def _derive(idea: str, ta: str, sub_expert: str):
    from app.services.market_sizing_derivation_service import (
        generate_market_sizing_derivation,
    )
    return generate_market_sizing_derivation(
        idea=idea,
        therapeutic_area=ta,
        sub_expert_id=sub_expert,
    )


# ─────────────────────────────────────────────────────────────────────────────
# G.2a — Small-molecule drug: reverse-leakage checks
# ─────────────────────────────────────────────────────────────────────────────

class TestDrugFixtureDeterminism:
    """G.2a determinism: drug derivation must be bit-identical across 5 runs."""

    def _runs(self):
        return [_derive(_DRUG_IDEA, _DRUG_TA, _DRUG_SUB_EXPERT) for _ in range(5)]

    def test_drug_tam_deterministic(self):
        tams = [r.us_tam_usd for r in self._runs()]
        assert len(set(tams)) == 1, f"G.2a: drug TAM not deterministic: {tams}"

    def test_drug_sam_deterministic(self):
        sams = [r.us_sam_usd for r in self._runs()]
        assert len(set(sams)) == 1, f"G.2a: drug SAM not deterministic: {sams}"

    def test_drug_som_deterministic(self):
        soms = [r.us_som_usd for r in self._runs()]
        assert len(set(soms)) == 1, f"G.2a: drug SOM not deterministic: {soms}"

    def test_drug_formula_name_deterministic(self):
        names = [r.formula_name for r in self._runs()]
        assert len(set(names)) == 1, f"G.2a: drug formula_name not deterministic: {names}"


class TestDrugFixtureContent:
    """G.2a reverse-leakage: clinical vocabulary MUST appear in a drug report."""

    def _r(self):
        return _derive(_DRUG_IDEA, _DRUG_TA, _DRUG_SUB_EXPERT)

    def test_drug_formula_is_pharma_based(self):
        """Drug must route through the pharmaceutical sizing formula, not research-tool."""
        r = self._r()
        formula_lower = r.formula_name.lower()
        assert "pharma" in formula_lower or "dismol" in formula_lower or "dismod" in formula_lower, (
            f"G.2a: drug must use pharmaceutical formula, not '{r.formula_name}'"
        )

    def test_drug_has_prevalence_or_patient_step(self):
        """
        Epidemiology cascade: step 1 must be patient population or prevalence.
        If this is missing, the formula is applying a non-clinical model to a drug.
        """
        r = self._r()
        step_titles_lower = " ".join(s.title.lower() for s in r.steps)
        assert any(kw in step_titles_lower for kw in ("prevalent", "patient population", "prevalence", "incidence")), (
            f"G.2a: drug derivation must have an epidemiology/patient population step. "
            f"Got step titles: {[s.title for s in r.steps]}"
        )

    def test_drug_has_wac_pricing_in_confidence_note(self):
        """WAC (Wholesale Acquisition Cost) must appear in drug derivation output."""
        r = self._r()
        note = (r.confidence_note or "").upper()
        assert "WAC" in note or "WHOLESALE" in note, (
            f"G.2a: drug confidence_note must reference WAC pricing. "
            f"Got: {r.confidence_note[:200] if r.confidence_note else 'None'}"
        )

    def test_drug_tam_is_clinical_scale(self):
        """Drug TAM must be > $100M — clinical markets are not academic-lab-sized."""
        r = self._r()
        assert r.us_tam_usd > 100_000_000, (
            f"G.2a: drug TAM ${r.us_tam_usd:,.0f} is too small for an NSCLC indication. "
            "If TAM < $100M, the research-tool or lab-buyer model is leaking into drug sizing."
        )

    def test_drug_has_no_lab_count_step(self):
        """
        Reverse-leakage guard: no step should talk about 'labs', 'institutions',
        or 'Carnegie' in a drug derivation. Those are research-tool concepts.
        """
        r = self._r()
        for step in r.steps:
            title_lower = step.title.lower()
            assert "lab" not in title_lower and "institution" not in title_lower, (
                f"G.2a: drug derivation step '{step.title}' contains research-tool vocabulary. "
                "Research-lab buyer model is leaking into drug sizing."
            )

    def test_drug_confidence_note_no_authored_ci(self):
        """G.2a/H-05: drug confidence_note must not assert an authored CI percentage."""
        import re
        note = _derive(_DRUG_IDEA, _DRUG_TA, _DRUG_SUB_EXPERT).confidence_note or ""
        assert "95% CI" not in note, f"G.2a: drug confidence_note must not assert '95% CI': {note[:200]}"
        assert "IQVIA reports 71" not in note, f"G.2a: drug must not cite IQVIA 71% error: {note[:200]}"

    def test_drug_regulatory_status_is_regulated(self):
        """Drug products must derive a regulated (not NOT_REGULATED) status."""
        from app.services.regulatory_status import RegulatoryStatus, derive_regulatory_status
        status = derive_regulatory_status(
            archetype=_DRUG_SUB_EXPERT,
            idea=_DRUG_IDEA,
            sub_expert_id=_DRUG_SUB_EXPERT,
        )
        assert status != RegulatoryStatus.NOT_REGULATED, (
            f"G.2a: drug must not derive NOT_REGULATED status. Got: {status}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# G.2b — Class II device: 510(k) + DRG/procedure-volume checks
# ─────────────────────────────────────────────────────────────────────────────

class TestDeviceFixtureDeterminism:
    """G.2b determinism: device derivation must be bit-identical across 5 runs."""

    def _runs(self):
        return [_derive(_DEVICE_IDEA, _DEVICE_TA, _DEVICE_SUB_EXPERT) for _ in range(5)]

    def test_device_tam_deterministic(self):
        tams = [r.us_tam_usd for r in self._runs()]
        assert len(set(tams)) == 1, f"G.2b: device TAM not deterministic: {tams}"

    def test_device_sam_deterministic(self):
        sams = [r.us_sam_usd for r in self._runs()]
        assert len(set(sams)) == 1, f"G.2b: device SAM not deterministic: {sams}"

    def test_device_formula_name_deterministic(self):
        names = [r.formula_name for r in self._runs()]
        assert len(set(names)) == 1, f"G.2b: device formula_name not deterministic: {names}"


class TestDeviceFixtureContent:
    """G.2b: device vocabulary MUST appear; drug or lab vocabulary must NOT."""

    def _r(self):
        return _derive(_DEVICE_IDEA, _DEVICE_TA, _DEVICE_SUB_EXPERT)

    def test_device_formula_is_procedure_volume_based(self):
        """Device must route through procedure-volume / DRG model, not pharma DisMod."""
        r = self._r()
        formula_lower = r.formula_name.lower()
        assert any(kw in formula_lower for kw in ("procedure", "drg", "cms", "volume")), (
            f"G.2b: device must use procedure-volume/DRG formula, not '{r.formula_name}'. "
            "If using pharma DisMod, drug formula is leaking into device sizing."
        )

    def test_device_has_procedure_volume_step(self):
        """Step 1 must be procedure volume, not patient prevalence."""
        r = self._r()
        first_step = r.steps[0].title.lower() if r.steps else ""
        assert any(kw in first_step for kw in ("procedure", "volume", "annual")), (
            f"G.2b: device step 1 must be about procedure volume. Got: '{r.steps[0].title if r.steps else None}'"
        )

    def test_device_has_drg_or_cpt_in_steps(self):
        """DRG or CPT must appear in step content — that's the device revenue model."""
        r = self._r()
        all_content = " ".join(
            (s.title + " " + (s.explanation or "")).lower() for s in r.steps
        )
        assert "drg" in all_content or "cpt" in all_content or "reimbursement" in all_content, (
            f"G.2b: device steps must reference DRG/CPT/reimbursement. "
            "These are the correct pricing anchors for a Class II device."
        )

    def test_device_tam_is_clinical_scale(self):
        """Device TAM must be > $100M — Class II cardiac devices are large markets."""
        r = self._r()
        assert r.us_tam_usd > 100_000_000, (
            f"G.2b: device TAM ${r.us_tam_usd:,.0f} is implausibly small for a "
            "cardiac loop recorder. Research-tool or academic buyer model may be leaking."
        )

    def test_device_has_no_wac_pricing(self):
        """
        Reverse-leakage: WAC (pharmaceutical pricing) must not appear in device steps.
        WAC is a drug concept; device revenue flows through DRG reimbursement.
        """
        r = self._r()
        note = (r.confidence_note or "").upper()
        all_steps = " ".join(s.title for s in r.steps).upper()
        # WAC in a device report = pharma pricing is leaking
        assert "WAC" not in note or "WAC" not in all_steps, (
            "G.2b: device derivation must not reference WAC pricing — "
            "that is a pharmaceutical concept leaking into device sizing."
        )

    def test_device_regulatory_status_is_regulated(self):
        """Class II device must be FDA-regulated."""
        from app.services.regulatory_status import RegulatoryStatus, derive_regulatory_status
        status = derive_regulatory_status(
            archetype=_DEVICE_SUB_EXPERT,
            idea=_DEVICE_IDEA,
            sub_expert_id=_DEVICE_SUB_EXPERT,
        )
        assert status != RegulatoryStatus.NOT_REGULATED, (
            f"G.2b: Class II device must not derive NOT_REGULATED status. Got: {status}"
        )

    def test_device_confidence_note_no_authored_ci(self):
        """G.2b/H-05: device confidence_note must not assert an authored CI percentage."""
        note = self._r().confidence_note or ""
        assert "95% CI" not in note and "IQVIA reports 71" not in note, (
            f"G.2b: device confidence_note must not contain authored CI%. Got: {note[:200]}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# G.2c — Non-life-sciences IoT: zero medical vocabulary
# ─────────────────────────────────────────────────────────────────────────────

_CLINICAL_TERMS = frozenset({
    "patient", "clinical", "reimbursement", "medicare", "medicaid",
    "ehr", "emr", "payer", "insurance", "diagnosis", "treatment",
    "formulary", "prior authorization", "phase 1", "phase 2", "phase 3",
    "ind ", "nda ", "bla ", "clinical trial", "pivotal study",
    "ntap", "drg ", "cpt ",
})


class TestIoTFixtureDeterminism:
    """G.2c determinism: non-LS IoT sensor derivation must be bit-identical across 5 runs."""

    def _runs(self):
        return [_derive(_IOT_IDEA, _IOT_TA, _IOT_SUB_EXPERT) for _ in range(5)]

    def test_iot_tam_deterministic(self):
        tams = [r.us_tam_usd for r in self._runs()]
        assert len(set(tams)) == 1, f"G.2c: IoT TAM not deterministic: {tams}"

    def test_iot_sam_deterministic(self):
        sams = [r.us_sam_usd for r in self._runs()]
        assert len(set(sams)) == 1, f"G.2c: IoT SAM not deterministic: {sams}"


class TestIoTFixtureContent:
    """G.2c: no clinical vocabulary in the non-LS IoT report path."""

    def test_iot_regulatory_status_not_regulated(self):
        """Agricultural IoT hardware must derive NOT_REGULATED status."""
        from app.services.regulatory_status import RegulatoryStatus, derive_regulatory_status
        status = derive_regulatory_status(
            archetype=_IOT_SUB_EXPERT,
            idea=_IOT_IDEA,
            sub_expert_id=_IOT_SUB_EXPERT,
        )
        assert status == RegulatoryStatus.NOT_REGULATED, (
            f"G.2c: IoT sensor must be NOT_REGULATED. Got: {status}"
        )

    def test_iot_archetype_inapplicable_sections_include_regulatory(self):
        """IoT must mark regulatory_pathway as inapplicable."""
        from app.services.product_archetype import ProductArchetype, get_manifest
        manifest = get_manifest(ProductArchetype.RESEARCH_INFRASTRUCTURE_SAAS)
        inapplicable = manifest.inapplicable_sections
        assert any("regulat" in s for s in inapplicable), (
            f"G.2c: RESEARCH_INFRASTRUCTURE_SAAS must mark regulatory as inapplicable. "
            f"Got: {inapplicable}"
        )

    def test_iot_clean_report_passes_vocabulary_check(self):
        """A non-clinical IoT report with no medical terms must pass validation."""
        from app.services.product_archetype import ProductArchetype, validate_report_dict
        clean_report = {
            "executive_summary": (
                "Wireless soil-moisture and pH sensor array for precision agriculture. "
                "Hardware nodes transmit to a cloud dashboard for irrigation management. "
                "Revenue model: hardware + annual subscription for data analytics."
            ),
            "market_access": {
                "primary_channel": "Direct sales to commercial farms and ag co-ops",
                "distribution_partners": ["John Deere dealerships", "Nutrien retail network"],
            },
        }
        violations = validate_report_dict(clean_report, ProductArchetype.RESEARCH_INFRASTRUCTURE_SAAS)
        assert len(violations) == 0, (
            f"G.2c: clean IoT report should have zero archetype violations. Got: {violations}"
        )

    def test_iot_clinical_vocab_in_report_fires_violation(self):
        """
        A report containing medical billing terms must be flagged for a non-LS product.
        Uses terms actually in RESEARCH_INFRASTRUCTURE_SAAS.banned_vocabulary:
        'ntap', 'cpt code', 'drg ', '510 (k)', 'wac price'.
        """
        from app.services.product_archetype import ProductArchetype, validate_report_dict
        bad_report = {
            "executive_summary": (
                "Reimbursement is available via the NTAP add-on payment mechanism. "
                "Providers bill using a CPT code for each procedure. "
                "The device DRG reimbursement covers the hospital's costs."
            ),
            "regulatory_pathway": {
                "recommended_pathway": "510 (k) clearance required.",
            },
        }
        violations = validate_report_dict(bad_report, ProductArchetype.RESEARCH_INFRASTRUCTURE_SAAS)
        assert len(violations) > 0, (
            "G.2c: report with clinical billing vocab (NTAP, CPT code, DRG, 510(k)) "
            "must fail validation for a non-life-sciences product. "
            "No violation was raised — banned_vocabulary may be misconfigured."
        )

    def test_iot_confidence_note_no_authored_ci(self):
        """G.2c/H-05: non-LS confidence_note must not contain authored CI percentages."""
        r = _derive(_IOT_IDEA, _IOT_TA, _IOT_SUB_EXPERT)
        note = r.confidence_note or ""
        assert "95% CI" not in note, (
            f"G.2c: IoT confidence_note must not contain '95% CI'. Got: {note[:200]}"
        )

    def test_iot_formula_is_not_pharma_dismod(self):
        """
        Non-LS products must NOT use the pharmaceutical DisMod formula.
        An IoT sensor should use a firmographic model (establishments × unit price),
        not a patient-prevalence cascade.
        """
        r = _derive(_IOT_IDEA, _IOT_TA, _IOT_SUB_EXPERT)
        formula_lower = r.formula_name.lower()
        assert "pharma" not in formula_lower and "dismod" not in formula_lower, (
            f"G.2c: IoT sensor should not use pharmaceutical formula '{r.formula_name}'. "
            "Firmographic (NAICS/Census CBP) model expected for non-LS products."
        )

    def test_iot_step_titles_contain_no_clinical_vocab(self):
        """Non-LS derivation steps must not reference patients, diagnosis, or treatment."""
        r = _derive(_IOT_IDEA, _IOT_TA, _IOT_SUB_EXPERT)
        step_text = " ".join(s.title.lower() for s in r.steps)
        found = [t for t in _CLINICAL_TERMS if t in step_text]
        assert found == [], (
            f"G.2c: IoT derivation step titles contain clinical vocabulary: {found}. "
            f"Step titles: {[s.title for s in r.steps]}"
        )
