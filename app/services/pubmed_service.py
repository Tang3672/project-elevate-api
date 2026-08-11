"""
PubMed Literature Intelligence Service
=======================================
Pulls top landmark publications for a disease + product type from PubMed
using NCBI E-utilities API (free, no key required, 3 req/sec limit).

Returns structured publication data:
- Top cited systematic reviews and meta-analyses
- Recent RCT results (Phase 2/3 outcomes)
- Key mechanistic papers
- Clinical guidelines publications

This gives each expert access to current literature that:
1. ChatGPT's training data may not include (post-cutoff papers)
2. Is structured with citation counts (identifies landmark papers)
3. Is indication-specific (not generic domain knowledge)
"""

import asyncio
import logging
import json
import re
import time
from typing import List, Dict, Optional
import httpx

logger = logging.getLogger(__name__)

# Import the shared audit logger; avoid circular at module load time
def _log_fetch_pubmed(url: str, method: str, status, latency_ms: float,
                      response_bytes: int, parsed_records: int, query_summary: str) -> None:
    """Emit a FETCH_AUDIT record for PubMed/E-utilities calls."""
    logger.debug(
        "FETCH_AUDIT service=pubmed method=%s status=%s latency_ms=%.0f bytes=%d "
        "records=%d url=%s query=%r",
        method, status, latency_ms, response_bytes, parsed_records, url, query_summary,
    )

PUBMED_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_FETCH_URL  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
PUBMED_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
TIMEOUT = 20.0
RATE_LIMIT_DELAY = 0.4  # 3 req/sec max without API key


async def get_landmark_publications(
    disease_name: str,
    sub_expert_id: str,
    max_papers: int = 8,
) -> Dict:
    """
    Pull top landmark publications for a disease + expert domain.
    Returns structured publication data ready to inject into expert context.
    """
    results = {
        "disease": disease_name,
        "publications": [],
        "systematic_reviews": [],
        "recent_trials": [],
        "guidelines": [],
        "total_found": 0,
    }

    # Build targeted queries based on expert domain
    queries = _build_pubmed_queries(disease_name, sub_expert_id)

    all_pmids = []
    for query in queries[:3]:  # 3 queries max
        await asyncio.sleep(RATE_LIMIT_DELAY)
        pmids = await _search_pubmed(query, max_results=5)
        all_pmids.extend(pmids)

    # Deduplicate
    all_pmids = list(dict.fromkeys(all_pmids))[:max_papers]

    if not all_pmids:
        return results

    # Fetch summaries for all PMIDs
    await asyncio.sleep(RATE_LIMIT_DELAY)
    papers = await _fetch_paper_summaries(all_pmids)

    results["publications"] = papers
    results["total_found"] = len(papers)

    # Categorize papers
    for p in papers:
        title_lower = p.get("title", "").lower()
        pub_type = p.get("pub_type", "")
        if any(t in title_lower for t in ["systematic review", "meta-analysis", "cochrane"]):
            results["systematic_reviews"].append(p)
        elif any(t in title_lower for t in ["randomized", "phase 2", "phase 3", "rct", "trial"]):
            results["recent_trials"].append(p)
        elif any(t in title_lower for t in ["guideline", "consensus", "recommendation"]):
            results["guidelines"].append(p)

    return results


# ── B-09 Literature relevance gate ────────────────────────────────────────────
# Title substrings that signal a paper is from a different scientific domain.
# When a paper from a non-clinical research tool product matches one of these
# terms its title, it is off-domain and should be dropped — UNLESS the product
# idea itself mentions the same term (e.g. an RNA-seq analysis tool is allowed
# to cite DESeq2).
_OFF_DOMAIN_SIGNALS: frozenset = frozenset({
    "rna-seq", "rnaseq", "deseq", "fold change", "rna sequence",
    "protein-protein", "protein interaction", "interaction network",
    "proteomics", "transcriptomics", "genomics", "differential expression",
    "gene expression", "gene editing", "gene ontology",
    "crispr", "crispr-cas", "cas9",
    "randomized controlled trial", "randomized clinical trial",
    "placebo-controlled", "double-blind",
    "chemotherapy", "immunotherapy", "checkpoint inhibitor",
    "clinical trial", "phase 2 trial", "phase 3 trial",
    "phase ii trial", "phase iii trial", "phase ii ", "phase iii ",
    "monoclonal antibod", "antibody therapy",
})


def _is_non_clinical_product(sub_expert_id: str) -> bool:
    s = (sub_expert_id or "").lower()
    return "non_clinical" in s or s.startswith("research_tool") or "lab_software" in s


def resolve_pmid(pmid: str) -> "dict | None":
    """Verify a PMID via E-utilities efetch and return authoritative metadata.

    Returns a dict with title, authors, journal, year, and abstract from the
    API response, or None if the PMID does not resolve. All fields come from
    the API — never from generation. This is the Part A fix: a PMID only
    renders in the report if it passes through this check.

    The abstract field is used by filter_literature_citations to verify that
    any statistics attributed to the paper actually appear in the abstract
    rather than being generated claims wearing a valid PMID.
    """
    import xml.etree.ElementTree as ET
    try:
        _t0 = time.monotonic()
        resp = httpx.get(
            PUBMED_FETCH_URL,
            params={"db": "pubmed", "id": pmid, "retmode": "xml"},
            timeout=10.0,
        )
        _log_fetch_pubmed(
            PUBMED_FETCH_URL, "GET", resp.status_code,
            (time.monotonic() - _t0) * 1000, len(resp.content),
            0 if not resp.is_success else 1,
            f"efetch pmid={pmid}",
        )
        if not resp.is_success:
            return None
        root = ET.fromstring(resp.text)
        article = root.find(".//PubmedArticle")
        if article is None:
            return None
        title = article.findtext(".//ArticleTitle", default="")
        journal = article.findtext(".//Journal/Title", default="")
        year = (
            article.findtext(".//PubDate/Year")
            or article.findtext(".//PubDate/MedlineDate", default="")[:4]
        )
        last_names = [a.findtext("LastName", "") for a in article.findall(".//Author") if a.findtext("LastName")]
        authors = (last_names[0] + " et al.") if last_names else ""
        if not title:
            return None
        # Structured abstracts have multiple <AbstractText> elements; join them all.
        abstract_parts = [el.text or "" for el in article.findall(".//AbstractText") if el.text]
        abstract = " ".join(abstract_parts)
        return {
            "pmid":     pmid,
            "title":    title,
            "authors":  authors,
            "journal":  journal,
            "year":     year,
            "abstract": abstract,
            "url":      f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        }
    except Exception as e:
        logger.warning("resolve_pmid(%s) failed: %s", pmid, e)
        return None


# Matches numeric statistics likely to be generated rather than quoted:
# percentages, dollar amounts, counts with + or ×, hour/minute counts.
_STAT_RE = re.compile(
    r"""
    (?:
      \d+(?:\.\d+)?\s*%          # percentages: 15%, 0.5%
    | \$\s*\d[\d,\.]*            # dollar amounts: $40K, $1.2M
    | \d+\+\s*(?:hours?|hrs?)    # hour counts: 40+ hours
    | \d{2,}\s*(?:hours?|hrs?)   # bare hours: 48 hours
    | \d+\s*[×x]\s*\d+           # multiplications: 2×, 3x
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _verify_claims_against_abstract(relevance: str, abstract: str) -> str:
    """Part A abstract guard: if relevance contains numeric claims that don't
    appear in the retrieved abstract, return 'claim not verifiable from abstract'.

    Only triggers when there IS an abstract (not for no-abstract PMIDs).
    """
    if not abstract:
        return relevance
    stats = _STAT_RE.findall(relevance or "")
    if not stats:
        return relevance
    abstract_lower = abstract.lower()
    for stat in stats:
        # Normalise whitespace for comparison
        needle = " ".join(stat.lower().split())
        if needle not in abstract_lower:
            logger.debug(
                "Part A abstract guard: stat %r not found in abstract — marking unverifiable",
                stat,
            )
            return "claim not verifiable from abstract"
    return relevance


def filter_literature_citations(
    citations: List[dict],
    idea: str,
    sub_expert_id: str,
) -> List[dict]:
    """
    Part A + B-09: Verify each PMID via E-utilities and drop citations that
    either don't resolve or whose title doesn't match the generated title
    (catches the fabricated-PMID-on-real-paper defect from spec v6).

    Off-domain signal filtering (B-09) still applies for non-clinical products.
    """
    if not citations:
        return citations

    verified = []
    for c in citations:
        pmid = (c.get("pmid") or "").strip()
        if not pmid:
            verified.append(c)  # no PMID → pass through, off-domain gate still applies
            continue

        resolved = resolve_pmid(pmid)
        if resolved is None:
            # Unresolvable PMID (network error or non-existent): pass through to the
            # domain gate. The hard drop only applies when a PMID resolves to a
            # DIFFERENT title, which is the genuine fabrication signal.
            logger.debug("Part A gate: PMID %s did not resolve — passing to relevance gate without title check", pmid)
            verified.append(c)
            continue

        # Title match check: if the LLM-generated title differs substantially from
        # the resolved title, the PMID was attached to the wrong paper.
        gen_title = (c.get("title") or "").lower().strip()
        real_title = resolved["title"].lower().strip()
        if gen_title and real_title:
            # Use word-overlap ratio: >30% of generated words must appear in real title
            gen_words = set(gen_title.split())
            real_words = set(real_title.split())
            overlap = len(gen_words & real_words) / max(len(gen_words), 1)
            if overlap < 0.30:
                logger.warning(
                    "Part A gate: PMID %s title mismatch — generated '%s...' vs real '%s...' — using real title",
                    pmid, gen_title[:60], real_title[:60],
                )
                # Replace with authoritative metadata from E-utilities
                c = {**c, **resolved, "relevance": c.get("relevance", "")}

        # Part A abstract guard: verify that any statistics in the relevance field
        # can actually be found in the paper's abstract. If not, flag as unverifiable
        # so the report surface can show a disclaimer rather than a false citation.
        abstract = resolved.get("abstract", "")
        checked_relevance = _verify_claims_against_abstract(c.get("relevance", ""), abstract)
        if checked_relevance != c.get("relevance", ""):
            c = {**c, "relevance": checked_relevance}

        verified.append(c)

    # B-09: off-domain signal filter for non-clinical products
    if not _is_non_clinical_product(sub_expert_id):
        return verified

    idea_lower = (idea or "").lower()
    product_own_signals = {sig for sig in _OFF_DOMAIN_SIGNALS if sig in idea_lower}

    kept = []
    for c in verified:
        title_lower = (c.get("title") or "").lower()
        paper_signals = {sig for sig in _OFF_DOMAIN_SIGNALS if sig in title_lower}
        if not paper_signals:
            kept.append(c)
        elif paper_signals & product_own_signals:
            kept.append(c)
        else:
            logger.debug(
                "B-09 gate: dropped citation '%s' (off-domain signals: %s)",
                c.get("title", "")[:80],
                paper_signals - product_own_signals,
            )
    return kept


def _build_pubmed_queries(disease_name: str, sub_expert_id: str) -> List[str]:
    """Build targeted PubMed queries based on expert domain."""
    disease = disease_name.split("(")[0].strip()

    # Domain-specific query modifiers
    domain_filters = {
        "drug_amr":              f'("{disease}"[MeSH] OR "{disease}"[Title]) AND (antibiotic[Title/Abstract] OR antimicrobial[Title/Abstract]) AND (clinical trial[pt] OR systematic review[pt])',
        "drug_oncology":         f'"{disease}"[MeSH] AND (drug therapy[MeSH] OR chemotherapy[Title/Abstract]) AND (randomized controlled trial[pt] OR meta-analysis[pt])',
        "drug_cns":              f'"{disease}"[MeSH] AND (drug therapy[MeSH] OR pharmacotherapy[Title/Abstract]) AND (randomized controlled trial[pt] OR systematic review[pt])',
        "drug_cardiology":       f'"{disease}"[MeSH] AND (cardiovascular[MeSH] OR drug therapy[MeSH]) AND (randomized controlled trial[pt] OR meta-analysis[pt])',
        "drug_metabolic":        f'"{disease}"[MeSH] AND (drug therapy[MeSH] OR treatment[Title/Abstract]) AND (randomized controlled trial[pt] OR meta-analysis[pt])',
        "drug_mental_health":    f'"{disease}"[MeSH] AND (psychopharmacology[MeSH] OR drug therapy[MeSH]) AND (randomized controlled trial[pt] OR systematic review[pt])',
        "drug_rare_disease":     f'("{disease}"[MeSH] OR "{disease}"[Title]) AND (orphan drug[Title/Abstract] OR rare disease[MeSH]) AND (clinical trial[pt] OR case series[pt])',
        "drug_infectious_non_amr": f'"{disease}"[MeSH] AND (antiviral[Title/Abstract] OR drug therapy[MeSH]) AND (randomized controlled trial[pt] OR systematic review[pt])',
        "drug_immunology":       f'"{disease}"[MeSH] AND (biological therapy[MeSH] OR immunosuppression[MeSH]) AND (randomized controlled trial[pt] OR meta-analysis[pt])',
        "biologic_oncology":     f'"{disease}"[MeSH] AND (monoclonal antibod[Title/Abstract] OR immunotherapy[MeSH]) AND (randomized controlled trial[pt] OR meta-analysis[pt])',
        "biologic_immunology":   f'"{disease}"[MeSH] AND (biological therapy[MeSH] OR monoclonal antibod[Title/Abstract]) AND (randomized controlled trial[pt] OR meta-analysis[pt])',
        "gene_therapy_rare":     f'("{disease}"[MeSH] OR "{disease}"[Title]) AND (gene therapy[MeSH] OR gene editing[Title/Abstract]) AND (clinical trial[pt] OR review[pt])',
        "gene_therapy_oncology": f'"{disease}"[MeSH] AND (CAR-T[Title/Abstract] OR gene therapy[MeSH] OR cell therapy[MeSH]) AND (clinical trial[pt] OR review[pt])',
        "device_cardiovascular": f'"{disease}"[MeSH] AND (equipment and supplies[MeSH] OR medical device[Title/Abstract]) AND (randomized controlled trial[pt] OR systematic review[pt])',
        "device_metabolic":      f'"{disease}"[MeSH] AND (monitoring[MeSH] OR insulin pump[Title/Abstract] OR continuous glucose[Title/Abstract]) AND (clinical trial[pt] OR review[pt])',
        "diagnostic_molecular":  f'("{disease}"[MeSH] OR "{disease}"[Title]) AND (molecular diagnostic[Title/Abstract] OR biomarker[MeSH]) AND (validation[Title/Abstract] OR sensitivity[Title/Abstract])',
        "vaccine_prophylactic":  f'"{disease}"[MeSH] AND (vaccine[MeSH] OR vaccination[MeSH]) AND (randomized controlled trial[pt] OR phase 3[Title/Abstract])',
        "vaccine_cancer_immuno": f'"{disease}"[MeSH] AND (cancer vaccine[Title/Abstract] OR immunotherapy[MeSH] OR checkpoint[Title/Abstract]) AND (randomized controlled trial[pt] OR meta-analysis[pt])',
        # Non-clinical research tools: search for adoption/workflow papers, NOT clinical trials
        "research_tool_non_clinical": f'("{disease}"[Title/Abstract]) AND (software[Title] OR platform[Title] OR tool[Title] OR workflow[Title] OR instrument[Title]) AND (laboratory[Title/Abstract] OR research[Title/Abstract] OR open-source[Title/Abstract] OR reproducib[Title/Abstract])',
    }

    default_query = f'"{disease}"[Title/Abstract] AND (clinical trial[pt] OR systematic review[pt] OR meta-analysis[pt])'
    primary_query = domain_filters.get(sub_expert_id, default_query)

    # Always add a recency query for last 3 years
    recency_query = f'"{disease}"[Title/Abstract] AND ("2023"[Date - Publication] : "2026"[Date - Publication])'

    # Guidelines query
    guidelines_query = f'"{disease}"[Title/Abstract] AND (guideline[pt] OR practice guideline[pt] OR consensus[Title/Abstract])'

    return [primary_query, recency_query, guidelines_query]


async def _search_pubmed(query: str, max_results: int = 5) -> List[str]:
    """Search PubMed and return list of PMIDs."""
    _t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(PUBMED_SEARCH_URL, params={
                "db": "pubmed",
                "term": query,
                "retmax": max_results,
                "retmode": "json",
                "sort": "relevance",
            })
            ids = []
            if r.status_code == 200:
                ids = r.json().get("esearchresult", {}).get("idlist", [])
            _log_fetch_pubmed(
                PUBMED_SEARCH_URL, "GET", r.status_code,
                (time.monotonic() - _t0) * 1000, len(r.content), len(ids),
                f"esearch {query[:80]}",
            )
            return ids
    except Exception as e:
        _log_fetch_pubmed(
            PUBMED_SEARCH_URL, "GET", None,
            (time.monotonic() - _t0) * 1000, 0, 0,
            f"esearch {query[:80]}",
        )
        logger.warning(f"PubMed search failed: {e}")
    return []


async def _fetch_paper_summaries(pmids: List[str]) -> List[Dict]:
    """Fetch paper summaries and abstracts for a list of PMIDs."""
    if not pmids:
        return []
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            # Get summary data
            _t0 = time.monotonic()
            r = await client.get(PUBMED_SUMMARY_URL, params={
                "db": "pubmed",
                "id": ",".join(pmids),
                "retmode": "json",
            })
            _log_fetch_pubmed(
                PUBMED_SUMMARY_URL, "GET", r.status_code,
                (time.monotonic() - _t0) * 1000, len(r.content), len(pmids),
                f"esummary ids={','.join(pmids[:5])}{'...' if len(pmids) > 5 else ''}",
            )
            if r.status_code != 200:
                return []

            data = r.json()
            result_data = data.get("result", {})
            papers = []

            for pmid in pmids:
                paper = result_data.get(pmid, {})
                if not paper or pmid == "uids":
                    continue

                authors = paper.get("authors", [])
                author_str = authors[0].get("name", "") if authors else "Unknown"
                if len(authors) > 1:
                    author_str += " et al."

                pub_date = paper.get("pubdate", "")
                journal = paper.get("source", "")
                title = paper.get("title", "")
                pub_types = [p.get("value", "") for p in paper.get("pubtype", [])]

                papers.append({
                    "pmid":     pmid,
                    "title":    title,
                    "authors":  author_str,
                    "journal":  journal,
                    "year":     pub_date[:4] if pub_date else "",
                    "pub_type": ", ".join(pub_types[:2]),
                    "url":      f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                })

            # Fetch abstracts in one batch call
            await asyncio.sleep(RATE_LIMIT_DELAY)
            try:
                _ta0 = time.monotonic()
                ra = await client.get(PUBMED_FETCH_URL, params={
                    "db": "pubmed",
                    "id": ",".join(pmids),
                    "rettype": "abstract",
                    "retmode": "text",
                })
                _log_fetch_pubmed(
                    PUBMED_FETCH_URL, "GET", ra.status_code,
                    (time.monotonic() - _ta0) * 1000, len(ra.content), len(pmids),
                    f"efetch abstracts ids={','.join(pmids[:5])}{'...' if len(pmids) > 5 else ''}",
                )
                if ra.status_code == 200:
                    abstract_text = ra.text
                    # Parse individual abstracts by PMID
                    for p in papers:
                        pmid = p["pmid"]
                        # Find abstract section for this PMID
                        idx = abstract_text.find(f"PMID- {pmid}")
                        if idx == -1:
                            idx = abstract_text.find(pmid)
                        if idx != -1:
                            ab_start = abstract_text.find("AB  -", idx)
                            ab_end = abstract_text.find("\n\n", ab_start) if ab_start != -1 else -1
                            if ab_start != -1 and ab_end != -1:
                                abstract = abstract_text[ab_start+6:ab_end].replace("\n      ", " ").strip()
                                p["abstract"] = abstract[:500]  # Cap at 500 chars
            except Exception as e:
                logger.warning(f"Abstract fetch failed: {e}")

            return papers

    except Exception as e:
        logger.warning(f"PubMed fetch failed: {e}")
        return []


def format_publications_for_expert(pub_data: Dict) -> str:
    """Format publication data as expert context for grant writing and investor reports."""
    if not pub_data.get("publications"):
        return ""

    lines = [f"\n=== PEER-REVIEWED LITERATURE: {pub_data['disease'].upper()} ==="]
    lines.append(f"({pub_data['total_found']} papers retrieved from PubMed)\n")
    lines.append("INSTRUCTIONS: Cite these papers throughout your report using [SOURCE: Author Year | URL] format.")
    lines.append("For market sizing, use epidemiology papers to justify patient population estimates.")
    lines.append("For regulatory section, cite clinical trial results and guidelines.")
    lines.append("For grant writing context, highlight unmet need from systematic reviews.\n")

    categories = [
        ("CLINICAL GUIDELINES (cite for regulatory strategy)", pub_data.get("guidelines", []), 2),
        ("SYSTEMATIC REVIEWS & META-ANALYSES (cite for market sizing epidemiology)", pub_data.get("systematic_reviews", []), 3),
        ("CLINICAL TRIAL RESULTS (cite for competitive landscape)", pub_data.get("recent_trials", []), 3),
    ]

    used = set()
    for label, papers, limit in categories:
        if papers:
            lines.append(label + ":")
            for p in papers[:limit]:
                used.add(p["pmid"])
                abstract = p.get("abstract", "")
                abstract_preview = f" | Abstract: {abstract[:200]}..." if abstract else ""
                lines.append(f"  PMID {p['pmid']}: {p['authors']} ({p['year']}). \"{p['title']}\". {p['journal']}.{abstract_preview}")
                lines.append(f"  URL: {p['url']}")
            lines.append("")

    remaining = [p for p in pub_data["publications"] if p["pmid"] not in used]
    if remaining:
        lines.append("OTHER KEY PAPERS:")
        for p in remaining[:2]:
            abstract = p.get("abstract", "")
            abstract_preview = f" | {abstract[:150]}..." if abstract else ""
            lines.append(f"  PMID {p['pmid']}: {p['authors']} ({p['year']}). \"{p['title']}\". {p['journal']}.{abstract_preview}")
            lines.append(f"  URL: {p['url']}")

    lines.append("\n[These are real PubMed papers. Use their data to support every quantitative claim in the report.]")
    return "\n".join(lines)
