"""
Template renderer — spec v9 Part 4
====================================
Converts prose templates that carry {{node_id}} or {{node_id|filter}} tokens
into HTML with bound <span class="mv" data-node="nid"> elements, and validates
that no literal numbers have leaked back into prose.

Usage:
    text = render("TAM is {{tam}} from {{buyer_population}} labs", model)
    validate_template(section_text)   # raises if bare number found
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.model.market_model import MarketModel

# Regex that finds bare numeric values in prose (outside {{ }} tokens).
# Matches: $12.5M  68,750,000  3,500  42%  $1,250/yr  etc.
_NUMERIC_RE = re.compile(
    r"(?<![{])"                 # not preceded by { (inside a token)
    r"(?<!\w)"                  # not part of a word
    r"(\$?\d[\d,]*\.?\d*"       # number, optionally with $, commas, decimal
    r"(?:\s*(?:%|B|M|K|bn|mn))?"  # optional SI suffix
    r"(?:/\w+)*)"               # optional /unit suffix  ($1,250/yr)
    r"(?![}])"                  # not followed by } (inside a token)
    r"(?!\w)"                   # not part of a word
)

_TOKEN_RE = re.compile(r"\{\{([^}]+)\}\}")

_DEFAULT_FILTERS: dict[str, str] = {
    "labs": "int",
    "USD": "usd",
    "USD/lab/yr": "usd",
    "ratio": "pct",
    "%": "pct",
}


def _default_filter(unit: str) -> str:
    return _DEFAULT_FILTERS.get(unit, "usd" if "usd" in unit.lower() else "compact")


def _apply_filter(value: float, filt: str) -> str:
    from app.model.market_model import _fmt_usd
    if filt == "usd":
        return _fmt_usd(value)
    if filt == "pct":
        return f"{value * 100:.1f}%"
    if filt == "int":
        return f"{value:,.0f}"
    if filt == "compact":
        if abs(value) >= 1e9:
            return f"{value/1e9:.1f}B"
        if abs(value) >= 1e6:
            return f"{value/1e6:.1f}M"
        if abs(value) >= 1e3:
            return f"{value/1e3:,.0f}K"
        return f"{value:,.0f}"
    return str(value)


def render(template: str, model: "MarketModel") -> str:
    """Expand {{node_id}} / {{node_id|filter}} tokens to bound <span> elements."""
    vals = model.values()
    nodes = model.nodes

    def sub(m: re.Match) -> str:
        ref = m.group(1)
        nid, _, filt = ref.partition("|")
        nid = nid.strip()
        if nid not in vals:
            return m.group(0)   # leave unknown tokens as-is
        filt = filt.strip() or _default_filter(nodes[nid].unit if nid in nodes else "")
        formatted = _apply_filter(vals[nid], filt)
        return f'<span class="mv" data-node="{nid}">{formatted}</span>'

    return _TOKEN_RE.sub(sub, template)


def validate_template(text: str) -> None:
    """Raise ValueError if a bare numeric value is found outside a {{ }} token."""
    # Strip existing tokens so their internal numbers don't trigger the check
    stripped = _TOKEN_RE.sub("", text)
    m = _NUMERIC_RE.search(stripped)
    if m:
        ctx = stripped[max(0, m.start()-20):m.end()+20].replace("\n", " ")
        raise ValueError(
            f"Literal number '{m.group()}' found in template prose. "
            f"Reference the model node instead. Context: …{ctx}…"
        )
