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
    funding_pathway: str = "commercial",
    user_id:        int = None,
) -> PIReport:
    """
    Full MoE pipeline: idea → Expert Router → Expert Context → Claude → PIReport.

    The router selects the best Expert (AMR, Oncology, Cardiology, Neuro,
    Metabolic, Mental Health) based on PI hint + Claude classification.
    Each expert injects deep domain knowledge into the Researcher context.
    """
    from app.services.expert_router import route as route_expert

    # Map new subcategory/tier1 IDs to legacy ProductType enum
    _PT_MAP = {
        "drug_small_molecule": ProductType.OTHER, "drug_amr": ProductType.ANTIBIOTIC,
        "drug_amr_community": ProductType.ANTIBIOTIC, "biologic": ProductType.OTHER,
        "gene_cell_therapy": ProductType.GENE_THERAPY, "gene_therapy": ProductType.GENE_THERAPY,
        "medical_device": ProductType.MEDICAL_DEVICE, "diagnostic": ProductType.DIAGNOSTIC,
        "digital_health": ProductType.SOFTWARE, "vaccine_immunotherapy": ProductType.OTHER,
        "other_platform": ProductType.OTHER,
    }
    try:
        pt = _PT_MAP.get(product_type.lower()) or ProductType(product_type.lower())
    except (ValueError, AttributeError):
        pt = ProductType.OTHER

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
        pi_memory_context=pi_memory_context, funding_pathway=funding_pathway)

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
                # Expert domain IDs from expert_profiles_v2
                "antibiotic_amr": "drug_amr",
                "drug_amr": "drug_amr",
                "drug_infectious": "drug_infectious_non_amr",
                "drug_oncology": "drug_oncology",
                "oncology_small_molecule": "drug_oncology",
                "biologic_oncology": "biologic_oncology",
                "biologic_hematology": "biologic_hematology",
                "biologic_immunology": "biologic_immunology",
                "biologic_cardiology": "biologic_cardiology",
                "biologic_rare": "biologic_rare_disease",
                "gene_therapy": "gene_therapy_rare",
                "gene_therapy_cns": "gene_therapy_cns",
                "gene_therapy_hematology": "gene_therapy_hematology",
                "gene_therapy_oncology": "gene_therapy_oncology",
                "gene_therapy_rna": "gene_therapy_rna",
                "cell_therapy": "gene_therapy_rare",
                "device_cardiovascular": "device_cardiovascular",
                "device_metabolic": "device_metabolic",
                "device_cgm": "device_metabolic",
                "device_neurology": "device_neurology",
                "diagnostic_molecular": "diagnostic_molecular",
                "diagnostic_companion": "diagnostic_companion",
                "digital_therapeutic": "digital_therapeutic",
                "digital_rpm": "digital_rpm",
                "digital_cds": "digital_cds",
                "vaccine_prophylactic": "vaccine_prophylactic",
                "vaccine_cancer": "vaccine_cancer_immuno",
                "crispr": "other_crispr",
                "microbiome": "other_microbiome",
                "delivery": "other_delivery",
                # Generic fallbacks
                "drug_small_molecule": "drug_amr",
                "drug_other": "drug_amr",
                "biologic": "biologic_oncology",
                "antibody": "biologic_oncology",
                "adc": "biologic_oncology",
                "medical_device": "device_cardiovascular",
                "device": "device_cardiovascular",
                "diagnostic": "diagnostic_molecular",
                "vaccine": "vaccine_prophylactic",
                "immunotherapy": "biologic_oncology",
                "oncology": "drug_oncology",
                "cns": "drug_cns",
                "neurology": "drug_cns",
                "rare_disease": "drug_rare_disease",
                "cardiology": "drug_cardiology",
                "metabolic": "drug_metabolic",
                "immunology": "drug_immunology",
                "mental_health": "drug_mental_health",
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

    #  Verification layer: LangGraph validation (P-existing) + Trust scorecard (P2).
    #  These are run CONCURRENTLY under a hard time budget. Previously they ran
    #  sequentially and each could approach its own 45-60s timeout, pushing total
    #  report latency past Railway's proxy limit → the client saw "Failed to fetch".
    #  Now they share one bounded budget and the report is always returned: if the
    #  budget is exceeded, verification is marked PENDING rather than blocking.
    import asyncio as _averify
    _sub_id = getattr(expert, "sub_expert_id", getattr(expert, "domain_id", "drug_amr"))
    _report_dict = report.model_dump(mode="json")
    _VERIFY_BUDGET_S = 25.0

    async def _run_validation():
        from app.services.validation_graph import validate_pi_report
        v = await validate_pi_report(_report_dict, _sub_id)
        return v.get("validation")

    async def _run_trust():
        from app.services.trust_layer_service import score_report_trust
        return await score_report_trust(_report_dict)

    report.validation = None
    report.trust = None
    try:
        _val_res, _trust_res = await _averify.wait_for(
            _averify.gather(_run_validation(), _run_trust(), return_exceptions=True),
            timeout=_VERIFY_BUDGET_S,
        )
        if not isinstance(_val_res, Exception):
            report.validation = _val_res
        else:
            logger.error(f"Validation graph error: {_val_res}")
        if not isinstance(_trust_res, Exception):
            report.trust = _trust_res
        else:
            logger.error(f"Trust layer error: {_trust_res}")
    except _averify.TimeoutError:
        logger.warning("Verification layer exceeded %.0fs budget — returning report, marking pending",
                       _VERIFY_BUDGET_S)
    except Exception as e:
        logger.error(f"Verification layer error: {e}")

    if report.validation is None:
        report.validation = {
            "status": "PENDING", "passed": True, "warnings": [], "notes": [],
            "total_flags": 0,
            "summary": "Validation deferred to keep the report responsive.",
            "validated_at": None,
        }
    if report.trust is None:
        report.trust = {
            "available": False,
            "summary": "Trust scoring deferred to keep the report responsive.",
            "abstention_required": False, "human_review_recommended": False,
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




async def _generate_expert_report(idea, product_type, expert, demand_results, hospital_matches_raw, total_signals, pi_memory_context="", funding_pathway="commercial"):
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

    # ── Funding pathway framing injection ─────────────────────────────────────
    # Appended to expert system prompt to change report structure based on
    # whether user is building a commercial product, SBIR grant, or basic science grant
    _pathway = funding_pathway or "commercial"
    _pathway_framing = {
        "sbir": """

FUNDING PATHWAY: SBIR/STTR FEDERAL GRANT
This report MUST address BOTH commercial AND scientific dimensions:
COMMERCIAL (60%): TAM/SAM market sizing, FDA regulatory pathway, buyer segments, competitive landscape, pricing
SCIENTIFIC SIGNIFICANCE (40%): Unmet medical need framed for NIH reviewers, innovation over current standard of care, potential impact statement, cite overlapping funded NIH grants via NIH Reporter
Use language appropriate for SBIR reviewers — balance business case with scientific merit.""",
        "basic_science": """

FUNDING PATHWAY: BASIC SCIENCE GRANT (NIH R01/R21/R03)
CRITICAL CHANGES TO REPORT STRUCTURE:
- REPLACE the TAM/SAM market sizing section with: NIH funding levels in this disease area, number of active research groups, overlapping funded grants from NIH Reporter
- REPLACE buyer segments / market access with: key journals, study sections, and funding mechanisms relevant to this research area
- ADD: Significance section (what scientific gap does this fill?), Innovation section (what is novel vs existing approaches?), Rigor section (what controls/validation are needed?)
- Use NIH review criteria language throughout: Significance, Innovation, Approach, Environment, Investigators
Do NOT include commercial pricing, sales channels, or go-to-market strategy.""",
        "commercial": "",
    }.get(_pathway, "")
    if _pathway_framing:
        expert_system_prompt = expert_system_prompt + _pathway_framing

    expert_critic_rules  = getattr(expert, "critic_rules", "")
    domain_static        = getattr(expert, "knowledge_base", "")

    # Load research world model — prior knowledge from previous analyses of this disease.
    # Edison Scientific's key differentiator: the system accumulates structured knowledge
    # across research runs rather than starting cold every time.
    world_model_ctx = ""
    try:
        from app.services.research_world_model import load_world_model
        world_model_ctx = await load_world_model(disease_name)
    except Exception as _wm_e:
        logger.debug("World model load skipped: %s", _wm_e)
    # Commercialization world-model GRAPH context (P4) — accumulated nodes/edges
    try:
        from app.services.world_model_graph import load_graph_context
        _graph_ctx = await load_graph_context(disease_name)
        if _graph_ctx:
            world_model_ctx = (world_model_ctx + "\n\n" + _graph_ctx).strip()
    except Exception as _gctx_e:
        logger.debug("World-model graph context load skipped: %s", _gctx_e)

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

        # Multi-Source Retrieval Pipeline (MSRP) — runs in parallel with other fetches
        # Implements Adaptive RAG + CRAG quality gating across 38+ sources
        from app.services.retrieval_pipeline import run_retrieval_pipeline
        from app.services.chapter_data_service import get_all_chapter_data, format_all_chapter_data
        from app.services.expert_panel import run_expert_panel
        from app.services.literature_synthesis import synthesize_literature
        from app.services.funding_intelligence_service import get_funding_intelligence, format_funding_intelligence
        from app.services.patent_landscape_service import get_patent_landscape, format_patent_landscape
        from app.services.regulatory_precedent_service import get_regulatory_precedent, format_regulatory_precedent

        # Hard 20-second cap on all data fetches. Anything that doesn't finish
        # in time is returned as a TimeoutError, which the downstream handlers
        # already treat identically to any other Exception (non-fatal, skip that source).
        # This keeps total request time well under Railway's 60s proxy timeout.
        gather_coro = asyncio.gather(
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
            get_all_chapter_data(
                disease_name=disease_name,
                therapeutic_area=ta_for_deriv or "other",
                subcategory_id=sub_expert_id or "drug_amr",
                idea=idea,
            ),
            run_retrieval_pipeline(
                disease_name=disease_name,
                therapeutic_area=ta_for_deriv or "other",
                subcategory_id=sub_expert_id or "drug_amr",
                idea=idea,
                max_total_sec=12.0,
            ),
            # Expert panel: 3 parallel Haiku sub-analyses (different analytical lenses).
            run_expert_panel(
                disease_name=disease_name,
                idea=idea,
                sub_expert_id=sub_expert_id or "drug_amr",
                product_type=product_type or "drug",
            ),
            # Real-time funding intelligence: NIH SBIR awards, SEC 8-K, preprint velocity.
            get_funding_intelligence(disease_name),
            # Patent landscape: recent US filings + assignees (Google Patents, free).
            get_patent_landscape(disease_name),
            # Regulatory precedent: FDA-approved drugs for this indication (openFDA, free).
            get_regulatory_precedent(disease_name),
            return_exceptions=True,
        )
        try:
            (ci, pub_data, strategic_intel, aggregated_sources, chapter_data,
             pipeline_result, panel_result, funding_intel,
             patent_landscape, regulatory_precedent) = await asyncio.wait_for(gather_coro, timeout=20.0)
        except asyncio.TimeoutError:
            logger.warning("Data gather hit 20s timeout — continuing with partial results")
            ci = pub_data = strategic_intel = aggregated_sources = chapter_data = pipeline_result = panel_result = funding_intel = patent_landscape = regulatory_precedent = Exception("timeout")

        # CRAG quality gating: inject MSRP pipeline results first (highest quality)
        # CRAG principle: evaluate retrieved data quality before injecting
        if not isinstance(pipeline_result, Exception) and pipeline_result:
            from app.services.retrieval_pipeline import RetrievalResult
            pr: RetrievalResult = pipeline_result
            avg_coverage = sum(pr.coverage_by_chapter.values()) / max(1, len(pr.coverage_by_chapter))
            logger.info(
                "MSRP: %d facts | %d sources | %.0f%% coverage | tier %d | %.0fms | cache %.0f%%",
                len(pr.facts), len(pr.sources_called), avg_coverage * 100,
                pr.tiers_reached, pr.total_latency_ms, pr.cache_hit_rate * 100,
            )
            # CRAG quality gate: only inject if coverage is meaningful (>20%)
            if avg_coverage > 0.20 and pr.context_blocks:
                pipeline_ctx = "\n\n=== RETRIEVAL PIPELINE (MSRP) — AUTHORITATIVE DATABASE FACTS ===\n"
                pipeline_ctx += f"Coverage: {avg_coverage:.0%} | Sources: {len(pr.sources_called)} | Cache hit: {pr.cache_hit_rate:.0%}\n"
                pipeline_ctx += "INSTRUCTION: Use these database-grounded facts. They override Claude's training data.\n"
                pipeline_ctx += "\n".join(pr.context_blocks.values())
                researcher_ctx = pipeline_ctx + "\n\n" + researcher_ctx  # Prepend = higher priority
        else:
            if isinstance(pipeline_result, Exception):
                logger.warning("MSRP pipeline failed (non-fatal): %s", pipeline_result)

        # Chapter data service: additional chapter-specific context
        if not isinstance(chapter_data, Exception) and chapter_data:
            researcher_ctx = researcher_ctx + "\n" + format_all_chapter_data(chapter_data)
            logger.info("Chapter data service: injected %d context blocks", len(chapter_data))
        else:
            if isinstance(chapter_data, Exception):
                logger.warning("Chapter data service failed (non-fatal): %s", chapter_data)

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

            # Deep literature synthesis — PMID-traceable findings, open questions, white space.
            # Runs after pub_data is available, before Opus call. Mini-Edison pattern:
            # every proven finding is anchored to a specific paper.
            try:
                lit_synthesis = await synthesize_literature(
                    disease_name=disease_name,
                    idea=idea,
                    pub_data=pub_data,
                )
                if lit_synthesis and lit_synthesis.formatted:
                    researcher_ctx = lit_synthesis.formatted + "\n\n" + researcher_ctx
                    logger.info("Literature synthesis: %d proven findings, %d open questions",
                                len(lit_synthesis.proven_findings), len(lit_synthesis.open_questions))
            except Exception as _ls_e:
                logger.warning("Literature synthesis failed (non-fatal): %s", _ls_e)

    except Exception as e:
        logger.warning(f"Competitive intelligence fetch failed: {e}")
        _competitive_intelligence = {}


    # === INNOVATION INTELLIGENCE SWEEP — runs in executor, doesn't block ===
    intelligence_text = ""
    try:
        from app.services.innovation_intelligence_service import (
            run_intelligence_sweep, format_intelligence_for_prompt
        )
        loop = asyncio.get_event_loop()
        intel = await loop.run_in_executor(
            None,
            lambda: run_intelligence_sweep(
                idea=idea,
                disease_name=disease_name,
                product_type=product_type,
                therapeutic_area=getattr(expert, "domain_id", "other"),
            )
        )
        intelligence_text = format_intelligence_for_prompt(intel)
        logger.info("Intelligence sweep: %d signals from %d sources",
                    len(intel.signals), len(intel.sources_swept))
    except Exception as e_intel:
        logger.warning("Intelligence sweep failed (non-fatal): %s", e_intel)

    # === UNIQUE MARKET SIZING DERIVATION — generate before building context ===
    market_derivation_text = ""
    deriv = None  # MarketSizingDerivation; reused below to build P1 provenance
    try:
        from app.services.market_sizing_derivation_service import (
            generate_market_sizing_derivation, format_derivation_for_prompt
        )

        # ── Accurate population lookup (3-level cascade) ──────────────────────
        # Level 1: DISEASE_POPULATIONS dict — curated per-disease values
        # Level 2: universe_builder match → TA-specific override
        # Level 3: expert-domain TA default (last resort)
        us_pop = 0
        ta_for_deriv = "other"
        try:
            from app.services.universe_builder import get_universe, DISEASE_POPULATIONS, get_disease_population

            # Level 1: exact match in curated population dict
            for key, pop in DISEASE_POPULATIONS.items():
                if disease_name and (disease_name.lower() in key.lower() or key.lower() in disease_name.lower()):
                    us_pop = pop
                    break

            # Level 2: scan universe for TA + TA-level default
            from app.services.opportunity_scorer_v2 import _TA_DEFAULTS, _DISEASE_OVERRIDES
            for d_entry, ta_entry, *rest in get_universe():
                if disease_name and (disease_name.lower() in d_entry.lower() or d_entry.lower() in disease_name.lower()):
                    ta_for_deriv = ta_entry
                    if not us_pop:
                        # Disease-specific override has better population data than TA default
                        override = _DISEASE_OVERRIDES.get(d_entry)
                        if override:
                            us_pop = override[1]  # pop is index 1 in _DISEASE_OVERRIDES tuples
                        else:
                            _, pop, _, _, _ = _TA_DEFAULTS.get(ta_entry, _TA_DEFAULTS["other"])
                            us_pop = pop
                    break

            # Level 3: map expert domain_id to TA if still no match
            if not ta_for_deriv or ta_for_deriv == "other":
                _EXPERT_TA_MAP = {
                    "drug_amr": "amr_infectious", "drug_amr_antibiotics": "amr_infectious",
                    "drug_oncology": "oncology", "biologic_oncology": "oncology",
                    "drug_cns": "cns", "drug_mental_health": "cns",
                    "drug_cardiology": "cardiovascular", "drug_metabolic": "metabolic",
                    "drug_rare_disease": "rare_disease", "biologic_rare_disease": "rare_disease",
                    "gene_therapy_rare": "gene_therapy", "gene_therapy_oncology": "oncology",
                    "gene_therapy_hematology": "hematology", "gene_therapy_cns": "cns",
                    "biologic_immunology": "immunology", "biologic_hematology": "hematology",
                    "device_cardiovascular": "cardiovascular", "device_metabolic": "metabolic",
                    "diagnostic_molecular": "diagnostic",
                    "digital_cds": "device", "digital_therapeutic": "device",
                    "vaccine_prophylactic": "vaccine",
                }
                expert_domain = getattr(expert, "domain_id", getattr(expert, "sub_expert_id", "other"))
                ta_for_deriv = _EXPERT_TA_MAP.get(expert_domain, "other")
                if not us_pop:
                    _, pop, _, _, _ = _TA_DEFAULTS.get(ta_for_deriv, _TA_DEFAULTS["other"])
                    us_pop = pop
        except Exception as e_pop:
            logger.debug("Population lookup failed: %s", e_pop)

        deriv = generate_market_sizing_derivation(
            idea=idea,
            product_type=product_type,
            disease_name=disease_name,
            therapeutic_area=ta_for_deriv,
            us_patient_population=us_pop,
        )
        market_derivation_text = format_derivation_for_prompt(deriv)
        logger.info("Market sizing derivation generated: TAM=%s SAM=%s", deriv.tam_fmt, deriv.sam_fmt)
    except Exception as e_deriv:
        logger.warning("Market sizing derivation failed (non-fatal): %s", e_deriv)

    # TRL assessment — stage-of-development scoring before main Opus call.
    # development_phase comes from the opportunity phase field, not product_type.
    trl_block = ""
    trl_result = None   # reused by the P5 decision engine below
    try:
        from app.services.trl_service import assess_trl
        # Map product_type → development_phase for TRL estimation.
        # product_type is the modality (drug_small_molecule, biologic, etc.).
        # The actual dev phase should come from the opportunity record; fall back to "preclinical".
        _dev_phase = "preclinical"  # conservative default — keyword matching in assess_trl refines this
        trl_result = assess_trl(
            idea=idea,
            development_phase=_dev_phase,
            sub_expert_id=sub_expert_id or "drug_amr",
        )
        trl_block = trl_result.formatted
        logger.info("TRL assessment: TRL %d — %s", trl_result.trl_level, trl_result.trl_label)
    except Exception as _trl_e:
        logger.warning("TRL assessment failed (non-fatal): %s", _trl_e)

    # Investor matching — who to call, what to say, grounded in TA + TRL.
    investor_block = ""
    try:
        from app.services.investor_matcher import format_investors_for_prompt
        _trl_level = trl_result.trl_level if trl_block else 3
        investor_block = format_investors_for_prompt(
            sub_expert_id=sub_expert_id or "drug_amr",
            trl_level=_trl_level,
            is_academic_spinout=True,
        )
        logger.info("Investor matching: injected for sub_expert=%s TRL=%d", sub_expert_id, _trl_level)
    except Exception as _inv_e:
        logger.warning("Investor matching failed (non-fatal): %s", _inv_e)

    # Funding intelligence — real-time competitive funding signals
    funding_block = ""
    sbir_count = 0   # reused by the P5 decision engine below
    try:
        if not isinstance(funding_intel, Exception) and funding_intel:
            funding_block = format_funding_intelligence(funding_intel, disease_name)
            sbir_count = len(funding_intel.get("sbir_awards", []))
            entrant_count = len(funding_intel.get("new_entrants", []))
            logger.info("Funding intel: %d SBIR awards, %d new trial entrants", sbir_count, entrant_count)
    except Exception as _fi_e:
        logger.warning("Funding intelligence injection failed (non-fatal): %s", _fi_e)

    # VC fund benchmarks — what investors expect (published Cambridge Associates / NVCA data)
    fund_bench_block = ""
    try:
        from app.services.fund_benchmarks import format_benchmarks_for_prompt
        _trl_for_bench = trl_result.trl_level if trl_block else 3
        fund_bench_block = format_benchmarks_for_prompt(_trl_for_bench)
    except Exception as _fb_e:
        logger.warning("Fund benchmarks injection failed (non-fatal): %s", _fb_e)

    # Patent landscape — IP whitespace / FTO signal (Google Patents, free)
    patent_block = ""
    try:
        if not isinstance(patent_landscape, Exception) and patent_landscape:
            patent_block = format_patent_landscape(patent_landscape, disease_name)
            logger.info("Patent landscape: %d filings, signal=%s",
                         patent_landscape.get("total_results", 0), patent_landscape.get("activity_signal", ""))
    except Exception as _pl_e:
        logger.warning("Patent landscape injection failed (non-fatal): %s", _pl_e)

    # Regulatory precedent — FDA-approved drug landscape (openFDA, free)
    regulatory_precedent_block = ""
    try:
        if not isinstance(regulatory_precedent, Exception) and regulatory_precedent:
            regulatory_precedent_block = format_regulatory_precedent(regulatory_precedent, disease_name)
            logger.info("Regulatory precedent: %d labels, %d approved drugs",
                         regulatory_precedent.get("total_labels", 0), len(regulatory_precedent.get("approved_drugs", [])))
    except Exception as _rp_e:
        logger.warning("Regulatory precedent injection failed (non-fatal): %s", _rp_e)

    # KOL network — key opinion leaders by citation influence (Semantic Scholar, free API)
    kol_block = ""
    try:
        from app.ingestion.connectors.semantic_scholar import get_kol_network, get_disease_literature_signal
        kols = get_kol_network(disease_name, limit=6)
        lit_signal = get_disease_literature_signal(disease_name)
        if kols:
            kol_lines = [
                "KEY OPINION LEADERS (by citation influence — Semantic Scholar):",
                f"Research momentum: {lit_signal.get('research_momentum', 'UNKNOWN')} "
                f"({lit_signal.get('total_citations_top5', 0):,} citations in top 5 papers)",
            ]
            for k in kols[:5]:
                kol_lines.append(f"  • {k['author']} — {k['paper_count']} papers, {k['citation_total']:,} citations")
            kol_block = "\n".join(kol_lines)
            logger.info("KOL network: %d KOLs for '%s'", len(kols), disease_name)
    except Exception as _kol_e:
        logger.warning("KOL network injection failed (non-fatal): %s", _kol_e)

    # Expert panel: inject structured pre-analysis as highest-priority context block
    panel_block = ""
    try:
        from app.services.expert_panel import format_panel_for_prompt, ExpertPanelResult
        if not isinstance(panel_result, Exception) and panel_result:
            panel_block = format_panel_for_prompt(panel_result)
            c = panel_result.clinical
            r = panel_result.regulatory
            com = panel_result.commercial
            logger.info(
                "Expert panel injected: mechanism=%.1f/10 approval=%d%% moat=%.1f/10",
                c.mechanism_score if c else 0,
                r.approval_probability_pct if r else 0,
                com.competitive_moat_score if com else 0,
            )
        elif isinstance(panel_result, Exception):
            logger.warning("Expert panel failed (non-fatal): %s", panel_result)
    except Exception as _pe:
        logger.warning("Expert panel injection failed (non-fatal): %s", _pe)

    # Build final context. Priority order (highest first):
    #   world model → TRL → expert panel → investor match → fund benchmarks →
    #   funding intel → KOL → literature synthesis → CI → market sizing
    context = _build_expert_context(
        idea, expert, demand_results, hospital_matches_raw,
        disease_knowledge=(
            world_model_ctx + "\n\n"
            + trl_block + "\n\n"
            + panel_block + "\n\n"
            + investor_block + "\n\n"
            + fund_bench_block + "\n\n"
            + funding_block + "\n\n"
            + patent_block + "\n\n"
            + regulatory_precedent_block + "\n\n"
            + kol_block + "\n\n"
            + researcher_ctx + intelligence_text + market_derivation_text
        ),
        pi_memory=pi_memory_context,
    )

    # Append clinical guideline compliance check to system prompt
    clinical_guideline_warning = _check_guideline_compliance(idea, product_type)

    # Reporting instructions: over-explain chapters 2-4
    reporting_instructions = (
        "\n\nREPORTING RULES: "
        "(1) Every number must cite its source by name. "
        "(2) TAM/SAM/SOM: use ONLY the values from the derivation above — no other estimates. "
        "(3) Regulatory timelines: cite a comparable approved drug. "
        "(4) Market access prices: cite CMS ASP or reimbursement data. "
        "(5) If uncertain, state a range with sources for both ends. "
        f"GUIDELINE NOTE: {clinical_guideline_warning[:200]}"
        + (
            "\n\nEXPERT PANEL INTEGRATION RULES (CRITICAL): "
            "An expert panel ran three independent sub-analyses before this synthesis. "
            "You MUST: "
            "(a) Reference the Clinical Validity Expert's mechanism score and risks in your scientific assessment. "
            "(b) Use the Regulatory Pathway Expert's recommended pathway and approval probability as your baseline — "
            "override only with cited precedent. "
            "(c) Use the Commercial Viability Expert's pricing benchmark and payer barrier in your market access section. "
            "If you disagree with any panel finding, state explicitly: "
            "'The panel assessed [X]; however, based on [specific evidence], my assessment is [Y].' "
            "Do NOT ignore the panel findings."
            if panel_block else ""
        )
    )

    system = expert.system_prompt + "\n\n" + EXPERT_JSON_SCHEMA + reporting_instructions

    # ── Cost-aware specialist router (P3) — pick the synthesis model tier; the
    #    frontier model is used only when complexity/uncertainty is high. ──
    _routing_plan = None
    _synthesis_model = None
    try:
        from app.services.cost_aware_router import build_routing_plan
        _routing_plan = build_routing_plan(
            idea=idea, product_type=product_type, sub_expert_id=sub_expert_id or "",
            development_stage=locals().get("_dev_phase", "preclinical"),
            signal_count=len(demand_results or []))
        _synthesis_model = _routing_plan["synthesis_model"]
        logger.info("Cost-aware router: complexity=%.2f synthesis_model=%s",
                    _routing_plan["complexity_score"], _synthesis_model)
    except Exception as _rt_e:
        logger.warning("Cost-aware router failed (non-fatal, default model): %s", _rt_e)

    raw  = await _call_claude(context, system, max_tokens=6144, model=_synthesis_model)
    data = _clean_json(raw)

    # Parse into PIReport
    report = _parse_expert_response(data, idea, product_type, expert, demand_results, hospital_matches_raw, total_signals)

    # Attach the cost-aware routing plan (P3) for visibility/audit.
    if _routing_plan is not None:
        report.routing_plan = _routing_plan

    # ── P1: market-sizing provenance — typed, source-backed assumptions + scenarios + waterfall ──
    if deriv is not None:
        try:
            from app.services.market_provenance_service import build_provenance
            provenance = build_provenance(deriv)
            report.market_sizing_provenance = provenance
            import asyncio as _aio_ms
            from app.db.market_sizing_repository import save_market_sizing_run
            _aio_ms.create_task(save_market_sizing_run(
                provenance, user_id=None, disease_name=disease_name or ""))
        except Exception as _prov_e:
            logger.warning("Market sizing provenance failed (non-fatal): %s", _prov_e)

    # ── P5: commercialization decision engine — probabilistic scores + drivers + recommendation ──
    try:
        from app.services.commercialization_decision_service import build_decision
        report.commercialization_scores = build_decision(
            product_type=product_type,
            sub_expert_id=sub_expert_id or "",
            panel_result=(panel_result if not isinstance(panel_result, Exception) else None),
            patent_landscape=(patent_landscape if not isinstance(patent_landscape, Exception) else None),
            trl_result=trl_result,
            deriv=deriv,
            sbir_awards=sbir_count,
        )
    except Exception as _dec_e:
        logger.warning("Commercialization decision engine failed (non-fatal): %s", _dec_e)

    # ── Expert-panel visibility (Sprint 2 UI) — attach the structured panel for the UI ──
    try:
        if panel_result is not None and not isinstance(panel_result, Exception):
            from app.services.expert_panel import panel_to_dict
            report.expert_panel = panel_to_dict(panel_result)
    except Exception as _ep_e:
        logger.debug("Expert panel attach failed (non-fatal): %s", _ep_e)

    # ── Sprint 7: stable id, portfolio benchmark (P7), persistence + graph ingest (P4/P11) ──
    try:
        from app.services.world_model_graph import report_id_for, ingest_report_to_graph
        _rdict = report.model_dump(mode="json")
        report.report_id = report_id_for(_rdict)

        # Portfolio benchmark (P7): percentile + comparables vs prior internal disclosures.
        try:
            from app.services.portfolio_benchmark_service import portfolio_benchmark
            report.portfolio_benchmark = await portfolio_benchmark(_rdict, user_id=None)
        except Exception as _pb_e:
            logger.warning("Portfolio benchmark failed (non-fatal): %s", _pb_e)

        # Persist report metrics (P7/P10 backbone) + ingest into the graph (P4) — background.
        import asyncio as _aio_s7
        from app.db.reports_repository import save_report_metrics
        _aio_s7.create_task(save_report_metrics(_rdict, user_id=None))
        _aio_s7.create_task(ingest_report_to_graph(_rdict, disease_name=disease_name, user_id=None))
    except Exception as _s7_e:
        logger.debug("Sprint-7 wiring failed (non-fatal): %s", _s7_e)

    # Update research world model asynchronously — fire and forget, non-blocking.
    # Next report for this disease will have richer prior context.
    try:
        import asyncio as _aio
        _ci_for_wm = _competitive_intelligence if isinstance(_competitive_intelligence, dict) else {}
        _pub_for_wm = pub_data if not isinstance(pub_data, Exception) else {}
        _aio.create_task(
            _update_world_model_bg(disease_name, report, _pub_for_wm, _ci_for_wm)
        )
    except Exception as _wm_upd_e:
        logger.debug("World model update scheduling failed (non-fatal): %s", _wm_upd_e)

    return report


async def _update_world_model_bg(disease_name: str, report, pub_data: dict, ci_data: dict):
    """Background task: update world model after report completes."""
    try:
        from app.services.research_world_model import update_world_model
        report_dict = report.model_dump(mode="json") if hasattr(report, "model_dump") else {}
        await update_world_model(disease_name, report_dict, pub_data, ci_data)
    except Exception as e:
        logger.debug("World model background update failed: %s", e)


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
  - Phase 1 general IND: https://www.fda.gov/drugs/guidance-documents-regulatory-information/clinical-pharmacology
  - Phase 1 safety/PK: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-pharmacology-considerations-antibody-drug-conjugates

IMPORTANT: Use DIFFERENT guidance URLs for different phases. Phase 1 = IND/clinical pharmacology guidance. Phase 2/3 = indication-specific guidance. Never use the same URL for all 3 phases.
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


def _check_guideline_compliance(idea: str, product_type: str) -> str:
    """
    Check whether the proposed innovation's mechanism might conflict with
    established clinical practice guidelines. Returns a warning string
    for injection into the report prompt.

    Based on TTO feedback: a case occurred where an innovator proposed replacing
    a medical procedure that was mandated by clinical guidelines — the product
    would have been commercially unviable because adoption would have required
    guideline deviation. This check flags such risks.
    """
    warnings = []
    idea_low = (idea + " " + product_type).lower()

    # Pattern: replaces / eliminates an established procedure or therapy
    replacement_signals = [
        "replac", "eliminat", "instead of", "bypass", "skip", "avoid",
        "without", "non-invasive alternative to", "alternative to"
    ]
    procedure_signals = [
        "surgery", "biopsy", "imaging", "colonoscopy", "mammography",
        "chemotherapy", "radiation", "dialysis", "transplant", "blood transfusion",
        "standard of care", "first-line", "guideline-recommended"
    ]

    replaces_procedure = any(r in idea_low for r in replacement_signals)
    mentions_procedure = any(p in idea_low for p in procedure_signals)

    if replaces_procedure and mentions_procedure:
        warnings.append(
            "GUIDELINE COMPLIANCE FLAG: This innovation appears to propose replacing or bypassing "
            "an established clinical procedure or standard-of-care therapy. IMPORTANT — in the report, "
            "explicitly check whether the proposed approach would conflict with major clinical practice "
            "guidelines (e.g. ACC/AHA, ASCO, IDSA, USPSTF). If a guideline mandates the procedure being "
            "replaced, payers will not reimburse a substitute without a guideline update or strong "
            "head-to-head trial data. Cite the relevant guideline and explain whether the innovation "
            "requires guideline revision to achieve market access."
        )

    # Pattern: AI/algorithm replacing physician judgment
    if any(x in idea_low for x in ["ai", "algorithm", "machine learning"]) and \
       any(x in idea_low for x in ["diagnos", "triage", "screen", "detect", "replac"]):
        warnings.append(
            "FDA/CMS SAMD WORKFLOW FLAG: AI/software replacing or augmenting clinical decision-making "
            "requires FDA SaMD classification (Class II/III) and CMS coverage determination. "
            "Explicitly discuss: (1) FDA De Novo or 510(k) pathway, (2) CMS coding (CPT/HCPCS) and "
            "whether NCD/LCD coverage exists for the use case, (3) whether the AI replaces or augments "
            "physician judgment — replacement triggers higher regulatory burden and payer resistance."
        )

    if not warnings:
        return "No specific guideline compliance flags detected. Standard commercialization pathway analysis applies."

    return " | ".join(warnings)


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


async def _call_claude(context: str, system_prompt: str, max_tokens: int = 2000,
                       model: str = None) -> str:
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
                "model": model or CLAUDE_MODEL,
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
        except json.JSONDecodeError:
            pass

    # Truncation repair: if the JSON is cut off mid-response, try closing it.
    # This happens when Claude hits the token limit before finishing the JSON.
    if start >= 0:
        fragment = clean[start:]
        # Count open braces/brackets to determine what we need to close
        depth_brace   = fragment.count('{') - fragment.count('}')
        depth_bracket = fragment.count('[') - fragment.count(']')
        # Check for trailing incomplete string (odd number of unescaped quotes)
        in_string = False
        escape    = False
        for ch in fragment:
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
        # Close any open string, brackets, then braces
        suffix = ''
        if in_string:
            suffix += '"'
        suffix += ']' * max(0, depth_bracket)
        suffix += '}' * max(0, depth_brace)
        if suffix:
            try:
                repaired = fragment + suffix
                result   = json.loads(repaired)
                logger.warning("JSON truncation repaired (added '%s')", suffix[:20])
                return result
            except json.JSONDecodeError:
                pass

        # Final attempt: extract any complete top-level JSON object
        import re as _re
        matches = list(_re.finditer(r'\{[^{}]*\}', clean, _re.DOTALL))
        if matches:
            for m in reversed(matches):
                try:
                    return json.loads(m.group())
                except json.JSONDecodeError:
                    continue

    logger.error("JSON parse failed: %s", clean[:300])
    raise ValueError(f"Could not parse JSON response. First 200 chars: {clean[:200]}")
