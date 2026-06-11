"""
Funding Intelligence Service — real-time biotech fundraising signals
=====================================================================
PitchBook charges $24k/user/year partly for "who just raised in your space."
This service replicates that from FREE public data:

  1. NIH SBIR/STTR new awards (NIH Reporter API — free, real-time)
     Companies that just won SBIR/STTR = credible early-stage competitors
     who are 12-24 months behind or ahead of you in the same space.

  2. SEC EDGAR 8-K filings with "private placement" or "securities offering"
     + disease keywords = companies that just closed a private round and
     disclosed it (required within 4 days of closing for material events).

  3. bioRxiv/medRxiv preprint velocity = research momentum signal.
     High preprint volume = many groups are approaching commercialization.
     Active preprint authors are often co-founders of stealth startups.

  4. ClinicalTrials.gov sponsor debut = new company entered the space.
     When a new company registers their first trial for a disease, that's
     effectively a funding signal — they've raised enough to run trials.

Free API sources:
  - NIH Reporter: api.reporter.nih.gov — no key required
  - SEC EDGAR EFTS: efts.sec.gov — no key required
  - ClinicalTrials.gov: clinicaltrials.gov/api — no key required
  - bioRxiv API: api.biorxiv.org — no key required
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional
import httpx

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 1. NIH SBIR/STTR recent awards — free, real-time
# ─────────────────────────────────────────────────────────────────────────────

async def get_recent_sbir_awards(disease_name: str, months_back: int = 12) -> list[dict]:
    """
    Pull recent SBIR/STTR awards for a disease from NIH Reporter (free API).
    Returns: list of {company, amount, project_title, fy, activity_code, pi_name}
    """
    from_year = (datetime.now() - timedelta(days=months_back * 30)).year
    url = "https://api.reporter.nih.gov/v2/projects/search"
    # Use disease keywords in project terms search
    keywords = disease_name.replace("(", "").replace(")", "").replace("/", " ").split()[:4]
    query_text = " ".join(keywords[:3])

    payload = {
        "criteria": {
            "project_terms": query_text,
            "activity_codes": ["R43", "R44", "R41", "R42"],  # SBIR/STTR codes
            "fiscal_years": list(range(from_year, datetime.now().year + 1)),
        },
        "offset": 0,
        "limit": 10,
        "sort_field": "award_amount",
        "sort_order": "desc",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload)
            if r.status_code != 200:
                return []
            data = r.json()
            awards = []
            for proj in data.get("results", [])[:8]:
                org = proj.get("organization", {})
                company = org.get("org_name", "") or "Unknown org"
                amount = proj.get("award_amount", 0) or 0
                title = proj.get("project_title", "")[:120]
                fy = proj.get("fiscal_year", "")
                code = proj.get("activity_code", "")
                pi_profiles = proj.get("principal_investigators", [])
                pi_name = pi_profiles[0].get("profile_id", "") if pi_profiles else ""
                if company and title:
                    awards.append({
                        "company":       company,
                        "amount_usd":    amount,
                        "project_title": title,
                        "fiscal_year":   fy,
                        "grant_type":    code,
                        "pi":            pi_name,
                        "source":        "NIH SBIR/STTR (Reporter API)",
                    })
            logger.info("NIH SBIR awards: %d recent awards for '%s'", len(awards), disease_name)
            return awards
    except Exception as e:
        logger.warning("NIH SBIR fetch failed (non-fatal): %s", e)
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 2. SEC EDGAR 8-K private placements — free, real-time
# ─────────────────────────────────────────────────────────────────────────────

async def get_recent_fundraises_from_edgar(disease_name: str, days_back: int = 180) -> list[dict]:
    """
    Search SEC EDGAR for 8-K filings containing disease keywords + financing terms.
    8-Ks are filed within 4 business days of material events including private placements.
    Returns: list of {company, date, filing_type, excerpt, url}
    """
    from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    keywords = disease_name.replace("(", "").replace(")", "").split()[:3]
    search_term = " ".join(keywords[:2])  # keep it focused

    # Combine disease name with financing signals
    financing_terms = [
        f'"{search_term}" "private placement"',
        f'"{search_term}" "Securities Purchase Agreement"',
        f'"{search_term}" "registered direct"',
    ]

    results = []
    url = "https://efts.sec.gov/LATEST/search-index"

    async with httpx.AsyncClient(timeout=10.0) as client:
        for term in financing_terms[:2]:  # limit to 2 to stay fast
            try:
                r = await client.get(url, params={
                    "q": term,
                    "dateRange": "custom",
                    "startdt": from_date,
                    "forms": "8-K",
                    "_source": "file_date,period_of_report,display_names,form_type",
                })
                if r.status_code != 200:
                    continue
                data = r.json()
                for hit in data.get("hits", {}).get("hits", [])[:4]:
                    src = hit.get("_source", {})
                    names = src.get("display_names", [])
                    company = names[0] if names else "Unknown"
                    filing_date = src.get("file_date", "")
                    edgar_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=8-K&dateb=&owner=include&count=40&search_text="
                    results.append({
                        "company":      company,
                        "date":         filing_date,
                        "filing_type":  "8-K",
                        "signal":       "Private placement / securities offering",
                        "source":       "SEC EDGAR 8-K",
                        "url":          edgar_url,
                    })
            except Exception as e:
                logger.debug("EDGAR fundraise fetch failed for term '%s': %s", term[:30], e)

    logger.info("SEC EDGAR fundraises: %d recent signals for '%s'", len(results), disease_name)
    return results[:6]


# ─────────────────────────────────────────────────────────────────────────────
# 3. bioRxiv preprint velocity — research momentum = pre-commercialization signal
# ─────────────────────────────────────────────────────────────────────────────

async def get_preprint_velocity(disease_name: str, days_back: int = 90) -> dict:
    """
    Count recent preprints on bioRxiv/medRxiv for a disease.
    High velocity = many groups approaching commercialization.
    Authors with multiple preprints = likely co-founders of stealth startups.
    Returns: {count, recent_titles, top_authors, velocity_signal}
    """
    keywords = disease_name.replace("(", "").replace(")", "").split()[:3]
    query = "+".join(keywords[:2])
    from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    to_date   = datetime.now().strftime("%Y-%m-%d")

    results = {"count": 0, "recent_titles": [], "top_authors": [], "velocity_signal": "LOW"}

    for server in ["medrxiv", "biorxiv"]:
        url = f"https://api.biorxiv.org/details/{server}/{from_date}/{to_date}/0/json"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(url)
                if r.status_code != 200:
                    continue
                data = r.json()
                papers = data.get("collection", [])
                # Filter by keyword in title/abstract
                relevant = [
                    p for p in papers
                    if any(kw.lower() in (p.get("title", "") + p.get("abstract", "")).lower()
                           for kw in keywords[:2])
                ][:10]
                results["count"] += len(relevant)
                for p in relevant[:3]:
                    results["recent_titles"].append({
                        "title":   p.get("title", "")[:100],
                        "authors": p.get("authors", "")[:60],
                        "date":    p.get("date", ""),
                        "server":  server,
                        "doi":     p.get("doi", ""),
                    })
        except Exception as e:
            logger.debug("bioRxiv fetch failed for %s: %s", server, e)

    count = results["count"]
    results["velocity_signal"] = (
        "HIGH (>10 preprints in 90 days — many groups racing)" if count > 10
        else "MODERATE (5-10 preprints)" if count > 4
        else "LOW (<5 preprints — less crowded space)"
    )
    logger.info("Preprint velocity: %d papers for '%s' in %d days", count, disease_name, days_back)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 4. ClinicalTrials.gov first-time sponsors — "new company entered your space"
# ─────────────────────────────────────────────────────────────────────────────

async def get_new_entrants(disease_name: str, days_back: int = 365) -> list[dict]:
    """
    Find companies that registered their FIRST trial for a disease in the last year.
    A first trial = they've raised money and are now a direct competitor.
    Uses ClinicalTrials.gov v2 API (free, no key).
    """
    from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    url = "https://clinicaltrials.gov/api/v2/studies"
    params = {
        "query.cond": disease_name[:60],
        "filter.advanced": f"AREA[StartDate]RANGE[{from_date}, MAX]",
        "fields": "NCTId,OfficialTitle,LeadSponsorName,StartDate,Phase,OverallStatus",
        "pageSize": 20,
        "format": "json",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, params=params)
            if r.status_code != 200:
                return []
            data = r.json()
            studies = data.get("studies", [])
            sponsors = set()
            new_entrants = []
            for s in studies:
                proto = s.get("protocolSection", {})
                ident = proto.get("identificationModule", {})
                sponsor_mod = proto.get("sponsorCollaboratorsModule", {})
                status_mod = proto.get("statusModule", {})
                sponsor = sponsor_mod.get("leadSponsor", {}).get("name", "")
                nct = ident.get("nctId", "")
                title = ident.get("officialTitle", "")[:100]
                start = status_mod.get("startDateStruct", {}).get("date", "")
                phase = proto.get("designModule", {}).get("phases", ["?"])[0] if proto.get("designModule") else "?"
                if sponsor and sponsor not in sponsors:
                    sponsors.add(sponsor)
                    new_entrants.append({
                        "sponsor": sponsor,
                        "nct_id":  nct,
                        "title":   title,
                        "start_date": start,
                        "phase":   phase,
                        "source":  "ClinicalTrials.gov",
                    })
            logger.info("New trial entrants: %d for '%s'", len(new_entrants), disease_name)
            return new_entrants[:8]
    except Exception as e:
        logger.warning("ClinicalTrials new entrants failed (non-fatal): %s", e)
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Main aggregator
# ─────────────────────────────────────────────────────────────────────────────

async def get_funding_intelligence(disease_name: str) -> dict:
    """
    Aggregate all funding signals for a disease area in parallel.
    Returns structured data for report injection.
    """
    sbir, edgar, preprints, entrants = await asyncio.gather(
        get_recent_sbir_awards(disease_name),
        get_recent_fundraises_from_edgar(disease_name),
        get_preprint_velocity(disease_name),
        get_new_entrants(disease_name),
        return_exceptions=True,
    )

    return {
        "sbir_awards":    sbir    if not isinstance(sbir, Exception)     else [],
        "edgar_signals":  edgar   if not isinstance(edgar, Exception)    else [],
        "preprints":      preprints if not isinstance(preprints, Exception) else {},
        "new_entrants":   entrants if not isinstance(entrants, Exception) else [],
    }


def format_funding_intelligence(data: dict, disease_name: str) -> str:
    """Format funding signals as a context block for the report."""
    lines = [
        "=== COMPETITIVE FUNDING INTELLIGENCE (free public data) ===",
        f"Real-time funding signals for companies active in: {disease_name}",
        "",
    ]

    # SBIR awards
    sbir = data.get("sbir_awards", [])
    if sbir:
        lines.append("RECENT NIH SBIR/STTR AWARDS (direct competitors just received federal funding):")
        for a in sbir[:5]:
            amt = f"${a['amount_usd']:,}" if a.get("amount_usd") else "undisclosed"
            lines.append(f"  • {a['company']} | {a['grant_type']} | {amt} | FY{a['fiscal_year']}")
            lines.append(f"    Project: {a['project_title']}")
        lines.append("")

    # New trial entrants
    entrants = data.get("new_entrants", [])
    if entrants:
        lines.append("NEW COMPANIES ENTERING THIS SPACE (first trial registered in past year):")
        for e in entrants[:5]:
            lines.append(f"  • {e['sponsor']} | {e['phase']} | Started: {e['start_date']} | {e['nct_id']}")
        lines.append("")

    # EDGAR fundraising signals
    edgar = data.get("edgar_signals", [])
    if edgar:
        lines.append("RECENT FUNDRAISING (SEC 8-K filings — private placements in this space):")
        for s in edgar[:4]:
            lines.append(f"  • {s['company']} | {s['date']} | {s['signal']}")
        lines.append("")

    # Preprint velocity
    pre = data.get("preprints", {})
    if pre:
        lines += [
            f"RESEARCH MOMENTUM (bioRxiv/medRxiv preprint velocity):",
            f"  {pre.get('count', 0)} preprints in last 90 days → {pre.get('velocity_signal', 'unknown')}",
        ]
        for t in pre.get("recent_titles", [])[:2]:
            lines.append(f"  • {t['title'][:80]} — {t['authors'][:40]} ({t['date']})")
        lines.append("")

    lines.append("=== END FUNDING INTELLIGENCE ===")
    return "\n".join(lines)
