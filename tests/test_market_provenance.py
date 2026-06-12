"""
Unit tests for the Market Sizing Provenance transform (Priority 1).

Pure transform — no DB, no API key. Uses a lightweight stand-in for
MarketSizingDerivation (the real one is a dataclass; build_provenance is
duck-typed so a SimpleNamespace works).

Run with: pytest tests/test_market_provenance.py -v
"""

from types import SimpleNamespace

from app.services.market_provenance_service import (
    build_provenance,
    build_scenarios,
    _classify_assumption_type,
    _classify_formula_role,
    _confidence_for,
)


def _step(num, title, value, unit, formula="", data_source="", url="", assumptions=None):
    return SimpleNamespace(
        step_num=num, title=title, value=value, unit=unit, formula=formula,
        source_paper="", source_url=url, explanation="why",
        data_source=data_source, assumptions=assumptions or [],
    )


def _deriv():
    return SimpleNamespace(
        idea="novel antibiotic for MRSA",
        archetype="pharma_small_molecule",
        archetype_label="Small Molecule Drug",
        formula_name="Bottom-up pharma TAM",
        formula_overview="prevalence x price x penetration",
        steps=[
            _step(1, "US prevalence of serious MRSA infections", 119247, "patients",
                  data_source="CDC AR Threats 2019", url="https://cdc.gov/ar"),
            _step(2, "Diagnosed and hospitalized fraction", 0.85, "ratio",
                  data_source="SEER", url="https://seer.cancer.gov"),
            _step(3, "Treatment-eligible addressable patients", 80000, "patients",
                  data_source="model", assumptions=["a", "b"]),
            _step(4, "Annual price per course (WAC)", 12000, "USD",
                  data_source="CMS ASP", url="https://cms.gov/asp"),
            _step(5, "Year-1 initial market penetration", 0.05, "percent",
                  data_source="launch comps assumption"),
        ],
        us_tam_usd=960_000_000,
        us_sam_usd=300_000_000,
        us_som_usd=48_000_000,
        tam_fmt="$1.0B", sam_fmt="$300M", som_fmt="$48M",
        key_assumptions=["IV therapy only"],
        confidence_note="moderate",
        primary_citations=[{"source": "NEJM 2022", "url": "https://nejm.org/x", "title": "MRSA burden"}],
    )


def test_assumption_type_classification():
    assert _classify_assumption_type("US prevalence of X", "patients", "") == "prevalence"
    assert _classify_assumption_type("Diagnosed fraction", "ratio", "") == "diagnosis_rate"
    assert _classify_assumption_type("Treatment-eligible patients", "patients", "") == "treatment_rate"
    assert _classify_assumption_type("Annual price per course (WAC)", "USD", "") == "price"
    assert _classify_assumption_type("Year-1 market penetration", "percent", "") == "penetration"


def test_formula_role():
    assert _classify_formula_role("Year-1 initial penetration", "penetration") == "SOM"
    assert _classify_formula_role("Serviceable reachable share", "penetration") == "SAM"
    assert _classify_formula_role("US prevalence", "prevalence") == "TAM"


def test_confidence_authoritative_vs_modeled():
    auth = _confidence_for("https://cdc.gov/ar", "CDC", [])
    modeled = _confidence_for("", "model assumption", ["a", "b"])
    assert auth > modeled
    assert 0.30 <= modeled <= 0.95 and 0.30 <= auth <= 0.95


def test_build_provenance_shape_and_typing():
    prov = build_provenance(_deriv())
    assert set(prov) == {"run", "assumptions", "scenarios", "sources", "waterfall"}

    # one assumption per step, each with the brief's required keys
    assert len(prov["assumptions"]) == 5
    for a in prov["assumptions"]:
        for key in ("assumption_type", "value", "unit", "source_name",
                    "source_url", "confidence", "used_in_formula", "retrieved_at"):
            assert key in a
        assert a["used_in_formula"] in ("TAM", "SAM", "SOM")

    # the price step is typed correctly and the modeled step has lower confidence
    by_label = {a["label"]: a for a in prov["assumptions"]}
    assert by_label["Annual price per course (WAC)"]["assumption_type"] == "price"
    assert by_label["Treatment-eligible addressable patients"]["confidence"] < \
        by_label["US prevalence of serious MRSA infections"]["confidence"]

    # run headline numbers carried through
    assert prov["run"]["tam_usd"] == 960_000_000
    assert prov["run"]["assumption_count"] == 5

    # sources deduped + includes the primary citation
    names = {s["source_name"] for s in prov["sources"]}
    assert "NEJM 2022" in names

    # waterfall ends with the 3 aggregate rows
    aggs = [r for r in prov["waterfall"] if r.get("is_aggregate")]
    assert {r["used_in_formula"] for r in aggs} == {"TAM", "SAM", "SOM"}


def test_scenarios_clamped_and_ordered():
    scns = build_scenarios(tam=1000.0, sam=400.0, som=100.0)
    assert [s["scenario"] for s in scns] == ["conservative", "base", "aggressive"]
    for s in scns:
        # invariant: SOM <= SAM <= TAM in every scenario
        assert s["som_usd"] <= s["sam_usd"] <= s["tam_usd"]
    cons, base, aggr = scns
    assert cons["som_usd"] < base["som_usd"] < aggr["som_usd"]


def test_scenarios_respect_tam_ceiling():
    # aggressive sam_mult would push SAM (900*1.3=1170) above TAM(1000) -> clamp
    scns = build_scenarios(tam=1000.0, sam=900.0, som=800.0)
    aggr = next(s for s in scns if s["scenario"] == "aggressive")
    assert aggr["sam_usd"] == 1000.0           # clamped to TAM
    assert aggr["som_usd"] <= aggr["sam_usd"]  # SOM still clamped to SAM
