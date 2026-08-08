"""
Typed Strategy library — Spec v4 Part E.

Provides a structured Strategy dataclass with explicit gating fields
(archetypes, domains, buyer_personas) and an apply_template that is
parameterized by the actual product, not free-form prose.

Usage pattern
-------------
from app.services.strategy_model import filter_strategies, render_strategy

strategies = filter_strategies(
    archetype="research_tool_non_clinical",
    domain="LIFE_SCIENCES_RESEARCH",
)
for s in strategies[:4]:
    rendered = render_strategy(s, {"product_name": "Hublink", "buyer_type": "academic PI"})
    ...

Design notes
------------
- The existing strategy_database.py dicts remain unchanged and serve
  clinical archetypes (THERAPEUTIC_* / DEVICE_*).
- For research_tool and research_infrastructure archetypes, this module
  is the source of truth.
- filter_strategies() replaces get_strategies_for_domain() for gated
  archetypes; format_strategies_for_report() is updated to call it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from string import Formatter


@dataclass
class Strategy:
    """A gated, parameterized commercialization strategy.

    Fields
    ------
    id            Unique kebab-case slug; stable across edits.
    headline      One-sentence headline visible to the PI.
    archetypes    Explicit archetype gates (sub_expert_id values).
                  Empty list = applies to all archetypes in the domain.
    domains       Explicit domain gates (ReportDomain values).
                  Empty list = domain-agnostic.
    buyer_personas Buyer types this strategy targets.
    example_company, example_product  The named proof point.
    example_evidence  What they did and what happened (cited, specific).
    source_url    URL for the primary claim citation.
    how_to_apply  Plain-text advice (generic; shown when template
                  rendering context is unavailable).
    apply_template  Parameterized version of how_to_apply; supports
                  {product_name}, {buyer_type}, {company_name},
                  {modality}, {funding_agency} placeholders.
    """
    id:               str
    headline:         str
    archetypes:       list[str]
    domains:          list[str]
    buyer_personas:   list[str]
    example_company:  str
    example_product:  str
    example_evidence: str
    source_url:       str
    how_to_apply:     str
    apply_template:   str = ""
    category:         str = ""


# ── Typed strategy library ────────────────────────────────────────────────────

TYPED_STRATEGY_LIBRARY: list[Strategy] = [

    # ── Research Tool / Non-Clinical ──────────────────────────────────────────

    Strategy(
        id="research-tool-methods-paper-first",
        category="Research Tool Commercialization",
        headline="Publish a peer-reviewed methods paper before commercial launch — it is the highest-ROI marketing spend for academic research tools",
        archetypes=["research_tool_non_clinical"],
        domains=["LIFE_SCIENCES_RESEARCH"],
        buyer_personas=["academic_pi", "core_facility_director"],
        example_company="10x Genomics",
        example_product="Chromium scRNA-seq platform",
        example_evidence=(
            "10x Genomics co-authored the foundational Chromium single-cell RNA-seq workflow "
            "paper (Zheng et al., Science 2017, PMID 28091601) before aggressive commercial "
            "rollout. The citation became the most-cited paper in the field. Academic labs "
            "adopted the platform because it was the standard-of-record in the published "
            "literature — not because of direct sales."
        ),
        source_url="https://pubmed.ncbi.nlm.nih.gov/28091601/",
        how_to_apply=(
            "Prioritize a methods paper with ≥2 academic PI co-authors before any direct "
            "sales motion. Target Nature Methods, HardwareX, or PLOS ONE. Budget 3–6 months; "
            "include the full data pipeline and reproducibility protocol, not just the hardware. "
            "Citation count on the methods paper directly predicts adoption rate."
        ),
        apply_template=(
            "Before any sales motion for {product_name}, co-author a methods paper with ≥2 "
            "academic PI co-authors — the PI's peers are your real sales force once they cite "
            "the paper. Target Nature Methods, HardwareX, or PLOS ONE. Budget 3–6 months and "
            "include the full data pipeline and reproducibility protocol alongside the "
            "{product_name} workflow. Citation count on the methods paper is the leading "
            "indicator of adoption rate in the {buyer_type} market."
        ),
    ),

    Strategy(
        id="research-tool-core-facility-beachhead",
        category="Core Facility Beachhead",
        headline="Win one core facility director and sell to the facility's entire user base — core facilities are the distribution channel with no clinical-sales equivalent",
        archetypes=["research_tool_non_clinical"],
        domains=["LIFE_SCIENCES_RESEARCH"],
        buyer_personas=["core_facility_director", "academic_pi"],
        example_company="Zeiss (Carl Zeiss AG)",
        example_product="LSM 880 Airyscan confocal system",
        example_evidence=(
            "Zeiss targets institutional core facility directors with multi-year service "
            "contracts and structured training programs. One core facility sale (typically "
            "$250k–$2M capital) serves 50–200 individual PI labs and converts each PI into "
            "a trained user and active recommender to peer institutions."
        ),
        source_url="https://abrf.org/core-facilities",
        how_to_apply=(
            "Map the 5–10 core facilities serving your target modality nationally. Offer the "
            "first a founding-partner price (30–40% discount) in exchange for co-authorship "
            "on a methods paper, a cohort training commitment, and a reference call. "
            "This converts a $15k per-lab license into a $100k–$500k facility contract "
            "with 50+ downstream trained users."
        ),
        apply_template=(
            "Map the 5–10 core facilities serving {modality} labs nationally. "
            "Offer the first facility a founding-partner price (30–40% discount) in exchange "
            "for co-authorship on a {product_name} methods paper, a cohort training "
            "commitment, and a reference call. One facility contract ($100k–$500k) delivers "
            "50+ trained PI users who become organic champions at peer institutions."
        ),
    ),

    Strategy(
        id="research-tool-sbir-before-preseed",
        category="SBIR / STTR Non-Dilutive Bridge",
        headline="SBIR Phase I establishes NIH credibility and pays for the first validated prototype — do not raise pre-seed until after a Phase I award",
        archetypes=["research_tool_non_clinical", "research_infrastructure_saas"],
        domains=["LIFE_SCIENCES_RESEARCH"],
        buyer_personas=["academic_pi", "core_facility_director", "institutional_it"],
        example_company="Open Ephys Productions",
        example_product="Open Ephys neural acquisition system",
        example_evidence=(
            "Open Ephys started as open-source lab hardware at MIT (Siegle et al., "
            "Nat Neurosci 2017). Bootstrapped commercialization through SBIR grants and "
            "a university core-facility model without VC dilution. Reached 300+ labs "
            "worldwide before raising outside capital."
        ),
        source_url="https://www.sbir.gov/about",
        how_to_apply=(
            "File as a for-profit entity first — SBIR requires one. Then submit SBIR Phase I "
            "($300k, 6 months) to NIH or NSF before a pre-seed round. The award validates "
            "the scientific problem and reduces dilution on the next raise. Phase II "
            "($1.5M–$2M, 2 years) can fund a full commercial-grade build."
        ),
        apply_template=(
            "File {company_name} as a for-profit entity, then submit SBIR Phase I to "
            "{funding_agency} before your pre-seed round. The $300k award validates "
            "{product_name}'s scientific problem statement and reduces dilution when you "
            "raise equity. Phase II ($1.5M–$2M over 2 years) can fund a full "
            "commercial-grade build. Institutional procurement is risk-averse and "
            "grant-funded — SBIR credentialing directly addresses both buyer objections."
        ),
    ),

    Strategy(
        id="research-tool-open-source-core",
        category="Open-Source Core / Commercial Services",
        headline="Open-source the core protocol and SDK, sell the commercial services layer — the academic research market rewards transparency and punishes lock-in",
        archetypes=["research_tool_non_clinical"],
        domains=["LIFE_SCIENCES_RESEARCH"],
        buyer_personas=["academic_pi", "research_engineer"],
        example_company="Plexon Inc.",
        example_product="OmniPlex neural data acquisition system",
        example_evidence=(
            "Plexon open-sourced its offline sorter and OmniPlex SDK while maintaining "
            "closed-source hardware drivers and cloud analytics. Open-source components "
            "built ecosystem adoption in 1,000+ labs; proprietary hardware remained the "
            "revenue vehicle."
        ),
        source_url="https://plexon.com/products/plexon-omniplex-neural-data-acquisition-system/",
        how_to_apply=(
            "Release firmware, data format specification, and Python/MATLAB SDK under MIT "
            "or Apache license before launch. File a provisional patent on the hardware "
            "implementation first. Open access generates inbound interest from technically "
            "capable PI labs that become organic champions. Retain commercial value in "
            "hardware, support contracts, and managed cloud sync services."
        ),
        apply_template=(
            "Release the {product_name} data format specification and Python/MATLAB SDK "
            "under MIT or Apache license before commercial launch — file a provisional "
            "patent on the specific hardware implementation first. Open access builds a "
            "PI champion network in {buyer_type} labs who become organic referrers. "
            "Retain commercial value in hardware, support contracts, and managed cloud "
            "sync services where lab IT cannot self-host."
        ),
    ),

    # ── Research Infrastructure SaaS ──────────────────────────────────────────

    Strategy(
        id="research-saas-institutional-site-license",
        category="Research SaaS — Institutional Site License",
        headline="Land in one department; expand via the research computing office — the IT buying unit is higher-value and faster than PI-by-PI expansion",
        archetypes=["research_infrastructure_saas"],
        domains=["LIFE_SCIENCES_RESEARCH"],
        buyer_personas=["institutional_it", "vp_research", "academic_pi"],
        example_company="LabArchives",
        example_product="LabArchives Electronic Lab Notebook",
        example_evidence=(
            "LabArchives shifted from individual PI sales ($10–30/user/month) to "
            "institutional site licenses ($20k–$100k/yr) by partnering with university "
            "IT and research computing offices rather than PIs. One institutional sale "
            "covers hundreds to thousands of users and renews on the institution's fiscal "
            "cycle, not the PI's grant cycle."
        ),
        source_url="https://www.labarchives.com",
        how_to_apply=(
            "After initial traction (≥5 active labs, ≥3 testimonials), approach the VP "
            "Research or CIO with an institutional site-license proposal. Lead with "
            "compliance arguments — NSF data management plans, NIH data sharing policy — "
            "that matter to the institution beyond individual PIs."
        ),
        apply_template=(
            "After landing ≥5 active labs with {product_name}, approach the VP Research "
            "or CIO with an institutional site-license proposal. Lead with compliance "
            "arguments — NSF data management plans, NIH data sharing policy — that create "
            "an institutional budget line independent of individual PI grants. "
            "One site license ($20k–$100k/yr) delivers more recurring revenue than "
            "20+ individual PI subscriptions."
        ),
    ),

    Strategy(
        id="research-saas-grant-cycle-timing",
        category="Grant Renewal Timing",
        headline="Time enterprise sales pitches to align with R01 renewal cycles — a PI in year 1–2 of a new award has budget authority; one in year 4–5 does not",
        archetypes=["research_tool_non_clinical"],
        domains=["LIFE_SCIENCES_RESEARCH"],
        buyer_personas=["academic_pi"],
        example_company="Benchling",
        example_product="Benchling R&D Cloud (life science SaaS)",
        example_evidence=(
            "Benchling's academic sales motion anchors to grant budget periods (typically "
            "5-year R01 cycles). Outreach timed to the start of new award periods, when "
            "PIs have full discretion over equipment and software budget lines, converts "
            "at 3–5× the rate of outreach timed to the final year."
        ),
        source_url="https://reporter.nih.gov",
        how_to_apply=(
            "Build a data layer from NIH RePORTER: pull active awards with start dates, "
            "project end dates, and abstract text. Flag labs in year 1–2 of a new award "
            "for priority outreach. Suppress outreach for labs in year 4–5. The sales "
            "cycle shrinks from months to weeks when the PI has current budget authority."
        ),
        apply_template=(
            "Build a priority queue from NIH RePORTER: flag labs in year 1–2 of a new "
            "R01 award for {product_name} outreach, suppress labs in year 4–5. "
            "Outreach to early-award PIs — who have full discretion over equipment and "
            "software budget lines — converts at 3–5× the rate of year-5 outreach. "
            "Pair this with the {product_name} methods paper: a cited workflow in year 1 "
            "of a new award becomes standard practice for the full grant period."
        ),
    ),
]


# ── Filter and render API ─────────────────────────────────────────────────────

def filter_strategies(
    archetype: str,
    domain: str,
    buyer_persona: str | None = None,
    max_strategies: int = 4,
) -> list[Strategy]:
    """Return strategies that match the archetype and domain gates.

    Matching rules
    --------------
    - archetypes=[] means the strategy is domain-gated only
    - domains=[] means the strategy is archetype-gated only
    - Both empty means universal (should not exist in this library)
    - buyer_persona filtering is additive if supplied, but never reduces
      results below 1 when other gates match
    """
    archetype = (archetype or "").lower()
    domain    = (domain    or "").upper()

    candidates: list[Strategy] = []
    for s in TYPED_STRATEGY_LIBRARY:
        arch_match  = (not s.archetypes)  or (archetype in s.archetypes)
        domain_match = (not s.domains)   or (domain in s.domains)
        if arch_match and domain_match:
            candidates.append(s)

    # Soft-filter by buyer_persona if supplied; only apply if it wouldn't
    # empty the list
    if buyer_persona and candidates:
        persona_filtered = [
            s for s in candidates
            if not s.buyer_personas or buyer_persona in s.buyer_personas
        ]
        if persona_filtered:
            candidates = persona_filtered

    return candidates[:max_strategies]


def render_strategy(strategy: Strategy, context: dict) -> dict:
    """Return a dict with all strategy fields, apply_template rendered.

    apply_template uses str.format_map with a SafeDict so missing keys
    leave the {placeholder} visible rather than raising KeyError.
    """
    class _SafeDict(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    rendered_template = ""
    if strategy.apply_template:
        try:
            rendered_template = strategy.apply_template.format_map(_SafeDict(context))
        except Exception:
            rendered_template = strategy.how_to_apply

    return {
        "id":               strategy.id,
        "strategy":         strategy.headline,
        "category":         strategy.category,
        "example":          f"{strategy.example_company} — {strategy.example_product}",
        "what_they_did":    strategy.example_evidence,
        "how_to_apply":     rendered_template or strategy.how_to_apply,
        "source_url":       strategy.source_url,
        "archetypes":       strategy.archetypes,
        "domains":          strategy.domains,
        "buyer_personas":   strategy.buyer_personas,
    }


def format_typed_strategies_for_report(
    archetype: str,
    domain: str,
    context: dict | None = None,
    max_strategies: int = 4,
) -> list[dict]:
    """Filter + render strategies as a list of report-ready dicts."""
    ctx = context or {}
    strategies = filter_strategies(archetype, domain, max_strategies=max_strategies)
    return [render_strategy(s, ctx) for s in strategies]
