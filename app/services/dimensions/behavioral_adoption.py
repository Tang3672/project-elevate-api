"""Behavioral / adoption dimensions — candidates for all archetypes."""
from app.services.dimensions import Dimension, DimensionFamily, register

def _always(c: dict, i: dict) -> bool:
    return True

register(Dimension(
    id="switching_cost", label="Switching Cost from Incumbent",
    family=DimensionFamily.BEHAVIORAL_ADOPTION,
    candidate_when=_always,
    may_differentiate=frozenset({"adoption","timing"}),
    data_granularity="individual",
    levels_source="intake",
    description="Low (open API) / Medium / High (deep integration)",
))
register(Dimension(
    id="decision_maker_seniority", label="Decision-Maker Seniority",
    family=DimensionFamily.BEHAVIORAL_ADOPTION,
    candidate_when=_always,
    may_differentiate=frozenset({"timing","channel"}),
    data_granularity="individual",
    levels_source="intake",
    description="Lab PI / Dept chair / C-suite / Procurement committee",
))
register(Dimension(
    id="workflow_integration_depth", label="Workflow Integration Depth",
    family=DimensionFamily.BEHAVIORAL_ADOPTION,
    candidate_when=_always,
    may_differentiate=frozenset({"adoption","timing","price"}),
    data_granularity="individual",
    levels_source="intake",
    description="Standalone / Integrated with 1 system / Enterprise",
))
register(Dimension(
    id="reference_customer_sensitivity", label="Reference-Customer Sensitivity",
    family=DimensionFamily.BEHAVIORAL_ADOPTION,
    candidate_when=_always,
    may_differentiate=frozenset({"timing","adoption"}),
    data_granularity="individual",
    levels_source="intake",
    description="Needs KOL endorsement / Peer reference / No reference required",
))
