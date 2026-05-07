"""
Expert Router — Mixture of Experts
====================================
Hybrid routing: PI selects a domain hint, Claude independently classifies
the idea text, and the router reconciles them.

Logic:
  1. If PI selected "auto" → use Claude classification only
  2. If PI selected a domain AND Claude agrees → proceed with that domain
  3. If PI selected a domain BUT Claude disagrees → Claude wins,
     but a mismatch warning is returned so the UI can show the PI

Returns:
  RouterResult(domain_id, expert, confidence, mismatch_warning)
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from app.core.config import settings
from app.services.expert_profiles import (
    ExpertProfile, EXPERT_REGISTRY, get_all_keywords, get_expert
)

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ROUTER_MODEL      = "claude-haiku-4-5-20251001"   # fast, cheap for routing
ROUTER_TIMEOUT    = 20.0


@dataclass
class RouterResult:
    domain_id:         str
    expert:            ExpertProfile
    confidence:        float          # 0.0 - 1.0
    pi_selected:       Optional[str]  # what the PI chose
    claude_classified: str            # what Claude classified
    mismatch_warning:  Optional[str]  # shown in UI if domains disagree
    routing_method:    str            # "auto" | "pi_confirmed" | "claude_override"


ROUTER_SYSTEM = """You are a medical domain classifier. Given a description of a healthcare product or innovation, classify it into exactly ONE of these domains:

- antibiotic_amr: antibiotics, antimicrobials, resistance (CRE, MRSA, C. diff, Acinetobacter), beta-lactams, BLI combinations, antifungals
- oncology: cancer, tumors, carcinomas, immunotherapy, CAR-T, ADC, targeted therapy, checkpoint inhibitors, any cancer type
- cardiology: heart disease, cardiac, cardiovascular, heart failure, AFib, hypertension, coronary artery disease, cardiac devices, cardiac monitoring
- neurology_cns: neurological diseases, CNS, Alzheimer's, Parkinson's, MS, epilepsy, ALS, stroke, migraine, CNS drugs, brain devices
- metabolic_diabetes: diabetes (T1D, T2D), obesity, glucose monitoring, CGM, insulin, GLP-1, SGLT2, metabolic syndrome, NASH, CKD related to diabetes
- mental_health: psychiatric conditions, depression, anxiety, PTSD, schizophrenia, bipolar, addiction, psychedelics, digital mental health, telepsychiatry

Respond ONLY with valid JSON:
{"domain": "<domain_id>", "confidence": <0.0-1.0>, "reasoning": "<one sentence>"}

If the idea spans multiple domains, pick the PRIMARY domain the innovation targets."""


async def classify_with_claude(idea: str) -> tuple[str, float, str]:
    """Use Claude Haiku to classify the idea into a disease domain."""
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
                    "messages":   [{"role": "user", "content": f"Classify this healthcare innovation:\n\n{idea[:1000]}"}],
                }
            )
            r.raise_for_status()
            text = r.json()["content"][0]["text"].strip()
            # Parse JSON
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text.strip())
            domain     = data.get("domain", "antibiotic_amr")
            confidence = float(data.get("confidence", 0.7))
            reasoning  = data.get("reasoning", "")
            # Validate domain exists
            if domain not in EXPERT_REGISTRY:
                domain = _keyword_classify(idea)
            return domain, confidence, reasoning
    except Exception as e:
        logger.warning(f"Claude router failed: {e} — falling back to keyword classification")
        domain = _keyword_classify(idea)
        return domain, 0.6, "Classified by keyword matching (Claude router unavailable)"


def _keyword_classify(idea: str) -> str:
    """Fast keyword-based fallback classifier."""
    idea_lower = idea.lower()
    all_keywords = get_all_keywords()
    scores = {}
    for domain_id, keywords in all_keywords.items():
        score = sum(1 for kw in keywords if kw in idea_lower)
        if score > 0:
            scores[domain_id] = score
    if not scores:
        return "antibiotic_amr"  # default
    return max(scores, key=scores.get)


async def route(
    idea:        str,
    pi_domain:   Optional[str] = None,   # what PI selected ("auto" or domain_id)
) -> RouterResult:
    """
    Main routing function.
    Returns a RouterResult with the selected expert and routing metadata.
    """
    # Normalize
    pi_domain = pi_domain or "auto"
    if pi_domain not in EXPERT_REGISTRY and pi_domain != "auto":
        logger.warning(f"Unknown PI domain '{pi_domain}' — treating as auto")
        pi_domain = "auto"

    # Always classify with Claude
    claude_domain, confidence, reasoning = await classify_with_claude(idea)
    logger.info(f"Claude classified: {claude_domain} (confidence={confidence:.2f})")

    # Routing logic
    if pi_domain == "auto":
        # Pure Claude classification
        final_domain    = claude_domain
        routing_method  = "auto"
        mismatch        = None
    elif pi_domain == claude_domain:
        # PI and Claude agree
        final_domain    = pi_domain
        routing_method  = "pi_confirmed"
        confidence      = min(confidence + 0.15, 1.0)   # boost confidence when they agree
        mismatch        = None
    else:
        # Disagreement — Claude wins
        pi_name     = EXPERT_REGISTRY.get(pi_domain, {})
        pi_label    = getattr(pi_name, 'display_name', pi_domain) if pi_name else pi_domain
        claude_name = EXPERT_REGISTRY[claude_domain].display_name
        final_domain   = claude_domain
        routing_method = "claude_override"
        mismatch       = (
            f"You selected {pi_label} but this idea appears to be in "
            f"{claude_name} ({reasoning}). Routing to {claude_name}."
        )
        logger.info(f"Domain mismatch: PI={pi_domain}, Claude={claude_domain} — Claude wins")

    expert = EXPERT_REGISTRY[final_domain]
    return RouterResult(
        domain_id         = final_domain,
        expert            = expert,
        confidence        = confidence,
        pi_selected       = pi_domain,
        claude_classified = claude_domain,
        mismatch_warning  = mismatch,
        routing_method    = routing_method,
    )
