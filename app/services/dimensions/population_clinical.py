"""Population / clinical dimensions — candidates only for patient-buyer archetypes."""
from app.services.dimensions import Dimension, DimensionFamily, register

_CLINICAL = frozenset({"small_molecule","biologic","gene_cell","vaccine","therapeutic"})

def _is_clinical(c: dict, i: dict) -> bool:
    return (
        str(c.get("archetype","")).lower() in _CLINICAL
        or str(i.get("domain","")).upper() == "LIFE_SCIENCES_CLINICAL"
    )

register(Dimension(
    id="age_band", label="Age Band",
    family=DimensionFamily.POPULATION_CLINICAL,
    candidate_when=_is_clinical,
    may_differentiate=frozenset({"adoption","timing"}),
    data_granularity="national",
    levels_source="intake",
    description="Pediatric (<18 yrs) / adult / geriatric (≥65 yrs)",
))
register(Dimension(
    id="sex", label="Sex",
    family=DimensionFamily.POPULATION_CLINICAL,
    candidate_when=_is_clinical,
    may_differentiate=frozenset({"adoption"}),
    data_granularity="national",
    levels_source="intake",
    description="Male / female / all-sex",
))
register(Dimension(
    id="race_ethnicity", label="Race & Ethnicity",
    family=DimensionFamily.POPULATION_CLINICAL,
    candidate_when=_is_clinical,
    may_differentiate=frozenset({"adoption","access"}),
    data_granularity="national",
    levels_source="intake",
    description="Non-Hispanic White / Black / Hispanic / Asian / Other",
))
register(Dimension(
    id="disease_severity", label="Disease Severity / Stage",
    family=DimensionFamily.POPULATION_CLINICAL,
    candidate_when=_is_clinical,
    may_differentiate=frozenset({"adoption","timing","price"}),
    data_granularity="national",
    levels_source="intake",
    description="Mild / moderate / severe (grade or stage-based)",
))
register(Dimension(
    id="line_of_therapy", label="Line of Therapy",
    family=DimensionFamily.POPULATION_CLINICAL,
    candidate_when=_is_clinical,
    may_differentiate=frozenset({"adoption","price","timing"}),
    data_granularity="national",
    levels_source="intake",
    description="1L / 2L / 3L+",
))
register(Dimension(
    id="biomarker_status", label="Biomarker Status",
    family=DimensionFamily.POPULATION_CLINICAL,
    candidate_when=_is_clinical,
    may_differentiate=frozenset({"adoption","access"}),
    data_granularity="national",
    levels_source="intake",
    description="Biomarker-positive / negative / not tested",
))
register(Dimension(
    id="diagnosis_status", label="Diagnosis Status",
    family=DimensionFamily.POPULATION_CLINICAL,
    candidate_when=_is_clinical,
    may_differentiate=frozenset({"adoption","timing","access"}),
    data_granularity="national",
    levels_source="intake",
    description="Diagnosed / undiagnosed / suspected",
))
register(Dimension(
    id="comorbidity_burden", label="Comorbidity Burden",
    family=DimensionFamily.POPULATION_CLINICAL,
    candidate_when=_is_clinical,
    may_differentiate=frozenset({"adoption","timing"}),
    data_granularity="individual",
    levels_source="claims_derived",
    description="Low (0–1 comorbidities) / moderate (2–3) / high (4+)",
))
register(Dimension(
    id="symptom_duration", label="Symptom Duration",
    family=DimensionFamily.POPULATION_CLINICAL,
    candidate_when=_is_clinical,
    may_differentiate=frozenset({"timing","adoption"}),
    data_granularity="individual",
    levels_source="intake",
    description="Acute (<3 months) / subacute / chronic (>12 months)",
))
register(Dimension(
    id="pediatric_adult", label="Pediatric vs. Adult",
    family=DimensionFamily.POPULATION_CLINICAL,
    candidate_when=_is_clinical,
    may_differentiate=frozenset({"adoption","access","price"}),
    data_granularity="national",
    levels_source="intake",
    description="Pediatric (<18) / adult",
))
