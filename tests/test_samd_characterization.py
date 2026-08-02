"""
Characterization test for _derive_samd_formula (MoE 'software_samd' expert).

Locks the EXACT TAM/SAM/SOM the SaMD expert produces today, so the incremental
refactor that routes its enterprise money-math through the shared SiteLicenseModel
primitive can be proven not to move any number. If a value here changes, the
refactor changed behavior — that's a failure, not an update.

Golden values computed from the pre-refactor formula:
  enterprise: tam = sites × license; sam = tam × 0.30; som = sam × 0.25
  per-patient: tam = patients × fee;  sam = tam × 0.25; som = sam × 0.15

Run: pytest tests/test_samd_characterization.py -v
"""

import pytest

from app.services.market_sizing_derivation_service import _derive_samd_formula


# (idea, us_prev, tam, sam, som)
CASES = [
    # ── enterprise site-license branches (the slice being refactored) ──
    ("AI radiology imaging triage for suspected stroke in hospital PACS",
     700_000, 720_000_000, 216_000_000, 54_000_000),          # 6000 × 120k
    ("AI sepsis early-warning system for hospital ICU critical care",
     500_000, 480_000_000, 144_000_000, 36_000_000),          # 6000 × 80k
    ("clinical decision support cds tool deployed to hospitals",
     500_000, 480_000_000, 144_000_000, 36_000_000),          # 8000 × 60k
    ("hospital enterprise clinical workflow software platform",
     500_000, 375_000_000, 112_500_000, 28_125_000),          # 5000 × 75k
    # ── per-patient branches ──
    ("direct-to-consumer wellness smartphone app for diabetes glucose",
     500_000, 7_200_000_000, 1_800_000_000, 270_000_000),     # 12M × 600
    ("direct-to-consumer mental health behavioral depression cbt app",
     0, 1_500_000_000, 375_000_000, 56_250_000),              # 5M × 300
    ("consumer wearable remote monitoring rpm continuous app",
     0, 6_400_000_000, 1_600_000_000, 240_000_000),           # 8M × 800
    ("consumer self-guided at-home app for some condition",
     1_000_000, 80_000_000, 20_000_000, 3_000_000),           # (1M//5) × 400
]


@pytest.mark.parametrize("idea,us_prev,tam,sam,som", CASES)
def test_samd_tam_sam_som_locked(idea, us_prev, tam, sam, som):
    d = _derive_samd_formula(idea, "test disease", "other", us_prev, signals={})
    assert d.us_tam_usd == pytest.approx(tam)
    assert d.us_sam_usd == pytest.approx(sam)
    assert d.us_som_usd == pytest.approx(som)


def test_enterprise_stays_site_based_not_patient_based():
    d = _derive_samd_formula(
        "AI sepsis early-warning for hospital ICU", "sepsis", "other", 500_000, signals={})
    # Step 1 base unit must be sites, never a patient count
    assert "site" in d.steps[0].unit.lower()
    assert d.us_tam_usd == pytest.approx(480_000_000)
