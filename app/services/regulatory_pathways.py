"""
Regulatory Pathways  (Build Spec v6, Part 2)
=============================================
Genuinely distinct pathway models per product type — not generic "FDA review" prose.

Each product family has its own ordered stages, durations, gate probabilities,
and reimbursement path.  The router infers the specific sub-path (510(k) vs PMA
vs De Novo; LDT vs IVD; SaMD class) from the product type + idea text.

Key asymmetry surfaced here that is invisible in the current engine:
  • Drugs:    FDA clearance → formulary access ~ 6-18 months (Part D/B)
  • Devices:  FDA clearance → Medicare coverage ~ 6.7 years median (JAMA 2021)
              (reduced to 2.5 yr with Breakthrough Device + NTAP)
  • Dx:       FDA clearance → CMS LCD ~ 12-24 months; gapfill/crosswalk pricing
  • SaMD:     Often NO reimbursement code exists — this is surfaced as a
              "critical risk: no standard payer pathway" flag.

Reimbursement failure is where commercialization actually dies, so this layer
makes that risk explicit in the report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ──────────────────────────────────────────────────────────────────────────────
# Data types
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class PathwayStage:
    """One stage in a regulatory/development pathway."""
    stage: str                          # unique ID, e.g. "ind", "phase1", "510k_submission"
    label: str                          # human-readable name
    typical_duration_months: float      # median duration in months
    evidence_required: str             # what must be produced
    gate_probability: float            # P(proceed to next stage | entering this stage)
    cost_estimate_usd: Optional[float] # order-of-magnitude cost; None = varies widely
    source: str                        # citation or basis
    confidence: str                    # "high" | "medium" | "low"

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "label": self.label,
            "typical_duration_months": self.typical_duration_months,
            "evidence_required": self.evidence_required,
            "gate_probability": self.gate_probability,
            "cost_estimate_usd": self.cost_estimate_usd,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass
class ReimbursementPath:
    """The payer coverage pathway after regulatory clearance/approval."""
    pathway_name: str           # "Part D formulary" | "CPT Category I" | "site license" | etc.
    coverage_lag_months: float  # typical FDA clearance → payer coverage
    risk_level: str             # "low" | "medium" | "high" | "critical"
    description: str            # one-paragraph narrative
    risk_note: Optional[str]    # specific risk the PI must plan around

    def to_dict(self) -> dict:
        return {
            "pathway_name": self.pathway_name,
            "coverage_lag_months": self.coverage_lag_months,
            "risk_level": self.risk_level,
            "description": self.description,
            "risk_note": self.risk_note,
        }


@dataclass
class RegulatoryPathway:
    """
    Complete regulatory + reimbursement pathway for one product type.
    Wires into the orchestrator report as a first-class section.
    """
    product_family: str             # "drug" | "device" | "diagnostic" | "samd"
    pathway_name: str               # "NDA (standard)" | "510(k)" | "PMA" | "De Novo" | etc.
    pathway_subtype: Optional[str]  # more specific sub-path when inferred
    stages: List[PathwayStage]
    reimbursement: ReimbursementPath

    # Derived
    total_development_months: float         # sum of stage durations (typical)
    time_to_first_revenue_months: float     # total_development + coverage_lag
    pathway_was_inferred: bool
    inference_basis: Optional[str]          # e.g. "keyword 'implant' → PMA assumed"
    clarifying_question: Optional[str]      # ask PI when ambiguous

    def time_to_market_years(self) -> float:
        return round(self.time_to_first_revenue_months / 12.0, 1)

    def to_dict(self) -> dict:
        return {
            "product_family": self.product_family,
            "pathway_name": self.pathway_name,
            "pathway_subtype": self.pathway_subtype,
            "stages": [s.to_dict() for s in self.stages],
            "reimbursement": self.reimbursement.to_dict(),
            "total_development_months": self.total_development_months,
            "time_to_first_revenue_months": self.time_to_first_revenue_months,
            "time_to_market_years": self.time_to_market_years(),
            "pathway_was_inferred": self.pathway_was_inferred,
            "inference_basis": self.inference_basis,
            "clarifying_question": self.clarifying_question,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Pathway definitions
# ──────────────────────────────────────────────────────────────────────────────

# ── 1. Drug / Biologic / Gene therapy ─────────────────────────────────────────

_DRUG_STAGES_STANDARD = [
    PathwayStage("ind",    "IND Filing",         2,  "Preclinical package, CMC, protocol",           0.92, 500_000,    "[FDA] IND review clock 30 days; >90% cleared",                  "high"),
    PathwayStage("phase1", "Phase 1 (Safety)",   18, "Safety, PK/PD, max tolerated dose",            0.53, 20_000_000, "[BIO2020] P1→P2 transition 52.9% all indications",               "high"),
    PathwayStage("phase2", "Phase 2 (POC)",      30, "Efficacy signal, dose selection, biomarker",   0.29, 60_000_000, "[BIO2020] P2→P3 transition 28.9% all indications",               "high"),
    PathwayStage("phase3", "Phase 3 (Pivotal)",  42, "Randomised controlled trial, primary endpoint",0.58, 200_000_000,"[BIO2020] P3→NDA/BLA submission 57.8%",                          "high"),
    PathwayStage("nda",    "NDA/BLA Submission", 12, "Complete filing, advisory committee",           0.85, 5_000_000,  "[FDA CDER] Standard review 12 months; priority 6 months",        "high"),
]

_DRUG_REIMBURSEMENT = ReimbursementPath(
    pathway_name="Part D formulary (oral) / Part B ASP+6% (IV/injected)",
    coverage_lag_months=12,
    risk_level="low",
    description=(
        "Oral drugs enter Part D formulary within 6-12 months of approval via PBM contracting. "
        "Injectable/IV biologics are reimbursed under Part B at ASP+6% — Medicare coverage is "
        "automatic at approval; commercial payer formulary takes 12-18 months. "
        "Gross-to-net haircut (rebates, co-pay cards) typically 20-50% for specialty drugs."
    ),
    risk_note=(
        "Gross-to-net discounts reduce effective net price by 20-50%. "
        "Step therapy / prior-auth may delay access for 3-6 months post-formulary. "
        "IRA Medicare price negotiation (2026+) applies to drugs with ≥9 years post-NDA."
    ),
)

def _drug_pathway(subtype: str = "standard", inferred: bool = False,
                  basis: Optional[str] = None) -> RegulatoryPathway:
    stages = _DRUG_STAGES_STANDARD
    total = sum(s.typical_duration_months for s in stages)
    return RegulatoryPathway(
        product_family="drug",
        pathway_name="NDA/BLA" if subtype == "standard" else f"NDA/BLA ({subtype})",
        pathway_subtype=subtype,
        stages=stages,
        reimbursement=_DRUG_REIMBURSEMENT,
        total_development_months=total,
        time_to_first_revenue_months=total + _DRUG_REIMBURSEMENT.coverage_lag_months,
        pathway_was_inferred=inferred,
        inference_basis=basis,
        clarifying_question=None,
    )


# ── 2. Medical Device ─────────────────────────────────────────────────────────

_DEVICE_STAGES_510K = [
    PathwayStage("bench_test",    "Bench & Safety Testing",   6,
                 "ASTM/ISO biocompatibility (ISO 10993), performance bench tests",
                 0.95, 500_000,  "[FDA CDRH] typical pre-submission preparation",      "high"),
    PathwayStage("510k_submit",   "510(k) Submission",        4,
                 "Predicate device comparison, substantial equivalence argument",
                 0.84, 200_000,  "[FDA CDRH FY2023] 510(k) clearance rate 84%",        "high"),
]

_DEVICE_STAGES_PMA = [
    PathwayStage("bench_test",    "Bench & Safety Testing",   9,
                 "ASTM/ISO biocompatibility, performance standards, sterility",
                 0.95, 2_000_000, "[FDA CDRH] PMA pre-submission testing scope",       "high"),
    PathwayStage("ide",           "IDE Clinical Study",       36,
                 "FDA-approved pivotal study, primary safety + effectiveness endpoints",
                 0.65, 80_000_000, "[FDA CDRH] IDE → PMA: ~65% cumulative success",   "high"),
    PathwayStage("pma_submit",    "PMA Submission & Review",  12,
                 "180-day review; advisory panel for novel devices",
                 0.62, 3_000_000, "[FDA CDRH FY2023] PMA approval rate 62%",           "high"),
]

_DEVICE_STAGES_DE_NOVO = [
    PathwayStage("bench_test",    "Bench & Safety Testing",   6,
                 "Analytical validation, biocompatibility",
                 0.95, 500_000,  "[FDA CDRH] De Novo preparation",                     "high"),
    PathwayStage("de_novo_submit","De Novo Submission",        9,
                 "Novel device type, proposed special controls",
                 0.70, 500_000,  "[FDA CDRH] De Novo grant rate ~70%",                 "medium"),
]

_DEVICE_REIMBURSEMENT_STANDARD = ReimbursementPath(
    pathway_name="CPT Category III → Category I + CMS coverage policy",
    coverage_lag_months=80,    # 6.7 years median (JAMA 2021)
    risk_level="high",
    description=(
        "Novel devices typically receive a Category III CPT code at clearance (no defined RVU). "
        "Category I promotion requires: (a) widespread adoption data, (b) AMA CPT Editorial "
        "Panel approval, and (c) CMS rate setting. Median FDA clearance → Medicare coverage: "
        "6.7 years (Tarricone et al., JAMA 2021). This is the single largest commercial risk "
        "for novel device companies — FDA clearance does NOT equal payer payment."
    ),
    risk_note=(
        "CRITICAL: Plan for 4-7 years without Medicare reimbursement. Commercial payers "
        "often follow Medicare. Mitigation: NTAP (New Technology Add-On Payment, reduces lag "
        "to ~4 yr); Breakthrough Device Designation + TCET pathway (target <2.5 yr)."
    ),
)

_DEVICE_REIMBURSEMENT_NTAP = ReimbursementPath(
    pathway_name="CPT Category I + NTAP add-on payment",
    coverage_lag_months=48,    # 4 years with NTAP
    risk_level="medium",
    description=(
        "NTAP (New Technology Add-On Payment) provides 65% of cost as a DRG add-on for "
        "up to 3 years. Requires CMS application filed ≥3 months before October rule. "
        "Bridges the gap while Category I CPT code is established. "
        "Applies to inpatient devices with meaningful clinical improvement vs standard care."
    ),
    risk_note=(
        "NTAP approval is not guaranteed; CMS reviews ~40 applications/year, approves ~60%. "
        "After NTAP period, device must have achieved Category I CPT + Medicare coverage."
    ),
)

_DEVICE_REIMBURSEMENT_BREAKTHROUGH = ReimbursementPath(
    pathway_name="Breakthrough Device + TCET pathway (target 30-month coverage)",
    coverage_lag_months=30,
    risk_level="medium",
    description=(
        "TCET (Transitional Coverage for Emerging Technologies, CMS 2024) was designed for "
        "FDA Breakthrough Device-designated products. Target: CMS coverage within 6 months "
        "of FDA clearance. Requires concurrent FDA-CMS development track. "
        "Very few products have completed this pathway as of 2024 — treat as aspirational."
    ),
    risk_note=(
        "TCET is new (2024) and untested at scale. Breakthrough Designation must be secured "
        "early (typically before pivotal study). Even with TCET, commercial payer adoption "
        "lags Medicare by 12-24 months."
    ),
)

def _device_pathway(subtype: str = "510k", inferred: bool = False,
                    basis: Optional[str] = None,
                    reimbursement_path: str = "standard") -> RegulatoryPathway:
    if subtype == "pma":
        stages = _DEVICE_STAGES_PMA
        pname = "PMA (Premarket Approval)"
        q = None
    elif subtype == "de_novo":
        stages = _DEVICE_STAGES_DE_NOVO
        pname = "De Novo"
        q = None
    else:
        stages = _DEVICE_STAGES_510K
        pname = "510(k)"
        q = (
            "Is there a predicate device this product is substantially equivalent to? "
            "If yes → 510(k). If it uses a novel technology with no predicate → De Novo. "
            "If it is high-risk (life-sustaining, Class III) → PMA required."
        ) if inferred else None

    if reimbursement_path == "breakthrough":
        reimb = _DEVICE_REIMBURSEMENT_BREAKTHROUGH
    elif reimbursement_path == "ntap":
        reimb = _DEVICE_REIMBURSEMENT_NTAP
    else:
        reimb = _DEVICE_REIMBURSEMENT_STANDARD

    total = sum(s.typical_duration_months for s in stages)
    return RegulatoryPathway(
        product_family="device",
        pathway_name=pname,
        pathway_subtype=subtype,
        stages=stages,
        reimbursement=reimb,
        total_development_months=total,
        time_to_first_revenue_months=total + reimb.coverage_lag_months,
        pathway_was_inferred=inferred,
        inference_basis=basis,
        clarifying_question=q,
    )


# ── 3. Diagnostic / IVD ───────────────────────────────────────────────────────

_DX_STAGES_IVD = [
    PathwayStage("analytical_val", "Analytical Validation",    6,
                 "Sensitivity, specificity, precision, interfering substances (CLSI EP)",
                 0.93, 2_000_000, "[CLSI EP17-A2] standard analytical validation",           "high"),
    PathwayStage("510k_ivd",       "510(k) IVD Submission",    4,
                 "Substantial equivalence to cleared predicate assay",
                 0.87, 300_000,   "[FDA CDRH FY2023] IVD 510(k) clearance rate 87%",        "high"),
]

_DX_STAGES_CDX = [
    PathwayStage("co_dev",         "CDx Co-development with Drug", 48,
                 "Analytical validation aligned with Phase 2/3 drug trials; assay lock",
                 0.70, 15_000_000, "[FDA] CDx must be co-developed with the drug partner",   "high"),
    PathwayStage("pma_cdx",        "PMA (CDx) + Drug Co-review",   12,
                 "CDx PMA reviewed simultaneously with drug NDA/BLA",
                 0.90, 2_000_000,  "[FDA] CDx PMA approval rate ~90% when drug is approved", "high"),
]

_DX_STAGES_LDT = [
    PathwayStage("clia_val",  "CLIA/CAP Laboratory Validation",  6,
                 "Internal analytical + clinical validation; CLIA certification",
                 0.97, 500_000,   "[CMS CLIA] laboratory-developed test validation standard","high"),
    PathwayStage("ldt_launch","LDT Commercial Launch",           0,
                 "No FDA submission required under LDT exemption (as of 2024 rule)",
                 1.00, 100_000,   "[FDA LDT Final Rule 2024] phased oversight 2025-2027",   "medium"),
]

_DX_REIMBURSEMENT = ReimbursementPath(
    pathway_name="CMS CLFS gapfill or crosswalk + LCD (Local Coverage Determination)",
    coverage_lag_months=18,
    risk_level="high",
    description=(
        "A new IVD with a PLA code (Proprietary Lab Analysis) or new HCPCS code must "
        "go through CMS gapfill pricing or crosswalk to an existing code. "
        "Medicare Administrative Contractors (MACs) issue Local Coverage Determinations "
        "(LCDs) that can take 12-24 months. Payment rates are set by PAMA methodology "
        "(weighted median of private payer rates from data collection period). "
        "Until LCD is established, labs may cover the test but bill under a broader code."
    ),
    risk_note=(
        "FDA clearance ≠ CMS coverage. The LCD process is the bottleneck: each MAC "
        "issues its own LCD independently, so national coverage can take 2-3 years. "
        "Novel molecular tests (e.g. multi-gene panels) face particular scrutiny — "
        "payers may require clinical utility evidence beyond analytical performance."
    ),
)

_CDX_REIMBURSEMENT = ReimbursementPath(
    pathway_name="Drug-linked CDx reimbursement (co-coded with drug)",
    coverage_lag_months=6,
    risk_level="low",
    description=(
        "A companion diagnostic approved with its drug partner gets automatic "
        "Medicare coverage — the CDx is required by the drug label, so payers must cover "
        "it when they cover the drug. CLFS rate set via gapfill, typically within 12-18 months. "
        "Commercial payers mirror Medicare coverage in most cases."
    ),
    risk_note=(
        "Coverage is contingent on the drug staying on the market and in label. "
        "If the drug is withdrawn or label is narrowed, CDx commercial value collapses."
    ),
)

def _dx_pathway(subtype: str = "ivd", inferred: bool = False,
                basis: Optional[str] = None) -> RegulatoryPathway:
    if subtype == "cdx":
        stages = _DX_STAGES_CDX
        pname = "CDx PMA (co-approval with drug)"
        reimb = _CDX_REIMBURSEMENT
        q = None
    elif subtype == "ldt":
        stages = _DX_STAGES_LDT
        pname = "Laboratory-Developed Test (LDT, CLIA)"
        reimb = _DX_REIMBURSEMENT
        q = (
            "Will this test be offered only through your own CLIA-certified lab, "
            "or do you intend to seek FDA clearance for distribution to third-party labs? "
            "LDT = in-house only; FDA-cleared IVD = distributed product."
        ) if inferred else None
    else:
        stages = _DX_STAGES_IVD
        pname = "510(k) IVD"
        reimb = _DX_REIMBURSEMENT
        q = None

    total = sum(s.typical_duration_months for s in stages)
    return RegulatoryPathway(
        product_family="diagnostic",
        pathway_name=pname,
        pathway_subtype=subtype,
        stages=stages,
        reimbursement=reimb,
        total_development_months=total,
        time_to_first_revenue_months=total + reimb.coverage_lag_months,
        pathway_was_inferred=inferred,
        inference_basis=basis,
        clarifying_question=q,
    )


# ── 4. Software / SaMD ────────────────────────────────────────────────────────

_SAMD_STAGES_510K = [
    PathwayStage("sw_validation",  "Software Design Validation",  4,
                 "IEC 62304 software lifecycle; cybersecurity (FDA 2023 guidance)",
                 0.97, 500_000,   "[FDA] Software as Medical Device guidance 2023",           "high"),
    PathwayStage("510k_samd",      "510(k) SaMD Submission",      4,
                 "Predicate SaMD, algorithm performance, real-world data",
                 0.85, 200_000,   "[FDA CDRH FY2023] SaMD 510(k) clearance rate ~85%",       "high"),
]

_SAMD_STAGES_DE_NOVO = [
    PathwayStage("sw_validation",  "Software Design Validation",  4,
                 "IEC 62304 software lifecycle; cybersecurity",
                 0.97, 500_000,   "[FDA] Software as Medical Device guidance 2023",           "high"),
    PathwayStage("de_novo_samd",   "De Novo (Novel SaMD Function)", 9,
                 "Novel function with no predicate; proposed special controls",
                 0.70, 300_000,   "[FDA CDRH] De Novo grant rate ~70%",                      "medium"),
]

_SAMD_REIMBURSEMENT_SITE_LICENSE = ReimbursementPath(
    pathway_name="Hospital site license (enterprise contract — no CPT/CMS code)",
    coverage_lag_months=0,
    risk_level="critical",
    description=(
        "Clinical AI / hospital-deployed SaMD is typically sold via direct hospital "
        "enterprise contracts — NOT reimbursed per-patient or per-use by Medicare/Medicaid. "
        "There is NO standard CPT or HCPCS code for most clinical decision support software. "
        "Revenue depends on hospital budget approval (12-18 month sales cycle), IT integration "
        "(Epic/Cerner contracting), and demonstrating ROI to C-suite."
    ),
    risk_note=(
        "CRITICAL RISK: No third-party payer reimburses the hospital for using your software — "
        "the hospital itself is the customer. If the hospital cannot demonstrate patient-outcome "
        "ROI or cost savings, adoption stalls regardless of FDA clearance. "
        "TCET (2024) may eventually provide a Medicare pathway for qualifying SaMD, but "
        "commercial payer reimbursement for hospital AI software is not yet established."
    ),
)

_SAMD_REIMBURSEMENT_DTX = ReimbursementPath(
    pathway_name="Prescription Digital Therapeutic (PDT) — CPT 99453/99454/99457 or payer contract",
    coverage_lag_months=18,
    risk_level="high",
    description=(
        "Patient-facing digital therapeutics (DTx) have two reimbursement paths: "
        "(a) CPT codes 99453/99454/99457 for remote patient monitoring (if the DTx generates "
        "physiological data) — covered by Medicare; or "
        "(b) direct payer contracts (PMPM arrangements with health plans / self-insured employers). "
        "Pear Therapeutics (reSET, Somryst) demonstrated that FDA clearance alone is insufficient "
        "— Pear went bankrupt in 2023 without securing broad payer coverage. "
        "Medicare coverage for PDT-specific indications requires a separate NCD or LCD."
    ),
    risk_note=(
        "Payer contracts for DTx take 12-24+ months; coverage is non-standard, "
        "fragmented by plan. RPM codes (99453/99454) cover device/monitoring setup and "
        "management — may apply if the DTx generates vitals data. "
        "Generic DTx (behavioral health) rarely qualifies for RPM billing."
    ),
)

def _samd_pathway(subtype: str = "site_license", inferred: bool = False,
                  basis: Optional[str] = None) -> RegulatoryPathway:
    stages = _SAMD_STAGES_510K if subtype != "de_novo" else _SAMD_STAGES_DE_NOVO
    pname = "510(k) SaMD" if subtype != "de_novo" else "De Novo (SaMD)"

    if "dtx" in (subtype or ""):
        reimb = _SAMD_REIMBURSEMENT_DTX
    else:
        reimb = _SAMD_REIMBURSEMENT_SITE_LICENSE

    q = (
        "Is this software sold to hospitals as an enterprise license, or to patients "
        "as a subscription / prescription digital therapeutic? "
        "This determines whether there is any payer reimbursement pathway."
    ) if inferred else None

    total = sum(s.typical_duration_months for s in stages)
    return RegulatoryPathway(
        product_family="samd",
        pathway_name=pname,
        pathway_subtype=subtype,
        stages=stages,
        reimbursement=reimb,
        total_development_months=total,
        time_to_first_revenue_months=total + reimb.coverage_lag_months,
        pathway_was_inferred=inferred,
        inference_basis=basis,
        clarifying_question=q,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Router
# ──────────────────────────────────────────────────────────────────────────────

# Product type → product family mapping (never cross these)
_FAMILY_MAP: dict[str, str] = {
    # Drugs
    "drug_small_molecule": "drug", "biologic": "drug",
    "gene_cell_therapy": "drug", "gene_therapy": "drug",
    "vaccine_immunotherapy": "drug", "antibiotic": "drug",
    "drug_amr": "drug", "drug_oncology": "drug", "drug_rare_disease": "drug",
    # Devices
    "medical_device": "device", "device": "device",
    # Diagnostics
    "diagnostic": "diagnostic",
    # SaMD / software
    "digital_health": "samd", "software": "samd", "samd": "samd",
}

# Keywords that hint at device sub-pathway
_PMA_KEYWORDS = [
    "implant", "pacemaker", "defibrillator", "ventricular assist",
    "cochlear implant", "deep brain stimulation", "spinal cord stimulator",
    "heart valve", "transcatheter", "tavi", "tavr", "high-risk", "class iii",
    "novel mechanism", "no predicate", "life-sustaining", "life-supporting",
]
_DE_NOVO_KEYWORDS = [
    "de novo", "novel device type", "no predicate", "new category",
    "first of its kind", "novel algorithm", "innovative",
]
_CDX_KEYWORDS = [
    "companion diagnostic", "companion dx", "cdx", "biomarker test",
    "co-developed", "co-approval", "genomic test tied to drug",
    "patient selection biomarker", "required for drug label",
]
_LDT_KEYWORDS = [
    "laboratory developed", "ldt", "in-house test", "our lab", "clia lab",
    "not distributed", "in-lab only",
]
_DTX_KEYWORDS = [
    "digital therapeutic", "dtx", "prescription digital", "patient app",
    "behavioral", "cognitive behavioral", "remote monitoring", "rpm",
    "wearable subscription", "consumer app", "direct to patient",
]
_NTAP_KEYWORDS = [
    "meaningful clinical improvement", "ntap", "drg add-on", "inpatient device",
    "hospital-based procedure",
]
_BREAKTHROUGH_KEYWORDS = [
    "breakthrough device", "breakthrough designation", "tcet", "unmet need",
    "no alternative", "serious or life-threatening",
]
_ORPHAN_KEYWORDS = [
    "orphan", "rare disease", "ultra-rare", "< 200,000", "200000",
]
_ACCEL_KEYWORDS = [
    "accelerated approval", "surrogate endpoint", "breakthrough therapy",
    "fast track", "priority review",
]


def select_regulatory_pathway(
    product_type: str,
    idea_text: str = "",
) -> RegulatoryPathway:
    """
    Select the appropriate regulatory pathway for a product.

    Returns a fully populated RegulatoryPathway with pathway_was_inferred=True
    when the sub-path had to be guessed, and a clarifying_question for the PI.

    Guarantee: drug products NEVER receive a device pathway and vice versa.
    """
    pt = (product_type or "").strip().lower()
    idea_l = (idea_text or "").lower()

    family = _FAMILY_MAP.get(pt)
    if family is None:
        # Infer from idea text keywords
        if any(k in idea_l for k in ["drug", "molecule", "compound", "pill", "tablet",
                                      "biologic", "antibody", "therapy", "treatment"]):
            family = "drug"
        elif any(k in idea_l for k in ["device", "implant", "catheter", "stent", "hardware"]):
            family = "device"
        elif any(k in idea_l for k in ["diagnostic", "test", "assay", "biomarker", "lab"]):
            family = "diagnostic"
        elif any(k in idea_l for k in ["software", "app", "ai", "algorithm", "digital"]):
            family = "samd"
        else:
            family = "drug"  # default fallback

    if family == "drug":
        return _drug_pathway(subtype="standard", inferred=False)

    elif family == "device":
        # Infer 510k / PMA / De Novo
        if any(k in idea_l for k in _PMA_KEYWORDS):
            reimb = "breakthrough" if any(k in idea_l for k in _BREAKTHROUGH_KEYWORDS) else (
                    "ntap" if any(k in idea_l for k in _NTAP_KEYWORDS) else "standard")
            return _device_pathway(
                subtype="pma", inferred=True,
                basis=f"keyword match → PMA (high-risk/novel implant); reimbursement={reimb}",
                reimbursement_path=reimb,
            )
        elif any(k in idea_l for k in _DE_NOVO_KEYWORDS):
            return _device_pathway(
                subtype="de_novo", inferred=True,
                basis="keyword 'novel device type / no predicate' → De Novo assumed",
            )
        else:
            # Default to 510(k) for devices
            reimb = "breakthrough" if any(k in idea_l for k in _BREAKTHROUGH_KEYWORDS) else (
                    "ntap" if any(k in idea_l for k in _NTAP_KEYWORDS) else "standard")
            return _device_pathway(
                subtype="510k", inferred=(not idea_l),
                basis="default 510(k) (predicate-based); no high-risk keywords found" if idea_l else None,
                reimbursement_path=reimb,
            )

    elif family == "diagnostic":
        if any(k in idea_l for k in _CDX_KEYWORDS):
            return _dx_pathway(subtype="cdx", inferred=True,
                               basis="CDx keywords found → PMA co-approval pathway")
        elif any(k in idea_l for k in _LDT_KEYWORDS):
            return _dx_pathway(subtype="ldt", inferred=True,
                               basis="LDT keywords found → CLIA laboratory-developed test pathway")
        else:
            return _dx_pathway(
                subtype="ivd", inferred=True,
                basis="default IVD 510(k) pathway; no CDx or LDT-specific keywords",
            )

    else:  # samd
        if any(k in idea_l for k in _DTX_KEYWORDS):
            return _samd_pathway(subtype="dtx", inferred=True,
                                 basis="DTx / patient-facing app keywords → DTx reimbursement path")
        else:
            return _samd_pathway(
                subtype="site_license", inferred=True,
                basis="hospital software / AI default → site license (no CPT code)",
            )


def time_to_market_summary(pathway: RegulatoryPathway) -> str:
    """One-sentence plain-English summary of the time-to-market estimate."""
    fam = pathway.product_family
    ttm = pathway.time_to_market_years()
    lag = pathway.reimbursement.coverage_lag_months
    risk = pathway.reimbursement.risk_level

    if fam == "drug":
        return (
            f"{pathway.pathway_name}: ~{ttm} years to first commercial revenue "
            f"(development ~{pathway.total_development_months//12} yr + "
            f"formulary access ~{lag} months)."
        )
    elif fam == "device":
        return (
            f"{pathway.pathway_name}: ~{pathway.total_development_months//12} yr to FDA clearance; "
            f"then ~{lag} months to Medicare coverage [{risk.upper()} reimbursement risk]. "
            f"Total first-revenue: ~{ttm} years."
        )
    elif fam == "diagnostic":
        return (
            f"{pathway.pathway_name}: ~{pathway.total_development_months//12} yr to clearance; "
            f"~{lag} months for LCD/coverage. First revenue ~{ttm} years. "
            f"Reimbursement risk: {risk.upper()}."
        )
    else:  # samd
        if pathway.reimbursement.risk_level == "critical":
            return (
                f"{pathway.pathway_name}: ~{pathway.total_development_months//12} yr to clearance. "
                f"⚠️  CRITICAL: No standard payer reimbursement code. "
                "Revenue depends on direct hospital enterprise contracts."
            )
        return (
            f"{pathway.pathway_name}: ~{pathway.total_development_months//12} yr to clearance; "
            f"~{lag} months for payer contracting. First revenue ~{ttm} years."
        )
