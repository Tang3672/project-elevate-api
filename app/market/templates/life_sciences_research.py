"""
Life Sciences Research Tool — Market Segmentation Template (Rules 4+7)
=======================================================================
Defines the funnel topology for research-tool products (lab instrumentation,
data-logging hardware, research software platforms, etc.).

Rules enforced here:
  Rule 1  — No numeric constants; all Axis/Gate/PriceTier values are 0.0.
             Actual numbers live in app/market/priors/life_sciences_research.py.
  Rule 4  — Built alongside engineering_hardware.py against the same Axis,
             Gate, PriceTier, FunnelSpec types from app/market/types.py.
  Rule 7  — Template (structure) in templates/; numbers in priors/; data in sources/.

Funnel topology:
  US labs with active NIH grants
    ↓ long_duration gate
  Labs running long-duration experiments (≥6 months)
    ↓ low_bandwidth gate
  Labs using low-bandwidth / passive data modality
    ↓ not_custom gate
  Labs without a bespoke in-house solution
    ↓ budget_authority gate
  Addressable labs (PI has direct budget authority)
    → price tiers: academic | core_facility | site_license
"""

from __future__ import annotations

from app.market.types import Axis, FunnelSpec, Gate, PriceTier

TEMPLATE = FunnelSpec(
    id="life_sciences_research",
    label="Life Sciences Research Tool",
    segment_domain="LIFE_SCIENCES_RESEARCH",
    axes=[
        Axis(
            id="nih_funded_labs",
            label="US labs with active NIH grants",
            unit="labs",
        ),
        Axis(
            id="long_duration_labs",
            label="Labs running long-duration instrumented experiments (≥6 months)",
            unit="labs",
        ),
        Axis(
            id="low_bandwidth_labs",
            label="Labs using low-bandwidth or passive data collection",
            unit="labs",
        ),
        Axis(
            id="not_custom_labs",
            label="Labs without a bespoke in-house solution",
            unit="labs",
        ),
        Axis(
            id="addressable_labs",
            label="Labs with PI direct budget authority (addressable market)",
            unit="labs",
        ),
    ],
    gates=[
        Gate(
            id="long_duration",
            label="Study duration ≥6 months",
        ),
        Gate(
            id="low_bandwidth",
            label="Passive or low-bandwidth data collection",
        ),
        Gate(
            id="not_custom",
            label="No bespoke in-house solution",
        ),
        Gate(
            id="budget_authority",
            label="PI has direct budget authority",
        ),
    ],
    price_tiers=[
        PriceTier(id="academic",       label="Individual academic lab"),
        PriceTier(id="core_facility",  label="Shared core facility"),
        PriceTier(id="site_license",   label="Institution-wide site license"),
    ],
    funnel_chain=[
        "nih_funded_labs",
        "long_duration_labs",
        "low_bandwidth_labs",
        "not_custom_labs",
        "addressable_labs",
    ],
    clinical_vocabulary_required=[],
    clinical_vocabulary_forbidden=[
        "wac price",
        "drg ",
        "cpt code",
        "ntap",
        "510(k)",
        "510 (k)",
    ],
)
