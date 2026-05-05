"""
DemandSignal: the canonical schema all data sources normalize into.

Every connector — CDC mortality, CMS hospital quality, openFDA adverse events,
Census insurance gaps, PLACES chronic disease — produces DemandSignals.

These are then embedded and stored in Postgres/pgvector as the demand index
that inventor alignment queries search against.

Design principle: the schema is WIDE enough to capture any source's meaning,
but the minimum required fields are deliberately minimal so all sources can
participate without forcing awkward mappings.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class SignalSource(str, Enum):
    # Tier 4 — Real-time / weekly
    CDC_WASTEWATER        = "cdc_wastewater"
    CDC_FLUVIEW           = "cdc_fluview"
    CDC_NNDSS             = "cdc_nndss"
    CDC_RESP_DASHBOARD    = "cdc_resp_dashboard"

    # Tier 2 — Disease & utilization burden
    CDC_WONDER            = "cdc_wonder"
    CDC_PLACES            = "cdc_places"
    CDC_BRFSS             = "cdc_brfss"
    CMS_HOSPITAL_QUALITY  = "cms_hospital_quality"
    CMS_HCAHPS            = "cms_hcahps"
    CMS_COST_REPORTS      = "cms_cost_reports"
    FDA_ADVERSE_EVENTS    = "fda_adverse_events"
    FDA_DEVICE_EVENTS     = "fda_device_events"
    FDA_RECALLS           = "fda_recalls"
    FDA_DRUG_SHORTAGES    = "fda_drug_shortages"
    CLINICAL_TRIALS       = "clinical_trials"
    PUBMED                = "pubmed"
    NIH_REPORTER          = "nih_reporter"

    # Tier 1 — Population baseline
    CENSUS_ACS            = "census_acs"
    CENSUS_SAHIE          = "census_sahie"
    HRSA_SHORTAGE         = "hrsa_shortage"
    CDC_SVI               = "cdc_svi"

    # Manual hospital submission (Step 1)
    MANUAL                = "manual"


class SignalType(str, Enum):
    # What kind of demand is this signal evidence of?
    DISEASE_BURDEN        = "disease_burden"       # mortality, incidence, prevalence
    CARE_GAP              = "care_gap"             # unmet need, shortage, underserved
    SAFETY_FAILURE        = "safety_failure"       # adverse events, recalls, complications
    UTILIZATION_PATTERN   = "utilization_pattern"  # how care is used / overused / underused
    POPULATION_RISK       = "population_risk"      # demographic risk factors, behaviors
    RESEARCH_TREND        = "research_trend"       # what research/trials are surging
    SUPPLY_SHORTAGE       = "supply_shortage"      # drug / device supply failure
    QUALITY_DEFICIT       = "quality_deficit"      # hospital quality scores, readmissions
    ENVIRONMENTAL_RISK    = "environmental_risk"   # air quality, water, SDOH
    SURVEILLANCE_ALERT    = "surveillance_alert"   # real-time outbreak / wastewater signal


class GeographicScope(str, Enum):
    NATIONAL   = "national"
    REGIONAL   = "regional"      # HHS region, Census division
    STATE      = "state"
    COUNTY     = "county"
    TRACT      = "census_tract"
    ZIPCODE    = "zipcode"
    FACILITY   = "facility"      # specific hospital / clinic
    UNKNOWN    = "unknown"


class DemandSignal(BaseModel):
    """
    Canonical demand signal. Every source connector produces these.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    source: SignalSource
    source_record_id: Optional[str] = None       # original ID in the source system
    signal_type: SignalType
    fetched_at: datetime = Field(default_factory=datetime.utcnow)

    # ── Core content (used for embedding + LLM context) ───────────────────────
    title: str = Field(
        ...,
        description="Short human-readable title of what this signal represents",
        examples=["High diabetes prevalence in Travis County, TX (23.4%)"]
    )
    description: str = Field(
        ...,
        min_length=20,
        description="Rich narrative description — this is what gets embedded. "
                    "Include condition, geography, magnitude, trend, population affected.",
        examples=[
            "Travis County, Texas has a 23.4% diabetes prevalence rate among adults, "
            "significantly above the national average of 11.3%. The rate has increased "
            "2.1 percentage points over the past 5 years. Predominantly affects adults "
            "aged 45-64 and Hispanic/Latino populations. This signals demand for diabetes "
            "management technology, remote monitoring devices, and preventive care platforms."
        ]
    )

    # ── Categorization (links to Health_Innovation_Categories taxonomy) ────────
    condition_or_topic: Optional[str] = None      # e.g. "Type 2 Diabetes", "Sepsis"
    innovation_category_hint: Optional[str] = None  # SOFTWARE / HARDWARE / SERVICE / etc.
    icd10_codes: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)

    # ── Geographic context ────────────────────────────────────────────────────
    geographic_scope: GeographicScope = GeographicScope.UNKNOWN
    country: str = "US"
    state_code: Optional[str] = None              # 2-letter FIPS or abbreviation
    county_fips: Optional[str] = None             # 5-digit FIPS
    census_tract: Optional[str] = None            # 11-digit FIPS
    location_name: Optional[str] = None           # human-readable: "Austin, TX"

    # ── Demographic context ───────────────────────────────────────────────────
    age_group: Optional[str] = None               # e.g. "65+", "18-44", "pediatric"
    sex: Optional[str] = None                     # "male", "female", "all"
    race_ethnicity: Optional[str] = None
    income_level: Optional[str] = None            # "low", "middle", "high", or % FPL
    insurance_status: Optional[str] = None        # "uninsured", "medicaid", "all"

    # ── Quantitative signal strength ──────────────────────────────────────────
    magnitude: Optional[float] = None             # raw metric value (rate, count, score)
    magnitude_unit: Optional[str] = None          # "per 100k", "percent", "count", "score"
    national_average: Optional[float] = None      # for comparison context
    trend_direction: Optional[str] = None         # "increasing", "decreasing", "stable"
    trend_magnitude: Optional[float] = None       # % change per year

    # ── Temporal ──────────────────────────────────────────────────────────────
    data_year: Optional[int] = None               # year of the underlying data
    data_period: Optional[str] = None             # e.g. "2022-2024", "Week 4 2025"
    data_freshness_days: Optional[int] = None     # how old is the source data?

    # ── Source metadata (for provenance and confidence) ───────────────────────
    source_url: Optional[str] = None
    confidence_score: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="How reliable is this signal? 1.0=definitive federal dataset, "
                    "0.5=modeled estimate, 0.3=scraped/unverified"
    )
    raw_data: Optional[Dict[str, Any]] = None     # original source record (for audit)
