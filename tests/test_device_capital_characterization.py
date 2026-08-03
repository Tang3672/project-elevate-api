"""
Characterization test for _derive_device_capital_formula (MoE 'medical_device_capital').

Locks the EXACT TAM/SAM/SOM the capital-equipment expert produces today, so the
refactor that routes its money-math through the shared SiteLicenseModel primitive
(install base × system ASP) can be proven not to move any number.

Money-math being locked:
  tam = sites × asp                    (full install-base value)
  sam = tam × bass_y5(0.015, 0.220)    (p ×1.3 if first-in-class)
  som = sam × share                    (0.30 first-in-class else 0.20)

Golden values captured from the pre-refactor formula.
Run: pytest tests/test_device_capital_characterization.py -v
"""

import pytest

from app.services.market_sizing_derivation_service import _derive_device_capital_formula


# (idea, signals, tam, sam, som)
CASES = [
    ("mri magnetic resonance imaging system", {},
     5_250_000_000.0, 656_262_239.630602, 131_252_447.92612),
    ("surgical robot robotic surgery system", {"is_first_in_class": True},
     4_500_000_000.0, 712_848_311.337351, 213_854_493.401205),
    ("radiation linac radiotherapy proton system", {},
     7_500_000_000.0, 937_517_485.186574, 187_503_497.037315),
    ("ultrasound pocus cart system", {},
     1_200_000_000.0, 150_002_797.629852, 30_000_559.52597),
    ("generic capital imaging equipment", {},
     2_000_000_000.0, 250_004_662.71642, 50_000_932.543284),
]


@pytest.mark.parametrize("idea,signals,tam,sam,som", CASES)
def test_device_capital_tam_sam_som_locked(idea, signals, tam, sam, som):
    d = _derive_device_capital_formula(idea, "test disease", "other", 0, signals=signals)
    assert d.us_tam_usd == pytest.approx(tam)
    assert d.us_sam_usd == pytest.approx(sam)
    assert d.us_som_usd == pytest.approx(som)


def test_capital_is_install_base_based():
    d = _derive_device_capital_formula("mri imaging system", "cancer", "other", 0, signals={})
    assert "facilit" in d.steps[0].unit.lower()  # facilities / install base, not patients
