from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum

class InnovationCategory(str, Enum):
    SOFTWARE = "SOFTWARE"
    HARDWARE = "HARDWARE"
    SERVICE = "SERVICE"
    PHARMACEUTICALS = "PHARMACEUTICALS"
    HYBRID = "HYBRID"
    UNCATEGORIZED = "UNCATEGORIZED"

class NeedSubmissionRequest(BaseModel):
    raw_text: str = Field(..., min_length=20, max_length=5000)
    hospital_id: Optional[str] = None
    submitted_by: Optional[str] = None

class ClassifiedNeed(BaseModel):
    department: str
    category: InnovationCategory
    subcategory: str
    urgency_score: int = Field(ge=1, le=5)
    patient_impact_score: int = Field(ge=1, le=5)
    keywords: List[str]
    reasoning: str

class NeedResponse(BaseModel):
    id: int
    raw_text: str
    department: str
    category: str
    subcategory: str
    urgency_score: int
    patient_impact_score: int
    keywords: List[str]
    hospital_id: Optional[str]
    submitted_by: Optional[str]
    source: str
    created_at: datetime

class NeedListResponse(BaseModel):
    total: int
    items: List[NeedResponse]

class SimilarNeed(BaseModel):
    id: int
    raw_text: str
    department: str
    category: str
    subcategory: str
    urgency_score: int
    patient_impact_score: int
    keywords: List[str]
    similarity_score: float = Field(ge=0.0, le=1.0)
    created_at: datetime

class SimilarNeedsResponse(BaseModel):
    query: str
    matches: List[SimilarNeed]
