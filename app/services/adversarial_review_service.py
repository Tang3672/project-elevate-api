"""
Adversarial Review Service  (S-06)
===================================
Runs a dedicated critic pass over the completed report's recommendations.
The critic is a separate Haiku call with a different system prompt — it does
NOT see the synthesis model's reasoning chain, only the output, so it gives
an independent evaluation rather than rationalizing what was already written.

Root cause of gap:
  The original report makes recommendations without counter-analysis. Gaidica's
  white paper explicitly analyses where its recommendations break down
  (e.g., metered pricing "penalises reliability — you bill less when the
  product works better"). That second-order reasoning is what the target
  audience expects and what Medlevate cannot currently produce.

Contract per item:
  {
    "recommendation":          string   # what the report recommends
    "supporting_case":         string   # strongest reason it's right
    "structural_risk":         string   # REQUIRED, non-empty — best reason it's wrong
    "disconfirming_evidence":  string   # specific counter-evidence or "None identified"
    "what_would_change_this":  string   # what evidence or condition would reverse it
  }

Usage: call run_adversarial_review(report_dict, idea, sub_expert_id).
Returns List[dict] suitable for PIReport.adversarial_review.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_HAIKU_MODEL      = "claude-haiku-4-5-20251001"
_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
_MAX_RECOMMENDATIONS = 5   # cap to keep the critic pass fast

_CRITIC_SYSTEM = """\
You are a critical advisor reviewing a draft commercial intelligence report.
Your job is NOT to agree with the report. Your job is to identify where each
recommendation could be wrong, where it is missing evidence, and what a
skeptical investor or experienced TTO officer would push back on.

For each recommendation you receive:
1. State the supporting case briefly (steelman).
2. State the structural risk — the best specific reason this recommendation
   could be wrong, mislead the client, or fail under realistic conditions.
   This field is REQUIRED and must be non-empty. "No risks identified" is
   not an acceptable answer.
3. Identify any specific disconfirming evidence from the market, comparable
   companies, or academic literature. If none, say "None identified" — but
   look hard before saying that.
4. State what evidence or changed condition would reverse your assessment.

Be specific. "This might not work" is not useful. "This assumes a 25% SAM
capture rate that no comparable early-stage B2B SaaS company has achieved
in year 1 — analogous companies (e.g. Samsara, Verkada) took 3-4 years to
reach 10% of their initial SAM" is useful.

Return ONLY valid JSON — a list of objects, one per recommendation:
[
  {
    "recommendation": "<text of the recommendation>",
    "supporting_case": "<strongest reason it is right, under 200 chars>",
    "structural_risk": "<specific reason it could be wrong, under 300 chars — REQUIRED>",
    "disconfirming_evidence": "<specific counter-evidence or 'None identified', under 200 chars>",
    "what_would_change_this": "<what evidence or condition would reverse the risk, under 200 chars>"
  }
]"""


def _extract_recommendations(report_dict: dict, idea: str) -> list[str]:
    """
    Pull the top recommendations from the report dict.
    Combines recommended_next_steps with key claims from strategic sections.
    """
    recs: list[str] = []

    # Primary: recommended_next_steps
    for step in report_dict.get("recommended_next_steps", [])[:_MAX_RECOMMENDATIONS]:
        if isinstance(step, str) and step.strip():
            recs.append(step.strip())

    # Supplement with pricing strategy if present
    pricing = report_dict.get("pricing_model_analysis") or {}
    for row in pricing.get("model_comparison", [])[:2]:
        if isinstance(row, dict) and row.get("strategic_stance") == "Recommended":
            recs.append(f"Pricing: adopt {row.get('pricing_model', '')} model")

    # Cap total
    return recs[:_MAX_RECOMMENDATIONS]


def _fallback_review(recommendations: list[str]) -> list[dict]:
    """Deterministic fallback when the Haiku call is unavailable."""
    return [
        {
            "recommendation": r,
            "supporting_case": "See supporting analysis in the report.",
            "structural_risk": "Independent adversarial review unavailable (API key not set). Manual review required.",
            "disconfirming_evidence": "Not assessed.",
            "what_would_change_this": "Not assessed.",
        }
        for r in recommendations
    ]


async def run_adversarial_review(
    report_dict: dict,
    idea: str = "",
    sub_expert_id: str = "",
) -> list[dict]:
    """
    Run the S-06 adversarial critic pass.

    Returns a list of structured review objects. If the API call fails,
    returns a fallback list that marks the gap honestly rather than silently
    omitting the section.
    """
    recommendations = _extract_recommendations(report_dict, idea)
    if not recommendations:
        logger.info("S-06: no recommendations to review in report dict")
        return []

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("S-06: ANTHROPIC_API_KEY not set — using fallback adversarial review")
        return _fallback_review(recommendations)

    user_msg = (
        f"Product: {idea[:300]}\n"
        f"Domain: {sub_expert_id}\n\n"
        "Recommendations to critique:\n"
        + "\n".join(f"{i+1}. {r}" for i, r in enumerate(recommendations))
    )

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                _ANTHROPIC_API_URL,
                headers={
                    "x-api-key":           api_key,
                    "anthropic-version":   "2023-06-01",
                    "content-type":        "application/json",
                },
                json={
                    "model":      _HAIKU_MODEL,
                    "max_tokens": 2048,
                    "system":     _CRITIC_SYSTEM,
                    "messages":   [{"role": "user", "content": user_msg}],
                },
            )
            r.raise_for_status()
            raw = r.json()["content"][0]["text"].strip()

            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            items = json.loads(raw)
            if not isinstance(items, list):
                raise ValueError(f"Expected list, got {type(items)}")

            # Enforce: structural_risk must be non-empty
            for item in items:
                if not isinstance(item, dict):
                    continue
                if not (item.get("structural_risk") or "").strip():
                    item["structural_risk"] = (
                        "Structural risk not assessed by critic model — manual review required."
                    )

            logger.info("S-06: adversarial review complete: %d items", len(items))
            return items

    except Exception as _e:
        logger.warning("S-06 adversarial review failed (non-fatal): %s", _e)
        return _fallback_review(recommendations)


def validate_adversarial_review(items: list[dict]) -> list[dict]:
    """
    Post-process the adversarial review list:
    - Enforce structural_risk is non-empty for every item
    - Drop items with no recommendation text
    """
    validated = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if not (item.get("recommendation") or "").strip():
            continue
        if not (item.get("structural_risk") or "").strip():
            item["structural_risk"] = (
                "Structural risk was not generated. Independent manual review recommended."
            )
        validated.append(item)
    return validated
