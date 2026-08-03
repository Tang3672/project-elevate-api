"""
Engineering Hardware / IoT Sensor — Market Segmentation Template (Rules 4+7)
=============================================================================
Defines the funnel topology for non-life-sciences hardware products
(precision agriculture sensors, industrial IoT, environmental monitoring, etc.).

Rules enforced here:
  Rule 1  — No numeric constants; all Axis/Gate/PriceTier values are 0.0.
             Actual numbers live in app/market/priors/engineering_hardware.py.
  Rule 4  — Built alongside life_sciences_research.py against the same Axis,
             Gate, PriceTier, FunnelSpec types from app/market/types.py.
  Rule 7  — Template (structure) in templates/; numbers in priors/; data in sources/.

Funnel topology:
  Total addressable deployment sites (operator-supplied from industry report)
    ↓ technical_fit gate
  Technically compatible sites (power, connectivity, environmental spec)
    ↓ budget_qualified gate
  Sites with capital budget authority
    → price tiers: unit_purchase | service_contract
"""

from __future__ import annotations

from app.market.types import Axis, FunnelSpec, Gate, PriceTier

TEMPLATE = FunnelSpec(
    id="engineering_hardware",
    label="Engineering Hardware / IoT Sensor",
    segment_domain="ENGINEERING_HARDWARE",
    axes=[
        Axis(
            id="total_sites",
            label="Total addressable deployment sites (operator-supplied)",
            unit="sites",
        ),
        Axis(
            id="compatible_sites",
            label="Technically compatible sites (power, connectivity, environmental spec)",
            unit="sites",
        ),
        Axis(
            id="addressable_sites",
            label="Sites with capital budget authority",
            unit="sites",
        ),
    ],
    gates=[
        Gate(
            id="technical_fit",
            label="Technical compatibility (power, connectivity, environmental spec)",
        ),
        Gate(
            id="budget_qualified",
            label="Capital budget authority present",
        ),
    ],
    price_tiers=[
        PriceTier(id="unit_purchase",    label="One-time unit purchase"),
        PriceTier(id="service_contract", label="Annual service / maintenance contract"),
    ],
    funnel_chain=[
        "total_sites",
        "compatible_sites",
        "addressable_sites",
    ],
    clinical_vocabulary_required=[],
    clinical_vocabulary_forbidden=[
        "wac price",
        "drg ",
        "cpt code",
        "ntap",
        "510(k)",
        "510 (k)",
        "clinical trial",
        "patient population",
        "prevalence",
        "incidence",
    ],
)
