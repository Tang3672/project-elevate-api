import asyncio
import os
"""
PI Alignment Service v2
=======================
Generates full go-to-market intelligence reports for principal investigators.

For ANTIBIOTIC product type, the report includes:
  - Deep disease intelligence (CDC AR Threats, WHO BPPL, incidence/mortality)
  - Transparent bottom-up market sizing (patients × price × penetration = TAM)
  - Full FDA regulatory pathway (QIDP, LPAD, 505(b)(2), Fast Track, etc.)
  - Clinical trial requirements by phase with costs and endpoints
  - Market access strategy with P&T committee dynamics
  - Friction points and loopholes (NTAP, PASTEUR Act, BARDA/CARB-X funding)
  - Source citation on every data point

All other product types fall back to the original alignment approach with
source citations added.
"""

import json
import logging
from datetime import datetime
from typing import Optional

import httpx

from app.services.embedding_service import embed_text
from app.db.demand_repository import search_similar_signals, get_signal_counts_by_source
from app.db.needs_repository import find_similar_needs
from app.models.alignment import (
    AlignmentReport, DemandScores, EvidenceItem,
    HospitalNeedMatch, MarketGeography,
    PIReport, ProductType,
    DiseaseIntelligence, DiseaseDataPoint,
    MarketSizingCalculation, MarketSizingStep,
    RegulatoryPathway, RegulatoryDesignation, ClinicalTrialRequirements,
    MarketAccessStrategy, BuyerSegment,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL      = "claude-opus-4-5"


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINTS
# ══════════════════════════════════════════════════════════════════════════════

async def generate_pi_report(
    idea:           str,
    product_type:   str = "other",
    disease_domain: str = "auto",
    tier1_category: str = "drug_small_molecule",
    user_id:        int = None,
) -> PIReport:
    """
    Full MoE pipeline: idea → Expert Router → Expert Context → Claude → PIReport.

    The router selects the best Expert (AMR, Oncology, Cardiology, Neuro,
    Metabolic, Mental Health) based on PI hint + Claude classification.
    Each expert injects deep domain knowledge into the Researcher context.
    """
    from app.services.expert_router import route as route_expert

    pt = ProductType(product_type.lower()) if product_type else ProductType.OTHER

    source_counts        = await get_signal_counts_by_source()
    total_signals        = sum(r["count"] for r in source_counts)
    idea_embedding       = await embed_text(idea)

    demand_results       = await search_similar_signals(
        query_embedding=idea_embedding, top_k=20, min_similarity=0.50)
    hospital_matches_raw = await find_similar_needs(
        query_embedding=idea_embedding, top_k=10, min_similarity=0.50)

    # ── PI Institutional Memory ───────────────────────────────────────────────
    pi_memory_context = ""
    if user_id:
        try:
            from app.services.pi_memory_service import get_pi_memory_context
            pi_memory_context = await get_pi_memory_context(user_id)
            if pi_memory_context:
                logger.info(f"PI memory loaded for user {user_id}")
        except Exception as e:
            logger.warning(f"PI memory load failed (non-fatal): {e}")

    # ── MoE Routing ───────────────────────────────────────────────────────────
    router_result = await route_expert(idea=idea, pi_domain=disease_domain)
    expert        = router_result.expert
    logger.info(
        f"MoE Router: domain={expert.domain_id} "
        f"method={router_result.routing_method} "
        f"confidence={router_result.confidence:.2f}"
    )

    # ── Generate with Expert context ──────────────────────────────────────────
    report = await _generate_expert_report(
        idea, pt, expert, demand_results, hospital_matches_raw, total_signals,
        pi_memory_context=pi_memory_context)

    # Build sources from structured data
    try:
        from app.services.source_formatter import build_sources_from_report
        report_dict = report.model_dump(mode="json")
        report_dict = build_sources_from_report(report_dict)
        report.sources = report_dict.get("sources", [])
    except Exception as e:
        logger.warning(f"Source building failed: {e}")

    # Attach routing metadata
    report.expert_domain   = getattr(expert, "sub_expert_id", getattr(expert, "domain_id", "unknown"))
    report.expert_name     = expert.display_name
    report.expert_icon     = expert.icon
    report.routing_method  = router_result.routing_method
    report.mismatch_warning = router_result.mismatch_warning

    # ── LangGraph Validation ──────────────────────────────────────────────────
    try:
        from app.services.validation_graph import validate_pi_report
        report_dict = report.model_dump(mode="json")
        # Pass sub_expert_id and critic context for domain-aware validation
        _sub_id = getattr(expert, "sub_expert_id", getattr(expert, "domain_id", "drug_amr"))
        validated   = await validate_pi_report(report_dict, _sub_id)
        report.validation = validated.get("validation")
    except Exception as e:
        logger.error(f"Validation graph error: {e}")
        report.validation = {
            "status": "ERROR", "passed": True, "warnings": [], "notes": [],
            "total_flags": 0, "error": str(e),
            "summary": "Validation service unavailable",
            "validated_at": None,
        }

    return report


async def generate_alignment_report(idea: str) -> AlignmentReport:
    """Legacy entry point — kept for backward compatibility."""
    source_counts       = await get_signal_counts_by_source()
    total_signals       = sum(r["count"] for r in source_counts)
    idea_embedding      = await embed_text(idea)
    demand_results      = await search_similar_signals(
        query_embedding=idea_embedding, top_k=20, min_similarity=0.50)
    hospital_matches_raw = await find_similar_needs(
        query_embedding=idea_embedding, top_k=10, min_similarity=0.55)
    context       = _build_legacy_context(idea, demand_results, hospital_matches_raw)
    claude_resp   = await _call_claude(context, LEGACY_SYSTEM_PROMPT)
    return _parse_legacy_response(
        claude_resp, idea, demand_results, hospital_matches_raw,
        total_signals, len(hospital_matches_raw))


# ══════════════════════════════════════════════════════════════════════════════
# ANTIBIOTIC-SPECIFIC PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

ANTIBIOTIC_SYSTEM_PROMPT = """You are a go-to-market intelligence engine specializing in antibiotic drug development for principal investigators (PIs).

Your job: generate a comprehensive, source-cited intelligence report that replaces the research a PI would normally do over weeks. Every number must cite its source.

CRITICAL RULES:
1. NO opaque scores (0-100). Replace with exact calculations showing every step.
2. Every data point must include source name + URL where available.
3. Market sizing must be bottom-up: (patients × price per course × penetration rate = TAM).
4. Regulatory guidance must be specific to the pathogen/indication, not generic.
5. Show friction points honestly — do not sugarcoat commercial challenges.
6. Include specific loopholes and expedient strategies used by real antibiotic developers.

You must respond with ONLY a valid JSON object. No markdown, no preamble. Use this exact schema:

{
  "executive_summary": "<2-3 sentence summary citing specific numbers>",

  "disease_intelligence": {
    "condition": "<primary pathogen or disease>",
    "data_points": [
      {
        "metric": "<e.g. Annual U.S. incidence>",
        "value": "<e.g. 119,247 infections>",
        "year": "<e.g. 2017>",
        "source": "<e.g. CDC MMWR 68(9), Vital Signs>",
        "source_url": "<URL or null>"
      }
    ],
    "resistance_profile": "<specific resistance mechanisms and prevalence>",
    "pipeline_status": "<competing products in clinical development>",
    "unmet_need_summary": "<1-2 sentence summary of what's missing>"
  },

  "market_sizing": {
    "steps": [
      {
        "label": "<e.g. Annual U.S. serious MRSA BSIs>",
        "value": 119247,
        "unit": "patients",
        "source": "<e.g. CDC MMWR 68(9) 2019>",
        "source_url": "<URL or null>",
        "notes": "<e.g. Subset requiring IV antibiotic therapy>"
      }
    ],
    "formula": "<e.g. Addressable patients (80,000) × Price per course ($12,000) × Market penetration (15%) = TAM>",
    "total_addressable_market_usd": 144000000,
    "serviceable_market_usd": 43200000,
    "methodology_note": "<explain key assumptions and why SAM < TAM>"
  },

  "regulatory_pathway": {
    "recommended_pathway": "<e.g. NDA via GAIN Act QIDP + Fast Track>",
    "pathway_rationale": "<why this pathway fits this specific product>",
    "designations": [
      {
        "name": "<e.g. QIDP Designation>",
        "description": "<what it is>",
        "benefit": "<what the PI gets — be specific: +5yr exclusivity, priority review, etc.>",
        "eligibility": "<how to qualify>",
        "how_to_apply": "<practical steps to apply>",
        "timeline": "<when to apply and FDA response time>",
        "source": "<e.g. GAIN Act 2012, 21 U.S.C. 355f; FDA QIDP Q&A Guidance 2021>",
        "source_url": "<URL>",
        "priority": "<recommended|consider|optional>"
      }
    ],
    "clinical_trial_requirements": [
      {
        "phase": "<e.g. Phase 3>",
        "patient_count": "<e.g. 500-1000 patients>",
        "duration": "<e.g. 18-24 months enrollment + 12 months follow-up>",
        "estimated_cost": "<e.g. $50M-$120M>",
        "key_endpoints": ["<e.g. 28-day all-cause mortality>", "<e.g. clinical cure at test-of-cure>"],
        "fda_guidance_document": "<exact FDA guidance title>",
        "source_url": "<URL>",
        "success_probability": "<e.g. ~40% Phase 2→3 transition for antibiotics>"
      }
    ],
    "total_timeline_estimate": "<e.g. 7-10 years from IND to NDA approval>",
    "total_cost_estimate": "<e.g. $300M-$600M including Phase 1-3 and NDA filing>",
    "key_friction_points": [
      "<e.g. Susceptibility test breakpoints: BD/Vitek AST devices lag CLSI M100 by 3-5 years, blocking commercial uptake until automated AST available (FDA Antibacterial Susceptibility Test Interpretive Criteria guidance)>",
      "<e.g. Non-inferiority trial design: FDA requires NI margin ≤10% for HABP/VABP, making it impossible to demonstrate 'substantial improvement' needed for Breakthrough Therapy designation>"
    ],
    "loopholes_and_strategies": [
      "<e.g. Stack QIDP + Orphan Drug Designation for narrow-spectrum agents targeting rare infections (e.g., Burkholderia, NTM) to get 5yr QIDP + 7yr ODE exclusivity simultaneously>",
      "<e.g. 505(b)(2) NDA pathway: rely on FDA's prior findings for a known mechanism, reformulate or combine, reducing Phase 3 requirements by 30-40% — used by Aradigm (ciprofloxacin inhaled), Paratek (omadacycline)>"
    ],
    "funding_programs": [
      "<e.g. CARB-X: up to $4M preclinical + $6M Phase 1 non-dilutive funding; apply at carb-x.org; deadlines twice yearly>",
      "<e.g. BARDA Broad Spectrum Antimicrobials program: $50M-$200M late-stage development contracts; requires prior IND and Phase 1 safety data; BAA posted at medicalcountermeasures.gov>"
    ]
  },

  "market_access": {
    "primary_channel": "<e.g. Hospital formulary via GPO contract (Vizient/Premier)>",
    "buyer_segments": [
      {
        "segment_name": "<e.g. Academic Medical Centers / Teaching Hospitals>",
        "buyer_count": "<e.g. ~350 facilities>",
        "decision_maker": "<e.g. P&T Committee + Antimicrobial Stewardship Pharmacist>",
        "price_per_unit": "<e.g. $8,000-$12,000 per treatment course>",
        "annual_spend_per_facility": "<e.g. $200K-$800K for novel gram-negative antibiotics>",
        "access_mechanism": "<e.g. P&T drug monograph + MUE; typically 12-18 months post-approval>",
        "timeline_to_access": "<e.g. 12-18 months post-FDA approval>",
        "source": "<cite source>"
      }
    ],
    "key_opinion_leaders": [
      "<e.g. IDSA Fellows in infectious disease — most influential; target IDSA Annual Meeting poster/oral presentations>",
      "<e.g. Hospital antimicrobial stewardship pharmacists — the actual formulary decision-makers in >80% of cases>"
    ],
    "reimbursement_pathway": "<e.g. CMS New Technology Add-On Payment (NTAP): 75% cost add-on above DRG for QIDP-designated antibiotics, effective 2-3 years post-approval — apply 2 years before expected approval date>",
    "first_commercial_step": "<most important first step to market>",
    "international_opportunities": [
      "<e.g. UK NHS Subscription Model: up to £10M/yr fixed payment per antibiotic, delinked from sales volume; apply via NICE health-tech assessment; deadline annually>",
      "<e.g. EU: HERA incentive framework under negotiation; EMA conditional marketing authorization available for serious/life-threatening infections>"
    ]
  },

  "market_geography": {
    "description": "<where demand is geographically concentrated>",
    "top_states": ["<state1>", "<state2>"],
    "scope": "<national|regional|concentrated>"
  },

  "recommended_next_steps": [
    "<specific, actionable step with timeline>",
    "<step 2>",
    "<step 3>",
    "<step 4>",
    "<step 5>"
  ],

  "limitations": "<honest assessment of data gaps and caveats>"
}"""




async def _generate_expert_report(idea, product_type, expert, demand_results, hospital_matches_raw, total_signals, pi_memory_context=""):
    """
    Generates a PI report using the selected Expert's domain knowledge.
    Injects expert system_prompt + knowledge_base into the researcher context.
    Falls back to antibiotic-specific parsing for AMR; generic parsing for others.
    """
    # ── Two-layer knowledge system ────────────────────────────────────────────
    # Layer 1: Disease Classifier → specific disease name
    disease_info = {}
    disease_name = "the indicated condition"
    try:
        from app.services.disease_classifier import classify_disease
        disease_info = await classify_disease(idea)
        disease_name = disease_info.get("disease_name", "the indicated condition")
    except Exception as e:
        logger.warning(f"Disease classification failed: {e}")

    # Layer 2: Knowledge Retriever → 5-6 parallel live searches
    # Uses sub_expert_id from router (v2) or domain_id (v1 fallback)
    sub_expert_id = getattr(expert, "sub_expert_id", getattr(expert, "domain_id", "drug_amr"))
    expert_system_prompt = getattr(expert, "system_prompt", "")
    expert_critic_rules  = getattr(expert, "critic_rules", "")
    domain_static        = getattr(expert, "knowledge_base", "")

    researcher_ctx = ""
    critic_ctx     = ""
    try:
        from app.services.knowledge_retriever import build_full_expert_context
        researcher_ctx, critic_ctx = await build_full_expert_context(
            sub_expert_id           = sub_expert_id,
            sub_expert_prompt       = expert_system_prompt,
            sub_expert_critic       = expert_critic_rules,
            disease_name            = disease_name,
            product_desc            = idea[:200],
            domain_static_knowledge = domain_static,
        )
    except Exception as e:
        logger.warning(f"Knowledge retriever failed: {e} — using static knowledge")
        researcher_ctx = expert_system_prompt + "\n\n" + domain_static
        critic_ctx     = expert_critic_rules

    # Moat Widener 2+3: inject FDA history + ClinicalTrials live pipeline
    try:
        from app.services.fda_pipeline import (
            get_full_competitive_intelligence,
            format_competitive_intelligence_for_report
        )
        from app.services.pubmed_service import (
            get_landmark_publications,
            format_publications_for_expert
        )
        disease_keywords = disease_name.replace("(", "").replace(")", "").split()[:4]
        sub_expert_id = getattr(expert, "sub_expert_id", getattr(expert, "domain_id", ""))

        # Run FDA/ClinicalTrials and PubMed in parallel
        ci, pub_data = await asyncio.gather(
            get_full_competitive_intelligence(
                condition=disease_name,
                disease_keywords=disease_keywords,
            ),
            get_landmark_publications(
                disease_name=disease_name,
                sub_expert_id=sub_expert_id,
            ),
            return_exceptions=True
        )

        if not isinstance(ci, Exception):
            ci_context = format_competitive_intelligence_for_report(ci)
            researcher_ctx = researcher_ctx + ci_context
            _competitive_intelligence = ci

        if not isinstance(pub_data, Exception) and pub_data:
            pub_context = format_publications_for_expert(pub_data)
            researcher_ctx = researcher_ctx + pub_context
            logger.info(f"✅ PubMed: {pub_data.get('total_found', 0)} publications loaded for {disease_name}")

    except Exception as e:
        logger.warning(f"Competitive intelligence fetch failed: {e}")
        _competitive_intelligence = {}


    # Build final context with demand signals + hospital matches
    context = _build_expert_context(
        idea, expert, demand_results, hospital_matches_raw,
        disease_knowledge=researcher_ctx,
        pi_memory=pi_memory_context,
    )

    # Use expert system prompt + JSON schema
    # Use static expert system prompt + JSON schema
    system = expert.system_prompt + "\n\n" + EXPERT_JSON_SCHEMA

    raw  = await _call_claude(context, system, max_tokens=6000)
    data = _clean_json(raw)

    # Parse into PIReport
    return _parse_expert_response(data, idea, product_type, expert, demand_results, hospital_matches_raw, total_signals)


def _build_expert_context(idea, expert, demand_results, hospital_matches, disease_knowledge="", pi_memory=""):
    lines = [
        f"PRINCIPAL INVESTIGATOR INNOVATION:\n{idea}",
        "",
    ]
    if pi_memory:
        lines += [pi_memory, ""]
    lines += [
        f"DOMAIN: {expert.display_name}",
        "",
        "DISEASE KNOWLEDGE (use these facts and source URLs):",
        disease_knowledge or expert.knowledge_base,
        "",
        f"DEMAND SIGNALS FROM FEDERAL DATABASES ({len(demand_results)} signals):",
    ]
    for i, s in enumerate(demand_results[:15], 1):
        lines.append(
            f"\nSignal {i} [{s['source']} | {s['signal_type']} | sim={s['similarity_score']:.2f}]"
            f"\nTitle: {s['title']}"
            f"\nDesc: {s['description'][:350]}"
            f"\nMagnitude: {s.get('magnitude')} {s.get('magnitude_unit','')}"
            f"\nGeo: {s.get('geographic_scope')} — {s.get('location_name') or 'National'}"
        )
    if hospital_matches:
        lines.append(f"\nCLINICAL PAIN POINTS ({len(hospital_matches)} matches):")
        for i, n in enumerate(hospital_matches[:5], 1):
            lines.append(
                f"\nNeed {i} [sim={n.similarity_score:.2f} | {n.department} | urgency={n.urgency_score}/5]"
                f"\n{n.raw_text[:300]}"
            )
    lines.append("\nGenerate the full PI intelligence report JSON now. Use your expert knowledge base to ensure accuracy.")
    return "\n".join(lines)


EXPERT_JSON_SCHEMA = """
Generate a biomedical research intelligence report. Return ONLY valid JSON with no markdown fences.

RULES: Every source_url must be a real URL. Use pubmed.ncbi.nlm.nih.gov for papers, fda.gov for regulatory docs, cdc.gov for epidemiology. Keep all string values under 200 characters. No newlines inside string values.

{
  "executive_summary": "<2 sentences, under 300 chars>",
  "disease_intelligence": {
    "condition": "<condition name>",
    "data_points": [{"metric":"<>","value":"<>","year":"<>","source":"<name>","source_url":"<real URL>"}],
    "resistance_profile": "<under 200 chars>",
    "pipeline_status": "<under 200 chars>",
    "unmet_need_summary": "<under 150 chars>"
  },
  "market_sizing": {
    "steps": [{"label":"<>","value":0,"unit":"<>","source":"<name>","source_url":"<real URL>","notes":"<under 100 chars>"}],
    "formula": "<under 150 chars>",
    "total_addressable_market_usd": 0,
    "serviceable_market_usd": 0,
    "methodology_note": "<under 200 chars>"
  },
  "regulatory_pathway": {
    "recommended_pathway": "<under 100 chars>",
    "pathway_rationale": "<under 200 chars>",
    "designations": [{"name":"<>","description":"<under 150 chars>","benefit":"<under 150 chars>","eligibility":"<under 150 chars>","how_to_apply":"<under 150 chars>","timeline":"<under 100 chars>","source":"<name>","source_url":"<real FDA URL>","priority":"<recommended|consider|optional>"}],
    "clinical_trial_requirements": [{"phase":"<Phase 1|2|3>","patient_count":"<range>","duration":"<>","estimated_cost":"<>","key_endpoints":["<under 80 chars>"],"fda_guidance_document":"<name>","source_url":"<real FDA URL>","success_probability":"<>"}],
    "total_timeline_estimate": "<>",
    "total_cost_estimate": "<>",
    "key_friction_points": ["<under 150 chars each, max 3>"],
    "loopholes_and_strategies": ["<under 150 chars each, max 3>"],
    "funding_programs": ["<under 150 chars each, max 3>"]
  },
  "market_access": {
    "primary_channel": "<under 150 chars>",
    "buyer_segments": [{"segment_name":"<>","buyer_count":"<>","decision_maker":"<>","price_per_unit":"<>","annual_spend_per_facility":"<>","access_mechanism":"<under 150 chars>","timeline_to_access":"<>","source":"<name>","source_url":"<URL or empty string>"}],
    "key_opinion_leaders": ["<Name, Institution - under 100 chars>"],
    "reimbursement_pathway": "<under 200 chars>",
    "first_commercial_step": "<under 150 chars>",
    "international_opportunities": ["<under 150 chars each, max 2>"]
  },
  "market_geography": {"description":"<under 200 chars>","top_states":["<state>"],"scope":"<national|regional|concentrated>"},
  "recommended_next_steps": ["<under 150 chars each, max 5>"],
  "limitations": "<under 200 chars>"
}"""


def _parse_expert_response(data, idea, product_type, expert, demand_results, hospital_matches_raw, total_signals):
    """Parse Claude JSON response into PIReport regardless of domain."""
    di_data = data.get("disease_intelligence", {})
    disease_intel = DiseaseIntelligence(
        condition          = di_data.get("condition", ""),
        data_points        = [DiseaseDataPoint(**dp) for dp in di_data.get("data_points", [])],
        resistance_profile = di_data.get("resistance_profile"),
        pipeline_status    = di_data.get("pipeline_status"),
        unmet_need_summary = di_data.get("unmet_need_summary", ""),
    ) if di_data else None

    ms_data = data.get("market_sizing", {})
    market_sizing = MarketSizingCalculation(
        steps                        = [MarketSizingStep(**s) for s in ms_data.get("steps", [])],
        formula                      = ms_data.get("formula", ""),
        total_addressable_market_usd = float(ms_data.get("total_addressable_market_usd", 0)),
        serviceable_market_usd       = float(ms_data.get("serviceable_market_usd", 0)),
        methodology_note             = ms_data.get("methodology_note", ""),
    ) if ms_data else None

    rp_data = data.get("regulatory_pathway", {})
    reg_pathway = RegulatoryPathway(
        recommended_pathway         = rp_data.get("recommended_pathway", ""),
        pathway_rationale           = rp_data.get("pathway_rationale", ""),
        designations                = [RegulatoryDesignation(**d) for d in rp_data.get("designations", [])],
        clinical_trial_requirements = [ClinicalTrialRequirements(**t) for t in rp_data.get("clinical_trial_requirements", [])],
        total_timeline_estimate     = rp_data.get("total_timeline_estimate", ""),
        total_cost_estimate         = rp_data.get("total_cost_estimate", ""),
        key_friction_points         = rp_data.get("key_friction_points", []),
        loopholes_and_strategies    = rp_data.get("loopholes_and_strategies", []),
        funding_programs            = rp_data.get("funding_programs", []),
    ) if rp_data else None

    ma_data = data.get("market_access", {})
    market_access = MarketAccessStrategy(
        primary_channel             = ma_data.get("primary_channel", ""),
        buyer_segments              = [BuyerSegment(**b) for b in ma_data.get("buyer_segments", [])],
        key_opinion_leaders         = ma_data.get("key_opinion_leaders", []),
        reimbursement_pathway       = ma_data.get("reimbursement_pathway", ""),
        first_commercial_step       = ma_data.get("first_commercial_step", ""),
        international_opportunities = ma_data.get("international_opportunities", []),
    ) if ma_data else None

    geo_data = data.get("market_geography", {})

    return PIReport(
        product_type           = product_type,
        idea_submitted         = idea,
        executive_summary      = data.get("executive_summary", ""),
        disease_intelligence   = disease_intel,
        market_sizing          = market_sizing,
        regulatory_pathway     = reg_pathway,
        market_access          = market_access,
        supporting_evidence    = _build_evidence_items(demand_results[:10]),
        hospital_need_matches  = _build_hospital_matches(hospital_matches_raw[:5]),
        market_geography       = MarketGeography(**geo_data) if geo_data else None,
        recommended_next_steps = data.get("recommended_next_steps", []),
        limitations            = data.get("limitations"),
        signals_searched       = total_signals,
        hospital_needs_searched = len(hospital_matches_raw),
        model_version          = "3.0-MoE",
    )


async def _generate_antibiotic_report(
    idea: str,
    demand_results: list,
    hospital_matches_raw: list,
    total_signals: int,
) -> PIReport:
    """Full antibiotic-specific PI report."""

    context = _build_antibiotic_context(idea, demand_results, hospital_matches_raw)
    raw = await _call_claude(context, ANTIBIOTIC_SYSTEM_PROMPT, max_tokens=4000)

    try:
        data = _clean_json(raw)
    except Exception as e:
        logger.error(f"Claude JSON parse failed: {e}\nRaw: {raw[:500]}")
        raise ValueError(f"Failed to parse Claude response: {e}")

    # Build supporting evidence
    evidence = _build_evidence_items(demand_results[:10])
    hospital_needs = _build_hospital_matches(hospital_matches_raw[:5])

    # Parse disease intelligence
    di_data = data.get("disease_intelligence", {})
    disease_intel = DiseaseIntelligence(
        condition=di_data.get("condition", ""),
        data_points=[
            DiseaseDataPoint(**dp) for dp in di_data.get("data_points", [])
        ],
        resistance_profile=di_data.get("resistance_profile"),
        pipeline_status=di_data.get("pipeline_status"),
        unmet_need_summary=di_data.get("unmet_need_summary", ""),
    ) if di_data else None

    # Parse market sizing
    ms_data = data.get("market_sizing", {})
    market_sizing = MarketSizingCalculation(
        steps=[MarketSizingStep(**s) for s in ms_data.get("steps", [])],
        formula=ms_data.get("formula", ""),
        total_addressable_market_usd=float(ms_data.get("total_addressable_market_usd", 0)),
        serviceable_market_usd=float(ms_data.get("serviceable_market_usd", 0)),
        methodology_note=ms_data.get("methodology_note", ""),
    ) if ms_data else None

    # Parse regulatory pathway
    rp_data = data.get("regulatory_pathway", {})
    reg_pathway = None
    if rp_data:
        designations = [RegulatoryDesignation(**d) for d in rp_data.get("designations", [])]
        trial_reqs   = [ClinicalTrialRequirements(**t) for t in rp_data.get("clinical_trial_requirements", [])]
        reg_pathway  = RegulatoryPathway(
            recommended_pathway=rp_data.get("recommended_pathway", ""),
            pathway_rationale=rp_data.get("pathway_rationale", ""),
            designations=designations,
            clinical_trial_requirements=trial_reqs,
            total_timeline_estimate=rp_data.get("total_timeline_estimate", ""),
            total_cost_estimate=rp_data.get("total_cost_estimate", ""),
            key_friction_points=rp_data.get("key_friction_points", []),
            loopholes_and_strategies=rp_data.get("loopholes_and_strategies", []),
            funding_programs=rp_data.get("funding_programs", []),
        )

    # Parse market access
    ma_data = data.get("market_access", {})
    market_access = None
    if ma_data:
        buyer_segs   = [BuyerSegment(**b) for b in ma_data.get("buyer_segments", [])]
        market_access = MarketAccessStrategy(
            primary_channel=ma_data.get("primary_channel", ""),
            buyer_segments=buyer_segs,
            key_opinion_leaders=ma_data.get("key_opinion_leaders", []),
            reimbursement_pathway=ma_data.get("reimbursement_pathway", ""),
            first_commercial_step=ma_data.get("first_commercial_step", ""),
            international_opportunities=ma_data.get("international_opportunities", []),
        )

    # Parse geography
    geo_data = data.get("market_geography", {})
    geography = MarketGeography(
        description=geo_data.get("description", ""),
        top_states=geo_data.get("top_states", []),
        scope=geo_data.get("scope", "national"),
    ) if geo_data else None

    return PIReport(
        product_type=ProductType.ANTIBIOTIC,
        idea_submitted=idea,
        executive_summary=data.get("executive_summary", ""),
        disease_intelligence=disease_intel,
        market_sizing=market_sizing,
        regulatory_pathway=reg_pathway,
        market_access=market_access,
        supporting_evidence=evidence,
        hospital_need_matches=hospital_needs,
        market_geography=geography,
        recommended_next_steps=data.get("recommended_next_steps", []),
        limitations=data.get("limitations"),
        signals_searched=total_signals,
        hospital_needs_searched=len(hospital_matches_raw),
        model_version="2.0",
    )


def _build_antibiotic_context(idea: str, demand_results: list, hospital_matches: list) -> str:
    lines = [
        "PRINCIPAL INVESTIGATOR'S PRODUCT IDEA (Antibiotic):",
        idea,
        "",
        f"DEMAND SIGNALS FROM FEDERAL DATABASES ({len(demand_results)} relevant signals):",
    ]
    for i, s in enumerate(demand_results[:15], 1):
        lines.append(
            f"\nSignal {i} [{s['source']} | {s['signal_type']} | sim={s['similarity_score']:.2f}]"
            f"\nTitle: {s['title']}"
            f"\nDescription: {s['description'][:350]}"
            f"\nMagnitude: {s.get('magnitude')} {s.get('magnitude_unit','')}"
            f"\nGeography: {s.get('geographic_scope')} — {s.get('location_name') or 'National'}"
        )
    if hospital_matches:
        lines.append(f"\nHOSPITAL / CLINICAL PAIN POINTS ({len(hospital_matches)} matches):")
        for i, n in enumerate(hospital_matches[:5], 1):
            lines.append(
                f"\nNeed {i} [sim={n.similarity_score:.2f} | dept={n.department} | urgency={n.urgency_score}/5]"
                f"\n{n.raw_text[:300]}"
            )
    lines.append("\nGenerate the full PI intelligence report JSON now.")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# GENERIC PI REPORT (non-antibiotic)
# ══════════════════════════════════════════════════════════════════════════════

GENERIC_PI_SYSTEM_PROMPT = """You are a go-to-market intelligence engine for principal investigators (PIs) developing healthcare products.

Generate a source-cited intelligence report. Every data point must show its source. No opaque 0-100 scores — use transparent bottom-up calculations.

Respond with ONLY this JSON schema:
{
  "executive_summary": "<2-3 sentences with specific numbers and sources>",
  "disease_intelligence": {
    "condition": "<primary condition>",
    "data_points": [
      {"metric": "<>", "value": "<>", "year": "<>", "source": "<>", "source_url": "<or null>"}
    ],
    "unmet_need_summary": "<>"
  },
  "market_sizing": {
    "steps": [
      {"label": "<>", "value": 0, "unit": "<>", "source": "<>", "source_url": "<or null>", "notes": "<or null>"}
    ],
    "formula": "<Addressable patients × Price × Penetration = TAM>",
    "total_addressable_market_usd": 0,
    "serviceable_market_usd": 0,
    "methodology_note": "<>"
  },
  "market_access": {
    "primary_channel": "<>",
    "buyer_segments": [
      {"segment_name":"<>","buyer_count":"<>","decision_maker":"<>","price_per_unit":"<>","annual_spend_per_facility":"<>","access_mechanism":"<>","timeline_to_access":"<>","source":"<>"}
    ],
    "key_opinion_leaders": ["<>"],
    "reimbursement_pathway": "<>",
    "first_commercial_step": "<>",
    "international_opportunities": ["<>"]
  },
  "market_geography": {
    "description": "<>",
    "top_states": ["<>"],
    "scope": "<national|regional|concentrated>"
  },
  "recommended_next_steps": ["<step with timeline>"],
  "limitations": "<>"
}"""


async def _generate_generic_pi_report(
    idea: str,
    product_type: ProductType,
    demand_results: list,
    hospital_matches_raw: list,
    total_signals: int,
) -> PIReport:
    context = _build_legacy_context(idea, demand_results, hospital_matches_raw)
    raw  = await _call_claude(context, GENERIC_PI_SYSTEM_PROMPT, max_tokens=3000)
    data = _clean_json(raw)

    di_data = data.get("disease_intelligence", {})
    disease_intel = DiseaseIntelligence(
        condition=di_data.get("condition", ""),
        data_points=[DiseaseDataPoint(**dp) for dp in di_data.get("data_points", [])],
        unmet_need_summary=di_data.get("unmet_need_summary", ""),
    ) if di_data else None

    ms_data = data.get("market_sizing", {})
    market_sizing = MarketSizingCalculation(
        steps=[MarketSizingStep(**s) for s in ms_data.get("steps", [])],
        formula=ms_data.get("formula", ""),
        total_addressable_market_usd=float(ms_data.get("total_addressable_market_usd", 0)),
        serviceable_market_usd=float(ms_data.get("serviceable_market_usd", 0)),
        methodology_note=ms_data.get("methodology_note", ""),
    ) if ms_data else None

    ma_data = data.get("market_access", {})
    market_access = MarketAccessStrategy(
        primary_channel=ma_data.get("primary_channel", ""),
        buyer_segments=[BuyerSegment(**b) for b in ma_data.get("buyer_segments", [])],
        key_opinion_leaders=ma_data.get("key_opinion_leaders", []),
        reimbursement_pathway=ma_data.get("reimbursement_pathway", ""),
        first_commercial_step=ma_data.get("first_commercial_step", ""),
        international_opportunities=ma_data.get("international_opportunities", []),
    ) if ma_data else None

    geo_data = data.get("market_geography", {})
    geography = MarketGeography(**geo_data) if geo_data else None

    return PIReport(
        product_type=product_type,
        idea_submitted=idea,
        executive_summary=data.get("executive_summary", ""),
        disease_intelligence=disease_intel,
        market_sizing=market_sizing,
        market_access=market_access,
        supporting_evidence=_build_evidence_items(demand_results[:10]),
        hospital_need_matches=_build_hospital_matches(hospital_matches_raw[:5]),
        market_geography=geography,
        recommended_next_steps=data.get("recommended_next_steps", []),
        limitations=data.get("limitations"),
        signals_searched=total_signals,
        hospital_needs_searched=len(hospital_matches_raw),
        model_version="2.0",
    )


# ══════════════════════════════════════════════════════════════════════════════
# LEGACY ALIGNMENT (backward compat)
# ══════════════════════════════════════════════════════════════════════════════

LEGACY_SYSTEM_PROMPT = """You are the demand intelligence engine for Project Elevate.

Given an inventor's idea and evidence from public health databases, generate a structured demand alignment report.

SCORING RUBRIC:
clinical_demand (0-100): 90-100 multiple federal datasets confirm high burden; 70-89 strong 2+ sources; 50-69 moderate; 30-49 limited; 0-29 weak
market_size (0-100): 90-100 10M+ Americans, national, active trials; 70-89 1-10M, Phase 3; 50-69 100k-1M regional; 30-49 <100k; 0-29 unclear
competition_gap (0-100): 90-100 Class I recalls + high adverse events; 70-89 significant failures; 50-69 moderate; 30-49 mostly adequate; 0-29 well-served
overall = (clinical_demand * 0.40) + (market_size * 0.35) + (competition_gap * 0.25)

Respond ONLY with JSON:
{
  "scores": {"clinical_demand": 0, "market_size": 0, "competition_gap": 0, "overall": 0},
  "executive_summary": "",
  "clinical_demand_narrative": "",
  "market_opportunity_narrative": "",
  "competition_gap_narrative": "",
  "innovation_category": "SOFTWARE|HARDWARE|SERVICE|PHARMACEUTICALS|HYBRID",
  "related_conditions": [],
  "market_geography": {"description": "", "top_states": [], "scope": "national"},
  "recommended_next_steps": [],
  "limitations": ""
}"""


def _build_legacy_context(idea: str, demand_results: list, hospital_matches: list) -> str:
    lines = [f"INVENTOR'S IDEA:\n{idea}", "",
             f"DEMAND SIGNALS ({len(demand_results)} found):"]
    for i, s in enumerate(demand_results[:15], 1):
        lines.append(
            f"\nSignal {i} [{s['source']} | {s['signal_type']} | sim={s['similarity_score']:.2f}]"
            f"\nTitle: {s['title']}\nDesc: {s['description'][:350]}"
            f"\nMagnitude: {s.get('magnitude')} {s.get('magnitude_unit','')}"
            f"\nGeo: {s.get('geographic_scope')} — {s.get('location_name') or 'National'}"
        )
    if hospital_matches:
        lines.append(f"\nHOSPITAL NEEDS ({len(hospital_matches)}):")
        for i, n in enumerate(hospital_matches[:5], 1):
            lines.append(f"\nNeed {i} [sim={n.similarity_score:.2f}]\n{n.raw_text[:300]}")
    lines.append("\nGenerate the alignment report JSON now.")
    return "\n".join(lines)


def _parse_legacy_response(claude_response, idea, demand_results, hospital_matches_raw,
                            total_signals, hospital_needs_count) -> AlignmentReport:
    data   = _clean_json(claude_response)
    sd     = data["scores"]
    scores = DemandScores(
        clinical_demand=sd["clinical_demand"], market_size=sd["market_size"],
        competition_gap=sd["competition_gap"], overall=sd["overall"])

    evidence = _build_evidence_items(demand_results[:10])
    h_needs  = _build_hospital_matches(hospital_matches_raw[:5])
    geo_d    = data.get("market_geography", {})
    geography = MarketGeography(**geo_d) if geo_d else None

    return AlignmentReport(
        scores=scores,
        executive_summary=data["executive_summary"],
        clinical_demand_narrative=data["clinical_demand_narrative"],
        market_opportunity_narrative=data["market_opportunity_narrative"],
        competition_gap_narrative=data["competition_gap_narrative"],
        supporting_evidence=evidence,
        hospital_need_matches=h_needs,
        market_geography=geography,
        innovation_category=data.get("innovation_category"),
        related_conditions=data.get("related_conditions", []),
        recommended_next_steps=data.get("recommended_next_steps", []),
        limitations=data.get("limitations"),
        idea_submitted=idea,
        signals_searched=total_signals,
        hospital_needs_searched=hospital_needs_count,
        model_version="1.0",
    )


# ══════════════════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════════════

SOURCE_URLS = {
    "fda_adverse_events":    "https://open.fda.gov/apis/drug/event/",
    "fda_device_events":     "https://open.fda.gov/apis/device/event/",
    "fda_recalls":           "https://open.fda.gov/apis/drug/enforcement/",
    "clinical_trials":       "https://clinicaltrials.gov/",
    "cdc_places":            "https://www.cdc.gov/places/",
    "census_sahie":          "https://www.census.gov/data/datasets/time-series/demo/sahie/",
    "cms_hospital_quality":  "https://www.medicare.gov/care-compare/",
    "hrsa_shortage":         "https://data.hrsa.gov/tools/shortage-area/hpsa-find",
    "cdc_wastewater":        "https://www.cdc.gov/nwss/",
    "cdc_fluview":           "https://www.cdc.gov/flu/weekly/",
}

SOURCE_EXPLANATIONS = {
    "fda_adverse_events":   "FDA FAERS safety data — existing drug solutions failing patients",
    "fda_device_events":    "FDA MAUDE device malfunction data — existing hardware inadequate",
    "fda_recalls":          "Active FDA Class I recall — strongest signal replacement is needed",
    "clinical_trials":      "Active trial pipeline — validated commercial and research investment",
    "cdc_places":           "County-level disease burden — geographic demand concentration",
    "census_sahie":         "Uninsured population — underserved markets with access gaps",
    "cms_hospital_quality": "Hospital quality deficit — where improvement technology is needed",
    "hrsa_shortage":        "Federal provider shortage designation — regulatory gap validation",
    "cdc_wastewater":       "Real-time surveillance — near-term demand surge signal",
    "cdc_fluview":          "Weekly respiratory illness — seasonal demand pattern",
}


def _build_evidence_items(demand_results: list) -> list:
    items = []
    for s in demand_results:
        items.append(EvidenceItem(
            source=s["source"],
            signal_type=s["signal_type"],
            title=s["title"],
            relevance_explanation=SOURCE_EXPLANATIONS.get(
                s.get("source", ""), "Relevant public health demand signal"),
            magnitude=s.get("magnitude"),
            magnitude_unit=s.get("magnitude_unit"),
            location=s.get("location_name") or s.get("state_code"),
            similarity_score=s["similarity_score"],
            source_url=SOURCE_URLS.get(s.get("source", "")),
        ))
    return items


def _build_hospital_matches(hospital_matches_raw: list) -> list:
    items = []
    for n in hospital_matches_raw:
        items.append(HospitalNeedMatch(
            need_id=n.id,
            raw_text=n.raw_text,
            department=n.department,
            category=n.category,
            urgency_score=n.urgency_score,
            patient_impact_score=n.patient_impact_score,
            similarity_score=n.similarity_score,
            source_platform=getattr(n, "source_platform", "direct_submission"),
            subreddit=getattr(n, "subreddit", None),
        ))
    return items


async def _call_claude(context: str, system_prompt: str, max_tokens: int = 2000) -> str:
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY") or settings.ANTHROPIC_API_KEY
    if not anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in Railway environment variables")
    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": [{"role": "user", "content": context}],
            }
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"]


def _clean_json(raw: str) -> dict:
    clean = raw.strip()
    # Strip markdown code fences
    if clean.startswith("```"):
        parts = clean.split("```")
        clean = parts[1] if len(parts) > 1 else clean
        if clean.startswith("json"):
            clean = clean[4:]
    clean = clean.strip()
    # Try direct parse first
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    # Replace smart quotes and problematic characters
    clean = clean.replace('‘', "'").replace('’', "'")
    clean = clean.replace('“', '"').replace('”', '"')
    clean = clean.replace('–', '-').replace('—', '-')
    clean = clean.replace(' ', ' ')
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    # Try removing literature_citations if it's causing parse issues
    import re
    try:
        clean_no_lit = re.sub(r',?\s*"literature_citations"\s*:\s*\[.*?\]', '', clean, flags=re.DOTALL)
        return json.loads(clean_no_lit)
    except json.JSONDecodeError:
        pass
    # Last resort: find JSON boundaries
    start = clean.find('{')
    end   = clean.rfind('}') + 1
    if start >= 0 and end > start:
        try:
            return json.loads(clean[start:end])
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse failed after cleanup: {e}")
            raise
    raise ValueError(f"No valid JSON found in response: {clean[:200]}")
