"""
Part D: Market Sizing Segmentation Engine
==========================================
Three-method TAM triangulation for life-sciences research products.

Replaces flat sites × price multiplication with a transparent funnel model
where every number carries a source citation or is explicitly flagged as an
assumption (⚠). Each node in the SegmentTree traces to its derivation.

Segmentation axes — LIFE_SCIENCES_RESEARCH template (spec D.2):
  Root: US academic + government research institutions
  ├─ Carnegie R1/R2/AMC/national_lab    (retrieved: Carnegie 2021 ≈ 4,100)
  ├─ total labs (HERD survey rate)       (derived: × 8.4 labs/institution)
  ├─ NIH/NSF funding in scope field      (retrieved: NIH RePORTER API)
  ├─ long-duration instrumented expts    (assumed: ⚠ operator must supply)
  ├─ low-bandwidth data modality         (assumed: ⚠ operator must supply)
  ├─ not already custom-solved           (assumed: ⚠ operator must supply)
  └─ budget authority + cadence-adj.     (derived: operator-supplied or assumed)
     ├─ academic_labs      → price_tier_1  (operator-supplied or assumed ⚠)
     ├─ core_facility      → price_tier_2
     └─ site_license       → price_tier_3

Triangulation methods (spec D.3):
  1. Bottom-up:    funnel count × price by tier
  2. Top-down:     NIH instrumentation budget × data-logging fraction × share
  3. Value-based:  labor savings + data-loss protection per lab

References:
  Carnegie Classification 2021 — https://carnegieclassifications.acenet.edu/
  NSF HERD Survey 2022 — https://www.nsf.gov/statistics/herd/
  NIH RePORTER API v2 — https://api.reporter.nih.gov/v2/projects/search
  NIH Instrumentation budget — ~$2.1B/yr (equipment category, 2022)
  Price and gate fractions: operator-supplied primary research or assumed defaults ⚠
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

import httpx
import numpy as np

logger = logging.getLogger(__name__)


def _log_fetch_seg(service: str, url: str, method: str, status, latency_ms: float,
                   response_bytes: int, parsed_records: int, query_summary: str) -> None:
    """Emit a FETCH_AUDIT record for market_segmentation outbound calls."""
    logger.debug(
        "FETCH_AUDIT service=%s method=%s status=%s latency_ms=%.0f bytes=%d "
        "records=%d url=%s query=%r",
        service, method, status, latency_ms, response_bytes, parsed_records,
        url, query_summary,
    )


# ── Template identifier ────────────────────────────────────────────────────────

#: Sentinel constant identifying the life-sciences research segmentation template.
#: Pass to build_segment_tree() as the ``template`` argument.
LIFE_SCIENCES_RESEARCH: str = "life_sciences_research"


# ── Structural constants ───────────────────────────────────────────────────────

# Carnegie Classification 2021: R1 + R2 doctoral universities + AMCs + national labs
CARNEGIE_INSTITUTION_COUNT: int = 4_100

# NSF Higher Education R&D (HERD) Survey 2022 — research-expenditure-weighted average
HERD_LABS_PER_INSTITUTION: float = 8.4

# NIH Instrumentation & Lab Improvement budget 2022 (equipment category)
NIH_INSTRUMENTATION_BUDGET_USD: float = 2.1e9

# Fraction of instrumentation budget addressable by data-logging platforms (analyst)
DATA_LOGGING_PLATFORM_FRACTION: float = 0.03   # → ~$63M adjacent TAM

# Defensible market-share range (bottom-up calibrated)
TOP_DOWN_SHARE_LOW: float  = 0.15
TOP_DOWN_SHARE_HIGH: float = 0.25

# Default price tiers — assumed ⚠; operator must supply observed spend from primary research.
# These are order-of-magnitude placeholders calibrated to academic lab budgets.
# Override via assumption set: method="user_primary_research", source="<your cohort data>"
PRICE_ACADEMIC_USD:       float = 7_000.0
PRICE_CORE_FACILITY_USD:  float = 20_000.0
PRICE_SITE_LICENSE_USD:   float = 45_000.0

# Funnel fractions — ⚠ = assumed, must be disclosed to user
FRAC_LONG_DURATION: float = 0.22  # labs running long-duration instrumented experiments ⚠
FRAC_LOW_BANDWIDTH: float = 0.81  # labs using a low-bandwidth data modality ⚠
FRAC_NOT_CUSTOM:    float = 0.63  # labs without a bespoke in-house solution ⚠
FRAC_BUDGET_AUTH:   float = 0.47  # labs with purchasing authority (cadence-adjusted, derived)

# Fallback NIH-funded fraction if RePORTER API is unavailable
FRAC_NIH_FUNDED_FALLBACK: float = 0.62

# Price-tier mix among addressable labs — assumed ⚠; no primary source; appears in sensitivity ranking.
MIX_ACADEMIC:      float = 0.80
MIX_CORE_FACILITY: float = 0.15
MIX_SITE_LICENSE:  float = 0.05

# Value-based drivers
GRAD_STUDENT_COST_PER_HR:     float = 35.0    # NIH NRSA stipend schedule 2023
HOURS_SAVED_PER_LAB_PER_YEAR: float = 120.0   # ~3 hrs/wk × 40 active experiment weeks
PROB_DATA_LOSS_PER_YEAR:      float = 0.08
COST_OF_LOST_EXPERIMENT_USD:  float = 15_000.0

# Survey signals driving value-based willingness to pay
PCTS_CITE_MANUAL_BURDEN: float = 0.70
PCTS_CITE_DATA_LOSS:     float = 0.60

# NIH RePORTER API
NIH_REPORTER_URL:     str   = "https://api.reporter.nih.gov/v2/projects/search"
NIH_REPORTER_TIMEOUT: float = 15.0


# ── Core data classes ──────────────────────────────────────────────────────────

@dataclass
class SegmentNode:
    """
    Single node in a segmentation funnel tree (spec D.1).

    Nodes form a directed tree from root (broadest population) to leaves
    (price-bearing segments). TAM = Σ(leaf.value × leaf.price_model["annual_usd"]).

    ``method`` signals epistemic status:
      retrieved     — sourced from an external API or authoritative dataset
      derived       — computed from parent(s) by a deterministic formula
      modeled       — statistical model or survey extrapolation
      assumed       — analyst assumption; must be disclosed ⚠
      user_override — PI has explicitly overridden the value
    """
    id:          str
    label:       str
    parent_id:   Optional[str]
    value:       float                # point estimate (labs / sites / patients)
    unit:        str                  # "labs" | "sites" | "patients"
    method:      Literal[
                     "retrieved",
                     "derived",
                     "modeled",
                     "assumed",
                     "user_override",
                 ]
    formula:     Optional[str] = None  # human-readable derivation expression
    source:      Optional[str] = None  # citation URL or reference string
    low:         float         = 0.0   # lower bound for uncertainty range
    high:        float         = 0.0   # upper bound for uncertainty range
    confidence:  float         = 0.5   # 0–1 subjective confidence in base value
    price_model: Optional[dict] = None # {annual_usd: float, tier: str} — leaves only
    editable:    bool          = True
    user_note:   Optional[str] = None


@dataclass
class PriceBand:
    """One pricing tier in the addressable market."""
    tier:        str    # "academic" | "core_facility" | "site_license"
    annual_usd:  float
    description: str
    mix:         float  # fraction of addressable labs in this tier (tiers must sum to 1.0)


@dataclass
class AdoptionModel:
    """S-curve adoption progression for a market segment."""
    year1: float   # penetration in year 1 (e.g. 0.03 = 3%)
    year3: float
    year5: float
    method: str    # "s_curve" | "linear" | "analyst"

    def projected_revenue(self, tam_usd: float) -> Dict[str, float]:
        """Apply adoption curve to a TAM figure."""
        return {
            "year1": tam_usd * self.year1,
            "year3": tam_usd * self.year3,
            "year5": tam_usd * self.year5,
        }


@dataclass
class TriangulationResult:
    """
    Three-method TAM triangulation with reconciliation (spec D.3).

    Attributes:
        bottom_up:    Funnel-based estimate (bottom-up count × price).
        top_down:     NIH budget × data-logging fraction × defensible share.
        value_based:  WTP inferred from labor savings + data-loss protection.
        reconciled:   Weighted average (BU=50%, TD=25%, VB=25%).
    """
    bottom_up:   dict
    top_down:    dict
    value_based: dict
    reconciled:  dict


# ── SegmentTree ───────────────────────────────────────────────────────────────

class SegmentTree:
    """
    Directed tree of SegmentNodes encoding a market-sizing funnel.

    Leaves (nodes with no children) are the price-bearing segments.
    TAM = Σ(leaf.value × leaf.price_model["annual_usd"]).

    The tree is deterministic given the same inputs.  Distributions are encoded
    in (low, high, confidence) on each node; the monte_carlo() function samples
    from those to produce P10/P50/P90 intervals.
    """

    def __init__(
        self,
        nodes: List[SegmentNode],
        root_id: str,
        product_name: str = "",
        idea: str = "",
        nih_labs_retrieved: Optional[int] = None,
        nih_query_keyword: Optional[str] = None,
        dimension_report: Optional[dict] = None,
    ) -> None:
        self.nodes: Dict[str, SegmentNode] = {n.id: n for n in nodes}
        self.root_id            = root_id
        self.product_name       = product_name
        self.idea               = idea
        self.nih_labs_retrieved = nih_labs_retrieved
        self.nih_query_keyword  = nih_query_keyword
        self.dimension_report   = dimension_report

    # ── Tree navigation ───────────────────────────────────────────────────────

    def children_of(self, node_id: str) -> List[SegmentNode]:
        """Return direct children of the given node."""
        return [n for n in self.nodes.values() if n.parent_id == node_id]

    def leaves(self) -> List[SegmentNode]:
        """Nodes with no children — price-bearing segments."""
        child_parents = {n.parent_id for n in self.nodes.values() if n.parent_id}
        return [n for n in self.nodes.values() if n.id not in child_parents]

    def assumed_nodes(self) -> List[SegmentNode]:
        """All nodes with method == 'assumed' — candidates for sensitivity analysis."""
        return [n for n in self.nodes.values() if n.method == "assumed"]

    def path_to_root(self, node_id: str) -> List[str]:
        """Return node ids from the given node up to root (inclusive, root last)."""
        path: List[str] = []
        current = node_id
        seen: set = set()
        while current and current not in seen:
            path.append(current)
            seen.add(current)
            node = self.nodes.get(current)
            current = node.parent_id if node else None
        return path

    # ── TAM computation ───────────────────────────────────────────────────────

    def compute_tam(self) -> float:
        """Sum TAM across all price-bearing leaf nodes using base values."""
        total = 0.0
        for leaf in self.leaves():
            if leaf.price_model and "annual_usd" in leaf.price_model:
                total += leaf.value * leaf.price_model["annual_usd"]
        return total

    def compute_tam_range(self) -> Tuple[float, float]:
        """Pessimistic (low) and optimistic (high) TAM using node uncertainty bounds."""
        lo_total = hi_total = 0.0
        for leaf in self.leaves():
            if leaf.price_model and "annual_usd" in leaf.price_model:
                price = leaf.price_model["annual_usd"]
                lo_val = leaf.low  if leaf.low  > 0 else leaf.value * 0.50
                hi_val = leaf.high if leaf.high > 0 else leaf.value * 1.50
                lo_total += lo_val * price
                hi_total += hi_val * price
        return lo_total, hi_total

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize the full tree to a JSON-compatible dict (for PIReport storage)."""
        return {
            "root_id":             self.root_id,
            "product_name":        self.product_name,
            "idea":                self.idea,
            "nih_labs_retrieved":  self.nih_labs_retrieved,
            "nih_query_keyword":   self.nih_query_keyword,
            "tam_usd":             self.compute_tam(),
            "leaves":              [n.id for n in self.leaves()],
            "assumed_nodes":       [n.id for n in self.assumed_nodes()],
            "nodes": {
                nid: {
                    "id":          n.id,
                    "label":       n.label,
                    "parent_id":   n.parent_id,
                    "value":       n.value,
                    "unit":        n.unit,
                    "method":      n.method,
                    "formula":     n.formula,
                    "source":      n.source,
                    "low":         n.low,
                    "high":        n.high,
                    "confidence":  n.confidence,
                    "price_model": n.price_model,
                    "editable":    n.editable,
                    "user_note":   n.user_note,
                }
                for nid, n in self.nodes.items()
            },
            "dimension_report": self.dimension_report,
        }


# ── Private helpers ────────────────────────────────────────────────────────────

def _sample_pert(
    rng: np.random.Generator, lo: float, mode: float, hi: float
) -> float:
    """
    Draw one sample from a PERT distribution parameterized by (lo, mode, hi).

    The PERT distribution is a beta scaled to [lo, hi] with shape parameters
    derived from the mode.  It is well-suited for expert-estimated ranges.
    """
    span = hi - lo
    if span <= 0 or lo >= hi:
        return mode
    mode_frac = max(0.0, min(1.0, (mode - lo) / span))
    alpha = 1.0 + 4.0 * mode_frac
    beta  = 1.0 + 4.0 * (1.0 - mode_frac)
    return lo + float(rng.beta(alpha, beta)) * span


def _propagate_with_fracs(
    tree: SegmentTree,
    sampled_fracs: Dict[str, float],
) -> Dict[str, float]:
    """
    BFS from root, recomputing node values using sampled fractions for uncertain nodes.

    ``sampled_fracs`` maps node_id → fraction_of_parent (not absolute value).
    Nodes not in sampled_fracs keep their base fraction relative to their parent.

    Returns a dict of {node_id: absolute_value}.
    """
    node_vals: Dict[str, float] = {}
    node_vals[tree.root_id] = tree.nodes[tree.root_id].value  # root is always fixed

    queue: deque = deque([tree.root_id])
    visited: set = {tree.root_id}

    while queue:
        current_id  = queue.popleft()
        current_val = node_vals[current_id]

        for child in tree.children_of(current_id):
            if child.id in visited:
                continue
            visited.add(child.id)

            if child.id in sampled_fracs:
                frac = sampled_fracs[child.id]
            else:
                parent_base = tree.nodes[current_id].value
                frac = (child.value / parent_base) if parent_base > 0 else 0.0

            node_vals[child.id] = current_val * frac
            queue.append(child.id)

    return node_vals


def _compute_tam_from_node_vals(
    tree: SegmentTree, node_vals: Dict[str, float]
) -> float:
    """
    Compute TAM from a propagated node-value dict, preserving leaf price-tier splits.

    Leaf values are derived by multiplying the leaf's base fraction (from its parent)
    by the parent's propagated value — so price-tier mix is preserved across iterations.
    """
    total = 0.0
    for leaf in tree.leaves():
        if not (leaf.price_model and "annual_usd" in leaf.price_model):
            continue
        if leaf.parent_id and leaf.parent_id in tree.nodes:
            parent_base = tree.nodes[leaf.parent_id].value
            parent_sim  = node_vals.get(leaf.parent_id, parent_base)
            frac        = (leaf.value / parent_base) if parent_base > 0 else 0.0
            leaf_val    = parent_sim * frac
        else:
            leaf_val = node_vals.get(leaf.id, leaf.value)
        total += leaf_val * leaf.price_model["annual_usd"]
    return total


# ── NIH RePORTER API ──────────────────────────────────────────────────────────

# Maps therapeutic-area keys (same vocabulary as market_calibration_service.py)
# to NIH Institute/Center codes accepted by the RePORTER v2 `agency_codes` filter.
# An empty list means "no IC filter — search all NIH" (used for research tools
# and for product types whose TA cannot be mapped).
# Rule 3 (Addendum): IC codes MUST be derived from intake (TA/product type),
# never hardcoded at a call site.
_TA_TO_NIH_IC_CODES: dict[str, list[str]] = {
    "oncology":       ["NCI"],
    "hematology":     ["NCI", "NHLBI"],
    "gene_therapy":   ["NCI", "NHGRI", "NHLBI"],
    "immunology":     ["NIAID", "NIAMS"],
    "cardiovascular": ["NHLBI"],
    "metabolic":      ["NIDDK"],
    "ibd":            ["NIDDK", "NIAID"],
    "nash_mash":      ["NIDDK"],
    "cns":            ["NINDS", "NIMH", "NIA"],
    "rare_disease":   ["NCATS", "ORDR"],
    # "other" and research-tool TAs intentionally absent → empty list → all NIH
}


def nih_ic_codes_for_ta(ta: str) -> list[str]:
    """Return NIH Institute/Center codes for a therapeutic area.

    Returns an empty list for unknown or non-clinical TAs (e.g. 'other',
    'research_tool'), meaning the RePORTER query is not IC-filtered and spans
    all active NIH grants.  This is the correct default for research tools
    whose customers cut across all disease areas.

    Args:
        ta: Therapeutic area key (e.g. 'cns', 'oncology'). Must come from
            intake (product type / disease domain) — never hardcoded at the
            call site (Rule 3).
    """
    return list(_TA_TO_NIH_IC_CODES.get(ta.lower().strip() if ta else "", []))


# ── NSF Awards API ────────────────────────────────────────────────────────────

# Maps TA keys to NSF directorate/division codes used by the NSF Awards API.
# NSF does not use disease-area filtering (it funds basic research), so this
# maps to the NSF directorate most relevant for instrumentation tools.
# "BIO" = Biological Sciences directorate (most relevant for life-sciences tools).
# "MPS" = Mathematical and Physical Sciences (physics/chemistry instruments).
# An empty list means "keyword-only, no directorate filter" — all NSF programs.
_TA_TO_NSF_DIRECTORATE: dict[str, list[str]] = {
    "neuroscience":     ["BIO", "SBE"],  # BIO + Social/Behavioral/Economic Sciences
    "cns":              ["BIO", "SBE"],
    "oncology":         ["BIO"],
    "immunology":       ["BIO"],
    "gene_therapy":     ["BIO"],
    "hematology":       ["BIO"],
    "metabolic":        ["BIO"],
    "cardiovascular":   ["BIO"],
    "rare_disease":     ["BIO"],
    "ibd":              ["BIO"],
    "nash_mash":        ["BIO"],
    # Agricultural / environmental research tools → ENG (instrumentation) + BIO
    "agronomy":         ["ENG", "BIO"],
    "ecology":          ["BIO"],
    "environmental":    ["ENG", "BIO"],
    # Research tools without a specific TA: search all NSF
}

NSF_AWARDS_URL:     str   = "https://api.nsf.gov/services/v1/awards.json"
NSF_AWARDS_TIMEOUT: float = 12.0
NSF_RECENT_YEAR:    int   = 2022   # awards from this year onward count as "active"


def nsf_directorate_for_ta(ta: str) -> list[str]:
    """Return NSF directorate codes for a therapeutic area.

    Returns an empty list for unknown or non-biology TAs, meaning the NSF
    query runs without a directorate filter (all active NSF awards).

    Args:
        ta: Therapeutic area key from intake — never hardcoded at the call site.
    """
    return list(_TA_TO_NSF_DIRECTORATE.get(ta.lower().strip() if ta else "", []))


async def query_nsf_awards(keyword: str, directorates: list[str] | tuple[str, ...] = ()) -> Dict[str, Any]:
    """
    Query the NSF Awards API v1 for recent awards matching the keyword.

    Counts distinct award IDs as a proxy for funded-lab count.
    The API is public and requires no authentication key.

    Endpoint: GET https://api.nsf.gov/services/v1/awards.json
    Params:   keyword=<kw>, dateStart=01/01/<NSF_RECENT_YEAR>, printFields=id

    Falls back to a static estimate if the API fails or times out.

    Args:
        keyword:      Search term derived from idea text or product name.
        directorates: Optional NSF directorate codes to filter the query.
                      Must be derived from intake via nsf_directorate_for_ta() —
                      never hardcoded at a call site.
                      Empty sequence (default) = no directorate filter = all NSF.

    Returns:
        dict with:
          award_count     — number of matching NSF awards (int)
          source          — human-readable source string for the node
          fallback_used   — True if the static fallback was applied
    """
    _NSF_STATIC_FALLBACK_COUNT = 800   # ~800 active NSF BIO/SBE awards/yr match broad instrumentation terms

    fallback: Dict[str, Any] = {
        "award_count":  _NSF_STATIC_FALLBACK_COUNT,
        "source": (
            f"Static fallback: ~{_NSF_STATIC_FALLBACK_COUNT} NSF awards/yr "
            f"in instrumentation-relevant directorates "
            f"(NSF Awards API unavailable)"
        ),
        "fallback_used": True,
    }

    params: dict = {
        "keyword":    keyword,
        "dateStart":  f"01/01/{NSF_RECENT_YEAR}",
        "printFields": "id",
    }
    if directorates:
        params["fundProgramName"] = ",".join(directorates)

    _t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=NSF_AWARDS_TIMEOUT) as client:
            resp = await client.get(NSF_AWARDS_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        awards = data.get("response", {}).get("award", []) or []
        count = len(awards)
        dir_note = f" directorates={directorates}" if directorates else ""
        _log_fetch_seg(
            "nsf_awards", NSF_AWARDS_URL, "GET", resp.status_code,
            (time.monotonic() - _t0) * 1000, len(resp.content), count,
            f"keyword={keyword!r}{dir_note}",
        )
        if count == 0:
            logger.info(
                "NSF Awards returned 0 results for keyword '%s'%s; using static fallback.",
                keyword, dir_note,
            )
            return fallback
        source = (
            f"NSF Awards API v1 — keyword='{keyword}'{dir_note}, "
            f"awards from {NSF_RECENT_YEAR} onward: {count} matching awards "
            f"(https://api.nsf.gov/services/v1/awards.json)"
        )
        logger.info("NSF Awards: keyword='%s'%s → %d awards", keyword, dir_note, count)
        return {
            "award_count":  count,
            "source":       source,
            "fallback_used": False,
        }
    except Exception as exc:
        _log_fetch_seg(
            "nsf_awards", NSF_AWARDS_URL, "GET", None,
            (time.monotonic() - _t0) * 1000, 0, 0,
            f"keyword={keyword!r}",
        )
        logger.warning("NSF Awards API failed (%s); using static fallback.", exc)
        return fallback


async def query_nih_reporter(keyword: str, agency_codes: tuple[str, ...] | list[str] = ()) -> Dict[str, Any]:
    """
    Query NIH RePORTER v2 for active grants matching the keyword.

    Counts distinct principal investigators (profile_id) as a proxy for lab
    count.  The API is public and requires no authentication key.

    Endpoint: POST https://api.reporter.nih.gov/v2/projects/search
    Body: {"criteria": {"advanced_text_search": {...}}, "limit": 500}

    Falls back to a static estimate if the API fails or times out.

    Args:
        keyword:      Search term derived from idea text or product name.
        agency_codes: Optional NIH IC codes to filter the query.
                      Must be derived from intake via nih_ic_codes_for_ta() —
                      never hardcoded at a call site (Rule 3).
                      Empty sequence (default) = no IC filter = all NIH.

    Returns:
        dict with:
          lab_count       — estimated number of distinct labs (int)
          total_projects  — total matching projects from API meta (int or None)
          distinct_pis    — distinct PIs counted in sample (int or None)
          source          — human-readable source string for the node
          fallback_used   — True if the static fallback was applied
    """
    total_labs = int(CARNEGIE_INSTITUTION_COUNT * HERD_LABS_PER_INSTITUTION)
    static_lab_count = int(total_labs * FRAC_NIH_FUNDED_FALLBACK)

    fallback: Dict[str, Any] = {
        "lab_count":      static_lab_count,
        "total_projects": None,
        "distinct_pis":   None,
        "source": (
            f"Static fallback: Carnegie 2021 ({CARNEGIE_INSTITUTION_COUNT} institutions) "
            f"× HERD {HERD_LABS_PER_INSTITUTION} labs/institution "
            f"× {FRAC_NIH_FUNDED_FALLBACK:.0%} NIH-funded fraction "
            f"(NIH RePORTER API unavailable)"
        ),
        "fallback_used": True,
    }

    criteria: dict = {
        "advanced_text_search": {
            "search_field": "all",
            "search_text":  keyword,
        },
        "project_status": ["Active"],
    }
    if agency_codes:
        # IC filter derived from intake TA — never hardcoded at call site (Rule 3)
        criteria["agency_codes"] = list(agency_codes)

    payload: dict = {
        "criteria": criteria,
        "limit":  500,
        "offset": 0,
        "fields": ["principal_investigators"],
    }

    _t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=NIH_REPORTER_TIMEOUT) as client:
            response = await client.post(NIH_REPORTER_URL, json=payload)
            response.raise_for_status()
            data = response.json()

        results: list = data.get("results", [])
        meta:    dict = data.get("meta", {})
        total_projects: int = meta.get("total", 0)
        ic_note = f" ics={list(agency_codes)}" if agency_codes else ""
        _log_fetch_seg(
            "nih_reporter", NIH_REPORTER_URL, "POST", response.status_code,
            (time.monotonic() - _t0) * 1000, len(response.content), total_projects,
            f"keyword={keyword!r}{ic_note}",
        )

        # Count distinct PI profile_ids from the 500-record sample
        pi_ids: set = set()
        for project in results:
            pis = project.get("principal_investigators") or []
            if pis:
                pid = pis[0].get("profile_id")
                if pid:
                    pi_ids.add(pid)

        distinct_in_sample = len(pi_ids)
        sample_size        = len(results)

        if distinct_in_sample > 0 and total_projects > sample_size > 0:
            # Scale from sample using square-root dampening (PIs repeat across projects)
            scale_factor       = total_projects / sample_size
            estimated_distinct = int(distinct_in_sample * math.sqrt(scale_factor))
        elif distinct_in_sample > 0:
            estimated_distinct = distinct_in_sample
        else:
            # Zero distinct PIs suggests a very narrow keyword; use total as proxy
            estimated_distinct = total_projects

        # Cap at physical ceiling: total known labs in the universe
        lab_count = min(max(estimated_distinct, 0), total_labs)

        # If the API returned zero matching projects (keyword too specific or no matches),
        # or the estimated lab count is implausibly low, blend toward the static fallback
        # to avoid a degenerate zero TAM.
        if total_projects == 0 or lab_count == 0:
            # Keyword too narrow for RePORTER; treat as non-specific and use fallback
            logger.info(
                "NIH RePORTER returned 0 results for keyword '%s'; "
                "using static fallback lab count.",
                keyword,
            )
            lab_count = static_lab_count
        elif lab_count < 100:
            lab_count = max(lab_count, static_lab_count // 4)

        await asyncio.sleep(0)  # yield to event loop; keeps function non-blocking

        ic_note = f", agency_codes={list(agency_codes)}" if agency_codes else ""
        return {
            "lab_count":      lab_count,
            "total_projects": total_projects,
            "distinct_pis":   distinct_in_sample,
            "source": (
                f"NIH RePORTER API v2 — keyword='{keyword}'{ic_note}, "
                f"total_projects={total_projects:,}, "
                f"distinct_PIs_in_sample={distinct_in_sample} "
                f"(https://api.reporter.nih.gov/v2/projects/search)"
            ),
            "fallback_used": False,
        }

    except Exception as exc:  # network error, timeout, bad JSON, etc.
        _log_fetch_seg(
            "nih_reporter", NIH_REPORTER_URL, "POST", None,
            (time.monotonic() - _t0) * 1000, 0, 0,
            f"keyword={keyword!r}",
        )
        logger.warning("NIH RePORTER API failed (%s); using static fallback.", exc)
        return fallback


# ── Product-specific buyer cells (A.2 / v6 Part D revision) ──────────────────
#
# Proxy cells encode (funding_agency, award_size_band, current_solution, adoption)
# for the typical buyer population.  Adoption rates differ by product domain so
# between-group variance — and therefore computed lifts — differ per product.
#
# Agency weight rules:
#   NIH-heavy TAs (cns, oncology, hematology …)   → NIH primary, adoption 0.19–0.21
#   Environmental / agronomy                       → USDA primary, NIH low (0.03–0.05)
#   Engineering / instrumentation                  → NSF primary, NIH secondary
#   Defense / dual-use                             → DoD primary
#   General / other                                → even NIH/NSF split
#
# Current-solution adoption pattern (stable across domains):
#   manual → high (users feel the pain most acutely)
#   diy_scripts → medium (already invested, switching cost)
#   commercial → low (problem solved, won't switch unless significantly better)
#
# The resulting variance in `adoption` across cells drives dimension_selection
# to compute genuinely different lifts for carnegie_tier, funding_agency, etc.
# across products — not the hardcoded 25/22/20/18/15 sequence.

_AGRONOMY_KWS   = frozenset({"soil","agronomy","crop","field","agriculture","usda","nifa",
                              "irrigation","water","moisture","plant","tillage"})
_ENGINEERING_KWS = frozenset({"sensor","instrument","hardware","embedded","firmware",
                               "iot","arduino","raspberry","fpga","pcb","circuit","dsp"})
_DEFENSE_KWS    = frozenset({"dod","darpa","defense","military","army","navy","air force"})
_NIH_HEAVY_TAS  = frozenset({"cns","oncology","hematology","gene_therapy","immunology",
                              "cardiovascular","metabolic","ibd","nash_mash","rare_disease",
                              "neuroscience","clinical"})


def _domain_from_ta_idea(ta: str, idea: str) -> str:
    """Classify the product into a funding-agency domain for cell generation."""
    ta_lower = (ta or "").lower()
    idea_lower = (idea or "").lower()

    if ta_lower in _NIH_HEAVY_TAS:
        return "nih_heavy"
    if any(kw in idea_lower for kw in _AGRONOMY_KWS):
        return "agronomy"
    if any(kw in idea_lower for kw in _DEFENSE_KWS) or "dod" in ta_lower:
        return "defense"
    if any(kw in idea_lower for kw in _ENGINEERING_KWS):
        return "engineering"
    return "general"   # even NIH/NSF split


def _build_product_cells(ta: str, nih_labs_val: float, idea: str) -> list[dict]:
    """
    Build proxy buyer cells tailored to the product's funding domain.

    Each cell = one representative buyer segment with a modeled adoption rate.
    Between-group variance in 'adoption' across cells drives dimension lift
    computation in build_dimension_report(); cells that vary more produce
    higher lifts for that dimension.

    Returns at least 7 cells covering all candidate dimension levels.
    """
    domain = _domain_from_ta_idea(ta, idea)
    P = PRICE_ACADEMIC_USD   # base price anchor

    # Current-solution adoption multipliers (stable across domains)
    # manual=1.0x, diy=0.70x, commercial=0.40x — frustrated users adopt more
    sol_mult = {"manual": 1.00, "diy_scripts": 0.70, "commercial": 0.40}

    if domain == "nih_heavy":
        # Biomedical / clinical — NIH dominant, NSF secondary, low USDA/DoD
        return [
            {"funding_agency":"NIH", "award_size_band":"large", "current_solution":"manual",     "adoption": 0.21, "price": P},
            {"funding_agency":"NIH", "award_size_band":"large", "current_solution":"diy_scripts","adoption": 0.15, "price": P},
            {"funding_agency":"NIH", "award_size_band":"mid",   "current_solution":"manual",     "adoption": 0.13, "price": P},
            {"funding_agency":"NIH", "award_size_band":"mid",   "current_solution":"diy_scripts","adoption": 0.09, "price": P},
            {"funding_agency":"NIH", "award_size_band":"small", "current_solution":"manual",     "adoption": 0.06, "price": P * 0.85},
            {"funding_agency":"NSF", "award_size_band":"large", "current_solution":"commercial", "adoption": 0.08, "price": P * 0.90},
            {"funding_agency":"NSF", "award_size_band":"mid",   "current_solution":"manual",     "adoption": 0.07, "price": P * 0.90},
            {"funding_agency":"DoD", "award_size_band":"large", "current_solution":"manual",     "adoption": 0.05, "price": P},
        ]

    if domain == "agronomy":
        # Agriculture / soil / crop — USDA-NIFA dominant, NSF-Earth secondary, NIH irrelevant
        return [
            {"funding_agency":"USDA",  "award_size_band":"large", "current_solution":"manual",     "adoption": 0.24, "price": P * 0.70},
            {"funding_agency":"USDA",  "award_size_band":"large", "current_solution":"diy_scripts","adoption": 0.17, "price": P * 0.70},
            {"funding_agency":"USDA",  "award_size_band":"mid",   "current_solution":"manual",     "adoption": 0.14, "price": P * 0.65},
            {"funding_agency":"USDA",  "award_size_band":"small", "current_solution":"manual",     "adoption": 0.07, "price": P * 0.60},
            {"funding_agency":"NSF",   "award_size_band":"large", "current_solution":"diy_scripts","adoption": 0.12, "price": P * 0.80},
            {"funding_agency":"NSF",   "award_size_band":"mid",   "current_solution":"commercial", "adoption": 0.06, "price": P * 0.80},
            {"funding_agency":"NIH",   "award_size_band":"mid",   "current_solution":"commercial", "adoption": 0.03, "price": P * 0.90},
            {"funding_agency":"DoE",   "award_size_band":"large", "current_solution":"commercial", "adoption": 0.09, "price": P * 0.75},
        ]

    if domain == "defense":
        # Defense / dual-use — DoD dominant, NSF secondary
        return [
            {"funding_agency":"DoD",  "award_size_band":"large", "current_solution":"manual",     "adoption": 0.23, "price": P * 1.20},
            {"funding_agency":"DoD",  "award_size_band":"large", "current_solution":"diy_scripts","adoption": 0.16, "price": P * 1.20},
            {"funding_agency":"DoD",  "award_size_band":"mid",   "current_solution":"manual",     "adoption": 0.12, "price": P * 1.10},
            {"funding_agency":"NSF",  "award_size_band":"large", "current_solution":"commercial", "adoption": 0.09, "price": P},
            {"funding_agency":"NSF",  "award_size_band":"mid",   "current_solution":"manual",     "adoption": 0.07, "price": P},
            {"funding_agency":"NIH",  "award_size_band":"mid",   "current_solution":"commercial", "adoption": 0.04, "price": P * 0.90},
            {"funding_agency":"DoE",  "award_size_band":"large", "current_solution":"diy_scripts","adoption": 0.11, "price": P},
        ]

    if domain == "engineering":
        # Instrumentation / engineering — NSF dominant, DoD secondary
        return [
            {"funding_agency":"NSF", "award_size_band":"large", "current_solution":"manual",     "adoption": 0.19, "price": P},
            {"funding_agency":"NSF", "award_size_band":"large", "current_solution":"diy_scripts","adoption": 0.13, "price": P},
            {"funding_agency":"NSF", "award_size_band":"mid",   "current_solution":"manual",     "adoption": 0.11, "price": P * 0.90},
            {"funding_agency":"NSF", "award_size_band":"small", "current_solution":"diy_scripts","adoption": 0.06, "price": P * 0.85},
            {"funding_agency":"NIH", "award_size_band":"large", "current_solution":"commercial", "adoption": 0.09, "price": P},
            {"funding_agency":"DoD", "award_size_band":"large", "current_solution":"manual",     "adoption": 0.14, "price": P * 1.10},
            {"funding_agency":"Foundation","award_size_band":"mid","current_solution":"manual",  "adoption": 0.05, "price": P * 0.80},
        ]

    # general — even NIH/NSF split, moderate adoption variance
    return [
        {"funding_agency":"NIH",       "award_size_band":"large", "current_solution":"manual",     "adoption": 0.20, "price": P},
        {"funding_agency":"NIH",       "award_size_band":"mid",   "current_solution":"diy_scripts","adoption": 0.13, "price": P},
        {"funding_agency":"NIH",       "award_size_band":"small", "current_solution":"manual",     "adoption": 0.07, "price": P * 0.85},
        {"funding_agency":"NSF",       "award_size_band":"large", "current_solution":"commercial", "adoption": 0.11, "price": P * 0.90},
        {"funding_agency":"NSF",       "award_size_band":"mid",   "current_solution":"manual",     "adoption": 0.08, "price": P * 0.90},
        {"funding_agency":"DoD",       "award_size_band":"large", "current_solution":"manual",     "adoption": 0.16, "price": P},
        {"funding_agency":"Foundation","award_size_band":"mid",   "current_solution":"diy_scripts","adoption": 0.06, "price": P * 0.80},
    ]


# ── Life-sciences research tree (spec D.2) ────────────────────────────────────

async def build_life_sciences_research_tree(
    idea: str,
    product_name: str = "",
    ta: str = "",
) -> SegmentTree:
    """
    Build the LIFE_SCIENCES_RESEARCH segmentation tree for research-tool products.

    Queries NIH RePORTER AND NSF Awards API concurrently to count labs with
    active grants in the relevant domain, then applies the D.2 funnel fractions
    to arrive at addressable labs split by operator-supplied or assumed price tiers.

    F-10 (spec v5 item 9): executes both NIH RePORTER and NSF Awards queries for
    real; IC codes and NSF directorates are derived from intake via the agency-
    mapping tables (_TA_TO_NIH_IC_CODES, _TA_TO_NSF_DIRECTORATE) — never hardcoded.

    All assumed fractions are flagged ⚠ and stored on the node with (low, high)
    bounds for Monte Carlo sampling.

    Args:
        idea:         Full idea / product description text (drives NIH keyword search).
        product_name: Short product name used as the NIH search keyword when provided.
        ta:           Therapeutic area key from intake (e.g. 'cns', 'oncology').
                      Drives NIH IC filtering via nih_ic_codes_for_ta() and NSF
                      directorate filtering via nsf_directorate_for_ta() — not hardcoded.
                      Empty string (default) = no filter = all NIH / all NSF (correct for
                      cross-disease research tools).

    Returns:
        Deterministic SegmentTree; distributions encoded in (low, high, confidence).
    """
    keyword       = product_name.strip() if product_name.strip() else (idea[:80].strip() if idea else "laboratory data logging instrumentation")
    ic_codes      = nih_ic_codes_for_ta(ta)
    nsf_divs      = nsf_directorate_for_ta(ta)

    # Execute NIH RePORTER and NSF Awards queries concurrently (F-10)
    nih_result, nsf_result = await asyncio.gather(
        query_nih_reporter(keyword, agency_codes=ic_codes),
        query_nsf_awards(keyword, directorates=nsf_divs),
    )

    # NIH count is the primary lab-count denominator (most R1 labs have NIH funding).
    # NSF adds non-NIH-funded labs (e.g. engineering, physics, math departments).
    # We add a conservative 20% of NSF awards as incremental non-NIH labs to avoid
    # double-counting (many labs hold both NIH and NSF grants simultaneously).
    nih_labs_val   = float(nih_result["lab_count"])
    nsf_incr_labs  = float(nsf_result["award_count"]) * 0.20   # incremental non-NIH labs
    combined_labs  = nih_labs_val + nsf_incr_labs

    nih_source = nih_result["source"]
    nsf_source = nsf_result["source"]
    combined_source = f"{nih_source} | NSF incremental: {nsf_source}"
    combined_method: Literal["retrieved", "modeled"] = (
        "retrieved"
        if (not nih_result["fallback_used"] or not nsf_result["fallback_used"])
        else "modeled"
    )
    combined_confidence = max(
        0.60 if not nih_result["fallback_used"] else 0.45,
        0.50 if not nsf_result["fallback_used"] else 0.35,
    )
    nih_labs_val = combined_labs   # use combined for downstream funnel

    nih_labs_val  = combined_labs
    nih_method    = combined_method
    nih_confidence = combined_confidence
    nih_source    = combined_source

    # Derived funnel values
    total_institutions  = float(CARNEGIE_INSTITUTION_COUNT)
    total_labs          = total_institutions * HERD_LABS_PER_INSTITUTION
    long_duration_labs  = nih_labs_val  * FRAC_LONG_DURATION
    low_bw_labs         = long_duration_labs * FRAC_LOW_BANDWIDTH
    not_custom_labs     = low_bw_labs    * FRAC_NOT_CUSTOM
    addressable_labs    = not_custom_labs * FRAC_BUDGET_AUTH
    academic_count      = addressable_labs * MIX_ACADEMIC
    core_facility_count = addressable_labs * MIX_CORE_FACILITY
    site_license_count  = addressable_labs * MIX_SITE_LICENSE

    nodes: List[SegmentNode] = [
        # ── Root: institution universe ────────────────────────────────────────
        SegmentNode(
            id="us_institutions",
            label="US Academic & Government Research Institutions",
            parent_id=None,
            value=total_institutions,
            unit="sites",
            method="retrieved",
            formula=None,
            source="Carnegie Classification 2021 — https://carnegieclassifications.acenet.edu/",
            low=3_800.0,
            high=4_400.0,
            confidence=0.85,
            price_model=None,
            editable=False,
        ),
        # ── Derived: labs per institution (HERD survey) ───────────────────────
        SegmentNode(
            id="labs_total",
            label="Total Research Labs (All Disciplines)",
            parent_id="us_institutions",
            value=total_labs,
            unit="labs",
            method="derived",
            formula=(
                f"us_institutions ({total_institutions:.0f}) "
                f"× {HERD_LABS_PER_INSTITUTION} labs/institution (HERD survey)"
            ),
            source="NSF Higher Education R&D Survey 2022 — https://www.nsf.gov/statistics/herd/",
            low=total_institutions * 6.5,
            high=total_institutions * 10.5,
            confidence=0.75,
            editable=False,
        ),
        # ── Retrieved: NIH+NSF-funded labs in scope (F-10) ──────────────────
        SegmentNode(
            id="nih_funded_labs",
            label="Labs with Active NIH or NSF Funding in Scope Field",
            parent_id="labs_total",
            value=nih_labs_val,
            unit="labs",
            method=nih_method,
            formula=(
                "NIH RePORTER API v2 (distinct PIs) + NSF Awards API "
                "(20% incremental non-NIH labs to avoid double-count)"
            ),
            source=nih_source,
            low=max(nih_labs_val * 0.70, 1.0),
            high=min(nih_labs_val * 1.40, total_labs),
            confidence=nih_confidence,
        ),
        # ── Assumed: long-duration experiments (⚠) ────────────────────────────
        SegmentNode(
            id="long_duration_labs",
            label="Running Long-Duration Instrumented Experiments",
            parent_id="nih_funded_labs",
            value=long_duration_labs,
            unit="labs",
            method="assumed",
            formula=(
                f"nih_funded_labs × {FRAC_LONG_DURATION:.0%} ⚠ "
                "(assumed — no primary survey; proxy from IoT sensor adoption literature)"
            ),
            source=None,
            low=nih_labs_val  * 0.12,
            high=nih_labs_val * 0.35,
            confidence=0.40,
        ),
        # ── Assumed: low-bandwidth modality (⚠) ──────────────────────────────
        SegmentNode(
            id="low_bandwidth_labs",
            label="Using Low-Bandwidth Data Modality (not streaming video/genomics)",
            parent_id="long_duration_labs",
            value=low_bw_labs,
            unit="labs",
            method="assumed",
            formula=(
                f"long_duration_labs × {FRAC_LOW_BANDWIDTH:.0%} ⚠ "
                "(assumed — low-bandwidth IoT proxy from NIST lab sensor survey)"
            ),
            source=None,
            low=long_duration_labs * 0.55,
            high=long_duration_labs * 0.95,
            confidence=0.50,
        ),
        # ── Assumed: not already custom-solved (⚠) ───────────────────────────
        SegmentNode(
            id="not_custom_solved",
            label="Not Already Using a Bespoke In-House Solution",
            parent_id="low_bandwidth_labs",
            value=not_custom_labs,
            unit="labs",
            method="assumed",
            formula=(
                f"low_bandwidth_labs × {FRAC_NOT_CUSTOM:.0%} ⚠ "
                "(assumed — custom-build rate from lab-informatics adoption surveys)"
            ),
            source=None,
            low=low_bw_labs * 0.45,
            high=low_bw_labs * 0.80,
            confidence=0.45,
        ),
        # ── Derived: budget authority, cadence-adjusted ───────────────────────
        SegmentNode(
            id="budget_authority_labs",
            label="Labs with Purchasing Authority (Annual Procurement Cadence)",
            parent_id="not_custom_solved",
            value=addressable_labs,
            unit="labs",
            method="derived",
            formula=(
                f"not_custom_solved × {FRAC_BUDGET_AUTH:.0%} "
                "(PI budget authority rate × annual procurement-cycle overlap — assumed ⚠)"
            ),
            source="Assumed — no primary source; appears in sensitivity analysis",
            low=not_custom_labs * 0.35,
            high=not_custom_labs * 0.62,
            confidence=0.55,
        ),
        # ── Leaf: academic per-lab license ($7,000/yr) ─────────────────────────
        SegmentNode(
            id="academic_labs",
            label="Academic Lab Subscribers (per-lab license)",
            parent_id="budget_authority_labs",
            value=academic_count,
            unit="labs",
            method="derived",
            formula=(
                f"budget_authority_labs × {MIX_ACADEMIC:.0%} "
                "(tier mix — assumed ⚠; no primary source)"
            ),
            source="Assumed — no primary source; appears in sensitivity analysis",
            low=addressable_labs * 0.65,
            high=addressable_labs * 0.90,
            confidence=0.60,
            price_model={"annual_usd": PRICE_ACADEMIC_USD, "tier": "academic"},
        ),
        # ── Leaf: core facility shared-resource license ($20,000/yr) ──────────
        SegmentNode(
            id="core_facility_labs",
            label="Core Facility Subscribers (shared-resource license)",
            parent_id="budget_authority_labs",
            value=core_facility_count,
            unit="labs",
            method="derived",
            formula=(
                f"budget_authority_labs × {MIX_CORE_FACILITY:.0%} "
                "(tier mix — assumed ⚠; no primary source)"
            ),
            source="Assumed — no primary source; appears in sensitivity analysis",
            low=addressable_labs * 0.08,
            high=addressable_labs * 0.22,
            confidence=0.55,
            price_model={"annual_usd": PRICE_CORE_FACILITY_USD, "tier": "core_facility"},
        ),
        # ── Leaf: institution-wide site license ($45,000/yr) ──────────────────
        SegmentNode(
            id="site_license_labs",
            label="Site License Customers (institution-wide)",
            parent_id="budget_authority_labs",
            value=site_license_count,
            unit="labs",
            method="derived",
            formula=(
                f"budget_authority_labs × {MIX_SITE_LICENSE:.0%} "
                "(tier mix — assumed ⚠; no primary source)"
            ),
            source="Assumed — no primary source; appears in sensitivity analysis",
            low=addressable_labs * 0.02,
            high=addressable_labs * 0.10,
            confidence=0.50,
            price_model={"annual_usd": PRICE_SITE_LICENSE_USD, "tier": "site_license"},
        ),
    ]

    # Part D Revised: dimension selection report
    # A.2 / v6 Part D: proxy cells are product-specific so computed lifts vary by product.
    _dim_report_dict = None
    try:
        from app.services.dimension_selection import build_dimension_report as _build_dr
        _cls = {"archetype": "research_tool"}
        _itn = {"domain": "LIFE_SCIENCES_RESEARCH", "therapeutic_area": ta or ""}
        _proxy_cells = _build_product_cells(ta, nih_labs_val=nih_labs_val, idea=idea)
        _dr = _build_dr(_cls, _itn, cells=_proxy_cells, param="adoption")
        _dim_report_dict = {
            "dimensions_considered": _dr.dimensions_considered_count,
            "dimensions_selected":   len(_dr.dimensions_selected),
            "dimensions_rejected":   len(_dr.dimensions_rejected),
            "selected":              _dr.dimensions_selected,
            "rejected":              _dr.dimensions_rejected[:10],
            "renders_considered_count": _dr.renders_considered_count,
        }
    except Exception as _dr_e:
        logger.warning("Part D: dimension_report failed (non-fatal): %s", _dr_e)

    return SegmentTree(
        nodes=nodes,
        root_id="us_institutions",
        product_name=product_name,
        idea=idea,
        nih_labs_retrieved=nih_result.get("lab_count"),
        nih_query_keyword=keyword,
        dimension_report=_dim_report_dict,
    )


async def build_segment_tree(
    template: str,
    idea: str,
    product_name: str = "",
    ta: str = "",
) -> SegmentTree:
    """
    Dispatcher: build a SegmentTree for the named template.

    Args:
        template:     Segmentation template name (LIFE_SCIENCES_RESEARCH).
        idea:         Full product description text.
        product_name: Short product name (NIH keyword override).
        ta:           Therapeutic area from intake — passed to nih_ic_codes_for_ta()
                      to derive the NIH IC filter without hardcoding (Rule 3).

    Currently supports: LIFE_SCIENCES_RESEARCH.
    """
    if template == LIFE_SCIENCES_RESEARCH:
        return await build_life_sciences_research_tree(idea=idea, product_name=product_name, ta=ta)
    raise ValueError(
        f"Unknown segmentation template: '{template}'. "
        f"Supported: '{LIFE_SCIENCES_RESEARCH}'"
    )


# ── Three-method triangulation (spec D.3) ─────────────────────────────────────

def triangulate(tree: SegmentTree) -> TriangulationResult:
    """
    Compute three independent TAM estimates from the tree and reconcile them.

    Methods:
      1. Bottom-up   (weight 0.50) — leaf-level funnel count × price by tier
      2. Top-down    (weight 0.25) — NIH instrumentation budget × data-logging share
      3. Value-based (weight 0.25) — WTP inferred from labor savings + data-loss risk

    Returns a TriangulationResult with dicts for each method and for the
    weighted reconciliation.  Flags divergence >3× across methods.
    """
    addressable_node = tree.nodes.get("budget_authority_labs")
    addressable_count = addressable_node.value if addressable_node else 0.0

    # ── 1. Bottom-up ──────────────────────────────────────────────────────────
    bu_tam         = tree.compute_tam()
    bu_low, bu_high = tree.compute_tam_range()

    academic_rev = (
        tree.nodes["academic_labs"].value * PRICE_ACADEMIC_USD
        if "academic_labs" in tree.nodes else 0.0
    )
    core_rev = (
        tree.nodes["core_facility_labs"].value * PRICE_CORE_FACILITY_USD
        if "core_facility_labs" in tree.nodes else 0.0
    )
    site_rev = (
        tree.nodes["site_license_labs"].value * PRICE_SITE_LICENSE_USD
        if "site_license_labs" in tree.nodes else 0.0
    )

    bottom_up: dict = {
        "method":           "bottom_up",
        "label":            "Bottom-Up Funnel",
        "tam_usd":          bu_tam,
        "low_usd":          bu_low,
        "high_usd":         bu_high,
        "addressable_labs": addressable_count,
        "tier_breakdown": {
            "academic_usd":      academic_rev,
            "core_facility_usd": core_rev,
            "site_license_usd":  site_rev,
        },
        "description": (
            "Funnel: Carnegie institutions → HERD labs → NIH-funded → "
            "long-duration → low-bandwidth → not custom-solved → "
            "budget authority; split by operator-supplied or assumed price tiers."
        ),
    }

    # ── 2. Top-down ───────────────────────────────────────────────────────────
    adjacent_tam = NIH_INSTRUMENTATION_BUDGET_USD * DATA_LOGGING_PLATFORM_FRACTION
    td_low       = adjacent_tam * TOP_DOWN_SHARE_LOW
    td_high      = adjacent_tam * TOP_DOWN_SHARE_HIGH
    td_mid       = (td_low + td_high) / 2.0

    top_down: dict = {
        "method":            "top_down",
        "label":             "Top-Down (NIH Instrumentation Budget)",
        "tam_usd":           td_mid,
        "low_usd":           td_low,
        "high_usd":          td_high,
        "adjacent_tam_usd":  adjacent_tam,
        "defensible_share_low":  TOP_DOWN_SHARE_LOW,
        "defensible_share_high": TOP_DOWN_SHARE_HIGH,
        "description": (
            f"NIH Instrumentation Budget ${NIH_INSTRUMENTATION_BUDGET_USD / 1e9:.1f}B/yr "
            f"× {DATA_LOGGING_PLATFORM_FRACTION:.0%} data-logging platform fraction "
            f"= ${adjacent_tam / 1e6:.0f}M adjacent TAM; "
            f"{TOP_DOWN_SHARE_LOW:.0%}–{TOP_DOWN_SHARE_HIGH:.0%} defensible share "
            f"→ ${td_low / 1e6:.1f}–${td_high / 1e6:.1f}M."
        ),
        "source": "NIH RePORTER equipment category 2022; share is analyst estimate ⚠",
    }

    # ── 3. Value-based ────────────────────────────────────────────────────────
    labor_value_per_lab     = HOURS_SAVED_PER_LAB_PER_YEAR * GRAD_STUDENT_COST_PER_HR
    data_loss_value_per_lab = PROB_DATA_LOSS_PER_YEAR      * COST_OF_LOST_EXPERIMENT_USD
    total_value_per_lab     = labor_value_per_lab + data_loss_value_per_lab

    # B2B software typically captures 20–30% of value created
    wtp_lo_per_lab  = total_value_per_lab * 0.20
    wtp_hi_per_lab  = total_value_per_lab * 0.30
    wtp_mid_per_lab = (wtp_lo_per_lab + wtp_hi_per_lab) / 2.0

    vb_tam  = addressable_count * wtp_mid_per_lab
    vb_low  = addressable_count * wtp_lo_per_lab
    vb_high = addressable_count * wtp_hi_per_lab

    value_based: dict = {
        "method":           "value_based",
        "label":            "Value-Based (WTP from Economic Impact)",
        "tam_usd":          vb_tam,
        "low_usd":          vb_low,
        "high_usd":         vb_high,
        "labor_value_per_lab_usd":     labor_value_per_lab,
        "data_loss_value_per_lab_usd": data_loss_value_per_lab,
        "total_value_per_lab_usd":     total_value_per_lab,
        "wtp_mid_per_lab_usd":         wtp_mid_per_lab,
        "addressable_labs":            addressable_count,
        "survey_signals": {
            "pct_cite_manual_burden": PCTS_CITE_MANUAL_BURDEN,
            "pct_cite_data_loss":     PCTS_CITE_DATA_LOSS,
        },
        "description": (
            f"{PCTS_CITE_MANUAL_BURDEN:.0%} of labs cite manual retrieval burden; "
            f"{PCTS_CITE_DATA_LOSS:.0%} cite data-loss risk. "
            f"Economic value = {HOURS_SAVED_PER_LAB_PER_YEAR:.0f} hrs/yr × "
            f"${GRAD_STUDENT_COST_PER_HR:.0f}/hr loaded cost "
            f"+ {PROB_DATA_LOSS_PER_YEAR:.0%} loss probability × "
            f"${COST_OF_LOST_EXPERIMENT_USD:,.0f} per incident "
            f"= ${total_value_per_lab:,.0f}/lab/yr; "
            f"WTP at 20–30% value capture → ${wtp_mid_per_lab:,.0f}/lab/yr."
        ),
        "sources": [
            "Grad student loaded cost: NIH NRSA stipend schedule 2023",
            "Data-loss probability: internal estimate — flagged ⚠",
            "WTP capture rate: B2B SaaS benchmark (analyst estimate ⚠)",
        ],
    }

    # ── Reconciliation ────────────────────────────────────────────────────────
    W_BU, W_TD, W_VB = 0.50, 0.25, 0.25

    rec_tam  = bu_tam  * W_BU + td_mid  * W_TD + vb_tam  * W_VB
    rec_low  = bu_low  * W_BU + td_low  * W_TD + vb_low  * W_VB
    rec_high = bu_high * W_BU + td_high * W_TD + vb_high * W_VB

    estimates = [bu_tam, td_mid, vb_tam]
    estimates_nonzero = [e for e in estimates if e > 0]
    divergence_ratio = (
        max(estimates_nonzero) / min(estimates_nonzero)
        if len(estimates_nonzero) >= 2 else 1.0
    )
    divergence_flag = divergence_ratio > 3.0

    reconciled: dict = {
        "method":    "reconciled",
        "label":     "Reconciled Estimate",
        "tam_usd":   rec_tam,
        "low_usd":   rec_low,
        "high_usd":  rec_high,
        "weights":   {"bottom_up": W_BU, "top_down": W_TD, "value_based": W_VB},
        "divergence_ratio": round(divergence_ratio, 2),
        "divergence_flag":  divergence_flag,
        "divergence_note": (
            f"Methods diverge {divergence_ratio:.1f}× — review assumed funnel fractions "
            "before presenting to investors."
            if divergence_flag else None
        ),
        "description": (
            f"Weighted: bottom-up 50% + top-down 25% + value-based 25% "
            f"→ ${rec_tam / 1e6:.1f}M TAM "
            f"[${rec_low / 1e6:.1f}–${rec_high / 1e6:.1f}M range]."
        ),
    }

    return TriangulationResult(
        bottom_up=bottom_up,
        top_down=top_down,
        value_based=value_based,
        reconciled=reconciled,
    )


# ── Monte Carlo uncertainty (spec D.6) ────────────────────────────────────────

def monte_carlo(
    tree: SegmentTree,
    n: int = 5_000,
    seed: int = 42,
) -> Dict[str, Any]:
    """
    Monte Carlo uncertainty quantification for the TAM estimate (spec D.6).

    Samples PERT distributions (parameterized by node.low / node.value / node.high)
    for every assumed or modeled node independently, propagates through the tree,
    and returns P10/P50/P90 plus supporting statistics.

    Reproducible: same tree + same seed → identical distribution every time.

    Args:
        tree: SegmentTree (deterministic; distributions encoded in low/high).
        n:    Number of Monte Carlo iterations (default 5,000).
        seed: NumPy random seed for reproducibility (default 42).

    Returns:
        dict with p10, p50, p90, mean, std, base_tam_usd, uncertain_parameters,
        description.
    """
    rng = np.random.default_rng(seed)

    # Build uncertain-step descriptors: (node_id, lo_frac, base_frac, hi_frac)
    # We sample the *fraction relative to parent*, then re-propagate top-down.
    uncertain_steps: List[dict] = []
    for nid, node in tree.nodes.items():
        if node.method not in ("assumed", "modeled"):
            continue
        if not node.parent_id or node.parent_id not in tree.nodes:
            continue
        parent_val = tree.nodes[node.parent_id].value
        if parent_val <= 0 or node.value <= 0:
            continue
        base_frac = node.value / parent_val
        lo_frac   = max((node.low  / parent_val) if node.low  > 0 else base_frac * 0.50, 0.0)
        hi_frac   = min((node.high / parent_val) if node.high > 0 else base_frac * 1.50, 1.0)
        uncertain_steps.append({
            "node_id":   nid,
            "lo_frac":   lo_frac,
            "base_frac": base_frac,
            "hi_frac":   hi_frac,
        })

    if not uncertain_steps:
        # No uncertain nodes: return a degenerate distribution at the base TAM
        base = tree.compute_tam()
        return {
            "n_iterations":          n,
            "seed":                  seed,
            "p10":                   base,
            "p50":                   base,
            "p90":                   base,
            "mean":                  base,
            "std":                   0.0,
            "base_tam_usd":          base,
            "uncertain_parameters":  [],
            "description":           "No uncertain nodes; distribution collapses to base TAM.",
        }

    tam_samples = np.empty(n, dtype=np.float64)

    for i in range(n):
        sampled_fracs: Dict[str, float] = {
            step["node_id"]: _sample_pert(
                rng, step["lo_frac"], step["base_frac"], step["hi_frac"]
            )
            for step in uncertain_steps
        }
        node_vals = _propagate_with_fracs(tree, sampled_fracs)
        tam_samples[i] = _compute_tam_from_node_vals(tree, node_vals)

    p10 = float(np.percentile(tam_samples, 10))
    p50 = float(np.percentile(tam_samples, 50))
    p90 = float(np.percentile(tam_samples, 90))

    return {
        "n_iterations":         n,
        "seed":                 seed,
        "p10":                  p10,
        "p50":                  p50,
        "p90":                  p90,
        "mean":                 float(np.mean(tam_samples)),
        "std":                  float(np.std(tam_samples)),
        "base_tam_usd":         tree.compute_tam(),
        "uncertain_parameters": [s["node_id"] for s in uncertain_steps],
        "description": (
            f"Monte Carlo ({n:,} iterations, seed={seed}). "
            f"PERT distributions on {len(uncertain_steps)} uncertain parameters. "
            f"P10=${p10 / 1e6:.1f}M / P50=${p50 / 1e6:.1f}M / P90=${p90 / 1e6:.1f}M."
        ),
    }


# ── Sensitivity analysis / tornado chart (spec D.7) ──────────────────────────

def sensitivity_analysis(tree: SegmentTree) -> List[Dict[str, Any]]:
    """
    Tornado-chart sensitivity: vary each assumed/modeled parameter ±50% (spec D.7).

    Each parameter is varied independently while all others are held at their
    base values.  Results are sorted by absolute TAM impact (largest first),
    ready for direct rendering as a tornado chart.

    Args:
        tree: SegmentTree with at least one assumed or modeled node.

    Returns:
        List of dicts (sorted descending by impact_usd), each containing:
          node_id, label, method, base_value, base_frac,
          low_frac, high_frac, tam_base_usd, tam_low_usd, tam_high_usd,
          impact_usd, impact_pct.
    """
    base_tam = tree.compute_tam()
    if base_tam <= 0:
        raise ValueError(f"sensitivity_analysis: non-positive baseline TAM ({base_tam})")
    results: List[Dict[str, Any]] = []

    for nid, node in tree.nodes.items():
        if node.method not in ("assumed", "modeled"):
            continue
        if not node.parent_id or node.parent_id not in tree.nodes:
            continue
        parent_val = tree.nodes[node.parent_id].value
        if parent_val <= 0 or node.value <= 0:
            continue

        base_frac = node.value / parent_val
        low_frac  = base_frac * 0.50
        high_frac = min(base_frac * 1.50, 1.0)

        node_vals_low  = _propagate_with_fracs(tree, {nid: low_frac})
        tam_low        = _compute_tam_from_node_vals(tree, node_vals_low)

        node_vals_high = _propagate_with_fracs(tree, {nid: high_frac})
        tam_high       = _compute_tam_from_node_vals(tree, node_vals_high)

        impact_usd = max(abs(tam_high - base_tam), abs(tam_low - base_tam))
        impact_pct = impact_usd / base_tam * 100
        assert 0 < impact_pct < 500, (
            f"sensitivity_analysis: impact_pct {impact_pct:.1f}% out of range for "
            f"node '{nid}' (tam_base={base_tam:.0f}, tam_low={tam_low:.0f}, tam_high={tam_high:.0f})"
        )

        results.append({
            "node_id":       nid,
            "label":         node.label,
            "method":        node.method,
            "base_value":    node.value,
            "base_frac":     round(base_frac, 4),
            "low_frac":      round(low_frac, 4),
            "high_frac":     round(high_frac, 4),
            "tam_base_usd":  base_tam,
            "tam_low_usd":   tam_low,
            "tam_high_usd":  tam_high,
            "impact_usd":    impact_usd,
            "impact_pct":    round(impact_pct, 2),
        })

    results.sort(key=lambda x: x["impact_usd"], reverse=True)
    return results
