"""Part D Revised — dimension registry tests (spec D.7)."""
import pytest
from app.services.dimensions import DIMENSION_REGISTRY, Dimension, DimensionFamily
from app.services.dimension_selection import get_candidates, selects, build_dimension_report, DimensionReport
from app.services.denominator_sources import VALID_SOURCES, validate_denominator, buyer_persona

# ── Fixtures ──────────────────────────────────────────────────────────────────

THERAPEUTIC_CLASS = {"archetype": "biologic", "domain": "LIFE_SCIENCES_CLINICAL"}
RESEARCH_CLASS    = {"archetype": "research_tool", "domain": "LIFE_SCIENCES_RESEARCH"}
DIAGNOSTIC_CLASS  = {"archetype": "diagnostic", "domain": "LIFE_SCIENCES_CLINICAL"}

CLINICAL_INTAKE    = {"domain": "LIFE_SCIENCES_CLINICAL", "therapeutic_area": "oncology"}
RESEARCH_INTAKE    = {"domain": "LIFE_SCIENCES_RESEARCH", "therapeutic_area": ""}
DIAGNOSTIC_INTAKE  = {"domain": "LIFE_SCIENCES_CLINICAL", "therapeutic_area": "oncology"}

_RESEARCH_CELLS = [
    {"funding_agency":"NIH",        "award_size_band":"large",  "current_solution":"manual",    "adoption":0.22},
    {"funding_agency":"NIH",        "award_size_band":"mid",    "current_solution":"diy_scripts","adoption":0.15},
    {"funding_agency":"NIH",        "award_size_band":"small",  "current_solution":"manual",    "adoption":0.08},
    {"funding_agency":"NSF",        "award_size_band":"large",  "current_solution":"commercial","adoption":0.11},
    {"funding_agency":"NSF",        "award_size_band":"mid",    "current_solution":"manual",    "adoption":0.09},
    {"funding_agency":"NSF",        "award_size_band":"small",  "current_solution":"none",      "adoption":0.05},
    {"funding_agency":"DoD",        "award_size_band":"large",  "current_solution":"manual",    "adoption":0.17},
    {"funding_agency":"Foundation", "award_size_band":"mid",    "current_solution":"diy_scripts","adoption":0.07},
    {"funding_agency":"Industry",   "award_size_band":"large",  "current_solution":"commercial","adoption":0.06},
]

_CLINICAL_CELLS = [
    {"payer_type":"commercial","line_of_therapy":"1L","site_of_care":"academic",  "adoption":0.35},
    {"payer_type":"commercial","line_of_therapy":"2L","site_of_care":"community", "adoption":0.28},
    {"payer_type":"medicare",  "line_of_therapy":"1L","site_of_care":"academic",  "adoption":0.20},
    {"payer_type":"medicare",  "line_of_therapy":"2L","site_of_care":"community", "adoption":0.14},
    {"payer_type":"medicaid",  "line_of_therapy":"1L","site_of_care":"community", "adoption":0.09},
    {"payer_type":"medicaid",  "line_of_therapy":"3L+","site_of_care":"academic", "adoption":0.05},
]

_DIAGNOSTIC_CELLS = [
    {"lab_type":"hospital",  "procedure_volume":"high",  "coverage_status":"covered",    "adoption":0.40},
    {"lab_type":"hospital",  "procedure_volume":"medium","coverage_status":"covered",    "adoption":0.30},
    {"lab_type":"reference", "procedure_volume":"high",  "coverage_status":"covered",    "adoption":0.25},
    {"lab_type":"physician", "procedure_volume":"low",   "coverage_status":"coverage_gap","adoption":0.10},
    {"lab_type":"physician", "procedure_volume":"low",   "coverage_status":"not_covered","adoption":0.05},
]


def _generate(cls: dict, intake: dict, cells: list) -> DimensionReport:
    return build_dimension_report(cls, intake, cells=cells)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_dimension_registry_is_open():
    assert isinstance(DIMENSION_REGISTRY, dict)
    assert len(DIMENSION_REGISTRY) > 0
    for dim_id, dim in DIMENSION_REGISTRY.items():
        assert isinstance(dim, Dimension)
        assert dim.id == dim_id
        assert isinstance(dim.family, DimensionFamily)
        assert callable(dim.candidate_when)


def test_candidates_match_buyer():
    for cls, intake in [
        (THERAPEUTIC_CLASS, CLINICAL_INTAKE),
        (RESEARCH_CLASS, RESEARCH_INTAKE),
        (DIAGNOSTIC_CLASS, DIAGNOSTIC_INTAKE),
    ]:
        candidates = get_candidates(cls, intake)
        for dim in candidates:
            assert dim.candidate_when(cls, intake), (
                f"Dimension '{dim.id}' returned as candidate but candidate_when is False "
                f"for archetype='{cls.get('archetype')}'"
            )


def test_denominator_matches_buyer():
    valid, _ = validate_denominator("research_tool", "nih_reporter")
    assert valid

    valid, reason = validate_denominator("biologic", "nih_reporter")
    assert not valid, f"Expected nih_reporter invalid for biologic; got: {reason}"

    valid, reason = validate_denominator("research_tool", "seer")
    assert not valid, f"Expected seer invalid for research_tool; got: {reason}"

    valid, reason = validate_denominator("biologic", "aha_annual_survey")
    assert not valid


def test_rejection_count_reported():
    report = _generate(RESEARCH_CLASS, RESEARCH_INTAKE, _RESEARCH_CELLS)
    assert report.renders_considered_count is True
    assert report.dimensions_considered_count > 0
    assert len(report.dimensions_selected) <= report.dimensions_considered_count
    # Research tool candidates << total registry (payer/clinical dims excluded)
    assert report.dimensions_considered_count < len(DIMENSION_REGISTRY)


def test_dimensions_differ_across_archetypes():
    a = _generate(THERAPEUTIC_CLASS, CLINICAL_INTAKE, _CLINICAL_CELLS)
    b = _generate(RESEARCH_CLASS, RESEARCH_INTAKE, _RESEARCH_CELLS)
    c = _generate(DIAGNOSTIC_CLASS, DIAGNOSTIC_INTAKE, _DIAGNOSTIC_CELLS)

    sets = [frozenset(d["id"] for d in r.dimensions_selected) for r in (a, b, c)]
    # Each archetype must select at least one dimension
    for i, (s, name) in enumerate(zip(sets, ("therapeutic","research_tool","diagnostic"))):
        assert len(s) > 0, f"{name} selected zero dimensions"
    # All three sets must be unique
    unique_sets = {s for s in sets}
    assert len(unique_sets) == 3, (
        f"Two archetypes selected identical dimensions:\n"
        f"  therapeutic:   {sets[0]}\n"
        f"  research_tool: {sets[1]}\n"
        f"  diagnostic:    {sets[2]}"
    )
