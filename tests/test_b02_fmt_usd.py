"""B-02: canonical USD formatter tests."""
import pytest
from app.utils import fmt_usd


@pytest.mark.parametrize("value,expected", [
    # Sub-million → K only for values ≥ $10,000, never $0M
    (438_750,    "$439K"),
    (10_000,     "$10K"),       # threshold: exactly $10K
    (9_999,      "$9,999"),     # just below threshold: shown as full dollar
    (1_000,      "$1,000"),     # below threshold: full dollar, not $1K
    (999_999,    "$1000K"),     # right at the million boundary; K tier uses no thousands comma
    (500,        "$500"),
    (0,          "$0"),

    # Million tier → 1 decimal, never $0M for non-zero
    (1_000_000,   "$1.0M"),
    (1_400_000,   "$1.4M"),
    (400_000_000, "$400.0M"),

    # Billion tier
    (1_500_000_000, "$1.5B"),
    (12_000_000_000, "$12.0B"),
])
def test_fmt_usd(value, expected):
    assert fmt_usd(value) == expected


def test_fmt_usd_no_zero_m_for_sub_million():
    """The original bug: $438,750 formatted as $0.4M and then read as ~$0M."""
    result = fmt_usd(438_750)
    assert "M" not in result, f"Sub-million value formatted with M tier: {result}"
    assert result != "$0M"
    assert result != "$0.4M"


def test_fmt_usd_none_like():
    """Falsy non-zero-int inputs return em dash."""
    assert fmt_usd(None) == "—"
    assert fmt_usd("") == "—"


def test_fmt_usd_float_million():
    assert fmt_usd(2.5e6) == "$2.5M"


def test_fmt_usd_exactly_zero():
    assert fmt_usd(0) == "$0"
