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


class ReportDomain(str, Enum):
    """Top-level domain gate. Controls which section libraries are active.
    Only LIFE_SCIENCES_CLINICAL unlocks disease burden, FDA pathway, payer sections.
    Everything else uses the general commercialization spine.
    """
    LIFE_SCIENCES_CLINICAL  = "LIFE_SCIENCES_CLINICAL"   # therapeutics, devices, diagnostics
    LIFE_SCIENCES_RESEARCH  = "LIFE_SCIENCES_RESEARCH"   # research tools, reagents, lab infra
    ENGINEERING_HARDWARE    = "ENGINEERING_HARDWARE"
    SOFTWARE_INFRASTRUCTURE = "SOFTWARE_INFRASTRUCTURE"
    MATERIALS_CHEMICAL      = "MATERIALS_CHEMICAL"
    ENERGY_CLIMATE          = "ENERGY_CLIMATE"
    AGRICULTURE_FOOD        = "AGRICULTURE_FOOD"
    OTHER_DEEP_TECH         = "OTHER_DEEP_TECH"


# ── Market Sizing ─────────────────────────────────────────────────────────────

class MarketSizingStep(BaseModel):
    label:       str
    value:       float
    unit:        str
    source:      str
    source_url:  Optional[str] = None
    notes:       Optional[str] = None


# ── Part E: Assumption Ledger ─────────────────────────────────────────────────

class AssumptionSource(str, Enum):
    LLM_GENERATED   = "llm_generated"    # Claude produced it from training data
    RETRIEVED        = "retrieved"        # came from a live API / retrieval call
    USER_OVERRIDE    = "user_override"    # PI explicitly provided or overrode it
    FALLBACK_DEFAULT = "fallback_default" # safe default used when no data available


class Assumption(BaseModel):
    """A single quantified market assumption with its provenance."""
    key:           str                          # e.g. "us_pi_count", "annual_price_usd"
    label:         str                          # human-readable name
    value:         float                        # numeric value (unit in `unit` field)
    unit:          str                          # e.g. "USD", "labs", "% market share"
    source:        AssumptionSource
    source_detail: Optional[str] = None        # "NIH RePORTER 2024" or URL
    confidence:    Optional[str] = None        # "low" | "medium" | "high"
    note:          Optional[str] = None        # any relevant caveat
    sensitivity_rank: Optional[int] = None     # 1 = highest sensitivity driver
    override_value: Optional[float] = None     # if user_override, original LLM value
    overridden_at: Optional[str] = None        # ISO timestamp of override


class AssumptionLedger(BaseModel):
    """Complete set of quantified assumptions underlying the market sizing."""
    assumptions:    List[Assumption] = Field(default_factory=list)
    generated_at:   Optional[str] = None       # ISO timestamp
    last_modified:  Optional[str] = None       # ISO timestamp of last user override
    override_count: int = 0                    # how many user overrides applied
    version_hash:   Optional[str] = None       # E.4: SHA-256 of ledger state at last save


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
    source_url:                 Optional[str] = None


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
    description:  str = ""
    top_states:   List[str] = Field(default_factory=list)
    scope:        str = ""


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
    strategic_playbook:     List[dict] = Field(default_factory=list)
    literature_citations:   Optional[List[dict]] = None
    limitations:            Optional[str] = None
    generated_at:           datetime = Field(default_factory=datetime.utcnow)
    signals_searched:       int = 0
    hospital_needs_searched: int = 0
    model_version:          str = "3.0-MoE"
    validation:             Optional[dict] = None
    trust:                  Optional[dict] = None   # report-level Trust Layer scorecard (P2)
    market_sizing_provenance: Optional[dict] = None # typed source-backed assumptions + scenarios (P1)
    commercialization_scores: Optional[dict] = None # probabilistic decision engine block (P5)
    expert_panel:           Optional[dict] = None   # structured 3-panel MoE outputs, for UI visibility
    report_id:              Optional[str]  = None    # stable id for feedback/outcome linkage (P11)
    product_name:           Optional[str]  = None    # F-01: dedicated intake field, not taxonomy
    institution:            Optional[str]  = None    # F-01: "Washington University Neurotech Hub"
    domain:                 Optional[str]  = None    # C.2: LIFE_SCIENCES_CLINICAL | LIFE_SCIENCES_RESEARCH | …
    portfolio_benchmark:    Optional[dict] = None    # institution-level percentile + comparables (P7)
    routing_plan:           Optional[dict] = None     # cost-aware specialist routing plan (P3)
    grounded_context:       Optional[list] = None      # retrieved facts used by synthesis, for trust judging
    competitive_landscape:  Optional[dict] = None       # server-side competitor sweep (reliable, no client fetch)
    competitive_alternatives: Optional[list] = None    # B-04: comparators extracted from main LLM call
    expert_domain:          Optional[str]  = None
    expert_name:            Optional[str]  = None
    expert_icon:            Optional[str]  = None
    routing_method:         Optional[str]  = None
    mismatch_warning:       Optional[str]  = None
    sources:                List[dict]     = Field(default_factory=list)   # all cited sources with URLs
    # ── P1 strategic sections (S-01 … S-09) ──────────────────────────────────
    evidence_base:          Optional[dict] = None   # S-01 evidence quality + gap block
    value_driver_ranking:   List[dict]    = Field(default_factory=list)   # S-02
    segment_fit_table:      List[dict]    = Field(default_factory=list)   # S-03 (≥1 Explicit non-target)
    feature_investment_posture: List[dict] = Field(default_factory=list) # S-04 (≥1 Exclude)
    pricing_model_analysis: Optional[dict] = None   # S-05 two-table trade-off
    adversarial_review:     List[dict]    = Field(default_factory=list)   # S-06 critic pass
    positioning_statement:  Optional[str] = None    # S-07 (must include "not" clause)
    strategic_risks:        List[str]     = Field(default_factory=list)   # S-08
    guiding_question:       Optional[str] = None    # S-09
    archetype_violations:   Optional[list] = None   # H-01 banned-vocab hits
    run_manifest:           Optional[dict] = None   # B-05: model/temp/routing metadata for reproducibility
    assumption_ledger:      Optional["AssumptionLedger"] = None  # Part E: quantified market assumptions
    segmentation_tree:      Optional[dict] = None   # D.1: full SegmentNode tree as dict
    triangulation:          Optional[dict] = None   # D.3: three methods + reconciliation
    sensitivity:            Optional[list] = None   # D.7: ranked sensitivity parameters
    axis_decisions:         Optional[dict] = None   # C.1/C.2: selected + rejected axis decisions with reasons
    market_sizing_derivation: Optional[dict] = None  # Part C: persisted buyer-model nodes for editable recompute


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
