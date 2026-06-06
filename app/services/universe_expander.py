"""
Universe Expander
=================
Expands the disease universe from 309 curated entries to ALL conditions
that have active clinical trial activity — potentially 5,000-15,000 diseases.

Strategy:
  1. Query ClinicalTrials.gov for active interventional trials
  2. Extract ALL condition names from trial records
  3. Deduplicate and normalise (MONDO/MeSH where available)
  4. Score each condition using TA-level defaults (fast — no live API per disease)
  5. Persist scores in disease_aggregate_extended table
  6. Discovery endpoint reads from this table for broader results

This runs as a background job (weekly). The first run takes ~30-60 minutes
to pull and process CT.gov data. Subsequent runs are incremental.

Coverage: WHO estimates ~10,000 recognised diseases. CT.gov conditions cover
~15,000 unique condition strings (many are duplicates/synonyms). After
normalisation we expect 3,000-8,000 unique disease concepts.
"""

import asyncio
import logging
import re
import time
from collections import Counter
from typing import Optional

import requests

logger = logging.getLogger(__name__)

CTGOV_BASE = "https://clinicaltrials.gov/api/v2/studies"
_DELAY     = 0.4

# ── TA classification by keyword ─────────────────────────────────────────────
_TA_KEYWORDS = {
    "oncology":       ["cancer","carcinoma","glioblastoma","leukemia","lymphoma","melanoma","sarcoma","tumor","myeloma","adenocarcinoma","blastoma","neoplasm","malignan"],
    "rare_disease":   ["rare ","orphan","ataxia","muscular dystrophy","spinal muscular","gaucher","fabry","phenylketonuria","sickle cell","huntington","friedreich","wilson","pompe","niemann"],
    "amr_infectious": ["resistant","mrsa","carbapenem","acinetobacter","difficile","staphylococc","enterobacterales","sepsis","infectious","antimicrobial","antibiotic","bacterial","viral","fungal","hiv","hepatitis","tuberculosis","malaria","influenza","rsv","covid"],
    "cns":            ["alzheimer","parkinson","huntington","multiple sclerosis","epilepsy","depression","bipolar","schizophrenia","dementia","neurodegen","als","amyotrophic","stroke","cerebral","neurolog","psychiatric","autism","adhd","anxiety","ptsd","migraine"],
    "cardiovascular": ["heart failure","atrial fibrillation","hypertension","coronary","myocardial","stroke","pulmonary arterial","cardiovascular","arrhythmia","cardiomyop","aortic","ventricular","cardiac"],
    "metabolic":      ["diabetes","obesity","nash","mash","nonalcoholic","fatty liver","metabolic","dyslipidemia","gout","thyroid","cushing","acromegaly"],
    "gene_therapy":   ["gene therapy","aav","lentiviral","gene editing","crispr","monogenic","gene replacement"],
    "immunology":     ["rheumatoid","lupus","psoriasis","inflammatory bowel","crohn","ulcerative colitis","autoimmune","immunodeficiency","vasculitis","sjogren","myositis","scleroderma","dermatomyositis"],
    "ophthalmology":  ["macular","glaucoma","retinal","geographic atrophy","amd","dry eye","optic","uveitis","corneal","retinitis"],
    "vaccine":        ["rsv","influenza","covid","sars","respiratory syncytial","vaccine","prophylactic","immunization"],
    "hematology":     ["hemophilia","thalassemia","anemia","myeloma","leukemia","lymphoma","thrombocytopenia","coagulation","platelet","neutropenia"],
    "device":         ["sepsis","diagnostic","device","monitor","detection","wearable","implant","catheter"],
    "respiratory":    ["copd","asthma","emphysema","pulmonary fibrosis","bronchiectasis","cystic fibrosis","respiratory"],
    "dermatology":    ["psoriasis","eczema","atopic dermatitis","acne","rosacea","vitiligo","alopecia","hair loss","pemphigus","urticaria"],
    "gastroenterology":["inflammatory bowel","crohn","colitis","liver","hepatitis","cirrhosis","gastroparesis","eosinophilic","celiac"],
    "musculoskeletal":["osteoarthritis","osteoporosis","spondylitis","gout","fibromyalgia","myositis","muscular"],
    "renal":          ["kidney","renal","nephropathy","glomerulosclerosis","polycystic kidney"],
}

def _classify_ta(condition: str) -> str:
    low = condition.lower()
    for ta, keywords in _TA_KEYWORDS.items():
        if any(kw in low for kw in keywords):
            return ta
    return "other"

# ── CT.gov condition harvester ────────────────────────────────────────────────

def _fetch_conditions_page(page_token: Optional[str] = None,
                            page_size: int = 1000) -> tuple[list[str], Optional[str]]:
    """Fetch one page of conditions from CT.gov active interventional trials."""
    params = {
        "filter.overallStatus": "RECRUITING,ACTIVE_NOT_RECRUITING,NOT_YET_RECRUITING",
        "filter.studyType":     "INTERVENTIONAL",
        "pageSize":             page_size,
        "format":               "json",
        "fields":               "ConditionList",
    }
    if page_token:
        params["pageToken"] = page_token

    conditions: list[str] = []
    next_token: Optional[str] = None

    try:
        r = requests.get(CTGOV_BASE, params=params, timeout=20)
        if r.status_code != 200:
            return conditions, None
        data = r.json()
        for study in data.get("studies", []):
            proto = study.get("protocolSection", {})
            conds = proto.get("conditionsModule", {}).get("conditions", [])
            conditions.extend(conds)
        next_token = data.get("nextPageToken")
    except Exception as e:
        logger.warning("CT.gov conditions page failed: %s", e)

    return conditions, next_token


def _normalise_condition(raw: str) -> str:
    """Basic normalisation: strip parenthetical subtypes, trim, title-case."""
    # Remove very specific subtypes that create noise
    name = re.sub(r'\s*\((?:stage|type|grade|subtype|phase|class)\s+[IViv\d]+\)', '', raw, flags=re.IGNORECASE)
    name = name.strip().strip(',').strip()
    # Remove trailing qualifiers like "- Newly Diagnosed"
    name = re.sub(r'\s*-\s*(newly diagnosed|relapsed|refractory|advanced|metastatic|recurrent)$', '', name, flags=re.IGNORECASE)
    return name[:120].strip()


async def harvest_all_conditions(max_pages: int = 50) -> dict[str, int]:
    """
    Pull conditions from CT.gov active interventional trials (without field filtering
    which causes 500 errors). Extracts conditions from full study responses.
    Returns {condition_name: trial_count}.
    """
    counter: Counter = Counter()
    page_token = None
    pages = 0

    logger.info("Starting CT.gov condition harvest (max %d pages)...", max_pages)

    while pages < max_pages:
        params = {
            "filter.overallStatus": "RECRUITING,ACTIVE_NOT_RECRUITING,NOT_YET_RECRUITING",
            "filter.studyType":     "INTERVENTIONAL",
            "pageSize":             1000,
            "format":               "json",
            # NOTE: No "fields" param — causes 500 on Railway; parse from full response
        }
        if page_token:
            params["pageToken"] = page_token

        conditions_this_page: list[str] = []
        next_token = None

        try:
            r = requests.get(CTGOV_BASE, params=params, timeout=20)
            if r.status_code == 200:
                data = r.json()
                for study in data.get("studies", []):
                    proto = study.get("protocolSection", {})
                    conds = proto.get("conditionsModule", {}).get("conditions", [])
                    conditions_this_page.extend(conds)
                next_token = data.get("nextPageToken")
            else:
                logger.warning("CT.gov returned %d on page %d", r.status_code, pages)
                break
        except Exception as e:
            logger.warning("CT.gov conditions page %d failed: %s", pages, e)
            break

        for c in conditions_this_page:
            norm = _normalise_condition(c)
            if norm and len(norm) > 3:
                counter[norm] += 1

        pages += 1
        logger.info("CT.gov harvest: page %d, total unique conditions: %d", pages, len(counter))
        time.sleep(_DELAY)

        if not next_token:
            break
        page_token = next_token

    logger.info("CT.gov harvest complete: %d unique conditions from %d pages", len(counter), pages)
    return dict(counter.most_common(10000))


async def run_mondo_expansion(max_pages: int = 40) -> dict:
    """
    Expand universe using full MONDO ontology (up to 20,000 diseases).
    More reliable than CT.gov on Railway — uses the existing bulk_load_mondo
    connector to load all MONDO disease terms, then scores each one.
    This is the PRIMARY expansion method.
    """
    from app.db.database import get_pool
    from app.ingestion.connectors.mondo import bulk_load_mondo

    logger.info("Starting MONDO-based universe expansion (max_pages=%d)...", max_pages)

    # Step 1: Load all MONDO diseases into the disease table
    total_mondo = await bulk_load_mondo(page_size=500, max_pages=max_pages)
    logger.info("MONDO bulk load complete: %d diseases loaded", total_mondo)

    # Step 2: Score all MONDO diseases not yet in disease_scored
    pool = await get_pool()
    scored = 0

    async with pool.acquire() as conn:
        await prescored_universe_table(conn)

        # Pull all diseases from the disease table
        rows = await conn.fetch("""
            SELECT d.mondo_id, d.label, d.therapeutic_area, d.is_rare,
                   d.icd10_ids, d.omim_ids
            FROM disease d
            WHERE d.label IS NOT NULL AND length(d.label) > 3
            ORDER BY d.mondo_id
        """)

        logger.info("Scoring %d MONDO diseases...", len(rows))

        for row in rows:
            label = row["label"]
            ta    = row["therapeutic_area"] or _classify_ta(label)

            # Use real trial count from cache if available, else default to 5
            from app.services.opportunity_scorer_v2 import _TRIAL_COUNT_CACHE
            cached = _TRIAL_COUNT_CACHE.get(label)
            trial_count = cached[0] if cached else 5

            if await score_and_persist_condition(conn, label, trial_count):
                scored += 1

            if scored % 500 == 0:
                logger.info("MONDO scoring: %d/%d scored", scored, len(rows))

    logger.info("MONDO expansion complete: %d diseases scored", scored)
    return {"mondo_loaded": total_mondo, "scored": scored, "source": "mondo"}


# ── Pre-scorer for expanded universe ─────────────────────────────────────────

async def prescored_universe_table(conn) -> None:
    """Create the extended disease scoring table if not exists."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS disease_scored (
            id              SERIAL PRIMARY KEY,
            disease_label   TEXT UNIQUE NOT NULL,
            mondo_id        VARCHAR(20),
            therapeutic_area VARCHAR(50),
            trial_count     INTEGER DEFAULT 0,
            score           FLOAT,
            tier            VARCHAR(20),
            opportunity     FLOAT,
            probability     FLOAT,
            value_score     FLOAT,
            approved_count  INTEGER DEFAULT 0,
            us_population   BIGINT,
            us_tam_fmt      TEXT,
            peak_revenue_fmt TEXT,
            notes           TEXT,
            last_scored     TIMESTAMPTZ DEFAULT NOW(),
            data_source     TEXT DEFAULT 'ct_gov_harvest'
        );
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS ds_score_idx ON disease_scored (score DESC NULLS LAST);")
    await conn.execute("CREATE INDEX IF NOT EXISTS ds_ta_idx ON disease_scored (therapeutic_area);")
    await conn.execute("CREATE INDEX IF NOT EXISTS ds_label_idx ON disease_scored (lower(disease_label));")


async def score_and_persist_condition(conn, condition: str, trial_count: int) -> bool:
    """Score one condition with TA-level defaults and upsert to disease_scored."""
    from app.services.opportunity_scorer_v2 import score_opportunity_v2, _tier

    ta = _classify_ta(condition)

    # TA-level defaults for unlisted diseases
    _TA_DEFAULTS = {
        "oncology":        {"phase": "phase2", "approved": 3, "pop": 80_000,   "cost": 150_000},
        "rare_disease":    {"phase": "phase2", "approved": 0, "pop": 15_000,   "cost": 300_000},
        "amr_infectious":  {"phase": "phase2", "approved": 2, "pop": 200_000,  "cost": 12_000},
        "cns":             {"phase": "phase2", "approved": 2, "pop": 300_000,  "cost": 30_000},
        "cardiovascular":  {"phase": "phase3", "approved": 4, "pop": 800_000,  "cost": 15_000},
        "metabolic":       {"phase": "phase3", "approved": 5, "pop": 2_000_000,"cost": 10_000},
        "gene_therapy":    {"phase": "phase2", "approved": 0, "pop": 10_000,   "cost": 2_000_000},
        "immunology":      {"phase": "phase2", "approved": 3, "pop": 400_000,  "cost": 40_000},
        "ophthalmology":   {"phase": "phase2", "approved": 2, "pop": 200_000,  "cost": 20_000},
        "vaccine":         {"phase": "phase3", "approved": 1, "pop": 5_000_000,"cost": 200},
        "hematology":      {"phase": "phase2", "approved": 3, "pop": 80_000,   "cost": 150_000},
        "device":          {"phase": "phase2", "approved": 1, "pop": 500_000,  "cost": 5_000},
        "respiratory":     {"phase": "phase2", "approved": 3, "pop": 600_000,  "cost": 20_000},
        "dermatology":     {"phase": "phase2", "approved": 3, "pop": 1_000_000,"cost": 25_000},
        "gastroenterology":{"phase": "phase2", "approved": 3, "pop": 300_000,  "cost": 40_000},
        "musculoskeletal": {"phase": "phase2", "approved": 4, "pop": 2_000_000,"cost": 8_000},
        "renal":           {"phase": "phase2", "approved": 2, "pop": 250_000,  "cost": 25_000},
        "other":           {"phase": "phase2", "approved": 2, "pop": 200_000,  "cost": 30_000},
    }
    d = _TA_DEFAULTS.get(ta, _TA_DEFAULTS["other"])

    try:
        r = await score_opportunity_v2(
            disease_name=condition,
            therapeutic_area=ta,
            development_phase=d["phase"],
            approved_treatments_count=d["approved"],
            competitor_trial_count=trial_count,
            annual_treatment_cost_usd=d["cost"],
            us_patient_population=d["pop"],
        )
        tier, _ = _tier(r["score"])
        s = r.get("subscores", {})

        await conn.execute("""
            INSERT INTO disease_scored
                (disease_label, therapeutic_area, trial_count, score, tier,
                 opportunity, probability, value_score,
                 approved_count, us_population, notes, last_scored)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,NOW())
            ON CONFLICT (disease_label) DO UPDATE SET
                therapeutic_area = EXCLUDED.therapeutic_area,
                trial_count      = EXCLUDED.trial_count,
                score            = EXCLUDED.score,
                tier             = EXCLUDED.tier,
                opportunity      = EXCLUDED.opportunity,
                probability      = EXCLUDED.probability,
                value_score      = EXCLUDED.value_score,
                last_scored      = NOW()
        """,
            condition, ta, trial_count, r["score"], tier,
            s.get("opportunity", 0), s.get("probability", 0), s.get("value", 0),
            d["approved"], d["pop"],
            f"Trial count: {trial_count} | TA: {ta} | Auto-scored from CT.gov",
        )
        return True
    except Exception as e:
        logger.debug("Score failed for '%s': %s", condition[:40], e)
        return False


async def run_universe_expansion(max_pages: int = 30) -> dict:
    """
    Main entry point: expand the disease universe to thousands using MONDO ontology
    + CT.gov conditions + curated 309 diseases.
    Primary source: MONDO (reliable, 20,000 diseases, no network blocks).
    Secondary source: CT.gov condition names (supplements MONDO).
    """
    from app.db.database import get_pool
    pool = await get_pool()

    async with pool.acquire() as conn:
        await prescored_universe_table(conn)

    # PRIMARY: MONDO ontology expansion (most reliable source)
    mondo_result = await run_mondo_expansion(max_pages=max_pages)
    logger.info("MONDO expansion: %s", mondo_result)

    # SECONDARY: CT.gov conditions (supplements MONDO with clinical trial names)
    try:
        condition_counts = await harvest_all_conditions(max_pages=min(max_pages, 20))
    except Exception as e:
        logger.warning("CT.gov harvest failed (non-fatal): %s", e)
        condition_counts = {}

    condition_counts = condition_counts  # may be empty if CT.gov blocked
    total_conditions = len(condition_counts)
    logger.info("Scoring %d conditions...", total_conditions)

    # Score in batches
    scored = 0
    async with pool.acquire() as conn:
        for condition, trial_count in condition_counts.items():
            if await score_and_persist_condition(conn, condition, trial_count):
                scored += 1
            if scored % 100 == 0:
                logger.info("Universe expansion: %d/%d scored", scored, total_conditions)

    # Also score all diseases from universe_builder (higher quality data)
    from app.services.universe_builder import get_universe
    universe = get_universe()
    async with pool.acquire() as conn:
        for disease, ta, phase, approved, cost, notes in universe:
            from app.services.opportunity_scorer_v2 import score_opportunity_v2, _tier, _TA_DEFAULTS
            _, pop, biomarker, modality, _ = _TA_DEFAULTS.get(ta, _TA_DEFAULTS["other"])
            try:
                r = await score_opportunity_v2(
                    disease_name=disease, therapeutic_area=ta,
                    development_phase=phase, approved_treatments_count=approved,
                    annual_treatment_cost_usd=cost, us_patient_population=pop,
                )
                tier_str, _ = _tier(r["score"])
                s = r.get("subscores", {})
                await conn.execute("""
                    INSERT INTO disease_scored
                        (disease_label, therapeutic_area, trial_count, score, tier,
                         opportunity, probability, value_score,
                         approved_count, us_population, notes, last_scored, data_source)
                    VALUES ($1,$2,0,$3,$4,$5,$6,$7,$8,$9,$10,NOW(),'universe_builder')
                    ON CONFLICT (disease_label) DO UPDATE SET
                        score=EXCLUDED.score, tier=EXCLUDED.tier,
                        opportunity=EXCLUDED.opportunity, probability=EXCLUDED.probability,
                        value_score=EXCLUDED.value_score, data_source='universe_builder',
                        last_scored=NOW()
                """,
                    disease, ta, r["score"], tier_str,
                    s.get("opportunity", 0), s.get("probability", 0), s.get("value", 0),
                    approved, pop, notes,
                )
            except Exception:
                pass

    return {
        "conditions_harvested": total_conditions,
        "conditions_scored":    scored,
        "curated_diseases":     len(universe),
    }


async def run_nightly_batch_scoring() -> dict:
    """
    Nightly job: score all diseases in two phases and persist to disease_scored.

    Phase 1 (~5-8 min): Run full opportunity_scorer_v2 engine on the 739+
    curated + ICD-10 diseases. Uses live trial/approval counts (populated by
    daytime traffic into the in-process caches). Persists sam_usd,
    peak_revenue_usd, commercial_tractability, and all sub-scores to DB.
    Then refreshes the in-process _DISCOVERY_RESULT_CACHE so morning users
    get an instant cache hit instead of a cold-start 25s rescore.

    Phase 2 (~10-15 min): Score any remaining MONDO-ontology diseases not
    yet in disease_scored, using TA-level defaults (no live API calls at
    that scale). Brings the DB toward the full 10,000-disease target.

    Scheduled: nightly at 2:30am UTC by ingestion_scheduler.
    """
    import time as _time
    start = _time.time()
    from app.db.database import get_pool
    pool = await get_pool()

    # Ensure schema has the extended columns (idempotent ALTER)
    async with pool.acquire() as conn:
        await prescored_universe_table(conn)
        await conn.execute("""
            ALTER TABLE disease_scored
                ADD COLUMN IF NOT EXISTS sam_usd                 BIGINT,
                ADD COLUMN IF NOT EXISTS peak_revenue_usd        BIGINT,
                ADD COLUMN IF NOT EXISTS us_tam_usd              BIGINT,
                ADD COLUMN IF NOT EXISTS commercial_tractability TEXT,
                ADD COLUMN IF NOT EXISTS tractability_note       TEXT,
                ADD COLUMN IF NOT EXISTS ptrs_pct                FLOAT
        """)

    # ── Phase 1: full engine on curated + ICD-10 universe ────────────────────
    phase1_count = 0
    try:
        from app.services.opportunity_scorer_v2 import run_discovery_engine_v2
        # top_n=10_000 returns all scored diseases (universe is ~739 curated)
        all_scored = await run_discovery_engine_v2(top_n=10_000)
        logger.info("Nightly batch phase 1: scored %d diseases", len(all_scored))

        async with pool.acquire() as conn:
            for r in all_scored:
                if not r:
                    continue
                s = r.get("subscores", {})
                try:
                    await conn.execute("""
                        INSERT INTO disease_scored
                            (disease_label, therapeutic_area, trial_count, score, tier,
                             opportunity, probability, value_score,
                             approved_count, us_population,
                             us_tam_fmt, us_tam_usd,
                             peak_revenue_fmt, sam_usd, peak_revenue_usd,
                             commercial_tractability, tractability_note,
                             ptrs_pct, notes, last_scored, data_source)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,NOW(),'nightly_full_score')
                        ON CONFLICT (disease_label) DO UPDATE SET
                            therapeutic_area        = EXCLUDED.therapeutic_area,
                            trial_count             = EXCLUDED.trial_count,
                            score                   = EXCLUDED.score,
                            tier                    = EXCLUDED.tier,
                            opportunity             = EXCLUDED.opportunity,
                            probability             = EXCLUDED.probability,
                            value_score             = EXCLUDED.value_score,
                            approved_count          = EXCLUDED.approved_count,
                            us_population           = EXCLUDED.us_population,
                            us_tam_fmt              = EXCLUDED.us_tam_fmt,
                            us_tam_usd              = EXCLUDED.us_tam_usd,
                            peak_revenue_fmt        = EXCLUDED.peak_revenue_fmt,
                            sam_usd                 = EXCLUDED.sam_usd,
                            peak_revenue_usd        = EXCLUDED.peak_revenue_usd,
                            commercial_tractability = EXCLUDED.commercial_tractability,
                            tractability_note       = EXCLUDED.tractability_note,
                            ptrs_pct                = EXCLUDED.ptrs_pct,
                            last_scored             = NOW(),
                            data_source             = 'nightly_full_score'
                    """,
                        r.get("disease"),           # $1
                        r.get("therapeutic_area"),  # $2
                        r.get("competitor_trial_count", 0),  # $3
                        r.get("score"),             # $4
                        r.get("tier"),              # $5
                        s.get("opportunity", 0),    # $6
                        s.get("probability", 0),    # $7
                        s.get("value", 0),          # $8
                        r.get("approved_treatments_count", 0),  # $9
                        r.get("us_patient_population", 0),      # $10
                        r.get("us_tam_fmt"),         # $11
                        r.get("us_tam_usd"),         # $12
                        r.get("peak_revenue_fmt"),   # $13
                        r.get("sam_usd"),            # $14
                        r.get("peak_revenue_usd"),   # $15
                        r.get("commercial_tractability"),  # $16
                        r.get("tractability_note"),  # $17
                        r.get("ptrs"),               # $18
                        r.get("notes", ""),          # $19
                    )
                    phase1_count += 1
                except Exception as e:
                    logger.debug("Persist failed '%s': %s", r.get("disease", "?")[:40], e)

    except Exception as e:
        logger.error("Nightly batch phase 1 failed: %s", e)

    logger.info("Nightly batch phase 1 persisted: %d diseases", phase1_count)

    # ── Phase 2: MONDO expansion for the remaining ~9,000+ diseases ──────────
    phase2_count = 0
    try:
        result = await run_mondo_expansion(max_pages=20)
        phase2_count = result.get("scored", 0)
        logger.info("Nightly batch phase 2 MONDO: %d additional diseases", phase2_count)
    except Exception as e:
        logger.warning("Nightly batch phase 2 MONDO failed (non-fatal): %s", e)

    elapsed = round(_time.time() - start, 1)
    total = phase1_count + phase2_count
    logger.info("Nightly batch scoring complete: %d diseases in %.1fs", total, elapsed)

    return {
        "phase1_curated":   phase1_count,
        "phase2_mondo":     phase2_count,
        "total":            total,
        "elapsed_seconds":  elapsed,
    }
