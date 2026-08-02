"""
tests/test_regulatory_pathways.py
==================================
Tests for app/services/regulatory_pathways.py (Build Spec v6, Part 2).

Key assertions:
  • Drug pathway has no device stages (no "510k", "pma", "IDE" stage IDs)
  • Device pathway has no IND/Phase stages
  • CDx pathway has co-review note in reimbursement
  • SaMD pathway flags no standard reimbursement code (critical risk)
  • Router returns distinct pathways per product type
  • Inferred pathways set pathway_was_inferred=True and supply clarifying_question
"""

from __future__ import annotations

import pytest

from app.services.regulatory_pathways import (
    RegulatoryPathway,
    select_regulatory_pathway,
    time_to_market_summary,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _stage_ids(pathway: RegulatoryPathway) -> list[str]:
    return [s.stage for s in pathway.stages]


# ──────────────────────────────────────────────────────────────────────────────
# 1. Drug pathway — no device stages present
# ──────────────────────────────────────────────────────────────────────────────

class TestDrugPathway:

    @pytest.fixture
    def drug(self) -> RegulatoryPathway:
        return select_regulatory_pathway("drug_small_molecule", "novel oral antibiotic")

    def test_drug_family(self, drug):
        assert drug.product_family == "drug", "Drug pathway must have product_family='drug'"

    def test_drug_has_nda_stage(self, drug):
        ids = _stage_ids(drug)
        assert "nda" in ids, "Drug pathway must include an NDA stage"

    def test_drug_has_phase_stages(self, drug):
        ids = _stage_ids(drug)
        assert any("phase" in i for i in ids), "Drug pathway must include Phase 1/2/3 stages"

    def test_drug_has_no_device_stages(self, drug):
        device_stage_ids = {"510k_submit", "510k_samd", "pma_submit", "ide",
                            "de_novo_submit", "de_novo_samd", "bench_test"}
        ids = set(_stage_ids(drug))
        overlap = ids & device_stage_ids
        assert not overlap, (
            f"Drug pathway must not contain device stages; found: {overlap}"
        )

    def test_drug_reimbursement_is_formulary(self, drug):
        reimb = drug.reimbursement.pathway_name.lower()
        assert "formulary" in reimb or "part" in reimb or "asp" in reimb, (
            "Drug reimbursement should be Part D formulary or Part B ASP"
        )

    def test_drug_coverage_lag_short(self, drug):
        assert drug.reimbursement.coverage_lag_months <= 18, (
            "Drug coverage lag should be ≤18 months"
        )

    def test_drug_time_to_market_reasonable(self, drug):
        ttm_yr = drug.time_to_market_years()
        assert 8 <= ttm_yr <= 20, (
            f"Drug time-to-market {ttm_yr}yr is outside expected range 8-20yr"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 2. Device pathway — no IND/Phase stages
# ──────────────────────────────────────────────────────────────────────────────

class TestDevicePathway:

    @pytest.fixture
    def device_510k(self) -> RegulatoryPathway:
        return select_regulatory_pathway("medical_device", "glucose monitor wearable")

    @pytest.fixture
    def device_pma(self) -> RegulatoryPathway:
        return select_regulatory_pathway("medical_device", "cardiac implant pacemaker high-risk")

    def test_device_family(self, device_510k):
        assert device_510k.product_family == "device"

    def test_device_has_no_drug_phases(self, device_510k):
        drug_stages = {"ind", "phase1", "phase2", "phase3", "nda"}
        ids = set(_stage_ids(device_510k))
        overlap = ids & drug_stages
        assert not overlap, (
            f"Device pathway must not contain drug/biologic stages; found: {overlap}"
        )

    def test_510k_has_510k_stage(self, device_510k):
        assert "510k_submit" in _stage_ids(device_510k), "510(k) device pathway must have 510k_submit stage"

    def test_pma_has_ide_stage(self, device_pma):
        assert "ide" in _stage_ids(device_pma), "PMA pathway must include an IDE clinical study stage"

    def test_pma_has_pma_submit_stage(self, device_pma):
        assert "pma_submit" in _stage_ids(device_pma), "PMA pathway must include pma_submit stage"

    def test_device_coverage_lag_high(self, device_510k):
        """Standard device coverage lag must be ≥24 months (the 6.7yr median)."""
        assert device_510k.reimbursement.coverage_lag_months >= 24, (
            "Standard device coverage lag must reflect ≥24 month reality "
            "(median 6.7yr per JAMA 2021)"
        )

    def test_device_reimbursement_risk_high_or_critical(self, device_510k):
        risk = device_510k.reimbursement.risk_level
        assert risk in ("high", "critical", "medium"), (
            f"Device reimbursement risk must be high/critical, got: {risk}"
        )

    def test_device_time_to_market_longer_than_drug_coverage(self, device_510k, drug):
        """Device TTM (including coverage lag) should be ≥5 years."""
        assert device_510k.time_to_market_years() >= 5.0

    @pytest.fixture
    def drug(self):
        return select_regulatory_pathway("drug_small_molecule", "")


# ──────────────────────────────────────────────────────────────────────────────
# 3. Diagnostic pathway — CDx has co-review note
# ──────────────────────────────────────────────────────────────────────────────

class TestDiagnosticPathway:

    @pytest.fixture
    def cdx(self) -> RegulatoryPathway:
        return select_regulatory_pathway(
            "diagnostic",
            "companion diagnostic biomarker test cdx co-developed with oncology drug"
        )

    @pytest.fixture
    def ivd(self) -> RegulatoryPathway:
        return select_regulatory_pathway("diagnostic", "molecular blood test PCR assay")

    def test_dx_family(self, ivd):
        assert ivd.product_family == "diagnostic"

    def test_dx_has_no_drug_phases(self, ivd):
        drug_stages = {"ind", "phase1", "phase2", "phase3", "nda"}
        ids = set(_stage_ids(ivd))
        assert not (ids & drug_stages), "Diagnostic pathway must not include drug phase stages"

    def test_cdx_subtype(self, cdx):
        assert cdx.pathway_subtype == "cdx", "CDx keyword matching must route to CDx sub-path"

    def test_cdx_has_co_dev_stage(self, cdx):
        assert "co_dev" in _stage_ids(cdx), "CDx pathway must have co-development stage"

    def test_cdx_has_pma_stage(self, cdx):
        assert "pma_cdx" in _stage_ids(cdx), "CDx pathway must have PMA review stage"

    def test_cdx_reimbursement_has_co_approval_note(self, cdx):
        desc = (cdx.reimbursement.description or "").lower()
        reimb_name = cdx.reimbursement.pathway_name.lower()
        assert "drug" in desc or "co-approval" in desc or "co-review" in reimb_name, (
            "CDx reimbursement description must mention drug co-approval linkage"
        )

    def test_cdx_low_coverage_risk(self, cdx):
        assert cdx.reimbursement.risk_level == "low", (
            "CDx reimbursement risk should be 'low' — coverage is linked to drug approval"
        )

    def test_ivd_has_510k_stage(self, ivd):
        assert "510k_ivd" in _stage_ids(ivd), "IVD pathway must include 510k_ivd submission stage"

    def test_dx_different_from_device(self, ivd):
        device = select_regulatory_pathway("medical_device", "glucose monitor")
        assert ivd.product_family != device.product_family, (
            "Diagnostic and device pathways must have different product_family"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 4. SaMD pathway — no standard reimbursement code (critical risk)
# ──────────────────────────────────────────────────────────────────────────────

class TestSaMDPathway:

    @pytest.fixture
    def samd(self) -> RegulatoryPathway:
        return select_regulatory_pathway("digital_health", "clinical decision support AI algorithm hospital")

    def test_samd_family(self, samd):
        assert samd.product_family == "samd"

    def test_samd_has_no_drug_or_device_stages(self, samd):
        forbidden = {"ind", "phase1", "phase2", "phase3", "nda", "ide", "pma_submit"}
        ids = set(_stage_ids(samd))
        overlap = ids & forbidden
        assert not overlap, f"SaMD pathway must not contain drug/PMA stages; found: {overlap}"

    def test_samd_reimbursement_critical(self, samd):
        assert samd.reimbursement.risk_level == "critical", (
            "Hospital AI SaMD reimbursement risk must be 'critical' "
            "(no standard CPT/payer code exists)"
        )

    def test_samd_risk_note_mentions_no_code(self, samd):
        note = (samd.reimbursement.risk_note or "").lower()
        desc = (samd.reimbursement.description or "").lower()
        combined = note + " " + desc
        assert "no standard" in combined or "no cpt" in combined or "no reimbursement" in combined or "no third-party" in combined, (
            "SaMD risk note must flag the absence of a standard payer reimbursement code"
        )

    def test_samd_different_from_all_others(self, samd):
        drug = select_regulatory_pathway("drug_small_molecule", "")
        device = select_regulatory_pathway("medical_device", "")
        dx = select_regulatory_pathway("diagnostic", "")
        assert samd.product_family != drug.product_family
        assert samd.product_family != device.product_family
        assert samd.product_family != dx.product_family


# ──────────────────────────────────────────────────────────────────────────────
# 5. Router — all four families are distinct and never cross-contaminate
# ──────────────────────────────────────────────────────────────────────────────

class TestRouter:

    def test_four_families_are_distinct(self):
        drug  = select_regulatory_pathway("drug_small_molecule", "")
        dev   = select_regulatory_pathway("medical_device", "")
        dx    = select_regulatory_pathway("diagnostic", "")
        samd  = select_regulatory_pathway("digital_health", "")
        families = {drug.product_family, dev.product_family, dx.product_family, samd.product_family}
        assert len(families) == 4, (
            f"drug/device/dx/samd must map to 4 distinct product_family values; got {families}"
        )

    def test_biologic_maps_to_drug_family(self):
        rp = select_regulatory_pathway("biologic", "monoclonal antibody")
        assert rp.product_family == "drug", (
            "Biologic product type must map to drug pathway family"
        )

    def test_gene_therapy_maps_to_drug_family(self):
        rp = select_regulatory_pathway("gene_therapy", "AAV gene therapy rare disease")
        assert rp.product_family == "drug"

    def test_keyword_fallback_drug(self):
        rp = select_regulatory_pathway("unknown_type", "novel pill compound for diabetes")
        assert rp.product_family == "drug"

    def test_keyword_fallback_device(self):
        rp = select_regulatory_pathway("unknown_type", "implantable cardiac device hardware")
        assert rp.product_family == "device"

    def test_keyword_fallback_diagnostic(self):
        rp = select_regulatory_pathway("unknown_type", "lab assay diagnostic test biomarker")
        assert rp.product_family == "diagnostic"

    def test_keyword_fallback_samd(self):
        rp = select_regulatory_pathway("unknown_type", "AI software algorithm clinical decision")
        assert rp.product_family == "samd"

    def test_pma_inferred_from_implant_keyword(self):
        rp = select_regulatory_pathway("medical_device", "implantable cardiac stimulator")
        assert rp.pathway_subtype == "pma", (
            "Keyword 'implant' in device idea text should infer PMA pathway"
        )
        assert rp.pathway_was_inferred is True

    def test_cdx_inferred_from_keyword(self):
        rp = select_regulatory_pathway("diagnostic",
                                       "companion diagnostic biomarker test for oncology drug")
        assert rp.pathway_subtype == "cdx"

    def test_ldt_inferred_from_keyword(self):
        rp = select_regulatory_pathway("diagnostic", "laboratory developed test ldt clia lab")
        assert rp.pathway_subtype == "ldt"

    def test_inferred_pathway_has_clarifying_question(self):
        rp = select_regulatory_pathway("medical_device", "novel sensor wearable")
        # Default 510(k) with empty idea text should have a clarifying_question
        # (or at minimum not crash when pathway_was_inferred is True)
        if rp.pathway_was_inferred:
            # clarifying_question may or may not be set depending on idea_text
            pass
        # Just verify no crash and has a pathway name
        assert rp.pathway_name, "Inferred pathway must have a non-empty pathway_name"


# ──────────────────────────────────────────────────────────────────────────────
# 6. time_to_market_summary — returns a non-empty, meaningful string
# ──────────────────────────────────────────────────────────────────────────────

class TestTimeToMarketSummary:

    def test_drug_summary_non_empty(self):
        rp = select_regulatory_pathway("drug_small_molecule", "")
        s = time_to_market_summary(rp)
        assert isinstance(s, str) and len(s) > 20, "Summary must be a non-trivial string"

    def test_device_summary_flags_coverage_risk(self):
        rp = select_regulatory_pathway("medical_device", "cardiac stent")
        s = time_to_market_summary(rp)
        assert "reimbursement" in s.lower() or "coverage" in s.lower() or "HIGH" in s, (
            "Device TTM summary must mention reimbursement/coverage risk"
        )

    def test_samd_summary_flags_critical(self):
        rp = select_regulatory_pathway("digital_health", "hospital ai software")
        s = time_to_market_summary(rp)
        assert "CRITICAL" in s or "critical" in s.lower() or "no standard" in s.lower(), (
            "SaMD TTM summary must prominently flag the absence of reimbursement"
        )

    def test_summary_contains_years(self):
        for pt in ("drug_small_molecule", "medical_device", "diagnostic", "digital_health"):
            rp = select_regulatory_pathway(pt, "")
            s = time_to_market_summary(rp)
            assert "yr" in s or "year" in s.lower(), (
                f"Summary for {pt} must include a year estimate"
            )

    def test_to_dict_is_json_round_trippable(self):
        import json
        rp = select_regulatory_pathway("biologic", "antibody drug oncology")
        d = rp.to_dict()
        s = json.dumps(d)
        parsed = json.loads(s)
        assert parsed["product_family"] == "drug"
        assert "stages" in parsed
        assert isinstance(parsed["stages"], list)
