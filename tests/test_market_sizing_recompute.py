"""
Tests for the post-report "adjust assumptions" endpoint:
    POST /api/v1/alignment/market-sizing/recompute

Lets the PI override any funnel gate (or combine segments) and re-run
TAM/SAM/SOM after a report exists. DB is monkeypatched so these are
pure, offline tests.

Run: pytest tests/test_market_sizing_recompute.py -v
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.db.market_segment_repository as repo
import app.db.market_sizing_override_repository as ovr_repo
from app.api.alignment import router


STROKE_LVO = {
    "id": 1,
    "disease_name": "Stroke (acute ischemic)",
    "segment_name": "LVO thrombectomy-eligible acute ischemic stroke",
    "pathway_tag": "mechanical_thrombectomy",
    "funnel": [
        {"gate": "total_incidence", "label": "US ischemic stroke incidence/yr",
         "value": 690000, "type": "absolute", "source": "CDC/AHA 2024"},
        {"gate": "lvo_fraction", "label": "LVO share",
         "rate": 0.33, "type": "rate", "source": "Malhotra 2017"},
        {"gate": "eligibility", "label": "thrombectomy-eligible",
         "rate": 0.48, "type": "rate", "source": "DAWN/DEFUSE-3 — REVIEW"},
        {"gate": "access", "label": "reachable at CSCs",
         "rate": 0.70, "type": "rate", "source": "analyst estimate — REVIEW"},
    ],
    "som_penetration_pct": 0.35,
    "care_setting": "comprehensive_stroke_center",
    "site_count": 300,
}

# A second segment for the combine/scenario path.
STROKE_TPA = {
    "id": 2,
    "disease_name": "Stroke (acute ischemic)",
    "segment_name": "tPA-eligible ischemic stroke",
    "pathway_tag": "iv_thrombolytic",
    "funnel": [
        {"gate": "total_incidence", "label": "US ischemic stroke incidence/yr",
         "value": 690000, "type": "absolute", "source": "CDC/AHA 2024"},
        {"gate": "eligibility", "label": "tPA window-eligible",
         "rate": 0.10, "type": "rate", "source": "lit"},
    ],
    "som_penetration_pct": 0.20,
}

_SEGMENTS = {1: STROKE_LVO, 2: STROKE_TPA}


@pytest.fixture
def client(monkeypatch):
    async def _fake_get_segment_by_id(seg_id):
        return _SEGMENTS.get(seg_id)

    monkeypatch.setattr(repo, "get_segment_by_id", _fake_get_segment_by_id)

    # In-memory stand-in for the override persistence layer.
    store: dict = {}

    async def _save(*, report_id, segment_id, user_id, net_price_usd, overrides,
                    added_gates, removed_gates, extra_segment_ids,
                    tam_usd=None, sam_usd=None, som_usd=None, label=None):
        key = (report_id, segment_id, user_id)
        store[key] = {
            "id": len(store) + 1, "report_id": report_id, "segment_id": segment_id,
            "user_id": user_id, "net_price_usd": net_price_usd, "overrides": overrides,
            "added_gates": added_gates, "removed_gates": removed_gates,
            "extra_segment_ids": extra_segment_ids, "tam_usd": tam_usd,
            "sam_usd": sam_usd, "som_usd": som_usd, "label": label,
            "updated_at": "2026-07-10T00:00:00Z",
        }
        return store[key]["id"]

    async def _get(report_id, segment_id, user_id=None):
        return store.get((report_id, segment_id, user_id)) \
            or store.get((report_id, segment_id, None))

    async def _list(report_id):
        return [v for k, v in store.items() if k[0] == report_id]

    async def _delete(report_id, segment_id, user_id=None):
        return store.pop((report_id, segment_id, user_id), None) is not None

    monkeypatch.setattr(ovr_repo, "save_override", _save)
    monkeypatch.setattr(ovr_repo, "get_override", _get)
    monkeypatch.setattr(ovr_repo, "list_overrides_for_report", _list)
    monkeypatch.setattr(ovr_repo, "delete_override", _delete)

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/alignment")
    c = TestClient(app)
    c._override_store = store  # exposed for assertions
    return c


URL = "/api/v1/alignment/market-sizing/recompute"


def test_baseline_recompute_matches_funnel_math(client):
    r = client.post(URL, json={"segment_id": 1, "net_price_usd": 25000})
    assert r.status_code == 200
    ms = r.json()["market_sizing"]
    # 690000 * .33 * .48 * .70 = 76507 SAM pop
    assert ms["sam_population"] == pytest.approx(76507, abs=2)
    assert ms["som_population"] == pytest.approx(int(76507 * 0.35), abs=2)
    # every step carries a source
    assert all(s["source"] for s in ms["funnel_steps"])


def test_override_changes_result(client):
    base = client.post(URL, json={"segment_id": 1, "net_price_usd": 25000}).json()
    bumped = client.post(URL, json={
        "segment_id": 1, "net_price_usd": 25000,
        "overrides": {"eligibility": {"rate": 0.60}},
    }).json()
    assert bumped["applied_overrides"] == {"eligibility": {"rate": 0.60}}
    # raising eligibility 0.48 -> 0.60 must raise SOM
    assert bumped["market_sizing"]["som_usd"] > base["market_sizing"]["som_usd"]


def test_override_absolute_top_line(client):
    r = client.post(URL, json={
        "segment_id": 1, "net_price_usd": 25000,
        "overrides": {"total_incidence": {"value": 800000}},
    })
    assert r.status_code == 200
    steps = r.json()["market_sizing"]["funnel_steps"]
    assert steps[0]["running_value"] == 800000


def test_unknown_gate_rejected(client):
    r = client.post(URL, json={
        "segment_id": 1, "net_price_usd": 25000,
        "overrides": {"not_a_gate": {"rate": 0.5}},
    })
    assert r.status_code == 400
    assert "unknown gate" in r.json()["detail"]


def test_empty_override_entry_ignored(client):
    # a gate with both fields null should be dropped, not applied
    r = client.post(URL, json={
        "segment_id": 1, "net_price_usd": 25000,
        "overrides": {"eligibility": {"rate": None, "value": None}},
    })
    assert r.status_code == 200
    assert r.json()["applied_overrides"] == {}


def test_missing_segment_404(client):
    r = client.post(URL, json={"segment_id": 999, "net_price_usd": 25000})
    assert r.status_code == 404


def test_combine_segments_sums_sam(client):
    single = client.post(URL, json={"segment_id": 1, "net_price_usd": 25000}).json()
    combined = client.post(URL, json={
        "segment_id": 1, "net_price_usd": 25000, "extra_segment_ids": [2],
    }).json()
    assert combined["market_sizing"]["sam_population"] > single["market_sizing"]["sam_population"]
    assert len(combined["market_sizing"]["segments_used"]) == 2


def test_rate_out_of_range_rejected(client):
    r = client.post(URL, json={
        "segment_id": 1, "net_price_usd": 25000,
        "overrides": {"lvo_fraction": {"rate": 1.5}},
    })
    assert r.status_code == 422  # pydantic validation (le=1)


def test_net_price_required_positive(client):
    r = client.post(URL, json={"segment_id": 1, "net_price_usd": 0})
    assert r.status_code == 422


# ── user-authored (typed-out) assumptions ────────────────────────────────────

def test_add_custom_rate_gate_narrows_market(client):
    base = client.post(URL, json={"segment_id": 1, "net_price_usd": 25000}).json()
    added = client.post(URL, json={
        "segment_id": 1, "net_price_usd": 25000,
        "added_gates": [{
            "label": "Reimbursement-covered",
            "type": "rate", "rate": 0.55,
            "source": "our payer interviews Q2'26",
            "after": "access",
        }],
    }).json()
    steps = added["market_sizing"]["funnel_steps"]
    # the new gate is present, source preserved, and appears after 'access'
    labels = [s["label"] for s in steps]
    assert "Reimbursement-covered" in labels
    new_step = next(s for s in steps if s["label"] == "Reimbursement-covered")
    assert new_step["source"] == "our payer interviews Q2'26"
    assert steps.index(new_step) == labels.index("reachable at CSCs") + 1 \
        if "reachable at CSCs" in labels else True
    # narrows SOM
    assert added["market_sizing"]["som_usd"] < base["market_sizing"]["som_usd"]


def test_added_gate_default_source_flags_weakest(client):
    r = client.post(URL, json={
        "segment_id": 1, "net_price_usd": 25000,
        "added_gates": [{"label": "Gut-feel adjustment", "type": "rate", "rate": 0.8}],
    }).json()
    weak = " ".join(r["market_sizing"]["weakest_assumptions"])
    assert "Gut-feel adjustment" in weak  # unverified user gate counted as weak


def test_add_gate_appended_when_no_after(client):
    r = client.post(URL, json={
        "segment_id": 1, "net_price_usd": 25000,
        "added_gates": [{"label": "Extra gate", "type": "rate", "rate": 0.9}],
    }).json()
    assert r["market_sizing"]["funnel_steps"][-1]["label"] == "Extra gate"


def test_remove_gate(client):
    r = client.post(URL, json={
        "segment_id": 1, "net_price_usd": 25000,
        "removed_gates": ["access"],
    })
    assert r.status_code == 200
    labels = [s["gate"] for s in r.json()["market_sizing"]["funnel_steps"]]
    assert "access" not in labels


def test_remove_then_readd_full_custom_funnel(client):
    # PI rebuilds the whole funnel: drop eligibility+access, type their own
    r = client.post(URL, json={
        "segment_id": 1, "net_price_usd": 25000,
        "removed_gates": ["eligibility", "access"],
        "added_gates": [{
            "label": "Our eligibility estimate", "type": "rate", "rate": 0.40,
            "source": "internal model", "after": "lvo_fraction",
        }],
    })
    assert r.status_code == 200
    gates = [s["gate"] for s in r.json()["market_sizing"]["funnel_steps"]]
    assert "eligibility" not in gates and "access" not in gates
    assert "our_eligibility_estimate" in gates


def test_absolute_gate_missing_value_422(client):
    r = client.post(URL, json={
        "segment_id": 1, "net_price_usd": 25000,
        "added_gates": [{"label": "New base", "type": "absolute"}],
    })
    assert r.status_code == 422


def test_funnel_must_start_absolute(client):
    # remove the only absolute gate -> 400 guard
    r = client.post(URL, json={
        "segment_id": 1, "net_price_usd": 25000,
        "removed_gates": ["total_incidence"],
    })
    assert r.status_code == 400
    assert "absolute" in r.json()["detail"]


def test_remove_unknown_gate_400(client):
    r = client.post(URL, json={
        "segment_id": 1, "net_price_usd": 25000,
        "removed_gates": ["nope"],
    })
    assert r.status_code == 400


def test_after_unknown_gate_400(client):
    r = client.post(URL, json={
        "segment_id": 1, "net_price_usd": 25000,
        "added_gates": [{"label": "X", "type": "rate", "rate": 0.5, "after": "ghost"}],
    })
    assert r.status_code == 400


def test_duplicate_added_slugs_disambiguated(client):
    r = client.post(URL, json={
        "segment_id": 1, "net_price_usd": 25000,
        "added_gates": [
            {"label": "Adjustment", "type": "rate", "rate": 0.9},
            {"label": "Adjustment", "type": "rate", "rate": 0.8},
        ],
    })
    assert r.status_code == 200
    gates = [s["gate"] for s in r.json()["market_sizing"]["funnel_steps"]]
    assert "adjustment" in gates and "adjustment_2" in gates


# ── persistence: adjusted TAM sticks to the report ───────────────────────────

LOAD = "/api/v1/alignment/market-sizing/override"


def test_recompute_persists_when_report_id_given(client):
    r = client.post(URL, json={
        "segment_id": 1, "net_price_usd": 25000, "report_id": "rpt-abc",
        "overrides": {"eligibility": {"rate": 0.60}},
        "label": "my payer case",
    }).json()
    assert r["saved"] is True
    assert r["saved_override_id"] is not None
    assert ("rpt-abc", 1, None) in client._override_store


def test_no_persist_without_report_id(client):
    r = client.post(URL, json={
        "segment_id": 1, "net_price_usd": 25000,
        "overrides": {"eligibility": {"rate": 0.60}},
    }).json()
    assert r["saved"] is False
    assert client._override_store == {}


def test_persist_false_previews_without_saving(client):
    r = client.post(URL, json={
        "segment_id": 1, "net_price_usd": 25000, "report_id": "rpt-abc",
        "persist": False,
        "overrides": {"eligibility": {"rate": 0.60}},
    }).json()
    assert r["saved"] is False
    assert client._override_store == {}


def test_saved_tam_sticks_on_reload(client):
    # PI adjusts + saves
    saved = client.post(URL, json={
        "segment_id": 1, "net_price_usd": 25000, "report_id": "rpt-abc",
        "overrides": {"eligibility": {"rate": 0.60}},
        "added_gates": [{"label": "Reimbursed", "type": "rate", "rate": 0.5,
                         "source": "payer calls", "after": "access"}],
    }).json()
    # reopening the report loads the same numbers
    loaded = client.get(LOAD, params={"report_id": "rpt-abc", "segment_id": 1}).json()
    assert loaded["market_sizing"]["som_usd"] == saved["market_sizing"]["som_usd"]
    assert loaded["market_sizing"]["tam_usd"] == saved["market_sizing"]["tam_usd"]
    labels = [s["label"] for s in loaded["market_sizing"]["funnel_steps"]]
    assert "Reimbursed" in labels


def test_load_404_when_nothing_saved(client):
    r = client.get(LOAD, params={"report_id": "nope", "segment_id": 1})
    assert r.status_code == 404


def test_resave_replaces_edit_set(client):
    client.post(URL, json={"segment_id": 1, "net_price_usd": 25000,
                           "report_id": "rpt-abc",
                           "overrides": {"eligibility": {"rate": 0.60}}})
    client.post(URL, json={"segment_id": 1, "net_price_usd": 25000,
                           "report_id": "rpt-abc",
                           "overrides": {"eligibility": {"rate": 0.20}}})
    loaded = client.get(LOAD, params={"report_id": "rpt-abc", "segment_id": 1}).json()
    assert loaded["applied_overrides"] == {"eligibility": {"rate": 0.20}}
    # only one row for that report/segment
    assert len(client._override_store) == 1


def test_list_overrides_for_report(client):
    client.post(URL, json={"segment_id": 1, "net_price_usd": 25000,
                           "report_id": "rpt-abc", "overrides": {"eligibility": {"rate": 0.6}}})
    client.post(URL, json={"segment_id": 2, "net_price_usd": 25000,
                           "report_id": "rpt-abc"})
    r = client.get(f"/api/v1/alignment/market-sizing/overrides/rpt-abc").json()
    assert r["count"] == 2


def test_revert_deletes_saved(client):
    client.post(URL, json={"segment_id": 1, "net_price_usd": 25000,
                           "report_id": "rpt-abc", "overrides": {"eligibility": {"rate": 0.6}}})
    d = client.delete(LOAD, params={"report_id": "rpt-abc", "segment_id": 1}).json()
    assert d["reverted"] is True
    assert client.get(LOAD, params={"report_id": "rpt-abc", "segment_id": 1}).status_code == 404
