"""
Predicate-based recommendation library.

Each Recommendation fires when `applies_when(model_values)` is True.
Multiple entries share the same `id` — only the first match per id is kept
(sorted by priority ascending, so low numbers fire first).

This is what makes `recommendations_changed` in the API response real:
a function of the model, not a generated string, so it moves when the model moves.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class Recommendation:
    id: str
    text: str
    priority: int
    applies_when: Callable[[dict], bool]


_LIBRARY: list[Recommendation] = [
    # market_size — fires first; shapes everything else
    Recommendation(
        id="market_size",
        priority=5,
        text="TAM is sub-scale for institutional VC. Target strategic acquirers and non-dilutive capital.",
        applies_when=lambda v: v.get("tam", 0) < 50_000_000,
    ),
    Recommendation(
        id="market_size",
        priority=5,
        text="TAM supports a VC-fundable company. Lead with the market size in your deck, not the product.",
        applies_when=lambda v: v.get("tam", 0) >= 50_000_000,
    ),
    # funding_path
    Recommendation(
        id="funding_path",
        priority=10,
        text="Non-dilutive only. SOM is below $1M — SBIR/STTR Phase I before any equity conversation.",
        applies_when=lambda v: v.get("som", 0) < 1_000_000,
    ),
    Recommendation(
        id="funding_path",
        priority=10,
        text=(
            "SBIR-first. SOM supports a capital-efficient build; "
            "a priced round is premature until you reach $5M ARR."
        ),
        applies_when=lambda v: 1_000_000 <= v.get("som", 0) < 10_000_000,
    ),
    Recommendation(
        id="funding_path",
        priority=10,
        text=(
            "SOM clears the threshold where a priced seed round is worth the dilution. "
            "Quantify your unfair advantage before the pitch."
        ),
        applies_when=lambda v: v.get("som", 0) >= 10_000_000,
    ),
    # channel
    Recommendation(
        id="channel",
        priority=20,
        text="PI-direct sales. At this population size, relationship-driven outreach is the only way in.",
        applies_when=lambda v: v.get("buyer_population", 0) < 5_000,
    ),
    Recommendation(
        id="channel",
        priority=20,
        text=(
            "Core-facility and institutional site licensing are viable. "
            "Population is large enough for a channel strategy."
        ),
        applies_when=lambda v: v.get("buyer_population", 0) >= 5_000,
    ),
    # penetration_risk — only fires when a problem exists; no competing variant
    Recommendation(
        id="penetration_risk",
        priority=30,
        text=(
            "SAM rate exceeds 60% — aggressive for early-stage. "
            "Verify that budget cycles and channel friction are reflected."
        ),
        applies_when=lambda v: v.get("sam_rate", 0) > 0.60,
    ),
]


def recommend(values: dict) -> list[Recommendation]:
    """Return one recommendation per id (first matching predicate wins)."""
    seen: set[str] = set()
    result: list[Recommendation] = []
    for rec in sorted(_LIBRARY, key=lambda r: r.priority):
        if rec.id not in seen and rec.applies_when(values):
            seen.add(rec.id)
            result.append(rec)
    return result
