"""
Product Archetype System  (Defect Report — H-01)
================================================
Resolves a first-class ProductArchetype at intake (before any panel runs),
owns an ArchetypeManifest that allowlists eligible vocabulary per archetype,
and enforces the manifest as a hard render-time gate.

Why: the Hublink report used clinical regulatory vocabulary (510(k), NTAP,
CPT 99453-99458) for a non-clinical research data platform. The root cause was
a missing first-class gate — the archetype was carried only as an advisory
string in a prompt, not enforced at validation time.

Architecture:
  1. resolve_archetype(sub_expert_id)  → ProductArchetype
  2. ArchetypeManifest per archetype   → allowlists + banned_vocabulary
  3. validate_content(text, archetype) → raises ArchetypeViolationError with
       the exact token that triggered the gate, so the caller can log the
       generating section and substitute an appropriate fallback.

Acceptance test (H-01): for RESEARCH_TOOL_NON_CLINICAL, zero occurrences of
  any banned token in all report sections except the "not-applicable" stub.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, List, Optional

logger = logging.getLogger(__name__)


# ─── Archetype enum ───────────────────────────────────────────────────────────

class ProductArchetype(str, Enum):
    THERAPEUTIC_SMALL_MOLECULE  = "therapeutic_small_molecule"
    THERAPEUTIC_BIOLOGIC        = "therapeutic_biologic"
    GENE_CELL_THERAPY           = "gene_cell_therapy"
    DEVICE_CLASS_II             = "device_class_ii"    # 510(k) devices (most common)
    DEVICE_CLASS_III            = "device_class_iii"   # PMA devices
    SAMD_CLINICAL               = "samd_clinical"      # CDS, RPM, DTx — clinical SaMD
    DIAGNOSTIC_IVD              = "diagnostic_ivd"
    VACCINE                     = "vaccine"
    RESEARCH_TOOL_NON_CLINICAL  = "research_tool_non_clinical"    # e.g. Hublink
    RESEARCH_INFRASTRUCTURE_SAAS = "research_infrastructure_saas" # e.g. LIMS, ELN
    CLINICAL_WORKFLOW_SAAS      = "clinical_workflow_saas"        # EHR tools, non-SaMD
    PLATFORM                    = "platform"
    UNKNOWN                     = "unknown"


# ─── Manifest ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ArchetypeManifest:
    """
    All allowlist / blocklist facts for one ProductArchetype.

    banned_vocabulary:
        Set of lowercase token substrings. If ANY appears in a rendered
        section (outside the designated non-applicability stub), the gate
        raises ArchetypeViolationError. Designed as substring match so
        "510(k)" catches "510(k)-clearance", "510(k) pathway", etc.

    eligible_regulatory_pathways:
        Short codes for pathways that are legitimate for this archetype.
        Anything outside this set is banned by extension through the vocab list.

    comparator_corpora:
        Which data-source corpora the competitive intelligence layer may use.
        Prevents FDA device registries from being the source for non-device products.

    tam_formula:
        Which tam_calculator formula to invoke. Prevents the drug-prevalence
        formula from running on a per-lab SaaS product.

    buyer_persona_hint:
        The expected primary buyer type. If the resolved buyer persona
        diverges from this hint, the report must flag the discrepancy.
    """
    archetype:                   ProductArchetype
    display_label:               str
    banned_vocabulary:           FrozenSet[str]
    eligible_regulatory_pathways: FrozenSet[str]
    eligible_revenue_models:     FrozenSet[str]
    eligible_reimbursement_vocab: FrozenSet[str]
    comparator_corpora:          FrozenSet[str]
    tam_formula:                 str
    buyer_persona_hint:          str
    eligible_expert_ids:         FrozenSet[str]
    inapplicable_sections:       FrozenSet[str]  # rendered as N/A stubs, not scored


# ─── Manifests ────────────────────────────────────────────────────────────────

# Vocabulary that should NEVER appear in a research-tool or non-clinical-SaaS
# report outside the explicitly-labeled "why this doesn't apply" stub.
_CLINICAL_REGULATED_VOCAB: FrozenSet[str] = frozenset({
    "510(k)", "de novo", "pma ", "premarket approval", "breakthrough device",
    "ntap", "new technology add-on", "cpt 99", "cpt code", "j-code",
    "drg ", "diagnosis-related group", "wac price", "average wholesale",
    "daly", "disability-adjusted", "predicate device", "pccp",
    "clinical indication", "510k", "fda clearance", "fda-cleared",
    "ifu label", "labeling claim", "510 k", "class ii device",
    "510 (k)", "premarket notification",
})

# Vocab that should NEVER appear in a drug/small-molecule report
_SAAS_VOCAB_IN_DRUG: FrozenSet[str] = frozenset({
    "site-license", "per-lab", "api subscription", "per-seat",
    "academic pi", "pi buyer",
})

ARCHETYPE_MANIFESTS: Dict[ProductArchetype, ArchetypeManifest] = {

    ProductArchetype.RESEARCH_TOOL_NON_CLINICAL: ArchetypeManifest(
        archetype=ProductArchetype.RESEARCH_TOOL_NON_CLINICAL,
        display_label="Non-Clinical Research Tool",
        banned_vocabulary=_CLINICAL_REGULATED_VOCAB | frozenset({
            "peak revenue", "peak sales", "hospital enterprise",
            "hospital system", "health system buyer",
            "live on medicare", "live on medicaid",
            "reimbursement pathway", "coverage pathway",
            "formulary placement", "prior authorization",
        }),
        eligible_regulatory_pathways=frozenset({
            "not_regulated", "likely_exempt", "fcc_part_15",
            "export_control_only", "irb_protocol",
        }),
        eligible_revenue_models=frozenset({
            "per_lab_license", "per_unit_sale", "usage_metered",
            "one_time_purchase", "annual_subscription_lab",
            "institutional_site_license",
        }),
        eligible_reimbursement_vocab=frozenset({
            "nih_grant", "federal_grant", "foundation_grant",
            "institutional_budget", "indirect_cost_recovery",
            "capex_lab_equipment", "lab_opex",
        }),
        comparator_corpora=frozenset({
            "commercial_research_tools", "nih_reporter_grants",
            "academic_software_vendors", "open_source_alternatives",
            "vc_research_infrastructure",
        }),
        tam_formula="research_tool_bottom_up",
        buyer_persona_hint="academic_pi",
        eligible_expert_ids=frozenset({"research_tool_non_clinical", "digital_rpm"}),
        inapplicable_sections=frozenset({
            "regulatory_pathway", "reimbursement_strategy",
            "payer_access", "clinical_trial_design",
        }),
    ),

    ProductArchetype.RESEARCH_INFRASTRUCTURE_SAAS: ArchetypeManifest(
        archetype=ProductArchetype.RESEARCH_INFRASTRUCTURE_SAAS,
        display_label="Research Infrastructure SaaS",
        banned_vocabulary=_CLINICAL_REGULATED_VOCAB | frozenset({
            "peak revenue", "hospital enterprise", "health system buyer",
        }),
        eligible_regulatory_pathways=frozenset({
            "not_regulated", "likely_exempt", "hipaa_covered_entity_only",
        }),
        eligible_revenue_models=frozenset({
            "per_seat_saas", "institutional_contract", "annual_subscription_lab",
            "usage_metered", "tiered_institutional",
        }),
        eligible_reimbursement_vocab=frozenset({
            "nih_grant", "federal_grant", "institutional_budget",
            "it_procurement", "indirect_cost_recovery",
        }),
        comparator_corpora=frozenset({
            "commercial_lims_eln", "academic_software_vendors",
            "nih_reporter_grants", "open_source_alternatives",
        }),
        tam_formula="research_tool_bottom_up",
        buyer_persona_hint="research_it_or_admin",
        eligible_expert_ids=frozenset({"research_tool_non_clinical", "digital_cds"}),
        inapplicable_sections=frozenset({
            "regulatory_pathway", "reimbursement_strategy",
            "payer_access",
        }),
    ),

    ProductArchetype.THERAPEUTIC_SMALL_MOLECULE: ArchetypeManifest(
        archetype=ProductArchetype.THERAPEUTIC_SMALL_MOLECULE,
        display_label="Therapeutic Small Molecule Drug",
        banned_vocabulary=frozenset({
            "510(k)", "de novo device", "pma device", "premarket approval device",
            "ntap device", "drg device", "j-code device",
            "site-license", "per-lab", "api subscription",
        }),
        eligible_regulatory_pathways=frozenset({
            "nda", "505b2", "505b1", "ind", "priority_review", "accelerated_approval",
            "rems", "fast_track", "qidp", "lpad", "breakthrough_therapy",
        }),
        eligible_revenue_models=frozenset({
            "wac_per_course", "wac_annual", "net_price_contracted",
            "340b_eligible", "specialty_pharmacy",
        }),
        eligible_reimbursement_vocab=frozenset({
            "j_code", "formulary", "pbm", "prior_auth", "step_therapy",
            "part_b", "part_d", "cms_coverage",
        }),
        comparator_corpora=frozenset({
            "fda_approvals_nda", "clinicaltrials_drug", "cms_asp",
            "iqvia_sales", "symphony_prescribers",
        }),
        tam_formula="drug_prevalence",
        buyer_persona_hint="payer_and_hospital_pharmacy",
        eligible_expert_ids=frozenset({
            "drug_amr", "drug_oncology", "drug_cns", "drug_metabolic",
            "drug_cardiology", "drug_immunology", "drug_rare_disease",
            "drug_mental_health", "drug_infectious_non_amr",
        }),
        inapplicable_sections=frozenset(),
    ),

    ProductArchetype.THERAPEUTIC_BIOLOGIC: ArchetypeManifest(
        archetype=ProductArchetype.THERAPEUTIC_BIOLOGIC,
        display_label="Therapeutic Biologic",
        banned_vocabulary=frozenset({
            "510(k)", "de novo device", "pma device", "site-license", "per-lab",
        }),
        eligible_regulatory_pathways=frozenset({
            "bla", "ind", "priority_review", "accelerated_approval",
            "rems", "fast_track", "breakthrough_therapy", "biosimilar_pathway",
        }),
        eligible_revenue_models=frozenset({
            "wac_per_infusion", "wac_annual", "net_price_contracted",
            "340b_eligible", "specialty_pharmacy", "buy_and_bill",
        }),
        eligible_reimbursement_vocab=frozenset({
            "j_code", "formulary", "pbm", "prior_auth", "step_therapy",
            "part_b_buy_and_bill", "part_d", "cms_coverage", "rems",
        }),
        comparator_corpora=frozenset({
            "fda_approvals_bla", "clinicaltrials_biologic", "cms_asp",
            "iqvia_sales",
        }),
        tam_formula="drug_prevalence",
        buyer_persona_hint="payer_and_hospital_pharmacy",
        eligible_expert_ids=frozenset({
            "biologic_oncology", "biologic_immunology", "biologic_hematology",
            "biologic_rare_disease", "biologic_cardiology",
        }),
        inapplicable_sections=frozenset(),
    ),

    ProductArchetype.SAMD_CLINICAL: ArchetypeManifest(
        archetype=ProductArchetype.SAMD_CLINICAL,
        display_label="Clinical Software as Medical Device (SaMD)",
        banned_vocabulary=frozenset({
            "wac price", "nda", "bla ", "formulary placement",
            "per-lab", "academic pi", "nih grant buyer",
        }),
        eligible_regulatory_pathways=frozenset({
            "510k", "de_novo", "pma", "cds_exemption", "predetermined_change_control_plan",
            "pccp", "dux_pilot",
        }),
        eligible_revenue_models=frozenset({
            "per_patient_annual", "facility_contract", "value_based_contract",
            "saas_hospital", "enterprise_health_system",
        }),
        eligible_reimbursement_vocab=frozenset({
            "cpt_99", "ntap", "drg_add_on", "coverage_policy",
            "acp", "pama", "mac_coverage",
        }),
        comparator_corpora=frozenset({
            "fda_510k_samd", "clinicaltrials_digital", "cms_coverage",
            "rock_health_funding", "klas_ehr",
        }),
        tam_formula="device",
        buyer_persona_hint="hospital_cio_or_cmo",
        eligible_expert_ids=frozenset({
            "digital_cds", "digital_rpm", "digital_therapeutic",
            "digital_samd_radiology",
        }),
        inapplicable_sections=frozenset(),
    ),

    ProductArchetype.DEVICE_CLASS_II: ArchetypeManifest(
        archetype=ProductArchetype.DEVICE_CLASS_II,
        display_label="Class II Medical Device (510(k))",
        banned_vocabulary=frozenset({
            "nda", "bla ", "wac price", "formulary",
            "per-lab", "academic pi",
        }),
        eligible_regulatory_pathways=frozenset({
            "510k", "de_novo", "qsupp", "special_510k",
        }),
        eligible_revenue_models=frozenset({
            "capital_sale", "disposable_pull_through", "per_procedure",
            "facility_contract", "group_purchasing_organization",
        }),
        eligible_reimbursement_vocab=frozenset({
            "cpt", "drg", "ntap", "pass_through_payment",
            "apc", "coverage_determination",
        }),
        comparator_corpora=frozenset({
            "fda_510k_device", "clinicaltrials_device", "cms_coverage",
        }),
        tam_formula="device",
        buyer_persona_hint="hospital_vp_surgery_or_procurement",
        eligible_expert_ids=frozenset({
            "device_cardiovascular", "device_metabolic", "device_neurology",
        }),
        inapplicable_sections=frozenset(),
    ),

    ProductArchetype.DIAGNOSTIC_IVD: ArchetypeManifest(
        archetype=ProductArchetype.DIAGNOSTIC_IVD,
        display_label="In Vitro Diagnostic",
        banned_vocabulary=frozenset({
            "nda", "bla ", "wac price", "formulary", "per-lab academic",
        }),
        eligible_regulatory_pathways=frozenset({
            "510k_ivd", "de_novo_ivd", "pma_ivd", "ldt_exemption",
            "eua", "clia_waived",
        }),
        eligible_revenue_models=frozenset({
            "per_test_fee", "lab_contract", "reagent_rental",
            "reagent_lease", "professional_services",
        }),
        eligible_reimbursement_vocab=frozenset({
            "cpt_lab", "local_coverage_determination", "pama_pricing",
            "mac_coverage", "medicare_fee_schedule_lab",
        }),
        comparator_corpora=frozenset({
            "fda_510k_ivd", "clinicaltrials_diagnostic", "cms_pama",
        }),
        tam_formula="device",
        buyer_persona_hint="lab_director_or_pathologist",
        eligible_expert_ids=frozenset({
            "diagnostic_molecular", "diagnostic_companion", "diagnostic_poc",
        }),
        inapplicable_sections=frozenset(),
    ),

    ProductArchetype.UNKNOWN: ArchetypeManifest(
        archetype=ProductArchetype.UNKNOWN,
        display_label="Unknown / Pending Classification",
        banned_vocabulary=frozenset(),   # no bans until archetype is known
        eligible_regulatory_pathways=frozenset(),
        eligible_revenue_models=frozenset(),
        eligible_reimbursement_vocab=frozenset(),
        comparator_corpora=frozenset(),
        tam_formula="generic_fallback",
        buyer_persona_hint="unknown",
        eligible_expert_ids=frozenset(),
        inapplicable_sections=frozenset(),
    ),
}

# Fill in remaining archetypes with sensible defaults (gene therapy, vaccine, etc.)
for _a in ProductArchetype:
    if _a not in ARCHETYPE_MANIFESTS:
        ARCHETYPE_MANIFESTS[_a] = ArchetypeManifest(
            archetype=_a,
            display_label=_a.value.replace("_", " ").title(),
            banned_vocabulary=frozenset(),
            eligible_regulatory_pathways=frozenset(),
            eligible_revenue_models=frozenset(),
            eligible_reimbursement_vocab=frozenset(),
            comparator_corpora=frozenset(),
            tam_formula="drug_prevalence",
            buyer_persona_hint="unknown",
            eligible_expert_ids=frozenset(),
            inapplicable_sections=frozenset(),
        )


# ─── Router → Archetype mapping ───────────────────────────────────────────────

_SUB_EXPERT_TO_ARCHETYPE: Dict[str, ProductArchetype] = {
    # Drugs
    "drug_amr":                ProductArchetype.THERAPEUTIC_SMALL_MOLECULE,
    "drug_oncology":           ProductArchetype.THERAPEUTIC_SMALL_MOLECULE,
    "drug_cns":                ProductArchetype.THERAPEUTIC_SMALL_MOLECULE,
    "drug_metabolic":          ProductArchetype.THERAPEUTIC_SMALL_MOLECULE,
    "drug_cardiology":         ProductArchetype.THERAPEUTIC_SMALL_MOLECULE,
    "drug_immunology":         ProductArchetype.THERAPEUTIC_SMALL_MOLECULE,
    "drug_rare_disease":       ProductArchetype.THERAPEUTIC_SMALL_MOLECULE,
    "drug_mental_health":      ProductArchetype.THERAPEUTIC_SMALL_MOLECULE,
    "drug_infectious_non_amr": ProductArchetype.THERAPEUTIC_SMALL_MOLECULE,
    # Biologics
    "biologic_oncology":       ProductArchetype.THERAPEUTIC_BIOLOGIC,
    "biologic_immunology":     ProductArchetype.THERAPEUTIC_BIOLOGIC,
    "biologic_hematology":     ProductArchetype.THERAPEUTIC_BIOLOGIC,
    "biologic_rare_disease":   ProductArchetype.THERAPEUTIC_BIOLOGIC,
    "biologic_cardiology":     ProductArchetype.THERAPEUTIC_BIOLOGIC,
    # Gene / Cell
    "gene_therapy_rare":       ProductArchetype.GENE_CELL_THERAPY,
    "gene_therapy_hematology": ProductArchetype.GENE_CELL_THERAPY,
    "gene_therapy_oncology":   ProductArchetype.GENE_CELL_THERAPY,
    "gene_therapy_cns":        ProductArchetype.GENE_CELL_THERAPY,
    "gene_therapy_rna":        ProductArchetype.GENE_CELL_THERAPY,
    # Devices
    "device_cardiovascular":   ProductArchetype.DEVICE_CLASS_II,
    "device_metabolic":        ProductArchetype.DEVICE_CLASS_II,
    "device_neurology":        ProductArchetype.DEVICE_CLASS_II,
    # Diagnostics
    "diagnostic_molecular":    ProductArchetype.DIAGNOSTIC_IVD,
    "diagnostic_companion":    ProductArchetype.DIAGNOSTIC_IVD,
    "diagnostic_poc":          ProductArchetype.DIAGNOSTIC_IVD,
    # Clinical SaMD
    "digital_cds":             ProductArchetype.SAMD_CLINICAL,
    "digital_therapeutic":     ProductArchetype.SAMD_CLINICAL,
    "digital_samd_radiology":  ProductArchetype.SAMD_CLINICAL,
    # Clinical RPM stays SaMD (clinical patient monitoring)
    "digital_rpm":             ProductArchetype.SAMD_CLINICAL,
    # Vaccines
    "vaccine_prophylactic":    ProductArchetype.VACCINE,
    "vaccine_cancer_immuno":   ProductArchetype.VACCINE,
    # Non-clinical research tools (the Hublink case)
    "research_tool_non_clinical": ProductArchetype.RESEARCH_TOOL_NON_CLINICAL,
    "research_infrastructure_saas": ProductArchetype.RESEARCH_INFRASTRUCTURE_SAAS,
    # Platforms
    "other_crispr":            ProductArchetype.GENE_CELL_THERAPY,
    "other_microbiome":        ProductArchetype.THERAPEUTIC_BIOLOGIC,
    "other_delivery":          ProductArchetype.THERAPEUTIC_SMALL_MOLECULE,
}


def resolve_archetype(sub_expert_id: str) -> ProductArchetype:
    """
    Map a granular sub_expert_id (from the v2 router) to a ProductArchetype.
    Returns UNKNOWN for unrecognised ids — callers must check for UNKNOWN
    and avoid imposing clinical vocabulary restrictions until resolved.
    """
    archetype = _SUB_EXPERT_TO_ARCHETYPE.get(sub_expert_id or "", ProductArchetype.UNKNOWN)
    logger.debug("Archetype resolved: sub_expert_id=%s → %s", sub_expert_id, archetype.value)
    return archetype


def get_manifest(archetype: ProductArchetype) -> ArchetypeManifest:
    return ARCHETYPE_MANIFESTS[archetype]


# ─── Render-time gate ─────────────────────────────────────────────────────────

class ArchetypeViolationError(Exception):
    """
    Raised when a generated section contains vocabulary that is not permitted
    for the resolved ProductArchetype. The generating section ID and the
    exact token that triggered the gate are included so the caller can:
      1. Log the violation (which expert/section leaked)
      2. Substitute the inapplicable-section stub instead of surfacing the
         bad content to the user.
    """
    def __init__(self, archetype: ProductArchetype, section_id: str,
                 token: str, text_excerpt: str = "") -> None:
        self.archetype    = archetype
        self.section_id   = section_id
        self.token        = token
        self.text_excerpt = text_excerpt[:200]
        super().__init__(
            f"ArchetypeViolation [{archetype.value}] section={section_id!r}: "
            f"banned token {token!r} found"
        )


# Sections where banned vocabulary is PERMITTED (the "why it doesn't apply" stub).
_EXEMPT_SECTION_IDS: FrozenSet[str] = frozenset({
    "regulatory_non_applicability",
    "reimbursement_non_applicability",
    "not_applicable_stub",
})


def validate_content(
    text: str,
    archetype: ProductArchetype,
    section_id: str,
    strict: bool = True,
) -> List[str]:
    """
    Scan generated text for banned vocabulary tokens for the given archetype.

    Args:
        text:       Generated section content (any length).
        archetype:  Resolved product archetype.
        section_id: Slug identifying which report section generated this text
                    (used to exempt the non-applicability stub sections).
        strict:     If True, raise ArchetypeViolationError on first hit.
                    If False, collect and return all violations as strings.

    Returns:
        List of violation strings (empty = passes gate). When strict=True,
        raises on the first violation instead of returning.
    """
    if section_id in _EXEMPT_SECTION_IDS:
        return []

    manifest  = get_manifest(archetype)
    text_lower = text.lower()
    violations: List[str] = []

    for token in manifest.banned_vocabulary:
        if token in text_lower:
            # Find excerpt around the violation for logging
            idx = text_lower.find(token)
            excerpt = text[max(0, idx - 40): idx + len(token) + 40]
            violations.append(f"banned token {token!r} in section {section_id!r}: ...{excerpt}...")
            if strict:
                raise ArchetypeViolationError(
                    archetype=archetype,
                    section_id=section_id,
                    token=token,
                    text_excerpt=excerpt,
                )

    return violations


def validate_report_dict(
    report: dict,
    archetype: ProductArchetype,
) -> List[str]:
    """
    Walk a serialised report dict and validate every string value.
    Returns all violation strings (empty = clean).
    Intended to run after generation and before set_done() persists the report.
    """
    violations: List[str] = []
    _walk_dict(report, archetype, path="root", violations=violations)
    return violations


def _walk_dict(
    obj: object,
    archetype: ProductArchetype,
    path: str,
    violations: List[str],
) -> None:
    if isinstance(obj, str):
        hits = validate_content(obj, archetype, section_id=path, strict=False)
        violations.extend(hits)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _walk_dict(v, archetype, path=f"{path}.{k}", violations=violations)
    elif isinstance(obj, (list, tuple)):
        for i, item in enumerate(obj):
            _walk_dict(item, archetype, path=f"{path}[{i}]", violations=violations)


# ─── Per-archetype competitor entry schema ────────────────────────────────────
#
# Each archetype expects competitor entries in a distinct shape.  Mixing schemas
# produces "undefined" in rendered output when a field from one schema is read
# on an entry that follows a different schema.
#
# required_fields: must be present (non-None, non-empty) in every entry.
# forbidden_fields: must NOT appear — their presence signals a schema mismatch.

COMPETITOR_SCHEMA: dict[ProductArchetype, dict] = {
    ProductArchetype.RESEARCH_TOOL_NON_CLINICAL: {
        "required_fields":  frozenset({"name", "category", "description"}),
        "optional_fields":  frozenset({"url", "incumbent", "key_differentiator"}),
        "forbidden_fields": frozenset({"stage", "nct_id", "sponsor", "company",
                                       "brand_name", "route", "advantages",
                                       "vulnerabilities"}),
    },
    ProductArchetype.RESEARCH_INFRASTRUCTURE_SAAS: {
        "required_fields":  frozenset({"name", "category", "description"}),
        "optional_fields":  frozenset({"url", "incumbent", "key_differentiator"}),
        "forbidden_fields": frozenset({"stage", "nct_id", "sponsor", "brand_name",
                                       "route"}),
    },
    ProductArchetype.THERAPEUTIC_SMALL_MOLECULE: {
        "required_fields":  frozenset({"name", "company", "stage"}),
        "optional_fields":  frozenset({"brand_name", "route", "advantages",
                                       "vulnerabilities", "positioning_signal",
                                       "nct_id", "title", "status", "sponsor"}),
        "forbidden_fields": frozenset({"incumbent", "url", "category"}),
    },
    ProductArchetype.THERAPEUTIC_BIOLOGIC: {
        "required_fields":  frozenset({"name", "company", "stage"}),
        "optional_fields":  frozenset({"brand_name", "route", "advantages",
                                       "vulnerabilities", "positioning_signal",
                                       "nct_id", "title", "status", "sponsor"}),
        "forbidden_fields": frozenset({"incumbent", "url", "category"}),
    },
    ProductArchetype.DEVICE_CLASS_II: {
        "required_fields":  frozenset({"name", "company", "stage"}),
        "optional_fields":  frozenset({"brand_name", "advantages", "vulnerabilities",
                                       "positioning_signal", "nct_id", "title",
                                       "status", "sponsor"}),
        "forbidden_fields": frozenset({"incumbent", "url", "category"}),
    },
    ProductArchetype.SAMD_CLINICAL: {
        "required_fields":  frozenset({"name", "company", "stage"}),
        "optional_fields":  frozenset({"brand_name", "advantages", "vulnerabilities",
                                       "positioning_signal", "nct_id", "title",
                                       "status", "sponsor"}),
        "forbidden_fields": frozenset({"incumbent", "url", "category"}),
    },
    ProductArchetype.DIAGNOSTIC_IVD: {
        "required_fields":  frozenset({"name", "company", "stage"}),
        "optional_fields":  frozenset({"brand_name", "route", "advantages",
                                       "vulnerabilities", "positioning_signal",
                                       "nct_id", "title", "status", "sponsor"}),
        "forbidden_fields": frozenset({"incumbent", "category"}),
    },
}


def get_competitor_schema(archetype: ProductArchetype) -> dict:
    """
    Return the competitor entry schema for an archetype.
    Falls back to the generic drug schema for archetypes without an explicit entry.
    """
    return COMPETITOR_SCHEMA.get(archetype, {
        "required_fields":  frozenset({"name", "company", "stage"}),
        "optional_fields":  frozenset(),
        "forbidden_fields": frozenset(),
    })


def validate_competitor_entry(
    entry: dict,
    archetype: ProductArchetype,
) -> list[str]:
    """
    Check a single competitor dict against the archetype schema.
    Returns a list of violation strings (empty = clean).
    """
    schema = get_competitor_schema(archetype)
    violations: list[str] = []
    for field in schema["required_fields"]:
        val = entry.get(field)
        if not val and val != 0:
            violations.append(
                f"required field {field!r} missing or empty in competitor entry "
                f"for archetype {archetype.value!r}"
            )
    for field in schema["forbidden_fields"]:
        if field in entry:
            violations.append(
                f"forbidden field {field!r} present in competitor entry "
                f"for archetype {archetype.value!r} (schema mismatch)"
            )
    return violations


# ─── Inapplicable section stub ────────────────────────────────────────────────

def inapplicable_stub(section_name: str, archetype: ProductArchetype) -> dict:
    """
    Return a standardised N/A stub for sections that don't apply to this archetype.
    Used when the manifest lists the section in `inapplicable_sections`.

    Acceptance test (H-09): inapplicable sections render as N/A and are
    excluded from all composite scores.
    """
    manifest = get_manifest(archetype)
    return {
        "section": section_name,
        "status": "not_applicable",
        "reason": (
            f"This section does not apply to {manifest.display_label} products. "
            f"The {section_name.replace('_', ' ').title()} rubric and its vocabulary "
            f"are not relevant to this archetype and have been excluded from scoring."
        ),
        "score": None,        # explicitly None — never 0.0 (H-09 fix)
        "included_in_composite": False,
    }
