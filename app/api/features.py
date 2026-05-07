"""
Clinical Roadmap, Portfolio, and Grant Co-Pilot API
====================================================
POST /api/v1/trial-sites          — get trial site recommendations
POST /api/v1/portfolio/analyze    — analyze lab portfolio (up to 10 ideas)
POST /api/v1/grant/generate       — generate grant sections
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── Trial Sites ───────────────────────────────────────────────────────────────

trial_router = APIRouter()

class TrialSiteRequest(BaseModel):
    idea:           str = Field(..., min_length=20)
    disease_domain: str = Field(default="auto")
    indication:     str = Field(..., min_length=5,
        description="Specific indication e.g. 'carbapenem-resistant infections in ICU patients'")
    num_sites:      int = Field(default=15, ge=5, le=20)


@trial_router.post("/trial-sites")
async def get_trial_sites(payload: TrialSiteRequest):
    """
    Get top Phase II/III trial recruitment site recommendations.
    Returns ranked list of hospitals with scores and map coordinates.
    Saves $200K+ in site selection consulting costs.
    """
    try:
        from app.services.trial_site_service import get_trial_sites
        sites = await get_trial_sites(
            idea           = payload.idea,
            disease_domain = payload.disease_domain,
            indication     = payload.indication,
            num_sites      = payload.num_sites,
        )
        return {
            "indication":  payload.indication,
            "total_sites": len(sites),
            "sites": [
                {
                    "rank":                  s.rank,
                    "hospital_name":         s.hospital_name,
                    "city":                  s.city,
                    "state":                 s.state,
                    "composite_score":       s.composite_score,
                    "patient_volume_score":  s.patient_volume_score,
                    "quality_deficit_score": s.quality_deficit_score,
                    "research_capacity":     s.research_capacity,
                    "estimated_enrollment":  s.estimated_enrollment,
                    "rationale":             s.rationale,
                    "latitude":              s.latitude,
                    "longitude":             s.longitude,
                }
                for s in sites
            ]
        }
    except Exception as e:
        logger.error(f"Trial site request failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ── Portfolio ─────────────────────────────────────────────────────────────────

portfolio_router = APIRouter()

class PortfolioIdea(BaseModel):
    name:        str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=20, max_length=1000)


class PortfolioRequest(BaseModel):
    ideas: List[PortfolioIdea] = Field(..., min_length=2, max_length=10)


@portfolio_router.post("/portfolio/analyze")
async def analyze_portfolio(payload: PortfolioRequest):
    """
    Analyze a lab portfolio of 2-10 ideas.
    Returns innovation heatmap with demand, funding, competition, and market scores.
    Identifies which ideas to pursue, validate, reframe, or shelve.
    """
    try:
        from app.services.portfolio_service import analyze_portfolio
        result = await analyze_portfolio(
            ideas=[{"name": i.name, "description": i.description} for i in payload.ideas]
        )
        return {
            "portfolio_summary": result.portfolio_summary,
            "pursue_count":      result.pursue_count,
            "validate_count":    result.validate_count,
            "reframe_count":     result.reframe_count,
            "shelve_count":      result.shelve_count,
            "ideas": [
                {
                    "idea_index":        s.idea_index,
                    "idea_name":         s.idea_name,
                    "idea_text":         s.idea_text,
                    "expert_domain":     s.expert_domain,
                    "expert_name":       s.expert_name,
                    "expert_icon":       s.expert_icon,
                    "demand_score":      s.demand_score,
                    "funding_score":     s.funding_score,
                    "competition_gap":   s.competition_gap,
                    "market_size_score": s.market_size_score,
                    "composite_score":   s.composite_score,
                    "quadrant":          s.quadrant,
                    "top_signals":       s.top_signals,
                    "recommendation":    s.recommendation,
                    "key_funding":       s.key_funding,
                    "estimated_tam":     s.estimated_tam,
                }
                for s in result.ideas
            ]
        }
    except Exception as e:
        logger.error(f"Portfolio analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ── Grant Co-Pilot ────────────────────────────────────────────────────────────

grant_router = APIRouter()

class GrantRequest(BaseModel):
    idea:         str = Field(..., min_length=30, max_length=2000)
    grant_type:   str = Field(default="nih_r01",
        description="nih_r01 | nih_sbir | nsf | all")
    specific_aim: Optional[str] = Field(default=None, max_length=1000,
        description="Optional: paste your specific aim for more targeted output")


@grant_router.post("/grant/generate")
async def generate_grant(payload: GrantRequest):
    """
    Generate ready-to-paste grant sections for NIH R01, SBIR/STTR, or NSF.
    Sections are written in proper grant language with current data citations.
    One click refreshes market data for annual grant renewals.
    """
    try:
        from app.services.grant_service import generate_grant_sections
        result = await generate_grant_sections(
            idea         = payload.idea,
            grant_type   = payload.grant_type,
            specific_aim = payload.specific_aim,
        )
        return {
            "grant_type":       result.grant_type,
            "expert_domain":    result.expert_domain,
            "expert_name":      result.expert_name,
            "overall_summary":  result.overall_summary,
            "sections": [
                {
                    "section_name":  s.section_name,
                    "content":       s.content,
                    "word_count":    s.word_count,
                    "key_citations": s.key_citations,
                }
                for s in result.sections
            ],
            "biosketch_bullets": result.biosketch_bullets,
        }
    except Exception as e:
        logger.error(f"Grant generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
