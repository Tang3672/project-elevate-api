"""
Alignment Service
=================
Step 3: the core of Project Elevate.

Takes an inventor's idea description, searches both the demand signals index
and the hospital needs index, then uses Claude to synthesize the evidence
into a structured alignment report with scores and narrative.

Flow:
  1. Embed the inventor's idea
  2. Search demand_signals (public health data) for relevant signals
  3. Search hospital_needs (Step 1 submissions) for matching pain points
  4. Build a structured context package
  5. Call Claude with the idea + evidence → generates scores + narrative
  6. Parse Claude's JSON response into an AlignmentReport
  7. Return to the inventor/investor
"""

import json
import logging
from datetime import datetime

import httpx

from app.services.embedding_service import embed_text
from app.db.demand_repository import search_similar_signals, get_signal_counts_by_source
from app.db.needs_repository import find_similar_needs
from app.models.alignment import (
    AlignmentReport, DemandScores, EvidenceItem,
    HospitalNeedMatch, MarketGeography
)
from app.core.config import settings

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-opus-4-5"


# ── System prompt ─────────────────────────────────────────────────────────────

ALIGNMENT_SYSTEM_PROMPT = """You are the demand intelligence engine for Project Elevate, a platform that connects healthcare inventors with real clinical demand.

Your job: given an inventor's idea and evidence from public health databases, generate a structured demand alignment report that serves BOTH the inventor (actionable guidance) and investors (market opportunity assessment).

SCORING RUBRIC:

clinical_demand (0-100):
  90-100: Multiple federal datasets confirm high burden + clear care gap
  70-89:  Strong evidence from 2+ sources, well-documented unmet need
  50-69:  Moderate evidence, some gaps in data coverage
  30-49:  Limited evidence, emerging signal only
  0-29:   Weak or contradictory signal

market_size (0-100):
  90-100: 10M+ Americans affected, national scope, active trial pipeline
  70-89:  1-10M affected, multi-state, Phase 3 trials present
  50-69:  100k-1M affected, regional concentration
  30-49:  <100k affected or highly concentrated geography
  0-29:   Very small or unclear addressable population

competition_gap (0-100):
  90-100: Active Class I recalls + high adverse events = existing solutions failing badly
  70-89:  Significant adverse event volume OR persistent shortage area
  50-69:  Moderate failure signals, some existing solutions present
  30-49:  Existing solutions mostly adequate, incremental improvement opportunity
  0-29:   Well-served market, high competition

overall = (clinical_demand * 0.40) + (market_size * 0.35) + (competition_gap * 0.25)

NARRATIVE GUIDANCE:
- executive_summary: 2-3 sentences. Lead with the verdict. Cite the single strongest piece of evidence.
- clinical_demand_narrative: 3-4 sentences. Cite specific numbers from the evidence. Connect conditions to the invention category.
- market_opportunity_narrative: 3-4 sentences. Quantify where possible. Mention trial pipeline phase as commercial readiness signal.
- competition_gap_narrative: 2-3 sentences. Be specific about what's failing. This is where investors look for moat signals.
- recommended_next_steps: 3-5 concrete actions. Be specific to THIS invention, not generic advice.
- limitations: 1-2 sentences. Be honest about data gaps.

OUTPUT: Respond with ONLY a JSON object matching this exact schema. No markdown, no explanation outside JSON.
{
  "scores": {
    "clinical_demand": <int 0-100>,
    "market_size": <int 0-100>,
    "competition_gap": <int 0-100>,
    "overall": <int 0-100>
  },
  "executive_summary": "<string>",
  "clinical_demand_narrative": "<string>",
  "market_opportunity_narrative": "<string>",
  "competition_gap_narrative": "<string>",
  "innovation_category": "<SOFTWARE|HARDWARE|SERVICE|PHARMACEUTICALS|HYBRID>",
  "related_conditions": ["<condition1>", "<condition2>"],
  "market_geography": {
    "description": "<string>",
    "top_states": ["<state1>", "<state2>"],
    "scope": "<national|regional|concentrated>"
  },
  "recommended_next_steps": ["<step1>", "<step2>", "<step3>"],
  "limitations": "<string>"
}"""


# ── Main alignment function ───────────────────────────────────────────────────

async def generate_alignment_report(idea: str) -> AlignmentReport:
    """
    Full pipeline: idea → search → Claude → AlignmentReport.

    Args:
        idea: The inventor's free-text description of their innovation

    Returns:
        AlignmentReport with scores, narrative, and supporting evidence
    """

    # 1. Get total signal count for metadata
    source_counts = await get_signal_counts_by_source()
    total_signals = sum(r["count"] for r in source_counts)

    # 2. Embed the idea
    idea_embedding = await embed_text(idea)

    # 3. Search demand signals (public health data)
    demand_results = await search_similar_signals(
        query_embedding=idea_embedding,
        top_k=20,
        min_similarity=0.50,
    )

    # 4. Search hospital needs (Step 1 submissions)
    hospital_matches_raw = await find_similar_needs(
        query_embedding=idea_embedding,
        top_k=10,
        min_similarity=0.55,
    )

    # 5. Build context for Claude
    context = _build_evidence_context(idea, demand_results, hospital_matches_raw)

    # 6. Call Claude
    claude_response = await _call_claude(context)

    # 7. Parse response into AlignmentReport
    report = _parse_claude_response(
        claude_response=claude_response,
        idea=idea,
        demand_results=demand_results,
        hospital_matches_raw=hospital_matches_raw,
        total_signals=total_signals,
        hospital_needs_count=len(hospital_matches_raw),
    )

    return report


# ── Context builder ───────────────────────────────────────────────────────────

def _build_evidence_context(
    idea: str,
    demand_results: list[dict],
    hospital_matches: list,
) -> str:
    """
    Builds the prompt context sent to Claude.
    Structures evidence clearly so Claude can cite specific numbers.
    """
    lines = [
        f"INVENTOR'S IDEA:\n{idea}",
        "",
        f"DEMAND SIGNALS FROM PUBLIC HEALTH DATABASES ({len(demand_results)} relevant signals found):",
    ]

    for i, signal in enumerate(demand_results[:15], 1):
        lines.append(f"""
Signal {i} [{signal['source']} | {signal['signal_type']} | similarity: {signal['similarity_score']:.2f}]
Title: {signal['title']}
Description: {signal['description'][:400]}
Magnitude: {signal.get('magnitude')} {signal.get('magnitude_unit', '')}
Geography: {signal.get('geographic_scope')} — {signal.get('location_name') or 'National'}
Confidence: {signal.get('confidence_score')}""")

    if hospital_matches:
        lines.append(f"\nMATCHING HOSPITAL PAIN POINTS ({len(hospital_matches)} found):")
        for i, need in enumerate(hospital_matches[:5], 1):
            lines.append(f"""
Hospital Need {i} [similarity: {need.similarity_score:.2f}]
Department: {need.department} | Category: {need.category}
Urgency: {need.urgency_score}/5 | Patient Impact: {need.patient_impact_score}/5
Description: {need.raw_text[:300]}""")
    else:
        lines.append("\nMATCHING HOSPITAL PAIN POINTS: None yet in database (database is early stage)")

    lines.append("\nGenerate the alignment report JSON now.")
    return "\n".join(lines)


# ── Claude API call ───────────────────────────────────────────────────────────

async def _call_claude(context: str) -> str:
    """Call Claude API and return the raw response text."""
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError(
            "ANTHROPIC_API_KEY not set. Add it to your .env file. "
            "Get one at console.anthropic.com"
        )

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 2000,
                "system": ALIGNMENT_SYSTEM_PROMPT,
                "messages": [
                    {"role": "user", "content": context}
                ],
            }
        )
        response.raise_for_status()
        data = response.json()
        return data["content"][0]["text"]


# ── Response parser ───────────────────────────────────────────────────────────

def _parse_claude_response(
    claude_response: str,
    idea: str,
    demand_results: list[dict],
    hospital_matches_raw: list,
    total_signals: int,
    hospital_needs_count: int,
) -> AlignmentReport:
    """Parse Claude's JSON response into a typed AlignmentReport."""

    # Strip any accidental markdown fences
    clean = claude_response.strip()
    if clean.startswith("```"):
        clean = clean.split("```")[1]
        if clean.startswith("json"):
            clean = clean[4:]
    clean = clean.strip()

    data = json.loads(clean)

    # Build scores
    scores_data = data["scores"]
    scores = DemandScores(
        clinical_demand=scores_data["clinical_demand"],
        market_size=scores_data["market_size"],
        competition_gap=scores_data["competition_gap"],
        overall=scores_data["overall"],
    )

    # Build evidence items from demand results
    supporting_evidence = []
    for signal in demand_results[:10]:
        supporting_evidence.append(EvidenceItem(
            source=signal["source"],
            signal_type=signal["signal_type"],
            title=signal["title"],
            relevance_explanation=_explain_relevance(signal, idea),
            magnitude=signal.get("magnitude"),
            magnitude_unit=signal.get("magnitude_unit"),
            location=signal.get("location_name") or signal.get("state_code"),
            similarity_score=signal["similarity_score"],
        ))

    # Build hospital need matches
    hospital_need_matches = []
    for need in hospital_matches_raw[:5]:
        hospital_need_matches.append(HospitalNeedMatch(
            need_id=need.id,
            raw_text=need.raw_text,
            department=need.department,
            category=need.category,
            urgency_score=need.urgency_score,
            patient_impact_score=need.patient_impact_score,
            similarity_score=need.similarity_score,
        ))

    # Build geography
    geo_data = data.get("market_geography")
    market_geography = None
    if geo_data:
        market_geography = MarketGeography(
            description=geo_data.get("description", ""),
            top_states=geo_data.get("top_states", []),
            scope=geo_data.get("scope", "national"),
        )

    return AlignmentReport(
        scores=scores,
        executive_summary=data["executive_summary"],
        clinical_demand_narrative=data["clinical_demand_narrative"],
        market_opportunity_narrative=data["market_opportunity_narrative"],
        competition_gap_narrative=data["competition_gap_narrative"],
        supporting_evidence=supporting_evidence,
        hospital_need_matches=hospital_need_matches,
        market_geography=market_geography,
        innovation_category=data.get("innovation_category"),
        related_conditions=data.get("related_conditions", []),
        recommended_next_steps=data.get("recommended_next_steps", []),
        limitations=data.get("limitations"),
        idea_submitted=idea,
        generated_at=datetime.utcnow(),
        signals_searched=total_signals,
        hospital_needs_searched=hospital_needs_count,
        model_version="1.0",
    )


def _explain_relevance(signal: dict, idea: str) -> str:
    """Generate a short explanation of why this signal is relevant."""
    source_explanations = {
        "fda_adverse_events": "FDA safety data showing existing solutions are failing — direct evidence of unmet need",
        "fda_device_events": "Medical device malfunction reports indicating current hardware is inadequate",
        "fda_recalls": "Active product recall — strongest possible signal that replacement innovation is needed",
        "clinical_trials": "Active research pipeline validating clinical and commercial investment in this area",
        "cdc_places": "Population-level disease burden data showing geographic concentration of need",
        "census_sahie": "Uninsured population data indicating underserved markets with access gaps",
        "cms_hospital_quality": "Hospital quality deficit indicating where improvement technology is needed",
        "hrsa_shortage": "Federal designation of healthcare provider shortage — regulatory validation of gap",
        "cdc_wastewater": "Real-time surveillance signal indicating near-term demand surge",
        "cdc_fluview": "Weekly respiratory illness data indicating seasonal demand patterns",
    }
    return source_explanations.get(
        signal.get("source", ""),
        "Relevant public health signal supporting this innovation area"
    )
