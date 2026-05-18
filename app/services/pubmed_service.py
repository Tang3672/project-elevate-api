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
from typing import List, Dict, Optional
import httpx

logger = logging.getLogger(__name__)

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
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(PUBMED_SEARCH_URL, params={
                "db": "pubmed",
                "term": query,
                "retmax": max_results,
                "retmode": "json",
                "sort": "relevance",
            })
            if r.status_code == 200:
                data = r.json()
                return data.get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        logger.warning(f"PubMed search failed: {e}")
    return []


async def _fetch_paper_summaries(pmids: List[str]) -> List[Dict]:
    """Fetch paper summaries and abstracts for a list of PMIDs."""
    if not pmids:
        return []
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            # Get summary data
            r = await client.get(PUBMED_SUMMARY_URL, params={
                "db": "pubmed",
                "id": ",".join(pmids),
                "retmode": "json",
            })
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
                ra = await client.get(PUBMED_FETCH_URL, params={
                    "db": "pubmed",
                    "id": ",".join(pmids),
                    "rettype": "abstract",
                    "retmode": "text",
                })
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
                            ab_end = abstract_text.find("

", ab_start) if ab_start != -1 else -1
                            if ab_start != -1 and ab_end != -1:
                                abstract = abstract_text[ab_start+6:ab_end].replace("
      ", " ").strip()
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
                lines.append(f"  PMID {p['pmid']}: {p['authors']} ({p['year']}). "{p['title']}". {p['journal']}.{abstract_preview}")
                lines.append(f"  URL: {p['url']}")
            lines.append("")

    remaining = [p for p in pub_data["publications"] if p["pmid"] not in used]
    if remaining:
        lines.append("OTHER KEY PAPERS:")
        for p in remaining[:2]:
            abstract = p.get("abstract", "")
            abstract_preview = f" | {abstract[:150]}..." if abstract else ""
            lines.append(f"  PMID {p['pmid']}: {p['authors']} ({p['year']}). "{p['title']}". {p['journal']}.{abstract_preview}")
            lines.append(f"  URL: {p['url']}")

    lines.append("\n[These are real PubMed papers. Use their data to support every quantitative claim in the report.]")
    return "\n".join(lines)
