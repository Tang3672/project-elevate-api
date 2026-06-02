"""
OpenAlex Publications Connector
=================================
Source:  OpenAlex REST API (api.openalex.org)
License: CC0 — fully commercial-safe; attribution appreciated
Rate:    Polite pool (add mailto param): 10 req/sec; no key required
Data:    474M+ scholarly works, citations, abstracts (inverted index), OA PDFs

Strategy:
  For each disease in our universe, fetch the top N most-cited open-access
  papers and store their metadata + reconstructed abstract in the
  `publication` table for RAG embedding (Phase 3b).

  Also stores per-disease publication counts in disease_burden for the
  scoring signal (academic momentum / research activity).

OpenAlex abstract_inverted_index: a dict of word → [positions].
We reconstruct the plain-text abstract from this.

License note on individual articles:
  OpenAlex metadata is CC0. The underlying articles vary (CC-BY/NC/0/OA).
  We store only metadata + abstracts (not full-text PDFs).
  Abstracts are generally fair use / covered by open access licensing.
"""

import logging
import time
from typing import Optional

import requests

from app.db.database import get_pool

logger = logging.getLogger(__name__)

OPENALEX_BASE = "https://api.openalex.org"
_MAILTO = "contact@projectelevate.io"   # polite pool: much higher rate limit
_DELAY  = 0.12   # ~8 req/sec, well under 10


# ── Abstract reconstruction ───────────────────────────────────────────────────

def _reconstruct_abstract(inverted_index: Optional[dict]) -> Optional[str]:
    """Convert OpenAlex abstract_inverted_index back to plain text."""
    if not inverted_index:
        return None
    try:
        words = {}
        for word, positions in inverted_index.items():
            for pos in positions:
                words[pos] = word
        return " ".join(words[i] for i in sorted(words))
    except Exception:
        return None


# ── API helpers ───────────────────────────────────────────────────────────────

def _search_works(query: str, oa_only: bool = True,
                  per_page: int = 50, page: int = 1,
                  sort: str = "cited_by_count:desc") -> dict:
    params = {
        "search":   query,
        "sort":     sort,
        "per-page": per_page,
        "page":     page,
        "mailto":   _MAILTO,
    }
    if oa_only:
        params["filter"] = "open_access.is_oa:true"
    try:
        r = requests.get(f"{OPENALEX_BASE}/works", params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning("OpenAlex search failed for '%s': %s", query, e)
        return {}


def _get_top_works(query: str, limit: int = 100,
                   oa_only: bool = True) -> tuple[int, list[dict]]:
    """Return (total_count, [work dicts]) for top cited papers."""
    works = []
    per_page = min(limit, 50)
    page = 1
    total = 0

    while len(works) < limit:
        data = _search_works(query, oa_only, per_page=per_page, page=page)
        time.sleep(_DELAY)
        meta   = data.get("meta", {})
        total  = meta.get("count", 0)
        batch  = data.get("results", [])
        if not batch:
            break
        works.extend(batch)
        page  += 1
        if len(works) >= limit or len(batch) < per_page:
            break

    return total, works[:limit]


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _ensure_publication_table(conn) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS publication (
            id              SERIAL PRIMARY KEY,
            openalex_id     TEXT UNIQUE,
            doi             TEXT,
            pmid            TEXT,
            title           TEXT NOT NULL,
            abstract        TEXT,
            publication_year INTEGER,
            cited_by_count  INTEGER DEFAULT 0,
            is_oa           BOOLEAN DEFAULT TRUE,
            journal         TEXT,
            -- Disease linkage
            disease_label   TEXT,
            mondo_id        VARCHAR(20),
            -- Embedding (populated in Phase 3b)
            embedding       vector(1536),
            embedded_at     TIMESTAMPTZ,
            -- Metadata
            source          TEXT DEFAULT 'openalex',
            fetched_at      TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS pub_disease_idx ON publication (disease_label);"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS pub_mondo_idx ON publication (mondo_id);"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS pub_year_idx ON publication (publication_year DESC);"
    )
    # HNSW index for vector similarity — created after embeddings are populated
    try:
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS pub_embedding_idx
            ON publication USING hnsw (embedding vector_cosine_ops)
            WITH (m=16, ef_construction=64);
        """)
    except Exception:
        pass  # pgvector may not be available


async def _upsert_publication(conn, work: dict,
                               disease_label: str, mondo_id: Optional[str]) -> None:
    oa_id = work.get("id", "").replace("https://openalex.org/", "")
    doi   = work.get("doi") or None
    pmid  = None
    for loc in (work.get("ids") or {}):
        pass  # ids is a dict
    ids_dict = work.get("ids") or {}
    pmid = str(ids_dict.get("pmid", "")).replace("https://pubmed.ncbi.nlm.nih.gov/", "") or None

    abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))
    source   = work.get("primary_location") or {}
    journal  = (source.get("source") or {}).get("display_name") if isinstance(source, dict) else None

    try:
        await conn.execute("""
            INSERT INTO publication
                (openalex_id, doi, pmid, title, abstract, publication_year,
                 cited_by_count, is_oa, journal, disease_label, mondo_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            ON CONFLICT (openalex_id) DO UPDATE SET
                cited_by_count = EXCLUDED.cited_by_count,
                abstract       = COALESCE(EXCLUDED.abstract, publication.abstract),
                disease_label  = EXCLUDED.disease_label,
                mondo_id       = COALESCE(EXCLUDED.mondo_id, publication.mondo_id),
                fetched_at     = NOW()
        """,
            oa_id, doi, pmid,
            (work.get("title") or "")[:500],
            abstract,
            work.get("publication_year"),
            work.get("cited_by_count") or 0,
            work.get("open_access", {}).get("is_oa", False),
            journal,
            disease_label,
            mondo_id,
        )
    except Exception as e:
        logger.warning("publication upsert failed: %s", e)


async def _upsert_pub_burden(conn, disease_label: str, mondo_id: Optional[str],
                              total_count: int) -> None:
    try:
        await conn.execute("""
            INSERT INTO disease_burden
                (mondo_id, disease_label, source_name, source_code, commercial_safe,
                 metric, value, unit, location, year)
            VALUES ($1,$2,'openalex','openalex',TRUE,'publication_count',$3,'papers','Global',2024)
            ON CONFLICT (mondo_id, source_name, metric, location, year, age_group, sex)
            DO UPDATE SET value=EXCLUDED.value, fetched_at=NOW()
        """, mondo_id, disease_label, float(total_count))
    except Exception as e:
        logger.warning("publication burden upsert failed: %s", e)


# ── Disease → OpenAlex search terms ──────────────────────────────────────────

_DISEASE_SEARCH_TERMS: dict[str, str] = {
    "Glioblastoma Multiforme":               "glioblastoma multiforme treatment",
    "Pancreatic Ductal Adenocarcinoma":      "pancreatic cancer therapy",
    "ALS (SOD1-mutant)":                     "amyotrophic lateral sclerosis SOD1",
    "Carbapenem-resistant Enterobacterales": "carbapenem resistant Enterobacterales treatment",
    "Acinetobacter baumannii MDR":           "Acinetobacter baumannii antibiotic",
    "Spinal Muscular Atrophy Type 2":        "spinal muscular atrophy gene therapy",
    "HER2-low Breast Cancer":               "HER2 low breast cancer trastuzumab deruxtecan",
    "KRAS G12C NSCLC":                       "KRAS G12C non-small cell lung cancer sotorasib",
    "Huntington Disease":                    "Huntington disease treatment clinical trial",
    "Friedreich Ataxia":                     "Friedreich ataxia omaveloxolone treatment",
    "C. difficile Infection":               "Clostridioides difficile treatment recurrence",
    "MRSA Skin Infections":                  "MRSA skin soft tissue infection antibiotic",
    "Type 1 Diabetes (CGM/automated insulin)": "type 1 diabetes continuous glucose monitor",
    "Alzheimer Disease (early/MCI)":        "Alzheimer disease lecanemab donanemab amyloid",
    "Pulmonary Arterial Hypertension":       "pulmonary arterial hypertension treatment",
    "Duchenne Muscular Dystrophy":           "Duchenne muscular dystrophy gene therapy exon skipping",
    "Myelofibrosis JAK-resistant":           "myelofibrosis JAK inhibitor ruxolitinib resistance",
    "Geographic Atrophy (dry AMD)":          "geographic atrophy AMD pegcetacoplan avacincaptad",
    "Sickle Cell Disease (gene therapy)":    "sickle cell disease gene therapy CRISPR",
    "RSV in elderly/immunocompromised":      "RSV respiratory syncytial virus elderly vaccine",
    "Sepsis (AI early detection)":           "sepsis early detection machine learning artificial intelligence",
    "NASH/MASH":                             "nonalcoholic steatohepatitis NASH resmetirom treatment",
    "Prostate Cancer (PSMA-targeted)":       "prostate cancer PSMA lutetium radioligand therapy",
    "Bipolar Depression":                    "bipolar disorder depression lumateperone treatment",
    "Rare Pediatric Epilepsy (SCN1A)":       "Dravet syndrome SCN1A epilepsy treatment",
}


# ── Public entry points ───────────────────────────────────────────────────────

async def load_publications(limit_per_disease: int = 50) -> dict[str, int]:
    """
    Fetch top papers for each disease and persist to publication table.
    Returns {disease_name: paper_count_fetched}.
    """
    pool = await get_pool()
    results: dict[str, int] = {}

    async with pool.acquire() as conn:
        await _ensure_publication_table(conn)

        for disease, query in _DISEASE_SEARCH_TERMS.items():
            total, works = _get_top_works(query, limit=limit_per_disease)

            mondo_id = None
            try:
                row = await conn.fetchrow(
                    "SELECT mondo_id FROM disease WHERE lower(label)=lower($1)", disease
                )
                if row:
                    mondo_id = row["mondo_id"]
            except Exception:
                pass

            for work in works:
                await _upsert_publication(conn, work, disease, mondo_id)

            await _upsert_pub_burden(conn, disease, mondo_id, total)
            results[disease] = len(works)
            logger.info("OpenAlex: %s → %d papers loaded (total=%d)", disease, len(works), total)

    return results
