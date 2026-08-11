"""Care delivery dimensions — candidates for clinical and device archetypes; NOT research tools."""
from app.services.dimensions import Dimension, DimensionFamily, register

_RESEARCH = frozenset({"research_tool","non_clinical","research_tool_non_clinical"})

def _not_research(c: dict, i: dict) -> bool:
    return str(c.get("archetype","")).lower() not in _RESEARCH

register(Dimension(
    id="site_of_care", label="Site of Care",
    family=DimensionFamily.CARE_DELIVERY,
    candidate_when=_not_research,
    may_differentiate=frozenset({"adoption","price","channel"}),
    data_granularity="facility",
    levels_source="aha_annual_survey",
    description="Academic/tertiary / Community/regional / Outpatient / Home/infusion",
))
register(Dimension(
    id="provider_type", label="Provider Type",
    family=DimensionFamily.CARE_DELIVERY,
    candidate_when=_not_research,
    may_differentiate=frozenset({"adoption","channel"}),
    data_granularity="facility",
    levels_source="nppes",
    description="Specialist / PCP / NP-PA / Hospital-employed",
))
register(Dimension(
    id="practice_size", label="Practice Size",
    family=DimensionFamily.CARE_DELIVERY,
    candidate_when=_not_research,
    may_differentiate=frozenset({"adoption","price","channel"}),
    data_granularity="facility",
    levels_source="nppes",
    description="Solo/small (<5 providers) / Medium (5–20) / Large (>20) / IDN",
))
register(Dimension(
    id="idn_affiliation", label="IDN Affiliation",
    family=DimensionFamily.CARE_DELIVERY,
    candidate_when=_not_research,
    may_differentiate=frozenset({"price","channel"}),
    data_granularity="facility",
    levels_source="definitive_healthcare",
    description="IDN-affiliated / Independent",
))
register(Dimension(
    id="academic_community", label="Academic vs. Community",
    family=DimensionFamily.CARE_DELIVERY,
    candidate_when=_not_research,
    may_differentiate=frozenset({"adoption","access"}),
    data_granularity="facility",
    levels_source="aha_annual_survey",
    description="Academic medical center / Community hospital / Outpatient clinic",
))
register(Dimension(
    id="procedure_volume", label="Annual Procedure Volume Band",
    family=DimensionFamily.CARE_DELIVERY,
    candidate_when=_not_research,
    may_differentiate=frozenset({"adoption","price"}),
    data_granularity="facility",
    levels_source="medicare_partb_utilization",
    description="Low (<50/yr) / Medium (50–200/yr) / High (>200/yr)",
))
register(Dimension(
    id="ehr_vendor", label="EHR Vendor",
    family=DimensionFamily.CARE_DELIVERY,
    candidate_when=_not_research,
    may_differentiate=frozenset({"adoption","timing"}),
    data_granularity="facility",
    levels_source="definitive_healthcare",
    description="Epic / Cerner/Oracle / Meditech / Other",
))
register(Dimension(
    id="status_340b", label="340B Status",
    family=DimensionFamily.CARE_DELIVERY,
    candidate_when=_not_research,
    may_differentiate=frozenset({"price","adoption"}),
    data_granularity="facility",
    levels_source="hrsa_340b",
    description="340B covered entity / Non-340B",
))
