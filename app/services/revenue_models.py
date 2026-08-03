"""
Revenue Models  (Build Spec v3, Part 1)
=======================================
The monetization unit depends on the PRODUCT TYPE, not on a hardcoded
`patients × price` drug formula. This module makes that explicit and testable.

Each revenue model consumes the base quantity that matches its unit — a
`SiteLicenseModel` consumes ADDRESSABLE SITES, never patients — and returns a
fully itemized derivation. `select_revenue_model()` picks the model from the
product type + idea text and, crucially, reports whether the choice was
INFERRED (so the UI can surface it and let the PI override the monetization
unit instead of silently applying the wrong one).

This is the clean, named layer over the existing per-archetype math in
`market_sizing_derivation_service.py`; it reuses that module's classifier so the
two never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict


# ── Monetization units ────────────────────────────────────────────────────────

class MonetizationUnit:
    PER_PATIENT_YEAR = "per patient per year"
    PER_PROCEDURE    = "per procedure"
    PER_SITE_YEAR    = "per site per year (subscription/license)"
    PER_SEAT_YEAR    = "per seat per year"
    PER_MEMBER_YEAR  = "per enrolled patient per year (subscription)"
    PER_TEST         = "per test"
    HYBRID           = "hybrid (capital + recurring)"


# The quantity kind each unit is priced against. Guards against sizing a
# site-license product on a patient count (the Error-2 failure mode).
# NOTE the three software units are deliberately distinct base kinds:
#   sites            → enterprise clinical software (imaging AI, CDS) sold per hospital
#   enrolled_members → per-patient SaMD (DTx / RPM) sold per enrolled patient
#   seats            → clinician-productivity SaaS sold per user login
_BASE_KIND = {
    MonetizationUnit.PER_PATIENT_YEAR: "patients",
    MonetizationUnit.PER_PROCEDURE:    "procedures",
    MonetizationUnit.PER_SITE_YEAR:    "sites",
    MonetizationUnit.PER_SEAT_YEAR:    "seats",
    MonetizationUnit.PER_MEMBER_YEAR:  "enrolled_members",
    MonetizationUnit.PER_TEST:         "tests",
    MonetizationUnit.HYBRID:           "mixed",
}


@dataclass
class SizingOutput:
    tam_usd: float
    sam_usd: float
    som_usd: float
    base_quantity: float          # e.g. addressable sites (NOT patients for site license)
    base_quantity_kind: str       # "patients" | "procedures" | "sites" | "seats" | "tests"
    price_per_unit: float
    monetization_unit: str
    model_name: str
    steps: List[dict] = field(default_factory=list)
    weakest_assumptions: List[str] = field(default_factory=list)
    patients_touched: Optional[int] = None   # informational only; must NOT drive the market

    def to_dict(self) -> dict:
        return {
            "tam_usd": self.tam_usd,
            "sam_usd": self.sam_usd,
            "som_usd": self.som_usd,
            "base_quantity": self.base_quantity,
            "base_quantity_kind": self.base_quantity_kind,
            "price_per_unit": self.price_per_unit,
            "monetization_unit": self.monetization_unit,
            "model_name": self.model_name,
            "steps": self.steps,
            "weakest_assumptions": self.weakest_assumptions,
            "patients_touched": self.patients_touched,
        }


def _weak(source: str) -> bool:
    s = (source or "").lower()
    return ("analyst estimate" in s or "review" in s or "unverified" in s
            or "assume" in s)


# ── Revenue models ────────────────────────────────────────────────────────────

class RevenueModel:
    """Base: name, unit, and the kind of base quantity it prices against."""
    name: str = "RevenueModel"
    monetization_unit: str = ""

    @property
    def base_quantity_kind(self) -> str:
        return _BASE_KIND.get(self.monetization_unit, "unknown")

    def _finish(self, base_qty, price, tam, sam_frac, som_frac, steps, weak,
                patients_touched=None) -> SizingOutput:
        sam = tam * sam_frac
        som = sam * som_frac
        return SizingOutput(
            tam_usd=tam, sam_usd=sam, som_usd=som,
            base_quantity=base_qty, base_quantity_kind=self.base_quantity_kind,
            price_per_unit=price, monetization_unit=self.monetization_unit,
            model_name=self.name, steps=steps, weakest_assumptions=weak,
            patients_touched=patients_touched,
        )


class PerPatientDrugModel(RevenueModel):
    """Drugs / biologics: treated_patients × annual_net_price × duration."""
    name = "PerPatientDrugModel"
    monetization_unit = MonetizationUnit.PER_PATIENT_YEAR

    def size(self, treated_patients: float, annual_net_price: float,
             treatment_duration_years: float = 1.0, *,
             sam_fraction: float = 1.0, som_fraction: float = 0.25,
             price_source: str = "", population_source: str = "") -> SizingOutput:
        tam = float(treated_patients) * float(annual_net_price) * float(treatment_duration_years)
        steps = [
            {"label": "Treated patients (initial indication)", "value": treated_patients,
             "unit": "patients", "source": population_source or "indication funnel"},
            {"label": "Annual net price × duration", "value": annual_net_price * treatment_duration_years,
             "unit": "$/patient", "source": price_source or "pricing benchmark"},
            {"label": "TAM = patients × price × duration", "value": tam, "unit": "$"},
        ]
        weak = [s["label"] for s in steps if _weak(s.get("source", ""))]
        return self._finish(treated_patients, annual_net_price, tam,
                            sam_fraction, som_fraction, steps, weak)


class PerProcedureModel(RevenueModel):
    """Interventional / single-use devices: eligible_procedures × price_per_procedure."""
    name = "PerProcedureModel"
    monetization_unit = MonetizationUnit.PER_PROCEDURE

    def size(self, eligible_procedures_per_year: float, price_per_procedure: float, *,
             sam_fraction: float = 1.0, som_fraction: float = 0.25,
             price_source: str = "", volume_source: str = "") -> SizingOutput:
        tam = float(eligible_procedures_per_year) * float(price_per_procedure)
        steps = [
            {"label": "Eligible procedures / yr", "value": eligible_procedures_per_year,
             "unit": "procedures", "source": volume_source or "CMS procedure volume"},
            {"label": "Device revenue / procedure", "value": price_per_procedure,
             "unit": "$/procedure", "source": price_source or "DRG/CPT reimbursement"},
            {"label": "TAM = procedures × price", "value": tam, "unit": "$"},
        ]
        weak = [s["label"] for s in steps if _weak(s.get("source", ""))]
        return self._finish(eligible_procedures_per_year, price_per_procedure, tam,
                            sam_fraction, som_fraction, steps, weak)


class SiteLicenseModel(RevenueModel):
    """
    Hospital / clinical SOFTWARE (the Error-2 fix): sized by the number of SITES
    that license it × annual license price. NEVER multiplied by patient count.
    Optionally price-tiered by site size.
    """
    name = "SiteLicenseModel"
    monetization_unit = MonetizationUnit.PER_SITE_YEAR

    def size(self, total_us_sites_of_type: float, addressable_fraction: float,
             annual_license_price: float, *, price_tiers: Optional[Dict[str, dict]] = None,
             sam_fraction: float = 1.0, som_fraction: float = 0.25,
             sites_source: str = "", price_source: str = "",
             patients_touched: Optional[int] = None) -> SizingOutput:
        addressable_sites = float(total_us_sites_of_type) * float(addressable_fraction)

        if price_tiers:
            # Weighted blend across site-size tiers: {tier: {"fraction":x,"price":y}}
            blended = 0.0
            for tier in price_tiers.values():
                blended += float(tier.get("fraction", 0)) * float(tier.get("price", 0))
            effective_price = blended or annual_license_price
        else:
            effective_price = float(annual_license_price)

        tam = addressable_sites * effective_price
        steps = [
            {"label": "Total US sites of type", "value": total_us_sites_of_type,
             "unit": "sites", "source": sites_source or "AHA Annual Survey"},
            {"label": "Addressable fraction (realistic adopters)", "value": addressable_fraction,
             "unit": "rate", "source": price_source and "analyst estimate — REVIEW" or "analyst estimate — REVIEW"},
            {"label": "Addressable sites", "value": addressable_sites, "unit": "sites"},
            {"label": "Annual license / site", "value": effective_price,
             "unit": "$/site/yr", "source": price_source or "analyst estimate — REVIEW"},
            {"label": "TAM = sites × license (NOT patients × price)", "value": tam, "unit": "$"},
        ]
        weak = [s["label"] for s in steps if _weak(s.get("source", ""))]
        return self._finish(addressable_sites, effective_price, tam,
                            sam_fraction, som_fraction, steps, weak,
                            patients_touched=patients_touched)


class PerSeatSaaSModel(RevenueModel):
    """Clinician-facing SaaS: addressable_clinicians × annual_price_per_seat."""
    name = "PerSeatSaaSModel"
    monetization_unit = MonetizationUnit.PER_SEAT_YEAR

    def size(self, addressable_clinicians: float, annual_price_per_seat: float, *,
             sam_fraction: float = 1.0, som_fraction: float = 0.25,
             seats_source: str = "", price_source: str = "") -> SizingOutput:
        tam = float(addressable_clinicians) * float(annual_price_per_seat)
        steps = [
            {"label": "Addressable clinicians (seats)", "value": addressable_clinicians,
             "unit": "seats", "source": seats_source or "specialty headcount"},
            {"label": "Annual price / seat", "value": annual_price_per_seat,
             "unit": "$/seat/yr", "source": price_source or "analyst estimate — REVIEW"},
            {"label": "TAM = seats × price", "value": tam, "unit": "$"},
        ]
        weak = [s["label"] for s in steps if _weak(s.get("source", ""))]
        return self._finish(addressable_clinicians, annual_price_per_seat, tam,
                            sam_fraction, som_fraction, steps, weak)


class PerMemberSubscriptionModel(RevenueModel):
    """
    Per-PATIENT SaMD (digital therapeutics / remote patient monitoring / digital
    chronic-care): enrolled_patients × annual subscription. This is a genuinely
    different beast from enterprise clinical software —

      • Enterprise (SiteLicenseModel): sold to a HOSPITAL as one per-site license;
        the buyer is IT/procurement; e.g. imaging-AI (Viz.ai), sepsis CDS.
      • Per-patient (this model): sold PER ENROLLED PATIENT/MEMBER, usually to a
        payer/employer PMPM or as a prescription DTx; the unit scales with patients,
        not sites; e.g. Livongo/Omada (diabetes), Pear reSET (DTx), RPM billed via
        CMS CPT 99453/99454/99457.

    Use this ONLY for patient-facing subscription products, never for hospital-
    deployed clinical software (that is SiteLicenseModel).
    """
    name = "PerMemberSubscriptionModel"
    monetization_unit = MonetizationUnit.PER_MEMBER_YEAR

    def size(self, enrolled_patients: float, annual_subscription: float, *,
             sam_fraction: float = 1.0, som_fraction: float = 0.25,
             enrollment_source: str = "", price_source: str = "") -> SizingOutput:
        tam = float(enrolled_patients) * float(annual_subscription)
        steps = [
            {"label": "Addressable enrolled patients / members", "value": enrolled_patients,
             "unit": "enrolled patients", "source": enrollment_source or "digitally-engaged population"},
            {"label": "Annual subscription / patient", "value": annual_subscription,
             "unit": "$/patient/yr", "source": price_source or "PMPM / DTx pricing benchmark"},
            {"label": "TAM = enrolled patients × subscription", "value": tam, "unit": "$"},
        ]
        weak = [s["label"] for s in steps if _weak(s.get("source", ""))]
        return self._finish(enrolled_patients, annual_subscription, tam,
                            sam_fraction, som_fraction, steps, weak)


class PerTestDiagnosticModel(RevenueModel):
    """Diagnostics / companion Dx: eligible_tests_per_year × price_per_test."""
    name = "PerTestDiagnosticModel"
    monetization_unit = MonetizationUnit.PER_TEST

    def size(self, eligible_tests_per_year: float, price_per_test: float, *,
             sam_fraction: float = 1.0, som_fraction: float = 0.25,
             volume_source: str = "", price_source: str = "") -> SizingOutput:
        tam = float(eligible_tests_per_year) * float(price_per_test)
        steps = [
            {"label": "Eligible tests / yr", "value": eligible_tests_per_year,
             "unit": "tests", "source": volume_source or "eligible-population × testing rate"},
            {"label": "Reimbursement / test", "value": price_per_test,
             "unit": "$/test", "source": price_source or "CMS CLFS"},
            {"label": "TAM = tests × price", "value": tam, "unit": "$"},
        ]
        weak = [s["label"] for s in steps if _weak(s.get("source", ""))]
        return self._finish(eligible_tests_per_year, price_per_test, tam,
                            sam_fraction, som_fraction, steps, weak)


class HybridModel(RevenueModel):
    """
    Capital/platform component (per-site) + recurring component (per-procedure /
    per-test). Sums two sub-model outputs into one market.
    """
    name = "HybridModel"
    monetization_unit = MonetizationUnit.HYBRID

    def size(self, capital: SizingOutput, recurring: SizingOutput, *,
             sam_fraction: float = 1.0, som_fraction: float = 0.25) -> SizingOutput:
        tam = capital.tam_usd + recurring.tam_usd
        steps = (
            [{"label": f"Capital component ({capital.model_name})", "value": capital.tam_usd, "unit": "$"}]
            + [{"label": f"Recurring component ({recurring.model_name})", "value": recurring.tam_usd, "unit": "$"}]
            + [{"label": "TAM = capital + recurring", "value": tam, "unit": "$"}]
        )
        weak = capital.weakest_assumptions + recurring.weakest_assumptions
        out = self._finish(capital.base_quantity + recurring.base_quantity, 0.0, tam,
                           sam_fraction, som_fraction, steps, weak)
        return out


# ── Registry + selection ──────────────────────────────────────────────────────

_MODELS = {
    "PerPatientDrugModel":        PerPatientDrugModel,
    "PerProcedureModel":          PerProcedureModel,
    "SiteLicenseModel":           SiteLicenseModel,
    "PerSeatSaaSModel":           PerSeatSaaSModel,
    "PerMemberSubscriptionModel": PerMemberSubscriptionModel,
    "PerTestDiagnosticModel":     PerTestDiagnosticModel,
    "HybridModel":                HybridModel,
}


@dataclass
class RevenueModelSelection:
    model_name: str
    monetization_unit: str
    base_quantity_kind: str
    model_was_inferred: bool          # True → the unit was guessed, not explicit
    needs_confirmation: bool          # True → surface a "how is this sold?" prompt
    confirmation_question: Optional[str]
    confirmation_options: List[str]
    alternatives: List[str]           # other plausible models the PI could switch to
    rationale: str
    archetype: str                    # underlying market_sizing_derivation_service archetype

    def instantiate(self) -> RevenueModel:
        return _MODELS[self.model_name]()

    def to_dict(self) -> dict:
        return {
            "model_name": self.model_name,
            "monetization_unit": self.monetization_unit,
            "base_quantity_kind": self.base_quantity_kind,
            "model_was_inferred": self.model_was_inferred,
            "needs_confirmation": self.needs_confirmation,
            "confirmation_question": self.confirmation_question,
            "confirmation_options": self.confirmation_options,
            "alternatives": self.alternatives,
            "rationale": self.rationale,
            "archetype": self.archetype,
        }


# Product types whose monetization unit is unambiguous — no confirm needed.
_EXPLICIT_UNIT = {
    "drug_small_molecule":   "PerPatientDrugModel",
    "biologic":              "PerPatientDrugModel",
    "gene_cell_therapy":     "PerPatientDrugModel",
    "gene_therapy":          "PerPatientDrugModel",
    "vaccine_immunotherapy": "PerPatientDrugModel",
    "antibiotic":            "PerPatientDrugModel",
    "oncology_drug":         "PerPatientDrugModel",
    "orphan_drug":           "PerPatientDrugModel",
    "diagnostic":            "PerTestDiagnosticModel",
}

_CONFIRM_QUESTION = "How is this sold?"
_CONFIRM_OPTIONS = [
    "per patient (drug/therapy course)",
    "per enrolled patient (app subscription / remote monitoring)",
    "per procedure",
    "per hospital site license (enterprise software)",
    "per clinician seat",
    "per test",
]

# archetype (from the derivation classifier) → revenue model when we must infer.
_ARCHETYPE_TO_MODEL = {
    "pharma_small_molecule":   "PerPatientDrugModel",
    "pharma_biologic":         "PerPatientDrugModel",
    "gene_cell_therapy":       "PerPatientDrugModel",
    "vaccine":                 "PerPatientDrugModel",
    "medical_device_surgical": "PerProcedureModel",
    "medical_device_capital":  "SiteLicenseModel",
    "in_vitro_diagnostic":     "PerTestDiagnosticModel",
    "software_samd":           "SiteLicenseModel",
    "combination":             "HybridModel",
}

_CONSUMER_SW = [
    "digital therapeutic", "dtx", "prescription digital", "cbt", "behavioral health app",
    "wellness", "consumer", "direct-to-consumer", "patient app", "self-guided", "at-home",
    "smartphone app", "remote patient monitoring", "remote monitoring", " rpm", "wearable",
]
_SINGLE_USE_DEVICE = [
    "single-use", "disposable", "catheter", "stent", "clot retrieval", "stentriever",
    "aspiration", "guidewire", "balloon", "suture", "implant",
]
_CAPITAL_DEVICE = [
    "imaging", "mri", "ct scan", "ct imaging", "scanner", "robot", "linac", "radiation",
    "capital equipment", "ultrasound system", "angiography suite", "installed base",
]


def select_revenue_model(product_type: str, idea_text: str = "") -> RevenueModelSelection:
    """
    Pick the revenue model (and monetization unit) for a product.

    Returns model_was_inferred=True whenever the unit was guessed rather than
    dictated by an unambiguous product type — the UI must then surface the choice
    and offer an override (`needs_confirmation`). This prevents silently sizing a
    hospital-software product per-patient.
    """
    pt = (product_type or "").strip().lower()
    idea_l = (idea_text or "").lower()

    # Reuse the derivation service's classifier so the two layers never disagree.
    try:
        from app.services.market_sizing_derivation_service import _classify_archetype
        archetype = _classify_archetype(idea_text or "", product_type or "")
    except Exception:
        archetype = _ARCHETYPE_TO_MODEL_default_archetype(pt)

    # 1) Unambiguous product types → explicit, no confirmation.
    if pt in _EXPLICIT_UNIT:
        model_name = _EXPLICIT_UNIT[pt]
        return _selection(model_name, archetype, inferred=False, needs_confirm=False,
                          rationale=f"'{product_type}' has an unambiguous monetization unit.")

    # 2) Device: default per-procedure, but capital/site is plausible → confirm.
    if pt in ("medical_device", "device"):
        if any(k in idea_l for k in _CAPITAL_DEVICE):
            model_name, alt = "SiteLicenseModel", ["PerProcedureModel"]
            why = "idea implies capital equipment (installed base × ASP / site)."
        else:
            model_name, alt = "PerProcedureModel", ["SiteLicenseModel", "HybridModel"]
            why = "default per-procedure for interventional device; capital equipment is the alternative."
        return _selection(model_name, archetype, inferred=True, needs_confirm=True,
                          rationale=why, alternatives=alt)

    # 3) Software / digital health / platform. Three DISTINCT monetization shapes:
    #    - patient-facing DTx/RPM  → PerMemberSubscriptionModel (per enrolled patient)
    #    - hospital clinical software → SiteLicenseModel        (per hospital site)
    #    - clinician-productivity SaaS → PerSeatSaaSModel        (per user seat, alt)
    if pt in ("digital_health", "software", "other_platform", "samd"):
        if any(k in idea_l for k in _CONSUMER_SW):
            model_name = "PerMemberSubscriptionModel"
            alt = ["PerSeatSaaSModel", "SiteLicenseModel"]
            why = ("patient-facing DTx / remote-monitoring / digital chronic-care → sold "
                   "PER ENROLLED PATIENT (PMPM / prescription DTx), NOT per hospital site.")
        else:
            model_name = "SiteLicenseModel"
            alt = ["PerMemberSubscriptionModel", "PerSeatSaaSModel"]
            why = ("hospital-deployed clinical software (imaging AI, CDS, triage) → per-site "
                   "hospital license, NOT per patient.")
        return _selection(model_name, archetype, inferred=True, needs_confirm=True,
                          rationale=why, alternatives=alt)

    # 4) Unknown / empty product type → infer from archetype, always confirm.
    model_name = _ARCHETYPE_TO_MODEL.get(archetype, "PerPatientDrugModel")
    return _selection(model_name, archetype, inferred=True, needs_confirm=True,
                      rationale=f"product type unspecified; inferred '{archetype}' from idea text.",
                      alternatives=[m for m in _MODELS if m != model_name][:3])


def _selection(model_name, archetype, *, inferred, needs_confirm, rationale,
               alternatives=None) -> RevenueModelSelection:
    unit = _MODELS[model_name]().monetization_unit
    return RevenueModelSelection(
        model_name=model_name,
        monetization_unit=unit,
        base_quantity_kind=_BASE_KIND.get(unit, "unknown"),
        model_was_inferred=inferred,
        needs_confirmation=needs_confirm,
        confirmation_question=_CONFIRM_QUESTION if needs_confirm else None,
        confirmation_options=_CONFIRM_OPTIONS if needs_confirm else [],
        alternatives=alternatives or [],
        rationale=rationale,
        archetype=archetype,
    )


def _ARCHETYPE_TO_MODEL_default_archetype(pt: str) -> str:
    """Fallback archetype if the derivation classifier import fails."""
    return {
        "medical_device": "medical_device_surgical",
        "diagnostic": "in_vitro_diagnostic",
        "digital_health": "software_samd",
        "software": "software_samd",
    }.get(pt, "pharma_small_molecule")


def model_by_name(name: str) -> Optional[RevenueModel]:
    cls = _MODELS.get(name)
    return cls() if cls else None
