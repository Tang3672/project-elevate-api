"""
Tests for overlay_saved_assumptions — the report-generation hook that ships a
report already-adjusted when the PI has saved custom market-sizing assumptions.

Offline: repos monkeypatched, a SimpleNamespace stands in for the report.

Run: pytest tests/test_overlay_saved_assumptions.py -v
"""

import asyncio
from types import SimpleNamespace

import pytest

import app.services.alignment_service as svc
import app.db.market_sizing_override_repository as ovr_repo
import app.db.market_segment_repository as seg_repo


SEGMENT = {
    "id": 1,
    "segment_name": "LVO thrombectomy-eligible acute ischemic stroke",
    "funnel": [
        {"gate": "total_incidence", "label": "US ischemic stroke incidence/yr",
         "value": 690000, "type": "absolute", "source": "CDC/AHA 2024"},
        {"gate": "eligibility", "label": "thrombectomy-eligible",
         "rate": 0.48, "type": "rate", "source": "lit"},
    ],
    "som_penetration_pct": 0.35,
}


def _report(rid="rpt-1"):
    return SimpleNamespace(
        report_id=rid,
        market_sizing_funnel={"som_usd": 0},
        segment_used={"id": 1, "segment_name": SEGMENT["segment_name"]},
    )


@pytest.fixture
def patched(monkeypatch):
    async def _get_segment_by_id(sid):
        return SEGMENT if sid == 1 else None
    monkeypatch.setattr(seg_repo, "get_segment_by_id", _get_segment_by_id)
    return monkeypatch


def _set_saved(monkeypatch, saved):
    async def _get_override(report_id, segment_id, user_id=None):
        return saved
    monkeypatch.setattr(ovr_repo, "get_override", _get_override)


def test_no_saved_returns_false(patched):
    _set_saved(patched, None)
    r = _report()
    applied = asyncio.run(svc.overlay_saved_assumptions(r, SEGMENT, user_id=None))
    assert applied is False
    assert r.market_sizing_funnel == {"som_usd": 0}  # untouched


def test_overlay_applies_saved_edits(patched):
    _set_saved(patched, {
        "net_price_usd": 25000,
        "overrides": {"eligibility": {"rate": 0.60}},
        "added_gates": [],
        "removed_gates": [],
        "extra_segment_ids": [],
        "label": "my payer case",
    })
    r = _report()
    applied = asyncio.run(svc.overlay_saved_assumptions(r, SEGMENT, user_id=None))
    assert applied is True
    # 690000 * .60 * .35 * 25000
    assert r.market_sizing_funnel["som_usd"] == pytest.approx(690000 * 0.60 * 0.35 * 25000)
    assert r.segment_used["user_adjusted"] is True
    assert r.segment_used["adjustment_label"] == "my payer case"


def test_overlay_includes_added_gate_in_funnel(patched):
    _set_saved(patched, {
        "net_price_usd": 25000,
        "overrides": {},
        "added_gates": [{"gate": "reimbursed", "label": "Reimbursed",
                         "type": "rate", "rate": 0.5, "source": "payer calls"}],
        "removed_gates": [],
        "extra_segment_ids": [],
        "label": None,
    })
    r = _report()
    asyncio.run(svc.overlay_saved_assumptions(r, SEGMENT, user_id=None))
    gates = [g["gate"] for g in r.segment_used["funnel"]]
    assert "reimbursed" in gates


def test_no_report_id_returns_false(patched):
    _set_saved(patched, {"net_price_usd": 1, "overrides": {}, "added_gates": [],
                         "removed_gates": [], "extra_segment_ids": []})
    r = _report(rid=None)
    applied = asyncio.run(svc.overlay_saved_assumptions(r, SEGMENT, user_id=None))
    assert applied is False


def test_no_segment_returns_false(patched):
    _set_saved(patched, {"net_price_usd": 1, "overrides": {}, "added_gates": [],
                         "removed_gates": [], "extra_segment_ids": []})
    r = _report()
    applied = asyncio.run(svc.overlay_saved_assumptions(r, None, user_id=None))
    assert applied is False
