"""
Monetization Engine  (Build Spec v5, Part C — Engine 2)
========================================================
Applies the correct revenue formula to the correct base unit.

Key invariant: software is NEVER sized on a per-patient basis.
  - SaMD / digital health → site-license model (revenue = sites × license)
  - drug / biologic / gene therapy → revenue = patients × price × persistency
  - device → revenue = procedures × per-procedure price
  - diagnostic → revenue = tests × per-test price

select_revenue_model() from revenue_models.py decides which branch — this engine
wraps it, adds confidence tracking, and prevents silent per-patient application
to software products.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"


@dataclass
class MonetizationResult:
    product_type: str
    revenue_model: str            # "per_patient" | "site_license" | "per_procedure" | "per_test"
    base_unit: str                # "patients" | "sites" | "procedures" | "tests"
    base_count: float
    net_price_usd: float
    annual_revenue_usd: float
    low_revenue_usd: float
    high_revenue_usd: float
    price_source: str
    price_confidence: str
    price_note: str
    assumptions: List[dict]       # fed into confidence_engine

    def to_dict(self) -> dict:
        return {
            "product_type": self.product_type,
            "revenue_model": self.revenue_model,
            "base_unit": self.base_unit,
            "base_count": self.base_count,
            "net_price_usd": self.net_price_usd,
            "annual_revenue_usd": self.annual_revenue_usd,
            "low_revenue_usd": self.low_revenue_usd,
            "high_revenue_usd": self.high_revenue_usd,
            "price_source": self.price_source,
            "price_confidence": self.price_confidence,
            "price_note": self.price_note,
            "assumptions": self.assumptions,
        }


# ─── product-type → model mapping ────────────────────────────────────────────

_PER_PATIENT_TYPES = {
    "drug_small_molecule", "biologic", "gene_cell_therapy",
    "drug", "biologic_drug", "gene_therapy", "cell_therapy",
    "drug_oncology", "drug_amr", "antibiotic",
}

_SITE_LICENSE_TYPES = {
    "samd", "digital_health_enterprise", "software",
    "clinical_ai", "enterprise_software",
}

_PER_PROCEDURE_TYPES = {
    "medical_device", "device", "surgical_device",
    "interventional_device",
}

_PER_TEST_TYPES = {
    "diagnostic", "companion_diagnostic", "molecular_test", "ivd",
}


def _infer_revenue_model(product_type: str) -> str:
    pt = (product_type or "").lower().strip()
    if pt in _PER_PATIENT_TYPES:
        return "per_patient"
    if pt in _SITE_LICENSE_TYPES:
        return "site_license"
    if pt in _PER_PROCEDURE_TYPES:
        return "per_procedure"
    if pt in _PER_TEST_TYPES:
        return "per_test"
    # Try partial match
    if any(k in pt for k in ("drug", "biologic", "therapy", "gene", "cell")):
        return "per_patient"
    if any(k in pt for k in ("software", "samd", "ai", "digital")):
        return "site_license"
    if any(k in pt for k in ("device", "implant", "catheter", "stent")):
        return "per_procedure"
    if any(k in pt for k in ("diagnostic", "test", "assay", "cdx")):
        return "per_test"
    return "per_patient"   # fallback (flagged low-confidence)


def _base_unit_for_model(revenue_model: str) -> str:
    return {
        "per_patient": "patients",
        "site_license": "sites",
        "per_procedure": "procedures",
        "per_test": "tests",
    }.get(revenue_model, "patients")


async def compute(
    product_type: str,
    disease_name: str,
    population: float,             # from patient_flow_engine (raw unit: patients | sites | procedures | tests)
    population_base_metric: str,   # what unit patient_flow_engine returned
    net_price_usd: Optional[float] = None,  # caller override; else look up from DB/JSON
    persistency_months: int = 12,
    overrides: Optional[dict] = None,
) -> MonetizationResult:
    """
    Compute annual revenue given population + product economics.

    If population_base_metric != the required base_unit for this revenue model,
    we flag it as a mismatch (don't silently convert — raise a warning and use
    population as-is with low confidence).
    """
    overrides = overrides or {}
    revenue_model = _infer_revenue_model(product_type)
    base_unit = _base_unit_for_model(revenue_model)

    assumptions: List[dict] = []

    # ── CRITICAL GUARD: never apply per-patient pricing to software ──────────
    if revenue_model == "per_patient" and population_base_metric == "sites":
        logger.error(
            "MONETIZATION MISMATCH: product_type=%s routed to per_patient but "
            "patient_flow returned 'sites'. Switching to site_license.",
            product_type,
        )
        revenue_model = "site_license"
        base_unit = "sites"
        assumptions.append({
            "field": "revenue_model_corrected", "value": "site_license",
            "source_type": "analyst_estimate", "confidence": "low",
            "expert_question": "Confirm product is priced per site license, not per-patient. What is the annual enterprise contract value?",
        })

    base_count = population

    # If patient_flow returned patients but we need a different unit, flag it
    if population_base_metric not in (base_unit, "patients", "sites", "procedures", "tests"):
        assumptions.append({
            "field": "unit_conversion", "value": f"{population_base_metric} → {base_unit}",
            "source_type": "analyst_estimate", "confidence": "low",
            "expert_question": f"Patient flow engine returned '{population_base_metric}' but revenue model expects '{base_unit}'. Are these equivalent for this product?",
        })

    # ── Price lookup ─────────────────────────────────────────────────────────
    if net_price_usd and net_price_usd > 0:
        price = float(net_price_usd)
        price_source = "caller_override"
        price_confidence = "medium"
        price_note = "Caller-supplied net price"
    else:
        price, price_source, price_confidence, price_note = await _lookup_price(
            disease_name, product_type, revenue_model
        )
        if not price:
            price, price_source, price_confidence, price_note = _default_price(revenue_model)
            assumptions.append({
                "field": "net_price_usd", "value": price,
                "source_type": "analyst_estimate", "confidence": "low",
                "expert_question": f"What is the expected net selling price (after discounts/rebates) for this {product_type} in {disease_name}? The engine used a class-level default of ${price:,.0f}.",
            })

    # Apply price override if supplied
    if "net_price_usd" in overrides:
        price = float(overrides["net_price_usd"])
        price_source = "override"

    # ── Revenue calculation ───────────────────────────────────────────────────
    # For per-patient: annualize via persistency
    # prevalent_on_treatment = incident × (persistency_months / 12)
    # revenue = prevalent × annual_cost  OR  incident × (persistency_months/12) × price
    if revenue_model == "per_patient" and persistency_months != 12:
        effective_count = base_count * (persistency_months / 12)
        assumptions.append({
            "field": "persistency_annualization",
            "value": f"{persistency_months}mo → {persistency_months/12:.2f}yr equivalent",
            "source_type": "literature", "confidence": "medium",
            "expert_question": None,
        })
    else:
        effective_count = base_count

    annual_revenue = effective_count * price

    # Confidence band based on price_confidence
    band = {"high": 0.20, "medium": 0.35, "low": 0.55}.get(price_confidence, 0.40)
    low_rev = annual_revenue * (1 - band * 0.5)
    high_rev = annual_revenue * (1 + band)

    return MonetizationResult(
        product_type=product_type,
        revenue_model=revenue_model,
        base_unit=base_unit,
        base_count=base_count,
        net_price_usd=price,
        annual_revenue_usd=annual_revenue,
        low_revenue_usd=low_rev,
        high_revenue_usd=high_rev,
        price_source=price_source,
        price_confidence=price_confidence,
        price_note=price_note,
        assumptions=assumptions,
    )


async def _lookup_price(
    disease_name: str, product_type: str, revenue_model: str
) -> tuple[Optional[float], str, str, str]:
    """Look up pricing_ref table for this disease + product_type."""
    price_type_map = {
        "per_patient": "net",
        "site_license": "site_license",
        "per_procedure": "procedure_reimbursement",
        "per_test": "per_test",
    }
    target_price_type = price_type_map.get(revenue_model, "net")

    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT price_usd, source_id, confidence, notes
                FROM pricing_ref
                WHERE (LOWER(disease_name) = LOWER($1) OR disease_name IS NULL)
                  AND LOWER(product_type) = LOWER($2)
                  AND price_type = $3
                ORDER BY (disease_name IS NOT NULL) DESC, confidence ASC
                LIMIT 1
            """, disease_name, product_type, target_price_type)

            if row:
                return (
                    float(row["price_usd"]),
                    row["source_id"] or "pricing_ref_db",
                    row["confidence"] or "medium",
                    row["notes"] or "",
                )
    except Exception as e:
        logger.warning("_lookup_price DB error: %s", e)
    return None, "", "", ""


def _default_price(revenue_model: str) -> tuple[float, str, str, str]:
    """Class-level price defaults when no DB row exists. All flagged analyst_estimate / low."""
    defaults = {
        "per_patient":    (50_000, "analyst_estimate", "low", "Class-level default net price; verify against comparators"),
        "site_license":   (80_000, "analyst_estimate", "low", "Annual enterprise site license default; verify with procurement"),
        "per_procedure":  (8_500,  "analyst_estimate", "low", "Typical device per-procedure reimbursement; verify CMS fee schedule"),
        "per_test":       (350,    "analyst_estimate", "low", "Per-test default (CDx/molecular); verify payer coverage"),
    }
    return defaults.get(revenue_model, (50_000, "analyst_estimate", "low", "Default"))
