"""
Alignment API
=============
Step 3: inventor-facing endpoints.

POST /api/v1/alignment/check     — submit an idea, get a full alignment report
GET  /api/v1/alignment/examples  — example ideas to try (onboarding)

This is the core value endpoint of Project Elevate.
An inventor or investor submits a description of their innovation
and receives a structured demand report in return.
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.alignment_service import generate_alignment_report
from app.models.alignment import AlignmentReport

logger = logging.getLogger(__name__)

router = APIRouter()


class AlignmentRequest(BaseModel):
    idea: str = Field(
        ...,
        min_length=30,
        max_length=2000,
        description="Description of the innovation — what it does, who it's for, what problem it solves",
        examples=[
            "An AI-powered medication dispensing system that reduces handoff errors "
            "in ICUs by automatically reconciling medication records during shift changes "
            "and flagging discrepancies before they reach the patient."
        ]
    )


@router.post("/check", response_model=AlignmentReport)
async def check_alignment(payload: AlignmentRequest):
    """
    Submit an inventor's idea and receive a full demand alignment report.

    The report includes:
    - Three demand scores (clinical demand, market size, competition gap)
    - An overall score with verdict (Strong / Moderate / Emerging / Weak)
    - Four narrative sections written for both inventor and investor audiences
    - Supporting evidence from FDA, CDC, CMS, Census, and ClinicalTrials databases
    - Matching hospital pain points from real submissions
    - Geographic market concentration analysis
    - Recommended next steps specific to this innovation

    This call takes 10-30 seconds — it searches the demand index and
    generates a Claude-powered narrative report.
    """
    try:
        report = await generate_alignment_report(payload.idea)
        return report
    except ValueError as e:
        # Missing API key or config error
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Alignment report generation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Report generation failed: {str(e)}"
        )


@router.get("/examples")
async def get_example_ideas():
    """
    Returns example idea descriptions inventors can use to explore the system.
    Useful for onboarding and demos.
    """
    return {
        "examples": [
            {
                "category": "SOFTWARE",
                "idea": "An AI-powered medication dispensing system that reduces handoff errors in ICUs by automatically reconciling medication records during shift changes and flagging discrepancies before they reach the patient.",
                "what_to_expect": "High clinical demand signal — ICU medication errors are a major patient safety issue"
            },
            {
                "category": "HARDWARE",
                "idea": "A wearable continuous glucose monitor designed specifically for rural and underinsured diabetic patients, with a 90-day sensor life and no smartphone requirement.",
                "what_to_expect": "Strong demand convergence — high diabetes burden + high uninsured rates in rural counties"
            },
            {
                "category": "SOFTWARE",
                "idea": "A telehealth platform for mental health therapy that works via basic phone call (no internet required), targeting rural areas with mental health provider shortages.",
                "what_to_expect": "Very strong care gap signal — 164M Americans in mental health shortage areas"
            },
            {
                "category": "SERVICE",
                "idea": "A care coordination service that helps hospitals reduce 30-day readmissions for heart failure patients by connecting them with community health workers post-discharge.",
                "what_to_expect": "Quality deficit signals from CMS readmission data + clinical trials pipeline"
            },
            {
                "category": "HARDWARE",
                "idea": "A safer insulin delivery device for Type 1 diabetes patients that eliminates the most common causes of insulin glargine adverse events through automated dosing verification.",
                "what_to_expect": "Direct FDA adverse event signal — insulin glargine has 123k+ serious reports"
            },
        ]
    }
