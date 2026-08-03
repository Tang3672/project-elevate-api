"""
Characterization test for _derive_pharma_formula (MoE 'pharma_small_molecule'
/ 'pharma_biologic') — the most intricate expert.

Locks the EXACT TAM/SAM/SOM so the refactor that routes its money-math through
the shared PerPatientDrugModel primitive can be proven not to move any number.
The DisMod cascade (prevalence × diagnostic yield × treatment eligibility),
gross-to-net pricing, DoT, Bass diffusion, BLP entry share, and the $200B TAM
cap all stay with the expert; only the eligible-patients × price → tam → sam →
som arithmetic is delegated.

The cardiovascular case deliberately triggers the $200B cap (locks that path).
Golden values captured from the pre-refactor formula.
Run: pytest tests/test_pharma_characterization.py -v
"""

import pytest

from app.services.market_sizing_derivation_service import _derive_pharma_formula


# (idea, disease, ta, us_prev, archetype, signals, tam, sam, som)
CASES = [
    ("kinase inhibitor for lung cancer", "lung cancer", "oncology", 0,
     "pharma_small_molecule", {"is_oncology": True, "has_biomarker": True},
     4_089_657_600.0, 1_267_036_316.1101, 633_518_158.0551),
    ("IV antibiotic for CRE infection", "CRE", "amr_infectious", 0,
     "pharma_small_molecule", {"is_amr": True, "is_iv": True},
     2_695_680_000.0, 160_110_556.8551, 56_038_694.8993),
    ("monoclonal antibody for RA", "rheumatoid arthritis", "immunology", 0,
     "pharma_biologic", {"is_first_in_class": True},
     3_407_616_000.0, 950_412_017.3977, 570_247_210.4386),
    # cap case: TAM pinned to exactly $200B
    ("small molecule for common chronic disease", "hypertension", "cardiovascular",
     100_000_000, "pharma_small_molecule", {},
     200_000_000_000, 29_265_381_665.2804, 10_242_883_582.8482),
]


@pytest.mark.parametrize("idea,dn,ta,pop,arch,signals,tam,sam,som", CASES)
def test_pharma_tam_sam_som_locked(idea, dn, ta, pop, arch, signals, tam, sam, som):
    d = _derive_pharma_formula(idea, dn, ta, pop, arch, signals=signals)
    assert d.us_tam_usd == pytest.approx(tam, rel=1e-9)
    assert d.us_sam_usd == pytest.approx(sam, rel=1e-9)
    assert d.us_som_usd == pytest.approx(som, rel=1e-9)


def test_pharma_cap_holds_at_200b():
    d = _derive_pharma_formula("small molecule for common chronic disease", "hypertension",
                               "cardiovascular", 100_000_000, "pharma_small_molecule", signals={})
    assert d.us_tam_usd == pytest.approx(200_000_000_000, rel=1e-9)


def test_pharma_is_patient_based():
    d = _derive_pharma_formula("kinase inhibitor for lung cancer", "lung cancer", "oncology",
                               0, "pharma_small_molecule", signals={})
    assert "patient" in d.steps[0].unit.lower()
