"""
Denominator source registry (Part D Revised, D.5).
Maps buyer personas to valid population sources.
"""

BUYER_PERSONA_FOR_ARCHETYPE: dict[str, str] = {
    "small_molecule":             "patient",
    "biologic":                   "patient",
    "gene_cell":                  "patient",
    "vaccine":                    "patient",
    "therapeutic":                "patient",
    "device":                     "health_system",
    "diagnostic":                 "lab",
    "digital":                    "health_system",
    "digital_samd":               "health_system",
    "research_tool":              "grant_funded_researcher",
    "research_tool_non_clinical": "grant_funded_researcher",
    "non_clinical":               "grant_funded_researcher",
}

VALID_SOURCES: dict[str, set[str]] = {
    "patient": {
        "cdc_wonder","seer","nhanes","brfss","claims_derived",
        "gbd","aha_heart_statistics","acs_cancer","alzheimers_association",
    },
    "health_system": {
        "aha_annual_survey","cms_pos","definitive_healthcare","hcris",
        "jc_accreditation","cms_care_compare",
    },
    "physician": {
        "nppes","medicare_partb_utilization","cms_care_compare","ama_masterfile",
    },
    "lab": {
        "clia_registry","cms_lab_fee_schedule","cap_accreditation",
    },
    "grant_funded_researcher": {
        "nih_reporter","nsf_awards","usaspending","herd_survey","carnegie_classification",
    },
    "commercial_firm": {
        "census_cbp","census_susb","naics_directory","dun_bradstreet",
    },
    "grower": {
        "usda_nass","usda_fsa","census_agriculture",
    },
}


def buyer_persona(archetype: str) -> str:
    return BUYER_PERSONA_FOR_ARCHETYPE.get(archetype.lower().strip(), "unknown")


def validate_denominator(archetype: str, source: str) -> tuple[bool, str]:
    persona = buyer_persona(archetype)
    if persona == "unknown":
        return True, f"Unknown archetype '{archetype}' — denominator not validated"
    valid = VALID_SOURCES.get(persona, set())
    if source in valid:
        return True, f"'{source}' is a valid denominator for buyer persona '{persona}'"
    return False, (
        f"'{source}' is NOT a valid denominator for buyer persona '{persona}' "
        f"(archetype='{archetype}'). Valid sources: {sorted(valid)}"
    )
