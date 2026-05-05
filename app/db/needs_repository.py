"""
Repository layer: all database operations for hospital_needs.

Keeps SQL out of the API routes and services.
All methods accept a connection (acquired from the pool by the caller).
"""

from typing import List, Optional
from app.models.needs import NeedResponse, SimilarNeed
from app.db.database import get_pool


async def insert_need(
    raw_text: str,
    department: str,
    category: str,
    subcategory: str,
    urgency_score: int,
    patient_impact_score: int,
    keywords: List[str],
    embedding: List[float],
    hospital_id: Optional[str] = None,
    submitted_by: Optional[str] = None,
    source: str = "manual"
) -> NeedResponse:
    """Insert a classified need with its embedding. Returns the saved record."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO hospital_needs
                (raw_text, department, category, subcategory,
                 urgency_score, patient_impact_score, keywords,
                 embedding, hospital_id, submitted_by, source)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector, $9, $10, $11)
            RETURNING id, raw_text, department, category, subcategory,
                      urgency_score, patient_impact_score, keywords,
                      hospital_id, submitted_by, source, created_at
            """,
            raw_text, department, category, subcategory,
            urgency_score, patient_impact_score, keywords,
            str(embedding),  # pgvector accepts '[0.1, 0.2, ...]' string format
            hospital_id, submitted_by, source
        )
    return _row_to_need_response(row)


async def get_needs(
    limit: int = 50,
    offset: int = 0,
    category: Optional[str] = None,
    department: Optional[str] = None,
    min_urgency: Optional[int] = None
) -> tuple[int, List[NeedResponse]]:
    """Fetch needs with optional filters. Returns (total_count, items)."""
    pool = await get_pool()

    filters = []
    params = []
    param_idx = 1

    if category:
        filters.append(f"category = ${param_idx}")
        params.append(category.upper())
        param_idx += 1
    if department:
        filters.append(f"department ILIKE ${param_idx}")
        params.append(f"%{department}%")
        param_idx += 1
    if min_urgency:
        filters.append(f"urgency_score >= ${param_idx}")
        params.append(min_urgency)
        param_idx += 1

    where_clause = "WHERE " + " AND ".join(filters) if filters else ""

    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM hospital_needs {where_clause}",
            *params
        )

        rows = await conn.fetch(
            f"""
            SELECT id, raw_text, department, category, subcategory,
                   urgency_score, patient_impact_score, keywords,
                   hospital_id, submitted_by, source, created_at
            FROM hospital_needs
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
            """,
            *params, limit, offset
        )

    return total, [_row_to_need_response(r) for r in rows]


async def get_need_by_id(need_id: int) -> Optional[NeedResponse]:
    """Fetch a single need by ID."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, raw_text, department, category, subcategory,
                   urgency_score, patient_impact_score, keywords,
                   hospital_id, submitted_by, source, created_at
            FROM hospital_needs WHERE id = $1
            """,
            need_id
        )
    return _row_to_need_response(row) if row else None


async def find_similar_needs(
    query_embedding: List[float],
    top_k: int = 10,
    min_similarity: float = 0.6
) -> List[SimilarNeed]:
    """
    Find the most semantically similar hospital needs using cosine similarity.

    min_similarity=0.6 means "at least moderately related".
    Cosine distance in pgvector: 0=identical, 2=opposite.
    So similarity = 1 - (cosine_distance / 2) maps to [0, 1].
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, raw_text, department, category, subcategory,
                   urgency_score, patient_impact_score, keywords, created_at,
                   1 - (embedding <=> $1::vector) / 2 AS similarity_score
            FROM hospital_needs
            WHERE 1 - (embedding <=> $1::vector) / 2 >= $2
            ORDER BY embedding <=> $1::vector
            LIMIT $3
            """,
            str(query_embedding),
            min_similarity,
            top_k
        )

    return [
        SimilarNeed(
            id=r["id"],
            raw_text=r["raw_text"],
            department=r["department"],
            category=r["category"],
            subcategory=r["subcategory"],
            urgency_score=r["urgency_score"],
            patient_impact_score=r["patient_impact_score"],
            keywords=list(r["keywords"]) if r["keywords"] else [],
            similarity_score=round(float(r["similarity_score"]), 4),
            created_at=r["created_at"]
        )
        for r in rows
    ]


# ── Private helpers ───────────────────────────────────────────────────────────

def _row_to_need_response(row) -> NeedResponse:
    return NeedResponse(
        id=row["id"],
        raw_text=row["raw_text"],
        department=row["department"],
        category=row["category"],
        subcategory=row["subcategory"],
        urgency_score=row["urgency_score"],
        patient_impact_score=row["patient_impact_score"],
        keywords=list(row["keywords"]) if row["keywords"] else [],
        hospital_id=row["hospital_id"],
        submitted_by=row["submitted_by"],
        source=row["source"],
        created_at=row["created_at"]
    )
