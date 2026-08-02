"""
Tests that /clarify always asks how an inferred-monetization product is sold
(Build Spec v3, Part 1 UX rule). The LLM call and auth are stubbed so the test
is offline.

Run: pytest tests/test_clarify_monetization.py -v
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.alignment as alignment_api
from app.api.alignment import router
from app.api.auth import get_current_user


@pytest.fixture
def client(monkeypatch):
    # Stub the Anthropic client so no network/LLM is hit; return two generic questions.
    class _FakeMsg:
        content = [type("C", (), {"text": '[{"question":"q1","field":"a","options":["x"],"hint":"h"},'
                                          '{"question":"q2","field":"b","options":["y"],"hint":"h"}]'})()]

    class _FakeMessages:
        def create(self, **kw):
            return _FakeMsg()

    class _FakeClient:
        def __init__(self, *a, **k):
            self.messages = _FakeMessages()

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient)

    # Bypass competitor sweep + enrichment side calls (best-effort blocks already swallow errors).
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/alignment")
    app.dependency_overrides[get_current_user] = lambda: {"id": 1}
    return TestClient(app)


URL = "/api/v1/alignment/clarify"


def test_software_gets_monetization_question_first(client):
    r = client.post(URL, json={
        "idea": "AI clinical decision support platform deployed across hospital ICUs for sepsis",
        "product_type": "digital_health",
    })
    assert r.status_code == 200
    qs = r.json()["questions"]
    assert qs[0]["field"] == "monetization_unit"
    assert any("hospital site license" in o for o in qs[0]["options"])
    assert any("enrolled patient" in o for o in qs[0]["options"])  # per-patient SaMD is distinct
    assert qs[0]["inferred_model"] == "SiteLicenseModel"


def test_drug_gets_no_monetization_question(client):
    r = client.post(URL, json={
        "idea": "Oral small molecule kinase inhibitor for acute ischemic stroke neuroprotection",
        "product_type": "drug_small_molecule",
    })
    assert r.status_code == 200
    fields = [q.get("field") for q in r.json()["questions"]]
    assert "monetization_unit" not in fields  # drug unit is unambiguous


def test_total_questions_capped_at_8(client):
    r = client.post(URL, json={
        "idea": "AI imaging triage software for stroke detection in hospital radiology",
        "product_type": "digital_health",
    })
    assert len(r.json()["questions"]) <= 8
