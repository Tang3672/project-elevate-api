"""
Grant Co-Pilot Service
======================
Generates ready-to-paste NIH/NSF grant sections for PIs.

Supported grant types:
  - NIH R01 (Significance + Innovation + Approach justification)
  - NIH SBIR/STTR (Significance + Innovation + Commercialization potential)
  - NSF (Intellectual Merit + Broader Impacts)

Each section is written in proper grant language — formal, cited,
with specific numbers from the expert knowledge base and demand signals.
"""
import json
import logging
from dataclasses import dataclass
from typing import List, Optional

import httpx

from app.core.config import settings
from app.services.embedding_service import embed_text
from app.db.demand_repository import search_similar_signals
from app.services.expert_router import route as route_expert
from app.services.expert_profiles import get_expert

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL      = "claude-sonnet-4-6"   # use Sonnet for grant quality writing


@dataclass
class GrantSection:
    section_name:  str     # e.g. "Significance"
    content:       str     # ready-to-paste grant text
    word_count:    int
    key_citations: List[str]


@dataclass
class GrantOutput:
    grant_type:      str
    pi_idea:         str
    expert_domain:   str
    expert_name:     str
    sections:        List[GrantSection]
    biosketch_bullets: List[str]    # 3-5 bullet points for biosketch
    overall_summary: str


GRANT_TYPE_SECTIONS = {
    "nih_r01":   ["Significance", "Innovation", "Approach Justification", "Biosketch Data Points"],
    "nih_sbir":  ["Significance", "Innovation", "Commercialization Potential", "Biosketch Data Points"],
    "nsf":       ["Intellectual Merit", "Broader Impacts", "Biosketch Data Points"],
    "all":       ["Significance", "Innovation", "Approach Justification", "Commercialization Potential", "Biosketch Data Points"],
}

GRANT_SYSTEM_PROMPTS = {
    "significance": """Write a NIH grant Significance section. Requirements:
- 250-350 words
- Open with the disease burden (specific numbers, cited sources)
- Describe the gap in current knowledge or treatment
- Explain why filling this gap is significant to public health
- Use formal academic language
- Every statistic must cite its source inline (Author, Year) style
- End with a clear statement of the critical barrier to progress""",

    "innovation": """Write a NIH grant Innovation section. Requirements:
- 200-300 words
- Explain what is conceptually or technically novel
- Compare to existing approaches and explain why this is an advance
- Mention specific innovative aspects (mechanism, technology, approach)
- Use NIH Innovation section language: "The proposed research is innovative because..."
- Avoid overclaiming — be specific about what is novel""",

    "approach_justification": """Write a NIH grant Approach justification paragraph. Requirements:
- 150-200 words
- Justify the choice of target population/indication
- Reference the documented unmet need from epidemiological data
- Explain why this indication is the right starting point
- Cite federal data sources (CDC, FDA, CMS)""",

    "commercialization": """Write a NIH SBIR/STTR Commercialization Potential section. Requirements:
- 200-300 words
- Describe the market size (TAM/SAM with sources)
- Identify the customer segments and decision makers
- Explain the reimbursement pathway
- Describe the path to FDA approval and commercial launch
- Use business-appropriate language while maintaining scientific credibility""",

    "intellectual_merit": """Write an NSF Intellectual Merit section. Requirements:
- 200-300 words
- Describe the scientific/engineering advances the work will make
- Connect to broader knowledge in the field
- Mention the PI's qualifications and prior work
- Use NSF language: focus on advancing knowledge, not just solving a problem""",

    "broader_impacts": """Write an NSF Broader Impacts section. Requirements:
- 200-300 words
- Describe the societal benefits of the work
- Include patient impact and public health implications
- Mention training and educational opportunities if applicable
- Quantify impact where possible (number of patients affected, economic burden)""",

    "biosketch": """Generate 5 bullet points for a NIH/NSF Biosketch Personal Statement. Requirements:
- Each bullet is 1-2 sentences
- Focus on market need and relevance of the work
- Include specific statistics
- Written from the PI's perspective ("My research addresses...")
- Professional, formal tone
- Cite sources"""
}


async def generate_grant_sections(
    idea:        str,
    grant_type:  str,
    specific_aim: Optional[str] = None,
) -> GrantOutput:
    """
    Generate all grant sections for the given grant type.

    Args:
        idea:         PI's product/research description
        grant_type:   "nih_r01" | "nih_sbir" | "nsf" | "all"
        specific_aim: Optional specific aim text for more targeted output

    Returns:
        GrantOutput with all sections ready to paste
    """
    # Route to expert
    router_result = await route_expert(idea=idea, pi_domain="auto")
    expert        = router_result.expert

    # Get demand signals for context
    embedding      = await embed_text(idea)
    demand_signals = await search_similar_signals(
        query_embedding=embedding, top_k=15, min_similarity=0.55)

    # Build rich context
    context = _build_grant_context(idea, expert, demand_signals, specific_aim)

    # Get sections to generate
    sections_to_gen = GRANT_TYPE_SECTIONS.get(grant_type, GRANT_TYPE_SECTIONS["nih_r01"])

    # Generate each section
    sections = []
    for section_name in sections_to_gen:
        if section_name == "Biosketch Data Points":
            continue   # handle separately
        section = await _generate_section(section_name, context, expert)
        sections.append(section)

    # Generate biosketch bullets
    biosketch_bullets = await _generate_biosketch(context, expert)

    # Overall summary
    grant_label = {
        "nih_r01":  "NIH R01",
        "nih_sbir": "NIH SBIR/STTR",
        "nsf":      "NSF",
        "all":      "NIH/NSF"
    }.get(grant_type, grant_type.upper())

    summary = (
        f"{grant_label} grant sections generated for: {idea[:100]}... "
        f"Expert: {expert.display_name}. "
        f"Based on {len(demand_signals)} matching federal demand signals."
    )

    return GrantOutput(
        grant_type       = grant_type,
        pi_idea          = idea,
        expert_domain    = expert.domain_id,
        expert_name      = expert.display_name,
        sections         = sections,
        biosketch_bullets = biosketch_bullets,
        overall_summary  = summary,
    )


def _build_grant_context(idea, expert, demand_signals, specific_aim=None) -> str:
    lines = [
        f"RESEARCH INNOVATION: {idea}",
        "",
        f"DISEASE DOMAIN: {expert.display_name}",
        "",
        "EXPERT KNOWLEDGE BASE (use these facts and citations):",
        expert.knowledge_base,
        "",
    ]
    if specific_aim:
        lines += [f"SPECIFIC AIM: {specific_aim}", ""]

    if demand_signals:
        lines.append(f"FEDERAL DEMAND SIGNALS ({len(demand_signals)} matches):")
        for s in demand_signals[:10]:
            mag  = f"{s.get('magnitude'):,.0f} {s.get('magnitude_unit','')}" if s.get('magnitude') else ""
            loc  = s.get('location_name') or s.get('state_code') or 'National'
            lines.append(f"- {s['title']} {mag} [{loc}, {s['source']}]")

    lines.append("\nGenerate the grant section now. Use specific numbers and citations from the knowledge base above.")
    return "\n".join(lines)


async def _generate_section(section_name: str, context: str, expert) -> GrantSection:
    """Generate a single grant section."""
    prompt_key = section_name.lower().replace(" ", "_")
    system     = GRANT_SYSTEM_PROMPTS.get(prompt_key, GRANT_SYSTEM_PROMPTS["significance"])

    full_system = f"""{system}

DOMAIN EXPERTISE ({expert.display_name}):
Use the facts, statistics, and citations from the context provided."""

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key":         settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      CLAUDE_MODEL,
                    "max_tokens": 800,
                    "system":     full_system,
                    "messages":   [{"role": "user", "content": context}],
                }
            )
            r.raise_for_status()
            text = r.json()["content"][0]["text"].strip()
            return GrantSection(
                section_name  = section_name,
                content       = text,
                word_count    = len(text.split()),
                key_citations = _extract_citations(text),
            )
    except Exception as e:
        logger.error(f"Grant section '{section_name}' failed: {e}")
        return GrantSection(
            section_name  = section_name,
            content       = f"Generation failed: {str(e)}. Please retry.",
            word_count    = 0,
            key_citations = [],
        )


async def _generate_biosketch(context: str, expert) -> List[str]:
    """Generate 5 biosketch bullet points."""
    system = GRANT_SYSTEM_PROMPTS["biosketch"] + f"\n\nDomain: {expert.display_name}\n{expert.knowledge_base[:500]}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key":         settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      CLAUDE_MODEL,
                    "max_tokens": 500,
                    "system":     system,
                    "messages":   [{"role": "user", "content": context[:1500]}],
                }
            )
            r.raise_for_status()
            text   = r.json()["content"][0]["text"].strip()
            # Parse bullets
            lines  = [l.strip().lstrip("•-*123456789. ").strip() for l in text.split("\n") if l.strip()]
            bullets = [l for l in lines if len(l) > 20][:5]
            return bullets
    except Exception as e:
        logger.error(f"Biosketch generation failed: {e}")
        return []


def _extract_citations(text: str) -> List[str]:
    """Extract inline citations from grant text."""
    import re
    # Match (Author, Year) or (Source Year) patterns
    citations = re.findall(r'\([A-Z][^()]{2,50},?\s+\d{4}\)', text)
    return list(set(citations))[:10]
