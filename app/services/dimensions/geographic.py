"""Geographic dimensions — broad candidates (all archetypes)."""
from app.services.dimensions import Dimension, DimensionFamily, register

_CLINICAL_DEVICE = frozenset({"small_molecule","biologic","gene_cell","vaccine","therapeutic","device","diagnostic","digital"})

def _always(c: dict, i: dict) -> bool:
    return True

def _needs_center_access(c: dict, i: dict) -> bool:
    return str(c.get("archetype","")).lower() in _CLINICAL_DEVICE

register(Dimension(
    id="census_division", label="US Census Division",
    family=DimensionFamily.GEOGRAPHIC,
    candidate_when=_always,
    may_differentiate=frozenset({"adoption","access"}),
    data_granularity="national",
    levels_source="census_bureau",
    description="9 US Census divisions",
))
register(Dimension(
    id="state", label="State",
    family=DimensionFamily.GEOGRAPHIC,
    candidate_when=_always,
    may_differentiate=frozenset({"adoption","access","price"}),
    data_granularity="state",
    levels_source="census_bureau",
    description="50 states + DC",
))
register(Dimension(
    id="rural_urban", label="Rural–Urban Continuum",
    family=DimensionFamily.GEOGRAPHIC,
    candidate_when=_always,
    may_differentiate=frozenset({"access","adoption"}),
    data_granularity="cbsa",
    levels_source="usda_ruca",
    description="Urban core / Suburban / Rural (RUCA codes)",
))
register(Dimension(
    id="distance_to_center", label="Distance to Nearest Treating Center",
    family=DimensionFamily.GEOGRAPHIC,
    candidate_when=_needs_center_access,
    may_differentiate=frozenset({"access","adoption"}),
    data_granularity="cbsa",
    levels_source="cms_pos",
    description="<30 mi / 30–100 mi / >100 mi to nearest treating center",
))
register(Dimension(
    id="con_state", label="CON State",
    family=DimensionFamily.GEOGRAPHIC,
    candidate_when=_needs_center_access,
    may_differentiate=frozenset({"access","adoption","timing"}),
    data_granularity="state",
    levels_source="ncsl_con_laws",
    description="Certificate-of-need state / Non-CON state",
))
