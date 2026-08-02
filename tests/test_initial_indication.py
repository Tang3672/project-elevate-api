"""
Tests for the initial-vs-eventual market resolver (Build Spec v3, Part 2).

A therapy first launches in a narrow sub-indication, so the initial addressable
market must be < the eventual/full-indication market.

Run: pytest tests/test_initial_indication.py -v
"""

import pytest

from app.services.market_sizing_engine import (
    resolve_initial_indication, segment_initial_indication, specialist_for_ta,
    apply_model_launch_indication)


# ── model-reasoned launch indication DRIVES the number (the general fix) ──────

def _ive(prior_fraction=0.15):
    return {
        "applicable": True,
        "initial_market": {"tam_usd": 150, "fraction_of_eventual": prior_fraction, "basis": "ta_default"},
        "eventual_market": {"tam_usd": 1000, "sam_usd": 500, "som_usd": 100},
        "driver": "disease_prior",
    }


def test_model_fraction_drives_initial_market():
    ive = apply_model_launch_indication(_ive(prior_fraction=0.15), {
        "population": "2L+ KRAS-G12C NSCLC", "fraction_of_disease": 0.05,
        "basis": "sotorasib label", "confidence": "high", "verify_with": "oncology KOL",
    })
    # model's 5% now drives the number, not the 15% prior
    assert ive["driver"] == "model"
    assert ive["initial_market"]["fraction_of_eventual"] == 0.05
    assert ive["initial_market"]["tam_usd"] == 50  # 1000 × 0.05
    assert ive["initial_market"]["population"] == "2L+ KRAS-G12C NSCLC"
    assert ive["verify_with"] == "oncology KOL"


def test_prior_kept_as_divergence_cross_check():
    ive = apply_model_launch_indication(_ive(prior_fraction=0.15), {
        "fraction_of_disease": 0.03, "population": "narrow slice", "basis": "x", "confidence": "low",
    })
    # 0.03 vs 0.15 prior → |0.03-0.15|/0.15 = 0.8 > 0.5 → flagged for review
    assert ive["prior_cross_check"]["fraction"] == 0.15
    assert ive["prior_divergence_flag"] is True


def test_invalid_model_fraction_is_noop():
    for bad in [None, {}, {"fraction_of_disease": 0}, {"fraction_of_disease": 1.5},
                {"fraction_of_disease": "abc"}]:
        ive = apply_model_launch_indication(_ive(), bad)
        assert ive["driver"] == "disease_prior"  # prior stands


def test_not_applicable_is_untouched():
    ive = {"applicable": False, "note": "site-license"}
    assert apply_model_launch_indication(ive, {"fraction_of_disease": 0.1}) == ive


# ── product-specific initial indication (the real stroke fix) ────────────────

_LVO_SEGMENT = {
    "segment_name": "LVO thrombectomy-eligible acute ischemic stroke",
    "pathway_tag": "mechanical_thrombectomy",
    "funnel": [
        {"gate": "total_incidence", "type": "absolute", "value": 690000},
        {"gate": "lvo", "type": "rate", "rate": 0.33},
    ],
}
_TPA_SEGMENT = {
    "segment_name": "tPA-eligible ischemic stroke",
    "pathway_tag": "iv_thrombolytic",
    "funnel": [{"gate": "total_incidence", "type": "absolute", "value": 690000}],
}


def test_product_specific_fraction_from_segment():
    r = segment_initial_indication(_LVO_SEGMENT, 110_000)
    assert r["basis"] == "product_segment"
    # 110k / 690k ≈ 16% — the thrombectomy launch population, not "all stroke"
    assert r["fraction"] == pytest.approx(110_000 / 690_000, abs=0.005)


def test_different_products_same_disease_get_different_gates():
    # the crux: two products in the SAME disease must NOT get the same fraction
    lvo = segment_initial_indication(_LVO_SEGMENT, 110_000)
    tpa = segment_initial_indication(_TPA_SEGMENT, 70_000)
    assert lvo["fraction"] != tpa["fraction"]


def test_product_specific_differs_from_disease_constant():
    seg_frac = segment_initial_indication(_LVO_SEGMENT, 110_000)["fraction"]
    disease_frac = resolve_initial_indication("acute ischemic stroke", "neurology_cns")["fraction"]
    assert seg_frac != disease_frac  # product-aware ≠ disease-level constant


def test_segment_without_base_returns_none():
    assert segment_initial_indication({"funnel": [{"gate": "x", "type": "rate", "rate": 0.5}]}, 100) is None
    assert segment_initial_indication(_LVO_SEGMENT, 0) is None


def test_specialist_mapping():
    assert "neurolog" in specialist_for_ta("neurology_cns").lower()
    assert "infectious" in specialist_for_ta("amr_infectious").lower()
    assert specialist_for_ta("nonexistent")  # always returns a fallback string


def test_stroke_initial_is_fraction_of_disease():
    r = resolve_initial_indication("acute ischemic stroke", "cardiovascular")
    assert 0 < r["fraction"] < 1.0          # never the whole disease
    assert r["basis"] == "disease_specific"
    assert r["expansion_years"] >= 1


def test_ta_default_when_no_disease_entry():
    r = resolve_initial_indication("some novel unlisted cancer", "oncology")
    assert r["basis"] == "ta_default"
    assert r["fraction"] == pytest.approx(0.15)  # FDA oncology median initial approval


def test_global_default_when_nothing_matches():
    r = resolve_initial_indication("totally unknown condition", "not_a_ta")
    assert r["basis"] == "global_default"
    assert r["fraction"] == pytest.approx(0.30)
    assert "REVIEW" in r["source"]


def test_initial_market_is_smaller_than_eventual():
    # the arithmetic the report applies: initial = eventual × fraction
    eventual_tam = 5_000_000_000
    r = resolve_initial_indication("acute ischemic stroke", "cardiovascular")
    initial_tam = eventual_tam * r["fraction"]
    assert initial_tam < eventual_tam
    # a stroke drug's launch market is a small slice, not "all stroke"
    assert initial_tam / eventual_tam < 0.5


def test_resolver_always_returns_required_keys():
    r = resolve_initial_indication("", "")
    assert set(r) >= {"fraction", "rationale", "expansion_years", "source", "basis"}
