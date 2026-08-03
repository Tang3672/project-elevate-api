"""
Life Sciences Research Tool — Numeric Priors (Rules 4+7)
=========================================================
Injects actual numeric values into the LIFE_SCIENCES_RESEARCH FunnelSpec template.
The template (templates/life_sciences_research.py) carries 0.0 placeholders;
this file has the real numbers.

Usage:
    from app.market.templates.life_sciences_research import TEMPLATE
    from app.market.priors.life_sciences_research import PRIORS
    spec = TEMPLATE.apply_priors(PRIORS)

Source attributions:
  Carnegie 2021: 4,100 R1/R2/D1/D2 and master's institutions (IPEDS supplement)
  NSF HERD 2022: 8.4 R&D-active laboratories per institution (STEM average)
  Funnel fractions: analyst assumption ⚠ — operator must supply observed data
                    from primary research or PI survey to override.
"""

from __future__ import annotations

_CARNEGIE_INSTITUTION_COUNT: int   = 4_100
_HERD_LABS_PER_INSTITUTION: float  = 8.4
_NIH_FUNDED_FRACTION: float        = 0.62  # fraction of labs with active NIH grant (static fallback ⚠)

PRIORS: dict = {
    "axes": {
        "nih_funded_labs": {
            "value":      _CARNEGIE_INSTITUTION_COUNT * _HERD_LABS_PER_INSTITUTION * _NIH_FUNDED_FRACTION,
            "low":        _CARNEGIE_INSTITUTION_COUNT * _HERD_LABS_PER_INSTITUTION * 0.45,
            "high":       _CARNEGIE_INSTITUTION_COUNT * _HERD_LABS_PER_INSTITUTION * 0.80,
            "confidence": 0.55,
            "source":     (
                f"Carnegie 2021 ({_CARNEGIE_INSTITUTION_COUNT:,} institutions) "
                f"× NSF HERD 2022 ({_HERD_LABS_PER_INSTITUTION} labs/institution) "
                f"× NIH-funded fraction {_NIH_FUNDED_FRACTION:.0%} (static fallback ⚠ — "
                "live NIH RePORTER API result overrides this when available)"
            ),
            "method": "modeled",
        },
    },
    "gates": {
        "long_duration": {
            "fraction":   0.22,
            "low":        0.15,
            "high":       0.35,
            "confidence": 0.50,
            "rationale":  "Assumed ⚠ — fraction of labs running instrumented studies ≥6 months; operator should supply from primary research",
        },
        "low_bandwidth": {
            "fraction":   0.81,
            "low":        0.65,
            "high":       0.92,
            "confidence": 0.55,
            "rationale":  "Assumed ⚠ — fraction using passive or low-bandwidth data collection (not real-time streaming)",
        },
        "not_custom": {
            "fraction":   0.63,
            "low":        0.50,
            "high":       0.75,
            "confidence": 0.50,
            "rationale":  "Assumed ⚠ — fraction without a bespoke in-house solution; verify from competitive landscape",
        },
        "budget_authority": {
            "fraction":   0.47,
            "low":        0.35,
            "high":       0.60,
            "confidence": 0.55,
            "rationale":  "Derived from PI budget authority rate × procurement-cycle overlap (assumed ⚠)",
        },
    },
    "price_tiers": {
        "academic": {
            "annual_usd": 7_000.0,
            "mix":        0.80,
        },
        "core_facility": {
            "annual_usd": 20_000.0,
            "mix":        0.15,
        },
        "site_license": {
            "annual_usd": 45_000.0,
            "mix":        0.05,
        },
    },
}
