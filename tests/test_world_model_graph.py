"""
Unit tests for the Commercialization World Model graph (Priority 4 / Sprint 3).

Covers the PURE pieces — normalization and `extract_graph_from_report` — plus
the expert-panel serializer. No DB / API key required.

Run with: pytest tests/test_world_model_graph.py -v
"""

from types import SimpleNamespace

from app.services.world_model_graph import (
    normalize_key,
    extract_graph_from_report,
    NODE_TYPES,
    EDGE_TYPES,
)
from app.services.expert_panel import panel_to_dict


def _report():
    return {
        "idea_submitted": "novel oral antibiotic for MRSA bloodstream infections",
        "product_type": "antibiotic",
        "generated_at": "2026-06-12T00:00:00",
        "expert_name": "AMR Expert",
        "disease_intelligence": {"condition": "MRSA", "unmet_need_summary": "resistance rising"},
        "market_sizing": {"total_addressable_market_usd": 9.6e8},
        "regulatory_pathway": {
            "recommended_pathway": "Traditional NDA with QIDP",
            "designations": [{"name": "QIDP", "benefit": "+5yr exclusivity"},
                             {"name": "Fast Track", "benefit": "rolling review"}],
        },
        "market_access": {"key_opinion_leaders": ["Dr. Jane Smith", "Dr. John Doe"]},
        "commercialization_scores": {
            "commercialization_scores": {"overall_priority": 0.6},
            "recommendation": "Pursue SBIR Phase I.",
        },
    }


def test_normalize_key():
    assert normalize_key("MRSA") == "mrsa"
    assert normalize_key("Carbapenem-Resistant  Enterobacterales!") == "carbapenem resistant enterobacterales"
    assert normalize_key("") == ""
    assert normalize_key(None) == ""


def test_extract_nodes_and_types_valid():
    g = extract_graph_from_report(_report(), disease_name="MRSA", user_id=42)
    types = {n["node_type"] for n in g["nodes"]}
    # core entities present
    assert {"disease", "modality", "report", "regulatory_pathway",
            "fda_designation", "kol", "pi_profile"} <= types
    # every node_type and edge_type is from the controlled vocabularies
    assert types <= NODE_TYPES
    assert {e["edge_type"] for e in g["edges"]} <= EDGE_TYPES


def test_extract_key_edges_present():
    g = extract_graph_from_report(_report(), disease_name="MRSA", user_id=42)
    pairs = {(e["src"].split("::")[0], e["edge_type"], e["dst"].split("::")[0]) for e in g["edges"]}
    assert ("report", "analyzes", "disease") in pairs
    assert ("report", "recommended_pathway", "regulatory_pathway") in pairs
    assert ("disease", "has_kol", "kol") in pairs
    assert ("pi_profile", "authored", "report") in pairs
    assert ("modality", "treats", "disease") in pairs


def test_report_node_carries_attributes():
    g = extract_graph_from_report(_report(), disease_name="MRSA")
    report_node = next(n for n in g["nodes"] if n["node_type"] == "report")
    assert report_node["attributes"]["tam_usd"] == 9.6e8
    assert report_node["attributes"]["overall_priority"] == 0.6
    assert "Pursue SBIR" in report_node["attributes"]["recommendation"]


def test_no_pi_node_without_user():
    g = extract_graph_from_report(_report(), disease_name="MRSA", user_id=None)
    assert not any(n["node_type"] == "pi_profile" for n in g["nodes"])


def test_dedup_same_disease_single_node():
    g = extract_graph_from_report(_report(), disease_name="MRSA")
    disease_nodes = [n for n in g["nodes"] if n["node_type"] == "disease"]
    assert len(disease_nodes) == 1


def test_handles_sparse_report_without_crashing():
    g = extract_graph_from_report({"idea_submitted": "x", "product_type": "other"})
    assert any(n["node_type"] == "disease" for n in g["nodes"])
    assert any(n["node_type"] == "modality" for n in g["nodes"])


def test_panel_to_dict_serialization():
    panel = SimpleNamespace(
        error_count=0,
        clinical=SimpleNamespace(mechanism_score=7.5, key_scientific_risks=["off-target"],
                                 recommended_endpoint="28-day mortality",
                                 differentiation_vs_soc="novel target", confidence=0.8),
        regulatory=SimpleNamespace(recommended_pathway="NDA+QIDP", approval_probability_pct=58,
                                   precedent_product="ceftaz-avibactam", expected_timeline_yrs=7.0,
                                   available_designations=["QIDP", "Fast Track"],
                                   top_regulatory_risk="resistance emergence"),
        commercial=SimpleNamespace(annual_price_benchmark_usd=12000, pricing_comparable="Avycaz",
                                   key_payer_barrier="DRG bundling", competitive_moat_score=6.5,
                                   moat_basis="composition patent", yrs_to_peak_revenue=6,
                                   reimbursement_mechanism="DRG+NTAP",
                                   licensing_upfront_range="$5M-$30M", licensing_royalty_range="2%-6%"),
    )
    d = panel_to_dict(panel)
    assert len(d["panels"]) == 3
    names = {p["name"] for p in d["panels"]}
    assert names == {"Clinical Validity", "Regulatory Pathway", "Commercial Viability"}
    reg = next(p for p in d["panels"] if p["name"] == "Regulatory Pathway")
    assert reg["headline_value"] == "58%"
    assert "QIDP" in reg["fields"]["Available designations"]


def test_panel_to_dict_partial():
    panel = SimpleNamespace(error_count=2, clinical=None, regulatory=None,
                            commercial=SimpleNamespace(
                                annual_price_benchmark_usd=0, pricing_comparable="",
                                key_payer_barrier="", competitive_moat_score=5.0,
                                moat_basis="", yrs_to_peak_revenue=5,
                                reimbursement_mechanism=""))
    d = panel_to_dict(panel)
    assert len(d["panels"]) == 1
    assert d["error_count"] == 2
