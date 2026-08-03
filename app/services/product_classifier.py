"""
Stage-1 Product Classifier  (Spec v3 — C.1 / C.2)
===================================================
Resolves a `Classification` at intake (before /clarify questions are generated)
so that:
  1. The report title uses the real product name instead of a description fragment.
  2. Questions are conditioned on archetype — research tools get PI-budget questions,
     not hospital P&T / formulary questions.
  3. Every `IntakeQuestion` binds to a named model field so downstream engines
     can map the answer directly into the pricing/market derivation.

Hard rule (C.2): no IntakeQuestion may exist without a `binds_to` field.

Architecture:
  classify_product(idea)          → Classification
  get_conditioned_questions(cls)  → list[IntakeQuestion]

The classifier is a thin LLM call (Claude Haiku) that extracts product name,
one-line characterisation, TRL, and ambiguities. Domain + archetype come from
the deterministic soft_router / product_archetype layer; the LLM is NOT trusted
to decide regulatory framing.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class Classification:
    product_name: str           # "Hublink"  ← root-cause fix for title bug
    one_line: str               # positive characterisation, never a negation
    domain: str                 # "LIFE_SCIENCES_RESEARCH" | "LIFE_SCIENCES_CLINICAL"
    archetype: str              # ProductArchetype value string
    trl: int                    # 1-9
    confidence: float           # 0-1
    ambiguities: list[str]      # drives stage-2 conditioned questions


@dataclass
class IntakeQuestion:
    id: str
    text: str
    binds_to: str               # "buyer.persona" | "price.observed_band" | ...
    why_asked: str
    input_type: Literal["single", "multi", "number", "range", "text"]
    options: list[str] | None
    default: Any | None
    impact_rank: int            # 1 = highest impact
    engine_estimate: str | None = None  # derived from generic comparables (Rule 8 — never operator-specific)


# ── Domain / archetype detection ──────────────────────────────────────────────

_RESEARCH_SUB_IDS = frozenset({
    "research_tool_non_clinical",
    "research_infrastructure_saas",
})

_RESEARCH_IDEA_PATTERNS = [
    r"\bresearch\s+(tool|platform|infrastructure|software|data)\b",
    r"\bacademic\s+(lab|research|neuroscience|biology|chemistry)\b",
    r"\bNIH[-\s](grant|funded|reporter)\b",
    r"\bprincipal\s+investigator\b",
    r"\b(PIs?)\b.{0,60}\b(data|sensor|lab|grant)\b",
    r"\bnon[-\s]?clinical\b",
    r"\bcore\s+facilit(y|ies)\b",
    r"\bwearable\s+sensor[s]?.{0,60}\blab\b",
    # Research infrastructure / lab-software patterns
    r"\b(scientific|experimental|behavioral|neural|electrophysiology)\s+data\b",
    r"\bsd[-\s]?card\b",
    r"\bmemory\s+card[s]?\b",
    r"\bdata\s+management\s+platform\b",
    r"\bdata\s+sync(hroniz)?\b",
    r"\blab(oratory)?\s+software\b",
    r"\bneurotech\b",
    r"\bdata\s+acquisition\b",
    r"\bresearchers?\s+across\b",
]


def _resolve_domain_and_archetype(idea: str) -> tuple[str, str]:
    """
    Deterministic domain + archetype resolution — no LLM.
    Returns (domain_str, archetype_str).
    """
    from app.services.soft_router import soft_route
    from app.services.product_archetype import resolve_archetype

    routing = soft_route(idea)
    primary_sub = routing.primary or ""

    # Research domain: check both routing signal and idea text patterns
    is_research_sub = primary_sub in _RESEARCH_SUB_IDS
    is_research_text = any(re.search(p, idea, re.I) for p in _RESEARCH_IDEA_PATTERNS)

    if is_research_sub or is_research_text:
        domain = "LIFE_SCIENCES_RESEARCH"
        # Prefer routing sub-id if it's a research type; otherwise default
        if primary_sub in _RESEARCH_SUB_IDS:
            archetype_str = primary_sub
        else:
            archetype_str = "research_infrastructure_saas"
    else:
        domain = "LIFE_SCIENCES_CLINICAL"
        arch = resolve_archetype(primary_sub)
        archetype_str = arch.value

    return domain, archetype_str


# ── LLM extraction ────────────────────────────────────────────────────────────

_CLASSIFY_PROMPT = """\
You are a product intake classifier for a health innovation intelligence tool.
Your task: extract structured metadata from a product description.

PRODUCT DESCRIPTION:
{idea}

Return ONLY a JSON object with these fields (no other text):
{{
  "product_name": "<short proper name of the product, e.g. 'Hublink' or 'CardioTrack AI'>",
  "one_line": "<one positive sentence: what it does and for whom — never a negation>",
  "trl": <integer 1-9, Technology Readiness Level>,
  "ambiguities": ["<question 1 the description leaves unanswered>", "<question 2>"]
}}

Rules:
- product_name: if a name is stated, use it exactly; otherwise infer a short 1-2 word name
- one_line: start with what the product does (verb phrase), end with the primary buyer
- trl: 1=concept only, 3=proof-of-concept, 5=prototype validated, 7=pilot deployed, 9=commercial
- ambiguities: 2-4 questions that matter for market sizing or go-to-market (buyer, price, competition, regulatory)
"""


def _llm_extract(idea: str) -> dict:
    """Run a Haiku call to extract product_name, one_line, trl, ambiguities."""
    try:
        import anthropic
        from app.core.config import settings

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": _CLASSIFY_PROMPT.format(idea=idea[:1500])}],
        )
        text = (msg.content[0].text if msg.content else "{}").strip()
        # Strip markdown fences if present
        text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.M)
        text = re.sub(r'\s*```$', '', text, flags=re.M)
        return json.loads(text)
    except Exception as exc:
        logger.warning("product_classifier: LLM extraction failed: %s", exc)
        return {}


def _extract_product_name_heuristic(idea: str) -> str:
    """Fallback: pull quoted name or first capitalized phrase."""
    # Look for "X is a ..." pattern
    m = re.match(r'^([A-Z][A-Za-z0-9\s\-]{1,25})\s+is\s+', idea.strip())
    if m:
        candidate = m.group(1).strip()
        if len(candidate.split()) <= 4:
            return candidate
    # Look for quoted product name
    m2 = re.search(r'"([A-Z][A-Za-z0-9\s\-]{1,25})"', idea)
    if m2:
        return m2.group(1).strip()
    return "Your Product"


# ── Public API ────────────────────────────────────────────────────────────────

def classify_product(idea: str) -> Classification:
    """
    Classify a product idea into a Classification object.
    Domain + archetype are derived deterministically; LLM is used only for
    display fields (product_name, one_line, trl, ambiguities).
    """
    domain, archetype_str = _resolve_domain_and_archetype(idea)

    # Compute routing confidence for Classification.confidence
    try:
        from app.services.soft_router import soft_route
        routing = soft_route(idea)
        confidence = round(routing.confidence, 3)
    except Exception:
        confidence = 0.5

    # LLM extraction for display fields
    extracted = _llm_extract(idea)

    product_name = (
        extracted.get("product_name") or _extract_product_name_heuristic(idea)
    ).strip()

    one_line = (
        extracted.get("one_line") or f"A {archetype_str.replace('_', ' ')} built for this market."
    ).strip()

    trl_raw = extracted.get("trl", 3)
    try:
        trl = max(1, min(9, int(trl_raw)))
    except (TypeError, ValueError):
        trl = 3

    ambiguities = extracted.get("ambiguities") or []
    if not isinstance(ambiguities, list):
        ambiguities = []
    ambiguities = [str(a) for a in ambiguities[:4]]

    cls = Classification(
        product_name=product_name,
        one_line=one_line,
        domain=domain,
        archetype=archetype_str,
        trl=trl,
        confidence=confidence,
        ambiguities=ambiguities,
    )
    logger.info(
        "classify_product: name=%r domain=%s archetype=%s trl=%d confidence=%.2f",
        cls.product_name, cls.domain, cls.archetype, cls.trl, cls.confidence,
    )
    return cls


# ── Question banks (conditioned on archetype) ─────────────────────────────────
#
# Each IntakeQuestion binds to a model field path.
# Accepted field paths (canonical):
#   buyer.persona, buyer.institution_type, buyer.budget_source
#   price.observed_band, price.grant_cycle_usd, price.deal_structure
#   seg.gate.long_duration_rate, seg.primary_use_case
#   comp.status_quo, comp.nearest_named_competitor
#   dev.evidence_stage, dev.clinical_validation_done
#   reg.intended_use_jurisdiction, reg.exempt_basis
#   ip.protection_type, ip.bayh_dole_applicable
#
# Rule 8 (Addendum): engine_estimate on price-band questions must be derived
# from generic comparables in app/market/priors/ — never from operator-specific
# primary research.  The helper below reads the priors at module load time.

def _lsr_price_band_estimate() -> str:
    """Return a priors-derived price estimate string for life-sciences research tools.

    Reads app/market/priors/life_sciences_research.py — numbers come from
    Carnegie/HERD/lab-software comparables, not any specific operator's data.
    """
    try:
        from app.market.priors.life_sciences_research import PRIORS
        tiers = PRIORS["price_tiers"]
        acad = int(tiers["academic"]["annual_usd"] / 1_000)
        core = int(tiers["core_facility"]["annual_usd"] / 1_000)
        site = int(tiers["site_license"]["annual_usd"] / 1_000)
        return (
            f"Engine estimate (lab-software comparables): "
            f"~${acad}k/yr academic lab · ~${core}k/yr core facility · ~${site}k/yr site license. "
            "Override with observed customer spend if available."
        )
    except Exception:
        return "Engine estimate: see market/priors/life_sciences_research.py for comparable price tiers."


_RESEARCH_QUESTIONS: list[IntakeQuestion] = [
    IntakeQuestion(
        id="rq_buyer_persona",
        text="Who is the primary purchaser and what drives their buying decision?",
        binds_to="buyer.persona",
        why_asked="Buyer persona (PI vs core facility vs IT) determines deal structure and price ceiling.",
        input_type="single",
        options=[
            "Individual PI with NIH R01/R21 funding — purchases from lab supplies budget",
            "Core facility director — institutional procurement, shared-use model",
            "Research IT / university admin — site-license or enterprise contract",
            "Industry R&D lab (pharma/biotech) — vendor qualification required",
        ],
        default=None,
        impact_rank=1,
    ),
    IntakeQuestion(
        id="rq_price_band",
        text="What is the expected total cost per lab or per grant cycle?",
        binds_to="price.observed_band",
        why_asked="Grant-cycle price band sets the TAM ceiling and informs SAM gating.",
        input_type="single",
        options=[
            "Under $5k (consumable / low-cost accessory)",
            "$5k–$20k (mid-tier equipment or annual software license)",
            "$20k–$50k (core infrastructure or multi-year license)",
            "Over $50k (capital equipment or enterprise contract)",
        ],
        default=None,
        impact_rank=2,
        engine_estimate=_lsr_price_band_estimate(),
    ),
    IntakeQuestion(
        id="rq_status_quo",
        text="What does the lab currently do instead of using your product?",
        binds_to="comp.status_quo",
        why_asked="The incumbent (manual workflow, open-source tool, or competitor) anchors the competitive moat score.",
        input_type="single",
        options=[
            "Manual process by grad students or lab staff (no software/hardware)",
            "DIY scripts or home-built hardware",
            "Open-source alternative (e.g. Bonsai, Spike2, custom Python)",
            "Commercial incumbent (name it in the detail box below)",
        ],
        default=None,
        impact_rank=3,
    ),
    IntakeQuestion(
        id="rq_experiment_type",
        text="What type of experiment does this serve?",
        binds_to="seg.primary_use_case",
        why_asked="Experiment type (short acute vs long-duration chronic) gates which lab segment is addressable.",
        input_type="single",
        options=[
            "Short acute recordings (< 4 hours, researcher present)",
            "Long-duration unattended experiments (days to weeks)",
            "High-throughput batch processing of stored data",
            "Real-time analysis or closed-loop feedback",
        ],
        default=None,
        impact_rank=4,
    ),
    IntakeQuestion(
        id="rq_regulatory_gate",
        text="Does the product ever inform a clinical decision about an identified patient?",
        binds_to="reg.intended_use_jurisdiction",
        why_asked="A 'yes' triggers FDA jurisdiction even for research-labeled hardware — changes §3 entirely.",
        input_type="single",
        options=[
            "No — purely research use, never touches a patient care decision",
            "No — but data is sometimes retrospectively linked to patient records (IRB covered)",
            "Unclear — the device could be used both ways and we need regulatory counsel",
            "Yes — there is a clinical intended use component",
        ],
        default="No — purely research use, never touches a patient care decision",
        impact_rank=5,
    ),
    IntakeQuestion(
        id="rq_grant_funding",
        text="Is the lab's purchase expected to be funded by a specific NIH mechanism?",
        binds_to="buyer.budget_source",
        why_asked="Grant mechanism (R01 vs S10 equipment grant vs SBIR) determines decision timeline and price elasticity.",
        input_type="single",
        options=[
            "R01/R21 lab supplies budget (~$50k–$200k/yr indirect)",
            "S10 shared instrumentation grant (equipment ≥ $50k, multi-PI)",
            "SBIR/STTR direct commercialisation grant",
            "Institutional/department discretionary budget (no specific grant)",
        ],
        default=None,
        impact_rank=6,
    ),
]

_DRUG_QUESTIONS: list[IntakeQuestion] = [
    IntakeQuestion(
        id="dq_eligible_population",
        text="Which specific patient subset does this target?",
        binds_to="seg.gate.eligible_population",
        why_asked="Eligible subpopulation size is the primary TAM input — must be more specific than disease prevalence.",
        input_type="single",
        options=[
            "All patients with the diagnosed condition (broad indication)",
            "Biomarker-selected subpopulation (genomic, proteomic, or other marker)",
            "Patients who failed at least one prior therapy (salvage population)",
            "Pediatric or rare subtype with distinct unmet need",
        ],
        default=None,
        impact_rank=1,
    ),
    IntakeQuestion(
        id="dq_line_of_therapy",
        text="Where does this fit in the treatment pathway?",
        binds_to="seg.gate.line_of_therapy",
        why_asked="Line of therapy determines addressable patient fraction and time-to-peak-sales.",
        input_type="single",
        options=[
            "First-line (replaces or adds to current standard of care)",
            "Second-line salvage (used after first-line failure)",
            "Adjunct / combination with an existing therapy",
            "Prophylactic / prevention before disease onset",
        ],
        default=None,
        impact_rank=2,
    ),
    IntakeQuestion(
        id="dq_mechanism_novelty",
        text="What is genuinely different about the mechanism vs approved alternatives?",
        binds_to="dev.mechanism_novelty",
        why_asked="Mechanism novelty drives moat score and informs whether QIDP/Breakthrough designation is realistic.",
        input_type="single",
        options=[
            "Novel target or first-in-class mechanism (no approved drug in this class)",
            "Same target, improved selectivity / fewer off-target effects",
            "Different route of administration (e.g. oral vs IV, inhaled vs systemic)",
            "Activity against resistant strains or refractory populations where approved drugs fail",
        ],
        default=None,
        impact_rank=3,
    ),
    IntakeQuestion(
        id="dq_evidence_stage",
        text="What data already validates efficacy?",
        binds_to="dev.evidence_stage",
        why_asked="Evidence stage determines PTRS probability and expected trial timeline.",
        input_type="single",
        options=[
            "In vitro only (MIC/IC50, cell-based assay)",
            "Animal model data (survival, dose-response)",
            "Phase 1 safety data in humans",
            "Phase 2 efficacy signal in target indication",
        ],
        default=None,
        impact_rank=4,
    ),
    IntakeQuestion(
        id="dq_buyer",
        text="Who signs the purchase decision and what is their price sensitivity?",
        binds_to="buyer.persona",
        why_asked="Buyer (hospital P&T vs payer formulary vs patient OOP) drives pricing strategy and peak sales ceiling.",
        input_type="single",
        options=[
            "Hospital P&T committee (inpatient, formulary placement)",
            "Payer / PBM (outpatient, step-therapy required)",
            "Specialty pharmacy (rare disease / patient assistance program)",
            "Patient out-of-pocket (DTC or OTC)",
        ],
        default=None,
        impact_rank=5,
    ),
    IntakeQuestion(
        id="dq_competitive_edge",
        text="vs the closest approved therapy, what is the measurable clinical advantage?",
        binds_to="comp.nearest_named_competitor",
        why_asked="Competitive differentiation determines pricing premium and formulary placement probability.",
        input_type="single",
        options=[
            "Superior efficacy endpoint (higher response rate, longer PFS/OS, or deeper response)",
            "Better tolerability / safety profile (fewer grade 3+ AEs or lower discontinuation rate)",
            "Significant dosing convenience advantage (once-daily oral vs IV, shorter infusion)",
            "Efficacy in a resistant or refractory population where the approved drug fails",
        ],
        default=None,
        impact_rank=6,
    ),
]

_DEVICE_QUESTIONS: list[IntakeQuestion] = [
    IntakeQuestion(
        id="devq_intended_use",
        text="Where in the care pathway does it act and is it assistive or autonomous?",
        binds_to="seg.primary_use_case",
        why_asked="Intended use determines predicate device and regulatory pathway.",
        input_type="text",
        options=None,
        default=None,
        impact_rank=1,
    ),
    IntakeQuestion(
        id="devq_target_sites",
        text="Which facility type and care setting is the unit of sale?",
        binds_to="seg.gate.facility_type",
        why_asked="Facility type (ED vs radiology vs outpatient) sets the addressable site count.",
        input_type="single",
        options=[
            "Hospital ED / emergency setting",
            "Hospital radiology / PACS environment",
            "Outpatient clinic or ambulatory surgery center",
            "ICU / critical care",
        ],
        default=None,
        impact_rank=2,
    ),
    IntakeQuestion(
        id="devq_validation",
        text="What validation evidence exists (sensitivity/specificity, AUC, site count)?",
        binds_to="dev.evidence_stage",
        why_asked="Validation data quality drives confidence in regulatory timeline estimates.",
        input_type="text",
        options=None,
        default=None,
        impact_rank=3,
    ),
    IntakeQuestion(
        id="devq_buyer",
        text="Who signs the purchase decision and how is it funded?",
        binds_to="buyer.persona",
        why_asked="Hospital IT vs service-line capital vs operating budget determines sales cycle length.",
        input_type="single",
        options=[
            "Hospital IT / CIO (enterprise software contract)",
            "Service-line medical director (capital equipment budget)",
            "Radiology / department head (service-line operating budget)",
            "Value-based care / ACO (shared-savings ROI model)",
        ],
        default=None,
        impact_rank=4,
    ),
    IntakeQuestion(
        id="devq_competitive_edge",
        text="vs the nearest cleared competitor, what is the measurable performance edge?",
        binds_to="comp.nearest_named_competitor",
        why_asked="Performance delta vs named cleared competitor determines moat score and pricing premium.",
        input_type="text",
        options=None,
        default=None,
        impact_rank=5,
    ),
    IntakeQuestion(
        id="devq_price_band",
        text="What is the expected per-facility contract value (annual)?",
        binds_to="price.observed_band",
        why_asked="Per-facility contract value × addressable site count = SAM.",
        input_type="single",
        options=[
            "Under $20k / year per facility",
            "$20k–$100k / year per facility",
            "$100k–$500k / year per facility (enterprise contract)",
            "Capital sale > $100k + disposables",
        ],
        default=None,
        impact_rank=6,
    ),
]

# Default fallback for archetypes not explicitly handled
_GENERIC_QUESTIONS: list[IntakeQuestion] = [
    IntakeQuestion(
        id="gq_target_population",
        text="What specific population or use case does this primarily address?",
        binds_to="seg.primary_use_case",
        why_asked="Target population anchors the TAM calculation.",
        input_type="text",
        options=None,
        default=None,
        impact_rank=1,
    ),
    IntakeQuestion(
        id="gq_status_quo",
        text="What is the current status quo, and what gap do you address?",
        binds_to="comp.status_quo",
        why_asked="Status quo anchors the competitive moat score.",
        input_type="text",
        options=None,
        default=None,
        impact_rank=2,
    ),
    IntakeQuestion(
        id="gq_buyer",
        text="Who is the primary purchase decision-maker?",
        binds_to="buyer.persona",
        why_asked="Buyer persona determines deal structure and pricing ceiling.",
        input_type="text",
        options=None,
        default=None,
        impact_rank=3,
    ),
    IntakeQuestion(
        id="gq_price",
        text="What is the expected price range per unit/license/year?",
        binds_to="price.observed_band",
        why_asked="Price band × addressable units = SAM.",
        input_type="text",
        options=None,
        default=None,
        impact_rank=4,
    ),
    IntakeQuestion(
        id="gq_evidence",
        text="What evidence already exists to validate the core technology?",
        binds_to="dev.evidence_stage",
        why_asked="Evidence stage determines PTRS probability and development timeline.",
        input_type="text",
        options=None,
        default=None,
        impact_rank=5,
    ),
    IntakeQuestion(
        id="gq_competition",
        text="Who is the nearest named competitor and what is your differentiated edge?",
        binds_to="comp.nearest_named_competitor",
        why_asked="Named competitor + measurable delta determines moat score.",
        input_type="text",
        options=None,
        default=None,
        impact_rank=6,
    ),
]

_RESEARCH_ARCHETYPES = frozenset({
    "research_tool_non_clinical",
    "research_infrastructure_saas",
    "research_saas",
})

_DEVICE_ARCHETYPES = frozenset({
    "device_class_ii",
    "device_class_iii",
    "samd_clinical",
    "diagnostic_ivd",
})

_DRUG_ARCHETYPES = frozenset({
    "therapeutic_small_molecule",
    "therapeutic_biologic",
    "gene_cell_therapy",
    "vaccine",
})


def get_conditioned_questions(cls: Classification) -> list[IntakeQuestion]:
    """
    Return IntakeQuestion[] conditioned on the Classification.
    Every returned question has a non-empty `binds_to` field.
    """
    arch_l = (cls.archetype or "").lower()
    domain_l = (cls.domain or "").upper()

    if arch_l in _RESEARCH_ARCHETYPES or domain_l == "LIFE_SCIENCES_RESEARCH":
        return list(_RESEARCH_QUESTIONS)
    elif arch_l in _DEVICE_ARCHETYPES:
        return list(_DEVICE_QUESTIONS)
    elif arch_l in _DRUG_ARCHETYPES:
        return list(_DRUG_QUESTIONS)
    else:
        return list(_GENERIC_QUESTIONS)


def questions_to_legacy_format(questions: list[IntakeQuestion]) -> list[dict]:
    """
    Convert IntakeQuestion[] to the legacy {question, field, options, hint} format
    so the existing frontend rendering code works without changes.

    engine_estimate is included when present — frontend can display it as a
    greyed-out hint below the input so PIs can see the engine's default before
    overriding it with observed data (Rule 8).
    """
    out = []
    for q in questions:
        entry: dict = {
            "question":       q.text,
            "field":          q.id,
            "options":        q.options or [],
            "hint":           q.why_asked,
            "binds_to":       q.binds_to,
            "impact_rank":    q.impact_rank,
            "engine_estimate": q.engine_estimate,
        }
        out.append(entry)
    return out
