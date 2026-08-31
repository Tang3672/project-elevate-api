"""
Expert Router v2 — Two-Tier Mixture of Experts
===============================================
Routes PI submissions to the correct sub-expert based on:
  1. Tier 1 product category (PI-selected from 8 options)
  2. Disease/indication keywords (from idea text)
  3. Claude Haiku classification (independent verification)

Returns RouterResult with the selected SubExpertProfile.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional, List
import httpx

from app.core.config import settings
from app.services.expert_profiles_v2 import (
    SubExpertProfile, SUB_EXPERT_REGISTRY,
    get_sub_experts_for_tier1, get_all_keywords, TIER1_CATEGORIES
)

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ROUTER_MODEL      = "claude-haiku-4-5-20251001"
ROUTER_TIMEOUT    = 20.0


@dataclass
class RouterResult:
    sub_expert_id:     str
    expert:            SubExpertProfile
    tier1_category:    str
    confidence:        float
    routing_method:    str        # "keyword" | "claude" | "pi_confirmed" | "claude_override"
    mismatch_warning:  Optional[str]


ROUTER_SYSTEM = """You are a healthcare product classifier. Given a description of a healthcare innovation and a tier1 product category selected by the PI, identify the best sub-expert to handle this report.

Tier1 categories:
- drug_small_molecule: chemical drugs, pills, oral/injectable small molecules
- biologic: monoclonal antibodies, ADCs, bispecifics, enzyme replacement, fusion proteins
- gene_cell_therapy: AAV gene therapy, CAR-T, cell therapy, ASOs, siRNA, mRNA therapeutics, base editing
- medical_device: hardware devices, implants, wearables, combination products
- diagnostic: lab tests, PCR, NGS, companion diagnostics, imaging diagnostics
- digital_health: SaMD, AI/ML software, digital therapeutics, remote monitoring
- vaccine_immunotherapy: prophylactic vaccines, therapeutic cancer vaccines
- other_platform: microbiome, CRISPR tools, delivery platforms, novel modalities

Sub-expert IDs to choose from:
Drug: drug_amr, drug_oncology, drug_cns, drug_cardiology, drug_metabolic, drug_mental_health, drug_rare_disease, drug_infectious_non_amr, drug_immunology
Biologic: biologic_oncology, biologic_immunology, biologic_hematology, biologic_rare_disease, biologic_cardiology
Gene/Cell: gene_therapy_rare, gene_therapy_oncology, gene_therapy_cns, gene_therapy_rna, gene_therapy_hematology
Device: device_cardiovascular, device_metabolic, device_neurology
Diagnostic: diagnostic_molecular, diagnostic_companion
Digital: digital_cds, digital_therapeutic, digital_rpm
Vaccine: vaccine_prophylactic, vaccine_cancer_immuno
Other: other_microbiome, other_crispr, other_delivery

Respond ONLY with JSON:
{"sub_expert_id": "<id>", "confidence": <0.0-1.0>, "reasoning": "<one sentence>"}"""


async def _classify_with_claude(idea: str, tier1: str) -> tuple[str, float, str]:
    try:
        async with httpx.AsyncClient(timeout=ROUTER_TIMEOUT) as client:
            r = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key":         settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":       ROUTER_MODEL,
                    "max_tokens":  150,
                    "temperature": 0,          # M-03: deterministic routing — identical ideas must route identically
                    "system":      ROUTER_SYSTEM,
                    "messages":    [{"role": "user", "content": f"Tier1: {tier1}\nIdea: {idea[:800]}"}],
                }
            )
            r.raise_for_status()
            text = r.json()["content"][0]["text"].strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text.strip())
            sub_id = data.get("sub_expert_id", "")
            if sub_id not in SUB_EXPERT_REGISTRY:
                sub_id = _keyword_route(idea, tier1)
            return sub_id, float(data.get("confidence", 0.7)), data.get("reasoning", "")
    except Exception as e:
        logger.warning(f"Claude router v2 failed: {e} — falling back to keyword routing")
        return _keyword_route(idea, tier1), 0.6, "Keyword classification"


def _keyword_route(idea: str, tier1: str) -> str:
    """Fast keyword-based sub-expert selection within a tier1 category."""
    idea_lower = idea.lower()

    # Get sub-experts for this tier1
    candidates = get_sub_experts_for_tier1(tier1)
    if not candidates:
        # Fallback: search all sub-experts
        candidates = list(SUB_EXPERT_REGISTRY.values())

    scores = {}
    for expert in candidates:
        score = sum(1 for kw in expert.router_keywords if kw in idea_lower)
        if score > 0:
            scores[expert.sub_expert_id] = score

    if scores:
        return max(scores, key=scores.get)

    # Default per tier1
    defaults = {
        "drug_small_molecule": "drug_oncology",    # LOW-01: was drug_rare_disease — rare disease framing is wrong for most unknown drugs
        "biologic":            "biologic_oncology",
        "gene_cell_therapy":   "gene_therapy_rare",
        "medical_device":      "device_cardiovascular",
        "diagnostic":          "diagnostic_molecular",
        "digital_health":      "digital_cds",
        "vaccine_immunotherapy": "vaccine_prophylactic",
        "other_platform":      "other_delivery",
    }
    return defaults.get(tier1, "drug_rare_disease")


async def route_v2(
    idea:          str,
    tier1_category: str = "drug_small_molecule",
    pi_sub_expert:  Optional[str] = None,
) -> RouterResult:
    """
    Main routing function for v2.

    Args:
        idea:           PI's product description
        tier1_category: PI-selected tier1 category
        pi_sub_expert:  Optional: PI-specified sub-expert (for future UI)
    """
    # Always run Claude classification
    claude_sub_id, confidence, reasoning = await _classify_with_claude(idea, tier1_category)
    logger.info(f"Router v2: tier1={tier1_category} → sub_expert={claude_sub_id} ({confidence:.2f})")

    # Determine final sub-expert
    if pi_sub_expert and pi_sub_expert in SUB_EXPERT_REGISTRY:
        if pi_sub_expert == claude_sub_id:
            method  = "pi_confirmed"
            final   = pi_sub_expert
            warning = None
        else:
            # Claude overrides PI
            pi_name    = SUB_EXPERT_REGISTRY[pi_sub_expert].display_name
            claude_name = SUB_EXPERT_REGISTRY[claude_sub_id].display_name
            method  = "claude_override"
            final   = claude_sub_id
            warning = (f"You indicated {pi_name} but this idea appears to be "
                      f"{claude_name} ({reasoning}). Routing to {claude_name}.")
    else:
        method  = "auto"
        final   = claude_sub_id
        warning = None

    expert = SUB_EXPERT_REGISTRY[final]

    return RouterResult(
        sub_expert_id    = final,
        expert           = expert,
        tier1_category   = tier1_category,
        confidence       = confidence,
        routing_method   = method,
        mismatch_warning = warning,
    )


# ── Backwards compatibility with v1 route() function ─────────────────────────
# The old system passed disease_domain. Map it to tier1 + run v2 routing.

DOMAIN_TO_TIER1 = {
    "antibiotic_amr":     "drug_small_molecule",
    "oncology":           "drug_small_molecule",  # H-04: was "biologic" — most oncology products are small molecules; biologic tier forces BLA/ADC framing for oral targeted therapies
    "cardiology":         "drug_small_molecule",
    "neurology_cns":      "drug_small_molecule",
    "metabolic_diabetes": "drug_small_molecule",
    "mental_health":      "drug_small_molecule",
    "auto":               "drug_small_molecule",
}

async def route(idea: str, pi_domain: str = "auto") -> RouterResult:
    """Backwards-compatible v1 route() — maps old disease_domain to new tier1 routing."""
    tier1 = DOMAIN_TO_TIER1.get(pi_domain, "drug_small_molecule")
    return await route_v2(idea=idea, tier1_category=tier1)


# ══════════════════════════════════════════════════════════════════════════════
# MoE Extension — Multi-Expert Activation + Heuristic Library
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ExpertActivation:
    sub_expert_id: str
    expert:        SubExpertProfile
    weight:        float
    sam_multiplier: float
    som_multiplier: float
    reasoning:     str

    def to_dict(self) -> dict:
        return {
            "sub_expert_id":  self.sub_expert_id,
            "expert_name":    self.expert.display_name,
            "weight":         self.weight,
            "sam_multiplier": self.sam_multiplier,
            "som_multiplier": self.som_multiplier,
            "reasoning":      self.reasoning,
        }


@dataclass
class ExpertConsensus:
    consensus_sam_multiplier: float
    consensus_som_multiplier: float
    has_disagreement:         bool
    disagreement_note:        str

    def to_dict(self) -> dict:
        return {
            "consensus_sam_multiplier": self.consensus_sam_multiplier,
            "consensus_som_multiplier": self.consensus_som_multiplier,
            "has_disagreement":         self.has_disagreement,
            "disagreement_note":        self.disagreement_note,
        }


@dataclass
class FiredHeuristic:
    rule_name:      str
    sam_adjustment: float
    som_adjustment: float
    note:           str
    source:         str

    def to_dict(self) -> dict:
        return {
            "rule_name":      self.rule_name,
            "sam_adjustment": self.sam_adjustment,
            "som_adjustment": self.som_adjustment,
            "note":           self.note,
            "source":         self.source,
        }


@dataclass
class _HeuristicRule:
    name:           str
    keywords:       List[str]
    product_types:  List[str]  # empty = all types; non-empty = only these
    note:           str
    source:         str
    confidence:     str        # "high" | "medium" | "low"
    sam_adjustment: float
    som_adjustment: float

    def matches(self, idea_lower: str, product_type: str) -> bool:
        if not idea_lower:
            return False
        if self.product_types and product_type not in self.product_types:
            return False
        return any(kw in idea_lower for kw in self.keywords)


HEURISTIC_LIBRARY: List[_HeuristicRule] = [
    _HeuristicRule(
        name="stewardship_restriction",
        keywords=["antibiotic", "amr", "antibacterial", "carbapenem", "reserve-tier",
                  "last-resort", "antimicrobial resistance"],
        product_types=[],
        note=(
            "Antibiotic stewardship programs (ASPs) enforce reserve-tier restrictions "
            "that limit use to confirmed refractory cases, materially compressing SOM. "
            "Penetration models without stewardship discounting overestimate market share by 30–50%."
        ),
        source="DOJ/FTC Horizontal Merger Guidelines; IDSA Stewardship Guidelines (2016); Laxminarayan et al. Lancet 2013",
        confidence="high",
        sam_adjustment=1.0,
        som_adjustment=0.55,
    ),
    _HeuristicRule(
        name="acute_episodic_use",
        keywords=["stroke", "acute ischemic", "heart attack", "myocardial infarction",
                  "episodic", "single infusion", "acute event", "emergency iv", "acute stroke"],
        product_types=[],
        note=(
            "Products used only at acute disease episodes (stroke, MI, sepsis) have "
            "much lower utilisation rates than chronic therapies. Standard analog penetration "
            "benchmarks assume chronic dosing; acute-episodic products require downward correction."
        ),
        source="Grabowski & Vernon J. Law & Econ. (1992); CMS episode-based payment data",
        confidence="high",
        sam_adjustment=0.90,
        som_adjustment=0.70,
    ),
    _HeuristicRule(
        name="narrow_indication_first",
        keywords=["orphan", "rare disease", "narrow indication", "initial label",
                  "first approval narrow"],
        product_types=[],
        note=(
            "Rare-disease and orphan initial approvals cover a narrow patient slice. "
            "SAM and SOM estimates should reflect the initial label population only; "
            "label expansions unlock the broader market only after additional trials succeed."
        ),
        source="FDA Orphan Drug Designations; Evaluate Pharma Rare Disease 2022 Report",
        confidence="medium",
        sam_adjustment=0.70,
        som_adjustment=0.60,
    ),
    _HeuristicRule(
        name="order_of_entry_penalty",
        keywords=["second-to-market", "biosimilar", "late entrant", "third-to-market",
                  "entrenched competition", "me-too", "follower"],
        product_types=[],
        note=(
            "Late-to-market products face entrenched formulary positions and physician habit. "
            "Empirically, the second entrant captures 20–35% of the pioneer's share in the same "
            "class (Grabowski & Vernon 1992). Penetration must be discounted vs first-in-class analogs."
        ),
        source="Grabowski & Vernon J. Law & Econ. (1992); IQVIA market share data",
        confidence="high",
        sam_adjustment=1.0,
        som_adjustment=0.70,
    ),
    _HeuristicRule(
        name="roa_stickiness",
        keywords=["iv infusion", "infusion center", "intravenous infusion", "injection burden",
                  "subcutaneous self-inject", "inhalation device"],
        product_types=[],
        note=(
            "Route-of-administration (RoA) requiring infusion center visits or complex injection "
            "protocols creates a structural adoption ceiling. Payer coverage requirements for "
            "specialist administration further restrict SOM vs oral therapy analogs."
        ),
        source="IQVIA Real-World Adherence Study (2020); FDA Prescribing Information burden data",
        confidence="medium",
        sam_adjustment=1.0,
        som_adjustment=0.85,
    ),
    _HeuristicRule(
        name="biomarker_defined_population",
        keywords=["companion diagnostic", "biomarker", "biomarker-positive", "cdx",
                  "her2+", "her2 positive", "kras", "pdl1", "pd-l1", "biomarker selection"],
        product_types=[],
        note=(
            "Products requiring a companion diagnostic (CDx) test to identify eligible patients "
            "restrict SAM to the biomarker-positive fraction of the disease. This can be 10–50% "
            "of the full diagnosed population, substantially reducing addressable market."
        ),
        source="FDA CDx Guidance (2014, updated 2023); Personalized Medicine Coalition Report 2022",
        confidence="high",
        sam_adjustment=0.75,
        som_adjustment=0.85,
    ),
    _HeuristicRule(
        name="combination_product_complexity",
        keywords=["combination product", "drug-device", "co-formulation", "dual-action",
                  "combination therapy device", "drug device combination"],
        product_types=[],
        note=(
            "Combination products (drug+device under a single 510(k)/PMA/NDA) face FDA Center "
            "coordination between CDER/CDRH, often adding 12–18 months to approval timelines and "
            "increasing regulatory cost. This delays the revenue ramp vs standalone products."
        ),
        source="FDA Combination Products Guidance (21 CFR Part 3); CDRH Combination Product Policy 2022",
        confidence="medium",
        sam_adjustment=1.0,
        som_adjustment=0.80,
    ),
    _HeuristicRule(
        name="samd_no_reimbursement_code",
        keywords=["clinical decision support", "hospital ai", "samd",
                  "software as a medical device", "ai clinical", "radiology ai",
                  "no cpt", "cds software"],
        product_types=["digital_health", "medical_device"],
        note=(
            "SaMD and AI-based clinical decision support tools frequently lack a dedicated CPT "
            "reimbursement code. Without a billable code, hospital systems adopt on a per-contract "
            "basis, making penetration slower and less predictable than device or drug analogs."
        ),
        source="AMA CPT Editorial Panel guidance; FDA SaMD Action Plan (2021); ICER Digital Health Report 2022",
        confidence="high",
        sam_adjustment=0.85,
        som_adjustment=0.60,
    ),
]


def apply_heuristics(idea_text: str, product_type: str = "") -> List[FiredHeuristic]:
    """Return FiredHeuristic list for every rule that matches idea_text + product_type."""
    if not idea_text:
        return []
    idea_lower = idea_text.lower()
    fired: List[FiredHeuristic] = []
    for rule in HEURISTIC_LIBRARY:
        if rule.matches(idea_lower, product_type):
            fired.append(FiredHeuristic(
                rule_name=rule.name,
                sam_adjustment=rule.sam_adjustment,
                som_adjustment=rule.som_adjustment,
                note=rule.note,
                source=rule.source,
            ))
    return fired


def reconcile(activations: List[ExpertActivation]) -> ExpertConsensus:
    """Compute weighted consensus across activations; flag SOM disagreement > 1.3×."""
    if not activations:
        raise ValueError("Cannot reconcile an empty list of expert activations")

    total_w = sum(a.weight for a in activations)
    if total_w == 0:
        raise ValueError("Total weight is zero — at least one activation must have weight > 0")

    consensus_sam = sum(a.weight * a.sam_multiplier for a in activations) / total_w
    consensus_som = sum(a.weight * a.som_multiplier for a in activations) / total_w

    if len(activations) == 1:
        return ExpertConsensus(
            consensus_sam_multiplier=round(consensus_sam, 4),
            consensus_som_multiplier=round(consensus_som, 4),
            has_disagreement=False,
            disagreement_note="",
        )

    som_values = [a.som_multiplier for a in activations]
    max_som = max(som_values)
    min_som = min(som_values)
    has_disagreement = (min_som > 0 and max_som / min_som > 1.3)
    note = ""
    if has_disagreement:
        note = (
            f"SOM multiplier disagreement: max={max_som:.2f}, min={min_som:.2f} "
            f"(spread={max_som / min_som:.2f}×). Expert consensus is uncertain — "
            "review competing expert assumptions before finalising."
        )

    return ExpertConsensus(
        consensus_sam_multiplier=round(consensus_sam, 4),
        consensus_som_multiplier=round(consensus_som, 4),
        has_disagreement=has_disagreement,
        disagreement_note=note,
    )


# Default SAM/SOM multipliers per tier1 category (calibrated vs drug chronic baseline)
_TIER1_MULTIPLIERS: dict = {
    "drug_small_molecule":   (1.00, 1.00),
    "biologic":              (1.00, 1.00),
    "gene_cell_therapy":     (0.80, 0.90),
    "medical_device":        (1.00, 1.00),
    "diagnostic":            (0.90, 0.85),
    "digital_health":        (0.90, 0.70),
    "vaccine_immunotherapy": (0.85, 0.85),
    "other_platform":        (0.85, 0.85),
}


async def route_to_experts(
    idea:           str,
    tier1_category: str = "drug_small_molecule",
) -> List[ExpertActivation]:
    """
    Multi-expert routing — returns ExpertActivation list with weights summing to 1.0.

    Uses keyword routing for the primary expert (no API call required).
    When a secondary candidate exists in the same tier1, activates it with 0.30 weight
    so the consensus reflects the full breadth of applicable expertise.
    """
    primary_id = _keyword_route(idea, tier1_category)
    primary_expert = SUB_EXPERT_REGISTRY.get(primary_id)
    if primary_expert is None:
        primary_id     = next(iter(SUB_EXPERT_REGISTRY))
        primary_expert = SUB_EXPERT_REGISTRY[primary_id]

    sam_mult, som_mult = _TIER1_MULTIPLIERS.get(tier1_category, (1.0, 1.0))

    # Find a secondary expert in the same tier1 (first non-primary)
    candidates  = get_sub_experts_for_tier1(tier1_category)
    secondary   = next((c for c in candidates if c.sub_expert_id != primary_id), None)

    primary_weight = 0.70 if secondary else 1.0

    activations: List[ExpertActivation] = [
        ExpertActivation(
            sub_expert_id=primary_id,
            expert=primary_expert,
            weight=primary_weight,
            sam_multiplier=sam_mult,
            som_multiplier=som_mult,
            reasoning=(
                f"Primary keyword routing → {primary_expert.display_name} "
                f"(tier1={tier1_category})"
            ),
        )
    ]

    if secondary:
        activations.append(
            ExpertActivation(
                sub_expert_id=secondary.sub_expert_id,
                expert=secondary,
                weight=0.30,
                sam_multiplier=round(sam_mult * 0.95, 4),
                som_multiplier=round(som_mult * 0.95, 4),
                reasoning=(
                    f"Secondary coverage expert ({secondary.display_name}) "
                    f"broadens consensus for {tier1_category}"
                ),
            )
        )

    return activations
