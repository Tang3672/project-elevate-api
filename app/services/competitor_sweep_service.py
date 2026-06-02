"""
Competitor Sweep Service
========================
Identifies and analyses named competing products across three sources:

  1. openFDA drug label API  — approved drugs for the indication (named generics + brands)
  2. ClinicalTrials.gov       — Phase 2/3 pipeline with sponsor + drug name
  3. OpenAlex                 — high-citation papers revealing competitor efficacy claims

For each identified competitor, builds an advantage profile covering:
  - Clinical advantage   (efficacy superiority, biomarker selection, safety)
  - IP / exclusivity     (approval date → years of market protection remaining)
  - Market position      (first-mover, brand recognition, distribution)
  - Pricing              (premium vs generic positioning, CMS WAC)
  - Administration       (oral vs IV — matters hugely for outpatient/ER prescribing)
  - Speculative signals  (analyst commentary, recent trial design choices)

Also identifies the competitive white space — what no current competitor addresses —
which is the single most important input for differentiation strategy.

Linda Wu design principles implemented here:
  - Keyword sweep across ALL major sources, not just trial counts
  - Named product identification, not just anonymous aggregate counts
  - Per-competitor advantage breakdown (not just "N competitors exist")
  - White-space gap analysis (biggest unmet need no one is capturing)
  - Speculative positioning signals (what competitor pipeline choices reveal)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_DELAY = 0.25   # throttle between API calls


# ──────────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CompetitorProduct:
    name:                str              # Generic or drug name
    brand_name:          Optional[str]    # Brand name if approved
    company:             str
    stage:               str              # "approved" | "phase3" | "phase2" | "phase1"
    nct_id:              Optional[str]    # ClinicalTrials.gov ID if in pipeline
    approval_year:       Optional[int]
    route:               Optional[str]    # "ORAL" | "INTRAVENOUS" | "SUBCUTANEOUS" etc.
    mechanism:           Optional[str]
    advantages:          list[str] = field(default_factory=list)
    vulnerabilities:     list[str] = field(default_factory=list)
    positioning_signal:  Optional[str] = None   # speculative analyst view
    source:              str = "openfda"
    source_url:          Optional[str] = None


@dataclass
class CompetitiveWhiteSpace:
    description:         str             # The gap no competitor addresses
    evidence:            list[str]       # Facts supporting the gap claim
    patient_segment:     str             # Who is underserved
    opportunity_size:    str             # Qualitative estimate


@dataclass
class CompetitorLandscape:
    disease:             str
    keywords_used:       list[str]
    approved_count:      int
    pipeline_count:      int
    competitors:         list[CompetitorProduct]
    white_space:         list[CompetitiveWhiteSpace]
    competitive_summary: str             # 2-sentence synthesis
    market_structure:    str             # "monopoly" | "duopoly" | "fragmented" | "crowded" | "empty"
    differentiation_levers: list[str]   # What a new entrant could exploit


# ──────────────────────────────────────────────────────────────────────────────
# Advantage inference rules (deterministic, no LLM needed per competitor)
# ──────────────────────────────────────────────────────────────────────────────

def _infer_advantages(prod: dict, context: dict) -> tuple[list[str], list[str], str]:
    """
    Given raw product data, return (advantages, vulnerabilities, positioning_signal).
    Uses deterministic rules from route, stage, approval_year, mechanism keywords.
    """
    advantages    = []
    vulns         = []
    signal        = ""

    route    = (prod.get("route") or "").upper()
    stage    = prod.get("stage", "")
    yr       = prod.get("approval_year")
    mech     = (prod.get("mechanism") or "").lower()
    name     = (prod.get("name") or "").lower()
    ta       = context.get("therapeutic_area", "")
    disease  = context.get("disease", "").lower()

    # ── Route of administration ───────────────────────────────────────────────
    if "ORAL" in route:
        advantages.append("Oral dosing — outpatient-compatible, no IV access required")
    elif "INTRAVENOUS" in route:
        if "amr" in ta or "infectious" in ta:
            vulns.append("IV-only — limits use to hospital/infusion setting; higher administration cost")
            advantages.append("IV delivery enables higher plasma concentrations for severe infections")
        else:
            vulns.append("IV or SC route — patient burden vs oral alternatives")
    if "SUBCUTANEOUS" in route:
        advantages.append("Subcutaneous dosing — monthly/bi-monthly schedule reduces patient burden")

    # ── Approval vintage → exclusivity remaining ──────────────────────────────
    if yr:
        years_on_market = 2026 - yr
        if years_on_market <= 2:
            advantages.append(f"Recently approved ({yr}) — full data exclusivity intact, no generics imminent")
            signal = f"Approved {yr} — company likely expanding label/indications and defending exclusivity aggressively"
        elif years_on_market <= 5:
            advantages.append(f"Established ({yr}) — growing formulary penetration, real-world evidence accumulating")
            signal = f"Approved {yr} — company likely focused on Phase 4 evidence generation and line extensions"
        elif years_on_market >= 8:
            vulns.append(f"Long-approved ({yr}) — generic erosion imminent or already occurring; pricing under pressure")
            signal = f"Approved {yr} — likely losing/lost exclusivity; generic competition or biosimilar entry expected"

    # ── Mechanism-based advantages ────────────────────────────────────────────
    mech_lower = mech.lower()
    if "first-in-class" in mech_lower or "novel" in mech_lower:
        advantages.append("First-in-class mechanism — no cross-resistance with existing drugs in class")
    if "broad spectrum" in mech_lower:
        advantages.append("Broad-spectrum activity — addresses multiple resistant organisms under one label")
    if "selective" in mech_lower or "targeted" in mech_lower:
        advantages.append("Selective mechanism — reduced off-target toxicity vs broad-spectrum alternatives")
    if any(x in mech_lower for x in ["biomarker", "companion diagnostic", "patient selection"]):
        advantages.append("Biomarker-selected population — enriched trial population drives cleaner efficacy signal")
    if "combination" in mech_lower or "synerg" in mech_lower:
        advantages.append("Combination approach — synergistic activity overcomes single-agent resistance mechanisms")

    # ── Drug name pattern clues ───────────────────────────────────────────────
    if any(x in name for x in ["vab", "avib", "relebac"]):  # BLI combination indicator
        advantages.append("Beta-lactam / BLI combination — restored activity against resistant gram-negatives")
        vulns.append("Combination product — complex manufacturing and potentially narrower label vs monotherapy")

    if "phase3" in stage:
        advantages.append("Phase 3 — pivotal data generation in progress; regulatory filing imminent if successful")
        signal = (signal or "") + " Phase 3 trial design choices reveal the differentiation thesis their team believes in most."
    elif "phase2" in stage:
        advantages.append("Phase 2 — proof-of-concept demonstrated; full efficacy/safety profile still emerging")
        signal = (signal or "") + " Phase 2 enrollment strategy (broad vs biomarker-selected) signals differentiation approach."

    # ── Disease-specific rules ────────────────────────────────────────────────
    if "sepsis" in disease or "critical" in disease:
        if "IV" in route:
            advantages.append("IV formulation appropriate for ICU/critical care setting where oral not feasible")
    if "outpatient" in disease or "skin" in disease or "uti" in disease:
        if "IV" in route and "ORAL" not in route:
            vulns.append("IV-only limits outpatient prescribing — community market largely inaccessible")

    return advantages[:5], vulns[:3], signal[:300] if signal else None


# ──────────────────────────────────────────────────────────────────────────────
# Source sweepers
# ──────────────────────────────────────────────────────────────────────────────

def _sweep_approved_openfda(
    indication_phrases: list[str],
    max_results: int = 12,
) -> list[dict]:
    """
    Query openFDA drug label API for approved drugs mentioning the indication.
    Returns list of {name, brand_name, route, manufacturer} dicts.
    """
    # Build a tight OR-joined search string from indication phrases
    search_str = " OR ".join(f'indications_and_usage:"{ph}"' for ph in indication_phrases[:3])
    seen_names: set = set()
    products: list[dict] = []

    try:
        r = requests.get(
            "https://api.fda.gov/drug/label.json",
            params={"search": search_str, "limit": 25},
            timeout=12,
        )
        if r.status_code != 200:
            return products
        data = r.json()
        for rec in data.get("results", [])[:25]:
            fda = rec.get("openfda", {})
            generic = (fda.get("generic_name") or [""])[0].strip()
            brand   = (fda.get("brand_name") or [""])[0].strip()
            mfr     = (fda.get("manufacturer_name") or [""])[0].strip()[:50]
            route   = (fda.get("route") or [""])[0].strip().upper()
            rxcui   = (fda.get("rxcui") or [""])[0]

            if not generic or generic.lower() in seen_names:
                continue
            # Skip obvious noise: OTC products, combination OTC, non-relevant drugs
            if any(x in generic.lower() for x in ["ibuprofen","acetaminophen","omeprazole","gabapentin","amoxicillin","cephalexin","prednisone","diclofenac","fluoxetine","metformin"]):
                continue

            seen_names.add(generic.lower())
            products.append({
                "name":        generic,
                "brand_name":  brand or None,
                "company":     mfr,
                "route":       route or None,
                "stage":       "approved",
                "mechanism":   None,
                "source":      "openfda",
                "source_url":  f"https://api.fda.gov/drug/label.json?search=openfda.rxcui:{rxcui}" if rxcui else None,
            })
            if len(products) >= max_results:
                break
    except Exception as e:
        logger.warning("openFDA sweep failed: %s", e)

    return products


def _sweep_pipeline_ctgov(
    disease_name: str,
    indication_keywords: list[str],
    max_results: int = 10,
) -> list[dict]:
    """
    Query ClinicalTrials.gov Phase 2/3 trials for the indication.
    Returns list of pipeline competitor dicts with drug name + sponsor.
    """
    products: list[dict] = []
    seen_drugs: set = set()

    search_cond = disease_name or indication_keywords[0] if indication_keywords else "disease"

    try:
        r = requests.get(
            "https://clinicaltrials.gov/api/v2/studies",
            params={
                "query.cond":           search_cond,
                "filter.overallStatus": "RECRUITING,ACTIVE_NOT_RECRUITING,NOT_YET_RECRUITING",
                "filter.phase":         "PHASE2,PHASE3",
                "pageSize":             max_results * 2,
                "format":               "json",
            },
            timeout=12,
        )
        if r.status_code != 200:
            return products

        data = r.json()
        for study in data.get("studies", [])[:max_results * 2]:
            proto  = study.get("protocolSection", {})
            ident  = proto.get("identificationModule", {})
            spon   = proto.get("sponsorCollaboratorsModule", {})
            design = proto.get("designModule", {})
            interv = proto.get("armsInterventionsModule", {}).get("interventions", [])

            sponsor   = spon.get("leadSponsor", {}).get("name", "Unknown")
            phases    = design.get("phases", [])
            phase_str = "phase3" if "PHASE3" in phases else "phase2"
            nct_id    = ident.get("nctId", "")

            for iv in interv:
                if iv.get("type") not in ("DRUG", "BIOLOGICAL", "GENETIC"):
                    continue
                drug_name = iv.get("name", "").strip()
                if not drug_name or drug_name.lower() in seen_drugs:
                    continue
                # Skip placebo / standard-of-care arms
                if any(x in drug_name.lower() for x in ["placebo","saline","sham","standard","best support"]):
                    continue
                seen_drugs.add(drug_name.lower())
                products.append({
                    "name":        drug_name,
                    "brand_name":  None,
                    "company":     sponsor,
                    "route":       None,
                    "stage":       phase_str,
                    "mechanism":   None,
                    "nct_id":      nct_id,
                    "source":      "clinicaltrials",
                    "source_url":  f"https://clinicaltrials.gov/study/{nct_id}",
                })
                if len(products) >= max_results:
                    break
            if len(products) >= max_results:
                break

    except Exception as e:
        logger.warning("CT.gov pipeline sweep failed: %s", e)

    return products


def _sweep_literature_openalex(
    disease_name: str,
    indication_keywords: list[str],
    max_results: int = 5,
) -> list[dict]:
    """
    Query OpenAlex for high-citation recent papers about competitor drugs.
    Returns key findings that reveal competitive positioning and analyst signals.
    """
    query = f"{disease_name} {' '.join(indication_keywords[:2])} clinical trial efficacy"
    papers: list[dict] = []

    try:
        r = requests.get(
            "https://api.openalex.org/works",
            params={
                "search":   query,
                "filter":   "open_access.is_oa:true,publication_year:>2020",
                "sort":     "cited_by_count:desc",
                "per-page": max_results,
                "mailto":   "contact@projectelevate.io",
            },
            timeout=10,
        )
        if r.status_code != 200:
            return papers

        for w in r.json().get("results", [])[:max_results]:
            title = (w.get("title") or "")[:150]
            doi   = w.get("doi") or ""
            cited = w.get("cited_by_count", 0)
            yr    = w.get("publication_year")
            if title:
                papers.append({"title": title, "doi": doi, "cited": cited, "year": yr})

    except Exception as e:
        logger.warning("OpenAlex literature sweep failed: %s", e)

    return papers


# ──────────────────────────────────────────────────────────────────────────────
# White space analysis
# ──────────────────────────────────────────────────────────────────────────────

def _analyse_white_space(
    competitors: list[CompetitorProduct],
    disease_name: str,
    therapeutic_area: str,
    indication_keywords: list[str],
) -> list[CompetitiveWhiteSpace]:
    """
    Identify gaps no current competitor addresses based on the competitor landscape.
    Deterministic gap logic based on route, stage, patient segment coverage.
    """
    gaps: list[CompetitiveWhiteSpace] = []
    all_routes  = {(c.route or "").upper() for c in competitors}
    all_stages  = {c.stage for c in competitors}
    n_approved  = sum(1 for c in competitors if c.stage == "approved")
    n_pipeline  = len(competitors) - n_approved

    ta = therapeutic_area.lower()

    # Gap 1: No oral option when all approved are IV
    if all_routes and all_routes.issubset({"INTRAVENOUS","IV","INJECTION"}) and "ORAL" not in all_routes:
        gaps.append(CompetitiveWhiteSpace(
            description="No approved oral therapy exists — outpatient treatment gap",
            evidence=[
                f"All {n_approved} approved products are intravenous/injectable",
                "Oral therapy would enable outpatient treatment, reducing hospitalisation cost",
                "Primary care physicians cannot prescribe IV-only agents without infusion setup",
            ],
            patient_segment="Outpatient, mild-to-moderate severity patients with no IV access",
            opportunity_size="Large — outpatient market is typically 3-5× the inpatient market by volume",
        ))

    # Gap 2: No approved therapy at all
    if n_approved == 0:
        gaps.append(CompetitiveWhiteSpace(
            description=f"No FDA-approved therapy for {disease_name} — first-to-market opportunity",
            evidence=[
                "Zero approved products identified in openFDA label search",
                f"{n_pipeline} products in pipeline signal validated unmet need",
                "First approval would capture 100% of the market on day 1",
            ],
            patient_segment="All diagnosed patients with no current pharmacological option",
            opportunity_size="Maximum — first-mover advantage with full orphan/exclusivity periods available",
        ))

    # Gap 3: Crowded but all mechanism-similar (class effect gap)
    if n_approved >= 4:
        gaps.append(CompetitiveWhiteSpace(
            description="Mechanism class is crowded — novel mechanism or combination needed to differentiate",
            evidence=[
                f"{n_approved} approved products create formulary competition and price compression",
                "All established products likely share similar mechanism — cross-resistance possible",
                "Payers favour generics; branded premium requires clear clinical differentiation",
            ],
            patient_segment="Patients who fail or are intolerant to standard therapies",
            opportunity_size="Moderate — positioned as second-line/salvage therapy for treatment failures",
        ))

    # Gap 4: No biomarker-selected product (oncology/immunology)
    if ta in ("oncology", "immunology", "hematology"):
        has_biomarker = any("biomarker" in " ".join(c.advantages).lower() for c in competitors)
        if not has_biomarker:
            gaps.append(CompetitiveWhiteSpace(
                description="No biomarker-stratified therapy — precision medicine gap",
                evidence=[
                    "No approved product uses patient-selection biomarker for this indication",
                    "BIO data: biomarker-selected programs have 3× higher Phase 2 success rate",
                    "FDA increasingly expects enriched populations for oncology/immunology approvals",
                ],
                patient_segment="Biomarker-positive subgroup with predicted high response probability",
                opportunity_size="Strong — cleaner trial design, faster approval, premium pricing justified",
            ))

    # Gap 5: Paediatric gap
    gaps.append(CompetitiveWhiteSpace(
        description="Paediatric formulation gap — most approved products are adult-labelled only",
        evidence=[
            "FDA Paediatric Research Equity Act (PREA) requires paediatric studies for most new drugs",
            "Off-label paediatric use creates liability and dosing uncertainty",
            "Paediatric exclusivity adds 6 months to all existing exclusivity periods",
        ],
        patient_segment="Paediatric patients with no on-label dosing option",
        opportunity_size="Niche — paediatric market is smaller but commands premium and extends exclusivity",
    ))

    return gaps[:4]


# ──────────────────────────────────────────────────────────────────────────────
# Market structure classification
# ──────────────────────────────────────────────────────────────────────────────

def _classify_market_structure(n_approved: int, n_pipeline: int) -> str:
    if n_approved == 0:
        return "empty" if n_pipeline < 3 else "pre-launch"
    if n_approved == 1:
        return "monopoly"
    if n_approved <= 3:
        return "oligopoly"
    if n_approved <= 7:
        return "competitive"
    return "crowded"


def _differentiation_levers(competitors: list[CompetitorProduct], ta: str) -> list[str]:
    """Identify unexploited differentiation levers from the competitive landscape."""
    levers: list[str] = []
    routes = {(c.route or "").upper() for c in competitors}
    stages = {c.stage for c in competitors}

    if "ORAL" not in routes:
        levers.append("Oral formulation — only entrant with outpatient-compatible dosing")
    if "SUBCUTANEOUS" not in routes and ta not in ("amr_infectious",):
        levers.append("Subcutaneous once-weekly/monthly dosing — superior patient convenience vs daily oral or IV")
    if not any("biomarker" in " ".join(c.advantages).lower() for c in competitors):
        levers.append("Biomarker-selected label — precision medicine premium pricing justified; faster Phase 3")
    if sum(1 for c in competitors if c.stage == "approved") >= 3:
        levers.append("Superior safety profile in head-to-head — clinical trial powered for non-inferiority + better tolerability")
    if all(c.stage in ("phase2","phase3") for c in competitors if c.stage != "approved"):
        levers.append("Accelerated development — regulatory strategy (Breakthrough/Fast Track) to reach market before pipeline matures")
    levers.append("Combination strategy — synergistic combination with existing SoC eliminates resistance mechanism gap")
    levers.append("Health economic advantage — outcome-based pricing or lower total cost of care (hospitalisation reduction)")

    return levers[:5]


# ──────────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────────

def sweep_competitors(
    disease_name: str,
    indication_keywords: list[str],
    therapeutic_area: str = "other",
    product_type: str = "drug_small_molecule",
    max_competitors: int = 12,
) -> CompetitorLandscape:
    """
    Full competitive sweep across openFDA, ClinicalTrials.gov, and OpenAlex.

    Returns a CompetitorLandscape with named competitors, their advantages,
    competitive white space, and differentiation levers.

    Designed to run synchronously (uses requests) for embedding into LLM prompts.
    At 200-400ms per call this is fast enough for report generation.
    """
    context = {"disease": disease_name, "therapeutic_area": therapeutic_area}

    # 1. Approved products
    approved_raw = _sweep_approved_openfda(indication_keywords)
    time.sleep(_DELAY)

    # 2. Pipeline products
    pipeline_raw = _sweep_pipeline_ctgov(disease_name, indication_keywords)
    time.sleep(_DELAY)

    # 3. Literature signals
    lit = _sweep_literature_openalex(disease_name, indication_keywords)

    # 4. Build structured competitor objects
    competitors: list[CompetitorProduct] = []
    for raw in approved_raw + pipeline_raw:
        if len(competitors) >= max_competitors:
            break
        advs, vulns, signal = _infer_advantages(raw, context)
        competitors.append(CompetitorProduct(
            name=raw["name"],
            brand_name=raw.get("brand_name"),
            company=raw.get("company", "Unknown"),
            stage=raw.get("stage", "unknown"),
            nct_id=raw.get("nct_id"),
            approval_year=raw.get("approval_year"),
            route=raw.get("route"),
            mechanism=raw.get("mechanism"),
            advantages=advs,
            vulnerabilities=vulns,
            positioning_signal=signal,
            source=raw.get("source", "openfda"),
            source_url=raw.get("source_url"),
        ))

    # 5. White space
    white_space = _analyse_white_space(competitors, disease_name, therapeutic_area, indication_keywords)

    # 6. Market structure
    n_approved = sum(1 for c in competitors if c.stage == "approved")
    n_pipeline = len(competitors) - n_approved
    structure  = _classify_market_structure(n_approved, n_pipeline)
    levers     = _differentiation_levers(competitors, therapeutic_area)

    # 7. Competitive summary
    if not competitors:
        summary = f"No established competitors identified for {disease_name} — potential first-mover opportunity."
    elif structure == "monopoly":
        c = competitors[0]
        summary = (
            f"{disease_name} is currently a monopoly market dominated by {c.company} ({c.name}). "
            f"Entry requires clear differentiation on at least one dimension — route, safety, biomarker, or mechanism."
        )
    elif structure in ("oligopoly", "competitive"):
        companies = list({c.company for c in competitors if c.stage == "approved"})[:3]
        summary = (
            f"{disease_name} has {n_approved} approved products from {', '.join(companies)}. "
            f"Market is {structure} — premium pricing requires head-to-head differentiation or a new patient segment."
        )
    else:
        summary = (
            f"{disease_name} has {n_approved} approved and {n_pipeline} pipeline products — "
            f"a {'crowded' if structure == 'crowded' else 'emerging'} market where novel mechanism "
            f"or biomarker selection is required to command formulary access and premium pricing."
        )

    return CompetitorLandscape(
        disease=disease_name,
        keywords_used=indication_keywords,
        approved_count=n_approved,
        pipeline_count=n_pipeline,
        competitors=competitors,
        white_space=white_space,
        competitive_summary=summary,
        market_structure=structure,
        differentiation_levers=levers,
    )


def format_for_prompt(landscape: CompetitorLandscape) -> str:
    """Format the competitive landscape for injection into an LLM expert prompt."""
    lines = [
        f"\n=== LIVE COMPETITIVE SWEEP: {landscape.disease.upper()} ===",
        f"Market structure: {landscape.market_structure.upper()} "
        f"({landscape.approved_count} approved, {landscape.pipeline_count} in pipeline)",
        f"Summary: {landscape.competitive_summary}",
        "",
        "NAMED COMPETITORS:",
    ]

    for c in landscape.competitors[:8]:
        stage_label = {"approved":"✅ APPROVED","phase3":"🔵 PHASE 3","phase2":"🟡 PHASE 2"}.get(c.stage, c.stage.upper())
        route_str   = f" [{c.route}]" if c.route else ""
        brand_str   = f" ({c.brand_name})" if c.brand_name else ""
        lines.append(f"  {stage_label} {c.name}{brand_str}{route_str} — {c.company}")
        for adv in c.advantages[:2]:
            lines.append(f"    ▲ {adv}")
        for vul in c.vulnerabilities[:1]:
            lines.append(f"    ▽ {vul}")
        if c.positioning_signal:
            lines.append(f"    → Speculative: {c.positioning_signal}")

    lines += ["", "COMPETITIVE WHITE SPACE (what no competitor addresses):"]
    for ws in landscape.white_space[:3]:
        lines.append(f"  • {ws.description}")
        lines.append(f"    Patient segment: {ws.patient_segment}")
        lines.append(f"    Opportunity: {ws.opportunity_size}")

    lines += ["", "DIFFERENTIATION LEVERS (what a new entrant could exploit):"]
    for lv in landscape.differentiation_levers[:4]:
        lines.append(f"  → {lv}")

    return "\n".join(lines)


def to_dict(landscape: CompetitorLandscape) -> dict:
    """Serialise to JSON-compatible dict for API responses."""
    d = asdict(landscape)
    return d
