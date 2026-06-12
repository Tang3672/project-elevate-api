"""
Unit tests for the Trust Layer scorecard (Priority 2).

These exercise the PURE, deterministic aggregation (`compute_trust_scorecard`)
and the evidence/claim collectors — no Anthropic API key required.

Run with: pytest tests/test_trust_layer.py -v
"""

from app.services.trust_layer_service import (
    compute_trust_scorecard,
    collect_evidence_pool,
    collect_claim_text,
)


def _claim(text, type_, support, evidence_ids=None):
    return {"claim": text, "type": type_, "support": support,
            "evidence_ids": evidence_ids or []}


def test_all_supported_high_trust():
    claims = [
        _claim("incidence is 119,247", "numerical", "supported", [0]),
        _claim("MRSA is gram-positive", "factual", "supported", [1]),
        _claim("TAM is $144M", "numerical", "supported", [2]),
        _claim("pursue SBIR first", "recommendation", "n/a"),
        _claim("strong opportunity", "interpretation", "n/a"),
    ]
    card = compute_trust_scorecard(claims, contradictions=[], evidence_pool_size=8)
    assert card["citation_support_score"] == 1.0
    assert card["retrieval_coverage"] == 1.0
    assert card["unsupported_claim_count"] == 0
    assert card["checkable_claims"] == 3          # recs/interpretations excluded
    assert card["abstention_required"] is False
    assert card["human_review_recommended"] is False
    assert card["trust_grade"] == "HIGH"


def test_recommendations_not_penalised():
    """A report of only recommendations has too few checkable claims -> abstain."""
    claims = [_claim(f"do thing {i}", "recommendation", "n/a") for i in range(5)]
    card = compute_trust_scorecard(claims, contradictions=[], evidence_pool_size=4)
    assert card["checkable_claims"] == 0
    assert card["abstention_required"] is True
    assert any("checkable" in r for r in card["abstention_reasons"])


def test_unsupported_claims_trigger_review():
    claims = [
        _claim("a", "numerical", "supported", [0]),
        _claim("b", "numerical", "supported", [1]),
        _claim("c", "factual", "unsupported"),
        _claim("d", "factual", "unsupported"),
        _claim("e", "factual", "unsupported"),
    ]
    card = compute_trust_scorecard(claims, contradictions=[], evidence_pool_size=6)
    assert card["unsupported_claim_count"] == 3
    # 2 supported + 3 unsupported => 2/5 = 0.4 support
    assert card["citation_support_score"] == 0.4
    assert card["human_review_recommended"] is True
    # support 0.4 < 0.50 abstain floor
    assert card["abstention_required"] is True


def test_weak_support_half_weight():
    claims = [
        _claim("a", "numerical", "supported", [0]),
        _claim("b", "numerical", "weak", [1]),
        _claim("c", "numerical", "weak", [2]),
        _claim("d", "numerical", "supported", [3]),
    ]
    card = compute_trust_scorecard(claims, contradictions=[], evidence_pool_size=5)
    # (1 + 0.5 + 0.5 + 1) / 4 = 0.75
    assert card["citation_support_score"] == 0.75
    # weak still counts as grounded (has evidence_ids) -> coverage 1.0
    assert card["retrieval_coverage"] == 1.0
    assert card["unsupported_claim_count"] == 0


def test_contradictions_and_validation_errors_combine():
    claims = [_claim(f"n{i}", "numerical", "supported", [i]) for i in range(4)]
    validation = {"errors": [{"issue": "math wrong"}, {"issue": "bad source"}]}
    card = compute_trust_scorecard(
        claims,
        contradictions=[{"claim_a": "x", "claim_b_or_evidence": "y", "explanation": "z"}],
        evidence_pool_size=6,
        validation=validation,
    )
    assert card["contradiction_count"] == 3   # 1 judge + 2 validation errors
    assert card["human_review_recommended"] is True
    assert card["citation_support_score"] == 1.0   # but support is still perfect


def test_empty_evidence_pool_forces_abstention():
    claims = [_claim(f"n{i}", "numerical", "unsupported") for i in range(4)]
    card = compute_trust_scorecard(claims, contradictions=[], evidence_pool_size=0)
    assert card["abstention_required"] is True
    assert any("no retrieved evidence" in r for r in card["abstention_reasons"])


def test_grade_moderate_band():
    # 9 supported, 1 unsupported => 0.9 support, no contradictions
    claims = [_claim(f"s{i}", "numerical", "supported", [i]) for i in range(9)]
    claims.append(_claim("u", "factual", "unsupported"))
    card = compute_trust_scorecard(claims, contradictions=[], evidence_pool_size=12)
    assert card["citation_support_score"] == 0.9
    assert card["trust_grade"] == "MODERATE"
    assert card["abstention_required"] is False


def test_collect_evidence_pool_dedups_and_pulls_all_sections():
    report = {
        "supporting_evidence": [
            {"source": "CDC", "source_url": "https://cdc.gov", "signal_type": "epi", "title": "AR Threats"},
            {"source": "CDC", "source_url": "https://cdc.gov", "signal_type": "epi", "title": "AR Threats"},  # dup
        ],
        "disease_intelligence": {"data_points": [
            {"source": "SEER", "metric": "incidence", "value": "119247", "year": "2019"},
        ]},
        "market_sizing": {"steps": [
            {"source": "CMS", "label": "price", "value": 12000, "unit": "USD"},
        ]},
    }
    pool = collect_evidence_pool(report)
    sources = {e["source"] for e in pool}
    assert sources == {"CDC", "SEER", "CMS"}
    assert len(pool) == 3   # CDC duplicate collapsed


def test_collect_claim_text_includes_sections():
    report = {
        "executive_summary": "A novel antibiotic for MRSA.",
        "market_sizing": {"formula": "p x price", "total_addressable_market_usd": 144000000},
        "recommended_next_steps": ["File provisional patent"],
    }
    text = collect_claim_text(report)
    assert "Executive Summary" in text
    assert "Market Sizing" in text
    assert "File provisional patent" in text
