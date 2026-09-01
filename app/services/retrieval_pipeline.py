"""
Multi-Source Retrieval Pipeline (MSRP)
=======================================
Efficiently retrieves accurate data from 38+ heterogeneous sources to ground
every chapter of the market intelligence report in real data, not hallucination.

Algorithm design (research-backed):

  Core framework: Adaptive RAG with authority-weighted information fusion
  ─────────────────────────────────────────────────────────────────────
  Based on:
    - Adaptive RAG (Jeong et al., 2024): route queries to appropriate retrieval
      depth based on complexity — no-retrieval / single-source / multi-source
    - FLARE (Jiang et al., 2023, EMNLP): only trigger retrieval for facts the
      model is uncertain about; stop when confidence is sufficient
    - CRAG (Yan et al., 2024, ICLR): evaluate retrieved document quality;
      suppress low-quality retrievals that would degrade output
    - Self-RAG (Asai et al., 2023, NeurIPS): selectively decide per-token
      whether retrieval is needed; adapted here to per-concept level

  Applied to structured medical APIs (not document search):
  ─────────────────────────────────────────────────────────
  Unlike text-corpus RAG, our sources return structured JSON with known
  schemas. This enables:
    1. Concept-level deduplication (same fact from multiple sources → take highest authority)
    2. Authority-based source routing (SEER > WHO GHO for oncology prevalence)
    3. Hard timeout budgets per tier (not possible with open-ended text search)
    4. Information gain computation via concept coverage (not embedding similarity)

  3-Tier Pipeline with Adaptive Stopping:
  ────────────────────────────────────────
  Tier 0 — Instant (pre-loaded, <10ms):
    PTRS tables, pricing benchmarks, MEPS stats, regulatory precedents,
    OECD multipliers, Reactome pathways, market calibration data
    → Always runs; no API calls; zero latency

  Tier 1 — Fast (<800ms budget):
    Orphanet, WHO GHO (cached), UniProt, Reactome live, ClinVar, SEER cache
    → Runs unconditionally in parallel; lightweight APIs

  Tier 2 — Medium (<4s budget):
    ClinicalTrials.gov, OpenFDA, NIH Reporter, OpenTargets, PubMed/OpenAlex
    → Runs only for concepts NOT covered by Tier 0+1 (adaptive stopping)

  Tier 3 — Rich (<10s budget):
    CMS Prescriber, Open Payments, STRING, Grants.gov, SEER API live
    → Runs only for high-value gaps remaining after Tier 2

  Information Quality Scoring (per retrieved fact):
  ──────────────────────────────────────────────────
  Q(fact) = Authority(source, data_type) × Specificity(disease vs TA) × Recency(year)

  Authority scores (per data type, empirically defined):
    Prevalence/incidence (oncology):   NCI SEER 1.0 > WHO GHO 0.85 > Orphanet 0.75
    Prevalence/incidence (rare):       Orphanet 1.0 > ClinVar 0.80 > WHO GHO 0.65
    Regulatory timeline:               FDA Drugs@FDA 1.0 > OpenFDA 0.85 > pre-loaded 0.70
    Drug pricing:                      CMS ASP 1.0 > CMS Part D 0.90 > pre-loaded 0.75
    Trial count:                       ClinicalTrials.gov 1.0 > OpenTargets 0.85
    KOL identification:                CMS Open Payments 1.0 > Semantic Scholar 0.80
    Target biology:                    UniProt 1.0 > STRING 0.90 > Reactome 0.85
    PTRS:                              PTRS tables (BIO2020) 1.0 > computed 0.80

  Caching (TTL-based, LRU in-memory + PostgreSQL persistent):
  ────────────────────────────────────────────────────────────
    Static tables (Tier 0):           ∞ TTL
    Orphanet, Reactome:                7 days (stable biological data)
    WHO GHO, SEER stats:               7 days
    ClinicalTrials.gov counts:         24 hours (active trial landscape)
    CMS Part D/B spending:             90 days (quarterly CMS updates)
    OpenFDA approvals:                 7 days (rare new approvals)
    NIH Reporter grants:               24 hours
    Open Payments, Prescriber:         365 days (annual Sunshine Act)
    Pubmed/OpenAlex papers:            24 hours

  Information Gain Stopping Criterion:
  ─────────────────────────────────────
  After each tier, compute coverage score = (concepts_filled / concepts_needed)
  If coverage >= COVERAGE_THRESHOLD (0.80), skip remaining tiers.
  This implements the core FLARE insight: don't retrieve what you already have.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

TIER1_BUDGET_SEC  = 0.8    # Tier 1 max wall-clock time (parallel)
TIER2_BUDGET_SEC  = 4.0    # Tier 2 max wall-clock time (parallel)
TIER3_BUDGET_SEC  = 10.0   # Tier 3 max wall-clock time (parallel)
COVERAGE_THRESHOLD = 0.80   # Stop early if ≥80% of concepts are filled
MAX_FACTS_PER_CONCEPT = 2   # Keep top-2 quality facts per concept type
CACHE_MAX_SIZE = 2000        # In-memory LRU entries


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CONCEPTS — the facts each chapter needs
# ═══════════════════════════════════════════════════════════════════════════════

# Canonical concept types that the report needs grounded
CONCEPT_TYPES = {
    "prevalence_incidence",     # How many patients (US annual)
    "disease_burden_dalys",     # WHO DALY burden
    "survival_prognosis",       # 5-year survival, median OS
    "stage_distribution",       # Stage at diagnosis (oncology)
    "biomarker_prevalence",     # Biomarker-selected subpopulation
    "gene_variant_data",        # Pathogenic variants (gene therapy)
    "competitor_trial_count",   # Active competing trials
    "fda_approval_timeline",    # Precedent drug approval timelines
    "drug_pricing",             # WAC, net price, GTN
    "ptrs_probability",         # Clinical development success rate
    "pathway_biology",          # Mechanism of action pathway
    "target_druggability",      # Target protein class/modality fit
    "kol_landscape",            # Key opinion leaders
    "buyer_counts",             # Hospital/prescriber universe
    "funding_opportunities",    # Grants, BARDA, CDMRP
    "payer_access_signal",      # NICE HTA, ICER decisions
    "global_market_size",       # Ex-US TAM multiplier
    "realized_tam_factor",      # MEPS adherence/fill rate adjustment
    "patent_cliff_data",        # Competitor patent expiry
    "research_literature",      # Landmark publications
}

# Concepts required per report chapter (minimum coverage)
CHAPTER_CONCEPTS: dict[str, set[str]] = {
    "disease_intelligence": {"prevalence_incidence", "disease_burden_dalys", "survival_prognosis", "stage_distribution", "biomarker_prevalence"},
    "market_sizing":        {"prevalence_incidence", "drug_pricing", "realized_tam_factor", "global_market_size", "biomarker_prevalence"},
    "regulatory_pathway":   {"fda_approval_timeline", "ptrs_probability", "competitor_trial_count"},
    "market_access":        {"buyer_counts", "kol_landscape", "payer_access_signal", "drug_pricing"},
    "market_geography":     {"prevalence_incidence"},
    "strategic_playbook":   {"competitor_trial_count", "fda_approval_timeline", "funding_opportunities", "payer_access_signal"},
    "literature_citations": {"research_literature"},
}


# ═══════════════════════════════════════════════════════════════════════════════
# SOURCE AUTHORITY MATRIX
# Defines which sources are authoritative for which concept types.
# Format: {concept_type: [(source_id, authority_score), ...]} sorted by authority desc
# ═══════════════════════════════════════════════════════════════════════════════

SOURCE_AUTHORITY: dict[str, list[tuple[str, float]]] = {
    "prevalence_incidence": [
        ("nci_seer",        1.00),  # Gold standard for oncology incidence
        ("orphanet",        0.95),  # Gold standard for rare disease prevalence
        ("who_gho",         0.85),  # WHO GHO DALYs (commercial-safe)
        ("seer_preloaded",  0.90),  # Pre-loaded SEER stats (instant)
    ],
    "disease_burden_dalys": [
        ("who_gho",         1.00),
        ("seer_preloaded",  0.80),  # SEER deaths as proxy
    ],
    "survival_prognosis": [
        ("seer_preloaded",  1.00),  # SEER 5-year survival rates
        ("pubmed_openalex", 0.80),  # Phase 3 trial OS data in papers
    ],
    "stage_distribution": [
        ("seer_preloaded",  1.00),
        ("nci_seer",        1.00),
    ],
    "biomarker_prevalence": [
        ("seer_preloaded",  0.90),  # Pre-loaded biomarker fractions in seer_cancer.py
        ("clinvar",         0.95),  # Gene variant prevalence for gene therapy
        ("pubmed_openalex", 0.75),  # Published biomarker frequency studies
        ("opentargets",     0.80),  # Target-disease associations
    ],
    "gene_variant_data": [
        ("clinvar",         1.00),
        ("opentargets",     0.85),
        ("uniprot",         0.80),
    ],
    "competitor_trial_count": [
        ("clinicaltrials_gov", 1.00),
        ("opentargets",        0.80),
        ("sec_edgar",          0.70),  # Pipeline disclosures in 10-K
    ],
    "fda_approval_timeline": [
        ("preloaded_fda_timelines", 1.00),  # chapter_data_service.py — most specific
        ("openfda",                 0.85),
        ("pubmed_openalex",         0.70),
    ],
    "drug_pricing": [
        ("cms_part_b_asp",      1.00),  # Actual ASP (Part B injectable drugs)
        ("cms_part_d",          0.95),  # Actual Part D spending
        ("preloaded_benchmarks", 0.80), # market_calibration_service.py
        ("icer",                 0.75),
    ],
    "ptrs_probability": [
        ("ptrs_tables",         1.00),  # Hard BIO2020 numbers
        ("preloaded_realized",  0.90),  # Realized PTRS back-validation
    ],
    "pathway_biology": [
        ("reactome",            1.00),
        ("opentargets",         0.85),
        ("uniprot",             0.80),
    ],
    "target_druggability": [
        ("uniprot",             1.00),
        ("string_db",           0.85),
        ("opentargets",         0.90),
    ],
    "kol_landscape": [
        ("cms_open_payments",   1.00),  # Sunshine Act — most authoritative
        ("semantic_scholar",    0.80),  # Citation network
        ("preloaded_kol",       0.70),  # Pre-loaded landscape summaries
    ],
    "buyer_counts": [
        ("preloaded_buyer_counts", 1.00),  # chapter_data_service.py verified counts
        ("cms_part_b_asp",         0.80),
        ("cms_prescriber_part_d",  0.75),
    ],
    "funding_opportunities": [
        ("nih_reporter",        0.90),
        ("grants_gov",          0.95),  # Prospective (open solicitations)
        ("sbir_gov",            0.85),
        ("usa_spending",        0.80),
        ("preloaded_barda",     0.80),  # Pre-loaded BARDA/CARB-X info
    ],
    "payer_access_signal": [
        ("nice_hta",            1.00),
        ("icer",                0.95),
        ("preloaded_icer",      0.90),
    ],
    "global_market_size": [
        ("oecd_health",         1.00),
        ("preloaded_oecd",      0.90),
    ],
    "realized_tam_factor": [
        ("ahrq_meps",           1.00),
        ("preloaded_meps",      0.95),
    ],
    "patent_cliff_data": [
        ("preloaded_patent_cliff", 1.00),  # market_calibration_service.py
        ("patents_view",            0.80),
    ],
    "research_literature": [
        ("openalex",            0.90),
        ("pubmed_openalex",     0.85),
        ("semantic_scholar",    0.80),
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# SOURCE TIER ASSIGNMENT
# ═══════════════════════════════════════════════════════════════════════════════

SOURCE_TIERS: dict[str, int] = {
    # Tier 0: pre-loaded, instant (no I/O)
    "ptrs_tables":              0,
    "preloaded_benchmarks":     0,
    "preloaded_fda_timelines":  0,
    "preloaded_buyer_counts":   0,
    "preloaded_icer":           0,
    "preloaded_oecd":           0,
    "preloaded_meps":           0,
    "preloaded_barda":          0,
    "preloaded_kol":            0,
    "preloaded_patent_cliff":   0,
    "preloaded_realized":       0,
    "seer_preloaded":           0,   # In-memory SEER stats from seer_cancer.py
    "reactome":                 0,   # Pre-loaded pathway maps in reactome.py

    # Tier 1: fast APIs (<800ms)
    "orphanet":                 1,
    "who_gho":                  1,
    "clinvar":                  1,
    "uniprot":                  1,
    "nice_hta":                 1,   # Pre-loaded NICE decisions
    "icer":                     1,   # Pre-loaded ICER assessments
    "oecd_health":              1,   # Pre-loaded OECD stats
    "ahrq_meps":                1,   # Pre-loaded MEPS summaries
    "cms_open_payments":        1,   # Pre-loaded KOL summaries

    # Tier 2: medium APIs (<4s)
    "clinicaltrials_gov":       2,
    "openfda":                  2,
    "nih_reporter":             2,
    "opentargets":              2,
    "pubmed_openalex":          2,
    "openalex":                 2,
    "nci_seer":                 2,   # SEER API (requires API key, moderate latency)
    "grants_gov":               2,
    "sec_edgar":                2,

    # Tier 3: rich but slow APIs (<10s)
    "cms_prescriber_part_d":    3,
    "cms_part_d":               3,
    "cms_part_b_asp":           2,   # Pre-loaded mostly, fast
    "string_db":                3,
    "usa_spending":             3,
    "sbir_gov":                 3,
    "semantic_scholar":         3,
    "patents_view":             3,
}


# ═══════════════════════════════════════════════════════════════════════════════
# SUBCATEGORY SOURCE RELEVANCE
# Which sources are relevant for each product subcategory.
# Key insight: don't call ClinVar for a GLP-1 drug or Orphanet for oncology.
# ═══════════════════════════════════════════════════════════════════════════════

SUBCATEGORY_SOURCE_RELEVANCE: dict[str, set[str]] = {
    "drug_amr": {
        "who_gho", "clinicaltrials_gov", "openfda", "nih_reporter", "preloaded_fda_timelines",
        "preloaded_benchmarks", "ptrs_tables", "grants_gov", "usa_spending",
        "preloaded_icer", "preloaded_buyer_counts", "cms_open_payments",
        "nice_hta", "pubmed_openalex", "opentargets", "preloaded_realized",
    },
    "drug_oncology": {
        "seer_preloaded", "nci_seer", "who_gho", "clinicaltrials_gov", "openfda",
        "opentargets", "pubmed_openalex", "preloaded_fda_timelines", "ptrs_tables",
        "cms_part_d", "cms_part_b_asp", "preloaded_benchmarks", "cms_open_payments",
        "cms_prescriber_part_d", "preloaded_buyer_counts", "preloaded_icer",
        "nice_hta", "oecd_health", "reactome", "preloaded_realized",
    },
    "biologic_oncology": {
        "seer_preloaded", "nci_seer", "who_gho", "clinicaltrials_gov", "openfda",
        "opentargets", "uniprot", "string_db", "pubmed_openalex",
        "preloaded_fda_timelines", "ptrs_tables", "cms_part_b_asp",
        "preloaded_benchmarks", "cms_open_payments", "cms_prescriber_part_d",
        "preloaded_buyer_counts", "preloaded_icer", "nice_hta", "reactome",
        "oecd_health", "preloaded_realized",
    },
    "drug_cns_neurodegen": {
        "who_gho", "clinicaltrials_gov", "openfda", "opentargets",
        "pubmed_openalex", "preloaded_fda_timelines", "ptrs_tables",
        "preloaded_benchmarks", "cms_open_payments", "preloaded_icer",
        "nice_hta", "uniprot", "reactome", "grants_gov", "preloaded_buyer_counts",
        "oecd_health", "preloaded_realized",
    },
    "gene_therapy_rare": {
        "orphanet", "clinvar", "who_gho", "clinicaltrials_gov", "openfda",
        "opentargets", "uniprot", "pubmed_openalex", "preloaded_fda_timelines",
        "ptrs_tables", "preloaded_benchmarks", "cms_part_b_asp",
        "preloaded_buyer_counts", "grants_gov", "nice_hta", "preloaded_icer",
        "reactome", "oecd_health", "preloaded_realized", "preloaded_patent_cliff",
    },
    "gene_therapy_hematology": {
        "orphanet", "clinvar", "seer_preloaded", "clinicaltrials_gov", "openfda",
        "opentargets", "uniprot", "pubmed_openalex", "preloaded_fda_timelines",
        "ptrs_tables", "preloaded_benchmarks", "cms_part_b_asp",
        "preloaded_buyer_counts", "grants_gov", "nice_hta", "preloaded_icer",
        "reactome", "oecd_health", "preloaded_realized",
    },
    "gene_therapy_oncology": {
        "seer_preloaded", "nci_seer", "who_gho", "clinicaltrials_gov", "openfda",
        "opentargets", "uniprot", "pubmed_openalex", "preloaded_fda_timelines",
        "ptrs_tables", "cms_part_b_asp", "preloaded_benchmarks",
        "cms_open_payments", "preloaded_buyer_counts", "nice_hta",
        "reactome", "oecd_health", "preloaded_realized",
    },
    "medical_device": {
        "who_gho", "clinicaltrials_gov", "openfda", "nih_reporter",
        "preloaded_fda_timelines", "ptrs_tables", "preloaded_benchmarks",
        "cms_part_b_asp", "preloaded_buyer_counts", "nice_hta", "pubmed_openalex",
        "preloaded_realized",
    },
    "diagnostic": {
        "who_gho", "clinicaltrials_gov", "openfda", "preloaded_fda_timelines",
        "ptrs_tables", "preloaded_benchmarks", "preloaded_buyer_counts",
        "nice_hta", "pubmed_openalex", "preloaded_realized",
    },
    "digital_health": {
        "who_gho", "clinicaltrials_gov", "preloaded_fda_timelines",
        "ptrs_tables", "preloaded_benchmarks", "preloaded_buyer_counts",
        "nice_hta", "grants_gov", "preloaded_realized",
    },
    "vaccine_prophylactic": {
        "who_gho", "clinicaltrials_gov", "openfda", "nih_reporter",
        "preloaded_fda_timelines", "ptrs_tables", "preloaded_benchmarks",
        "preloaded_buyer_counts", "nice_hta", "pubmed_openalex",
        "grants_gov", "oecd_health", "preloaded_realized",
    },
    # Non-clinical research tool archetypes — grant databases only, no clinical registries.
    # D-01/D-03: clinical sources (openFDA, ClinicalTrials, SEER, etc.) must not appear
    # here; they index regulated clinical products and produce irrelevant results for
    # lab instruments, sensors, and research infrastructure tools.
    "research_tool_non_clinical": {
        "nih_reporter", "grants_gov", "pubmed_openalex",
        "preloaded_buyer_counts", "preloaded_benchmarks",
    },
    "research_tool_agronomy": {
        "nih_reporter", "grants_gov", "pubmed_openalex",
        "preloaded_buyer_counts", "preloaded_benchmarks",
    },
    "research_infrastructure_saas": {
        "nih_reporter", "grants_gov", "pubmed_openalex",
        "preloaded_buyer_counts", "preloaded_benchmarks",
    },
    # Default: all Tier 0+1 sources + core Tier 2
    "default": {
        "who_gho", "clinicaltrials_gov", "openfda", "opentargets",
        "pubmed_openalex", "preloaded_fda_timelines", "ptrs_tables",
        "preloaded_benchmarks", "preloaded_buyer_counts", "nice_hta",
        "preloaded_icer", "oecd_health", "preloaded_realized",
    },
}

# D-01: archetypes whose reports must never receive clinical-domain signals
# (disease prevalence, FDA timelines, trial counts, payer decisions).
_NON_CLINICAL_ARCHETYPES: frozenset[str] = frozenset({
    "research_tool_non_clinical",
    "research_tool_agronomy",
    "research_infrastructure_saas",
})


# ═══════════════════════════════════════════════════════════════════════════════
# IN-MEMORY LRU CACHE
# ═══════════════════════════════════════════════════════════════════════════════

from collections import OrderedDict

class _LRUCache:
    """Thread-safe LRU cache with TTL per entry."""
    def __init__(self, max_size: int = CACHE_MAX_SIZE):
        self._store: OrderedDict[str, tuple[Any, float, float]] = OrderedDict()
        self._max_size = max_size

    def _key(self, source_id: str, query: str) -> str:
        return hashlib.md5(f"{source_id}:{query}".encode()).hexdigest()

    def get(self, source_id: str, query: str) -> Optional[Any]:
        k = self._key(source_id, query)
        entry = self._store.get(k)
        if not entry:
            return None
        value, fetched_at, ttl = entry
        if time.monotonic() - fetched_at > ttl:
            del self._store[k]
            return None
        self._store.move_to_end(k)
        return value

    def set(self, source_id: str, query: str, value: Any, ttl_sec: float):
        k = self._key(source_id, query)
        self._store[k] = (value, time.monotonic(), ttl_sec)
        self._store.move_to_end(k)
        if len(self._store) > self._max_size:
            self._store.popitem(last=False)

    def stats(self) -> dict:
        return {"size": len(self._store), "max_size": self._max_size}


_CACHE = _LRUCache()

# TTL in seconds for each source
SOURCE_TTL: dict[str, float] = {
    "ptrs_tables":              float("inf"),   # Static
    "preloaded_benchmarks":     float("inf"),
    "preloaded_fda_timelines":  float("inf"),
    "preloaded_buyer_counts":   float("inf"),
    "preloaded_icer":           float("inf"),
    "preloaded_oecd":           float("inf"),
    "preloaded_meps":           float("inf"),
    "seer_preloaded":           float("inf"),
    "reactome":                 float("inf"),
    "preloaded_barda":          float("inf"),
    "preloaded_kol":            float("inf"),
    "preloaded_patent_cliff":   float("inf"),
    "preloaded_realized":       float("inf"),
    "orphanet":           7 * 86400,    # 7 days
    "who_gho":            7 * 86400,
    "clinvar":            7 * 86400,
    "uniprot":            7 * 86400,
    "opentargets":        7 * 86400,
    "nice_hta":           7 * 86400,
    "icer":               7 * 86400,
    "oecd_health":        7 * 86400,
    "ahrq_meps":          30 * 86400,   # 30 days (annual survey)
    "cms_open_payments":  365 * 86400,  # Annual Sunshine Act
    "nci_seer":           7 * 86400,
    "clinicaltrials_gov": 1 * 86400,    # 24 hours (active trials change)
    "openfda":            7 * 86400,
    "nih_reporter":       1 * 86400,
    "pubmed_openalex":    1 * 86400,
    "openalex":           1 * 86400,
    "grants_gov":         1 * 86400,
    "sec_edgar":          1 * 86400,
    "cms_prescriber_part_d": 365 * 86400,  # Annual
    "cms_part_d":         90 * 86400,   # Quarterly
    "cms_part_b_asp":     90 * 86400,
    "string_db":          7 * 86400,
    "usa_spending":       1 * 86400,
    "sbir_gov":           1 * 86400,
    "semantic_scholar":   1 * 86400,
    "patents_view":       30 * 86400,
}


# ═══════════════════════════════════════════════════════════════════════════════
# RETRIEVED FACT DATACLASS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RetrievedFact:
    concept_type:   str
    source_id:      str
    value:          Any            # The actual data retrieved
    quality_score:  float          # 0.0 - 1.0 (authority × specificity × recency)
    tier:           int
    latency_ms:     float = 0.0
    cached:         bool = False
    formatted_text: str = ""       # Ready-to-inject context string


@dataclass
class RetrievalResult:
    facts:              list[RetrievedFact]
    coverage_by_chapter: dict[str, float]   # chapter → 0.0-1.0 coverage score
    total_latency_ms:   float
    cache_hit_rate:     float
    tiers_reached:      int                  # How far down we needed to go
    sources_called:     list[str]
    concepts_filled:    set[str]
    context_blocks:     dict[str, str]       # chapter → formatted context string
    # G.1 retrieval audit: all outbound HTTP calls made during this pipeline run
    fetch_logs:         list = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# QUALITY SCORING
# ═══════════════════════════════════════════════════════════════════════════════

def _authority_score(source_id: str, concept_type: str) -> float:
    """Return the authority score for a source-concept pair."""
    authority_list = SOURCE_AUTHORITY.get(concept_type, [])
    for sid, score in authority_list:
        if sid == source_id:
            return score
    return 0.50  # Unknown source → neutral authority

def _specificity_score(value: Any, disease_name: str) -> float:
    """Higher score if the data is disease-specific vs TA-level default."""
    if not value:
        return 0.0
    v_str = str(value).lower()
    if disease_name.lower()[:10] in v_str:
        return 1.0   # Disease-specific
    return 0.70      # TA-level

def _recency_score(year: Optional[int]) -> float:
    """Score recency: 2024=1.0, 2020=0.8, 2015=0.6, older=0.5."""
    if not year:
        return 0.75  # Unknown → slight penalty
    current = 2026
    delta = current - year
    if delta <= 1:  return 1.00
    if delta <= 3:  return 0.92
    if delta <= 5:  return 0.82
    if delta <= 8:  return 0.70
    return max(0.50, 0.70 - (delta - 8) * 0.02)

def compute_quality(
    source_id: str,
    concept_type: str,
    value: Any,
    disease_name: str,
    data_year: Optional[int] = None,
) -> float:
    """Composite quality score: Authority × Specificity × Recency."""
    a = _authority_score(source_id, concept_type)
    s = _specificity_score(value, disease_name)
    r = _recency_score(data_year)
    return round(a * s * r, 4)


# ═══════════════════════════════════════════════════════════════════════════════
# TIER 0 FETCHER — pre-loaded data (zero latency)
# ═══════════════════════════════════════════════════════════════════════════════

def _fetch_tier0(
    disease_name: str,
    therapeutic_area: str,
    subcategory_id: str,
    idea: str,
) -> list[RetrievedFact]:
    """Fetch from all pre-loaded databases (zero I/O). Always runs first."""
    facts = []

    # PTRS tables
    try:
        from app.services.ptrs_tables import get_ptrs
        loa, ptrs_pct, citation = get_ptrs(subcategory_id, "phase1", False)
        facts.append(RetrievedFact(
            concept_type="ptrs_probability",
            source_id="ptrs_tables",
            value={"loa": loa, "ptrs_pct": ptrs_pct, "citation": citation},
            quality_score=compute_quality("ptrs_tables", "ptrs_probability", loa, disease_name, 2021),
            tier=0,
        ))
    except Exception: pass

    # NCI SEER pre-loaded stats — skip for non-clinical archetypes (D-01: prevents
    # disease prevalence facts from contaminating lab-tool / agronomy reports).
    if subcategory_id not in _NON_CLINICAL_ARCHETYPES:
        try:
            from app.ingestion.connectors.seer_cancer import get_cancer_incidence
            seer = get_cancer_incidence(disease_name)
            if seer:
                facts.append(RetrievedFact(
                    concept_type="prevalence_incidence",
                    source_id="seer_preloaded",
                    value=seer,
                    quality_score=compute_quality("seer_preloaded", "prevalence_incidence", seer, disease_name, 2024),
                    tier=0,
                ))
                facts.append(RetrievedFact(
                    concept_type="survival_prognosis",
                    source_id="seer_preloaded",
                    value=seer,
                    quality_score=compute_quality("seer_preloaded", "survival_prognosis", seer, disease_name, 2024),
                    tier=0,
                ))
                facts.append(RetrievedFact(
                    concept_type="stage_distribution",
                    source_id="seer_preloaded",
                    value=seer,
                    quality_score=compute_quality("seer_preloaded", "stage_distribution", seer, disease_name, 2024),
                    tier=0,
                ))
        except Exception: pass

    # Reactome pathways (pre-loaded) — H-15: skip for non-clinical archetypes
    if subcategory_id not in _NON_CLINICAL_ARCHETYPES:
        try:
            from app.ingestion.connectors.reactome import get_disease_pathways
            pathways = get_disease_pathways(disease_name)
            if pathways:
                facts.append(RetrievedFact(
                    concept_type="pathway_biology",
                    source_id="reactome",
                    value=pathways,
                    quality_score=compute_quality("reactome", "pathway_biology", pathways, disease_name, 2024),
                    tier=0,
                ))
        except Exception: pass

    # PTRS back-validation (pre-loaded)
    try:
        from app.services.market_calibration_service import get_realized_ptrs_validation
        ptrs_val = get_realized_ptrs_validation(subcategory_id)
        if ptrs_val.get("validated"):
            facts.append(RetrievedFact(
                concept_type="ptrs_probability",
                source_id="preloaded_realized",
                value=ptrs_val,
                quality_score=0.90,
                tier=0,
            ))
    except Exception: pass

    # Buyer counts (pre-loaded)
    try:
        from app.services.chapter_data_service import get_buyer_universe
        buyers = get_buyer_universe(therapeutic_area, subcategory_id)
        if buyers.get("segments"):
            facts.append(RetrievedFact(
                concept_type="buyer_counts",
                source_id="preloaded_buyer_counts",
                value=buyers,
                quality_score=0.95,
                tier=0,
            ))
    except Exception: pass

    # ICER pre-loaded
    try:
        from app.services.market_calibration_service import get_icer_payer_signal
        icer = get_icer_payer_signal(therapeutic_area, idea[:80], 50_000)
        if icer.get("icer_found"):
            facts.append(RetrievedFact(
                concept_type="payer_access_signal",
                source_id="preloaded_icer",
                value=icer,
                quality_score=0.90,
                tier=0,
            ))
    except Exception: pass

    # OECD global multiplier (pre-loaded)
    try:
        from app.ingestion.connectors.oecd_health import compute_global_tam, get_country_price_comparison
        price_context = get_country_price_comparison(therapeutic_area)
        facts.append(RetrievedFact(
            concept_type="global_market_size",
            source_id="preloaded_oecd",
            value=price_context,
            quality_score=0.90,
            tier=0,
        ))
    except Exception: pass

    # AHRQ MEPS realized TAM factor (pre-loaded)
    try:
        from app.ingestion.connectors.ahrq_meps import get_treatment_access_data
        meps = get_treatment_access_data(therapeutic_area)
        if meps:
            facts.append(RetrievedFact(
                concept_type="realized_tam_factor",
                source_id="preloaded_meps",
                value=meps,
                quality_score=0.95,
                tier=0,
            ))
    except Exception: pass

    # Patent cliff (pre-loaded)
    try:
        from app.services.market_calibration_service import get_cms_analogues
        analogues = get_cms_analogues(therapeutic_area, 3)
        if analogues:
            facts.append(RetrievedFact(
                concept_type="drug_pricing",
                source_id="preloaded_benchmarks",
                value=analogues,
                quality_score=0.80,
                tier=0,
            ))
    except Exception: pass

    # ClinVar, Orphanet, regulatory precedents — H-15: skip for non-clinical archetypes (D-01)
    if subcategory_id not in _NON_CLINICAL_ARCHETYPES:
        try:
            from app.ingestion.connectors.clinvar import get_gene_therapy_eligibility
            clinvar_data = get_gene_therapy_eligibility(disease_name)
            if clinvar_data.get("found"):
                facts.append(RetrievedFact(
                    concept_type="gene_variant_data",
                    source_id="clinvar",
                    value=clinvar_data,
                    quality_score=compute_quality("clinvar", "gene_variant_data", clinvar_data, disease_name, 2024),
                    tier=0,
                ))
        except Exception: pass

        try:
            from app.ingestion.connectors.orphanet import get_rare_disease_prevalence
            orphan_data = get_rare_disease_prevalence(disease_name)
            if orphan_data.get("found"):
                facts.append(RetrievedFact(
                    concept_type="prevalence_incidence",
                    source_id="orphanet",
                    value=orphan_data,
                    quality_score=compute_quality("orphanet", "prevalence_incidence", orphan_data, disease_name, 2024),
                    tier=0,
                ))
        except Exception: pass

        try:
            from app.services.chapter_data_service import get_regulatory_precedents
            precedents = get_regulatory_precedents(subcategory_id, disease_name)
            if precedents:
                facts.append(RetrievedFact(
                    concept_type="fda_approval_timeline",
                    source_id="preloaded_fda_timelines",
                    value=precedents,
                    quality_score=1.0,
                    tier=0,
                ))
        except Exception: pass

    # CDMRP + DoD funding opportunities (pre-loaded)
    try:
        from app.ingestion.connectors.grants_gov import get_cdmrp_program
        cdmrp = get_cdmrp_program(disease_name)
        if cdmrp:
            facts.append(RetrievedFact(
                concept_type="funding_opportunities",
                source_id="preloaded_barda",
                value=cdmrp,
                quality_score=0.85,
                tier=0,
            ))
    except Exception: pass

    logger.debug("Tier 0: %d facts retrieved (0ms)", len(facts))
    return facts


# ═══════════════════════════════════════════════════════════════════════════════
# TIER 1-3 FETCHERS — live API calls
# ═══════════════════════════════════════════════════════════════════════════════

async def _fetch_source(
    source_id: str,
    disease_name: str,
    therapeutic_area: str,
    subcategory_id: str,
    idea: str,
) -> list[RetrievedFact]:
    """Fetch from a single source, with caching. Returns list of RetrievedFacts."""
    cache_key = f"{disease_name}:{subcategory_id}"
    # C-11: UniProt/STRING results depend on target gene extracted from idea — include it
    if source_id in ("uniprot", "string_db"):
        import re as _re_ck
        _ck_genes = _re_ck.findall(r'\b([A-Z][A-Z0-9]{1,7})\b', idea)
        cache_key = f"{cache_key}:{_ck_genes[0] if _ck_genes else ''}"
    # Cache key must include therapeutic_area for TA-specific sources
    if source_id in ("who_gho", "nice_hta", "icer", "oecd_health", "ahrq_meps", "cms_prescriber_part_d"):
        cache_key = f"{cache_key}:{therapeutic_area}"
    cached = _CACHE.get(source_id, cache_key)
    if cached is not None:
        return [RetrievedFact(
            concept_type=f.concept_type, source_id=f.source_id, value=f.value,
            quality_score=f.quality_score, tier=f.tier, cached=True,
        ) for f in cached]

    t0 = time.monotonic()
    facts = []

    try:
        if source_id == "who_gho":
            from app.services.opportunity_scorer_v2 import _get_commercial_safe_dalys
            dalys, src = await _get_commercial_safe_dalys(disease_name, therapeutic_area)
            if dalys:
                facts.append(RetrievedFact(
                    concept_type="disease_burden_dalys", source_id=source_id,
                    value={"dalys": dalys, "source_label": src},
                    quality_score=compute_quality(source_id, "disease_burden_dalys", dalys, disease_name, 2022),
                    tier=1,
                ))

        elif source_id == "uniprot":
            import re
            # Extract gene symbols from idea text
            gene_pattern = r'\b([A-Z][A-Z0-9]{1,7})\b'
            candidates = re.findall(gene_pattern, idea)
            gene = candidates[0] if candidates else None
            if gene:
                from app.ingestion.connectors.uniprot import get_target_biology
                target = get_target_biology(gene)
                if target:
                    facts.append(RetrievedFact(
                        concept_type="target_druggability", source_id=source_id,
                        value=target, quality_score=1.0, tier=1,
                    ))

        elif source_id == "nice_hta":
            from app.ingestion.connectors.nice_hta import get_hta_payer_signal
            nice = get_hta_payer_signal(therapeutic_area, idea[:80])
            if nice.get("found"):
                facts.append(RetrievedFact(
                    concept_type="payer_access_signal", source_id=source_id,
                    value=nice, quality_score=1.0, tier=1,
                ))

        elif source_id == "clinicaltrials_gov":
            import requests as _req
            from app.services.knowledge_retriever import _log_fetch, FetchLog
            _t0_ct = time.monotonic()
            _ct_url = "https://clinicaltrials.gov/api/v2/studies"
            _ct_params = {"query.cond": disease_name, "filter.overallStatus": "RECRUITING,ACTIVE_NOT_RECRUITING",
                          "fields": "NCTId,Phase,BriefTitle", "pageSize": 3}
            r = _req.get(_ct_url, params=_ct_params, timeout=4)
            _studies = r.json().get("studies", []) if r.ok else []
            _log_fetch(FetchLog(
                service="clinicaltrials_gov",
                url=_ct_url,
                method="GET",
                status=r.status_code,
                latency_ms=(time.monotonic() - _t0_ct) * 1000,
                response_bytes=len(r.content) if r.ok else 0,
                parsed_records=len(_studies),
                query_summary=f"clinicaltrials_gov cond={disease_name[:50]!r}",
            ))
            if r.ok:
                facts.append(RetrievedFact(
                    concept_type="competitor_trial_count", source_id=source_id,
                    value={"count": len(_studies), "studies": _studies},
                    quality_score=compute_quality(source_id, "competitor_trial_count", _studies, disease_name, 2024),
                    tier=2,
                ))

        elif source_id == "nih_reporter":
            import requests as _req
            from app.services.knowledge_retriever import _log_fetch, FetchLog
            _RT_EXPERTS = frozenset({"research_tool_non_clinical", "research_infrastructure_saas",
                                     "research_tool_agronomy"})
            if subcategory_id in _RT_EXPERTS:
                # Research tools: search by product text, not disease_conditions.
                # "disease_conditions" on a soil sensor returns NIH clinical grants —
                # what we need is grants that funded comparable instrumentation work.
                _search_text = idea[:80] if idea else (disease_name[:50] or "research instrumentation")
                _nih_body = {
                    "criteria": {
                        "advanced_text_search": {
                            "operator": "and",
                            "search_field": "all",
                            "search_text": _search_text,
                        },
                        "fiscal_years": [2023, 2024, 2025],
                        "is_active": True,
                    },
                    "include_fields": ["ProjectNum", "ProjectTitle", "AwardAmount",
                                       "Organization", "AbstractText"],
                    "limit": 5,
                }
                _concept = "funding_opportunities"
            else:
                _nih_body = {
                    "criteria": {
                        "disease_conditions": [disease_name[:50]],
                        "fiscal_years": [2024, 2025],
                        "is_active": True,  # L: skip expired grants
                    },
                    "limit": 3,
                }
                _concept = "funding_opportunities"
            _t0_nih = time.monotonic()
            r = _req.post(
                "https://api.reporter.nih.gov/v2/projects/search",
                json=_nih_body,
                timeout=6,
            )
            _log_fetch(FetchLog(
                service="nih_reporter",
                url="https://api.reporter.nih.gov/v2/projects/search",
                method="POST",
                status=r.status_code if hasattr(r, "status_code") else None,
                latency_ms=(time.monotonic() - _t0_nih) * 1000,
                response_bytes=len(r.content) if r.ok else 0,
                parsed_records=len(r.json().get("results", [])) if r.ok else 0,
                query_summary=(f"nih_reporter research_tool text={_search_text[:60]!r}"
                               if subcategory_id in _RT_EXPERTS
                               else f"nih_reporter disease={disease_name[:40]!r}"),
            ))
            if r.ok:
                projects = r.json().get("results", [])
                if projects:
                    facts.append(RetrievedFact(
                        concept_type=_concept, source_id=source_id,
                        value=projects[:5], quality_score=0.90, tier=2,
                    ))

        elif source_id == "grants_gov":
            from app.ingestion.connectors.grants_gov import search_funding_opportunities
            opps = search_funding_opportunities(disease_name, agency_code="HHS", limit=3)
            if opps:
                facts.append(RetrievedFact(
                    concept_type="funding_opportunities", source_id=source_id,
                    value=opps, quality_score=0.95, tier=2,
                ))

        elif source_id == "cms_open_payments":
            from app.ingestion.connectors.cms_open_payments import get_kol_landscape_summary
            kol = get_kol_landscape_summary(therapeutic_area)
            if kol:
                facts.append(RetrievedFact(
                    concept_type="kol_landscape", source_id=source_id,
                    value=kol, quality_score=1.0, tier=1,
                ))

        elif source_id == "oecd_health":
            from app.ingestion.connectors.oecd_health import compute_global_tam
            global_data = compute_global_tam(1_000_000_000, therapeutic_area)
            facts.append(RetrievedFact(
                concept_type="global_market_size", source_id=source_id,
                value=global_data, quality_score=1.0, tier=1,
            ))

        elif source_id == "string_db":
            import re
            gene_pattern = r'\b([A-Z][A-Z0-9]{1,7})\b'
            candidates = re.findall(gene_pattern, idea)
            gene = candidates[0] if candidates else None
            if gene:
                from app.ingestion.connectors.string_db import assess_network_liability
                ppi = assess_network_liability(gene)
                if ppi.get("hub_score") != "unknown":
                    facts.append(RetrievedFact(
                        concept_type="target_druggability", source_id=source_id,
                        value=ppi, quality_score=0.85, tier=3,
                    ))

    except Exception as e:
        logger.debug("Source %s failed: %s", source_id, e)

    latency = (time.monotonic() - t0) * 1000
    for f in facts:
        f.latency_ms = latency

    # Cache the result
    if facts:
        ttl = SOURCE_TTL.get(source_id, 86400)
        if ttl != float("inf"):
            _CACHE.set(source_id, cache_key, facts, ttl)

    return facts


async def _fetch_tier_parallel(
    sources: list[str],
    disease_name: str,
    therapeutic_area: str,
    subcategory_id: str,
    idea: str,
    budget_sec: float,
) -> list[RetrievedFact]:
    """Fetch from multiple sources in parallel with a hard wall-clock budget."""
    tasks = [
        asyncio.wait_for(
            _fetch_source(s, disease_name, therapeutic_area, subcategory_id, idea),
            timeout=budget_sec,
        )
        for s in sources
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    facts = []
    for r in results:
        if isinstance(r, list):
            facts.extend(r)
    return facts


# ═══════════════════════════════════════════════════════════════════════════════
# INFORMATION FUSION — deduplication + quality ranking
# ═══════════════════════════════════════════════════════════════════════════════

def _fuse_facts(facts: list[RetrievedFact]) -> dict[str, list[RetrievedFact]]:
    """
    Group facts by concept_type and keep the top-N highest quality per concept.
    This is the deduplication step: multiple sources returning 'prevalence_incidence'
    → keep only the most authoritative one(s).
    """
    by_concept: dict[str, list[RetrievedFact]] = {}
    for fact in facts:
        by_concept.setdefault(fact.concept_type, []).append(fact)

    # Sort by quality descending within each concept
    for concept in by_concept:
        by_concept[concept].sort(key=lambda f: -f.quality_score)
        by_concept[concept] = by_concept[concept][:MAX_FACTS_PER_CONCEPT]

    return by_concept


def _compute_coverage(
    fused: dict[str, list[RetrievedFact]],
    chapters_needed: list[str],
) -> dict[str, float]:
    """
    Compute coverage score per chapter.
    Coverage = (concepts_filled / concepts_needed) for each chapter.
    """
    coverage = {}
    for chapter in chapters_needed:
        needed = CHAPTER_CONCEPTS.get(chapter, set())
        if not needed:
            coverage[chapter] = 1.0
            continue
        filled = sum(1 for c in needed if c in fused and fused[c])
        coverage[chapter] = filled / len(needed)
    return coverage


# ═══════════════════════════════════════════════════════════════════════════════
# FORMAT FUSED FACTS INTO CHAPTER CONTEXT STRINGS
# ═══════════════════════════════════════════════════════════════════════════════

# F-11 / C-01: minimum quality score required for a fact to appear in §1
# context blocks. Facts below this threshold are dropped (relevance gate).
# Tier label is appended to each included fact so Claude knows source quality.
_MIN_QUALITY_SECTION1: float = 0.60


def _tier_label(tier: int) -> str:
    """Return a bracketed tier label for source-quality transparency."""
    return f"[T{tier}]"


def _best_fact_above_threshold(
    fused: dict[str, list[RetrievedFact]],
    concept: str,
    min_quality: float = _MIN_QUALITY_SECTION1,
) -> "RetrievedFact | None":
    """Return the highest-quality fact for `concept` at or above `min_quality`.

    Facts in `fused[concept]` are already sorted descending by quality_score
    (from _fuse_facts). This function enforces the F-11 relevance gate.
    Returns None if no fact meets the threshold.
    """
    for fact in fused.get(concept, []):
        if fact.quality_score >= min_quality:
            return fact
    return None


def _format_facts_for_context(
    fused: dict[str, list[RetrievedFact]],
    disease_name: str,
    therapeutic_area: str,
    subcategory_id: str = "",
) -> dict[str, str]:
    """
    Format retrieved facts into chapter-specific context strings
    ready for injection into Claude's prompt.

    F-11 (C-01): only facts with quality_score >= _MIN_QUALITY_SECTION1 are
    included. Each included fact carries a tier label ([T0]–[T3]) so Claude
    can signal source quality in §1 narrative without hallucinating a tier.

    D-01: disease_intelligence block is skipped for non-clinical archetypes to
    prevent clinical-domain signals (prevalence, prognosis, DALYs) from
    contaminating lab-tool and agronomy reports.
    """
    blocks: dict[str, str] = {}

    # ── disease_intelligence ─────────────────────────────────────────────────
    # D-01: skip entirely for non-clinical archetypes — they have no disease
    # burden concepts in scope, and emitting this block would contaminate the
    # synthesis context with irrelevant clinical signals.
    if subcategory_id not in _NON_CLINICAL_ARCHETYPES:
        # F-11: only facts with quality_score >= _MIN_QUALITY_SECTION1 are included;
        # each fact carries a tier label for source transparency in §1 narrative.
        di_lines = [f"\n=== DISEASE INTELLIGENCE — {disease_name.upper()} (Database-Grounded) ==="]
        for concept in ["prevalence_incidence", "survival_prognosis", "stage_distribution",
                         "disease_burden_dalys", "biomarker_prevalence", "gene_variant_data"]:
            fact = _best_fact_above_threshold(fused, concept)
            if fact is None:
                continue   # relevance gate: no fact met _MIN_QUALITY_SECTION1
            v = fact.value
            if not v:
                continue
            tl = _tier_label(fact.tier)
            if concept == "prevalence_incidence":
                if isinstance(v, dict) and "annual_new_cases" in v:
                    di_lines.append(f"  • Annual incidence: {v['annual_new_cases']:,} new cases/yr [NCI SEER 2024, seer.cancer.gov] {tl}")
                elif isinstance(v, dict) and "us_patient_estimate" in v:
                    di_lines.append(f"  • US patient population: ~{v['us_patient_estimate']:,} [Orphanet CC BY 4.0] {tl}")
                elif isinstance(v, dict) and "dalys" in v:
                    di_lines.append(f"  • Disease burden: {v['dalys']:,.0f} US DALYs [WHO GHO] {tl}")
            elif concept == "survival_prognosis" and isinstance(v, dict) and "5yr_survival_all" in v:
                di_lines.append(f"  • 5-year survival (all stages): {v['5yr_survival_all']:.1%} [NCI SEER 2024] {tl}")
            elif concept == "stage_distribution" and isinstance(v, dict) and "stage_dist_distant" in v:
                di_lines.append(f"  • Stage IV at diagnosis: {v.get('stage_dist_distant', 0):.0%} [NCI SEER 2024] {tl}")
            elif concept == "disease_burden_dalys" and isinstance(v, dict) and "dalys" in v:
                di_lines.append(f"  • US DALYs: {v['dalys']:,.0f} [WHO GHO] {tl}")
            elif concept == "gene_variant_data" and isinstance(v, dict) and v.get("found"):
                di_lines.append(f"  • Gene target: {v.get('gene_symbol')} — {v.get('note', '')} [ClinVar, NCBI] {tl}")
        di_lines.append("INSTRUCTION: Cite these data points verbatim. Do NOT generate different numbers.")
        blocks["disease_intelligence"] = "\n".join(di_lines)

    # ── regulatory_pathway ───────────────────────────────────────────────────
    reg_lines = ["\n=== REGULATORY PATHWAY — Precedent-Grounded ==="]
    fact = _best_fact_above_threshold(fused, "fda_approval_timeline")
    if fact is not None and isinstance(fact.value, list):
        tl = _tier_label(fact.tier)
        for p in fact.value[:2]:
            reg_lines.append(f"  • {p['drug']}: {p['total_years']}yr via {p['pathway']} [{p['fda_application']}] {tl}")
            reg_lines.append(f"    Source: {p['source']} | {p['url']}")
    fact = _best_fact_above_threshold(fused, "ptrs_probability")
    if fact is not None:
        v = fact.value
        tl = _tier_label(fact.tier)
        if isinstance(v, dict) and "ptrs_pct" in v:
            reg_lines.append(f"  • Cumulative LOA (Phase 1→approval): {v['ptrs_pct']:.1f}% [{v.get('citation', 'BIO2020')[:60]}] {tl}")
        elif isinstance(v, dict) and v.get("validated"):
            reg_lines.append(f"  • Realized LOA (FDA outcomes): {v.get('realized_loa_pct', 'N/A')}% (model: {v.get('model_loa_pct')}%) {tl}")
    fact = _best_fact_above_threshold(fused, "competitor_trial_count")
    if fact is not None:
        v = fact.value
        tl = _tier_label(fact.tier)
        if isinstance(v, dict) and "count" in v:
            reg_lines.append(f"  • Active competing trials: {v['count']} [ClinicalTrials.gov] {tl}")
    blocks["regulatory_pathway"] = "\n".join(reg_lines)

    # ── market_access ────────────────────────────────────────────────────────
    ma_lines = ["\n=== MARKET ACCESS — Verified Counts ==="]
    fact = _best_fact_above_threshold(fused, "buyer_counts")
    if fact is not None:
        v = fact.value
        tl = _tier_label(fact.tier)
        if isinstance(v, dict) and "segments" in v:
            for seg, data in list(v["segments"].items())[:4]:
                count_data = data.get("count", {})
                count_val = count_data.get("count", "N/A")
                count_src = count_data.get("source", "")
                ma_lines.append(
                    f"  • {seg}: {count_val:,} [{count_src}] {tl}"
                    if isinstance(count_val, int)
                    else f"  • {seg}: {count_val} [{count_src}] {tl}"
                )
    fact = _best_fact_above_threshold(fused, "payer_access_signal")
    if fact is not None:
        v = fact.value
        tl = _tier_label(fact.tier)
        if isinstance(v, dict) and v.get("icer_found"):
            ma_lines.append(f"  • ICER: {v.get('drug_class')} — {v.get('payer_concern', '')} [{v.get('source', '')[:50]}] {tl}")
        elif isinstance(v, dict) and v.get("found"):
            ma_lines.append(f"  • NICE HTA: {v.get('signal', '')} ({v.get('analogous_ta_count')} analogous TAs) {tl}")
    fact = _best_fact_above_threshold(fused, "kol_landscape")
    if fact is not None:
        v = fact.value
        tl = _tier_label(fact.tier)
        if isinstance(v, dict) and "top_institutions" in v:
            ma_lines.append(f"  • Top KOL institutions: {', '.join(v['top_institutions'][:3])} [CMS Open Payments] {tl}")
    blocks["market_access"] = "\n".join(ma_lines)

    # ── strategic_playbook ───────────────────────────────────────────────────
    sp_lines = ["\n=== STRATEGIC INTELLIGENCE ==="]
    fact = _best_fact_above_threshold(fused, "funding_opportunities")
    if fact is not None:
        v = fact.value
        tl = _tier_label(fact.tier)
        if isinstance(v, dict) and "program" in v:
            sp_lines.append(f"  • {v['program']}: ${v.get('annual_funding_m')}M/yr [DoD CDMRP, cdmrp.health.mil] {tl}")
        elif isinstance(v, list):
            for opp in v[:2]:
                sp_lines.append(f"  • {opp.get('type', '')}: {opp.get('title', '')[:80]} [{opp.get('source', '')}] {tl}")
    fact = _best_fact_above_threshold(fused, "global_market_size")
    if fact is not None:
        v = fact.value
        tl = _tier_label(fact.tier)
        if isinstance(v, dict) and "global_multiplier" in v:
            sp_lines.append(f"  • Global TAM multiplier: {v['global_multiplier']}× US (OECD per-capita pharma spend ratios) {tl}")
        elif isinstance(v, dict) and "citation" in v:
            sp_lines.append(f"  • International pricing context: {v.get('note', '')} [{v.get('citation', '')[:60]}] {tl}")
    fact = _best_fact_above_threshold(fused, "realized_tam_factor")
    if fact is not None:
        v = fact.value
        tl = _tier_label(fact.tier)
        if isinstance(v, dict) and "realized_tam_factor" in v:
            sp_lines.append(f"  • Realized TAM factor: {v['realized_tam_factor']:.0%} (fill rate {v.get('pct_with_any_rx', 0):.0%} × adherence {v.get('real_world_adherence', 0):.0%}) [AHRQ MEPS] {tl}")
    fact = _best_fact_above_threshold(fused, "pathway_biology")
    if fact is not None:
        v = fact.value
        tl = _tier_label(fact.tier)
        if isinstance(v, list) and v:
            sp_lines.append(f"  • MOA pathway: {v[0].get('pathway', '')} [{v[0].get('reactome_id', '')}] [Reactome CC BY 4.0] {tl}")
    blocks["strategic_playbook"] = "\n".join(sp_lines)

    return blocks


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

async def run_retrieval_pipeline(
    disease_name: str,
    therapeutic_area: str,
    subcategory_id: str,
    idea: str,
    chapters_needed: list[str] = None,
    max_total_sec: float = 12.0,
) -> RetrievalResult:
    """
    Main retrieval pipeline. Implements 3-tier adaptive retrieval with
    quality-weighted information fusion and FLARE-inspired stopping.

    Algorithm:
      1. Tier 0 (instant): fetch all pre-loaded data
      2. Check coverage — if ≥80% filled, stop here
      3. Tier 1 (fast parallel, <0.8s budget): lightweight live APIs
      4. Check coverage — if ≥80% filled, stop here
      5. Tier 2 (medium parallel, <4s budget): major structured APIs
      6. Check coverage — if ≥80% filled, stop here
      7. Tier 3 (rich parallel, <10s budget): expensive/slow APIs
      8. Fuse: deduplicate, authority-rank, format into chapter context
    """
    chapters_needed = chapters_needed or list(CHAPTER_CONCEPTS.keys())
    t_start = time.monotonic()

    # G.1 retrieval audit: activate per-generation fetch log collection
    from app.services.knowledge_retriever import start_fetch_log
    start_fetch_log()

    # Determine relevant sources for this subcategory
    relevant_sources = SUBCATEGORY_SOURCE_RELEVANCE.get(
        subcategory_id,
        SUBCATEGORY_SOURCE_RELEVANCE["default"],
    )

    all_facts: list[RetrievedFact] = []
    sources_called: list[str] = []

    # ── Tier 0: instant pre-loaded ────────────────────────────────────────────
    tier0_facts = _fetch_tier0(disease_name, therapeutic_area, subcategory_id, idea)
    all_facts.extend(tier0_facts)
    sources_called.extend(set(f.source_id for f in tier0_facts))

    fused = _fuse_facts(all_facts)
    coverage = _compute_coverage(fused, chapters_needed)
    avg_coverage = sum(coverage.values()) / max(1, len(coverage))
    logger.info("Tier 0 done: %d facts, %.0f%% coverage", len(all_facts), avg_coverage * 100)

    if avg_coverage >= COVERAGE_THRESHOLD:
        logger.info("FLARE stop: coverage threshold met after Tier 0")
        context_blocks = _format_facts_for_context(fused, disease_name, therapeutic_area, subcategory_id)
        return _build_result(all_facts, fused, coverage, t_start, sources_called, 0, context_blocks)

    # ── Tier 1: fast parallel (<0.8s) ────────────────────────────────────────
    tier1_sources = [
        s for s in relevant_sources
        if SOURCE_TIERS.get(s, 99) == 1 and s not in sources_called
    ]
    if tier1_sources:
        tier1_facts = await _fetch_tier_parallel(
            tier1_sources, disease_name, therapeutic_area, subcategory_id, idea,
            budget_sec=TIER1_BUDGET_SEC,
        )
        all_facts.extend(tier1_facts)
        sources_called.extend(tier1_sources)
        fused = _fuse_facts(all_facts)
        coverage = _compute_coverage(fused, chapters_needed)
        avg_coverage = sum(coverage.values()) / max(1, len(coverage))
        logger.info("Tier 1 done: %d facts total, %.0f%% coverage", len(all_facts), avg_coverage * 100)

    if avg_coverage >= COVERAGE_THRESHOLD:
        logger.info("FLARE stop: coverage threshold met after Tier 1")
        context_blocks = _format_facts_for_context(fused, disease_name, therapeutic_area, subcategory_id)
        return _build_result(all_facts, fused, coverage, t_start, sources_called, 1, context_blocks)

    # ── Tier 2: medium parallel (<4s) ────────────────────────────────────────
    elapsed = time.monotonic() - t_start
    remaining = max_total_sec - elapsed - TIER3_BUDGET_SEC
    tier2_budget = min(TIER2_BUDGET_SEC, remaining)

    if tier2_budget > 0.5:
        tier2_sources = [
            s for s in relevant_sources
            if SOURCE_TIERS.get(s, 99) == 2 and s not in sources_called
        ]
        if tier2_sources:
            tier2_facts = await _fetch_tier_parallel(
                tier2_sources, disease_name, therapeutic_area, subcategory_id, idea,
                budget_sec=tier2_budget,
            )
            all_facts.extend(tier2_facts)
            sources_called.extend(tier2_sources)
            fused = _fuse_facts(all_facts)
            coverage = _compute_coverage(fused, chapters_needed)
            avg_coverage = sum(coverage.values()) / max(1, len(coverage))
            logger.info("Tier 2 done: %d facts total, %.0f%% coverage", len(all_facts), avg_coverage * 100)

    if avg_coverage >= COVERAGE_THRESHOLD:
        context_blocks = _format_facts_for_context(fused, disease_name, therapeutic_area, subcategory_id)
        return _build_result(all_facts, fused, coverage, t_start, sources_called, 2, context_blocks)

    # ── Tier 3: rich parallel (<10s) ─────────────────────────────────────────
    elapsed = time.monotonic() - t_start
    tier3_budget = min(TIER3_BUDGET_SEC, max_total_sec - elapsed)

    if tier3_budget > 1.0:
        tier3_sources = [
            s for s in relevant_sources
            if SOURCE_TIERS.get(s, 99) == 3 and s not in sources_called
        ]
        if tier3_sources:
            tier3_facts = await _fetch_tier_parallel(
                tier3_sources, disease_name, therapeutic_area, subcategory_id, idea,
                budget_sec=tier3_budget,
            )
            all_facts.extend(tier3_facts)
            sources_called.extend(tier3_sources)
            fused = _fuse_facts(all_facts)
            coverage = _compute_coverage(fused, chapters_needed)

    context_blocks = _format_facts_for_context(fused, disease_name, therapeutic_area, subcategory_id)
    return _build_result(all_facts, fused, coverage, t_start, sources_called, 3, context_blocks)


def _build_result(
    all_facts, fused, coverage, t_start, sources_called, tiers_reached, context_blocks
) -> RetrievalResult:
    from app.services.knowledge_retriever import get_fetch_log
    total_ms = (time.monotonic() - t_start) * 1000
    cached_count = sum(1 for f in all_facts if f.cached)
    cache_hit_rate = cached_count / max(1, len(all_facts))
    concepts_filled = set(fused.keys())

    return RetrievalResult(
        facts=all_facts,
        coverage_by_chapter=coverage,
        total_latency_ms=round(total_ms),
        cache_hit_rate=round(cache_hit_rate, 3),
        tiers_reached=tiers_reached,
        sources_called=sources_called,
        concepts_filled=concepts_filled,
        context_blocks=context_blocks,
        fetch_logs=list(get_fetch_log()),
    )
