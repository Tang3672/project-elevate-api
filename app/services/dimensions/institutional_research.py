"""Institutional / research dimensions — candidates ONLY for research-tool archetype."""
from app.services.dimensions import Dimension, DimensionFamily, register

_RESEARCH = frozenset({"research_tool","non_clinical","research_tool_non_clinical"})

def _is_research(c: dict, i: dict) -> bool:
    return (
        str(c.get("archetype","")).lower() in _RESEARCH
        or str(i.get("domain","")).upper() == "LIFE_SCIENCES_RESEARCH"
    )

register(Dimension(
    id="funding_agency", label="Funding Agency",
    family=DimensionFamily.INSTITUTIONAL_RESEARCH,
    candidate_when=_is_research,
    may_differentiate=frozenset({"adoption","channel"}),
    data_granularity="national",
    levels_source="nih_reporter",
    description="NIH / NSF / DoD / Foundation / Industry-funded",
))
register(Dimension(
    id="award_size_band", label="Award Size Band",
    family=DimensionFamily.INSTITUTIONAL_RESEARCH,
    candidate_when=_is_research,
    may_differentiate=frozenset({"price","adoption"}),
    data_granularity="national",
    levels_source="nih_reporter",
    description="Small (<$250K) / Mid ($250K–$750K) / Large (>$750K)",
))
register(Dimension(
    id="current_solution", label="Current Solution in Place",
    family=DimensionFamily.INSTITUTIONAL_RESEARCH,
    candidate_when=_is_research,
    may_differentiate=frozenset({"adoption","timing"}),
    data_granularity="individual",
    levels_source="intake",
    description="Manual/paper / DIY scripts / Commercial software / None",
))
register(Dimension(
    id="carnegie_tier", label="Carnegie Tier",
    family=DimensionFamily.INSTITUTIONAL_RESEARCH,
    candidate_when=_is_research,
    may_differentiate=frozenset({"price","adoption","channel"}),
    data_granularity="facility",
    levels_source="carnegie_classification",
    description="R1 doctoral / R2 doctoral / AMC / National lab / Liberal arts",
))
register(Dimension(
    id="lab_headcount", label="Lab Headcount",
    family=DimensionFamily.INSTITUTIONAL_RESEARCH,
    candidate_when=_is_research,
    may_differentiate=frozenset({"adoption","price"}),
    data_granularity="individual",
    levels_source="intake",
    description="Solo PI (<3) / Small (3–10) / Medium (11–30) / Large (>30)",
))
register(Dimension(
    id="core_facility_presence", label="Core Facility Presence",
    family=DimensionFamily.INSTITUTIONAL_RESEARCH,
    candidate_when=_is_research,
    may_differentiate=frozenset({"channel","price"}),
    data_granularity="facility",
    levels_source="intake",
    description="Has institutional core / No core facility",
))
register(Dimension(
    id="purchase_cadence", label="Purchase Cadence",
    family=DimensionFamily.INSTITUTIONAL_RESEARCH,
    candidate_when=_is_research,
    may_differentiate=frozenset({"timing","adoption"}),
    data_granularity="individual",
    levels_source="intake",
    description="Annual budget cycle / Grant-renewal timed / Ad hoc",
))
