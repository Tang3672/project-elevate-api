"""
Data Source Registry — Project Elevate
========================================
Complete catalog of all data sources: license, commercial status, API endpoint,
and what unique data each provides.

Use this as the authoritative reference for:
  1. Legal compliance audit (before enterprise customer distribution)
  2. Attribution requirements (what to cite in generated reports)
  3. Understanding what each source uniquely contributes to market intelligence

Sources are categorized as:
  CLEAR    — public domain or CC0/CC-BY, no restrictions
  ALLOWED  — commercial use permitted with conditions (attribution, no endorsement)
  WATCH    — use with care (specific restrictions to avoid)
  BLOCKED  — non-commercial only, DO NOT USE in customer-facing output
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DataSource:
    source_id:        str
    name:             str
    category:         str          # epidemiology | regulatory | clinical | economic | literature | ip
    commercial_status: str         # CLEAR | ALLOWED | WATCH | BLOCKED
    license_type:     str
    api_endpoint:     Optional[str]
    connector_file:   Optional[str]
    unique_data:      str          # What this uniquely provides
    attribution:      str          # What to display in reports
    restrictions:     str          # Key things NOT to do
    rate_limit:       Optional[str]
    requires_key:     bool
    key_source:       Optional[str]


DATA_SOURCES = [

    # ── EPIDEMIOLOGY / DISEASE BURDEN ────────────────────────────────────────

    DataSource(
        source_id="who_gho",
        name="WHO Global Health Observatory (GHO)",
        category="epidemiology",
        commercial_status="ALLOWED",
        license_type="WHO Terms of Use — commercial use permitted with attribution",
        api_endpoint="https://ghoapi.azureedge.net/api",
        connector_file="ingestion/connectors/who_gho.py",
        unique_data="Disease DALYs, mortality, prevalence for 194 countries. Primary commercial-safe replacement for IHME GBD.",
        attribution='Source: "World Health Organization. Global Health Observatory." WHO does not endorse Project Elevate.',
        restrictions="Cannot imply WHO endorsement. Cannot alter data to misrepresent WHO findings.",
        rate_limit="~1 req/sec practical",
        requires_key=False, key_source=None,
    ),

    DataSource(
        source_id="nci_seer",
        name="NCI SEER — Cancer Incidence & Survival",
        category="epidemiology",
        commercial_status="CLEAR",
        license_type="US Public Domain (NCI, government work)",
        api_endpoint="https://api.seer.cancer.gov",
        connector_file="ingestion/connectors/seer_cancer.py",
        unique_data="Age-standardized cancer incidence by site/stage/year. 5-year survival by stage. Biomarker prevalence. Gold standard for oncology TAM sizing.",
        attribution='Source: "National Cancer Institute. SEER Cancer Stat Facts. seer.cancer.gov"',
        restrictions="No redistribution restrictions (public domain).",
        rate_limit="None documented (free API key required)",
        requires_key=True, key_source="https://api.seer.cancer.gov/keys",
    ),

    DataSource(
        source_id="orphanet",
        name="Orphanet — Rare Disease Prevalence",
        category="epidemiology",
        commercial_status="ALLOWED",
        license_type="CC BY 4.0 — commercial use YES",
        api_endpoint="https://api.orphacode.org/EN",
        connector_file="ingestion/connectors/orphanet.py",
        unique_data="Official EU rare disease prevalence (patients/million). ORPHAcode taxonomy. Gene-disease associations. Used in FDA orphan designation applications.",
        attribution='Source: "Orphanet. orphadata.com. Accessed 2024."',
        restrictions="Attribution required. Cannot claim Orphanet endorses Project Elevate.",
        rate_limit="None documented",
        requires_key=False, key_source=None,
    ),

    DataSource(
        source_id="nchs_mortality",
        name="NCHS / CDC — National Center for Health Statistics",
        category="epidemiology",
        commercial_status="CLEAR",
        license_type="US Public Domain",
        api_endpoint="https://data.cdc.gov/resource/bi63-dtpu.json",
        connector_file=None,  # Uses existing Socrata infrastructure
        unique_data="Leading causes of death by ICD-10 code, age group, sex, race. Mortality trends 1999-present. Complements WHO GHO with US-specific granularity.",
        attribution='Source: "CDC/NCHS. National Vital Statistics System. wonder.cdc.gov"',
        restrictions="Do NOT automate CDC Wonder directly (terms violation). Use data.cdc.gov Socrata endpoints.",
        rate_limit="Socrata standard limits",
        requires_key=False, key_source=None,
    ),

    DataSource(
        source_id="ihme_gbd",
        name="IHME Global Burden of Disease (GBD)",
        category="epidemiology",
        commercial_status="BLOCKED",
        license_type="IHME Free-of-Charge Non-Commercial User Agreement",
        api_endpoint=None,
        connector_file="app/services/opportunity_scorer_v2.py (flagged, fallback only)",
        unique_data="Disease DALYs, YLDs, YLLs. DO NOT USE in commercial output.",
        attribution="N/A — BLOCKED",
        restrictions="PROHIBITED for commercial use, redistribution, sublicensing. Codebase flags commercial_use_restricted=True.",
        rate_limit="N/A",
        requires_key=False, key_source=None,
    ),

    # ── REGULATORY / APPROVAL ────────────────────────────────────────────────

    DataSource(
        source_id="openfda",
        name="OpenFDA — FDA Drug/Device/Food Data",
        category="regulatory",
        commercial_status="CLEAR",
        license_type="CC0 (public domain dedication)",
        api_endpoint="https://api.fda.gov",
        connector_file="ingestion/connectors/openfda.py, fda_approvals.py",
        unique_data="NDA/BLA approval history, FAERS adverse events, MAUDE device events, drug recalls, Orange Book.",
        attribution='Source: "U.S. Food and Drug Administration. openFDA. api.fda.gov"',
        restrictions="Cannot imply FDA endorsement. FDA recommends citing specific dataset used.",
        rate_limit="1,000 req/day unauthenticated; 120,000 req/day with free API key",
        requires_key=True, key_source="https://open.fda.gov/apis/authentication/",
    ),

    DataSource(
        source_id="clinicaltrials_gov",
        name="ClinicalTrials.gov API v2",
        category="clinical",
        commercial_status="CLEAR",
        license_type="US Public Domain (17 U.S.C. § 105)",
        api_endpoint="https://clinicaltrials.gov/api/v2/studies",
        connector_file="ingestion/connectors/clinical_trials.py",
        unique_data="Active trial pipeline by condition, phase, intervention type. Trial results reporting (primary outcomes). Competitive landscape signal.",
        attribution='Source: "ClinicalTrials.gov. National Library of Medicine. clinicaltrials.gov"',
        restrictions="No rate limits but heavy scraping discouraged. NLM not responsible for downstream use.",
        rate_limit="~10 req/sec unenforced",
        requires_key=False, key_source=None,
    ),

    DataSource(
        source_id="nice_ta",
        name="NICE Technology Appraisals",
        category="regulatory",
        commercial_status="ALLOWED",
        license_type="UK Open Government Licence v3.0 — commercial use YES",
        api_endpoint="https://api.nice.org.uk/services/evidence",
        connector_file="ingestion/connectors/nice_hta.py",
        unique_data="UK HTA decisions (recommended/not recommended) with ICER ranges. Only publicly accessible API-enabled HTA database. US payers cite NICE decisions.",
        attribution='Source: "NICE Technology Appraisals. nice.org.uk. UK Open Government Licence v3.0."',
        restrictions="Cannot imply NICE endorsement. Decisions apply to NHS England — extrapolation to US required.",
        rate_limit="None documented",
        requires_key=False, key_source=None,
    ),

    DataSource(
        source_id="eu_ctis",
        name="EU Clinical Trials Information System (CTIS)",
        category="clinical",
        commercial_status="ALLOWED",
        license_type="EU Open Data — commercial use YES",
        api_endpoint="https://euclinicaltrials.eu/api/v1/",
        connector_file=None,  # Not yet implemented
        unique_data="EU-specific trial registrations not in ClinicalTrials.gov. Sponsor country, EU site count, EMA protocol approval.",
        attribution='Source: "EU Clinical Trials Register. euclinicaltrials.eu"',
        restrictions="Beta API — structure may change. EU trials also registered on ClinicalTrials.gov (partial overlap).",
        rate_limit="None documented (beta)",
        requires_key=False, key_source=None,
    ),

    # ── DRUG / GENOMIC INTELLIGENCE ──────────────────────────────────────────

    DataSource(
        source_id="open_targets",
        name="OpenTargets Platform",
        category="regulatory",
        commercial_status="ALLOWED",
        license_type="Apache-2.0 (platform); data components vary (ChEMBL CC BY-SA 3.0)",
        api_endpoint="https://api.platform.opentargets.org/api/v4/graphql",
        connector_file="ingestion/connectors/open_targets.py",
        unique_data="Disease-target genetic associations, drug-target mechanisms, target tractability, safety signals. Genetic validation score = strongest LOA predictor.",
        attribution='Source: "Open Targets Platform. opentargets.org. CC BY-SA 3.0."',
        restrictions="ChEMBL data (CC BY-SA) — derivative works must carry same license or only expose derived scores.",
        rate_limit="None documented; GraphQL batching recommended",
        requires_key=False, key_source=None,
    ),

    DataSource(
        source_id="clinvar",
        name="NCBI ClinVar — Genetic Variants",
        category="epidemiology",
        commercial_status="CLEAR",
        license_type="US Public Domain (NCBI/NLM government work)",
        api_endpoint="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
        connector_file="ingestion/connectors/clinvar.py",
        unique_data="Pathogenic variant classifications. Gene-disease associations. DMD exon deletion breakdown (critical for exon-skip drug eligibility sizing). Hemophilia F8/F9 variant spectrum.",
        attribution='Source: "NCBI ClinVar. ncbi.nlm.nih.gov/clinvar. National Library of Medicine."',
        restrictions="No commercial restrictions (public domain). Include email in API requests (NCBI best practice).",
        rate_limit="3 req/sec without key; 10 req/sec with free NCBI API key",
        requires_key=False, key_source="https://www.ncbi.nlm.nih.gov/account/",
    ),

    DataSource(
        source_id="rxnorm",
        name="RxNorm Drug Normalization (NLM)",
        category="regulatory",
        commercial_status="CLEAR",
        license_type="US Public Domain",
        api_endpoint="https://rxnav.nlm.nih.gov/REST",
        connector_file="ingestion/connectors/rxnorm.py",
        unique_data="Drug name normalization, RxCUI codes, ingredient-brand mapping. Enables cross-source drug name matching.",
        attribution='Source: "RxNorm. U.S. National Library of Medicine."',
        restrictions="None (public domain).",
        rate_limit="~20 req/sec",
        requires_key=False, key_source=None,
    ),

    DataSource(
        source_id="pharmgkb",
        name="PharmGKB — Pharmacogenomics",
        category="epidemiology",
        commercial_status="ALLOWED",
        license_type="CC BY-SA 4.0 — commercial use YES with attribution",
        api_endpoint=None,
        connector_file=None,  # Flat file download only
        unique_data="Drug-gene-variant-phenotype associations. Which patient genotypes respond to which drugs. CPIC dosing guidelines. CYP2D6/CYP2C19 metabolizer status.",
        attribution='Source: "PharmGKB. pharmgkb.org. CC BY-SA 4.0."',
        restrictions="CC BY-SA: derivative works must carry same license. Expose only derived scores in commercial outputs.",
        rate_limit="Flat file download; no API rate limit",
        requires_key=False, key_source="https://www.pharmgkb.org/downloads",
    ),

    # ── ECONOMIC / PRICING ───────────────────────────────────────────────────

    DataSource(
        source_id="cms_part_d",
        name="CMS Medicare Part D Drug Spending",
        category="economic",
        commercial_status="CLEAR",
        license_type="US Public Domain",
        api_endpoint="https://data.cms.gov/resource/qm9z-4mdc.json",
        connector_file="ingestion/connectors/cms_spending.py",
        unique_data="Actual realized Medicare Part D drug spend by year: gross cost, beneficiary count, cost per beneficiary. Covers ORAL specialty drugs.",
        attribution='Source: "CMS Medicare Part D Drug Spending Dashboard. data.cms.gov."',
        restrictions="Cannot imply CMS endorsement.",
        rate_limit="Socrata standard; get free app token to remove limit",
        requires_key=False, key_source="https://data.cms.gov/developer",
    ),

    DataSource(
        source_id="cms_part_b_asp",
        name="CMS Medicare Part B ASP (Average Sales Price)",
        category="economic",
        commercial_status="CLEAR",
        license_type="US Public Domain",
        api_endpoint="https://www.cms.gov/files/zip/asp{YEAR}q{Q}.zip",
        connector_file="ingestion/connectors/cms_asp.py",
        unique_data="ASP for ALL injectable/infused drugs administered in physician/hospital settings. Covers oncology biologics (Keytruda, Darzalex, CAR-T), neurology (Ocrevus), ophthalmology (Eylea). CRITICAL GAP: Part D misses all Part B drugs.",
        attribution='Source: "CMS Medicare Part B Drug Pricing. cms.gov/medicare/payment/asp-drug-pricing."',
        restrictions="Quarterly lag (~6 months). ASP + 6% = Medicare reimbursement.",
        rate_limit="Static quarterly files (no API)",
        requires_key=False, key_source=None,
    ),

    DataSource(
        source_id="cms_nadac",
        name="CMS NADAC (National Average Drug Acquisition Cost)",
        category="economic",
        commercial_status="CLEAR",
        license_type="US Public Domain",
        api_endpoint="https://data.medicaid.gov/dataset/4bec4d37-da3b-4d2e-9f94-1c84eded56e7",
        connector_file=None,  # Not yet implemented
        unique_data="Weekly pharmacy acquisition cost for ~3,000 drugs. Actual manufacturer-to-pharmacy price (not WAC). Foundation for gross margin analysis and price erosion tracking.",
        attribution='Source: "CMS NADAC. data.medicaid.gov."',
        restrictions="Cannot imply CMS endorsement.",
        rate_limit="Socrata standard",
        requires_key=False, key_source=None,
    ),

    DataSource(
        source_id="icer",
        name="ICER Evidence Reports",
        category="economic",
        commercial_status="ALLOWED",
        license_type="Public access; ICER reports are publicly available documents",
        api_endpoint=None,
        connector_file="app/services/market_calibration_service.py (pre-loaded)",
        unique_data="US cost-effectiveness assessments ($/QALY), value-based prices, payer uptake signals. Pre-loaded for 9 major drug classes.",
        attribution='Source: "Institute for Clinical and Economic Review. icer.org."',
        restrictions="Cannot imply ICER endorsement. ICER explicitly maintains editorial independence.",
        rate_limit="N/A (pre-loaded structured data)",
        requires_key=False, key_source=None,
    ),

    # ── INTELLECTUAL PROPERTY ────────────────────────────────────────────────

    DataSource(
        source_id="patents_view",
        name="PatentsView (USPTO)",
        category="ip",
        commercial_status="CLEAR",
        license_type="US Public Domain (USPTO data)",
        api_endpoint="https://api.patentsview.org",
        connector_file="ingestion/connectors/patents.py",
        unique_data="US patents by assignee, inventor, technology class. Patent citation networks. US-only.",
        attribution='Source: "PatentsView. patentsview.org. USPTO."',
        restrictions="None (public domain).",
        rate_limit="~45 req/min; contact for higher",
        requires_key=False, key_source=None,
    ),

    DataSource(
        source_id="sec_edgar",
        name="SEC EDGAR — Public Company Filings",
        category="economic",
        commercial_status="CLEAR",
        license_type="US Public Domain",
        api_endpoint="https://efts.sec.gov/LATEST/search-index",
        connector_file="ingestion/connectors/sec_edgar.py",
        unique_data="10-K/10-Q pipeline disclosures. Revenue by product line. Preclinical/clinical program updates. Phase-specific milestone payments from licensing deals.",
        attribution='Source: "SEC EDGAR. sec.gov. Public company filings."',
        restrictions="10 req/sec hard limit. User-Agent MUST include org name + email or gets blocked.",
        rate_limit="10 req/sec",
        requires_key=False, key_source=None,
    ),

    # ── LITERATURE / SCIENCE ─────────────────────────────────────────────────

    DataSource(
        source_id="openalex",
        name="OpenAlex — Scientific Literature",
        category="literature",
        commercial_status="CLEAR",
        license_type="CC0 — no rights reserved",
        api_endpoint="https://api.openalex.org",
        connector_file="ingestion/connectors/openalex.py",
        unique_data="250M+ scholarly works, open access status, citation network, author affiliations. Best CC0 replacement for Semantic Scholar.",
        attribution="None required (CC0); mailto= param for polite pool",
        restrictions="None (CC0).",
        rate_limit="10 req/sec with mailto= param",
        requires_key=False, key_source=None,
    ),

    DataSource(
        source_id="pubmed",
        name="PubMed / PubMed Central (NCBI)",
        category="literature",
        commercial_status="WATCH",
        license_type="NLM public domain (metadata); article content varies by publisher",
        api_endpoint="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
        connector_file="ingestion/connectors/pubmed_canonical.py",
        unique_data="40M+ biomedical articles. Clinical trial results. Phase 3 primary publications.",
        attribution='Source: "PubMed. National Library of Medicine. pubmed.ncbi.nlm.nih.gov."',
        restrictions="WATCH: Abstract counts = SAFE. Full article text = publisher copyright (varies). Never display full article text without checking individual article CC license.",
        rate_limit="3 req/sec without key; 10 req/sec with free NCBI key",
        requires_key=False, key_source="https://www.ncbi.nlm.nih.gov/account/",
    ),

    DataSource(
        source_id="semantic_scholar",
        name="Semantic Scholar (Allen AI)",
        category="literature",
        commercial_status="WATCH",
        license_type="Non-commercial for bulk data; individual API queries for commercial products allowed",
        api_endpoint="https://api.semanticscholar.org/graph/v1",
        connector_file="ingestion/connectors/semantic_scholar.py",
        unique_data="AI-generated TLDRs (1-sentence summaries) that are safe to display. Citation velocity. KOL network analysis. Influential citation flag.",
        attribution='Source: "Semantic Scholar. Allen Institute for AI. semanticscholar.org."',
        restrictions="WATCH: Non-commercial for bulk redistribution of raw data. Individual API queries for derived products OK commercially. Use TLDRs (AI-generated) not raw abstracts.",
        rate_limit="100 req/min unauthenticated; higher with free API key",
        requires_key=False, key_source="https://api.semanticscholar.org/",
    ),

    # ── GOVERNMENT GRANTS / CONTRACTS ────────────────────────────────────────

    DataSource(
        source_id="nih_reporter",
        name="NIH Reporter — Research Grants",
        category="economic",
        commercial_status="CLEAR",
        license_type="US Public Domain",
        api_endpoint="https://api.reporter.nih.gov/v2/projects/search",
        connector_file="ingestion/connectors/nih_reporter.py",
        unique_data="NIH grant funding by disease area, PI institution. R01/R21/U01/P01 activity codes. Funding density = research validation signal.",
        attribution='Source: "NIH Reporter. reporter.nih.gov. National Institutes of Health."',
        restrictions="Cannot imply NIH endorsement.",
        rate_limit="None documented",
        requires_key=False, key_source=None,
    ),

    DataSource(
        source_id="usa_spending",
        name="USASpending.gov — Federal Contracts",
        category="economic",
        commercial_status="CLEAR",
        license_type="US Public Domain",
        api_endpoint="https://api.usaspending.gov/api/v2/",
        connector_file="ingestion/connectors/usa_spending.py",
        unique_data="BARDA antimicrobial contracts, DoD health tech procurement, CMS IT contracts. Complements NIH RePORTER (grants) with larger government awards.",
        attribution='Source: "USASpending.gov. US government federal spending."',
        restrictions="None (public domain).",
        rate_limit="None documented",
        requires_key=False, key_source=None,
    ),

    DataSource(
        source_id="sbir_gov",
        name="SBIR.gov — Small Business Innovation Awards",
        category="economic",
        commercial_status="CLEAR",
        license_type="US Public Domain",
        api_endpoint="https://api.sbir.gov/public/api/awards",
        connector_file="ingestion/connectors/usa_spending.py (get_sbir_healthcare_awards)",
        unique_data="SBIR/STTR award amounts by keyword, agency. Early-stage healthcare innovation funding signal. Predicts what startups are working on 3-5 years ahead.",
        attribution='Source: "SBIR.gov. Small Business Administration."',
        restrictions="None (public domain).",
        rate_limit="None documented",
        requires_key=False, key_source=None,
    ),

    # ── AI GENERATION ────────────────────────────────────────────────────────

    DataSource(
        source_id="anthropic_claude",
        name="Anthropic Claude API",
        category="literature",
        commercial_status="CLEAR",
        license_type="Proprietary — commercial use YES per Anthropic ToS",
        api_endpoint="https://api.anthropic.com/v1/messages",
        connector_file="app/services/alignment_service.py",
        unique_data="Market analysis generation, competitive intelligence synthesis, regulatory pathway recommendations.",
        attribution="Optional: 'AI-assisted analysis by Project Elevate'",
        restrictions="Cannot use outputs to train competing models. Outputs are customer-owned.",
        rate_limit="Tier-based; scales with usage",
        requires_key=True, key_source="https://console.anthropic.com/",
    ),

    DataSource(
        source_id="openai_embeddings",
        name="OpenAI Embeddings API",
        category="literature",
        commercial_status="CLEAR",
        license_type="Proprietary — commercial use YES per OpenAI ToS",
        api_endpoint="https://api.openai.com/v1/embeddings",
        connector_file="app/services/embedding_service.py",
        unique_data="Text embeddings for semantic search and similarity matching.",
        attribution="None required in output.",
        restrictions="Cannot claim AI-generated outputs are human. Cannot use to train competing models.",
        rate_limit="Tier-based (default 500K TPM text-embedding-3)",
        requires_key=True, key_source="https://platform.openai.com/",
    ),
]

# Quick lookup by source_id
REGISTRY: dict[str, DataSource] = {ds.source_id: ds for ds in DATA_SOURCES}

# Sources blocked for commercial use
BLOCKED_SOURCES = [ds for ds in DATA_SOURCES if ds.commercial_status == "BLOCKED"]

# Sources requiring immediate action (missing API keys or not yet implemented)
NEEDS_ACTION = [
    {"source": "openfda", "action": "Get free API key to raise rate limit from 1K to 120K req/day", "url": "https://open.fda.gov/apis/authentication/"},
    {"source": "nci_seer", "action": "Register for free SEER API key to access cancer incidence data", "url": "https://api.seer.cancer.gov/keys"},
    {"source": "sec_edgar", "action": "Add org name + email to User-Agent header in sec_edgar.py", "url": None},
    {"source": "cms_part_d", "action": "Get free Socrata app token to remove rate limits", "url": "https://data.cms.gov/developer"},
    {"source": "cms_nadac", "action": "Implement connector — high-value acquisition price data not yet integrated", "url": "https://data.medicaid.gov/dataset/4bec4d37-"},
    {"source": "pharmgkb", "action": "Implement flat-file download connector — pharmacogenomics data not yet integrated", "url": "https://www.pharmgkb.org/downloads"},
    {"source": "eu_ctis", "action": "Implement EU clinical trial connector (beta API)", "url": "https://euclinicaltrials.eu/api/v1/"},
]


def get_attribution_block(source_ids: list[str]) -> str:
    """Generate citation block for a report using specified data sources."""
    lines = ["Data Sources:"]
    for sid in source_ids:
        ds = REGISTRY.get(sid)
        if ds:
            lines.append(f"  • {ds.name}: {ds.attribution}")
    return "\n".join(lines)


def audit_commercial_compliance() -> dict:
    """Return compliance summary for commercial distribution."""
    blocked = [ds.name for ds in DATA_SOURCES if ds.commercial_status == "BLOCKED"]
    watch = [ds.name for ds in DATA_SOURCES if ds.commercial_status == "WATCH"]
    clear = [ds.name for ds in DATA_SOURCES if ds.commercial_status in ("CLEAR", "ALLOWED")]

    return {
        "total_sources": len(DATA_SOURCES),
        "commercial_safe": len(clear),
        "requires_caution": len(watch),
        "blocked_must_not_use": len(blocked),
        "blocked_sources": blocked,
        "watch_sources": watch,
        "compliance_status": "COMPLIANT" if len(blocked) == 0 else f"ACTION REQUIRED: {len(blocked)} blocked sources in use",
    }
