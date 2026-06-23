"""
Unit tests for Portfolio Benchmarking (Priority 7) — pure functions only.

Run with: pytest tests/test_portfolio_benchmark.py -v
"""

from app.services.portfolio_benchmark_service import (
    compute_percentile,
    build_benchmark,
)
from app.db.reports_repository import VALID_ACTIONS, VALID_OUTCOMES


def test_percentile_basic():
    peers = [0.2, 0.4, 0.6, 0.8]
    assert compute_percentile(0.6, peers) == 75       # 3 of 4 <= 0.6
    assert compute_percentile(0.9, peers) == 100
    assert compute_percentile(0.1, peers) == 0
    assert compute_percentile(0.5, peers) == 50


def test_percentile_edge_cases():
    assert compute_percentile(None, [0.5]) is None
    assert compute_percentile(0.5, []) is None
    assert compute_percentile(0.5, [None, None]) is None
    assert compute_percentile(0.7, [None, 0.6]) == 100   # ignores None peers


def _report(priority, drivers, scores=None):
    return {
        "idea_submitted": "novel antibiotic",
        "product_type": "antibiotic",
        "disease_intelligence": {"condition": "MRSA"},
        "commercialization_scores": {
            "commercialization_scores": dict(scores or {}, overall_priority=priority),
            "top_drivers": drivers,
        },
    }


def _peer(rid, priority):
    return {"report_id": rid, "idea": f"idea {rid}", "disease_name": "MRSA",
            "modality": "antibiotic", "overall_priority": priority, "tam_usd": 1e8}


def test_build_benchmark_above_average():
    peers = [_peer("a", 0.3), _peer("b", 0.4), _peer("c", 0.5)]
    rep = _report(0.7, ["Strong non-dilutive SBIR/STTR fit", "Large addressable market"])
    b = build_benchmark(rep, peers)
    assert b["portfolio_percentile"] == 100          # 0.7 above all 3 peers
    assert b["peer_count"] == 3
    assert b["rank"] == 1 and b["rank_total"] == 4   # small pool -> rank, not percentile
    assert len(b["similar_internal_projects"]) == 3
    # small-N uses rank wording ("#1 of 4"), and the real drivers are still there
    assert any("#1 of 4" in w for w in b["why_this_is_above_average"])
    assert any("SBIR" in w for w in b["why_this_is_above_average"])


def test_build_benchmark_below_average_collects_risks():
    peers = [_peer("a", 0.7), _peer("b", 0.8), _peer("c", 0.9)]
    rep = _report(0.4, ["Crowded patent & competitive landscape",
                        "Uncertain reimbursement / payer pathway"])
    b = build_benchmark(rep, peers)
    assert b["portfolio_percentile"] == 0
    assert b["rank"] == 4 and b["rank_total"] == 4   # last of 4
    assert any("#4 of 4" in w for w in b["why_this_may_fail"])
    assert any("Crowded" in w for w in b["why_this_may_fail"])


def test_large_pool_uses_percentile_not_rank():
    peers = [_peer(str(i), i / 10.0) for i in range(6)]   # 6 peers -> not small
    rep = _report(0.95, ["Large addressable market"])
    b = build_benchmark(rep, peers)
    assert any("top" in w.lower() for w in b["why_this_is_above_average"])


def test_build_benchmark_no_peers():
    rep = _report(0.6, ["Large addressable market"])
    b = build_benchmark(rep, [])
    assert b["portfolio_percentile"] is None
    assert b["peer_count"] == 0
    assert b["similar_internal_projects"] == []


def test_driver_polarity_split_uses_scores_fallback():
    # no drivers -> backfill from strongest/weakest scores
    rep = _report(0.5, [], scores={"sbir_fit": 0.85, "reimbursement_feasibility": 0.30})
    b = build_benchmark(rep, [_peer("a", 0.5)])
    assert any("sbir" in w.lower() for w in b["why_this_is_above_average"])
    assert any("reimbursement" in w.lower() for w in b["why_this_may_fail"])


def test_enum_vocabularies():
    assert "accepted" in VALID_ACTIONS and "ignored" in VALID_ACTIONS
    assert "licensed" in VALID_OUTCOMES and "deprioritized" in VALID_OUTCOMES
