"""
PI Alignment Service v2
"""
import json
import logging
from datetime import datetime
import httpx

from app.services.embedding_service import embed_text
from app.db.demand_repository import search_similar_signals, get_signal_counts_by_source
from app.db.needs_repository import find_similar_needs
from app.models.alignment import (
    AlignmentReport, DemandScores, EvidenceItem, HospitalNeedMatch, MarketGeography,
    PIReport, ProductType, DiseaseIntelligence, DiseaseDataPoint,
    MarketSizingCalculation, MarketSizingStep, RegulatoryPathway,
    RegulatoryDesignation, ClinicalTrialRequirements,
    MarketAccessStrategy, BuyerSegment,
)
from app.core.config import settings

logger = logging.getLogger(__name__)
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL      = "claude-sonnet-4-6"

SOURCE_URLS = {
    "fda_adverse_events":   "https://open.fda.gov/apis/drug/event/",
    "fda_device_events":    "https://open.fda.gov/apis/device/event/",
    "fda_recalls":          "https://open.fda.gov/apis/drug/enforcement/",
    "clinical_trials":      "https://clinicaltrials.gov/",
    "cdc_places":           "https://www.cdc.gov/places/",
    "census_sahie":         "https://www.census.gov/data/datasets/time-series/demo/sahie/",
    "cms_hospital_quality": "https://www.medicare.gov/care-compare/",
    "hrsa_shortage":        "https://data.hrsa.gov/tools/shortage-area/hpsa-find",
    "cdc_wastewater":       "https://www.cdc.gov/nwss/",
    "cdc_fluview":          "https://www.cdc.gov/flu/weekly/",
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


async def generate_pi_report(idea: str, product_type: str = "other") -> PIReport:
    pt = ProductType(product_type.lower()) if product_type else ProductType.OTHER
    source_counts = await get_signal_counts_by_source()
    total_signals = sum(r["count"] for r in source_counts)
    idea_embedding = await embed_text(idea)
    demand_results = await search_similar_signals(query_embedding=idea_embedding, top_k=20, min_similarity=0.62)
    hospital_matches_raw = await find_similar_needs(query_embedding=idea_embedding, top_k=10, min_similarity=0.50)

    if pt == ProductType.ANTIBIOTIC:
        report = await _generate_antibiotic_report(idea, demand_results, hospital_matches_raw, total_signals)
        try:
            from app.services.validation_graph import validate_pi_report
            report_dict = report.model_dump(mode="json")
            validated   = await validate_pi_report(report_dict, "antibiotic")
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
    return await _generate_generic_pi_report(idea, pt, demand_results, hospital_matches_raw, total_signals)


async def generate_alignment_report(idea: str) -> AlignmentReport:
    source_counts = await get_signal_counts_by_source()
    total_signals = sum(r["count"] for r in source_counts)
    idea_embedding = await embed_text(idea)
    demand_results = await search_similar_signals(query_embedding=idea_embedding, top_k=20, min_similarity=0.62)
    hospital_matches_raw = await find_similar_needs(query_embedding=idea_embedding, top_k=10, min_similarity=0.55)
    context = _build_legacy_context(idea, demand_results, hospital_matches_raw)
    raw = await _call_claude(context, LEGACY_SYSTEM_PROMPT)
    return _parse_legacy_response(raw, idea, demand_results, hospital_matches_raw, total_signals, len(hospital_matches_raw))


ANTIBIOTIC_SYSTEM_PROMPT = '''You are a go-to-market intelligence engine for principal investigators developing antibiotics. Generate a source-cited report. Be concise — every field should be 1-3 sentences maximum. No padding or repetition.

Respond ONLY with valid compact JSON. No markdown. Use this exact schema:
{
  "executive_summary": "<2 sentences max, cite one specific number with source>",
  "disease_intelligence": {
    "condition": "<pathogen name>",
    "data_points": [
      {"metric": "<name>", "value": "<value>", "year": "<year>", "source": "<source name>", "source_url": "<url or null>"}
    ],
    "resistance_profile": "<1-2 sentences>",
    "pipeline_status": "<1 sentence on competing drugs>",
    "unmet_need_summary": "<1 sentence>"
  },
  "market_sizing": {
    "steps": [
      {"label": "<step name>", "value": 0, "unit": "<unit>", "source": "<source>", "source_url": "<url or null>", "notes": "<1 sentence or null>"}
    ],
    "formula": "<patients x price x penetration = TAM>",
    "total_addressable_market_usd": 0,
    "serviceable_market_usd": 0,
    "methodology_note": "<1-2 sentences>"
  },
  "regulatory_pathway": {
    "recommended_pathway": "<pathway name>",
    "pathway_rationale": "<1-2 sentences>",
    "designations": [
      {"name": "<name>", "description": "<1 sentence>", "benefit": "<1 sentence>", "eligibility": "<1 sentence>", "how_to_apply": "<1 sentence>", "timeline": "<1 sentence>", "source": "<source>", "source_url": "<url or null>", "priority": "<recommended|consider|optional>"}
    ],
    "clinical_trial_requirements": [
      {"phase": "<Phase 1|2|3>", "patient_count": "<range>", "duration": "<duration>", "estimated_cost": "<range>", "key_endpoints": ["<endpoint>"], "fda_guidance_document": "<title>", "source_url": "<url or null>", "success_probability": "<percent>"}
    ],
    "total_timeline_estimate": "<range>",
    "total_cost_estimate": "<range>",
    "key_friction_points": ["<1 sentence each, max 3>"],
    "loopholes_and_strategies": ["<1 sentence each, max 3>"],
    "funding_programs": ["<1 sentence each, max 3>"]
  },
  "market_access": {
    "primary_channel": "<1 sentence>",
    "buyer_segments": [
      {"segment_name": "<name>", "buyer_count": "<count>", "decision_maker": "<role>", "price_per_unit": "<price>", "annual_spend_per_facility": "<amount>", "access_mechanism": "<1 sentence>", "timeline_to_access": "<timeframe>", "source": "<source>"}
    ],
    "key_opinion_leaders": ["<1 sentence each, max 2>"],
    "reimbursement_pathway": "<1-2 sentences>",
    "first_commercial_step": "<1 sentence>",
    "international_opportunities": ["<1 sentence each, max 2>"]
  },
  "market_geography": {"description": "<1-2 sentences>", "top_states": ["<state>"], "scope": "<national|regional|concentrated>"},
  "recommended_next_steps": ["<1 sentence each, max 5>"],
  "limitations": "<1-2 sentences>"
}'''



async def _generate_antibiotic_report(idea, demand_results, hospital_matches_raw, total_signals):
    context = _build_antibiotic_context(idea, demand_results, hospital_matches_raw)
    raw  = await _call_claude(context, ANTIBIOTIC_SYSTEM_PROMPT, max_tokens=6000)
    data = _clean_json(raw)

    di_data = data.get("disease_intelligence", {})
    disease_intel = DiseaseIntelligence(
        condition=di_data.get("condition", ""),
        data_points=[DiseaseDataPoint(**dp) for dp in di_data.get("data_points", [])],
        resistance_profile=di_data.get("resistance_profile"),
        pipeline_status=di_data.get("pipeline_status"),
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

    rp_data = data.get("regulatory_pathway", {})
    reg_pathway = None
    if rp_data:
        reg_pathway = RegulatoryPathway(
            recommended_pathway=rp_data.get("recommended_pathway", ""),
            pathway_rationale=rp_data.get("pathway_rationale", ""),
            designations=[RegulatoryDesignation(**d) for d in rp_data.get("designations", [])],
            clinical_trial_requirements=[ClinicalTrialRequirements(**t) for t in rp_data.get("clinical_trial_requirements", [])],
            total_timeline_estimate=rp_data.get("total_timeline_estimate", ""),
            total_cost_estimate=rp_data.get("total_cost_estimate", ""),
            key_friction_points=rp_data.get("key_friction_points", []),
            loopholes_and_strategies=rp_data.get("loopholes_and_strategies", []),
            funding_programs=rp_data.get("funding_programs", []),
        )

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
        product_type=ProductType.ANTIBIOTIC,
        idea_submitted=idea,
        executive_summary=data.get("executive_summary", ""),
        disease_intelligence=disease_intel,
        market_sizing=market_sizing,
        regulatory_pathway=reg_pathway,
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


def _build_antibiotic_context(idea, demand_results, hospital_matches):
    lines = ["PRINCIPAL INVESTIGATOR ANTIBIOTIC PRODUCT:", idea, "",
             f"DEMAND SIGNALS FROM FEDERAL DATABASES ({len(demand_results)} signals):"]
    for i, s in enumerate(demand_results[:15], 1):
        lines.append(f"\nSignal {i} [{s['source']} | {s['signal_type']} | sim={s['similarity_score']:.2f}]"
                     f"\nTitle: {s['title']}\nDesc: {s['description'][:350]}"
                     f"\nMagnitude: {s.get('magnitude')} {s.get('magnitude_unit','')}"
                     f"\nGeo: {s.get('geographic_scope')} — {s.get('location_name') or 'National'}")
    if hospital_matches:
        lines.append(f"\nCLINICAL PAIN POINTS ({len(hospital_matches)} matches):")
        for i, n in enumerate(hospital_matches[:5], 1):
            lines.append(f"\nNeed {i} [sim={n.similarity_score:.2f} | {n.department} | urgency={n.urgency_score}/5]\n{n.raw_text[:300]}")
    lines.append("\nGenerate the full PI intelligence report JSON now.")
    return "\n".join(lines)


GENERIC_PI_SYSTEM_PROMPT = '''You are a go-to-market intelligence engine for principal investigators developing healthcare products.

Generate a source-cited intelligence report. Every data point must show its source. No opaque scores — use transparent bottom-up calculations.

Respond ONLY with valid JSON:
{
  "executive_summary": "<2-3 sentences with specific numbers and sources>",
  "disease_intelligence": {
    "condition": "<>",
    "data_points": [{"metric":"<>","value":"<>","year":"<>","source":"<>","source_url":"<or null>"}],
    "unmet_need_summary": "<>"
  },
  "market_sizing": {
    "steps": [{"label":"<>","value":0,"unit":"<>","source":"<>","source_url":"<or null>","notes":"<or null>"}],
    "formula": "<Addressable patients x Price x Penetration = TAM>",
    "total_addressable_market_usd": 0,
    "serviceable_market_usd": 0,
    "methodology_note": "<>"
  },
  "market_access": {
    "primary_channel": "<>",
    "buyer_segments": [{"segment_name":"<>","buyer_count":"<>","decision_maker":"<>","price_per_unit":"<>","annual_spend_per_facility":"<>","access_mechanism":"<>","timeline_to_access":"<>","source":"<>"}],
    "key_opinion_leaders": ["<>"],
    "reimbursement_pathway": "<>",
    "first_commercial_step": "<>",
    "international_opportunities": ["<>"]
  },
  "market_geography": {"description":"<>","top_states":["<>"],"scope":"<national|regional|concentrated>"},
  "recommended_next_steps": ["<step with timeline>"],
  "limitations": "<>"
}'''


async def _generate_generic_pi_report(idea, product_type, demand_results, hospital_matches_raw, total_signals):
    context = _build_legacy_context(idea, demand_results, hospital_matches_raw)
    raw  = await _call_claude(context, GENERIC_PI_SYSTEM_PROMPT, max_tokens=6000)
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
    return PIReport(
        product_type=product_type,
        idea_submitted=idea,
        executive_summary=data.get("executive_summary", ""),
        disease_intelligence=disease_intel,
        market_sizing=market_sizing,
        market_access=market_access,
        supporting_evidence=_build_evidence_items(demand_results[:10]),
        hospital_need_matches=_build_hospital_matches(hospital_matches_raw[:5]),
        market_geography=MarketGeography(**geo_data) if geo_data else None,
        recommended_next_steps=data.get("recommended_next_steps", []),
        limitations=data.get("limitations"),
        signals_searched=total_signals,
        hospital_needs_searched=len(hospital_matches_raw),
        model_version="2.0",
    )


LEGACY_SYSTEM_PROMPT = '''You are the demand intelligence engine for Project Elevate.
Given an inventor idea and evidence from public health databases, generate a structured demand alignment report.
SCORING: clinical_demand(0-100): 90-100 multiple federal datasets; 70-89 strong 2+ sources; 50-69 moderate; 30-49 limited; 0-29 weak
market_size(0-100): 90-100 10M+ national active trials; 70-89 1-10M Phase3; 50-69 100k-1M regional; 30-49 <100k; 0-29 unclear
competition_gap(0-100): 90-100 Class I recalls + high AEs; 70-89 significant failures; 50-69 moderate; 30-49 mostly adequate; 0-29 well-served
overall=(clinical_demand*0.40)+(market_size*0.35)+(competition_gap*0.25)
Respond ONLY with JSON:
{"scores":{"clinical_demand":0,"market_size":0,"competition_gap":0,"overall":0},"executive_summary":"","clinical_demand_narrative":"","market_opportunity_narrative":"","competition_gap_narrative":"","innovation_category":"SOFTWARE|HARDWARE|SERVICE|PHARMACEUTICALS|HYBRID","related_conditions":[],"market_geography":{"description":"","top_states":[],"scope":"national"},"recommended_next_steps":[],"limitations":""}'''


def _build_legacy_context(idea, demand_results, hospital_matches):
    lines = [f"INVENTOR IDEA:\n{idea}", "", f"DEMAND SIGNALS ({len(demand_results)} found):"]
    for i, s in enumerate(demand_results[:15], 1):
        lines.append(f"\nSignal {i} [{s['source']} | sim={s['similarity_score']:.2f}]\nTitle: {s['title']}\nDesc: {s['description'][:300]}")
    if hospital_matches:
        lines.append(f"\nHOSPITAL NEEDS ({len(hospital_matches)}):")
        for i, n in enumerate(hospital_matches[:5], 1):
            lines.append(f"\nNeed {i} [sim={n.similarity_score:.2f}]\n{n.raw_text[:250]}")
    lines.append("\nGenerate alignment report JSON now.")
    return "\n".join(lines)


def _parse_legacy_response(raw, idea, demand_results, hospital_matches_raw, total_signals, hospital_needs_count):
    data = _clean_json(raw)
    sd = data["scores"]
    scores = DemandScores(clinical_demand=sd["clinical_demand"], market_size=sd["market_size"],
                          competition_gap=sd["competition_gap"], overall=sd["overall"])
    geo_d = data.get("market_geography", {})
    return AlignmentReport(
        scores=scores,
        executive_summary=data["executive_summary"],
        clinical_demand_narrative=data["clinical_demand_narrative"],
        market_opportunity_narrative=data["market_opportunity_narrative"],
        competition_gap_narrative=data["competition_gap_narrative"],
        supporting_evidence=_build_evidence_items(demand_results[:10]),
        hospital_need_matches=_build_hospital_matches(hospital_matches_raw[:5]),
        market_geography=MarketGeography(**geo_d) if geo_d else None,
        innovation_category=data.get("innovation_category"),
        related_conditions=data.get("related_conditions", []),
        recommended_next_steps=data.get("recommended_next_steps", []),
        limitations=data.get("limitations"),
        idea_submitted=idea,
        signals_searched=total_signals,
        hospital_needs_searched=hospital_needs_count,
        model_version="1.0",
    )


def _build_evidence_items(demand_results):
    return [EvidenceItem(
        source=s["source"], signal_type=s["signal_type"], title=s["title"],
        relevance_explanation=SOURCE_EXPLANATIONS.get(s.get("source",""), "Relevant public health demand signal"),
        magnitude=s.get("magnitude"), magnitude_unit=s.get("magnitude_unit"),
        location=s.get("location_name") or s.get("state_code"),
        similarity_score=s["similarity_score"],
        source_url=SOURCE_URLS.get(s.get("source","")),
    ) for s in demand_results]


def _build_hospital_matches(hospital_matches_raw):
    return [HospitalNeedMatch(
        need_id=n.id, raw_text=n.raw_text, department=n.department,
        category=n.category, urgency_score=n.urgency_score,
        patient_impact_score=n.patient_impact_score,
        similarity_score=n.similarity_score,
        source_platform=getattr(n, "source_platform", "direct_submission"),
        subreddit=getattr(n, "subreddit", None),
    ) for n in hospital_matches_raw]


async def _call_claude(context, system_prompt, max_tokens=4000):
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set in .env")
    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(ANTHROPIC_API_URL,
            headers={"x-api-key": settings.ANTHROPIC_API_KEY,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": CLAUDE_MODEL, "max_tokens": max_tokens, "system": system_prompt,
                  "messages": [{"role": "user", "content": context}]})
        r.raise_for_status()
        return r.json()["content"][0]["text"]


def _clean_json(raw):
    clean = raw.strip()
    if clean.startswith("```"):
        parts = clean.split("```")
        clean = parts[1] if len(parts) > 1 else clean
        if clean.startswith("json"):
            clean = clean[4:]
    return json.loads(clean.strip())


