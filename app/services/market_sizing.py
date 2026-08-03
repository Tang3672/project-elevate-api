"""
Segment-Based Market Sizing Engine  (Part D of Build Spec v2)
=============================================================
Sizes markets at the TREATABLE-SEGMENT level, not the whole-disease level.

Design:
  - Walk the funnel JSONB gate-by-gate to get SAM population
  - TAM  = pre-access-gate population × net price
  - SAM  = full-funnel population × net price
  - SOM  = SAM × som_penetration_pct
  - Every step carries its source — no unexplained numbers
  - Confidence band width reflects gate source quality
  - Supports overrides (user changes a gate rate or adds/removes a gate)
  - Supports combining multiple segments (sum their SAM populations)
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class FunnelStep:
    gate: str
    label: str
    rate: Optional[float]       # None for the first absolute gate
    running_value: int          # patients after this gate
    source: str
    gate_type: str              # "absolute" | "rate"
    is_access_gate: bool = False  # True → contributes to SAM but not TAM


@dataclass
class MarketSizeResult:
    # Dollar markets
    tam_usd: float
    sam_usd: float
    som_usd: float
    # Population markets
    tam_population: int
    sam_population: int
    som_population: int
    # Full derivation
    funnel_steps: List[FunnelStep]
    # Confidence band (based on gate source quality)
    confidence_low_usd: float
    confidence_high_usd: float
    # Provenance metadata
    weakest_assumptions: List[str]
    segments_used: List[str]
    has_expert_report: bool = False
    net_price_usd: float = 0.0
    som_penetration_pct: float = 0.0
    care_setting: Optional[str] = None
    site_count: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "tam_usd": self.tam_usd,
            "sam_usd": self.sam_usd,
            "som_usd": self.som_usd,
            "tam_population": self.tam_population,
            "sam_population": self.sam_population,
            "som_population": self.som_population,
            "confidence_low_usd": self.confidence_low_usd,
            "confidence_high_usd": self.confidence_high_usd,
            "weakest_assumptions": self.weakest_assumptions,
            "segments_used": self.segments_used,
            "has_expert_report": self.has_expert_report,
            "net_price_usd": self.net_price_usd,
            "som_penetration_pct": self.som_penetration_pct,
            "care_setting": self.care_setting,
            "site_count": self.site_count,
            "funnel_steps": [
                {
                    "gate": s.gate,
                    "label": s.label,
                    "rate": s.rate,
                    "running_value": s.running_value,
                    "source": s.source,
                    "gate_type": s.gate_type,
                    "is_access_gate": s.is_access_gate,
                }
                for s in self.funnel_steps
            ],
        }


def build_effective_funnel(
    base_funnel: List[dict],
    added_gates: Optional[List[dict]] = None,
    removed_gates: Optional[List[str]] = None,
) -> List[dict]:
    """
    Produce the funnel actually walked, after the user's structural edits:
      - drop every gate whose name is in `removed_gates`
      - insert each gate in `added_gates` — after the gate named in its optional
        "after" key, else appended at the end.

    Each added gate is a self-describing funnel gate the PI typed out
    (gate/label/type/rate|value/source). Returned gates are shallow copies;
    the "after" key is stripped from the stored gate.
    """
    removed = set(removed_gates or [])
    funnel = [dict(g) for g in base_funnel if g.get("gate") not in removed]
    for ag in (added_gates or []):
        gate = dict(ag)
        after = gate.pop("after", None)
        if after:
            idx = next((i for i, g in enumerate(funnel) if g.get("gate") == after), None)
            if idx is not None:
                funnel.insert(idx + 1, gate)
                continue
        funnel.append(gate)
    return funnel


def compute_market_size(
    segment: dict,
    net_price_usd: float,
    overrides: Optional[Dict[str, Any]] = None,
    extra_segments: Optional[List[dict]] = None,
    expert_report: Optional[dict] = None,
    added_gates: Optional[List[dict]] = None,
    removed_gates: Optional[List[str]] = None,
) -> MarketSizeResult:
    """
    Walk segment.funnel applying overrides, return TAM/SAM/SOM with full step trace.

    overrides: dict keyed by gate name → {"rate": 0.xx} or {"value": nnn}
               to let the user adjust individual funnel gates without rebuilding.
    added_gates: user-authored funnel gates to insert (fully typed-out assumptions).
    removed_gates: gate names the user chose to drop from the funnel.
    extra_segments: additional segment dicts to combine (sum their SAM populations).
    expert_report: if present, apply its structured_claims as gate overrides.
    """
    overrides = overrides or {}

    # Apply the user's structural edits (added / removed gates) before walking.
    if added_gates or removed_gates:
        segment = dict(segment)
        segment["funnel"] = build_effective_funnel(
            segment.get("funnel", []), added_gates, removed_gates
        )

    # If an expert report is present, its claims take precedence over literature rates.
    if expert_report:
        for claim in (expert_report.get("structured_claims") or []):
            gate = claim.get("gate")
            value = claim.get("value")
            if gate and value is not None:
                overrides.setdefault(gate, {})
                if claim.get("type") == "rate":
                    overrides[gate]["rate"] = float(value)
                else:
                    overrides[gate]["value"] = float(value)

    primary_result = _walk_funnel(segment, net_price_usd, overrides)
    primary_result.has_expert_report = bool(expert_report)

    # Combine with extra segments if requested (sum SAM populations)
    if extra_segments:
        combined_sam_pop = primary_result.sam_population
        combined_som_pop = primary_result.som_population
        combined_segs = list(primary_result.segments_used)
        for extra in extra_segments:
            er = _walk_funnel(extra, net_price_usd, {})
            combined_sam_pop += er.sam_population
            combined_som_pop += er.som_population
            combined_segs.extend(er.segments_used)
        combined_sam_usd = combined_sam_pop * net_price_usd
        combined_som_usd = combined_som_pop * net_price_usd
        # Recompute TAM as the larger of primary TAM or combined SAM
        combined_tam_pop = max(primary_result.tam_population, combined_sam_pop)
        combined_tam_usd = combined_tam_pop * net_price_usd
        _apply_confidence_band(primary_result, combined_segs)
        return MarketSizeResult(
            tam_usd=combined_tam_usd,
            sam_usd=combined_sam_usd,
            som_usd=combined_som_usd,
            tam_population=combined_tam_pop,
            sam_population=combined_sam_pop,
            som_population=combined_som_pop,
            funnel_steps=primary_result.funnel_steps,
            confidence_low_usd=primary_result.confidence_low_usd,
            confidence_high_usd=primary_result.confidence_high_usd,
            weakest_assumptions=primary_result.weakest_assumptions,
            segments_used=combined_segs,
            has_expert_report=bool(expert_report),
            net_price_usd=net_price_usd,
            som_penetration_pct=primary_result.som_penetration_pct,
            care_setting=primary_result.care_setting,
            site_count=primary_result.site_count,
        )

    return primary_result


def _walk_funnel(segment: dict, net_price_usd: float, overrides: dict) -> MarketSizeResult:
    """Walk a single segment's funnel gates and produce a MarketSizeResult."""
    gates = segment.get("funnel", [])
    som_pct = float(segment.get("som_penetration_pct") or 0.25)

    funnel_steps: List[FunnelStep] = []
    running = 0
    tam_population = 0  # population BEFORE the first access gate
    found_access_gate = False
    weakest: List[str] = []

    for gate in gates:
        gate_name = gate.get("gate", "")
        gate_type = gate.get("type", "rate")
        label = gate.get("label", gate_name)
        source = gate.get("source", "unknown source")
        is_access = gate_name == "access" or gate_name.startswith("access_")

        # Apply override if present
        ov = overrides.get(gate_name, {})

        if gate_type == "absolute":
            val = ov.get("value", gate.get("value", 0))
            running = int(val)
        else:
            rate = ov.get("rate", gate.get("rate", 1.0))
            running = int(running * float(rate))

        # TAM boundary: everything before the first access gate
        if not found_access_gate and not is_access:
            tam_population = running
        if is_access:
            found_access_gate = True

        # Flag analyst estimates + user-entered assumptions for the confidence band
        src_l = source.lower()
        if ("analyst estimate" in src_l or "REVIEW" in source
                or "unverified" in src_l or "pi-entered" in src_l
                or "user-entered" in src_l):
            weakest.append(f"{label} [{source}]")

        step = FunnelStep(
            gate=gate_name,
            label=label,
            rate=gate.get("rate") if gate_type == "rate" else None,
            running_value=running,
            source=source,
            gate_type=gate_type,
            is_access_gate=is_access,
        )
        funnel_steps.append(step)

    sam_population = running
    som_population = int(sam_population * som_pct)

    # If no explicit access gate found, TAM = SAM (whole funnel is the treatable segment)
    if tam_population == 0:
        tam_population = sam_population

    tam_usd = float(tam_population) * net_price_usd
    sam_usd = float(sam_population) * net_price_usd
    som_usd = float(som_population) * net_price_usd

    # Confidence band: widen proportionally to number of analyst-estimate gates
    analyst_fraction = len(weakest) / max(len(funnel_steps), 1)
    band_width = max(0.25, analyst_fraction * 0.50)  # ±12.5% to ±25%
    conf_low = som_usd * (1.0 - band_width / 2)
    conf_high = som_usd * (1.0 + band_width)

    result = MarketSizeResult(
        tam_usd=tam_usd,
        sam_usd=sam_usd,
        som_usd=som_usd,
        tam_population=tam_population,
        sam_population=sam_population,
        som_population=som_population,
        funnel_steps=funnel_steps,
        confidence_low_usd=conf_low,
        confidence_high_usd=conf_high,
        weakest_assumptions=weakest,
        segments_used=[segment.get("segment_name", "unnamed segment")],
        has_expert_report=False,
        net_price_usd=net_price_usd,
        som_penetration_pct=som_pct,
        care_setting=segment.get("care_setting"),
        site_count=segment.get("site_count"),
    )
    return result


def _apply_confidence_band(result: MarketSizeResult, all_segments: List[str]) -> None:
    """Widen confidence band for combined multi-segment results."""
    result.segments_used = all_segments
    result.confidence_low_usd *= 0.85
    result.confidence_high_usd *= 1.15


def format_segment_for_prompt(
    segment: dict,
    result: MarketSizeResult,
    alternatives: Optional[List[dict]] = None,
    has_expert_report: bool = False,
) -> str:
    """
    Format the resolved segment + computed funnel as a high-priority context block
    for injection into the Opus synthesis prompt.

    This block explicitly overrides any whole-disease TAM calculation.
    """
    lines = [
        "=== SEGMENTED MARKET SIZING — AUTHORITATIVE (use these numbers, not disease-level TAM) ===",
        f"Segment: {segment.get('segment_name', 'unknown')}",
        f"Pathway: {segment.get('pathway_tag', 'N/A')}",
        f"Care setting: {segment.get('care_setting', 'N/A')}",
        "",
        "CRITICAL INSTRUCTION: This product maps to the TREATABLE SEGMENT below, NOT the whole disease population.",
        "Use the TAM/SAM/SOM values from this funnel derivation. Do NOT use whole-disease prevalence as the market.",
        "",
        "FUNNEL DERIVATION (source-stamped, gate-by-gate):",
    ]

    for step in result.funnel_steps:
        if step.gate_type == "absolute":
            lines.append(
                f"  [{step.gate}] {step.label}: "
                f"{step.running_value:,} patients  ← {step.source}"
            )
        else:
            pct = f"{step.rate * 100:.0f}%" if step.rate is not None else "N/A"
            lines.append(
                f"  [{step.gate}] {step.label}: ×{pct} → {step.running_value:,} patients"
                + (f"  {'ACCESS GATE →' if step.is_access_gate else ''}"
                   f"  ← {step.source}")
            )

    lines += [
        "",
        f"TAM (treatable segment × net price):  {_fmt(result.tam_usd)}"
        f"  ({result.tam_population:,} patients × ${result.net_price_usd:,.0f}/yr)",
        f"SAM (after access/care-setting gates): {_fmt(result.sam_usd)}"
        f"  ({result.sam_population:,} patients)",
        f"SOM ({result.som_penetration_pct * 100:.0f}% penetration at maturity): {_fmt(result.som_usd)}"
        f"  ({result.som_population:,} patients)",
        f"Site count: {result.site_count:,} {result.care_setting or 'sites'}"
        if result.site_count else "",
        "",
    ]

    if result.weakest_assumptions:
        lines.append("WEAKEST ASSUMPTIONS (verify with a domain expert or KOL):")
        for w in result.weakest_assumptions[:3]:
            lines.append(f"  ! {w}")
        lines.append("")

    lines.append(
        f"Confidence range (SOM): {_fmt(result.confidence_low_usd)} — {_fmt(result.confidence_high_usd)}"
    )
    lines.append(
        f"Data quality: {'expert_report — high confidence' if has_expert_report else 'literature/analyst seed — verify key rates'}"
    )

    if alternatives:
        lines.append("")
        lines.append(f"ALTERNATIVE SEGMENTS (user may switch to these):")
        for alt in alternatives[:3]:
            lines.append(f"  • {alt.get('segment_name')} [{alt.get('pathway_tag')}]")

    lines.append("=== END SEGMENT SIZING ===")
    return "\n".join(l for l in lines if l is not None)


def _fmt(usd: float) -> str:
    if usd >= 1e9:
        return f"${usd / 1e9:.1f}B"
    if usd >= 1e6:
        return f"${usd / 1e6:.0f}M"
    return f"${usd:,.0f}"
