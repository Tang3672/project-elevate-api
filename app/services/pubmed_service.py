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

# B-02: archetypes whose primary literature is NOT in PubMed (agronomy, materials,
# engineering). Route these through OpenAlex, which covers all disciplines.
_NON_PUBMED_ARCHETYPES: frozenset = frozenset({
    "research_tool_non_clinical",
    "research_infrastructure_saas",
    "research_tool_agronomy",
})


def _invert_index_to_text(inverted_index: dict) -> str:
    """Reconstruct abstract text from OpenAlex's inverted-index format.

    OpenAlex stores abstracts as {word: [position, ...]} to avoid copyright issues.
    This reconstructs a readable sentence for relevance scoring.
    """
    if not inverted_index:
        return ""
    try:
        max_pos = max(p for positions in inverted_index.values() for p in positions) + 1
        words: list[str] = [""] * max_pos
        for word, positions in inverted_index.items():
            for pos in positions:
                if 0 <= pos < max_pos:
                    words[pos] = word
        return " ".join(w for w in words if w)[:500]
    except Exception:
        return ""


async def _get_openalex_publications(topic: str, sub_expert_id: str, max_results: int = 8) -> list:
    """B-02: Primary publication retrieval via OpenAlex for non-biomedical archetypes.

    PubMed doesn't index agronomy, soil science, or materials engineering journals.
    OpenAlex covers all disciplines, including foundational sensor papers (Topp 1980,
    Vellidis 2008) that PubMed will never return.
    """
    try:
        # Build a topic search phrase that avoids clinical/disease framing
        search_phrase = topic[:80]

        params = {
            "search":   search_phrase,
            "per-page": str(max_results),
            "select":   "id,doi,display_name,authorships,primary_location,publication_year,abstract_inverted_index",
            "mailto":   _CONTACT_EMAIL,
            "sort":     "cited_by_count:desc",
        }
        t0 = time.monotonic()
        r = httpx.get(_OPENALEX_URL, params=params, timeout=12.0)
        latency_ms = (time.monotonic() - t0) * 1000
        items = r.json().get("results", []) if r.status_code == 200 else []
        _log_fetch_pubmed(
            _OPENALEX_URL, "GET", r.status_code,
            latency_ms, len(r.content), len(items),
            f"openalex primary search={search_phrase[:60]}",
        )

        papers = []
        for w in items:
            doi = (w.get("doi") or "").replace("https://doi.org/", "")
            authors_raw = w.get("authorships") or []
            last_names = [
                a.get("author", {}).get("display_name", "").split()[-1]
                for a in authors_raw[:3]
                if a.get("author", {}).get("display_name")
            ]
            authors_str = (
                (last_names[0] + " et al.") if len(last_names) > 1
                else (last_names[0] if last_names else "")
            )
            journal = ((w.get("primary_location") or {}).get("source") or {})
            abstract = _invert_index_to_text(w.get("abstract_inverted_index") or {})
            papers.append({
                "pmid":         "",
                "title":        w.get("display_name", ""),
                "authors":      authors_str,
                "journal":      journal.get("display_name", ""),
                "year":         str(w.get("publication_year", "")),
                "url":          f"https://doi.org/{doi}" if doi else "",
                "doi":          doi,
                "abstract":     abstract,
                "verified_via": "openAlex",
            })
        return papers
    except Exception as exc:
        logger.warning("OpenAlex publication search failed (non-fatal): %s", exc)
        return []


async def get_landmark_publications(
    disease_name: str,
    sub_expert_id: str,
    max_papers: int = 8,
) -> Dict:
    """
    Pull top landmark publications for a disease + expert domain.

    B-02: non-biomedical archetypes (agronomy, engineering research tools) route
    through OpenAlex, which indexes all disciplines. PubMed does not index
    Canadian Journal of Soil Science, Computers and Electronics in Agriculture,
    or MDPI Sensors — the core literature for those products.
    """
    results = {
        "disease": disease_name,
        "publications": [],
        "systematic_reviews": [],
        "recent_trials": [],
        "guidelines": [],
        "total_found": 0,
    }

    # B-02: non-biomedical products → OpenAlex primary retrieval
    if sub_expert_id in _NON_PUBMED_ARCHETYPES:
        papers = await _get_openalex_publications(disease_name, sub_expert_id, max_papers)
        results["publications"] = papers
        results["total_found"] = len(papers)
        return results

    # Biomedical products → PubMed (unchanged path)
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
    # Clinical psychology / neuropsychology (B-01: apathy-motivation paper, PMID 37012520)
    "apathy", "psychometric",
    # Ophthalmology (B-01: ocular toxicity paper, PMID 35817277)
    "ocular toxicity", "vigabatrin", "infantile spasms",
})


def _is_non_clinical_product(sub_expert_id: str) -> bool:
    s = (sub_expert_id or "").lower()
    return "non_clinical" in s or s.startswith("research_tool") or "lab_software" in s


# ── G.3 OpenAlex: fallback verifier + primary retrieval for non-biomedical ────

_OPENALEX_URL  = "https://api.openalex.org/works"
_CROSSREF_URL  = "https://api.crossref.org/works"
_CONTACT_EMAIL = "oneonesie100@gmail.com"   # required by OpenAlex polite pool


def _openalex_result_to_meta(w: dict, query_title: str) -> "dict | None":
    """Convert a raw OpenAlex work dict to our normalised metadata format."""
    w_title = (w.get("display_name") or "").lower()
    q_words = set(query_title.lower().split())
    w_words = set(w_title.split())
    if not q_words or len(q_words & w_words) / len(q_words) < 0.40:
        return None
    doi = (w.get("doi") or "").replace("https://doi.org/", "")
    authors_raw = w.get("authorships") or []
    last_names = [
        a.get("author", {}).get("display_name", "").split()[-1]
        for a in authors_raw[:3]
        if a.get("author", {}).get("display_name")
    ]
    authors_str = (last_names[0] + " et al.") if len(last_names) > 1 else (last_names[0] if last_names else "")
    journal = ((w.get("primary_location") or {}).get("source") or {})
    return {
        "title":        w.get("display_name", ""),
        "authors":      authors_str,
        "journal":      journal.get("display_name", ""),
        "year":         str(w.get("publication_year", "")),
        "doi":          doi,
        "url":          f"https://doi.org/{doi}" if doi else "",
        "verified_via": "openAlex",
    }


def resolve_via_openalex(title: str) -> "dict | None":
    """Query OpenAlex by title (sync). Returns normalised metadata dict or None."""
    if not title or len(title) < 10:
        return None
    try:
        t0 = time.monotonic()
        r = httpx.get(
            _OPENALEX_URL,
            params={
                "filter":   f"title.search:{title[:120]}",
                "per-page": "1",
                "select":   "id,doi,display_name,authorships,primary_location,publication_year",
                "mailto":   _CONTACT_EMAIL,
            },
            timeout=8.0,
        )
        _log_fetch_pubmed(
            _OPENALEX_URL, "GET", r.status_code,
            (time.monotonic() - t0) * 1000, len(r.content),
            1 if r.status_code == 200 else 0,
            f"openalex title={title[:60]}",
        )
        if r.status_code != 200:
            return None
        items = r.json().get("results", [])
        if not items:
            return None
        return _openalex_result_to_meta(items[0], title)
    except Exception as exc:
        logger.debug("OpenAlex lookup failed for %r: %s", title[:60], exc)
        return None


def resolve_via_crossref(title: str) -> "dict | None":
    """Query Crossref by title (sync). Returns normalised metadata dict or None."""
    if not title or len(title) < 10:
        return None
    try:
        t0 = time.monotonic()
        r = httpx.get(
            _CROSSREF_URL,
            params={
                "query.title": title[:120],
                "rows":        "1",
                "select":      "DOI,title,author,published,container-title",
            },
            timeout=8.0,
        )
        _log_fetch_pubmed(
            _CROSSREF_URL, "GET", r.status_code,
            (time.monotonic() - t0) * 1000, len(r.content),
            1 if r.status_code == 200 else 0,
            f"crossref title={title[:60]}",
        )
        if r.status_code != 200:
            return None
        items = (r.json().get("message") or {}).get("items") or []
        if not items:
            return None
        item = items[0]
        cr_title = (item.get("title") or [""])[0]
        q_words = set(title.lower().split())
        c_words = set(cr_title.lower().split())
        if not q_words or len(q_words & c_words) / len(q_words) < 0.40:
            return None
        doi = item.get("DOI", "")
        authors_raw = item.get("author") or []
        last_names = [a.get("family", "") for a in authors_raw[:3] if a.get("family")]
        authors_str = (last_names[0] + " et al.") if len(last_names) > 1 else (last_names[0] if last_names else "")
        pub_date = item.get("published", {}).get("date-parts") or [[""]]
        year = str(pub_date[0][0]) if pub_date[0] else ""
        container = (item.get("container-title") or [""])[0]
        return {
            "title":        cr_title,
            "authors":      authors_str,
            "journal":      container,
            "year":         year,
            "doi":          doi,
            "url":          f"https://doi.org/{doi}" if doi else "",
            "verified_via": "crossref",
        }
    except Exception as exc:
        logger.debug("Crossref lookup failed for %r: %s", title[:60], exc)
        return None


# ── G.3 Relevance gate ─────────────────────────────────────────────────────────

def _keyword_relevance_score(title: str, abstract: str, idea: str) -> int:
    """
    Heuristic 0-10 relevance score: how well does a paper match the product idea?
    Counts distinct idea-word matches in title+abstract; scales to 0-10.

    A score < 6 indicates the paper is probably off-topic for this product.
    """
    if not idea:
        return 10  # no idea text → can't filter, pass everything
    # Extract meaningful words from idea (≥4 chars, skip stopwords)
    _STOP = {"with", "that", "this", "from", "have", "been", "will", "which",
              "their", "using", "based", "into", "more", "than", "also",
              "about", "some", "such", "when", "where", "what", "each"}
    idea_words = {w for w in idea.lower().split() if len(w) >= 4 and w not in _STOP}
    if not idea_words:
        return 10
    corpus = ((title or "") + " " + (abstract or "")).lower()
    matched = sum(1 for w in idea_words if w in corpus)
    # Scale: 0 matches → 0, all matches → 10; anything ≥ 30% of idea words → ≥ 6
    score = min(10, round(matched / len(idea_words) * 10 * 2))  # ×2 so 30% → 6
    return score


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


_RELEVANCE_THRESHOLD_NULL_PMID = 6   # null-PMID (LLM-recalled): strict gate
_RELEVANCE_THRESHOLD_PMID      = 6   # fix 7: same threshold for PMID-backed; score abstract first
_RELEVANCE_THRESHOLD = _RELEVANCE_THRESHOLD_NULL_PMID  # alias used by tests


def filter_literature_citations(
    citations: List[dict],
    idea: str,
    sub_expert_id: str,
) -> List[dict]:
    """
    Part A + B-09 + G.3: Verify each citation and gate on relevance.

    Changes in G.3:
    - Null-PMID citations → try OpenAlex then Crossref by title.
      If neither resolves, the citation is an LLM hallucination and is dropped.
    - All citations (PMID and non-PMID alike) are scored for relevance to the
      idea using _keyword_relevance_score. Score < 6 → dropped before display.

    Off-domain signal filtering (B-09) still applies for non-clinical products.
    """
    if not citations:
        return citations

    # Sentinel title prefixes that some retrieval paths emit as "no results" entries.
    # These are plumbing artifacts, not papers — drop them unconditionally.
    _SENTINEL_PREFIXES = (
        "no pubmed", "no publications", "not indexed", "no results",
        "no papers found", "not available", "no literature",
    )

    verified = []
    for c in citations:
        pmid = (c.get("pmid") or "").strip()

        # D-02: PMC IDs (PMC\d+) are NOT PubMed IDs. Also drop sentinel non-numeric
        # values like "N/A", "NA", "None". Real PMIDs are purely numeric.
        # Non-numeric "PMIDs" are treated as null-PMID → stricter gate applies.
        if pmid and (pmid.upper().startswith("PMC") or not pmid.lstrip("-").isdigit()):
            logger.debug(
                "D-02: non-numeric or PMC-namespace ID '%s' treated as null-PMID", pmid
            )
            pmid = ""

        # ── G.3: null-PMID path — verify via OpenAlex / Crossref ─────────────
        if not pmid:
            title = (c.get("title") or "").strip()
            if not title:
                logger.debug("G.3: dropping citation with no PMID and no title")
                continue
            # Drop sentinel "no results" titles before attempting any external lookup.
            if title.lower().startswith(_SENTINEL_PREFIXES) or title.lower() in ("n/a", "na", "none"):
                logger.debug("D-02: dropping sentinel no-result entry '%s'", title[:60])
                continue
            external = resolve_via_openalex(title) or resolve_via_crossref(title)
            if external is None:
                logger.warning(
                    "G.3: dropping unverifiable null-PMID citation '%s' "
                    "(not found in OpenAlex or Crossref)",
                    title[:80],
                )
                continue
            # Replace LLM-recalled metadata with verified external metadata
            c = {**c, **external, "relevance": c.get("relevance", "")}
            logger.info(
                "G.3: null-PMID citation '%s' verified via %s",
                title[:60], external.get("verified_via", "?"),
            )

        # ── PMID path (unchanged from Part A) ────────────────────────────────
        else:
            resolved = resolve_pmid(pmid)
            _pmid_resolved_ok = resolved is not None
            if resolved is None:
                # Unresolvable PMID (network error or non-existent): pass through.
                # Hard drop only when a PMID resolves to a DIFFERENT title.
                logger.debug("Part A gate: PMID %s did not resolve — passing to relevance gate", pmid)
            else:
                # Title match check
                gen_title = (c.get("title") or "").lower().strip()
                real_title = resolved["title"].lower().strip()
                if gen_title and real_title:
                    gen_words = set(gen_title.split())
                    real_words = set(real_title.split())
                    overlap = len(gen_words & real_words) / max(len(gen_words), 1)
                    if overlap < 0.30:
                        logger.warning(
                            "Part A gate: PMID %s title mismatch — generated '%s...' vs real '%s...' — using real title",
                            pmid, gen_title[:60], real_title[:60],
                        )
                        c = {**c, **resolved, "relevance": c.get("relevance", "")}

                # Part A abstract guard
                abstract = resolved.get("abstract", "")
                checked_relevance = _verify_claims_against_abstract(c.get("relevance", ""), abstract)
                if checked_relevance != c.get("relevance", ""):
                    c = {**c, "relevance": checked_relevance}
                # fix 7: provide the real abstract for relevance scoring below
                # (it's not in c unless the title mismatched and triggered a full merge)
                if abstract and not c.get("abstract"):
                    c = {**c, "abstract": abstract}

                # G.3 strict gate for research tools: if a PMID resolves to real
                # metadata but has zero keyword overlap with the product idea, it's a
                # false-positive retrieval (e.g. "laryngeal mask airways" for a soil
                # moisture sensor). Drop it. Doesn't fire for clinical products or
                # unresolvable PMIDs (those fall through to the main threshold gate).
                if _is_non_clinical_product(sub_expert_id) and idea:
                    _strict_score = _keyword_relevance_score(
                        resolved.get("title", ""), resolved.get("abstract", ""), idea
                    )
                    if _strict_score == 0:
                        logger.debug(
                            "G.3 strict gate (research tool, verified PMID): dropped '%s' (score=0)",
                            resolved.get("title", "")[:80],
                        )
                        continue

        # ── G.3 relevance gate — ALL citations (B-01 fix) ───────────────────────
        # null-PMID: strict gate (threshold 6) — these are LLM-recalled with no
        # prior retrieval filter.  A score < 6 means <30% idea-word overlap, almost
        # certainly off-topic (e.g. apathy paper recalled for cloud sync platform).
        #
        # PMID-backed: gate is threshold 0 (never fires here) — PubMed search
        # already filtered for domain relevance. The additional research-tool strict
        # gate above (inside the PMID resolved block) catches fully-resolved PMIDs
        # that still have zero overlap with the product idea.
        threshold = _RELEVANCE_THRESHOLD_NULL_PMID if not pmid else _RELEVANCE_THRESHOLD_PMID
        score = _keyword_relevance_score(
            c.get("title") or "",
            c.get("abstract") or "",
            idea,
        )
        if score < threshold:
            logger.debug(
                "G.3 relevance gate: dropped citation '%s' (score=%d < threshold=%d, pmid=%r)",
                (c.get("title") or "")[:80], score, threshold, pmid or "null",
            )
            continue

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
