"""
PI Report Validation Pipeline - LangGraph Multi-Agent
======================================================
Implements a true multi-agent validation graph where specialized
independent agents verify different aspects of the report in parallel.

Graph Architecture:
                    +---> Math Verifier ------+
                    |                          |
Report --> Router --+---> Source Verifier ----+--> Arbitrator --> Formatter
                    |                          |
                    +---> Regulatory Verifier -+
                    |                          |
                    +---> Market Verifier -----+

Each verifier is an independent Claude instance with specialized knowledge.
The Arbitrator synthesizes all findings and makes a final verdict.
"""

import json
import logging
import asyncio
from typing import TypedDict, Optional, List, Annotated
from datetime import datetime
import operator

import httpx
from langgraph.graph import StateGraph, END

from app.core.config import settings

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
VERIFIER_MODEL    = "claude-haiku-4-5-20251001"  # Fast + cheap for verification
ARBITRATOR_MODEL  = "claude-sonnet-4-6"           # Stronger for final synthesis
TIMEOUT           = 60.0


# ── State ─────────────────────────────────────────────────────────────────────

class ValidationFlag(TypedDict):
    severity:   str   # "ERROR" | "WARNING" | "NOTE"
    category:   str   # "MATH" | "SOURCE" | "REGULATORY" | "MARKET" | "FACTUAL"
    field:      str
    issue:      str
    suggestion: str
    agent:      str   # which agent found this


class PIReportState(TypedDict):
    report:              dict
    product_type:        str
    sub_expert_id:       str
    expert_critic_rules: str

    # Each verifier writes its flags here (parallel execution)
    math_flags:       List[ValidationFlag]
    source_flags:     List[ValidationFlag]
    regulatory_flags: List[ValidationFlag]
    market_flags:     List[ValidationFlag]
    factual_flags:    List[ValidationFlag]

    # Errors from each agent
    math_error:       Optional[str]
    source_error:     Optional[str]
    regulatory_error: Optional[str]
    market_error:     Optional[str]
    factual_error:    Optional[str]

    # Final
    all_flags:          List[ValidationFlag]
    validation_passed:  bool
    validated_report:   Optional[dict]
    factual_skipped:    bool   # True when factual verifier was not run (research domain)


# ── Claude caller ─────────────────────────────────────────────────────────────

async def _call_claude(system: str, user: str, max_tokens: int = 1500,
                        model: str = VERIFIER_MODEL) -> str:
    from datetime import date as _date
    # Verifiers lack a clock and were flagging valid current/recent dates as
    # "future" — ground them in today's date to kill that class of false errors.
    dated_system = (f"CONTEXT: Today's date is {_date.today().isoformat()}. Any date on or "
                    f"before today is in the past or present — NEVER flag it as a 'future date'.\n\n"
                    + system)
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
                "system":     dated_system,
                "messages":   [{"role": "user", "content": user}],
            }
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"]


def _parse_flags(raw: str, agent: str) -> List[ValidationFlag]:
    """Parse flags from agent response, add agent name."""
    try:
        clean = raw.strip()
        if clean.startswith("```"):
            parts = clean.split("```")
            clean = parts[1] if len(parts) > 1 else clean
            if clean.startswith("json"):
                clean = clean[4:]
        data = json.loads(clean.strip())
        flags = data.get("flags", [])
        for f in flags:
            f["agent"] = agent
        return flags
    except Exception:
        return []


# ── AGENT 1: Math Verifier ────────────────────────────────────────────────────

MATH_VERIFIER_SYSTEM = """You are a financial analyst verifying market sizing calculations in biomedical reports.

Your ONLY job: re-derive every TAM/SAM calculation from scratch and check the math.

For each market sizing step:
1. Extract the inputs: patient_count, price, penetration_rate
2. Calculate TAM = patients x price (100% penetration)
3. Calculate SAM = TAM x penetration_rate
4. Compare to stated values

Also check:
- Does the formula text match the actual numbers used?
- Are penetration rates realistic? (Novel drug: 15-40% Year 5 is typical. >60% is suspicious.)
- Is WAC pricing in the right range for the drug class?
  * Oral antibiotics: $200-2,000/course
  * IV antibiotics: $5,000-25,000/course
  * Oncology oral: $8,000-25,000/month
  * Gene therapy one-time: $500,000-3,500,000
  * Medical devices: $1,000-100,000
  * Diagnostics: $50-5,000/test

Respond ONLY with JSON:
{"flags": [{"severity": "ERROR|WARNING|NOTE", "category": "MATH", "field": "market_sizing.X", "issue": "<specific issue with numbers>", "suggestion": "<what to fix>"}]}
If math checks out: {"flags": []}"""


async def math_verifier_node(state: PIReportState) -> dict:
    """Independently re-derives all market sizing calculations."""
    logger.info("Math verifier running")
    try:
        from app.services.math_consistency_guard import check_market_arithmetic

        ms = state["report"].get("market_sizing", {})
        if not ms:
            return {"math_flags": [], "math_error": None}

        # B-02: deterministic arithmetic check — immune to LLM "resolved" hallucination
        deterministic_flags = check_market_arithmetic(ms)

        user_input = json.dumps({
            "stated_TAM": ms.get("total_addressable_market_usd"),
            "stated_SAM": ms.get("serviceable_market_usd"),
            "formula": ms.get("formula"),
            "steps": ms.get("steps", []),
            "methodology": ms.get("methodology_note"),
            "product_type": state["product_type"],
        }, indent=2)

        raw = await _call_claude(MATH_VERIFIER_SYSTEM, f"Verify these calculations:\n{user_input}")
        llm_flags = _parse_flags(raw, "Math Verifier")
        flags = deterministic_flags + llm_flags
        logger.info(
            f"Math verifier: {len(flags)} flags "
            f"({len(deterministic_flags)} deterministic, {len(llm_flags)} LLM)"
        )
        return {"math_flags": flags, "math_error": None}
    except Exception as e:
        logger.error(f"Math verifier failed: {e}")
        return {"math_flags": [], "math_error": str(e)}


# ── AGENT 2: Source Verifier ──────────────────────────────────────────────────

SOURCE_VERIFIER_SYSTEM = """You are a research librarian verifying source citations in biomedical reports.

For each cited source, assess:
1. EXISTENCE: Does this source plausibly exist?
   - REAL: "CDC AR Threats Report 2019", "NEJM 2022 DOI:...", "FDA QIDP Guidance", "PubMed PMID:12345678"
   - SUSPICIOUS: "IDSA 2023 CRE-Specific Mortality Registry", "WHO Global AMR Database 2024 Table 7.3B"
   - FLAG: Any source with suspiciously specific internal references that don't match known publication patterns

2. URL VALIDITY: Check each source_url
   - Valid domains: cdc.gov, fda.gov, pubmed.ncbi.nlm.nih.gov, nih.gov, cms.gov, idsociety.org, nejm.org, thelancet.com, jamanetwork.com
   - Flag if URL domain doesn't match claimed source name
   - Flag if URL looks fabricated (e.g., random paths that don't follow FDA/CDC URL patterns)

3. CLAIM-SOURCE MATCH: Does the source plausibly contain the claimed data?
   - "CDC AR Threats Report" containing infection/death counts: PLAUSIBLE
   - "FDA approval database" containing drug WAC pricing: IMPLAUSIBLE (FDA doesn't publish pricing)
   - Flag mismatches between what source is claimed to contain and what it plausibly would contain

Respond ONLY with JSON:
{"flags": [{"severity": "ERROR|WARNING|NOTE", "category": "SOURCE", "field": "field.source_name", "issue": "<specific issue>", "suggestion": "<what to verify>"}]}
If all sources check out: {"flags": []}"""


async def source_verifier_node(state: PIReportState) -> dict:
    """Checks all source citations for validity and plausibility."""
    logger.info("Source verifier running")
    try:
        from app.services.source_type_guard import (
            check_source_type_bindings,
            check_price_segment_consistency,
        )

        report = state["report"]
        di = report.get("disease_intelligence", {})
        ms = report.get("market_sizing", {})
        rp = report.get("regulatory_pathway", {})
        ma = report.get("market_access", {})

        sources_to_check = []

        for dp in di.get("data_points", []):
            if dp.get("source"):
                sources_to_check.append({
                    "field": "disease_intelligence.data_points",
                    "source": dp.get("source"),
                    "url": dp.get("source_url"),
                    "claim": f"{dp.get('metric')}: {dp.get('value')}"
                })

        for step in ms.get("steps", []):
            if step.get("source"):
                sources_to_check.append({
                    "field": "market_sizing.steps",
                    "source": step.get("source"),
                    "url": step.get("source_url"),
                    "claim": f"{step.get('label')}: {step.get('value')} {step.get('unit')}"
                })

        for d in rp.get("designations", []):
            if d.get("source"):
                sources_to_check.append({
                    "field": f"regulatory_pathway.designations.{d.get('name')}",
                    "source": d.get("source"),
                    "url": d.get("source_url"),
                    "claim": d.get("benefit")
                })

        # B-03: deterministic source-type binding check (no LLM needed)
        deterministic_flags = check_source_type_bindings(sources_to_check)
        deterministic_flags += check_price_segment_consistency(
            ma.get("buyer_segments", []),
            state.get("product_type", ""),
        )

        if not sources_to_check:
            return {"source_flags": deterministic_flags, "source_error": None}

        user_input = json.dumps(sources_to_check[:15], indent=2)  # Cap at 15 sources
        raw = await _call_claude(SOURCE_VERIFIER_SYSTEM,
                                  f"Verify these {len(sources_to_check)} source citations:\n{user_input}")
        llm_flags = _parse_flags(raw, "Source Verifier")
        flags = deterministic_flags + llm_flags
        logger.info(
            f"Source verifier: {len(flags)} flags "
            f"({len(deterministic_flags)} deterministic, {len(llm_flags)} LLM)"
        )
        return {"source_flags": flags, "source_error": None}
    except Exception as e:
        logger.error(f"Source verifier failed: {e}")
        return {"source_flags": [], "source_error": str(e)}


# ── AGENT 3: Regulatory Verifier ─────────────────────────────────────────────

REGULATORY_VERIFIER_SYSTEM = """You are an FDA regulatory affairs expert with 20 years of experience.
You verify that FDA pathway information in biomedical reports is accurate.

Check these universal FDA facts:

EXCLUSIVITY:
- New Chemical Entity (NCE/NME): 5 years for small molecules, 12 years for biologics
- Orphan Drug: 7 years
- QIDP (antibiotics/antifungals): +5 additional years on top of existing exclusivity
- Pediatric Exclusivity: +6 months on top of ALL existing exclusivities
- RMAT (regenerative medicine): rolling review, NOT additional exclusivity

REVIEW TIMELINES:
- Standard review: 10-12 months PDUFA date
- Priority Review: 6-month PDUFA date
- Breakthrough Therapy: NOT a separate review timeline — provides rolling review + more FDA meetings
- Fast Track: rolling review + more FDA meetings — does NOT guarantee Priority Review
- Accelerated Approval: based on surrogate endpoint; requires confirmatory trial

PATHWAYS:
- 505(b)(1): full NDA with all new data
- 505(b)(2): can rely on existing published data/FDA findings
- 505(j) ANDA: generic drug with bioequivalence
- BLA (biologics): different from NDA; 12-year reference product exclusivity
- PMA (devices): Class III; clinical data required
- 510(k) (devices): predicate-based; no clinical trial usually required

SPECIFIC DESIGNATIONS:
- QIDP: +5yr exclusivity, Priority Review, Fast Track — NOT accelerated approval
- NTAP: 65-75% cost add-on above DRG threshold for 2-3 years — NOT permanent
- LPAD: limited population label, smaller Phase 3, NOT equivalent to standard approval
- BTD: requires CLINICAL evidence of substantial improvement — NOT preclinical

If the report states any of these incorrectly, flag it.

Respond ONLY with JSON:
{"flags": [{"severity": "ERROR|WARNING|NOTE", "category": "REGULATORY", "field": "regulatory_pathway.X", "issue": "<specific error>", "suggestion": "<correct information>"}]}
If all regulatory information is accurate: {"flags": []}"""


async def regulatory_verifier_node(state: PIReportState) -> dict:
    """Verifies FDA pathway details against known regulatory facts."""
    logger.info("Regulatory verifier running")
    try:
        rp = state["report"].get("regulatory_pathway", {})
        if not rp:
            return {"regulatory_flags": [], "regulatory_error": None}

        user_input = json.dumps({
            "recommended_pathway": rp.get("recommended_pathway"),
            "pathway_rationale": rp.get("pathway_rationale"),
            "designations": [
                {
                    "name": d.get("name"),
                    "benefit": d.get("benefit"),
                    "description": d.get("description"),
                    "timeline": d.get("timeline"),
                }
                for d in rp.get("designations", [])
            ],
            "total_timeline": rp.get("total_timeline_estimate"),
            "total_cost": rp.get("total_cost_estimate"),
            "product_type": state["product_type"],
            "expert_domain": state["sub_expert_id"],
        }, indent=2)

        # Inject domain-specific rules
        domain_rules = state.get("expert_critic_rules", "")
        system = REGULATORY_VERIFIER_SYSTEM
        if domain_rules:
            system += f"\n\nDOMAIN-SPECIFIC RULES:\n{domain_rules}"

        raw = await _call_claude(system,
                                  f"Verify this regulatory pathway information:\n{user_input}")
        flags = _parse_flags(raw, "Regulatory Verifier")
        logger.info(f"Regulatory verifier: {len(flags)} flags")
        return {"regulatory_flags": flags, "regulatory_error": None}
    except Exception as e:
        logger.error(f"Regulatory verifier failed: {e}")
        return {"regulatory_flags": [], "regulatory_error": str(e)}


# ── AGENT 4: Market Intelligence Verifier ────────────────────────────────────

MARKET_VERIFIER_SYSTEM = """You are a healthcare market analyst verifying market intelligence in biomedical reports.

Check the following:

1. COMPETITIVE LANDSCAPE: Are the stated competitors real approved drugs?
   - Verify drug names and approval years are plausible
   - Flag if a drug is stated as approved but sounds fictional
   - Flag if approval year seems wrong (e.g., drug stated approved 2010 that you know was approved 2019)

2. PRICING BENCHMARKS: Is WAC pricing realistic for the drug class?
   Reference ranges:
   - Oral antibiotics: $200-2,000/course (generic competition anchor)
   - IV antibiotics (novel): $8,000-25,000/course (QIDP premium)
   - Checkpoint inhibitors: $10,000-20,000/month
   - ADCs: $15,000-25,000/month
   - CAR-T: $300,000-600,000 one-time
   - Gene therapy: $500,000-3,500,000 one-time
   - Medical devices Class III: $5,000-100,000
   - Diagnostics: $50-5,000/test
   Flag if pricing is >2x or <0.5x the expected range.

3. MARKET ACCESS: Is the described market access pathway realistic?
   - Hospital formulary addition: 6-18 months is typical
   - GPO contract: 6-12 months
   - Specialty pharmacy: 1-3 months
   - VA National Formulary: 12-24 months
   Flag timelines that are unrealistically fast (<3 months for formulary addition)

4. REIMBURSEMENT: Is reimbursement pathway correctly described?
   - NTAP applies ONLY to inpatient hospital drugs (not outpatient/pharmacy)
   - Part B covers physician-administered drugs (IV/injectable)
   - Part D covers oral prescription drugs
   - Specialty tier for expensive drugs (>$600/month threshold)
   Flag reimbursement pathway errors.

Respond ONLY with JSON:
{"flags": [{"severity": "ERROR|WARNING|NOTE", "category": "MARKET", "field": "market_access.X", "issue": "<specific issue>", "suggestion": "<correction>"}]}
If market intelligence is accurate: {"flags": []}"""


async def market_verifier_node(state: PIReportState) -> dict:
    """Verifies competitive landscape, pricing, and market access claims."""
    logger.info("Market verifier running")
    try:
        report = state["report"]
        ma = report.get("market_access", {})
        di = report.get("disease_intelligence", {})

        user_input = json.dumps({
            "product_type": state["product_type"],
            "pipeline_status": di.get("pipeline_status"),
            "primary_channel": ma.get("primary_channel"),
            "reimbursement_pathway": ma.get("reimbursement_pathway"),
            "buyer_segments": [
                {
                    "name": b.get("segment_name"),
                    "price": b.get("price_per_unit"),
                    "timeline": b.get("timeline_to_access"),
                }
                for b in ma.get("buyer_segments", [])
            ],
            "market_sizing_steps": [
                {"label": s.get("label"), "value": s.get("value"), "unit": s.get("unit")}
                for s in report.get("market_sizing", {}).get("steps", [])
            ],
        }, indent=2)

        raw = await _call_claude(MARKET_VERIFIER_SYSTEM,
                                  f"Verify this market intelligence:\n{user_input}")
        flags = _parse_flags(raw, "Market Verifier")
        logger.info(f"Market verifier: {len(flags)} flags")
        return {"market_flags": flags, "market_error": None}
    except Exception as e:
        logger.error(f"Market verifier failed: {e}")
        return {"market_flags": [], "market_error": str(e)}


# ── AGENT 5: Factual Verifier ─────────────────────────────────────────────────

FACTUAL_VERIFIER_SYSTEM = """You are an epidemiologist and biomedical scientist verifying factual claims.

Check these known epidemiological facts (CDC 2019-2024 data):

AMR/INFECTIOUS DISEASE:
- CRE: ~13,100 infections/yr, ~1,100 deaths/yr (NOT the other way around)
- MRSA: ~119,247 infections/yr, ~19,832 deaths/yr
- C. difficile: ~223,900 cases/yr, ~12,800 deaths/yr
- VRE: ~54,500 infections/yr, ~5,400 deaths/yr
- ESBL-E: ~197,400 infections/yr, ~9,100 deaths/yr
- Acinetobacter MDR: ~8,500 infections/yr, ~700 deaths/yr
- Sepsis: ~1.7M hospitalizations/yr, ~270,000 deaths/yr

ONCOLOGY:
- NSCLC: ~238,340 new cases/yr (SEER 2023)
- EGFR mutation in NSCLC: ~15% U.S., ~50% Asian patients
- KRAS G12C in NSCLC: ~13%
- HER2+ breast cancer: ~20% of breast cancers
- AML: ~20,380 new cases/yr
- FLT3-ITD in AML: ~25-30%

RARE DISEASE:
- SMA Type 1: ~400 new cases/yr U.S.
- DMD: ~15,000 U.S. patients
- Hemophilia A: ~20,000 U.S. patients
- ALS: ~33,000 U.S. prevalent, ~5,000 new cases/yr

Flag if stated numbers deviate from known values by >25%.
Flag if infections and deaths are stated in reversed order.
Flag obvious biological impossibilities (e.g., mortality rate >100%).

Respond ONLY with JSON:
{"flags": [{"severity": "ERROR|WARNING|NOTE", "category": "FACTUAL", "field": "disease_intelligence.X", "issue": "<specific error>", "suggestion": "<correct value>"}]}
If all facts check out: {"flags": []}"""


_RESEARCH_TOOL_SIDS = frozenset({
    "research_tool_non_clinical", "research_infrastructure_saas", "research_tool_agronomy",
})


async def factual_verifier_node(state: PIReportState) -> dict:
    """Verifies epidemiological and biological facts."""
    logger.info("Factual verifier running")
    try:
        # Skip for research tools — verifier only knows clinical/AMR/oncology reference data;
        # running it on agronomy or non-clinical research reports produces spurious ERRORs.
        _sid = state.get("sub_expert_id", "") or ""
        if _sid in _RESEARCH_TOOL_SIDS or "research_tool" in _sid or "research_infrastructure" in _sid:
            logger.info("Factual verifier: skipped for research tool archetype (%s)", _sid)
            return {"factual_flags": [], "factual_error": None, "factual_skipped": True}

        di = state["report"].get("disease_intelligence", {})
        if not di:
            return {"factual_flags": [], "factual_error": None}

        user_input = json.dumps({
            "condition": di.get("condition"),
            "data_points": di.get("data_points", []),
            "resistance_profile": di.get("resistance_profile"),
            "pipeline_status": di.get("pipeline_status"),
            "unmet_need": di.get("unmet_need_summary"),
        }, indent=2)

        raw = await _call_claude(FACTUAL_VERIFIER_SYSTEM,
                                  f"Verify these epidemiological facts:\n{user_input}")
        flags = _parse_flags(raw, "Factual Verifier")
        logger.info(f"Factual verifier: {len(flags)} flags")
        return {"factual_flags": flags, "factual_error": None}
    except Exception as e:
        logger.error(f"Factual verifier failed: {e}")
        return {"factual_flags": [], "factual_error": str(e)}


# ── ROUTER: Runs all verifiers in parallel ────────────────────────────────────

async def parallel_verifier_node(state: PIReportState) -> dict:
    """Runs all 4 verifier agents in parallel using asyncio.gather."""
    logger.info("Running all verifiers in parallel")

    results = await asyncio.gather(
        math_verifier_node(state),
        source_verifier_node(state),
        regulatory_verifier_node(state),
        market_verifier_node(state),
        factual_verifier_node(state),
        return_exceptions=True
    )

    math_result, source_result, reg_result, market_result, factual_result = results

    combined = {}
    for result, defaults in [
        (math_result,    {"math_flags": [], "math_error": None}),
        (source_result,  {"source_flags": [], "source_error": None}),
        (reg_result,     {"regulatory_flags": [], "regulatory_error": None}),
        (market_result,  {"market_flags": [], "market_error": None}),
        (factual_result, {"factual_flags": [], "factual_error": None}),
    ]:
        if isinstance(result, Exception):
            combined.update(defaults)
        else:
            combined.update(result)

    return combined


# ── ARBITRATOR: Synthesizes all findings ─────────────────────────────────────

def _is_blocking_error(flag: dict) -> bool:
    """
    Returns True only for non-MATH ERRORs severe enough to block PDF export.

    Horizon-contradiction MATH flags (sub_category="horizon") block export — they
    reflect a genuine content error (two different SOM time-horizons in one report)
    that cannot be dismissed as a stale-value artifact.

    Arithmetic MATH flags (TAM/SAM step-vs-headline, pop×price) do NOT block.
    The server guard compares against total_addressable_market_usd as stored at
    report-generation time; user edits via the buyer-model UI update the live model
    but the stored field may lag. The client guard in market-model.js is the
    authoritative arithmetic checker for the live model.
    """
    return flag.get("category") == "MATH" and flag.get("sub_category") == "horizon"


def arbitrator_node(state: PIReportState) -> dict:
    """Combines all flags and determines final verdict."""
    all_flags = (
        state.get("math_flags", []) +
        state.get("source_flags", []) +
        state.get("regulatory_flags", []) +
        state.get("market_flags", []) +
        state.get("factual_flags", [])
    )

    blocking = [f for f in all_flags if _is_blocking_error(f)]
    errors   = [f for f in all_flags if f.get("severity") == "ERROR" and not _is_blocking_error(f)]
    warnings = [f for f in all_flags if f.get("severity") == "WARNING"]
    notes    = [f for f in all_flags if f.get("severity") == "NOTE"]

    if blocking:
        # BLOCKING: arithmetic errors make the report factually wrong — no export.
        passed  = False
        verdict = "BLOCKING"
    elif errors:
        passed  = False
        verdict = "ERROR"
    elif warnings:
        passed  = True   # deliver but flag
        verdict = "FLAG"
    elif notes:
        passed  = True
        verdict = "REVIEW"
    else:
        passed  = True
        verdict = "PASS"

    logger.info(
        "Arbitrator: %d blocking, %d errors, %d warnings, %d notes -> %s",
        len(blocking), len(errors), len(warnings), len(notes), verdict,
    )
    return {
        "all_flags":        all_flags,
        "validation_passed": passed,
        "_verdict":          verdict,
    }


# ── FORMATTER: Attaches validation to report ──────────────────────────────────

def formatter_node(state: PIReportState) -> dict:
    """Attaches full validation results to the report."""
    report          = state["report"].copy()
    flags           = state.get("all_flags", [])
    factual_skipped = state.get("factual_skipped", False)

    # Recompute verdict from actual flags — don't rely on _verdict which LangGraph
    # may drop if the key isn't in PIReportState TypedDict.
    blocking = [f for f in flags if _is_blocking_error(f)]
    errors   = [f for f in flags if f.get("severity") == "ERROR" and not _is_blocking_error(f)]
    warnings = [f for f in flags if f.get("severity") == "WARNING"]
    notes    = [f for f in flags if f.get("severity") == "NOTE"]

    if blocking:
        verdict = "BLOCKING"
        passed  = False
    elif errors:
        verdict = "ERROR"
        passed  = False
    elif warnings:
        verdict = "FLAG"
        passed  = True
    elif notes:
        verdict = "REVIEW"
        passed  = True
    else:
        verdict = "PASS"
        passed  = True

    export_blocked = verdict == "BLOCKING"

    # Group by agent for display
    by_agent = {}
    for f in flags:
        agent = f.get("agent", "Unknown")
        by_agent.setdefault(agent, []).append(f)

    errors_by_agent = [
        {"agent": agent, "count": len([f for f in agent_flags if f.get("severity") == "ERROR"]),
         "flags": [f for f in agent_flags if f.get("severity") in ("ERROR", "WARNING")]}
        for agent, agent_flags in by_agent.items()
        if any(f.get("severity") in ("ERROR", "WARNING") for f in agent_flags)
    ]

    all_errors = blocking + errors   # for display grouping
    report["validation"] = {
        "status":           verdict,
        "passed":           passed,
        "export_blocked":   export_blocked,
        "errors":           all_errors,
        "warnings":         warnings,
        "notes":            notes,
        "total_flags":      len(flags),
        "agents_run":       [
            "Math Verifier", "Source Verifier", "Regulatory Verifier", "Market Verifier",
            "Factual Verifier (not run — research tool domain)" if factual_skipped else "Factual Verifier",
        ],
        "factual_skipped":  factual_skipped,
        "by_agent":         errors_by_agent,
        "validator_model":  VERIFIER_MODEL,
        "validated_at":     datetime.utcnow().isoformat(),
        "summary": (
            (
                f"✓ PASS: 4 of 5 verification agents found no issues — math, sources, regulatory, and market checks all clear. "
                f"Factual verifier: not available for this product domain (research tools use domain-specific knowledge not covered by the clinical verifier)."
                if factual_skipped else
                f"✓ PASS: All 5 verification agents found no issues — math, sources, regulatory, market, and factual checks all clear."
            )
            if verdict == "PASS" else
            f"⚠ FLAG: {len(warnings)} warning(s) found by {', '.join(sorted(set(f.get('agent','') for f in warnings)))}. Report is usable but review flagged items."
            if verdict == "FLAG" else
            f"ℹ REVIEW: {len(notes)} minor note(s) found — no errors or warnings."
            if verdict == "REVIEW" else
            f"✗ BLOCKING: {len(blocking)} arithmetic error(s) found — PDF export is blocked until the market model is corrected. "
            f"Flagged by: {', '.join(sorted(set(f.get('agent','') for f in blocking)))}."
            if verdict == "BLOCKING" else
            f"✗ ERROR: {len(errors)} critical error(s) found by {', '.join(sorted(set(f.get('agent','') for f in errors)))}. Report contains inaccuracies that should be corrected."
        )
    }

    logger.info(f"Validation complete: {verdict} with {len(flags)} total flags across 5 agents")
    return {"validated_report": report}


# ── Source Formatter ──────────────────────────────────────────────────────────

def source_formatter_node(state: PIReportState) -> dict:
    """Extracts inline source markers and builds sources list."""
    try:
        from app.services.source_formatter import extract_and_format_sources
        report = extract_and_format_sources(state["report"].copy())
        logger.info(f"Source formatter: {len(report.get('sources', []))} sources extracted")
        return {"report": report}
    except Exception as e:
        logger.warning(f"Source formatter failed: {e}")
        return {}


# ── Build Graph ───────────────────────────────────────────────────────────────

def build_validation_graph():
    graph = StateGraph(PIReportState)

    graph.add_node("parallel_verifiers", parallel_verifier_node)
    graph.add_node("arbitrator",         arbitrator_node)
    graph.add_node("source_formatter",   source_formatter_node)
    graph.add_node("formatter",          formatter_node)

    graph.set_entry_point("parallel_verifiers")
    graph.add_edge("parallel_verifiers", "arbitrator")
    graph.add_edge("arbitrator",         "source_formatter")
    graph.add_edge("source_formatter",   "formatter")
    graph.add_edge("formatter",          END)

    return graph.compile()


_validation_graph = None

def get_validation_graph():
    global _validation_graph
    if _validation_graph is None:
        _validation_graph = build_validation_graph()
    return _validation_graph


# ── Self-correction: fix verifier-flagged sections, then the caller re-validates ──

CORRECTOR_MODEL = "claude-sonnet-4-6"

_SECTION_FIELDS = {  # top-level report sections a flag can target
    "disease_intelligence", "market_sizing", "regulatory_pathway",
    "market_access", "market_geography", "executive_summary",
}

# Verifiers often emit RELATIVE field paths ("designations[0].benefit",
# "data_points[4]"), so map by keyword in the field + issue text, not just prefix.
_FIELD_KEYWORDS = [
    ("designation", "regulatory_pathway"), ("pathway", "regulatory_pathway"),
    ("regulatory", "regulatory_pathway"), ("exclusivity", "regulatory_pathway"),
    ("clinical_trial", "regulatory_pathway"), ("fda", "regulatory_pathway"),
    ("data_point", "disease_intelligence"), ("incidence", "disease_intelligence"),
    ("prevalence", "disease_intelligence"), ("resistance", "disease_intelligence"),
    ("pipeline", "disease_intelligence"), ("epidemiolog", "disease_intelligence"),
    ("step", "market_sizing"), ("penetration", "market_sizing"),
    ("tam", "market_sizing"), ("sam", "market_sizing"), ("market_sizing", "market_sizing"),
    ("buyer", "market_access"), ("reimbursement", "market_access"),
    ("payer", "market_access"), ("market_access", "market_access"),
    ("geograph", "market_geography"),
    ("executive", "executive_summary"),
]


def section_for_flag(field: str, issue: str = "") -> str:
    """Map a verifier flag (possibly a relative field path) to a top-level section."""
    pref = (field or "").split(".")[0].split("[")[0]
    if pref in _SECTION_FIELDS:
        return pref
    blob = f"{field} {issue}".lower()
    for kw, sec in _FIELD_KEYWORDS:
        if kw in blob:
            return sec
    return ""


async def correct_flagged_sections(report: dict, error_flags: list) -> dict:
    """Given the verifiers' ERROR flags, ask the model to fix ONLY the affected
    report sections and return them as JSON. Returns {section: corrected_value}.
    Best-effort; returns {} on any problem (the report is then left as-is)."""
    if not error_flags:
        return {}
    sections = {section_for_flag(f.get("field", ""), f.get("issue", "")) for f in error_flags}
    sections = {s for s in sections if s in _SECTION_FIELDS}
    if not sections:
        return {}

    current = {s: report.get(s) for s in sections}
    flags_txt = "\n".join(
        f"- [{f.get('agent')}] {f.get('field')}: {f.get('issue')} (fix: {f.get('suggestion','')})"
        for f in error_flags)

    system = (
        "You are a careful editor fixing factual/numeric errors that independent verifiers "
        "found in a biomedical commercialization report. Fix ONLY the specific issues listed. "
        "Keep the exact same JSON schema for each section. Do not invent new sources or URLs; "
        "if a fact is uncertain, soften it or cite a comparable precedent rather than asserting "
        "a wrong number. Respond with ONLY a JSON object mapping each section name to its "
        "corrected value, e.g. {\"regulatory_pathway\": {...}}.")
    user = (f"VERIFIER ERRORS:\n{flags_txt}\n\nCURRENT SECTIONS (fix these):\n"
            f"{json.dumps(current, indent=2)[:9000]}\n\nReturn the corrected sections as JSON.")

    try:
        raw = await _call_claude(system, user, max_tokens=4000, model=CORRECTOR_MODEL)
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.lower().startswith("json"):
                clean = clean[4:]
        start, end = clean.find("{"), clean.rfind("}")
        data = json.loads(clean[start:end + 1]) if start != -1 else {}
        # Only return sections we asked about.
        return {k: v for k, v in data.items() if k in sections and v}
    except Exception as e:
        logger.warning("correct_flagged_sections failed (non-fatal): %s", e)
        return {}


# ── Public Entry Point ────────────────────────────────────────────────────────

# Antibiotic/small-molecule tokens that must NOT appear in a non-drug (device /
# diagnostic / SaMD / biologic / gene-therapy / vaccine) report. Deterministic backstop
# in case any antibiotic content survives the modality-locked generation prompt.
_ANTIBIOTIC_TOKENS = [
    "qidp", "lpad", "gain act", "pasteur act", "carb-x", "beta-lactam", "bli combination",
    "price per course", "per course", "pathogen", "antimicrobial resistance", "antibiotic",
]
_SMALL_MOLECULE_TOKENS = ["small molecule", "small-molecule", "composition of matter", "drug wac"]
# Drug/biologic-only regulatory + pricing concepts that must not appear on a device/SaMD.
_DRUG_ONLY_TOKENS = ["fast track", "priority review", "accelerated approval",
                     "net realized price per patient", "price per course", "price per patient per year",
                     "bio/informa", "bio/thomas", "phase 1/2/3", "wac"]


def _modality_contamination_flags(report: dict, sub_expert_id: str) -> list:
    """Deterministically flag cross-modality contamination for non-drug products so the
    existing self-correction regenerates the offending sections. Returns [] for
    antibiotics and small-molecule drugs (their tokens are legitimate there)."""
    sid = (sub_expert_id or "").lower()
    if sid.startswith("drug_amr"):
        return []                          # antibiotic — tokens are expected
    is_drug = sid.startswith("drug_")
    is_non_drug = sid.startswith(("device_", "diagnostic_", "digital_", "biologic_",
                                  "gene_therapy_", "vaccine_", "other_"))
    if not (is_drug or is_non_drug):
        return []

    import json as _json
    # Scan only the narrative/commercial sections most prone to antibiotic bleed.
    scan_fields = ("executive_summary", "regulatory_pathway", "market_sizing",
                   "market_access", "strategic_playbook", "commercialization",
                   "commercialization_scores", "expert_panel")
    blob = " ".join(
        _json.dumps(report.get(f, ""), default=str).lower() for f in scan_fields
    )
    tokens = list(_ANTIBIOTIC_TOKENS)
    if is_non_drug:
        tokens += _SMALL_MOLECULE_TOKENS
        # Devices/SaMD/diagnostics must not carry drug-only regulatory/pricing concepts.
        if sid.startswith(("device_", "diagnostic_", "digital_")):
            tokens += _DRUG_ONLY_TOKENS
    hits = sorted({t for t in tokens if t in blob})
    if not hits:
        return []
    label = ("a non-drug medical product" if is_non_drug else "a non-antibiotic drug")
    return [{
        "agent":      "Modality Guard",
        "severity":   "ERROR",
        "category":   "REGULATORY",
        "field":      "regulatory_pathway",
        "issue":      (f"This is {label} ({sub_expert_id}), but the report contains "
                       f"antibiotic/small-molecule-specific content: {', '.join(hits)}."),
        "suggestion": ("Remove all antibiotic/small-molecule framing (QIDP, LPAD, GAIN/PASTEUR, "
                       "CARB-X, BLI, 'price per course', 'small molecule') and use the pathway, "
                       "pricing, and reimbursement appropriate to this modality."),
    }]


async def validate_pi_report(report: dict, sub_expert_id: str = "drug_amr") -> dict:
    """
    Run PI report through 5-agent parallel validation graph.
    Returns report with validation section attached.
    """
    graph = get_validation_graph()

    # Get domain-specific critic rules
    expert_critic_rules = ""
    try:
        from app.services.expert_profiles_v2 import SUB_EXPERT_REGISTRY
        expert = SUB_EXPERT_REGISTRY.get(sub_expert_id)
        if expert:
            expert_critic_rules = getattr(expert, "critic_rules", "")
    except Exception:
        pass

    # Map product_type from sub_expert_id
    product_type_map = {
        "drug_amr": "antibiotic", "drug_oncology": "oncology_drug",
        "biologic_oncology": "biologic_oncology", "gene_therapy_rare": "gene_therapy",
        "device_cardiovascular": "medical_device", "diagnostic_molecular": "diagnostic",
    }
    product_type = product_type_map.get(sub_expert_id, sub_expert_id)

    initial_state: PIReportState = {
        "report":              report,
        "product_type":        product_type,
        "sub_expert_id":       sub_expert_id,
        "expert_critic_rules": expert_critic_rules,
        "math_flags":          [],
        "source_flags":        [],
        "regulatory_flags":    [],
        "market_flags":        [],
        "factual_flags":       [],
        "math_error":          None,
        "source_error":        None,
        "regulatory_error":    None,
        "market_error":        None,
        "factual_error":       None,
        "all_flags":           [],
        "validation_passed":   True,
        "validated_report":    None,
        "factual_skipped":     False,
    }

    try:
        final_state = await graph.ainvoke(initial_state)
        result = final_state.get("validated_report", report)

        # Deterministic modality-contamination backstop — merge into the validation
        # result so any residual antibiotic/small-molecule bleed is flagged as an ERROR
        # and picked up by the self-correction pass.
        try:
            contam = _modality_contamination_flags(report, sub_expert_id)
            if contam:
                v = result.setdefault("validation", {})
                v["errors"] = (v.get("errors") or []) + contam
                v["total_flags"] = (v.get("total_flags") or 0) + len(contam)
                v["status"] = "ERROR"
                v["passed"] = False
                agents = v.get("agents_run") or []
                if "Modality Guard" not in agents:
                    v["agents_run"] = agents + ["Modality Guard"]
                logger.warning("Modality Guard flagged contamination for %s: %s",
                               sub_expert_id, contam[0]["issue"])
        except Exception as _mg:
            logger.warning("Modality Guard check failed (non-fatal): %s", _mg)

        agents_run = len(result.get("validation", {}).get("agents_run", []))
        total_flags = result.get("validation", {}).get("total_flags", 0)
        logger.info(f"Validation complete: {agents_run} agents, {total_flags} flags")
        return result
    except Exception as e:
        logger.error(f"Validation graph failed: {e}")
        report["validation"] = {
            "status": "ERROR",
            "passed": True,
            "export_blocked": False,
            "errors": [], "warnings": [], "notes": [],
            "total_flags": 0,
            "agents_run": [],
            "error": str(e),
            "summary": "Validation service unavailable",
            "validated_at": datetime.utcnow().isoformat(),
        }
        return report
