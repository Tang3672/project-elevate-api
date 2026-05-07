"""
Lab Portfolio Discovery Service
================================
Scores up to 10 innovation ideas across 4 dimensions and generates
an innovation heatmap for lab directors and tech transfer offices.

Scoring dimensions:
  1. Demand score        — semantic similarity vs 46,733 federal signals
  2. Funding opportunity — match against known programs per expert domain
  3. Competition gap     — how crowded is the pipeline (inverse of competition)
  4. Market size         — TAM estimate from expert knowledge base

Output: ranked list + 2x2 matrix (Demand vs Funding) showing:
  - PURSUE   (high demand, high funding)
  - VALIDATE (high demand, low funding)
  - REFRAME  (low demand, high funding)
  - SHELVE   (low demand, low funding)
"""
import json
import logging
from dataclasses import dataclass
from typing import List, Optional

import httpx

from app.core.config import settings
from app.services.embedding_service import embed_text
from app.services.expert_router import route as route_expert
from app.db.demand_repository import search_similar_signals
from app.services.expert_profiles import get_expert

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL      = "claude-haiku-4-5-20251001"


@dataclass
class IdeaScore:
    idea_index:          int
    idea_text:           str
    idea_name:           str
    expert_domain:       str
    expert_name:         str
    expert_icon:         str
    demand_score:        float    # 0-100
    funding_score:       float    # 0-100
    competition_gap:     float    # 0-100 (higher = less competition = better)
    market_size_score:   float    # 0-100
    composite_score:     float    # weighted average
    quadrant:            str      # PURSUE | VALIDATE | REFRAME | SHELVE
    top_signals:         int      # number of matching demand signals
    recommendation:      str      # 1-2 sentence strategic recommendation
    key_funding:         List[str]  # top 2-3 funding programs for this domain
    estimated_tam:       str      # e.g. "$135M - $289M U.S."


@dataclass
class PortfolioResult:
    ideas:               List[IdeaScore]
    top_idea:            IdeaScore
    portfolio_summary:   str
    pursue_count:        int
    validate_count:      int
    reframe_count:       int
    shelve_count:        int


async def analyze_portfolio(
    ideas: List[dict],   # [{"name": str, "description": str}]
) -> PortfolioResult:
    """
    Score a portfolio of up to 10 ideas and generate the innovation heatmap.

    Args:
        ideas: list of {name, description} dicts

    Returns:
        PortfolioResult with scored IdeaScore objects and summary
    """
    ideas = ideas[:10]   # cap at 10
    scored_ideas = []

    for i, idea_dict in enumerate(ideas):
        name = idea_dict.get("name", f"Idea {i+1}")
        desc = idea_dict.get("description", "")

        try:
            score = await _score_idea(i, name, desc)
            scored_ideas.append(score)
        except Exception as e:
            logger.error(f"Failed to score idea {i} '{name}': {e}")
            # Add a placeholder so we don't lose the idea
            scored_ideas.append(IdeaScore(
                idea_index=i, idea_text=desc, idea_name=name,
                expert_domain="unknown", expert_name="Unknown", expert_icon="⚕️",
                demand_score=0, funding_score=0, competition_gap=50,
                market_size_score=0, composite_score=0, quadrant="SHELVE",
                top_signals=0, recommendation="Scoring failed — please retry.",
                key_funding=[], estimated_tam="Unknown"
            ))

    # Sort by composite score
    scored_ideas.sort(key=lambda x: x.composite_score, reverse=True)

    # Count quadrants
    pursue   = sum(1 for s in scored_ideas if s.quadrant == "PURSUE")
    validate = sum(1 for s in scored_ideas if s.quadrant == "VALIDATE")
    reframe  = sum(1 for s in scored_ideas if s.quadrant == "REFRAME")
    shelve   = sum(1 for s in scored_ideas if s.quadrant == "SHELVE")

    # Generate portfolio summary
    summary = await _generate_portfolio_summary(scored_ideas)

    return PortfolioResult(
        ideas             = scored_ideas,
        top_idea          = scored_ideas[0] if scored_ideas else None,
        portfolio_summary = summary,
        pursue_count      = pursue,
        validate_count    = validate,
        reframe_count     = reframe,
        shelve_count      = shelve,
    )


async def _score_idea(idx: int, name: str, description: str) -> IdeaScore:
    """Score a single idea across all 4 dimensions."""

    # 1. Route to expert domain
    router_result = await route_expert(idea=description, pi_domain="auto")
    expert        = router_result.expert

    # 2. Demand score — semantic similarity search
    embedding      = await embed_text(description)
    demand_signals = await search_similar_signals(
        query_embedding=embedding, top_k=20, min_similarity=0.55)
    top_signals    = len(demand_signals)

    # Demand score: 0-100 based on number and quality of matches
    avg_similarity = (
        sum(s['similarity_score'] for s in demand_signals) / len(demand_signals)
        if demand_signals else 0
    )
    demand_score = min(100, (top_signals * 3) + (avg_similarity * 40))

    # 3. Get Claude to score funding, competition gap, market size
    scores = await _claude_score_idea(description, expert, demand_score, top_signals)

    # 4. Composite score (weighted)
    composite = (
        demand_score             * 0.35 +
        scores['funding_score']  * 0.30 +
        scores['competition_gap'] * 0.20 +
        scores['market_size_score'] * 0.15
    )

    # 5. Assign quadrant
    quadrant = _assign_quadrant(demand_score, scores['funding_score'])

    return IdeaScore(
        idea_index          = idx,
        idea_text           = description,
        idea_name           = name,
        expert_domain       = expert.domain_id,
        expert_name         = expert.display_name,
        expert_icon         = expert.icon,
        demand_score        = round(demand_score, 1),
        funding_score       = round(scores['funding_score'], 1),
        competition_gap     = round(scores['competition_gap'], 1),
        market_size_score   = round(scores['market_size_score'], 1),
        composite_score     = round(composite, 1),
        quadrant            = quadrant,
        top_signals         = top_signals,
        recommendation      = scores['recommendation'],
        key_funding         = scores['key_funding'],
        estimated_tam       = scores['estimated_tam'],
    )


async def _claude_score_idea(
    description: str,
    expert,
    demand_score: float,
    signal_count: int,
) -> dict:
    """Use Claude Haiku to quickly score funding, competition, and market size."""

    system = f"""You are a healthcare innovation portfolio analyst. Score innovations quickly and accurately.

Domain expertise ({expert.display_name}):
{expert.knowledge_base[:800]}

Respond ONLY with valid JSON:
{{
  "funding_score": <0-100>,
  "competition_gap": <0-100>,
  "market_size_score": <0-100>,
  "recommendation": "<1-2 sentences: strategic recommendation for this idea>",
  "key_funding": ["<funding program 1>", "<funding program 2>"],
  "estimated_tam": "<e.g. $135M-$289M U.S.>"
}}

Scoring guide:
- funding_score: 90-100 = multiple large programs available (BARDA, NCI, NHLBI); 70-89 = 1-2 major programs; 50-69 = limited funding; <50 = must be self-funded
- competition_gap: 90-100 = no approved products, clear unmet need; 70-89 = 1-2 competitors with gaps; 50-69 = crowded but differentiable; <50 = commoditized market
- market_size_score: 90-100 = TAM >$1B; 70-89 = $200M-$1B; 50-69 = $50M-$200M; <50 = <$50M"""

    user = f"""Score this healthcare innovation:

{description[:600]}

Context: {signal_count} federal demand signals matched (out of 46,733 indexed). Demand score: {demand_score:.0f}/100."""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key":         settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      CLAUDE_MODEL,
                    "max_tokens": 400,
                    "system":     system,
                    "messages":   [{"role": "user", "content": user}],
                }
            )
            r.raise_for_status()
            text = r.json()["content"][0]["text"].strip()
            if text.startswith("```"):
                parts = text.split("```")
                text  = parts[1] if len(parts) > 1 else text
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text.strip())
    except Exception as e:
        logger.error(f"Claude scoring failed: {e}")
        return {
            "funding_score": 50, "competition_gap": 50,
            "market_size_score": 50,
            "recommendation": "Scoring unavailable — please retry.",
            "key_funding": [], "estimated_tam": "Unknown"
        }


def _assign_quadrant(demand_score: float, funding_score: float) -> str:
    """Assign 2x2 matrix quadrant based on demand and funding scores."""
    high_demand  = demand_score  >= 55
    high_funding = funding_score >= 55
    if high_demand and high_funding:   return "PURSUE"
    if high_demand and not high_funding: return "VALIDATE"
    if not high_demand and high_funding: return "REFRAME"
    return "SHELVE"


async def _generate_portfolio_summary(ideas: List[IdeaScore]) -> str:
    """Generate a strategic summary of the portfolio."""
    if not ideas:
        return "No ideas to summarize."

    pursue_ideas = [i for i in ideas if i.quadrant == "PURSUE"]
    top = ideas[0]

    if pursue_ideas:
        names = ", ".join(i.idea_name for i in pursue_ideas[:3])
        return (
            f"Your portfolio's strongest opportunities are {names} — "
            f"all showing high demand signals and strong funding availability. "
            f"{top.idea_name} leads with a composite score of {top.composite_score:.0f}/100 "
            f"and is recommended as the primary focus."
        )
    else:
        return (
            f"No ideas in the portfolio currently meet the 'Pursue' threshold. "
            f"{top.idea_name} shows the most promise with a {top.composite_score:.0f}/100 score. "
            f"Consider refining the top ideas or exploring adjacent indications with higher unmet need."
        )
