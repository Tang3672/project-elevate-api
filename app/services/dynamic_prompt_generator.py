"""
Dynamic Expert Prompt Generator
================================
Generates prescriptive, disease-specific system prompts for each sub-expert
at report time using the expert's domain profile + the classified disease.

This replaces hardcoded system_prompt strings with generated ones that are:
- Specific to the exact disease (not just the domain)
- Prescriptive (MUST do X) rather than descriptive (here's what you know)
- Scalable: adding a new expert = adding a lightweight domain_profile dict

Architecture:
  SubExpertProfile.domain_profile (lightweight dict)
      + disease_name (from Disease Classifier)
      + Haiku call (~1.5s, ~500 tokens)
      → prescriptive system_prompt string
      → injected into Researcher Claude context
"""

import logging
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
HAIKU_MODEL = "claude-haiku-4-5-20251001"
TIMEOUT = 20.0

# ── Domain Profiles ───────────────────────────────────────────────────────────
# Lightweight per-expert metadata used to generate prescriptive system prompts.
# Add a new expert = add a new entry here. No prompt engineering required.

DOMAIN_PROFILES = {

    "drug_amr": {
        "title": "AMR / Antibiotic Drug Regulatory Expert",
        "product_class": "small molecule antibiotic or antifungal (NDA)",
        "regulatory_bodies": ["FDA CDER", "IDSA", "ESCMID"],
        "key_designations": ["QIDP (+5yr exclusivity, 6-month Priority Review)", "LPAD (limited population)", "Fast Track", "Breakthrough Therapy"],
        "trial_frameworks": ["HABP/VABP (FDA 2014)", "cUTI (2018 SUFA endpoint)", "ABSSSI (48-72hr responder)", "cIAI (2015 guidance)", "non-inferiority vs superiority"],
        "funding_sources": ["CARB-X (up to $4.5M Ph1, $12M Ph2, NO Phase 3)", "BARDA CBRN BAA ($50M-$500M)", "NIH NIAID DMID ($5M-$50M)", "PASTEUR Act (proposed, not law)"],
        "market_access": ["NTAP (65-75% cost add-on, 2-3yr post-approval)", "antimicrobial stewardship restrictions", "VA/DoD formulary", "GPO contracts"],
        "forbidden_generics": ["significant unmet need", "complex regulatory pathway", "competitors exist", "large market opportunity"],
        "hard_facts": ["CARB-X does NOT fund Phase 3", "NDM not covered by avibactam or vaborbactam", "QIDP = +5yr not +3yr or +7yr", "NTAP = 65-75% not 50% or 100%"],
    },

    "drug_oncology": {
        "title": "Oncology Drug Regulatory Expert",
        "product_class": "small molecule oncology drug (NDA)",
        "regulatory_bodies": ["FDA CDER Oncology Center of Excellence", "ASCO", "NCCN", "NCI"],
        "key_designations": ["Breakthrough Therapy", "Accelerated Approval (surrogate endpoint)", "Priority Review", "Orphan Drug (+7yr exclusivity, tax credits)", "Fast Track"],
        "trial_frameworks": ["ORR as surrogate for accelerated approval", "OS/PFS for full approval", "basket trials", "biomarker-selected populations", "adaptive trial design"],
        "funding_sources": ["NCI SBIR/STTR ($300K-$2M Ph1, up to $3M Ph2)", "NCI CRADA", "cancer-specific foundations (LLS, PCF, etc.)", "Stand Up To Cancer"],
        "market_access": ["oncology carve-outs from PBM formulary", "buy-and-bill vs specialty pharmacy", "J-code reimbursement", "payer prior authorization by biomarker"],
        "forbidden_generics": ["cancer is a large market", "there is unmet need in oncology", "FDA has special pathways"],
        "hard_facts": ["Accelerated Approval requires confirmatory trial", "Orphan Drug = <200K US patients/yr", "Breakthrough Therapy ≠ guaranteed approval", "OS benefit required for full approval if AA granted on ORR"],
    },

    "drug_cns": {
        "title": "CNS Drug Regulatory Expert",
        "product_class": "small molecule CNS drug (NDA)",
        "regulatory_bodies": ["FDA CDER Division of Psychiatry", "FDA Division of Neurology", "AAN", "APA"],
        "key_designations": ["Breakthrough Therapy", "Fast Track", "Orphan Drug (rare neurological)", "Priority Review"],
        "trial_frameworks": ["placebo-controlled RCT (FDA default for CNS)", "crossover design limitations", "validated rating scales (ADAS-Cog, MADRS, PANSS, UPDRS)", "patient-reported outcomes", "enriched enrollment designs"],
        "funding_sources": ["NIMH SBIR ($300K-$2M)", "NINDS ($5M-$20M clinical)", "Patient advocacy grants (Alzheimer's Association, MDF)", "NCATS CTSA network"],
        "market_access": ["high generic substitution pressure", "step therapy requirements", "prior auth for branded CNS drugs", "REMS programs for abuse-potential drugs"],
        "forbidden_generics": ["CNS is a difficult space", "blood-brain barrier is a challenge", "psychiatric drugs face stigma"],
        "hard_facts": ["FDA requires 2 adequate and well-controlled trials for most CNS indications", "Patient-reported outcomes require FDA COA qualification", "REMS required for opioids, certain antipsychotics, and abuse-potential drugs"],
    },

    "drug_cardiology": {
        "title": "Cardiovascular Drug Regulatory Expert",
        "product_class": "small molecule cardiovascular drug (NDA)",
        "regulatory_bodies": ["FDA CDER Division of Cardiology and Nephrology", "ACC", "AHA", "ESC"],
        "key_designations": ["Breakthrough Therapy", "Fast Track", "Priority Review", "Orphan Drug (rare cardiac)"],
        "trial_frameworks": ["MACE endpoint (CV death, MI, stroke)", "superiority vs non-inferiority", "CVOT (cardiovascular outcomes trial)", "surrogate endpoints (LDL, HbA1c) vs hard outcomes", "adaptive enrichment"],
        "funding_sources": ["NHLBI SBIR ($300K-$2M)", "AHA Strategically Focused Research Networks", "Patient advocacy (Heart Failure Society)"],
        "market_access": ["formulary tier placement by payer", "PCSK9 inhibitor prior auth as precedent", "cardiologist vs PCP prescribing dynamics", "outcomes-based contracts with payers"],
        "forbidden_generics": ["cardiovascular disease is common", "large patient population", "unmet need exists"],
        "hard_facts": ["FDA typically requires CVOT post-approval for new CV drugs", "Surrogate endpoint approval requires confirmatory outcomes data", "ACC/AHA guidelines drive formulary decisions more than FDA label"],
    },

    "drug_metabolic": {
        "title": "Metabolic Disease Drug Regulatory Expert",
        "product_class": "small molecule metabolic drug (NDA) — diabetes, obesity, NASH, lipids",
        "regulatory_bodies": ["FDA CDER Division of Diabetes, Lipid Disorders, and Obesity", "ADA", "AACE", "EASD"],
        "key_designations": ["Fast Track", "Breakthrough Therapy (rare metabolic)", "Orphan Drug (rare metabolic disorders)"],
        "trial_frameworks": ["HbA1c as surrogate for T2D", "CVOT requirement for T2D drugs post-2008 FDA guidance", "weight loss % for obesity (≥5% placebo-adjusted)", "liver histology endpoints for NASH (NAS score, fibrosis stage)", "NAFLD Activity Score"],
        "funding_sources": ["NIDDK SBIR ($300K-$2M)", "ADA research grants", "Helmsley Charitable Trust (T1D)", "JDRF (T1D focused)"],
        "market_access": ["PBM formulary wars (GLP-1 class example)", "step therapy: metformin first for T2D", "obesity drug coverage gap (Medicare excluded until 2024)", "payer outcomes-based contracts (Novo/Eli Lilly precedents)"],
        "forbidden_generics": ["diabetes is a large market", "obesity is growing", "metabolic disease is common"],
        "hard_facts": ["FDA 2008 guidance requires CVOT for T2D drugs to rule out CV harm", "Obesity drug approval requires ≥5% weight loss vs placebo AND safety data", "NASH: FDA accepts surrogate (histology) but confirmatory outcomes trial required", "GLP-1 class dominates — any new entrant must show differentiation vs semaglutide"],
    },

    "drug_mental_health": {
        "title": "Mental Health Drug Regulatory Expert",
        "product_class": "small molecule psychiatric drug (NDA)",
        "regulatory_bodies": ["FDA CDER Division of Psychiatry", "APA", "NIMH"],
        "key_designations": ["Breakthrough Therapy", "Fast Track", "REMS (for abuse-potential or high-risk drugs)"],
        "trial_frameworks": ["MADRS/HAM-D for depression", "PANSS for schizophrenia", "Y-BOCS for OCD", "CAPS for PTSD", "placebo response rate challenge in psychiatric trials", "fixed-dose parallel group design"],
        "funding_sources": ["NIMH SBIR ($300K-$2M)", "Brain & Behavior Research Foundation (NARSAD grants)", "One Mind"],
        "market_access": ["high generic substitution (most branded psychiatrics face generics)", "prior auth standard for branded vs generic", "REMS restricts distribution channels", "step therapy through generic SSRIs/SNRIs first"],
        "forbidden_generics": ["mental health is stigmatized", "psychiatric drugs are controversial", "large unmet need"],
        "hard_facts": ["FDA requires 2 adequate well-controlled trials for psychiatric indications", "Placebo response rates in depression trials average 35-40% — underpowered trials fail", "REMS required for clozapine, esketamine, sodium oxybate class", "Most psychiatric drugs face generic competition within 5-10yr of launch"],
    },

    "drug_rare_disease": {
        "title": "Rare Disease Drug Regulatory Expert",
        "product_class": "small molecule rare disease drug (NDA)",
        "regulatory_bodies": ["FDA CDER Office of Orphan Products Development", "NORD", "EURORDIS"],
        "key_designations": ["Orphan Drug Designation (+7yr exclusivity, $500K+ tax credit, waived PDUFA fees)", "Breakthrough Therapy", "Accelerated Approval (surrogate/intermediate endpoint)", "Priority Review", "Rare Pediatric Disease (priority review voucher)"],
        "trial_frameworks": ["single-arm trials with natural history controls", "N-of-1 and basket designs", "biomarker/surrogate endpoints", "patient registry data as external control", "adaptive designs with small N"],
        "funding_sources": ["NIH NCATS RDCRN ($5M-$30M)", "OOPD grants ($500K)", "patient advocacy foundations (disease-specific)", "FDA Rare Pediatric Disease PRV (worth $100M-$150M at auction)"],
        "market_access": ["orphan drug pricing ($100K-$500K/yr standard)", "payer coverage generally favorable for rare disease", "patient assistance programs critical", "KOL network extremely concentrated (10-20 specialists globally)"],
        "forbidden_generics": ["rare diseases have unmet need", "small patient population", "orphan drug designation is available"],
        "hard_facts": ["Orphan Drug = <200,000 US patients/yr", "7yr exclusivity blocks SAME drug for SAME indication — does not block different drugs", "Rare Pediatric Disease PRV auctioned for $100M-$150M recently", "Single-arm trial with natural history control is FDA-accepted for rare disease"],
    },

    "drug_infectious_non_amr": {
        "title": "Infectious Disease Drug Expert (non-AMR)",
        "product_class": "small molecule antiviral, antiparasitic, or non-AMR anti-infective (NDA)",
        "regulatory_bodies": ["FDA CDER Division of Antivirals", "WHO", "IDSA", "PEPFAR"],
        "key_designations": ["Breakthrough Therapy (HIV, HCV, RSV)", "Fast Track", "Priority Review", "Accelerated Approval (surrogate: viral load, SVR)"],
        "trial_frameworks": ["viral load suppression as surrogate (HIV, HCV)", "SVR12 for HCV", "time-to-event for viral outcomes", "non-inferiority vs standard of care", "open-label in HIV"],
        "funding_sources": ["NIAID SBIR ($300K-$2M)", "BARDA (pandemic preparedness)", "USAID/PEPFAR (HIV/malaria global health)", "Gates Foundation (LMIC-relevant)"],
        "market_access": ["340B pricing for HIV (safety net hospitals)", "ADAP programs for HIV drugs", "generic competition rapid for HCV post-SVR era", "global access agreements for LMIC"],
        "forbidden_generics": ["infectious disease has unmet need", "viruses mutate", "global burden is high"],
        "hard_facts": ["HIV: FDA accepts viral load <50 copies/mL as surrogate", "HCV: SVR12 is accepted surrogate for cure", "RSV: two approved vaccines (Abrysvo, Arexvy) as of 2023", "COVID antivirals: Paxlovid standard of care — new entrant must differentiate"],
    },

    "drug_immunology": {
        "title": "Immunology / Autoimmune Drug Regulatory Expert",
        "product_class": "small molecule immunology drug — JAK inhibitors, S1P modulators, PDE4 inhibitors (NDA)",
        "regulatory_bodies": ["FDA CDER Division of Rheumatology and Transplant Medicine", "ACR", "EULAR"],
        "key_designations": ["Breakthrough Therapy", "Priority Review", "REMS (JAK inhibitors post-2021 boxed warning)"],
        "trial_frameworks": ["ACR20/50/70 response criteria (RA)", "PASI 75/90/100 (psoriasis)", "Mayo score (IBD)", "placebo-controlled 12-52 week induction", "long-term extension studies required"],
        "funding_sources": ["NIAID/NIAMS SBIR ($300K-$2M)", "Arthritis Foundation", "Crohn's & Colitis Foundation"],
        "market_access": ["JAK inhibitor REMS (boxed warning for MACE, malignancy, thrombosis)", "step therapy through methotrexate/conventional DMARDs first", "biosimilar competition to anti-TNFs changes market dynamics", "payer prefers established biologics with outcomes data"],
        "forbidden_generics": ["autoimmune disease is common", "JAK inhibitors are a crowded space", "biologics dominate"],
        "hard_facts": ["FDA 2021: JAK inhibitors require REMS and boxed warning for MACE/malignancy/thrombosis", "ACR20 = 20% improvement in tender/swollen joint count plus 3 of 5 other measures", "Step therapy: most payers require methotrexate failure before JAK inhibitor", "Tofacitinib ORAL trial showed increased CV risk vs TNF inhibitors"],
    },

    "biologic_oncology": {
        "title": "Oncology Biologic Regulatory Expert",
        "product_class": "monoclonal antibody, ADC, bispecific, or fusion protein for oncology (BLA)",
        "regulatory_bodies": ["FDA CDER Oncology Center of Excellence", "FDA CBER (CAR-T)", "ASCO", "NCCN"],
        "key_designations": ["Breakthrough Therapy", "Accelerated Approval (ORR surrogate)", "Priority Review", "Orphan Drug", "Biosimilar pathway (351(k))"],
        "trial_frameworks": ["ORR for accelerated approval", "OS/PFS for full approval", "biomarker-selected enrollment (companion diagnostic requirement)", "ADC: payload + linker + target trifecta analysis", "bispecific: CD3 engagement toxicity management"],
        "funding_sources": ["NCI SBIR ($300K-$3M)", "NCI CRADA", "cancer foundations", "Stand Up To Cancer Dream Teams"],
        "market_access": ["companion diagnostic co-development required for targeted therapy", "buy-and-bill oncology reimbursement", "J-code assignment timeline (6-12 months post-approval)", "NCCN Category 1 designation drives formulary"],
        "forbidden_generics": ["antibodies are effective in cancer", "immuno-oncology is growing", "there are biomarker opportunities"],
        "hard_facts": ["ADC: >15 FDA-approved as of 2024 — must identify payload/linker differentiation", "Bispecific: blinatumomab/mosunetuzumab precedents — CRS management is key CMC/clinical issue", "Companion diagnostic: FDA requires PMA/510(k) co-approval for biomarker-selected therapy", "Biosimilar mAbs: reference product exclusivity = 12yr (Biologics Price Competition Act)"],
    },

    "biologic_immunology": {
        "title": "Immunology Biologic Regulatory Expert",
        "product_class": "monoclonal antibody or fusion protein for autoimmune/inflammatory disease (BLA)",
        "regulatory_bodies": ["FDA CDER Division of Rheumatology", "FDA CDER Dermatology", "ACR", "EULAR", "AAD"],
        "key_designations": ["Breakthrough Therapy", "Priority Review", "Biosimilar pathway (12yr exclusivity for reference biologic)"],
        "trial_frameworks": ["ACR20/50/70 (RA)", "PASI 75/90/100 (psoriasis)", "IGA 0/1 (atopic dermatitis)", "Mayo score (IBD)", "52-week induction + maintenance design"],
        "funding_sources": ["NIAMS SBIR", "Arthritis Foundation", "patient advocacy (Crohn's & Colitis Foundation)"],
        "market_access": ["anti-TNF biosimilar wave (adalimumab LOE 2023) reshaping market", "payer step therapy through biosimilars before branded", "IL-17/IL-23 class differentiation vs anti-TNF", "subcutaneous vs IV formulation preference"],
        "forbidden_generics": ["biologics are effective for autoimmune", "there is significant pipeline"],
        "hard_facts": ["Humira (adalimumab) LOE 2023 — 9 biosimilars approved, market pricing down 85%", "IL-23 inhibitors (risankizumab, guselkumab) show superior PASI 100 vs IL-17", "Biosimilar reference product: 12yr data exclusivity under BPCIA", "Interchangeable biosimilar designation allows pharmacist substitution without prescriber"],
    },

    "biologic_hematology": {
        "title": "Hematology Biologic Regulatory Expert",
        "product_class": "biologic for blood disorders — hemophilia, sickle cell, MDS, ITP (BLA)",
        "regulatory_bodies": ["FDA CDER Division of Hematology", "ASH", "NHF"],
        "key_designations": ["Breakthrough Therapy", "Orphan Drug", "Accelerated Approval", "Priority Review", "Rare Pediatric Disease PRV"],
        "trial_frameworks": ["annualized bleed rate (ABR) for hemophilia", "hemoglobin response for sickle cell/anemia", "platelet count response for ITP", "transfusion independence for MDS", "subcutaneous vs IV dosing preference"],
        "funding_sources": ["NHLBI SBIR ($300K-$2M)", "NHF (hemophilia)", "Sickle Cell Disease Association", "NIH NIDDK"],
        "market_access": ["hemophilia: specialty pharmacy only, 100% specialty benefit", "factor pricing $200K-$800K/yr", "gene therapy entering (higher upfront cost vs lifetime factor cost)", "payer outcomes-based contracts for gene therapy"],
        "forbidden_generics": ["rare blood disorders have unmet need", "hemophilia is well-characterized"],
        "hard_facts": ["Hemophilia A market: emicizumab (Hemlibra) dominates — new entrant must beat ABR and dosing convenience", "Sickle cell: 2 gene therapies approved 2023 (Casgevy, Lyfgenia) — curative intent changes market", "ITP: romiplostim and eltrombopag established — new entrant needs differentiation on safety or dosing", "Factor VIII: half-life extension is current innovation frontier"],
    },

    "biologic_rare_disease": {
        "title": "Rare Disease Biologic Regulatory Expert",
        "product_class": "biologic (enzyme replacement, fusion protein, mAb) for rare disease (BLA)",
        "regulatory_bodies": ["FDA OOPD", "FDA CDER/CBER (product-dependent)", "NORD", "EURORDIS"],
        "key_designations": ["Orphan Drug (+7yr exclusivity)", "Breakthrough Therapy", "Accelerated Approval", "Rare Pediatric Disease PRV ($100M-$150M auction value)", "Priority Review"],
        "trial_frameworks": ["natural history as external control", "single-arm with biomarker endpoint", "N-of-1 basket designs", "patient registry data", "PRO development in rare disease"],
        "funding_sources": ["NCATS ($5M-$30M)", "OOPD grants ($500K)", "disease-specific patient foundations", "BARDA (for certain rare diseases with biodefense angle)"],
        "market_access": ["pricing $100K-$2M+/yr (enzyme replacement precedents)", "payer coverage generally favorable", "patient assistance programs essential", "ultra-rare (<1,000 patients) may require global pricing"],
        "forbidden_generics": ["rare disease has unmet need", "small patient population is challenging"],
        "hard_facts": ["ERT (enzyme replacement): Cerezyme for Gaucher's = pricing benchmark at $200K-$300K/yr", "Orphan Drug exclusivity: 7yr but does NOT block drugs with clinical superiority", "PRV: recent auctions $100M-$150M — significant non-dilutive financing tool", "FDA will accept surrogate endpoints for rare disease if plausibly predicts clinical benefit"],
    },

    "biologic_cardiology": {
        "title": "Cardiovascular Biologic Regulatory Expert",
        "product_class": "biologic for cardiovascular disease — PCSK9i, anti-inflammatory, RNA therapeutic (BLA)",
        "regulatory_bodies": ["FDA CDER Division of Cardiology", "ACC", "AHA", "ESC"],
        "key_designations": ["Breakthrough Therapy", "Fast Track", "Priority Review"],
        "trial_frameworks": ["MACE endpoint (CV death, MI, stroke, hospitalization)", "LDL-C reduction as surrogate (PCSK9i precedent)", "CVOT required post-approval", "large N >10,000 for MACE outcomes", "placebo on background statin therapy"],
        "funding_sources": ["NHLBI SBIR", "AHA Strategically Focused Networks", "outcomes-based payer contracts"],
        "market_access": ["PCSK9i prior auth burden (step therapy through max-dose statin)", "LDL <70 threshold for PCSK9i coverage", "outcomes-based contracts (Novartis inclisiran model)", "cardiologist vs PCP prescribing split"],
        "forbidden_generics": ["cardiovascular disease is common", "statins are not enough for all patients"],
        "hard_facts": ["PCSK9i (evolocumab, alirocumab): 15% CV event reduction on top of statins — new entrant must match or beat", "inclisiran: twice-yearly dosing vs monthly injection = key differentiator", "Colchicine (Lodoco): anti-inflammatory CV approved 2023 — low-cost generic competition", "ATTR amyloidosis: tafamidis + patisiran + vutrisiran approved — crowded but growing"],
    },

    "gene_therapy_rare": {
        "title": "Rare Disease Gene Therapy Regulatory Expert",
        "product_class": "AAV gene therapy for rare monogenic disease (BLA — CBER)",
        "regulatory_bodies": ["FDA CBER Office of Tissues and Advanced Therapies (OTAT)", "EMA CAT", "ASGCT"],
        "key_designations": ["Breakthrough Therapy", "Orphan Drug", "Accelerated Approval", "Rare Pediatric Disease PRV", "RMAT (Regenerative Medicine Advanced Therapy)"],
        "trial_frameworks": ["single-arm with natural history control", "biomarker + functional endpoint", "long-term follow-up 15yr (FDA GT guidance)", "immune response monitoring (NAb titers)", "re-dosing limitation (AAV immunogenicity)"],
        "funding_sources": ["NCATS ($5M-$30M)", "OOPD", "disease foundations (MDA, Parent Project MD)", "BARDA (for select conditions)", "ARPA-H"],
        "market_access": ["one-time pricing $2M-$4M (Zolgensma precedent)", "annuity-based payer contracts", "outcomes-based payment (pay-over-time if durable)", "Medicaid rebate cliff for one-time therapies"],
        "forbidden_generics": ["gene therapy is promising", "one-time treatment is appealing", "AAV is a validated platform"],
        "hard_facts": ["FDA CBER OTAT regulates — NOT CDER", "RMAT designation = rolling review + early interactions + priority review", "AAV immunogenicity: pre-existing NAb titers exclude ~30-50% of patients", "Zolgensma ($2.1M) and Hemgenix ($3.5M) set pricing precedent", "15yr long-term follow-up required by FDA GT guidance", "Re-dosing generally not possible due to AAV immune response"],
    },

    "gene_therapy_oncology": {
        "title": "Oncology Gene & Cell Therapy Regulatory Expert",
        "product_class": "CAR-T, TCR-T, TIL therapy, oncolytic virus for cancer (BLA — CBER)",
        "regulatory_bodies": ["FDA CBER OTAT", "ASCO", "ASGCT", "NCI"],
        "key_designations": ["Breakthrough Therapy", "RMAT", "Accelerated Approval (ORR surrogate)", "Priority Review", "Orphan Drug"],
        "trial_frameworks": ["ORR/CR rate for accelerated approval", "durability of response (DOR)", "single-arm pivotal (precedent: axicabtagene, tisagenlecleucel)", "CRS and ICANS grading (ASTCT criteria)", "manufacturing turnaround time as clinical endpoint"],
        "funding_sources": ["NCI SBIR ($300K-$3M)", "NCI CRADA", "Stand Up To Cancer", "ARPA-H"],
        "market_access": ["CAR-T: hospital outpatient only, REMS required", "CMS NTAP for CAR-T ($150K-$500K add-on)", "authorized treatment centers limit access", "allogeneic vs autologous cost/access tradeoff"],
        "forbidden_generics": ["CAR-T is a breakthrough", "cell therapy is promising", "personalized medicine is the future"],
        "hard_facts": ["6 FDA-approved CAR-T products as of 2024 (axi-cel, tisa-cel, liso-cel, ide-cel, cilta-cel, brexu-cel)", "Manufacturing: autologous = 2-4 week turnaround, allogeneic = off-the-shelf", "CRS grade 3-4 in 20-30% of patients — key safety differentiator", "REMS required for all approved CAR-T products", "NTAP: new CAR-T products can apply for ~$186K-$500K add-on payment"],
    },

    "gene_therapy_cns": {
        "title": "CNS Gene Therapy Regulatory Expert",
        "product_class": "AAV or ASO gene therapy for neurological disease (BLA — CBER or NDA)",
        "regulatory_bodies": ["FDA CBER OTAT (AAV)", "FDA CDER (ASO — NDA)", "AAN", "CureSMA", "NORD"],
        "key_designations": ["Breakthrough Therapy", "RMAT (AAV)", "Orphan Drug", "Rare Pediatric Disease PRV", "Accelerated Approval"],
        "trial_frameworks": ["motor function scales (CHOP-INTEND, HINE, RULM)", "cognitive/functional endpoints", "natural history controls", "biomarker endpoints (neurofilament light)", "intrathecal vs IV vs direct CNS delivery"],
        "funding_sources": ["NCATS", "NINDS ($5M-$30M)", "disease foundations (CureSMA, Muscular Dystrophy Association)", "ARPA-H"],
        "market_access": ["SMA: Zolgensma + nusinersen + risdiplam — three approved, market defined", "intrathecal delivery requires specialized center", "newborn screening expanding access window", "outcomes-based pricing for durable therapies"],
        "forbidden_generics": ["CNS gene therapy is promising", "blood-brain barrier is the challenge"],
        "hard_facts": ["Zolgensma (SMA): $2.1M one-time, IV in infants <2yr", "Nusinersen (Spinraza): intrathecal ASO, $750K year 1 then $375K/yr", "Risdiplam (Evrysdi): oral SMN2 splicing modifier, $340K/yr", "AAV9 crosses BBB in neonates — less effective in adults", "Neurofilament light (NfL) emerging as surrogate biomarker for neurodegeneration"],
    },

    "gene_therapy_rna": {
        "title": "RNA Therapeutics Regulatory Expert",
        "product_class": "siRNA, ASO, mRNA therapeutic (NDA or BLA depending on modality)",
        "regulatory_bodies": ["FDA CDER (ASO/siRNA as drugs)", "FDA CBER (mRNA as biologic)", "OTS (oligonucleotide therapeutics)"],
        "key_designations": ["Breakthrough Therapy", "Orphan Drug", "Fast Track", "Accelerated Approval"],
        "trial_frameworks": ["protein knockdown as surrogate (siRNA)", "splicing correction as biomarker (ASO)", "mRNA: protein expression level + functional endpoint", "LNP delivery: liver-targeting validated, extrahepatic emerging"],
        "funding_sources": ["DARPA (mRNA platform)", "BARDA (pandemic/biodefense)", "NCATS", "NIH NCI/NIAID"],
        "market_access": ["siRNA pricing: inclisiran $3,250/dose, givosiran $460K/yr", "ASO: nusinersen $750K yr1 — established high pricing", "LNP IP landscape: Moderna/Alnylam/Arbutus patent thicket", "delivery route determines reimbursement pathway"],
        "forbidden_generics": ["RNA therapeutics are a growing field", "mRNA platform is validated by COVID vaccines"],
        "hard_facts": ["siRNA: Alnylam has 5 approved products — IP position dominant in RNAi", "ASO: Ionis has 10+ approved — largest ASO portfolio", "mRNA therapeutics (non-vaccine): no approved small molecule mRNA therapeutic as of 2024 outside vaccines", "LNP patent landscape: Alnylam-Moderna settlement 2022 — licensing required", "Extrahepatic delivery: major unsolved problem for non-liver targets"],
    },

    "gene_therapy_hematology": {
        "title": "Hematology Gene Therapy Regulatory Expert",
        "product_class": "gene therapy or gene editing for blood disorders — sickle cell, hemophilia, thalassemia (BLA)",
        "regulatory_bodies": ["FDA CBER OTAT", "ASH", "NHF", "Sickle Cell Disease Association"],
        "key_designations": ["Breakthrough Therapy", "RMAT", "Orphan Drug", "Rare Pediatric Disease PRV", "Accelerated Approval"],
        "trial_frameworks": ["VOC (vaso-occlusive crisis) reduction for sickle cell", "transfusion independence for thalassemia", "annualized bleed rate for hemophilia", "HbF induction as surrogate", "engraftment and persistence as biomarker"],
        "funding_sources": ["NHLBI ($5M-$30M)", "Sickle Cell Disease Association", "NHF", "Gates Foundation (global sickle cell)"],
        "market_access": ["Casgevy (exa-cel): $2.2M — CRISPR-based, one-time", "Lyfgenia (lovo-cel): $3.1M — lentiviral, one-time", "Hemgenix (hemophilia B): $3.5M one-time", "Medicaid: states negotiating value-based agreements for one-time therapies"],
        "forbidden_generics": ["sickle cell has unmet need", "gene therapy is curative", "hemophilia market is large"],
        "hard_facts": ["Casgevy = first CRISPR therapy approved (FDA Dec 2023)", "Lyfgenia: boxed warning for hematologic malignancy", "Hemgenix ($3.5M): most expensive drug ever approved at launch", "Hydroxyurea: $200/yr generic — any new sickle cell therapy must justify cost vs HU"],
    },

    "device_cardiovascular": {
        "title": "Cardiovascular Medical Device Regulatory Expert",
        "product_class": "cardiovascular medical device — stents, valves, electrophysiology, ventricular assist (PMA or 510(k))",
        "regulatory_bodies": ["FDA CDRH Office of Cardiovascular Devices", "ACC", "AHA", "HRS", "STS"],
        "key_designations": ["PMA (Class III — high risk)", "510(k) (Class II — substantial equivalence)", "De Novo (novel low-risk)", "Breakthrough Device Designation", "HDE (Humanitarian Device Exemption — <8,000 pts/yr)"],
        "trial_frameworks": ["IDE (Investigational Device Exemption) required for significant risk devices", "MACE primary endpoint", "non-inferiority vs standard of care", "pivotal trial 500-2,000 patients", "real-world evidence post-approval (522 studies)"],
        "funding_sources": ["NIH NHLBI SBIR ($300K-$2M)", "AHA grant programs", "BARDA (cardiac biodefense)"],
        "market_access": ["DRG bundled payment vs separate reimbursement", "NTAP for novel high-cost devices", "hospital value analysis committee (VAC) approval", "surgeon preference items — KOL adoption critical", "CPT code assignment (1-2yr post-approval)"],
        "forbidden_generics": ["cardiovascular devices have large market", "minimally invasive is the trend"],
        "hard_facts": ["PMA: $300K-$500K PDUFA fee, 180-day review", "510(k): must identify predicate device — if no predicate, De Novo required", "Breakthrough Device: 25% faster total time to decision (FDA data)", "TAVR (transcatheter aortic valve): >100K procedures/yr — mature, competitive market", "CMS NCD required for novel high-cost CV devices before broad coverage"],
    },

    "device_metabolic": {
        "title": "Metabolic Disease Device Regulatory Expert",
        "product_class": "metabolic medical device — CGM, insulin pump, bariatric device (PMA or 510(k))",
        "regulatory_bodies": ["FDA CDRH Division of Diabetes, Endocrinology, and Obesity", "ADA", "AACE", "ASMBS (bariatric)"],
        "key_designations": ["PMA (Class III)", "510(k) (Class II)", "De Novo", "Breakthrough Device"],
        "trial_frameworks": ["HbA1c reduction as primary endpoint (CGM/pump)", "time-in-range (TIR) — FDA accepted 2023", "weight loss % for bariatric devices", "hypoglycemia reduction as key safety endpoint", "closed-loop (AID system) — iCGM + ACE pump pairing"],
        "funding_sources": ["NIDDK SBIR", "JDRF (T1D device focus)", "Helmsley Charitable Trust"],
        "market_access": ["CGM: Medicare coverage requires 3x/day fingerstick or insulin use", "iCGM designation required for AID system integration", "ACE pump designation for algorithm-agnostic integration", "bariatric device: coverage extremely limited by payers"],
        "forbidden_generics": ["diabetes device market is large", "CGM is growing", "closed-loop is the future"],
        "hard_facts": ["Dexcom G7 and Abbott FreeStyle Libre 3 dominate CGM — new entrant needs differentiation on accuracy, wear time, or cost", "Time-in-range (TIR 70-180mg/dL): FDA accepted as primary endpoint 2023", "iCGM designation (21 CFR 895.3650): required for integration with AID systems", "Closed-loop (AID): Control-IQ, MiniMed 780G, Omnipod 5 approved — market maturing"],
    },

    "device_neurology": {
        "title": "Neurology Device Regulatory Expert",
        "product_class": "neurological device — neuromodulation, BCI, DBS, TMS, epilepsy (PMA or 510(k))",
        "regulatory_bodies": ["FDA CDRH Division of Neurological and Physical Medicine Devices", "AAN", "AES (epilepsy)", "CNS Summit"],
        "key_designations": ["PMA (Class III)", "Breakthrough Device", "HDE (rare neurological conditions)", "De Novo"],
        "trial_frameworks": ["seizure frequency reduction (epilepsy)", "motor function scales (DBS for Parkinson's)", "responder rate at 50% seizure reduction", "sham-controlled trial design challenge", "open-label extension for chronic implants"],
        "funding_sources": ["NINDS SBIR ($300K-$2M)", "DARPA (BCI programs)", "Brain Initiative (NIH)", "patient foundations (Epilepsy Foundation)"],
        "market_access": ["neuromodulation: CPT codes established for DBS, VNS, TMS", "payer prior auth for TMS (depression)", "neurosurgeon required for implantable devices", "hospital capital equipment budget cycle"],
        "forbidden_generics": ["neuromodulation is growing", "brain-computer interfaces are exciting"],
        "hard_facts": ["DBS (deep brain stimulation): Medtronic, Abbott, Boston Scientific dominate — FDA approved for PD, ET, OCD, epilepsy", "TMS: FDA cleared for MDD, OCD, smoking cessation — CPT codes exist but payer coverage variable", "BCI: Synchron and Neuralink in trials — no FDA approval as of 2024", "Vagus nerve stimulation (VNS): approved for epilepsy and depression — established market"],
    },

    "diagnostic_molecular": {
        "title": "Molecular Diagnostic Regulatory Expert",
        "product_class": "molecular diagnostic — PCR, NGS, liquid biopsy, infectious disease test (510(k), De Novo, or PMA)",
        "regulatory_bodies": ["FDA CDRH Office of In Vitro Diagnostics (OHT7)", "CAP", "CLIA", "CMS"],
        "key_designations": ["510(k) (most IVDs)", "De Novo (novel with no predicate)", "PMA (high-risk, Class III)", "EUA (emergency — COVID precedent)", "Breakthrough Device"],
        "trial_frameworks": ["sensitivity/specificity vs gold standard", "positive/negative predictive value", "clinical validation study (prospective preferred)", "concordance study for NGS", "CLIA laboratory validation requirements"],
        "funding_sources": ["NCI SBIR (cancer diagnostics)", "BARDA (infectious disease)", "ARPA-H", "NIH NCI Early Detection Research Network"],
        "market_access": ["CPT code for reimbursement (MolDX for molecular tests)", "LCD (Local Coverage Determination) by MAC", "hospital lab buy vs reference lab send-out", "LDT vs IVD regulatory pathway choice"],
        "forbidden_generics": ["diagnostics enable precision medicine", "liquid biopsy is growing", "molecular testing is the future"],
        "hard_facts": ["LDT (lab-developed test): historically unregulated by FDA — FDA LDT rule 2024 changes this", "MolDX: Palmetto GBA/Noridian manage molecular diagnostic coverage — submission required", "NGS panels: Foundation Medicine (FoundationOne CDx) = gold standard for companion diagnostic", "Liquid biopsy: Guardant360, FoundationOne Liquid CDx approved — new entrant needs analytical validation vs these"],
    },

    "diagnostic_companion": {
        "title": "Companion Diagnostic Regulatory Expert",
        "product_class": "companion diagnostic (CDx) co-developed with a therapeutic (PMA)",
        "regulatory_bodies": ["FDA CDRH OHT7 + FDA CDER/CBER (co-review)", "CAP", "CLIA"],
        "key_designations": ["PMA (required for CDx)", "Breakthrough Device (if paired with BT therapy)", "Supplemental PMA (new indication for existing CDx)"],
        "trial_frameworks": ["clinical validation in pivotal drug trial samples", "analytical validation (sensitivity/specificity/reproducibility)", "co-development timeline synchronized with drug BLA/NDA", "bridging study if CDx platform changes", "retrospective vs prospective sample collection"],
        "funding_sources": ["co-development funded by pharma partner", "NCI for cancer biomarker development", "ARPA-H"],
        "market_access": ["CDx required for drug prescribing — formulary tied to drug launch", "CPT code for CDx (often tied to drug J-code timeline)", "hospital lab adoption vs reference lab (Quest, LabCorp)", "reflexive testing protocol at oncology centers"],
        "forbidden_generics": ["precision medicine requires diagnostics", "biomarkers are important"],
        "hard_facts": ["FDA requires PMA for CDx — not 510(k)", "CDx must be approved simultaneously or before drug approval", "If CDx platform changes post-approval: supplemental PMA or bridging study required", "Foundation Medicine CDx: 5 FDA-approved CDx on FoundationOne platform — dominant in oncology", "Roche Diagnostics: largest CDx partner for oncology drugs globally"],
    },

    "digital_cds": {
        "title": "Clinical Decision Support Software Regulatory Expert",
        "product_class": "clinical decision support software (CDS) — SaMD, AI/ML diagnostic aid (510(k) or De Novo)",
        "regulatory_bodies": ["FDA CDRH Digital Health Center of Excellence (DHCoE)", "ONC", "CMS", "The Joint Commission"],
        "key_designations": ["510(k) (most SaMD)", "De Novo (novel AI/ML)", "Breakthrough Device", "Non-Device CDS (if meets 21st Century Cures exemption)"],
        "trial_frameworks": ["prospective clinical validation study", "reader study (radiology AI)", "sensitivity/specificity on independent test set", "real-world performance monitoring (PCCP)", "algorithmic bias assessment required"],
        "funding_sources": ["NCI SBIR (cancer AI)", "AHRQ (clinical decision support)", "ONC grants", "ARPA-H (health AI)"],
        "market_access": ["CPT code for AI software (limited — AMA CPT process)", "payer coverage LCD for AI diagnostics (variable)", "hospital IT procurement (Epic/Cerner integration required)", "CMS MCIT pathway for breakthrough devices"],
        "forbidden_generics": ["AI is transforming healthcare", "clinical decision support improves outcomes", "machine learning can analyze data"],
        "hard_facts": ["FDA 2021 AI/ML Action Plan: predetermined change control plan (PCCP) for adaptive algorithms", "21st Century Cures Act: CDS exempt from FDA regulation if it displays basis of recommendation and clinician can independently review", "AUC-ROC is insufficient for FDA — must show clinical utility in intended use population", "Epic/Cerner integration: required for hospital adoption — API partnership critical", "CPT codes for AI: Category III codes available but Category I (reimbursed) requires AMA evidence review"],
    },

    "digital_therapeutic": {
        "title": "Digital Therapeutic Regulatory Expert",
        "product_class": "prescription digital therapeutic (PDT) — software as medical device delivering therapeutic intervention (De Novo or 510(k))",
        "regulatory_bodies": ["FDA CDRH DHCoE", "APA (behavioral health)", "ADA (diabetes)"],
        "key_designations": ["De Novo (most PDTs — novel)", "Breakthrough Device", "510(k) (if predicate exists)"],
        "trial_frameworks": ["RCT with sham control (digital placebo challenge)", "patient-reported outcomes (PRO)", "engagement metrics as secondary endpoint", "6-12 week pivotal trial (shorter than drug trials)", "FDA-qualified COA instruments required for PRO"],
        "funding_sources": ["NIMH SBIR (behavioral health DTx)", "AHRQ", "Robert Wood Johnson Foundation", "CDC (prevention DTx)"],
        "market_access": ["Pear Therapeutics bankruptcy 2023 — payer reimbursement failure warning", "CPT codes for DTx: limited, mostly Category III", "employer/payer direct contracting model emerging", "prescription required (Rx PDT) vs OTC digital wellness"],
        "forbidden_generics": ["digital therapeutics are scalable", "software can deliver CBT", "digital health improves access"],
        "hard_facts": ["Pear Therapeutics (reSET, Somryst): FDA authorized but went bankrupt 2023 due to no payer reimbursement", "No CPT Category I codes for PDTs as of 2024 — reimbursement model unresolved", "FDA De Novo required for novel PDT claims (treatment/cure/prevention)", "Sham control: digital placebo is methodologically difficult — engagement confounds outcomes", "Prescription PDT: requires prescriber relationship — limits scalability vs OTC"],
    },

    "digital_rpm": {
        "title": "Remote Patient Monitoring & Digital Health Regulatory Expert",
        "product_class": "remote patient monitoring (RPM), wearable, or connected health device (510(k) or De Novo)",
        "regulatory_bodies": ["FDA CDRH DHCoE", "CMS (reimbursement)", "ATA (telehealth)"],
        "key_designations": ["510(k) (most RPM devices)", "De Novo (novel)", "Breakthrough Device", "Non-Device (wellness exemption if no medical claims)"],
        "trial_frameworks": ["real-world evidence study", "pragmatic RCT", "clinical outcomes (hospitalization, mortality)", "usability study (FDA human factors guidance)", "cybersecurity assessment (FDA 2023 guidance required)"],
        "funding_sources": ["AHRQ ($300K-$2M)", "CMS Innovation Center (CMMI) models", "CDC chronic disease prevention grants", "NIH NIA (aging/RPM)"],
        "market_access": ["CPT 99453, 99454, 99457, 99458: RPM billing codes — $120-$150/patient/month", "CMS RPM: requires 16+ days of data/month, physician must review", "Apple Watch/Fitbit cleared features: ECG (AFib), SpO2, fall detection — competitor landscape", "Hospital at Home: CMS waiver program driving RPM adoption"],
        "forbidden_generics": ["remote monitoring improves outcomes", "wearables are growing", "patients want to be monitored at home"],
        "hard_facts": ["CMS RPM CPT codes pay ~$120-$150/patient/month — defined reimbursement model", "FDA 2023 cybersecurity guidance: mandatory for all connected devices", "Apple Watch AFib detection: cleared 510(k) — benchmark for consumer-grade cardiac monitoring", "Hospital at Home: CMS extended waiver through 2024 — $3.5B market opportunity", "16+ days of RPM data required for CMS billing — adherence is key clinical and business challenge"],
    },

    "vaccine_prophylactic": {
        "title": "Prophylactic Vaccine Regulatory Expert",
        "product_class": "prophylactic vaccine — infectious disease prevention (BLA — CBER)",
        "regulatory_bodies": ["FDA CBER Office of Vaccines Research and Review (OVRR)", "CDC ACIP", "WHO SAGE", "GAVI"],
        "key_designations": ["Breakthrough Therapy (rarely applied to vaccines)", "Fast Track", "Priority Review", "Accelerated Approval (rare — mostly full approval)", "EUA (emergency — COVID precedent)"],
        "trial_frameworks": ["vaccine efficacy (VE) against confirmed disease (primary endpoint)", "immunogenicity (antibody titer) as surrogate for accelerated approval", "Phase 3: 10,000-30,000 participants minimum", "non-inferiority for new formulations", "correlates of protection (CoP) — regulatory gold standard challenge"],
        "funding_sources": ["BARDA (up to $500M for priority pathogens)", "NIH NIAID VRC", "CEPI ($100M-$500M)", "GAVI (LMIC purchase commitment)", "Gates Foundation"],
        "market_access": ["ACIP vote required for CDC schedule inclusion (drives pediatric coverage)", "VFC program for pediatric vaccines", "adult vaccine coverage: payer-dependent", "COVAX/CEPI for global markets"],
        "forbidden_generics": ["vaccines prevent disease", "immunogenicity predicts protection", "there is unmet need for vaccines"],
        "hard_facts": ["ACIP vote drives US market: without ACIP recommendation, pediatric uptake minimal", "Correlates of protection (CoP): for most pathogens, unknown — VE trial required", "mRNA vaccine platform: validated by COVID — Moderna/Pfizer IP dominant", "RSV vaccines (Abrysvo, Arexvy) approved 2023 — first RSV vaccines after 60 years of failure", "COVID vaccine market: compressed — EUA precedent but commercial market collapsing post-pandemic"],
    },

    "vaccine_cancer_immuno": {
        "title": "Cancer Vaccine & Immunotherapy Regulatory Expert",
        "product_class": "therapeutic cancer vaccine, checkpoint inhibitor, or cancer immunotherapy (BLA — CBER or CDER)",
        "regulatory_bodies": ["FDA CBER OTAT (cell-based vaccines)", "FDA CDER Oncology (checkpoint inhibitors)", "ASCO", "SITC"],
        "key_designations": ["Breakthrough Therapy", "RMAT (cell-based)", "Accelerated Approval (ORR surrogate)", "Priority Review", "Orphan Drug"],
        "trial_frameworks": ["ORR for accelerated approval", "OS benefit for full approval", "DFS/RFS for adjuvant setting", "neoantigen identification pipeline", "TMB/MSI as predictive biomarkers", "combination with checkpoint inhibitors"],
        "funding_sources": ["NCI SBIR ($300K-$3M)", "NCI CRADA", "Stand Up To Cancer", "cancer-specific foundations"],
        "market_access": ["checkpoint inhibitor market: anti-PD-1/L1 dominates — pembrolizumab in 30+ indications", "neoantigen vaccine: mRNA-4157 (Moderna/MSD) Phase 3 — first mRNA cancer vaccine approaching approval", "combination IO: payer covers if both agents separately approved", "biomarker (TMB, MSI, PDL1) determines coverage and patient selection"],
        "forbidden_generics": ["immunotherapy is revolutionizing cancer", "the immune system can fight cancer", "personalized medicine is important"],
        "hard_facts": ["Provenge (sipuleucel-T): first approved cancer vaccine 2010 — withdrawn from market due to commercial failure", "Pembrolizumab (Keytruda): $25B/yr — any cancer IO must show benefit vs pembro or in combination", "mRNA-4157 (V940): adjuvant melanoma Phase 3 with pembrolizumab — first individualized neoantigen vaccine near approval", "MSI-H/dMMR: pembrolizumab approved tumor-agnostic — TMB-H approval withdrawn by Merck 2021", "CAR-T for solid tumors: no approval as of 2024 — antigen heterogeneity and trafficking unsolved"],
    },

    "other_microbiome": {
        "title": "Microbiome Therapeutic Regulatory Expert",
        "product_class": "microbiome-based therapeutic — FMT, live biotherapeutic product (LBP) (BLA or NDA)",
        "regulatory_bodies": ["FDA CBER (LBPs)", "FDA CDER (small molecule microbiome modulators)", "FDA CDRH (microbiome diagnostics)"],
        "key_designations": ["Breakthrough Therapy", "Fast Track", "Orphan Drug (for rare microbiome conditions)", "RMAT (if cell-based)"],
        "trial_frameworks": ["recurrence endpoint (C. diff)", "remission rate (IBD)", "microbiome engraftment as biomarker", "placebo: autologous FMT or capsule without bacteria", "open-label challenge in C. diff (placebo problematic)"],
        "funding_sources": ["NIDDK SBIR", "NIAID (infectious microbiome)", "Helmsley (IBD microbiome)", "Gates Foundation (global gut health)"],
        "market_access": ["Vowst (SER-109): first oral LBP approved 2023 for C. diff — $17,500/course", "Rebyota (RBX2660): FMT-derived, rectal, approved 2022 — $3,000-$8,000/course", "payer coverage for C. diff: favorable given recurrence cost", "hospital pharmacy: LBPs require cold chain and special handling"],
        "forbidden_generics": ["the microbiome is important", "gut health affects everything", "FMT is promising"],
        "hard_facts": ["Vowst (SER-109): first oral microbiome drug approved — oral spores, 4 capsules/day × 3 days", "Rebyota: rectal FMT product — first FDA-approved FMT product (2022)", "LBP regulatory pathway: BLA under 21 CFR 600 — NOT drug NDA", "C. diff recurrence rate: 25-30% after first episode, 40-60% after second — strong unmet need", "Fecal transplant: unregulated stool banks remain competitive threat to approved LBPs"],
    },

    "other_crispr": {
        "title": "CRISPR & Gene Editing Regulatory Expert",
        "product_class": "CRISPR-based gene editing therapeutic — ex vivo or in vivo (BLA — CBER)",
        "regulatory_bodies": ["FDA CBER OTAT", "NIH RAC (recombinant DNA advisory)", "ASGCT", "EMA CAT"],
        "key_designations": ["Breakthrough Therapy", "RMAT", "Orphan Drug", "Rare Pediatric Disease PRV"],
        "trial_frameworks": ["ex vivo: cell editing + infusion (sickle cell, thalassemia model)", "in vivo: direct delivery (liver-targeting LNP — NTLA-2001 precedent)", "off-target editing assessment (GUIDE-seq, rhAmpSeq)", "long-term follow-up 15yr required", "myeloablative conditioning for ex vivo"],
        "funding_sources": ["NHLBI", "NCATS", "disease foundations", "ARPA-H (in vivo editing)", "Wellcome Trust"],
        "market_access": ["Casgevy (exa-cel): $2.2M — first CRISPR therapy approved (FDA Dec 2023)", "ex vivo: authorized treatment center model (bone marrow transplant centers)", "in vivo: broader access potential if LNP delivery validated", "insurance: outcomes-based payment models being negotiated"],
        "forbidden_generics": ["CRISPR can cure genetic disease", "gene editing is precise", "the technology is proven"],
        "hard_facts": ["Casgevy (exa-cel, Vertex/CRISPR Tx): approved Dec 2023 for SCD and TDT — first CRISPR therapy", "Off-target editing: FDA expects comprehensive off-target analysis (GUIDE-seq minimum)", "In vivo CRISPR: Intellia NTLA-2001 (TTR amyloidosis) in Phase 3 — first in vivo CRISPR in pivotal trial", "Myeloablative conditioning: required for ex vivo CRISPR — significant toxicity burden", "RMAT designation: expedites CBER review — apply early for CRISPR therapeutics"],
    },

    "other_delivery": {
        "title": "Drug Delivery Platform Regulatory Expert",
        "product_class": "novel drug delivery platform — LNP, nanoparticle, implant, transdermal, inhaled (505(b)(2) NDA or BLA)",
        "regulatory_bodies": ["FDA CDER Office of Pharmaceutical Quality (OPQ)", "FDA CDER (505(b)(2))", "FDA CBER (LNP for biologics)"],
        "key_designations": ["505(b)(2) (relies on existing drug data)", "Orphan Drug (rare disease delivery)", "Breakthrough Therapy", "Fast Track"],
        "trial_frameworks": ["bioequivalence for reformulations", "pharmacokinetic bridging study", "CMC: particle size, encapsulation efficiency, stability", "LNP: ionizable lipid composition, pKa, PEGylation", "inhaled: FPD, MMAD, cascade impaction testing"],
        "funding_sources": ["NIH NCI (cancer nanoparticle)", "DARPA (delivery platforms)", "BARDA (pandemic platform)"],
        "market_access": ["505(b)(2) advantage: reduced clinical data required if referencing approved drug", "LNP IP: Alnylam-Moderna settlement — licensing landscape complex", "inhaled: dry powder vs nebulizer vs MDI — payer and patient preference differs", "implant: procedure cost adds to COGS — payer values convenience premium"],
        "forbidden_generics": ["delivery improves drug performance", "nanoparticles enhance bioavailability", "LNPs are validated by COVID vaccines"],
        "hard_facts": ["505(b)(2): can reference approved drug's safety/efficacy — reduces Phase 2/3 burden", "LNP composition: ionizable lipid + DSPC + cholesterol + PEG-lipid — Alnylam/Moderna hold key patents", "Doxil (PEGylated liposomal doxorubicin): 505(b)(2) precedent — reduced cardiotoxicity vs free drug", "Inhaled insulin (Afrezza): approved but commercial failure — patient/physician acceptance challenge", "Implantable drug delivery: Brixia (buprenorphine implant) model — 6-month dosing, high adherence"],
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMIC PROMPT GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

async def generate_expert_system_prompt(
    sub_expert_id: str,
    disease_name: str,
    idea: str,
) -> str:
    """
    Generate a prescriptive, disease-specific system prompt for a sub-expert.
    Falls back to a generic domain prompt if generation fails.
    """
    profile = DOMAIN_PROFILES.get(sub_expert_id)
    if not profile:
        return _fallback_prompt(sub_expert_id, disease_name)

    prompt = f"""You are building a system prompt for an AI expert called "{profile['title']}".

The PI's specific disease/condition is: {disease_name}
The PI's idea: {idea[:300]}

Using the domain profile below, write a PRESCRIPTIVE system prompt that:
1. Opens with: "You are the {profile['title']} for Project Elevate."
2. States a MANDATORY ANALYTICAL FRAMEWORK with 4-6 specific sections the AI MUST address
3. For each section, gives disease-specific instructions using exact numbers, named products, and sources
4. Lists FORBIDDEN GENERIC STATEMENTS (vague phrases that must never appear)
5. States OUTPUT REQUIREMENTS (every number needs a source tag)

Be maximally specific to "{disease_name}" — not generic to the domain.
Use these domain facts:
- Product class: {profile['product_class']}
- Regulatory bodies: {', '.join(profile['regulatory_bodies'])}
- Key designations: {', '.join(profile['key_designations'])}
- Trial frameworks: {', '.join(profile['trial_frameworks'])}
- Funding sources: {', '.join(profile['funding_sources'])}
- Market access factors: {', '.join(profile['market_access'])}
- Hard facts to enforce: {', '.join(profile['hard_facts'])}
- Forbidden generic phrases: {', '.join(profile['forbidden_generics'])}

Write ONLY the system prompt text. No preamble. No explanation. Start with "You are the {profile['title']}".
Keep it under 800 words. Be directive and specific."""

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": HAIKU_MODEL,
                    "max_tokens": 1000,
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
            data = r.json()
            generated = data["content"][0]["text"].strip()
            logger.info(f"✅ Dynamic prompt generated for {sub_expert_id} / {disease_name}")
            return generated
    except Exception as e:
        logger.warning(f"Dynamic prompt generation failed for {sub_expert_id}: {e}")
        return _fallback_prompt(sub_expert_id, disease_name)


def _fallback_prompt(sub_expert_id: str, disease_name: str) -> str:
    """Simple fallback if Haiku call fails."""
    return f"""You are a regulatory and commercial expert for {sub_expert_id.replace('_', ' ').title()} products.
You are analyzing: {disease_name}.
Be specific. Name exact competitors, exact regulatory pathways, exact funding sources with dollar amounts.
Never use vague language. Every claim needs a source. Identify gaps in the current treatment landscape."""
