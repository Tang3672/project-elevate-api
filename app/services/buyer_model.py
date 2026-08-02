"""
Buyer Model  (Defect Report — H-07, H-08)
==========================================
Encodes who signs the purchase order, what budget it comes from, and
what the observed spend band is from primary research. TAM must derive
from this model — not from hospital counts or generic population statistics.

H-07 root cause: the Hublink report used 5,000 hospital sites × $75,000/yr
as the TAM denominator. Hublink's actual buyer is an academic PI with a
$20k-$30k multi-year equipment budget. Bottom-up TAM should be:
  ~5,000-10,000 eligible labs × $6k-$8k/yr annualised ≈ $30M-$80M TAM.

H-08 root cause: TAM/SAM/SOM were authored by the LLM with two different
roundings of the same figure. This module enforces single-source arithmetic:
compute_market_sizes() takes the buyer model and returns a single canonical
MarketSizeResult. All report sections must reference this object.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


# ─── Buyer persona codes ──────────────────────────────────────────────────────

BUYER_PERSONAS = {
    "academic_pi":             "Academic principal investigator (NIH/NSF-funded lab)",
    "core_facility_director":  "Core facility director (shared institutional resource)",
    "research_it_or_admin":    "Research IT or lab administrator (institutional procurement)",
    "hospital_cio_or_cmo":     "Hospital CIO/CMO or health system VP",
    "hospital_vp_surgery":     "Hospital VP of Surgery or procurement committee",
    "lab_director_pathologist":"Clinical lab director or pathologist",
    "payer_and_hospital_pharmacy": "Payer formulary committee or hospital pharmacy",
    "tto_or_licensing":        "Technology transfer office",
    "unknown":                 "Not yet characterised",
}

PURCHASE_CADENCES = {
    "annual":          "Renews every year (SaaS, reagent subscription)",
    "biennial":        "Every 2 years",
    "triennial":       "Every 3 years",
    "quinquennial":    "Every 5 years (major capital equipment)",
    "one_time":        "Single purchase, no renewal",
    "grant_cycle":     "Tied to grant renewal (typically 3-5 years)",
}


# ─── Buyer model ──────────────────────────────────────────────────────────────

@dataclass
class BuyerModel:
    """
    Complete description of the primary buyer for a product.

    Fields:
        buyer_persona:          Who signs the purchase order.
        budget_line:            Which budget the spend comes from.
        purchase_cadence:       How often the product is purchased/renewed.
        approval_chain:         Who else must approve (None = solo decision).
        observed_spend_band_lo: Lower bound of observed per-unit spend per cycle (USD).
        observed_spend_band_hi: Upper bound of observed per-unit spend per cycle (USD).
        spend_source:           Evidence for the spend band (e.g. "Gaidica 2026 n=10 interviews").
        buyer_population_lo:    Conservative estimate of eligible buyers (units).
        buyer_population_hi:    Optimistic estimate of eligible buyers.
        population_denominator: Description of what one "buyer" is.
        population_source:      Evidence for the population (e.g. "NIH RePORTER query").
        annualization_factor:   spend_per_cycle / years_per_cycle → annual equivalent.
    """
    buyer_persona:           str
    budget_line:             str
    purchase_cadence:        str
    approval_chain:          Optional[str]
    observed_spend_band_lo:  float   # USD per cycle per buyer
    observed_spend_band_hi:  float
    spend_source:            str
    buyer_population_lo:     int
    buyer_population_hi:     int
    population_denominator:  str     # "NIH-funded neurotech labs" etc.
    population_source:       str
    annualization_factor:    float = 1.0  # 1/cycle_years  (e.g. 0.25 for 4-year cycle)

    def annualised_spend_lo(self) -> float:
        return self.observed_spend_band_lo * self.annualization_factor

    def annualised_spend_hi(self) -> float:
        return self.observed_spend_band_hi * self.annualization_factor


# ─── Market size computation ──────────────────────────────────────────────────

@dataclass
class MarketSizeResult:
    """
    Single canonical market sizing object. All report sections must reference
    this object — never author TAM/SAM/SOM numbers independently (H-08).
    """
    buyer_model:    BuyerModel

    # Inputs (from buyer model + SAM/SOM fractions)
    sam_fraction:   float    # fraction of TAM that is reachable in the next 5 years
    som_fraction:   float    # fraction of SAM reachable in the planning horizon
    som_horizon_years: int   # horizon for SOM capture

    # Outputs (computed, never authored)
    tam_lo_usd:  float = field(init=False)
    tam_hi_usd:  float = field(init=False)
    sam_lo_usd:  float = field(init=False)
    sam_hi_usd:  float = field(init=False)
    som_lo_usd:  float = field(init=False)
    som_hi_usd:  float = field(init=False)

    # Confidence band (one method, one CI — H-08)
    p10_usd:     float = field(init=False)
    p90_usd:     float = field(init=False)
    uncertainty_method: str = "buyer_model_range_propagation"

    def __post_init__(self) -> None:
        bm = self.buyer_model
        self.tam_lo_usd = bm.buyer_population_lo * bm.annualised_spend_lo()
        self.tam_hi_usd = bm.buyer_population_hi * bm.annualised_spend_hi()
        self.sam_lo_usd = self.tam_lo_usd * self.sam_fraction
        self.sam_hi_usd = self.tam_hi_usd * self.sam_fraction
        self.som_lo_usd = self.sam_lo_usd * self.som_fraction
        self.som_hi_usd = self.sam_hi_usd * self.som_fraction
        # P10/P90: use the lo/hi bounds as the CI endpoints
        self.p10_usd = self.som_lo_usd
        self.p90_usd = self.som_hi_usd

    def format_usd(self, value: float) -> str:
        if value >= 1e9:
            return f"${value / 1e9:.1f}B"
        if value >= 1e6:
            return f"${value / 1e6:.0f}M"
        return f"${value / 1e3:.0f}K"

    def explain(self) -> str:
        bm = self.buyer_model
        lines = [
            "Market Sizing (bottom-up from buyer model):",
            f"  Buyer:            {BUYER_PERSONAS.get(bm.buyer_persona, bm.buyer_persona)}",
            f"  Population:       {bm.buyer_population_lo:,}–{bm.buyer_population_hi:,} "
            f"{bm.population_denominator}",
            f"  Population source:{bm.population_source}",
            f"  Spend per cycle:  ${bm.observed_spend_band_lo:,.0f}–${bm.observed_spend_band_hi:,.0f} "
            f"({bm.purchase_cadence})",
            f"  Spend source:     {bm.spend_source}",
            f"  Annualised spend: ${bm.annualised_spend_lo():,.0f}–${bm.annualised_spend_hi():,.0f}/yr",
            "",
            f"  TAM = population × annualised_spend",
            f"      = [{bm.buyer_population_lo:,}–{bm.buyer_population_hi:,}] × "
            f"[${bm.annualised_spend_lo():,.0f}–${bm.annualised_spend_hi():,.0f}]",
            f"      = {self.format_usd(self.tam_lo_usd)}–{self.format_usd(self.tam_hi_usd)}",
            "",
            f"  SAM = TAM × {self.sam_fraction:.0%} (reachable market fraction)",
            f"      = {self.format_usd(self.sam_lo_usd)}–{self.format_usd(self.sam_hi_usd)}",
            "",
            f"  SOM = SAM × {self.som_fraction:.0%} ({self.som_horizon_years}yr capture)",
            f"      = {self.format_usd(self.som_lo_usd)}–{self.format_usd(self.som_hi_usd)}",
            "",
            f"  CI [{self.uncertainty_method}]: P10={self.format_usd(self.p10_usd)}, "
            f"P90={self.format_usd(self.p90_usd)}",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        bm = self.buyer_model
        return {
            "buyer_persona":         bm.buyer_persona,
            "population_denominator": bm.population_denominator,
            "population_lo":         bm.buyer_population_lo,
            "population_hi":         bm.buyer_population_hi,
            "population_source":     bm.population_source,
            "annualised_spend_lo":   round(bm.annualised_spend_lo(), 2),
            "annualised_spend_hi":   round(bm.annualised_spend_hi(), 2),
            "spend_source":          bm.spend_source,
            "tam_lo_usd":            round(self.tam_lo_usd),
            "tam_hi_usd":            round(self.tam_hi_usd),
            "sam_fraction":          self.sam_fraction,
            "sam_lo_usd":            round(self.sam_lo_usd),
            "sam_hi_usd":            round(self.sam_hi_usd),
            "som_fraction":          self.som_fraction,
            "som_horizon_years":     self.som_horizon_years,
            "som_lo_usd":            round(self.som_lo_usd),
            "som_hi_usd":            round(self.som_hi_usd),
            "p10_usd":               round(self.p10_usd),
            "p90_usd":               round(self.p90_usd),
            "uncertainty_method":    self.uncertainty_method,
        }


# ─── Serviceable-buyer reconciliation check (H-07) ───────────────────────────

@dataclass
class SpendGapWarning:
    product_price_per_year: float
    spend_band_hi_annualised: float
    gap_multiple: float
    message: str


def check_price_vs_spend_band(
    product_price_per_year: float,
    buyer_model: BuyerModel,
) -> Optional[SpendGapWarning]:
    """
    H-07 serviceable-buyer reconciliation.
    Raises a warning (not an error) when the product's asking price exceeds
    the buyer's observed annual spend band. This does not block the report —
    it forces the mismatch to be surfaced rather than proceeding silently.

    Example: Hublink at $75,000/yr vs observed spend of $6k-$10k/yr annualised
    → gap multiple ≈ 7.5-12.5×. Flag prominently.
    """
    hi_annual = buyer_model.annualised_spend_hi()
    if hi_annual <= 0:
        return None

    if product_price_per_year > hi_annual:
        gap = product_price_per_year / hi_annual
        return SpendGapWarning(
            product_price_per_year=product_price_per_year,
            spend_band_hi_annualised=hi_annual,
            gap_multiple=round(gap, 1),
            message=(
                f"PRICING MISMATCH: product asks ${product_price_per_year:,.0f}/yr but "
                f"the {buyer_model.buyer_persona} buyer's observed annual spend ceiling is "
                f"${hi_annual:,.0f}/yr (source: {buyer_model.spend_source}). "
                f"Gap is {gap:.1f}×. Report must flag this gap and include a pricing "
                f"viability analysis before proceeding to market projections."
            ),
        )
    return None


# ─── Pre-built buyer models for common research-tool archetypes ───────────────

def academic_neurotech_lab_buyer(
    observed_spend_lo: float = 20_000,
    observed_spend_hi: float = 30_000,
    cycle_years: float = 3.0,
    population_lo: int = 3_000,
    population_hi: int = 8_000,
    population_denominator: str = "NIH-funded neuroscience/neurotech labs running instrumented experiments",
    population_source: str = "NIH RePORTER query — estimate pending verification",
    spend_source: str = "Primary research (specify source)",
) -> BuyerModel:
    """
    Default buyer model for Hublink-class neurotech data-logging tools.
    Numbers from Gaidica (2026) primary research: n=10 PIs, $20k-$30k per multi-year cycle.
    """
    return BuyerModel(
        buyer_persona="academic_pi",
        budget_line="nih_grant_direct_costs_equipment_line",
        purchase_cadence="grant_cycle",
        approval_chain="department_chair_for_capital_over_50k",
        observed_spend_band_lo=observed_spend_lo,
        observed_spend_band_hi=observed_spend_hi,
        spend_source=spend_source,
        buyer_population_lo=population_lo,
        buyer_population_hi=population_hi,
        population_denominator=population_denominator,
        population_source=population_source,
        annualization_factor=1.0 / cycle_years,
    )
