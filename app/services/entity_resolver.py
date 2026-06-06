"""
Entity Resolver
===============
Maps free-text disease/drug mentions → canonical IDs (MONDO / RxCUI).

Resolution cascade (deterministic-first, probabilistic-second):
  Disease:
    1. Exact label match against disease table (case-insensitive)
    2. Synonym match against disease.synonyms array
    3. xref_map lookup (previous resolutions cached here)
    4. OLS4 MONDO API search (exact, then fuzzy)
    5. Store with method + confidence; return None if unresolvable

  Drug:
    1. Exact label/generic_name match against drug table
    2. xref_map lookup
    3. RxNav exact → approximate cascade
    4. Store result in xref_map for future lookups

All resolutions are persisted in xref_map with method + confidence so
every mapping is transparent and auditable. Manual overrides (curated=TRUE)
take priority over all automated methods.

Usage:
    from app.services.entity_resolver import resolve_disease, resolve_drug

    mondo_id = await resolve_disease("Alzheimer's disease")
    rxcui    = await resolve_drug("metformin hydrochloride")
"""

import logging
import re
import time
from typing import Optional

from app.db.database import get_pool
from app.ingestion.connectors.mondo import _search_mondo, _fetch_term_by_iri, _term_to_row, _upsert_disease
from app.ingestion.connectors.rxnorm import resolve_drug_name, _upsert_drug, _build_drug_row

logger = logging.getLogger(__name__)

_DELAY = 0.15


# ── Normalisation helpers ─────────────────────────────────────────────────────

def _normalize_text(s: str) -> str:
    """Lowercase, strip punctuation variants, collapse whitespace."""
    s = s.lower().strip()
    s = re.sub(r"[''`]", "", s)          # remove apostrophes
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\(.*?\)", "", s).strip() # strip parenthetical qualifiers
    return s


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _check_xref_cache(conn, source_id: str, canonical_type: str) -> Optional[str]:
    """Look up a previous resolution in xref_map. Curated results take priority."""
    row = await conn.fetchrow("""
        SELECT canonical_id FROM xref_map
        WHERE lower(source_id) = lower($1)
          AND canonical_type   = $2
        ORDER BY curated DESC, confidence DESC
        LIMIT 1
    """, source_id, canonical_type)
    return row["canonical_id"] if row else None


async def _store_xref(conn, source_name: str, source_id: str,
                      canonical_type: str, canonical_id: str,
                      canonical_label: str, method: str, confidence: float) -> None:
    try:
        await conn.execute("""
            INSERT INTO xref_map
                (source_name, source_id, canonical_type, canonical_id, canonical_label, method, confidence)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (source_name, source_id, canonical_type) DO UPDATE SET
                canonical_id    = EXCLUDED.canonical_id,
                canonical_label = EXCLUDED.canonical_label,
                method          = EXCLUDED.method,
                confidence      = EXCLUDED.confidence
        """, source_name, source_id, canonical_type, canonical_id, canonical_label, method, confidence)
    except Exception as e:
        logger.warning("xref store failed: %s", e)


# ── Disease resolution ────────────────────────────────────────────────────────

async def resolve_disease(text: str, source_name: str = "query") -> Optional[str]:
    """
    Resolve a free-text disease name to a MONDO ID.
    Returns MONDO ID string (e.g. 'MONDO:0004975') or None.
    """
    if not text or len(text) < 3:
        return None

    pool = await get_pool()
    norm = _normalize_text(text)

    async with pool.acquire() as conn:
        # 1. Cache: exact match in xref_map
        cached = await _check_xref_cache(conn, text, "disease")
        if cached:
            return cached

        # 2. Exact label match in disease table
        row = await conn.fetchrow(
            "SELECT mondo_id, label FROM disease WHERE lower(label) = lower($1)", text
        )
        if not row:
            row = await conn.fetchrow(
                "SELECT mondo_id, label FROM disease WHERE lower(label) = lower($1)", norm
            )
        if row:
            await _store_xref(conn, source_name, text, "disease",
                              row["mondo_id"], row["label"], "exact_label", 1.0)
            return row["mondo_id"]

        # 3. Synonym match
        row = await conn.fetchrow(
            "SELECT mondo_id, label FROM disease WHERE $1 = ANY(synonyms)", text.lower()
        )
        if not row:
            row = await conn.fetchrow(
                "SELECT mondo_id, label FROM disease WHERE $1 = ANY(synonyms)", norm
            )
        if row:
            await _store_xref(conn, source_name, text, "disease",
                              row["mondo_id"], row["label"], "synonym", 0.95)
            return row["mondo_id"]

        # 4. OLS4 MONDO API — exact then fuzzy
        time.sleep(_DELAY)
        docs = _search_mondo(text, exact=True, rows=3)
        method, confidence = "ols4_exact", 0.92
        if not docs:
            docs = _search_mondo(norm, exact=False, rows=5)
            method, confidence = "ols4_fuzzy", 0.75

        if docs:
            best = next((d for d in docs
                         if _normalize_text(d.get("label","")) == norm), docs[0])
            if _normalize_text(best.get("label","")) == norm:
                method, confidence = "ols4_exact", 0.95

            iri  = best.get("iri") or ""
            time.sleep(_DELAY)
            term = _fetch_term_by_iri(iri) if iri else None
            term_row = _term_to_row(term) if term else None

            if term_row:
                await _upsert_disease(conn, term_row)
                mondo_id = term_row["mondo_id"]
                await _store_xref(conn, source_name, text, "disease",
                                  mondo_id, term_row["label"], method, confidence)
                return mondo_id

    logger.info("MONDO: could not resolve '%s'", text)
    return None


# ── Drug resolution ───────────────────────────────────────────────────────────

async def resolve_drug(text: str, source_name: str = "query") -> Optional[str]:
    """
    Resolve a free-text drug name to an RxCUI.
    Returns RxCUI string or None.
    """
    if not text or len(text) < 2:
        return None

    pool = await get_pool()

    async with pool.acquire() as conn:
        # 1. Cache
        cached = await _check_xref_cache(conn, text, "drug")
        if cached:
            return cached

        # 2. Exact label match in drug table
        row = await conn.fetchrow(
            "SELECT rxcui, label FROM drug WHERE lower(label) = lower($1) OR lower(generic_name) = lower($1)",
            text
        )
        if row:
            await _store_xref(conn, source_name, text, "drug",
                              row["rxcui"], row["label"], "exact_label", 1.0)
            return row["rxcui"]

        # 3. RxNav cascade
        time.sleep(_DELAY)
        result = resolve_drug_name(text)
        if result:
            rxcui = result["rxcui"]
            row_data = _build_drug_row(rxcui, result["label"], result.get("tty",""))
            await _upsert_drug(conn, row_data)
            await _store_xref(conn, source_name, text, "drug",
                              rxcui, result["label"], result["method"], result["confidence"])
            return rxcui

    logger.info("RxNorm: could not resolve '%s'", text)
    return None


# ── Batch helpers ─────────────────────────────────────────────────────────────

async def resolve_diseases_batch(names: list[str],
                                 source_name: str = "batch") -> dict[str, Optional[str]]:
    """Resolve a list of disease names. Returns {name: mondo_id_or_None}."""
    return {name: await resolve_disease(name, source_name) for name in names}


async def resolve_drugs_batch(names: list[str],
                              source_name: str = "batch") -> dict[str, Optional[str]]:
    """Resolve a list of drug names. Returns {name: rxcui_or_None}."""
    return {name: await resolve_drug(name, source_name) for name in names}


# ── ICD-10 / MeSH → MONDO lookup ─────────────────────────────────────────────

async def mondo_from_icd10(icd_code: str) -> Optional[str]:
    """Return MONDO ID for an ICD-10 code, if loaded in the disease table."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT mondo_id FROM disease WHERE $1 = ANY(icd10_ids) LIMIT 1", icd_code
        )
        return row["mondo_id"] if row else None


async def mondo_from_mesh(mesh_id: str) -> Optional[str]:
    """Return MONDO ID for a MeSH descriptor ID."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT mondo_id FROM disease WHERE $1 = ANY(mesh_ids) LIMIT 1", mesh_id
        )
        return row["mondo_id"] if row else None
