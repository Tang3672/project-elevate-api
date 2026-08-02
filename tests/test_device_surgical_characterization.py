"""
Characterization test for _derive_device_surgical_formula (MoE 'medical_device_surgical').

Locks the EXACT TAM/SAM/SOM the surgical-device expert produces today, so the
refactor that routes its money-math through the shared PerProcedureModel
primitive can be proven not to move any number.

Money-math being locked:
  device_revenue = drg_payment × device_cost_fraction
  tam = annual_procedures × device_revenue
  sam = tam × bass_y5(p,q)          (p bumped 1.30× if first-in-class)
  som = sam × market_share          (0.30 first-in-class else 0.20)

Golden values captured from the pre-refactor formula.
Run: pytest tests/test_device_surgical_characterization.py -v
"""

import pytest

from app.services.market_sizing_derivation_service import _derive_device_surgical_formula


# (idea, us_prev, is_first_in_class, tam, sam, som)
CASES = [
    ("spinal fusion implant device", 0, False,
     6_776_000_000.0, 653_711_717.237968, 130_742_343.447594),
    ("cardiac stent pacemaker device", 0, False,
     13_229_999_999.999998, 1_276_358_621.466694, 255_271_724.293339),
    ("cochlear hearing implant", 0, False,
     2_145_000_000.0, 206_937_962.437344, 41_387_592.487469),
    ("knee hip joint replacement orthopedic implant", 0, True,
     9_680_000_000.0, 1_190_886_361.247889, 357_265_908.374367),
    ("generic surgical device widget", 800_000, False,
     500_000_000.0, 48_237_287.281432, 9_647_457.456286),
]


@pytest.mark.parametrize("idea,us_prev,fic,tam,sam,som", CASES)
def test_device_surgical_tam_sam_som_locked(idea, us_prev, fic, tam, sam, som):
    d = _derive_device_surgical_formula(
        idea, "test disease", "other", us_prev, signals={"is_first_in_class": fic})
    assert d.us_tam_usd == pytest.approx(tam)
    assert d.us_sam_usd == pytest.approx(sam)
    assert d.us_som_usd == pytest.approx(som)


def test_device_is_procedure_based_not_patient_based():
    d = _derive_device_surgical_formula(
        "spinal fusion implant device", "back pain", "other", 0, signals={})
    assert "procedure" in d.steps[0].unit.lower()
