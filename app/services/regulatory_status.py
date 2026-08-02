"""
Regulatory Status  (H-02)
=========================
Derives a single typed regulatory status for a product before the report
is generated. The status drives what §3 (regulatory pathway) renders.

Root cause of defect:
  Hublink (non-clinical research data logger) received a full §3 describing
  510(k) pathway, De Novo, NTAP, and CPT 99453-99458 — none of which apply.
  The engine was running two parallel narratives ("it might be regulated / it
  might not") instead of a single decision tree.

Design:
  1. `RegulatoryStatus` enum — four values, each maps to a different §3 template.
  2. `derive_regulatory_status(archetype, idea)` — deterministic rules. No LLM.
     Archetype is the primary signal; idea text is checked for override triggers.
  3. `format_regulatory_section(status, archetype, idea)` — renders §3 content
     appropriate to the status. NOT_REGULATED renders "Not applicable" with
     explanation; REGULATED unlocks the full pathway block; others render
     appropriately scoped content.
  4. `regulatory_directive(status, archetype)` — one-line instruction injected
     into the system prompt so the LLM knows which template to use.

Wiring: alignment_service.py derives status at intake (after archetype
resolution) and injects the directive into the synthesis prompt.
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


# ── Status enum ───────────────────────────────────────────────────────────────

class RegulatoryStatus(str, Enum):
    NOT_REGULATED         = "NOT_REGULATED"         # no FDA jurisdiction; no pathway
    LIKELY_EXEMPT         = "LIKELY_EXEMPT"          # likely 21 CFR 880.6310 / LDT exemption
    REGULATED             = "REGULATED"              # requires FDA clearance/approval
    AMBIGUOUS_REQUIRES_COUNSEL = "AMBIGUOUS_REQUIRES_COUNSEL"  # borderline; legal review needed


# ── Archetype → status mapping ────────────────────────────────────────────────
# Deterministic first pass: if archetype is known, map directly.
_ARCHETYPE_STATUS_MAP: dict[str, RegulatoryStatus] = {
    # Non-clinical research tools — no clinical indication, not intended for patient use
    "research_tool_non_clinical":   RegulatoryStatus.NOT_REGULATED,
    "research_infrastructure_saas": RegulatoryStatus.NOT_REGULATED,
    # Clinical/regulated archetypes
    "drug":                         RegulatoryStatus.REGULATED,
    "biologic":                     RegulatoryStatus.REGULATED,
    "device_class_ii":              RegulatoryStatus.REGULATED,
    "device_class_iii":             RegulatoryStatus.REGULATED,
    "samd":                         RegulatoryStatus.REGULATED,
    "ivd":                          RegulatoryStatus.REGULATED,
    "companion_diagnostic":         RegulatoryStatus.REGULATED,
    "gene_therapy":                 RegulatoryStatus.REGULATED,
    "vaccine":                      RegulatoryStatus.REGULATED,
    # Digital/software — depends on intended use
    "digital_therapeutic":          RegulatoryStatus.REGULATED,
    "digital_cds":                  RegulatoryStatus.AMBIGUOUS_REQUIRES_COUNSEL,
    "digital_rpm":                  RegulatoryStatus.REGULATED,
    "digital_wellness":             RegulatoryStatus.LIKELY_EXEMPT,
    # Lab tests
    "ldt":                          RegulatoryStatus.LIKELY_EXEMPT,
    # Research software without patient-facing claims
    "research_saas":                RegulatoryStatus.NOT_REGULATED,
}

# Sub-expert IDs that auto-map (they contain the archetype as a prefix)
_REGULATED_PREFIXES = (
    "drug_", "biologic_", "gene_therapy_", "device_", "diagnostic_",
    "vaccine_", "digital_therapeutic", "digital_rpm", "digital_cds",
)
_NOT_REGULATED_PREFIXES = (
    "research_tool_", "research_infrastructure_",
)
_LIKELY_EXEMPT_PREFIXES = (
    "digital_wellness",
)


# ── Idea-text override triggers ────────────────────────────────────────────────
# If the idea text strongly signals a clinical intended use, bump up to REGULATED.
_CLINICAL_USE_PATTERNS = [
    r"\bdiagnos[ei]\b",
    r"\btreat(?:ment|ing|s)\b",
    r"\bprescri(?:be|ption)\b",
    r"\bclinical\s+(?:trial|study|decision)\b",
    r"\bpatient\b",
    r"\bhospital\b",
    r"\bphysician\b",
    r"\bFDA\s+(?:cleared|approved|510\(k\))\b",
]
# If the idea text clearly signals NON-clinical research use, lock to NOT_REGULATED.
_NON_CLINICAL_PATTERNS = [
    r"\bresearch\s+(?:tool|platform|lab|study|use|purpose)\b",
    r"\bacademic\s+(?:lab|research|neuroscience|neurology|biology|chemistry)\b",
    r"\bPIs?\b.{0,50}\bdata\b",          # "PIs" or "PI", up to 50 chars before "data"
    r"\bNIH\s+(?:grant|funded|reporter)\b",
    r"\bnon[- ]clinical\b",
    r"\bno\s+patient\s+(?:care|contact|interaction|data)\b",  # negation of patient use
    r"\bnot\s+intended\s+for\s+(?:patient|clinical|diagnostic)\b",
    r"\bsold\s+exclusively\s+to\s+(?:university|academic|research|lab)\b",
    r"\bresearch[- ]use\s+only\b",
]


# ── Derivation ────────────────────────────────────────────────────────────────

def derive_regulatory_status(
    archetype: str,
    idea: str = "",
    sub_expert_id: str = "",
) -> RegulatoryStatus:
    """
    Deterministic derivation — no LLM call.

    Priority:
    1. Exact archetype mapping
    2. Sub-expert-id prefix matching
    3. Idea-text pattern matching (override)
    4. Fallback: AMBIGUOUS_REQUIRES_COUNSEL
    """
    arch_l = (archetype or "").lower()
    sid_l  = (sub_expert_id or "").lower()
    idea_l = (idea or "").lower()

    # 1. Exact archetype map
    if arch_l in _ARCHETYPE_STATUS_MAP:
        status = _ARCHETYPE_STATUS_MAP[arch_l]
    # 2. Sub-expert-id prefix
    elif any(sid_l.startswith(p) for p in _NOT_REGULATED_PREFIXES):
        status = RegulatoryStatus.NOT_REGULATED
    elif any(sid_l.startswith(p) for p in _REGULATED_PREFIXES):
        status = RegulatoryStatus.REGULATED
    elif any(sid_l.startswith(p) for p in _LIKELY_EXEMPT_PREFIXES):
        status = RegulatoryStatus.LIKELY_EXEMPT
    else:
        status = RegulatoryStatus.AMBIGUOUS_REQUIRES_COUNSEL

    # 3. Idea-text override (only upgrades NOT_REGULATED → AMBIGUOUS, never the reverse)
    #    Non-clinical signals in the idea text block the upgrade: a disclaimer like
    #    "No patient care" contains "patient" but is not a clinical-use claim.
    if status == RegulatoryStatus.NOT_REGULATED and idea:
        has_clinical  = any(re.search(p, idea, re.I) for p in _CLINICAL_USE_PATTERNS)
        has_non_clinical = any(re.search(p, idea, re.I) for p in _NON_CLINICAL_PATTERNS)
        if has_clinical and not has_non_clinical:
            logger.info(
                "H-02: idea text contains clinical-use language for non-clinical archetype '%s' "
                "(no countervailing non-clinical signal) — upgrading to AMBIGUOUS_REQUIRES_COUNSEL",
                arch_l,
            )
            status = RegulatoryStatus.AMBIGUOUS_REQUIRES_COUNSEL
        elif has_clinical and has_non_clinical:
            logger.debug(
                "H-02: idea text has both clinical and non-clinical signals for archetype '%s' "
                "— non-clinical signal wins; keeping NOT_REGULATED", arch_l,
            )

    logger.debug("H-02: archetype='%s' sub_expert_id='%s' → status=%s", arch_l, sid_l, status.value)
    return status


# ── Decision tree text ────────────────────────────────────────────────────────

_DECISION_TREE_TEMPLATE = """\
REGULATORY STATUS DETERMINATION (H-02):
  Q1: Is this product intended to diagnose, treat, cure, or prevent disease in a patient?
      {q1_answer}

  Q2: Is it used directly in clinical care or does it influence a clinical decision?
      {q2_answer}

  DETERMINATION: {status}
  {rationale}

INSTRUCTION FOR §3 (Regulatory Pathway):
  {section_instruction}
"""


def regulatory_directive(status: RegulatoryStatus, archetype: str = "") -> str:
    """
    One-line directive injected into the synthesis system prompt.
    Tells the LLM exactly what to render in §3.
    """
    directives = {
        RegulatoryStatus.NOT_REGULATED: (
            "§4 REGULATORY & COMPLIANCE OVERVIEW: This product is NOT a regulated medical device or drug. "
            "Do NOT mention 510(k), De Novo, PMA, NDA, BLA, CPT codes, NTAP, or any FDA pathway. "
            "Title this section 'Regulatory & Compliance Overview', not 'Regulatory Pathway'. "
            "Open with: 'FDA jurisdiction: not required.' and explain why (non-clinical intended use, "
            "outside 21 CFR § 201(h)). "
            "Then list what DOES apply in a structured table: "
            "(1) IRB/IACUC if human- or animal-subjects research; "
            "(2) intended-use legal opinion before commercial launch ($15k–$40k); "
            "(3) export controls (EAR/ITAR) if hardware ships internationally; "
            "(4) Bayh-Dole/IP obligations if federally funded; "
            "(5) FCC Part 15 certification if any RF hardware; "
            "(6) state lab safety/OSHA compliance. "
            "Close with a watch-out paragraph: list the marketing claims or use-case changes "
            "that would trigger FDA jurisdiction (diagnostic claims, clinical decision support, "
            "patient monitoring). Be specific and actionable."
        ),
        RegulatoryStatus.LIKELY_EXEMPT: (
            "§3 REGULATORY PATHWAY: This product is likely exempt from FDA premarket review "
            "(e.g., general wellness, LDT, or 21 CFR Part 880 exemption). "
            "State the specific exemption basis and its limits. Note what would trigger "
            "regulated status (e.g., making diagnostic claims, marketing to patients). "
            "Do NOT write a full 510(k)/De Novo pathway — that would be misleading."
        ),
        RegulatoryStatus.REGULATED: (
            "§3 REGULATORY PATHWAY: This product requires FDA clearance or approval. "
            "Write the full regulatory pathway: exact submission type, predicate product "
            "(if 510(k)/De Novo), expected timeline, available expedited designations, "
            "and a named precedent product with its approval date and application number."
        ),
        RegulatoryStatus.AMBIGUOUS_REQUIRES_COUNSEL: (
            "§3 REGULATORY PATHWAY: The regulatory status of this product is ambiguous. "
            "Present a decision tree (the gating question is: does the product constitute "
            "a medical device or drug under its intended use?). For each branch (regulated / "
            "not regulated), describe what changes about the development path. "
            "Explicitly recommend regulatory counsel before development investment. "
            "Do NOT assert a definitive pathway — the ambiguity is the finding."
        ),
    }
    return directives.get(status, directives[RegulatoryStatus.AMBIGUOUS_REQUIRES_COUNSEL])


def format_regulatory_decision_tree(
    status: RegulatoryStatus,
    archetype: str = "",
    idea: str = "",
) -> str:
    """
    Human-readable decision tree block for logging/audit. Not user-facing.
    """
    is_not_regulated = status == RegulatoryStatus.NOT_REGULATED
    is_likely_exempt = status == RegulatoryStatus.LIKELY_EXEMPT

    q1 = "NO — product is not intended to diagnose, treat, cure, or prevent disease." if is_not_regulated else \
         "LIKELY NO — intended for research only, but intended use must be controlled." if is_likely_exempt else \
         "YES (or plausible) — intended use is clinical or influences clinical decision."

    q2 = "NO — sold to academic investigators for lab research, not clinical care." if is_not_regulated else \
         "UNLIKELY — but must be confirmed by the product labeling and marketing." if is_likely_exempt else \
         "YES — used in clinical care or influences a regulated clinical decision."

    rationales = {
        RegulatoryStatus.NOT_REGULATED:
            f"Archetype '{archetype}' is a non-clinical research tool. "
            "No FDA premarket review required under 21 CFR.",
        RegulatoryStatus.LIKELY_EXEMPT:
            f"Archetype '{archetype}' is likely exempt from premarket review "
            "under the general wellness or LDT exemption, subject to labeling controls.",
        RegulatoryStatus.REGULATED:
            f"Archetype '{archetype}' constitutes a medical device, drug, biologic, or "
            "IVD requiring FDA premarket review.",
        RegulatoryStatus.AMBIGUOUS_REQUIRES_COUNSEL:
            f"Archetype '{archetype}' is borderline. Intended use, labeling, and marketing "
            "claims determine whether FDA jurisdiction applies. Regulatory counsel required.",
    }

    section_instructions = {
        RegulatoryStatus.NOT_REGULATED:    "Render §3 as 'Not Applicable — Not a regulated product.'",
        RegulatoryStatus.LIKELY_EXEMPT:    "Render §3 with the exemption basis and its trigger conditions.",
        RegulatoryStatus.REGULATED:        "Render §3 in full with pathway, timeline, and precedent.",
        RegulatoryStatus.AMBIGUOUS_REQUIRES_COUNSEL: "Render §3 as a conditional decision tree.",
    }

    return _DECISION_TREE_TEMPLATE.format(
        q1_answer=q1,
        q2_answer=q2,
        status=status.value,
        rationale=rationales.get(status, ""),
        section_instruction=section_instructions.get(status, ""),
    )
