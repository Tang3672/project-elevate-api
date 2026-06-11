"""
Technology Readiness Level (TRL) Assessment Service
=====================================================
TRL 1-9 scoring for biomedical innovations, grounded in:
  - NIH NHLBI Catalyze TRL framework (nhlbicatalyze.org/trl)
  - BARDA/DARPA TRL framework for medical countermeasures
  - FDA biomedical TRL guidance for drugs, devices, and diagnostics
  - SBIR.gov phase-specific TRL requirements

Why this matters vs. ChatGPT:
  TRL is the universal language TTOs, investors, SBIR program managers, and
  tech transfer committees use to evaluate stage-of-development. ChatGPT gives
  vague "early stage" or "proof-of-concept" assessments. This service returns
  a specific TRL score with:
    - The exact evidence required to justify that level
    - What's missing to reach the next level (gap analysis)
    - What's needed for SBIR Phase I (TRL 2-4) vs. Phase II (TRL 5-7)
    - Estimated cost range to reach the next level

References:
  [NIH]    NHLBI Catalyze TRL Framework, 2023
  [BARDA]  BARDA/DoD Biomedical TRL Integrated Framework, 2021
  [SBIR]   SBIR/STTR Program Policy Directive, TRL requirements by agency
  [FDA]    FDA Technology Readiness Levels for Medical Countermeasures
"""

from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# TRL level definitions — biomedical specific
# ─────────────────────────────────────────────────────────────────────────────

TRL_DEFINITIONS = {
    1: {
        "label":       "Basic Principles Observed",
        "description": "Scientific hypothesis proposed. Literature review identifies target/mechanism. No experimental data yet.",
        "evidence":    ["Published literature supporting the hypothesis", "Target/mechanism identified", "No experimental data from the lab"],
    },
    2: {
        "label":       "Technology Concept Formulated",
        "description": "Technology concept and application defined. Initial in silico or in vitro experiments begun.",
        "evidence":    ["Target identified with supporting data", "Initial in vitro or in silico assay data", "Proof-of-concept design documented"],
    },
    3: {
        "label":       "Experimental Proof of Concept",
        "description": "In vitro or in silico proof-of-concept demonstrated. Key function proven in lab.",
        "evidence":    ["In vitro efficacy data in relevant cell/biochemical assay", "Initial structure-activity relationship (SAR) or equivalent", "No animal data required"],
    },
    4: {
        "label":       "Technology Validated in Lab",
        "description": "Basic technological components validated in laboratory. In vitro or initial in vivo data.",
        "evidence":    ["In vitro efficacy in disease-relevant model", "Initial ADME/PK data or device bench testing", "Toxicity: at minimum cytotoxicity screen"],
    },
    5: {
        "label":       "Technology Validated in Relevant Environment",
        "description": "Technology validated in disease-relevant in vivo model or clinical prototype.",
        "evidence":    ["In vivo efficacy (rodent or relevant animal model)", "PK/PD profile established", "Initial safety/tolerability data in animals"],
    },
    6: {
        "label":       "Technology Demonstrated in Relevant Environment",
        "description": "Prototype demonstrated in relevant environment. IND-enabling studies complete or underway.",
        "evidence":    ["Efficacy in non-rodent model (or clinical prototype tested)", "GLP safety/tox studies initiated or complete", "IND or IDE submission in preparation or filed"],
    },
    7: {
        "label":       "System Prototype Demonstration",
        "description": "System prototype demonstrated in operational environment. Phase 1 clinical trial complete or underway.",
        "evidence":    ["Phase 1 trial initiated or complete (human safety data)", "Initial human PK data available", "Manufacturing process defined (GMP-ready)"],
    },
    8: {
        "label":       "System Complete and Qualified",
        "description": "Technology complete. Phase 2/3 clinical evidence with regulatory submission in preparation.",
        "evidence":    ["Phase 2 clinical data demonstrating efficacy signal", "Phase 3 trial complete or underway", "Regulatory submission (NDA/BLA/PMA/510k) prepared or filed"],
    },
    9: {
        "label":       "Actual System Proven",
        "description": "Technology approved and commercially available.",
        "evidence":    ["FDA clearance or approval obtained", "Commercial manufacturing operational", "Post-market surveillance active"],
    },
}

# What needs to happen to advance FROM each level
TRL_ADVANCEMENT_REQUIREMENTS = {
    1: {
        "to_next": [
            "Identify and validate a specific molecular or biological target",
            "Develop initial in vitro assay or in silico model to test hypothesis",
            "Confirm patent freedom-to-operate landscape",
        ],
        "cost_range": "$10k–$50k (assay development, computational modeling)",
    },
    2: {
        "to_next": [
            "Generate in vitro proof-of-concept data (cell-based or biochemical assay)",
            "Synthesize/express/produce initial lead compound, construct, or device prototype",
            "Conduct preliminary selectivity or specificity testing",
        ],
        "cost_range": "$25k–$150k (initial prototype, in vitro testing)",
    },
    3: {
        "to_next": [
            "Optimize lead compound/construct with SAR or equivalent (10-50 analogues)",
            "Establish disease-relevant in vitro model (primary cells, organoid, or disease cell line)",
            "Generate initial ADME data (permeability, metabolic stability, or device equivalent)",
        ],
        "cost_range": "$100k–$500k (medicinal chemistry, assay development)",
    },
    4: {
        "to_next": [
            "Demonstrate efficacy in a disease-relevant animal model",
            "Obtain preliminary in vivo PK/PD data",
            "Conduct initial in vivo tolerability/safety assessment",
        ],
        "cost_range": "$200k–$1M (in vivo studies, PK/PD)",
    },
    5: {
        "to_next": [
            "Demonstrate efficacy in a second, more translationally relevant animal model",
            "Complete GLP safety pharmacology studies",
            "Develop scalable manufacturing process to GMP standards",
            "Prepare pre-IND briefing document",
        ],
        "cost_range": "$500k–$3M (GLP studies, process development)",
    },
    6: {
        "to_next": [
            "Complete IND-enabling GLP tox studies (28-day repeat dose, genotoxicity, safety pharm)",
            "File IND or IDE with FDA",
            "Complete Phase 1 trial design and protocol approval",
            "Establish GMP manufacturing site",
        ],
        "cost_range": "$1M–$8M (IND-enabling package, GMP manufacturing)",
    },
    7: {
        "to_next": [
            "Complete Phase 1 clinical trial with safety and PK data in humans",
            "Design and initiate Phase 2 study with pre-specified efficacy endpoints",
            "Negotiate payer coverage strategy / reimbursement pathway",
        ],
        "cost_range": "$3M–$25M (Phase 1 trial, Phase 2 design)",
    },
    8: {
        "to_next": [
            "Complete Phase 3 pivotal trial",
            "Prepare and submit NDA/BLA/PMA/510(k)",
            "Establish commercial manufacturing and supply chain",
            "Secure payer coverage and reimbursement codes",
        ],
        "cost_range": "$20M–$300M+ (Phase 3, regulatory submission, commercial prep)",
    },
    9: {
        "to_next": ["Product approved and in commercial distribution."],
        "cost_range": "N/A (commercialization phase)",
    },
}

# SBIR phase requirements
SBIR_TRL_REQUIREMENTS = {
    "phase1":  "TRL 2-4 (concept defined with early in vitro data)",
    "phase2":  "TRL 4-6 (in vivo validation underway, IND-enabling studies in plan)",
    "phase3":  "TRL 6-8 (clinical data available, near-commercialization)",
}


# ─────────────────────────────────────────────────────────────────────────────
# Keyword indicators for TRL estimation
# ─────────────────────────────────────────────────────────────────────────────

_TRL_KEYWORD_SIGNALS = {
    # Keywords that suggest higher TRL
    9: ["fda approved", "fda cleared", "on market", "commercial product", "launched", "510(k) cleared"],
    8: ["phase 3", "phase iii", "nda filed", "bla filed", "pma filed", "510k filed", "pivotal trial"],
    7: ["phase 2", "phase ii", "phase 1 complete", "first in human", "ind filed", "ide filed", "clinical data"],
    6: ["phase 1", "phase i", "ind-enabling", "ind enabling", "glp tox", "gmp", "pre-ind"],
    5: ["animal model", "in vivo", "rodent model", "mouse model", "rat model", "non-human primate", "pk/pd", "efficacy model"],
    4: ["proof of concept", "poc", "in vitro", "cell line", "primary cells", "in vivo preliminary"],
    3: ["mechanism of action", "target validated", "hit identified", "lead compound", "biochemical assay"],
    2: ["hypothesis", "concept", "proposed", "in silico", "computational", "theoretical"],
    1: ["basic research", "early stage", "discovery", "fundamental"],
}

_DEVELOPMENT_PHASE_TRL_MAP = {
    "preclinical": 4,   # assume TRL 4 if in preclinical stage
    "phase1":      7,
    "phase2":      8,
    "phase3":      8,
    "approved":    9,
}


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TRLResult:
    trl_level:           int                  # 1-9
    trl_label:           str
    trl_description:     str
    evidence_present:    list[str]            # what supports the current TRL
    gaps_to_next_level:  list[str]            # what's needed for TRL+1
    cost_to_next:        str                  # estimated cost range
    sbir_phase1_ready:   bool                 # meets TRL for SBIR Phase I
    sbir_phase2_ready:   bool                 # meets TRL for SBIR Phase II
    sbir_gap:            Optional[str]        # what's needed for SBIR Phase I/II
    investor_readiness:  str                  # "Pre-seed", "Seed", "Series A", etc.
    formatted:           str = ""            # pre-formatted string for report injection


def _estimate_trl_from_idea(idea: str, development_phase: str = "preclinical") -> int:
    """
    Estimate TRL from idea description text and stated development phase.
    Uses keyword matching as a fast heuristic; the Haiku panel refines this.
    """
    idea_lower = idea.lower()

    # Start with phase-based estimate
    base_trl = _DEVELOPMENT_PHASE_TRL_MAP.get(development_phase.lower().replace(" ", "").replace("-", ""), 3)

    # Adjust up/down based on keywords
    for trl, keywords in sorted(_TRL_KEYWORD_SIGNALS.items(), reverse=True):
        if any(kw in idea_lower for kw in keywords):
            # Use the highest TRL whose keywords appear in the idea
            return min(max(trl, base_trl), 9)

    return base_trl


def assess_trl(
    idea: str,
    development_phase: str = "preclinical",
    sub_expert_id: str = "drug_amr",
    explicit_trl: Optional[int] = None,
) -> TRLResult:
    """
    Compute a TRL assessment with gap analysis.

    idea: the PI's innovation description
    development_phase: preclinical | phase1 | phase2 | phase3 | approved
    sub_expert_id: used for context-specific gap advice
    explicit_trl: if known (e.g., user stated it), skip keyword estimation
    """
    trl = explicit_trl if explicit_trl else _estimate_trl_from_idea(idea, development_phase)
    trl = max(1, min(9, trl))

    defn = TRL_DEFINITIONS[trl]
    adv  = TRL_ADVANCEMENT_REQUIREMENTS[trl]

    # SBIR readiness
    sbir_p1_ready  = trl >= 2
    sbir_p2_ready  = trl >= 4
    if not sbir_p2_ready:
        sbir_gap = f"SBIR Phase II typically requires TRL 4-6. Current: TRL {trl}. Gaps: {'; '.join(adv['to_next'][:2])}"
    elif not sbir_p1_ready:
        sbir_gap = f"SBIR Phase I requires TRL 2-4. Current: TRL {trl}. Need: initial in vitro proof-of-concept."
    else:
        sbir_gap = None

    # Investor readiness
    if trl <= 2:
        investor_stage = "Friends/family, angel — concept-stage"
    elif trl <= 3:
        investor_stage = "Pre-seed angel / NIH R21 / proof-of-concept fund"
    elif trl <= 4:
        investor_stage = "SBIR Phase I / seed angel ($500k-$2M)"
    elif trl <= 5:
        investor_stage = "SBIR Phase II / seed VC ($2M-$5M)"
    elif trl <= 6:
        investor_stage = "Series A ($5M-$20M) / SBIR Phase II + follow-on"
    elif trl <= 7:
        investor_stage = "Series B ($20M-$80M) — Phase 1 data in hand"
    elif trl <= 8:
        investor_stage = "Series C+ ($50M-$200M) / late-stage crossover"
    else:
        investor_stage = "Commercial (post-approval)"

    result = TRLResult(
        trl_level           = trl,
        trl_label           = defn["label"],
        trl_description     = defn["description"],
        evidence_present    = defn["evidence"],
        gaps_to_next_level  = adv["to_next"],
        cost_to_next        = adv["cost_range"],
        sbir_phase1_ready   = sbir_p1_ready,
        sbir_phase2_ready   = sbir_p2_ready,
        sbir_gap            = sbir_gap,
        investor_readiness  = investor_stage,
    )

    result.formatted = _format_trl(result)
    return result


def _format_trl(r: TRLResult) -> str:
    lines = [
        f"TECHNOLOGY READINESS LEVEL: TRL {r.trl_level}/9 — {r.trl_label}",
        f"  {r.trl_description}",
        "",
        "  Evidence supporting this TRL assessment:",
    ]
    for e in r.evidence_present:
        lines.append(f"    • {e}")
    lines += [
        "",
        f"  Gaps to reach TRL {r.trl_level + 1}:" if r.trl_level < 9 else "  Status: Fully commercialized.",
    ]
    for g in r.gaps_to_next_level[:3]:
        lines.append(f"    → {g}")
    lines += [
        f"  Estimated cost to next level: {r.cost_to_next}",
        "",
        f"  SBIR Phase I ready: {'Yes' if r.sbir_phase1_ready else 'Not yet — need TRL 2+'}",
        f"  SBIR Phase II ready: {'Yes' if r.sbir_phase2_ready else 'Not yet — need TRL 4+'}",
        f"  Investor stage: {r.investor_readiness}",
    ]
    if r.sbir_gap and not r.sbir_phase2_ready:
        lines.append(f"  SBIR gap: {r.sbir_gap}")
    return "\n".join(lines)
