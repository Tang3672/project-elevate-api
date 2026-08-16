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
  4. Market sizing waterfall steps
  5. Regulatory pathway designations + trial requirements
  6. Market access buyer segments
  7. Demand signals / supporting evidence (NIH RePORTER, NSF, etc.)
  8. Strategic playbook
  9. Pipeline-level: Google Patents, NIH SBIR awards, Semantic Scholar KOLs

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
        with NIH Reporter URLs.  May be None if the service failed.
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

    # ── Number sequentially ───────────────────────────────────────────────────
    for i, entry in enumerate(entries, 1):
        entry["number"] = i

    logger.info("source_aggregator: collected %d citations", len(entries))
    return entries
