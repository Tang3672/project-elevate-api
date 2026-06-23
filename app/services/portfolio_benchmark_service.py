"""
Portfolio Benchmarking Engine  (Brief Priority 7 / Sprint 7)
============================================================
Gives a TTO/incubator institution-level value: how does THIS invention compare
to the institution's prior disclosures in the same space, and what makes it
above- or below-average?

This is hard for a generic AI tool to replicate because it draws on the
institution's accumulated portfolio (the `reports` registry + world-model
graph) — not public data.

Output (the brief's P7 block):
    {
      "portfolio_percentile": 82,
      "similar_internal_projects": [...],
      "similar_successful_external_projects": [...],
      "similar_failed_external_projects": [...],
      "why_this_is_above_average": [...],
      "why_this_may_fail": [...]
    }

The percentile math and rationale assembly are PURE functions (unit-testable);
the async wrapper pulls peers from the reports registry.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def compute_percentile(score: Optional[float], peer_scores: list[float]) -> Optional[int]:
    """Percentile rank of `score` among peers (0-100). None if no score/peers.
    Uses the standard 'percent of peers at or below' definition."""
    if score is None or not peer_scores:
        return None
    valid = [p for p in peer_scores if p is not None]
    if not valid:
        return None
    at_or_below = sum(1 for p in valid if p <= score)
    return round(100 * at_or_below / len(valid))


def _fmt_usd(v) -> str:
    if not v:
        return "—"
    v = float(v)
    if v >= 1e9: return f"${v/1e9:.1f}B"
    if v >= 1e6: return f"${v/1e6:.0f}M"
    return f"${v/1e3:.0f}K"


def build_benchmark(report: dict, internal_peers: list[dict],
                    external: Optional[dict] = None) -> dict:
    """
    Assemble the P7 benchmark block from this report + its internal peers.
    Pure — no I/O. `internal_peers` are dicts from the reports registry.
    """
    cs_block = report.get("commercialization_scores") or {}
    scores = cs_block.get("commercialization_scores") or {}
    my_priority = scores.get("overall_priority")

    peer_scores = [p.get("overall_priority") for p in internal_peers]
    percentile = compute_percentile(my_priority, peer_scores)

    similar_internal = [
        {
            "report_id": p.get("report_id"),
            "idea": (p.get("idea") or "")[:120],
            "disease": p.get("disease_name"),
            "modality": p.get("modality"),
            "overall_priority": p.get("overall_priority"),
            "tam": _fmt_usd(p.get("tam_usd")),
        }
        for p in internal_peers[:8]
    ]

    # Rationale: ground "above average" in the decision engine's own drivers, and
    # in the relative comparison to the portfolio (no fabrication).
    drivers = cs_block.get("top_drivers") or []
    above, may_fail = _split_drivers(drivers, scores)

    # Rank is clearer than a percentile when the pool is tiny (a "top 0% of 2"
    # percentile is nonsense). Compute an explicit rank and prefer it for small N.
    n = len([s for s in peer_scores if s is not None])
    rank = rank_total = None
    if my_priority is not None and n:
        rank = 1 + sum(1 for s in peer_scores if s is not None and s > my_priority)
        rank_total = n + 1
        if n < 5:
            line = f"Ranks #{rank} of {rank_total} comparable internal disclosures on file"
            (above if rank * 2 <= rank_total else may_fail).insert(0, line)
        elif percentile is not None and percentile >= 60:
            above.insert(0, f"In the top {max(1, 100 - percentile)}% of {n} comparable internal disclosures")
        elif percentile is not None and percentile <= 40:
            may_fail.insert(0, f"Below the median of {n} comparable internal disclosures (P{percentile})")

    ext = external or {}
    return {
        "portfolio_percentile": percentile,
        "rank": rank,
        "rank_total": rank_total,
        "peer_count": n,
        "similar_internal_projects": similar_internal,
        "similar_successful_external_projects": ext.get("successful", []),
        "similar_failed_external_projects": ext.get("failed", []),
        "why_this_is_above_average": _dedupe(above)[:5],
        "why_this_may_fail": _dedupe(may_fail)[:5],
        "basis": ("Institutional portfolio (prior disclosures in the same disease/"
                  "modality) + this report's commercialization drivers."),
    }


# driver phrasing → polarity is inferred from the decision engine's wording.
_NEG_HINTS = ("low", "crowded", "uncertain", "weak", "limited", "below", "risk")


def _split_drivers(drivers: list[str], scores: dict) -> tuple[list[str], list[str]]:
    above, may_fail = [], []
    for d in drivers:
        (may_fail if any(h in d.lower() for h in _NEG_HINTS) else above).append(d)
    # Backfill from the strongest/weakest scores if drivers were sparse.
    ranked = sorted(((k, v) for k, v in scores.items() if k != "overall_priority"),
                    key=lambda kv: kv[1])
    if not may_fail and ranked:
        k, v = ranked[0]
        if v <= 0.45:
            may_fail.append(f"Weakest dimension: {k.replace('_', ' ')} ({int(v*100)}%)")
    if not above and ranked:
        k, v = ranked[-1]
        if v >= 0.6:
            above.append(f"Strongest dimension: {k.replace('_', ' ')} ({int(v*100)}%)")
    return above, may_fail


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for i in items:
        if i and i.lower() not in seen:
            seen.add(i.lower()); out.append(i)
    return out


async def portfolio_benchmark(report: dict, user_id: Optional[int] = None,
                              institution_id: Optional[str] = None) -> dict:
    """Async wrapper: fetch this owner's prior peers from the registry, then build
    the block. Scoped to the user/institution — never a cross-account global pool."""
    try:
        if user_id is None and not institution_id:
            return {"portfolio_percentile": None, "rank": None, "similar_internal_projects": [],
                    "why_this_is_above_average": [], "why_this_may_fail": [],
                    "note": "First disclosure in this account — no internal portfolio to rank against yet."}
        from app.db.reports_repository import peer_reports
        from app.services.world_model_graph import report_id_for
        di = report.get("disease_intelligence") or {}
        disease = di.get("condition") or report.get("idea_submitted", "")[:60]
        peers = await peer_reports(
            disease_name=disease, modality=report.get("product_type", ""),
            exclude_report_id=report_id_for(report), user_id=user_id, institution_id=institution_id)
        return build_benchmark(report, peers)
    except Exception as e:
        logger.warning("portfolio_benchmark failed (non-fatal): %s", e)
        return {"portfolio_percentile": None, "similar_internal_projects": [],
                "why_this_is_above_average": [], "why_this_may_fail": [],
                "note": "Portfolio benchmarking unavailable."}
