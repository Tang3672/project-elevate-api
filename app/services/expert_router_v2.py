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
from dataclasses import dataclass
from typing import Optional
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
                    "model":      ROUTER_MODEL,
                    "max_tokens": 150,
                    "system":     ROUTER_SYSTEM,
                    "messages":   [{"role": "user", "content": f"Tier1: {tier1}\nIdea: {idea[:800]}"}],
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
        "drug_small_molecule": "drug_rare_disease",
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
    "oncology":           "biologic",
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
