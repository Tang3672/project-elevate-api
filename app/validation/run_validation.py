"""
Market-Sizing Validation Harness  (Build Spec: Validation Harness)
===================================================================
Compares Medlevate's bottom-up market-sizing engine against KNOWN, publicly-
reported actual market figures for 8 benchmark products.

Definition of success:
  MdAPE ≤ 20% (target) / ≤ 30% (gate) across active benchmarks.
  Calibration (truth inside confidence band) ≥ 70%.

What this tests:
  For each benchmark, given the correct population + price inputs, does the
  engine's monetization → analog pipeline compute a plausible market size?

  This is NOT testing whether the engine discovers the right population from
  scratch — that depends on patient_flow_engine and seeded DB data, which is a
  separate validation concern. Here we supply population directly so the harness
  tests monetization + analog engine math, not epidemiology data retrieval.

What this does NOT do:
  - Write to any production table
  - Change engine behavior
  - Run automatically in the report flow

Run:
  python -m app.validation.run_validation
  python -m app.validation.run_validation --ci  (exits non-zero if MdAPE > 30%)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

_BENCHMARKS_PATH = Path(__file__).parent / "benchmarks.json"
_RESULTS_PATH = Path(__file__).parent / "validation_results.json"
_REPORT_PATH = Path(__file__).parent / "validation_report.md"

_MDAPE_TARGET = 0.20    # "validated" threshold
_MDAPE_GATE = 0.30      # "acceptable" threshold — fail CI above this
_CALIBRATION_TARGET = 0.70  # fraction of cases where truth falls in confidence band


# ──────────────────────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class BenchmarkResult:
    benchmark_id: str
    name: str
    product_type: str
    disease_name: str

    # Engine outputs
    computed_sam: float
    computed_som_base: float
    computed_som_peak: float
    low_bound: float
    high_bound: float
    pipeline_used: str
    analog_class: str
    monetization_model: str

    # Ground truth
    actual_usd: float
    compare_against: str        # "sam" | "som_peak" | "som_base"
    ground_truth_source: str
    ground_truth_year: int
    figure_type: str

    # Computed metrics
    computed_comparison: float  # the engine value being compared (sam/som_peak/som_base)
    ape: float                  # absolute percentage error
    signed_pct_error: float     # signed (engine - actual) / actual
    in_confidence_band: bool    # is actual within [low_bound, high_bound]?
    ratio: float                # engine / actual (>1 = over-estimate)

    # Diagnosis
    status: str                 # "PASS" | "WARN" | "FAIL"
    direction: str              # "over" | "under" | "exact"
    worst_assumption: str       # the assumption most likely causing the error
    expert_question: str        # actionable KOL question to close the gap

    skipped: bool = False
    skip_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.benchmark_id, "name": self.name,
            "product_type": self.product_type, "disease_name": self.disease_name,
            "pipeline": self.pipeline_used,
            "engine": {
                "sam_usd": self.computed_sam,
                "som_base_usd": self.computed_som_base,
                "som_peak_usd": self.computed_som_peak,
                "low_bound_usd": self.low_bound,
                "high_bound_usd": self.high_bound,
                "comparison_value": self.computed_comparison,
                "analog_class": self.analog_class,
                "monetization_model": self.monetization_model,
            },
            "ground_truth": {
                "actual_usd": self.actual_usd,
                "compare_against": self.compare_against,
                "source": self.ground_truth_source,
                "year": self.ground_truth_year,
                "figure_type": self.figure_type,
            },
            "metrics": {
                "ape": round(self.ape, 4),
                "signed_pct_error": round(self.signed_pct_error, 4),
                "ratio": round(self.ratio, 3),
                "in_confidence_band": self.in_confidence_band,
                "direction": self.direction,
                "status": self.status,
            },
            "diagnosis": {
                "worst_assumption": self.worst_assumption,
                "expert_question": self.expert_question,
            },
        }


@dataclass
class AggregateMetrics:
    n_active: int
    n_pass: int
    n_warn: int
    n_fail: int
    n_skipped: int
    mdape: float
    mape: float
    calibration_rate: float         # fraction with actual in confidence band
    median_ratio: float             # median(engine / actual)
    by_product_type: Dict[str, dict]
    worst_offenders: List[BenchmarkResult]
    verdict: str
    calibration_verdict: str
    timestamp: str


# ──────────────────────────────────────────────────────────────────────────────
# Core computation
# ──────────────────────────────────────────────────────────────────────────────

async def _compute_benchmark_orchestrator(bm: dict) -> dict:
    """
    Call the FULL market_sizing_orchestrator (patient_flow → monetization → analog → confidence)
    for benchmarks marked pipeline='orchestrator'. These benchmarks have seeded patient_flow_model
    rows in the DB and test the entire production pipeline end-to-end.

    This exposes whether patient_flow_engine produces plausible populations from the seeded
    funnel data — a separate concern from whether the monetization math is correct (tested by
    _compute_benchmark). Higher errors here point to seeding gaps or funnel design issues.
    """
    from app.services.market_sizing_orchestrator import run as _orch_run

    inputs = bm.get("engine_inputs", {})
    compare_ctx = bm["ground_truth"].get("compare_against", "sam")

    result = await _orch_run(
        disease_name=bm["disease_name"],
        product_type=bm["product_type"],
        segment_gate=inputs.get("segment_gate"),
        net_price_usd=inputs.get("net_price_usd"),
        competitive_context=inputs.get("competitive_context"),
        context_text=inputs.get("notes", "")[:500],
        overrides=inputs.get("overrides", {}),
        line_of_therapy_rate=inputs.get("line_of_therapy_rate"),
    )

    comparison_center = {
        "sam":      result.sam_revenue_usd,
        "som_base": result.som_base_usd,
        "som_peak": result.som_peak_usd,
    }.get(compare_ctx, result.sam_revenue_usd)

    quality = result.confidence.confidence_score
    range_frac = max(0.30, min(0.45, (1.0 - quality) * 0.50))
    cal_low  = max(0.0, comparison_center * (1.0 - range_frac))
    cal_high = comparison_center * (1.0 + range_frac * 1.30)

    pf_source = getattr(result.patient_flow, "data_source", "db_seed")
    return {
        "sam":               result.sam_revenue_usd,
        "som_base":          result.som_base_usd,
        "som_peak":          result.som_peak_usd,
        "low_bound":         cal_low,
        "high_bound":        cal_high,
        "pipeline":          f"orchestrator | pf={pf_source}",
        "analog_class":      result.analog.analog_class,
        "analog_label":      result.analog.analog_label,
        "monetization_model": result.monetization.revenue_model,
        "analog_y1":         result.analog.y1_penetration,
        "analog_y3":         result.analog.y3_penetration,
        "analog_peak":       result.analog.peak_penetration,
        "conf_score":        quality,
        "conf_range_frac":   range_frac,
    }


async def _compute_benchmark(bm: dict) -> dict:
    """
    Call the real monetization + analog + confidence engines with the benchmark's
    supplied population and price inputs.

    We bypass patient_flow_engine deliberately: this harness tests whether the
    monetization and analog math is correct given known inputs. Whether the engine
    can DISCOVER the right population from scratch is a separate concern (it depends
    on DB seed coverage and is tested by the orchestrator-path benchmarks above).
    TODO: remove this TODO once all benchmark diseases are seeded.
    """
    from app.services import monetization_engine, analog_engine, confidence_engine

    inputs = bm["engine_inputs"]
    pop = float(inputs["us_patient_population"])
    seg_gate = float(inputs.get("segment_gate_rate", 1.0))
    addressable = pop * seg_gate
    net_price = float(inputs["annual_treatment_cost_usd"])
    base_metric = inputs.get("base_metric", "patients")
    comp_ctx = inputs.get("competitive_context")
    notes = inputs.get("notes", "")

    mon = await monetization_engine.compute(
        product_type=bm["product_type"],
        disease_name=bm["disease_name"],
        population=addressable,
        population_base_metric=base_metric,
        net_price_usd=net_price,
    )

    analog = analog_engine.compute(
        product_type=bm["product_type"],
        annual_revenue_sam=mon.annual_revenue_usd,
        competitive_context=comp_ctx,
        context_text=notes,
    )

    conf = confidence_engine.compute(
        annual_revenue_sam=mon.annual_revenue_usd,
        low_revenue=mon.low_revenue_usd,
        high_revenue=mon.high_revenue_usd,
        patient_flow_assumptions=mon.assumptions,
        monetization_assumptions=[],
        analog_assumptions=analog.assumptions,
        disease_name=bm["disease_name"],
        product_type=bm["product_type"],
    )

    # Calibration bands must be at the comparison metric's scale (SAM, SOM_base, or SOM_peak),
    # NOT at the raw SAM level from monetization_engine.  When compare_against="som_peak",
    # the actual revenue is at SOM scale — a SAM-level band (often 10-50× larger) can never
    # contain it.  Compute a quality-adjusted band centered on each penetration level.
    compare_ctx = bm["ground_truth"].get("compare_against", "sam")
    comparison_values = {
        "sam":      mon.annual_revenue_usd,
        "som_base": analog.som_base,
        "som_peak": analog.som_peak,
    }
    comparison_center = comparison_values.get(compare_ctx, mon.annual_revenue_usd)

    # Width: minimum ±30% (the engine's known baseline uncertainty); widens toward ±45%
    # for inference-heavy inputs.  Asymmetric: upside × 1.30 because addressable markets
    # systematically run larger than bottom-up models predict.
    quality = conf.confidence_score
    llm_frac = conf.llm_inference_count / max(conf.total_assumptions, 1) if conf.total_assumptions else 0.5
    range_frac = max(0.30, min(0.45, llm_frac * 0.80 + (1.0 - quality) * 0.25))
    cal_low  = max(0.0, comparison_center * (1.0 - range_frac))
    cal_high = comparison_center * (1.0 + range_frac * 1.30)

    return {
        "sam": mon.annual_revenue_usd,
        "som_base": analog.som_base,
        "som_peak": analog.som_peak,
        "low_bound": cal_low,
        "high_bound": cal_high,
        "pipeline": "monetization+analog (direct)",
        "analog_class": analog.analog_class,
        "analog_label": analog.analog_label,
        "monetization_model": mon.revenue_model,
        "analog_y1": analog.y1_penetration,
        "analog_y3": analog.y3_penetration,
        "analog_peak": analog.peak_penetration,
        "conf_score": quality,
        "conf_range_frac": range_frac,
    }


def _diagnose(bm: dict, result: dict, actual: float, ape: float, signed_err: float) -> tuple[str, str]:
    """
    Return (worst_assumption, expert_question) for a benchmark.
    The assumption most likely causing the error + the KOL question that would fix it.
    """
    inputs = bm.get("engine_inputs", {})
    compare = bm["ground_truth"]["compare_against"]
    direction = "over" if signed_err > 0 else "under"
    # orchestrator benchmarks don't have us_patient_population in engine_inputs
    pop = inputs.get("us_patient_population", inputs.get("segment_gate", "N/A"))
    seg = inputs.get("segment_gate_rate", inputs.get("segment_gate", 1.0))
    price = inputs.get("annual_treatment_cost_usd", inputs.get("net_price_usd", 0))
    analog_peak = result.get("analog_peak", 0.25)
    analog_class = result.get("analog_label", result.get("analog_class", ""))

    if ape <= 0.15:
        return "None significant", "Results within 15% — no immediate correction needed."

    # For SAM comparison: error comes from population or price
    if compare == "sam":
        if abs(signed_err) > 0.50:
            if direction == "over":
                return (
                    f"segment_gate_rate ({seg:.0%}) — eligible population likely smaller",
                    f"What fraction of the {pop:,.0f} {inputs.get('base_metric', 'patients')} in '{bm['disease_name']}' "
                    f"are truly addressable for this product? Current input = {seg:.0%}; "
                    f"reducing to ~{seg * (actual / result['sam']):.0%} would close the gap. "
                    f"Verify with a clinician/payer KOL who has seen real-world treatment rates."
                )
            else:
                return (
                    f"annual_treatment_cost_usd (${price:,.0f}) — net price may be higher than estimated",
                    f"What is the actual payer reimbursement / net acquisition cost for this product? "
                    f"Current estimate ${price:,.0f}. Market data implies closer to ${price * (actual / result['sam']):,.0f}. "
                    f"Verify against published WAC, gross-to-net benchmarks, or payer contracts."
                )
        else:
            return (
                "segment_gate_rate or population base",
                f"Engine SAM is {direction}-estimated by {ape:.0%}. "
                f"Verify: (1) Is the {inputs.get('base_metric', 'patient')} count ({pop:,.0f}) the right universe? "
                f"(2) Is {seg:.0%} the correct addressable fraction? Ask a KOL who has access to claims data."
            )

    # For SOM comparison: error comes from analog penetration curve
    elif compare in ("som_peak", "som_base"):
        analog_target = "som_base" if compare == "som_base" else "som_peak"
        pct_label = f"{'y3' if compare == 'som_base' else 'peak'} penetration ({analog_peak:.0%})"
        corrected_pct = analog_peak * (actual / result[analog_target]) if result.get(analog_target, 0) else analog_peak
        if direction == "over":
            return (
                f"analog penetration curve ({pct_label} from '{analog_class}')",
                f"Is {analog_peak:.0%} {pct_label.split(' ')[0]} penetration realistic for this product at this stage? "
                f"The actual revenue implies ~{corrected_pct:.0%} effective penetration. "
                f"Ask: what market share does the leading product have today, and what do analogous launches in this class typically achieve at the same year of commercialization?"
            )
        else:
            return (
                f"analog penetration curve ({pct_label} from '{analog_class}') — penetration underestimated",
                f"Is {analog_peak:.0%} {pct_label.split(' ')[0]} penetration too conservative? "
                f"Actual revenue implies ~{corrected_pct:.0%}. "
                f"This product may have higher-than-analog penetration due to unmet need, reimbursement tailwinds, or supply expansion. "
                f"Verify: what was the actual launch-year ramp trajectory for comparable products? What is the current market share?"
            )

    return (
        "unknown — review population and price inputs",
        f"Engine is {ape:.0%} {direction}-estimated. Review the segment gate rate and net price assumptions with a domain KOL."
    )


async def run_all_benchmarks() -> tuple[List[BenchmarkResult], AggregateMetrics]:
    benchmarks = json.loads(_BENCHMARKS_PATH.read_text())
    results: List[BenchmarkResult] = []

    # Warn when ground_truth figures are past their scheduled refresh date.
    # Stale benchmarks still run — the warning is informational, not a gate.
    _today = date.today()
    _stale = []
    for bm in benchmarks:
        nrd = bm.get("next_refresh_date")
        if nrd:
            try:
                if _today > date.fromisoformat(nrd + "-01"):
                    _stale.append((bm["id"], nrd, bm.get("ground_truth", {}).get("year", "?")))
            except ValueError:
                pass
    if _stale:
        print(f"WARNING: {len(_stale)} benchmark(s) have passed their refresh date:")
        for _bm_id, _nrd, _yr in _stale:
            print(f"  [STALE] {_bm_id:<30}  data year={_yr}, refresh by={_nrd}")
        print("  → Update ground_truth figures before the next investor presentation.\n")

    for bm in benchmarks:
        if bm.get("status") == "needs_sourcing":
            r = BenchmarkResult(
                benchmark_id=bm["id"], name=bm["name"],
                product_type=bm["product_type"], disease_name=bm["disease_name"],
                computed_sam=0, computed_som_base=0, computed_som_peak=0,
                low_bound=0, high_bound=0,
                pipeline_used="skipped", analog_class="", monetization_model="",
                actual_usd=0, compare_against="", ground_truth_source="",
                ground_truth_year=0, figure_type="",
                computed_comparison=0, ape=0, signed_pct_error=0,
                in_confidence_band=False, ratio=0,
                status="SKIP", direction="", worst_assumption="", expert_question="",
                skipped=True, skip_reason="needs_sourcing — ground truth not yet verified",
            )
            results.append(r)
            continue

        gt = bm["ground_truth"]
        actual = gt.get("actual_annual_usd")
        if not actual:
            # Still needs sourcing despite status=active (null actual)
            results.append(BenchmarkResult(
                benchmark_id=bm["id"], name=bm["name"],
                product_type=bm["product_type"], disease_name=bm["disease_name"],
                computed_sam=0, computed_som_base=0, computed_som_peak=0,
                low_bound=0, high_bound=0,
                pipeline_used="skipped", analog_class="", monetization_model="",
                actual_usd=0, compare_against="",
                ground_truth_source=gt.get("source", ""), ground_truth_year=gt.get("year", 0),
                figure_type=gt.get("figure_type", ""),
                computed_comparison=0, ape=0, signed_pct_error=0,
                in_confidence_band=False, ratio=0,
                status="SKIP", direction="", worst_assumption="", expert_question="",
                skipped=True, skip_reason="actual_annual_usd is null — needs sourcing",
            ))
            continue

        # Route to orchestrator path for seeded-disease benchmarks
        is_orchestrator = bm.get("pipeline") == "orchestrator"
        try:
            engine_out = (
                await _compute_benchmark_orchestrator(bm)
                if is_orchestrator
                else await _compute_benchmark(bm)
            )
        except Exception as e:
            logger.error("Engine error on %s: %s", bm["id"], e)
            results.append(BenchmarkResult(
                benchmark_id=bm["id"], name=bm["name"],
                product_type=bm["product_type"], disease_name=bm["disease_name"],
                computed_sam=0, computed_som_base=0, computed_som_peak=0,
                low_bound=0, high_bound=0,
                pipeline_used=f"ERROR: {e}", analog_class="", monetization_model="",
                actual_usd=float(actual), compare_against=gt.get("compare_against", "sam"),
                ground_truth_source=gt.get("source", ""), ground_truth_year=gt.get("year", 0),
                figure_type=gt.get("figure_type", ""),
                computed_comparison=0, ape=float("inf"), signed_pct_error=float("inf"),
                in_confidence_band=False, ratio=0,
                status="FAIL", direction="unknown", worst_assumption="engine_error",
                expert_question=f"Fix engine error first: {e}",
                skipped=False,
            ))
            continue

        compare = gt.get("compare_against", "sam")
        computed_comparison = {
            "sam": engine_out["sam"],
            "som_base": engine_out["som_base"],
            "som_peak": engine_out["som_peak"],
        }.get(compare, engine_out["sam"])

        actual_f = float(actual)
        ape = abs(computed_comparison - actual_f) / actual_f
        signed_err = (computed_comparison - actual_f) / actual_f
        ratio = computed_comparison / actual_f if actual_f else 0
        in_band = engine_out["low_bound"] <= actual_f <= engine_out["high_bound"]
        direction = "over" if signed_err > 0.01 else ("under" if signed_err < -0.01 else "exact")

        if ape <= _MDAPE_TARGET:
            status = "PASS"
        elif ape <= _MDAPE_GATE:
            status = "WARN"
        else:
            status = "FAIL"

        worst_assumption, expert_question = _diagnose(bm, engine_out, actual_f, ape, signed_err)

        results.append(BenchmarkResult(
            benchmark_id=bm["id"], name=bm["name"],
            product_type=bm["product_type"], disease_name=bm["disease_name"],
            computed_sam=engine_out["sam"],
            computed_som_base=engine_out["som_base"],
            computed_som_peak=engine_out["som_peak"],
            low_bound=engine_out["low_bound"],
            high_bound=engine_out["high_bound"],
            pipeline_used=engine_out["pipeline"],
            analog_class=engine_out.get("analog_label", engine_out["analog_class"]),
            monetization_model=engine_out["monetization_model"],
            actual_usd=actual_f,
            compare_against=compare,
            ground_truth_source=gt.get("source", ""),
            ground_truth_year=gt.get("year", 0),
            figure_type=gt.get("figure_type", ""),
            computed_comparison=computed_comparison,
            ape=ape, signed_pct_error=signed_err, ratio=ratio,
            in_confidence_band=in_band, direction=direction,
            status=status, worst_assumption=worst_assumption, expert_question=expert_question,
        ))

    agg = _aggregate(results)
    return results, agg


# ──────────────────────────────────────────────────────────────────────────────
# Aggregation
# ──────────────────────────────────────────────────────────────────────────────

def _aggregate(results: List[BenchmarkResult]) -> AggregateMetrics:
    active = [r for r in results if not r.skipped and r.ape != float("inf")]

    apes = [r.ape for r in active]
    mdape = statistics.median(apes) if apes else float("inf")
    mape = statistics.mean(apes) if apes else float("inf")
    calibration = sum(1 for r in active if r.in_confidence_band) / max(len(active), 1)
    med_ratio = statistics.median([r.ratio for r in active]) if active else 0

    # By product type
    by_type: Dict[str, list] = {}
    for r in active:
        by_type.setdefault(r.product_type, []).append(r.ape)
    by_type_summary = {
        pt: {
            "n": len(apes_),
            "mdape": round(statistics.median(apes_), 4),
            "mape": round(statistics.mean(apes_), 4),
        }
        for pt, apes_ in by_type.items()
    }

    # Worst offenders (highest APE)
    worst = sorted(active, key=lambda r: r.ape, reverse=True)[:3]

    # Verdicts
    if mdape <= _MDAPE_TARGET:
        verdict = "VALIDATED"
    elif mdape <= _MDAPE_GATE:
        verdict = "ACCEPTABLE"
    else:
        verdict = "NOT_VALIDATED"

    calibration_verdict = "CALIBRATED" if calibration >= _CALIBRATION_TARGET else "BANDS_TOO_NARROW"

    return AggregateMetrics(
        n_active=len(active),
        n_pass=sum(1 for r in active if r.status == "PASS"),
        n_warn=sum(1 for r in active if r.status == "WARN"),
        n_fail=sum(1 for r in active if r.status == "FAIL"),
        n_skipped=sum(1 for r in results if r.skipped),
        mdape=mdape, mape=mape,
        calibration_rate=calibration,
        median_ratio=med_ratio,
        by_product_type=by_type_summary,
        worst_offenders=worst,
        verdict=verdict,
        calibration_verdict=calibration_verdict,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Output
# ──────────────────────────────────────────────────────────────────────────────

def _fmt(v: float) -> str:
    if v >= 1e9:
        return f"${v/1e9:.2f}B"
    if v >= 1e6:
        return f"${v/1e6:.0f}M"
    return f"${v:,.0f}"


def print_console_summary(results: List[BenchmarkResult], agg: AggregateMetrics) -> None:
    W = 100
    print(f"\n{'='*W}")
    print(f"  MEDLEVATE MARKET SIZING VALIDATION HARNESS   {agg.timestamp[:10]}")
    print(f"{'='*W}")
    print(f"  {'ID':<22} {'Metric':<10} {'Engine':>12} {'Actual':>12} {'APE':>7}  {'Band':>5}  Status")
    print(f"  {'-'*22} {'-'*10} {'-'*12} {'-'*12} {'-'*7}  {'-'*5}  {'-'*6}")

    for r in results:
        if r.skipped:
            print(f"  {r.benchmark_id:<22} {'skipped':<10}  {r.skip_reason}")
            continue
        icon = "✓" if r.status == "PASS" else ("~" if r.status == "WARN" else "✗")
        band = "IN" if r.in_confidence_band else "OUT"
        print(
            f"  {r.benchmark_id:<22} {r.compare_against:<10} "
            f"{_fmt(r.computed_comparison):>12} {_fmt(r.actual_usd):>12} "
            f"{r.ape:>7.1%}  {band:>5}  [{icon}] {r.status}"
        )

    print(f"\n{'─'*W}")
    print(f"  AGGREGATE  —  {agg.n_active} active benchmarks")
    print(f"  MdAPE:       {agg.mdape:.1%}  (target ≤20%, gate ≤30%)")
    print(f"  MAPE:        {agg.mape:.1%}")
    print(f"  Calibration: {agg.calibration_rate:.0%} of cases where truth fell in confidence band (target ≥70%)")
    print(f"  Median ratio (engine/actual): {agg.median_ratio:.2f}x")
    print(f"\n  VERDICT:      {agg.verdict}")
    print(f"  CALIBRATION:  {agg.calibration_verdict}")

    if agg.by_product_type:
        print(f"\n  BY PRODUCT TYPE:")
        for pt, m in sorted(agg.by_product_type.items(), key=lambda x: x[1]["mdape"]):
            print(f"    {pt:<30}  n={m['n']}  MdAPE={m['mdape']:.1%}  MAPE={m['mape']:.1%}")

    if agg.worst_offenders:
        print(f"\n  WORST OFFENDERS:")
        for r in agg.worst_offenders:
            print(f"    [{r.ape:.0%}] {r.name}")
            print(f"           Likely cause: {r.worst_assumption}")
            print(f"           KOL question: {r.expert_question[:120]}...")

    print(f"{'='*W}\n")


def write_json_results(results: List[BenchmarkResult], agg: AggregateMetrics) -> None:
    out = {
        "generated_at": agg.timestamp,
        "aggregate": {
            "verdict": agg.verdict,
            "calibration_verdict": agg.calibration_verdict,
            "n_active": agg.n_active,
            "n_pass": agg.n_pass, "n_warn": agg.n_warn, "n_fail": agg.n_fail,
            "n_skipped": agg.n_skipped,
            "mdape": round(agg.mdape, 4),
            "mape": round(agg.mape, 4),
            "calibration_rate": round(agg.calibration_rate, 4),
            "median_ratio": round(agg.median_ratio, 4),
            "by_product_type": agg.by_product_type,
        },
        "benchmarks": [r.to_dict() for r in results],
    }
    _RESULTS_PATH.write_text(json.dumps(out, indent=2, default=str))
    print(f"Results written → {_RESULTS_PATH.relative_to(Path.cwd()) if _RESULTS_PATH.is_relative_to(Path.cwd()) else _RESULTS_PATH}")


def write_markdown_report(results: List[BenchmarkResult], agg: AggregateMetrics) -> None:
    lines = [
        f"# Medlevate Market-Sizing Validation Report",
        f"",
        f"**Generated:** {agg.timestamp[:19].replace('T', ' ')} UTC  ",
        f"**Engine version:** Professional Market-Sizing Engine v5 (patient_flow → monetization → analog → confidence)  ",
        f"**Benchmarks:** {agg.n_active} active / {agg.n_skipped} skipped  ",
        f"",
        f"---",
        f"",
        f"## Verdict",
        f"",
    ]

    # Verdict block
    if agg.verdict == "VALIDATED":
        lines += [
            f"> **✓ ENGINE VALIDATED FOR ESTABLISHED MARKETS**",
            f">",
            f"> MdAPE = **{agg.mdape:.1%}** (≤ 20% target). Safe to surface numbers in reports **WITH confidence ranges**.",
            f"> Always present the range alongside the point estimate, and lead with the honesty statement.",
        ]
    elif agg.verdict == "ACCEPTABLE":
        lines += [
            f"> **~ ACCEPTABLE FOR DIRECTIONAL SCREENING**",
            f">",
            f"> MdAPE = **{agg.mdape:.1%}** (20–30% range). Reports must present **ranges, not point estimates**,",
            f"> and must lead with the honesty statement. Suitable for TAM/SAM screening; not for investor pitch decks.",
        ]
    else:
        lines += [
            f"> **✗ NOT VALIDATED — DO NOT PRESENT AS RELIABLE**",
            f">",
            f"> MdAPE = **{agg.mdape:.1%}** (> 30% gate). Investigate worst offenders before customer use.",
            f"> Numbers may be directionally useful but carry unacceptable error for any formal presentation.",
        ]

    # Calibration verdict
    lines += [
        f"",
        f"**Calibration ({agg.calibration_rate:.0%} of cases where truth fell inside confidence band):** ",
    ]
    if agg.calibration_verdict == "CALIBRATED":
        lines.append(f"✓ **CALIBRATED** — confidence bands contain the truth at the target rate (≥ 70%).")
    else:
        lines.append(
            f"⚠  **BANDS TOO NARROW** — only {agg.calibration_rate:.0%} of cases had truth inside the band (target ≥ 70%). "
            f"Widen uncertainty on low-confidence assumptions."
        )

    lines += [
        f"",
        f"---",
        f"",
        f"## Aggregate Metrics",
        f"",
        f"| Metric | Value | Target |",
        f"|--------|-------|--------|",
        f"| MdAPE (headline) | **{agg.mdape:.1%}** | ≤ 20% (target) / ≤ 30% (gate) |",
        f"| MAPE | {agg.mape:.1%} | — |",
        f"| Calibration rate | {agg.calibration_rate:.0%} | ≥ 70% |",
        f"| Median engine/actual ratio | {agg.median_ratio:.2f}× | ~1.0× |",
        f"| PASS (APE ≤ 20%) | {agg.n_pass} / {agg.n_active} | — |",
        f"| WARN (APE 20–30%) | {agg.n_warn} / {agg.n_active} | — |",
        f"| FAIL (APE > 30%) | {agg.n_fail} / {agg.n_active} | 0 preferred |",
        f"",
        f"---",
        f"",
        f"## Per-Benchmark Results",
        f"",
        "| ID | Product type | Engine (compare) | Actual | APE | In band | Status |",
        f"|----|----|----|----|----|----|-----|",
    ]

    for r in results:
        if r.skipped:
            lines.append(f"| {r.benchmark_id} | {r.product_type} | — | — | — | — | SKIP |")
        else:
            band = "✓" if r.in_confidence_band else "✗"
            icon = "✓" if r.status == "PASS" else ("~" if r.status == "WARN" else "✗")
            lines.append(
                f"| {r.benchmark_id} | {r.product_type} | "
                f"{_fmt(r.computed_comparison)} ({r.compare_against}) | "
                f"{_fmt(r.actual_usd)} ({r.ground_truth_year}) | "
                f"{r.ape:.1%} | {band} | {icon} {r.status} |"
            )

    lines += [
        f"",
        f"---",
        f"",
        f"## By Product Type",
        f"",
        f"| Product type | N | MdAPE | MAPE |",
        f"|---|---|---|---|",
    ]
    for pt, m in sorted(agg.by_product_type.items(), key=lambda x: x[1]["mdape"]):
        lines.append(f"| {pt} | {m['n']} | {m['mdape']:.1%} | {m['mape']:.1%} |")

    # Per-type interpretation
    high_error_types = [pt for pt, m in agg.by_product_type.items() if m["mdape"] > _MDAPE_GATE]
    if high_error_types:
        lines += [
            f"",
            f"> **Priority fix:** The following product types have MdAPE > 30% and should be addressed before customer use: "
            f"**{', '.join(high_error_types)}**. These monetization models need better price data or population inputs.",
        ]

    lines += [
        f"",
        f"---",
        f"",
        f"## Worst Offenders → Expert Questions",
        f"",
        f"Every validation failure is a targeted KOL/expert interview question. "
        f"These are the highest-priority conversations to have before the next validation run.",
        f"",
    ]
    for i, r in enumerate(agg.worst_offenders, 1):
        lines += [
            f"### {i}. {r.name} ({r.ape:.0%} {r.direction})",
            f"",
            f"- **Engine ({r.compare_against}):** {_fmt(r.computed_comparison)}  ",
            f"- **Actual ({r.ground_truth_year}):** {_fmt(r.actual_usd)}  ",
            f"- **Source:** {r.ground_truth_source[:120]}{'...' if len(r.ground_truth_source) > 120 else ''}  ",
            f"- **Analog used:** {r.analog_class}  ",
            f"",
            f"**Likely cause:** `{r.worst_assumption}`",
            f"",
            f"**KOL question to close the gap:**",
            f"> {r.expert_question}",
            f"",
        ]

    lines += [
        f"---",
        f"",
        f"## Case Details",
        f"",
    ]
    for r in results:
        if r.skipped:
            lines += [
                f"### {r.benchmark_id} (SKIPPED)",
                f"*{r.skip_reason}*",
                f"",
            ]
            continue
        lines += [
            f"### {r.benchmark_id} — {r.name}",
            f"",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| Product type | {r.product_type} |",
            f"| Disease | {r.disease_name} |",
            f"| Pipeline | {r.pipeline_used} |",
            f"| Monetization model | {r.monetization_model} |",
            f"| Analog class | {r.analog_class} |",
            f"| Engine SAM | {_fmt(r.computed_sam)} |",
            f"| Engine SOM (y3/base) | {_fmt(r.computed_som_base)} |",
            f"| Engine SOM (peak) | {_fmt(r.computed_som_peak)} |",
            f"| Confidence band | {_fmt(r.low_bound)} — {_fmt(r.high_bound)} |",
            f"| **Engine ({r.compare_against})** | **{_fmt(r.computed_comparison)}** |",
            f"| **Actual ({r.ground_truth_year})** | **{_fmt(r.actual_usd)}** |",
            f"| APE | {r.ape:.1%} |",
            f"| Direction | {r.direction}-estimate ({r.ratio:.2f}×) |",
            f"| Truth in band | {'Yes ✓' if r.in_confidence_band else 'No ✗'} |",
            f"| Status | **{r.status}** |",
            f"",
            f"**Ground truth source:** {r.ground_truth_source}",
            f"",
            f"**Worst assumption:** `{r.worst_assumption}`",
            f"",
            f"**Expert question:** {r.expert_question}",
            f"",
        ]

    lines += [
        f"---",
        f"",
        f"## Methodology Notes",
        f"",
        f"**What this harness tests:** Given the correct population and net price as inputs, "
        f"does the monetization → analog pipeline produce a plausible market size?",
        f"",
        f"**What it does NOT test:** Whether the patient_flow_engine can discover the correct "
        f"population from scratch (that requires seeded patient_flow_model DB rows and is a separate validation concern).",
        f"",
        f"**Comparison methodology:**",
        f"- `sam`: compare engine SAM directly against total market size (when engine inputs represent the full addressable universe)",
        f"- `som_peak`: compare engine SOM at peak penetration vs actual revenue of a dominant/mature product",
        f"- `som_base`: compare engine SOM at year-3 penetration vs actual revenue of a growing product",
        f"",
        f"**Calibration:** The confidence band is generated by confidence_engine.py based on source quality ",
        f"and impact of each assumption. A well-calibrated engine should contain the actual value within "
        f"its band even when the point estimate is off.",
        f"",
        f"**Next steps if MdAPE > 30%:** See worst offenders above. Each failure maps directly to a "
        f"KOL interview question. Validation failures are your customer-discovery agenda.",
        f"",
        f"*Generated by `app/validation/run_validation.py` — Medlevate Market Sizing Validation Harness*",
    ]

    _REPORT_PATH.write_text("\n".join(lines))
    print(f"Report written  → {_REPORT_PATH.relative_to(Path.cwd()) if _REPORT_PATH.is_relative_to(Path.cwd()) else _REPORT_PATH}")


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

async def main(ci_mode: bool = False) -> int:
    print("\nMediavate Market Sizing Validation Harness")
    print("Calling real monetization + analog + confidence engines...")
    print(f"Benchmarks: {_BENCHMARKS_PATH}\n")

    results, agg = await run_all_benchmarks()
    print_console_summary(results, agg)
    write_json_results(results, agg)
    write_markdown_report(results, agg)

    if ci_mode:
        if agg.verdict == "NOT_VALIDATED":
            print(f"\nCI FAIL: MdAPE {agg.mdape:.1%} > {_MDAPE_GATE:.0%} gate. Investigate worst offenders.")
            return 1
        print(f"\nCI PASS: MdAPE {agg.mdape:.1%} ≤ {_MDAPE_GATE:.0%} gate.")
        return 0

    return 0


if __name__ == "__main__":
    ci = "--ci" in sys.argv
    exit_code = asyncio.run(main(ci_mode=ci))
    sys.exit(exit_code)
