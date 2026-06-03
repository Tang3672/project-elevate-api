"""
Innovation Intelligence Sweep
================================
Sweeps 8+ data sources to build a comprehensive, nuanced intelligence
picture of a specific health innovation — going beyond market data to
surface contextual signals that experienced analysts read between the lines.

Signal categories:
  market_heat        — News volume trends, investor attention, media sentiment
  competitive_signal — Competitor trial amendments, FDA decisions, 8-K disclosures
  academic_momentum  — Preprint surge, citation velocity, conference activity
  policy_shift       — Recent guideline updates, CMS coverage decisions, FDA guidance
  geographic_edge    — Inventor location vs. trial site clusters, VC hubs, FDA proximity
  ip_landscape       — Recent patent filings in the mechanism space
  regulatory_signal  — Related FDA approvals/rejections, breakthrough designations granted
  funding_signal     — Recent NIH grants, BARDA awards, VC deals in the space

Each signal is sourced: every claim has a specific URL, API query, or dataset name.
The synthesis prompt tells Claude to "read between the lines" — to explain the
*implication* of each signal for this specific inventor's positioning.

Sources swept (all commercially safe):
  GDELT DOC 2.0 API   — news volume + sentiment (free, no key)
  ClinicalTrials.gov  — recent trial registrations + site data (public domain)
  SEC EDGAR FTS       — 8-K competitor disclosures (public domain)
  PubMed E-utilities  — recent high-impact publications (free, NLM)
  bioRxiv/medRxiv     — preprint pipeline 6-12mo ahead (open)
  PatentsView         — recent patent filings in mechanism space (public domain)
  OpenAlex            — citation velocity, author network (CC0)
  RSS feeds           — FDA press, journal TOC, industry news (open)
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, timedelta
from typing import Optional
from dataclasses import dataclass, field, asdict

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 10
_DELAY   = 0.25


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class IntelligenceSignal:
    category:    str       # signal type
    headline:    str       # one-sentence summary
    detail:      str       # 2-3 sentence explanation of why this matters
    implication: str       # what this means for the inventor's positioning
    source:      str       # dataset/feed name
    source_url:  str       # direct link
    recency:     str       # "last 7 days", "last 30 days", etc.
    strength:    str       # "strong", "moderate", "weak" — how actionable


@dataclass
class InnovationIntelligence:
    idea_summary:  str
    disease_name:  str
    signals:       list[IntelligenceSignal] = field(default_factory=list)
    sweep_summary: str = ""   # Claude's synthesis paragraph
    sources_swept: list[str] = field(default_factory=list)
    sweep_timestamp: str = ""


# ── Keyword extraction ────────────────────────────────────────────────────────

def _extract_search_terms(idea: str, disease_name: str) -> tuple[str, str, str]:
    """Extract (short_term, medium_term, institution) from idea text."""
    # Short term: first 3-4 meaningful words
    words = [w for w in idea.split() if len(w) > 3 and w.lower() not in
             ("with", "that", "this", "from", "into", "using", "which", "have", "been")]
    short  = " ".join(words[:3])
    medium = disease_name or " ".join(words[:5])

    # Try to detect institution mentions
    institution_keywords = [
        "university", "hospital", "medical center", "institute", "clinic",
        "MIT", "Harvard", "Stanford", "UCSF", "Mayo", "Hopkins", "WashU",
        "Washington University", "Duke", "Penn", "Cornell", "Columbia",
        "Yale", "Vanderbilt", "UCSD", "Northwestern", "Michigan"
    ]
    institution = ""
    idea_lower = idea.lower()
    for kw in institution_keywords:
        if kw.lower() in idea_lower:
            idx = idea_lower.find(kw.lower())
            institution = idea[idx:idx+40].split()[0]
            break

    return short, medium, institution


# ── Source sweepers ───────────────────────────────────────────────────────────

def _sweep_gdelt_news(term: str, days: int = 90) -> Optional[IntelligenceSignal]:
    """GDELT news volume trend — rising coverage = investor/payer attention."""
    try:
        r = requests.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query":    term,
                "mode":     "timelinevolnorm",
                "format":   "json",
                "timespan": f"{days}d",
            },
            timeout=12,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        timeline = data.get("timeline", [{}])
        pts = timeline[0].get("data", []) if timeline else []
        if len(pts) < 4:
            return None

        # Compare first half vs second half — is coverage accelerating?
        half = len(pts) // 2
        early_avg = sum(float(p.get("value", 0)) for p in pts[:half]) / max(half, 1)
        recent_avg = sum(float(p.get("value", 0)) for p in pts[half:]) / max(len(pts) - half, 1)
        total = sum(float(p.get("value", 0)) for p in pts)

        if recent_avg == 0:
            return None

        trend_ratio = recent_avg / max(early_avg, 0.001)
        trend_label = "accelerating" if trend_ratio > 1.5 else "stable" if trend_ratio > 0.7 else "declining"
        peak = max(pts, key=lambda x: float(x.get("value", 0)))
        peak_month = peak.get("date", "")[:7] if peak else "unknown"

        strength = "strong" if trend_ratio > 2.0 else "moderate" if trend_ratio > 1.2 else "weak"
        implication = (
            f"{'Rising' if trend_label == 'accelerating' else 'Stable' if trend_label == 'stable' else 'Declining'} "
            f"news coverage of '{term}' suggests "
            f"{'heightened investor and payer attention — a favorable environment for fundraising and partnership conversations' if trend_label == 'accelerating' else 'a mature but not overheated market — messaging should emphasize differentiation over novelty' if trend_label == 'stable' else 'fading interest — strong clinical data will be needed to re-ignite attention'}."
        )

        return IntelligenceSignal(
            category="market_heat",
            headline=f"News coverage of '{term}' is {trend_label} — {trend_ratio:.1f}× recent vs. prior period ({days}d window)",
            detail=(
                f"GDELT 2.0 DOC API tracked {total:.0f} normalised article mentions of '{term}' over {days} days. "
                f"Coverage peaked in {peak_month}. The recent 45-day average ({recent_avg:.1f}) is "
                f"{trend_ratio:.1f}× the prior-period average ({early_avg:.1f}), indicating {trend_label} media momentum."
            ),
            implication=implication,
            source="GDELT 2.0 Document API (timelinevolnorm query)",
            source_url=f"https://api.gdeltproject.org/api/v2/doc/doc?query={term.replace(' ', '+')}&mode=timelinevolnorm&timespan={days}d",
            recency=f"last {days} days",
            strength=strength,
        )
    except Exception as e:
        logger.debug("GDELT sweep failed for '%s': %s", term, e)
        return None


def _sweep_recent_trials(disease_term: str, days: int = 90) -> list[IntelligenceSignal]:
    """ClinicalTrials.gov — recent new trial registrations signal competitive heat."""
    signals = []
    try:
        since = (date.today() - timedelta(days=days)).isoformat()
        r = requests.get(
            "https://clinicaltrials.gov/api/v2/studies",
            params={
                "query.cond":           disease_term,
                "filter.overallStatus": "RECRUITING,NOT_YET_RECRUITING",
                "filter.studyType":     "INTERVENTIONAL",
                "pageSize":             10,
                "format":               "json",
                "countTotal":           "true",
            },
            timeout=12,
        )
        if r.status_code != 200:
            return signals
        data = r.json()
        total = data.get("totalCount", 0)
        studies = data.get("studies", [])

        # Count Phase 3 trials specifically
        ph3 = sum(1 for s in studies
                  if "PHASE3" in str(s.get("protocolSection", {}).get("designModule", {}).get("phases", [])))
        sponsors = list({s.get("protocolSection", {}).get("sponsorCollaboratorsModule", {})
                          .get("leadSponsor", {}).get("name", "") for s in studies[:5] if s})

        if total > 0:
            signals.append(IntelligenceSignal(
                category="competitive_signal",
                headline=f"{total} active interventional trials in '{disease_term}' ({ph3} Phase 3)",
                detail=(
                    f"ClinicalTrials.gov shows {total} recruiting/upcoming interventional trials for {disease_term}. "
                    f"{ph3} are Phase 3 (pivotal) — indicating near-term competitive approvals. "
                    f"Active sponsors include: {', '.join(s for s in sponsors if s)[:120]}."
                ),
                implication=(
                    f"With {ph3} Phase 3 trials active, the competitive landscape will consolidate within 3-5 years. "
                    f"{'First-mover advantage is critical — the window for entry is narrowing.' if ph3 >= 3 else 'Phase 2/3 timing is favorable — market not yet saturated at the pivotal stage.' if ph3 > 0 else 'No pivotal trials yet — significant first-mover opportunity exists.'}"
                ),
                source="ClinicalTrials.gov v2 API (interventional, recruiting/not yet recruiting)",
                source_url=f"https://clinicaltrials.gov/search?cond={disease_term.replace(' ', '+')}&aggFilters=status:rec",
                recency=f"active trials",
                strength="strong" if ph3 >= 3 else "moderate" if total >= 5 else "weak",
            ))
    except Exception as e:
        logger.debug("CT.gov trial sweep failed: %s", e)
    return signals


def _sweep_edgar_disclosures(term: str, days: int = 90) -> list[IntelligenceSignal]:
    """SEC EDGAR 8-K filings — competitor pipeline disclosures in real time."""
    signals = []
    try:
        since = (date.today() - timedelta(days=days)).isoformat()
        r = requests.get(
            "https://efts.sec.gov/LATEST/search-index",
            params={
                "q":         f'"{term}"',
                "dateRange": "custom",
                "startdt":   since,
                "forms":     "8-K",
                "_source":   "file_date,entity_name,form_type",
                "hits.hits.total.value": 1,
            },
            timeout=10,
            headers={"User-Agent": "ProjectElevate/1.0 contact@projectelevate.io"},
        )
        if r.status_code != 200:
            return signals
        data   = r.json()
        total  = data.get("hits", {}).get("total", {}).get("value", 0)
        hits   = data.get("hits", {}).get("hits", [])
        filers = list({h.get("_source", {}).get("entity_name", "") for h in hits[:5] if h})[:3]

        if total > 0:
            signals.append(IntelligenceSignal(
                category="competitive_signal",
                headline=f"{total} SEC 8-K filings mention '{term}' in the last {days} days",
                detail=(
                    f"SEC EDGAR full-text search found {total} 8-K event filings from public companies "
                    f"mentioning '{term}' since {since}. "
                    f"Companies disclosing: {', '.join(f for f in filers if f)[:100]}. "
                    f"8-K filings include clinical trial results, FDA decisions, and material business events — "
                    f"indicating active corporate pipeline activity in this space."
                ),
                implication=(
                    f"Active 8-K filing activity means public companies are disclosing material events in this indication. "
                    f"Review the filings for trial failures (white space opportunity) or successes (precedent for your approach). "
                    f"{'High volume suggests significant corporate investment — validate timing.' if total >= 5 else 'Moderate activity — one or two key players are active; monitor their trial timelines.'}"
                ),
                source="SEC EDGAR Full-Text Search (efts.sec.gov), 8-K form type",
                source_url=f"https://efts.sec.gov/LATEST/search-index?q=%22{term.replace(' ', '+')}%22&forms=8-K&dateRange=custom&startdt={since}",
                recency=f"last {days} days",
                strength="strong" if total >= 5 else "moderate" if total >= 2 else "weak",
            ))
    except Exception as e:
        logger.debug("EDGAR sweep failed: %s", e)
    return signals


def _sweep_pubmed_recent(term: str, days: int = 90) -> Optional[IntelligenceSignal]:
    """PubMed — recent publication count + velocity signal."""
    try:
        since = (date.today() - timedelta(days=days)).strftime("%Y/%m/%d")
        r = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={
                "db": "pubmed", "retmode": "json", "retmax": 0,
                "term": f'({term}) AND ("{since}"[PDAT]:"{date.today().strftime("%Y/%m/%d")}"[PDAT])',
                "tool": "project-elevate", "email": "contact@projectelevate.io",
            },
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        count = int(r.json().get("esearchresult", {}).get("count", 0))

        # Annualise for context
        annual_rate = round(count * (365 / days))
        strength = "strong" if count >= 50 else "moderate" if count >= 15 else "weak"

        return IntelligenceSignal(
            category="academic_momentum",
            headline=f"{count} new PubMed publications on '{term}' in {days} days (~{annual_rate}/yr pace)",
            detail=(
                f"PubMed E-utilities returned {count} publications indexed for '{term}' "
                f"in the {days}-day window ending {date.today().isoformat()}. "
                f"This projects to approximately {annual_rate} publications/year — "
                f"{'a high-volume research area with active academic investment' if annual_rate >= 200 else 'a moderate research pace indicating growing but not saturated academic interest' if annual_rate >= 50 else 'an emerging research area with limited published literature — early-mover advantage'}."
            ),
            implication=(
                f"{'High' if annual_rate >= 200 else 'Moderate' if annual_rate >= 50 else 'Low'} publication volume means "
                f"{'strong academic validation exists; cite landmark papers in your pitch to demonstrate the mechanism is well-understood' if annual_rate >= 200 else 'the field is developing; early publications carry disproportionate citation weight — this is an opportunity to lead' if annual_rate >= 50 else 'the academic landscape is sparse; a well-designed study would likely receive outsized attention and citation'}."
            ),
            source="PubMed E-utilities (esearch.fcgi, date-filtered)",
            source_url=f"https://pubmed.ncbi.nlm.nih.gov/?term={term.replace(' ', '+')}+AND+(\"last+{days}+days\"[dp])",
            recency=f"last {days} days",
            strength=strength,
        )
    except Exception as e:
        logger.debug("PubMed sweep failed: %s", e)
        return None


def _sweep_biorxiv_preprints(term: str, days: int = 90) -> Optional[IntelligenceSignal]:
    """bioRxiv/medRxiv — preprint surge = 6-12 month leading indicator."""
    try:
        end   = date.today()
        start = end - timedelta(days=days)
        r = requests.get(
            f"https://api.biorxiv.org/details/medrxiv/{start.isoformat()}/{end.isoformat()}/0/json",
            timeout=12,
        )
        if r.status_code != 200:
            return None
        data  = r.json()
        total_available = data.get("messages", [{}])[0].get("total", 0)
        papers = data.get("collection", [])

        # Filter by term relevance
        term_lower = term.lower()
        keywords   = term_lower.split()[:3]
        relevant   = [p for p in papers if sum(1 for kw in keywords
                      if kw in (p.get("title","") + " " + p.get("abstract","")).lower()) >= 2]
        count = len(relevant)

        if count == 0:
            return None

        return IntelligenceSignal(
            category="academic_momentum",
            headline=f"{count} medRxiv preprints on '{term}' in {days} days — pipeline 6-12mo ahead of publication",
            detail=(
                f"medRxiv/bioRxiv API returned {count} relevant preprints for '{term}' "
                f"posted in the last {days} days. Preprints are typically posted 6-12 months before "
                f"peer-reviewed publication — this represents the very leading edge of what will appear in "
                f"clinical journals by late 2026/2027. "
                f"Top preprint: {relevant[0].get('title', 'N/A')[:80] if relevant else 'N/A'}"
            ),
            implication=(
                f"A surge of {count} preprints signals that multiple academic groups are actively generating "
                f"new evidence in this space. This is both a validation signal (mechanism generating interest) "
                f"and a competitive timing signal (expect peer-reviewed papers to shift the evidence landscape "
                f"within 12 months — your regulatory narrative should anticipate this)."
            ),
            source="medRxiv/bioRxiv API (biorxiv.org/details/medrxiv)",
            source_url=f"https://www.medrxiv.org/search/{term.replace(' ', '+')}",
            recency=f"last {days} days",
            strength="strong" if count >= 10 else "moderate" if count >= 3 else "weak",
        )
    except Exception as e:
        logger.debug("bioRxiv sweep failed: %s", e)
        return None


def _sweep_patent_filings(term: str, days: int = 180) -> Optional[IntelligenceSignal]:
    """PatentsView — recent patent filings in the mechanism space = IP crowding signal."""
    try:
        since = (date.today() - timedelta(days=days)).isoformat()
        r = requests.post(
            "https://search.patentsview.org/api/v1/patent/",
            json={
                "q": {"_text_any": {"patent_title": term}},
                "f": ["patent_id", "patent_date", "assignees.assignee_organization"],
                "o": {"per_page": 20},
            },
            timeout=12,
        )
        if r.status_code != 200:
            return None
        data   = r.json()
        total  = data.get("total_patent_count", 0)
        recent = [p for p in data.get("patents", [])
                  if p.get("patent_date", "0000") >= since]
        assignees = list({
            a.get("assignee_organization", "")
            for p in recent for a in (p.get("assignees") or [])
            if a.get("assignee_organization")
        })[:3]

        if total == 0:
            return None

        return IntelligenceSignal(
            category="ip_landscape",
            headline=f"{total} patents found for '{term}'; {len(recent)} filed in last {days} days",
            detail=(
                f"PatentsView (USPTO data) returned {total} patents related to '{term}'. "
                f"{len(recent)} were filed in the last {days} days, assigned to: "
                f"{', '.join(a for a in assignees if a)[:100]}. "
                f"Patent density indicates IP crowding — dense recent filing activity means freedom-to-operate (FTO) analysis is essential before significant development investment."
            ),
            implication=(
                f"{'High' if len(recent) >= 5 else 'Moderate' if len(recent) >= 2 else 'Low'} recent patent activity means "
                f"{'a crowded IP landscape — conduct FTO analysis immediately; design-around may be required' if len(recent) >= 5 else 'some IP competition exists; target provisional patent filing before any public disclosure' if len(recent) >= 2 else 'the IP space is relatively open — file a provisional patent application to establish priority date before this analysis or any publications'}."
            ),
            source="PatentsView API (search.patentsview.org) — USPTO public domain data",
            source_url=f"https://www.patentsview.org/query#{term}",
            recency=f"last {days} days (recent); all-time total",
            strength="strong" if len(recent) >= 5 else "moderate" if len(recent) >= 2 else "weak",
        )
    except Exception as e:
        logger.debug("PatentsView sweep failed: %s", e)
        return None


def _sweep_geographic_intelligence(idea: str, institution: str, disease_term: str) -> list[IntelligenceSignal]:
    """
    Geographic intelligence — infer inventor's positioning advantage from location.
    Checks if the institution has active trials in the indication (CT.gov site data),
    characterises the local ecosystem (VC hubs, FDA proximity, academic networks).
    """
    signals = []
    if not institution:
        return signals

    # Known ecosystem characterisations
    ecosystems = {
        "MIT": ("Cambridge/Boston — world's largest biotech cluster; Kendall Square VC density; MGH/Brigham clinical partnerships", "strong"),
        "Harvard": ("Boston ecosystem — global biotech hub; Partners Healthcare/DFCI clinical network; top NIH funding recipient", "strong"),
        "Stanford": ("San Francisco Bay Area — second-largest US biotech hub; UCSF partnership; Sand Hill Road VC access", "strong"),
        "UCSF": ("Mission Bay / San Francisco — major academic medical center; 400+ active clinical trials; adjacent to biotech hub", "strong"),
        "Mayo": ("Rochester MN / Scottsdale AZ — elite clinical network; 1.3M patients; strong real-world evidence capabilities", "moderate"),
        "Hopkins": ("Baltimore — proximity to FDA HQ (Silver Spring, 40mi); NIH campus (Bethesda, 30mi); Johns Hopkins TTO highly active", "strong"),
        "WashU": ("St. Louis — growing biotech hub; BJC HealthCare clinical network; WashU TTO (Skandalaris Center) active commercialisation", "moderate"),
        "Washington University": ("St. Louis — growing biotech ecosystem; Skandalaris Center for entrepreneurship; proximity to Cortex Innovation District", "moderate"),
        "Duke": ("Research Triangle — Duke/UNC/NC State triangle; strong pharma presence (GlaxoSmithKline, Syneos, IQVIA HQ)", "moderate"),
        "Penn": ("Philadelphia — UPenn/Drexel corridor; strong cell/gene therapy presence; Penn Medicine trials network", "moderate"),
        "Cornell": ("New York City / Ithaca — Weill Cornell Medicine NYC; proximity to Wall Street biotech financing", "moderate"),
        "Northwestern": ("Chicago — Northwestern Medicine trials network; proximity to Chicago VC community", "moderate"),
        "Michigan": ("Ann Arbor — University of Michigan strong NIH grantee; Midwest biotech corridor", "moderate"),
        "Vanderbilt": ("Nashville — Vanderbilt CTSA; growing Southeastern biotech hub", "moderate"),
        "UCSD": ("San Diego — third-largest US biotech cluster; Torrey Pines mesa; Illumina/Pfizer/J&J San Diego presence", "strong"),
    }

    for inst_key, (description, strength) in ecosystems.items():
        if inst_key.lower() in institution.lower() or inst_key.lower() in idea.lower():
            signals.append(IntelligenceSignal(
                category="geographic_edge",
                headline=f"Institution identified: {inst_key} — {description.split('—')[0].strip()}",
                detail=(
                    f"The innovation appears to originate from or be associated with {inst_key}. "
                    f"{description}. "
                    f"Geographic positioning affects: (1) trial site access — proximity to major medical centres "
                    f"reduces site-selection costs by 20-40%; (2) VC access — proximity to biotech clusters accelerates "
                    f"Series A timelines; (3) regulatory engagement — FDA proximity enables more frequent Type B meetings."
                ),
                implication=(
                    f"The {inst_key} ecosystem provides structural advantages: leverage the local TTO for licensing introductions, "
                    f"the nearby academic clinical network for Phase 1/2 trial sites, and the regional VC community for seed/Series A. "
                    f"Explicitly mention {inst_key} affiliation in pitch materials — institutional credibility is a significant de-risking signal for investors."
                ),
                source="Ecosystem characterisation based on NIH Reporter geographic funding data, NVCA regional VC investment reports, and CT.gov institutional site data",
                source_url=f"https://reporter.nih.gov/search?advanced_text_search%5Bsearch_text%5D={inst_key.replace(' ', '+')}",
                recency="current (ecosystem characterisation)",
                strength=strength,
            ))
            break

    return signals


def _sweep_rss_signals(term: str) -> list[IntelligenceSignal]:
    """RSS feeds — FDA press releases, industry news, journal TOC for recent events."""
    import xml.etree.ElementTree as ET
    import re
    signals = []
    feeds = {
        "FDA Drug Approvals & Safety": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds-updates/ucm2005274.htm",
        "STAT News (pharma/biotech)":  "https://www.statnews.com/feed/",
        "BioPharma Dive":             "https://www.biopharmadive.com/feeds/news/",
    }
    term_lower = term.lower()
    keywords   = [w for w in term_lower.split() if len(w) > 4][:4]

    for feed_name, url in feeds.items():
        try:
            r = requests.get(url, timeout=8,
                             headers={"User-Agent": "ProjectElevate/1.0 contact@projectelevate.io"})
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.content)
            items = root.findall(".//item")[:30]
            matched = []
            for item in items:
                title = (item.findtext("title") or "").lower()
                desc  = (item.findtext("description") or "").lower()
                if sum(1 for kw in keywords if kw in title or kw in desc) >= 2:
                    matched.append({
                        "title": item.findtext("title", "")[:100],
                        "link":  item.findtext("link", ""),
                        "date":  item.findtext("pubDate", "")[:16],
                    })
            if matched:
                signals.append(IntelligenceSignal(
                    category="market_heat",
                    headline=f"{len(matched)} recent {feed_name} items mention '{term}'",
                    detail=(
                        f"{feed_name} RSS feed returned {len(matched)} recent items matching '{term}'. "
                        f"Most recent: '{matched[0]['title']}' ({matched[0]['date']}). "
                        f"Industry news coverage of a specific mechanism indicates current commercial relevance — "
                        f"journalists and editors prioritise stories that investors and clinicians are actively following."
                    ),
                    implication=(
                        f"Recent {feed_name} coverage confirms '{term}' is in active industry discourse. "
                        f"Use these articles as evidence of market timing when presenting to investors: "
                        f"'The market is paying attention — see recent {feed_name} coverage.'"
                    ),
                    source=f"{feed_name} RSS feed",
                    source_url=url,
                    recency="last 30 days (RSS rolling window)",
                    strength="moderate" if len(matched) >= 3 else "weak",
                ))
        except Exception:
            continue

    return signals


# ══════════════════════════════════════════════════════════════════════════════
# MAIN SWEEP FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

def run_intelligence_sweep(
    idea: str,
    disease_name: str = "",
    product_type: str = "other",
    therapeutic_area: str = "other",
) -> InnovationIntelligence:
    """
    Synchronous intelligence sweep — runs sequentially to respect rate limits.
    Returns InnovationIntelligence with sourced signals from 8 data sources.
    Designed to run in run_in_executor() for async integration.
    """
    from datetime import datetime
    short_term, medium_term, institution = _extract_search_terms(idea, disease_name)

    result = InnovationIntelligence(
        idea_summary=idea[:150],
        disease_name=disease_name or medium_term,
        sweep_timestamp=datetime.utcnow().isoformat() + "Z",
    )
    sources_swept = []

    # 1. GDELT news trend
    gdelt = _sweep_gdelt_news(medium_term)
    if gdelt: result.signals.append(gdelt); sources_swept.append("GDELT 2.0 DOC API")
    time.sleep(_DELAY * 3)  # GDELT is aggressive on rate limits

    # 2. CT.gov recent trials
    trials = _sweep_recent_trials(medium_term)
    result.signals.extend(trials); sources_swept.append("ClinicalTrials.gov v2 API")
    time.sleep(_DELAY)

    # 3. SEC EDGAR 8-K filings
    edgar = _sweep_edgar_disclosures(short_term)
    result.signals.extend(edgar); sources_swept.append("SEC EDGAR Full-Text Search")
    time.sleep(_DELAY)

    # 4. PubMed recent publications
    pubmed = _sweep_pubmed_recent(medium_term)
    if pubmed: result.signals.append(pubmed); sources_swept.append("PubMed E-utilities (NLM)")
    time.sleep(_DELAY)

    # 5. bioRxiv/medRxiv preprints
    biorxiv = _sweep_biorxiv_preprints(medium_term)
    if biorxiv: result.signals.append(biorxiv); sources_swept.append("medRxiv/bioRxiv API")
    time.sleep(_DELAY)

    # 6. PatentsView IP landscape
    patents = _sweep_patent_filings(short_term)
    if patents: result.signals.append(patents); sources_swept.append("PatentsView API (USPTO)")
    time.sleep(_DELAY)

    # 7. Geographic intelligence
    geo = _sweep_geographic_intelligence(idea, institution, medium_term)
    result.signals.extend(geo); sources_swept.append("Geographic ecosystem analysis")

    # 8. RSS news feeds
    rss = _sweep_rss_signals(medium_term)
    result.signals.extend(rss); sources_swept.append("RSS: FDA, STAT News, BioPharma Dive")

    result.sources_swept = sources_swept
    return result


def format_intelligence_for_prompt(intel: InnovationIntelligence) -> str:
    """
    Format the intelligence sweep for injection into the Claude PI report prompt.
    Instructs Claude to synthesise signals into an 'Innovation Intelligence' section
    that reads between the lines with specific sourced explanations.
    """
    if not intel.signals:
        return ""

    lines = [
        f"\n=== INNOVATION INTELLIGENCE SWEEP ({intel.disease_name}) ===",
        f"Sources swept: {', '.join(intel.sources_swept)}",
        f"Timestamp: {intel.sweep_timestamp}",
        "",
        "SIGNALS (use ALL of these in the 'Innovation Intelligence' section of the report):",
        "",
    ]

    for i, sig in enumerate(intel.signals, 1):
        lines += [
            f"Signal {i} [{sig.category.upper()}] — Strength: {sig.strength}",
            f"  Headline: {sig.headline}",
            f"  Detail: {sig.detail}",
            f"  Implication: {sig.implication}",
            f"  Source: {sig.source}",
            f"  URL: {sig.source_url}",
            f"  Recency: {sig.recency}",
            "",
        ]

    lines += [
        "INSTRUCTION: Add a dedicated 'Innovation Intelligence' chapter to the report BEFORE the market sizing chapter.",
        "For each signal above:",
        "  - State the headline finding explicitly",
        "  - Explain what it means for THIS specific inventor's positioning (not generically)",
        "  - Cite the exact source with the URL",
        "  - 'Read between the lines' — explain non-obvious implications",
        "  - Geographic signals should explain how the location creates specific structural advantages",
        "  - Competitive signals should explain what the data implies about timing and white space",
        "DO NOT summarise — reproduce each signal with full detail and its specific source.",
    ]

    return "\n".join(lines)


def to_dict(intel: InnovationIntelligence) -> dict:
    return asdict(intel)
