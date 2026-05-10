"""
Knowledge Retriever
===================
Replaces static system_prompt knowledge with live retrieval
from authoritative sources at report time.

For each sub-expert + specific disease, runs 5-6 parallel
targeted web searches pulling from:
  - fda.gov (guidance documents, drug approvals, labels)
  - clinicaltrials.gov (current pipeline)
  - cdc.gov / nih.gov (epidemiology)
  - pubmed / ncbi (systematic reviews, meta-analyses)
  - Disease-specific authoritative sources

Returns ~8,000-10,000 words of current, sourced context
ready to inject into the Researcher Claude's prompt.
"""

import asyncio
import logging
from typing import List, Dict, Optional
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
SEARCH_MODEL      = "claude-sonnet-4-6"
SEARCH_TIMEOUT    = 30.0


# ── Search Templates per Sub-Expert ──────────────────────────────────────────
# {disease} and {product} are interpolated at runtime from the Disease Classifier

SEARCH_TEMPLATES: Dict[str, List[str]] = {

    # ── Drug / Small Molecule ─────────────────────────────────────────────────
    "drug_amr": [
        "FDA guidance {disease} antibiotic clinical trial design site:fda.gov",
        "CDC {disease} epidemiology surveillance report 2024 site:cdc.gov",
        "{disease} approved antibiotics pipeline clinical trials 2024 site:clinicaltrials.gov",
        "CARB-X BARDA {disease} antibiotic funding open applications 2024",
        "{disease} resistance mechanism treatment outcomes mortality 2024",
        "IDSA {disease} treatment guidelines recommendations site:idsociety.org",
    ],
    "drug_oncology": [
        "FDA {disease} drug approvals 2023 2024 site:fda.gov",
        "{disease} clinical trials Phase 2 3 active recruiting site:clinicaltrials.gov",
        "{disease} incidence survival statistics SEER 2024 site:seer.cancer.gov",
        "{disease} standard of care NCCN ASCO guidelines 2024",
        "{disease} targeted therapy biomarkers resistance mechanisms 2024",
        "NCI SBIR {disease} funding opportunities 2024 site:cancer.gov",
    ],
    "drug_cns": [
        "FDA {disease} drug approval guidance site:fda.gov",
        "{disease} clinical trials 2024 Phase 2 3 site:clinicaltrials.gov",
        "{disease} epidemiology prevalence incidence NIH 2024 site:nih.gov OR site:nimh.nih.gov",
        "{disease} standard of care treatment guidelines 2024",
        "{disease} unmet need treatment failure biomarkers 2024",
        "NINDS {disease} research funding priorities 2024 site:ninds.nih.gov",
    ],
    "drug_cardiology": [
        "FDA {disease} cardiovascular drug approval 2024 site:fda.gov",
        "{disease} clinical trials outcomes 2024 site:clinicaltrials.gov",
        "ACC AHA {disease} treatment guidelines 2024 site:acc.org OR site:ahajournals.org",
        "{disease} epidemiology burden statistics AHA 2024 site:heart.org",
        "{disease} unmet need treatment gaps standard of care 2024",
        "NHLBI {disease} research priorities funding 2024 site:nhlbi.nih.gov",
    ],
    "drug_metabolic": [
        "FDA {disease} drug approval 2024 site:fda.gov",
        "{disease} clinical trials recruiting 2024 site:clinicaltrials.gov",
        "CDC {disease} statistics prevalence 2024 site:cdc.gov",
        "ADA {disease} standards of care treatment guidelines 2024",
        "{disease} unmet need treatment outcomes real world data 2024",
        "NIDDK {disease} research funding 2024 site:niddk.nih.gov",
    ],
    "drug_mental_health": [
        "FDA {disease} psychiatric drug approval 2024 site:fda.gov",
        "{disease} clinical trials Phase 2 3 2024 site:clinicaltrials.gov",
        "NIMH {disease} statistics prevalence burden 2024 site:nimh.nih.gov",
        "{disease} treatment guidelines APA recommendations 2024",
        "{disease} treatment resistance unmet need 2024",
        "SAMHSA {disease} access shortage data 2024 site:samhsa.gov",
    ],
    "drug_rare_disease": [
        "FDA orphan drug {disease} approval designation 2024 site:fda.gov",
        "{disease} natural history clinical trials site:clinicaltrials.gov",
        "{disease} prevalence incidence epidemiology NORD Orphanet 2024",
        "FDA OOPD orphan products grant {disease} funding site:fda.gov",
        "{disease} current treatment standard of care limitations 2024",
        "patient advocacy {disease} foundation research funding 2024",
    ],
    "drug_infectious_non_amr": [
        "FDA {disease} antiviral drug approval 2024 site:fda.gov",
        "{disease} clinical trials Phase 2 3 2024 site:clinicaltrials.gov",
        "CDC WHO {disease} global epidemiology burden 2024",
        "{disease} treatment guidelines WHO IDSA 2024",
        "PEPFAR BARDA CEPI {disease} funding programs 2024",
        "{disease} drug resistance treatment failure pipeline 2024",
    ],
    "drug_immunology": [
        "FDA {disease} biologic small molecule approval 2024 site:fda.gov",
        "{disease} clinical trials JAK inhibitor biologic 2024 site:clinicaltrials.gov",
        "ACR EULAR {disease} treatment guidelines 2024",
        "{disease} epidemiology burden prevalence 2024",
        "{disease} biosimilar competition treatment landscape 2024",
        "NIAMS {disease} research funding 2024 site:niams.nih.gov",
    ],

    # ── Biologic ──────────────────────────────────────────────────────────────
    "biologic_oncology": [
        "FDA {disease} biologic mAb ADC approval 2024 site:fda.gov",
        "{disease} monoclonal antibody clinical trials Phase 3 site:clinicaltrials.gov",
        "{disease} biomarker companion diagnostic FDA 2024",
        "{disease} immunotherapy checkpoint inhibitor outcomes 2024",
        "{disease} ADC antibody drug conjugate pipeline 2024",
        "NCI {disease} biologic funding SBIR 2024 site:cancer.gov",
    ],
    "biologic_immunology": [
        "FDA {disease} biologic approval 2024 site:fda.gov",
        "{disease} IL inhibitor TNF biologic clinical trials 2024",
        "{disease} treatment guidelines ACR EULAR 2024",
        "{disease} biosimilar competition market landscape 2024",
        "{disease} real world outcomes biologic therapy 2024",
        "NIAMS {disease} biologic research funding 2024",
    ],
    "biologic_hematology": [
        "FDA {disease} hematology biologic factor approval 2024 site:fda.gov",
        "{disease} gene therapy biologic clinical trials 2024 site:clinicaltrials.gov",
        "{disease} epidemiology prevalence burden 2024",
        "{disease} standard of care treatment guidelines ASH 2024",
        "{disease} factor replacement bispecific pricing outcomes 2024",
        "patient advocacy {disease} hemophilia sickle cell funding 2024",
    ],
    "biologic_rare_disease": [
        "FDA orphan {disease} enzyme replacement biologic approval site:fda.gov",
        "{disease} natural history study clinical trials site:clinicaltrials.gov",
        "{disease} enzyme replacement therapy outcomes real world 2024",
        "{disease} Orphanet NORD prevalence epidemiology 2024",
        "FDA OOPD grant {disease} rare biologic funding site:fda.gov",
        "{disease} patient advocacy foundation research funding 2024",
    ],
    "biologic_cardiology": [
        "FDA {disease} cardiovascular biologic approval PCSK9 2024 site:fda.gov",
        "{disease} biologic siRNA RNA interference clinical trials 2024",
        "{disease} cardiovascular outcomes trial CVOT 2024",
        "{disease} LDL reduction cardiovascular risk real world 2024",
        "NHLBI cardiovascular biologic research 2024 site:nhlbi.nih.gov",
        "{disease} payer coverage reimbursement access 2024",
    ],

    # ── Gene & Cell Therapy ───────────────────────────────────────────────────
    "gene_therapy_rare": [
        "FDA AAV gene therapy {disease} approval guidance site:fda.gov",
        "{disease} gene therapy clinical trials AAV lentiviral 2024 site:clinicaltrials.gov",
        "{disease} natural history data epidemiology 2024 site:nih.gov",
        "{disease} gene therapy outcomes long term follow up safety 2024",
        "FDA OOPD NCATS {disease} gene therapy grant funding 2024",
        "{disease} AAV manufacturing challenges immunogenicity 2024",
    ],
    "gene_therapy_oncology": [
        "FDA CAR-T TIL {disease} cell therapy approval 2024 site:fda.gov",
        "{disease} CAR-T TIL clinical trials 2024 site:clinicaltrials.gov",
        "{disease} CAR-T outcomes CRS ICANS real world 2024",
        "{disease} solid tumor cell therapy challenges TME 2024",
        "NCI {disease} cell therapy funding SBIR 2024 site:cancer.gov",
        "{disease} allogeneic off-the-shelf cell therapy pipeline 2024",
    ],
    "gene_therapy_cns": [
        "FDA {disease} CNS gene therapy ASO approval 2024 site:fda.gov",
        "{disease} CNS gene therapy ASO siRNA clinical trials 2024",
        "{disease} AAV9 intrathecal delivery CNS gene therapy 2024",
        "{disease} natural history biomarkers gene therapy endpoints 2024",
        "NINDS {disease} gene therapy funding 2024 site:ninds.nih.gov",
        "{disease} blood brain barrier gene therapy delivery challenges 2024",
    ],
    "gene_therapy_rna": [
        "FDA {disease} siRNA ASO mRNA approval 2024 site:fda.gov",
        "{disease} RNA therapeutics clinical trials LNP GalNAc 2024",
        "{disease} siRNA ASO mechanism efficacy outcomes 2024",
        "{disease} LNP delivery RNA therapeutic challenges 2024",
        "FDA oligonucleotide guidance {disease} regulatory 2024 site:fda.gov",
        "{disease} RNA therapeutic manufacturing cold chain 2024",
    ],
    "gene_therapy_hematology": [
        "FDA {disease} gene therapy CRISPR approval 2024 site:fda.gov",
        "{disease} gene therapy CRISPR lentiviral clinical trials 2024",
        "{disease} gene therapy outcomes long term durability 2024",
        "{disease} Casgevy Lyfgenia real world outcomes pricing 2024",
        "{disease} gene therapy payer coverage insurance access 2024",
        "{disease} busulfan conditioning gene therapy outcomes 2024",
    ],

    # ── Medical Device ────────────────────────────────────────────────────────
    "device_cardiovascular": [
        "FDA {disease} cardiovascular device PMA 510k approval 2024 site:fda.gov",
        "{disease} cardiovascular device clinical trials IDE 2024 site:clinicaltrials.gov",
        "ACC AHA {disease} device guidelines 2024",
        "{disease} device reimbursement CMS DRG coverage 2024 site:cms.gov",
        "{disease} device market size competitors 2024",
        "CMS coverage with evidence development {disease} device 2024",
    ],
    "device_metabolic": [
        "FDA CGM insulin pump AID {disease} clearance 2024 site:fda.gov",
        "{disease} CGM AID clinical trials outcomes 2024",
        "CMS Medicare {disease} device coverage reimbursement 2024 site:cms.gov",
        "{disease} CGM real world outcomes adoption rural access 2024",
        "ADA {disease} technology standards guidelines 2024",
        "NIDDK {disease} device funding 2024 site:niddk.nih.gov",
    ],
    "device_neurology": [
        "FDA {disease} neurostimulation DBS TMS device approval 2024 site:fda.gov",
        "{disease} DBS TMS VNS clinical trials 2024 site:clinicaltrials.gov",
        "{disease} neuromodulation outcomes real world evidence 2024",
        "CMS {disease} DBS TMS reimbursement coverage 2024 site:cms.gov",
        "{disease} brain computer interface BCI pipeline 2024",
        "NINDS {disease} neuromodulation funding 2024",
    ],

    # ── Diagnostic ────────────────────────────────────────────────────────────
    "diagnostic_molecular": [
        "FDA {disease} molecular diagnostic PCR NGS clearance 2024 site:fda.gov",
        "{disease} diagnostic test clinical utility outcomes 2024",
        "CMS CPT code {disease} molecular diagnostic reimbursement 2024",
        "{disease} liquid biopsy ctDNA diagnostic accuracy 2024",
        "{disease} point of care diagnostic CLIA waiver 2024",
        "{disease} diagnostic market size competitors 2024",
    ],
    "diagnostic_companion": [
        "FDA {disease} companion diagnostic CDx PMA approval 2024 site:fda.gov",
        "{disease} biomarker companion diagnostic clinical validation 2024",
        "{disease} CDx drug co-development regulatory strategy 2024",
        "{disease} IHC FISH NGS biomarker testing standard 2024",
        "{disease} companion diagnostic reimbursement coverage 2024",
        "{disease} tumor biomarker prevalence testing rate 2024",
    ],

    # ── Digital Health ────────────────────────────────────────────────────────
    "digital_cds": [
        "FDA {disease} AI ML clinical decision support software clearance 2024 site:fda.gov",
        "{disease} AI diagnostic clinical decision support outcomes 2024",
        "FDA AI ML SaMD guidance predetermined change control 2024 site:fda.gov",
        "{disease} clinical decision support reimbursement CMS CPT 2024",
        "{disease} AI algorithm validation clinical trial evidence 2024",
        "{disease} AI diagnostic market size competitors 2024",
    ],
    "digital_therapeutic": [
        "FDA {disease} prescription digital therapeutic PDT De Novo 2024 site:fda.gov",
        "{disease} digital therapeutic CBT app clinical trial outcomes 2024",
        "{disease} digital therapeutic reimbursement payer coverage 2024",
        "{disease} mental health app digital health market 2024",
        "FDA De Novo digital therapeutic {disease} clearance 2024",
        "{disease} digital therapeutic efficacy evidence real world 2024",
    ],
    "digital_rpm": [
        "CMS RPM remote patient monitoring {disease} reimbursement CPT 2024 site:cms.gov",
        "{disease} remote monitoring wearable clinical outcomes 2024",
        "FDA {disease} remote monitoring device clearance 2024 site:fda.gov",
        "{disease} RPM telehealth adoption outcomes evidence 2024",
        "{disease} remote monitoring market size competitors 2024",
        "telehealth {disease} policy reimbursement 2025 extension site:cms.gov",
    ],

    # ── Vaccine / Immunotherapy ───────────────────────────────────────────────
    "vaccine_prophylactic": [
        "FDA {disease} vaccine approval BLA 2024 site:fda.gov",
        "{disease} vaccine clinical trials Phase 3 efficacy 2024",
        "BARDA CEPI {disease} vaccine funding 2024",
        "{disease} vaccine epidemiology disease burden 2024 site:cdc.gov",
        "CDC ACIP {disease} vaccine recommendations 2024 site:cdc.gov",
        "{disease} vaccine manufacturing scale challenge 2024",
    ],
    "vaccine_cancer_immuno": [
        "FDA {disease} cancer vaccine immunotherapy approval 2024 site:fda.gov",
        "{disease} neoantigen mRNA cancer vaccine clinical trials 2024",
        "{disease} tumor antigen vaccine immunotherapy outcomes 2024",
        "NCI {disease} cancer vaccine funding SBIR 2024 site:cancer.gov",
        "{disease} therapeutic vaccine checkpoint inhibitor combination 2024",
        "{disease} cancer vaccine manufacturing personalized challenges 2024",
    ],

    # ── Other / Platform ─────────────────────────────────────────────────────
    "other_microbiome": [
        "FDA {disease} microbiome live biotherapeutic LBP approval 2024 site:fda.gov",
        "{disease} FMT microbiome clinical trials outcomes 2024",
        "{disease} gut microbiome dysbiosis mechanism 2024 site:pubmed.ncbi.nlm.nih.gov",
        "{disease} microbiome therapeutic reimbursement coverage 2024",
        "Rebyota Vowst {disease} microbiome real world outcomes 2024",
        "{disease} microbiome manufacturing lot variability challenges 2024",
    ],
    "other_crispr": [
        "FDA {disease} CRISPR gene editing approval guidance 2024 site:fda.gov",
        "{disease} CRISPR base editing gene editing clinical trials 2024",
        "Casgevy {disease} CRISPR real world outcomes 2024",
        "{disease} in vivo CRISPR gene editing safety off-target 2024",
        "{disease} CRISPR gene editing manufacturing scale 2024",
        "FDA long term follow up gene editing {disease} 2024 site:fda.gov",
    ],
    "other_delivery": [
        "FDA {disease} LNP nanoparticle drug delivery approval 2024 site:fda.gov",
        "{disease} LNP lipid nanoparticle delivery clinical outcomes 2024",
        "{disease} targeted delivery organ tropism challenges 2024",
        "{disease} drug delivery bioavailability improvement 2024",
        "{disease} delivery platform manufacturing scale challenges 2024",
        "FDA drug delivery platform combination product guidance {disease} 2024",
    ],
}

# Fallback searches when sub_expert_id not in SEARCH_TEMPLATES
DEFAULT_SEARCHES = [
    "FDA {disease} drug device approval 2024 site:fda.gov",
    "{disease} clinical trials Phase 2 3 2024 site:clinicaltrials.gov",
    "{disease} epidemiology prevalence incidence 2024 site:nih.gov OR site:cdc.gov",
    "{disease} standard of care treatment guidelines 2024",
    "{disease} unmet need pipeline funding 2024",
]


async def _run_single_search(
    query:       str,
    session_id:  str,
) -> str:
    """Run a single web search via Claude and return formatted results."""
    try:
        async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
            r = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key":         settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      SEARCH_MODEL,
                    "max_tokens": 800,
                    "tools":      [{"type": "web_search_20250305", "name": "web_search"}],
                    "messages":   [{
                        "role":    "user",
                        "content": (
                            f"Search for: {query}\n\n"
                            "Extract the most important facts, statistics, and findings. "
                            "For each fact, include: the fact, its source name, and URL. "
                            "Format: FACT: [text] | SOURCE: [name] | URL: [url] | YEAR: [year]\n"
                            "Focus on authoritative sources (FDA, CDC, NIH, peer-reviewed journals). "
                            "Be concise — extract 5-8 key facts maximum."
                        )
                    }],
                }
            )
            r.raise_for_status()
            text = ""
            for block in r.json().get("content", []):
                if block.get("type") == "text":
                    text += block.get("text", "")
            return f"\n--- Search: {query} ---\n{text}\n"
    except Exception as e:
        logger.warning(f"Search failed for '{query}': {e}")
        return f"\n--- Search: {query} ---\n[Search unavailable: {str(e)[:100]}]\n"


async def retrieve_knowledge(
    sub_expert_id: str,
    disease_name:  str,
    product_desc:  str = "",
) -> str:
    """
    Retrieve deep knowledge for a specific sub-expert + disease combination.
    Runs 5-6 searches in parallel, returns combined context.

    Args:
        sub_expert_id: e.g. "drug_amr", "gene_therapy_rare"
        disease_name:  specific disease from Disease Classifier
        product_desc:  PI's product description (for context)

    Returns:
        Combined knowledge string (~3,000-6,000 words)
    """
    templates = SEARCH_TEMPLATES.get(sub_expert_id, DEFAULT_SEARCHES)

    # Interpolate disease name into search queries
    disease_short = disease_name.split("(")[0].strip()  # Remove parenthetical abbreviations
    queries = [
        t.replace("{disease}", disease_short)
         .replace("{product}", product_desc[:50])
        for t in templates
    ]

    logger.info(f"Retrieving knowledge: sub_expert={sub_expert_id} disease='{disease_short}' queries={len(queries)}")

    # Run all searches in parallel
    queries = queries[:3]  # Cap at 3 searches to avoid Railway timeout
    tasks = [_run_single_search(q, f"{sub_expert_id}_{i}") for i, q in enumerate(queries)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Combine results
    combined = f"\n=== RETRIEVED KNOWLEDGE: {disease_name.upper()} ({sub_expert_id}) ===\n"
    combined += f"Sources searched: FDA.gov, ClinicalTrials.gov, CDC.gov, NIH.gov, authoritative literature\n\n"

    for result in results:
        if isinstance(result, Exception):
            logger.warning(f"Search task failed: {result}")
        else:
            combined += str(result)

    logger.info(f"Knowledge retrieval complete: {len(combined)} chars for {disease_short}")
    return combined


async def build_full_expert_context(
    sub_expert_id:         str,
    sub_expert_prompt:     str,
    sub_expert_critic:     str,
    disease_name:          str,
    product_desc:          str,
    domain_static_knowledge: str = "",
) -> tuple[str, str]:
    """
    Build the complete Researcher context and Critic context for a report.

    Returns:
        (researcher_context, critic_context)
    """
    # Retrieve live knowledge in parallel with any other prep
    live_knowledge = await retrieve_knowledge(sub_expert_id, disease_name, product_desc)

    researcher_context = f"""{sub_expert_prompt}

{domain_static_knowledge}

{live_knowledge}

CRITICAL INSTRUCTION: Every statistic and claim in your report MUST be tagged with 
[SOURCE: source_name | url] immediately after the fact.
Use the URLs from the knowledge retrieved above. Only cite real, authoritative sources."""

    critic_context = f"""{sub_expert_critic}

RETRIEVED KNOWLEDGE CONTEXT:
{live_knowledge[:2000]}"""

    return researcher_context, critic_context
