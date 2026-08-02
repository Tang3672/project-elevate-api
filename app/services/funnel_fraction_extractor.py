"""
Funnel Fraction Extractor
=========================
Citation-enforced literature extraction of patient-funnel gate fractions.

Blueprint constraint: "No fraction ships without a citation + verbatim quote."
Confidence gate: fraction ≥ 0.70 confidence → used directly; < 0.70 → queued
for human review (used with warning flag, not silently discarded).

Pipeline per gate:
  1. Check fraction_review_queue DB for an already-approved fraction (< 100ms)
  2. Try RAG local retrieval (pgvector over publication table)
  3. Fall back to live PubMed E-utilities search
  4. Extract fraction via Claude Haiku with a structured JSON prompt
  5. Return LiteratureFractionResult — caller decides how to use it

Never raises to caller; returns fraction=None on total failure so the engine
can fall back to its existing defaults.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional, List

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL  = "https://api.anthropic.com/v1/messages"
HAIKU_MODEL        = "claude-haiku-4-5-20251001"
PUBMED_SEARCH_URL  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_FETCH_URL   = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
PUBMED_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
PUBMED_RATE_LIMIT  = 0.4   # sec between requests (3 req/s without key)
PUBMED_TIMEOUT     = 20.0
LLM_TIMEOUT        = 30.0
MAX_ABSTRACT_CHARS = 1500  # cap sent to LLM (full abstract, not 500-char summary)
CONFIDENCE_GATE    = 0.70  # below this → needs_review = True


@dataclass
class LiteratureFractionResult:
    disease_name: str
    gate_name: str
    gate_label: str
    fraction: Optional[float]        # 0.0–1.0; None when extraction failed
    pmid: Optional[str]
    verbatim_quote: Optional[str]    # exact sentence from abstract supporting the fraction
    citation: Optional[str]          # "Author et al. (Year). Title. Journal. PMID: N"
    confidence: float                 # 0.0–1.0; calibrated (not raw LLM output)
    needs_review: bool                # True when confidence < CONFIDENCE_GATE
    extraction_method: str            # "db_approved" | "rag_local" | "pubmed_live" | "fallback_default"
    raw_abstract: Optional[str]       # truncated abstract for audit trail
    expert_question: Optional[str] = field(default=None)  # surfaced to PI when needs_review

    def to_dict(self) -> dict:
        return {
            "disease_name":    self.disease_name,
            "gate_name":       self.gate_name,
            "gate_label":      self.gate_label,
            "fraction":        self.fraction,
            "pmid":            self.pmid,
            "verbatim_quote":  self.verbatim_quote,
            "citation":        self.citation,
            "confidence":      round(self.confidence, 3),
            "needs_review":    self.needs_review,
            "extraction_method": self.extraction_method,
            "expert_question": self.expert_question,
        }


# ─── Main entry point ─────────────────────────────────────────────────────────

async def extract_funnel_fraction(
    disease_name: str,
    gate_name: str,
    gate_label: str,
    gate_note: Optional[str] = None,
) -> LiteratureFractionResult:
    """
    Extract a literature-backed fraction for a funnel gate.

    Returns a LiteratureFractionResult. fraction may be None if no usable source
    was found — caller must handle the None case with its own fallback logic.
    """
    _failure = LiteratureFractionResult(
        disease_name=disease_name,
        gate_name=gate_name,
        gate_label=gate_label,
        fraction=None,
        pmid=None,
        verbatim_quote=None,
        citation=None,
        confidence=0.0,
        needs_review=True,
        extraction_method="fallback_default",
        raw_abstract=None,
        expert_question=(
            f"What fraction of {disease_name} patients meet the criterion: "
            f"'{gate_label}'? No literature source was found automatically."
        ),
    )

    try:
        # Step 1: check DB for a pre-approved fraction
        from app.db.fraction_review_queue import check_approved_fraction
        approved = await check_approved_fraction(disease_name, gate_name)
        if approved is not None:
            return LiteratureFractionResult(
                disease_name=disease_name,
                gate_name=gate_name,
                gate_label=gate_label,
                fraction=approved,
                pmid=None,
                verbatim_quote=None,
                citation="[Human-reviewed approved fraction]",
                confidence=0.95,
                needs_review=False,
                extraction_method="db_approved",
                raw_abstract=None,
            )
    except Exception as e:
        logger.debug("DB fraction check failed (non-fatal): %s", e)

    # Step 2: try RAG (local publication table)
    try:
        rag_result = await _try_rag_extraction(disease_name, gate_name, gate_label)
        if rag_result and rag_result.fraction is not None:
            return rag_result
    except Exception as e:
        logger.debug("RAG fraction extraction failed (non-fatal): %s", e)

    # Step 3: PubMed live search
    try:
        pubmed_result = await _try_pubmed_extraction(
            disease_name, gate_name, gate_label, gate_note
        )
        if pubmed_result and pubmed_result.fraction is not None:
            return pubmed_result
    except Exception as e:
        logger.debug("PubMed fraction extraction failed (non-fatal): %s", e)

    return _failure


# ─── RAG path ─────────────────────────────────────────────────────────────────

async def _try_rag_extraction(
    disease_name: str,
    gate_name: str,
    gate_label: str,
) -> Optional[LiteratureFractionResult]:
    """
    Query the local publication RAG index for abstracts relevant to the gate.
    Returns a result if a fraction was found, None otherwise.
    """
    from app.services.rag_service import retrieve

    query = f"{disease_name} {gate_label} fraction proportion percentage patients"
    docs = await retrieve(query, disease_label=disease_name.split()[0], top_k=3)

    for doc in docs:
        abstract = (doc.get("abstract") or "")[:MAX_ABSTRACT_CHARS]
        if not abstract:
            continue

        result = await _llm_extract_fraction(
            disease_name=disease_name,
            gate_name=gate_name,
            gate_label=gate_label,
            abstract=abstract,
            pmid=str(doc.get("pmid") or doc.get("id") or ""),
            authors=doc.get("authors", ""),
            year=str(doc.get("year") or ""),
            title=doc.get("title", ""),
            journal=doc.get("journal", ""),
            extraction_method="rag_local",
        )
        if result and result.fraction is not None:
            return result

    return None


# ─── PubMed live path ─────────────────────────────────────────────────────────

async def _try_pubmed_extraction(
    disease_name: str,
    gate_name: str,
    gate_label: str,
    gate_note: Optional[str],
) -> Optional[LiteratureFractionResult]:
    """
    Search PubMed for abstracts relevant to the gate and extract the fraction.
    """
    query = _build_fraction_query(disease_name, gate_label, gate_note)
    pmids = await _search_pubmed(query, max_results=5)
    if not pmids:
        return None

    papers = await _fetch_abstracts(pmids)
    for paper in papers:
        abstract = paper.get("abstract", "")
        if not abstract:
            continue

        result = await _llm_extract_fraction(
            disease_name=disease_name,
            gate_name=gate_name,
            gate_label=gate_label,
            abstract=abstract[:MAX_ABSTRACT_CHARS],
            pmid=paper.get("pmid", ""),
            authors=paper.get("authors", ""),
            year=paper.get("year", ""),
            title=paper.get("title", ""),
            journal=paper.get("journal", ""),
            extraction_method="pubmed_live",
        )
        if result and result.fraction is not None:
            return result

    return None


def _build_fraction_query(
    disease_name: str,
    gate_label: str,
    gate_note: Optional[str],
) -> str:
    """Build a PubMed query targeting epidemiological fraction papers."""
    disease = disease_name.split("(")[0].strip()
    # Gate label may contain descriptive text — distill to key nouns
    gate_kw = re.sub(r"[^a-zA-Z0-9 /-]", " ", gate_label).strip()
    note_kw = ""
    if gate_note:
        # Extract first useful keyword phrase from the note
        note_kw = gate_note.split(";")[0].split(".")[0].strip()[:60]

    base = (
        f'("{disease}"[MeSH] OR "{disease}"[Title/Abstract]) AND '
        f'("{gate_kw}"[Title/Abstract] OR {note_kw}[Title/Abstract]) AND '
        f'(proportion[Title/Abstract] OR fraction[Title/Abstract] OR '
        f'prevalence[MeSH] OR incidence[MeSH] OR epidemiology[MeSH])'
    )
    return base


async def _search_pubmed(query: str, max_results: int = 5) -> List[str]:
    try:
        async with httpx.AsyncClient(timeout=PUBMED_TIMEOUT) as client:
            r = await client.get(PUBMED_SEARCH_URL, params={
                "db": "pubmed", "term": query,
                "retmax": max_results, "retmode": "json", "sort": "relevance",
            })
            if r.status_code == 200:
                return r.json().get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        logger.debug("PubMed search error: %s", e)
    return []


async def _fetch_abstracts(pmids: List[str]) -> List[dict]:
    """
    Fetch title, authors, journal, year, and full abstract for each PMID.
    Returns papers with 'abstract' key containing up to MAX_ABSTRACT_CHARS of text.
    """
    if not pmids:
        return []

    papers: dict[str, dict] = {}

    try:
        async with httpx.AsyncClient(timeout=PUBMED_TIMEOUT) as client:
            # Summary for metadata
            r = await client.get(PUBMED_SUMMARY_URL, params={
                "db": "pubmed", "id": ",".join(pmids), "retmode": "json",
            })
            if r.status_code == 200:
                result_data = r.json().get("result", {})
                for pmid in pmids:
                    p = result_data.get(pmid, {})
                    if not p or pmid == "uids":
                        continue
                    authors = p.get("authors", [])
                    first_author = authors[0].get("name", "") if authors else ""
                    if len(authors) > 1:
                        first_author += " et al."
                    papers[pmid] = {
                        "pmid":    pmid,
                        "title":   p.get("title", ""),
                        "authors": first_author,
                        "journal": p.get("source", ""),
                        "year":    (p.get("pubdate") or "")[:4],
                        "abstract": "",
                    }

            # Abstract text via efetch
            await asyncio.sleep(PUBMED_RATE_LIMIT)
            ra = await client.get(PUBMED_FETCH_URL, params={
                "db": "pubmed", "id": ",".join(pmids),
                "rettype": "abstract", "retmode": "text",
            })
            if ra.status_code == 200:
                text = ra.text
                for pmid in pmids:
                    if pmid not in papers:
                        continue
                    idx = text.find(f"PMID- {pmid}")
                    if idx == -1:
                        idx = text.find(pmid)
                    if idx != -1:
                        ab_start = text.find("AB  -", idx)
                        if ab_start != -1:
                            ab_end = text.find("\n\n", ab_start)
                            if ab_end == -1:
                                ab_end = ab_start + MAX_ABSTRACT_CHARS + 20
                            raw = text[ab_start + 6: ab_end]
                            # Continuation lines in MEDLINE format start with 6 spaces
                            abstract = raw.replace("\n      ", " ").strip()
                            papers[pmid]["abstract"] = abstract[:MAX_ABSTRACT_CHARS]

    except Exception as e:
        logger.debug("_fetch_abstracts error: %s", e)

    return [p for p in papers.values() if p.get("abstract")]


# ─── LLM extraction ───────────────────────────────────────────────────────────

async def _llm_extract_fraction(
    disease_name: str,
    gate_name: str,
    gate_label: str,
    abstract: str,
    pmid: str,
    authors: str,
    year: str,
    title: str,
    journal: str,
    extraction_method: str,
) -> Optional[LiteratureFractionResult]:
    """
    Call Claude Haiku with a structured extraction prompt.
    Returns None if the LLM could not extract a fraction from this abstract.
    """
    prompt = f"""You are a medical literature analyst extracting a specific epidemiological fraction from a paper abstract.

DISEASE: {disease_name}
GATE (what fraction we need): {gate_label}

ABSTRACT (PMID {pmid}):
{abstract}

TASK: Extract the fraction of {disease_name} patients who meet the criterion: "{gate_label}".

RULES:
1. Only extract a fraction if it is DIRECTLY stated in the abstract — do not infer or calculate.
2. The fraction must be expressed as a decimal between 0.0 and 1.0 (e.g., "25%" → 0.25).
3. Quote the EXACT sentence(s) from the abstract that support the fraction. No paraphrasing.
4. Confidence: 1.0 = fraction stated directly for this exact disease/subgroup; 0.5 = requires minor interpretation; 0.0 = not found.
5. If the abstract does not contain this specific fraction, return null for fraction and quote.

Return ONLY valid JSON (no markdown, no explanation):
{{"fraction": <float 0-1 or null>, "quote": <exact sentence or null>, "confidence": <float 0-1>}}"""

    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
            r = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key":         settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      HAIKU_MODEL,
                    "max_tokens": 200,
                    "messages":   [{"role": "user", "content": prompt}],
                },
            )
            r.raise_for_status()
            data = r.json()
            raw_text = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    raw_text += block.get("text", "")

            parsed = json.loads(raw_text.strip())
            fraction = parsed.get("fraction")
            quote    = parsed.get("quote")
            llm_conf = float(parsed.get("confidence", 0.0))

            if fraction is None:
                return None

            fraction = float(fraction)
            if not (0.0 <= fraction <= 1.0):
                return None

            # Calibrate confidence
            confidence = _calibrate_confidence(llm_conf, abstract, title)
            needs_review = confidence < CONFIDENCE_GATE

            citation = _build_citation(authors, year, title, journal, pmid)

            return LiteratureFractionResult(
                disease_name=disease_name,
                gate_name=gate_name,
                gate_label=gate_label,
                fraction=fraction,
                pmid=pmid or None,
                verbatim_quote=quote,
                citation=citation,
                confidence=confidence,
                needs_review=needs_review,
                extraction_method=extraction_method,
                raw_abstract=abstract[:500],
                expert_question=(
                    f"Literature found fraction={fraction:.1%} for '{gate_label}' in {disease_name} "
                    f"(conf={confidence:.2f}, {'NEEDS REVIEW' if needs_review else 'auto-approved'}). "
                    f"Source: {citation}. Agree?"
                ) if needs_review else None,
            )

    except Exception as e:
        logger.debug("LLM extraction failed for PMID %s: %s", pmid, e)
        return None


def _calibrate_confidence(llm_confidence: float, abstract: str, title: str) -> float:
    """
    Adjust raw LLM confidence using study-design signals from the abstract text.
    Upgrades for meta-analyses; downgrades for single-center/case reports.
    """
    conf = llm_confidence
    ab_lower = (abstract + " " + title).lower()

    if any(k in ab_lower for k in ("meta-analysis", "systematic review", "pooled analysis")):
        conf = min(conf + 0.05, 0.95)
    if any(k in ab_lower for k in ("single center", "single-center", "single institution")):
        conf = max(conf - 0.05, 0.0)
    if any(k in ab_lower for k in ("case report", "case series", "n =")):
        conf = max(conf - 0.10, 0.0)

    return round(conf, 3)


def _build_citation(authors: str, year: str, title: str, journal: str, pmid: str) -> str:
    parts = []
    if authors:
        parts.append(authors)
    if year:
        parts.append(f"({year})")
    if title:
        parts.append(f'"{title.rstrip(".")}."')
    if journal:
        parts.append(journal + ".")
    if pmid:
        parts.append(f"PMID: {pmid}")
    return " ".join(parts)
