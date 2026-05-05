"""
Classification service: takes raw free-text from a hospital worker,
returns a structured ClassifiedNeed via GPT-4o.

Separation of concerns:
  - This file ONLY handles LLM calls for classification.
  - Embeddings live in embedding_service.py
  - DB persistence lives in needs_repository.py
"""

import json
import re
from openai import AsyncOpenAI
from app.core.config import settings
from app.models.needs import ClassifiedNeed, InnovationCategory

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# ── Category taxonomy pulled directly from Health_Innovation_Categories doc ──
CATEGORY_TAXONOMY = """
PRIMARY CATEGORIES:
- SOFTWARE: EHR/EMR, Telehealth Platforms, Clinical Decision Support (CDSS),
  Practice Management, mHealth Apps, Healthcare Analytics, HIE/FHIR,
  Lab/LIMS, Pharmacy Management, Digital Therapeutics, Cybersecurity,
  VR/AR Simulation
- HARDWARE: Diagnostic Imaging, Patient Monitoring Devices, Wearables/IoT,
  Therapeutic Equipment, Lab Equipment, Surgical Instruments,
  Rehabilitation Equipment, Digital Health Devices
- SERVICE: Telehealth Services, Healthcare Consulting, Training & Education,
  Technical Support, Integration Services, Quality Assurance,
  Revenue Cycle Management, Population Health, Supply Chain
- PHARMACEUTICALS: Drug Discovery, Regulatory & Compliance,
  Manufacturing, Commercialization, Post-Market, Digital Therapeutics
- HYBRID: Integrated Care Platforms, Device+Software Bundles,
  Service+Technology Packages, Platform+Consulting
"""

CLASSIFICATION_SYSTEM_PROMPT = f"""You are a healthcare innovation analyst for Project Elevate.
Your job is to analyze free-text submissions from hospital workers describing unmet needs,
and classify them into structured data.

{CATEGORY_TAXONOMY}

SCORING GUIDE:
- urgency_score (1-5): How time-sensitive is solving this?
  1=nice-to-have, 3=causes regular inefficiency, 5=patient safety risk
- patient_impact_score (1-5): How directly does this affect patient outcomes?
  1=purely administrative, 3=moderate clinical impact, 5=direct patient safety/outcome impact

OUTPUT FORMAT: Respond with ONLY a JSON object. No markdown, no explanation outside the JSON.
{{
  "department": "<clinical department or operational area, e.g. 'ICU', 'Emergency', 'Radiology', 'Supply Chain'>",
  "category": "<one of: SOFTWARE, HARDWARE, SERVICE, PHARMACEUTICALS, HYBRID, UNCATEGORIZED>",
  "subcategory": "<specific subcategory from the taxonomy above>",
  "urgency_score": <1-5>,
  "patient_impact_score": <1-5>,
  "keywords": ["<3-7 specific keywords>"],
  "reasoning": "<2-3 sentences explaining your classification decisions>"
}}"""

async def classify_need(raw_text: str) -> ClassifiedNeed:
    """
    Send raw hospital need text to GPT-4o for structured classification.
    Returns a ClassifiedNeed object.
    """
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": CLASSIFICATION_SYSTEM_PROMPT},
            {"role": "user", "content": f"Classify this hospital need:\n\n{raw_text}"}
        ],
        temperature=0.1,  # Low temp for consistent classification
        max_tokens=500,
        response_format={"type": "json_object"}
    )

    raw_json = response.choices[0].message.content
    data = json.loads(raw_json)

    # Normalize category to enum (fallback to UNCATEGORIZED if unexpected value)
    category_str = data.get("category", "UNCATEGORIZED").upper()
    try:
        category = InnovationCategory(category_str)
    except ValueError:
        category = InnovationCategory.UNCATEGORIZED

    return ClassifiedNeed(
        department=data.get("department", "Unknown"),
        category=category,
        subcategory=data.get("subcategory", "Unknown"),
        urgency_score=int(data.get("urgency_score", 3)),
        patient_impact_score=int(data.get("patient_impact_score", 3)),
        keywords=data.get("keywords", []),
        reasoning=data.get("reasoning", "")
    )
