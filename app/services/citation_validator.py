"""
Citation Validator  (H-05)
==========================
Enforces that every user-facing citation:
  1. Is NOT sourced from an internal knowledge base (internal KB must never
     appear in the user-facing source list — it either has an external citation
     or the claim is dropped).
  2. Has a URL whose domain plausibly matches the named publisher.
  3. Does not emit placeholder values for required numeric fields.

Root cause of defect:
  - "RPM Expert Domain Knowledge - Medlevate RPM Context 2024" cited as a
    source with URL → klasresearch.com (unrelated domain).
  - "WHO Global Burden (DALYs)" citing a number that WHO does not publish.
  - Source name and URL treated as independent free-text fields, so they drift.

Design: runs as a post-processing pass on the serialised report dict.
  strip_internal_citations()  — removes internal KB entries from sources list
  audit_citation_url_domains() — flags domain/publisher mismatches
  strip_placeholder_numerics() — nulls required numerics that are placeholder values
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# ── Internal knowledge base patterns ─────────────────────────────────────────
# Any source whose name matches these substrings was authored internally and
# must not appear as a user-facing citation. The claim either has an external
# source or is dropped.
INTERNAL_KB_PATTERNS: frozenset[str] = frozenset({
    "expert domain knowledge",
    "medlevate",
    "project elevate",
    "medlevate rpm context",
    "rpm context",
    "sub-expert context",
    "sub expert context",
    "domain knowledge base",
    "internal knowledge",
    "expert context",
    "elevate context",
})


# ── Publisher → expected URL domain keywords ──────────────────────────────────
# If a citation names a well-known publisher, its URL must contain at least
# one of the listed keywords. Violations are logged as warnings (not errors).
_PUBLISHER_DOMAIN_MAP: dict[str, list[str]] = {
    "cdc":              ["cdc.gov"],
    "fda":              ["fda.gov", "accessdata.fda.gov"],
    "nih":              ["nih.gov", "nlm.nih.gov", "ncbi.nlm.nih.gov"],
    "pubmed":           ["pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov"],
    "cms":              ["cms.gov", "medicare.gov"],
    "who":              ["who.int"],
    "iqvia":            ["iqvia.com"],
    "rock health":      ["rockhealth.com", "rock.health"],
    "klas":             ["klasresearch.com", "klas"],
    "clinicaltrials":   ["clinicaltrials.gov"],
    "nejm":             ["nejm.org"],
    "lancet":           ["thelancet.com", "lancet.com"],
    "jama":             ["jamanetwork.com"],
    "nature":           ["nature.com", "nature medicine"],
    "barda":            ["barda.hhs.gov", "medicalcountermeasures.gov"],
    "carb-x":           ["carb-x.org"],
    "aha":              ["heart.org", "ahajournals.org"],
    "nci":              ["cancer.gov"],
    "acip":             ["cdc.gov/vaccines/acip"],
    "nih reporter":     ["reporter.nih.gov"],
    "semantic scholar": ["semanticscholar.org", "api.semanticscholar.org"],
}

# Numeric fields that must not carry placeholder defaults.
# The convention: a value of exactly 0 for a non-zero-meaning field is a
# placeholder. We do not null valid zeros (e.g., year 0 doesn't make sense
# for a year field but other 0s may be legitimate), so we target specific
# field names only.
_PLACEHOLDER_NUMERIC_FIELDS = frozenset({
    "total_addressable_market_usd",
    "serviceable_market_usd",
    "tam_estimate",
    "daly_burden",
    "daly_estimate",
    "global_burden_dalys",
})

# Values that are clearly placeholders regardless of field name
_PLACEHOLDER_VALUES = frozenset({0, "0", "N/A", "TBD", "Unknown", "unknown", None})


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class CitationViolation:
    field_path:      str
    publisher:       str
    url:             str
    violation_type:  str   # "internal_kb" | "domain_mismatch" | "placeholder_numeric"
    detail:          str = ""


@dataclass
class CitationAuditResult:
    violations:       list[CitationViolation] = field(default_factory=list)
    internal_stripped: int = 0
    domain_mismatches: int = 0
    placeholder_nulled: int = 0

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)

    def summary(self) -> str:
        parts = []
        if self.internal_stripped:
            parts.append(f"{self.internal_stripped} internal KB citation(s) stripped")
        if self.domain_mismatches:
            parts.append(f"{self.domain_mismatches} publisher/URL domain mismatch(es)")
        if self.placeholder_nulled:
            parts.append(f"{self.placeholder_nulled} placeholder numeric(s) nulled")
        return "; ".join(parts) if parts else "no violations"


# ── Core helpers ──────────────────────────────────────────────────────────────

def _is_internal_kb(name: str) -> bool:
    """Return True if the source name matches any internal KB pattern."""
    name_l = (name or "").lower()
    return any(pat in name_l for pat in INTERNAL_KB_PATTERNS)


def _domain_matches_publisher(url: str, publisher: str) -> Optional[bool]:
    """
    Return True if the URL domain is consistent with the named publisher,
    False if it is clearly inconsistent, None if we have no opinion.
    """
    if not url or not publisher:
        return None
    publisher_l = publisher.lower()
    try:
        domain = urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return None

    for pub_keyword, expected_domains in _PUBLISHER_DOMAIN_MAP.items():
        if pub_keyword in publisher_l:
            match = any(exp in domain or exp in url.lower() for exp in expected_domains)
            return match
    return None   # no opinion for unknown publishers


def _walk_citations(obj, path: str = ""):
    """
    Yield (path, source_dict) for every dict that looks like a citation
    (has at least a 'source' or 'name' key alongside a 'url' or 'source_url' key).
    """
    if isinstance(obj, dict):
        has_source_key = "source" in obj or "name" in obj
        has_url_key = "url" in obj or "source_url" in obj
        if has_source_key and has_url_key:
            yield path, obj
        for k, v in obj.items():
            yield from _walk_citations(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            yield from _walk_citations(item, f"{path}[{i}]")


def _get_pub_url(citation: dict) -> tuple[str, str]:
    publisher = citation.get("source") or citation.get("name") or citation.get("publisher") or ""
    url = citation.get("url") or citation.get("source_url") or ""
    return str(publisher), str(url)


# ── Public API ────────────────────────────────────────────────────────────────

def strip_internal_citations(report_dict: dict) -> tuple[dict, int]:
    """
    Walk the report dict and null the URL (and optionally the source name)
    for any citation whose publisher is an internal KB source.

    Returns (mutated_report_dict, count_stripped).
    The report is mutated in place for efficiency; the same object is returned.
    """
    count = 0
    # 1. Clean the top-level 'sources' list
    sources = report_dict.get("sources")
    if isinstance(sources, list):
        cleaned: list = []
        for s in sources:
            name = s.get("name") or s.get("source") or ""
            if _is_internal_kb(name):
                count += 1
                logger.info("H-05: stripped internal KB source: %r", name[:80])
            else:
                cleaned.append(s)
        if count:
            report_dict["sources"] = cleaned

    # 2. Null source_url fields inside nested citation objects
    for path, citation in _walk_citations(report_dict):
        pub, url = _get_pub_url(citation)
        if _is_internal_kb(pub) and url:
            citation["url"] = None
            if "source_url" in citation:
                citation["source_url"] = None
            count += 1
            logger.debug("H-05: nulled internal KB URL at %s: %r", path, pub[:60])

    return report_dict, count


def audit_citation_url_domains(report_dict: dict) -> list[CitationViolation]:
    """
    Scan all citations and flag where the URL domain does not plausibly
    match the named publisher. Returns a list of violations for logging;
    does NOT mutate the report (the caller decides what to do with mismatches).
    """
    violations: list[CitationViolation] = []
    for path, citation in _walk_citations(report_dict):
        pub, url = _get_pub_url(citation)
        if not pub or not url:
            continue
        match = _domain_matches_publisher(url, pub)
        if match is False:   # clearly inconsistent (not None = unknown)
            try:
                domain = urlparse(url).netloc
            except Exception:
                domain = url[:40]
            violations.append(CitationViolation(
                field_path=path,
                publisher=pub,
                url=url,
                violation_type="domain_mismatch",
                detail=f"Publisher '{pub[:50]}' → URL domain '{domain}' (inconsistent)",
            ))
    return violations


def strip_placeholder_numerics(report_dict: dict) -> tuple[dict, int]:
    """
    Walk the report dict and null any value in _PLACEHOLDER_NUMERIC_FIELDS
    that is a known placeholder (0, "N/A", "TBD", etc.).

    Returns (mutated_report_dict, count_nulled).
    """
    count = 0

    def _walk(obj):
        nonlocal count
        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                if k in _PLACEHOLDER_NUMERIC_FIELDS and v in _PLACEHOLDER_VALUES:
                    obj[k] = None
                    count += 1
                    logger.debug("H-05: nulled placeholder numeric field '%s'=%r", k, v)
                else:
                    _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(report_dict)
    return report_dict, count


def run_citation_audit(report_dict: dict) -> CitationAuditResult:
    """
    Full H-05 citation audit pass. Mutates the report in place.
    Returns a CitationAuditResult summary.
    """
    result = CitationAuditResult()

    report_dict, stripped = strip_internal_citations(report_dict)
    result.internal_stripped = stripped

    mismatches = audit_citation_url_domains(report_dict)
    result.domain_mismatches = len(mismatches)
    result.violations.extend(mismatches)
    for v in mismatches:
        logger.warning("H-05 domain mismatch: %s | %s → %s", v.field_path, v.publisher[:50], v.url[:60])

    report_dict, nulled = strip_placeholder_numerics(report_dict)
    result.placeholder_nulled = nulled

    if result.has_violations or stripped or nulled:
        logger.info("H-05 citation audit: %s", result.summary())

    return result
