"""
Source-type binding guard (B-03).

Deterministic, LLM-free checks that catch known source-type misattributions.
These complement the LLM-based CLAIM-SOURCE MATCH in source_verifier_node.

Rules here mirror the SOURCE TYPE GUARD prompt instruction in alignment_service —
the prompt tells the LLM not to cite these sources inappropriately; this guard
catches misattributions that survive generation without requiring an LLM call.
"""
from __future__ import annotations

import re
from typing import TypedDict


class SourceCheckItem(TypedDict, total=False):
    field: str
    source: str
    url: str
    claim: str


# Each rule: patterns to match the source name (lowercase), and forbidden claim
# keywords. The first matching keyword per source item produces one flag.
_SOURCE_TYPE_RULES: list[dict] = [
    {
        "name": "rock_health",
        "patterns": ["rock health"],
        "what_it_tracks": "venture capital investments into digital health companies",
        "forbidden_keywords": [
            "market",
            "tam",
            "addressable",
            "revenue",
            "pric",
            "sales",
            "size",
        ],
        "suggestion": (
            "Replace with a market research source (MarketsandMarkets, Mordor Intelligence, "
            "IQVIA, Grand View Research) for market sizing. Rock Health is appropriate "
            "only for tracking VC investment activity."
        ),
    },
    {
        "name": "autm",
        "patterns": ["autm"],
        "what_it_tracks": "licensing deal counts and royalty revenue at U.S. universities",
        "forbidden_keywords": [
            "market",
            "tam",
            "addressable",
        ],
        "suggestion": (
            "AUTM licensing counts are not a proxy for market size or TAM. "
            "Use industry market reports for TAM estimation."
        ),
    },
    {
        "name": "cms_mpfs",
        "patterns": ["mpfs", "physician fee schedule"],
        "what_it_tracks": "Medicare physician reimbursement rates by CPT code",
        "forbidden_keywords": [
            "growth",
            "cagr",
            "trend",
        ],
        "suggestion": (
            "CMS MPFS is a static reimbursement rate schedule, not a market dynamics "
            "source. Use CDC, IQVIA, or peer-reviewed epidemiology for CAGR/growth data."
        ),
    },
]


def check_source_type_bindings(sources: list[SourceCheckItem]) -> list[dict]:
    """
    Deterministic source-type mismatch check. Returns ValidationFlag-format dicts.
    No LLM call required — pure Python.
    """
    flags: list[dict] = []
    for item in sources:
        src = (item.get("source") or "").lower()
        claim = (item.get("claim") or "").lower()
        field = item.get("field") or "sources"

        for rule in _SOURCE_TYPE_RULES:
            if not any(pat in src for pat in rule["patterns"]):
                continue
            for keyword in rule["forbidden_keywords"]:
                if keyword in claim:
                    flags.append({
                        "severity": "WARNING",
                        "category": "SOURCE",
                        "field": field,
                        "issue": (
                            f"'{item.get('source')}' cited for a '{keyword}' claim, "
                            f"but this source tracks {rule['what_it_tracks']} — "
                            f"not appropriate for this claim type."
                        ),
                        "suggestion": rule["suggestion"],
                        "agent": "Source Type Guard",
                    })
                    break  # one flag per (item, rule)
    return flags


# ── Price-segment binding ─────────────────────────────────────────────────────

_RESEARCH_TOOL_MAX_ANNUAL_USD = 50_000  # anything above this is enterprise-tier

_PRICE_K_RE = re.compile(r"(\d+)\s*k\b", re.I)
_PRICE_NUM_RE = re.compile(r"[\d,]+")


def _min_usd_from_str(price_str: str) -> float:
    """
    Extract the minimum USD value from a price range string.
    "$50,000-200,000"  → 50000.0
    "$5k-$15k/yr"      → 5000.0
    "$800-1,500/course" → 800.0
    Returns 0.0 when no parseable value is found.
    """
    normalized = _PRICE_K_RE.sub(lambda m: str(int(m.group(1)) * 1000), price_str)
    parsed = []
    for tok in _PRICE_NUM_RE.findall(normalized):
        try:
            n = float(tok.replace(",", ""))
            if n >= 1000:  # filter out small ordinal numbers ("5 labs")
                parsed.append(n)
        except ValueError:
            pass
    return min(parsed) if parsed else 0.0


def check_price_segment_consistency(
    buyer_segments: list[dict],
    product_type: str,
) -> list[dict]:
    """
    Flag market_access.buyer_segments price estimates that exceed the expected
    annual range for the given product_type.

    The canonical B-03 failure mode: a research_tool is priced at enterprise-SaaS
    rates ($75k+/yr) for academic PI labs, which typically spend $5k-$15k/yr.
    """
    if product_type != "research_tool":
        return []

    flags: list[dict] = []
    for seg in buyer_segments:
        price_str = (
            seg.get("annual_spend_per_facility")
            or seg.get("price_per_unit")
            or ""
        )
        if not price_str:
            continue
        min_usd = _min_usd_from_str(price_str)
        if min_usd > _RESEARCH_TOOL_MAX_ANNUAL_USD:
            flags.append({
                "severity": "WARNING",
                "category": "SOURCE",
                "field": "market_access.buyer_segments",
                "issue": (
                    f"Segment '{seg.get('segment_name', 'unknown')}' shows "
                    f"annual_spend='{price_str}' (min ~${min_usd:,.0f}), "
                    f"which is enterprise-SaaS tier for a research_tool product. "
                    f"Academic PI labs typically spend $5k–$15k/yr on research tools."
                ),
                "suggestion": (
                    "Verify the buyer archetype. For academic research tools, typical "
                    "annual spend per lab is $5k–$15k. If the segment is enterprise/biotech, "
                    "confirm the product_type is not research_tool."
                ),
                "agent": "Source Type Guard",
            })
    return flags
