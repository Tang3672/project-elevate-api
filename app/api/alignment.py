"""
Alignment API v2
================
POST /api/v1/alignment/check        — legacy (original inventors, returns AlignmentReport)
POST /api/v1/alignment/pi-report    — new PI endpoint (returns full PIReport with
                                      market sizing, regulatory pathway, disease intel)
GET  /api/v1/alignment/examples     — example ideas
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from app.services.alignment_service import generate_alignment_report, generate_pi_report
from app.models.alignment import AlignmentReport, PIReport

logger = logging.getLogger(__name__)
router = APIRouter()


class AlignmentRequest(BaseModel):
    idea: str = Field(..., min_length=30, max_length=2000)


class PIReportRequest(BaseModel):
    idea: str = Field(..., min_length=30, max_length=2000,
        description="Description of the product — what it does, who it's for, what it solves")
    product_type: str = Field(default="other",
        description="antibiotic | medical_device | software | diagnostic | other")
    target_pathogen: Optional[str] = Field(default=None,
        description="For antibiotics: primary target pathogen (e.g. MRSA, CRE, C. difficile)")
    disease_domain: str = Field(default="auto",
        description="auto | antibiotic_amr | oncology | cardiology | neurology_cns | metabolic_diabetes | mental_health")
    tier1_category: str = Field(default="drug_small_molecule",
        description="drug_small_molecule | biologic | gene_cell_therapy | medical_device | diagnostic | digital_health | vaccine_immunotherapy | other_platform")
    disease_domain: str = Field(default="auto",
        description="auto | antibiotic_amr | oncology | cardiology | neurology_cns | metabolic_diabetes | mental_health")
    tier1_category: str = Field(default="drug_small_molecule",
        description="drug_small_molecule | biologic | gene_cell_therapy | medical_device | diagnostic | digital_health | vaccine_immunotherapy | other_platform")


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


@router.post("/pi-report", response_model=PIReport)
async def get_pi_report(payload: PIReportRequest):
    """
    Full PI go-to-market intelligence report.

    For antibiotics: includes disease intelligence, transparent bottom-up market
    sizing, FDA regulatory pathway (QIDP/LPAD/Fast Track), clinical trial
    requirements, P&T committee access strategy, friction points and loopholes,
    BARDA/CARB-X funding programs — all with explicit source citations.

    Takes 20-40 seconds.
    """
    try:
        idea = payload.idea
        if payload.target_pathogen:
            idea = f"{idea}\n\nTarget pathogen: {payload.target_pathogen}"
        report = await generate_pi_report(idea, payload.product_type, payload.disease_domain, getattr(payload, "tier1_category", "drug_small_molecule"))
        # Increment free report counter if not subscribed
        try:
            if current_user:
                from app.db.user_repository import get_user_by_id, increment_free_report_count
                user = await get_user_by_id(current_user["id"])
                status = user.get("subscription_status", "none") if user else "none"
                dev_emails = {"test@projectelevate.io", "ijw91021@gmail.com", "admin@projectelevate.io"}
                if status not in ("active", "trialing") and current_user.get("email") not in dev_emails:
                    await increment_free_report_count(current_user["id"])
        except Exception as inc_e:
            import logging; logging.getLogger(__name__).warning(f"Failed to increment free report count: {inc_e}")
        return report
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"PI report failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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
            {"title": "Clinical Practice Guidelines by IDSA for Skin and Soft Tissue Infections", "authors": "Stevens DL et al.", "journal": "Clinical Infectious Diseases", "year": "2014", "pmid": "24947530", "source_url": "https://pubmed.ncbi.nlm.nih.gov/24947530/", "relevance": "Primary clinical guideline defining MRSA SSTI treatment standards and endpoint definitions for clinical trials."},
            {"title": "Delafloxacin versus Moxifloxacin for Acute Bacterial Skin and Skin Structure Infections", "authors": "Kingsley J et al.", "journal": "New England Journal of Medicine", "year": "2017", "pmid": "28537196", "source_url": "https://pubmed.ncbi.nlm.nih.gov/28537196/", "relevance": "Pivotal Phase 3 trial establishing ABSSSI endpoint design precedent for novel oral MRSA agents."},
            {"title": "Prevalence of community-associated methicillin-resistant Staphylococcus aureus", "authors": "Hersh AL et al.", "journal": "JAMA", "year": "2008", "pmid": "18577731", "source_url": "https://pubmed.ncbi.nlm.nih.gov/18577731/", "relevance": "Establishes epidemiological basis for outpatient MRSA SSTI market sizing."}
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
                {"phase": "Phase 1", "patient_count": "60-80", "duration": "12-18 months", "estimated_cost": "$8-12M", "key_endpoints": ["Single/multiple ascending dose PK", "Safety and tolerability", "Food effect", "Drug-drug interactions"], "fda_guidance_document": "General Clinical Pharmacology Guidance", "source_url": "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-pharmacology-considerations-antibacterial-drugs", "success_probability": "85-90%"},
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
