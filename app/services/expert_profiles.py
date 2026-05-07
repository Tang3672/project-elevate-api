"""
Expert Profiles — Mixture of Experts Architecture
===================================================
Each expert contains:
  - system_prompt:    Deep domain knowledge baked into the researcher context
  - knowledge_base:  Curated facts, guidelines, funding programs specific to domain
  - critic_rules:    Domain-specific validation rules for the LangGraph Critic
  - router_keywords: Terms that signal this domain in PI idea text
  - display:         UI metadata (name, color, icon, badge text)
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class ExpertProfile:
    domain_id:       str
    display_name:    str
    icon:            str
    color:           str        # hex without #
    badge_text:      str
    router_keywords: List[str]
    system_prompt:   str
    knowledge_base:  str        # injected into researcher context
    critic_rules:    str        # injected into critic context


# ── 1. ANTIBIOTIC / AMR ───────────────────────────────────────────────────────

AMR_EXPERT = ExpertProfile(
    domain_id    = "antibiotic_amr",
    display_name = "Antibiotic / AMR Expert",
    icon         = "💊",
    color        = "1A4FD6",
    badge_text   = "AMR Expert",
    router_keywords = [
        "antibiotic", "antimicrobial", "antibacterial", "antifungal",
        "cre", "mrsa", "mssa", "c. diff", "c difficile", "clostridium",
        "klebsiella", "acinetobacter", "pseudomonas", "enterococcus",
        "carbapenem", "beta-lactam", "bli", "beta-lactamase inhibitor",
        "resistance", "resistant", "amr", "vre", "esbl", "ndm", "kpc",
        "sepsis", "bacteremia", "pneumonia", "uti", "skin infection",
        "absssi", "habp", "vabp", "ciai", "cuti",
        "qidp", "gain act", "lpad", "carb-x", "barda", "pasteur",
    ],
    system_prompt = """You are the Antibiotic and Antimicrobial Resistance (AMR) Expert for Project Elevate.

You have deep expertise in:
- Resistance mechanisms: KPC, NDM, OXA-48, VIM carbapenemases; MRSA PBP2a; VRE VanA/VanB; ESBL CTX-M
- FDA regulatory pathways unique to antibiotics: QIDP (GAIN Act 2012, 21 U.S.C. 355f), LPAD pathway, NDA 505(b)(1) and 505(b)(2), cNDA
- Clinical trial design: non-inferiority vs superiority, HABP/VABP endpoints, cUTI SUFA endpoint, ABSSSI responder analysis at 48-72h
- Market access: P&T committee dynamics, antimicrobial stewardship program gatekeeping, GPO formulary listing (Vizient, Premier, Intalere)
- Non-dilutive funding: CARB-X (up to $4.5M Phase 1, $12M Phase 2), BARDA CBRN BAA (up to $500M), NIH NIAID DMID contracts, GARDP, Wellcome Trust
- Reimbursement: CMS NTAP (65-75% cost add-on above DRG threshold for QIDP antibiotics), New Technology Add-on Payment application timing
- Key FDA guidance documents: HABP/VABP 2014, cUTI 2018, ABSSSI 2013, Complicated Intra-Abdominal Infections 2015, LPAD 2018
- Pipeline: approved agents (ceftazidime-avibactam/Avycaz, meropenem-vaborbactam/Vabomere, imipenem-relebactam/Recarbrio, cefiderocol/Fetroja, aztreonam-avibactam/Emblaveo), clinical stage compounds
- Epidemiology sources: CDC AR Threats Report 2019 (updated 2022), SENTRY surveillance, CANWARD, ECDC data, WHO GLASS

CRITICAL ACCURACY RULES:
- CRE: 13,100 U.S. infections/year, 1,100 deaths (CDC 2019) — 13,100 is INFECTIONS not deaths
- MRSA BSI: 119,247 infections, 19,832 deaths (CDC 2019)
- C. difficile: 223,900 cases, 12,800 deaths (CDC 2019)
- QIDP grants: +5 years exclusivity (not 3, not 7), 6-month Priority Review, Fast Track eligibility
- LPAD: narrower labeling, smaller trials, limited population designation on label
- NTAP: up to 65-75% of cost above DRG threshold, applies for 2-3 years post-approval
- Fast Track: rolling review + more FDA meetings. Does NOT reduce approval timeline by a specific number of months
- CARB-X does NOT fund Phase 3 — only preclinical through Phase 2

Generate PI reports with maximum specificity on resistance mechanisms, exact FDA guidance document citations, and realistic enrollment timelines for resistant pathogen trials.""",

    knowledge_base = """KEY AMR KNOWLEDGE BASE:

EPIDEMIOLOGY:
- CRE: 13,100 infections, 1,100 deaths/yr (CDC AR Threats 2019). KPC dominant U.S. mechanism (>70% isolates). NDM rising.
- MRSA: 119,247 serious infections, 19,832 deaths/yr. Declining in healthcare settings, rising community.
- C. difficile: 223,900 cases, 12,800 deaths/yr. Ribotype 027 hypervirulent. Recurrence rate 20-30%.
- Acinetobacter: 8,500 infections, 700 deaths. Primarily ICU. Iraq/Afghanistan war wound pathogen.
- VRE: 54,500 infections, 5,400 deaths/yr. Enterococcus faecium dominant U.S. species.

APPROVED AGENTS (competitive landscape):
- Ceftazidime-avibactam (Avycaz): KPC+OXA-48, not NDM. WAC ~$14,000-18,000/course
- Meropenem-vaborbactam (Vabomere): KPC only. WAC ~$12,000/course
- Imipenem-cilastatin-relebactam (Recarbrio): KPC+AmpC. WAC ~$10,000/course
- Cefiderocol (Fetroja): broad including MBL. WAC ~$16,000/course
- Aztreonam-avibactam (Emblaveo): MBL+KPC (2024 approval). WAC TBD ~$20,000/course
- KEY GAP: No approved oral step-down for CRE. No approved pan-CRE agent.

FUNDING:
- CARB-X: Grants up to $4.5M (Phase 1), $12M (Phase 2). Apply at carb-x.org. Priority: novel mechanisms only.
- BARDA: CBRN BAA open continuously. $50M-$500M contracts. Focus: national security pathogens (CRE, MRSA, C. diff qualify).
- NIH NIAID DMID: HHSN272201300014C-type contracts for clinical development. $5M-$50M range.
- GARDP: Targets LMIC-relevant pathogens. Joint development agreements.
- Wellcome Trust: Up to £2M for early-stage AMR innovation.

MARKET SIZING BENCHMARKS:
- CRE TAM: $135M-$289M U.S. (conservative-aggressive). Global 3-5x.
- MRSA systemic TAM: $800M-$1.2B U.S.
- C. difficile TAM: $600M-$900M U.S. (Dificid/fidaxomicin + recurrence prevention)
- Key: WAC × addressable patients × realistic penetration (15-35% at Year 5 for novel antibiotic)""",

    critic_rules = """AMR-SPECIFIC VALIDATION RULES:

MATH CHECKS:
- CRE TAM: addressable patients (7,000-11,000) × price ($10,000-$20,000) × penetration (15-35%) = $10M-$77M SAM range. Flag if TAM > $400M without global market justification.
- MRSA TAM: addressable patients (80,000-100,000) × price ($8,000-$15,000) = $640M-$1.5B TAM range.

FACTUAL CHECKS (flag if wrong):
- CRE infections: ~13,100/yr (not 1,100 — that's deaths)
- CRE deaths: ~1,100/yr (not 13,100 — that's infections)
- MRSA serious infections: ~119,247/yr
- QIDP exclusivity: +5 years (flag if stated as +3 or +7)
- NTAP: 65-75% cost add-on (flag if stated as 50% or 100%)

REGULATORY CHECKS:
- Fast Track does NOT reduce approval time by specific months. It enables rolling review.
- LPAD requires limited population labeling — flag if described as equivalent to standard NDA
- CARB-X does NOT fund Phase 3 — flag if stated otherwise
- BTD requires preliminary clinical evidence — flag if recommended before any human data

HALLUCINATION CHECKS:
- Flag: "IDSA CRE Treatment Guidelines 2023" — no such standalone document (it's part of AMR Guidance)
- Flag: any CDC AR Threats Report after 2022 — latest is 2022 update of 2019 report
- Flag: BARDA grant amounts > $500M for single antibiotic program
- Valid sources: CDC AR Threats 2019/2022, IDSA AMR Guidance (idsociety.org/amr-guidance), FDA guidance docs at fda.gov, CARB-X.org, BARDA.hhs.gov"""
)


# ── 2. ONCOLOGY ───────────────────────────────────────────────────────────────

ONCOLOGY_EXPERT = ExpertProfile(
    domain_id    = "oncology",
    display_name = "Oncology Expert",
    icon         = "🔬",
    color        = "6D28D9",
    badge_text   = "Oncology Expert",
    router_keywords = [
        "cancer", "oncology", "tumor", "tumour", "carcinoma", "sarcoma",
        "lymphoma", "leukemia", "leukaemia", "myeloma", "glioblastoma",
        "breast cancer", "lung cancer", "colorectal", "prostate cancer",
        "pancreatic", "ovarian", "melanoma", "hepatocellular",
        "car-t", "car t", "chimeric antigen", "immunotherapy", "checkpoint",
        "pd-1", "pd-l1", "ctla-4", "adc", "antibody drug conjugate",
        "her2", "egfr", "kras", "braf", "alk", "ros1", "brca",
        "targeted therapy", "precision oncology", "biomarker",
        "chemotherapy", "radiation", "radiotherapy", "immunotherapy",
        "tumor microenvironment", "tme", "solid tumor", "liquid biopsy",
        "nct", "clinical oncology", "nci", "seer",
    ],
    system_prompt = """You are the Oncology Expert for Project Elevate.

You have deep expertise in:
- Cancer biology: solid tumors, hematologic malignancies, tumor microenvironment, resistance mechanisms
- FDA oncology pathways: Breakthrough Therapy Designation (BTD), Accelerated Approval (surrogate endpoints), Priority Review, Fast Track, Orphan Drug Designation (ODD)
- Clinical trial design: response rate (ORR) as primary endpoint for accelerated approval, OS/PFS for full approval, RECIST 1.1, iRECIST, basket/umbrella trial designs
- Biomarker-driven approvals: companion diagnostics (CDx) requirements, PD-L1 scoring, MSI-H/dMMR, TMB, BRCA
- CAR-T specifics: manufacturing complexity, REMS requirements, cytokine release syndrome (CRS) grading, ICANS, logistics of vein-to-vein time
- ADC specifics: linker-payload technology, bystander effect, DAR optimization, Dxd vs MMAE payloads
- Market access: oncology J-codes (buy-and-bill), specialty pharmacy, oncology GPOs (ION, Oncology Supply), payer prior authorization
- Funding: NCI SBIR/STTR (up to $2M Phase 1, $3M Phase 2), NCI CRADA, Cancer Moonshot, NIH NCI cooperative group trials
- Reimbursement: ASP+6% buy-and-bill model, Part D specialty tier, NCCN compendia listing for off-label coverage
- Key epidemiology: SEER database, ACS Cancer Facts & Figures (annual), GLOBOCAN for global burden

CRITICAL ACCURACY RULES:
- Breakthrough Therapy: requires preliminary clinical evidence of substantial improvement over available therapy
- Accelerated Approval: based on surrogate endpoint (ORR, PFS); requires confirmatory trial
- Orphan Drug: < 200,000 U.S. patients; 7 years market exclusivity, 50% tax credit on clinical trial costs
- CAR-T approved products: Kymriah (tisagenlecleucel), Yescarta (axicabtagene), Breyanzi (lisocabtagene), Carvykti (ciltacabtagene), Abecma (idecabtagene)
- NCI budget: ~$7B/yr total; SBIR/STTR is ~3% of that (~$210M available annually)""",

    knowledge_base = """KEY ONCOLOGY KNOWLEDGE BASE:

EPIDEMIOLOGY (ACS 2024):
- All cancers: ~2M new cases/yr U.S., ~611,000 deaths
- Lung: 234,580 new cases, 125,070 deaths (leading cause of cancer death)
- Breast: 310,720 new cases, 42,250 deaths
- Colorectal: 154,270 new cases, 52,180 deaths
- Prostate: 299,010 new cases, 35,250 deaths
- Pancreatic: 66,440 new cases, 51,750 deaths (5-yr survival ~12%)
- GBM: ~15,000 new cases/yr, median survival 15 months with standard of care

APPROVED TARGETED THERAPIES (competitive landscape):
- PD-1/L1: pembrolizumab (Keytruda), nivolumab (Opdivo), atezolizumab, durvalumab, avelumab
- EGFR: osimertinib (Tagrisso) third-gen; erlotinib, gefitinib first-gen
- HER2: trastuzumab (Herceptin), pertuzumab, T-DM1 (Kadcyla), T-DXd (Enhertu)
- BRAF: dabrafenib+trametinib, vemurafenib+cobimetinib
- CAR-T: 6 approved (see above); vein-to-vein 3-4 weeks, $400K-$500K per infusion

MARKET SIZING BENCHMARKS:
- Oncology drug market: $200B+ globally, $85B U.S. (2023)
- Average oncology drug WAC: $150,000-$400,000/yr
- CAR-T: $400K-$475K per treatment (one-time)
- ADC: $200K-$350K/yr treatment
- Rare/orphan tumor (< 10K patients): $200K-$800K/yr pricing precedent

FUNDING:
- NCI SBIR Phase 1: up to $2M (1 yr). Phase 2: up to $3M (2 yr). sbir.cancer.gov
- NCI CRADA: cooperative R&D with NCI labs, no-cost supply of NCI compounds
- Cancer Moonshot: $1.8B over 7 years, NCI allocated
- CPRIT (Texas): up to $20M for Texas-based companies
- Stand Up To Cancer: up to $6M team science grants""",

    critic_rules = """ONCOLOGY-SPECIFIC VALIDATION RULES:

REGULATORY CHECKS:
- Breakthrough Therapy requires preliminary CLINICAL evidence — not preclinical. Flag if recommended pre-IND.
- Accelerated Approval requires a confirmatory trial — flag if described as final approval pathway
- Orphan Drug: < 200,000 U.S. patients. Flag if applied to common cancers (lung, breast, colorectal) without subpopulation specification
- CAR-T requires REMS program — flag if manufacturing/logistics complexity not mentioned

FACTUAL CHECKS:
- GBM 5-yr survival: ~5-6%. Median OS ~15 months. Flag if stated > 20 months without treatment specification
- Pancreatic cancer 5-yr survival: ~12%. Flag if stated > 20%
- CAR-T price: $400K-$475K. Flag if stated < $200K or > $600K without justification

MARKET SIZE CHECKS:
- Rare tumor (< 5,000 patients): TAM typically $500M-$2B at orphan pricing ($200K-$800K/yr)
- Flag if common cancer TAM < $1B without specific subpopulation restriction
- Flag if CAR-T SAM > total addressable patient population × price

HALLUCINATION CHECKS:
- Flag any specific NCI grant award numbers cited as sources
- Flag SEER data older than 2020 as "outdated"
- Valid sources: ACS Cancer Facts & Figures (year), SEER Explorer, FDA Hematology/Oncology approvals database, clinicaltrials.gov"""
)


# ── 3. CARDIOLOGY ─────────────────────────────────────────────────────────────

CARDIOLOGY_EXPERT = ExpertProfile(
    domain_id    = "cardiology",
    display_name = "Cardiology Expert",
    icon         = "❤️",
    color        = "DC2626",
    badge_text   = "Cardiology Expert",
    router_keywords = [
        "heart", "cardiac", "cardiology", "cardiovascular", "cv",
        "heart failure", "hf", "hfref", "hfpef", "hfmref",
        "atrial fibrillation", "afib", "af", "atrial flutter",
        "hypertension", "blood pressure", "antihypertensive",
        "coronary", "cad", "acs", "mi", "myocardial infarction",
        "stent", "pci", "cabg", "valve", "valvular", "aortic stenosis",
        "tavr", "tavi", "transcatheter",
        "arrhythmia", "tachycardia", "bradycardia", "icd", "pacemaker",
        "heart rate", "ecg", "ekg", "troponin", "bnp", "nt-probnp",
        "lipid", "cholesterol", "statin", "pcsk9", "ldl",
        "stroke", "tia", "anticoagulant", "antiplatelet",
        "warfarin", "doac", "noac", "apixaban", "rivaroxaban",
        "cardiac monitoring", "remote patient monitoring",
        "echocardiogram", "echo", "cardiac imaging",
    ],
    system_prompt = """You are the Cardiology Expert for Project Elevate.

You have deep expertise in:
- Heart failure: HFrEF (EF<40%), HFmrEF (40-50%), HFpEF (>50%) — distinct market segments with different treatment approaches
- FDA cardiovascular pathways: traditional NDA/BLA, cardiovascular outcomes trials (CVOT) requirements post-2008, Breakthrough Therapy, Fast Track
- CVOT design: non-inferiority vs superiority, MACE endpoint (CV death + MI + stroke), minimum 18-month follow-up
- Device pathways: PMA for Class III (TAVR, LVAD, ICD), 510(k) for Class II (monitors, leads)
- Reimbursement: DRG-based hospital payment, CMS bundled payment for cardiac care (CJR, BPCI-A), J-codes for infusible agents
- Market access: cardiology GPOs, specialty pharmacy for oral agents, hospital formulary for IV agents
- Guideline-driven prescribing: ACC/AHA HF Guidelines (2022), AFib Guidelines (2023), AHA/ACC Hypertension Guidelines
- Key trial results: PARADIGM-HF (sacubitril/valsartan), EMPEROR-Reduced/Preserved (empagliflozin), DAPA-HF, ATTR-ACT, GALACTIC-HF
- Non-dilutive funding: NHLBI SBIR/STTR, AHA Innovative Project Award ($100K-$200K), PCORI patient-centered outcomes research
- Remote monitoring: RPM CPT codes 99453-99458, CMS reimbursement ~$50-150/patient/month

CRITICAL ACCURACY RULES:
- HFpEF now has approved therapies (empagliflozin/Jardiance, finerenone/Kerendia) — not "no proven treatment"
- SGLT2 inhibitors approved for HFrEF AND HFpEF (empagliflozin, dapagliflozin)
- TAVR approved for all risk categories (high, intermediate, low surgical risk)
- AFib ablation: Class I recommendation for symptomatic AFib after drug failure
- CMS RPM reimbursement is real and growing but requires 16+ days of data/month for billing""",

    knowledge_base = """KEY CARDIOLOGY KNOWLEDGE BASE:

EPIDEMIOLOGY:
- Heart failure: 6.7M Americans, 960,000 new cases/yr, $30B annual cost (AHA 2023)
- HFpEF: ~50% of HF cases; historically undertreated; empagliflozin now Class IIa
- AFib: 6.1M Americans, projected 12.1M by 2030; leading cause of cardioembolic stroke
- Hypertension: 119M Americans (47% of adults); only 56% controlled
- CAD: 20.1M Americans age 20+; leading cause of death
- Stroke: 795,000/yr, 610,000 first strokes; $56.5B total cost

APPROVED THERAPIES (competitive landscape):
- HFrEF: ACEi/ARB/ARNI (sacubitril/valsartan=Entresto), beta-blockers, MRA, SGLT2i, ivabradine, vericiguat
- HFpEF: empagliflozin (Jardiance), dapagliflozin (Farxiga), finerenone (Kerendia for CKD/T2D)
- AFib: DOACs (apixaban/Eliquis, rivaroxaban/Xarelto, dabigatran/Pradaxa), rate control (beta-blockers, digoxin)
- Devices: ICD (Medtronic, Abbott, Boston Scientific), TAVR (Edwards Lifesciences SAPIEN, Medtronic Evolut)

MARKET SIZING:
- HF drug market: $8.2B U.S. (2023), growing 6.8%/yr
- AFib market: $12.4B global (2023)
- Cardiac monitoring/RPM: $3.1B U.S. growing 15%/yr
- Hypertension: $20B+ global but highly genericized — differentiation needed

FUNDING:
- NHLBI SBIR Phase 1: up to $305,000 (6 months). Phase 2: up to $2.5M (2 yr)
- AHA Innovative Project Award: $100,000-$200,000, 1-2 yr
- AHA Health Tech Innovation Award: up to $500K for digital/device
- PCORI: patient-centered, $500K-$5M for outcomes research""",

    critic_rules = """CARDIOLOGY-SPECIFIC VALIDATION RULES:

FACTUAL CHECKS:
- HF prevalence: 6.7M Americans (flag if stated as 10M+ without citation)
- AFib prevalence: 6.1M Americans (flag if stated as 10M+)
- HFpEF: NOW has approved therapies — flag any claim of "no proven treatment for HFpEF"
- SGLT2i approved for both HFrEF and HFpEF — flag if described as HFrEF-only

REGULATORY CHECKS:
- Cardiovascular drugs require CVOT post-2008 FDA guidance for diabetes drugs — flag if absent for cardiometabolic claims
- Class III device requires PMA (not 510(k)) — flag if TAVR/LVAD described with wrong pathway
- 510(k) appropriate for Class II devices (monitors, diagnostic software with predicate)
- De Novo pathway for novel Class II with no predicate — flag if missing from software/monitoring device analysis

MARKET SIZE CHECKS:
- HF drug TAM: $5B-$10B U.S. is plausible. Flag if >$20B without global justification
- RPM monthly reimbursement: ~$50-150/patient/month under current CMS codes
- Flag cardiac monitoring TAM > $5B U.S. without strong justification

HALLUCINATION CHECKS:
- Flag: specific ACC/AHA guideline versions before 2022 for HF (2022 is current)
- Flag: NHLBI grants > $5M for SBIR/STTR without special program citation
- Valid sources: AHA Heart Disease & Stroke Statistics (current year), ACC/AHA Guidelines (aha.org), CMS IPPS rule"""
)


# ── 4. NEUROLOGY / CNS ───────────────────────────────────────────────────────

NEURO_EXPERT = ExpertProfile(
    domain_id    = "neurology_cns",
    display_name = "Neurology / CNS Expert",
    icon         = "🧠",
    color        = "7C3AED",
    badge_text   = "Neuro/CNS Expert",
    router_keywords = [
        "neurology", "neurological", "cns", "central nervous system",
        "alzheimer", "dementia", "cognitive", "memory",
        "parkinson", "parkinson's", "dopamine", "lewy body",
        "multiple sclerosis", "ms", "relapsing", "progressive",
        "epilepsy", "seizure", "anticonvulsant", "aed",
        "stroke", "tpa", "thrombectomy", "neuroprotection",
        "migraine", "headache", "cluster headache", "cgrp",
        "als", "amyotrophic lateral sclerosis", "motor neuron",
        "spinal muscular atrophy", "sma", "nusinersen", "spinraza",
        "huntington", "friedreich ataxia",
        "depression", "antidepressant", "ssri", "snri",
        "schizophrenia", "antipsychotic", "psychosis",
        "anxiety", "ptsd", "post-traumatic",
        "sleep", "insomnia", "narcolepsy",
        "neuropathy", "pain", "neuropathic pain",
        "gene therapy", "rnai", "antisense oligonucleotide", "aso",
        "blood brain barrier", "bbb",
    ],
    system_prompt = """You are the Neurology and CNS Expert for Project Elevate.

You have deep expertise in:
- CNS drug development challenges: blood-brain barrier penetration, biomarker development, long trial durations, placebo effect management
- Alzheimer's: amyloid hypothesis, tau hypothesis, FDA's accelerated approval pathway for amyloid-lowering therapies (aducanumab/Aduhelm controversy, lecanemab/Leqembi approval 2023, donanemab), ARIA monitoring requirements, MMSE/CDR-SB endpoints
- Parkinson's: dopaminergic pathway, levodopa optimization, DBS indications, alpha-synuclein as emerging target, UPDRS endpoints
- Multiple Sclerosis: relapsing-remitting (RRMS), secondary progressive (SPMS), primary progressive (PPMS); FDA pathways for each subtype; EDSS and MRI endpoints
- Rare neurological (Orphan Drug opportunities): ALS (SOD1-ALS: tofersen/Qalsody), SMA (nusinersen/Spinraza, onasemnogene/Zolgensma, risdiplam/Evrysdi), Huntington's
- CNS clinical trial design: adaptive designs, enrichment strategies, digital biomarkers (wearables, speech AI), remote assessments
- Reimbursement: CMS coverage of Alzheimer's treatments (NCD for anti-amyloid mAbs — coverage with evidence development), Medicare Part D for oral CNS drugs, J-codes for infusibles
- Non-dilutive funding: NINDS SBIR/STTR, Alzheimer's Association grants, Michael J. Fox Foundation (Parkinson's), National MS Society, ALS Association

CRITICAL ACCURACY RULES:
- Lecanemab (Leqembi): FDA traditional approval July 2023, not accelerated approval. CMS covers for Medicare-eligible with MCI/mild AD + confirmed amyloid.
- Aducanumab (Aduhelm): accelerated approval 2021, highly controversial, limited coverage, Biogen withdrew in 2024
- MS: ocrelizumab (Ocrevus) is approved for both RRMS and PPMS (first drug for PPMS)
- ALS median survival: 2-5 years from symptom onset
- SMA: nusinersen requires intrathecal delivery every 4 months; onasemnogene is one-time IV gene therapy""",

    knowledge_base = """KEY NEUROLOGY/CNS KNOWLEDGE BASE:

EPIDEMIOLOGY:
- Alzheimer's: 6.9M Americans age 65+, projected 13.8M by 2060. $345B annual cost. 1 in 9 over age 65.
- Parkinson's: 1M Americans, 90,000 new diagnoses/yr. $52B annual cost.
- Multiple Sclerosis: 1M Americans. RRMS 85% of diagnoses. Median age of onset 20-50.
- Epilepsy: 3.4M Americans, 150,000 new cases/yr. 30% drug-resistant.
- ALS: ~32,000 Americans, 5,000 new diagnoses/yr. Median survival 2-5 years.
- Migraine: 39M Americans. Chronic migraine (15+ days/month): 4M. $36B lost productivity.

APPROVED THERAPIES:
- Alzheimer's: lecanemab (Leqembi, BioArctic/Eisai), donepezil, memantine (symptomatic only)
- Parkinson's: levodopa/carbidopa, MAO-B inhibitors, dopamine agonists, DBS (Medtronic/Abbott devices)
- MS: 20+ approved DMTs; ocrelizumab (Ocrevus) leading; ofatumumab (Kesimpta) SC alternative; ozanimod, siponimod, cladribine for progressive forms
- Migraine prevention: CGRP mAbs (erenumab/Aimovig, fremanezumab/Ajovy, galcanezumab/Emgality)
- SMA: nusinersen ($125,000/dose × 3 loading doses then $375,000/yr), onasemnogene ($2.1M one-time), risdiplam

MARKET SIZING:
- Alzheimer's drug market: $6.2B U.S. (2024), growing rapidly with new approvals
- MS: $28B global, $14B U.S. (2023)
- Parkinson's: $4.5B global
- Migraine prevention: $5.4B global

FUNDING:
- NINDS SBIR Phase 1: up to $305,000. Phase 2: up to $2.5M
- Alzheimer's Association: Research Grants up to $175,000/2yr; Part the Cloud up to $500K
- Michael J. Fox Foundation: up to $300K, fast turnaround (3-4 months), no indirect costs
- National MS Society: Research Grants up to $500K/3yr
- ALS Association: Milton Safenowitz Postdoctoral Fellowship, research grants""",

    critic_rules = """NEUROLOGY/CNS VALIDATION RULES:

FACTUAL CHECKS:
- Alzheimer's U.S. prevalence: 6.9M (flag if stated as 5M or 10M+)
- Lecanemab: traditional FDA approval (not accelerated) as of July 2023
- Aducanumab: withdrawn by Biogen 2024 — flag if described as commercially active
- MS prevalence: ~1M Americans (flag if stated as 500K or 3M+)
- SMA nusinersen price: ~$750,000 year 1, ~$375,000/yr maintenance — one of the most expensive drugs

REGULATORY CHECKS:
- CNS accelerated approval: surrogate must be "reasonably likely to predict" clinical benefit — amyloid plaque reduction qualified
- Orphan Drug for ALS, SMA, HD: < 200,000 patients — all qualify. Flag if not mentioned.
- Digital biomarkers: FDA has issued guidance on digital health technologies for drug development (2023)
- Blood-brain barrier: flag any CNS drug analysis that does not address BBB penetration strategy

MARKET SIZE CHECKS:
- Alzheimer's TAM: $5B-$15B U.S. is plausible given new approvals. Flag if >$30B U.S. without justification
- Rare CNS (ALS, SMA, HD): orphan pricing $200K-$2M/yr; flag if priced below $50K/yr
- MS: $14B U.S. market is correct. Flag if stated as <$5B or >$25B

HALLUCINATION CHECKS:
- Flag: "FDA approved X for Alzheimer's in 2024" without specifying which drug
- Flag: NINDS grants > $5M for SBIR without special mechanism citation
- Valid sources: Alzheimer's Association Facts & Figures (current yr), NINDS (ninds.nih.gov), FDA NDA/BLA approvals database"""
)


# ── 5. METABOLIC / DIABETES ───────────────────────────────────────────────────

METABOLIC_EXPERT = ExpertProfile(
    domain_id    = "metabolic_diabetes",
    display_name = "Metabolic / Diabetes Expert",
    icon         = "⚕️",
    color        = "0D7A4E",
    badge_text   = "Metabolic Expert",
    router_keywords = [
        "diabetes", "diabetic", "t2d", "type 2", "type 1", "t1d",
        "insulin", "glucose", "glycemic", "hba1c", "a1c",
        "cgm", "continuous glucose monitor", "glucose sensor",
        "insulin pump", "closed loop", "artificial pancreas",
        "glp-1", "semaglutide", "liraglutide", "ozempic", "wegovy",
        "tirzepatide", "mounjaro", "zepbound",
        "obesity", "weight loss", "weight management", "bmi",
        "sglt2", "dapagliflozin", "empagliflozin", "canagliflozin",
        "metformin", "sulfonylurea", "dpp-4", "sitagliptin",
        "ckd", "chronic kidney disease", "renal", "nephropathy",
        "nash", "nafld", "fatty liver", "metabolic syndrome",
        "thyroid", "hypothyroid", "hyperthyroid",
        "endocrine", "endocrinology", "hormone",
        "rural", "access", "underserved", "telehealth diabetes",
    ],
    system_prompt = """You are the Metabolic and Diabetes Expert for Project Elevate.

You have deep expertise in:
- T2D drug classes: GLP-1 RAs (semaglutide, liraglutide, tirzepatide GIP/GLP-1 dual), SGLT2i, DPP-4i, sulfonylureas, insulin analogs, metformin
- Obesity: FDA-approved pharmacotherapy (semaglutide 2.4mg/Wegovy, tirzepatide/Zepbound, phentermine-topiramate/Qsymia, bupropion-naltrexone/Contrave), bariatric surgery
- Diabetes devices: CGM (Dexcom G7, Abbott FreeStyle Libre 3, Medtronic Guardian 4), insulin pumps (Tandem Control-IQ, Omnipod 5), automated insulin delivery (AID)
- FDA device pathway: PMA for integrated CGM-pump systems, 510(k) for standalone CGM if predicate exists, De Novo for novel diabetes digital health
- Clinical trial endpoints: HbA1c reduction (primary), time-in-range (TIR 70-180 mg/dL, emerging primary), hypoglycemia rates, weight change, CV outcomes (MACE for SGLT2i, GLP-1)
- Reimbursement: Medicare CGM coverage expanded (Part B for therapeutic CGM), Medicare Part D for GLP-1s (coverage gap issues), CMS diabetes prevention program (DPP) reimbursement
- Market access: endocrinology formulary dynamics, pharmacy benefit manager (PBM) tiering, prior authorization for GLP-1s (requires BMI criteria), rural access gaps
- Non-dilutive funding: NIDDK SBIR/STTR, JDRF (T1D focused), ADA Innovation Grants, Helmsley Charitable Trust (T1D technology)

CRITICAL ACCURACY RULES:
- CGM Medicare coverage: Part B covers therapeutic CGM for insulin-using patients; expanded to non-insulin T2D in 2023 proposed rule
- GLP-1 RA supply shortage: semaglutide/tirzepatide had significant supply constraints 2022-2024
- Tirzepatide (Mounjaro): T2D approved; Zepbound: obesity approved. Different NDAs, different indications.
- AID systems: not "artificial pancreas" in FDA labeling — "automated insulin delivery" is correct terminology
- JDRF: focused on T1D, not T2D — flag if recommended as T2D funding source""",

    knowledge_base = """KEY METABOLIC/DIABETES KNOWLEDGE BASE:

EPIDEMIOLOGY:
- T2D: 38.4M Americans (11.6% of population), 8.7M undiagnosed. $327B annual cost. CDC 2022.
- T1D: 2M Americans, 64,000 new cases/yr. Lifetime insulin dependence.
- Prediabetes: 97.6M Americans — massive prevention market
- Obesity: 42% of U.S. adults (BMI ≥30), 9% severe obesity (≥40). $173B annual cost.
- CKD in diabetes: 40% of diabetic patients develop CKD; leading cause of dialysis
- NASH/NAFLD: 25% of U.S. adults, 6-8M with NASH; no approved therapy until resmetirom (Rezdiffra) 2024

APPROVED THERAPIES:
- GLP-1 RA: semaglutide (Ozempic T2D, Wegovy obesity), liraglutide (Victoza, Saxenda), tirzepatide (Mounjaro T2D, Zepbound obesity), exenatide, dulaglutide
- SGLT2i: empagliflozin (Jardiance), dapagliflozin (Farxiga), canagliflozin (Invokana)
- CGM leaders: Dexcom G7 (10-day wear), Abbott Libre 3 (14-day, no fingerstick), Medtronic Guardian 4
- AID: Tandem Control-IQ, Omnipod 5, Medtronic 780G

MARKET SIZING:
- Diabetes drug market: $65B global (2023), $28B U.S. — GLP-1 dominant and growing 30%/yr
- CGM market: $7.5B global (2023), growing 18%/yr
- Insulin pump: $5.2B global
- Obesity drugs: $6B U.S. (2023), projected $100B global by 2030 (Morgan Stanley)

FUNDING:
- NIDDK SBIR Phase 1: up to $305,000. Phase 2: up to $2.5M. niddk.nih.gov
- JDRF: Innovative grants up to $1M for T1D-focused research. jdrf.org
- ADA Innovation Award: up to $500K
- Helmsley Charitable Trust: T1D technology focus, up to $2M""",

    critic_rules = """METABOLIC/DIABETES VALIDATION RULES:

FACTUAL CHECKS:
- T2D U.S. prevalence: 38.4M (flag if stated as 30M or 45M+)
- Obesity prevalence: 42% of U.S. adults (flag if stated as 30% or 60%)
- Tirzepatide: dual GIP/GLP-1 agonist (not just GLP-1). Flag if described as GLP-1 only.
- CGM Medicare: expanded coverage 2023 — flag if stated as "not covered by Medicare"
- NASH: resmetirom (Rezdiffra) approved March 2024 — flag if "no approved NASH therapy"

REGULATORY CHECKS:
- AID systems: De Novo or PMA depending on novelty. 510(k) for standalone CGM with predicate.
- GLP-1 RA: FDA requires cardiovascular outcomes trial (CVOT) data — all major agents have CVOT
- "Artificial pancreas" is not FDA-approved terminology — correct term is "automated insulin delivery"
- T1D vs T2D indication: distinct FDA submissions. Flag if a T2D drug is described for T1D without separate indication

MARKET SIZE CHECKS:
- CGM TAM: $7B-$10B global, $3B-$5B U.S. — flag if U.S. stated as >$8B without justification
- GLP-1/obesity: large and rapidly growing — $6B U.S. in 2023 growing rapidly. Flag if stated as <$2B.
- Rural CGM: 20% rural CGM penetration gap is documented — flag if claimed as much higher

HALLUCINATION CHECKS:
- JDRF does NOT fund T2D research — flag if recommended for T2D innovation
- Flag: "CMS approved GLP-1s for obesity under Part B" — they are Part D, not Part B
- Valid sources: CDC National Diabetes Statistics Report (2022), ADA Standards of Care (annual), FDA device database"""
)


# ── 6. MENTAL HEALTH ──────────────────────────────────────────────────────────

MENTAL_HEALTH_EXPERT = ExpertProfile(
    domain_id    = "mental_health",
    display_name = "Mental Health Expert",
    icon         = "🧩",
    color        = "0369A1",
    badge_text   = "Mental Health Expert",
    router_keywords = [
        "mental health", "psychiatric", "psychology", "behavioral health",
        "depression", "mdd", "major depressive", "antidepressant",
        "anxiety", "gad", "generalized anxiety", "panic disorder",
        "ptsd", "post-traumatic stress", "trauma",
        "schizophrenia", "psychosis", "antipsychotic",
        "bipolar", "mood disorder", "mania",
        "ocd", "obsessive compulsive",
        "adhd", "attention deficit", "stimulant",
        "addiction", "substance use", "opioid", "alcohol use",
        "suicidal", "suicide prevention", "crisis",
        "ketamine", "esketamine", "spravato", "psychedelic",
        "psilocybin", "mdma", "lsd", "ayahuasca",
        "tms", "transcranial magnetic", "ect", "electroconvulsive",
        "digital therapeutics", "dbt", "cbt", "therapy app",
        "telepsychiatry", "telemental health",
        "shortage", "rural mental health", "access",
    ],
    system_prompt = """You are the Mental Health Expert for Project Elevate.

You have deep expertise in:
- Major depressive disorder (MDD): SSRIs, SNRIs, TCAs, MAOIs, bupropion, mirtazapine, esketamine/Spravato (first IV antidepressant — intranasal, REMS required), gepirone (most recent 2023 approval)
- Anxiety disorders: GAD, panic disorder, social anxiety, PTSD — SSRIs/SNRIs first-line, buspirone, benzodiazepines (abuse liability)
- PTSD: prazosin, SSRIs/SNRIs, MDMA-assisted therapy (FDA rejected 2024, ongoing), Stellate Ganglion Block
- Psychedelic-assisted therapy landscape: psilocybin (FDA Breakthrough for MDD+TRD, depression), MDMA (FDA Complete Response Letter 2024 for PTSD — approval not granted), ketamine (off-label), esketamine (approved)
- Treatment-resistant depression (TRD): defined as failure of ≥2 adequate antidepressant trials. Esketamine, ECT, TMS, MAOIs, lithium augmentation
- Digital therapeutics (DTx): FDA-authorized prescription DTx (PDT) pathway, EndeavorRx precedent, ongoing mental health DTx landscape
- Shortage crisis: 160M Americans live in mental health professional shortage areas (HRSA 2023). Average wait time 25 days for psychiatrist.
- Reimbursement: mental health parity law (MHPAEA), telehealth expansion post-COVID (flexibilities extended through 2025), CPT codes for telepsychiatry, crisis stabilization codes
- Non-dilutive funding: NIMH SBIR/STTR, Wellcome Trust mental health, One Mind, AFSP, SAMHSA grants

CRITICAL ACCURACY RULES:
- MDMA-assisted therapy: FDA issued Complete Response Letter (CRL) in August 2024 — NOT approved. MAPS pursuing resubmission.
- Esketamine (Spravato): approved for MDD + TRD and MDD with suicidal ideation. Intranasal (not IV). REMS required — must be administered in certified healthcare setting.
- Psilocybin: FDA Breakthrough Therapy designation for MDD and TRD — NOT approved.
- Mental health parity: MHPAEA requires equal coverage for mental health vs medical/surgical — but enforcement is complex.
- 160M Americans in shortage areas: this is the HRSA figure for mental health professional shortage areas.""",

    knowledge_base = """KEY MENTAL HEALTH KNOWLEDGE BASE:

EPIDEMIOLOGY:
- MDD: 21M Americans (8.3% of adults), 14.8M with serious impairment. 60% do not receive treatment.
- Anxiety disorders: 40M Americans (18.1% of adults). Most common mental illness.
- PTSD: 12M Americans in given year; 20% of Iraq/Afghanistan veterans.
- Schizophrenia: 3.5M Americans (1.1%). Severe, chronic.
- Bipolar: 5.7M Americans (2.8%). High economic burden.
- Substance use disorder: 46.3M Americans age 12+ (2021). Opioid OD deaths: 80,411 in 2021.
- Mental health provider shortage: 160M Americans in HPSAs. 50%+ of counties have no psychiatrist.

APPROVED THERAPIES:
- MDD: SSRIs (fluoxetine, sertraline, escitalopram), SNRIs (venlafaxine, duloxetine), bupropion, mirtazapine, esketamine/Spravato (REMS), brexanolone/Zulresso (PPD), zuranolone/Zurzuvae (2023, oral, MDD+PPD)
- PTSD: sertraline, paroxetine (only FDA-approved pharmacotherapy for PTSD), prazosin (nightmares)
- TRD: esketamine, ECT, TMS (FDA cleared for MDD, OCD, anxiety, smoking cessation)
- Schizophrenia: typical + atypical antipsychotics; long-acting injectables (LAI) for adherence; lumateperone (Caplyta), deutetrabenazine

MARKET SIZING:
- Mental health drug market: $18.7B U.S. (2023)
- Digital mental health/apps: $5.8B global (2023), growing 24%/yr
- Telepsychiatry: $2.4B U.S., growing 35%/yr
- TMS: $1.2B global

FUNDING:
- NIMH SBIR Phase 1: up to $305,000. Phase 2: up to $2.5M. nimh.nih.gov/funding/grants
- SAMHSA grants: $500K-$5M for access, prevention, treatment programs
- Wellcome Trust: mental health focus grants, £100K-£2M
- One Mind: industry partnerships for mental health innovation
- AFSP (American Foundation for Suicide Prevention): research grants up to $75K""",

    critic_rules = """MENTAL HEALTH VALIDATION RULES:

FACTUAL CHECKS:
- MDMA-assisted therapy: FDA CRL August 2024 — NOT approved. Flag if described as "approved" or "recently approved"
- Psilocybin: FDA Breakthrough Therapy designation for MDD/TRD — NOT approved for clinical use
- MDD prevalence: 21M Americans (flag if stated as 10M or 40M+)
- Mental health provider shortage: 160M Americans in HPSAs (flag if stated as 50M or 200M+)
- Esketamine: intranasal (NOT IV), REMS required, must be in certified healthcare setting

REGULATORY CHECKS:
- Prescription Digital Therapeutics (PDT): FDA De Novo pathway. Only EndeavorRx (ADHD) and a few others authorized.
- REMS for esketamine: patient must be observed for 2 hours post-administration. Cannot be dispensed for home use.
- Mental health parity (MHPAEA): requires equivalent coverage but does NOT guarantee payment or access
- TMS: FDA 510(k) cleared, not PMA approved — important distinction for investors

MARKET SIZE CHECKS:
- Mental health drug market: $18.7B U.S. — flag if stated as <$10B or >$30B
- Digital mental health: fast-growing but still <$6B U.S. — flag if stated as >$15B U.S.
- Flag: any claim that esketamine/Spravato dominates TRD market — it has limited adoption due to REMS burden

HALLUCINATION CHECKS:
- Flag: "FDA approved MDMA for PTSD" — CRL was issued in August 2024
- Flag: NIMH grants > $5M for SBIR without special mechanism
- Flag: any psychedelic drug described as "recently FDA approved" without specifying which drug
- Valid sources: NIMH (nimh.nih.gov), SAMHSA (samhsa.gov), FDA Drug Approvals database"""
)


# ── Expert Registry ───────────────────────────────────────────────────────────

EXPERT_REGISTRY: Dict[str, ExpertProfile] = {
    "antibiotic_amr":      AMR_EXPERT,
    "oncology":            ONCOLOGY_EXPERT,
    "cardiology":          CARDIOLOGY_EXPERT,
    "neurology_cns":       NEURO_EXPERT,
    "metabolic_diabetes":  METABOLIC_EXPERT,
    "mental_health":       MENTAL_HEALTH_EXPERT,
}

DOMAIN_CHOICES = [
    ("auto",              "Auto-detect",          "🔍"),
    ("antibiotic_amr",    "Antibiotic / AMR",     "💊"),
    ("oncology",          "Oncology",             "🔬"),
    ("cardiology",        "Cardiology",           "❤️"),
    ("neurology_cns",     "Neurology / CNS",      "🧠"),
    ("metabolic_diabetes","Metabolic / Diabetes", "⚕️"),
    ("mental_health",     "Mental Health",        "🧩"),
]


def get_expert(domain_id: str) -> Optional[ExpertProfile]:
    return EXPERT_REGISTRY.get(domain_id)


def get_all_keywords() -> Dict[str, List[str]]:
    return {k: v.router_keywords for k, v in EXPERT_REGISTRY.items()}
