"""
tam_calculator.py — Bottom-up TAM by disease category.

Each formula matches the commercial economics of its product type:

  drug_prevalence  — chronic disease drug (price × treated population)
  drug_incidence   — cancer / acute drug (price per course × annual cases)
  gene_therapy     — one-time curative treatment (annual eligible cohort × price)
  amr_antibiotic   — antibiotic priced per hospital course
  device           — SaaS/hardware (facility contract or per-patient annual cost)
  vaccine          — immunisation economics (population × coverage × dose price)

Returns:
  us_tam_usd        — 100% market capture (theoretical ceiling)
  peak_revenue_usd  — realistic Year-5 revenue at stated peak_penetration
  formula           — which formula was applied
"""

import json
import logging
import pathlib
from typing import Optional

logger = logging.getLogger(__name__)

_DATA_PATH = pathlib.Path(__file__).parent.parent / "data" / "tam_parameters.json"


def _load_params() -> dict:
    try:
        return json.loads(_DATA_PATH.read_text())["diseases"]
    except Exception as e:
        logger.warning("TAM parameters file not loaded: %s", e)
        return {}


_PARAMS: dict = _load_params()


# ── Formula implementations ───────────────────────────────────────────────────

def _drug_prevalence(p: dict) -> dict:
    tam = (
        p["prevalent_patients"]
        * p["diagnosis_rate"]
        * p["treatment_rate"]
        * p["novel_eligible_fraction"]
        * p["price_per_year_usd"]
        * p["net_price_factor"]
    )
    return {"us_tam_usd": tam, "peak_revenue_usd": tam * p["peak_penetration"], "formula": "drug_prevalence"}


def _drug_incidence(p: dict) -> dict:
    tam = (
        p["annual_incidence"]
        * p["treatment_rate"]
        * p["novel_eligible_fraction"]
        * p["price_per_course_usd"]
        * p["net_price_factor"]
    )
    return {"us_tam_usd": tam, "peak_revenue_usd": tam * p["peak_penetration"], "formula": "drug_incidence"}


def _gene_therapy(p: dict) -> dict:
    # Steady-state annual cohort × one-time treatment price
    tam = p["annual_eligible_cohort"] * p["price_per_treatment_usd"] * p["net_price_factor"]
    return {"us_tam_usd": tam, "peak_revenue_usd": tam * p["peak_penetration"], "formula": "gene_therapy"}


def _amr_antibiotic(p: dict) -> dict:
    tam = (
        p["annual_incidence"]
        * p["novel_eligible_fraction"]
        * p["price_per_course_usd"]
        * p["net_price_factor"]
    )
    return {"us_tam_usd": tam, "peak_revenue_usd": tam * p["peak_penetration"], "formula": "amr_antibiotic"}


def _device(p: dict) -> dict:
    if "target_facilities" in p:
        tam = p["target_facilities"] * p["adoption_rate"] * p["annual_contract_per_facility_usd"]
    else:
        tam = (
            p["addressable_patients"]
            * p["adoption_rate"]
            * p["annual_cost_per_patient_usd"]
            * p["net_price_factor"]
        )
    return {"us_tam_usd": tam, "peak_revenue_usd": tam * p["peak_penetration"], "formula": "device"}


def _vaccine(p: dict) -> dict:
    tam = (
        p["target_population"]
        * p["vaccination_rate"]
        * p["doses_per_series"]
        * p["price_per_dose_usd"]
        * p["net_price_factor"]
    )
    return {"us_tam_usd": tam, "peak_revenue_usd": tam * p["peak_penetration"], "formula": "vaccine"}


_FORMULA_MAP = {
    "drug_prevalence": _drug_prevalence,
    "drug_incidence":  _drug_incidence,
    "gene_therapy":    _gene_therapy,
    "amr_antibiotic":  _amr_antibiotic,
    "device":          _device,
    "vaccine":         _vaccine,
}


# ── Public API ────────────────────────────────────────────────────────────────

def calculate_tam(disease: str, fallback_population: int = 0, fallback_price: float = 0) -> Optional[dict]:
    """
    Calculate bottom-up TAM for a disease using its expert parameters.

    Returns a dict with:
      us_tam_usd        — total addressable market (USD)
      peak_revenue_usd  — realistic Year-5 revenue
      formula           — formula used
      pricing_rationale — brief justification

    Returns None if no parameters exist for this disease.
    """
    params = _PARAMS.get(disease)
    if not params:
        logger.debug("No TAM parameters for '%s'; using fallback", disease)
        if fallback_population and fallback_price:
            peak_sales = fallback_population * 0.05 * fallback_price * 0.55
            return {
                "us_tam_usd": peak_sales / 0.05,
                "peak_revenue_usd": peak_sales,
                "formula": "generic_fallback",
                "pricing_rationale": "Generic fallback: 5% penetration × population × price × 0.55 net price",
            }
        return None

    formula_fn = _FORMULA_MAP.get(params["formula"])
    if not formula_fn:
        logger.warning("Unknown formula '%s' for '%s'", params["formula"], disease)
        return None

    result = formula_fn(params)
    result["pricing_rationale"] = params.get("pricing_rationale", "")
    result["peak_penetration"] = params.get("peak_penetration", 0)
    return result


def format_tam(usd: float) -> str:
    """Format a dollar amount as '$XB', '$XM', or '$XK'."""
    if usd >= 1e9:
        return f"${usd / 1e9:.1f}B"
    if usd >= 1e6:
        return f"${usd / 1e6:.0f}M"
    return f"${usd / 1e3:.0f}K"
