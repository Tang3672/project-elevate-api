"""
Tests for the revenue-model abstraction (Build Spec v3, Part 6).

Verifies the two structural fixes:
  - the monetization UNIT is selected from product type (not hardcoded per-patient)
  - a SiteLicenseModel sizes on SITES, never on patient count
  - ambiguous device/software choices are flagged model_was_inferred=True

Pure unit tests — no DB, no network.
Run: pytest tests/test_revenue_models.py -v
"""

import pytest

from app.services.revenue_models import (
    select_revenue_model, MonetizationUnit,
    PerPatientDrugModel, PerProcedureModel, SiteLicenseModel,
    PerSeatSaaSModel, PerMemberSubscriptionModel, PerTestDiagnosticModel, HybridModel,
)


# ── selection ─────────────────────────────────────────────────────────────────

def test_hospital_software_selects_site_license_not_per_patient():
    sel = select_revenue_model(
        "digital_health",
        "AI sepsis early-warning clinical decision support deployed across hospital ICUs")
    assert sel.model_name == "SiteLicenseModel"
    assert sel.monetization_unit == MonetizationUnit.PER_SITE_YEAR
    assert sel.base_quantity_kind == "sites"
    assert sel.base_quantity_kind != "patients"


def test_drug_selects_per_patient_and_is_not_inferred():
    sel = select_revenue_model("drug_small_molecule", "oral small molecule for ischemic stroke")
    assert sel.model_name == "PerPatientDrugModel"
    assert sel.monetization_unit == MonetizationUnit.PER_PATIENT_YEAR
    assert sel.model_was_inferred is False
    assert sel.needs_confirmation is False


def test_diagnostic_selects_per_test():
    sel = select_revenue_model("diagnostic", "companion Dx blood test for KRAS mutation")
    assert sel.model_name == "PerTestDiagnosticModel"
    assert sel.monetization_unit == MonetizationUnit.PER_TEST


def test_ambiguous_software_flags_inferred_and_confirmation():
    sel = select_revenue_model("digital_health", "clinical analytics platform")
    assert sel.model_was_inferred is True
    assert sel.needs_confirmation is True
    assert sel.confirmation_question and sel.confirmation_options
    assert "SiteLicenseModel" in [sel.model_name, *sel.alternatives]


def test_consumer_dtx_selects_per_member_subscription():
    sel = select_revenue_model("digital_health",
                               "direct-to-consumer smartphone app wearable for wellness")
    assert sel.model_name == "PerMemberSubscriptionModel"
    assert sel.monetization_unit == MonetizationUnit.PER_MEMBER_YEAR
    assert sel.base_quantity_kind == "enrolled_members"
    assert sel.model_was_inferred is True


def test_enterprise_and_per_patient_samd_are_distinct():
    # the two SaMD shapes must never collapse to the same model / unit / base
    enterprise = select_revenue_model(
        "digital_health", "AI imaging triage clinical decision support for hospital radiology")
    per_patient = select_revenue_model(
        "digital_health", "prescription digital therapeutic dtx app for patients at home")
    assert enterprise.model_name == "SiteLicenseModel"
    assert per_patient.model_name == "PerMemberSubscriptionModel"
    assert enterprise.base_quantity_kind == "sites"
    assert per_patient.base_quantity_kind == "enrolled_members"
    assert enterprise.monetization_unit != per_patient.monetization_unit


def test_per_member_subscription_math():
    out = PerMemberSubscriptionModel().size(enrolled_patients=12_000_000,
                                            annual_subscription=600)
    assert out.base_quantity_kind == "enrolled_members"
    assert out.tam_usd == pytest.approx(12_000_000 * 600)
    # distinct from a per-site license base
    assert out.base_quantity_kind != "sites"


def test_device_defaults_per_procedure_but_confirms():
    sel = select_revenue_model("medical_device", "single-use thrombectomy clot-retrieval catheter")
    assert sel.model_name == "PerProcedureModel"
    assert sel.needs_confirmation is True
    assert "SiteLicenseModel" in sel.alternatives


def test_capital_device_selects_site_license():
    sel = select_revenue_model("medical_device", "MRI imaging capital equipment scanner")
    assert sel.model_name == "SiteLicenseModel"


def test_unknown_product_type_infers_and_confirms():
    sel = select_revenue_model("", "some novel platform")
    assert sel.model_was_inferred is True
    assert sel.needs_confirmation is True


# ── model math ────────────────────────────────────────────────────────────────

def test_site_license_math_uses_sites_not_patients():
    out = SiteLicenseModel().size(
        total_us_sites_of_type=6000, addressable_fraction=0.30,
        annual_license_price=80000, som_fraction=0.25)
    # 6000 * 0.30 = 1800 sites; × 80000 = 144,000,000
    assert out.base_quantity == pytest.approx(1800)
    assert out.base_quantity_kind == "sites"
    assert out.tam_usd == pytest.approx(144_000_000)
    # the market number is exactly sites × price — no patient term enters it
    assert out.tam_usd == pytest.approx(out.base_quantity * out.price_per_unit)
    assert out.monetization_unit == MonetizationUnit.PER_SITE_YEAR


def test_site_license_patients_touched_is_informational_only():
    out = SiteLicenseModel().size(
        total_us_sites_of_type=300, addressable_fraction=0.5,
        annual_license_price=100000, patients_touched=500000)
    # patients_touched does not enter the market number
    assert out.patients_touched == 500000
    assert out.tam_usd == pytest.approx(150 * 100000)


def test_site_license_price_tiers_blend():
    out = SiteLicenseModel().size(
        total_us_sites_of_type=1000, addressable_fraction=1.0, annual_license_price=0,
        price_tiers={
            "academic":  {"fraction": 0.2, "price": 200000},
            "community": {"fraction": 0.8, "price": 50000},
        })
    # blended price = 0.2*200k + 0.8*50k = 80k; × 1000 sites
    assert out.price_per_unit == pytest.approx(80000)
    assert out.tam_usd == pytest.approx(80_000_000)


def test_per_patient_drug_math():
    out = PerPatientDrugModel().size(treated_patients=138000, annual_net_price=20000,
                                     treatment_duration_years=1.0)
    assert out.base_quantity_kind == "patients"
    assert out.tam_usd == pytest.approx(138000 * 20000)


def test_per_procedure_math():
    out = PerProcedureModel().size(eligible_procedures_per_year=110000, price_per_procedure=8000)
    assert out.base_quantity_kind == "procedures"
    assert out.tam_usd == pytest.approx(110000 * 8000)


def test_per_test_math():
    out = PerTestDiagnosticModel().size(eligible_tests_per_year=250000, price_per_test=3000)
    assert out.base_quantity_kind == "tests"
    assert out.tam_usd == pytest.approx(250000 * 3000)


def test_per_seat_math():
    out = PerSeatSaaSModel().size(addressable_clinicians=12000, annual_price_per_seat=1200)
    assert out.base_quantity_kind == "seats"
    assert out.tam_usd == pytest.approx(12000 * 1200)


def test_hybrid_sums_capital_and_recurring():
    capital = SiteLicenseModel().size(total_us_sites_of_type=300, addressable_fraction=1.0,
                                      annual_license_price=100000)
    recurring = PerProcedureModel().size(eligible_procedures_per_year=50000, price_per_procedure=500)
    out = HybridModel().size(capital, recurring)
    assert out.tam_usd == pytest.approx(capital.tam_usd + recurring.tam_usd)


def test_selection_instantiates_matching_base_kind():
    # compute_market invariant: base quantity kind matches the model unit
    for pt, expect_kind in [
        ("drug_small_molecule", "patients"),
        ("diagnostic", "tests"),
        ("digital_health", "sites"),
    ]:
        sel = select_revenue_model(pt, "hospital clinical tool")
        model = sel.instantiate()
        assert model.base_quantity_kind == sel.base_quantity_kind
        if not sel.model_was_inferred:
            assert sel.base_quantity_kind == expect_kind
