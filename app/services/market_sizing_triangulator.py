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


def compute_top_down(
    disease_name: str,
    therapeutic_area: str,
    product_type: str,
    prevalent_patients: Optional[int] = None,
) -> tuple[float, float, float, float, str]:
    """
    Top-down TAM estimate:
      TA market anchor × disease prevalence share × product-type share

    Returns:
      (top_down_tam_usd, ta_anchor_usd, disease_share, product_share, source_note)
    """
    ta = therapeutic_area.lower()
    pt = product_type.lower()

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
            "The gap represents patients who exist but are not yet reachable "
            "(undiagnosed, untreated, or out of label)."
        )
    else:
        direction = (
            f"Both methods converge tightly ({_fmt(a)} vs {_fmt(b)}). "
            "This is the strongest possible validation signal."
        )

    note = (
        f"{note_prefix} ({divergence:.0%} divergence)\n"
        f"  Bottom-up SAM (patient-based): {_fmt(a)}\n"
        f"  Top-down TAM (industry anchor): {_fmt(b)}\n"
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
    )
    return triangulate(
        bottom_up_sam_usd=bottom_up_sam_usd,
        bottom_up_tam_usd=bottom_up_tam_usd,
        top_down_tam_usd=top_down_tam,
        disease_name=disease_name,
        therapeutic_area=therapeutic_area,
        product_type=product_type,
        prevalent_patients=prevalent_patients,
        underdiagnosis_multiplier=underdiagnosis_multiplier,
        underdiagnosis_rationale=underdiagnosis_rationale,
        treatment_funnel_summary=treatment_funnel_summary,
    )
