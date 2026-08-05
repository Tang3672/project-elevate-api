"""
Competitive Intelligence Service
=================================
Pulls live data from four sources at report time:
1. ClinicalTrials.gov — active competitor trials with enrollment/endpoints
2. FDA drugs@FDA — approval history and precedents for comparable drugs
3. CMS ASP — actual Medicare reimbursement pricing
4. Web search — strategic moves by comparable companies

Runs in parallel with main report generation.
"""

import asyncio
import json
import logging
import os
from typing import Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

CLINICAL_TRIALS_URL  = "https://clinicaltrials.gov/api/v2/studies"
FDA_DRUGS_URL        = "https://api.fda.gov/drug/drugsfda.json"
TIMEOUT              = 15.0

# H-04: relevance gate constants
_HAIKU_MODEL         = "claude-haiku-4-5-20251001"
_ANTHROPIC_API_URL   = "https://api.anthropic.com/v1/messages"
_RELEVANCE_THRESHOLD = 6   # 0-10 Haiku judge score; comparators below this are dropped
_MIN_COMPARATORS     = 3   # fewer than this and we emit the honest empty-state

_RESEARCH_TOOL_ARCHETYPES: frozenset[str] = frozenset({
    "research_tool_non_clinical",
    "research_infrastructure_saas",
})

# For non-clinical research tools, ClinicalTrials.gov and FDA drugs@FDA are the
# wrong corpora.  Return a canned list of genuine functional comparators instead.
_RESEARCH_TOOL_COMPARATORS: list[dict] = [
    {
        "name":         "ActiGraph (Actigraph LLC)",
        "category":     "Commercial research wearable logger",
        "description":  "Industry-standard wearable motion sensing and movement data logger used in NIH-funded trials. "
                        "GT9X Link and CentrePoint platform. Dominant in clinical research; weak at custom firmware.",
        "url":          "https://actigraphcorp.com",
        "incumbent":    True,
    },
    {
        "name":         "Empatica EmbracePlus (research tier)",
        "category":     "Research wearable + cloud data pipeline",
        "description":  "FDA-cleared as medical but also sold to academic researchers under a research-tier license. "
                        "Strong in CNS/epilepsy research. REST API for data export.",
        "url":          "https://www.empatica.com/embraceplus/",
        "incumbent":    False,
    },
    {
        "name":         "Movisens Move4 / EcgMove4",
        "category":     "Research sensor + movisensXS software",
        "description":  "German research-grade wearable sensor platform for ambulatory monitoring. "
                        "Strong in European academic research networks. Per-device one-time license.",
        "url":          "https://www.movisens.com",
        "incumbent":    False,
    },
    {
        "name":         "Golioth IoT platform",
        "category":     "Cloud infrastructure for embedded device fleets",
        "description":  "Firmware OTA + device telemetry platform for custom embedded devices. "
                        "Competes on device-fleet management for labs that build their own hardware.",
        "url":          "https://golioth.io",
        "incumbent":    False,
    },
    {
        "name":         "Blues Wireless (Notecard)",
        "category":     "Low-power cellular data logging module",
        "description":  "Cellular IoT module with pre-paid global data for sensor telemetry. "
                        "Competes when the lab needs offline → cloud data transport without WiFi.",
        "url":          "https://blues.com",
        "incumbent":    False,
    },
    {
        "name":         "Memfault",
        "category":     "Embedded device monitoring & crash analytics",
        "description":  "Device observability platform: crash reporting, OTA, and metrics for embedded devices. "
                        "Competes on lab-built device fleets that need telemetry without a data scientist.",
        "url":          "https://memfault.com",
        "incumbent":    False,
    },
    {
        "name":         "DIY / Status quo (SD-card + lab scripts)",
        "category":     "Status quo — no commercial product",
        "description":  "Most academic neurotech labs write custom Python/MATLAB scripts and store data on SD cards "
                        "or lab-managed servers. Zero direct cost; high researcher time cost. The dominant incumbent.",
        "url":          "",
        "incumbent":    True,
    },
]

# Honest empty-state text by archetype — emitted when the wrong corpus is queried
_HONEST_EMPTY_STATE: dict[str, str] = {
    "research_tool_non_clinical": (
        "No functional comparators were identified through ClinicalTrials.gov or FDA drugs@FDA "
        "(these databases index clinical-use regulated products and are not the correct corpus "
        "for a non-clinical research data-logging platform). "
        "Genuine functional comparators are commercial research tools (see above), not FDA-regulated devices."
    ),
}


# ── DOMAIN → SEARCH TERMS MAPPING ────────────────────────────────────────────

DOMAIN_SEARCH_TERMS = {
    "drug_amr":              {"condition": "antibiotic resistant infection", "terms": ["antibiotic", "antimicrobial", "ESKAPE", "carbapenem", "MRSA", "CRE"]},
    "drug_oncology":         {"condition": "cancer", "terms": ["kinase inhibitor", "targeted therapy", "checkpoint", "oncology"]},
    "drug_cns":              {"condition": "neurological disorder", "terms": ["CNS", "neurology", "brain", "neurodegeneration"]},
    "drug_cardiology":       {"condition": "cardiovascular disease", "terms": ["heart failure", "cardiac", "cardiovascular"]},
    "drug_metabolic":        {"condition": "metabolic disorder", "terms": ["diabetes", "obesity", "metabolic syndrome", "NASH"]},
    "drug_mental_health":    {"condition": "psychiatric disorder", "terms": ["depression", "schizophrenia", "bipolar", "anxiety"]},
    "drug_rare_disease":     {"condition": "rare disease", "terms": ["orphan", "rare disease", "genetic disorder"]},
    "drug_infectious_non_amr": {"condition": "infectious disease", "terms": ["antiviral", "HIV", "hepatitis", "fungal"]},
    "drug_immunology":       {"condition": "autoimmune disease", "terms": ["autoimmune", "inflammation", "rheumatoid", "lupus"]},
    "biologic_oncology":     {"condition": "cancer", "terms": ["monoclonal antibody", "checkpoint inhibitor", "ADC", "bispecific"]},
    "biologic_immunology":   {"condition": "autoimmune", "terms": ["biologic", "monoclonal antibody", "TNF", "IL-6"]},
    "biologic_hematology":   {"condition": "hematologic disorder", "terms": ["hematology", "anemia", "coagulation", "myeloma"]},
    "biologic_rare_disease": {"condition": "rare disease", "terms": ["enzyme replacement", "biologic", "orphan"]},
    "biologic_cardiology":   {"condition": "cardiovascular", "terms": ["cardiac biologic", "heart failure biologic"]},
    "gene_therapy_rare":     {"condition": "rare genetic disease", "terms": ["gene therapy", "AAV", "gene replacement"]},
    "gene_therapy_oncology": {"condition": "cancer", "terms": ["CAR-T", "gene therapy", "cell therapy", "TIL"]},
    "gene_therapy_cns":      {"condition": "neurological disease", "terms": ["gene therapy", "CNS", "neurological AAV"]},
    "gene_therapy_rna":      {"condition": "RNA therapy", "terms": ["siRNA", "ASO", "mRNA", "RNAi"]},
    "gene_therapy_hematology": {"condition": "hematologic disease", "terms": ["gene therapy", "hemophilia", "sickle cell"]},
    "device_cardiovascular": {"condition": "cardiovascular disease", "terms": ["cardiac device", "heart valve", "TAVR", "pacemaker"]},
    "device_metabolic":      {"condition": "metabolic disease", "terms": ["CGM", "insulin pump", "diabetes device"]},
    "device_neurology":      {"condition": "neurological disease", "terms": ["neuromodulation", "DBS", "spinal cord"]},
    "diagnostic_molecular":  {"condition": "infectious disease", "terms": ["molecular diagnostic", "PCR", "NGS", "liquid biopsy"]},
    "diagnostic_companion":  {"condition": "cancer", "terms": ["companion diagnostic", "biomarker", "CDx"]},
    "digital_cds":           {"condition": "clinical decision support", "terms": ["AI diagnostic", "clinical decision support", "SaMD"]},
    "digital_therapeutic":   {"condition": "behavioral health", "terms": ["digital therapeutic", "DTx", "app-based therapy"]},
    "digital_rpm":           {"condition": "chronic disease", "terms": ["remote monitoring", "wearable", "telehealth"]},
    "vaccine_prophylactic":  {"condition": "infectious disease", "terms": ["vaccine", "prophylactic", "immunization"]},
    "vaccine_cancer_immuno": {"condition": "cancer", "terms": ["cancer vaccine", "therapeutic vaccine", "neoantigen"]},
    "other_microbiome":      {"condition": "microbiome disorder", "terms": ["microbiome", "FMT", "probiotic therapeutic"]},
    "other_crispr":          {"condition": "genetic disease", "terms": ["CRISPR", "gene editing", "base editing"]},
    "other_delivery":        {"condition": "drug delivery", "terms": ["nanoparticle", "drug delivery", "lipid nanoparticle"]},
    # Non-clinical research tools — ClinicalTrials.gov is not the right corpus,
    # but include terms so callers can still perform keyword searches if needed.
    "research_tool_non_clinical":   {"condition": "research data logging wearable", "terms": ["ambulatory monitoring", "wearable sensor", "data logger", "research platform", "wearable monitoring"]},
    "research_infrastructure_saas": {"condition": "research software platform", "terms": ["lab informatics", "research data management", "device telemetry", "IoT platform"]},
}

# ── SPECIAL STRATEGIES BY DOMAIN ─────────────────────────────────────────────

DOMAIN_STRATEGIES = {
    "drug_amr": [
        {
            "strategy": "Antibiotic-beta-lactamase inhibitor combination packaging",
            "description": "Package a novel beta-lactam with a new beta-lactamase inhibitor to extend spectrum and create IP protection on both components. Avibactam alone has no activity — combined with ceftazidime it becomes Avycaz. This strategy extends patent life and closes resistance gaps simultaneously.",
            "example_company": "Pfizer / AstraZeneca (Avycaz)",
            "example_drug": "Ceftazidime-avibactam (Avycaz)",
            "what_they_did": "AstraZeneca licensed avibactam from Novexel and combined it with off-patent ceftazidime. The combination created a new patentable entity with QIDP designation. AZ sold US rights to Pfizer for $1.6B in 2016.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/26063370/",
            "applicability": "Any BLI developer should consider which existing off-patent beta-lactam best complements their inhibitor spectrum."
        },
        {
            "strategy": "Orphan-like LPAD approval for resistant subset then label expansion",
            "description": "Seek LPAD approval for a narrowly defined resistant pathogen subset (e.g., NDM-producing CRE only) with a smaller trial, then pursue sNDA for broader gram-negative indication post-commercialization.",
            "example_company": "Pfizer",
            "example_drug": "Aztreonam-avibactam (Emblaveo)",
            "what_they_did": "Pfizer + AZ developed aztreonam-avibactam specifically targeting MBL-producing organisms (NDM, VIM, IMP) that avibactam-based regimens cannot cover. FDA approved 2024 for cUTI/cIAI. Plan to expand to HABP/VABP.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/36223745/",
            "applicability": "If your antibiotic covers a resistance mechanism no approved drug covers, use LPAD for rapid approval in that niche, then expand."
        },
        {
            "strategy": "Non-dilutive BARDA partnership before Phase 3 to derisk equity raise",
            "description": "Secure BARDA contract ($50-500M) before beginning Phase 3 to fund the most expensive development stage without dilution, then raise equity post-BARDA for commercialization.",
            "example_company": "Paratek Pharmaceuticals",
            "example_drug": "Omadacycline (Nuzyra)",
            "what_they_did": "Paratek received $216M BARDA contract to fund Phase 3 trials for CABP and ABSSSI. This allowed them to complete two Phase 3 trials without major equity dilution. Approved 2018.",
            "source_url": "https://medicalcountermeasures.gov/barda/cbrn/broad-spectrum-antimicrobials/",
            "applicability": "Any novel antibiotic against a national security pathogen (CRE, Acinetobacter, anthrax) should pursue BARDA before Phase 3."
        },
    ],
    "drug_oncology": [
        {
            "strategy": "Biomarker enrichment + companion diagnostic co-development for accelerated approval",
            "description": "Identify a molecular biomarker that predicts response, co-develop a CDx, and use accelerated approval on ORR in the biomarker-positive subset. Dramatically reduces sample size and gets to market 3-4 years faster than unselected population trial.",
            "example_company": "Pfizer",
            "example_drug": "Crizotinib (Xalkori) with Vysis ALK FISH CDx",
            "what_they_did": "Pfizer identified ALK rearrangement as predictive biomarker, partnered with Abbott for ALK FISH CDx, ran 82-patient Phase 1/2 showing 57% ORR, got accelerated approval 2011 — 5 years faster than standard. Peak sales $600M+.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/20979469/",
            "applicability": "Any targeted therapy where biomarker can be prospectively identified should co-develop CDx from Phase 1."
        },
        {
            "strategy": "Tumor-agnostic approval across multiple cancer types with single MSI-H biomarker",
            "description": "Rather than seeking indication-by-indication approvals, pursue FDA tumor-agnostic approval based on molecular marker. One trial across multiple tumor types. Opens entire oncology market simultaneously.",
            "example_company": "Merck",
            "example_drug": "Pembrolizumab (Keytruda) — MSI-H/dMMR tumor-agnostic",
            "what_they_did": "Merck ran KEYNOTE-158 basket trial across 10+ tumor types in MSI-H patients. FDA granted first tumor-agnostic approval 2017. Now covers 40+ indications. Strategy: one biomarker, all cancers.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/28967792/",
            "applicability": "Any immunotherapy or targeted therapy with a pan-tumor biomarker should design a basket trial for tumor-agnostic approval."
        },
        {
            "strategy": "Adjuvant indication expansion after metastatic approval to 10x patient population",
            "description": "Get initial approval in metastatic/advanced setting (faster, smaller trial), then run adjuvant trial in early-stage disease. Adjuvant market is 5-10x larger by patient volume.",
            "example_company": "AstraZeneca",
            "example_drug": "Olaparib (Lynparza)",
            "what_they_did": "AZ got Lynparza approved in metastatic BRCA+ ovarian cancer first (2014), then expanded to adjuvant breast (OlympiA trial, 2021) — dramatically increasing addressable population. Annual revenue went from $500M to $2.7B.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/34081848/",
            "applicability": "Design your Phase 3 program with adjuvant expansion in mind from the start. Biomarker selection and trial design must support both indications."
        },
    ],
    "biologic_oncology": [
        {
            "strategy": "ADC payload licensing + existing antibody combination to create novel ADC",
            "description": "License a validated payload/linker technology and attach it to an antibody targeting a novel antigen. Avoids reinventing payload chemistry — focus differentiation on target selection and indication.",
            "example_company": "Daiichi Sankyo / AstraZeneca",
            "example_drug": "Trastuzumab deruxtecan (Enhertu)",
            "what_they_did": "Daiichi Sankyo developed DXd topoisomerase I inhibitor payload with cleavable linker. Combined with trastuzumab (existing HER2 antibody). AZ paid $6.9B for global rights 2019. Now treating HER2+ breast, gastric, NSCLC. ORR 70%+ in HER2+ breast.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/31189866/",
            "applicability": "If you have a validated antibody against a tumor antigen, licensing a proven payload/linker platform is faster than developing novel chemistry."
        },
        {
            "strategy": "BiTE/bispecific T-cell engager for liquid tumors with step-up dosing for CRS management",
            "description": "Design bispecific engaging CD3 on T cells + tumor antigen. Use step-up dosing protocol to manage CRS and enable outpatient administration. Target liquid tumors first (faster enrollment, clearer endpoints).",
            "example_company": "Amgen",
            "example_drug": "Blinatumomab (Blincyto)",
            "what_they_did": "Amgen developed BiTE platform, got accelerated approval for R/R ALL 2014. Step-up dosing (9mcg → 28mcg) dramatically reduced CRS severity. TOWER trial showed OS benefit. Expanded to MRD+ ALL. Now $500M+/yr.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/28087395/",
            "applicability": "CRS management protocol is make-or-break for T-cell engagers. File REMS early and design step-up dosing into Phase 1."
        },
    ],
    "gene_therapy_rare": [
        {
            "strategy": "One-time curative pricing with outcomes-based contract to overcome payer resistance",
            "description": "Price the therapy at the net present value of lifetime disease management costs. Offer payer outcomes-based contracts (payment over 3-5 years tied to durability outcomes) to reduce budget impact and enable coverage.",
            "example_company": "AveXis / Novartis",
            "example_drug": "Onasemnogene abeparvovec (Zolgensma)",
            "what_they_did": "AveXis priced Zolgensma at $2.125M, justified by $4-5M lifetime cost of nusinersen + supportive care. Offered annuity payment model to Medicaid (5yr installments). Medicare/Medicaid coverage secured within 6 months of approval.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/31399232/",
            "applicability": "Any one-time gene therapy must model outcomes-based contracts into commercial strategy from Phase 2. Engage ICER and major PBMs 18 months pre-approval."
        },
        {
            "strategy": "Natural history study as external control arm to reduce trial size by 50-70%",
            "description": "Establish a prospective natural history study or use existing registries as external control. FDA accepts single-arm trials with historical controls for rare diseases where randomization is unethical.",
            "example_company": "Spark Therapeutics",
            "example_drug": "Voretigene neparvovec (Luxturna)",
            "what_they_did": "Spark used a randomized delayed-treatment design (not placebo) — 21 patients treated vs 10 delayed. FDA accepted this because blinding was impossible and disease was well-characterized. Approved 2017.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/28873341/",
            "applicability": "Establish natural history database as early as Phase 1. Partner with patient registries (NORD, disease foundations) to collect pre-treatment data."
        },
    ],
    "device_cardiovascular": [
        {
            "strategy": "Lower-risk indication first (510k) then PMA expansion to higher-risk indication",
            "description": "Get 510(k) clearance for monitoring/diagnostic application first (faster, no clinical trial), build clinical evidence, then use that data to support PMA for therapeutic application.",
            "example_company": "Medtronic",
            "example_drug": "Reveal LINQ ICM → Arctic Front cardiac ablation",
            "what_they_did": "Medtronic cleared LINQ ICM via 510(k) for arrhythmia monitoring. Built real-world evidence base of AFib detection. Used that data to support PMA for AFib ablation catheters. ICM data justified ablation need.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/25765320/",
            "applicability": "If your therapy requires PMA, consider whether a diagnostic 510(k) companion can generate clinical evidence and market access simultaneously."
        },
    ],
    "diagnostic_molecular": [
        {
            "strategy": "LDT-first commercial launch while pursuing 510(k)/PMA clearance",
            "description": "Launch as laboratory-developed test (LDT) immediately after CLIA validation — no FDA clearance required (historically). Generate revenue and real-world data during FDA clearance process (18-24 months). Use real-world data to strengthen 510(k)/PMA submission.",
            "example_company": "Genomic Health (now Exact Sciences)",
            "example_drug": "Oncotype DX breast cancer recurrence score",
            "what_they_did": "Genomic Health launched Oncotype DX as LDT in 2004 without FDA clearance. Built $100M+ revenue base and massive clinical evidence (TAILORx trial). FDA cleared 2017 as IVD — 13 years after commercial launch. LDT revenue funded the clinical evidence that got FDA clearance.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/25028123/",
            "applicability": "Under new FDA LDT rule (2024), 4-year phase-in gives window for LDT-first strategy. Plan FDA submission from day 1 but launch LDT immediately post-CLIA validation."
        },
    ],
    "vaccine_prophylactic": [
        {
            "strategy": "BARDA OTA (Other Transaction Authority) contract for pandemic-relevant vaccines",
            "description": "Structure vaccine development as a BARDA OTA contract rather than traditional grant. OTA contracts are faster to execute, allow cost-sharing, and can include procurement guarantees that de-risk the entire development program.",
            "example_company": "Moderna",
            "example_drug": "mRNA-1273 (Spikevax)",
            "what_they_did": "Moderna received $955M BARDA OTA in 2020 for Phase 3 and manufacturing scale-up. OTA structure allowed faster contracting than FAR-based grants. Procurement guarantee of 100M doses de-risked manufacturing investment.",
            "source_url": "https://medicalcountermeasures.gov/barda/cbrn/covid-19/",
            "applicability": "Any vaccine against a pathogen on BARDA priority list (pandemic flu, COVID variants, bioterrorism agents) should pursue OTA structure for maximum funding speed."
        },
    ],
}

# Fill remaining domains with generic strategies
_DEFAULT_STRATEGIES = [
    {
        "strategy": "Seek multiple FDA expedited designations simultaneously",
        "description": "Stack Breakthrough Therapy + Fast Track + Priority Review + Orphan Drug (if applicable) to maximize regulatory acceleration. Each designation provides independent benefits that compound.",
        "example_company": "Multiple — standard practice for rare/serious conditions",
        "example_drug": "Most recently approved rare disease drugs have 3+ designations",
        "what_they_did": "Companies like Vertex (for CF modulators) and Sarepta (for DMD) systematically obtained all applicable designations, cutting review timelines by 40-50%.",
        "source_url": "https://www.fda.gov/patients/fast-track-breakthrough-therapy-accelerated-approval-priority-review/fast-track",
        "applicability": "File for all applicable designations simultaneously at Phase 1 completion. Each has a different eligibility bar — don't assume disqualification."
    },
]

# B-04: non-clinical archetypes must never inherit clinical _DEFAULT_STRATEGIES.
# Their strategies come from strategy_database.format_strategies_for_report.
_NON_CLINICAL_ARCHETYPES = frozenset({"research_tool_non_clinical", "research_infrastructure_saas"})
for domain in DOMAIN_SEARCH_TERMS:
    if domain not in DOMAIN_STRATEGIES and domain not in _NON_CLINICAL_ARCHETYPES:
        DOMAIN_STRATEGIES[domain] = _DEFAULT_STRATEGIES


# ── CLINICALTRIALS.GOV FETCHER ────────────────────────────────────────────────

async def get_competitor_trials(disease_name: str, sub_expert_id: str, max_results: int = 8) -> Dict:
    """Pull active competitor trials from ClinicalTrials.gov."""
    search_terms = DOMAIN_SEARCH_TERMS.get(sub_expert_id, {})
    condition = disease_name or search_terms.get("condition", "")
    
    results = {"trials": [], "total_found": 0, "disease": disease_name}
    
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            params = {
                "query.cond": condition,
                "filter.overallStatus": "RECRUITING,ACTIVE_NOT_RECRUITING,ENROLLING_BY_INVITATION",
                "pageSize": max_results,
                "format": "json",
                "fields": "NCTId,BriefTitle,Phase,EnrollmentCount,PrimaryCompletionDate,LeadSponsorName,InterventionName,OverallStatus,StartDate,PrimaryOutcomeMeasure",
            }
            
            r = await client.get(CLINICAL_TRIALS_URL, params=params)
            if r.status_code != 200:
                logger.warning(f"ClinicalTrials.gov returned {r.status_code}")
                return results
            
            data = r.json()
            studies = data.get("studies", [])
            results["total_found"] = data.get("totalCount", len(studies))
            
            for study in studies[:max_results]:
                proto = study.get("protocolSection", {})
                id_mod = proto.get("identificationModule", {})
                design_mod = proto.get("designModule", {})
                sponsor_mod = proto.get("sponsorCollaboratorsModule", {})
                status_mod = proto.get("statusModule", {})
                interventions = proto.get("armsInterventionsModule", {}).get("interventions", [])
                outcomes = proto.get("outcomesModule", {}).get("primaryOutcomes", [])
                
                phases = design_mod.get("phases", [])
                phase_str = ", ".join(phases) if phases else "N/A"
                
                intervention_names = [i.get("name", "") for i in interventions[:3]]
                primary_outcome = outcomes[0].get("measure", "") if outcomes else ""
                
                results["trials"].append({
                    "nct_id": id_mod.get("nctId", ""),
                    "title": id_mod.get("briefTitle", "")[:120],
                    "phase": phase_str,
                    "status": status_mod.get("overallStatus", ""),
                    "sponsor": sponsor_mod.get("leadSponsor", {}).get("name", ""),
                    "enrollment": design_mod.get("enrollmentInfo", {}).get("count", "N/A"),
                    "start_date": status_mod.get("startDateStruct", {}).get("date", ""),
                    "primary_completion": status_mod.get("primaryCompletionDateStruct", {}).get("date", ""),
                    "interventions": intervention_names,
                    "primary_outcome": primary_outcome[:150],
                    "url": f"https://clinicaltrials.gov/study/{id_mod.get('nctId', '')}",
                })
    
    except Exception as e:
        logger.warning(f"ClinicalTrials.gov fetch failed: {e}")
    
    return results


# ── FDA APPROVAL PRECEDENTS FETCHER ──────────────────────────────────────────

async def get_fda_precedents(disease_name: str, sub_expert_id: str) -> Dict:
    """Pull FDA approval precedents for comparable drugs."""
    results = {"approvals": [], "disease": disease_name}
    
    # Map domain to relevant FDA search terms
    fda_search_map = {
        "drug_amr": "ceftazidime OR avycaz OR vabomere OR fetroja OR recarbrio OR emblaveo",
        "drug_oncology": "kinase inhibitor OR checkpoint inhibitor OR parp inhibitor",
        "biologic_oncology": "checkpoint inhibitor OR monoclonal antibody OR ADC",
        "gene_therapy_rare": "gene therapy OR AAV OR gene replacement",
        "device_cardiovascular": "cardiac device OR TAVR OR pacemaker",
        "diagnostic_molecular": "molecular diagnostic OR companion diagnostic",
        "vaccine_prophylactic": "vaccine OR prophylactic immunization",
    }
    
    search_term = fda_search_map.get(sub_expert_id, disease_name.split("(")[0].strip())
    
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(FDA_DRUGS_URL, params={
                "search": f"products.brand_name:{search_term.split()[0]}",
                "limit": 5,
            })
            
            if r.status_code == 200:
                data = r.json()
                for result in data.get("results", [])[:5]:
                    submissions = result.get("submissions", [])
                    approval_sub = next((s for s in submissions if s.get("action_type") == "AP"), None)
                    
                    products = result.get("products", [])
                    brand_names = [p.get("brand_name", "") for p in products if p.get("brand_name")]
                    
                    if brand_names and approval_sub:
                        results["approvals"].append({
                            "application_number": result.get("application_number", ""),
                            "sponsor": result.get("sponsor_name", ""),
                            "brand_name": brand_names[0] if brand_names else "",
                            "approval_date": approval_sub.get("submission_status_date", ""),
                            "application_type": result.get("application_type", ""),
                            "url": f"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo={result.get('application_number','').replace('NDA','').replace('BLA','').replace('ANDA','')}",
                        })
    except Exception as e:
        logger.warning(f"FDA precedents fetch failed: {e}")
    
    return results


# ── H-04: RELEVANCE GATE ─────────────────────────────────────────────────────

async def _score_comparator_relevance(
    product_desc: str,
    comparator_name: str,
    comparator_desc: str,
    archetype: str = "",
) -> int:
    """
    Call Haiku to score functional substitutability between the focal product
    and a comparator on a 0–10 scale. Returns -1 on failure (caller treats as unknown).
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return -1
    system = (
        "You are a biomedical competitive intelligence analyst. "
        "Score the degree to which a comparator is a functional substitute or direct competitor "
        "for the focal product on a scale of 0–10. "
        "0 = completely unrelated, 10 = near-identical substitutes. "
        "Respond with ONLY valid JSON: {\"score\": N, \"reason\": \"one sentence\"}. "
        "No other text."
    )
    user = (
        f"Focal product: {product_desc[:300]}\n"
        f"Archetype: {archetype}\n"
        f"Comparator: {comparator_name} — {comparator_desc[:300]}\n"
        "What is the functional substitutability score (0-10)?"
    )
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(
                _ANTHROPIC_API_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": _HAIKU_MODEL,
                    "max_tokens": 80,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
            )
            r.raise_for_status()
            text = r.json()["content"][0]["text"]
            parsed = json.loads(text)
            score = int(parsed.get("score", -1))
            return max(0, min(10, score))
    except Exception as _e:
        logger.debug("Relevance judge failed for '%s': %s", comparator_name[:40], _e)
        return -1


async def _filter_trials_by_relevance(
    trials: list,
    product_desc: str,
    archetype: str = "",
) -> tuple[list, list]:
    """
    Score each trial for relevance to the focal product.
    Returns (passed, dropped) where passed are those scoring ≥ _RELEVANCE_THRESHOLD.
    Trials whose score is -1 (judge call failed) are kept (fail open).
    """
    if not trials or not product_desc:
        return trials, []

    tasks = [
        _score_comparator_relevance(
            product_desc,
            t.get("title", "")[:120],
            f"Phase {t.get('phase','')} trial for {t.get('condition','')} by {t.get('sponsor','')}",
            archetype,
        )
        for t in trials
    ]
    scores = await asyncio.gather(*tasks, return_exceptions=True)

    passed, dropped = [], []
    for trial, score in zip(trials, scores):
        s = score if isinstance(score, int) else -1
        if s < 0 or s >= _RELEVANCE_THRESHOLD:   # -1 = unknown → keep (fail open)
            passed.append(trial)
        else:
            dropped.append(trial)
            logger.debug(
                "H-04 relevance gate: dropped trial '%s' (score=%d < %d)",
                trial.get("title", "")[:60], s, _RELEVANCE_THRESHOLD,
            )
    return passed, dropped


async def _gather_research_tool_intel(disease_name: str, sub_expert_id: str) -> Dict:
    """
    For non-clinical research tool archetypes: skip ClinicalTrials.gov and FDA
    (wrong corpora), return the static comparator list with an honest explanation.

    B-04: strategies come from strategy_database (archetype-specific), never
    from _DEFAULT_STRATEGIES (clinical FDA designations).
    """
    from app.services.strategy_database import format_strategies_for_report
    archetype_note = _HONEST_EMPTY_STATE.get("research_tool_non_clinical", "")
    return {
        "competitor_trials":    {"trials": [], "total_found": 0, "corpus_note": archetype_note},
        "fda_precedents":       {"approvals": [], "corpus_note": archetype_note},
        "research_tool_comparators": _RESEARCH_TOOL_COMPARATORS,
        "strategic_playbook":   format_strategies_for_report(sub_expert_id),
        "honest_empty_state":   archetype_note,
    }


# ── MAIN INTELLIGENCE GATHERER ────────────────────────────────────────────────

async def gather_competitive_intelligence(
    disease_name: str,
    sub_expert_id: str,
    product_desc: str = "",   # H-04: used by relevance judge; defaults to disease_name
) -> Dict:
    """
    Run all intelligence gathering in parallel.
    Returns combined dict with trials, FDA precedents, and strategies.

    H-04: research_tool archetypes skip ClinicalTrials.gov/FDA (wrong corpora)
    and get a static comparator list instead. Other archetypes apply a Haiku
    relevance gate (score ≥ 6/10) with an honest empty state if <3 pass.
    """
    # H-04: short-circuit for non-clinical research tools
    _arch = (sub_expert_id or "").lower()
    if any(_arch == rt or _arch.startswith(rt) for rt in _RESEARCH_TOOL_ARCHETYPES):
        logger.info("H-04: research tool archetype '%s' — skipping CT.gov/FDA, returning research tool comparators", _arch)
        return await _gather_research_tool_intel(disease_name, sub_expert_id)

    # Standard path: query ClinicalTrials.gov + FDA in parallel
    trials_task = get_competitor_trials(disease_name, sub_expert_id)
    fda_task    = get_fda_precedents(disease_name, sub_expert_id)

    trials_data, fda_data = await asyncio.gather(
        trials_task, fda_task,
        return_exceptions=True
    )

    if isinstance(trials_data, Exception):
        logger.warning("Trials fetch failed: %s", trials_data)
        trials_data = {"trials": [], "total_found": 0}

    if isinstance(fda_data, Exception):
        logger.warning("FDA fetch failed: %s", fda_data)
        fda_data = {"approvals": []}

    # H-04: apply relevance gate to trials
    _desc = product_desc or disease_name
    _trials_raw = trials_data.get("trials", [])
    _honest_empty = ""
    if _trials_raw and _desc:
        try:
            _passed, _dropped = await _filter_trials_by_relevance(_trials_raw, _desc, _arch)
            if len(_passed) < _MIN_COMPARATORS and _dropped:
                logger.info(
                    "H-04 relevance gate: %d/%d trials passed for '%s' (threshold %d/10)",
                    len(_passed), len(_trials_raw), disease_name, _RELEVANCE_THRESHOLD,
                )
                if len(_passed) < _MIN_COMPARATORS:
                    _honest_empty = (
                        f"Automated retrieval from ClinicalTrials.gov returned {len(_trials_raw)} result(s) "
                        f"but only {len(_passed)} scored ≥{_RELEVANCE_THRESHOLD}/10 on functional substitutability. "
                        "No functional comparators were identified through automated retrieval. "
                        "Manual competitive landscape research recommended."
                    )
            trials_data = {"trials": _passed, "total_found": len(_passed), "dropped_count": len(_dropped)}
        except Exception as _rg_e:
            logger.warning("H-04 relevance gate failed (non-fatal): %s", _rg_e)

    # B-04: always resolve strategies through strategy_database (archetype-gated,
    # no minimum-count padding) rather than falling back to _DEFAULT_STRATEGIES.
    from app.services.strategy_database import format_strategies_for_report
    strategies = format_strategies_for_report(sub_expert_id)

    result = {
        "competitor_trials":  trials_data,
        "fda_precedents":     fda_data,
        "strategic_playbook": strategies,
    }
    if _honest_empty:
        result["honest_empty_state"] = _honest_empty
    return result


def format_intelligence_for_expert(intel: Dict, disease_name: str) -> str:
    """Format competitive intelligence as expert context."""
    lines = [f"\n=== LIVE COMPETITIVE INTELLIGENCE: {disease_name.upper()} ===\n"]

    # H-04: honest empty state (emitted before comparators so context is clear)
    honest_empty = intel.get("honest_empty_state", "")
    if honest_empty:
        lines.append(f"NOTE: {honest_empty}\n")

    # H-04: research tool comparators (replaces CT.gov trials for non-clinical tools)
    rt_comparators = intel.get("research_tool_comparators", [])
    if rt_comparators:
        lines.append("FUNCTIONAL COMPARATORS — COMMERCIAL RESEARCH TOOL LANDSCAPE:")
        lines.append("These are genuine functional substitutes, not FDA-regulated clinical devices.\n")
        for c in rt_comparators:
            tag = " [INCUMBENT]" if c.get("incumbent") else ""
            lines.append(f"  {c['name']}{tag} | {c['category']}")
            lines.append(f"  {c['description']}")
            if c.get("url"):
                lines.append(f"  URL: {c['url']}")
            lines.append("")

    # Competitor trials (standard path — clinical archetypes only)
    trials = intel.get("competitor_trials", {}).get("trials", [])
    corpus_note = intel.get("competitor_trials", {}).get("corpus_note", "")
    if trials:
        lines.append(f"ACTIVE COMPETITOR TRIALS ({intel['competitor_trials'].get('total_found', len(trials))} passed relevance gate on ClinicalTrials.gov):")
        lines.append("Use these to identify gaps in current development landscape and position your differentiation.\n")
        for t in trials[:6]:
            lines.append(f"  {t['nct_id']} | {t['phase']} | {t['sponsor']}")
            lines.append(f"  Title: {t['title']}")
            lines.append(f"  Status: {t['status']} | Enrollment: {t['enrollment']} | Completion: {t['primary_completion']}")
            if t.get('primary_outcome'):
                lines.append(f"  Primary endpoint: {t['primary_outcome']}")
            lines.append(f"  URL: {t['url']}\n")
    elif corpus_note:
        lines.append(f"COMPETITOR TRIALS: [corpus not applicable — {corpus_note[:120]}]\n")

    # FDA precedents
    approvals = intel.get("fda_precedents", {}).get("approvals", [])
    fda_note = intel.get("fda_precedents", {}).get("corpus_note", "")
    if approvals:
        lines.append("FDA APPROVAL PRECEDENTS (cite these for regulatory pathway justification):")
        for a in approvals[:4]:
            lines.append(f"  {a['brand_name']} | {a['application_number']} | {a['sponsor']} | Approved: {a['approval_date']}")
            lines.append(f"  URL: {a['url']}\n")
    elif fda_note:
        lines.append(f"FDA PRECEDENTS: [corpus not applicable — {fda_note[:120]}]\n")

    # Strategic playbook
    strategies = intel.get("strategic_playbook", [])
    if strategies:
        lines.append("STRATEGIC PLAYBOOK — PROVEN STRATEGIES FROM THIS SPACE:")
        lines.append("Include a 'Strategic Playbook' section in your report covering these strategies.\n")
        for s in strategies[:3]:
            lines.append(f"  STRATEGY: {s['strategy']}")
            lines.append(f"  Real example: {s['example_company']} with {s['example_drug']}")
            lines.append(f"  What they did: {s['what_they_did']}")
            lines.append(f"  Source: {s['source_url']}")
            lines.append(f"  Apply to your product: {s['applicability']}\n")

    if trials:
        lines.append("[CRITICAL: Cite specific NCT IDs and FDA application numbers in your report. Use the strategic playbook to generate a Strategic Playbook section with named examples.]")
    else:
        lines.append("[NOTE: No regulatory trial comparators available for this archetype. Use the functional comparator list above for competitive positioning.]")

    return "\n".join(lines)
