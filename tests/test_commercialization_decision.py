"""
Unit tests for the Commercialization Decision Engine (Priority 5).

Pure scorer — no DB, no API key.

Run with: pytest tests/test_commercialization_decision.py -v
"""

from types import SimpleNamespace

from app.services.commercialization_decision_service import (
    score_commercialization,
    gather_signals,
    build_decision,
    _modality,
    _market_score,
    _whitespace_from_signal,
)

_SCORE_KEYS = {
    "patentability", "licensing_likelihood", "spinout_likelihood", "sbir_fit",
    "investor_attractiveness", "regulatory_feasibility", "reimbursement_feasibility",
    "acquisition_potential", "competitive_whitespace", "overall_priority",
}


def test_all_scores_present_and_in_range():
    out = score_commercialization({"modality": "small_molecule", "approval_prob": 0.6})
    scores = out["commercialization_scores"]
    assert set(scores) == _SCORE_KEYS
    for v in scores.values():
        assert 0.0 <= v <= 1.0


def test_neutral_priors_when_no_signals():
    out = score_commercialization({})
    # nothing should be NaN / out of range, and overall should be mid-ish
    assert 0.3 <= out["commercialization_scores"]["overall_priority"] <= 0.7
    assert out["method"].startswith("rules")


def test_modality_classification():
    assert _modality("gene_therapy", "gene_therapy_rare") == "gene_cell"
    assert _modality("antibiotic", "drug_amr") == "small_molecule"
    assert _modality("diagnostic", "diagnostic_molecular") == "diagnostic"
    assert _modality("digital_health", "digital_cds") == "digital"
    assert _modality("medical_device", "device_cardiovascular") == "device"


def test_market_score_log_scale():
    assert _market_score(1e6) == 0.0          # ~$1M floor
    assert _market_score(1e9) == 1.0          # ~$1B ceiling
    assert 0.0 < _market_score(3e7) < 1.0
    assert _market_score(0) == 0.5            # unknown -> neutral
    assert _market_score(None) == 0.5


def test_whitespace_mapping():
    assert _whitespace_from_signal("OPEN") > _whitespace_from_signal("ACTIVE")
    assert _whitespace_from_signal("ACTIVE") > _whitespace_from_signal("CROWDED")
    assert _whitespace_from_signal(None) == 0.5


def test_higher_approval_raises_regulatory_feasibility():
    lo = score_commercialization({"approval_prob": 0.2})["commercialization_scores"]["regulatory_feasibility"]
    hi = score_commercialization({"approval_prob": 0.9})["commercialization_scores"]["regulatory_feasibility"]
    assert hi > lo


def test_crowded_ip_lowers_whitespace_and_patentability():
    crowded = score_commercialization({"whitespace": 0.25, "modality": "small_molecule"})["commercialization_scores"]
    openips = score_commercialization({"whitespace": 0.85, "modality": "small_molecule"})["commercialization_scores"]
    assert openips["competitive_whitespace"] > crowded["competitive_whitespace"]
    assert openips["patentability"] > crowded["patentability"]


def test_early_trl_strong_sbir_signal_recommends_sbir():
    out = score_commercialization({
        "modality": "small_molecule", "trl": 3, "sbir_p1_ready": True,
        "sbir_awards": 8, "som_usd": 2e7, "approval_prob": 0.45, "moat": 0.4,
    })
    assert out["commercialization_scores"]["sbir_fit"] >= 0.6
    assert "SBIR" in out["recommendation"]


def test_strong_venture_profile_recommendation():
    out = score_commercialization({
        "modality": "biologic", "trl": 6, "som_usd": 2e9,
        "approval_prob": 0.7, "moat": 0.8, "whitespace": 0.8, "sbir_p1_ready": False,
    })
    assert out["commercialization_scores"]["investor_attractiveness"] >= 0.65
    assert out["commercialization_scores"]["overall_priority"] >= 0.6
    assert out["top_drivers"]   # non-empty


def test_low_overall_triggers_deprioritize():
    out = score_commercialization({
        "modality": "digital", "trl": 2, "som_usd": 1e6,
        "approval_prob": 0.15, "moat": 0.1, "whitespace": 0.2, "sbir_awards": 0,
    })
    assert out["commercialization_scores"]["overall_priority"] < 0.45
    assert "Deprioritize" in out["recommendation"]


def test_gather_signals_from_pipeline_objects():
    panel = SimpleNamespace(
        regulatory=SimpleNamespace(approval_probability_pct=65,
                                   available_designations=["Fast Track", "QIDP"]),
        commercial=SimpleNamespace(competitive_moat_score=7.0,
                                   key_payer_barrier="no code yet, high price"),
    )
    patent = {"activity_signal": "OPEN", "total_results": 12}
    trl = SimpleNamespace(trl_level=4, sbir_phase1_ready=True)
    deriv = SimpleNamespace(us_som_usd=4.8e7, us_tam_usd=9.6e8)

    sig = gather_signals(product_type="antibiotic", sub_expert_id="drug_amr",
                         panel_result=panel, patent_landscape=patent,
                         trl_result=trl, deriv=deriv, sbir_awards=5)
    assert sig["modality"] == "small_molecule"
    assert abs(sig["approval_prob"] - 0.65) < 1e-9
    assert abs(sig["moat"] - 0.70) < 1e-9
    assert sig["whitespace"] == _whitespace_from_signal("OPEN")
    assert sig["trl"] == 4 and sig["sbir_p1_ready"] is True
    assert sig["som_usd"] == 4.8e7
    assert sig["designations"] == ["Fast Track", "QIDP"]

    # end-to-end via build_decision with the same objects
    out = build_decision(product_type="antibiotic", sub_expert_id="drug_amr",
                         panel_result=panel, patent_landscape=patent,
                         trl_result=trl, deriv=deriv, sbir_awards=5)
    assert set(out["commercialization_scores"]) == _SCORE_KEYS


def test_gather_tolerates_missing_and_exception_objects():
    # all objects None -> neutral signals, no crash
    sig = gather_signals(product_type="other")
    out = score_commercialization(sig)
    assert set(out["commercialization_scores"]) == _SCORE_KEYS
