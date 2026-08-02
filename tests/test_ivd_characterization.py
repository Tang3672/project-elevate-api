"""
Characterization test for _derive_ivd_formula (MoE 'in_vitro_diagnostic').

Locks the EXACT TAM/SAM/SOM the IVD expert produces today, so the refactor that
routes its money-math through the shared PerTestDiagnosticModel primitive can be
proven not to move any number.

Money-math being locked:
  manufacturer_revenue = clfs_rate × 0.60
  tam = annual_tests × manufacturer_revenue
  sam = tam × bass_y5(0.025, 0.350)
  som = sam × market_share          (0.40 first-in-class else 0.25)

Golden values captured from the pre-refactor formula.
Run: pytest tests/test_ivd_characterization.py -v
"""

import pytest

from app.services.market_sizing_derivation_service import _derive_ivd_formula


# (idea, us_prev, signals, tam, sam, som)
CASES = [
    ("ngs next-generation sequencing liquid biopsy panel", 0, {},
     864_000_000.0, 232_446_263.085062, 58_111_565.771265),
    ("pcr molecular diagnostic test", 0, {},
     12_000_000_000.0, 3_228_420_320.625857, 807_105_080.156464),
    ("companion diagnostic cdx biomarker for drug selection", 0, {"is_first_in_class": True},
     85_500_000.0, 23_002_494.784459, 9_200_997.913784),
    ("rapid antigen immunoassay point of care", 0, {"is_poc": True},
     5_399_999_999.999999, 1_452_789_144.281635, 363_197_286.070409),
    ("generic diagnostic assay for some disease", 5_000_000, {},
     900_000_000.0, 242_131_524.046939, 60_532_881.011735),
]


@pytest.mark.parametrize("idea,us_prev,signals,tam,sam,som", CASES)
def test_ivd_tam_sam_som_locked(idea, us_prev, signals, tam, sam, som):
    d = _derive_ivd_formula(idea, "test disease", "other", us_prev, signals=signals)
    assert d.us_tam_usd == pytest.approx(tam)
    assert d.us_sam_usd == pytest.approx(sam)
    assert d.us_som_usd == pytest.approx(som)


def test_ivd_is_test_based_not_patient_based():
    d = _derive_ivd_formula("pcr molecular diagnostic test", "flu", "other", 0, signals={})
    assert "test" in d.steps[0].unit.lower()
