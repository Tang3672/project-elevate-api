"""
Phase 2 Data-Layer Table Interfaces  (Build Spec v6, Part 5)
=============================================================
STUB DEFINITIONS ONLY — no ingestion pipeline is built here.

These interfaces define the table schemas that Phase 2 will populate.
Each table has a `commercial_ok: bool = False` quarantine flag.
Data is NOT usable by any algorithm until that flag is set to True by
a human reviewer.

Why `commercial_ok = False` by default:
  Phase 2 data comes from web scraping, partner APIs, and NLP extraction —
  sources that can introduce hallucinated or stale figures.  The quarantine
  flag prevents any unvetted data from flowing into a PI-facing market size
  estimate.  A human data steward must set commercial_ok = True after
  verifying the source, methodology, and recency.

DO NOT BUILD INGESTION CODE HERE.  This file is the contract spec only.
Ingestion will be implemented in Phase 2 once data provenance is confirmed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional


# ──────────────────────────────────────────────────────────────────────────────
# PHASE 2 — TreatmentPathwayGraph
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TreatmentPathwayNode:
    """
    One node in a treatment pathway graph (e.g., 'first-line chemo' → 'second-line IO').
    """
    node_id: str                    # unique node key, e.g. "nsclc_1l_chemo"
    disease_name: str
    line_of_therapy: int            # 1 = first-line, 2 = second-line, etc.
    treatment_label: str            # human-readable, e.g. "Carboplatin + Paclitaxel"
    modality: str                   # "chemotherapy" | "immunotherapy" | "targeted" | "surgery" | etc.
    next_node_ids: List[str]        # IDs of nodes that follow this one
    transition_probability: float   # P(patient moves to this node from prior node)
    median_time_on_treatment_months: float
    source_url: Optional[str]
    extracted_date: Optional[date]
    commercial_ok: bool = False     # QUARANTINE — must be True before use in sizing


@dataclass
class TreatmentPathwayGraph:
    """
    Full treatment pathway graph for a disease.
    Provides the structural backbone for sequence-of-therapy market modeling.
    """
    disease_name: str
    indication: str                 # e.g. "NSCLC stage IIIB-IV"
    source: str                     # e.g. "NCCN Guidelines v2.2024" | "extracted from ClinicalTrials"
    nodes: List[TreatmentPathwayNode]
    last_reviewed_date: Optional[date]
    reviewer: Optional[str]
    commercial_ok: bool = False     # QUARANTINE — entire graph quarantined until reviewed


# ──────────────────────────────────────────────────────────────────────────────
# PHASE 2 — AnalogLaunchRecord
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class AnalogLaunchRecord:
    """
    Observed launch trajectory for a real drug/device/diagnostic.
    Used to calibrate analog engine penetration curves with real data.
    Currently the analog engine uses a static JSON table; Phase 2 will
    replace/augment it with this DB-backed record.
    """
    drug_name: str                  # e.g. "nivolumab"
    brand_name: Optional[str]       # e.g. "Opdivo"
    indication: str                 # e.g. "2L NSCLC"
    approval_year: int
    product_type: str               # maps to OrchestratedResult.product_type
    analog_class: str               # maps to AnalogResult.analog_class
    y1_revenue_usd: Optional[float] # actual Year 1 US net revenue
    y2_revenue_usd: Optional[float]
    y3_revenue_usd: Optional[float]
    peak_revenue_usd: Optional[float]
    peak_year: Optional[int]
    y1_penetration: Optional[float] # fraction of addressable patients treated
    y3_penetration: Optional[float]
    peak_penetration: Optional[float]
    data_source: str                # "10-K", "EvaluatePharma", "IQVIA", etc.
    extracted_date: Optional[date]
    commercial_ok: bool = False     # QUARANTINE


# ──────────────────────────────────────────────────────────────────────────────
# PHASE 2 — ReimbursementCoverage
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ReimbursementCoverage:
    """
    A specific payer's coverage decision for a drug/device/diagnostic.
    Enriches regulatory_pathways.py with actual observed coverage lag data.
    """
    product_name: str               # drug/device name
    payer_name: str                 # "CMS Medicare" | "Aetna" | "BCBS-MA" | etc.
    coverage_type: str              # "formulary" | "LCD" | "NCD" | "NTAP" | "CPT" | "site_license"
    fda_approval_date: Optional[date]
    payer_coverage_date: Optional[date]
    coverage_lag_days: Optional[int]  # computed from above two dates
    prior_auth_required: bool
    step_therapy_required: bool
    coverage_tier: Optional[str]    # "preferred" | "non-preferred" | "specialty" | "restricted"
    notes: Optional[str]
    source_url: Optional[str]
    extracted_date: Optional[date]
    commercial_ok: bool = False     # QUARANTINE


# ──────────────────────────────────────────────────────────────────────────────
# PHASE 2 — TreatmentRateBenchmark
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TreatmentRateBenchmark:
    """
    Observed treatment rate (% of diagnosed patients who receive any treatment)
    for a disease + line of therapy.  Feeds the segment_gate in patient_flow_engine.
    """
    disease_name: str
    line_of_therapy: int
    treatment_rate: float           # 0-1: fraction of eligible patients treated
    confidence_interval_low: Optional[float]
    confidence_interval_high: Optional[float]
    year: int                       # data year
    source: str                     # e.g. "SEER-Medicare", "ASCO abstract 2023"
    source_url: Optional[str]
    extracted_date: Optional[date]
    commercial_ok: bool = False     # QUARANTINE


# ──────────────────────────────────────────────────────────────────────────────
# PHASE 2 — PricingRecord
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class PricingRecord:
    """
    Observed or estimated net price for a drug/device/diagnostic.
    Enriches monetization_engine.py price lookup with real-world net prices
    (list price minus gross-to-net discounts).
    """
    product_name: str
    brand_name: Optional[str]
    indication: str
    price_type: str                 # "wac" | "asp" | "net_price" | "estimated_net"
    price_usd: float                # annual price for chronic; per-episode for acute
    revenue_model: str              # "per_patient_per_year" | "per_episode" | "site_license_annual"
    gross_to_net_pct: Optional[float]   # e.g. 0.35 = 35% discount off WAC
    year: int
    source: str
    source_url: Optional[str]
    extracted_date: Optional[date]
    commercial_ok: bool = False     # QUARANTINE


# ──────────────────────────────────────────────────────────────────────────────
# PHASE 2 — ExpertAssumptionLibrary
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ExpertAssumption:
    """
    A validated assumption contributed by a domain expert or extracted from
    peer-reviewed literature.  These replace LLM-inferred assumptions in
    the confidence_engine when available.
    """
    assumption_key: str             # e.g. "nsclc_2l_io_treatment_rate"
    disease_name: str
    product_type: str
    field_name: str                 # which field this assumption covers (e.g. "segment_gate")
    value: float
    value_low: Optional[float]
    value_high: Optional[float]
    confidence: str                 # "high" | "medium" | "low"
    source_type: str                # "peer_review" | "kol_interview" | "registry" | "claims"
    citation: str
    year: int
    reviewer: Optional[str]
    commercial_ok: bool = False     # QUARANTINE


@dataclass
class ExpertAssumptionLibrary:
    """Container for a set of expert assumptions for one disease/product type."""
    disease_name: str
    product_type: str
    assumptions: List[ExpertAssumption] = field(default_factory=list)
    commercial_ok: bool = False     # QUARANTINE — entire library quarantined until reviewed


# ──────────────────────────────────────────────────────────────────────────────
# PHASE 2 — CompetitivePipelineRecord
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CompetitivePipelineRecord:
    """
    A competing product in the same indication extracted from ClinicalTrials.gov,
    SEC filings, or press releases.  Used to calibrate competitive context in
    analog_engine and apply order-of-entry heuristics.
    """
    target_drug: str                # drug/device being sized by the PI
    competitor_name: str
    sponsor: str
    indication: str
    phase: str                      # "preclinical" | "phase1" | "phase2" | "phase3" | "approved"
    mechanism_of_action: Optional[str]
    estimated_approval_year: Optional[int]
    notes: Optional[str]
    source: str                     # "clinicaltrials.gov" | "10-K" | "press_release"
    source_url: Optional[str]
    extracted_date: Optional[date]
    commercial_ok: bool = False     # QUARANTINE


# ──────────────────────────────────────────────────────────────────────────────
# Registry — all Phase 2 table classes, for introspection / migration tooling
# ──────────────────────────────────────────────────────────────────────────────

PHASE2_TABLE_CLASSES = [
    TreatmentPathwayNode,
    TreatmentPathwayGraph,
    AnalogLaunchRecord,
    ReimbursementCoverage,
    TreatmentRateBenchmark,
    PricingRecord,
    ExpertAssumption,
    ExpertAssumptionLibrary,
    CompetitivePipelineRecord,
]
