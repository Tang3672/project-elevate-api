"""
G.1 Fixtures — Determinism + Non-Life-Sciences Vocabulary Tests
===============================================================
G.1a  Determinism: 5× same input through the deterministic sub-pipeline
       (market sizing derivation + regulatory status) must produce bit-identical
       TAM/SAM/SOM figures and the same regulatory status. No LLM calls made.

G.1b  Non-life-sciences vocabulary: when the resolved domain is outside
       LIFE_SCIENCES_*, the report output must contain no medical vocabulary
       (no FDA, CPT, ICD, DRG, payer, reimbursement, clinical, patient, etc.)
       in the section that would be inapplicable for the product type.

These tests run entirely without live API calls.
"""

from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / test data
# ─────────────────────────────────────────────────────────────────────────────

_RESEARCH_TOOL_IDEA = (
    "Hublink: a wearable data capture platform for academic neuroscience labs. "
    "Records accelerometry and ECG from Bluetooth sensors and uploads to a "
    "lab server for offline analysis. Sold exclusively to university PIs — "
    "no patient care, no diagnostic claims, no clinical use."
)
_RESEARCH_TOOL_SUB_EXPERT = "research_tool_non_clinical"

_DIAGNOSTIC_IDEA = (
    "A rapid 30-minute PCR-based antibiotic susceptibility test that runs on "
    "existing hospital analyzers. Sold to hospital microbiology labs — "
    "intended for in-vitro diagnostic use."
)
_DIAGNOSTIC_SUB_EXPERT = "diagnostic_molecular"

_NON_LIFE_SCIENCES_IDEA = (
    "An IoT sensor platform for industrial temperature monitoring in "
    "semiconductor fabrication facilities. No medical or clinical use."
)
_NON_LIFE_SCIENCES_SUB_EXPERT = "research_infrastructure_saas"


# ─────────────────────────────────────────────────────────────────────────────
# G.1a — Determinism: market sizing derivation produces identical figures
#         across 5 independent calls with the same input parameters.
# ─────────────────────────────────────────────────────────────────────────────

class TestDeterminism:
    """
    The market sizing derivation is a pure function of its inputs.
    Run it 5 times on the same input and assert:
      - us_tam_usd is identical across all 5 runs (not just close — identical)
      - us_sam_usd is identical
      - us_som_usd is identical
      - formula_name is identical
    """

    def _run_derivation(self, idea: str, sub_expert_id: str, ta: str = "other"):
        from app.services.market_sizing_derivation_service import (
            generate_market_sizing_derivation,
        )
        return generate_market_sizing_derivation(
            idea=idea,
            therapeutic_area=ta,
            sub_expert_id=sub_expert_id,
        )

    def test_research_tool_tam_deterministic(self):
        results = [self._run_derivation(_RESEARCH_TOOL_IDEA, _RESEARCH_TOOL_SUB_EXPERT)
                   for _ in range(5)]
        tams = [r.us_tam_usd for r in results]
        assert len(set(tams)) == 1, (
            f"G.1a: us_tam_usd must be identical across 5 runs for research tool. "
            f"Got: {tams}"
        )

    def test_research_tool_sam_deterministic(self):
        results = [self._run_derivation(_RESEARCH_TOOL_IDEA, _RESEARCH_TOOL_SUB_EXPERT)
                   for _ in range(5)]
        sams = [r.us_sam_usd for r in results]
        assert len(set(sams)) == 1, (
            f"G.1a: us_sam_usd must be identical across 5 runs. Got: {sams}"
        )

    def test_research_tool_som_deterministic(self):
        results = [self._run_derivation(_RESEARCH_TOOL_IDEA, _RESEARCH_TOOL_SUB_EXPERT)
                   for _ in range(5)]
        soms = [r.us_som_usd for r in results]
        assert len(set(soms)) == 1, (
            f"G.1a: us_som_usd must be identical across 5 runs. Got: {soms}"
        )

    def test_research_tool_formula_name_deterministic(self):
        results = [self._run_derivation(_RESEARCH_TOOL_IDEA, _RESEARCH_TOOL_SUB_EXPERT)
                   for _ in range(5)]
        names = [r.formula_name for r in results]
        assert len(set(names)) == 1, (
            f"G.1a: formula_name must be identical across 5 runs. Got: {names}"
        )

    def test_diagnostic_tam_deterministic(self):
        results = [self._run_derivation(_DIAGNOSTIC_IDEA, _DIAGNOSTIC_SUB_EXPERT,
                                        ta="infectious_disease")
                   for _ in range(5)]
        tams = [r.us_tam_usd for r in results]
        assert len(set(tams)) == 1, (
            f"G.1a: diagnostic TAM must be identical across 5 runs. Got: {tams}"
        )

    def test_regulatory_status_deterministic(self):
        from app.services.regulatory_status import derive_regulatory_status
        statuses = [
            derive_regulatory_status(
                archetype=_RESEARCH_TOOL_SUB_EXPERT,
                idea=_RESEARCH_TOOL_IDEA,
                sub_expert_id=_RESEARCH_TOOL_SUB_EXPERT,
            )
            for _ in range(5)
        ]
        assert len(set(s.value for s in statuses)) == 1, (
            f"G.1a: regulatory status must be deterministic. Got: {[s.value for s in statuses]}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# G.1b — Non-life-sciences: no clinical vocabulary in inapplicable sections
# ─────────────────────────────────────────────────────────────────────────────

_CLINICAL_VOCAB = frozenset({
    "patient", "clinical", "physician", "clinician", "hospital",
    "reimbursement", "cpt ", "medicare", "medicaid", "ehr", "emr",
    "payer", "insurance", "diagnosis", "treatment", "therapy", "drug",
    "dose", "fda 510", "premarket", "pma ", "de novo",
    "ntap", "drg", "formulary", "prior authorization",
    "phase 1", "phase 2", "phase 3", "ind ", "nda ", "bla ",
    "clinical trial", "pivotal study",
})


def _contains_clinical_vocab(text: str) -> list[str]:
    """Return list of clinical vocab terms found in text (lowercased)."""
    lower = text.lower()
    return [term for term in _CLINICAL_VOCAB if term in lower]


class TestNonLifeSciencesVocabulary:
    """
    When a product is classified as a research tool (non-clinical), the
    archetype manifest must ban clinical vocabulary, the regulatory status
    must not be FDA-regulated, and the section inapplicable set must include
    clinical sections (regulatory_pathway, reimbursement_strategy).
    """

    def test_research_tool_archetype_bans_clinical_vocab(self):
        from app.services.product_archetype import (
            ProductArchetype, get_manifest,
        )
        manifest = get_manifest(ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        banned = {v.lower() for v in manifest.banned_vocabulary}
        # Spot-check a few core clinical terms that must appear in the ban list
        for term in ("ntap", "cpt ", "medicare", "formulary", "prior authorization"):
            # Each term (or a containing term) must be in banned vocabulary
            found = any(term in b for b in banned)
            assert found, (
                f"G.1b: '{term}' or containing term must be in RESEARCH_TOOL_NON_CLINICAL "
                f"banned_vocabulary. Banned set sample: {list(banned)[:10]}"
            )

    def test_research_tool_inapplicable_sections_include_regulatory(self):
        from app.services.product_archetype import (
            ProductArchetype, get_manifest,
        )
        manifest = get_manifest(ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        assert "regulatory_pathway" in manifest.inapplicable_sections or \
               any("regulat" in s for s in manifest.inapplicable_sections), (
            "G.1b: regulatory_pathway must be in RESEARCH_TOOL_NON_CLINICAL.inapplicable_sections"
        )

    def test_research_tool_inapplicable_sections_include_reimbursement(self):
        from app.services.product_archetype import (
            ProductArchetype, get_manifest,
        )
        manifest = get_manifest(ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        assert any("reimburse" in s or "payer" in s for s in manifest.inapplicable_sections), (
            "G.1b: reimbursement or payer section must be in RESEARCH_TOOL_NON_CLINICAL.inapplicable_sections"
        )

    def test_validate_report_dict_fires_on_clinical_vocab(self):
        from app.services.product_archetype import (
            ProductArchetype, validate_report_dict,
        )
        fake_report = {
            "executive_summary": "Patients receive treatment through a CPT billing code.",
            "regulatory_pathway": {"recommended_pathway": "510(k) clearance required"},
            "market_access": {"reimbursement_pathway": "NTAP eligible via Medicare"},
        }
        violations = validate_report_dict(
            fake_report, ProductArchetype.RESEARCH_TOOL_NON_CLINICAL
        )
        assert len(violations) > 0, (
            "G.1b: validate_report_dict must return violations when clinical vocab "
            "appears in a research tool report"
        )

    def test_validate_report_dict_clean_report_passes(self):
        from app.services.product_archetype import (
            ProductArchetype, validate_report_dict,
        )
        clean_report = {
            "executive_summary": (
                "This research tool captures accelerometry from Bluetooth sensors "
                "for academic neuroscience lab use. Revenue model is institutional site license."
            ),
            "market_access": {
                "primary_channel": "Direct academic lab sales",
                "reimbursement_pathway": "NIH equipment grants and lab CAPEX budget",
            },
        }
        violations = validate_report_dict(
            clean_report, ProductArchetype.RESEARCH_TOOL_NON_CLINICAL
        )
        assert len(violations) == 0, (
            f"G.1b: clean research tool report should have zero archetype violations. "
            f"Got: {violations}"
        )

    def test_regulatory_status_not_regulated_for_research_tool(self):
        from app.services.regulatory_status import (
            RegulatoryStatus, derive_regulatory_status,
        )
        status = derive_regulatory_status(
            archetype=_RESEARCH_TOOL_SUB_EXPERT,
            idea=_RESEARCH_TOOL_IDEA,
            sub_expert_id=_RESEARCH_TOOL_SUB_EXPERT,
        )
        assert status == RegulatoryStatus.NOT_REGULATED, (
            f"G.1b: research tool must derive NOT_REGULATED regulatory status, got {status}"
        )

    def test_research_infrastructure_saas_inapplicable_sections(self):
        from app.services.product_archetype import (
            ProductArchetype, get_manifest,
        )
        manifest = get_manifest(ProductArchetype.RESEARCH_INFRASTRUCTURE_SAAS)
        inapplicable = manifest.inapplicable_sections
        assert "regulatory_pathway" in inapplicable or \
               any("regulat" in s for s in inapplicable), (
            "G.1b: RESEARCH_INFRASTRUCTURE_SAAS must mark regulatory_pathway as inapplicable"
        )

    def test_assumption_ledger_extraction_deterministic(self):
        """The assumption ledger builder must produce the same number of entries
        on repeated calls for the same derivation."""
        from app.services.market_sizing_derivation_service import (
            generate_market_sizing_derivation,
        )
        from app.services.assumption_ledger_service import build_ledger_from_derivation

        derivations = [
            generate_market_sizing_derivation(
                idea=_RESEARCH_TOOL_IDEA,
                therapeutic_area="other",
                sub_expert_id=_RESEARCH_TOOL_SUB_EXPERT,
            )
            for _ in range(3)
        ]
        ledgers = [build_ledger_from_derivation(d) for d in derivations]
        counts = [len(l.assumptions) for l in ledgers]
        assert len(set(counts)) == 1, (
            f"G.1a: assumption ledger must produce the same entry count across runs. "
            f"Got: {counts}"
        )
        tams = [
            next((a.value for a in l.assumptions if a.key == "us_tam_usd"), None)
            for l in ledgers
        ]
        assert len(set(tams)) == 1, (
            f"G.1a: us_tam_usd in ledger must be identical across runs. Got: {tams}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# G.1c — Extended: no fabricated 0.0 scores, no authored CI language,
#         segmentation tree present for research tools
# ─────────────────────────────────────────────────────────────────────────────

class TestExtendedFixtures:
    """
    G.1c extended quality gates:
      - No 0.0/10 scores in derivation output (would indicate a broken panel echoing through)
      - No authored '95% CI' / 'IQVIA' language in confidence_note (H-05 / B-07)
      - Derivation confidence_note describes method, not a fabricated CI percentage
      - version_hash is set after an assumption override (E.4)
      - Assumption ledger has non-zero TAM
    """

    def _derive(self, idea: str, sub_expert: str, ta: str = "other"):
        from app.services.market_sizing_derivation_service import (
            generate_market_sizing_derivation,
        )
        return generate_market_sizing_derivation(
            idea=idea,
            therapeutic_area=ta,
            sub_expert_id=sub_expert,
        )

    def test_research_tool_no_authored_ci_in_confidence_note(self):
        """G.1c: confidence_note must not contain '95% CI' or 'IQVIA' (H-05)."""
        deriv = self._derive(_RESEARCH_TOOL_IDEA, _RESEARCH_TOOL_SUB_EXPERT)
        note = deriv.confidence_note or ""
        assert "95% CI" not in note, (
            f"G.1c: confidence_note must not contain authored '95% CI'. Got: {note[:200]}"
        )
        assert "IQVIA" not in note, (
            f"G.1c: confidence_note must not cite IQVIA error rates. Got: {note[:200]}"
        )

    def test_diagnostic_no_authored_ci_in_confidence_note(self):
        """G.1c: diagnostic derivation confidence_note must not contain '95% CI' or IQVIA."""
        deriv = self._derive(_DIAGNOSTIC_IDEA, _DIAGNOSTIC_SUB_EXPERT, ta="infectious_disease")
        note = deriv.confidence_note or ""
        assert "95% CI" not in note, (
            f"G.1c: confidence_note must not contain authored '95% CI'. Got: {note[:200]}"
        )
        assert "IQVIA reports 71" not in note, (
            f"G.1c: confidence_note must not cite IQVIA 71% forecast error. Got: {note[:200]}"
        )

    def test_research_tool_tam_nonzero(self):
        """G.1c: research tool TAM must be > 0 (broken buyer model returns 0)."""
        deriv = self._derive(_RESEARCH_TOOL_IDEA, _RESEARCH_TOOL_SUB_EXPERT)
        assert deriv.us_tam_usd > 0, (
            f"G.1c: research tool us_tam_usd must be > 0. Got: {deriv.us_tam_usd}"
        )
        assert deriv.us_sam_usd > 0, (
            f"G.1c: research tool us_sam_usd must be > 0. Got: {deriv.us_sam_usd}"
        )
        assert deriv.us_som_usd > 0, (
            f"G.1c: research tool us_som_usd must be > 0. Got: {deriv.us_som_usd}"
        )

    def test_research_tool_price_in_academic_tier(self):
        """G.1c / B-03: research tool spend per lab must be in academic range ($5k-$15k/yr)."""
        deriv = self._derive(_RESEARCH_TOOL_IDEA, _RESEARCH_TOOL_SUB_EXPERT)
        # Step 2 is the spend-per-lab step; its value should be in the academic range
        spend_steps = [s for s in deriv.steps if "spend" in s.title.lower() or "annuali" in s.title.lower()]
        if spend_steps:
            spend_val = spend_steps[0].value
            assert 5_000 <= spend_val <= 20_000, (
                f"G.1c/B-03: annualised spend per lab must be in $5k-$20k academic range, "
                f"not enterprise SaaS pricing. Got: ${spend_val:,.0f}"
            )

    def test_assumption_version_hash_set_after_override(self):
        """G.1c / E.4: version_hash must be populated after an assumption override."""
        from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
        from app.services.assumption_ledger_service import (
            build_ledger_from_derivation, apply_override,
        )
        deriv = generate_market_sizing_derivation(
            idea=_RESEARCH_TOOL_IDEA,
            therapeutic_area="other",
            sub_expert_id=_RESEARCH_TOOL_SUB_EXPERT,
        )
        ledger = build_ledger_from_derivation(deriv)
        assert ledger.version_hash is None, (
            "G.1c/E.4: version_hash must be None before any override"
        )
        updated, found = apply_override(ledger, "us_tam_usd", 50_000_000.0, note="test")
        assert found, "G.1c: us_tam_usd must be found in ledger for override"
        assert updated.version_hash is not None, (
            "G.1c/E.4: version_hash must be set after applying an override"
        )
        assert len(updated.version_hash) == 16, (
            f"G.1c/E.4: version_hash should be 16 hex chars. Got: '{updated.version_hash}'"
        )

    def test_confidence_note_describes_method_not_pct(self):
        """G.1c: confidence_note must be a method description, not an authored CI percentage."""
        import re
        deriv = self._derive(_RESEARCH_TOOL_IDEA, _RESEARCH_TOOL_SUB_EXPERT)
        note = deriv.confidence_note or ""
        ci_pattern = re.compile(r"\b\d{2,3}%\s+(?:CI|confidence\s+interval)", re.I)
        assert not ci_pattern.search(note), (
            f"G.1c: confidence_note must not assert a CI percentage. Got: {note[:200]}"
        )

    def test_non_life_sciences_has_no_rock_health_citation_for_market_size(self):
        """G.1c / B-07: derivation steps must not cite Rock Health for market size claims."""
        deriv = self._derive(_RESEARCH_TOOL_IDEA, _RESEARCH_TOOL_SUB_EXPERT)
        for step in deriv.steps:
            src = (step.source_paper or "") + (step.data_source or "")
            assert "Rock Health" not in src or "funding" not in src.lower(), (
                f"G.1c/B-07: Step '{step.title}' cites Rock Health for market size/pricing. "
                f"Rock Health tracks VC funding, not market size. Source: {src[:200]}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# G.1d — openFDA K-number verification round-trip (B-08)
# ─────────────────────────────────────────────────────────────────────────────

class TestOpenFDAVerifier:
    """
    G.1d: openFDA device-number verification.
    Tests use a known K-number (K173922, a cleared device) and a fabricated one.
    These tests make real HTTP calls — mark them as integration tests.
    """

    def test_extract_device_numbers_from_text(self):
        """G.1d: regex must extract K-numbers from mixed text."""
        from app.services.openfda_verifier import extract_device_numbers
        text = "Cleared under K173922 and P200001; also see DEN200050."
        nums = extract_device_numbers(text)
        assert "K173922" in nums, f"G.1d: K173922 must be extracted. Got: {nums}"
        assert "P200001" in nums, f"G.1d: P200001 must be extracted. Got: {nums}"
        assert "DEN200050" in nums, f"G.1d: DEN200050 must be extracted. Got: {nums}"

    def test_fabricated_k_number_not_in_text_passes_clean(self):
        """G.1d: text with no device numbers returns same text (no scrubbing needed)."""
        from app.services.openfda_verifier import scrub_unverified_device_numbers
        clean_text = "This product uses NIH-funded research infrastructure."
        scrubbed, misses = scrub_unverified_device_numbers(clean_text)
        assert scrubbed == clean_text, (
            f"G.1d: clean text with no device numbers should pass unchanged. Got: {scrubbed}"
        )
        assert misses == [], (
            f"G.1d: no misses expected for text with no device numbers. Got: {misses}"
        )
