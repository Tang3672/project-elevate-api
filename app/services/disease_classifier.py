"""
Disease Classifier
==================
Classifies a PI's idea into a specific disease/condition name.
Runs as part of the Expert Router pipeline — adds minimal latency
since it uses Claude Haiku (fast, cheap).

Output: specific disease name used to drive targeted live searches.

Examples:
  "novel BLI targeting CRE" → "Carbapenem-resistant Enterobacterales (CRE)"
  "ALS gene therapy SOD1" → "Amyotrophic Lateral Sclerosis (ALS)"
  "GBM immunotherapy TIL" → "Glioblastoma Multiforme (GBM)"
  "T2D GLP-1 rural CGM" → "Type 2 Diabetes Mellitus"
  "Duchenne exon skipping" → "Duchenne Muscular Dystrophy (DMD)"
"""

import json
import logging
from typing import Optional
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
CLASSIFIER_MODEL  = "claude-haiku-4-5-20251001"

CLASSIFIER_SYSTEM = """You are a medical disease classifier. Given a description of a healthcare innovation, identify the PRIMARY specific disease or condition it targets.

Be specific — not just "cancer" but "glioblastoma multiforme" or "pancreatic ductal adenocarcinoma".
Not just "bacteria" but "Clostridioides difficile" or "carbapenem-resistant Klebsiella pneumoniae".

Respond ONLY with JSON:
{
  "disease_name": "<specific disease name with abbreviation if common>",
  "disease_aliases": ["<alias1>", "<alias2>"],
  "icd_category": "<broad ICD category e.g. Infectious Disease, Oncology, Neurology>",
  "is_rare": <true if <200,000 U.S. patients>,
  "search_terms": ["<best PubMed/CDC search term>", "<alternative term>"]
}

Examples:
- "CRE antibiotic" → {"disease_name": "Carbapenem-resistant Enterobacterales (CRE)", "disease_aliases": ["carbapenem-resistant Klebsiella pneumoniae", "KPC"], "icd_category": "Infectious Disease", "is_rare": false, "search_terms": ["carbapenem resistant enterobacterales", "CRE infection epidemiology"]}
- "ALS SOD1 gene therapy" → {"disease_name": "Amyotrophic Lateral Sclerosis (ALS)", "disease_aliases": ["Lou Gehrig's disease", "motor neuron disease"], "icd_category": "Neurology", "is_rare": true, "search_terms": ["amyotrophic lateral sclerosis epidemiology", "ALS SOD1 treatment"]}
- "GBM TIL therapy" → {"disease_name": "Glioblastoma Multiforme (GBM)", "disease_aliases": ["glioblastoma", "GBM grade IV"], "icd_category": "Oncology", "is_rare": false, "search_terms": ["glioblastoma epidemiology treatment", "GBM immunotherapy"]}"""


async def classify_disease(idea: str) -> dict:
    """
    Classify the specific disease from a PI's idea description.
    Returns dict with disease_name, search_terms, is_rare, etc.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key":         settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      CLASSIFIER_MODEL,
                    "max_tokens": 300,
                    "system":     CLASSIFIER_SYSTEM,
                    "messages":   [{"role": "user", "content": f"Classify the disease in this innovation:\n\n{idea[:600]}"}],
                }
            )
            r.raise_for_status()
            text = r.json()["content"][0]["text"].strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            result = json.loads(text.strip())
            logger.info(f"Disease classified: {result.get('disease_name')} (rare={result.get('is_rare')})")
            return result
    except Exception as e:
        logger.warning(f"Disease classification failed: {e}")
        return {
            "disease_name":    "the indicated condition",
            "disease_aliases": [],
            "icd_category":    "Healthcare",
            "is_rare":         False,
            "search_terms":    [idea[:50]],
        }
