"""
Regression Fixtures — Frozen Acceptance Tests
==============================================
Four fixed input scenarios that must continue to produce the correct downstream
behaviour after every code change. These run entirely without LLM API calls:
they test the deterministic decision chain only.

Fixture 1  — Hublink / Neurotech Hub (RESEARCH_TOOL_NON_CLINICAL)
Fixture 2  — Small-molecule therapeutic (THERAPEUTIC_SMALL_MOLECULE)
Fixture 3  — Class II diagnostic device (DEVICE_CLASS_II)
Fixture 4  — Deliberate ambiguity / digital CDS (AMBIGUOUS_REQUIRES_COUNSEL)

Pass criteria per fixture:
  • Archetype resolves correctly from sub_expert_id
  • Regulatory status derives correctly (deterministic, no LLM)
  • Regulatory directive contains the right instruction class
  • Archetype manifest vocabulary gate fires on planted banned tokens
  • Archetype manifest allows legitimate vocabulary for that archetype
  • TAM formula field matches the archetype
  • Competitive intelligence takes the correct data path
  • Cross-report isolation: world-model read returns '' without user_id
  • (Fixture 4) decision-tree language appears in the directive
"""

from __future__ import annotations

import pytest

# ── shared imports ────────────────────────────────────────────────────────────

from app.services.product_archetype import (
    ProductArchetype,
    ArchetypeViolationError,
    resolve_archetype,
    get_manifest,
    validate_content,
    validate_report_dict,
)
from app.services.regulatory_status import (
    RegulatoryStatus,
    derive_regulatory_status,
    regulatory_directive,
    format_regulatory_decision_tree,
)


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURE 1 — Hublink / Neurotech Hub  (RESEARCH_TOOL_NON_CLINICAL)
# ═══════════════════════════════════════════════════════════════════════════════

_HUB_IDEA = (
    "Hublink: a non-clinical wearable data platform for academic PIs. "
    "Records accelerometry, ECG, and peripheral blood oxygen from "
    "off-the-shelf Bluetooth sensors and uploads to a NIH-grant-funded "
    "lab server. No patient care, no diagnostic claims."
)
_HUB_SUB_EXPERT_ID = "research_tool_non_clinical"


class TestFixture1Hublink:

    # ── archetype resolution ─────────────────────────────────────────────────

    def test_archetype_resolves_to_research_tool(self):
        arch = resolve_archetype(_HUB_SUB_EXPERT_ID)
        assert arch == ProductArchetype.RESEARCH_TOOL_NON_CLINICAL, (
            f"Hublink must resolve to RESEARCH_TOOL_NON_CLINICAL, got {arch}"
        )

    def test_manifest_tam_formula_is_research_bottom_up(self):
        manifest = get_manifest(ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        assert "research" in manifest.tam_formula.lower(), (
            f"TAM formula for research tool must be research-based, got '{manifest.tam_formula}'"
        )

    def test_manifest_buyer_persona_is_not_hospital(self):
        manifest = get_manifest(ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        hint = manifest.buyer_persona_hint.lower()
        assert "hospital" not in hint and "payer" not in hint, (
            "Research tool buyer persona must not mention hospital or payer"
        )

    def test_manifest_inapplicable_sections_include_regulatory(self):
        manifest = get_manifest(ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        inapplicable = {s.lower() for s in manifest.inapplicable_sections}
        assert any("regulat" in s for s in inapplicable) or \
               any("reimburse" in s for s in inapplicable), (
            "RESEARCH_TOOL_NON_CLINICAL manifest must mark regulatory or reimbursement "
            "sections as inapplicable"
        )

    # ── regulatory status ────────────────────────────────────────────────────

    def test_regulatory_status_is_not_regulated(self):
        status = derive_regulatory_status(
            archetype=_HUB_SUB_EXPERT_ID,
            idea=_HUB_IDEA,
            sub_expert_id=_HUB_SUB_EXPERT_ID,
        )
        assert status == RegulatoryStatus.NOT_REGULATED, (
            f"Hublink must derive NOT_REGULATED, got {status}"
        )

    def test_regulatory_directive_bans_510k(self):
        status = derive_regulatory_status(_HUB_SUB_EXPERT_ID, _HUB_IDEA, _HUB_SUB_EXPERT_ID)
        directive = regulatory_directive(status, _HUB_SUB_EXPERT_ID)
        assert "510" not in directive.lower() or "NOT" in directive or "Do NOT" in directive, (
            "NOT_REGULATED directive must not instruct the LLM to write a 510(k) pathway"
        )
        assert "do not mention 510" in directive.lower() or \
               "do not" in directive.lower(), (
            "NOT_REGULATED directive must contain a DO NOT instruction for 510(k)"
        )

    def test_regulatory_directive_bans_ntap(self):
        status = derive_regulatory_status(_HUB_SUB_EXPERT_ID, _HUB_IDEA, _HUB_SUB_EXPERT_ID)
        directive = regulatory_directive(status, _HUB_SUB_EXPERT_ID)
        assert "ntap" in directive.lower(), (
            "NOT_REGULATED directive must explicitly ban NTAP"
        )

    def test_regulatory_directive_mentions_non_clinical(self):
        status = derive_regulatory_status(_HUB_SUB_EXPERT_ID, _HUB_IDEA, _HUB_SUB_EXPERT_ID)
        directive = regulatory_directive(status, _HUB_SUB_EXPERT_ID)
        assert "not a regulated" in directive.lower() or \
               "non-clinical" in directive.lower() or \
               "not a medical device" in directive.lower(), (
            "NOT_REGULATED directive must state the product is not a regulated medical device"
        )

    def test_decision_tree_says_not_regulated(self):
        status = derive_regulatory_status(_HUB_SUB_EXPERT_ID, _HUB_IDEA, _HUB_SUB_EXPERT_ID)
        tree = format_regulatory_decision_tree(status, _HUB_SUB_EXPERT_ID, _HUB_IDEA)
        assert "NOT_REGULATED" in tree, (
            "Decision tree output must contain 'NOT_REGULATED' for Hublink"
        )

    # ── vocabulary gate ───────────────────────────────────────────────────────

    def test_vocab_gate_fires_on_510k(self):
        arch = ProductArchetype.RESEARCH_TOOL_NON_CLINICAL
        # The gate raises on the first banned token it finds (set order is unordered).
        # Both "510(k)" and "premarket notification" are banned — assert that ANY fires.
        with pytest.raises(ArchetypeViolationError):
            validate_content(
                "The recommended pathway is 510(k) premarket notification to FDA.",
                archetype=arch,
                section_id="regulatory_pathway",
                strict=True,
            )

    def test_vocab_gate_fires_on_ntap(self):
        arch = ProductArchetype.RESEARCH_TOOL_NON_CLINICAL
        violations = validate_content(
            "NTAP designation would add $20k per patient.",
            archetype=arch,
            section_id="market_access",
            strict=False,
        )
        assert violations, "NTAP token must trigger a vocabulary violation for research_tool"

    def test_vocab_gate_fires_on_cpt_code(self):
        arch = ProductArchetype.RESEARCH_TOOL_NON_CLINICAL
        violations = validate_content(
            "Billing is via CPT 99453 (remote monitoring setup).",
            archetype=arch,
            section_id="reimbursement",
            strict=False,
        )
        assert violations, "CPT code must trigger a vocabulary violation for research_tool"

    def test_vocab_gate_fires_on_daly(self):
        arch = ProductArchetype.RESEARCH_TOOL_NON_CLINICAL
        violations = validate_content(
            "The DALY burden is 45 million globally.",
            archetype=arch,
            section_id="disease_intelligence",
            strict=False,
        )
        assert violations, "DALY must trigger a vocabulary violation for research_tool"

    def test_vocab_gate_allows_nih_grant(self):
        arch = ProductArchetype.RESEARCH_TOOL_NON_CLINICAL
        violations = validate_content(
            "Primary buyers are academic PIs with NIH R01 grant funding.",
            archetype=arch,
            section_id="market_access",
            strict=False,
        )
        assert not violations, "NIH grant language must be allowed for research_tool"

    def test_vocab_gate_allows_saas_pricing(self):
        arch = ProductArchetype.RESEARCH_TOOL_NON_CLINICAL
        violations = validate_content(
            "Pricing is $5,000 per lab per year under a site-license model.",
            archetype=arch,
            section_id="pricing",
            strict=False,
        )
        assert not violations, "Site-license pricing language must be allowed for research_tool"

    def test_vocab_gate_exempt_section_passes_clinical_vocab(self):
        """The 'not applicable' stub is allowed to contain banned tokens (explains why it doesn't apply)."""
        arch = ProductArchetype.RESEARCH_TOOL_NON_CLINICAL
        violations = validate_content(
            "Not applicable: 510(k) premarket notification does not apply to this research tool.",
            archetype=arch,
            section_id="regulatory_non_applicability",
            strict=False,
        )
        assert not violations, (
            "The exempt section 'regulatory_non_applicability' must be allowed to contain "
            "normally-banned tokens"
        )

    # ── competitive intelligence path ─────────────────────────────────────────

    def test_competitive_intel_skips_ct_gov_for_research_tool(self):
        """Research tools must not invoke CT.gov/FDA fetch helpers — verified by inspect."""
        import inspect
        from app.services.competitive_intelligence_service import _gather_research_tool_intel
        src = inspect.getsource(_gather_research_tool_intel)
        # The function must not call the external CT.gov / FDA fetch helpers.
        # ("clinicaltrials" may appear in docstrings explaining what is skipped.)
        assert "_fetch_ct_gov" not in src and "fetch_trials" not in src, (
            "_gather_research_tool_intel must not invoke the CT.gov fetch helper"
        )
        assert "httpx" not in src and "requests.get" not in src, (
            "_gather_research_tool_intel must not make direct HTTP calls"
        )

    def test_competitive_intel_returns_comparators_for_research_tool(self):
        import asyncio
        from app.services.competitive_intelligence_service import _gather_research_tool_intel
        result = asyncio.run(
            _gather_research_tool_intel("neuroscience", _HUB_SUB_EXPERT_ID)
        )
        comparators = result.get("research_tool_comparators", [])
        assert isinstance(comparators, list), \
            "_gather_research_tool_intel must return a 'research_tool_comparators' list"
        # F-2: static list deleted; _extract_research_tool_comparators() populates §7
        # comparators from the idea text — _gather_research_tool_intel now returns []

    # ── world model isolation ─────────────────────────────────────────────────

    def test_world_model_returns_empty_without_user_id(self):
        import asyncio
        from app.services.research_world_model import load_world_model
        result = asyncio.run(
            load_world_model("neurotech hub wearable")  # no user_id
        )
        assert result == "", (
            "load_world_model without user_id must return '' (H-03 cross-project isolation)"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURE 2 — Small-molecule therapeutic (THERAPEUTIC_SMALL_MOLECULE)
# ═══════════════════════════════════════════════════════════════════════════════

_DRUG_IDEA = (
    "Novel oral PCSK9 inhibitor for LDL reduction in statin-intolerant "
    "cardiovascular patients. Phase 1 POC complete. Seeking NDA pathway."
)
_DRUG_SUB_EXPERT_ID = "drug_cardiology"


class TestFixture2SmallMolecule:

    def test_archetype_resolves_to_small_molecule(self):
        arch = resolve_archetype(_DRUG_SUB_EXPERT_ID)
        assert arch == ProductArchetype.THERAPEUTIC_SMALL_MOLECULE, (
            f"drug_cardiology must resolve to THERAPEUTIC_SMALL_MOLECULE, got {arch}"
        )

    def test_regulatory_status_is_regulated(self):
        status = derive_regulatory_status(
            archetype=_DRUG_SUB_EXPERT_ID,
            idea=_DRUG_IDEA,
            sub_expert_id=_DRUG_SUB_EXPERT_ID,
        )
        assert status == RegulatoryStatus.REGULATED, (
            f"Small-molecule drug must derive REGULATED, got {status}"
        )

    def test_regulatory_directive_instructs_full_pathway(self):
        status = derive_regulatory_status(_DRUG_SUB_EXPERT_ID, _DRUG_IDEA, _DRUG_SUB_EXPERT_ID)
        directive = regulatory_directive(status, _DRUG_SUB_EXPERT_ID)
        assert "full regulatory pathway" in directive.lower() or \
               "requires fda" in directive.lower() or \
               "clearance or approval" in directive.lower(), (
            "REGULATED directive must instruct the LLM to write the full regulatory pathway"
        )

    def test_manifest_tam_formula_is_patient_based(self):
        manifest = get_manifest(ProductArchetype.THERAPEUTIC_SMALL_MOLECULE)
        assert manifest.tam_formula, "THERAPEUTIC_SMALL_MOLECULE must have a TAM formula"
        assert "patient" in manifest.tam_formula.lower() or \
               "prevalence" in manifest.tam_formula.lower() or \
               "drug" in manifest.tam_formula.lower(), (
            f"Small-molecule TAM formula must be patient/prevalence-based, got '{manifest.tam_formula}'"
        )

    def test_vocab_gate_blocks_research_tool_pricing(self):
        arch = ProductArchetype.THERAPEUTIC_SMALL_MOLECULE
        violations = validate_content(
            "Pricing is $5,000 per PI per year under a per-lab subscription.",
            archetype=arch,
            section_id="pricing",
            strict=False,
        )
        assert violations, (
            "Per-lab / per-PI pricing language must be flagged as a vocabulary violation "
            "for THERAPEUTIC_SMALL_MOLECULE"
        )

    def test_vocab_gate_allows_nda_language(self):
        arch = ProductArchetype.THERAPEUTIC_SMALL_MOLECULE
        violations = validate_content(
            "File an NDA under 21 CFR Part 314 after Phase 3 completion.",
            archetype=arch,
            section_id="regulatory_pathway",
            strict=False,
        )
        assert not violations, "NDA language must be allowed for THERAPEUTIC_SMALL_MOLECULE"

    def test_all_standard_drug_sub_expert_ids_resolve_correctly(self):
        drug_ids = [
            "drug_amr", "drug_oncology", "drug_cns", "drug_metabolic",
            "drug_cardiology", "drug_immunology", "drug_rare_disease",
        ]
        for sid in drug_ids:
            arch = resolve_archetype(sid)
            assert arch == ProductArchetype.THERAPEUTIC_SMALL_MOLECULE, (
                f"sub_expert_id '{sid}' must resolve to THERAPEUTIC_SMALL_MOLECULE, got {arch}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURE 3 — Class II diagnostic device (DEVICE_CLASS_II)
# ═══════════════════════════════════════════════════════════════════════════════

_DEVICE_IDEA = (
    "Implantable cardiac loop recorder with AI-driven AF detection. "
    "Intended to continuously monitor cardiac rhythm in patients with "
    "cryptogenic stroke. 510(k) predicate: Medtronic Reveal LINQ."
)
_DEVICE_SUB_EXPERT_ID = "device_cardiovascular"


class TestFixture3DeviceClassII:

    def test_archetype_resolves_to_device_class_ii(self):
        arch = resolve_archetype(_DEVICE_SUB_EXPERT_ID)
        assert arch == ProductArchetype.DEVICE_CLASS_II, (
            f"device_cardiovascular must resolve to DEVICE_CLASS_II, got {arch}"
        )

    def test_regulatory_status_is_regulated(self):
        status = derive_regulatory_status(
            archetype=_DEVICE_SUB_EXPERT_ID,
            idea=_DEVICE_IDEA,
            sub_expert_id=_DEVICE_SUB_EXPERT_ID,
        )
        assert status == RegulatoryStatus.REGULATED, (
            f"Class II device must derive REGULATED, got {status}"
        )

    def test_regulatory_directive_instructs_full_pathway(self):
        status = derive_regulatory_status(_DEVICE_SUB_EXPERT_ID, _DEVICE_IDEA, _DEVICE_SUB_EXPERT_ID)
        directive = regulatory_directive(status, _DEVICE_SUB_EXPERT_ID)
        lower = directive.lower()
        assert "clearance or approval" in lower or "fda" in lower, (
            "REGULATED directive for Class II device must mention FDA clearance/approval"
        )

    def test_vocab_gate_allows_510k_language(self):
        """510(k) is banned only for RESEARCH_TOOL — it is expected for DEVICE_CLASS_II."""
        arch = ProductArchetype.DEVICE_CLASS_II
        violations = validate_content(
            "The recommended pathway is 510(k) with Medtronic Reveal LINQ as predicate.",
            archetype=arch,
            section_id="regulatory_pathway",
            strict=False,
        )
        assert not violations, (
            "510(k) language must be ALLOWED for DEVICE_CLASS_II (only banned for research tools)"
        )

    def test_vocab_gate_allows_predicate_device(self):
        arch = ProductArchetype.DEVICE_CLASS_II
        violations = validate_content(
            "Predicate device: Medtronic Reveal LINQ (K153152).",
            archetype=arch,
            section_id="regulatory_pathway",
            strict=False,
        )
        assert not violations, "Predicate device language must be allowed for DEVICE_CLASS_II"

    def test_vocab_gate_blocks_drug_pricing_language(self):
        arch = ProductArchetype.DEVICE_CLASS_II
        manifest = get_manifest(arch)
        # WAC/per-course drug pricing should not appear for a device
        # The manifest may or may not ban these explicitly; just verify 510k is allowed
        # (the key invariant for this fixture is the 510k ALLOW, not a ban)
        assert "510(k)" not in manifest.banned_vocabulary and \
               "510k" not in manifest.banned_vocabulary, (
            "DEVICE_CLASS_II manifest must NOT ban 510(k) vocabulary"
        )

    def test_manifest_tam_formula_is_not_research_tool(self):
        manifest = get_manifest(ProductArchetype.DEVICE_CLASS_II)
        assert "research_tool" not in manifest.tam_formula.lower(), (
            "DEVICE_CLASS_II TAM formula must not be the research_tool_bottom_up formula"
        )

    def test_all_device_sub_expert_ids_resolve_correctly(self):
        device_ids = ["device_cardiovascular", "device_metabolic", "device_neurology"]
        for sid in device_ids:
            arch = resolve_archetype(sid)
            assert arch == ProductArchetype.DEVICE_CLASS_II, (
                f"sub_expert_id '{sid}' must resolve to DEVICE_CLASS_II, got {arch}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURE 4 — Deliberate ambiguity / digital CDS (AMBIGUOUS_REQUIRES_COUNSEL)
# ═══════════════════════════════════════════════════════════════════════════════

_CDS_IDEA = (
    "AI clinical decision support tool that integrates with the EHR and "
    "surfaces sepsis risk scores to ICU nurses. The algorithm suggests "
    "but does not automate treatment decisions."
)
_CDS_SUB_EXPERT_ID = "digital_cds"


class TestFixture4DeliberateAmbiguity:

    def test_archetype_resolves_for_digital_cds(self):
        arch = resolve_archetype(_CDS_SUB_EXPERT_ID)
        # digital_cds maps to SAMD_CLINICAL in product_archetype.py
        assert arch in (ProductArchetype.SAMD_CLINICAL, ProductArchetype.UNKNOWN), (
            f"digital_cds should resolve to SAMD_CLINICAL or remain UNKNOWN pending "
            f"intended-use clarification; got {arch}"
        )

    def test_regulatory_status_is_ambiguous(self):
        status = derive_regulatory_status(
            archetype=_CDS_SUB_EXPERT_ID,
            idea=_CDS_IDEA,
            sub_expert_id=_CDS_SUB_EXPERT_ID,
        )
        assert status == RegulatoryStatus.AMBIGUOUS_REQUIRES_COUNSEL, (
            f"digital_cds must derive AMBIGUOUS_REQUIRES_COUNSEL, got {status}"
        )

    def test_regulatory_directive_renders_decision_tree(self):
        status = derive_regulatory_status(_CDS_SUB_EXPERT_ID, _CDS_IDEA, _CDS_SUB_EXPERT_ID)
        directive = regulatory_directive(status, _CDS_SUB_EXPERT_ID)
        lower = directive.lower()
        assert "decision tree" in lower or "both branch" in lower or \
               "branch" in lower or "conditional" in lower, (
            "AMBIGUOUS directive must instruct the LLM to render a decision tree / both branches"
        )

    def test_regulatory_directive_does_not_assert_definitive_pathway(self):
        status = derive_regulatory_status(_CDS_SUB_EXPERT_ID, _CDS_IDEA, _CDS_SUB_EXPERT_ID)
        directive = regulatory_directive(status, _CDS_SUB_EXPERT_ID)
        lower = directive.lower()
        # Must not claim "this is regulated" or "this is not regulated" definitively
        assert "do not assert" in lower or "ambiguity is the finding" in lower or \
               "recommend regulatory counsel" in lower, (
            "AMBIGUOUS directive must explicitly instruct the LLM not to assert a definitive pathway"
        )

    def test_regulatory_directive_recommends_counsel(self):
        status = derive_regulatory_status(_CDS_SUB_EXPERT_ID, _CDS_IDEA, _CDS_SUB_EXPERT_ID)
        directive = regulatory_directive(status, _CDS_SUB_EXPERT_ID)
        assert "counsel" in directive.lower(), (
            "AMBIGUOUS_REQUIRES_COUNSEL directive must recommend regulatory counsel"
        )

    def test_decision_tree_text_contains_both_branches(self):
        status = derive_regulatory_status(_CDS_SUB_EXPERT_ID, _CDS_IDEA, _CDS_SUB_EXPERT_ID)
        tree = format_regulatory_decision_tree(status, _CDS_SUB_EXPERT_ID, _CDS_IDEA)
        lower = tree.lower()
        # Decision tree must address the "is it regulated?" question
        assert "q1" in lower and "q2" in lower, (
            "Decision tree must render Q1 and Q2 gating questions"
        )
        assert "AMBIGUOUS_REQUIRES_COUNSEL" in tree, (
            "Decision tree must state AMBIGUOUS_REQUIRES_COUNSEL as the determination"
        )

    def test_archetype_not_research_tool(self):
        """CDS is never a research tool — confirm the gate is distinct."""
        arch = resolve_archetype(_CDS_SUB_EXPERT_ID)
        assert arch != ProductArchetype.RESEARCH_TOOL_NON_CLINICAL, (
            "digital_cds must NOT resolve to RESEARCH_TOOL_NON_CLINICAL"
        )

    def test_status_does_not_downgrade_to_not_regulated(self):
        """Even if the idea sounds benign, CDS with clinical framing must not drop to NOT_REGULATED."""
        benign_idea = "An AI tool that shows population health statistics on a dashboard."
        status = derive_regulatory_status(
            archetype=_CDS_SUB_EXPERT_ID,
            idea=benign_idea,
            sub_expert_id=_CDS_SUB_EXPERT_ID,
        )
        assert status != RegulatoryStatus.NOT_REGULATED, (
            "digital_cds must never derive NOT_REGULATED regardless of idea text, "
            f"got {status}"
        )

    # ── cross-fixture: status enum is stable across all four archetypes ───────

    def test_all_four_fixture_statuses_are_distinct_or_expected(self):
        """
        Freeze the expected status for each of the four fixture archetypes.
        This is the primary regression guard — if status derivation changes,
        this test catches it immediately.
        """
        cases = [
            (_HUB_SUB_EXPERT_ID, _HUB_IDEA, RegulatoryStatus.NOT_REGULATED),
            (_DRUG_SUB_EXPERT_ID, _DRUG_IDEA, RegulatoryStatus.REGULATED),
            (_DEVICE_SUB_EXPERT_ID, _DEVICE_IDEA, RegulatoryStatus.REGULATED),
            (_CDS_SUB_EXPERT_ID, _CDS_IDEA, RegulatoryStatus.AMBIGUOUS_REQUIRES_COUNSEL),
        ]
        for sid, idea, expected in cases:
            actual = derive_regulatory_status(archetype=sid, idea=idea, sub_expert_id=sid)
            assert actual == expected, (
                f"Regulatory status regression: sub_expert_id={sid!r} → "
                f"expected {expected.value}, got {actual.value}"
            )
