"""Shared utilities used across the Medlevate backend."""

from __future__ import annotations


def fmt_usd(v: float) -> str:
    """B-02: canonical USD formatter.

    Never produces $0M / $0K for a non-zero value.
    Uses :.1f for M/B (so $0.4M, not $0M) and K for sub-million.
    """
    if not v and v != 0:
        return "—"
    v = float(v)
    if v >= 1_000_000_000:
        return f"${v / 1e9:.1f}B"
    if v >= 1_000_000:
        return f"${v / 1e6:.1f}M"
    if v >= 10_000:
        return f"${v / 1e3:.0f}K"
    return f"${v:,.0f}"
