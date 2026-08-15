"""
Market sizing axis library — Spec v4 Part C.

Implements the axis-selection and rejection engine.  Each AxisDefinition
knows which product domains it applies to; select_axes() returns a list of
AxisDecision objects covering both selected and rejected candidates with
human-readable reasons.

The rejection list is deliberately rendered alongside the selection list —
it's what signals expertise ("we considered patient demographics and excluded
them because the buyer is an institutional purchaser, not a patient").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal


AxisFamily = Literal[
    "patient_demographic",
    "geographic",
    "institutional",
    "firmographic",
    "payer",
    "clinical",
    "behavioral",
    "operational",
]


@dataclass
class AxisDefinition:
    """A segmentation axis candidate in the library.

    Definitions are static — they carry no computed numeric values.
    applies_when is a predicate over (domain, expert_domain) that decides
    whether the axis fires for a given classification.
    """
    id:               str
    label:            str
    family:           AxisFamily
    applies_when:     Callable[[str, str], bool]
    rejection_reason: str
    typical_lift:     float = 0.0
    requires:         list[str] = field(default_factory=list)


@dataclass
class AxisDecision:
    """The result of evaluating one AxisDefinition against a classification."""
    axis_id:        str
    label:          str
    family:         AxisFamily
    selected:       bool
    reason:         str
    est_lift:       float | None = None
    data_available: bool = True


# ── Domain predicates ─────────────────────────────────────────────────────────

def _is_clinical(domain: str, _expert: str) -> bool:
    return domain == "LIFE_SCIENCES_CLINICAL"


def _is_research_tool(domain: str, expert: str) -> bool:
    return (
        domain == "LIFE_SCIENCES_RESEARCH"
        or expert.startswith(("research_tool", "research_infrastructure"))
    )


def _is_b2b_commercial(domain: str, _expert: str) -> bool:
    return domain in ("ENGINEERING_HARDWARE", "SOFTWARE_INFRASTRUCTURE")


def _always(_d: str, _e: str) -> bool:
    return True


# ── Axis library ──────────────────────────────────────────────────────────────

AXIS_LIBRARY: list[AxisDefinition] = [

    # Patient-demographic axes — only clinical products
    AxisDefinition(
        id="age_band",
        label="Patient age distribution",
        family="patient_demographic",
        applies_when=_is_clinical,
        rejection_reason=(
            "Buyer is an institutional purchaser (PI / core facility), not a patient "
            "population — patient age adds no discrimination to the addressable market."
        ),
        typical_lift=0.18,
    ),
    AxisDefinition(
        id="sex",
        label="Patient sex",
        family="patient_demographic",
        applies_when=_is_clinical,
        rejection_reason="No patient population in buyer model.",
        typical_lift=0.05,
    ),
    AxisDefinition(
        id="race_ethnicity",
        label="Race / ethnicity",
        family="patient_demographic",
        applies_when=_is_clinical,
        rejection_reason=(
            "Buyer is an institution, not an individual patient — racial/ethnic "
            "epidemiology is inapplicable to this market."
        ),
        typical_lift=0.08,
    ),
    AxisDefinition(
        id="income_quintile",
        label="Patient income quintile",
        family="patient_demographic",
        applies_when=_is_clinical,
        rejection_reason=(
            "No patient buyer; income-based access barriers (co-pay, adherence) "
            "do not apply to an institutional purchasing model."
        ),
        typical_lift=0.12,
    ),

    # Payer / reimbursement axes — clinical only
    AxisDefinition(
        id="insurance_status",
        label="Insurance / payer type",
        family="payer",
        applies_when=_is_clinical,
        rejection_reason=(
            "Product has no reimbursement pathway; payer-mix axis adds no "
            "discrimination to addressable market sizing."
        ),
        typical_lift=0.22,
    ),
    AxisDefinition(
        id="payer_mix",
        label="Payer mix (commercial / Medicare / Medicaid / self-pay)",
        family="payer",
        applies_when=_is_clinical,
        rejection_reason="Product has no reimbursement pathway; payer-mix does not apply.",
        typical_lift=0.22,
    ),

    # Geographic axes — universal
    AxisDefinition(
        id="rural_urban_rucc",
        label="Rural / urban classification (RUCC)",
        family="geographic",
        applies_when=_is_clinical,
        rejection_reason=(
            "Federal research funding concentrates in metro R1 institutions; "
            "rural/urban classification adds no material discrimination for "
            "research-tool buyers."
        ),
        typical_lift=0.14,
    ),
    AxisDefinition(
        id="geography_us_region",
        label="US Census region (Northeast / Midwest / South / West)",
        family="geographic",
        applies_when=_always,
        rejection_reason="",
        typical_lift=0.10,
    ),

    # Institutional axes — research tools
    AxisDefinition(
        id="carnegie_tier",
        label="Carnegie classification tier (R1 / R2 / D1 / other)",
        family="institutional",
        applies_when=_is_research_tool,
        rejection_reason=(
            "Buyer is a clinical institution or commercial entity, not an "
            "academic research lab — Carnegie tier is inapplicable."
        ),
        typical_lift=0.25,
    ),
    AxisDefinition(
        id="funding_agency",
        label="Primary funding agency (NIH / NSF / DoD / other)",
        family="institutional",
        applies_when=_is_research_tool,
        rejection_reason="Buyer is not grant-funded; funding-agency axis is inapplicable.",
        typical_lift=0.18,
    ),
    AxisDefinition(
        id="award_band",
        label="Grant award size band (< $250K / $250K–$1M / > $1M)",
        family="institutional",
        applies_when=_is_research_tool,
        rejection_reason="No grant-funded buyer; award-size axis is inapplicable.",
        typical_lift=0.15,
    ),
    AxisDefinition(
        id="lab_size",
        label="Lab headcount (1–3 / 4–10 / 11+ personnel)",
        family="institutional",
        applies_when=_is_research_tool,
        rejection_reason="Not applicable to this buyer type.",
        typical_lift=0.12,
    ),
    AxisDefinition(
        id="department",
        label="Academic department / field (neuroscience / biology / engineering / …)",
        family="institutional",
        applies_when=_is_research_tool,
        rejection_reason="Not applicable to this buyer type.",
        typical_lift=0.20,
    ),

    # Clinical / therapeutic axes
    AxisDefinition(
        id="line_of_therapy",
        label="Line of therapy (1L / 2L / 3L+)",
        family="clinical",
        applies_when=_is_clinical,
        rejection_reason="Not applicable: product is not a therapeutic.",
        typical_lift=0.28,
    ),
    AxisDefinition(
        id="biomarker",
        label="Biomarker / indication specificity",
        family="clinical",
        applies_when=_is_clinical,
        rejection_reason="Not applicable: no clinical indication or patient biomarker.",
        typical_lift=0.20,
    ),
    AxisDefinition(
        id="site_of_care",
        label="Site of care (inpatient / outpatient / home / clinic)",
        family="clinical",
        applies_when=_is_clinical,
        rejection_reason=(
            "Not a care-delivery product; site-of-care segmentation does not apply."
        ),
        typical_lift=0.16,
    ),

    # Firmographic axes — B2B commercial
    AxisDefinition(
        id="employee_band",
        label="Buyer company headcount band",
        family="firmographic",
        applies_when=_is_b2b_commercial,
        rejection_reason=(
            "Buyer is an academic institution, not a commercial entity — "
            "headcount band is inapplicable."
        ),
        typical_lift=0.15,
    ),
    AxisDefinition(
        id="revenue_band",
        label="Buyer company revenue band",
        family="firmographic",
        applies_when=_is_b2b_commercial,
        rejection_reason=(
            "Buyer is grant-funded; revenue does not determine budget authority "
            "for this product."
        ),
        typical_lift=0.12,
    ),

    # Behavioral / operational axes — universal
    AxisDefinition(
        id="current_solution",
        label="Current solution (status quo / DIY / incumbent tool)",
        family="behavioral",
        applies_when=_always,
        rejection_reason="",
        typical_lift=0.22,
    ),
    AxisDefinition(
        id="purchase_cadence",
        label="Purchase / renewal cadence (one-time / annual / grant-cycle-aligned)",
        family="operational",
        applies_when=_always,
        rejection_reason="",
        typical_lift=0.10,
    ),
]


# ── Candidacy gate ────────────────────────────────────────────────────────────

# Families that require a clinical patient-buyer. No lift value can override this.
CLINICAL_FAMILIES: frozenset[str] = frozenset({"patient_demographic", "payer", "clinical"})


def is_candidate(defn: AxisDefinition, domain: str) -> bool:
    """Hard boolean gate: block clinical-family axes for non-clinical products.

    Runs before applies_when() so no lift value or predicate can override it.
    A product is clinical only when its domain is explicitly LIFE_SCIENCES_CLINICAL.
    """
    if domain != "LIFE_SCIENCES_CLINICAL" and defn.family in CLINICAL_FAMILIES:
        return False
    return True


# ── Selection engine ──────────────────────────────────────────────────────────

def select_axes(domain: str, expert_domain: str) -> list[AxisDecision]:
    """Evaluate AXIS_LIBRARY against a product classification.

    Returns an AxisDecision for every axis — selected (applies_when=True)
    and rejected (applies_when=False) — sorted selected-first by descending
    typical_lift, then rejected in their library order.

    The rejection list is an explicit output: omitting it would remove the
    key signal that distinguishes expert segmentation from naive enumeration.
    """
    domain       = (domain       or "").upper()
    expert_domain = (expert_domain or "").lower()

    selected: list[AxisDecision] = []
    rejected: list[AxisDecision] = []

    for defn in AXIS_LIBRARY:
        # Hard gate runs first — no lift value can override it
        if not is_candidate(defn, domain):
            rejected.append(AxisDecision(
                axis_id=defn.id,
                label=defn.label,
                family=defn.family,
                selected=False,
                reason=defn.rejection_reason,
                est_lift=None,
                data_available=True,
            ))
            continue

        fires = defn.applies_when(domain, expert_domain)
        if fires:
            domain_label = domain.replace("_", " ").lower()
            reason = f"Selected: relevant segmentation axis for {domain_label} products."
            selected.append(AxisDecision(
                axis_id=defn.id,
                label=defn.label,
                family=defn.family,
                selected=True,
                reason=reason,
                est_lift=defn.typical_lift,
                data_available=True,
            ))
        else:
            rejected.append(AxisDecision(
                axis_id=defn.id,
                label=defn.label,
                family=defn.family,
                selected=False,
                reason=defn.rejection_reason,
                est_lift=None,
                data_available=True,
            ))

    selected.sort(key=lambda d: -(d.est_lift or 0.0))
    return selected + rejected


def format_axis_decisions(decisions: list[AxisDecision]) -> dict:
    """Serialize axis decisions for report storage.

    Returns {"selected": [...], "rejected": [...]} with each entry as a dict.
    Used by alignment_service to attach decisions to the report.
    """
    def _to_dict(d: AxisDecision) -> dict:
        return {
            "axis_id":        d.axis_id,
            "label":          d.label,
            "family":         d.family,
            "selected":       d.selected,
            "reason":         d.reason,
            "est_lift":       d.est_lift,
            "data_available": d.data_available,
        }

    return {
        "selected": [_to_dict(d) for d in decisions if d.selected],
        "rejected": [_to_dict(d) for d in decisions if not d.selected],
    }
