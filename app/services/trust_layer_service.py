"""
Trust Layer Service  (Brief Priority 2)
=======================================
Turns a finished PIReport into a *report-level trust scorecard* so the product
can visibly demonstrate that it verifies claims before returning them — the
thing a raw ChatGPT answer cannot do.

Pipeline (runs AFTER the multi-agent validation_graph):

  1. Collect the report's own retrieved-evidence pool (supporting_evidence,
     sources, and every cited source inside disease/market/regulatory sections).
  2. One Haiku call atomizes the report narrative into atomic claims, classifies
     each (factual | numerical | forecast | recommendation | interpretation),
     judges whether the *report's own evidence* supports each checkable claim,
     and surfaces contradictions between claims/evidence.
  3. `compute_trust_scorecard()` aggregates those judgments into deterministic,
     auditable metrics — this is pure Python (no LLM) so it is unit-testable and
     reproducible:

        {
          "citation_support_score":   0.95,
          "unsupported_claim_count":  2,
          "contradiction_count":      1,
          "retrieval_coverage":       0.87,
          "abstention_required":      false,
          "human_review_recommended": false,
          ...
        }

The LLM only *labels* claims; all thresholds and scores are computed in code, so
the verdict is defensible and stable across runs.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
JUDGE_MODEL       = "claude-haiku-4-5-20251001"   # cheap + fast, same as verifiers
TIMEOUT           = 45.0

# Claim types that we hold to an evidence standard. Forecasts/recommendations/
# interpretations are judgement calls and are NOT counted against citation
# support (penalising a recommendation for lacking a citation is wrong).
CHECKABLE_TYPES = {"factual", "numerical"}

# Support label -> numeric weight used for the citation_support_score mean.
SUPPORT_WEIGHTS = {"supported": 1.0, "weak": 0.5, "unsupported": 0.0}

# ── Decision thresholds (tunable; surfaced in the scorecard for transparency) ──
# These are per-report gates, intentionally more lenient than the brief's
# release-gate targets (support >= 0.95, coverage >= 0.85) which apply to the
# benchmark suite, not to whether a single report is safe to show.
ABSTAIN_COVERAGE_FLOOR  = 0.40   # below this, too little is grounded -> abstain
ABSTAIN_SUPPORT_FLOOR   = 0.50   # below this, claims are largely unsupported -> abstain
ABSTAIN_MIN_CHECKABLE   = 3      # too few checkable claims to assess -> abstain
REVIEW_SUPPORT_FLOOR    = 0.85   # below this, recommend a human look
REVIEW_COVERAGE_FLOOR   = 0.70
REVIEW_UNSUPPORTED_MAX  = 2      # >2 unsupported checkable claims -> review


# ── Claude caller ─────────────────────────────────────────────────────────────

async def _call_claude(system: str, user: str, max_tokens: int = 3500,
                       model: str = JUDGE_MODEL) -> str:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key":         settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      model,
                "max_tokens": max_tokens,
                "system":     system,
                "messages":   [{"role": "user", "content": user}],
            },
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"]


def _parse_json(raw: str) -> dict:
    """Tolerant JSON parse — strips ``` fences and leading prose."""
    clean = (raw or "").strip()
    if clean.startswith("```"):
        parts = clean.split("```")
        clean = parts[1] if len(parts) > 1 else clean
        if clean.lower().startswith("json"):
            clean = clean[4:]
    clean = clean.strip()
    # Salvage the outermost JSON object if the model added trailing text.
    start, end = clean.find("{"), clean.rfind("}")
    if start != -1 and end != -1 and end > start:
        clean = clean[start:end + 1]
    return json.loads(clean)


# ── Evidence pool + claim context extraction ──────────────────────────────────

def collect_evidence_pool(report: dict) -> list[dict]:
    """
    The set of 'retrieved facts' a claim can be grounded against — built ONLY
    from sources the report actually carries (not the LLM's training data).
    Each entry: {"id", "source", "url", "detail"}.
    """
    pool: list[dict] = []
    seen: set[tuple] = set()

    def add(source: Optional[str], url: Optional[str], detail: str):
        source = (source or "").strip()
        if not source:
            return
        key = (source.lower(), (detail or "").lower()[:80])
        if key in seen:
            return
        seen.add(key)
        pool.append({
            "id": len(pool),
            "source": source,
            "url": url or "",
            "detail": (detail or "")[:200],
        })

    for ev in report.get("supporting_evidence", []) or []:
        add(ev.get("source"), ev.get("source_url"),
            f"{ev.get('signal_type', '')}: {ev.get('title', '')}")

    di = report.get("disease_intelligence") or {}
    for dp in di.get("data_points", []) or []:
        add(dp.get("source"), dp.get("source_url"),
            f"{dp.get('metric', '')} = {dp.get('value', '')} ({dp.get('year', '')})")

    ms = report.get("market_sizing") or {}
    for step in ms.get("steps", []) or []:
        add(step.get("source"), step.get("source_url"),
            f"{step.get('label', '')} = {step.get('value', '')} {step.get('unit', '')}")

    rp = report.get("regulatory_pathway") or {}
    for d in rp.get("designations", []) or []:
        add(d.get("source"), d.get("source_url"),
            f"{d.get('name', '')}: {d.get('benefit', '')}")

    ma = report.get("market_access") or {}
    for b in ma.get("buyer_segments", []) or []:
        add(b.get("source"), b.get("source_url"),
            f"{b.get('segment_name', '')}: {b.get('price_per_unit', '')}")

    for s in report.get("sources", []) or []:
        add(s.get("name") or s.get("source"), s.get("url") or s.get("source_url"),
            s.get("title", "") or s.get("description", ""))

    for cit in report.get("literature_citations", []) or []:
        add(cit.get("source") or cit.get("journal") or "Literature",
            cit.get("url"), cit.get("title", ""))

    # Expert panel — 3 independently-grounded sub-analyses (approval odds anchored
    # to PTRS tables, pricing to deal comps, precedents named). A major evidence
    # source the judge previously couldn't see, so its claims were wrongly unsupported.
    ep = report.get("expert_panel") or {}
    for p in ep.get("panels", []) or []:
        name = p.get("name", "Expert Panel")
        add(name, None, f"{p.get('headline_metric', '')}: {p.get('headline_value', '')}")
        for k, v in (p.get("fields") or {}).items():
            if v and v != "—":
                add(name, None, f"{k}: {v}")

    # Commercialization decision rationale — each score's sourced drivers.
    cs = report.get("commercialization_scores") or {}
    for dim in (cs.get("score_rationales") or {}).values():
        for drv in dim.get("drivers", []) or []:
            add(drv.get("source", "Decision engine"), None, drv.get("fact", ""))

    # Regulatory pathway prose carries named precedents/timelines.
    rp2 = report.get("regulatory_pathway") or {}
    if rp2.get("recommended_pathway"):
        add("FDA regulatory analysis", None,
            f"{rp2.get('recommended_pathway', '')}: {rp2.get('pathway_rationale', '')[:160]}")

    return pool


def collect_claim_text(report: dict) -> str:
    """Assemble the narrative surfaces of the report that contain checkable claims."""
    parts: list[str] = []

    def section(title: str, text: str):
        text = (text or "").strip()
        if text:
            parts.append(f"## {title}\n{text}")

    section("Executive Summary", report.get("executive_summary", ""))

    di = report.get("disease_intelligence") or {}
    if di:
        dps = "; ".join(
            f"{dp.get('metric','')}: {dp.get('value','')} ({dp.get('year','')})"
            for dp in di.get("data_points", []) or []
        )
        section("Disease Intelligence",
                f"{dps}\nResistance: {di.get('resistance_profile','')}\n"
                f"Pipeline: {di.get('pipeline_status','')}\n"
                f"Unmet need: {di.get('unmet_need_summary','')}")

    ms = report.get("market_sizing") or {}
    if ms:
        steps = "; ".join(
            f"{s.get('label','')}={s.get('value','')} {s.get('unit','')}"
            for s in ms.get("steps", []) or []
        )
        section("Market Sizing",
                f"Formula: {ms.get('formula','')}\nSteps: {steps}\n"
                f"TAM: {ms.get('total_addressable_market_usd','')}; "
                f"SAM: {ms.get('serviceable_market_usd','')}\n"
                f"Methodology: {ms.get('methodology_note','')}")

    rp = report.get("regulatory_pathway") or {}
    if rp:
        designations = "; ".join(
            f"{d.get('name','')} ({d.get('benefit','')})"
            for d in rp.get("designations", []) or []
        )
        section("Regulatory Pathway",
                f"Recommended: {rp.get('recommended_pathway','')}\n"
                f"Rationale: {rp.get('pathway_rationale','')}\n"
                f"Designations: {designations}\n"
                f"Timeline: {rp.get('total_timeline_estimate','')}; "
                f"Cost: {rp.get('total_cost_estimate','')}")

    ma = report.get("market_access") or {}
    if ma:
        section("Market Access",
                f"Channel: {ma.get('primary_channel','')}\n"
                f"Reimbursement: {ma.get('reimbursement_pathway','')}\n"
                f"First step: {ma.get('first_commercial_step','')}")

    steps_next = report.get("recommended_next_steps", []) or []
    if steps_next:
        section("Recommended Next Steps", "\n".join(f"- {s}" for s in steps_next))

    return "\n\n".join(parts)


# ── The claim judge (LLM labels only) ──────────────────────────────────────────

CLAIM_JUDGE_SYSTEM = """You are a citation auditor for a biomedical commercialization intelligence platform. \
You do NOT write or improve the report. Your only job is to break it into atomic claims, classify each, \
and judge whether the report's OWN retrieved evidence supports it.

You will receive:
1. REPORT_TEXT — the narrative to audit.
2. EVIDENCE_POOL — a numbered list of sources the report actually retrieved. This is the ONLY evidence you may \
credit. Do NOT use your own background knowledge to mark a claim 'supported'; if the pool doesn't back it, it is unsupported.

For EACH atomic claim, output:
- "claim": the specific assertion (one fact per claim; split compound sentences).
- "type": one of "factual" | "numerical" | "forecast" | "recommendation" | "interpretation".
    * factual: a checkable statement about the world (e.g., "Drug X is FDA-approved for sepsis").
    * numerical: contains a specific number/quantity/rate/dollar figure.
    * forecast: a prediction about the future (timelines, projected adoption).
    * recommendation: advice/strategy ("pursue SBIR Phase I first").
    * interpretation: subjective synthesis ("this is a strong opportunity").
- "support": one of "supported" | "weak" | "unsupported" | "n/a".
    * Only judge support for "factual" and "numerical" claims. For other types output "n/a".
    * supported: an evidence pool item clearly backs the claim.
    * weak: an evidence pool item is topically related but doesn't directly establish the claim.
    * unsupported: no evidence pool item backs it.
- "evidence_ids": array of EVIDENCE_POOL ids that back it (empty if none).
- "note": <=15 words on why (only for weak/unsupported).

Also return "contradictions": an array of conflicts you find — either between two claims, or between a claim and \
the evidence pool. Each: {"claim_a": "...", "claim_b_or_evidence": "...", "explanation": "<=25 words"}.

Be strict and literal. A confidently-worded number with no matching evidence pool item is "unsupported", not "weak".

Respond with ONLY valid JSON, no markdown:
{"claims": [{"claim": "...", "type": "...", "support": "...", "evidence_ids": [], "note": "..."}], "contradictions": []}"""


async def judge_claims(report: dict, evidence_pool: list[dict]) -> dict:
    """LLM pass: atomize + classify + judge. Returns {'claims': [...], 'contradictions': [...]}."""
    report_text = collect_claim_text(report)
    if not report_text.strip():
        return {"claims": [], "contradictions": [], "_error": "empty report text"}

    pool_text = "\n".join(
        f"[{e['id']}] {e['source']} — {e['detail']}".strip(" —")
        for e in evidence_pool
    ) or "(no retrieved evidence available)"

    user = (
        f"EVIDENCE_POOL ({len(evidence_pool)} sources):\n{pool_text}\n\n"
        f"REPORT_TEXT:\n{report_text}\n\n"
        "Audit the report now. Return only the JSON object."
    )

    raw = await _call_claude(CLAIM_JUDGE_SYSTEM, user, max_tokens=6000)
    try:
        data = _parse_json(raw)
        return {
            "claims": data.get("claims", []) or [],
            "contradictions": data.get("contradictions", []) or [],
        }
    except (ValueError, TypeError):
        # The judge's JSON was truncated/malformed — salvage every complete claim
        # object rather than discarding the whole scorecard.
        return _salvage_claims(raw)


def _salvage_claims(raw: str) -> dict:
    """Bracket-scan the `claims` array and keep each complete {...} object,
    tolerating a truncated tail. Contradictions are dropped on salvage."""
    claims: list[dict] = []
    i = (raw or "").find('"claims"')
    arr = raw.find("[", i) if i != -1 else -1
    if arr != -1:
        depth, start = 0, None
        for j in range(arr + 1, len(raw)):
            ch = raw[j]
            if ch == "{":
                if depth == 0:
                    start = j
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    try:
                        claims.append(json.loads(raw[start:j + 1]))
                    except (ValueError, TypeError):
                        pass
                    start = None
            elif ch == "]" and depth == 0:
                break
    logger.warning("Trust judge JSON malformed — salvaged %d claim(s)", len(claims))
    return {"claims": claims, "contradictions": []}


# ── Deterministic scorecard (pure; unit-tested) ────────────────────────────────

def compute_trust_scorecard(
    claims: list[dict],
    contradictions: list[dict],
    evidence_pool_size: int,
    validation: Optional[dict] = None,
) -> dict:
    """
    Aggregate per-claim judgments into the report-level trust metrics.
    Pure function — no I/O — so it is deterministic and unit-testable.
    """
    validation = validation or {}

    checkable = [c for c in claims if c.get("type") in CHECKABLE_TYPES]
    n_checkable = len(checkable)

    def support_of(c: dict) -> str:
        s = (c.get("support") or "").lower()
        return s if s in SUPPORT_WEIGHTS else "unsupported"

    if n_checkable:
        weight_sum = sum(SUPPORT_WEIGHTS[support_of(c)] for c in checkable)
        citation_support_score = round(weight_sum / n_checkable, 3)
        grounded = sum(
            1 for c in checkable
            if support_of(c) in ("supported", "weak") and c.get("evidence_ids")
        )
        retrieval_coverage = round(grounded / n_checkable, 3)
    else:
        citation_support_score = 0.0
        retrieval_coverage = 0.0

    unsupported = [c for c in checkable if support_of(c) == "unsupported"]
    unsupported_claim_count = len(unsupported)

    # Contradictions: the judge's findings, plus any hard ERROR flags raised by
    # the upstream validation graph (those are real, independently-found issues).
    validation_errors = len(validation.get("errors", []) or [])
    contradiction_count = len(contradictions) + validation_errors

    # ── Abstention: the report cannot stand on its own evidence. ──
    abstention_reasons: list[str] = []
    if n_checkable < ABSTAIN_MIN_CHECKABLE:
        abstention_reasons.append(
            f"only {n_checkable} checkable claims (< {ABSTAIN_MIN_CHECKABLE})")
    if retrieval_coverage < ABSTAIN_COVERAGE_FLOOR:
        abstention_reasons.append(
            f"retrieval coverage {retrieval_coverage:.0%} < {ABSTAIN_COVERAGE_FLOOR:.0%}")
    if citation_support_score < ABSTAIN_SUPPORT_FLOOR:
        abstention_reasons.append(
            f"citation support {citation_support_score:.0%} < {ABSTAIN_SUPPORT_FLOOR:.0%}")
    if evidence_pool_size == 0:
        abstention_reasons.append("no retrieved evidence available")
    abstention_required = bool(abstention_reasons)

    # ── Human review: usable but should be checked. ──
    review_reasons: list[str] = []
    if citation_support_score < REVIEW_SUPPORT_FLOOR:
        review_reasons.append(
            f"citation support {citation_support_score:.0%} < {REVIEW_SUPPORT_FLOOR:.0%}")
    if retrieval_coverage < REVIEW_COVERAGE_FLOOR:
        review_reasons.append(
            f"retrieval coverage {retrieval_coverage:.0%} < {REVIEW_COVERAGE_FLOOR:.0%}")
    if unsupported_claim_count > REVIEW_UNSUPPORTED_MAX:
        review_reasons.append(
            f"{unsupported_claim_count} unsupported claims (> {REVIEW_UNSUPPORTED_MAX})")
    if contradiction_count > 0:
        review_reasons.append(f"{contradiction_count} contradiction(s)")
    if validation_errors > 0:
        review_reasons.append(f"{validation_errors} validation error(s)")
    human_review_recommended = abstention_required or bool(review_reasons)

    # Trust grade for at-a-glance UI.
    if abstention_required:
        grade = "INSUFFICIENT_EVIDENCE"
    elif citation_support_score >= 0.95 and contradiction_count == 0:
        grade = "HIGH"
    elif citation_support_score >= REVIEW_SUPPORT_FLOOR and contradiction_count == 0:
        grade = "MODERATE"
    else:
        grade = "LOW"

    type_breakdown: dict[str, int] = {}
    for c in claims:
        t = c.get("type", "unknown")
        type_breakdown[t] = type_breakdown.get(t, 0) + 1

    return {
        "citation_support_score":   citation_support_score,
        "unsupported_claim_count":  unsupported_claim_count,
        "contradiction_count":      contradiction_count,
        "retrieval_coverage":       retrieval_coverage,
        "abstention_required":      abstention_required,
        "human_review_recommended": human_review_recommended,
        "trust_grade":              grade,
        "total_claims":             len(claims),
        "checkable_claims":         n_checkable,
        "evidence_pool_size":       evidence_pool_size,
        "claim_type_breakdown":     type_breakdown,
        "abstention_reasons":       abstention_reasons,
        "review_reasons":           review_reasons,
        "unsupported_claims":       [c.get("claim", "") for c in unsupported][:10],
        "contradictions":           contradictions[:10],
        "thresholds": {
            "abstain_coverage_floor": ABSTAIN_COVERAGE_FLOOR,
            "abstain_support_floor":  ABSTAIN_SUPPORT_FLOOR,
            "review_support_floor":   REVIEW_SUPPORT_FLOOR,
            "review_coverage_floor":  REVIEW_COVERAGE_FLOOR,
        },
    }


def _trust_summary(card: dict) -> str:
    if card["abstention_required"]:
        return ("Insufficient evidence to stand behind this report: "
                + "; ".join(card["abstention_reasons"])
                + ". Human review required before relying on it.")
    pct = card["citation_support_score"]
    cov = card["retrieval_coverage"]
    base = (f"{pct:.0%} of checkable claims are source-supported "
            f"({card['checkable_claims']} claims, {cov:.0%} grounded in retrieved evidence).")
    if card["human_review_recommended"]:
        return base + " Flagged for human review: " + "; ".join(card["review_reasons"]) + "."
    return base + " No contradictions or unsupported major claims detected."


# ── Public entry point ─────────────────────────────────────────────────────────

async def score_report_trust(report: dict) -> dict:
    """
    Compute the Trust Layer scorecard for a finished report dict.

    Returns the trust dict (also safe to attach to report['trust']). Always
    returns a dict; degrades gracefully to an explicit 'unavailable' card if the
    judge call fails, rather than blocking report delivery.
    """
    try:
        evidence_pool = collect_evidence_pool(report)
        judged = await judge_claims(report, evidence_pool)
        card = compute_trust_scorecard(
            claims=judged.get("claims", []),
            contradictions=judged.get("contradictions", []),
            evidence_pool_size=len(evidence_pool),
            validation=report.get("validation"),
        )
        card["summary"] = _trust_summary(card)
        card["judge_model"] = JUDGE_MODEL
        card["claims"] = judged.get("claims", [])   # auditable per-claim trail
        card["scored_at"] = datetime.utcnow().isoformat()
        logger.info(
            "Trust layer: grade=%s support=%.2f coverage=%.2f unsupported=%d contradictions=%d abstain=%s",
            card["trust_grade"], card["citation_support_score"], card["retrieval_coverage"],
            card["unsupported_claim_count"], card["contradiction_count"], card["abstention_required"],
        )
        return card
    except Exception as e:
        logger.error("Trust layer scoring failed: %s", e)
        return {
            "available": False,
            "error": str(e),
            "summary": "Trust scoring unavailable for this report.",
            "abstention_required": False,
            "human_review_recommended": False,
            "scored_at": datetime.utcnow().isoformat(),
        }
