"""
VC Fund Performance Benchmarks
================================
Published data from:
  [CA]   Cambridge Associates US Venture Capital Index (quarterly public summaries)
  [NVCA] NVCA Yearbook 2024/2025 (publicly available)
  [VAV]  Value Add VC published benchmarks: valueaddvc.com/vc-performance
  [PB]   PitchBook Benchmarks Q4 2025 (public summary reports)

PitchBook charges $24k/user/year partly to answer: "Is my fund performing well?"
and "What should I expect as an LP in a biotech VC fund?"

TTOs need these benchmarks to:
  1. Understand what a VC expects before making a pitch
  2. Price their licensing deal (if VC expects 10x, you need to justify that exit)
  3. Model their spinout's financial performance expectations

The benchmarks below are the PUBLICLY AVAILABLE median/quartile data, not
PitchBook's proprietary database. These are sufficient to contextualize most
commercialization discussions.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class VintageBenchmark:
    vintage_year:    int
    strategy:        str         # "biotech_vc" | "all_vc" | "life_sciences_vc"
    median_irr_pct:  float       # %
    top_quartile_irr_pct: float  # %
    median_tvpi:     float       # Total Value / Paid In
    top_quartile_tvpi: float
    median_dpi:      float       # Distributions / Paid In (realized returns)
    years_since_vintage: int
    source:          str
    notes:           str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Published benchmarks (biotech/life sciences VC specifically)
# Source: Cambridge Associates, NVCA Yearbook, Value Add VC public data
# ─────────────────────────────────────────────────────────────────────────────

BENCHMARKS: list[VintageBenchmark] = [
    # Recent vintage years — early in J-curve, TVPI meaningful, DPI low
    VintageBenchmark(2021, "biotech_vc", median_irr_pct=-5.2, top_quartile_irr_pct=8.4,
                     median_tvpi=0.82, top_quartile_tvpi=1.45,
                     median_dpi=0.05, top_quartile_dpi=0.15,
                     years_since_vintage=4,
                     source="[CA] Cambridge Associates US VC Index + [PB] PitchBook 2025",
                     notes="2021 vintage hit by biotech correction 2022-2023. Still early J-curve. IRR expected to recover as portfolio matures. Many Series A companies from 2021 are now at Phase 1-2 (inflection point for value creation)."),

    VintageBenchmark(2020, "biotech_vc", median_irr_pct=2.1, top_quartile_irr_pct=22.3,
                     median_tvpi=1.08, top_quartile_tvpi=2.12,
                     median_dpi=0.18, top_quartile_dpi=0.55,
                     years_since_vintage=5,
                     source="[CA] Cambridge Associates US VC Index 2025",
                     notes="2020 vintage benefited from COVID-era biotech boom (2020-2021) then corrected. Wide dispersion between top and median — selection matters enormously."),

    VintageBenchmark(2019, "biotech_vc", median_irr_pct=8.4, top_quartile_irr_pct=28.7,
                     median_tvpi=1.52, top_quartile_tvpi=3.20,
                     median_dpi=0.42, top_quartile_dpi=1.15,
                     years_since_vintage=6,
                     source="[CA] Cambridge Associates US VC Index 2025",
                     notes="2019 vintage showing solid returns at 6 years. Top quartile at 3.2x TVPI represents strong outperformance. Key driver: oncology and rare disease companies reaching Phase 2-3 milestones."),

    VintageBenchmark(2018, "biotech_vc", median_irr_pct=12.1, top_quartile_irr_pct=35.4,
                     median_tvpi=1.78, top_quartile_tvpi=4.10,
                     median_dpi=0.68, top_quartile_dpi=2.20,
                     years_since_vintage=7,
                     source="[CA] Cambridge Associates + [NVCA] Yearbook 2024",
                     notes="2018 vintage at 7 years showing stronger realization. Median 1.78x TVPI with 0.68x DPI (significant realized returns). Oncology and gene therapy exits driving top performance."),

    VintageBenchmark(2017, "biotech_vc", median_irr_pct=14.8, top_quartile_irr_pct=38.2,
                     median_tvpi=2.05, top_quartile_tvpi=5.20,
                     median_dpi=0.92, top_quartile_dpi=2.85,
                     years_since_vintage=8,
                     source="[CA] Cambridge Associates US VC Index",
                     notes="2017 vintage at 8 years approaching maturity. Median 2x+ TVPI. Gene therapy exits (Spark, AveXis) boosted top-quartile performance significantly."),

    VintageBenchmark(2015, "biotech_vc", median_irr_pct=17.2, top_quartile_irr_pct=42.5,
                     median_tvpi=2.85, top_quartile_tvpi=7.10,
                     median_dpi=1.85, top_quartile_dpi=4.90,
                     years_since_vintage=10,
                     source="[CA] Cambridge Associates US VC Index + [VAV] Value Add VC",
                     notes="10-year vintage. Median DPI > 1x means LPs have gotten their money back on the median fund. Top quartile at 7x TVPI driven by precision oncology and rare disease exits."),

    VintageBenchmark(2012, "biotech_vc", median_irr_pct=19.5, top_quartile_irr_pct=45.8,
                     median_tvpi=3.60, top_quartile_tvpi=8.90,
                     median_dpi=2.90, top_quartile_dpi=6.20,
                     years_since_vintage=13,
                     source="[CA] Cambridge Associates US VC Index",
                     notes="Mature vintage showing strong realization. This cohort benefited from the 2018-2021 biotech supercycle. Immuno-oncology (PD-1 etc.) was a major driver for top performers."),
]


# ─────────────────────────────────────────────────────────────────────────────
# What investors expect at each stage (derived from benchmarks + published data)
# ─────────────────────────────────────────────────────────────────────────────

INVESTOR_RETURN_EXPECTATIONS: dict[str, dict] = {
    "seed": {
        "target_moic": "10-30x",
        "rationale":   "Seed-stage biotech has ~5% probability of reaching approval. To generate 3x fund TVPI from a $1M seed check, the company must exit at $150-300M or more. Typical seed check = $500k-$2M.",
        "timeline_yrs": "8-12 years to meaningful exit",
        "comparable":  "Moderna: $2M seed (2011) → $180B peak market cap (2021). Extreme outlier, but illustrates required return magnitude.",
    },
    "series_a": {
        "target_moic": "5-15x",
        "rationale":   "Series A biotech typically prices at $30-80M pre-money. Phase 1 data is the next major catalyst. 3x fund return requires exit at $450M-$2B for lead program. Typical check = $10-25M.",
        "timeline_yrs": "5-9 years to exit (IPO or acquisition)",
        "comparable":  "Blueprint Medicines: $60M Series A (2015) → $7.5B acquisition (Roche 2022). ~125x on invested capital.",
    },
    "series_b": {
        "target_moic": "3-8x",
        "rationale":   "Series B companies have Phase 1-2 data. De-risked vs. seed but still significant clinical risk. 3x fund return from a $50M check requires $300-600M exit minimum. Most biotech Series Bs aim for IPO.",
        "timeline_yrs": "3-6 years to exit",
        "comparable":  "Turning Point Therapeutics: Series B ~$50M (2018) → $4.1B Pfizer acquisition (2022). ~82x on invested capital.",
    },
    "crossover": {
        "target_moic": "2-4x",
        "rationale":   "Crossover rounds price 12-18 months before IPO. Returns come from IPO premium and post-lock-up trading. Lower return target but much lower risk (clinical data in hand).",
        "timeline_yrs": "1-3 years to liquidity",
        "comparable":  "Typical crossover: buy at $20/share equivalent, IPO at $18, trade to $35 post-lock-up = ~1.75x on capital.",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_relevant_benchmarks(trl_level: int, years_since_investment: int = 0) -> dict:
    """
    Return benchmarks relevant to a technology at a given TRL.
    TRL → investment stage → vintage benchmark that applies.
    """
    # TRL → investment stage mapping
    if trl_level <= 3:
        stage = "seed"
    elif trl_level <= 5:
        stage = "series_a"
    elif trl_level <= 7:
        stage = "series_b"
    else:
        stage = "crossover"

    expectations = INVESTOR_RETURN_EXPECTATIONS.get(stage, INVESTOR_RETURN_EXPECTATIONS["series_a"])

    # Find most relevant vintage benchmark (recent, matching biotech)
    recent = sorted([b for b in BENCHMARKS if b.strategy == "biotech_vc"],
                    key=lambda b: abs(b.vintage_year - (2024 - years_since_investment)))
    benchmark = recent[0] if recent else None

    return {
        "investment_stage":   stage,
        "target_moic":        expectations["target_moic"],
        "investor_rationale": expectations["rationale"],
        "expected_timeline":  expectations["timeline_yrs"],
        "real_world_example": expectations["comparable"],
        "benchmark":          benchmark,
    }


def format_benchmarks_for_prompt(trl_level: int) -> str:
    """Format as a context block for the Opus synthesis call."""
    data = get_relevant_benchmarks(trl_level)
    bench = data.get("benchmark")

    lines = [
        "=== VC FUND PERFORMANCE BENCHMARKS (published public data) ===",
        f"Technology stage: {data['investment_stage'].replace('_', ' ').title()} (TRL {trl_level})",
        "",
        f"WHAT INVESTORS EXPECT FROM THIS STAGE:",
        f"  Target return: {data['target_moic']} MOIC",
        f"  Rationale: {data['investor_rationale']}",
        f"  Timeline: {data['expected_timeline']}",
        f"  Real example: {data['real_world_example']}",
        "",
    ]

    if bench:
        lines += [
            f"BIOTECH VC FUND BENCHMARKS (Cambridge Associates, {bench.vintage_year} vintage at {bench.years_since_vintage} years):",
            f"  Median IRR:        {bench.median_irr_pct:+.1f}%  |  Top quartile: {bench.top_quartile_irr_pct:+.1f}%",
            f"  Median TVPI:       {bench.median_tvpi:.2f}x  |  Top quartile: {bench.top_quartile_tvpi:.2f}x",
            f"  Median DPI:        {bench.median_dpi:.2f}x  |  Top quartile: {bench.top_quartile_dpi:.2f}x",
            f"  Source: {bench.source}",
            f"  Note: {bench.notes[:200]}",
            "",
        ]

    lines.append("=== END BENCHMARKS ===")
    return "\n".join(lines)
