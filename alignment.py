"""
Alignment Report Model
======================
The structured output of Step 3 — what an inventor or investor receives
when they submit an idea to Project Elevate.

Design: structured JSON with a narrative summary embedded inside.
Scores are split across three dimensions so inventors and investors
each get the signals most relevant to them.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class DemandScores(BaseModel):
    """
    Three-dimensional scoring of innovation demand.

    clinical_demand:   How strongly does real clinical/epidemiological evidence
                       support need for this type of solution?
                       Driven by: disease burden, care gaps, quality deficits,
                       adverse events, shortage areas.

    market_size:       How large is the addressable market?
                       Driven by: population affected, trial enrollment,
                       number of facilities with the problem, geographic spread.

    competition_gap:   How much unmet need exists relative to current solutions?
                       Driven by: recall rates (existing products failing),
                       high adverse event counts (current drugs inadequate),
                       persistent shortage areas (market not self-correcting).

    overall:           Weighted composite. clinical_demand 40%, market_size 35%,
                       competition_gap 25%.
    """
    clinical_demand: int = Field(..., ge=0, le=100,
        description="Strength of clinical/epidemiological evidence for this need")
    market_size: int = Field(..., ge=0, le=100,
        description="Scale of the addressable market based on population signals")
    competition_gap: int = Field(..., ge=0, le=100,
        description="Degree to which current solutions are failing or absent")
    overall: int = Field(..., ge=0, le=100,
        description="Weighted composite score")

    @property
    def verdict(self) -> str:
        if self.overall >= 75:
            return "Strong Demand"
        elif self.overall >= 55:
            return "Moderate Demand"
        elif self.overall >= 35:
            return "Emerging Demand"
        else:
            return "Weak Signal"


class EvidenceItem(BaseModel):
    """A single piece of supporting evidence from the demand signal index."""
    source: str                          # e.g. "clinical_trials", "fda_adverse_events"
    signal_type: str                     # e.g. "research_trend", "safety_failure"
    title: str
    relevance_explanation: str           # why this evidence supports the idea
    magnitude: Optional[float] = None
    magnitude_unit: Optional[str] = None
    location: Optional[str] = None
    similarity_score: float


class HospitalNeedMatch(BaseModel):
    """A matching hospital pain point from Step 1 submissions."""
    need_id: int
    raw_text: str
    department: str
    category: str
    urgency_score: int
    patient_impact_score: int
    similarity_score: float


class MarketGeography(BaseModel):
    """Geographic demand concentration — useful for go-to-market planning."""
    description: str
    top_states: List[str] = Field(default_factory=list)
    scope: str  # "national", "regional", "concentrated"


class AlignmentReport(BaseModel):
    """
    The full alignment report returned to an inventor or investor.

    Structure:
    - scores:           Three-dimensional demand scores + verdict
    - narrative:        Four sections of human-readable analysis
    - evidence:         Ranked supporting signals from public health data
    - hospital_matches: Matching pain points from hospital submissions
    - market_geography: Where demand is concentrated
    - recommended_next_steps: Concrete actions for the inventor
    - metadata:         Request/response bookkeeping
    """

    # ── Core output ───────────────────────────────────────────────────────────
    scores: DemandScores

    # ── Narrative sections ────────────────────────────────────────────────────
    # Written by Claude, tailored for both inventor and investor audiences
    executive_summary: str = Field(
        ...,
        description="2-3 sentence summary of demand strength and key finding"
    )
    clinical_demand_narrative: str = Field(
        ...,
        description="Analysis of the clinical evidence base — disease burden, "
                    "care gaps, quality deficits supporting this innovation"
    )
    market_opportunity_narrative: str = Field(
        ...,
        description="Market size analysis — population affected, facility count, "
                    "trial pipeline activity, commercial readiness signals"
    )
    competition_gap_narrative: str = Field(
        ...,
        description="Analysis of current solution failures — recalls, adverse events, "
                    "persistent shortages — explaining why the gap exists"
    )

    # ── Evidence ──────────────────────────────────────────────────────────────
    supporting_evidence: List[EvidenceItem] = Field(
        default_factory=list,
        description="Top demand signals supporting this innovation, ranked by relevance"
    )
    hospital_need_matches: List[HospitalNeedMatch] = Field(
        default_factory=list,
        description="Matching pain points from hospital submissions"
    )

    # ── Strategic context ─────────────────────────────────────────────────────
    market_geography: Optional[MarketGeography] = None
    innovation_category: Optional[str] = None   # SOFTWARE / HARDWARE / SERVICE / etc.
    related_conditions: List[str] = Field(default_factory=list)
    recommended_next_steps: List[str] = Field(
        default_factory=list,
        description="Concrete actions for the inventor based on evidence found"
    )

    # ── Caveats ───────────────────────────────────────────────────────────────
    limitations: Optional[str] = None   # data gaps, confidence caveats

    # ── Metadata ──────────────────────────────────────────────────────────────
    idea_submitted: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    signals_searched: int = 0
    hospital_needs_searched: int = 0
    model_version: str = "1.0"
