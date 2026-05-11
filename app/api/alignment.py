"""
Alignment API v2
================
POST /api/v1/alignment/check        — legacy (original inventors, returns AlignmentReport)
POST /api/v1/alignment/pi-report    — new PI endpoint (returns full PIReport with
                                      market sizing, regulatory pathway, disease intel)
GET  /api/v1/alignment/examples     — example ideas
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
    idea: str = Field(..., min_length=30, max_length=2000,
        description="Description of the product — what it does, who it's for, what it solves")
    product_type: str = Field(default="other",
        description="antibiotic | medical_device | software | diagnostic | other")
    target_pathogen: Optional[str] = Field(default=None,
        description="For antibiotics: primary target pathogen (e.g. MRSA, CRE, C. difficile)")
    disease_domain: str = Field(default="auto",
        description="auto | antibiotic_amr | oncology | cardiology | neurology_cns | metabolic_diabetes | mental_health")
    tier1_category: str = Field(default="drug_small_molecule",
        description="drug_small_molecule | biologic | gene_cell_therapy | medical_device | diagnostic | digital_health | vaccine_immunotherapy | other_platform")
    disease_domain: str = Field(default="auto",
        description="auto | antibiotic_amr | oncology | cardiology | neurology_cns | metabolic_diabetes | mental_health")
    tier1_category: str = Field(default="drug_small_molecule",
        description="drug_small_molecule | biologic | gene_cell_therapy | medical_device | diagnostic | digital_health | vaccine_immunotherapy | other_platform")


@router.post("/check", response_model=AlignmentReport)
async def check_alignment(payload: AlignmentRequest):
    """Legacy endpoint — returns original scored AlignmentReport."""
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
    Full PI go-to-market intelligence report.

    For antibiotics: includes disease intelligence, transparent bottom-up market
    sizing, FDA regulatory pathway (QIDP/LPAD/Fast Track), clinical trial
    requirements, P&T committee access strategy, friction points and loopholes,
    BARDA/CARB-X funding programs — all with explicit source citations.

    Takes 20-40 seconds.
    """
    try:
        idea = payload.idea
        if payload.target_pathogen:
            idea = f"{idea}\n\nTarget pathogen: {payload.target_pathogen}"
        return await generate_pi_report(idea, payload.product_type, payload.disease_domain, getattr(payload, "tier1_category", "drug_small_molecule"))
    # Increment free report counter if not subscribed
    try:
        if current_user:
            from app.db.user_repository import get_user_by_id, increment_free_report_count
            user = await get_user_by_id(current_user["id"])
            status = user.get("subscription_status", "none") if user else "none"
            dev_emails = {"test@projectelevate.io", "ijw91021@gmail.com", "admin@projectelevate.io"}
            if status not in ("active", "trialing") and current_user.get("email") not in dev_emails:
                await increment_free_report_count(current_user["id"])
    except Exception as e:
        import logging; logging.getLogger(__name__).warning(f"Failed to increment free report count: {e}")
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
                "target_pathogen": "Carbapenem-resistant Enterobacterales (CRE)",
                "what_to_expect": "Full QIDP/LPAD regulatory analysis, CRE market sizing (~$289M U.S.), BARDA/CARB-X funding pathways"
            },
            {
                "category": "ANTIBIOTIC",
                "product_type": "antibiotic",
                "idea": "A first-in-class oral antibiotic with activity against MRSA for outpatient skin and soft tissue infections, addressing the gap left by linezolid resistance.",
                "target_pathogen": "MRSA",
                "what_to_expect": "MRSA incidence (119,247 BSIs/yr), ABSSSI trial endpoints, P&T formulary strategy"
            },
            {
                "category": "SOFTWARE",
                "product_type": "software",
                "idea": "An AI clinical decision support system that flags early sepsis in the ED by continuously analyzing vitals, lab trends, and nursing notes — targeting the 6-8 hour delay problem.",
                "what_to_expect": "Sepsis market sizing, CMS reimbursement pathway, hospital formulary access strategy"
            },
            {
                "category": "MEDICAL_DEVICE",
                "product_type": "medical_device",
                "idea": "A wearable continuous glucose monitor for rural diabetic patients with 90-day sensor life and no smartphone requirement.",
                "what_to_expect": "Rural diabetes burden, FDA 510(k) vs PMA pathway, CGM market access"
            },
            {
                "category": "DIAGNOSTIC",
                "product_type": "diagnostic",
                "idea": "A rapid 30-minute PCR-based test for antibiotic susceptibility that runs on existing hospital analyzers, eliminating the 48-72 hour wait for culture results.",
                "what_to_expect": "AST market sizing, CLIA waiver pathway, hospital lab access strategy"
            },
        ]
    }
