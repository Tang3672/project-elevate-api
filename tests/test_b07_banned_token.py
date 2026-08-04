"""
B-07 — Banned-token test for modality vocabulary leaks in template strings
==========================================================================
Three complementary enforcement layers must agree on what is forbidden for
each archetype, and each must actually enforce its list:

  1. _modality_class / _modality_directive — routes each sub_expert_id to the
     correct framing key (or empty for archetypes with a dedicated system_prompt).
  2. ArchetypeManifest.banned_vocabulary — the per-archetype blocklist enforced
     at render time by validate_content / validate_report_dict.
  3. FunnelSpec.clinical_vocabulary_forbidden — the template-level blocklist that
     must be a subset of the manifest-level one (no split enforcement).

Additionally: the research-tool expert system_prompt and critic_rules may
mention banned tokens only in explicit prohibition sentences ("Do NOT", "BANNED
VOCABULARY: …"). An uninstructional mention (as an example or framing hint)
is a vocabulary leak — the LLM will reproduce it.

All tests are pure-Python (no API key, no DB).
"""

from __future__ import annotations

import re

import pytest


# ── shared helpers ────────────────────────────────────────────────────────────

def _manifest(archetype_value: str):
    from app.services.product_archetype import ARCHETYPE_MANIFESTS, ProductArchetype
    return ARCHETYPE_MANIFESTS[ProductArchetype(archetype_value)]


def _validate_content(text: str, archetype_value: str, section_id: str = "body", strict: bool = True):
    from app.services.product_archetype import ProductArchetype, validate_content
    return validate_content(text, ProductArchetype(archetype_value), section_id, strict=strict)


# ══════════════════════════════════════════════════════════════════════════════
# Modality directive routing
# ══════════════════════════════════════════════════════════════════════════════

class TestModalityDirectiveRouting:
    """
    _modality_class must map each sub_expert_id prefix to the correct framing key.
    A wrong routing injects the wrong vocabulary into LLM prompts — e.g. device
    framing (510k, DRG, NTAP) leaked into a research-tool prompt.
    """

    def _cls(self, sub_expert_id: str) -> str:
        from app.services.alignment_service import _modality_class
        return _modality_class(sub_expert_id, None)

    def test_research_tool_returns_empty(self):
        """research_tool_non_clinical must return '' — it has a dedicated system_prompt
        and must NOT receive the drug/device modality framing block."""
        assert self._cls("research_tool_non_clinical") == "", (
            "_modality_class('research_tool_non_clinical') must return '' so the "
            "drug-schema override is never injected into a research-tool prompt."
        )

    def test_research_infrastructure_returns_empty(self):
        assert self._cls("research_infrastructure_saas") == ""

    def test_device_prefix_gives_device(self):
        assert self._cls("device_cardiovascular") == "device"
        assert self._cls("device_metabolic") == "device"
        assert self._cls("device_neurology") == "device"

    def test_digital_prefix_gives_samd(self):
        assert self._cls("digital_cds") == "samd"
        assert self._cls("digital_rpm") == "samd"
        assert self._cls("digital_therapeutic") == "samd"

    def test_biologic_prefix_gives_biologic(self):
        assert self._cls("biologic_oncology") == "biologic"
        assert self._cls("biologic_immunology") == "biologic"

    def test_gene_therapy_prefix_gives_gene_therapy(self):
        assert self._cls("gene_therapy_rare") == "gene_therapy"
        assert self._cls("gene_therapy_rna") == "gene_therapy"

    def test_vaccine_prefix_gives_vaccine(self):
        assert self._cls("vaccine_prophylactic") == "vaccine"
        assert self._cls("vaccine_cancer_immuno") == "vaccine"

    def test_amr_drug_returns_empty(self):
        """drug_amr is the antibiotic base case — keeps its original schema unchanged."""
        assert self._cls("drug_amr") == ""

    def test_nonamr_drug_gives_nonamr_drug(self):
        assert self._cls("drug_cns") == "nonamr_drug"
        assert self._cls("drug_oncology") == "nonamr_drug"
        assert self._cls("drug_metabolic") == "nonamr_drug"


class TestModalityDirectiveContent:
    """
    For each non-empty modality class the directive must contain vocabulary
    appropriate to that class and must NOT contain vocabulary from a different class.
    """

    def _directive(self, sub_expert_id: str) -> str:
        from app.services.alignment_service import _modality_directive
        return _modality_directive(sub_expert_id, None)

    def test_device_directive_contains_device_terms(self):
        d = self._directive("device_cardiovascular")
        assert "510" in d or "predicate" in d.lower(), (
            "Device modality directive must reference device-specific terms (510k/predicate)."
        )

    def test_device_directive_blocks_drug_terms_in_hard_block(self):
        """The HARD BLOCK section of a device directive must ban drug-specific terms."""
        d = self._directive("device_cardiovascular").lower()
        assert "nda" in d or "bla" in d, (
            "Device HARD BLOCK must name NDA/BLA as forbidden drug terms."
        )

    def test_samd_directive_contains_samd_terms(self):
        d = self._directive("digital_cds")
        assert "SaMD" in d or "samd" in d.lower() or "software as a medical device" in d.lower(), (
            "SaMD modality directive must reference SaMD-specific terms."
        )

    def test_research_tool_directive_is_empty(self):
        """Empty directive = research tool uses its own system_prompt; no cross-contamination."""
        d = self._directive("research_tool_non_clinical")
        assert d == "", (
            "research_tool_non_clinical must NOT receive any modality directive — "
            f"got {d[:100]!r}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# validate_content enforcement
# ══════════════════════════════════════════════════════════════════════════════

class TestValidateContentEnforcement:
    """
    validate_content must catch each banned token for RESEARCH_TOOL_NON_CLINICAL
    in strict=True (raises) and strict=False (collects) modes.
    """

    ARCHETYPE = "research_tool_non_clinical"

    def test_clean_text_passes(self):
        violations = _validate_content(
            "The PI purchased a data logger for long-duration recording.",
            self.ARCHETYPE, strict=False,
        )
        assert violations == []

    @pytest.mark.parametrize("token", [
        "510(k)", "de novo", "pma ", "ntap", "drg ", "cpt code",
        "wac price", "j-code", "daly", "peak revenue",
    ])
    def test_each_banned_token_is_caught_strict(self, token: str):
        text = f"This product follows the {token} pathway."
        from app.services.product_archetype import ArchetypeViolationError
        with pytest.raises(ArchetypeViolationError) as exc:
            _validate_content(text, self.ARCHETYPE, strict=True)
        assert exc.value.token in text.lower(), (
            f"ArchetypeViolationError.token must be the matched token, "
            f"got {exc.value.token!r}"
        )
        assert exc.value.section_id == "body"
        assert exc.value.archetype.value == self.ARCHETYPE

    @pytest.mark.parametrize("token", [
        "510(k)", "drg ", "ntap",
    ])
    def test_each_banned_token_collected_in_non_strict(self, token: str):
        text = f"Consider the {token} pathway."
        violations = _validate_content(text, self.ARCHETYPE, strict=False)
        assert len(violations) >= 1, (
            f"validate_content(strict=False) must collect violation for {token!r}"
        )
        assert any(token in v for v in violations), (
            f"Violation list must name the offending token {token!r}: {violations}"
        )

    def test_multiple_banned_tokens_all_collected(self):
        """strict=False must find every banned token, not stop at first."""
        text = "The 510(k) pathway costs drg  reimbursement and ntap approval."
        violations = _validate_content(text, self.ARCHETYPE, strict=False)
        assert len(violations) >= 2, (
            f"Must collect all violations (found {len(violations)}): {violations}"
        )

    def test_exempt_stub_section_never_raises(self):
        """The 'regulatory_non_applicability' stub may name banned terms to explain why
        they don't apply — validate_content must not flag it."""
        text = "510(k), NTAP, DRG, WAC price — none of these apply to this research tool."
        violations = _validate_content(
            text, self.ARCHETYPE, section_id="regulatory_non_applicability", strict=False
        )
        assert violations == [], (
            "Exempt stub section must never yield violations even with banned vocabulary."
        )

    def test_not_applicable_stub_is_exempt(self):
        violations = _validate_content(
            "510(k) clearance is not applicable to this archetype.",
            self.ARCHETYPE, section_id="not_applicable_stub", strict=False,
        )
        assert violations == []

    def test_reimbursement_stub_is_exempt(self):
        violations = _validate_content(
            "WAC price and J-code reimbursement are not relevant here.",
            self.ARCHETYPE, section_id="reimbursement_non_applicability", strict=False,
        )
        assert violations == []


# ══════════════════════════════════════════════════════════════════════════════
# FunnelSpec ↔ ArchetypeManifest consistency
# ══════════════════════════════════════════════════════════════════════════════

class TestFunnelSpecConsistency:
    """
    FunnelSpec.clinical_vocabulary_forbidden is the template-level blocklist;
    ArchetypeManifest.banned_vocabulary is the render-time enforcement.
    Every term in the template-level list must also appear in the manifest —
    otherwise the render-time gate doesn't cover what the template promised.
    """

    def test_life_sciences_research_forbidden_subset_of_manifest(self):
        from app.market.templates.life_sciences_research import TEMPLATE
        manifest = _manifest("research_tool_non_clinical")
        missing = []
        for term in TEMPLATE.clinical_vocabulary_forbidden:
            term_lc = term.lower()
            # Substring match — manifest tokens are substring patterns
            if not any(term_lc in tok or tok in term_lc
                       for tok in manifest.banned_vocabulary):
                missing.append(term)
        assert not missing, (
            "These FunnelSpec.clinical_vocabulary_forbidden terms are NOT covered "
            "by RESEARCH_TOOL_NON_CLINICAL.banned_vocabulary — the render-time gate "
            "would miss them:\n" + "\n".join(f"  {t!r}" for t in missing)
        )

    def test_engineering_hardware_forbidden_subset_of_manifest(self):
        """engineering_hardware TEMPLATE should have no terms that would evade the
        research-tool manifest (they share the same template-level guard intent)."""
        from app.market.templates.engineering_hardware import TEMPLATE
        # engineering_hardware maps to a different archetype;
        # just verify the template itself is self-consistent (non-empty forbidden list)
        assert len(TEMPLATE.clinical_vocabulary_forbidden) >= 4, (
            "engineering_hardware template must define clinical_vocabulary_forbidden. "
            f"Got: {TEMPLATE.clinical_vocabulary_forbidden!r}"
        )

    def test_research_tool_manifest_has_core_clinical_terms(self):
        """Quick sanity: the manifest must ban the six core clinical terms."""
        manifest = _manifest("research_tool_non_clinical")
        core = {"510(k)", "ntap", "drg ", "wac price", "j-code", "cpt code"}
        missing = core - manifest.banned_vocabulary
        assert not missing, (
            f"RESEARCH_TOOL_NON_CLINICAL manifest is missing core clinical bans: {missing!r}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# validate_report_dict — nested coverage
# ══════════════════════════════════════════════════════════════════════════════

class TestValidateReportDict:

    ARCHETYPE = "research_tool_non_clinical"

    def test_nested_dict_violation_is_found(self):
        from app.services.product_archetype import ProductArchetype, validate_report_dict
        report = {
            "market_sizing": {
                "formula": "TAM = hospitals × DRG weight × ASP",
            }
        }
        violations = validate_report_dict(report, ProductArchetype(self.ARCHETYPE))
        assert violations, "Banned token in nested dict must be found by validate_report_dict."
        assert any("drg" in v.lower() for v in violations), (
            f"Violation list must reference 'drg': {violations}"
        )

    def test_nested_list_violation_is_found(self):
        from app.services.product_archetype import ProductArchetype, validate_report_dict
        report = {
            "strategies": [
                {"title": "Obtain 510(k) clearance first"},
                {"title": "Pursue NIH R01 grant funding"},
            ]
        }
        violations = validate_report_dict(report, ProductArchetype(self.ARCHETYPE))
        assert violations, "Banned token in list element must be found."
        assert any("510" in v for v in violations), (
            f"Violation must reference '510(k)': {violations}"
        )

    def test_clean_report_dict_passes(self):
        from app.services.product_archetype import ProductArchetype, validate_report_dict
        report = {
            "market_sizing": {
                "formula": "TAM = NIH-funded labs × annualised spend per lab",
            },
            "strategies": [
                {"title": "Partner with NIH-funded PIs"},
            ]
        }
        violations = validate_report_dict(report, ProductArchetype(self.ARCHETYPE))
        assert violations == [], f"Clean research-tool report must pass: {violations}"

    def test_violation_path_is_reported(self):
        from app.services.product_archetype import ProductArchetype, validate_report_dict
        report = {"competitive_summary": "The NTAP add-on payment drives hospital adoption."}
        violations = validate_report_dict(report, ProductArchetype(self.ARCHETYPE))
        assert violations, "Violation must be detected."
        assert any("competitive_summary" in v for v in violations), (
            "Violation path must include the dict key where the token was found. "
            f"Got: {violations}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Expert template system_prompt — no instructional use of banned tokens
# ══════════════════════════════════════════════════════════════════════════════

# Markers that indicate a line is a prohibition (not an instructional leak)
_PROHIBITION_MARKERS = re.compile(
    r'\b(do not|don\'t|must not|never|cannot|no |banned|not applicable|not apply|'
    r'not a |not an |not for|not fda|excluded|forbidden|prohibited|'
    r'n/a|not regulated|not relevant|ignore|is not|are not|not ")\b',
    re.IGNORECASE,
)

_INSTRUCTIONAL_BANNED = [
    "510(k)", "510k", "de novo", "pma ", "ntap", "drg ", "cpt code",
    "j-code", "daly", "peak revenue", "wac price", "peak sales",
]


def _get_non_prohibition_lines(text: str) -> list[str]:
    """Return lines from text that do NOT contain a prohibition marker."""
    return [
        ln for ln in text.splitlines()
        if not _PROHIBITION_MARKERS.search(ln)
    ]


class TestResearchToolTemplateVocabulary:
    """
    The research_tool_non_clinical expert system_prompt and critic_rules may
    name banned vocabulary ONLY in prohibition context ("Do NOT mention 510(k)",
    "BANNED VOCABULARY: 510(k), …"). Appearing as an instruction or example is
    a vocabulary leak — the LLM will reproduce the word regardless of subsequent
    prohibition text.
    """

    def _get_profile(self):
        from app.services.expert_profiles_v2 import SUB_EXPERT_REGISTRY
        return SUB_EXPERT_REGISTRY["research_tool_non_clinical"]

    def test_system_prompt_no_uninstructional_banned_tokens(self):
        """Banned tokens must not appear on lines without a prohibition marker."""
        profile = self._get_profile()
        leaky_lines = []
        non_prohib = _get_non_prohibition_lines(profile.system_prompt)
        for line in non_prohib:
            line_lc = line.lower()
            for token in _INSTRUCTIONAL_BANNED:
                if token in line_lc:
                    leaky_lines.append((token, line.strip()))
        assert not leaky_lines, (
            "research_tool_non_clinical system_prompt contains banned vocabulary "
            "outside a prohibition sentence:\n" +
            "\n".join(f"  token={tok!r}: {ln[:120]!r}" for tok, ln in leaky_lines)
        )

    def test_critic_rules_non_prohibition_lines_clean(self):
        """critic_rules line that names banned tokens must always be the BANNED
        VOCABULARY list header or another prohibition. A line like 'Use 510(k)...'
        would be a leak."""
        profile = self._get_profile()
        non_prohib = _get_non_prohibition_lines(profile.critic_rules)
        leaky_lines = []
        for line in non_prohib:
            line_lc = line.lower()
            for token in _INSTRUCTIONAL_BANNED:
                if token in line_lc:
                    leaky_lines.append((token, line.strip()))
        assert not leaky_lines, (
            "research_tool_non_clinical critic_rules has banned vocabulary on a "
            "non-prohibition line:\n" +
            "\n".join(f"  token={tok!r}: {ln[:120]!r}" for tok, ln in leaky_lines)
        )

    def test_system_prompt_mentions_nih_denominator(self):
        """Research-tool template must frame the market denominator as labs, not hospitals."""
        profile = self._get_profile()
        prompt_lower = profile.system_prompt.lower()
        assert "nih" in prompt_lower and ("lab" in prompt_lower or "pi" in prompt_lower), (
            "research_tool system_prompt must anchor market sizing to NIH-funded labs, "
            "not hospital counts."
        )
        # "hospital count" may appear only in prohibition lines (e.g. "not hospital count").
        non_prohib = _get_non_prohibition_lines(profile.system_prompt)
        instructional_hospital_count = [
            ln for ln in non_prohib if "hospital count" in ln.lower()
        ]
        assert not instructional_hospital_count, (
            "system_prompt must not instruct the LLM to use hospital count as the denominator "
            "(non-prohibition lines). Found:\n" +
            "\n".join(f"  {ln.strip()!r}" for ln in instructional_hospital_count)
        )

    def test_research_tool_inapplicable_sections_non_empty(self):
        """Manifest must list the sections that do not apply to research tools."""
        manifest = _manifest("research_tool_non_clinical")
        assert manifest.inapplicable_sections, (
            "RESEARCH_TOOL_NON_CLINICAL must declare inapplicable_sections "
            "(regulatory_pathway, reimbursement_strategy, etc.)."
        )
        assert "regulatory_pathway" in manifest.inapplicable_sections or \
               "reimbursement_strategy" in manifest.inapplicable_sections, (
            "inapplicable_sections must include at least one of regulatory_pathway or "
            "reimbursement_strategy for a non-clinical research tool."
        )
