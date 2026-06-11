"""
Deep Literature Synthesis — the mini-Edison Scientific differentiator
======================================================================
Edison Scientific's Kosmos reads 1,500 papers per run with full traceability:
every conclusion linked to a specific paper sentence or code cell. This service
does the same pattern for a disease area using the PubMed papers we already
fetch — but adds:

  1. PROVEN FINDINGS: What has been conclusively shown in recent literature?
     Each finding cited to a specific PMID.
  2. OPEN RESEARCH QUESTIONS: What remains unresolved? These are the white
     spaces where the PI's approach can claim novelty.
  3. PI APPROACH POSITIONING: How does the PI's specific approach compare
     to what's published? Is this genuinely novel or incremental?
  4. CONFLICTING EVIDENCE: Where do papers disagree? Conflicts = risk for
     the PI but also opportunity for decisive first-mover advantage.

Why this beats just dumping papers into context:
  - Structured output forces specific citations (not vague "literature shows")
  - Identifies white space that the PI may not know about
  - Pre-positions the PI's approach vs. published work before the main call
  - Gives Opus specific findings to reference with PMIDs in the report
  - Mirrors how Edison frames outputs: every claim traceable to a source
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional, List, Dict

import httpx

logger = logging.getLogger(__name__)

HAIKU_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


@dataclass
class LiteratureFinding:
    finding:  str         # the proven finding
    pmid:     str         # PubMed ID — traceability anchor
    citation: str         # "Author et al., Year"
    strength: str         # "strong" | "moderate" | "preliminary"


@dataclass
class LiteratureSynthesisResult:
    proven_findings:        List[LiteratureFinding]
    open_questions:         List[str]    # unresolved gaps = white space
    pi_approach_comparison: str          # how PI's approach differs from published work
    conflicting_evidence:   Optional[str]
    formatted:              str          # pre-formatted for Opus injection


async def synthesize_literature(
    disease_name: str,
    idea: str,
    pub_data: Dict,
) -> Optional[LiteratureSynthesisResult]:
    """
    Run a focused Haiku synthesis pass on PubMed papers already fetched.
    Produces structured findings with PMID traceability — not vague prose.

    pub_data: the dict returned by pubmed_service.get_landmark_publications()
    """
    papers = pub_data.get("publications", [])
    if not papers:
        return None

    # Format papers as concise input for Haiku (titles + abstracts)
    paper_lines = []
    for p in papers[:10]:  # cap at 10 to stay within Haiku context
        abstract = p.get("abstract", "")[:300]
        paper_lines.append(
            f"PMID {p['pmid']} | {p.get('authors','?')} ({p.get('year','?')}) | "
            f"{p.get('title','?')[:120]}"
            + (f" | Abstract excerpt: {abstract}" if abstract else "")
        )

    papers_text = "\n".join(paper_lines)

    system = (
        "You are a scientific literature analyst. Analyze the provided PubMed papers and "
        "the investigator's proposed approach, then produce a structured synthesis.\n\n"
        "CRITICAL: Every finding MUST cite a specific PMID from the provided list. "
        "Do NOT invent PMIDs or cite papers not in the list.\n\n"
        "Return ONLY valid JSON:\n"
        "{\n"
        '  "proven_findings": [\n'
        '    {"finding": "<specific proven fact>", "pmid": "<PMID from list>", "citation": "<Author Year>", "strength": "strong|moderate|preliminary"},\n'
        "    // 2-4 findings maximum\n"
        "  ],\n"
        '  "open_questions": [\n'
        '    "<specific unresolved research question that represents white space>",\n'
        "    // 2-3 questions maximum\n"
        "  ],\n"
        '  "pi_approach_comparison": "<1-2 sentences: how the PI\'s proposed approach specifically differs from or extends what is published. Be concrete — name what\'s novel>",\n'
        '  "conflicting_evidence": "<1 sentence describing any paper disagreements, or null if none>"\n'
        "}"
    )

    user = (
        f"Disease: {disease_name}\n\n"
        f"PI's proposed innovation:\n{idea[:500]}\n\n"
        f"PubMed papers retrieved for this disease ({len(papers)} total, showing top {min(10, len(papers))}):\n"
        f"{papers_text}"
    )

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": HAIKU_MODEL,
                    "max_tokens": 800,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
            )
            r.raise_for_status()
            text = r.json()["content"][0]["text"].strip()
            if text.startswith("```"):
                parts = text.split("```")
                text = parts[1] if len(parts) > 1 else text
                if text.startswith("json"):
                    text = text[4:]

        data = json.loads(text)

        findings = [
            LiteratureFinding(
                finding  = f.get("finding", ""),
                pmid     = str(f.get("pmid", "")),
                citation = f.get("citation", ""),
                strength = f.get("strength", "moderate"),
            )
            for f in data.get("proven_findings", [])[:4]
        ]

        result = LiteratureSynthesisResult(
            proven_findings        = findings,
            open_questions         = data.get("open_questions", [])[:3],
            pi_approach_comparison = data.get("pi_approach_comparison", ""),
            conflicting_evidence   = data.get("conflicting_evidence") or None,
            formatted              = "",
        )
        result.formatted = _format_synthesis(result)

        logger.info(
            "Literature synthesis: %d proven findings, %d open questions for %s",
            len(findings), len(result.open_questions), disease_name,
        )
        return result

    except Exception as e:
        logger.warning("Literature synthesis failed (non-fatal): %s", e)
        return None


def _format_synthesis(r: LiteratureSynthesisResult) -> str:
    """
    Format as a high-priority context block with PMID-traceable citations.
    This is the Edison Scientific pattern: every claim traces to a source.
    """
    lines = [
        "=== DEEP LITERATURE SYNTHESIS (PMID-TRACEABLE) ===",
        "Each finding below is anchored to a specific PubMed paper.",
        "Use these in your report — cite the PMID directly.",
        "",
    ]

    if r.proven_findings:
        lines.append("PROVEN FINDINGS (cite these in your report):")
        for f in r.proven_findings:
            strength_icon = {"strong": "✓✓", "moderate": "✓", "preliminary": "~"}.get(f.strength, "✓")
            lines.append(
                f"  {strength_icon} {f.finding}"
                f"  [PMID {f.pmid} | {f.citation}]"
            )
        lines.append("")

    if r.open_questions:
        lines.append("OPEN RESEARCH QUESTIONS (white space — your approach addresses these):")
        for q in r.open_questions:
            lines.append(f"  ? {q}")
        lines.append("")

    if r.pi_approach_comparison:
        lines.append(f"PI APPROACH vs. PUBLISHED WORK:")
        lines.append(f"  {r.pi_approach_comparison}")
        lines.append("")

    if r.conflicting_evidence:
        lines.append(f"CONFLICTING EVIDENCE (risk/opportunity):")
        lines.append(f"  ! {r.conflicting_evidence}")
        lines.append("")

    lines.append("=== END LITERATURE SYNTHESIS ===")
    return "\n".join(lines)
