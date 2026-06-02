"""
RAG Retrieval Service
======================
Hybrid retrieval over the `publication` table using:
  1. Semantic search   — pgvector cosine similarity (HNSW index)
  2. Full-text search  — Postgres tsvector + ts_rank (BM25-like)
  3. Reciprocal Rank Fusion (RRF) — merges both ranked lists

This runs entirely in PostgreSQL — no separate vector DB needed
at our scale (< 5M documents). See guide §3 for migration triggers.

Embedding pipeline:
  - embed_publications(): batch-embeds abstracts using OpenAI text-embedding-3-small
    (1536-dim). Called by the scheduler after load_publications().
  - retrieve(): at query time, embeds the query and runs hybrid search.

RAG context is injected into the PI report narrative sections in
alignment_service.py via retrieve_context_for_idea().
"""

import json
import logging
from typing import Optional

from app.db.database import get_pool
from app.services.embedding_service import embed_text
from app.core.config import settings

logger = logging.getLogger(__name__)

_EMBED_BATCH = 20   # abstracts per OpenAI embedding batch


# ── Embedding pipeline ────────────────────────────────────────────────────────

async def embed_publications(disease_label: Optional[str] = None,
                              limit: int = 500) -> int:
    """
    Embed abstracts for publications that don't yet have an embedding.
    Runs in batches to respect OpenAI rate limits.
    Returns number of publications embedded.
    """
    pool = await get_pool()
    embedded = 0

    async with pool.acquire() as conn:
        where = "WHERE embedding IS NULL AND abstract IS NOT NULL"
        if disease_label:
            where += f" AND disease_label = '{disease_label.replace(chr(39), '')}'"

        rows = await conn.fetch(
            f"SELECT id, title, abstract FROM publication {where} LIMIT $1", limit
        )

        for i in range(0, len(rows), _EMBED_BATCH):
            batch = rows[i: i + _EMBED_BATCH]
            for row in batch:
                text = f"{row['title']}\n\n{row['abstract'] or ''}"
                try:
                    vector = await embed_text(text)
                    if vector:
                        await conn.execute(
                            "UPDATE publication SET embedding=$1, embedded_at=NOW() WHERE id=$2",
                            vector, row["id"],
                        )
                        embedded += 1
                except Exception as e:
                    logger.warning("Embedding failed for pub id=%d: %s", row["id"], e)

    logger.info("Embedded %d publications", embedded)
    return embedded


# ── Retrieval ─────────────────────────────────────────────────────────────────

async def retrieve(query: str, disease_label: Optional[str] = None,
                   top_k: int = 8, semantic_weight: float = 0.6) -> list[dict]:
    """
    Hybrid semantic + full-text retrieval using RRF.

    Args:
        query:          Free-text query (e.g. the user's idea).
        disease_label:  Optional filter to disease-specific papers.
        top_k:          Number of results to return.
        semantic_weight: Weight for semantic vs FTS score (0-1).

    Returns list of dicts: {title, abstract, doi, cited_by_count, score, source}.
    """
    pool = await get_pool()

    # 1. Embed query
    try:
        query_vec = await embed_text(query)
    except Exception as e:
        logger.warning("Query embedding failed, falling back to FTS only: %s", e)
        query_vec = None

    disease_filter = ""
    disease_param  = []
    if disease_label:
        disease_filter = "AND disease_label = $2"
        disease_param  = [disease_label]

    async with pool.acquire() as conn:
        results = []

        # 2. Semantic search (if embedding available)
        sem_rows = []
        if query_vec:
            try:
                sem_sql = f"""
                    SELECT id, title, abstract, doi, cited_by_count,
                           1 - (embedding <=> $1::vector) AS sem_score
                    FROM publication
                    WHERE embedding IS NOT NULL {disease_filter}
                    ORDER BY embedding <=> $1::vector
                    LIMIT {top_k * 3}
                """
                params = [query_vec] + disease_param
                sem_rows = await conn.fetch(sem_sql, *params)
            except Exception as e:
                logger.warning("Semantic search failed: %s", e)

        # 3. Full-text search
        fts_rows = []
        try:
            fts_sql = f"""
                SELECT id, title, abstract, doi, cited_by_count,
                       ts_rank(to_tsvector('english', coalesce(title,'') || ' ' || coalesce(abstract,'')),
                               plainto_tsquery('english', $1)) AS fts_score
                FROM publication
                WHERE to_tsvector('english', coalesce(title,'') || ' ' || coalesce(abstract,''))
                      @@ plainto_tsquery('english', $1)
                  {disease_filter}
                ORDER BY fts_score DESC
                LIMIT {top_k * 3}
            """
            params = [query] + disease_param
            fts_rows = await conn.fetch(fts_sql, *params)
        except Exception as e:
            logger.warning("FTS search failed: %s", e)

        # 4. Reciprocal Rank Fusion
        rrf_k   = 60  # standard RRF constant
        scores: dict[int, float] = {}
        titles: dict[int, dict]  = {}

        def _store(row):
            titles[row["id"]] = {
                "title":          row["title"],
                "abstract":       (row["abstract"] or "")[:800],
                "doi":            row.get("doi"),
                "cited_by_count": row.get("cited_by_count", 0),
            }

        for rank, row in enumerate(sem_rows, 1):
            scores[row["id"]] = scores.get(row["id"], 0) + semantic_weight / (rrf_k + rank)
            _store(row)

        fts_weight = 1.0 - semantic_weight
        for rank, row in enumerate(fts_rows, 1):
            scores[row["id"]] = scores.get(row["id"], 0) + fts_weight / (rrf_k + rank)
            _store(row)

        # 5. Sort + format
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        for pub_id, score in ranked:
            meta = titles[pub_id]
            results.append({**meta, "score": round(score, 4), "source": "openalex"})

    return results


async def retrieve_context_for_idea(idea: str, disease_label: Optional[str] = None,
                                    top_k: int = 6) -> str:
    """
    High-level helper: retrieve papers and format them as a cited context block
    for injection into an LLM prompt.
    """
    papers = await retrieve(idea, disease_label=disease_label, top_k=top_k)
    if not papers:
        return ""

    lines = ["Relevant literature (from OpenAlex CC0 database):"]
    for i, p in enumerate(papers, 1):
        doi_str = f" | DOI: {p['doi']}" if p.get("doi") else ""
        lines.append(
            f"\n[{i}] {p['title']}{doi_str} | Cited: {p.get('cited_by_count', 0)}"
        )
        if p.get("abstract"):
            lines.append(f"     Abstract: {p['abstract'][:300]}...")

    return "\n".join(lines)
