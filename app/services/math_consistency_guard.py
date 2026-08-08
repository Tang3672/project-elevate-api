"""
B-02 — Deterministic market-arithmetic consistency guard.

The LLM math verifier can hallucinate "resolved" or emit no flags even when
the numbers disagree. This module runs independent numeric checks with no LLM
call. Its flags cannot be silenced by the LLM's verdict.

Public API: check_market_arithmetic(market_sizing: dict) -> list[dict]
"""

from __future__ import annotations

from typing import Optional


# ── helpers ───────────────────────────────────────────────────────────────────

def _to_float(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _rel_err(a: float, b: float) -> float:
    return abs(a - b) / abs(b) if b != 0 else 0.0


def _flag(field: str, issue: str, suggestion: str) -> dict:
    return {
        "severity":   "ERROR",
        "category":   "MATH",
        "field":      field,
        "issue":      issue,
        "suggestion": suggestion,
        "agent":      "Math Consistency Guard",
    }


def _usd_tier_values(steps: list[dict]) -> dict[str, float]:
    """Return {'tam': v, 'sam': v, 'som': v} from step labels (first match wins)."""
    out: dict[str, float] = {}
    for s in steps:
        lbl = (s.get("label") or "").lower()
        val = _to_float(s.get("value"))
        if val is None:
            continue
        if "total addressable" in lbl or ("tam" in lbl and "sam" not in lbl and "som" not in lbl):
            out.setdefault("tam", val)
        elif "serviceable addressable" in lbl or ("sam" in lbl and "som" not in lbl):
            out.setdefault("sam", val)
        elif "obtainable" in lbl or ("som" in lbl):
            out.setdefault("som", val)
    return out


_COUNT_UNITS = {"labs", "patients", "sites", "procedures", "facilities", "hospitals", "devices"}


def _buyer_population(steps: list[dict]) -> Optional[float]:
    """Find the first step whose unit looks like a population count."""
    for s in steps:
        unit = (s.get("unit") or "").lower()
        if any(u in unit for u in _COUNT_UNITS):
            return _to_float(s.get("value"))
    return None


def _unit_price(steps: list[dict]) -> Optional[float]:
    """Find the first step whose unit looks like a USD-per-something rate."""
    for s in steps:
        unit = (s.get("unit") or "").lower()
        if "usd" in unit and "/" in unit:
            return _to_float(s.get("value"))
    return None


# ── public API ────────────────────────────────────────────────────────────────

def check_market_arithmetic(market_sizing: dict) -> list[dict]:
    """
    Deterministic arithmetic checks — no LLM, no false 'resolved' verdicts.

    Checks:
      1. TAM step value ≈ headline total_addressable_market_usd (≤1% tolerance)
      2. SAM step value ≈ headline serviceable_market_usd (≤1% tolerance)
      3. Headline SAM ≤ TAM
      4. Bottom-up product (pop × price per unit) ≈ TAM (≤10% tolerance)

    Returns a list of MATH ERROR ValidationFlag dicts.
    """
    if not market_sizing:
        return []

    flags: list[dict] = []

    stated_tam = _to_float(market_sizing.get("total_addressable_market_usd"))
    stated_sam = _to_float(market_sizing.get("serviceable_market_usd"))
    steps: list[dict] = market_sizing.get("steps") or []

    step_vals = _usd_tier_values(steps)

    # ── 1. TAM step vs headline ──────────────────────────────────────────────
    if stated_tam is not None and "tam" in step_vals:
        err = _rel_err(step_vals["tam"], stated_tam)
        if err > 0.01:
            flags.append(_flag(
                "market_sizing.steps.tam",
                f"TAM step value (${step_vals['tam']:,.0f}) disagrees with headline "
                f"total_addressable_market_usd (${stated_tam:,.0f}) by {err:.1%}. "
                "The step table and headline must agree.",
                "Run _enforce_market_consistency to propagate the code-computed "
                "TAM into the step, or correct the step value manually.",
            ))

    # ── 2. SAM step vs headline ──────────────────────────────────────────────
    if stated_sam is not None and "sam" in step_vals:
        err = _rel_err(step_vals["sam"], stated_sam)
        if err > 0.01:
            flags.append(_flag(
                "market_sizing.steps.sam",
                f"SAM step value (${step_vals['sam']:,.0f}) disagrees with headline "
                f"serviceable_market_usd (${stated_sam:,.0f}) by {err:.1%}.",
                "Correct the SAM step value to match the headline SAM.",
            ))

    # ── 3. SAM ≤ TAM (basic constraint) ─────────────────────────────────────
    if stated_tam is not None and stated_sam is not None:
        if stated_sam > stated_tam * 1.01:
            flags.append(_flag(
                "market_sizing.serviceable_market_usd",
                f"SAM (${stated_sam:,.0f}) exceeds TAM (${stated_tam:,.0f}). "
                "The serviceable market cannot be larger than the total addressable market.",
                "Reduce SAM or increase TAM so SAM ≤ TAM.",
            ))

    # ── 4. Bottom-up product check ───────────────────────────────────────────
    if stated_tam is not None and steps:
        pop = _buyer_population(steps)
        price = _unit_price(steps)
        if pop is not None and price is not None and pop > 0 and price > 0:
            computed = pop * price
            err = _rel_err(computed, stated_tam)
            if err > 0.10:
                flags.append(_flag(
                    "market_sizing.total_addressable_market_usd",
                    f"Bottom-up product ({pop:,.0f} buyers × ${price:,.0f}/buyer = "
                    f"${computed:,.0f}) differs from stated TAM (${stated_tam:,.0f}) "
                    f"by {err:.1%}. The stated TAM must follow from the inputs in the steps.",
                    "Align the buyer count and per-unit price in the steps with the "
                    "stated TAM headline, or correct the headline to match the inputs.",
                ))

    return flags
