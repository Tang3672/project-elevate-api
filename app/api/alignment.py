from datetime import datetime
"""
Alignment API v2
================
POST /api/v1/alignment/check        — legacy (original inventors, returns AlignmentReport)
POST /api/v1/alignment/pi-report    — new PI endpoint (returns full PIReport with
                                      market sizing, regulatory pathway, disease intel)
GET  /api/v1/alignment/examples     — example ideas
"""

import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional

from app.services.alignment_service import generate_alignment_report, generate_pi_report
from app.api.auth import get_current_user, get_optional_user
from app.models.alignment import AlignmentReport, PIReport

logger = logging.getLogger(__name__)
router = APIRouter()


# ── G.2 Cross-run contamination guard ────────────────────────────────────────

import re as _re

def _camel_split(word: str) -> list[str]:
    """Split a CamelCase or snake_case word into lowercase components."""
    parts = _re.sub(r"([A-Z])", r" \1", word).split()
    return [p.lower() for p in parts if p]


def _sanitize_product_name(product_name: str | None, idea: str) -> str | None:
    """
    Guard against cross-run state leakage where the frontend sends a stale
    product_name from a prior generation alongside a different idea.

    Logic: if product_name is provided and NONE of its significant sub-words appear
    in the idea text, it is foreign to this request and must be cleared.
    The alignment service then derives product_name from the idea text instead.

    Handles CamelCase names (NeuroSync → ['neuro', 'sync']) and space-separated words.
    Sub-words under 4 characters are skipped (articles, prepositions, etc.).
    """
    if not product_name:
        return product_name
    idea_lower = (idea or "").lower()
    # Extract all significant sub-words: split on spaces, then camel-case each token
    all_sub_words: list[str] = []
    for token in product_name.split():
        all_sub_words.extend(_camel_split(token))
    sig_words = [w for w in all_sub_words if len(w) >= 4]
    if not sig_words:
        return product_name  # very short name — can't validate; pass through
    matched = sum(1 for w in sig_words if w in idea_lower)
    if matched == 0:
        logger.warning(
            "G.2: product_name %r has no word overlap with idea — "
            "clearing to prevent cross-run contamination (idea[:80]=%r)",
            product_name, idea[:80],
        )
        return None
    return product_name


class AlignmentRequest(BaseModel):
    idea: str = Field(..., min_length=30, max_length=2000)


class PIReportRequest(BaseModel):
    idea: str = Field(..., min_length=30, max_length=2000,
        description="Description of the product — what it does, who it's for, what it solves")
    product_type: str = Field(default="other",
        description="antibiotic | medical_device | software | diagnostic | other")
    funding_pathway: Optional[str] = Field(default="commercial",
        description="commercial | sbir | basic_science — controls report framing")
    target_pathogen: Optional[str] = Field(default=None,
        description="For antibiotics: primary target pathogen (e.g. MRSA, CRE, C. difficile)")
    disease_domain: str = Field(default="auto",
        description="auto | antibiotic_amr | oncology | cardiology | neurology_cns | metabolic_diabetes | mental_health")
    tier1_category: str = Field(default="drug_small_molecule",
        description="drug_small_molecule | biologic | gene_cell_therapy | medical_device | diagnostic | digital_health | vaccine_immunotherapy | other_platform")
    product_name: Optional[str] = Field(default=None,
        description="Short brand / working name (e.g. 'NeuroSense'). If omitted, derived from idea text.")
    institution: Optional[str] = Field(default=None,
        description="Originating institution (e.g. 'University of Michigan', 'NIH NIBIB').")
    domain: Optional[str] = Field(default=None,
        description="LIFE_SCIENCES_CLINICAL | LIFE_SCIENCES_RESEARCH | ENGINEERING_HARDWARE | SOFTWARE_INFRASTRUCTURE | ENERGY_CLIMATE | OTHER_DEEP_TECH. Auto-detected if omitted.")
    clarify_answers: Optional[dict] = Field(default=None,
        description="Structured answers from /clarify intake questions, keyed by binds_to field (e.g. 'seg.target_lab_count': '1,000-5,000 labs'). Used to override default market sizing parameters.")


@router.post("/check", response_model=AlignmentReport)
async def check_alignment(payload: AlignmentRequest):
    """Legacy endpoint — returns original scored AlignmentReport."""
    try:
        return await generate_alignment_report(payload.idea)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Alignment failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


_DEV_EMAILS = {"test@projectelevate.io", "ijw91021@gmail.com",
               "admin@projectelevate.io", "oneonesie100@gmail.com",
               "lizpeek11@gmail.com", "peek@wustl.edu"}
_PLAN_LIMITS = {
    "basic":        5,    # Explorer $49
    "starter":      20,   # Innovator $149
    "professional": None,  # Institution $799 — unlimited
    "active":       None,
    "trialing":     None,
}


async def _enforce_quota(current_user):
    """Server-side quota gate (BEFORE calling Claude). Raises HTTPException(402)
    if over limit. Frontend checks are UX only; this is the real gate."""
    try:
        if current_user and current_user.get("email") not in _DEV_EMAILS:
            from app.db.user_repository import get_user_by_id
            user = await get_user_by_id(current_user["id"])
            if user:
                sub_status = user.get("subscription_status", "none")
                plan       = user.get("plan", "none")
                used       = user.get("free_reports_used", 0) or 0
                limit      = _PLAN_LIMITS.get(plan) or _PLAN_LIMITS.get(sub_status)

                # Early-access period: grant 10 free analyses to waitlist members.
                on_waitlist = False
                try:
                    from app.db.database import get_pool
                    pool = await get_pool()
                    async with pool.acquire() as conn:
                        wl = await conn.fetchrow(
                            "SELECT id FROM waitlist WHERE lower(email)=lower($1)",
                            current_user.get("email", ""))
                        on_waitlist = bool(wl)
                except Exception:
                    pass
                if on_waitlist and used < 10:
                    limit = 10

                if limit is not None and used >= limit:
                    raise HTTPException(status_code=402, detail={
                        "error": "quota_exceeded",
                        "message": f"You've used all {limit} analyses on your plan. Upgrade to continue.",
                        "used": used, "limit": limit,
                    })
    except HTTPException:
        raise
    except Exception as quota_e:
        logger.warning("Quota check failed (non-fatal): %s", quota_e)


async def _increment_usage(current_user):
    try:
        if current_user and current_user.get("email") not in _DEV_EMAILS:
            from app.db.user_repository import get_user_by_id, increment_free_report_count
            user = await get_user_by_id(current_user["id"])
            status = user.get("subscription_status", "none") if user else "none"
            if status not in ("active", "trialing"):
                await increment_free_report_count(current_user["id"])
    except Exception as inc_e:
        logger.warning(f"Failed to increment report count: {inc_e}")


def _idea_from_payload(payload: "PIReportRequest") -> str:
    idea = payload.idea
    if payload.target_pathogen:
        idea = f"{idea}\n\nTarget pathogen: {payload.target_pathogen}"
    return idea


@router.post("/pi-report", response_model=PIReport)
async def get_pi_report(payload: PIReportRequest, current_user = Depends(get_current_user)):
    """Full PI go-to-market intelligence report (synchronous). Kept for backward
    compatibility; the frontend now uses the async pair below to avoid proxy
    timeouts on the ~2-3 minute generation."""
    await _enforce_quota(current_user)
    try:
        idea = _idea_from_payload(payload)
        report = await generate_pi_report(
            idea, payload.product_type, payload.disease_domain,
            payload.tier1_category, funding_pathway=payload.funding_pathway,
            product_name=_sanitize_product_name(payload.product_name, idea),
            institution=payload.institution,
            domain=payload.domain, clarify_answers=payload.clarify_answers,
        )
        await _increment_usage(current_user)
        return report
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"PI report failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pi-report/async")
async def get_pi_report_async(payload: PIReportRequest, current_user = Depends(get_current_user)):
    """Start report generation in the background; returns a job_id immediately so
    the client never holds a long request open. Poll /pi-report/status/{job_id}."""
    await _enforce_quota(current_user)   # synchronous gate — 402 returns instantly
    import asyncio
    from app.services.report_jobs import create_job, set_done, set_error, update_report
    _owner_id = str((current_user or {}).get("id", "")) or None
    job_id = await create_job(owner_id=_owner_id)
    idea = _idea_from_payload(payload)
    _user = current_user

    async def _run():
        try:
            # Phase 1: core report WITHOUT the slow verification — deliver it fast.
            report = await generate_pi_report(
                idea, payload.product_type, payload.disease_domain,
                payload.tier1_category, funding_pathway=payload.funding_pathway,
                user_id=(_user or {}).get("id"), skip_verification=True,
                product_name=_sanitize_product_name(payload.product_name, idea),
                institution=payload.institution,
                domain=payload.domain, clarify_answers=payload.clarify_answers,
            )
            rd = report.model_dump(mode="json")
            try:
                from app.services.url_validator import clean_report_urls
                logger.info("URL validation: %s", await clean_report_urls(rd))
            except Exception as _u:
                logger.warning("URL validation skipped (non-fatal): %s", _u)
            await set_done(job_id, rd)            # report is now viewable
            await _increment_usage(_user)

            # Part C: persist buyer-model baseline (version 1) for editable recompute
            try:
                _msd = getattr(report, "market_sizing_derivation", None)
                if _msd:
                    from app.db.market_model_repository import init_market_model_table, save_baseline
                    await init_market_model_table()
                    _nodes = {
                        k: _msd.get(k)
                        for k in ("pop_lo", "pop_hi", "sp_lo", "sp_hi",
                                  "sam_lo", "sam_hi", "som_lo", "som_hi",
                                  "pop_src", "sp_src", "key_assumptions",
                                  "archetype", "idea", "us_tam_usd", "us_sam_usd", "us_som_usd")
                        if _msd.get(k) is not None
                    }
                    _nodes["_full_derivation"] = _msd
                    # Item 9: freeze commercialization signals so recommendation can recompute on edit
                    _cs_raw = getattr(report, "commercialization_scores", None) or {}
                    _comm_sigs = _cs_raw.get("_input_signals") if isinstance(_cs_raw, dict) else None
                    if _comm_sigs:
                        _nodes["_comm_signals"] = _comm_sigs
                    await save_baseline(job_id, _nodes)
                    logger.info("Part C: buyer-model baseline saved for job %s", job_id)
            except Exception as _mmc_e:
                logger.warning("Part C: baseline save failed (non-fatal): %s", _mmc_e)

            # Phase 2: run verification (validation + trust + self-correction) in the
            # background, then patch the job so the badges fill in client-side.
            try:
                from app.services.alignment_service import run_report_verification, attach_competitive_landscape, _enforce_market_consistency
                await attach_competitive_landscape(report)   # reliable server-side sweep
                await run_report_verification(report)
                # Re-enforce market consistency after verification: self-correction can
                # rewrite market_sizing from a fresh LLM call, losing the derivation values.
                try:
                    _msd2 = getattr(report, "market_sizing_derivation", None)
                    if _msd2 and isinstance(_msd2, dict):
                        class _DerivProxy:
                            def __init__(self, d):
                                self.__dict__.update(d)
                        _enforce_market_consistency(report, _DerivProxy(_msd2))
                except Exception as _re_e:
                    logger.warning("Post-verification market re-enforcement failed (non-fatal): %s", _re_e)
                rd2 = report.model_dump(mode="json")
                try:
                    from app.services.url_validator import clean_report_urls
                    await clean_report_urls(rd2)   # corrected sections may add URLs
                except Exception:
                    pass
                await update_report(job_id, rd2)
            except Exception as _ve:
                logger.warning("Background verification failed (non-fatal): %s", _ve)
        except ValueError as e:
            await set_error(job_id, str(e))
        except asyncio.CancelledError:
            # Railway container restart killed the task — mark the job as failed so
            # the frontend can show an actionable error instead of timing out silently.
            logger.warning("Async PI report task cancelled (container restart?): job=%s", job_id)
            await set_error(job_id, "Report generation was interrupted by a server restart. Please try again.")
            raise   # re-raise so asyncio can clean up normally
        except Exception as e:
            logger.error(f"Async PI report failed: {e}", exc_info=True)
            await set_error(job_id, str(e))

    asyncio.create_task(_run())
    return {"job_id": job_id, "status": "running"}


@router.get("/pi-report/status/{job_id}")
async def get_pi_report_status(job_id: str, current_user = Depends(get_current_user)):
    """Poll an async report job. Returns {status: running|done|error, report?, error?}.
    Requires the caller to be the job owner (or unauthenticated jobs are readable by anyone)."""
    from app.services.report_jobs import get_job
    job = await get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    # Ownership check: if the job has an owner, only that user may read it.
    owner_id = job.get("owner_id")
    if owner_id:
        caller_id = str((current_user or {}).get("id", "")) or None
        if caller_id != owner_id:
            raise HTTPException(status_code=403, detail="Not authorised to view this report")
    return {"status": job["status"], "report": job["report"], "error": job["error"]}


@router.get("/world-graph")
async def get_world_graph(disease: str):
    """Commercialization world-model subgraph for a disease (P4): nodes + edges
    accumulated across all reports. Powers the graph visualization."""
    from app.services.world_model_graph import get_disease_subgraph
    return await get_disease_subgraph(disease)


# ── Outcome / feedback learning (P11) + evaluation dashboard (P10) ──────────────

class FeedbackRequest(BaseModel):
    report_id:         str
    user_action:       Optional[str] = None   # accepted | rejected | edited | ignored
    outcome:           Optional[str] = None   # patented | licensed | grant_funded | spun_out | deprioritized | ...
    recommendation_id: Optional[str] = None
    notes:             Optional[str] = None
    outcome_date:      Optional[str] = None   # ISO date
    institution_id:    Optional[str] = None


@router.post("/feedback")
async def submit_feedback(req: FeedbackRequest):
    """Capture what the user/TTO did with a recommendation and how it turned out (P11)."""
    from app.db.reports_repository import record_feedback
    try:
        return await record_feedback(
            req.report_id, user_action=req.user_action, outcome=req.outcome,
            recommendation_id=req.recommendation_id, notes=req.notes,
            outcome_date=req.outcome_date, institution_id=req.institution_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/outcomes")
async def get_outcomes(report_id: str = "", user_id: int = None):
    from app.db.reports_repository import list_outcomes
    return {"outcomes": await list_outcomes(report_id=report_id, user_id=user_id)}


@router.get("/eval-dashboard")
async def get_eval_dashboard(institution_id: str = None):
    """Internal evaluation metrics: trust, priority, abstention, acceptance, outcomes (P10)."""
    from app.db.reports_repository import eval_metrics
    return await eval_metrics(institution_id=institution_id)


# ── TTO review dashboard / workflow (Sprint 5) ──────────────────────────────────

@router.get("/review-queue")
async def review_queue(institution_id: str = None, status: str = "", reviewer: str = ""):
    """The TTO review queue: inventions with triage scores, status, reviewer, next action."""
    from app.db.reports_repository import list_review_queue
    return {"inventions": await list_review_queue(
        institution_id=institution_id, status=status, reviewer=reviewer)}


@router.get("/invention/{report_id}")
async def invention_detail(report_id: str):
    from app.db.reports_repository import get_invention
    inv = await get_invention(report_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invention not found")
    return inv


class ReviewUpdateRequest(BaseModel):
    report_id:         str
    status:            Optional[str] = None   # intake | triaged | under_review | decided | deprioritized
    assigned_reviewer: Optional[str] = None
    next_action:       Optional[str] = None


@router.post("/review-update")
async def review_update(req: ReviewUpdateRequest):
    from app.db.reports_repository import update_review
    try:
        return await update_review(req.report_id, status=req.status,
                                   assigned_reviewer=req.assigned_reviewer,
                                   next_action=req.next_action)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/examples")
async def get_examples():
    return {
        "examples": [
            {
                "category": "ANTIBIOTIC",
                "product_type": "antibiotic",
                "idea": "A novel beta-lactam/beta-lactamase inhibitor combination targeting carbapenem-resistant Klebsiella pneumoniae (CRE) and Acinetobacter baumannii in hospitalized patients with limited treatment options.",
                "target_pathogen": "Carbapenem-resistant Enterobacterales (CRE)",
                "what_to_expect": "Full QIDP/LPAD regulatory analysis, CRE market sizing (~$289M U.S.), BARDA/CARB-X funding pathways"
            },
            {
                "category": "ANTIBIOTIC",
                "product_type": "antibiotic",
                "idea": "A first-in-class oral antibiotic with activity against MRSA for outpatient skin and soft tissue infections, addressing the gap left by linezolid resistance.",
                "target_pathogen": "MRSA",
                "what_to_expect": "MRSA incidence (119,247 BSIs/yr), ABSSSI trial endpoints, P&T formulary strategy"
            },
            {
                "category": "SOFTWARE",
                "product_type": "software",
                "idea": "An AI clinical decision support system that flags early sepsis in the ED by continuously analyzing vitals, lab trends, and nursing notes — targeting the 6-8 hour delay problem.",
                "what_to_expect": "Sepsis market sizing, CMS reimbursement pathway, hospital formulary access strategy"
            },
            {
                "category": "MEDICAL_DEVICE",
                "product_type": "medical_device",
                "idea": "A wearable continuous glucose monitor for rural diabetic patients with 90-day sensor life and no smartphone requirement.",
                "what_to_expect": "Rural diabetes burden, FDA 510(k) vs PMA pathway, CGM market access"
            },
            {
                "category": "DIAGNOSTIC",
                "product_type": "diagnostic",
                "idea": "A rapid 30-minute PCR-based test for antibiotic susceptibility that runs on existing hospital analyzers, eliminating the 48-72 hour wait for culture results.",
                "what_to_expect": "AST market sizing, CLIA waiver pathway, hospital lab access strategy"
            },
        ]
    }


@router.get("/pi-report/mock")
async def mock_pi_report():
    """Mock endpoint for frontend testing — returns sample report without calling Claude."""
    return {
        "executive_summary": "This novel beta-lactam targets MRSA outpatient skin infections with an estimated 119,247 annual U.S. cases [SOURCE: CDC AR Threats 2019 | https://www.cdc.gov/antimicrobial-resistance/data-research/threats/index.html]. The QIDP pathway provides +5 years exclusivity and Priority Review, with a $180-320M development cost and $285M addressable U.S. market.",
        "expert_domain": "drug_amr",
        "expert_name": "AMR / Antibiotic Drug Expert",
        "model_version": "mock-1.0",
        "generated_at": "2026-05-17T00:00:00Z",
        "signals_searched": 12788,
        "disease_intelligence": {
            "condition": "Methicillin-resistant Staphylococcus aureus (MRSA) skin and soft tissue infections",
            "data_points": [
                {"metric": "Annual U.S. MRSA infections", "value": "119,247", "year": "2019", "source": "CDC AR Threats Report", "source_url": "https://www.cdc.gov/antimicrobial-resistance/data-research/threats/index.html"},
                {"metric": "Annual U.S. MRSA deaths", "value": "19,832", "year": "2019", "source": "CDC AR Threats Report", "source_url": "https://www.cdc.gov/antimicrobial-resistance/data-research/threats/index.html"},
                {"metric": "SSTI proportion of MRSA infections", "value": "~60%", "year": "2022", "source": "IDSA SSTI Guidelines", "source_url": "https://www.idsociety.org/practice-guideline/skin-and-soft-tissue-infections/"},
                {"metric": "Outpatient MRSA SSTI annual cases", "value": "~70,000", "year": "2022", "source": "CDC Outpatient Surveillance", "source_url": "https://www.cdc.gov/mrsa/community/index.html"}
            ],
            "resistance_profile": "MRSA resistance mediated by mecA gene (PBP2a). Community-MRSA (USA300 clone) dominates outpatient SSTIs. Resistance to beta-lactams is near-universal; novel agents must bind PBP2a or use non-beta-lactam mechanism.",
            "pipeline_status": "Current standard: TMP-SMX (generic, oral), doxycycline (generic, oral). IV options: vancomycin (generic), daptomycin (Cubicin), linezolid (Zyvox/generic). Delafloxacin (Baxdela) approved 2017 for ABSSSI.",
            "unmet_need_summary": "No novel oral MRSA-active agent approved since delafloxacin (2017); resistance to TMP-SMX rising to 15-20% in some regions, leaving limited outpatient options."
        },
        "literature_citations": [
            {"title": "Clinical Practice Guidelines by IDSA for Skin and Soft Tissue Infections", "authors": "Stevens DL et al.", "journal": "Clinical Infectious Diseases", "year": "2014", "pmid": "24947530", "source_url": "https://pubmed.ncbi.nlm.nih.gov/24947530/", "relevance": "Stevens et al. (Clin Infect Dis, 2014) established TMP-SMX and doxycycline as first-line oral therapy for uncomplicated MRSA SSTIs, directly defining the standard of care your novel agent must improve upon to justify premium pricing and formulary adoption."},
            {"title": "Delafloxacin versus Moxifloxacin for Acute Bacterial Skin and Skin Structure Infections", "authors": "Kingsley J et al.", "journal": "New England Journal of Medicine", "year": "2017", "pmid": "28537196", "source_url": "https://pubmed.ncbi.nlm.nih.gov/28537196/", "relevance": "The SOLO I/II trials (Kingsley et al., NEJM 2017) demonstrated non-inferiority of delafloxacin vs vancomycin/linezolid in 1,510 ABSSSI patients using the 48-72 hour early clinical response endpoint now required by FDA — this trial design is the direct regulatory precedent for your Phase 3 program."},
            {"title": "Prevalence of community-associated methicillin-resistant Staphylococcus aureus", "authors": "Hersh AL et al.", "journal": "JAMA", "year": "2008", "pmid": "18577731", "source_url": "https://pubmed.ncbi.nlm.nih.gov/18577731/", "relevance": "Hersh et al. (JAMA, 2008) documented the explosive rise of CA-MRSA in U.S. emergency departments, with SSTI visit rates tripling from 1993-2005. This establishes the epidemiological trend supporting the 70,000 annual outpatient MRSA SSTI estimate used in the TAM calculation above."}
        ],
        "market_sizing": {
            "steps": [
                {"label": "Annual U.S. MRSA infections", "value": 119247, "unit": "patients", "source": "CDC AR Threats Report 2019", "source_url": "https://www.cdc.gov/antimicrobial-resistance/data-research/threats/index.html", "notes": "All MRSA infections including hospital and community"},
                {"label": "Outpatient SSTI subset", "value": 70000, "unit": "patients", "source": "CDC Community MRSA Surveillance", "source_url": "https://www.cdc.gov/mrsa/community/index.html", "notes": "~60% of MRSA infections are SSTIs; ~60% managed outpatient"},
                {"label": "Average WAC per oral course", "value": 1200, "unit": "USD", "source": "Baxdela/delafloxacin pricing (comparator)", "source_url": "https://www.accessdata.fda.gov/drugsatfda_docs/label/2017/208610s000lbl.pdf", "notes": "Premium oral MRSA agent pricing benchmark"},
                {"label": "Year 5 market penetration", "value": 35, "unit": "percent", "source": "Industry benchmark for novel antibiotics", "source_url": "https://www.idsociety.org/practice-guideline/skin-and-soft-tissue-infections/", "notes": "Conservative estimate for novel branded oral antibiotic"}
            ],
            "formula": "(70,000 outpatient MRSA SSTI patients x $1,200 WAC x 35% penetration) = $29.4M Year 5 U.S. revenue",
            "total_addressable_market_usd": 84000000,
            "serviceable_market_usd": 29400000,
            "methodology_note": "TAM assumes 100% of outpatient MRSA SSTIs captured at WAC pricing. SAM reflects realistic Year 5 market share given generic TMP-SMX competition and formulary access timelines."
        },
        "regulatory_pathway": {
            "recommended_pathway": "NDA 505(b)(1) with QIDP designation under GAIN Act 2012",
            "pathway_rationale": "MRSA is explicitly listed as a qualifying pathogen under the GAIN Act. QIDP provides +5 years exclusivity, Priority Review (6 months), and automatic Fast Track eligibility for an oral ABSSSI agent.",
            "total_timeline_estimate": "6-8 years from IND to approval",
            "total_cost_estimate": "$120-220M total development cost",
            "designations": [
                {"name": "Qualified Infectious Disease Product (QIDP)", "description": "Statutory designation under GAIN Act 2012 for antibiotics targeting serious infections.", "benefit": "+5 years added to existing exclusivity, Priority Review (6-month target), automatic Fast Track eligibility.", "eligibility": "Antibiotics targeting MRSA qualify under CDC Urgent Threat pathogen list.", "how_to_apply": "Submit QIDP request to FDA CDER at least 90 days before NDA submission.", "timeline": "FDA response within 60 days; apply before Phase 3 initiation.", "source": "FDA QIDP Guidance", "source_url": "https://www.fda.gov/drugs/development-resources/qualified-infectious-disease-product-qidp-designation", "priority": "recommended"},
                {"name": "Fast Track Designation", "description": "Automatic with QIDP; allows rolling NDA submission and increased FDA interactions.", "benefit": "Rolling review reduces total review time; more frequent FDA meetings reduce regulatory risk.", "eligibility": "Granted automatically with QIDP designation.", "how_to_apply": "Automatic with QIDP; can also request independently.", "timeline": "60-day FDA response.", "source": "FDA Fast Track Guidance", "source_url": "https://www.fda.gov/patients/fast-track-breakthrough-therapy-accelerated-approval-priority-review/fast-track", "priority": "recommended"}
            ],
            "clinical_trial_requirements": [
                {"phase": "Phase 1", "patient_count": "60-80", "duration": "12-18 months", "estimated_cost": "$8-12M", "key_endpoints": ["Single/multiple ascending dose PK", "Safety and tolerability", "Food effect", "Drug-drug interactions"], "fda_guidance_document": "General Clinical Pharmacology Guidance", "source_url": "https://www.fda.gov/drugs/guidance-documents-regulatory-information/antibacterial-drugs", "success_probability": "85-90%"},
                {"phase": "Phase 2", "patient_count": "150-200", "duration": "18-24 months", "estimated_cost": "$20-35M", "key_endpoints": ["Clinical success at Day 48-72 (ABSSSI)", "Microbiological eradication", "PK/PD target attainment"], "fda_guidance_document": "ABSSSI Guidance 2013", "source_url": "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/acute-bacterial-skin-and-skin-structure-infections-developing-drugs-treatment", "success_probability": "50-60%"},
                {"phase": "Phase 3", "patient_count": "600-900", "duration": "24-30 months", "estimated_cost": "$80-150M", "key_endpoints": ["Early clinical response at 48-72 hours (primary)", "Investigator assessment at Day 14", "Non-inferiority margin of 10% vs comparator"], "fda_guidance_document": "ABSSSI Guidance 2013", "source_url": "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/acute-bacterial-skin-and-skin-structure-infections-developing-drugs-treatment", "success_probability": "55-65%"}
            ],
            "key_friction_points": [
                "Generic TMP-SMX ($4/course) creates extreme price pressure — novel agent must justify 300x premium through superior efficacy or resistance profile data",
                "ABSSSI Phase 3 enrollment requires rapid enrollment across 40-60 sites; 48-72 hour primary endpoint means tight operational execution",
                "Antimicrobial stewardship programs restrict novel antibiotics to failure cases — KOL engagement and compelling clinical data required for formulary access"
            ],
            "loopholes_and_strategies": [
                "Target TMP-SMX-resistant MRSA as enriched enrollment population — reduces sample size and strengthens differentiation claim vs generic standard of care",
                "Pursue ABSSSI as lead indication: fastest enrollment, clearest endpoint, largest outpatient market; expand to other MRSA indications post-approval via sNDA",
                "Apply for CARB-X funding (up to $4.5M Phase 1) if mechanism is novel — reduces equity dilution through Phase 1"
            ],
            "funding_programs": [
                "CARB-X: up to $4.5M Phase 1, $12M Phase 2 for novel mechanisms only. Does NOT fund Phase 3. Apply at carb-x.org twice yearly.",
                "NIH NIAID DMID: $5-50M clinical development contracts for MRSA as priority pathogen. RFPs at niaid.nih.gov quarterly.",
                "BARDA Broad Spectrum Antimicrobials: $50-200M for late-stage development. Requires prior Phase 1 safety data. BAA at medicalcountermeasures.gov."
            ]
        },
        "market_access": {
            "primary_channel": "Outpatient pharmacy via physician prescription; primary prescribers are emergency medicine, urgent care, and primary care physicians",
            "buyer_segments": [
                {"segment_name": "Emergency Departments (~5,000 facilities)", "buyer_count": "~5,000", "decision_maker": "P&T Committee, Formulary Director", "price_per_unit": "$800-1,500/course", "annual_spend_per_facility": "$50,000-200,000", "access_mechanism": "Hospital formulary addition required; ASP approval for ED prescribing", "timeline_to_access": "12-18 months post-approval", "source": "CMS Hospital Data", "source_url": "https://www.cms.gov/Research-Statistics-Data-and-Systems/Statistics-Trends-and-Reports/Medicare-Provider-Charge-Data"},
                {"segment_name": "Urgent Care Centers (~12,000 facilities)", "buyer_count": "~12,000", "decision_maker": "Medical Director, Group Purchasing", "price_per_unit": "$800-1,200/course", "annual_spend_per_facility": "$20,000-80,000", "access_mechanism": "Direct prescribing without formulary restriction; GPO contract listing accelerates adoption", "timeline_to_access": "6-12 months post-approval", "source": "UCAOA Market Data", "source_url": "https://www.ucaoa.org/"}
            ],
            "key_opinion_leaders": [
                "Dr. Henry Chambers, UCSF - MRSA clinical trials, ABSSSI trial design",
                "Dr. Vance Fowler, Duke University - Staphylococcal infections outcomes research"
            ],
            "reimbursement_pathway": "Outpatient oral antibiotic: covered under Part D pharmacy benefit. NTAP does not apply to outpatient drugs. Payer prior auth expected for branded agent given generic alternatives; outcomes-based contract may accelerate coverage.",
            "first_commercial_step": "Submit dossier to top 5 PBMs (Express Scripts, CVS Caremark, OptumRx, Prime, MedImpact) 6 months pre-approval for formulary placement negotiation.",
            "international_opportunities": [
                "EU: EMA centralized procedure; MRSA prevalence highest in Romania, Greece, Italy — priority markets for launch",
                "Japan: PMDA approval; hospital-acquired MRSA high burden, premium pricing achievable"
            ]
        },
        "market_geography": {
            "description": "MRSA SSTIs concentrated in urban areas with high community transmission. Highest burden in Southeast U.S., urban Northeast, and California. Emergency department visits for SSTIs highest in states with high uninsured rates.",
            "top_states": ["California", "Texas", "Florida", "New York", "Georgia"],
            "scope": "national"
        },
        "recommended_next_steps": [
            "Submit QIDP designation request to FDA CDER with MRSA justification citing CDC Urgent Threat status — target 60-day response before IND filing",
            "Apply to CARB-X for Phase 1 non-dilutive funding (up to $4.5M) if mechanism is novel; next application window at carb-x.org",
            "Schedule pre-IND meeting with FDA Division of Anti-Infectives to align on ABSSSI trial design, NI margin, and TMP-SMX-resistant enrichment strategy",
            "Establish MIC surveillance data against contemporary TMP-SMX-resistant MRSA isolates via CDC AR Lab Network partnership",
            "Engage Dr. Chambers (UCSF) and Dr. Fowler (Duke) as clinical advisors for Phase 2/3 trial design and KOL network development"
        ],
        "supporting_evidence": [],
        "hospital_need_matches": [],
        "sources": [
            {"number": 1, "name": "CDC AR Threats Report 2019", "url": "https://www.cdc.gov/antimicrobial-resistance/data-research/threats/index.html", "accessed": "2026-05-17"},
            {"number": 2, "name": "IDSA SSTI Clinical Practice Guidelines", "url": "https://www.idsociety.org/practice-guideline/skin-and-soft-tissue-infections/", "accessed": "2026-05-17"},
            {"number": 3, "name": "FDA QIDP Designation Guidance", "url": "https://www.fda.gov/drugs/development-resources/qualified-infectious-disease-product-qidp-designation", "accessed": "2026-05-17"},
            {"number": 4, "name": "FDA ABSSSI Guidance 2013", "url": "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/acute-bacterial-skin-and-skin-structure-infections-developing-drugs-treatment", "accessed": "2026-05-17"},
            {"number": 5, "name": "PubMed: IDSA SSTI Guidelines", "url": "https://pubmed.ncbi.nlm.nih.gov/24947530/", "accessed": "2026-05-17"},
            {"number": 6, "name": "PubMed: Delafloxacin Phase 3 Trial", "url": "https://pubmed.ncbi.nlm.nih.gov/28537196/", "accessed": "2026-05-17"}
        ],
        "strategic_playbook": [
            {
                "strategy": "LPAD approval for resistant subset then label expansion",
                "example": "Pfizer - Aztreonam-avibactam (Emblaveo)",
                "what_they_did": "Sought approval specifically for NDM-producing organisms no other drug covers, then planned sNDA expansion to broader gram-negative indications post-commercialization.",
                "how_to_apply": "If your antibiotic covers a resistance mechanism with no approved alternative, file LPAD for that niche first. Broader expansion follows with real-world evidence.",
                "source_url": "https://pubmed.ncbi.nlm.nih.gov/36223745/"
            },
            {
                "strategy": "BARDA partnership before Phase 3 to eliminate dilutive financing",
                "example": "Paratek Pharmaceuticals - Omadacycline (Nuzyra)",
                "what_they_did": "Secured $216M BARDA contract to fund both Phase 3 trials (CABP and ABSSSI) before raising equity. Approved 2018 with minimal dilution during most expensive development stage.",
                "how_to_apply": "Submit BARDA TechWatch pre-application before Phase 2 completion. Frame as national security asset if pathogen is on CDC urgent threat list.",
                "source_url": "https://www.medicalcountermeasures.gov/barda/cbrn/omadacycline/"
            },
            {
                "strategy": "Antibiotic-BLI combination packaging to create new patentable entity from off-patent drug",
                "example": "AstraZeneca/Pfizer - Ceftazidime-avibactam (Avycaz)",
                "what_they_did": "Licensed avibactam BLI and combined with off-patent ceftazidime. Created new patentable combination with QIDP designation. AZ sold US rights to Pfizer for $1.6B in 2016.",
                "how_to_apply": "If developing a BLI, identify which off-patent beta-lactams best complement your inhibitor spectrum. The combination becomes a new patentable entity with independent IP.",
                "source_url": "https://pubmed.ncbi.nlm.nih.gov/26063370/"
            }
        ],
        "limitations": "Market sizing based on 2019 CDC surveillance data; actual MRSA SSTI incidence may vary. Pricing assumptions derived from delafloxacin comparator and subject to payer negotiation."
    }


@router.post("/market-sizing-derivation")
async def get_market_sizing_derivation(body: dict):
    """
    Returns the full structured market sizing derivation — all 8 steps with
    citations, formulas, and explanations — as JSON for direct frontend rendering.
    Bypasses Claude so numbers are deterministic and always sourced.
    """
    try:
        from app.services.market_sizing_derivation_service import (
            generate_market_sizing_derivation, MarketSizingDerivation
        )
        from dataclasses import asdict
        idea     = body.get("idea", "")
        pt       = body.get("product_type", "other")
        disease  = body.get("disease_name", "")
        ta       = body.get("therapeutic_area", "other")
        pop      = int(body.get("us_patient_population", 0))
        if not idea:
            raise HTTPException(status_code=400, detail="idea required")
        deriv = generate_market_sizing_derivation(
            idea=idea, product_type=pt, disease_name=disease,
            therapeutic_area=ta, us_patient_population=pop,
        )
        return asdict(deriv)
    except Exception as e:
        logger.error("Market sizing derivation failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/market-sizing-override")
async def save_market_sizing_override(
    body: dict,
    current_user=Depends(get_optional_user),
):
    """Persist a PI's edited market-sizing step values for a report."""
    from app.db import market_sizing_override_repository as _repo
    report_id = body.get("report_id")
    if not report_id:
        raise HTTPException(status_code=400, detail="report_id required")
    user_id = (current_user or {}).get("id")
    step_overrides = body.get("step_overrides", {})
    rationale      = body.get("rationale", "")
    row_id = await _repo.save_override(
        report_id=str(report_id),
        segment_id=0,
        user_id=user_id,
        net_price_usd=0,
        overrides={
            "step_overrides": step_overrides,
            "rationale": rationale,
        },
        added_gates=[],
        removed_gates=[],
        extra_segment_ids=[],
        tam_usd=body.get("tam_usd"),
        sam_usd=body.get("sam_usd"),
        som_usd=body.get("som_usd"),
        label=(rationale or "")[:120] or None,
    )

    # v3 Part F: capture corrections in the aggregated override ledger (training data).
    # Best-effort: any DB failure here must not affect the save response.
    try:
        from app.db import override_ledger_repository as _ledger
        await _ledger.append_corrections(
            step_overrides=step_overrides,
            rationale=rationale,
            report_id=str(report_id),
        )
    except Exception as _le:
        logger.warning("override_ledger capture failed (non-fatal): %s", _le)

    return {"ok": True, "override_id": row_id}


@router.get("/override-ledger/stats")
async def get_override_ledger_stats(
    step_label: str = "",
    min_corrections: int = 1,
    limit: int = 50,
    current_user=Depends(get_current_user),
):
    """
    v3 Part F: return aggregated expert correction statistics from the override ledger.

    Each row shows how many times a given model step has been corrected by users,
    and the distribution of correction ratios (new_value / orig_value).

    A median_ratio of 0.05 means experts consistently correct this step to 5% of
    the model's estimate — a reliable signal that the prior is systematically wrong.

    Requires authentication: ledger data is internal to the operator.
    """
    from app.db import override_ledger_repository as _ledger
    stats = await _ledger.get_stats(
        step_label=step_label or None,
        min_corrections=max(1, min_corrections),
        limit=min(limit, 200),
    )
    total = await _ledger.count_total_corrections()
    return {
        "total_corrections": total,
        "stats": stats,
        "min_corrections_threshold": min_corrections,
    }


@router.get("/market-sizing-override/{report_id}")
async def get_market_sizing_override(
    report_id: str,
    current_user=Depends(get_optional_user),
):
    """Return saved market-sizing overrides for a report, or {has_override: false}."""
    from app.db import market_sizing_override_repository as _repo
    user_id = (current_user or {}).get("id")
    saved = await _repo.get_override(str(report_id), 0, user_id)
    if not saved:
        return {"has_override": False}
    ov = saved.get("overrides") or {}
    return {
        "has_override": True,
        "step_overrides": ov.get("step_overrides", {}),
        "rationale": ov.get("rationale", ""),
        "tam_usd": saved.get("tam_usd"),
        "sam_usd": saved.get("sam_usd"),
        "som_usd": saved.get("som_usd"),
        "updated_at": str(saved.get("updated_at", "")),
    }


# ── Discovery Engine Endpoints ────────────────────────────────────────────────

@router.get("/discovery/opportunities")
async def get_opportunities(
    top_n: int = 100,
    offset: int = 0,
    search: str = "",
    current_user = Depends(get_current_user),
):
    """
    Return ranked biomedical opportunities.
    G.8: serves from pre-built static JSON artifact when available (fast path, ~50ms).
    Falls back to live v2 engine for the curated 309 + disease_scored DB.
    """
    # G.8: fast path — static artifact built by scripts/build_discovery_index.py
    import pathlib as _pathlib, json as _json, time as _time
    _STATIC_INDEX = _pathlib.Path(__file__).parent.parent / "data" / "discovery-index.json"
    _STATIC_MAX_AGE_S = 25 * 60 * 60  # 25 h — fresh if built within last day
    if not search and _STATIC_INDEX.exists():
        try:
            _stat_age = _time.time() - _STATIC_INDEX.stat().st_mtime
            if _stat_age < _STATIC_MAX_AGE_S:
                _payload = _json.loads(_STATIC_INDEX.read_text(encoding="utf-8"))
                _opps = _payload.get("opportunities", [])
                if _opps:
                    _page = _opps[offset : offset + top_n]
                    for i, o in enumerate(_page, offset + 1):
                        o["rank"] = i
                    logger.info(
                        "G.8: served discovery from static artifact (age=%.0fs, %d opps)",
                        _stat_age, len(_opps),
                    )
                    return {
                        "opportunities":  _page,
                        "universe_size":  _payload.get("universe_size", len(_opps)),
                        "total_scored":   len(_opps),
                        "built_at":       _payload.get("built_at"),
                        "algorithm":      _payload.get("algorithm", "Static index"),
                        "generated_at":   _payload.get("generated_at"),
                        "_source":        "static",
                    }
        except Exception as _e:
            logger.warning("G.8: static index read failed (falling back to live): %s", _e)

    # Strategy: Live v2 engine for curated 309 (expert TAM, EXCEPTIONAL tiers)
    # + disease_scored DB for extended MONDO universe (search only when >1000 entries)
    curated_opps = []
    extended_total = 0

    # Always run live v2 for the curated 309 (highest quality)
    try:
        from app.services.opportunity_scorer_v2 import run_discovery_engine_v2
        curated_opps = await run_discovery_engine_v2(top_n=max(top_n, 309))
    except Exception as e_v2:
        logger.error("v2 engine failed: %s", e_v2)
        try:
            from app.services.opportunity_scorer import run_discovery_engine
            curated_opps = await run_discovery_engine(top_n=top_n)
        except Exception:
            curated_opps = []

    curated_names = {o["disease"].lower() for o in curated_opps}

    # If searching or extended universe is ready, supplement with disease_scored
    if search or True:  # always check for extended diseases
        try:
            from app.db.database import get_pool
            pool = await get_pool()
            async with pool.acquire() as conn:
                extended_total = await conn.fetchval(
                    "SELECT COUNT(*) FROM disease_scored WHERE data_source != 'universe_builder'"
                ) or 0

                if search:
                    # Search curated first
                    curated_filtered = [o for o in curated_opps
                                        if search.lower() in o["disease"].lower()
                                        or search.lower() in (o.get("notes") or "").lower()]
                    # Also search extended universe
                    ext_rows = await conn.fetch("""
                        SELECT * FROM disease_scored
                        WHERE (lower(disease_label) LIKE lower($1)
                               OR lower(notes) LIKE lower($1))
                          AND lower(disease_label) NOT IN
                              (SELECT lower(disease_label) FROM disease_scored WHERE data_source='universe_builder')
                        ORDER BY score DESC NULLS LAST LIMIT $2
                    """, f"%{search}%", top_n)

                    ext_opps = [_row_to_opp(row, i + len(curated_filtered))
                                for i, row in enumerate(ext_rows, 1)]
                    all_opps = curated_filtered + ext_opps
                    # Re-sort by score
                    all_opps.sort(key=lambda x: x["score"], reverse=True)
                    for i, o in enumerate(all_opps, 1):
                        o["rank"] = i
                    return {
                        "opportunities": all_opps[:top_n],
                        "generated_at":  datetime.utcnow().isoformat(),
                        "algorithm":     f"Expert 309 + {extended_total:,} MONDO diseases",
                        "total_scored":  len(all_opps),
                        "universe_size": 309 + extended_total,
                    }

                elif extended_total > 100:
                    # Merge curated + DB diseases; support offset pagination
                    needed = max(0, top_n + offset - len(curated_opps))
                    ext_rows = await conn.fetch("""
                        SELECT * FROM disease_scored
                        WHERE data_source != 'universe_builder'
                        ORDER BY COALESCE(sam_usd, 0) DESC NULLS LAST,
                                 score DESC NULLS LAST
                        LIMIT $1
                    """, needed + 50)  # fetch a few extra for sort stability
                    ext_opps = [_row_to_opp(row, 0) for row in ext_rows]

                    all_opps = curated_opps + ext_opps
                    all_opps.sort(
                        key=lambda x: x.get("sam_usd") or (x.get("score", 0) * 1_000_000),
                        reverse=True,
                    )
                    page = all_opps[offset : offset + top_n]
                    for i, o in enumerate(page, offset + 1):
                        o["rank"] = i
                    universe = len(curated_opps) + extended_total
                    return {
                        "opportunities": page,
                        "generated_at":  datetime.utcnow().isoformat(),
                        "algorithm":     f"Expert {len(curated_opps)} curated + {extended_total:,} extended diseases",
                        "total_scored":  len(all_opps),
                        "universe_size": universe,
                    }
        except Exception as e_db:
            logger.debug("disease_scored supplement failed: %s", e_db)

    # Fallback — return curated universe with accurate count
    curated_size = len(curated_opps)
    try:
        from app.services.universe_expander_v2 import get_all_diseases_for_batch_scoring
        total_known = len(get_all_diseases_for_batch_scoring())
    except Exception:
        total_known = curated_size
    page = curated_opps[offset : offset + top_n]
    for i, o in enumerate(page, offset + 1):
        o["rank"] = i
    return {
        "opportunities": page,
        "generated_at":  datetime.utcnow().isoformat(),
        "algorithm":     f"Expert {curated_size} curated diseases",
        "total_scored":  len(curated_opps[:top_n]),
        "universe_size": total_known,
    }


def _row_to_opp(row, rank: int) -> dict:
    """Convert a disease_scored DB row to the frontend opportunity dict."""
    score  = float(row["score"] or 0)
    sam    = row["sam_usd"] if "sam_usd" in row.keys() and row["sam_usd"] else None
    peak   = row["peak_revenue_usd"] if "peak_revenue_usd" in row.keys() and row["peak_revenue_usd"] else None
    tam_usd = row["us_tam_usd"] if "us_tam_usd" in row.keys() and row["us_tam_usd"] else None
    pop    = row["us_population"] if "us_population" in row.keys() else None
    ptrs   = row["ptrs_pct"] if "ptrs_pct" in row.keys() and row["ptrs_pct"] else None

    def _fmt(v):
        if not v: return "—"
        v = float(v)
        if v >= 1e9:  return f"${v/1e9:.1f}B"
        if v >= 1e6:  return f"${v/1e6:.0f}M"
        return f"${v/1e3:.0f}K"

    sam_fmt  = _fmt(sam or peak)
    tam_fmt  = row["us_tam_fmt"] or _fmt(tam_usd) or "—"
    peak_fmt = row["peak_revenue_fmt"] or _fmt(peak) or "—"

    return {
        "rank":               rank,
        "disease":            row["disease_label"],
        "therapeutic_area":   row["therapeutic_area"] or "other",
        "score":              round(score, 1),
        "tier":               row["tier"] or "MODERATE",
        "tier_color":         _tier_color(row["tier"]),
        "score_raw":          round(score, 2),
        "ptrs":               round(float(ptrs), 1) if ptrs else 0,
        "confidence_low":     round(score * 0.82, 1),
        "confidence_high":    round(score * 1.18, 1),
        "notes":              row["notes"] or "",
        "phase":              "phase2",
        "components": {
            "opportunity": round(float(row["opportunity"] or 0), 1),
            "probability": round(float(row["probability"] or 0), 1),
            "value":       round(float(row["value_score"] or 0), 1),
        },
        "subscores": {
            "opportunity": round(float(row["opportunity"] or 0), 1),
            "probability": round(float(row["probability"] or 0), 1),
            "value":       round(float(row["value_score"] or 0), 1),
            "innovation":  0,
        },
        "us_tam_usd":         int(tam_usd) if tam_usd else None,
        "us_tam_fmt":         tam_fmt,
        "peak_revenue_usd":   int(peak) if peak else None,
        "peak_revenue_fmt":   peak_fmt,
        "sam_usd":            int(sam or peak or 0),
        "sam_fmt":            sam_fmt,
        "us_patient_population": int(pop) if pop else None,
        "commercial_tractability": row["commercial_tractability"] if "commercial_tractability" in row.keys() else None,
        "tractability_note":  row["tractability_note"] if "tractability_note" in row.keys() else None,
        "funding_pathway":    "commercial",
        "data_source":        row["data_source"] or "db",
    }


def _tier_color(tier: str) -> str:
    return {"EXCEPTIONAL": "#059669", "HIGH": "#0891b2",
            "MODERATE": "#d97706", "LOW": "#dc2626"}.get(tier or "", "#6366f1")


@router.post("/discovery/score")
async def score_custom_opportunity(
    body: dict,
    current_user = Depends(get_current_user),
):
    """Score a custom opportunity provided by the user."""
    from app.services.opportunity_scorer import score_opportunity
    try:
        result = await score_opportunity(
            disease_name=body.get("disease_name", ""),
            therapeutic_area=body.get("therapeutic_area", "default"),
            development_phase=body.get("development_phase", "preclinical"),
            approved_treatments_count=body.get("approved_treatments_count"),
            competitor_trial_count=body.get("competitor_trial_count"),
            annual_treatment_cost_usd=body.get("annual_treatment_cost_usd"),
            us_patient_population=body.get("us_patient_population"),
            designations=body.get("designations", []),
            order_of_entry=body.get("order_of_entry"),
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/idea-builder")
async def idea_builder(body: dict):
    """
    Idea Builder: market → innovator direction.
    Takes innovator profile (modality, stage, constraint, differentiator)
    + selected market opportunities, returns 3 matched ideas with refined
    idea statements generated by Claude Haiku.

    Public endpoint — no auth required (just idea generation, no quota hit).
    """
    platform       = body.get("platform", body.get("modality", "intervention"))
    biology        = body.get("biology", body.get("constraint", ""))
    patients       = body.get("patients", body.get("differentiator", ""))
    stage          = body.get("stage", "")
    differentiator = body.get("differentiator", "")
    markets        = body.get("markets", [])[:3]

    if not markets:
        raise HTTPException(status_code=400, detail="At least one market required")

    market_str = "\n".join(
        f"- {m.get('disease','?')}: {m.get('ta','').replace('_',' ')} | SAM {m.get('sam','?')} | score {m.get('score',50):.0f}/100"
        for m in markets
    )

    prompt = f"""You are a medical market intelligence expert helping a health innovator identify their best opportunity.

INNOVATOR PROFILE:
- Platform / modality: {platform}
- Biological mechanism targeted: {biology}
- Target patient population: {patients}
- Development stage: {stage}
- Key differentiator: {differentiator}

MATCHED MARKET OPPORTUNITIES (ranked by biology + patient fit, then SAM):
{market_str}

Generate exactly 3 refined idea concepts — one per market — that specifically connect
this innovator's biological mechanism and platform to each disease.
Be precise: name the specific target protein, pathway, or mechanism. Do NOT write generic ideas.

Return ONLY valid JSON (no markdown):
{{
  "ideas": [
    {{
      "disease": "<disease name from the list>",
      "therapeutic_area": "<ta from the list>",
      "tam": "<TAM from the list>",
      "match_score": <integer 60-95>,
      "refined_idea": "<1-2 sentence specific idea statement connecting their modality + differentiator to this disease. Be concrete about mechanism or approach. Under 180 chars.>",
      "fit_reason": "<under 60 chars: why their modality fits this TA>",
      "opportunity": "<under 50 chars: key unmet need in this market>",
      "fast_path": "<under 70 chars: fastest regulatory or funding path given their constraint>"
    }}
  ]
}}

Order by match_score descending. Make the refined_idea statements specific and compelling, not generic."""

    try:
        import httpx
        from app.core.config import settings
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key":         settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      "claude-haiku-4-5-20251001",
                    "max_tokens": 1000,
                    "messages":   [{"role": "user", "content": prompt}],
                },
            )
            r.raise_for_status()
            raw = r.json()["content"][0]["text"].strip()
            # Clean JSON if wrapped in markdown
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            import json as _json
            data = _json.loads(raw.strip())
            return data
    except Exception as e:
        logger.warning("Idea builder Claude call failed: %s", e)
        # Fallback: return structured ideas without AI
        return {
            "ideas": [
                {
                    "disease": m.get("disease", "?"),
                    "therapeutic_area": m.get("ta", ""),
                    "tam": m.get("tam", "—"),
                    "match_score": max(60, int(m.get("score", 65))),
                    "refined_idea": f"A {platform} targeting {biology.split('/')[0].lower() if biology else 'the underlying pathway'} in {m.get('disease','?')} — {patients.lower() if patients else 'addressing unmet clinical need'} at {stage.split('—')[0].strip()} stage.",
                    "fit_reason": f"{platform} mechanism matches {m.get('ta','').replace('_',' ')} biology",
                    "opportunity": "High unmet need, limited approved options",
                    "fast_path": "Seek FDA expedited designation early",
                }
                for m in markets
            ]
        }


@router.post("/competitive-sweep")
async def competitive_sweep(
    body: dict,
    current_user = Depends(get_current_user),
):
    """
    Sweep openFDA, ClinicalTrials.gov, and OpenAlex for named competitors.
    Returns structured competitive landscape: named products, advantages,
    white space gaps, and differentiation levers.
    """
    import asyncio
    from app.services.competitor_sweep_service import sweep_competitors, to_dict

    disease    = body.get("disease_name", body.get("idea", "")[:80])
    keywords   = body.get("keywords", [])
    ta         = body.get("therapeutic_area", "other")
    pt         = body.get("product_type", "drug_small_molecule")

    if not disease:
        raise HTTPException(status_code=400, detail="disease_name or idea required")

    if not keywords:
        keywords = [w for w in disease.split() if len(w) > 4][:5]

    try:
        loop = asyncio.get_event_loop()
        # Hard 30s cap so a slow external sweep can't hold the request open past the
        # proxy timeout (which surfaced to the client as "Failed to fetch").
        landscape = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: sweep_competitors(
                    disease_name=disease,
                    indication_keywords=keywords,
                    therapeutic_area=ta,
                    product_type=pt,
                )
            ),
            timeout=30.0,
        )
        return to_dict(landscape)
    except asyncio.TimeoutError:
        logger.warning("Competitive sweep timed out for %s", disease)
        return {"available": False, "competitors": [],
                "note": "Live competitor sweep took too long; see the competitive pipeline "
                        "summarized in the Opportunity section above."}
    except Exception as e:
        logger.error("Competitive sweep failed: %s", e, exc_info=True)
        return {"available": False, "competitors": [],
                "note": "Live competitor sweep is temporarily unavailable; see the "
                        "competitive pipeline in the Opportunity section above."}


@router.post("/classify")
async def classify_product_endpoint(
    body: dict,
    current_user = Depends(get_current_user),
):
    """
    Stage-1 product classifier (Spec v3 C.1).

    Accepts: { "idea": str }
    Returns: Classification fields + conditioned IntakeQuestion[]

    Domain + archetype are resolved deterministically via soft_router +
    product_archetype. The LLM (Haiku) is used only for display fields
    (product_name, one_line, trl, ambiguities).
    """
    from app.services.product_classifier import classify_product, get_conditioned_questions, questions_to_legacy_format
    from dataclasses import asdict

    idea = (body.get("idea") or "").strip()
    if not idea or len(idea) < 20:
        raise HTTPException(status_code=400, detail="Idea too short for classification")

    try:
        import asyncio
        loop = asyncio.get_event_loop()
        # classify_product() makes a blocking Haiku call — run it off the event loop
        # so the connection doesn't drop while the thread is waiting on Anthropic.
        cls = await loop.run_in_executor(None, classify_product, idea)
        conditioned_qs = get_conditioned_questions(cls)
        legacy_qs = questions_to_legacy_format(conditioned_qs)

        return {
            "classification": {
                "product_name": cls.product_name,
                "one_line":     cls.one_line,
                "domain":       cls.domain,
                "archetype":    cls.archetype,
                "trl":          cls.trl,
                "confidence":   cls.confidence,
                "ambiguities":  cls.ambiguities,
            },
            "questions": legacy_qs,
        }
    except Exception as exc:
        logger.error("classify_product_endpoint failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/clarify")
async def generate_clarifying_questions(
    body: dict,
    current_user = Depends(get_current_user),
):
    """
    Generate 5-10 targeted clarifying questions based on the user's idea and
    funding pathway. Mirrors the ChatGPT Deep Research pattern: ask smart
    questions before generating the report to get structured, descriptive input.
    """
    import anthropic
    from app.core.config import settings

    idea = body.get("idea", "")
    pathway = body.get("pathway", "commercial")
    product_type = body.get("product_type", "")
    disease_hint = body.get("disease_name", "")
    # Optional: if the caller already has a Classification object (from /classify),
    # use the conditioned question bank instead of the LLM-generated questions.
    # This guarantees every question has a binds_to field (spec C.2).
    classification_hint = body.get("classification")  # dict or None

    if not idea or len(idea) < 20:
        raise HTTPException(status_code=400, detail="Idea too short")

    # classification_hint is available to the LLM prompt below (for context),
    # but we no longer short-circuit to the static bank here — the LLM generates
    # questions tailored to the specific product description. Static conditioned
    # questions are only the fallback when the LLM call fails.

    # Run live competitive sweep in parallel so the questions can reference real named competitors
    competitive_context = ""
    try:
        import asyncio
        from app.services.competitor_sweep_service import sweep_competitors, format_for_prompt
        # Extract keywords from idea + disease hint
        keywords = [w for w in (disease_hint or idea).split() if len(w) > 4][:4]
        loop = asyncio.get_event_loop()
        # Bounded so /clarify stays well under the proxy timeout — an unbounded sweep was
        # pushing total latency to ~40s and intermittently forcing the client onto the
        # generic fallback questions. product_type steers a device/SaMD sweep to real
        # device/AI competitors instead of drugs.
        landscape = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: sweep_competitors(
                    disease_name=disease_hint or idea[:60],
                    indication_keywords=keywords,
                    therapeutic_area="other",
                    product_type=product_type or "drug_small_molecule",
                )
            ),
            timeout=5.0,
        )
        if landscape.competitors:
            competitive_context = format_for_prompt(landscape)
    except Exception as ce:
        logger.warning("Competitor sweep for clarify failed/timed out: %s", ce)

    pathway_context = {
        "commercial": "a commercial product seeking go-to-market strategy (TAM/SAM, FDA pathway, buyers, pricing, competitive landscape)",
        "sbir": "an SBIR/STTR grant or licensing opportunity — needs both commercial market evidence and scientific significance for tech transfer or grant applications",
        "basic_science": "a basic science grant (NIH R01/R21) focused on significance, innovation, and scientific impact rather than commercial market",
    }.get(pathway, "a commercial product")

    # Pull specialized data to inform what we already know vs what we need
    data_context = ""
    try:
        from app.services.soft_router import soft_route
        from app.services.disease_data_enricher import get_enrichment_data
        routing = soft_route(idea)
        sub_id  = routing.primary
        enrich  = get_enrichment_data(disease_hint or idea[:50], routing.primary.split("_")[0])
        data_context = (
            f"\nWhat our database already knows about this market:\n"
            f"  - Subcategory: {sub_id} ({routing.confidence:.0%} confidence)\n"
            f"  - Known patient population: {enrich.us_patient_population:,} ({enrich.population_source[:60]})\n"
            f"  - Typical pricing: ${enrich.annual_treatment_cost:,.0f}/yr ({enrich.pricing_source[:60]})\n"
            f"  - Formulary coverage: {enrich.formulary_coverage:.0%} of plans\n"
            f"  - MEPS adherence: {enrich.meps_adherence_rate:.0%} real-world\n"
            f"  - Realized TAM factor: {enrich.realized_tam_factor:.0%} of theoretical\n"
        )
    except Exception:
        pass

    # Determine modality so the questions match the KIND of product.
    _mod_sid = ""
    try:
        from app.services.soft_router import soft_route
        _mod_sid = (soft_route(idea).primary or "")
    except Exception:
        pass
    _mk = f"{_mod_sid} {product_type}".lower()
    # Also look at the classification archetype (from /classify) if available
    _arch = (classification_hint or {}).get("archetype", "") if isinstance(classification_hint, dict) else ""
    _is_devicelike = (_mod_sid.lower().startswith(("device_", "diagnostic_", "digital_"))
                      or any(x in _mk for x in ("software", "samd", "medical_device", "diagnostic", "digital")))
    # Explicit research_* archetype from /classify always wins over product_type inference
    _is_research_tool = (
        _arch.lower().startswith("research_")
        or (not _is_devicelike and (
            _mod_sid.lower().startswith("research_")
            or any(x in _mk for x in ("research_tool", "research_infra", "research_saas"))
        ))
    )
    if _is_research_tool:
        _is_devicelike = False

    if _is_devicelike:
        param_block = """REQUIRED PARAMETERS TO UNLOCK (one question per parameter) — this is a DEVICE / DIAGNOSTIC / SaMD, so ask about the software/device, NOT drug patient populations:
  Q1 → INTENDED USE & CLINICAL WORKFLOW: Where in the care pathway does it act, and is it assistive or autonomous?
       (e.g., "CT triage/notification for suspected LVO" vs "diagnostic read"; clinician-in-the-loop vs autonomous)
  Q2 → TARGET SITES & SETTING: Which facilities/departments and care setting are the unit of sale?
       (e.g., comprehensive stroke centers, ED, radiology/PACS; inpatient vs outpatient; # of US sites)
  Q3 → TECHNICAL DIFFERENTIATION: What is genuinely different technically vs the installed standard?
       (input modality, sensitivity/specificity, time-to-result, multi-condition breadth, on-prem/edge/cloud, EHR/PACS integration)
  Q4 → VALIDATION EVIDENCE: What validation data exists (this replaces drug trials — do NOT ask about Phase 1/2/3 or MIC/IC50)?
       (retrospective AUC/sensitivity/specificity, # of sites/scanners, prospective study status, reference standard / ground truth)
  Q5 → ECONOMIC BUYER & PAYMENT PATHWAY: Who signs the check and how is it funded?
       (hospital IT/procurement, service-line capital vs operating budget, NTAP / Category III CPT, value-based ROI e.g. bed-days or readmissions avoided)
  Q6 → COMPETITIVE ADVANTAGE vs a NAMED cleared AI/device: vs the closest cleared tool (e.g. RapidAI, Viz.ai, Aidoc, Brainomix), what is the measurable edge?
       (e.g., higher sensitivity, faster time-to-notification, native Epic/PACS integration, broader condition coverage)"""
        options_rules = """RULES FOR OPTIONS:
- Every option must be specific to THIS software/device and clinical use — never abstract, and never drug-shaped
- Use real device/AI competitor names and real technical endpoints (sensitivity, specificity, AUC, time-to-result) — NOT drug names, organisms, MIC/IC50, or lines of therapy
- Options should cover the realistic range for this specific product
- Include a "None of these — explain:" option when appropriate"""
    elif _is_research_tool:
        param_block = """This is a NON-CLINICAL RESEARCH TOOL. Ask 6 questions about HOW THE PRODUCT WORKS — not about market size numbers the PI can't know. The backend derives TAM/SAM/SOM from the product-understanding answers automatically.

CRITICAL PHILOSOPHY: Ask what the PI KNOWS (their product). Do NOT ask them to guess market size, lab counts, or adoption rates — the algorithm derives those from their answers.

Q1 field="buyer.persona" — Who is the primary decision-maker who adopts and pays? Write specific to THIS product.
Options (pick 4 that fit): "Individual PI or lab director — purchases from discretionary lab budget" | "Graduate student / postdoc — bottom-up viral adoption, PI ratifies the spend later" | "Core facility director — institutional procurement, serves multiple labs" | "Industry R&D lab (pharma / biotech) — formal vendor qualification required"

Q2 field="price.annual_per_lab" — What is the expected annual price per lab? Write specific to THIS product and its buyer.
Options (EXACT format — numbers are parsed by backend): "Under $500/yr — consumable-level or grant-incidental spend" | "$500–$2,000/yr — standard research software subscription" | "$2,000–$8,000/yr — mid-tier lab infrastructure tool" | "$8,000–$25,000/yr — core facility or institutional license"

Q3 field="seg.instrument_requirement" — What does a research lab need to HAVE in order to use this product? This sets the addressable population ceiling — write it specific to THIS product's actual technical requirements.
Options MUST embed lab-count ranges (backend parses these numbers to set TAM population):
"Any internet-connected computer — no specialized instruments required (~30,000–80,000 US academic research labs)" | "Labs with specific data-generating instruments (describe the instrument type for this product) (~5,000–20,000 qualifying labs)" | "Labs running a particular instrument model or brand-specific workflow (~1,500–5,000 qualifying labs)" | "Core facilities or institutional shared-equipment deployments (~500–2,000 facilities)"
Customize each option's description to match THIS product's actual requirements.

Q4 field="seg.workflow_type" — What is the core workflow or problem this product addresses? Write specific to THIS product's function.
Options MUST contain keywords the backend uses to set SAM rate:
"Passive data sync or automated transfer — [describe what this product collects/moves automatically, without researcher action]" | "Active data analysis or visualization — [describe what the researcher does to process each experiment]" | "Lab operations or protocol coordination — [describe how teams use it to organize work]" | "Instrument integration or hardware control — [describe what instruments it connects or drives]"
Customize descriptions for THIS product. Keep "passive"/"sync"/"automatic"/"without researcher" wording in option 1; keep "instrument"/"control"/"hardware" wording in option 4.

Q5 field="comp.status_quo" — What do labs currently use instead of this product? Write specific to THIS product's competitive landscape.
Options: "Manual process by lab staff — [describe the specific manual task this replaces]" | "DIY scripts or home-built tools — [describe the typical custom solution]" | "Open-source alternative — [name a real open-source tool that competes]" | "Commercial incumbent — [name a real paid product they're currently using]"

Q6 field="seg.adoption_pathway" — How do new labs typically discover and start using this product? Write specific to THIS product.
Options MUST contain keywords the backend uses to set SOM penetration rate:
"Peer-to-peer among researchers — a grad student or postdoc finds it and recommends it within their network" | "PI-led evaluation — the lab PI initiates a deliberate pilot after a referral or demo" | "Conference or publication-driven — labs adopt after seeing it in a talk, paper, or preprint" | "Core facility or IT roll-out — a facility director or university IT deploys it across multiple labs"
Keep "peer"/"viral"/"grad student"/"recommend" wording in option 1; keep "conference"/"publication"/"paper" in option 3; keep "facility"/"roll-out"/"IT"/"deploy" in option 4."""
        options_rules = """OPTIONS RULES for research tool questions:
- Q2 options MUST include the exact dollar ranges shown — backend parses them to set price
- Q3 options MUST include the exact lab-count ranges (~X,000–Y,000) — backend parses them to set TAM population
- Q4 options MUST preserve the keyword phrases (passive/sync/automatic; instrument/control/hardware) — backend keyword-matches to set SAM rate
- Q6 options MUST preserve the keyword phrases (peer/recommend; conference/publication/paper; facility/IT/deploy) — backend keyword-matches to set SOM rate
- Customize every option's descriptive text to be specific to THIS product — but KEEP the parseable numbers and keywords
- Never use clinical language (no patients, diseases, FDA, trials)"""
    else:
        param_block = """REQUIRED FORMULA PARAMETERS TO UNLOCK (one question per parameter):
  Q1 → ELIGIBLE SUBPOPULATION: Which specific patient subset does this target?
       (e.g., "Exon 51-skippable DMD patients" vs "all DMD", or "CRE bacteremia, not just colonization")
  Q2 → LINE OF THERAPY / TREATMENT SETTING: Where does this fit in the clinical pathway?
       (1st-line vs salvage, inpatient ICU vs outpatient, post-surgical vs prophylactic)
  Q3 → CLINICAL MECHANISM NOVELTY: What is genuinely different about the mechanism?
       (Not the disease area — specifically what does this do that approved drugs don't)
  Q4 → DEVELOPMENT EVIDENCE: What data already exists to validate efficacy?
       (In vitro MIC/IC50, animal model survival, Phase 1 safety, Phase 2 ORR — be specific)
  Q5 → PRIMARY ECONOMIC BUYER: Who signs the check and what is their price sensitivity?
       (Hospital P&T committee, specialty pharmacy PBM, patient OOP, payer formulary tier)
  Q6 → COMPETITIVE CLINICAL ADVANTAGE: vs the single closest approved therapy, what is the measurable advantage?
       (e.g., "vs ceftazidime-avibactam, your drug covers NDM-1 producing organisms — confirmed by MIC data?")"""
        options_rules = """RULES FOR OPTIONS:
- Every option must be specific to THIS innovation and disease area — never abstract
- Use real drug names, real organism names, real clinical endpoints
- Options should cover the realistic range for this specific product
- Include a "None of these — explain:" option when appropriate"""

    # Include classification context if available so LLM knows the product category
    classification_context = ""
    if isinstance(classification_hint, dict):
        _hint_arch = classification_hint.get("archetype", "")
        _hint_domain = classification_hint.get("domain", "")
        _hint_one_line = classification_hint.get("one_line", "")
        if _hint_arch:
            classification_context = f"\nClassified as: {_hint_arch} ({_hint_domain})"
            if _hint_one_line:
                classification_context += f"\nOne-line: {_hint_one_line}"

    prompt = f"""You are conducting deep research on a health innovation before generating a market intelligence report.
Your goal: ask the 6 most important questions that will make this specific report dramatically more accurate.

THE INNOVATION:
"{idea}"

Product type: {product_type}{classification_context}
{data_context}
{competitive_context}

DEEP RESEARCH PRINCIPLES (follow these exactly):
1. We already know the rough market size and standard pricing — DO NOT ask generic "what is your market size" questions
2. Ask what would CHANGE the analysis significantly for THIS kind of product
3. Reference SPECIFIC named products/competitors as comparators — never say "competitor A"
4. Ask about things our databases can't know: unpublished data, specific novelty, proprietary IP
5. Each question should unlock a DIFFERENT parameter — no redundancy
6. Questions must be answerable by the PI in 1 sentence based on what they know about their own work

{param_block}

{options_rules}

Return ONLY a valid JSON array of 6 objects. No markdown, no explanation, no other text.
[{{
  "question": "<specific question directly referencing the product>",
  "field": "snake_case_key",
  "options": ["<specific option with concrete detail>", "<specific option>", "<specific option>", "<specific option>"],
  "hint": "<prompt for what additional detail would most improve the analysis>"
}}]"""

    try:
        # AsyncAnthropic is the native async client — no run_in_executor needed.
        # The previous sync+run_in_executor pattern was unreliable on Railway because
        # the competitive sweep (up to 12 s) + LLM (5-8 s) together could exceed
        # Railway's proxy timeout before the response was assembled.
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        msg = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text if msg.content else "[]"
        # Extract JSON array
        import json, re
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            questions = json.loads(match.group())
            # Inject binds_to from the field key so every question has the C.2 contract field.
            _FIELD_TO_BINDS: dict[str, str] = {
                "eligible_subpopulation": "seg.gate.eligible_population",
                "target_population": "seg.primary_use_case",
                "line_of_therapy": "seg.gate.line_of_therapy",
                "mechanism_novelty": "dev.mechanism_novelty",
                "development_evidence": "dev.evidence_stage",
                "validation_evidence": "dev.evidence_stage",
                "clinical_differentiation": "dev.clinical_validation_done",
                "buyer": "buyer.persona",
                "economic_buyer": "buyer.persona",
                "price_band": "price.observed_band",
                "competitive_advantage": "comp.nearest_named_competitor",
                "competitive_edge": "comp.nearest_named_competitor",
                "status_quo": "comp.status_quo",
                "target_sites": "seg.gate.facility_type",
                "intended_use": "seg.primary_use_case",
                # research-tool fields (legacy)
                "lab_segment": "seg.primary_use_case",
                "research_workflow_positioning": "seg.gate.use_case_depth",
                "incumbent": "comp.status_quo",
                "technical_novelty": "dev.mechanism_novelty",
                "adoption_evidence": "dev.evidence_stage",
                "competitive_moat": "comp.nearest_named_competitor",
                "eligible_research_subpopulation": "seg.gate.eligible_population",
                # research-tool product-understanding fields (F-17 redesign)
                # field key == binds_to so _apply_user_params finds them directly
                "seg.instrument_requirement": "seg.instrument_requirement",
                "seg.workflow_type":          "seg.workflow_type",
                "seg.adoption_pathway":       "seg.adoption_pathway",
                "buyer.persona":              "buyer.persona",
                "price.annual_per_lab":       "price.annual_per_lab",
                "comp.status_quo":            "comp.status_quo",
            }
            for q in questions:
                if "binds_to" not in q:
                    fk = (q.get("field") or "").lower()
                    q["binds_to"] = _FIELD_TO_BINDS.get(fk, f"intake.{fk}" if fk else "intake.misc")
            # For device-like products (SaMD / digital health), the revenue model is
            # ambiguous (site license vs per-patient vs enterprise SaaS). Prepend a
            # monetization_unit question so the report picks the right pricing model.
            if _is_devicelike:
                _mono_q = {
                    "question": "How is this product sold — and what is the unit of payment?",
                    "field": "monetization_unit",
                    "options": [
                        "hospital site license (annual, all patients included)",
                        "enrolled patient / per-case fee (usage-based)",
                        "enterprise SaaS — health-system-wide contract",
                        "procedure-bundled payment (CPT / DRG add-on)",
                    ],
                    "hint": "This determines whether your revenue model is volume-driven or seat-driven",
                    "binds_to": "price.deal_structure",
                    "inferred_model": "SiteLicenseModel",
                }
                questions = [_mono_q] + questions
            return {"questions": questions[:8], "pathway": pathway}
        # LLM returned no parseable questions — fall back to conditioned static bank
        logger.warning("/clarify: LLM returned no questions, falling back to static bank")
        if classification_hint and isinstance(classification_hint, dict):
            try:
                from app.services.product_classifier import (
                    Classification, get_conditioned_questions, questions_to_legacy_format,
                )
                _cls = Classification(
                    product_name=classification_hint.get("product_name", ""),
                    one_line=classification_hint.get("one_line", ""),
                    domain=classification_hint.get("domain", "LIFE_SCIENCES_CLINICAL"),
                    archetype=classification_hint.get("archetype", "therapeutic_small_molecule"),
                    trl=int(classification_hint.get("trl", 3)),
                    confidence=float(classification_hint.get("confidence", 0.5)),
                    ambiguities=classification_hint.get("ambiguities", []),
                )
                _legacy = questions_to_legacy_format(get_conditioned_questions(_cls))
                return {"questions": _legacy, "pathway": pathway, "conditioned": True}
            except Exception:
                pass
        return {"questions": [], "pathway": pathway}
    except Exception as e:
        # LLM call failed entirely — fall back to static bank before returning 500
        logger.warning("/clarify: LLM exception, falling back to static bank: %s", e)
        if classification_hint and isinstance(classification_hint, dict):
            try:
                from app.services.product_classifier import (
                    Classification, get_conditioned_questions, questions_to_legacy_format,
                )
                _cls = Classification(
                    product_name=classification_hint.get("product_name", ""),
                    one_line=classification_hint.get("one_line", ""),
                    domain=classification_hint.get("domain", "LIFE_SCIENCES_CLINICAL"),
                    archetype=classification_hint.get("archetype", "therapeutic_small_molecule"),
                    trl=int(classification_hint.get("trl", 3)),
                    confidence=float(classification_hint.get("confidence", 0.5)),
                    ambiguities=classification_hint.get("ambiguities", []),
                )
                _legacy = questions_to_legacy_format(get_conditioned_questions(_cls))
                return {"questions": _legacy, "pathway": pathway, "conditioned": True}
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=str(e))


# ── Non-Confidential Summary (NCS) generator ─────────────────────────────────

class NCSRequest(BaseModel):
    idea: str = Field(..., min_length=30, max_length=2000)
    product_type: str = Field(default="other")
    disease_name: Optional[str] = Field(default=None)
    development_stage: str = Field(default="preclinical",
        description="preclinical | phase1 | phase2 | phase3")
    institution: Optional[str] = Field(default=None,
        description="University/institution name for the NCS header")
    contact_name: Optional[str] = Field(default=None)
    contact_email: Optional[str] = Field(default=None)


@router.post("/ncs")
async def generate_ncs(payload: NCSRequest, current_user=Depends(get_current_user)):
    """
    Generate a Non-Confidential Summary (NCS) — the one-page document TTOs send
    to potential industry licensees.

    TTOs spend 3-5 hours writing each NCS manually. This endpoint auto-generates
    a complete, professionally formatted NCS from the PI's innovation description.

    The NCS includes: technology summary, applications, competitive advantages,
    development status (TRL), IP status, collaboration model, and contact information.
    """
    import anthropic, json as _json
    from app.core.config import settings

    # TRL assessment for development stage section
    trl_text = ""
    try:
        from app.services.trl_service import assess_trl
        trl = assess_trl(idea=payload.idea, development_phase=payload.development_stage)
        trl_text = f"TRL {trl.trl_level}/9 — {trl.trl_label}. {trl.trl_description}"
    except Exception:
        trl_text = f"Development stage: {payload.development_stage}"

    system = """You are a technology transfer professional at a leading research university.
Write a Non-Confidential Summary (NCS) exactly as TTOs write them to attract industry licensees.
The NCS must be concise, commercially focused, and use industry language — not academic language.
Return ONLY valid JSON with these exact fields:
{
  "title": "<technology title — 8-12 words, commercially appealing>",
  "technology_summary": "<2-3 sentences: what it is, how it works, what problem it solves — NO jargon>",
  "unmet_need": "<1-2 sentences: why existing solutions are inadequate, quantify if possible>",
  "applications": ["<primary application>", "<secondary application>", "<tertiary application>"],
  "competitive_advantages": ["<advantage 1 — be specific>", "<advantage 2>", "<advantage 3>"],
  "development_status": "<TRL level + what key experiments have been done>",
  "ip_status": "<patent filed/issued/pending + brief claim scope — do NOT reveal confidential details>",
  "collaboration_sought": "<type of partner: licensee, co-developer, sponsored research, option agreement>",
  "tagline": "<one sentence value proposition — the elevator pitch>"
}"""

    user = (
        f"Innovation description:\n{payload.idea}\n\n"
        f"Product type: {payload.product_type}\n"
        f"Disease/indication: {payload.disease_name or 'not specified'}\n"
        f"Development status: {trl_text}\n"
        f"Institution: {payload.institution or 'research university'}\n"
    )

    try:
        import asyncio as _aio
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        _ncs_loop = _aio.get_event_loop()
        msg = await _ncs_loop.run_in_executor(
            None,
            lambda: client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1200,
                system=system,
                messages=[{"role": "user", "content": user}],
            ),
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
        data = _json.loads(raw)

        # Add metadata
        data["development_status_trl"] = trl_text
        data["institution"]   = payload.institution or ""
        data["contact_name"]  = payload.contact_name or ""
        data["contact_email"] = payload.contact_email or ""
        data["generated_at"]  = datetime.utcnow().isoformat() + "Z"
        return data
    except Exception as e:
        logger.error("NCS generation failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ── Dataset Analysis (Edison Scientific play) ─────────────────────────────────

class DatasetAnalysisRequest(BaseModel):
    csv_data:          str  = Field(..., description="CSV text with column headers in first row")
    disease_name:      str  = Field(..., min_length=3, max_length=200)
    research_question: str  = Field(
        default="What do these results mean for drug development?",
        max_length=500,
    )


@router.post("/analyze-data")
async def analyze_experimental_data(
    payload: DatasetAnalysisRequest,
    current_user=Depends(get_current_user),
):
    """
    Upload experimental data (IC50 table, binding affinities, efficacy %, survival data,
    gene expression, clinical PK data) and receive:

      - Statistical summary (mean, median, IQR, range)
      - Benchmark comparison: how your values compare to published standards
        with specific PubMed citations (PMID-traceable, like Edison Scientific)
      - Commercialization implication: what these results mean for TRL,
        investor narrative, and regulatory pathway

    This is the mini-Edison play: your experimental data contextualized against
    published benchmarks, with every comparison traceable to a specific paper.

    CSV format: first row = column headers, subsequent rows = data.
    Example:
      Compound,IC50_nM,Selectivity_Index,Cytotox_CC50_uM
      Compound_A,45.2,28.4,189.5
      Compound_B,120.8,12.1,98.2
    """
    from app.services.dataset_analysis_service import analyze_dataset

    if len(payload.csv_data) > 50_000:
        raise HTTPException(status_code=400, detail="CSV too large — max 50,000 characters")

    try:
        result = await analyze_dataset(
            csv_text         = payload.csv_data,
            disease_name     = payload.disease_name,
            research_question = payload.research_question,
        )
        return {
            "disease_name":                   payload.disease_name,
            "data_type_identified":           result.inferred_data_type,
            "key_finding":                    result.key_finding,
            "benchmark_context":              result.benchmark_context,
            "commercialization_implication":  result.commercialization_implication,
            "supporting_pmids":               result.supporting_pmids,
            "column_stats": [
                {
                    "name":    c.name,
                    "n":       c.n,
                    "mean":    round(c.mean, 4) if c.mean is not None else None,
                    "median":  round(c.median, 4) if c.median is not None else None,
                    "std":     round(c.std, 4) if c.std is not None else None,
                    "min":     round(c.min, 4) if c.min is not None else None,
                    "max":     round(c.max, 4) if c.max is not None else None,
                    "p25":     round(c.p25, 4) if c.p25 is not None else None,
                    "p75":     round(c.p75, 4) if c.p75 is not None else None,
                }
                for c in result.column_stats
            ],
            "formatted_analysis": result.formatted,
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Dataset analysis failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ── Part E: Assumption Ledger endpoints ──────────────────────────────────────

class AssumptionOverrideRequest(BaseModel):
    value: float = Field(..., description="New numeric value for this assumption")
    note:  Optional[str] = Field(default=None, description="Optional note explaining the override")


@router.get("/pi-report/{job_id}/assumptions")
async def get_assumption_ledger(job_id: str, current_user=Depends(get_current_user)):
    """
    Part E: Return the full assumption ledger for a completed report.
    Includes all market sizing assumptions with provenance and sensitivity ranks.
    """
    from app.services.report_jobs import get_job
    job = await get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") != "done":
        raise HTTPException(status_code=409, detail="Report not yet complete")
    report_data = job.get("report") or {}
    ledger = report_data.get("assumption_ledger")
    if not ledger:
        raise HTTPException(status_code=404, detail="No assumption ledger for this report")
    return ledger


@router.get("/pi-report/{job_id}/assumptions/diff")
async def get_assumption_diff(job_id: str, current_user=Depends(get_current_user)):
    """
    Part E.3/E.4: Return user-overridden assumptions with original vs. new values.
    Includes TAM delta (absolute and % change in us_tam_usd) and version hash.
    Empty diffs list if no overrides have been applied.
    """
    from app.services.report_jobs import get_job
    from app.services.assumption_ledger_service import ledger_diff
    from app.models.alignment import AssumptionLedger, AssumptionSource
    job = await get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    report_data = job.get("report") or {}
    ledger_raw = report_data.get("assumption_ledger")
    if not ledger_raw:
        return {"diffs": [], "override_count": 0, "tam_delta": None, "version_hash": None}
    ledger = AssumptionLedger(**ledger_raw) if isinstance(ledger_raw, dict) else ledger_raw

    # E.3: compute TAM delta — compare original us_tam_usd to current value
    tam_delta = None
    for a in ledger.assumptions:
        if a.key == "us_tam_usd":
            original_tam = a.override_value if a.source == AssumptionSource.USER_OVERRIDE else a.value
            current_tam = a.value
            if original_tam and original_tam != current_tam:
                tam_delta = {
                    "original_usd": original_tam,
                    "current_usd":  current_tam,
                    "delta_usd":    current_tam - original_tam,
                    "delta_pct":    round((current_tam - original_tam) / original_tam * 100, 1)
                                    if original_tam else 0,
                }
            break

    return {
        "diffs":          ledger_diff(ledger),
        "override_count": ledger.override_count,
        "tam_delta":      tam_delta,
        "version_hash":   ledger.version_hash,
        "last_modified":  ledger.last_modified,
    }


@router.patch("/pi-report/{job_id}/assumptions/{assumption_key}")
async def override_assumption(
    job_id: str,
    assumption_key: str,
    body: AssumptionOverrideRequest,
    current_user=Depends(get_current_user),
):
    """
    Part E: Override a single assumption value.
    The original LLM-generated value is preserved in override_value for diff view.
    """
    from app.services.report_jobs import get_job, update_report
    from app.services.assumption_ledger_service import apply_override
    from app.models.alignment import AssumptionLedger

    job = await get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") != "done":
        raise HTTPException(status_code=409, detail="Report not yet complete")

    report_data = job.get("report") or {}
    ledger_raw = report_data.get("assumption_ledger")
    if not ledger_raw:
        raise HTTPException(status_code=404, detail="No assumption ledger for this report")

    ledger = AssumptionLedger(**ledger_raw) if isinstance(ledger_raw, dict) else ledger_raw
    updated_ledger, found = apply_override(ledger, assumption_key, body.value, body.note)
    if not found:
        raise HTTPException(
            status_code=404,
            detail=f"Assumption key '{assumption_key}' not found in ledger",
        )

    report_data["assumption_ledger"] = updated_ledger.model_dump()
    await update_report(job_id, report_data)
    logger.info(
        "Part E: assumption '%s' overridden to %.4g for job %s by user %s",
        assumption_key, body.value, job_id, getattr(current_user, "id", "?"),
    )
    return {
        "key": assumption_key,
        "new_value": body.value,
        "override_count": updated_ledger.override_count,
    }


# ── Part F: Market-sizing recompute + assumption persistence ──────────────────
#
# POST /market-sizing/recompute   — run funnel math with user overrides
# GET  /market-sizing/override    — load saved override for a segment/report
# GET  /market-sizing/overrides/{report_id} — list all overrides for a report
# DELETE /market-sizing/override  — revert (delete) a saved override


def _slugify(label: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def _run_funnel(gates: list[dict], net_price_usd: float, som_pct: float) -> dict:
    """
    Pure math: walk a funnel list and return TAM/SAM/SOM + step details.
    Gates format: [{gate, label, type: absolute|rate, value?, rate?, source?}]
    First gate must be absolute; all others are multiplied in sequence.
    """
    if not gates or gates[0].get("type") != "absolute":
        raise ValueError("Funnel must start with an absolute gate")

    running = float(gates[0].get("value", 0))
    steps = [{
        "gate":          gates[0]["gate"],
        "label":         gates[0].get("label", gates[0]["gate"]),
        "running_value": running,
        "type":          "absolute",
        "source":        gates[0].get("source", ""),
        "applied":       None,
    }]

    for g in gates[1:]:
        if g.get("type") == "absolute":
            running = float(g.get("value", running))
            applied = None
        else:
            rate = float(g.get("rate", 1.0))
            running = running * rate
            applied = rate
        steps.append({
            "gate":          g["gate"],
            "label":         g.get("label", g["gate"]),
            "running_value": round(running),
            "type":          g.get("type", "rate"),
            "source":        g.get("source", "analyst estimate — REVIEW"),
            "applied":       applied,
        })

    sam_pop  = round(running)
    sam_usd  = round(sam_pop * net_price_usd)
    tam_usd  = round(steps[0]["running_value"] * net_price_usd)
    som_pop  = round(sam_pop * som_pct)
    som_usd  = round(som_pop * net_price_usd)

    weakest = [s["label"] for s in steps if "REVIEW" in (s.get("source") or "") or not s.get("source")]
    return {
        "tam_usd":           tam_usd,
        "sam_population":    sam_pop,
        "sam_usd":           sam_usd,
        "som_population":    som_pop,
        "som_usd":           som_usd,
        "funnel_steps":      steps,
        "weakest_assumptions": weakest,
        "segments_used":     [],   # filled in by caller for multi-segment
    }


class _AddedGate(BaseModel):
    label:  str
    type:   str = Field(default="rate", pattern="^(absolute|rate)$")
    rate:   Optional[float] = Field(default=None, ge=0.0, le=1.0)
    value:  Optional[float] = Field(default=None, gt=0)
    source: Optional[str]   = None
    after:  Optional[str]   = None

    def as_gate_dict(self, slug: str) -> dict:
        return {
            "gate":   slug,
            "label":  self.label,
            "type":   self.type,
            "rate":   self.rate,
            "value":  self.value,
            "source": self.source or "analyst estimate — REVIEW",
        }


class _GateOverride(BaseModel):
    rate:  Optional[float] = Field(default=None, ge=0.0, le=1.0)
    value: Optional[float] = Field(default=None, gt=0)


class RecomputeRequest(BaseModel):
    segment_id:        int
    net_price_usd:     float = Field(..., gt=0)
    report_id:         Optional[str] = None
    persist:           bool = True
    label:             Optional[str] = None
    overrides:         dict[str, _GateOverride] = Field(default_factory=dict)
    added_gates:       list[_AddedGate]         = Field(default_factory=list)
    removed_gates:     list[str]                = Field(default_factory=list)
    extra_segment_ids: list[int]                = Field(default_factory=list)


@router.post("/market-sizing/recompute")
async def market_sizing_recompute(body: RecomputeRequest):
    """
    Recompute TAM/SAM/SOM for a segment with user-authored overrides.
    Optionally persists the override set so it can be reloaded with the report.
    No auth required — the segment and report IDs are the access control.
    """
    import app.db.market_segment_repository as _seg_repo
    import app.db.market_sizing_override_repository as _ovr_repo

    # ── Load base segment ──────────────────────────────────────────────────────
    seg = await _seg_repo.get_segment_by_id(body.segment_id)
    if not seg:
        raise HTTPException(status_code=404, detail=f"Segment {body.segment_id} not found")

    som_pct = float(seg.get("som_penetration_pct", 0.35))
    base_gates: list[dict] = [dict(g) for g in (seg.get("funnel") or [])]

    # ── Validate overrides reference real gates ────────────────────────────────
    gate_slugs = {g["gate"] for g in base_gates}
    for k in body.overrides:
        if k not in gate_slugs:
            raise HTTPException(status_code=400, detail=f"unknown gate '{k}' in overrides")

    # ── Validate removed_gates ─────────────────────────────────────────────────
    for r in body.removed_gates:
        if r not in gate_slugs:
            raise HTTPException(status_code=400, detail=f"unknown gate '{r}' in removed_gates")

    # ── Validate added_gates: absolute needs value, rate needs rate ────────────
    for ag in body.added_gates:
        if ag.type == "absolute" and ag.value is None:
            raise HTTPException(status_code=422, detail=f"absolute gate '{ag.label}' requires value")
        if ag.type == "rate" and ag.rate is None:
            raise HTTPException(status_code=422, detail=f"rate gate '{ag.label}' requires rate")
        if ag.after and ag.after not in gate_slugs:
            raise HTTPException(status_code=400, detail=f"after gate '{ag.after}' not in funnel")

    # ── Build working funnel ───────────────────────────────────────────────────
    # 1. Remove gates
    working = [g for g in base_gates if g["gate"] not in body.removed_gates]

    # 2. Apply overrides (only non-null fields)
    applied_overrides: dict = {}
    for gate_slug, ov in body.overrides.items():
        if ov.rate is None and ov.value is None:
            continue    # empty override — skip
        for g in working:
            if g["gate"] == gate_slug:
                if ov.rate is not None:
                    g["rate"] = ov.rate
                    applied_overrides[gate_slug] = {"rate": ov.rate}
                elif ov.value is not None:
                    g["value"] = ov.value
                    applied_overrides[gate_slug] = {"value": ov.value}

    # 3. Insert added gates (slugify label, disambiguate duplicates)
    used_slugs: set[str] = {g["gate"] for g in working}
    new_gate_dicts: list[dict] = []
    for ag in body.added_gates:
        slug = _slugify(ag.label)
        if slug in used_slugs:
            n = 2
            while f"{slug}_{n}" in used_slugs:
                n += 1
            slug = f"{slug}_{n}"
        used_slugs.add(slug)
        new_gate_dicts.append((ag.after, ag.as_gate_dict(slug)))

    # Insert after the specified gate (or append if no after)
    for after_gate, gd in new_gate_dicts:
        if after_gate:
            pos = next((i for i, g in enumerate(working) if g["gate"] == after_gate), None)
            if pos is not None:
                working.insert(pos + 1, gd)
            else:
                working.append(gd)
        else:
            working.append(gd)

    # 4. Guard: first gate must still be absolute
    if not working or working[0].get("type") != "absolute":
        raise HTTPException(status_code=400,
            detail="funnel must start with an absolute gate; cannot remove the base population gate")

    # ── Run math for primary segment ───────────────────────────────────────────
    result = _run_funnel(working, body.net_price_usd, som_pct)
    result["segments_used"] = [{"id": body.segment_id, "name": seg.get("segment_name", "")}]

    # ── Combine extra segments (additive SAM) ─────────────────────────────────
    for extra_id in body.extra_segment_ids:
        extra_seg = await _seg_repo.get_segment_by_id(extra_id)
        if not extra_seg:
            continue
        extra_result = _run_funnel(
            [dict(g) for g in (extra_seg.get("funnel") or [])],
            body.net_price_usd,
            float(extra_seg.get("som_penetration_pct", 0.35)),
        )
        result["sam_population"] += extra_result["sam_population"]
        result["sam_usd"]        += extra_result["sam_usd"]
        result["som_population"] += extra_result["som_population"]
        result["som_usd"]        += extra_result["som_usd"]
        result["tam_usd"]        = max(result["tam_usd"], extra_result["tam_usd"])
        result["segments_used"].append({"id": extra_id, "name": extra_seg.get("segment_name", "")})

    # ── Persist if report_id and persist=True ─────────────────────────────────
    saved = False
    saved_id = None
    if body.report_id and body.persist:
        saved_id = await _ovr_repo.save_override(
            report_id=body.report_id,
            segment_id=body.segment_id,
            user_id=None,
            net_price_usd=body.net_price_usd,
            overrides=applied_overrides,
            added_gates=[ag.model_dump() for ag in body.added_gates],
            removed_gates=body.removed_gates,
            extra_segment_ids=body.extra_segment_ids,
            tam_usd=result["tam_usd"],
            sam_usd=result["sam_usd"],
            som_usd=result["som_usd"],
            label=body.label,
        )
        saved = True

    return {
        "market_sizing":    result,
        "applied_overrides": applied_overrides,
        "saved":             saved,
        "saved_override_id": saved_id,
    }


@router.get("/market-sizing/override")
async def get_market_sizing_override(report_id: str, segment_id: int):
    """Load a previously saved override for a report+segment and recompute."""
    import app.db.market_segment_repository as _seg_repo
    import app.db.market_sizing_override_repository as _ovr_repo

    saved = await _ovr_repo.get_override(report_id, segment_id)
    if not saved:
        raise HTTPException(status_code=404, detail="No saved override for this report/segment")

    seg = await _seg_repo.get_segment_by_id(segment_id)
    if not seg:
        raise HTTPException(status_code=404, detail=f"Segment {segment_id} not found")

    # Reconstruct as a RecomputeRequest and replay
    ov_dict = saved.get("overrides") or {}
    added   = [_AddedGate(**ag) for ag in (saved.get("added_gates") or [])]
    removed = saved.get("removed_gates") or []

    # Build a fake body and re-run through the same logic
    fake = RecomputeRequest(
        segment_id=segment_id,
        net_price_usd=float(saved.get("net_price_usd", 25000)),
        overrides={k: _GateOverride(**v) for k, v in ov_dict.items()},
        added_gates=added,
        removed_gates=removed,
        extra_segment_ids=saved.get("extra_segment_ids") or [],
        persist=False,
    )
    resp = await market_sizing_recompute(fake)
    resp["applied_overrides"] = ov_dict
    resp["label"] = saved.get("label")
    return resp


@router.get("/market-sizing/overrides/{report_id}")
async def list_market_sizing_overrides(report_id: str):
    """List all saved overrides for a report (one per segment)."""
    import app.db.market_sizing_override_repository as _ovr_repo
    rows = await _ovr_repo.list_overrides_for_report(report_id)
    return {"report_id": report_id, "count": len(rows), "overrides": rows}


@router.delete("/market-sizing/override")
async def delete_market_sizing_override(report_id: str, segment_id: int):
    """Revert all custom assumptions for a segment (delete the saved override)."""
    import app.db.market_sizing_override_repository as _ovr_repo
    deleted = await _ovr_repo.delete_override(report_id, segment_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="No saved override to revert")
    return {"reverted": True}


# ── Part C: MarketModel editable nodes (research tool buyer model) ─────────────
#
# POST /market-model/{report_id}/edit   — edit a node, recompute, save new version
# GET  /market-model/{report_id}/versions  — list all versions + rationale
# GET  /market-model/{report_id}/diff/{v1}/{v2}  — diff two versions
# POST /market-model/{report_id}/revert/{version}  — restore a prior version


class _NodeEdit(BaseModel):
    node_id:    str = Field(..., description="pop | sp | sam_rate | som_rate")
    value_lo:   Optional[float] = Field(default=None, gt=0)
    value_hi:   Optional[float] = Field(default=None, gt=0)
    value_mid:  Optional[float] = Field(default=None, gt=0)
    rationale:  str = Field(..., min_length=1, max_length=500)
    base_version: Optional[int] = Field(default=None, ge=1)


def _recompute_buyer_model(nodes: dict) -> dict:
    """
    Deterministic recompute of the research-tool buyer model from editable nodes.
    Inputs: pop_lo, pop_hi, sp_lo, sp_hi, sam_lo, sam_hi, som_lo, som_hi
    Outputs: tam, sam, som + formatted strings
    """
    pop_lo  = float(nodes.get("pop_lo", 3000))
    pop_hi  = float(nodes.get("pop_hi", 8000))
    sp_lo   = float(nodes.get("sp_lo", 1000))
    sp_hi   = float(nodes.get("sp_hi", 5000))
    sam_lo  = float(nodes.get("sam_lo", 0.35))
    sam_hi  = float(nodes.get("sam_hi", 0.65))
    som_lo  = float(nodes.get("som_lo", 0.08))
    som_hi  = float(nodes.get("som_hi", 0.25))

    pop_mid = (pop_lo + pop_hi) / 2
    sp_mid  = (sp_lo  + sp_hi)  / 2
    sam_mid = (sam_lo + sam_hi) / 2
    som_mid = (som_lo + som_hi) / 2

    tam = pop_mid * sp_mid
    sam = tam * sam_mid
    som = sam * som_mid

    def _fmt(v: float) -> str:
        if v >= 1e9:  return f"${v/1e9:.1f}B"
        if v >= 1e6:  return f"${v/1e6:.1f}M"
        if v >= 1e3:  return f"${v/1e3:.0f}K"
        return f"${v:,.0f}"

    return {
        **nodes,
        "pop_lo": pop_lo, "pop_hi": pop_hi,
        "sp_lo": sp_lo,   "sp_hi": sp_hi,
        "sam_lo": sam_lo, "sam_hi": sam_hi,
        "som_lo": som_lo, "som_hi": som_hi,
        "us_tam_usd": tam,
        "us_sam_usd": sam,
        "us_som_usd": som,
        "tam_fmt": _fmt(tam),
        "sam_fmt": _fmt(sam),
        "som_fmt": _fmt(som),
        "steps": [
            {"step_num": 1, "title": "Eligible buyer population",
             "value": pop_mid, "unit": "labs",
             "formula": f"{pop_lo:,.0f}–{pop_hi:,.0f} labs"},
            {"step_num": 2, "title": "Annualised spend per lab",
             "value": sp_mid, "unit": "USD/lab/yr",
             "formula": f"${sp_lo:,.0f}–${sp_hi:,.0f}/yr"},
            {"step_num": 3, "title": "Total Addressable Market (TAM)",
             "value": tam, "unit": "USD",
             "formula": f"{pop_mid:,.0f} × ${sp_mid:,.0f} = {_fmt(tam)}"},
            {"step_num": 4, "title": "Serviceable Addressable Market (SAM)",
             "value": sam, "unit": "USD",
             "formula": f"{_fmt(tam)} × {sam_mid:.0%} = {_fmt(sam)}"},
            {"step_num": 5, "title": "Serviceable Obtainable Market (SOM, 5-yr)",
             "value": som, "unit": "USD",
             "formula": f"{_fmt(sam)} × {som_mid:.0%} = {_fmt(som)}"},
        ],
    }


def _diff_nodes(old: dict, new: dict) -> list:
    """Return list of changed parameters with old/new values."""
    diffs = []
    for key in ("pop_lo", "pop_hi", "sp_lo", "sp_hi", "sam_lo", "sam_hi", "som_lo", "som_hi"):
        ov = old.get(key)
        nv = new.get(key)
        if ov is not None and nv is not None and abs(float(ov) - float(nv)) > 1e-9:
            diffs.append({"param": key, "old": ov, "new": nv})
    for key in ("us_tam_usd", "us_sam_usd", "us_som_usd"):
        ov = old.get(key)
        nv = new.get(key)
        if ov is not None and nv is not None and abs(float(ov) - float(nv)) > 0.01:
            diffs.append({"param": key, "old": ov, "new": nv, "computed": True})
    return diffs


@router.post("/market-model/{report_id}/edit")
async def market_model_node_edit(
    report_id: str,
    body: _NodeEdit,
    current_user=Depends(get_current_user),
):
    """
    Edit one input node of the research-tool buyer model, recompute downstream,
    and save the result as a new immutable version. Returns the updated model + diff.
    """
    import app.db.market_model_repository as _mmr

    await _mmr.init_market_model_table()

    # Load the base version (user-specified or latest)
    if body.base_version:
        base = await _mmr.get_version(report_id, body.base_version)
    else:
        base = await _mmr.get_latest(report_id)

    if not base:
        raise HTTPException(status_code=404,
            detail="No buyer model found for this report. "
                   "Only research-tool reports (LIFE_SCIENCES_RESEARCH) have an editable buyer model.")

    nodes = dict(base.get("nodes") or {})

    # Apply the edit to the correct node(s)
    node = body.node_id
    if node == "pop":
        if body.value_lo is not None: nodes["pop_lo"] = body.value_lo
        if body.value_hi is not None: nodes["pop_hi"] = body.value_hi
        if body.value_mid is not None:
            spread = (nodes.get("pop_hi", 8000) - nodes.get("pop_lo", 3000)) / 2
            nodes["pop_lo"] = max(1, body.value_mid - spread)
            nodes["pop_hi"] = body.value_mid + spread
        nodes["pop_src"] = f"User edit: {body.rationale}"
    elif node == "sp":
        if body.value_lo is not None: nodes["sp_lo"] = body.value_lo
        if body.value_hi is not None: nodes["sp_hi"] = body.value_hi
        if body.value_mid is not None:
            spread = (nodes.get("sp_hi", 5000) - nodes.get("sp_lo", 1000)) / 2
            nodes["sp_lo"] = max(1, body.value_mid - spread)
            nodes["sp_hi"] = body.value_mid + spread
        nodes["sp_src"] = f"User edit: {body.rationale}"
    elif node == "sam_rate":
        if body.value_lo is not None: nodes["sam_lo"] = min(1.0, body.value_lo)
        if body.value_hi is not None: nodes["sam_hi"] = min(1.0, body.value_hi)
        if body.value_mid is not None:
            spread = (nodes.get("sam_hi", 0.65) - nodes.get("sam_lo", 0.35)) / 2
            nodes["sam_lo"] = max(0.01, body.value_mid - spread)
            nodes["sam_hi"] = min(1.0,  body.value_mid + spread)
    elif node == "som_rate":
        if body.value_lo is not None: nodes["som_lo"] = min(1.0, body.value_lo)
        if body.value_hi is not None: nodes["som_hi"] = min(1.0, body.value_hi)
        if body.value_mid is not None:
            spread = (nodes.get("som_hi", 0.25) - nodes.get("som_lo", 0.08)) / 2
            nodes["som_lo"] = max(0.01, body.value_mid - spread)
            nodes["som_hi"] = min(1.0,  body.value_mid + spread)
    else:
        raise HTTPException(status_code=400,
            detail=f"Unknown node_id '{node}'. Valid: pop | sp | sam_rate | som_rate")

    # Recompute
    new_nodes = _recompute_buyer_model(nodes)

    # Item 9: deterministic recommendation recompute — only SOM/TAM change; all other signals frozen
    _recommendation_update = None
    try:
        _comm_sigs = (base.get("nodes") or {}).get("_comm_signals")
        if _comm_sigs and isinstance(_comm_sigs, dict):
            from app.services.commercialization_decision_service import score_commercialization as _score_comm
            _sigs = dict(_comm_sigs)
            _sigs["som_usd"] = new_nodes.get("us_som_usd")
            _sigs["tam_usd"] = new_nodes.get("us_tam_usd")
            _cr = _score_comm(_sigs)
            _recommendation_update = {
                "recommendation":   _cr["recommendation"],
                "overall_priority": _cr["commercialization_scores"]["overall_priority"],
                "top_drivers":      _cr["top_drivers"],
            }
    except Exception as _rec_e:
        logger.warning("Item 9: recommendation recompute failed (non-fatal): %s", _rec_e)

    # Save new version
    parent_ver = base.get("version", 1)
    new_ver = await _mmr.save_edit(
        report_id=report_id,
        parent_version=parent_ver,
        nodes=new_nodes,
        rationale=body.rationale,
        user_id=getattr(current_user, "id", None),
    )

    # Diff against parent
    parent_nodes = _recompute_buyer_model(base.get("nodes") or {})
    diffs = _diff_nodes(parent_nodes, new_nodes)

    return {
        "version":              new_ver,
        "parent_version":       parent_ver,
        "rationale":            body.rationale,
        "nodes":                new_nodes,
        "diff":                 diffs,
        "tam_fmt":              new_nodes["tam_fmt"],
        "sam_fmt":              new_nodes["sam_fmt"],
        "som_fmt":              new_nodes["som_fmt"],
        "steps":                new_nodes.get("steps", []),
        "recommendation_update": _recommendation_update,  # Item 9
    }


@router.get("/market-model/{report_id}/versions")
async def list_market_model_versions(report_id: str):
    """List all saved versions of a report's buyer model (timeline + rationale)."""
    import app.db.market_model_repository as _mmr
    versions = await _mmr.list_versions(report_id)
    return {"report_id": report_id, "versions": versions, "count": len(versions)}


@router.get("/market-model/{report_id}/diff/{v1}/{v2}")
async def diff_market_model_versions(report_id: str, v1: int, v2: int):
    """Compare two model versions: what changed and by how much."""
    import app.db.market_model_repository as _mmr
    row1 = await _mmr.get_version(report_id, v1)
    row2 = await _mmr.get_version(report_id, v2)
    if not row1 or not row2:
        raise HTTPException(status_code=404, detail="One or both versions not found")
    n1 = _recompute_buyer_model(row1["nodes"])
    n2 = _recompute_buyer_model(row2["nodes"])
    return {
        "from_version": v1,
        "to_version":   v2,
        "diff":         _diff_nodes(n1, n2),
        "from": {"tam_fmt": n1["tam_fmt"], "sam_fmt": n1["sam_fmt"], "som_fmt": n1["som_fmt"]},
        "to":   {"tam_fmt": n2["tam_fmt"], "sam_fmt": n2["sam_fmt"], "som_fmt": n2["som_fmt"]},
        "rationale_from": row1.get("rationale"),
        "rationale_to":   row2.get("rationale"),
    }


@router.post("/market-model/{report_id}/revert/{version}")
async def revert_market_model(
    report_id: str, version: int, current_user=Depends(get_current_user)
):
    """Fork from a prior version, making it the new latest. Returns the restored model."""
    import app.db.market_model_repository as _mmr
    row = await _mmr.get_version(report_id, version)
    if not row:
        raise HTTPException(status_code=404, detail=f"Version {version} not found")
    new_nodes = _recompute_buyer_model(row["nodes"])
    new_ver = await _mmr.save_edit(
        report_id=report_id,
        parent_version=version,
        nodes=new_nodes,
        rationale=f"Reverted to version {version}",
        user_id=getattr(current_user, "id", None),
    )
    return {"version": new_ver, "parent_version": version, "nodes": new_nodes,
            "tam_fmt": new_nodes["tam_fmt"], "sam_fmt": new_nodes["sam_fmt"],
            "som_fmt": new_nodes["som_fmt"]}


# ── Spec v9: node-graph endpoints (richer response contract) ─────────────────
#
# These sit alongside the legacy /edit endpoint and use the new MarketModel
# object. The response shape matches spec Part 3.2.

class _OverrideRequest(BaseModel):
    node_id:   str   = Field(..., description="id of the node to override")
    value:     float = Field(..., description="new scalar value")
    rationale: str   = Field(..., min_length=1, max_length=500,
                             description="required — stored in override_events")
    version:   Optional[int] = Field(default=None, description="base version; latest if omitted")


class _GateRequest(BaseModel):
    target_node_id: str   = Field(..., description="node the gate multiplies")
    label:          str   = Field(..., description="human-readable name")
    value:          float = Field(..., gt=0, le=1.0, description="ratio in (0, 1]")
    rationale:      str   = Field(..., min_length=1, max_length=500)


def _build_override_response(old_m, new_m) -> dict:
    """Construct the spec Part 3.2 response from two model versions."""
    old_v = old_m.values()
    new_v = new_m.values()

    # diff — only nodes that changed
    diff_out = {}
    for nid, nv in new_v.items():
        ov = old_v.get(nid, nv)
        if abs(ov - nv) > 1e-9:
            denom = abs(ov) if abs(ov) > 1e-9 else 1.0
            diff_out[nid] = {"from": ov, "to": nv, "pct": round((nv - ov) / denom * 100, 1)}

    # recommendation recompute — predicate library, no LLM call
    recommendations_changed = []
    try:
        from app.services.recommendation_library import recommend as _lib_rec
        old_recs = {r.id: r.text for r in _lib_rec(old_v)}
        new_recs = {r.id: r.text for r in _lib_rec(new_v)}
        for rid in set(old_recs) | set(new_recs):
            if old_recs.get(rid) != new_recs.get(rid):
                recommendations_changed.append({
                    "id": rid,
                    "from": old_recs.get(rid, ""),
                    "to":   new_recs.get(rid, ""),
                })
    except Exception:
        pass

    # stale prose sections — sections that embed any changed node
    stale = []
    changed_nodes = set(diff_out.keys())
    if changed_nodes & {"tam", "buyer_population", "spend_per_unit"}:
        stale.extend(["executive_summary", "market_sizing"])
    if changed_nodes & {"sam", "sam_rate"}:
        stale.append("market_access")
    if changed_nodes & {"som", "som_rate"}:
        stale.extend(["strategic_risks", "recommended_next_steps"])

    fmt = new_m.formatted()
    # Active user-added gates — nodes with method="user_gate"
    active_gates = [
        {
            "id": nid,
            "label": n.label,
            "value": round(n.override_value if n.override_value is not None else (n.raw_value or 0), 4),
            "target_node_id": next(
                (tid for tid, tn in new_m.nodes.items() if nid in tn.gates), None
            ),
        }
        for nid, n in new_m.nodes.items()
        if n.method == "user_gate"
    ]
    return {
        "version":                   new_m.version,
        "parent_version":            new_m.parent_version,
        "model_hash":                new_m.model_hash(),
        "rationale":                 new_m.change_note,
        "values":                    new_v,
        "formatted":                 fmt,
        # legacy shape — kept so the existing frontend buyer-model panel still works
        "tam_fmt":                   fmt.get("tam", ""),
        "sam_fmt":                   fmt.get("sam", ""),
        "som_fmt":                   fmt.get("som", ""),
        "diff":                      diff_out,
        "active_gates":              active_gates,
        "recommendations_changed":   recommendations_changed,
        "verification":              {"state": "PASS", "issues": []},
        "export_unlocked":           True,
        "stale_narrative_sections":  stale,
    }


@router.post("/market-model/{report_id}/override")
async def market_model_override(
    report_id: str,
    body: _OverrideRequest,
    current_user=Depends(get_current_user),
):
    """Edit one node, recompute downstream, save as a new immutable version.

    Returns the spec Part 3.2 response including formatted values, diff,
    changed recommendations, and stale prose sections.

    422 if the edit would violate SAM ≤ TAM or SOM ≤ SAM.
    """
    from app.model import ModelStore
    import app.db.market_model_repository as _mmr

    await _mmr.init_market_model_table()
    store = ModelStore()

    old_m = await store.load(report_id, body.version)
    if old_m is None:
        raise HTTPException(status_code=404,
            detail="No market model found for this report. "
                   "Only research-tool reports have an editable buyer model.")

    try:
        new_m = old_m.with_override(
            body.node_id, body.value, body.rationale,
            str(getattr(current_user, "id", "anon")),
        )
    except AssertionError as e:
        raise HTTPException(status_code=422, detail=f"Invalid model state: {e}")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Unknown node: {e}")

    await store.save(new_m)

    # Log to override_events (non-fatal)
    try:
        old_node_val = old_m.values().get(body.node_id, 0.0)
        new_node_val = new_m.values().get(body.node_id, 0.0)
        old_som = old_m.values().get("som", 0.0)
        new_som = new_m.values().get("som", 0.0)
        delta_pct = ((new_som - old_som) / old_som * 100) if old_som else None
        await _mmr.insert_override_event(
            report_id=report_id,
            node_id=body.node_id,
            original_value=old_node_val,
            new_value=new_node_val,
            rationale=body.rationale,
            user_id=str(getattr(current_user, "id", "anon")),
            downstream_delta_pct=delta_pct,
        )
    except Exception as _oe_err:
        logger.warning("override_events logging failed (non-fatal): %s", _oe_err)

    return _build_override_response(old_m, new_m)


@router.post("/market-model/{report_id}/gate")
async def market_model_add_gate(
    report_id: str,
    body: _GateRequest,
    current_user=Depends(get_current_user),
):
    """Add a multiplicative gate to a node (e.g. 'only labs with vivarium, ×0.6')."""
    from app.model import ModelStore, Node
    import app.db.market_model_repository as _mmr

    await _mmr.init_market_model_table()
    store = ModelStore()

    old_m = await store.load(report_id)
    if old_m is None:
        raise HTTPException(status_code=404, detail="No market model found")

    import uuid as _uuid
    gate_id = f"gate_{_uuid.uuid4().hex[:8]}"
    gate = Node(
        id=gate_id,
        label=body.label,
        unit="ratio",
        raw_value=body.value,
        method="user_gate",
        rationale=body.rationale,
    )
    try:
        new_m = old_m.with_gate(body.target_node_id, gate)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    await store.save(new_m)

    resp = _build_override_response(old_m, new_m)
    resp["gate_id"] = gate_id
    return resp


@router.delete("/market-model/{report_id}/gate/{gate_id}")
async def market_model_remove_gate(
    report_id: str,
    gate_id: str,
    current_user=Depends(get_current_user),
):
    """Remove a previously added gate."""
    from app.model import ModelStore
    import app.db.market_model_repository as _mmr

    await _mmr.init_market_model_table()
    store = ModelStore()

    old_m = await store.load(report_id)
    if old_m is None:
        raise HTTPException(status_code=404, detail="No market model found")

    try:
        new_m = old_m.without_gate(gate_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    await store.save(new_m)
    return _build_override_response(old_m, new_m)


@router.post("/market-model/{report_id}/reset")
async def market_model_reset(
    report_id: str,
    current_user=Depends(get_current_user),
):
    """Revert to the engine-generated baseline (version 1)."""
    from app.model import ModelStore
    import app.db.market_model_repository as _mmr

    await _mmr.init_market_model_table()
    store = ModelStore()

    old_m = await store.load(report_id)
    baseline = await store.load(report_id, version=1)
    if old_m is None or baseline is None:
        raise HTTPException(status_code=404, detail="No market model found")

    # Create a new version that points back to version 1's nodes
    from app.model.market_model import MarketModel, _new_id, _utcnow
    from dataclasses import replace as _replace
    reset_m = _replace(
        baseline,
        id=_new_id(),
        version=old_m.version + 1,
        parent_version=old_m.version,
        created_at=_utcnow(),
        created_by="user",
        change_note="Reset to engine baseline (v1)",
    )
    await store.save(reset_m)
    return _build_override_response(old_m, reset_m)


# ── market-model.js NL assumption endpoints ──────────────────────────────────

_ASSUMPTION_PARSE_PROMPT = """You parse a PI's natural-language market assumption into a list of
typed operations against a 4-key market model.

Model keys (all numeric):
  buyer_population  — number of eligible buyers (integer count)
  spend_per_unit    — annualised spend per buyer in USD (float)
  sam_rate          — fraction of buyers reachable (0.0–1.0)
  som_rate          — 5-year market penetration fraction (0.0–1.0)

Operation types:
  gate   — multiplicative filter: value × factor (factor in [0,1])
  set    — override to a specific absolute value
  cap    — ceiling: new value = min(current, cap)
  floor  — floor: new value = max(current, floor)
  note   — on-record only; no numeric change (for qualitative observations)

Return ONLY valid JSON, no prose:
{
  "ops": [
    {
      "op":          "gate" | "set" | "cap" | "floor" | "note",
      "target":      "buyer_population" | "spend_per_unit" | "sam_rate" | "som_rate",
      "value":       <number>,
      "label":       "<short human label for the ledger>",
      "quoted_span": "<verbatim fragment from input that justifies this op>",
      "confidence":  <0.0–1.0>,
      "unit":        "<optional display unit string>"
    }
  ],
  "clarifying_question": null | "<question to ask if a required number is missing>"
}

Rules:
- If the text mentions a fraction or percentage of buyers, use gate on buyer_population.
- If the text mentions a price ceiling or cap, use cap on spend_per_unit.
- If the text is qualitative with no number, use note (omit target/value).
- Rates (sam_rate, som_rate) must be in [0, 1]; convert percentages to decimals.
- Set clarifying_question when the intent is clear but a required number is absent.
- Do not invent facts; only extract what the text says."""


async def _parse_assumption_nl(text: str, state: dict, ops: list) -> dict:
    """Call Claude to parse NL text into market model operations."""
    import os, json as _json
    import httpx

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    context = f"""Current model state: {_json.dumps(state)}
Existing ops already applied: {_json.dumps(ops)}

New assumption text from the PI:
"{text}"

Return the parsed ops JSON."""

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model":      "claude-haiku-4-5-20251001",
                "max_tokens": 512,
                "temperature": 0,
                "system":     _ASSUMPTION_PARSE_PROMPT,
                "messages":   [{"role": "user", "content": context}],
            },
        )
    resp.raise_for_status()
    raw = resp.json()["content"][0]["text"].strip()

    # Strip markdown fences
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return _json.loads(raw.strip())


class _ParseBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    state: dict = Field(default_factory=dict)
    ops: list    = Field(default_factory=list)


class _ApplyBody(BaseModel):
    text: str = Field(default="")
    ops:  list = Field(default_factory=list)


_REGEN_SYSTEM_PROMPT = """You rewrite one paragraph of a market sizing report after the user
adjusted the model inputs. Your output becomes the new paragraph — nothing else.

Rules:
1. Keep the same structure and approximate sentence count as the original.
2. Update every specific number to the new values supplied.
3. If a qualitative judgment (e.g. "does not support a priced round") is no longer
   accurate given the updated figures, revise it to match the new magnitude.
4. Keep the same analytical voice and tense.
5. For any market value you write, use a placeholder token so the frontend can
   keep the number live. Tokens (use exactly as written):
     {{buyer_population}}  — eligible buyer count
     {{spend_per_unit}}    — annualised spend per buyer (USD)
     {{tam}}               — total addressable market (USD)
     {{sam}}               — serviceable addressable market (USD)
     {{som}}               — serviceable obtainable market (USD)
6. Output ONLY the paragraph text. No headers, markdown, explanation, or surrounding quotes."""


class _RegenBody(BaseModel):
    section:         str  = Field(default="")
    original_text:   str  = Field(default="", max_length=4000)
    current_values:  dict = Field(default_factory=dict)
    baseline_values: dict = Field(default_factory=dict)
    assumptions:     list = Field(default_factory=list)


@router.post("/reports/{report_id}/assumptions/parse")
async def parse_assumption(
    report_id: str,
    body: _ParseBody,
    current_user=Depends(get_current_user),
):
    """Parse a natural-language assumption into typed market model operations.

    Called by market-model.js when the user clicks Interpret. Returns ops
    that the frontend previews before the user chooses to apply or discard.
    """
    try:
        result = await _parse_assumption_nl(body.text, body.state, body.ops)
    except Exception as exc:
        logger.error("assumption parse failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"LLM parse error: {exc}")
    return result


@router.get("/reports/{report_id}/assumptions")
async def list_assumptions(
    report_id: str,
    current_user=Depends(get_current_user),
):
    """Return persisted NL assumption ops for a report (used on page reload)."""
    import app.db.market_model_repository as _mmr
    try:
        await _mmr.init_nl_assumptions_table()
        return await _mmr.list_nl_assumptions(report_id)
    except Exception as exc:
        logger.warning("list_assumptions non-fatal: %s", exc)
        return []


@router.post("/reports/{report_id}/assumptions/apply")
async def apply_assumption(
    report_id: str,
    body: _ApplyBody,
    current_user=Depends(get_current_user),
):
    """Persist applied assumption ops so they survive page reload."""
    import app.db.market_model_repository as _mmr
    await _mmr.init_nl_assumptions_table()
    for op in (body.ops or []):
        op_dict = op if isinstance(op, dict) else op.model_dump()
        if not op_dict.get("id"):
            continue
        try:
            await _mmr.save_nl_assumption(report_id, op_dict)
        except Exception as exc:
            logger.warning("save_nl_assumption non-fatal: %s", exc)
    return {"ok": True}


@router.delete("/reports/{report_id}/assumptions/{assumption_id}")
async def delete_assumption(
    report_id: str,
    assumption_id: str,
    current_user=Depends(get_current_user),
):
    """Remove one persisted assumption op from the ledger."""
    import app.db.market_model_repository as _mmr
    try:
        await _mmr.init_nl_assumptions_table()
        await _mmr.delete_nl_assumption(report_id, assumption_id)
    except Exception as exc:
        logger.warning("delete_nl_assumption non-fatal: %s", exc)
    return {"ok": True}


@router.post("/reports/{report_id}/assumptions/regenerate-section")
async def regenerate_section(
    report_id: str,
    body: _RegenBody,
    current_user=Depends(get_current_user),
):
    """Rewrite one narrative paragraph using the updated market model values.

    Called when the user clicks 'Regenerate this section' on a stale paragraph.
    Uses Haiku to rewrite the prose; placeholders in the output are replaced with
    data-node-tagged spans so the numbers remain live after injection.
    """
    import os, httpx

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")

    def _usd(v):
        v = float(v or 0)
        if v >= 1e9: return f'${v/1e9:.1f}B'
        if v >= 1e6: return f'${v/1e6:.1f}M'
        if v >= 1e3: return f'${round(v/1e3):,}K'
        return f'${round(v):,}'

    def _int_fmt(v):
        return f'{round(float(v or 0)):,}'

    cv = body.current_values
    bv = body.baseline_values

    assumptions_txt = "\n".join(
        f"  {o.get('op','?')} {o.get('target','?')}"
        f"{'×' if o.get('op')=='gate' else ' ='}{o.get('value','?')}: "
        f"\"{o.get('quoted_span','')}\"" for o in (body.assumptions or [])
    ) or "  (none)"

    user_msg = (
        f"Original paragraph:\n\"\"\"{body.original_text}\"\"\"\n\n"
        f"Baseline: TAM {_usd(bv.get('tam',0))}, SAM {_usd(bv.get('sam',0))}, "
        f"SOM {_usd(bv.get('som',0))}\n\n"
        f"Updated values:\n"
        f"  Buyer population: {_int_fmt(cv.get('buyer_population',0))}\n"
        f"  Spend/unit: {_usd(cv.get('spend_per_unit',0))}\n"
        f"  TAM: {_usd(cv.get('tam',0))}\n"
        f"  SAM: {_usd(cv.get('sam',0))}\n"
        f"  SOM: {_usd(cv.get('som',0))}\n\n"
        f"Assumptions applied by the user:\n{assumptions_txt}\n\n"
        "Rewrite the paragraph. Use {{buyer_population}}, {{spend_per_unit}}, "
        "{{tam}}, {{sam}}, {{som}} as placeholder tokens for every market figure."
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model":       "claude-haiku-4-5-20251001",
                    "max_tokens":  512,
                    "temperature": 0.3,
                    "system":      _REGEN_SYSTEM_PROMPT,
                    "messages":    [{"role": "user", "content": user_msg}],
                },
            )
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"].strip().strip('"')
    except Exception as exc:
        logger.error("regenerate_section failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    # Replace {{key}} placeholders with formatted + data-node-tagged spans
    FMT = {
        "tam": _usd, "sam": _usd, "som": _usd,
        "spend_per_unit": _usd, "buyer_population": _int_fmt,
    }
    html = raw
    for key, fn in FMT.items():
        placeholder = "{{" + key + "}}"
        if placeholder in html:
            span = f'<span class="mv" data-node="{key}">{fn(cv.get(key, 0))}</span>'
            html = html.replace(placeholder, span)

    return {"html": html}
