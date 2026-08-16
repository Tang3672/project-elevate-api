"""
Expert Panel: three parallel Haiku sub-analyses that anchor the main Opus synthesis.

Each panel has a DIFFERENT analytical lens and sees DIFFERENT slices of the data:
  - Clinical Validity:  mechanism feasibility, scientific risks, endpoint
  - Regulatory Pathway: exact pathway, approval probability, precedent, timeline
  - Commercial Viability: pricing benchmark, payer barriers, competitive moat

This is genuinely different from the single Opus call because:
  1. Each panel is constrained to answer SPECIFIC structured questions
  2. Each produces numbers and named references (not prose)
  3. The Opus synthesis must cite or explicitly disagree with each panel finding
  4. Scientific risks ≠ regulatory risks ≠ commercial barriers — different experts surface different issues

Panels run in parallel inside the existing asyncio.gather — zero latency overhead.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional, List

import httpx

logger = logging.getLogger(__name__)


def _normalize_usd_range(s: str) -> str:
    """Normalize LLM-generated USD range strings.

    Converts sub-$1M amounts expressed as decimal millions ($0.05M) to thousands
    ($50K). This fixes the recurring fmt_usd issue where Haiku emits "$0.05M–$0.15M"
    for a $50K–$150K range.

    Examples:
        "$0.05M–$0.15M" → "$50K–$150K"
        "$0.5M–$2M"     → "$500K–$2M"   (0.5M = 500K; only sub-1 affected)
        "$5M–$30M"      → "$5M–$30M"    (unchanged)
        "$50K–$150K"    → "$50K–$150K"  (unchanged)
    """
    if not s:
        return s

    def _replace(m: re.Match) -> str:
        val = float(m.group(1))
        if val < 1.0:
            k = int(round(val * 1000))
            return f"${k}K"
        return m.group(0)

    return re.sub(r"\$(\d+(?:\.\d+)?)M", _replace, s)

HAIKU_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

# ── Domain-specific regulatory hints injected per sub_expert_id ───────────────
# These give the regulatory panel expert-level context it wouldn't have otherwise
_REGULATORY_DOMAIN_HINTS: dict[str, str] = {
    "drug_amr":               "Key designations: QIDP (+5yr exclusivity), LPAD (limited population), FastTrack. NTAP: 65-75% cost add-on. CARB-X funds only through Phase 2.",
    "drug_amr_antibiotics":   "Key designations: QIDP (+5yr exclusivity), LPAD (limited population), FastTrack. NTAP: 65-75% cost add-on. CARB-X funds only through Phase 2.",
    "biologic_oncology":      "Key designations: BTD (Breakthrough), Accelerated Approval (surrogate endpoint), Priority Review. BLA pathway. CAR-T: RMAT designation.",
    "drug_oncology":          "Key designations: BTD, Accelerated Approval, Orphan (if <200k pts). NDA pathway. Tumor-agnostic approval possible with biomarker.",
    "gene_therapy_rare":      "RMAT designation for regenerative medicine. BLA pathway. FDA has specific GT guidance (2020). Manufacturing CMC is the #1 regulatory risk.",
    "gene_therapy_oncology":  "RMAT designation. BLA pathway. Accelerated Approval likely if durable response rate >30%. Manufacturing CMC is the #1 regulatory risk.",
    "biologic_rare_disease":  "Orphan Drug Act: 7yr exclusivity + tax credits. BLA pathway. Accelerated Approval with biomarker surrogate. PRV voucher worth ~$100M.",
    "drug_rare_disease":      "Orphan Drug Act: 7yr exclusivity + tax credits. NDA pathway. Accelerated Approval with biomarker surrogate. PRV voucher worth ~$100M.",
    "device_cardiovascular":  "PMA for Class III (high-risk). De Novo for novel moderate-risk. IDE required for trials. Breakthrough Device designation for unmet need.",
    "device_metabolic":       "De Novo or 510(k) depending on predicate. IDE if trials needed. Breakthrough Device if for serious condition with no adequate alternative.",
    "diagnostic_molecular":   "FDA: IVD pathway under 21 CFR Part 820. PMA for high-risk (Class III). 510(k) with predicate for Class II. LDT policy currently in flux.",
    "digital_therapeutic":    "FDA: SaMD (Software as Medical Device). DTx Pre-Cert pilot. De Novo likely for novel DTx. CE Mark in parallel for EU. No J-code yet for most DTx.",
    "vaccine_prophylactic":   "BLA pathway. Phase 3 efficacy trial required (typically 30k+ participants). ACIP recommendation required for commercial uptake. EUA possible.",
    "biologic_immunology":    "BLA pathway. Often Orphan + BTD for autoimmune. Biosimilar risk: reference product exclusivity 12 years (Biologics Price Competition Act).",
    "biologic_hematology":    "BLA pathway. Often Orphan. BTD for severe unmet need. Accelerated Approval with surrogate (e.g., overall response rate). PRV for rare pediatric.",
    "drug_cns":               "NDA 505(b)(1) or 505(b)(2). Breakthrough Therapy for serious condition. CNS trials: endpoint validation is key regulatory risk (FDA PDDS guidance).",
    "drug_mental_health":     "NDA pathway. BTD rarely granted for psychiatry. REMS required for high-risk medications. SSRI/SNRI precedents inform approval probability.",
    "drug_cardiology":        "NDA or BLA. Hard endpoints (MACE, HF hospitalization) typically required. Cardiovascular Safety Trial (CVOT) may be required post-approval.",
    "digital_cds":            "FDA Software as a Medical Device (SaMD). De Novo for a novel AI/ML algorithm with no predicate; 510(k) if a cleared predicate exists; Predetermined Change Control Plan (PCCP) for adaptive models; 21st Century Cures CDS exemption if the clinician independently reviews the basis. The ONLY expedited programs for a device/SaMD are Breakthrough Device Designation (BDD) and TAP (Total Product Lifecycle Advisory Program). Do NOT use Fast Track, Priority Review, Accelerated Approval, QIDP, LPAD, or NDA — those are drug/biologic (CDER/CBER) programs that do NOT exist for devices.",
    "digital_samd_radiology": "FDA SaMD. De Novo for novel AI imaging with no predicate; 510(k) with predicate; PCCP for adaptive models; Breakthrough Device Designation. Do NOT use QIDP/LPAD/NDA.",
    "digital_rpm":            "FDA SaMD/device. 510(k) typical for connected monitors; CMS RPM CPT codes (99453-99458). Breakthrough Device for serious conditions. Do NOT use QIDP/LPAD/NDA.",
    "diagnostic_companion":   "FDA companion diagnostic (CDx), typically PMA co-approved with a therapy. Breakthrough Device possible. Do NOT use QIDP/LPAD/NDA.",
    "diagnostic_poc":         "FDA IVD; 510(k) or CLIA-waiver for point-of-care; De Novo if novel. Do NOT use QIDP/LPAD/NDA.",
    "device_neurology":       "PMA for Class III (implantable neurostimulation); De Novo for novel moderate-risk; 510(k) with predicate; IDE for trials; Breakthrough Device Designation. Do NOT use QIDP/LPAD/NDA.",
    "device_surgical_general":"PMA for Class III; De Novo for novel moderate-risk; 510(k) with predicate; IDE for trials; Breakthrough Device Designation. Do NOT use QIDP/LPAD/NDA.",
    "device_ophthalmology":   "PMA for Class III implants; De Novo/510(k) otherwise; IDE for trials; Breakthrough Device Designation. Do NOT use QIDP/LPAD/NDA.",
}


# Designations that exist ONLY for drugs/biologics (CDER/CBER) and must never appear on
# a device/SaMD report. Stripped deterministically regardless of the LLM's output.
_DRUG_ONLY_DESIGNATIONS = [
    "fast track", "priority review", "accelerated approval", "breakthrough therapy",
    "qidp", "lpad", "gain act", "rmat", "orphan drug", "nda", "bla", "505(b)",
]


def _sanitize_designations(desigs: list, sub_expert_id: str) -> list:
    """For device/diagnostic/SaMD, remove drug/biologic-only designations (Fast Track,
    Priority Review, QIDP, …). Ensures Breakthrough DEVICE Designation is offered instead."""
    sid = (sub_expert_id or "").lower()
    if not sid.startswith(("device_", "diagnostic_", "digital_")):
        return desigs
    cleaned = [d for d in (desigs or [])
               if d and not any(bad in d.lower() for bad in _DRUG_ONLY_DESIGNATIONS)]
    if not any("breakthrough device" in (d or "").lower() for d in cleaned):
        cleaned.insert(0, "Breakthrough Device Designation (BDD)")
    return cleaned


def _regulatory_hint(sub_expert_id: str) -> str:
    """Modality-appropriate regulatory hint for the panel. Falls back on the sub-expert
    id PREFIX so a non-drug modality never defaults to inventing antibiotic designations
    (QIDP/LPAD) just because it lacks an explicit dict entry."""
    sid = (sub_expert_id or "").lower()
    if sid in _REGULATORY_DOMAIN_HINTS:
        return _REGULATORY_DOMAIN_HINTS[sid]
    if sid.startswith("digital_"):
        return _REGULATORY_DOMAIN_HINTS["digital_cds"]
    if sid.startswith("diagnostic_"):
        return "FDA in-vitro/imaging diagnostic. 510(k) with predicate (Class II); De Novo for novel; PMA for high-risk; CLIA/LDT for lab-developed tests. Only device expedited programs: Breakthrough Device Designation (BDD) and TAP. Do NOT use Fast Track, Priority Review, QIDP, LPAD, or NDA (drug-only)."
    if sid.startswith("device_"):
        return "PMA for Class III (high-risk); De Novo for novel moderate-risk; 510(k) with predicate; IDE for trials. Only device expedited programs: Breakthrough Device Designation (BDD) and TAP (Total Product Lifecycle Advisory Program). Do NOT use Fast Track, Priority Review, Accelerated Approval, QIDP, LPAD, or NDA — those are drug/biologic programs that do NOT exist for devices."
    if sid.startswith("vaccine_"):
        return "BLA pathway (FDA CBER). ACIP recommendation drives uptake; Phase 3 efficacy trial required. Do NOT use antibiotic QIDP/LPAD."
    if sid.startswith("gene_therapy_"):
        return "BLA via FDA CBER (OTAT). RMAT designation; 15-yr long-term follow-up; CMC is the #1 regulatory risk. Do NOT use antibiotic QIDP/LPAD."
    if sid.startswith("biologic_"):
        return "BLA pathway. BTD/Orphan as relevant; reference-product exclusivity 12 yrs. Do NOT use antibiotic QIDP/LPAD."
    if sid.startswith("other_"):
        return "Use the FDA pathway appropriate to the specific platform. Do NOT assume an antibiotic NDA/QIDP."
    return ""   # drug/unknown — no injected hint (drug path unchanged)

# ── Non-clinical research tool archetype identifiers ─────────────────────────
# Panels whose rubrics require a clinical indication or FDA pathway are not
# scored for these archetypes — they render as N/A (H-09).
_RESEARCH_TOOL_ARCHETYPES = frozenset({
    "research_tool_non_clinical",
    "research_infrastructure_saas",
    "research_tool_agronomy",
})

# ── Per-domain commercial hints for the commercial panel ─────────────────────
_COMMERCIAL_DOMAIN_HINTS: dict[str, str] = {
    "research_tool_non_clinical": (
        "Buyer is an academic PI funded by NIH/NSF grants. "
        "Purchase cadence: every 2-5 years (grant cycle). "
        "Observed spend band: $20k-$30k per cycle = ~$6k-$10k/yr annualised. "
        "Budget line: grant direct costs, equipment line. "
        "Revenue model: per-lab subscription or one-time site license — NOT WAC pricing, NOT CPT, NOT J-code. "
        "Primary competitor: status quo (manual SD cards, lab-built scripts). "
        "Pricing comparable: commercial research instrumentation relevant to the domain (e.g., Movisens/Empatica for physiology; METER Group/Onset for environmental; Noldus for behavioral). "
        "Do NOT reference hospital systems, DRG, NTAP, or drug pricing as comparables."
    ),
    "research_tool_agronomy": (
        "Buyer is an academic agronomist, crop scientist, or environmental researcher funded by USDA-NIFA or NSF. "
        "Purchase cadence: every 3-5 years (grant cycle). "
        "Observed spend band: $5k-$20k per deployment; annualised ≈ $2k-$6k/yr. "
        "Budget line: USDA-NIFA SBIR/STTR or NSF grant direct costs, equipment line. "
        "Revenue model: per-site license or hardware + subscription — NOT WAC, NOT CPT, NOT J-code. "
        "Primary SBIR funder: USDA-NIFA (nifa.usda.gov/grants) — NOT NIH. NSF is secondary. "
        "Pricing comparable: environmental/soil sensing hardware (METER Group, Onset HOBO, Decagon, Sentek). "
        "Do NOT reference ActiGraph, Empatica, hospital systems, DRG, NTAP, or drug pricing as comparables. "
        "Do NOT cite NIH RePORTER as the buyer population source; use USDA CRIS or NSF Award Search instead."
    ),
    "research_infrastructure_saas": (
        "Buyer is an academic PI or core facility director funded by institutional or federal grants. "
        "Purchase cadence: annual SaaS or multi-year site license. "
        "Budget line: indirect or direct costs, IT budget. "
        "Revenue model: per-institution or per-lab SaaS license — NOT drug WAC or CPT codes. "
        "Do NOT reference hospital payers, DRG, NTAP, or drug pricing."
    ),
    "drug_amr":               "Hospital formulary acquisition. GPO contracts critical. NTAP coverage adds 65-75% above DRG. Pull incentives (PASTEUR Act, BARDA) are key commercial levers.",
    "biologic_oncology":      "J-code reimbursement or buy-and-bill. Payer prior auth based on biomarker. Specialty pharmacy channel. ASP+6% in oncology office. CAR-T: ~$400k-$500k launch price precedent.",
    "drug_oncology":          "Specialty pharmacy. Payer prior auth based on biomarker. ASP+6% for IV. Oral oncology: specialty pharmacy, copay assistance programs critical.",
    "gene_therapy_rare":      "One-time high-cost treatment ($1M-$3.5M). Payer outcomes-based contracts common. Installment payment models (e.g., bluebird bio model). ICER review likely.",
    "biologic_rare_disease":  "Specialty pharmacy. Orphan pricing ($100k-$700k/yr). Patient advocacy groups key. ICER review common. Payer prior auth strict. PRV creates $100M+ windfall.",
    "drug_rare_disease":      "Specialty pharmacy. Orphan pricing ($80k-$400k/yr). Patient advocacy critical. ICER review common. Payer prior auth strict. PRV creates $100M+ windfall.",
    "device_cardiovascular":  "Hospital capital budget. GPO/IDN contracts. DRG reimbursement + NTAP for novel devices. Physician champions key. Clinical evidence for payer coverage.",
    "diagnostic_molecular":   "CPT code reimbursement (varies $250-$5k). CMS LCD/NCD policy critical. MAAA code for multi-analyte. Companion diagnostic: tied to drug approval.",
    "digital_therapeutic":    "Self-pay or employer benefit. Rx DTx: limited payer coverage today. B2B employer channel growing. Revenue < $500/user/yr typical for behavioral DTx.",
    "vaccine_prophylactic":   "ACIP recommendation = commercial success. VFC program for pediatric. GPO for adult vaccines. CMS NCD for Medicare coverage of ACIP-recommended vaccines.",
    "biologic_immunology":    "Specialty pharmacy. Payer biosimilar step therapy risk. Reference product loses exclusivity in 12 years. Copay assistance programs critical for adherence.",
}


# ─────────────────────────────────────────────────────────────────────────────
# Panel result dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ClinicalPanelResult:
    mechanism_score: float          # 0-10
    key_scientific_risks: List[str]
    recommended_endpoint: str
    differentiation_vs_soc: str
    confidence: float               # 0-1


@dataclass
class RegulatoryPanelResult:
    recommended_pathway: str
    approval_probability_pct: int   # 0-100
    precedent_product: str
    expected_timeline_yrs: float
    available_designations: List[str]
    top_regulatory_risk: str


@dataclass
class CommercialPanelResult:
    annual_price_benchmark_usd: int
    pricing_comparable: str
    key_payer_barrier: str
    competitive_moat_score: float   # 0-10
    moat_basis: str
    yrs_to_peak_revenue: int
    reimbursement_mechanism: str
    licensing_upfront_range: str = ""   # e.g. "$5M-$30M"
    licensing_royalty_range: str = ""   # e.g. "2%-6% (academic)"


@dataclass
class ExpertPanelResult:
    clinical:    Optional[ClinicalPanelResult]    = None
    regulatory:  Optional[RegulatoryPanelResult]  = None
    commercial:  Optional[CommercialPanelResult]  = None
    error_count: int                               = 0


# ─────────────────────────────────────────────────────────────────────────────
# Serialization for UI visibility (Sprint 2)
# ─────────────────────────────────────────────────────────────────────────────

def panel_to_dict(panel: "ExpertPanelResult") -> dict:
    """Flatten an ExpertPanelResult into a UI-friendly dict. Each sub-panel is a
    separate Haiku call with its own grounding, so exposing them makes the
    mixture-of-experts work visible rather than hidden."""
    out: dict = {"error_count": getattr(panel, "error_count", 0), "panels": []}
    c = getattr(panel, "clinical", None)
    if c is not None:
        out["panels"].append({
            "name": "Clinical Validity", "icon": "🧪",
            "headline_metric": "Mechanism score", "headline_value": f"{c.mechanism_score:.1f}/10",
            "confidence": getattr(c, "confidence", None),
            "fields": {
                "Recommended endpoint": c.recommended_endpoint,
                "Differentiation vs. standard of care": c.differentiation_vs_soc,
            },
            "risks": list(c.key_scientific_risks or []),
        })
    r = getattr(panel, "regulatory", None)
    if r is not None:
        out["panels"].append({
            "name": "Regulatory Pathway", "icon": "🏛",
            "headline_metric": "Approval probability", "headline_value": f"{r.approval_probability_pct}%",
            "fields": {
                "Recommended pathway": r.recommended_pathway,
                "Precedent product": r.precedent_product,
                "Expected timeline": f"{r.expected_timeline_yrs} yrs",
                "Available designations": ", ".join(r.available_designations or []) or "—",
            },
            "risks": [r.top_regulatory_risk] if getattr(r, "top_regulatory_risk", "") else [],
        })
    com = getattr(panel, "commercial", None)
    if com is not None:
        out["panels"].append({
            "name": "Commercial Viability", "icon": "💰",
            "headline_metric": "Competitive moat", "headline_value": f"{com.competitive_moat_score:.1f}/10",
            "fields": {
                "Annual price benchmark": f"${com.annual_price_benchmark_usd:,}" if com.annual_price_benchmark_usd else "—",
                "Pricing comparable": com.pricing_comparable,
                "Moat basis": com.moat_basis,
                "Years to peak revenue": str(com.yrs_to_peak_revenue),
                "Reimbursement mechanism": getattr(com, "reimbursement_mechanism", ""),
                "Licensing upfront range": getattr(com, "licensing_upfront_range", "") or "—",
                "Licensing royalty range": getattr(com, "licensing_royalty_range", "") or "—",
            },
            "risks": [com.key_payer_barrier] if getattr(com, "key_payer_barrier", "") else [],
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _haiku_call(system: str, user: str) -> dict:
    """Single Haiku call returning parsed JSON dict."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    async with httpx.AsyncClient(timeout=12.0) as client:
        r = await client.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": HAIKU_MODEL,
                "max_tokens": 512,
                "temperature": 0,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        r.raise_for_status()
        text = r.json()["content"][0]["text"].strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)


async def _run_clinical_panel(disease_name: str, idea: str) -> Optional[ClinicalPanelResult]:
    system = (
        "You are a clinical scientist evaluating a biomedical innovation for scientific feasibility.\n"
        "Analyze ONLY the disease mechanism and scientific validity of the proposed approach.\n"
        "Return ONLY valid JSON — no prose, no markdown:\n"
        "{\n"
        '  "mechanism_score": <float 0-10, where 10=highly validated target with strong preclinical evidence>,\n'
        '  "key_scientific_risks": [<exactly 3 specific scientific risk strings>],\n'
        '  "recommended_endpoint": "<specific, named FDA-acceptable primary endpoint for this indication>",\n'
        '  "differentiation_vs_soc": "<one sentence: how this mechanistically differs from current standard of care>",\n'
        '  "confidence": <float 0-1, your confidence in this assessment given information available>\n'
        "}"
    )
    user = f"Disease: {disease_name}\n\nProposed innovation:\n{idea[:800]}"
    try:
        data = await _haiku_call(system, user)
        return ClinicalPanelResult(
            mechanism_score         = float(data.get("mechanism_score", 5.0)),
            key_scientific_risks    = list(data.get("key_scientific_risks", []))[:3],
            recommended_endpoint    = str(data.get("recommended_endpoint", "")),
            differentiation_vs_soc  = str(data.get("differentiation_vs_soc", "")),
            confidence              = float(data.get("confidence", 0.5)),
        )
    except Exception as e:
        logger.warning("Clinical panel failed: %s", e)
        return None


async def _run_regulatory_panel(
    disease_name: str,
    idea: str,
    sub_expert_id: str,
    product_type: str = "drug",
    development_phase: str = "preclinical",
) -> Optional[RegulatoryPanelResult]:
    # Anchor approval probability on calibrated historical FDA data from ptrs_tables.
    # Haiku's job is qualitative analysis (pathway, precedent, risk) — not guessing rates.
    calibrated_loa_pct: Optional[float] = None
    calibrated_citation: str = ""
    try:
        from app.services.ptrs_tables import get_ptrs
        loa_frac, loa_pct, citation = get_ptrs(sub_expert_id, development_phase)
        calibrated_loa_pct  = loa_pct
        calibrated_citation = citation
    except Exception:
        pass  # Fall back to Haiku estimate if ptrs_tables unavailable

    domain_hint = _regulatory_hint(sub_expert_id)
    _sid = (sub_expert_id or "").lower()
    _is_device = _sid.startswith(("device_", "diagnostic_", "digital_"))
    if calibrated_loa_pct is None:
        ptrs_anchor = ""
    elif _is_device:
        # Devices/SaMD: this is an FDA CDRH CLEARANCE likelihood, not a drug LoA. Do NOT
        # frame it as Phase 1/2/3 approval probability.
        ptrs_anchor = (
            f"FDA CDRH CLEARANCE LIKELIHOOD (device/SaMD — NOT a drug Phase 1/2/3 rate): "
            f"~{calibrated_loa_pct:.0f}% based on De Novo grant / 510(k) clearance rates. "
            f"Source: {calibrated_citation}. Frame the roadmap as bench + validation studies "
            f"(retrospective then prospective), NOT drug Phase 1/2/3 human safety trials.\n"
        )
    else:
        ptrs_anchor = (
            f"HISTORICAL FDA APPROVAL RATE (from published BIO/WONG data): "
            f"{calibrated_loa_pct:.1f}% probability of approval from {development_phase} stage. "
            f"Source: {calibrated_citation}. "
            f"Use this as your baseline — you may adjust ±5% only with specific cited reasoning.\n"
        )
    system = (
        "You are an FDA regulatory strategist specializing in biomedical product development.\n"
        + (f"Domain context: {domain_hint}\n" if domain_hint else "")
        + ptrs_anchor
        + "Given the disease and proposed approach, determine the regulatory pathway. "
        "Your approval_probability_pct MUST be within ±5% of the historical baseline unless you cite a specific reason.\n"
        "Return ONLY valid JSON — no prose, no markdown:\n"
        "{\n"
        '  "recommended_pathway": "<exact pathway: NDA 505(b)(1), NDA 505(b)(2), BLA, PMA, De Novo, 510(k), etc.>",\n'
        '  "approval_probability_pct": <integer 0-100, anchored to historical baseline>,\n'
        '  "probability_adjustment_reason": "<why you adjusted from baseline, or \'baseline\' if unchanged>",\n'
        '  "precedent_product": "<name and approval year of most comparable FDA-approved product>",\n'
        '  "expected_timeline_yrs": <float, total years from current early stage to FDA approval>,\n'
        '  "available_designations": [<applicable: "BTD", "FastTrack", "QIDP", "Orphan", "RMAT", "PRV", "LPAD", "AccelApproval">],\n'
        '  "top_regulatory_risk": "<single most critical regulatory challenge in one specific sentence>"\n'
        "}"
    )
    user = (
        f"Disease: {disease_name}\n"
        f"Product type: {product_type}\n"
        f"Development stage: {development_phase}\n"
        f"Domain: {sub_expert_id}\n\n"
        f"Proposed innovation:\n{idea[:600]}"
    )
    try:
        data = await _haiku_call(system, user)
        raw_prob = int(data.get("approval_probability_pct", calibrated_loa_pct or 30))
        # If we have a calibrated baseline, cap the drift at ±10 percentage points
        if calibrated_loa_pct is not None:
            clamped = max(round(calibrated_loa_pct) - 10, min(round(calibrated_loa_pct) + 10, raw_prob))
        else:
            clamped = raw_prob
        return RegulatoryPanelResult(
            recommended_pathway     = str(data.get("recommended_pathway", "")),
            approval_probability_pct= clamped,
            precedent_product       = str(data.get("precedent_product", "")),
            expected_timeline_yrs   = float(data.get("expected_timeline_yrs", 8.0)),
            available_designations  = _sanitize_designations(list(data.get("available_designations", [])), _sid),
            top_regulatory_risk     = str(data.get("top_regulatory_risk", "")),
        )
    except Exception as e:
        logger.warning("Regulatory panel failed: %s", e)
        # Return calibrated baseline even if Haiku call fails
        if calibrated_loa_pct is not None:
            return RegulatoryPanelResult(
                recommended_pathway     = "See expert system prompt for pathway",
                approval_probability_pct= round(calibrated_loa_pct),
                precedent_product       = "",
                expected_timeline_yrs   = 8.0,
                available_designations  = [],
                top_regulatory_risk     = "Regulatory panel unavailable — see expert analysis",
            )
        return None


async def _run_commercial_panel(
    disease_name: str,
    idea: str,
    sub_expert_id: str,
    market_context: str = "",
    development_phase: str = "preclinical",
) -> Optional[CommercialPanelResult]:
    domain_hint = _COMMERCIAL_DOMAIN_HINTS.get(sub_expert_id, "")
    # Inject calibrated deal comparables — TTOs negotiate against these numbers
    deal_comp_block = ""
    try:
        from app.services.deal_comps import format_deal_comps_for_prompt
        deal_comp_block = format_deal_comps_for_prompt(sub_expert_id, development_phase)
    except Exception:
        pass
    system = (
        "You are a biotech market access and commercialization analyst.\n"
        + (f"Domain context: {domain_hint}\n" if domain_hint else "")
        + (f"\n{deal_comp_block}\n" if deal_comp_block else "")
        + "Assess the commercial viability of this biomedical innovation. "
        "Your pricing and deal structure estimates MUST reference the deal comparables above.\n"
        "Return ONLY valid JSON — no prose, no markdown:\n"
        "{\n"
        '  "annual_price_benchmark_usd": <integer, estimated annual WAC price in USD>,\n'
        '  "pricing_comparable": "<name of comparable product used as pricing anchor>",\n'
        '  "key_payer_barrier": "<single most important commercial barrier in one specific sentence>",\n'
        '  "competitive_moat_score": <float 0-10, where 10=highly defensible competitive position>,\n'
        '  "moat_basis": "<what specifically creates or undermines the moat in one sentence>",\n'
        '  "yrs_to_peak_revenue": <integer, years post-launch to peak annual revenue>,\n'
        '  "reimbursement_mechanism": "<primary code/pathway, e.g., J-code, DRG+NTAP, CPT, self-pay>",\n'
        '  "licensing_upfront_range": "<use K for amounts under $1M, e.g. $50K-$150K not $0.05M-$0.15M; for larger deals use $XM-$YM>",\n'
        '  "licensing_royalty_range": "<X%-Y% royalty on net sales (academic) or X%-Y% (corporate)>"\n'
        "}"
    )
    user = (
        f"Disease: {disease_name}\n"
        f"Domain: {sub_expert_id}\n"
        f"Development stage: {development_phase}\n"
        + (f"Market context:\n{market_context[:400]}\n" if market_context else "")
        + f"\nProposed innovation:\n{idea[:600]}"
    )
    try:
        data = await _haiku_call(system, user)
        return CommercialPanelResult(
            annual_price_benchmark_usd = int(data.get("annual_price_benchmark_usd", 0)),
            pricing_comparable         = str(data.get("pricing_comparable", "")),
            key_payer_barrier          = str(data.get("key_payer_barrier", "")),
            competitive_moat_score     = float(data.get("competitive_moat_score", 5.0)),
            moat_basis                 = str(data.get("moat_basis", "")),
            yrs_to_peak_revenue        = int(data.get("yrs_to_peak_revenue", 5)),
            reimbursement_mechanism    = str(data.get("reimbursement_mechanism", "")),
            licensing_upfront_range    = _normalize_usd_range(str(data.get("licensing_upfront_range", ""))),
            licensing_royalty_range    = str(data.get("licensing_royalty_range", "")),
        )
    except Exception as e:
        logger.warning("Commercial panel failed: %s", e)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

async def run_expert_panel(
    disease_name: str,
    idea: str,
    sub_expert_id: str,
    product_type: str = "drug",
    market_context: str = "",
    development_phase: str = "preclinical",
    archetype: str = "",
) -> ExpertPanelResult:
    """
    Run sub-expert panels in parallel. Each panel has a different analytical lens.

    H-09 gate: clinical and regulatory panels require a clinical indication and an
    FDA pathway. For non-clinical research tools these rubrics do not apply —
    running them produces meaningless scores (0.0/10 mechanism feasibility,
    "not regulated" pathway) that pollute the executive summary. They are skipped
    and left as None, which renders as N/A in panel_to_dict and is excluded from
    all composites.

    Key improvements over pure LLM:
    - Regulatory panel anchors on ptrs_tables.py calibrated historical FDA approval data
    - Commercial panel anchors on deal_comps.py sourced from AUTM/BIO transaction databases
    """
    import asyncio

    _arch = (archetype or sub_expert_id or "").lower()
    _is_research_tool = any(_arch == rt or _arch.startswith(rt) for rt in _RESEARCH_TOOL_ARCHETYPES)

    if _is_research_tool:
        # Clinical validity and regulatory pathway panels are structurally inapplicable
        # for non-clinical research tools. Only the commercial panel runs, with a
        # research-tool-appropriate prompt via _COMMERCIAL_DOMAIN_HINTS.
        logger.info(
            "Panel gate [H-09]: skipping clinical and regulatory panels for archetype '%s' "
            "(not applicable — no clinical indication, no FDA pathway)", _arch,
        )
        commercial = await _run_commercial_panel(
            disease_name, idea, sub_expert_id, market_context, development_phase,
        )
        result = ExpertPanelResult(clinical=None, regulatory=None, commercial=commercial,
                                   error_count=(1 if commercial is None else 0))
        logger.info(
            "Expert panel complete [research tool]: clinical=N/A regulatory=N/A commercial=%s",
            "✓" if commercial else "✗",
        )
        return result

    clinical, regulatory, commercial = await asyncio.gather(
        _run_clinical_panel(disease_name, idea),
        _run_regulatory_panel(disease_name, idea, sub_expert_id, product_type, development_phase),
        _run_commercial_panel(disease_name, idea, sub_expert_id, market_context, development_phase),
        return_exceptions=False,
    )
    errors = sum(1 for x in (clinical, regulatory, commercial) if x is None)
    result = ExpertPanelResult(
        clinical=clinical,
        regulatory=regulatory,
        commercial=commercial,
        error_count=errors,
    )
    logger.info(
        "Expert panel complete: clinical=%s regulatory=%s commercial=%s errors=%d",
        "✓" if clinical else "✗",
        "✓" if regulatory else "✗",
        "✓" if commercial else "✗",
        errors,
    )
    return result


def format_panel_for_prompt(panel: ExpertPanelResult) -> str:
    """
    Format panel results as a high-priority context block for injection into the Opus call.
    The synthesis instruction forces Opus to explicitly cite or disagree with each finding.
    """
    if not panel or (not panel.clinical and not panel.regulatory and not panel.commercial):
        return ""

    lines = [
        "=== EXPERT PANEL PRE-ANALYSIS ===",
        "Three independent sub-expert analyses conducted in parallel before this synthesis.",
        "MANDATORY: Your report MUST reference these panel findings by name in the relevant chapters.",
        "If you disagree with any finding, write: 'The panel assessed [X]; however, [your reasoning with cited evidence].'",
        "",
    ]

    if panel.clinical:
        c = panel.clinical
        risks_fmt = "\n".join(f"    {i+1}. {r}" for i, r in enumerate(c.key_scientific_risks))
        lines += [
            "── CLINICAL VALIDITY EXPERT ──",
            f"  Mechanism Feasibility Score: {c.mechanism_score:.1f}/10  (confidence: {c.confidence:.0%})",
            f"  Key Scientific Risks:",
            risks_fmt,
            f"  Recommended Primary Endpoint: {c.recommended_endpoint}",
            f"  vs. Standard of Care: {c.differentiation_vs_soc}",
            "",
        ]

    if panel.regulatory:
        r = panel.regulatory
        desig_fmt = ", ".join(r.available_designations) if r.available_designations else "None identified"
        lines += [
            "── REGULATORY PATHWAY EXPERT (calibrated on historical FDA data) ──",
            f"  Recommended Pathway: {r.recommended_pathway}",
            f"  Approval Probability: {r.approval_probability_pct}% (source: BIO/WONG historical FDA approval rates)",
            f"  Closest Precedent: {r.precedent_product}",
            f"  Expected Timeline: {r.expected_timeline_yrs:.1f} years to approval",
            f"  Available Designations: {desig_fmt}",
            f"  Top Regulatory Risk: {r.top_regulatory_risk}",
            "",
        ]

    if panel.commercial:
        com = panel.commercial
        price_fmt = (
            f"${com.annual_price_benchmark_usd:,.0f}/yr"
            if com.annual_price_benchmark_usd >= 10_000
            else f"${com.annual_price_benchmark_usd:,}/course"
        )
        lines += [
            "── COMMERCIAL VIABILITY EXPERT (anchored on AUTM/BIO deal transaction data) ──",
            f"  Pricing Benchmark: {price_fmt} (based on {com.pricing_comparable})",
            f"  Key Payer Barrier: {com.key_payer_barrier}",
            f"  Competitive Moat: {com.competitive_moat_score:.1f}/10 — {com.moat_basis}",
            f"  Time to Peak Revenue: {com.yrs_to_peak_revenue} years post-launch",
            f"  Reimbursement Mechanism: {com.reimbursement_mechanism}",
        ]
        if com.licensing_upfront_range:
            lines.append(f"  License Deal Benchmark — Upfront: {com.licensing_upfront_range}")
        if com.licensing_royalty_range:
            lines.append(f"  License Deal Benchmark — Royalty: {com.licensing_royalty_range}")
        lines.append("")

    lines.append("=== END EXPERT PANEL ===")
    return "\n".join(lines)
