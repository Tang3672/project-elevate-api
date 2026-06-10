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
from dataclasses import dataclass, field
from typing import Optional, List

import httpx

logger = logging.getLogger(__name__)

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
}

# ── Per-domain commercial hints for the commercial panel ─────────────────────
_COMMERCIAL_DOMAIN_HINTS: dict[str, str] = {
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


@dataclass
class ExpertPanelResult:
    clinical:    Optional[ClinicalPanelResult]    = None
    regulatory:  Optional[RegulatoryPanelResult]  = None
    commercial:  Optional[CommercialPanelResult]  = None
    error_count: int                               = 0


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _haiku_call(system: str, user: str) -> dict:
    """Single Haiku call returning parsed JSON dict."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    async with httpx.AsyncClient(timeout=30.0) as client:
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
) -> Optional[RegulatoryPanelResult]:
    domain_hint = _REGULATORY_DOMAIN_HINTS.get(sub_expert_id, "")
    system = (
        "You are an FDA regulatory strategist specializing in biomedical product development.\n"
        + (f"Domain context: {domain_hint}\n" if domain_hint else "")
        + "Given the disease and proposed approach, determine the regulatory pathway.\n"
        "Return ONLY valid JSON — no prose, no markdown:\n"
        "{\n"
        '  "recommended_pathway": "<exact pathway: NDA 505(b)(1), NDA 505(b)(2), BLA, PMA, De Novo, 510(k), etc.>",\n'
        '  "approval_probability_pct": <integer 0-100, based on disease + mechanism + precedent>,\n'
        '  "precedent_product": "<name and approval year of most comparable FDA-approved product>",\n'
        '  "expected_timeline_yrs": <float, total years from current early stage to FDA approval>,\n'
        '  "available_designations": [<applicable: "BTD", "FastTrack", "QIDP", "Orphan", "RMAT", "PRV", "LPAD", "AccelApproval">],\n'
        '  "top_regulatory_risk": "<single most critical regulatory challenge in one specific sentence>"\n'
        "}"
    )
    user = (
        f"Disease: {disease_name}\n"
        f"Product type: {product_type}\n"
        f"Domain: {sub_expert_id}\n\n"
        f"Proposed innovation:\n{idea[:600]}"
    )
    try:
        data = await _haiku_call(system, user)
        return RegulatoryPanelResult(
            recommended_pathway     = str(data.get("recommended_pathway", "")),
            approval_probability_pct= int(data.get("approval_probability_pct", 30)),
            precedent_product       = str(data.get("precedent_product", "")),
            expected_timeline_yrs   = float(data.get("expected_timeline_yrs", 8.0)),
            available_designations  = list(data.get("available_designations", [])),
            top_regulatory_risk     = str(data.get("top_regulatory_risk", "")),
        )
    except Exception as e:
        logger.warning("Regulatory panel failed: %s", e)
        return None


async def _run_commercial_panel(
    disease_name: str,
    idea: str,
    sub_expert_id: str,
    market_context: str = "",
) -> Optional[CommercialPanelResult]:
    domain_hint = _COMMERCIAL_DOMAIN_HINTS.get(sub_expert_id, "")
    system = (
        "You are a biotech market access and commercialization analyst.\n"
        + (f"Domain context: {domain_hint}\n" if domain_hint else "")
        + "Assess the commercial viability of this biomedical innovation.\n"
        "Return ONLY valid JSON — no prose, no markdown:\n"
        "{\n"
        '  "annual_price_benchmark_usd": <integer, estimated annual WAC price in USD>,\n'
        '  "pricing_comparable": "<name of comparable product used as pricing anchor>",\n'
        '  "key_payer_barrier": "<single most important commercial barrier in one specific sentence>",\n'
        '  "competitive_moat_score": <float 0-10, where 10=highly defensible competitive position>,\n'
        '  "moat_basis": "<what specifically creates or undermines the moat in one sentence>",\n'
        '  "yrs_to_peak_revenue": <integer, years post-launch to peak annual revenue>,\n'
        '  "reimbursement_mechanism": "<primary code/pathway, e.g., J-code, DRG+NTAP, CPT, self-pay>"\n'
        "}"
    )
    user = (
        f"Disease: {disease_name}\n"
        f"Domain: {sub_expert_id}\n"
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
) -> ExpertPanelResult:
    """
    Run all three sub-expert panels in parallel. Each panel has a different analytical
    lens and produces structured JSON with specific numbers/names — not prose.

    Designed to be called inside an asyncio.gather alongside other data fetches
    so it adds zero latency to the overall report generation flow.
    """
    import asyncio
    clinical, regulatory, commercial = await asyncio.gather(
        _run_clinical_panel(disease_name, idea),
        _run_regulatory_panel(disease_name, idea, sub_expert_id, product_type),
        _run_commercial_panel(disease_name, idea, sub_expert_id, market_context),
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
            "── REGULATORY PATHWAY EXPERT ──",
            f"  Recommended Pathway: {r.recommended_pathway}",
            f"  Approval Probability: {r.approval_probability_pct}%",
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
            "── COMMERCIAL VIABILITY EXPERT ──",
            f"  Pricing Benchmark: {price_fmt} (based on {com.pricing_comparable})",
            f"  Key Payer Barrier: {com.key_payer_barrier}",
            f"  Competitive Moat: {com.competitive_moat_score:.1f}/10 — {com.moat_basis}",
            f"  Time to Peak Revenue: {com.yrs_to_peak_revenue} years post-launch",
            f"  Reimbursement Mechanism: {com.reimbursement_mechanism}",
            "",
        ]

    lines.append("=== END EXPERT PANEL ===")
    return "\n".join(lines)
