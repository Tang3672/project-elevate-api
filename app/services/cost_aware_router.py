"""
Cost-Aware Specialist Router  (Brief Priority 3 / Sprint 6)
===========================================================
The brief's framing: "Do NOT lead with multiple LLMs. Lead with cost-aware
specialist routing + deterministic decision engines." This module is that
router — a deterministic planner that, for each request:

  1. classifies the task across many task-native dimensions (not just domain),
  2. picks a model TIER for each pipeline stage (classify / extract / specialist
     panel / synthesize / verify), escalating to the frontier model ONLY when
     uncertainty/complexity is high,
  3. plans which source tiers to query (escalating to slower tiers only when
     evidence is thin),
  4. estimates relative cost + latency.

All functions are pure and unit-testable. The orchestrator returns a plan dict;
the only side-effect in the pipeline is that the synthesis stage uses
`plan["synthesis_model"]` instead of always defaulting to the frontier — real
cost savings on low-complexity, well-evidenced, low-risk requests.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Real model ids, mapped to the brief's capability tiers.
FRONTIER_MODEL   = "claude-opus-5"            # premium synthesis
SPECIALIST_MODEL = "claude-sonnet-5"          # mid-tier synthesis / domain
SMALL_MODEL      = "claude-haiku-4-5-20251001"  # router / extraction / verifier

# Escalate synthesis to the frontier model at/above this complexity. Set high so
# the fast specialist model (Sonnet) handles the large majority of reports and the
# frontier (Opus) is reserved for genuinely hard cases — cost- AND latency-aware.
FRONTIER_ESCALATION_THRESHOLD = 0.80

# Regulatory-risk priors by modality (proxy for development + approval difficulty).
_REG_RISK = {
    "gene_cell": "high", "biologic": "medium", "vaccine": "medium",
    "device": "high", "diagnostic": "medium", "digital": "low",
    "small_molecule": "medium", "other": "medium",
}
_MODALITY_COMPLEXITY = {
    "gene_cell": 0.9, "biologic": 0.7, "device": 0.6, "vaccine": 0.6,
    "small_molecule": 0.5, "diagnostic": 0.5, "digital": 0.4, "other": 0.55,
}
_RISK_SCORE = {"high": 1.0, "medium": 0.6, "low": 0.3}
_EVIDENCE_COMPLEXITY = {"low": 0.9, "medium": 0.6, "high": 0.3}

_NOVELTY_HINTS = ("novel", "first-in-class", "first in class", "breakthrough",
                  "unprecedented", "new class", "de novo", "proprietary")


def _modality(product_type: str, sub_expert_id: str = "") -> str:
    s = f"{product_type} {sub_expert_id}".lower()
    if any(k in s for k in ("gene", "cell", "car-t", "car_t", "crispr", "aav")):
        return "gene_cell"
    if any(k in s for k in ("biologic", "antibody", "mab", "protein", "peptide", "adc")):
        return "biologic"
    if "vaccine" in s:
        return "vaccine"
    if any(k in s for k in ("device", "implant", "stent", "surgical")):
        return "device"
    if any(k in s for k in ("diagnostic", "assay", "ivd", "test", "biomarker")):
        return "diagnostic"
    if any(k in s for k in ("software", "digital", "samd", "algorithm", "app")):
        return "digital"
    if any(k in s for k in ("antibiotic", "small_molecule", "small molecule", "drug", "molecule", "amr")):
        return "small_molecule"
    return "other"


def _evidence_availability(signal_count: int) -> str:
    if signal_count >= 12:
        return "high"
    if signal_count >= 4:
        return "medium"
    return "low"


# ── Task classification ────────────────────────────────────────────────────────

def classify_task(idea: str, product_type: str, *, sub_expert_id: str = "",
                  development_stage: str = "preclinical", signal_count: int = 0,
                  output_type: str = "full_report") -> dict:
    """Classify a request across the brief's task-native dimensions."""
    modality = _modality(product_type, sub_expert_id)
    reg_risk = _REG_RISK.get(modality, "medium")
    evidence = _evidence_availability(signal_count)
    novel = any(h in (idea or "").lower() for h in _NOVELTY_HINTS)

    return {
        "modality": modality,
        "product_category": product_type,
        "sub_expert_id": sub_expert_id,     # needed by plan_sources for domain-gated source routing
        "development_stage": development_stage,
        "evidence_availability": evidence,
        "regulatory_risk": reg_risk,
        "data_sensitivity": "low",          # all sources are public — no PHI
        "novelty": "high" if novel else "standard",
        "required_output_type": output_type,
        "latency_budget_s": 20 if output_type == "full_report" else 8,
    }


def compute_complexity(profile: dict) -> float:
    """0-1 complexity score driving model-tier escalation."""
    reg = _RISK_SCORE.get(profile.get("regulatory_risk"), 0.6)
    nov = 0.9 if profile.get("novelty") == "high" else 0.5
    evi = _EVIDENCE_COMPLEXITY.get(profile.get("evidence_availability"), 0.6)
    mod = _MODALITY_COMPLEXITY.get(profile.get("modality"), 0.55)
    score = 0.30 * reg + 0.25 * nov + 0.25 * evi + 0.20 * mod
    return round(min(1.0, max(0.0, score)), 3)


# ── Model + source planning ─────────────────────────────────────────────────────

def plan_models(profile: dict, complexity: float) -> dict:
    """Pick a model tier per pipeline stage; frontier only when complex/uncertain."""
    quick = profile.get("required_output_type") != "full_report"
    # Frontier only for the hardest cases (complexity already folds in regulatory
    # risk, novelty, evidence thinness, and modality difficulty).
    escalate = (not quick) and complexity >= FRONTIER_ESCALATION_THRESHOLD
    synthesis_model = FRONTIER_MODEL if escalate else SPECIALIST_MODEL
    reason = (
        f"frontier ({FRONTIER_MODEL}) — high complexity {complexity:.2f} ≥ "
        f"{FRONTIER_ESCALATION_THRESHOLD}"
        if escalate else
        f"specialist ({SPECIALIST_MODEL}) — complexity {complexity:.2f} < "
        f"{FRONTIER_ESCALATION_THRESHOLD}; frontier reserved for the hardest cases"
    )
    return {
        "classify_model": SMALL_MODEL,
        "extract_model": SMALL_MODEL,
        "specialist_panel_model": SMALL_MODEL,
        "synthesis_model": synthesis_model,
        "verify_model": SMALL_MODEL,
        "escalated_to_frontier": escalate,
        "escalation_reason": reason,
    }


# Modality → prioritized source connectors (which to query and in what order).
# Clinical-only sources (openFDA, ClinicalTrials.gov, CDC PLACES, CMS data) must
# NOT appear for research tools or agriculture — those corpora index regulated
# clinical products and produce irrelevant results for lab instruments and sensors.
_SOURCE_MAP = {
    "small_molecule":   ["openFDA", "ClinicalTrials.gov", "DailyMed", "CMS ASP", "PubMed", "Google Patents"],
    "biologic":         ["openFDA", "ClinicalTrials.gov", "Open Targets", "CMS ASP", "PubMed", "Google Patents"],
    "gene_cell":        ["ClinicalTrials.gov", "ClinVar", "Orphanet", "NIH GARD", "openFDA", "PubMed"],
    "vaccine":          ["ClinicalTrials.gov", "openFDA", "WHO GHO", "CDC Surveillance", "PubMed"],
    "device":           ["openFDA", "ClinicalTrials.gov", "CMS Quality", "County Health Rankings", "Google Patents"],
    "diagnostic":       ["openFDA", "CMS ASP", "cBioPortal", "Open Targets", "PubMed"],
    "digital":          ["ClinicalTrials.gov", "CMS Quality", "AHRQ MEPS", "PubMed"],
    # Research tool and agriculture domains: NIH/NSF grant databases and OpenAlex
    # are the correct corpora — not clinical registries or drug databases.
    "research_tool":    ["NIH RePORTER", "NSF Awards", "OpenAlex", "Google Patents", "Semantic Scholar"],
    "research_infra":   ["NIH RePORTER", "NSF Awards", "OpenAlex", "Google Patents", "Semantic Scholar"],
    "agriculture":      ["USDA NIFA", "NSF Awards", "USDA NASS", "OpenAlex", "Google Patents"],
    "other":            ["openFDA", "ClinicalTrials.gov", "PubMed", "Google Patents"],
}


def plan_sources(profile: dict) -> dict:
    """Choose which sources to query; escalate to slower tiers only when thin."""
    modality = profile.get("modality", "other")
    sub_expert_id = profile.get("sub_expert_id", "") or ""

    # Research tool and agriculture archetypes override modality-based lookup:
    # their correct corpora are grant databases (NIH, NSF, USDA), not clinical registries.
    if sub_expert_id.startswith("research_tool") or sub_expert_id.startswith("research_infrastructure"):
        modality = "research_tool"
    elif sub_expert_id.startswith("research_infra"):
        modality = "research_infra"
    elif "agronomy" in sub_expert_id or "agriculture" in sub_expert_id or "agri" in sub_expert_id:
        modality = "agriculture"

    sources = _SOURCE_MAP.get(modality, _SOURCE_MAP["other"])
    escalate_tiers = profile.get("evidence_availability") == "low"
    # Funding/IP sweep is always worth it for full reports, but only for clinical domains
    # (NIH Reporter and EDGAR are already in the research tool plan above).
    if profile.get("required_output_type") == "full_report" and modality not in (
        "research_tool", "research_infra", "agriculture"
    ):
        for extra in ("NIH Reporter (SBIR/STTR)", "SEC EDGAR"):
            if extra not in sources:
                sources = sources + [extra]
    return {
        "prioritized_sources": sources,
        "escalate_to_slow_tiers": escalate_tiers,
        "max_tier": 3 if escalate_tiers else 2,
    }


def _estimate(profile: dict, models: dict) -> dict:
    """Rough relative cost/latency estimate (not billed $; for the dashboard)."""
    # Relative units: frontier synthesis dominates; small-model stages are cheap.
    synth_cost = 10 if models["escalated_to_frontier"] else 3
    base = 4  # router + extraction + 3-panel + verifier (all small models)
    return {
        "relative_cost_units": synth_cost + base,
        "estimated_latency_s": profile.get("latency_budget_s", 20),
        "cost_tier": "premium" if models["escalated_to_frontier"] else "standard",
    }


def build_routing_plan(idea: str, product_type: str, *, sub_expert_id: str = "",
                       development_stage: str = "preclinical", signal_count: int = 0,
                       output_type: str = "full_report") -> dict:
    """Full routing plan: classification + complexity + model plan + source plan + estimate."""
    profile = classify_task(idea, product_type, sub_expert_id=sub_expert_id,
                            development_stage=development_stage,
                            signal_count=signal_count, output_type=output_type)
    complexity = compute_complexity(profile)
    models = plan_models(profile, complexity)
    sources = plan_sources(profile)
    return {
        "task_profile": profile,
        "complexity_score": complexity,
        "model_plan": models,
        "synthesis_model": models["synthesis_model"],   # convenience for the pipeline
        "source_plan": sources,
        "estimate": _estimate(profile, models),
        "method": "deterministic_cost_aware_router_v1",
    }
