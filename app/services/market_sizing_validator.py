"""
Market Sizing Validator  (Build Spec v5, Part E)
=================================================
For each disease with a known public market figure, run the orchestrator
and assert within 30%. Outputs a per-disease accuracy report.

Usage:
    python -m app.services.market_sizing_validator

Public figures sourced from:
  - EvaluatePharma / GlobalData / IQVIA press releases (2023-2024)
  - NCI SEER market reports
  - These are TAM figures at the disease level, not SOM
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ValidationCase:
    disease_name: str
    product_type: str
    segment_gate: float          # the treated-segment rate to test against
    net_price_usd: float
    public_market_usd: float     # known TAM (SAM level, not SOM)
    source: str


@dataclass
class ValidationResult:
    disease_name: str
    engine_sam_usd: float
    public_sam_usd: float
    pct_error: float             # (engine - public) / public
    within_30pct: bool
    status: str                  # "PASS" | "FAIL" | "WARN"
    notes: str


# Known public market figures (SAM-level annual revenue)
_VALIDATION_CASES: List[ValidationCase] = [
    ValidationCase(
        disease_name="stroke",
        product_type="drug_small_molecule",
        segment_gate=0.10,        # LVO thrombectomy-eligible as fraction of all stroke
        net_price_usd=13_750,     # tPA/thrombolytics blended net
        public_market_usd=1_200_000_000,   # ~$1.2B US acute stroke drug market
        source="EvaluatePharma Stroke 2023",
    ),
    ValidationCase(
        disease_name="NSCLC",
        product_type="drug_small_molecule",
        segment_gate=0.13,        # KRAS G12C positive (~13% of NSCLC)
        net_price_usd=180_000,    # Sotorasib/Adagrasib blended net
        public_market_usd=2_000_000_000,   # ~$2B US KRAS G12C NSCLC addressable
        source="GlobalData NSCLC 2023; KRAS G12C Inhibitors market",
    ),
    ValidationCase(
        disease_name="atrial fibrillation",
        product_type="medical_device",
        segment_gate=0.35,        # catheter ablation-eligible AF patients
        net_price_usd=8_500,
        public_market_usd=3_800_000_000,   # ~$3.8B US AF ablation device market
        source="BIS Research AF Device Market 2023",
    ),
    ValidationCase(
        disease_name="sepsis",
        product_type="samd",
        segment_gate=None,        # site-license: gate is site count, not patient fraction
        net_price_usd=75_000,     # annual site license
        public_market_usd=1_500_000_000,   # ~$1.5B US sepsis AI/software addressable
        source="MarketsandMarkets Sepsis Management 2023",
    ),
    ValidationCase(
        disease_name="HER2-low breast cancer",
        product_type="diagnostic",
        segment_gate=0.55,        # HER2-low (IHC 1+/2+/ISH-) fraction of all breast cancer
        net_price_usd=350,
        public_market_usd=150_000_000,    # ~$150M US HER2 Dx market (companion Dx)
        source="Grand View Research HER2 Testing Market 2023",
    ),
]

_TOLERANCE = 0.30   # 30% — spec requirement


async def run_validation() -> List[ValidationResult]:
    """Run all validation cases and return results."""
    from app.services import market_sizing_orchestrator

    results = []
    for case in _VALIDATION_CASES:
        try:
            orchestrated = await market_sizing_orchestrator.run(
                disease_name=case.disease_name,
                product_type=case.product_type,
                segment_gate=case.segment_gate,
                net_price_usd=case.net_price_usd,
            )
            engine_val = orchestrated.sam_revenue_usd
            pct_err = (engine_val - case.public_market_usd) / case.public_market_usd
            within = abs(pct_err) <= _TOLERANCE
            status = "PASS" if within else ("WARN" if abs(pct_err) <= 0.60 else "FAIL")
            note = (
                f"Engine: {_fmt(engine_val)} | Public: {_fmt(case.public_market_usd)} | "
                f"Error: {pct_err:+.0%} | Source: {case.source}"
            )
            results.append(ValidationResult(
                disease_name=case.disease_name,
                engine_sam_usd=engine_val,
                public_sam_usd=case.public_market_usd,
                pct_error=pct_err,
                within_30pct=within,
                status=status,
                notes=note,
            ))
        except Exception as e:
            logger.error("Validation failed for %s: %s", case.disease_name, e)
            results.append(ValidationResult(
                disease_name=case.disease_name,
                engine_sam_usd=0,
                public_sam_usd=case.public_market_usd,
                pct_error=float("inf"),
                within_30pct=False,
                status="FAIL",
                notes=f"Exception: {e}",
            ))

    _print_report(results)
    return results


def _print_report(results: List[ValidationResult]) -> None:
    passed = sum(1 for r in results if r.within_30pct)
    total = len(results)
    print(f"\n{'='*70}")
    print(f"MARKET SIZING VALIDATOR  —  {passed}/{total} within ±30%")
    print(f"{'='*70}")
    for r in results:
        icon = "✓" if r.within_30pct else ("~" if r.status == "WARN" else "✗")
        print(f"  [{icon}] {r.disease_name:<35} {r.status}  {r.pct_error:+.0%}")
        print(f"       {r.notes}")
    print(f"{'='*70}\n")
    if passed < total:
        failed = [r.disease_name for r in results if not r.within_30pct]
        print(f"OUT OF TOLERANCE: {', '.join(failed)}")
        print("Check seed data in patient_flows_seed.py and pricing_ref rows.\n")


def _fmt(v: float) -> str:
    if v >= 1e9:
        return f"${v/1e9:.2f}B"
    if v >= 1e6:
        return f"${v/1e6:.1f}M"
    return f"${v:,.0f}"


if __name__ == "__main__":
    import sys
    import os
    # Add project root to path
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    asyncio.run(run_validation())
