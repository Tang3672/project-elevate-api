"""
B-05 — Unified competitor schema.

All product archetypes use the same Competitor dict shape on the wire.
Drug-specific counts (approved_count, pipeline_count) live alongside but
never replace the generic fields. Any frontend or renderer that reads a
field not in this schema receives an empty string, never JavaScript
`undefined`.

Public API
----------
normalize_competitor(raw: dict) -> dict
    Fill all required keys with safe defaults so no downstream renderer
    can encounter a missing key.

COMPETITOR_CATEGORY : frozenset
    Valid values for the `category` field.
"""

from __future__ import annotations

from typing import Any

# ── Controlled vocabulary for the category field ──────────────────────────────
COMPETITOR_CATEGORY = frozenset({
    "status_quo",        # incumbent behaviour (DIY, spreadsheets, scripts)
    "diy_internal",      # lab-built internal solution
    "adjacent_general",  # general-purpose tool used for this task
    "direct",            # product built for the same use case
    "upstream_platform", # infrastructure the product depends on / competes with
    "approved_drug",     # FDA-approved drug (clinical archetypes)
    "pipeline_drug",     # drug in clinical trials
    "medical_device",    # cleared/approved device
    "diagnostic",        # IVD / companion diagnostic
    "samd",              # SaMD / digital therapeutic
})

# ── Required fields for every competitor entry ────────────────────────────────
_REQUIRED_FIELDS: tuple[str, ...] = (
    "name",
    "category",
    "overlap",
    "where_you_win",
    "where_you_lose",
    "switching_cost",
)

# ── Drug-archetype-specific fields (present only for clinical products) ────────
_DRUG_FIELDS: tuple[str, ...] = (
    "stage",
    "company",
    "brand_name",
    "route",
    "advantages",
    "vulnerabilities",
    "positioning_signal",
)

# ── Defaults for fields absent in legacy / drug-schema entries ────────────────
_FIELD_DEFAULTS: dict[str, Any] = {
    "name":            "",
    "category":        "direct",
    "overlap":         "",
    "where_you_win":   "",
    "where_you_lose":  "",
    "switching_cost":  "",
    "price_point":     None,
    "incumbent":       False,
    "description":     "",
    "url":             "",
    # drug schema pass-throughs (empty for non-drug archetypes)
    "stage":           "",
    "company":         "",
    "brand_name":      "",
    "route":           "",
    "advantages":      [],
    "vulnerabilities": [],
    "positioning_signal": "",
    "nct_id":          "",
    "status":          "",
    "sponsor":         "",
    "key_differentiator": "",
}


def normalize_competitor(raw: dict) -> dict:
    """
    Return a copy of `raw` with every expected key present.

    Missing keys get safe defaults so a JS frontend reading
    `entry.stage` on a research-tool competitor returns ``""``
    rather than ``undefined``.
    """
    out = dict(_FIELD_DEFAULTS)
    out.update({k: v for k, v in raw.items() if v is not None})
    # Coerce list fields to lists
    for lf in ("advantages", "vulnerabilities"):
        if not isinstance(out.get(lf), list):
            out[lf] = [out[lf]] if out.get(lf) else []
    # Coerce bool
    out["incumbent"] = bool(out.get("incumbent", False))
    return out


def normalize_landscape(landscape: dict) -> dict:
    """
    Return a copy of `landscape` with:
    - `competitors` key present (aliases from `research_tool_comparators`/`comparators`)
    - every competitor entry normalized via `normalize_competitor`
    """
    out = dict(landscape)
    # Unify key names: prefer `competitors`, fall back to older aliases
    competitors = (
        out.get("competitors")
        or out.get("research_tool_comparators")
        or out.get("comparators")
        or []
    )
    out["competitors"] = [normalize_competitor(c) for c in competitors]
    # Remove aliases so callers only see `competitors`
    out.pop("research_tool_comparators", None)
    out.pop("comparators", None)
    return out
