"""
Unit tests for the TTO review-queue shaping (Sprint 5) — pure helpers only.

Run with: pytest tests/test_review_queue.py -v
"""

from datetime import datetime

from app.db.reports_repository import _invention_row, _parse_scores, VALID_STATUSES


def test_parse_scores_variants():
    assert _parse_scores({"a": 1}) == {"a": 1}
    assert _parse_scores('{"a": 1}') == {"a": 1}
    assert _parse_scores("not json") == {}
    assert _parse_scores(None) == {}
    assert _parse_scores("") == {}


def test_invention_row_maps_dashboard_columns():
    row = {
        "report_id": "abc123", "idea": "novel antibiotic", "disease_name": "MRSA",
        "modality": "antibiotic", "overall_priority": 0.69, "tam_usd": 9.6e8,
        "scores": {"regulatory_feasibility": 0.6, "competitive_whitespace": 0.58,
                   "sbir_fit": 0.83, "licensing_likelihood": 0.61},
        "recommendation": "Pursue SBIR Phase I.", "next_action": "Pursue SBIR Phase I.",
        "status": "under_review", "assigned_reviewer": "A. Lee",
        "created_at": datetime(2026, 6, 12, 9, 0, 0),
    }
    rec = _invention_row(row)
    assert rec["priority_score"] == 0.69
    assert rec["market_opportunity_usd"] == 9.6e8
    assert rec["regulatory_feasibility"] == 0.6
    assert rec["competitive_whitespace"] == 0.58
    assert rec["funding_fit"] == 0.83
    assert rec["licensing_fit"] == 0.61
    assert rec["status"] == "under_review"
    assert rec["assigned_reviewer"] == "A. Lee"
    assert rec["created_at"].startswith("2026-06-12")


def test_invention_row_defaults_and_jsonb_string():
    # scores arriving as a JSONB string (asyncpg) and missing status -> defaults
    row = {"report_id": "x", "idea": "i", "disease_name": "d", "modality": "m",
           "overall_priority": None, "tam_usd": None,
           "scores": '{"sbir_fit": 0.5}', "recommendation": None,
           "next_action": None, "status": None, "assigned_reviewer": None,
           "created_at": None}
    rec = _invention_row(row)
    assert rec["status"] == "triaged"          # default
    assert rec["funding_fit"] == 0.5           # parsed from JSONB string
    assert rec["regulatory_feasibility"] is None
    assert rec["created_at"] is None


def test_valid_statuses():
    assert {"intake", "triaged", "under_review", "decided", "deprioritized"} == VALID_STATUSES
