from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum

# ── Enums matching the Health_Innovation_Categories doc ──────────────────────

class InnovationCategory(str, Enum):
    SOFTWARE = "SOFTWARE"
    HARDWARE = "HARDWARE"
    SERVICE = "SERVICE"
    PHARMACEUTICALS = "PHARMACEUTICALS"
    HYBRID = "HYBRID"
    UNCATEGORIZED = "UNCATEGORIZED"

class UrgencyLevel(int, Enum):
    LOW = 1
    MODERATE = 2
    MEDIUM = 3
    HIGH = 4
    CRITICAL = 5

# ── Request / Response Schemas ────────────────────────────────────────────────

class NeedSubmissionRequest(BaseModel):
    """What a hospital worker submits via the form."""
    raw_text: str = Field(
        ...,
        min_length=20,
        max_length=5000,
        description="Free-text description of the problem or unmet need",
        examples=["We frequently lose track of patient vitals during shift handoffs. "
                  "Nurses spend 20 min per handoff manually transferring notes and errors happen."]
    )
    hospital_id: Optional[str] = Field(
        None,
        description="Anonymized hospital identifier (e.g. 'HOSP_001')"
    )
    submitted_by: Optional[str] = Field(
        None,
        description="Role of submitter (e.g. 'Charge Nurse', 'Department Head')"
    )

class ClassifiedNeed(BaseModel):
    """Output from the LLM classification step."""
    department: str
    category: InnovationCategory
    subcategory: str
    urgency_score: int = Field(ge=1, le=5)
    patient_impact_score: int = Field(ge=1, le=5)
    keywords: List[str]
    reasoning: str  # LLM's explanation — kept for audit trail

class NeedResponse(BaseModel):
    """Full need record returned to the client."""
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
    """A need returned by similarity search, with its cosine distance."""
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
