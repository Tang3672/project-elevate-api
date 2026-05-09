"""
Alignment Report Model v2
=========================
Rebuilt for principal investigators (PIs).
- Transparent bottom-up market sizing with source on every step
- Full regulatory pathway with designations and trial requirements
- Market access strategy with buyer segments
- Disease-specific epidemiological intelligence
- No opaque scores — raw numbers with exact calculations
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class ProductType(str, Enum):
    ANTIBIOTIC     = "antibiotic"
    ORPHAN_DRUG    = "orphan_drug"
    ONCOLOGY_DRUG  = "oncology_drug"
    GENE_THERAPY   = "gene_therapy"
    MEDICAL_DEVICE = "medical_device"
    SOFTWARE       = "software"
    DIAGNOSTIC     = "diagnostic"
    OTHER          = "other"


# ── Market Sizing ─────────────────────────────────────────────────────────────

class MarketSizingStep(BaseModel):
    label:       str
    value:       float
    unit:        str
    source:      str
    source_url:  Optional[str] = None
    notes:       Optional[str] = None


class MarketSizingCalculation(BaseModel):
    steps:                       List[MarketSizingStep] = Field(default_factory=list)
    formula:                     str
    total_addressable_market_usd: float
    serviceable_market_usd:      float
    methodology_note:            str

    @property
    def tam_formatted(self) -> str:
        b = self.total_addressable_market_usd / 1e9
        m = self.total_addressable_market_usd / 1e6
        return f"${b:.1f}B" if b >= 1 else f"${m:.0f}M"

    @property
    def sam_formatted(self) -> str:
        return f"${self.serviceable_market_usd / 1e6:.0f}M"


# ── Regulatory Pathway ────────────────────────────────────────────────────────

class RegulatoryDesignation(BaseModel):
    name:         str
    description:  str
    benefit:      str
    eligibility:  str
    how_to_apply: str
    timeline:     str
    source:       str
    source_url:   Optional[str] = None
    priority:     str = "recommended"


class ClinicalTrialRequirements(BaseModel):
    phase:                      str
    patient_count:              str
    duration:                   str
    estimated_cost:             str
    key_endpoints:              List[str]
    fda_guidance_document:      str
    source_url:                 Optional[str] = None
    success_probability:        str


class RegulatoryPathway(BaseModel):
    recommended_pathway:        str
    pathway_rationale:          str
    designations:               List[RegulatoryDesignation] = Field(default_factory=list)
    clinical_trial_requirements: List[ClinicalTrialRequirements] = Field(default_factory=list)
    total_timeline_estimate:    str
    total_cost_estimate:        str
    key_friction_points:        List[str] = Field(default_factory=list)
    loopholes_and_strategies:   List[str] = Field(default_factory=list)
    funding_programs:           List[str] = Field(default_factory=list)


# ── Market Access ─────────────────────────────────────────────────────────────

class BuyerSegment(BaseModel):
    segment_name:               str
    buyer_count:                str
    decision_maker:             str
    price_per_unit:             str
    annual_spend_per_facility:  str
    access_mechanism:           str
    timeline_to_access:         str
    source:                     str


class MarketAccessStrategy(BaseModel):
    primary_channel:            str
    buyer_segments:             List[BuyerSegment] = Field(default_factory=list)
    key_opinion_leaders:        List[str] = Field(default_factory=list)
    reimbursement_pathway:      str
    first_commercial_step:      str
    international_opportunities: List[str] = Field(default_factory=list)


# ── Disease Intelligence ──────────────────────────────────────────────────────

class DiseaseDataPoint(BaseModel):
    metric:      str
    value:       str
    year:        str
    source:      str
    source_url:  Optional[str] = None


class DiseaseIntelligence(BaseModel):
    condition:            str
    data_points:          List[DiseaseDataPoint] = Field(default_factory=list)
    resistance_profile:   Optional[str] = None
    pipeline_status:      Optional[str] = None
    unmet_need_summary:   str


# ── Evidence ──────────────────────────────────────────────────────────────────

class EvidenceItem(BaseModel):
    source:               str
    signal_type:          str
    title:                str
    relevance_explanation: str
    magnitude:            Optional[float] = None
    magnitude_unit:       Optional[str] = None
    location:             Optional[str] = None
    similarity_score:     float
    source_url:           Optional[str] = None


class HospitalNeedMatch(BaseModel):
    need_id:              int
    raw_text:             str
    department:           str
    category:             str
    urgency_score:        int
    patient_impact_score: int
    similarity_score:     float
    source_platform:      str = "direct_submission"
    subreddit:            Optional[str] = None


class MarketGeography(BaseModel):
    description:  str
    top_states:   List[str] = Field(default_factory=list)
    scope:        str


# ── Full PI Report ────────────────────────────────────────────────────────────

class PIReport(BaseModel):
    """
    Full go-to-market intelligence report for a principal investigator.
    No opaque scores — every number shows its exact source and calculation.
    """
    product_type:           ProductType
    idea_submitted:         str
    executive_summary:      str
    disease_intelligence:   Optional[DiseaseIntelligence] = None
    market_sizing:          Optional[MarketSizingCalculation] = None
    regulatory_pathway:     Optional[RegulatoryPathway] = None
    market_access:          Optional[MarketAccessStrategy] = None
    supporting_evidence:    List[EvidenceItem]   = Field(default_factory=list)
    hospital_need_matches:  List[HospitalNeedMatch] = Field(default_factory=list)
    market_geography:       Optional[MarketGeography] = None
    recommended_next_steps: List[str] = Field(default_factory=list)
    limitations:            Optional[str] = None
    generated_at:           datetime = Field(default_factory=datetime.utcnow)
    signals_searched:       int = 0
    hospital_needs_searched: int = 0
    model_version:          str = "3.0-MoE"
    validation:             Optional[dict] = None
    expert_domain:          Optional[str]  = None
    expert_name:            Optional[str]  = None
    expert_icon:            Optional[str]  = None
    routing_method:         Optional[str]  = None
    mismatch_warning:       Optional[str]  = None
    sources:                List[dict]     = Field(default_factory=list)   # all cited sources with URLs


# ── Legacy AlignmentReport (kept for backward compat) ─────────────────────────

class DemandScores(BaseModel):
    clinical_demand: int = Field(..., ge=0, le=100)
    market_size:     int = Field(..., ge=0, le=100)
    competition_gap: int = Field(..., ge=0, le=100)
    overall:         int = Field(..., ge=0, le=100)

    @property
    def verdict(self) -> str:
        if self.overall >= 75: return "Strong Demand"
        if self.overall >= 55: return "Moderate Demand"
        if self.overall >= 35: return "Emerging Demand"
        return "Weak Signal"


class AlignmentReport(BaseModel):
    scores:                     DemandScores
    executive_summary:          str
    clinical_demand_narrative:  str
    market_opportunity_narrative: str
    competition_gap_narrative:  str
    supporting_evidence:        List[EvidenceItem]   = Field(default_factory=list)
    hospital_need_matches:      List[HospitalNeedMatch] = Field(default_factory=list)
    market_geography:           Optional[MarketGeography] = None
    innovation_category:        Optional[str] = None
    related_conditions:         List[str] = Field(default_factory=list)
    recommended_next_steps:     List[str] = Field(default_factory=list)
    limitations:                Optional[str] = None
    idea_submitted:             str
    generated_at:               datetime = Field(default_factory=datetime.utcnow)
    signals_searched:           int = 0
    hospital_needs_searched:    int = 0
    model_version:              str = "1.0"
