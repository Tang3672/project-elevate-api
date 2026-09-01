"""
Source Formatter — LangGraph Node
===================================
Extracts inline [SOURCE: url] markers from report text,
replaces with numbered superscripts [1][2] etc.,
and builds a deduplicated sources list.
"""
import re
import logging
from typing import List, Dict
from datetime import datetime

logger = logging.getLogger(__name__)

# B-06: search/query URLs are not citable sources — they are ephemeral API calls.
# Any URL matching these patterns is excluded from the sources list.
_QUERY_URL_PATTERNS = (
    "reporter.nih.gov/search",
    "reporter.nih.gov/v2/projects/search",
    "eutils.ncbi.nlm.nih.gov",
    "pubmed.ncbi.nlm.nih.gov/search",
    "ncbi.nlm.nih.gov/pmc/search",
    "medrxiv.org/search",
    "biorxiv.org/search",
    "clinicaltrials.gov/search",
    "scholar.google.com/scholar?",
    "semanticscholar.org/search",
)

def _is_query_url(url: str) -> bool:
    """Return True if the URL is a search/query endpoint rather than a specific page."""
    if not url:
        return False
    url_l = url.lower()
    return any(p in url_l for p in _QUERY_URL_PATTERNS)


def extract_and_format_sources(report: dict) -> dict:
    """
    Process all text fields in the report:
    1. Find [SOURCE: url] or [SOURCE: name | url] markers
    2. Replace with [N] superscript
    3. Build sources list

    Returns updated report dict with sources array added.
    """
    sources: List[Dict] = []
    url_to_idx: Dict[str, int] = {}

    def replace_source_markers(text: str) -> str:
        """Replace [SOURCE: url] with [N] and collect sources."""
        if not text or not isinstance(text, str):
            return text

        # Pattern: [SOURCE: name | url] or [SOURCE: url]
        pattern = r'\[SOURCE:\s*([^\]|]+?)(?:\s*\|\s*([^\]]+))?\]'

        def replacer(m):
            name_or_url = m.group(1).strip()
            url         = m.group(2).strip() if m.group(2) else ""

            # If only one part, try to determine if it's a URL
            if not url:
                if name_or_url.startswith("http"):
                    url  = name_or_url
                    name = _url_to_name(url)
                else:
                    name = name_or_url
                    url  = ""
            else:
                name = name_or_url

            # B-06: skip search/query endpoints — they are not citable sources
            if _is_query_url(url):
                return ""

            # Deduplicate by URL
            key = url or name
            if key not in url_to_idx:
                idx = len(sources) + 1
                url_to_idx[key] = idx
                sources.append({
                    "number":       idx,
                    "name":         name,
                    "url":          url,
                    "accessed":     datetime.utcnow().strftime("%Y-%m-%d"),
                })
            n = url_to_idx[key]
            return f"[{n}]"

        return re.sub(pattern, replacer, text)

    def process_value(v):
        """Recursively process all string values in the report."""
        if isinstance(v, str):
            return replace_source_markers(v)
        if isinstance(v, list):
            return [process_value(item) for item in v]
        if isinstance(v, dict):
            return {k: process_value(val) for k, val in v.items()}
        return v

    # Process the entire report
    processed = {k: process_value(v) for k, v in report.items()}

    # Add sources section
    if sources:
        processed["sources"] = sources
        logger.info(f"Source formatter: {len(sources)} unique sources extracted")
    else:
        processed["sources"] = []

    return processed


def _url_to_name(url: str) -> str:
    """Convert URL to readable source name."""
    url_names = {
        "cdc.gov":              "CDC",
        "fda.gov":              "FDA",
        "nih.gov":              "NIH",
        "pubmed.ncbi.nlm.nih.gov": "PubMed",
        "ncbi.nlm.nih.gov":    "NCBI/PubMed",
        "who.int":              "WHO",
        "idsociety.org":        "IDSA",
        "ahajournals.org":      "AHA Journals",
        "cancer.org":           "American Cancer Society",
        "alz.org":              "Alzheimer's Association",
        "barda.hhs.gov":        "BARDA",
        "carb-x.org":           "CARB-X",
        "clinicaltrials.gov":   "ClinicalTrials.gov",
        "medicare.gov":         "CMS Medicare",
        "hrsa.gov":             "HRSA",
        "samhsa.gov":           "SAMHSA",
        "nimh.nih.gov":         "NIMH",
        "niddk.nih.gov":        "NIDDK",
        "nhlbi.nih.gov":        "NHLBI",
        "ninds.nih.gov":        "NINDS",
        "nejm.org":             "New England Journal of Medicine",
        "thelancet.com":        "The Lancet",
        "jamanetwork.com":      "JAMA",
    }
    for domain, name in url_names.items():
        if domain in url:
            return name
    # Extract domain as fallback
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return url[:50]


def build_sources_from_report(report: dict) -> dict:
    """
    Build sources list from structured source_url fields and inline [SOURCE:] markers.
    Returns the text-processed report (all [SOURCE:...] markers replaced with [N]).
    """
    from datetime import datetime

    # M-06: process inline markers first — returns report with [SOURCE:] replaced by [N]
    processed = extract_and_format_sources(report)

    # Seed dedup index from already-extracted inline sources
    url_to_idx: dict = {s["url"]: s["number"] for s in processed.get("sources", []) if s.get("url")}
    sources: list = list(processed.get("sources", []))
    today = datetime.utcnow().strftime("%Y-%m-%d")

    def add_source(name: str, url: str):
        if not url or url == "None":
            return
        if _is_query_url(url):
            return
        key = url.strip()
        if key not in url_to_idx:
            idx = len(sources) + 1
            url_to_idx[key] = idx
            sources.append({
                "number":   idx,
                "name":     name or _url_to_name(url),
                "url":      key,
                "accessed": today,
            })

    # Merge additional sources from structured source_url fields in the processed report
    di = processed.get("disease_intelligence") or {}
    for dp in di.get("data_points", []):
        add_source(dp.get("source", ""), dp.get("source_url", ""))

    ms = processed.get("market_sizing") or {}
    for step in ms.get("steps", []):
        add_source(step.get("source", ""), step.get("source_url", ""))

    rp = processed.get("regulatory_pathway") or {}
    for des in rp.get("designations", []):
        add_source(des.get("source", ""), des.get("source_url", ""))
    for trial in rp.get("clinical_trial_requirements", []):
        add_source(trial.get("fda_guidance_document", ""), trial.get("source_url", ""))

    ma = processed.get("market_access") or {}
    for seg in ma.get("buyer_segments", []):
        add_source(seg.get("source", ""), seg.get("source_url", ""))

    if sources:
        processed["sources"] = sources

    return processed
