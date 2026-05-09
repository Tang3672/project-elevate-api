"""
Disease Knowledge Service v2
==============================
Option 3: Disease Classifier + Targeted Live Search

For ANY disease a PI submits, generates deep knowledge by:
1. Classifying the specific disease (Haiku, fast)
2. Running 4 targeted web searches specific to that disease
3. Combining with domain expert static knowledge base

This covers every disease — rare, common, newly emerging —
not just the 6 domains we pre-wrote static knowledge for.
"""

import logging
from typing import Optional
import httpx

from app.core.config import settings
from app.services.disease_classifier import classify_disease

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
SEARCH_MODEL      = "claude-sonnet-4-6"

# Domain expert static knowledge (used as base layer — see expert_profiles.py)
# The live search supplements this with disease-specific current data


async def get_disease_knowledge(
    idea:      str,
    domain_id: str,
    expert_knowledge_base: str = "",
) -> tuple[str, dict]:
    """
    Get comprehensive disease knowledge for any specific disease.

    Returns:
        (knowledge_string, disease_info_dict)
        knowledge_string: full context to inject into Researcher prompt
        disease_info_dict: classified disease metadata
    """
    # Step 1: Classify the specific disease
    disease_info = await classify_disease(idea)
    disease_name = disease_info.get("disease_name", "the condition")
    search_terms = disease_info.get("search_terms", [disease_name])
    is_rare      = disease_info.get("is_rare", False)

    logger.info(f"Getting knowledge for: {disease_name} (domain={domain_id})")

    # Step 2: Run targeted live searches for this specific disease
    live_knowledge = await _run_disease_searches(disease_name, search_terms, is_rare)

    # Step 3: Combine domain expert base + live disease-specific knowledge
    combined = f"""
=== DOMAIN EXPERT KNOWLEDGE ({domain_id}) ===
{expert_knowledge_base}

=== DISEASE-SPECIFIC KNOWLEDGE: {disease_name.upper()} ===
{live_knowledge}
"""
    return combined, disease_info


async def _run_disease_searches(
    disease_name: str,
    search_terms: list,
    is_rare:      bool,
) -> str:
    """
    Run 4 targeted web searches and synthesize into structured knowledge.
    Covers: mechanism, epidemiology, history/SOC, pipeline.
    """
    primary_term = search_terms[0] if search_terms else disease_name
    alt_term     = search_terms[1] if len(search_terms) > 1 else disease_name

    # Build targeted search prompts
    search_instruction = f"""You are a medical research assistant. Search for comprehensive, current information about: {disease_name}

Run these specific searches:
1. "{primary_term} disease mechanism pathophysiology molecular biology"
2. "{primary_term} epidemiology incidence prevalence mortality United States 2024"
3. "{primary_term} FDA approved treatments standard of care limitations 2024"
4. "{alt_term} clinical trials pipeline unmet medical need 2024 2025"
{"5. \"" + primary_term + " orphan drug rare disease funding programs\"" if is_rare else ""}

For each search, extract and cite:
- Key statistics with exact numbers
- Source name and URL
- Publication year

Structure your response as:

MECHANISM:
[Disease mechanism with citations like: stat [SOURCE: source_name | url]]

EPIDEMIOLOGY:
[Incidence, prevalence, mortality, demographics with citations]

HISTORY & STANDARD OF CARE:
[Historical context, currently approved treatments, their limitations]

PIPELINE & UNMET NEED:
[What's in development, why current treatments fall short, key unmet needs]

{"RARE DISEASE PROGRAMS:\n[Orphan Drug designation details, funding programs available]" if is_rare else ""}

CRITICAL: Every statistic must be tagged [SOURCE: name | url]. Use real published URLs."""

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            r = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key":         settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      SEARCH_MODEL,
                    "max_tokens": 3000,
                    "tools":      [{"type": "web_search_20250305", "name": "web_search"}],
                    "messages":   [{"role": "user", "content": search_instruction}],
                }
            )
            r.raise_for_status()
            data = r.json()

            # Extract all text blocks (Claude may return multiple after tool use)
            knowledge = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    knowledge += block.get("text", "")

            if knowledge:
                logger.info(f"Live search returned {len(knowledge)} chars for {disease_name}")
                return knowledge
            else:
                logger.warning(f"No text returned from live search for {disease_name}")
                return f"Live search data unavailable for {disease_name}. Using domain expert knowledge base."

    except Exception as e:
        logger.error(f"Disease live search failed for {disease_name}: {e}")
        return f"Live search unavailable: {str(e)}. Report based on expert knowledge base."
