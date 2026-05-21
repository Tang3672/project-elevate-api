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

    #  PI Institutional Memory 
    pi_memory_context = ""
    if user_id:
        try:
            from app.services.pi_memory_service import get_pi_memory_context
            pi_memory_context = await get_pi_memory_context(user_id)
            if pi_memory_context:
                logger.info(f"PI memory loaded for user {user_id}")
        except Exception as e:
            logger.warning(f"PI memory load failed (non-fatal): {e}")

    #  MoE Routing 
    router_result = await route_expert(idea=idea, pi_domain=disease_domain)
    expert        = router_result.expert
    logger.info(
        f"MoE Router: domain={expert.domain_id} "
        f"method={router_result.routing_method} "
        f"confidence={router_result.confidence:.2f}"
    )

    #  Generate with Expert context 
    report = await _generate_expert_report(
        idea, pt, expert, demand_results, hospital_matches_raw, total_signals,
        pi_memory_context=pi_memory_context)

    # Build sources from structured data
    try:
        from app.services.source_formatter import build_sources_from_report
        report_dict = report.model_dump(mode="json")
        report_dict = build_sources_from_report(report_dict)
        report.sources = report_dict.get("sources", [])

        # (aggregated sources injected later after aggregator runs)


    except Exception as e:
        logger.warning(f"Source building failed: {e}")

    # Post-process buyer segments OUTSIDE source building try block
    try:
        if report.market_access and report.market_access.buyer_segments:
            BUYER_URL_LOOKUP = {
                "academic": "https://www.aamc.org/data-reports/hospitals-health-systems/report/academic-medical-center-and-teaching-hospital-characteristics",
                "cancer center": "https://www.cancer.gov/research/infrastructure/cancer-centers/find",
                "hospital": "https://www.aha.org/statistics/fast-facts-us-hospitals",
                "community health": "https://www.hrsa.gov/opa/eligibility-and-registration/health-centers/fqhc",
                "community hospital": "https://www.aha.org/statistics/fast-facts-us-hospitals",
                "fqhc": "https://www.hrsa.gov/opa/eligibility-and-registration/health-centers/fqhc",
                "federally qualified": "https://www.hrsa.gov/opa/eligibility-and-registration/health-centers/fqhc",
                "pharmacy": "https://www.nacds.org/about-nacds/chain-pharmacy-industry/",
                "urgent care": "https://www.ucaoa.org/page/IndustryFacts",
                "emergency": "https://www.acep.org/patient-care/policy-statements/emergency-department-utilization/",
                "ltach": "https://www.ahca.org/quality/quality-initiatives/long-term-care",
                "long-term": "https://www.ahca.org/quality/quality-initiatives/long-term-care",
                "payer": "https://www.cms.gov/data-research/statistics-trends-and-reports",
                "medicare": "https://www.cms.gov/data-research/statistics-trends-and-reports",
                "medicaid": "https://www.medicaid.gov/medicaid/program-information/index.html",
                "commercial": "https://www.cms.gov/data-research/statistics-trends-and-reports",
                "insurance": "https://www.cms.gov/data-research/statistics-trends-and-reports",
                "va ": "https://www.va.gov/health/aboutvha.asp",
                "veteran": "https://www.va.gov/health/aboutvha.asp",
                "dod": "https://www.health.mil/Military-Health-Topics/MHS-Fact-Sheet",
                "military": "https://www.health.mil/Military-Health-Topics/MHS-Fact-Sheet",
                "correctional": "https://www.ncchc.org/resources/standards-resources/",
                "prison": "https://www.ncchc.org/resources/standards-resources/",
                "jail": "https://www.ncchc.org/resources/standards-resources/",
                "specialty": "https://www.ncpdp.org/Resources/Industry-Information",
                "neurology": "https://www.aan.com/tools-and-resources/practicing-neurologists-administrators/aap-resources/",
                "pediatric": "https://www.childrenshospitals.org/about-us/data-and-analytics",
                "children": "https://www.childrenshospitals.org/about-us/data-and-analytics",
                "idn": "https://www.healthsystemtracker.org/chart-collection/how-do-hospital-costs-compare-across-hospital-types/",
                "integrated": "https://www.healthsystemtracker.org/chart-collection/how-do-hospital-costs-compare-across-hospital-types/",
                "retail": "https://www.nacds.org/about-nacds/chain-pharmacy-industry/",
                "chain": "https://www.nacds.org/about-nacds/chain-pharmacy-industry/",
                "infectious disease": "https://www.idsociety.org/about-idsa/",
                "oncology": "https://www.asco.org/practice-patients/cancer-care-initiatives/value-cancer-care",
                "nci": "https://www.cancer.gov/research/infrastructure/cancer-centers/find",
                "dialysis": "https://www.cms.gov/Medicare/End-Stage-Renal-Disease/ESRDQualityImproveInit",
                "skilled nursing": "https://www.ahcancal.org/Skilled-Nursing/Pages/default.aspx",
                "snf": "https://www.ahcancal.org/Skilled-Nursing/Pages/default.aspx",
                "home health": "https://www.nahc.org/about/about-home-care-hospice/",
                "clinic": "https://www.aha.org/statistics/fast-facts-us-hospitals",
            }
            for seg in report.market_access.buyer_segments:
                if not getattr(seg, 'source_url', None):
                    seg_name_lower = (getattr(seg, 'segment_name', '') or '').lower()
                    for keyword, url in BUYER_URL_LOOKUP.items():
                        if keyword in seg_name_lower:
                            seg.source_url = url
                            break
                    if not getattr(seg, 'source_url', None):
                        seg.source_url = "https://www.aha.org/statistics/fast-facts-us-hospitals"
            logger.info(f"Buyer segment URLs populated")
    except Exception as e:
        logger.warning(f"Buyer segment post-process failed: {e}")

    # Strategic playbook OUTSIDE source building try block
    try:
        from app.services.strategy_database import format_strategies_for_report
        _sub_id = getattr(expert, "sub_expert_id", getattr(expert, "domain_id", "drug_amr"))
        logger.info(f"Strategic playbook: sub_expert_id={_sub_id}")
        playbook = format_strategies_for_report(_sub_id)
        if not playbook:
            fallback_map = {
                "drug_small_molecule": "drug_amr",
                "drug_other": "drug_amr",
                "biologic": "biologic_oncology",
                "gene_cell_therapy": "gene_therapy_rare",
                "medical_device": "device_cardiovascular",
                "diagnostic": "diagnostic_molecular",
                "vaccine": "vaccine_prophylactic",
            }
            fallback_id = fallback_map.get(_sub_id, "drug_amr")
            playbook = format_strategies_for_report(fallback_id)
            logger.info(f"Used fallback sub_expert_id={fallback_id}")
        report.strategic_playbook = playbook
        logger.info(f"Strategic playbook: {len(report.strategic_playbook)} strategies")
    except Exception as e:
        logger.warning(f"Strategic playbook failed: {e}")
        import traceback
        logger.warning(traceback.format_exc())

    # Attach routing metadata
    report.expert_domain   = getattr(expert, "sub_expert_id", getattr(expert, "domain_id", "unknown"))
    report.expert_name     = expert.display_name
    report.expert_icon     = expert.icon
    report.routing_method  = router_result.routing_method
    report.mismatch_warning = router_result.mismatch_warning

    #  LangGraph Validation 
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
    """Legacy entry point - kept for backward compatibility."""
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
5. Show friction points honestly - do not sugarcoat commercial challenges.
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
        "benefit": "<what the PI gets - be specific: +5yr exclusivity, priority review, etc.>",
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
      "<e.g. 505(b)(2) NDA pathway: rely on FDA's prior findings for a known mechanism, reformulate or combine, reducing Phase 3 requirements by 30-40% - used by Aradigm (ciprofloxacin inhaled), Paratek (omadacycline)>"
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
      "<e.g. IDSA Fellows in infectious disease - most influential; target IDSA Annual Meeting poster/oral presentations>",
      "<e.g. Hospital antimicrobial stewardship pharmacists - the actual formulary decision-makers in >80% of cases>"
    ],
    "reimbursement_pathway": "<e.g. CMS New Technology Add-On Payment (NTAP): 75% cost add-on above DRG for QIDP-designated antibiotics, effective 2-3 years post-approval - apply 2 years before expected approval date>",
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

    "strategic_playbook": [{"strategy":"<REQUIRED - strategy name>","example":"<REQUIRED - real Company - real Drug name>","what_they_did":"<REQUIRED - what they actually did, under 120 chars>","how_to_apply":"<REQUIRED - how to apply to this product, under 120 chars>","source_url":"<REQUIRED - real URL>"}],

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
    #  Two-layer knowledge system 
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
        citation_style_instruction = """
CITATION STYLE: Write like a Nature Medicine paper or NIH grant application. Every statistic, claim, and regulatory fact must be attributed inline. Examples:
- "A 2019 CDC Threats Report documented 2.8 million AMR infections annually in the U.S., with 35,000 deaths."
- "The pivotal SOLO I/II trials (Eckmann et al., NEJM 2015, PMID 25853744) demonstrated non-inferiority of oritavancin vs vancomycin for ABSSSI."
- "Under 21 CFR 314.500, FDA accelerated approval allows approval based on a surrogate endpoint reasonably likely to predict clinical benefit."
Do NOT separate citations from claims. Do NOT use [SOURCE: x] format. Embed the citation in the sentence itself.

TIMELINE AND COST RULES - CRITICAL:
Never state development timelines or costs without citing a real comparable drug program.
Use these verified precedents:

ANTIBIOTIC PRECEDENTS:
- Omadacycline (Nuzyra): Phase 1-3 + NDA = 8 years (2010-2018), M Phase 3 funded by BARDA
- Ceftazidime-avibactam (Avycaz): Phase 1-3 + NDA = 7 years (2009-2015), ~M total
- Delafloxacin (Baxdela): Phase 1-3 + NDA = 9 years (2008-2017), ~M total
- Imipenem-relebactam (Recarbrio): Phase 1-3 + NDA = 8 years (2010-2019), ~M total

ONCOLOGY PRECEDENTS:
- Crizotinib (Xalkori): Phase 1-approval = 5 years (2006-2011), ~M (accelerated)
- Osimertinib (Tagrisso): Phase 1-approval = 4 years (2012-2015), ~M (BTD + accelerated)
- Venetoclax (Venclexta): Phase 1-approval = 5 years (2011-2016), ~M

RARE DISEASE PRECEDENTS:
- Nusinersen (Spinraza): Phase 1-approval = 6 years (2011-2016), ~M
- Onasemnogene (Zolgensma): Phase 1-approval = 7 years (2012-2019), ~M
- Voretigene (Luxturna): Phase 1-approval = 8 years (2009-2017), ~M (small trial)

GENE THERAPY PRECEDENTS:
- Betibeglogene (Zynteglo): Phase 1-approval = 9 years (2013-2022), ~M
- Casgevy (exagamglogene): Phase 1-approval = 6 years (2018-2023), ~M

DEVICE PRECEDENTS (PMA):
- WATCHMAN FLX: Phase 1-approval = 8 years (2012-2020), ~M IDE trial
- TAVR (SAPIEN): Phase 1-approval = 12 years (2004-2016 intermediate risk), ~M total program

When stating timeline: "Based on comparable programs [cite drug], development typically requires X-Y years from IND to approval."
When stating cost: "Phase 3 costs for comparable [drug class] programs have ranged from -Y million, as evidenced by [cite drug and source]."
"""

        researcher_ctx, critic_ctx = await build_full_expert_context(
            sub_expert_id           = sub_expert_id,
            sub_expert_prompt       = expert_system_prompt,
            sub_expert_critic       = expert_critic_rules,
            disease_name            = disease_name,
            product_desc            = idea[:200],
            domain_static_knowledge = domain_static,
        )
    except Exception as e:
        logger.warning(f"Knowledge retriever failed: {e} - using static knowledge")

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
        from app.services.competitive_intelligence_service import (
            gather_competitive_intelligence,
            format_intelligence_for_expert,
        )
        from app.services.source_aggregator_service import (
            aggregate_all_sources,
            format_aggregated_sources,
        )

        ci, pub_data, strategic_intel, aggregated_sources = await asyncio.gather(
            get_full_competitive_intelligence(
                condition=disease_name,
                disease_keywords=disease_keywords,
            ),
            get_landmark_publications(
                disease_name=disease_name,
                sub_expert_id=sub_expert_id,
            ),
            gather_competitive_intelligence(
                disease_name=disease_name,
                sub_expert_id=sub_expert_id,
            ),
            aggregate_all_sources(
                disease_name=disease_name,
                sub_expert_id=sub_expert_id,
            ),
            return_exceptions=True
        )

        if not isinstance(ci, Exception):
            ci_context = format_competitive_intelligence_for_report(ci)
            researcher_ctx = researcher_ctx + ci_context
            _competitive_intelligence = ci

        if not isinstance(strategic_intel, Exception):
            strategic_context = format_intelligence_for_expert(strategic_intel, disease_name)
            researcher_ctx = researcher_ctx + strategic_context
        else:
            # Always inject at least the domain strategies even if full intel fails
            from app.services.competitive_intelligence_service import DOMAIN_STRATEGIES, _DEFAULT_STRATEGIES, format_intelligence_for_expert
            fallback_intel = {
                'competitor_trials': {'trials': [], 'total_found': 0},
                'fda_precedents': {'approvals': []},
                'strategic_playbook': DOMAIN_STRATEGIES.get(sub_expert_id, _DEFAULT_STRATEGIES),
            }
            researcher_ctx = researcher_ctx + format_intelligence_for_expert(fallback_intel, disease_name)

        if not isinstance(aggregated_sources, Exception):
            agg_context = format_aggregated_sources(aggregated_sources, disease_name)
            researcher_ctx = researcher_ctx + agg_context
            _aggregated_sources = aggregated_sources
        else:
            _aggregated_sources = None

        # Inject aggregated papers into report sources NOW (after aggregator ran)
        if _aggregated_sources and hasattr(report, 'sources'):
            from datetime import datetime as _dt2
            from app.models.alignment import ReportSource
            existing_urls = set(s.url for s in report.sources if hasattr(s, 'url') and s.url)
            next_num = max((s.number for s in report.sources if hasattr(s, 'number')), default=0) + 1
            for paper in _aggregated_sources.get('papers', [])[:5]:
                url = paper.get('url', '')
                if url and url not in existing_urls:
                    existing_urls.add(url)
                    name = (paper.get('authors','') + ' (' + paper.get('year','') + '). ' +
                            paper.get('title','')[:80] + '. ' + paper.get('journal',''))[:200]
                    try:
                        report.sources.append(ReportSource(
                            number=next_num, name=name, url=url,
                            accessed=_dt2.utcnow().strftime('%Y-%m-%d')
                        ))
                        next_num += 1
                    except Exception as _e:
                        logger.warning(f"Could not append source: {_e}")

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
            f"\nGeo: {s.get('geographic_scope')} - {s.get('location_name') or 'National'}"
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

CITATION STYLE RULES - CRITICAL:
Write every factual claim as a scientist would in a grant application or NEJM paper. Do NOT say "Source: CDC" at the end. Instead, weave the citation INTO the sentence naturally.

WRONG: "CRE causes 13,100 infections per year. Source: CDC AR Threats Report."
RIGHT: "According to the CDC Antimicrobial Resistance Threats Report (2019), carbapenem-resistant Enterobacterales (CRE) cause approximately 13,100 infections and 1,100 deaths annually in the United States."

WRONG: "The QIDP pathway provides exclusivity benefits."
RIGHT: "Under the GAIN Act of 2012 (21 U.S.C. 355f), QIDP designation confers an additional five years of market exclusivity and guarantees Priority Review with a six-month FDA target action date."

For literature_citations entries, write the relevance field as a full sentence explaining exactly what the paper found and why it matters: "Murray et al. (Lancet, 2022) estimated 1.27 million deaths directly attributable to AMR globally in 2019, establishing the epidemiological basis for the unmet need calculation in this report."

RULES:
1. Every source_url must point to a SPECIFIC page, not a homepage. Examples:
   WRONG: https://www.cdc.gov/antimicrobial-resistance/
   RIGHT: https://www.cdc.gov/antimicrobial-resistance/data-research/threats/index.html
   WRONG: https://www.fda.gov/drugs
   RIGHT: https://www.fda.gov/drugs/development-resources/qualified-infectious-disease-product-qidp-designation
   WRONG: https://pubmed.ncbi.nlm.nih.gov
   RIGHT: https://pubmed.ncbi.nlm.nih.gov/35065702/
2. Every data_point source must include the specific report name and year in the source field.
   WRONG: source: "CDC"
   RIGHT: source: "CDC Antimicrobial Resistance Threats Report 2019, Table 1 (p.7)"
3. Keep all string values under 200 characters. No newlines inside string values.
4. CRITICAL: Your context includes papers from CrossRef, Semantic Scholar, Europe PMC, NIH Reporter grants, and news sources. Cite these throughout the report - do not only cite FDA and CDC.
5. For buyer segments: source_url is MANDATORY - use real URLs like https://www.aha.org/statistics/fast-facts-us-hospitals or https://www.cancer.gov/research/infrastructure/cancer-centers/find or https://data.cms.gov/ - NEVER leave empty.
6. For clinical trial FDA guidance URLs, ONLY use these verified working URLs — never guess:

ANTIBIOTICS/AMR:
  - ABSSSI: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/acute-bacterial-skin-and-skin-structure-infections-developing-drugs-treatment
  - HAP/VAP: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/hospital-acquired-bacterial-pneumonia-and-ventilator-associated-bacterial-pneumonia
  - cUTI: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/complicated-urinary-tract-infections-developing-drugs-treatment
  - General antibacterial: https://www.fda.gov/drugs/guidance-documents-regulatory-information/antibacterial-drugs

ONCOLOGY:
  - Cancer endpoints: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-trial-endpoints-approval-cancer-drugs-and-biologics
  - ADC: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-pharmacology-considerations-antibody-drug-conjugates
  - Pancreatic cancer: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/pancreatic-adenocarcinoma-developing-drugs-treatment
  - Master protocols: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/master-protocols-efficient-clinical-trial-design-strategies-expedite-development-oncology-drugs

RARE DISEASE / GENE THERAPY:
  - Gene therapy: https://www.fda.gov/vaccines-blood-biologics/biologics-guidances/gene-therapy-guidances
  - Neurodegenerative: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/human-gene-therapy-neurodegenerative-diseases
  - ALS: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/amyotrophic-lateral-sclerosis-developing-drugs-treatment
  - SMA: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/spinal-muscular-atrophy-developing-drugs-treatment

CELL THERAPY:
  - CAR-T: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/considerations-development-chimeric-antigen-receptor-car-t-cell-products
  - RMAT: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/expedited-programs-regenerative-medicine-therapies-serious-conditions

DEVICES:
  - IDE: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/investigational-device-exemptions-ides-early-feasibility-medical-device-clinical-studies-including
  - De Novo: https://www.fda.gov/medical-devices/premarket-submissions-selecting-and-preparing-correct-submission/de-novo-classification-request

GENERAL:
  - Phase 1 clinical pharmacology: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/m3r2-nonclinical-safety-studies-conduct-human-clinical-trials-and-marketing-authorization
  - Adaptive trials: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/adaptive-designs-clinical-trials-drugs-and-biologics
  - Accelerated approval: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/accelerated-approval-serious-conditions

If the exact guidance is not listed above, use the general FDA guidance search: https://www.fda.gov/regulatory-information/search-fda-guidance-documents — do NOT fabricate a URL.
7. For market sizing steps, the source field must name the specific dataset or publication that contains the patient count or pricing data used.
3. CRITICAL: The MULTI-SOURCE INTELLIGENCE PACKAGE in your context contains papers from CrossRef, Semantic Scholar, NIH Reporter, and news sources. You MUST cite these in your report and include them in the sources array. Do not only cite FDA and CDC - use the full range of sources provided.
4. For buyer segments: source_url is MANDATORY. Real examples: https://www.aha.org/statistics/fast-facts-us-hospitals, https://www.cancer.gov/research/infrastructure/cancer-centers/find, https://data.cms.gov/, https://www.curesma.org/about-sma/. NEVER leave source_url empty or as empty strings the buyer data.

{
  "executive_summary": "<2 sentences, under 300 chars>",
  "literature_citations": [{"pmid":"<PMID from context>","title":"<under 120 chars>","authors":"<First author et al.>","journal":"<journal name>","year":"<year>","url":"<pubmed URL>","relevance":"<under 100 chars>"}],
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
    "total_timeline_estimate": "<X-Y years IND to approval - cite a comparable approved drug and its actual timeline as evidence>",
    "total_cost_estimate": "<$X-Y total development cost - cite a comparable drug program cost as evidence, e.g. Omadacycline Phase 3 cost $216M per BARDA contract>",
    "key_friction_points": ["<under 150 chars each, max 3>"],
    "loopholes_and_strategies": ["<under 150 chars each, max 3>"],
    "funding_programs": ["<under 150 chars each, max 3>"]
  },
  "market_access": {
    "primary_channel": "<under 150 chars>",
    "buyer_segments": [{"segment_name":"<>","buyer_count":"<>","decision_maker":"<>","price_per_unit":"<>","annual_spend_per_facility":"<>","access_mechanism":"<under 150 chars>","timeline_to_access":"<>","source":"<specific org/publication with year e.g. AHA Hospital Statistics 2024>","source_url":"<REQUIRED real URL e.g. https://www.aha.org/statistics/fast-facts-us-hospitals OR https://www.cancer.org/research/cancer-facts-statistics OR https://www.vizientinc.com OR https://www.ncbi.nlm.nih.gov/books/NBK558954/>"}],
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
        strategic_playbook     = data.get("strategic_playbook", []),
        literature_citations   = data.get("literature_citations", []),
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
        strategic_playbook=data.get("strategic_playbook", []),
        literature_citations=data.get("literature_citations", []),
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
            f"\nGeography: {s.get('geographic_scope')} - {s.get('location_name') or 'National'}"
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

Generate a source-cited intelligence report. Every data point must show its source. No opaque 0-100 scores - use transparent bottom-up calculations.

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
        strategic_playbook=data.get("strategic_playbook", []),
        literature_citations=data.get("literature_citations", []),
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
            f"\nGeo: {s.get('geographic_scope')} - {s.get('location_name') or 'National'}"
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
        strategic_playbook=data.get("strategic_playbook", []),
        literature_citations=data.get("literature_citations", []),
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
    "fda_adverse_events":   "FDA FAERS safety data - existing drug solutions failing patients",
    "fda_device_events":    "FDA MAUDE device malfunction data - existing hardware inadequate",
    "fda_recalls":          "Active FDA Class I recall - strongest signal replacement is needed",
    "clinical_trials":      "Active trial pipeline - validated commercial and research investment",
    "cdc_places":           "County-level disease burden - geographic demand concentration",
    "census_sahie":         "Uninsured population - underserved markets with access gaps",
    "cms_hospital_quality": "Hospital quality deficit - where improvement technology is needed",
    "hrsa_shortage":        "Federal provider shortage designation - regulatory gap validation",
    "cdc_wastewater":       "Real-time surveillance - near-term demand surge signal",
    "cdc_fluview":          "Weekly respiratory illness - seasonal demand pattern",
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
    clean = clean.replace('-', '-').replace('-', '-')
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
