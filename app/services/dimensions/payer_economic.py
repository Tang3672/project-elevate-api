"""Payer / economic dimensions — NOT candidates for research tools."""
from app.services.dimensions import Dimension, DimensionFamily, register

_RESEARCH = frozenset({"research_tool","non_clinical","research_tool_non_clinical"})

def _not_research(c: dict, i: dict) -> bool:
    return str(c.get("archetype","")).lower() not in _RESEARCH

register(Dimension(
    id="payer_type", label="Payer Type",
    family=DimensionFamily.PAYER_ECONOMIC,
    candidate_when=_not_research,
    may_differentiate=frozenset({"price","adoption","access"}),
    data_granularity="national",
    levels_source="cms_pos",
    description="Commercial / Medicare / Medicaid / Other/uninsured",
))
register(Dimension(
    id="formulary_tier", label="Formulary Tier",
    family=DimensionFamily.PAYER_ECONOMIC,
    candidate_when=_not_research,
    may_differentiate=frozenset({"adoption","price"}),
    data_granularity="national",
    levels_source="cms_pos",
    description="Tier 1 (preferred) / Tier 2 / Tier 3 / Not covered",
))
register(Dimension(
    id="prior_auth_burden", label="Prior Authorization Burden",
    family=DimensionFamily.PAYER_ECONOMIC,
    candidate_when=_not_research,
    may_differentiate=frozenset({"adoption","timing"}),
    data_granularity="national",
    levels_source="intake",
    description="No PA / PA required–typically approved / PA required–often denied",
))
register(Dimension(
    id="oop_exposure", label="Out-of-Pocket Exposure",
    family=DimensionFamily.PAYER_ECONOMIC,
    candidate_when=_not_research,
    may_differentiate=frozenset({"adoption","access"}),
    data_granularity="individual",
    levels_source="intake",
    description="Low (<$500/yr) / Medium ($500–$3K) / High (>$3K)",
))
register(Dimension(
    id="coverage_status", label="Coverage / Reimbursement Status",
    family=DimensionFamily.PAYER_ECONOMIC,
    candidate_when=_not_research,
    may_differentiate=frozenset({"adoption","access","price"}),
    data_granularity="national",
    levels_source="cms_lab_fee_schedule",
    description="Covered / Coverage gap / Not reimbursed",
))
