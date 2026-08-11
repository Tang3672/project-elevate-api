"""Firmographic dimensions — institutional buyers (device, diagnostic, digital, research)."""
from app.services.dimensions import Dimension, DimensionFamily, register

_INSTITUTIONAL = frozenset({"device","diagnostic","digital","digital_samd","research_tool","non_clinical"})

def _is_institutional(c: dict, i: dict) -> bool:
    return str(c.get("archetype","")).lower() in _INSTITUTIONAL

register(Dimension(
    id="naics_sector", label="NAICS Sector",
    family=DimensionFamily.FIRMOGRAPHIC,
    candidate_when=_is_institutional,
    may_differentiate=frozenset({"price","channel","adoption"}),
    data_granularity="national",
    levels_source="census_cbp",
    description="Healthcare / Biotech / Pharma / Academic / Government",
))
register(Dimension(
    id="employee_band", label="Employee Band",
    family=DimensionFamily.FIRMOGRAPHIC,
    candidate_when=_is_institutional,
    may_differentiate=frozenset({"price","adoption"}),
    data_granularity="national",
    levels_source="census_susb",
    description="<50 / 50–500 / >500 employees",
))
register(Dimension(
    id="procurement_model", label="Procurement Model",
    family=DimensionFamily.FIRMOGRAPHIC,
    candidate_when=_is_institutional,
    may_differentiate=frozenset({"price","timing","channel"}),
    data_granularity="facility",
    levels_source="intake",
    description="Centralized / Departmental / GPO-negotiated",
))
register(Dimension(
    id="replacement_cycle", label="Replacement Cycle",
    family=DimensionFamily.FIRMOGRAPHIC,
    candidate_when=_is_institutional,
    may_differentiate=frozenset({"timing","adoption"}),
    data_granularity="facility",
    levels_source="intake",
    description="<2 yrs / 2–5 yrs / >5 yrs",
))
