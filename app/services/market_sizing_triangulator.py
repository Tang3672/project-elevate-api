"""
Market Sizing Triangulator  (Step 10 of the orchestrator pipeline)
===================================================================
Implements the three-methodology triangulation recommended by Kim & Sawada (2024)
and the ISPOR/PM360 patient-based market sizing framework:

  Method A — Bottom-up (patient-based):
    Reported prevalence → under-diagnosis correction → diagnostic funnel
    → treatment funnel → eligibility funnel → price × population = SAM

  Method B — Top-down (industry segment):
    Published TA market size → disease-specific share → product-type share
    → product's realistic slice = TAM estimate

  Cross-validation:
    Compare A and B. If they diverge > DIVERGENCE_THRESHOLD, flag and reconcile
    using a weighted geometric mean that discounts the outlier.

Returns TriangulationResult with:
  - both estimates
  - divergence ratio
  - reconciled figure
  - a plain-English note ready for injection into the Claude prompt
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Divergence threshold above which we flag and reconcile.
# 25% is the industry standard (McKinsey/Waveup triangulation playbook).
DIVERGENCE_THRESHOLD = 0.25

# ── Published therapeutic area market sizes (US, 2024-2025, USD) ──────────────
# Sources: GlobalData, EvaluatePharma, IQVIA, Grand View Research (2024 reports).
# These are the TOTAL US drug/device/biologics REVENUE for the TA — not patient
# counts. Used as the anchor for the top-down calculation.
_TA_MARKET_USD: dict[str, float] = {
    "oncology":        210_000_000_000,   # $210B — IQVIA 2024 US oncology spend
    "hematology":       38_000_000_000,   # $38B  — EvaluatePharma 2024
    "rare_disease":     22_000_000_000,   # $22B  — NORD/IQVIA 2024 orphan segment
    "gene_therapy":      4_500_000_000,   # $4.5B — ASGCT 2024 commercial gene therapy
    "cns":              90_000_000_000,   # $90B  — GlobalData US CNS 2024
    "cardiovascular":   60_000_000_000,   # $60B  — IQVIA CardioVascular 2024
    "metabolic":        85_000_000_000,   # $85B  — GLP-1 driven; IQVIA 2024
    "amr_infectious":   12_000_000_000,   # $12B  — BARDA/CARB-X market estimate
    "immunology":       95_000_000_000,   # $95B  — IQVIA US immunology 2024
    "ophthalmology":    18_000_000_000,   # $18B  — GlobalData US ophthalmology 2024
    "vaccine":          25_000_000_000,   # $25B  — IQVIA US vaccine 2024
    "device":           80_000_000_000,   # $80B  — AdvaMed US device market 2024
    "diagnostic":       30_000_000_000,   # $30B  — GlobalData US diagnostics 2024
    "respiratory":      35_000_000_000,   # $35B  — IQVIA US respiratory 2024
    "other":            15_000_000_000,   # $15B  — conservative placeholder
}

# Product-type share of the TA revenue. Novel products typically capture
# a fraction of total TA spend, depending on how differentiated they are.
# These are calibrated to FDA approval histories and EvaluatePharma peak-sales data.
_PRODUCT_TYPE_SHARE: dict[str, float] = {
    "drug_small_molecule": 0.040,    # 4% of TA market — typical peak for new SMD entrant
    "biologic":            0.055,    # 5.5% — biologics command larger share due to fewer competitors
    "gene_cell_therapy":   0.120,    # 12% — small total market, near-monopoly if approved
    "gene_therapy":        0.120,
    "medical_device":      0.030,    # 3% — devices are more fragmented
    "device":              0.030,
    "diagnostic":          0.045,    # 4.5% — companion diagnostics can be category-defining
    "digital_health":      0.020,    # 2% — software in healthcare struggles with adoption
    "vaccine_immunotherapy":0.080,   # 8% — vaccines can be near-universal in target population
    "vaccine":             0.080,
    "antibiotic":          0.025,    # 2.5% — AMR pricing is constrained by push incentives
    "drug_amr":            0.025,
    "other_platform":      0.035,
}


@dataclass
class TriangulationResult:
    # Method A — bottom-up (passed in from orchestrator)
    bottom_up_sam_usd: float

    # Method B — top-down
    top_down_tam_usd: float
    ta_market_anchor_usd: float         # TA total market used as anchor
    product_type_share: float           # fraction of TA attributed to this product type
    disease_prevalence_share: float     # fraction of TA market attributed to this disease
    top_down_source: str

    # Cross-validation
    divergence_ratio: float             # |A - B| / max(A, B)
    divergence_flagged: bool            # True when > DIVERGENCE_THRESHOLD
    reconciled_sam_usd: float           # weighted geometric mean
    reconciliation_weight_bottom_up: float
    reconciliation_weight_top_down: float

    # Plain-English output for the Claude prompt
    cross_validation_note: str

    # Under-diagnosis context (carried from engine for display)
    underdiagnosis_multiplier: float = field(default=1.0)
    underdiagnosis_rationale: str = field(default="")

    # Treatment funnel summary
    treatment_funnel_summary: str = field(default="")

    # Product archetype, and the stepwise top-down derivation when one was built.
    # Research tools size top-down off federal research funding rather than a
    # therapeutic drug anchor, and each factor carries its own range and source so
    # the top-down can be shown as a waterfall beside the bottom-up.
    archetype: str = field(default="")
    top_down_steps: list = field(default_factory=list)
    top_down_tam_lo_usd: float = field(default=0.0)
    top_down_tam_hi_usd: float = field(default=0.0)

    def to_dict(self) -> dict:
        return {
            "bottom_up_sam_usd":             round(self.bottom_up_sam_usd),
            "top_down_tam_usd":              round(self.top_down_tam_usd),
            "ta_market_anchor_usd":          round(self.ta_market_anchor_usd),
            "product_type_share":            round(self.product_type_share, 4),
            "disease_prevalence_share":      round(self.disease_prevalence_share, 4),
            "divergence_ratio":              round(self.divergence_ratio, 3),
            "divergence_flagged":            self.divergence_flagged,
            "reconciled_sam_usd":            round(self.reconciled_sam_usd),
            "reconciliation_weight_bottom_up": round(self.reconciliation_weight_bottom_up, 3),
            "reconciliation_weight_top_down":  round(self.reconciliation_weight_top_down, 3),
            "underdiagnosis_multiplier":     round(self.underdiagnosis_multiplier, 2),
            "underdiagnosis_rationale":      self.underdiagnosis_rationale,
            "treatment_funnel_summary":      self.treatment_funnel_summary,
            "cross_validation_note":         self.cross_validation_note,
            "archetype":                     self.archetype,
            "top_down_steps":                self.top_down_steps,
            "top_down_tam_lo_usd":           round(self.top_down_tam_lo_usd),
            "top_down_tam_hi_usd":           round(self.top_down_tam_hi_usd),
        }


def _fmt(usd: float) -> str:
    if usd >= 1e9:
        return f"${usd / 1e9:.1f}B"
    if usd >= 1e6:
        return f"${usd / 1e6:.0f}M"
    return f"${usd / 1e3:.0f}K"


def _disease_prevalence_share(
    disease_name: str,
    therapeutic_area: str,
    prevalent_patients: Optional[int],
) -> float:
    """
    Estimate this disease's share of its TA's total patient population.
    Used to narrow the TA-level market anchor to a disease-specific slice.

    If prevalence is known, compute the share from TA-level patient counts.
    Otherwise fall back to a conservative default.
    """
    # Approximate US patient populations for common TAs (for share calculation)
    _TA_PATIENTS: dict[str, int] = {
        "oncology":        1_900_000,    # ~1.9M new cancer diagnoses/yr (SEER)
        "hematology":        200_000,    # blood cancers subset
        "rare_disease":       30_000,    # median rare disease US prevalence
        "gene_therapy":       10_000,    # ultra-rare
        "cns":             5_000_000,    # all neurological conditions combined
        "cardiovascular":  6_000_000,   # heart failure + AF + CAD combined
        "metabolic":      38_000_000,   # T2D alone
        "amr_infectious":    300_000,   # serious AMR infections/yr
        "immunology":      3_000_000,   # RA + IBD + psoriasis combined
        "ophthalmology":   2_000_000,   # wet AMD + glaucoma combined
        "vaccine":       100_000_000,   # target populations are large
        "device":         10_000_000,   # procedure-based — approximate
        "diagnostic":     50_000_000,   # broad
        "respiratory":    25_000_000,   # COPD + asthma US
        "other":           1_000_000,
    }
    ta = therapeutic_area.lower()
    ta_patients = _TA_PATIENTS.get(ta, 1_000_000)

    if prevalent_patients and prevalent_patients > 0:
        share = min(prevalent_patients / ta_patients, 1.0)
        return max(share, 0.001)   # floor at 0.1% to avoid zero

    # No prevalence known — use TA default share
    _TA_DEFAULT_SHARE: dict[str, float] = {
        "rare_disease":  0.30,   # orphan diseases dominate small TAs
        "gene_therapy":  0.40,
        "oncology":      0.05,   # one of many cancer types
        "hematology":    0.15,
        "other":         0.10,
    }
    return _TA_DEFAULT_SHARE.get(ta, 0.08)


# ── Research-tool top-down: federal research funding, not a drug market ───────
# The clinical anchors above are therapeutic drug markets. Pointing them at a lab
# instrument or research-software product is a category error — a behavioural-lab
# data tool does not compete for oncology drug spend — and it produced a top-down
# figure built entirely from fallback defaults. Research tools are bought out of
# federal grant budgets, so the anchor chain follows that money instead.
#
# Every factor carries a lo/mid/hi range and a citable source, matching the rigour
# of the bottom-up buyer model rather than a single-point multiply. Factors that
# are genuinely assumed are marked assumed=True so the report can say so.

_FEDERAL_RESEARCH_FUNDING_USD = {
    # Checked against FY2025 appropriations: NIH program level ~$47.0B with ~82-83%
    # going to extramural research (~$39B), plus NSF Research & Related Activities
    # at $7.53B — roughly $46.5B combined. The band is kept wide because the figure
    # moves with each appropriation cycle and continuing resolutions.
    "lo": 42_000_000_000, "mid": 47_000_000_000, "hi": 52_000_000_000,
    "source": "NIH FY2025 appropriation (~83% extramural) + NSF FY2025 Research & Related Activities ($7.53B)",
    "source_url": "https://www.nih.gov/about-nih/organization/budget",
}

# Field share of federal extramural research funding. NIH reports categorical
# spending by research area (RCDC); these are the shares of the combined
# NIH + NSF extramural pool attributable to each field.
_FIELD_FUNDING_SHARE = {
    "neuroscience":   (0.14, 0.19, 0.24),
    "cns":            (0.14, 0.19, 0.24),
    "oncology":       (0.12, 0.16, 0.20),
    "immunology":     (0.08, 0.11, 0.14),
    "genomics":       (0.05, 0.08, 0.11),
    "cardiovascular": (0.05, 0.07, 0.09),
    "metabolic":      (0.04, 0.06, 0.08),
    "agronomy":       (0.02, 0.04, 0.06),
    "engineering":    (0.05, 0.08, 0.11),
    "other":          (0.03, 0.06, 0.09),
}

# Share of grant direct costs that buys equipment and supplies rather than
# personnel. NIH modular budgets put personnel well above half of direct costs;
# equipment + supplies is the line a research tool is actually purchased from.
_EQUIPMENT_SUPPLIES_SHARE = (0.08, 0.12, 0.18)
_EQUIPMENT_SOURCE_URL = "https://grants.nih.gov/grants/policy/nihgps/nihgps.pdf"

# Share of the equipment + supplies line spent on software and data infrastructure
# rather than reagents, consumables and bench hardware. This is the least grounded
# factor in the chain and is reported as an explicit assumption with a wide band.
_RESEARCH_SOFTWARE_SHARE = (0.03, 0.06, 0.10)


def compute_top_down_research_tool(
    field: str,
    idea: str = "",
) -> tuple[float, float, float, list[dict]]:
    """Stepwise top-down TAM for a research tool, sized off federal research funding.

    Returns (tam_lo, tam_mid, tam_hi, steps) where each step records its own
    lo/mid/hi, unit, source and whether it is an assumption — so the top-down can
    be rendered as a waterfall beside the bottom-up instead of a single number.
    """
    f = (field or "other").lower()
    fund = _FEDERAL_RESEARCH_FUNDING_USD
    fs_lo, fs_mid, fs_hi = _FIELD_FUNDING_SHARE.get(f, _FIELD_FUNDING_SHARE["other"])
    eq_lo, eq_mid, eq_hi = _EQUIPMENT_SUPPLIES_SHARE
    sw_lo, sw_mid, sw_hi = _RESEARCH_SOFTWARE_SHARE

    steps = [
        {
            "step": 1,
            "label": "US federal extramural research funding",
            "lo": fund["lo"], "mid": fund["mid"], "hi": fund["hi"],
            "unit": "USD/yr",
            "basis": "NIH extramural (~80% of appropriation) plus the NSF research account. "
                     "This is the pool research-tool purchases are made from.",
            "source": fund["source"],
            "source_url": fund["source_url"],
            "assumed": False,
        },
        {
            "step": 2,
            "label": f"Share of that funding in {field or 'this field'}",
            "lo": fs_lo, "mid": fs_mid, "hi": fs_hi,
            "unit": "fraction",
            "basis": "NIH reports categorical spending by research area (RCDC). This share is "
                     "approximate: the RCDC table is the authoritative figure and should be "
                     "read directly for the field in question before the number is quoted.",
            "source": "NIH RePORT categorical spending (approximate — verify against the RCDC table)",
            "source_url": "https://report.nih.gov/funding/categorical-spending",
            "assumed": False,
        },
        {
            "step": 3,
            "label": "Equipment and supplies share of grant direct costs",
            "lo": eq_lo, "mid": eq_mid, "hi": eq_hi,
            "unit": "fraction",
            "basis": "Personnel dominates direct costs; equipment and supplies is the budget "
                     "line a research tool is purchased from.",
            "source": "NIH Grants Policy Statement (budget composition)",
            "source_url": _EQUIPMENT_SOURCE_URL,
            "assumed": False,
        },
        {
            "step": 4,
            "label": "Software and data-infrastructure share of that line",
            "lo": sw_lo, "mid": sw_mid, "hi": sw_hi,
            "unit": "fraction",
            "basis": "Fraction spent on software and data tooling rather than reagents, "
                     "consumables and bench hardware. Least grounded factor in the chain — "
                     "validate against institutional procurement data before relying on it.",
            "source": "Assumed — no primary source; reported as an explicit assumption",
            "source_url": "",
            "assumed": True,
        },
    ]

    tam_lo = fund["lo"] * fs_lo * eq_lo * sw_lo
    tam_mid = fund["mid"] * fs_mid * eq_mid * sw_mid
    tam_hi = fund["hi"] * fs_hi * eq_hi * sw_hi

    steps.append({
        "step": 5,
        "label": "Top-down TAM (product of steps 1-4)",
        "lo": tam_lo, "mid": tam_mid, "hi": tam_hi,
        "unit": "USD/yr",
        "basis": "Range is the product of the low and high ends; the midpoint is the "
                 "planning base. Compare against the bottom-up TAM, not the SAM.",
        "source": "Derived from steps 1-4",
        "source_url": "",
        "assumed": False,
    })
    return tam_lo, tam_mid, tam_hi, steps


def _is_research_archetype(archetype: str, therapeutic_area: str = "") -> bool:
    a = (archetype or "").lower()
    return a.startswith(("research_tool", "research_infrastructure"))


def compute_top_down(
    disease_name: str,
    therapeutic_area: str,
    product_type: str,
    prevalent_patients: Optional[int] = None,
    archetype: str = "",
) -> tuple[float, float, float, float, str]:
    """
    Top-down TAM estimate:
      TA market anchor × disease prevalence share × product-type share

    Returns:
      (top_down_tam_usd, ta_anchor_usd, disease_share, product_share, source_note)
    """
    ta = therapeutic_area.lower()
    pt = product_type.lower()

    # Research tools are bought from grant budgets, not from therapeutic drug spend.
    # Routing them through the clinical anchors produced a figure assembled entirely
    # from fallback defaults ($15B "other" placeholder x default shares).
    if _is_research_archetype(archetype, ta):
        _lo, _mid, _hi, _steps = compute_top_down_research_tool(ta, disease_name)
        return (
            _mid,
            _FEDERAL_RESEARCH_FUNDING_USD["mid"],
            _FIELD_FUNDING_SHARE.get(ta, _FIELD_FUNDING_SHARE["other"])[1],
            _EQUIPMENT_SUPPLIES_SHARE[1] * _RESEARCH_SOFTWARE_SHARE[1],
            "Top-down (research tool): US federal extramural research funding "
            f"({_fmt(_FEDERAL_RESEARCH_FUNDING_USD['mid'])}) x field share x "
            f"equipment/supplies share x software share = {_fmt(_mid)} "
            f"(range {_fmt(_lo)}-{_fmt(_hi)})",
        )

    ta_anchor = _TA_MARKET_USD.get(ta, _TA_MARKET_USD["other"])
    disease_share = _disease_prevalence_share(disease_name, ta, prevalent_patients)
    product_share = _PRODUCT_TYPE_SHARE.get(pt, _PRODUCT_TYPE_SHARE.get("other_platform", 0.035))

    top_down_tam = ta_anchor * disease_share * product_share

    source = (
        f"Top-down: US {therapeutic_area} market ({_fmt(ta_anchor)}) "
        f"× disease share ({disease_share:.1%}) × product-type share ({product_share:.1%})"
    )
    return top_down_tam, ta_anchor, disease_share, product_share, source


def triangulate(
    bottom_up_sam_usd: float,
    top_down_tam_usd: float,
    disease_name: str,
    therapeutic_area: str,
    product_type: str,
    bottom_up_tam_usd: Optional[float] = None,
    prevalent_patients: Optional[int] = None,
    archetype: str = "",
    underdiagnosis_multiplier: float = 1.0,
    underdiagnosis_rationale: str = "",
    treatment_funnel_summary: str = "",
) -> TriangulationResult:
    """
    Cross-validate bottom-up SAM against top-down TAM.

    Reconciliation logic:
    - If divergence ≤ 25%: simple average (both estimates are credible)
    - If divergence 25–75%: weighted geometric mean — bottom-up gets 70%
      weight (it's more data-driven); top-down gets 30%
    - If divergence > 75%: bottom-up wins with 85% weight and a strong flag
      prompting the analyst to review the top-down TA anchor assumption

    Note on bottom-up vs top-down semantics:
      Bottom-up SAM is the Serviceable Addressable Market (post-funnel).
      Top-down TAM is the Total Addressable Market (pre-funnel, broader).
      We expect top-down ≥ bottom-up; if bottom-up > top-down something is wrong.
    """
    _td_steps: list = []
    _td_lo = _td_hi = 0.0
    if _is_research_archetype(archetype, therapeutic_area):
        _td_lo, _td_mid, _td_hi, _td_steps = compute_top_down_research_tool(
            therapeutic_area, disease_name)

    a = max(bottom_up_sam_usd, 1.0)
    b = max(top_down_tam_usd, 1.0)

    # Divergence must compare the SAME funnel stage. Measuring bottom-up SAM
    # against top-down TAM builds the SAM fraction into the "disagreement": with a
    # 60% SAM fraction two models that agree perfectly still score 40% divergence,
    # above the 25% threshold, so the check could never pass. Compare TAM to TAM
    # whenever the bottom-up TAM is available; fall back to the old behaviour only
    # when it is not.
    if bottom_up_tam_usd and bottom_up_tam_usd > 0:
        _cmp_a = max(float(bottom_up_tam_usd), 1.0)
        divergence = abs(_cmp_a - b) / max(_cmp_a, b)
    else:
        divergence = abs(a - b) / max(a, b)
    flagged = divergence > DIVERGENCE_THRESHOLD

    # Reconciliation weights: bottom-up is always more trusted (built from real
    # patient flows), but top-down provides a sanity anchor from published data.
    if divergence <= DIVERGENCE_THRESHOLD:
        w_bu, w_td = 0.60, 0.40
        note_prefix = "✓ CROSS-VALIDATION PASSED"
    elif divergence <= 0.75:
        w_bu, w_td = 0.70, 0.30
        note_prefix = "⚠ CROSS-VALIDATION DIVERGENCE DETECTED"
    else:
        w_bu, w_td = 0.85, 0.15
        note_prefix = "🚨 LARGE CROSS-VALIDATION DIVERGENCE — REVIEW REQUIRED"

    # Weighted geometric mean: A^w_bu × B^w_td
    reconciled = (a ** w_bu) * (b ** w_td)

    # Build the plain-English note for the Claude prompt
    direction = ""
    if a > b * 1.05:
        direction = (
            f"Bottom-up SAM ({_fmt(a)}) is HIGHER than top-down TAM ({_fmt(b)}). "
            "This can indicate that the TA market anchor underestimates this specific disease, "
            "or that the treatment funnel is wider than industry average. "
            "Verify the eligibility fraction and net price assumptions."
        )
    elif b > a * 1.05:
        direction = (
            f"Top-down TAM ({_fmt(b)}) is HIGHER than bottom-up SAM ({_fmt(a)}). "
            "This is expected — TAM is broader than post-funnel SAM. "
            + ("The gap represents labs that sit in the funded field but are not "
               "reachable for this workflow (wrong instrumentation, no unmet need, "
               "or no budget line in the current cycle)."
               if _is_research_archetype(archetype, therapeutic_area) else
               "The gap represents patients who exist but are not yet reachable "
               "(undiagnosed, untreated, or out of label).")
        )
    else:
        direction = (
            f"Both methods converge tightly ({_fmt(a)} vs {_fmt(b)}). "
            "This is the strongest possible validation signal."
        )

    # Label the comparison for what it actually is. The bottom-up figure compared
    # here is the TAM (same funnel stage as the top-down), and a research tool is
    # sized off grant budgets rather than a patient population.
    _is_research = _is_research_archetype(archetype, therapeutic_area)
    bu_cmp = float(bottom_up_tam_usd) if (bottom_up_tam_usd and bottom_up_tam_usd > 0) else a
    _bu_basis = "buyer population x spend" if _is_research else "patient-based"
    _td_basis = "federal research funding chain" if _is_research else "industry anchor"
    _td_range = f" (range {_fmt(_td_lo)}-{_fmt(_td_hi)})" if (_td_lo and _td_hi) else ""
    if _td_lo and _td_hi and _td_lo <= bu_cmp <= _td_hi:
        _within_note = (
            "The bottom-up TAM falls INSIDE the top-down range, so the two methods "
            "corroborate each other despite the midpoint gap."
        )
    elif _td_lo and _td_hi:
        _within_note = (
            "The bottom-up TAM falls OUTSIDE the top-down range - reconcile the "
            "buyer population or the field/equipment share assumptions."
        )
    else:
        _within_note = "Top-down is a single-point anchor; no range available to test containment."

    note = (
        f"{note_prefix} ({divergence:.0%} divergence)\n"
        f"  Bottom-up TAM ({_bu_basis}): {_fmt(bu_cmp)}\n"
        f"  Top-down TAM ({_td_basis}): {_fmt(b)}{_td_range}\n"
        f"  {_within_note}\n"
        f"  Reconciled estimate:            {_fmt(reconciled)} "
        f"  (bottom-up weight {w_bu:.0%} / top-down weight {w_td:.0%})\n"
        f"  {direction}"
    )

    if flagged and divergence > 0.75:
        note += (
            "\n  ACTION REQUIRED: Divergence exceeds 75%. "
            "Review (a) the TA market anchor for currency and scope, "
            "(b) the net price assumption in the bottom-up model, "
            "(c) the treatment eligibility fraction."
        )

    return TriangulationResult(
        bottom_up_sam_usd=a,
        top_down_tam_usd=b,
        ta_market_anchor_usd=_TA_MARKET_USD.get(therapeutic_area.lower(), 0),
        product_type_share=_PRODUCT_TYPE_SHARE.get(
            product_type.lower(),
            _PRODUCT_TYPE_SHARE.get("other_platform", 0.035)
        ),
        disease_prevalence_share=_disease_prevalence_share(
            disease_name, therapeutic_area, prevalent_patients
        ),
        top_down_source=f"US {therapeutic_area} TA anchor × disease share × product-type share",
        divergence_ratio=divergence,
        divergence_flagged=flagged,
        reconciled_sam_usd=reconciled,
        reconciliation_weight_bottom_up=w_bu,
        reconciliation_weight_top_down=w_td,
        cross_validation_note=note,
        archetype=archetype,
        top_down_steps=_td_steps,
        top_down_tam_lo_usd=_td_lo,
        top_down_tam_hi_usd=_td_hi,
        underdiagnosis_multiplier=underdiagnosis_multiplier,
        underdiagnosis_rationale=underdiagnosis_rationale,
        treatment_funnel_summary=treatment_funnel_summary,
    )


def run(
    disease_name: str,
    therapeutic_area: str,
    product_type: str,
    bottom_up_sam_usd: float,
    bottom_up_tam_usd: Optional[float] = None,
    prevalent_patients: Optional[int] = None,
    underdiagnosis_multiplier: float = 1.0,
    underdiagnosis_rationale: str = "",
    treatment_funnel_summary: str = "",
    archetype: str = "",
) -> TriangulationResult:
    """
    Entry point called by the orchestrator (Step 10).
    Runs the top-down calculation then triangulates against the bottom-up SAM.
    """
    top_down_tam, _ta_anchor, _ds, _ps, _src = compute_top_down(
        disease_name=disease_name,
        therapeutic_area=therapeutic_area,
        product_type=product_type,
        prevalent_patients=prevalent_patients,
        archetype=archetype,
    )
    return triangulate(
        bottom_up_sam_usd=bottom_up_sam_usd,
        bottom_up_tam_usd=bottom_up_tam_usd,
        top_down_tam_usd=top_down_tam,
        disease_name=disease_name,
        therapeutic_area=therapeutic_area,
        product_type=product_type,
        prevalent_patients=prevalent_patients,
        archetype=archetype,
        underdiagnosis_multiplier=underdiagnosis_multiplier,
        underdiagnosis_rationale=underdiagnosis_rationale,
        treatment_funnel_summary=treatment_funnel_summary,
    )
