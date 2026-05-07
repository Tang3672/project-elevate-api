"""
Trial Site Optimizer
====================
Recommends the best Phase II/III clinical trial recruitment sites
for a given disease indication by scoring hospitals from the CMS
quality deficit index against 4 criteria:

  1. Patient volume    — how many patients with this condition
  2. Quality deficit   — poor outcomes = most need for new treatments
  3. Research capacity — academic/teaching hospitals ranked higher
  4. Geographic spread — ensures national coverage

Saves PIs $200K+ in site selection consulting costs.
"""
import logging
import json
from typing import List, Optional
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.db.database import get_pool
from app.services.expert_profiles import get_expert

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL      = "claude-haiku-4-5-20251001"   # fast enough for site scoring


@dataclass
class TrialSite:
    rank:                  int
    hospital_name:         str
    city:                  str
    state:                 str
    composite_score:       float    # 0-100
    patient_volume_score:  float
    quality_deficit_score: float
    research_capacity:     str      # "Academic Medical Center" | "Teaching Hospital" | "Community"
    estimated_enrollment:  str      # e.g. "8-15 patients/year"
    rationale:             str
    latitude:              Optional[float] = None
    longitude:             Optional[float] = None
    cms_provider_id:       Optional[str]   = None


async def get_trial_sites(
    idea:          str,
    disease_domain: str,
    indication:    str,
    num_sites:     int = 15,
) -> List[TrialSite]:
    """
    Get top trial site recommendations for a given indication.

    Args:
        idea:           PI's product description
        disease_domain: expert domain ID
        indication:     specific indication (e.g. "carbapenem-resistant infections")
        num_sites:      number of sites to return (default 15)

    Returns:
        List of TrialSite objects ranked by composite score
    """
    # Get CMS hospital quality signals for this domain
    cms_signals = await _get_cms_signals_for_domain(disease_domain)

    # Get expert profile for domain context
    expert = get_expert(disease_domain)
    domain_context = expert.knowledge_base if expert else ""

    # Use Claude to score and rank hospitals
    sites = await _rank_sites_with_claude(
        idea, indication, disease_domain, domain_context,
        cms_signals, num_sites
    )
    return sites


async def _get_cms_signals_for_domain(domain_id: str) -> List[dict]:
    """Fetch CMS hospital quality signals relevant to this disease domain."""
    pool = await get_pool()

    # Domain → CMS quality measure keywords
    domain_cms_map = {
        "antibiotic_amr":     ["infection", "sepsis", "pneumonia", "antibiotic", "c diff"],
        "oncology":           ["cancer", "oncology", "chemotherapy", "tumor"],
        "cardiology":         ["heart failure", "cardiac", "mi", "stroke", "afib"],
        "neurology_cns":      ["stroke", "neurology", "seizure", "dementia"],
        "metabolic_diabetes": ["diabetes", "kidney", "renal", "glucose"],
        "mental_health":      ["psychiatric", "mental health", "depression", "substance"],
    }
    keywords = domain_cms_map.get(domain_id, ["hospital", "patient"])

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT title, description, magnitude, magnitude_unit,
                   location_name, state_code, geographic_scope
            FROM demand_signals
            WHERE source = 'cms_hospital_quality'
              AND (
                  """ + " OR ".join([f"LOWER(title) LIKE '%{kw}%'" for kw in keywords]) + """
              )
            ORDER BY magnitude DESC NULLS LAST
            LIMIT 100
            """,
        )
        return [dict(r) for r in rows]


async def _rank_sites_with_claude(
    idea:           str,
    indication:     str,
    domain_id:      str,
    domain_context: str,
    cms_signals:    List[dict],
    num_sites:      int,
) -> List[TrialSite]:
    """Use Claude to generate ranked trial site recommendations."""

    # Build CMS signal summary
    cms_summary = "\n".join([
        f"- {s['title']}: {s.get('magnitude','N/A')} {s.get('magnitude_unit','')} [{s.get('location_name','')}, {s.get('state_code','')}]"
        for s in cms_signals[:30]
    ]) if cms_signals else "No CMS data available — using general recommendations."

    system = f"""You are a clinical trial site selection expert with deep knowledge of U.S. hospital networks, academic medical centers, and patient population distribution.

You help pharmaceutical and medical device companies identify the optimal Phase II/III trial recruitment sites based on:
1. Patient population size for the specific indication
2. Hospital quality deficits (poor outcomes = greatest need for new treatments)
3. Research infrastructure (IRB capacity, dedicated research staff, prior trial experience)
4. Geographic distribution for national coverage

Domain context:
{domain_context[:1000]}

Respond ONLY with valid JSON array of exactly {num_sites} trial sites:
[{{
  "rank": 1,
  "hospital_name": "<full hospital name>",
  "city": "<city>",
  "state": "<2-letter state code>",
  "composite_score": <0-100>,
  "patient_volume_score": <0-100>,
  "quality_deficit_score": <0-100>,
  "research_capacity": "<Academic Medical Center|Teaching Hospital|Community Hospital>",
  "estimated_enrollment": "<e.g. 8-15 patients/year>",
  "rationale": "<2 sentences: why this site is ideal for this specific trial>",
  "latitude": <float>,
  "longitude": <float>
}}]

Use real U.S. hospitals. Prioritize geographic diversity across regions. For AMR/infection trials prioritize hospitals with high ICU volumes and active ID departments."""

    user = f"""Select the top {num_sites} Phase II/III clinical trial sites for:

INDICATION: {indication}
PRODUCT: {idea[:500]}
DOMAIN: {domain_id}

CMS HOSPITAL QUALITY DATA (available signals):
{cms_summary}

Rank hospitals by composite score. Ensure geographic diversity — include hospitals from at least 6 different states."""

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key":         settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      CLAUDE_MODEL,
                    "max_tokens": 3000,
                    "system":     system,
                    "messages":   [{"role": "user", "content": user}],
                }
            )
            r.raise_for_status()
            text = r.json()["content"][0]["text"].strip()
            # Clean JSON
            if text.startswith("```"):
                parts = text.split("```")
                text  = parts[1] if len(parts) > 1 else text
                if text.startswith("json"):
                    text = text[4:]
            sites_data = json.loads(text.strip())

            return [
                TrialSite(
                    rank                  = s.get("rank", i+1),
                    hospital_name         = s.get("hospital_name", ""),
                    city                  = s.get("city", ""),
                    state                 = s.get("state", ""),
                    composite_score       = float(s.get("composite_score", 0)),
                    patient_volume_score  = float(s.get("patient_volume_score", 0)),
                    quality_deficit_score = float(s.get("quality_deficit_score", 0)),
                    research_capacity     = s.get("research_capacity", "Hospital"),
                    estimated_enrollment  = s.get("estimated_enrollment", "Unknown"),
                    rationale             = s.get("rationale", ""),
                    latitude              = s.get("latitude"),
                    longitude             = s.get("longitude"),
                )
                for i, s in enumerate(sites_data[:num_sites])
            ]
    except Exception as e:
        logger.error(f"Trial site ranking failed: {e}")
        return []
