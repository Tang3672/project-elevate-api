from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.models.needs import (
    NeedSubmissionRequest, NeedResponse, NeedListResponse,
    SimilarNeedsResponse
)
from app.services.classification_service import classify_need
from app.services.embedding_service import embed_text
from app.db.needs_repository import (
    insert_need, get_needs, get_need_by_id, find_similar_needs
)

router = APIRouter()


@router.post("", response_model=NeedResponse, status_code=201)
async def submit_need(payload: NeedSubmissionRequest):
    try:
        classification = await classify_need(payload.raw_text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Classification failed: {str(e)}")

    try:
        embedding = await embed_text(payload.raw_text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Embedding failed: {str(e)}")

    saved = await insert_need(
        raw_text=payload.raw_text,
        department=classification.department,
        category=classification.category.value,
        subcategory=classification.subcategory,
        urgency_score=classification.urgency_score,
        patient_impact_score=classification.patient_impact_score,
        keywords=classification.keywords,
        embedding=embedding,
        hospital_id=payload.hospital_id,
        submitted_by=payload.submitted_by,
        source="manual"
    )
    return saved


@router.get("", response_model=NeedListResponse)
async def list_needs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    category: Optional[str] = Query(default=None),
    department: Optional[str] = Query(default=None),
    min_urgency: Optional[int] = Query(default=None, ge=1, le=5)
):
    total, items = await get_needs(
        limit=limit, offset=offset,
        category=category, department=department, min_urgency=min_urgency
    )
    return NeedListResponse(total=total, items=items)


@router.get("/{need_id}", response_model=NeedResponse)
async def get_need(need_id: int):
    need = await get_need_by_id(need_id)
    if not need:
        raise HTTPException(status_code=404, detail=f"Need {need_id} not found")
    return need


@router.post("/search", response_model=SimilarNeedsResponse)
async def search_similar_needs(
    query: str,
    top_k: int = Query(default=10, ge=1, le=50),
    min_similarity: float = Query(default=0.6, ge=0.0, le=1.0)
):
    try:
        query_embedding = await embed_text(query)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Embedding failed: {str(e)}")

    matches = await find_similar_needs(
        query_embedding=query_embedding,
        top_k=top_k,
        min_similarity=min_similarity
    )
    return SimilarNeedsResponse(query=query, matches=matches)
