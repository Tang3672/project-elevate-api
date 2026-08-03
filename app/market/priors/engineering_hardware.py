"""
Engineering Hardware / IoT Sensor — Numeric Priors (Rules 4+7)
===============================================================
Injects actual numeric values into the ENGINEERING_HARDWARE FunnelSpec template.
The template (templates/engineering_hardware.py) carries 0.0 placeholders;
this file declares the expected prior structure and documents what the operator
must supply.

Usage:
    from app.market.templates.engineering_hardware import TEMPLATE
    from app.market.priors.engineering_hardware import PRIORS
    spec = TEMPLATE.apply_priors(PRIORS)

Why all zeros here:
  Unlike life-sciences research tools, there is no universal "total deployment
  sites" count for engineering hardware — the addressable universe differs
  dramatically between, e.g., a precision-agriculture soil sensor (USDA counts
  ~2M commercial farms) and an industrial vibration monitor (BLS counts ~300K
  manufacturing establishments). The operator must supply the root axis value
  from the appropriate industry source before the funnel is meaningful.

  The gate fractions (technical_fit, budget_qualified) also depend on the
  specific product specification — power requirements, connectivity options,
  environmental rating — which the engine cannot generalize.

Operator override entry point:
  Build a product-specific priors dict that extends or overrides this one:

      from app.market.priors.engineering_hardware import PRIORS as BASE
      my_priors = {**BASE, "axes": {"total_sites": {"value": 2_000_000, ...}}}
      spec = TEMPLATE.apply_priors(my_priors)
"""

from __future__ import annotations

PRIORS: dict = {
    "axes": {
        "total_sites": {
            "value":      0.0,
            "low":        0.0,
            "high":       0.0,
            "confidence": 0.30,
            "source":     "Operator must supply from industry report (USDA, Census, BLS, etc.) ⚠",
            "method":     "assumed",
        },
    },
    "gates": {
        "technical_fit": {
            "fraction":   0.0,
            "low":        0.0,
            "high":       0.0,
            "confidence": 0.40,
            "rationale":  "Operator must supply — depends on power, connectivity, and environmental spec for this product ⚠",
        },
        "budget_qualified": {
            "fraction":   0.0,
            "low":        0.0,
            "high":       0.0,
            "confidence": 0.40,
            "rationale":  "Operator must supply — depends on buyer type (farm, facility, municipality) and procurement cycle ⚠",
        },
    },
    "price_tiers": {
        "unit_purchase": {
            "annual_usd": 0.0,
            "mix":        0.0,
        },
        "service_contract": {
            "annual_usd": 0.0,
            "mix":        0.0,
        },
    },
}
