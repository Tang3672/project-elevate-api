"""
source_aggregator.py — comprehensive bibliography builder
=========================================================
Collects every cited source across all report sections into a single
deduplicated, numbered list.  Called at report-generation time so both
the web frontend (report.sources) and the PDF export get the same ~50
entries.

Sources harvested (in priority order for deduplication):
  1. LLM-generated sources (report["sources"])
  2. PubMed / OpenAlex literature citations
  3. Disease intelligence data_points
  4. Market sizing waterfall steps + derivation step academic references
  5. Regulatory pathway designations + trial requirements
  6. Market access buyer segments
  7. Demand signals / supporting evidence (NIH RePORTER, NSF, etc.)
  8. Strategic playbook
  9. Pipeline-level: Google Patents, NIH SBIR awards, SEC EDGAR 8-K,
     ClinicalTrials.gov new entrants, bioRxiv/medRxiv preprints
 10. Aggregated sources: CrossRef, Europe PMC, Semantic Scholar, NIH grants,
     GBD, CMS pricing, SEC EDGAR 10-K, ASHP drug shortage
 11. FDA-approved drugs with DailyMed URLs (regulatory_precedent)
 12. Competitor trials (ClinicalTrials.gov) + FDA precedents (competitive_intelligence)

Deduplication is URL-based: sources with no URL are always included;
sources with a URL are included once (first occurrence wins).
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _slug(url: str) -> str:
    """Normalise a URL for dedup: strip trailing slash and lowercase scheme."""
    return url.lower().rstrip("/") if url else ""


def collect_all_citations(
    report: dict,
    *,
    patent_landscape: Optional[dict] = None,
    funding_intel: Optional[dict] = None,
    aggregated_sources: Optional[dict] = None,
    regulatory_precedent: Optional[dict] = None,
    competitive_intelligence: Optional[dict] = None,
) -> list[dict]:
    """
    Return a numbered list of all cited sources for a given report dict.

    Parameters
    ----------
    report:
        The serialised PIReport dict (e.g. from report.model_dump() or the DB).
    patent_landscape:
        Raw return value of get_patent_landscape() — contains recent_patents
        with Google Patents URLs.  May be None if the service failed.
    funding_intel:
        Raw return value of get_funding_intelligence() — contains sbir_awards
        (NIH Reporter), edgar_signals (SEC EDGAR), new_entrants (ClinicalTrials),
        and preprints (bioRxiv/medRxiv).  May be None if the service failed.
    regulatory_precedent:
        Raw return value of get_regulatory_precedent() — contains approved_drugs
        with DailyMed URLs.  May be None if the service failed.
    competitive_intelligence:
        Raw return value of gather_competitive_intelligence() — contains
        competitor_trials (ClinicalTrials.gov) and fda_precedents (Drugs@FDA).
        May be None if the service failed.
    aggregated_sources:
        Raw return value of source_aggregator_service.aggregate_all_sources() —
        contains CrossRef, Europe PMC, Semantic Scholar, NIH grants, GBD, and
        CMS pricing data with URLs.  May be None if the service failed.
    """
    entries: list[dict] = []
    seen: set[str] = set()

    def add(name: str, url: str, *, category: str = "") -> None:
        name = (name or "").strip()
        url = (url or "").strip()
        slug = _slug(url)
        if slug and slug in seen:
            return
        if slug:
            seen.add(slug)
        if not name and not url:
            return
        entry: dict = {"name": name, "url": url}
        if category:
            entry["category"] = category
        entries.append(entry)

    # ── 1. LLM-generated sources ───────────────────────────────────────────────
    for s in report.get("sources") or []:
        add(s.get("name", ""), s.get("url", ""), category="report")

    # ── 2. Literature citations (PubMed / OpenAlex) ───────────────────────────
    for p in report.get("literature_citations") or []:
        url = (
            p.get("url")
            or p.get("source_url")
            or (f"https://pubmed.ncbi.nlm.nih.gov/{p['pmid']}/" if p.get("pmid") else "")
        )
        name = (
            p.get("title")
            or p.get("name")
            or f"{p.get('authors', '')} ({p.get('year', '')}). {p.get('journal', '')}".strip(". ")
        )
        add(name, url, category="literature")

    # ── 3. Disease intelligence data points ───────────────────────────────────
    di = report.get("disease_intelligence") or {}
    for dp in di.get("data_points") or []:
        add(
            f"{dp.get('source', '')} — {dp.get('metric', '')[:60]}",
            dp.get("source_url", ""),
            category="disease_data",
        )

    # ── 4. Market sizing waterfall steps ──────────────────────────────────────
    ms = report.get("market_sizing") or {}
    for step in ms.get("steps") or []:
        add(
            f"{step.get('source', '')} — {step.get('label', '')[:60]}",
            step.get("source_url", ""),
            category="market_sizing",
        )

    # ── 4b. Market sizing derivation primary citations ─────────────────────────
    # These are the named sources from the MoE specialist formula (NIH RePORTER,
    # NSF Award Search, IQVIA, EvaluatePharma, etc.) that were injected into the
    # Claude prompt but may not have been reproduced verbatim in the LLM narrative.
    for c in (report.get("market_sizing_derivation") or {}).get("primary_citations") or []:
        add(
            f"{c.get('ref', '')} — {c.get('title', '')}"[:120],
            c.get("url", ""),
            category="market_sizing",
        )

    # ── 5a. Regulatory pathway designations ───────────────────────────────────
    rp = report.get("regulatory_pathway") or {}
    for des in rp.get("designations") or []:
        add(
            f"{des.get('name', '')} ({des.get('source', '')})",
            des.get("source_url", ""),
            category="regulatory",
        )

    # ── 5b. Clinical trial phase guidance documents ───────────────────────────
    for ctr in rp.get("clinical_trial_requirements") or []:
        add(
            ctr.get("fda_guidance_document", ""),
            ctr.get("source_url", ""),
            category="regulatory",
        )

    # ── 6. Market access buyer segments ───────────────────────────────────────
    ma = report.get("market_access") or {}
    for seg in ma.get("buyer_segments") or []:
        add(
            f"{seg.get('source', '')} — {seg.get('segment_name', '')}",
            seg.get("source_url", ""),
            category="market_access",
        )
    reimb_url = ma.get("reimbursement_source_url", "")
    if reimb_url:
        add("Reimbursement pathway source", reimb_url, category="market_access")

    # ── 7. Demand signals / supporting evidence ────────────────────────────────
    # These are the live federal database signals (NIH RePORTER, NSF, ClinicalTrials,
    # HRSA) that the LLM used to ground §1 and the market estimate.
    for ev in report.get("supporting_evidence") or []:
        src = ev.get("source", "")
        title = ev.get("title", "")[:100]
        url = ev.get("source_url", "")
        name = f"{src}: {title}" if title else src
        add(name, url, category="demand_signal")

    # ── 8. Strategic playbook ──────────────────────────────────────────────────
    for play in report.get("strategic_playbook") or []:
        add(
            f"{play.get('example', '')} — {play.get('strategy', '')}"[:100],
            play.get("source_url", ""),
            category="playbook",
        )

    # ── 9a. Pipeline: Google Patents ──────────────────────────────────────────
    if isinstance(patent_landscape, dict):
        for pat in (patent_landscape.get("recent_patents") or [])[:15]:
            title = pat.get("title", "")[:90]
            assignee = pat.get("assignee", "")
            pub_no = pat.get("publication_number", "")
            label = f"Patent: {title}" + (f" ({assignee})" if assignee else "")
            url = pat.get("url", "") or (
                f"https://patents.google.com/patent/{pub_no}" if pub_no else ""
            )
            add(label, url, category="patent")

    # ── 9b. Pipeline: NIH Reporter SBIR/STTR awards ───────────────────────────
    if isinstance(funding_intel, dict):
        for award in (funding_intel.get("sbir_awards") or [])[:10]:
            title = award.get("project_title", "")[:90]
            company = award.get("company", "")
            url = award.get("url", "")
            fy = award.get("fiscal_year", "")
            label = f"SBIR Award (FY{fy}): {title}"
            if company and company != "Unknown org":
                label += f" — {company}"
            add(label, url, category="sbir_award")

        # ── 9c. SEC EDGAR 8-K financing signals ───────────────────────────────
        for signal in (funding_intel.get("edgar_signals") or [])[:6]:
            company = signal.get("company", "")
            date = signal.get("date", "")
            url = signal.get("url", "")
            label = f"SEC EDGAR 8-K: {company}" + (f" ({date})" if date else "")
            add(label[:120], url, category="funding_signal")

        # ── 9d. ClinicalTrials.gov new entrants (competitor trial registrations) ─
        for entrant in (funding_intel.get("new_entrants") or [])[:8]:
            sponsor = entrant.get("sponsor", "")
            nct = entrant.get("nct_id", "")
            title = entrant.get("title", "")[:80]
            url = entrant.get("url", "") or (f"https://clinicaltrials.gov/study/{nct}" if nct else "")
            phase = entrant.get("phase", "")
            label = f"ClinicalTrials.gov {phase}: {title} — {sponsor}"
            add(label[:120], url, category="competitive_landscape")

        # ── 9e. bioRxiv/medRxiv preprints (research momentum signal) ──────────
        preprints_data = funding_intel.get("preprints") or {}
        for preprint in (preprints_data.get("recent_titles") or [])[:5]:
            title = preprint.get("title", "")[:90]
            authors = preprint.get("authors", "")[:50]
            server = preprint.get("server", "")
            doi = preprint.get("doi", "")
            url = preprint.get("url", "") or (f"https://doi.org/{doi}" if doi else "")
            label = f"[{server}] {title}" + (f" — {authors}" if authors else "")
            add(label[:120], url, category="literature")

    # ── 4c. Derivation step source_url (academic references per formula step) ─
    # DerivationStep.source_url holds paper/guideline URLs (DisMod II, NICE TSD 14,
    # Bass model, BLP demand system, ISPOR, ICER, CMS, CDC, etc.) that are wired
    # into the formula engine but never propagated to the bibliography.
    for step in (report.get("market_sizing_derivation") or {}).get("steps") or []:
        title = step.get("title", "") or step.get("label", "")
        source_paper = step.get("source_paper", "")
        label = f"{source_paper} — {title}"[:120] if source_paper else title[:120]
        add(label, step.get("source_url", ""), category="market_sizing")

    # ── 5c. Competitive landscape competitor source URLs ──────────────────────
    cl = report.get("competitive_landscape") or {}
    for comp in cl.get("competitors") or []:
        name = comp.get("name", "") or comp.get("company", "")
        url = comp.get("source_url", "") or comp.get("url", "")
        if name or url:
            add(f"Competitor: {name}", url, category="competitive_landscape")

    # ── 10. Aggregated multi-source data (CrossRef, Europe PMC, Semantic Scholar,
    #         NIH Grants, GBD, CMS drug pricing) — fetched live, URL-bearing ────
    if isinstance(aggregated_sources, dict):
        # Academic papers (CrossRef / Europe PMC / Semantic Scholar)
        for paper in (aggregated_sources.get("papers") or []):
            title = paper.get("title", "")[:100]
            url = paper.get("url", "") or paper.get("doi_url", "")
            authors = paper.get("authors", "")
            year = paper.get("year", "")
            source = paper.get("source", "")
            label = title or f"{authors} ({year})"
            if source:
                label = f"[{source}] {label}"
            add(label[:120], url, category="literature")

        # NIH grants (NIH RePORTER)
        for grant in (aggregated_sources.get("nih_grants") or []):
            title = grant.get("title", "")[:90]
            pi = grant.get("pi_name", "") or grant.get("contact_pi_name", "")
            grant_num = grant.get("project_num", "") or grant.get("grant_number", "")
            url = grant.get("url", "") or (
                f"https://reporter.nih.gov/project-details/{grant_num}" if grant_num else ""
            )
            label = f"NIH Grant ({grant_num}): {title}" if grant_num else f"NIH Grant: {title}"
            if pi:
                label += f" — PI: {pi}"
            add(label[:120], url, category="nih_grant")

        # GBD (Global Burden of Disease) data points
        for gbd_item in (aggregated_sources.get("gbd") or []):
            title = gbd_item.get("title", "") or gbd_item.get("metric", "")
            url = gbd_item.get("url", "")
            add(f"GBD: {title}"[:100], url, category="disease_data")

        # CMS drug/device pricing data
        for cms_item in (aggregated_sources.get("cms_pricing") or []):
            drug = cms_item.get("drug_name", "") or cms_item.get("name", "")
            url = cms_item.get("url", "")
            add(f"CMS Pricing: {drug}"[:100], url, category="market_sizing")

        # SEC EDGAR filings (10-K / 8-K competitor financials)
        for filing in (aggregated_sources.get("sec_filings") or [])[:5]:
            company = filing.get("company", "")
            form = filing.get("form_type", "")
            date = filing.get("filing_date", "")
            url = filing.get("url", "")
            label = f"SEC {form}: {company}" + (f" ({date})" if date else "")
            add(label[:120], url, category="funding_signal")

        # ASHP drug shortage data
        for shortage in (aggregated_sources.get("drug_shortage") or [])[:3]:
            drug = shortage.get("drug", "")
            url = shortage.get("url", "")
            add(f"ASHP Drug Shortage: {drug}"[:100], url, category="market_sizing")

    # ── 11. FDA-approved drugs for this indication (openFDA / DailyMed) ───────
    # From get_regulatory_precedent() — drugs listed in FDA drug label database
    # for this indication, with DailyMed URLs for label verification.
    if isinstance(regulatory_precedent, dict):
        for drug in (regulatory_precedent.get("approved_drugs") or []):
            generic = drug.get("generic_name", "")
            brand = drug.get("brand_name", "")
            manufacturer = drug.get("manufacturer", "")
            url = drug.get("url", "")
            label = f"FDA Approved: {generic}"
            if brand and brand.lower() != generic.lower():
                label += f" ({brand})"
            if manufacturer and manufacturer != "Unknown":
                label += f" — {manufacturer}"
            add(label[:120], url, category="regulatory")

    # ── 12. Competitive intelligence — live ClinicalTrials.gov + Drugs@FDA ────
    # From gather_competitive_intelligence() — real-time competitor trial and
    # approval URLs that informed the competitive landscape narrative.
    if isinstance(competitive_intelligence, dict):
        for trial in (competitive_intelligence.get("competitor_trials") or {}).get("trials", []):
            sponsor = trial.get("sponsor", "") or trial.get("lead_sponsor", "")
            title = trial.get("title", "") or trial.get("brief_title", "")
            nct = trial.get("nct_id", "") or trial.get("nctId", "")
            url = trial.get("url", "") or (f"https://clinicaltrials.gov/study/{nct}" if nct else "")
            phase = trial.get("phase", "")
            label = f"Competitor Trial {phase}: {title}"[:90] + (f" — {sponsor}" if sponsor else "")
            add(label[:120], url, category="competitive_landscape")

        for approval in (competitive_intelligence.get("fda_precedents") or {}).get("approvals", []):
            drug = approval.get("drug_name", "") or approval.get("generic_name", "")
            company = approval.get("company", "") or approval.get("applicant", "")
            url = approval.get("url", "")
            label = f"FDA Precedent: {drug}" + (f" ({company})" if company else "")
            add(label[:120], url, category="regulatory")

    # ── Number sequentially ───────────────────────────────────────────────────
    for i, entry in enumerate(entries, 1):
        entry["number"] = i

    logger.info("source_aggregator: collected %d citations", len(entries))
    return entries
