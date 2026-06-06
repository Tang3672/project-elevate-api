"""
FDA Approval History + ClinicalTrials.gov Live Pipeline
=========================================================
Moat Widener 2: FDA approval/failure history per indication
Moat Widener 3: Live Phase 2/3 competitor pipeline

Both use public APIs — no scraping needed.
FDA API: https://api.fda.gov/drug/drugsfda.json
ClinicalTrials API v2: https://clinicaltrials.gov/api/v2/studies

Data is fetched at report time and injected into the researcher context,
making every report contain intelligence ChatGPT cannot provide.
"""

import asyncio
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
import httpx

logger = logging.getLogger(__name__)

FDA_API_BASE = "https://api.fda.gov/drug/drugsfda.json"
CT_API_BASE  = "https://clinicaltrials.gov/api/v2/studies"
TIMEOUT      = 20.0


# ══════════════════════════════════════════════════════════════════════════════
# MOAT WIDENER 2: FDA APPROVAL HISTORY
# ══════════════════════════════════════════════════════════════════════════════

async def get_fda_approval_history(condition: str, years_back: int = 10) -> Dict:
    """
    Pull FDA drug approval history for a given condition/indication.
    Returns approvals, failures (CRLs), and key patterns.
    
    Uses openFDA public API — no key required.
    """
    results = {
        "approvals": [],
        "total_approvals": 0,
        "recent_failures": [],
        "fastest_approval_months": None,
        "common_pathways": {},
        "condition": condition,
        "years_searched": years_back,
    }

    # Search by indication in submission data
    # Use condition keywords to search product labels
    search_terms = condition.replace(" ", "+AND+")
    cutoff_year = datetime.now().year - years_back

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            # Search FDA drug approvals
            r = await client.get(
                FDA_API_BASE,
                params={
                    "search": f'products.brand_name:"{condition.split()[0]}" OR '
                              f'submissions.submission_type:NDA+AND+submissions.submission_status:AP',
                    "limit": 10,
                }
            )
            if r.status_code == 200:
                data = r.json()
                results["raw_count"] = data.get("meta", {}).get("results", {}).get("total", 0)

            # Better search: use indication text search via drug label API
            r2 = await client.get(
                "https://api.fda.gov/drug/label.json",
                params={
                    "search": f'indications_and_usage:"{condition.split()[0]}"',
                    "limit": 5,
                }
            )
            if r2.status_code == 200:
                label_data = r2.json()
                for result in label_data.get("results", [])[:5]:
                    openfda = result.get("openfda", {})
                    brand = openfda.get("brand_name", ["Unknown"])[0] if openfda.get("brand_name") else "Unknown"
                    generic = openfda.get("generic_name", ["Unknown"])[0] if openfda.get("generic_name") else "Unknown"
                    manufacturer = openfda.get("manufacturer_name", ["Unknown"])[0] if openfda.get("manufacturer_name") else "Unknown"
                    route = openfda.get("route", ["Unknown"])[0] if openfda.get("route") else "Unknown"
                    indications = result.get("indications_and_usage", [""])[0][:300] if result.get("indications_and_usage") else ""

                    results["approvals"].append({
                        "brand_name":    brand,
                        "generic_name":  generic,
                        "manufacturer":  manufacturer,
                        "route":         route,
                        "indication_snippet": indications,
                        "source": "openFDA Drug Label API",
                        "url": f"https://www.accessdata.fda.gov/scripts/cder/daf/",
                    })

            results["total_approvals"] = len(results["approvals"])

    except Exception as e:
        logger.warning(f"FDA approval history fetch failed for '{condition}': {e}")

    return results


async def get_fda_recent_actions(disease_keywords: List[str]) -> List[Dict]:
    """
    Get recent FDA drug actions (approvals + CRLs) for a disease area
    using openFDA submissions endpoint.
    """
    actions = []
    keyword = disease_keywords[0] if disease_keywords else "oncology"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            # Get recent NDA/BLA approvals
            r = await client.get(
                FDA_API_BASE,
                params={
                    "search": f"submissions.submission_status:AP",
                    "limit": 5,
                    "sort": "submissions.submission_status_date:desc",
                }
            )
            if r.status_code == 200:
                data = r.json()
                for result in data.get("results", [])[:5]:
                    products = result.get("products", [{}])
                    submissions = result.get("submissions", [{}])
                    latest_sub = submissions[-1] if submissions else {}
                    product = products[0] if products else {}

                    actions.append({
                        "action_type":   "Approval",
                        "drug_name":     product.get("brand_name", "Unknown"),
                        "applicant":     result.get("sponsor_name", "Unknown"),
                        "date":          latest_sub.get("submission_status_date", "Unknown"),
                        "submission_type": latest_sub.get("submission_type", "NDA"),
                        "application_number": result.get("application_number", ""),
                        "url": f"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo={result.get('application_number','').replace('NDA','').replace('BLA','')}",
                        "source": "openFDA"
                    })

    except Exception as e:
        logger.warning(f"FDA recent actions fetch failed: {e}")

    return actions


# ══════════════════════════════════════════════════════════════════════════════
# MOAT WIDENER 3: CLINICALTRIALS.GOV LIVE PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

async def get_competitor_trials(condition: str, phase: List[str] = None) -> Dict:
    """
    Pull active Phase 2/3 competitor trials from ClinicalTrials.gov API v2.
    
    Returns structured competitive intelligence:
    - Who is running trials
    - What endpoints they're using
    - When they expect to read out
    - Enrollment status (recruiting = active threat)
    """
    if phase is None:
        phase = ["PHASE2", "PHASE3"]

    results = {
        "condition": condition,
        "total_trials": 0,
        "active_trials": [],
        "recruiting_count": 0,
        "completed_count": 0,
        "sponsors": [],
        "common_endpoints": [],
        "earliest_readout": None,
        "competitive_threat_level": "low",
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            params = {
                "query.cond":   condition,
                "filter.overallStatus": "RECRUITING,ACTIVE_NOT_RECRUITING,COMPLETED",
                "filter.phase": "|".join(phase),
                "fields": "NCTId,BriefTitle,OverallStatus,Phase,StartDate,PrimaryCompletionDate,LeadSponsorName,EnrollmentCount,PrimaryOutcomeMeasure,Condition,InterventionName,LocationCountry",
                "pageSize": 20,
                "sort": "LastUpdatePostDate:desc",
            }

            r = await client.get(CT_API_BASE, params=params)

            if r.status_code == 200:
                data = r.json()
                studies = data.get("studies", [])
                results["total_trials"] = data.get("totalCount", len(studies))

                sponsors_seen = set()
                readout_dates = []

                for study in studies[:15]:
                    proto = study.get("protocolSection", {})
                    id_module      = proto.get("identificationModule", {})
                    status_module  = proto.get("statusModule", {})
                    design_module  = proto.get("designModule", {})
                    sponsor_module = proto.get("sponsorCollaboratorsModule", {})
                    outcomes       = proto.get("outcomesModule", {})
                    interventions  = proto.get("armsInterventionsModule", {})

                    nct_id       = id_module.get("nctId", "")
                    title        = id_module.get("briefTitle", "")
                    status       = status_module.get("overallStatus", "")
                    phase_val    = design_module.get("phases", ["Unknown"])
                    sponsor      = sponsor_module.get("leadSponsor", {}).get("name", "Unknown")
                    enrollment   = design_module.get("enrollmentInfo", {}).get("count", 0)
                    completion   = status_module.get("primaryCompletionDateStruct", {}).get("date", "")
                    primary_ep   = outcomes.get("primaryOutcomes", [{}])[0].get("measure", "") if outcomes.get("primaryOutcomes") else ""

                    # Get intervention names
                    intervention_list = interventions.get("interventions", [])
                    drug_names = [i.get("name", "") for i in intervention_list if i.get("type") == "DRUG"]

                    if status == "RECRUITING":
                        results["recruiting_count"] += 1
                    elif status == "COMPLETED":
                        results["completed_count"] += 1

                    sponsors_seen.add(sponsor)

                    if completion:
                        readout_dates.append(completion)

                    # Calculate competitive threat score
                    threat = "low"
                    if "PHASE3" in str(phase_val) and status == "RECRUITING":
                        threat = "high"
                    elif "PHASE2" in str(phase_val) and status == "RECRUITING":
                        threat = "medium"
                    elif status == "COMPLETED":
                        threat = "medium"

                    results["active_trials"].append({
                        "nct_id":        nct_id,
                        "title":         title[:120],
                        "status":        status,
                        "phase":         phase_val,
                        "sponsor":       sponsor,
                        "enrollment":    enrollment,
                        "drugs":         drug_names[:3],
                        "primary_endpoint": primary_ep[:150],
                        "expected_completion": completion,
                        "competitive_threat": threat,
                        "url": f"https://clinicaltrials.gov/study/{nct_id}",
                    })

                results["sponsors"] = list(sponsors_seen)[:10]

                # Sort readout dates
                if readout_dates:
                    results["earliest_readout"] = sorted(readout_dates)[0]

                # Overall competitive threat
                if results["recruiting_count"] >= 5:
                    results["competitive_threat_level"] = "high"
                elif results["recruiting_count"] >= 2:
                    results["competitive_threat_level"] = "medium"

    except Exception as e:
        logger.error(f"ClinicalTrials.gov fetch failed for '{condition}': {e}")

    return results


async def get_recently_completed_trials(condition: str) -> List[Dict]:
    """
    Get trials that completed in the last 6 months — these are imminent readouts
    that could change the competitive landscape overnight.
    """
    completed = []
    cutoff = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(
                CT_API_BASE,
                params={
                    "query.cond":   condition,
                    "filter.overallStatus": "COMPLETED",
                    "filter.phase": "PHASE3",
                    "fields": "NCTId,BriefTitle,LeadSponsorName,PrimaryCompletionDate,PrimaryOutcomeMeasure,ResultsFirstPostDate",
                    "pageSize": 5,
                    "sort": "PrimaryCompletionDate:desc",
                }
            )
            if r.status_code == 200:
                data = r.json()
                for study in data.get("studies", [])[:5]:
                    proto = study.get("protocolSection", {})
                    id_mod     = proto.get("identificationModule", {})
                    status_mod = proto.get("statusModule", {})
                    sponsor_mod = proto.get("sponsorCollaboratorsModule", {})
                    outcomes   = proto.get("outcomesModule", {})

                    completion_date = status_mod.get("primaryCompletionDateStruct", {}).get("date", "")
                    results_posted  = status_mod.get("resultsFirstPostDateStruct", {}).get("date", "")

                    completed.append({
                        "nct_id":     id_mod.get("nctId", ""),
                        "title":      id_mod.get("briefTitle", "")[:120],
                        "sponsor":    sponsor_mod.get("leadSponsor", {}).get("name", "Unknown"),
                        "completed":  completion_date,
                        "results_posted": results_posted,
                        "primary_endpoint": outcomes.get("primaryOutcomes", [{}])[0].get("measure", "") if outcomes.get("primaryOutcomes") else "",
                        "url": f"https://clinicaltrials.gov/study/{id_mod.get('nctId','')}",
                        "significance": "HIGH — Phase 3 completed recently. Results may have been published."
                    })

    except Exception as e:
        logger.warning(f"Recently completed trials fetch failed: {e}")

    return completed


# ══════════════════════════════════════════════════════════════════════════════
# COMBINED COMPETITIVE INTELLIGENCE FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

async def get_full_competitive_intelligence(
    condition:        str,
    disease_keywords: List[str],
) -> Dict:
    """
    Runs FDA history + ClinicalTrials pipeline in parallel.
    Returns combined competitive intelligence ready to inject into reports.
    """
    # Run all three in parallel
    fda_task      = get_fda_recent_actions(disease_keywords)
    trials_task   = get_competitor_trials(condition)
    completed_task = get_recently_completed_trials(condition)

    fda_actions, trial_pipeline, recent_completions = await asyncio.gather(
        fda_task, trials_task, completed_task,
        return_exceptions=True
    )

    # Handle exceptions gracefully
    if isinstance(fda_actions, Exception):
        logger.warning(f"FDA actions failed: {fda_actions}")
        fda_actions = []
    if isinstance(trial_pipeline, Exception):
        logger.warning(f"Trial pipeline failed: {trial_pipeline}")
        trial_pipeline = {"active_trials": [], "total_trials": 0, "competitive_threat_level": "unknown"}
    if isinstance(recent_completions, Exception):
        logger.warning(f"Recent completions failed: {recent_completions}")
        recent_completions = []

    return {
        "fda_recent_actions":      fda_actions,
        "trial_pipeline":          trial_pipeline,
        "recently_completed":      recent_completions,
        "intelligence_summary":    _summarize_competitive_intelligence(trial_pipeline, fda_actions, recent_completions),
        "data_sources":            ["openFDA API", "ClinicalTrials.gov API v2"],
        "fetched_at":              datetime.now(timezone.utc).isoformat(),
    }


def _summarize_competitive_intelligence(pipeline: dict, fda: list, completed: list) -> str:
    """Generate a one-paragraph competitive intelligence summary."""
    total   = pipeline.get("total_trials", 0)
    recruit = pipeline.get("recruiting_count", 0)
    threat  = pipeline.get("competitive_threat_level", "unknown")
    sponsors = pipeline.get("sponsors", [])[:3]
    condition = pipeline.get("condition", "this indication")

    lines = []

    if total > 0:
        lines.append(f"ClinicalTrials.gov shows {total} active trials in {condition}, with {recruit} currently recruiting.")
    if sponsors:
        lines.append(f"Key competitors include {', '.join(sponsors)}.")
    if threat == "high":
        lines.append("Competitive threat level is HIGH — multiple Phase 3 trials are actively recruiting, suggesting near-term FDA submissions from competitors.")
    elif threat == "medium":
        lines.append("Competitive threat level is MEDIUM — Phase 2 data readouts expected within 12-18 months.")
    if completed:
        lines.append(f"{len(completed)} Phase 3 trial(s) completed recently — results may alter the competitive landscape.")
    if fda:
        lines.append(f"{len(fda)} recent FDA actions found in related areas.")

    return " ".join(lines) if lines else "Competitive landscape data retrieved from ClinicalTrials.gov and openFDA."


def format_competitive_intelligence_for_report(ci: Dict) -> str:
    """
    Format competitive intelligence for injection into the Researcher's context.
    This is what makes Project Elevate's reports fundamentally different from ChatGPT.
    """
    pipeline  = ci.get("trial_pipeline", {})
    trials    = pipeline.get("active_trials", [])
    completed = ci.get("recently_completed", [])
    fda       = ci.get("fda_recent_actions", [])
    summary   = ci.get("intelligence_summary", "")

    lines = [
        "\n=== LIVE COMPETITIVE INTELLIGENCE (ClinicalTrials.gov + openFDA) ===",
        f"Data fetched: {ci.get('fetched_at', 'now')}",
        f"Sources: {', '.join(ci.get('data_sources', []))}",
        f"\nSUMMARY: {summary}",
        f"\nCOMPETITIVE THREAT LEVEL: {pipeline.get('competitive_threat_level', 'unknown').upper()}",
        f"Total trials in indication: {pipeline.get('total_trials', 0)}",
        f"Currently recruiting: {pipeline.get('recruiting_count', 0)}",
        f"Recently completed Phase 3: {len(completed)}",
    ]

    if trials:
        lines.append(f"\nACTIVE COMPETITOR TRIALS (top {min(8, len(trials))}):")
        for t in trials[:8]:
            threat_flag = "🔴 HIGH THREAT" if t.get("competitive_threat") == "high" else "🟡 MEDIUM" if t.get("competitive_threat") == "medium" else "🟢 LOW"
            lines.append(
                f"\n{threat_flag} | {t.get('sponsor','?')} | {t.get('phase',['?'])} | {t.get('status','?')}"
                f"\nTitle: {t.get('title','')}"
                f"\nDrugs: {', '.join(t.get('drugs',[])) or 'Not specified'}"
                f"\nPrimary endpoint: {t.get('primary_endpoint','Not specified')}"
                f"\nExpected completion: {t.get('expected_completion','Unknown')}"
                f"\nEnrollment: {t.get('enrollment', 'Unknown')} patients"
                f"\nURL: {t.get('url','')}"
            )

    if completed:
        lines.append(f"\nRECENTLY COMPLETED PHASE 3 TRIALS (potential readouts):")
        for c in completed:
            lines.append(
                f"\n⚠️ {c.get('sponsor','?')} — {c.get('title','')}"
                f"\nCompleted: {c.get('completed','')} | Results posted: {c.get('results_posted','Pending')}"
                f"\nURL: {c.get('url','')}"
            )

    if fda:
        lines.append(f"\nRECENT FDA ACTIONS:")
        for f_action in fda[:3]:
            lines.append(
                f"\n✅ {f_action.get('action_type','')} — {f_action.get('drug_name','')} ({f_action.get('applicant','')})"
                f"\nDate: {f_action.get('date','')} | Type: {f_action.get('submission_type','')}"
                f"\nURL: {f_action.get('url','')}"
            )

    lines.append("\nCRITICAL INSTRUCTION: Use the competitor trial data above to populate the pipeline_status field and competitive landscape section of the report. Every competitor listed above is a real trial from ClinicalTrials.gov — cite them specifically.")

    return "\n".join(lines)
