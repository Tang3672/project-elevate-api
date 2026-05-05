"""
Alignment API v2
POST /api/v1/alignment/check      — legacy AlignmentReport
POST /api/v1/alignment/pi-report  — full PIReport with market sizing + regulatory
GET  /api/v1/alignment/examples   — example ideas
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from app.services.alignment_service import generate_alignment_report, generate_pi_report
from app.models.alignment import AlignmentReport, PIReport

logger = logging.getLogger(__name__)
router = APIRouter()


class AlignmentRequest(BaseModel):
    idea: str = Field(..., min_length=30, max_length=2000)


class PIReportRequest(BaseModel):
    idea: str = Field(..., min_length=30, max_length=2000)
    product_type: str = Field(default="other")
    target_pathogen: Optional[str] = Field(default=None)


@router.post("/check", response_model=AlignmentReport)
async def check_alignment(payload: AlignmentRequest):
    try:
        return await generate_alignment_report(payload.idea)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Alignment failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pi-report", response_model=PIReport)
async def get_pi_report(payload: PIReportRequest):
    """
    Full PI go-to-market intelligence report. For antibiotics includes:
    disease intelligence, transparent bottom-up market sizing, FDA regulatory
    pathway (QIDP/LPAD/Fast Track), clinical trial requirements, P&T committee
    access strategy, friction points, loopholes, BARDA/CARB-X funding —
    all with explicit source citations. Takes 20-40 seconds.
    """
    try:
        idea = payload.idea
        if payload.target_pathogen:
            idea = f"{idea}\n\nTarget pathogen: {payload.target_pathogen}"
        return await generate_pi_report(idea, payload.product_type)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"PI report failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/examples")
async def get_examples():
    return {
        "examples": [
            {
                "category": "ANTIBIOTIC",
                "product_type": "antibiotic",
                "idea": "A novel beta-lactam/beta-lactamase inhibitor combination targeting carbapenem-resistant Klebsiella pneumoniae (CRE) and Acinetobacter baumannii in hospitalized patients with limited treatment options.",
                "target_pathogen": "Carbapenem-resistant Enterobacterales (CRE)"
            },
            {
                "category": "ANTIBIOTIC",
                "product_type": "antibiotic",
                "idea": "A first-in-class oral antibiotic with activity against MRSA for outpatient skin and soft tissue infections, addressing the resistance gap left by linezolid.",
                "target_pathogen": "MRSA"
            },
            {
                "category": "SOFTWARE",
                "product_type": "software",
                "idea": "An AI clinical decision support system that flags early sepsis in the ED 6 hours before deterioration by continuously analyzing vitals, lab trends, and nursing notes."
            },
            {
                "category": "MEDICAL_DEVICE",
                "product_type": "medical_device",
                "idea": "A wearable continuous glucose monitor for rural diabetic patients with 90-day sensor life and no smartphone requirement."
            },
            {
                "category": "DIAGNOSTIC",
                "product_type": "diagnostic",
                "idea": "A rapid 30-minute PCR-based antibiotic susceptibility test that runs on existing hospital analyzers, eliminating the 48-72 hour culture wait."
            },
        ]
    }
