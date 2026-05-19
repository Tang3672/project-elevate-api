"""
Strategy Database
==================
Deep industry strategies for FDA approval acceleration, IP protection,
funding optimization, and commercial launch — with real named examples.

These strategies require deep industry knowledge and cannot be found
through simple Google searches or generic AI prompts.

Organized by:
1. Universal strategies (apply to all domains)
2. Domain-specific strategies
"""

# ── UNIVERSAL STRATEGIES (all product types) ──────────────────────────────────

UNIVERSAL_STRATEGIES = [
    {
        "category": "Regulatory Acceleration",
        "strategy": "Stack all applicable FDA expedited designations simultaneously at Phase 1 completion",
        "detail": "Most companies apply for one designation at a time. The optimal approach is to apply for BTD, Fast Track, Orphan Drug, and Priority Review simultaneously if eligible. Each has independent eligibility criteria and independent benefits that compound. The filing cost is low (~$50K legal fees) relative to the 12-18 month timeline savings.",
        "example_company": "Vertex Pharmaceuticals",
        "example_drug": "Ivacaftor (Kalydeco) for cystic fibrosis",
        "what_they_did": "Vertex obtained Breakthrough Therapy + Fast Track + Priority Review + Orphan Drug simultaneously for ivacaftor. FDA approved in 4 months after NDA submission vs standard 10 months. First CF drug to target underlying cause rather than symptoms.",
        "how_to_apply": "At Phase 1 data readout, assess eligibility for all 4 designations simultaneously. File within 30 days of each other. Total incremental cost ~$200K; potential timeline savings 12-24 months.",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/22083580/",
        "applicability": "Any drug with serious/life-threatening indication and preliminary evidence of substantial improvement over available therapy."
    },
    {
        "category": "Regulatory Acceleration",
        "strategy": "Pediatric exclusivity extension adds 6 months to all existing exclusivity — often worth $500M-2B in additional revenue",
        "detail": "The Best Pharmaceuticals for Children Act (BPCA) grants 6 months of additional exclusivity for conducting FDA-requested pediatric studies, regardless of whether the studies show efficacy in children. This 6-month extension applies to ALL existing exclusivities (NCE, Orphan, patent-based) simultaneously, dramatically amplifying its value.",
        "example_company": "AbbVie",
        "example_drug": "Humira (adalimumab)",
        "what_they_did": "AbbVie conducted pediatric studies for Humira as required by FDA Written Request. Received 6-month pediatric exclusivity extension on top of existing patent protection. At $20B/year revenue, each month of additional exclusivity was worth ~$1.7B.",
        "how_to_apply": "Request FDA Written Request (WR) for pediatric studies at NDA submission. Even if pediatric indication is not your target market, the exclusivity extension applies to adult indications. Budget $5-15M for pediatric PK and safety studies.",
        "source_url": "https://www.fda.gov/drugs/development-resources/pediatric-drug-development",
        "applicability": "Any drug that may have pediatric use. FDA issues Written Requests for ~100 drugs/year. Exclusivity extension value scales with adult market size."
    },
    {
        "category": "Regulatory Acceleration",
        "strategy": "Type B pre-NDA meeting 12 months before submission locks in FDA agreement on CMC, clinical, and labeling — preventing 50% of Complete Response Letters",
        "detail": "50% of Complete Response Letters (CRLs) cite issues that were never discussed with FDA pre-submission. A Type B pre-NDA meeting held 12 months before NDA submission locks in FDA agreement on: data package sufficiency, proposed labeling language, CMC specifications, and risk management. This single meeting reduces CRL probability by approximately half.",
        "example_company": "Gilead Sciences",
        "example_drug": "Remdesivir (Veklury)",
        "what_they_did": "Gilead held multiple Type A and B meetings with FDA during COVID development, pre-aligning on endpoints and data package. First IV antiviral for COVID approved via EUA in 10 weeks from first data, then traditional approval in 6 months from NDA submission — no CRL.",
        "how_to_apply": "Request Type B pre-NDA meeting at least 15 months before planned NDA submission. Submit detailed meeting package including proposed labeling, clinical summary, CMC overview. FDA must respond within 30 days and hold meeting within 90 days.",
        "source_url": "https://www.fda.gov/drugs/guidance-documents-regulatory-information/formal-meetings-between-fda-and-sponsors-or-applicants-pdufa-products",
        "applicability": "All NDA/BLA submissions. Particularly critical for novel mechanisms, first-in-class drugs, and products with complex manufacturing."
    },
    {
        "category": "IP and Exclusivity",
        "strategy": "505(b)(2) NDA pathway allows reliance on existing safety/efficacy data — cuts development cost by 40-60% for reformulations and new indications",
        "detail": "505(b)(2) allows an NDA to rely on published literature or FDA's findings for a previously approved drug, without requiring the applicant to obtain a right of reference from the original data. This is the optimal pathway for: new formulations, new routes of administration, new dosage strengths, new combinations, and new indications of approved drugs.",
        "example_company": "Jazz Pharmaceuticals",
        "example_drug": "Xyrem (sodium oxybate) to Lumryz (extended-release oxybate)",
        "what_they_did": "Jazz developed Lumryz as a once-nightly formulation of twice-nightly Xyrem using 505(b)(2), relying on existing safety database. Avoided full Phase 3 PK/safety program. Approved 2023 with new 7-year Orphan exclusivity, resetting the exclusivity clock despite same active ingredient.",
        "how_to_apply": "If your drug is a derivative of an approved product, map to 505(b)(2) before initiating Phase 3. Identify which existing safety/efficacy data you can rely on. Submit Paragraph IV certification if existing patents block. Budget 30-40% less than 505(b)(1) development.",
        "source_url": "https://www.fda.gov/drugs/types-applications/505b2-applications",
        "applicability": "New formulations, combinations, routes of administration, or indications of approved drugs. Also for drugs with significant published literature base."
    },
    {
        "category": "Funding Optimization",
        "strategy": "Rare Pediatric Disease Priority Review Voucher (PRV) worth $100-200M — can be sold to large pharma at NDA approval",
        "detail": "FDA awards a Priority Review Voucher upon approval of a drug for a rare pediatric disease. This voucher can be sold to any company for use on any future NDA/BLA submission, guaranteeing 6-month Priority Review vs standard 10-month. PRVs have sold for $67M to $350M. This creates a significant non-dilutive windfall at approval.",
        "example_company": "BioMarin Pharmaceutical",
        "example_drug": "Brineura (cerliponase alfa) for CLN2 disease",
        "what_they_did": "BioMarin received Rare Pediatric Disease PRV upon Brineura approval in 2017. Sold the PRV to AbbVie for $125M. This single PRV sale covered a significant portion of the drug's development cost, making the program economically viable despite the tiny patient population.",
        "how_to_apply": "Apply for Rare Pediatric Disease designation if patient population <200,000 U.S. patients under 18. Designation is free. PRV is awarded automatically at approval. Engage investment bankers to run a competitive PRV sale process simultaneously with NDA approval — typical sale closes within 90 days of approval.",
        "source_url": "https://www.fda.gov/industry/developing-products-rare-diseases-conditions/rare-pediatric-disease-priority-review-vouchers",
        "applicability": "Any drug for rare disease with substantial pediatric patient population. PRV value is highest when large pharma has multiple large NDAs in pipeline."
    },
    {
        "category": "Clinical Trial Design",
        "strategy": "Seamless adaptive Phase 2/3 design eliminates the 6-18 month gap between Phase 2 and Phase 3 — saves 12-18 months and 20-30% of trial cost",
        "detail": "Traditional drug development has a 6-18 month gap between Phase 2 completion and Phase 3 initiation (analysis, design, protocol finalization, site activation). A pre-specified seamless adaptive design allows Phase 2 patients to roll directly into Phase 3 if interim analysis confirms dose selection, with the Phase 2 data contributing to the Phase 3 dataset.",
        "example_company": "Moderna",
        "example_drug": "mRNA-1273 COVID-19 vaccine",
        "what_they_did": "Moderna used seamless Phase 2/3 adaptive design for mRNA-1273. Phase 2 ran for 28 days then transitioned directly to Phase 3 enrollment, with Phase 2 patients folded into Phase 3 dataset. Total development time from IND to EUA: 11 months. Traditional approach would have taken 3-4 years.",
        "how_to_apply": "Design the seamless adaptive trial at Phase 1 completion. Pre-specify the interim analysis decision rules and Phase 3 transition criteria in the protocol. Discuss with FDA at End-of-Phase-1 meeting — FDA has published guidance on adaptive designs. Critical: pre-specify everything to avoid Type I error inflation.",
        "source_url": "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/adaptive-designs-clinical-trials-drugs-and-biologics",
        "applicability": "Any indication where Phase 2 and Phase 3 use similar endpoints and patient populations. Most valuable in rare diseases (limited patient pool) and urgent unmet needs."
    },
    {
        "category": "Clinical Trial Design",
        "strategy": "Biomarker enrichment using companion diagnostic cuts Phase 3 sample size by 60-80% and dramatically improves success probability",
        "detail": "Unselected Phase 3 trials for targeted therapies fail because the drug works in a subpopulation but the signal is diluted by non-responders. Biomarker enrichment using a prospectively validated companion diagnostic allows you to enrich for responders, cutting sample size from 1,000+ to 200-400 patients while improving ORR from 10-15% to 40-70%.",
        "example_company": "Pfizer",
        "example_drug": "Crizotinib (Xalkori) with Vysis ALK FISH CDx",
        "what_they_did": "Pfizer identified ALK rearrangement biomarker in Phase 1, immediately partnered with Abbott for ALK FISH CDx, and ran enriched Phase 1/2 with 82 ALK+ patients showing 57% ORR. FDA granted accelerated approval based on this single-arm 82-patient trial in 2011 — 5 years faster than standard unselected trial.",
        "how_to_apply": "Identify predictive biomarker in Phase 1 pharmacodynamic studies. Lock companion diagnostic assay before Phase 2 enrollment begins. Co-develop CDx with LabCorp, Foundation Medicine, or Guardant. Submit CDx PMA simultaneously with drug NDA.",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/20979469/",
        "applicability": "Any targeted therapy where mechanism of action suggests a molecular subset will respond. Oncology, rare genetic diseases, autoimmune diseases with defined molecular subtypes."
    },
    {
        "category": "Regulatory Acceleration",
        "strategy": "Japanese PMDA Sakigake designation + parallel FDA/EMA review cuts global approval timeline by 2-3 years for diseases with high unmet need in Japan",
        "detail": "Japan's Sakigake designation (equivalent to FDA Breakthrough) provides rolling review, priority consultation, and 6-month review target. Running PMDA review in parallel with FDA review — using the same clinical data package — achieves 3-market approval (US, EU, Japan) within 12-18 months of each other rather than the traditional sequential 5-7 year international rollout.",
        "example_company": "Biogen",
        "example_drug": "Nusinersen (Spinraza) for SMA",
        "what_they_did": "Biogen received PMDA Sakigake designation for nusinersen. FDA approved December 2016; PMDA approved July 2017 — only 7 months later, vs typical 3-5 year Japan lag. This approach captured Japanese premium pricing ($750,000/year) without the traditional delay.",
        "how_to_apply": "Apply for PMDA Sakigake at Phase 2 initiation. Request PMDA consultation meetings to align on clinical package design. Run FDA and PMDA regulatory submissions in parallel — same clinical data, translated label. Japan pricing is typically 30-50% below US but still premium.",
        "source_url": "https://www.pmda.go.jp/english/review-services/reviews/0001.html",
        "applicability": "Serious/life-threatening diseases with high unmet need in Japan. Japanese market is 3rd largest pharma market globally. Particularly valuable for rare diseases, oncology, and CNS."
    },
    {
        "category": "Funding Optimization",
        "strategy": "NIH CRADA (Cooperative Research and Development Agreement) provides free NIH lab resources, expertise, and co-development funding in exchange for licensing rights",
        "detail": "A CRADA with NIH gives a company access to NIH intramural scientists, laboratory facilities, reagents, and patient cohorts at no cost. In exchange, the company licenses the resulting IP with royalty obligations. CRADAs have funded Phase 1/2 trials that would have cost $10-30M privately — essentially zero-cost clinical development in exchange for downstream royalties.",
        "example_company": "MedImmune (now AstraZeneca)",
        "example_drug": "Palivizumab (Synagis) for RSV",
        "what_they_did": "MedImmune entered CRADA with NIH NIAID to co-develop palivizumab. NIH provided the monoclonal antibody research platform and clinical trial infrastructure. MedImmune funded manufacturing. Approved 1998; peak sales $1.5B/year. NIH received royalties covering a significant portion of its investment.",
        "how_to_apply": "Identify NIH institute with overlapping research interest (NIAID for infectious disease, NCI for cancer, NHLBI for cardiac). Submit CRADA proposal to NIH Office of Technology Transfer. Negotiate IP terms — typically company gets exclusive license with royalty cap. Timeline to execute CRADA: 6-12 months.",
        "source_url": "https://www.ott.nih.gov/crada",
        "applicability": "Early-stage companies with promising preclinical data in areas of NIH research interest. Most valuable for companies lacking Phase 1 clinical infrastructure."
    },
    {
        "category": "IP and Exclusivity",
        "strategy": "New Chemical Entity (NCE) exclusivity can be combined with Orphan Drug exclusivity for maximum protection — up to 12 years total for rare disease biologics",
        "detail": "NCE exclusivity (5 years for small molecules, 12 years for biologics) and Orphan Drug exclusivity (7 years) run concurrently for the first 5 years of NCE exclusivity, but Orphan exclusivity provides an independent block. For a biologic orphan drug: 12-year reference product exclusivity + 7-year Orphan exclusivity = the later of the two applies, providing maximum protection. Understanding the interaction is critical for IP strategy.",
        "example_company": "Sarepta Therapeutics",
        "example_drug": "Eteplirsen (Exondys 51) for DMD",
        "what_they_did": "Sarepta received Accelerated Approval + Orphan Drug + NCE exclusivity. Stacked IP portfolio with composition-of-matter patents, method of treatment patents, and formulation patents. Combined exclusivity and patent protection extended commercial runway to 2034+.",
        "how_to_apply": "Conduct comprehensive IP landscape analysis at IND submission. File composition-of-matter, formulation, method of treatment, and metabolite patents simultaneously. Apply for Orphan designation if <200K patients. For biologics, 12-year reference product exclusivity is automatic — layer Orphan on top.",
        "source_url": "https://www.fda.gov/industry/developing-products-rare-diseases-conditions/designating-orphan-product-drugs-and-biological-products",
        "applicability": "Any drug with potential rare disease indication. Filing for Orphan designation early (even pre-IND) costs only ~$5K and preserves the option for 7-year Orphan exclusivity."
    },
]

# ── DOMAIN-SPECIFIC STRATEGIES ────────────────────────────────────────────────

DOMAIN_SPECIFIC_STRATEGIES = {
    "drug_amr": [
        {
            "category": "AMR-Specific",
            "strategy": "Antibiotic-BLI combination packaging to create new patentable entity from off-patent backbone",
            "detail": "Pair a novel beta-lactamase inhibitor with an off-patent beta-lactam. The combination is a new patentable entity with independent IP, QIDP designation, and full NCE exclusivity. The off-patent backbone provides safety data via 505(b)(2), cutting development cost 30-40%.",
            "example_company": "AstraZeneca / Pfizer",
            "example_drug": "Ceftazidime-avibactam (Avycaz)",
            "what_they_did": "AZ licensed avibactam from Novexel and combined with off-patent ceftazidime. New patentable combination with QIDP. AZ sold US rights to Pfizer for $1.6B in 2016.",
            "how_to_apply": "If developing a BLI, identify which off-patent beta-lactams best complement your inhibitor spectrum. The combination becomes a new patentable entity with independent IP.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/26063370/",
        },
        {
            "category": "AMR-Specific",
            "strategy": "LPAD approval for resistant pathogen niche first, then label expansion via sNDA",
            "detail": "LPAD (Limited Population Pathway for Antibacterial and Antifungal Drugs) allows approval based on 300-400 patient Phase 3 vs standard 600-900, with a narrower label. Approve in the niche first (e.g., NDM-only CRE), build real-world evidence, then file supplemental NDA for broader gram-negative indication.",
            "example_company": "Pfizer / AstraZeneca",
            "example_drug": "Aztreonam-avibactam (Emblaveo)",
            "what_they_did": "Targeted MBL-producing organisms specifically — the one resistance mechanism no approved drug covers. FDA approved 2024 for cUTI/cIAI. Plan to expand to HABP/VABP via sNDA.",
            "how_to_apply": "Identify which resistance mechanism your drug uniquely covers. File LPAD for that niche. Broader expansion follows with real-world evidence from narrow indication.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/36223745/",
        },
        {
            "category": "AMR-Specific",
            "strategy": "BARDA OTA contract before Phase 3 to fund development without equity dilution",
            "detail": "BARDA Other Transaction Authority (OTA) contracts move faster than FAR-based grants and can include procurement guarantees. Securing $50-500M BARDA contract before Phase 3 funds the most expensive development stage without dilution, then raise equity post-BARDA for commercialization at a much higher valuation.",
            "example_company": "Paratek Pharmaceuticals",
            "example_drug": "Omadacycline (Nuzyra)",
            "what_they_did": "Paratek received $216M BARDA contract funding both Phase 3 trials before raising equity. Approved 2018. BARDA funding preserved equity for commercialization phase.",
            "how_to_apply": "Submit BARDA TechWatch pre-application 12 months before Phase 3 start. Frame antibiotic as national security asset if targeting CDC Urgent Threat pathogen. BARDA contract negotiation takes 6-12 months.",
            "source_url": "https://medicalcountermeasures.gov/barda/cbrn/broad-spectrum-antimicrobials/",
        },
        {
            "category": "AMR-Specific",
            "strategy": "PASTEUR Act subscription model pitch to hedge commercialization risk — position for government pull incentive",
            "detail": "The PASTEUR Act (proposed legislation) would create $11.5B in subscription-based pull incentives for novel antibiotics meeting medical need — paying $750M-$3B per antibiotic regardless of sales volume. While not yet law, positioning your antibiotic development as PASTEUR-eligible changes the investor return profile dramatically.",
            "example_company": "Entasis Therapeutics",
            "example_drug": "Sulbactam-durlobactam (Xacduro) for Acinetobacter",
            "what_they_did": "Entasis developed first-in-class Acinetobacter antibiotic — a pathogen with virtually no commercial market but enormous public health need. FDA approved 2023. Entasis positioned for government procurement contracts and PASTEUR-type mechanisms. Acquired by Innoviva for $270M.",
            "how_to_apply": "Track PASTEUR Act legislation. If targeting Acinetobacter, CRE, or other CDC Urgent Threats with no approved therapy, structure development to meet PASTEUR eligibility criteria. Engage IDSA and BARDA policy teams to participate in PASTEUR advocacy.",
            "source_url": "https://www.idsociety.org/public-outreach/antimicrobial-resistance/pasteur-act/",
        },
    ],
    "drug_oncology": [
        {
            "category": "Oncology-Specific",
            "strategy": "Tumor-agnostic approval via basket trial — one biomarker, all cancers simultaneously",
            "detail": "Instead of indication-by-indication approvals (each requiring separate Phase 3), run a basket trial enrolling all tumor types with a shared biomarker. FDA has now approved multiple tumor-agnostic therapies. One approval covers all cancers with the biomarker — dramatically expanding addressable market vs sequential indication approvals.",
            "example_company": "Merck",
            "example_drug": "Pembrolizumab (Keytruda) MSI-H/dMMR tumor-agnostic",
            "what_they_did": "KEYNOTE-158 basket trial enrolled 10+ tumor types in MSI-H patients. FDA granted first tumor-agnostic approval 2017. Now covers 40+ indications from one biomarker. Strategy opened entire oncology market simultaneously.",
            "how_to_apply": "If your drug has a pan-tumor biomarker, design basket trial at Phase 2. Include 6-10 tumor types. Pre-specify primary analysis by biomarker status, not tumor type. Engage FDA Oncology Center of Excellence for basket trial design guidance.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/28967792/",
        },
        {
            "category": "Oncology-Specific",
            "strategy": "Adjuvant indication expansion after metastatic approval — 5-10x patient population increase",
            "detail": "Phase 3 in metastatic/advanced setting is faster and smaller (higher event rate, shorter follow-up). Get initial approval in metastatic setting, then run adjuvant trial in earlier-stage disease. Adjuvant market is 5-10x larger by patient volume. This sequential strategy is lower risk than launching in adjuvant first.",
            "example_company": "AstraZeneca",
            "example_drug": "Olaparib (Lynparza)",
            "what_they_did": "Got Lynparza approved in metastatic BRCA+ ovarian (2014), then expanded to adjuvant breast (OlympiA trial, 2021). Annual revenue went from $500M to $2.7B post-adjuvant approval. Patient population expanded 5x.",
            "how_to_apply": "Design Phase 3 in metastatic setting first. Power for OS or PFS. Simultaneously initiate adjuvant trial at Phase 2 completion. Use metastatic approval to fund adjuvant trial. Adjuvant trial uses EFS as primary endpoint.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/34081848/",
        },
        {
            "category": "Oncology-Specific",
            "strategy": "Project Optimus dose optimization in Phase 1 — FDA now requires it and it reduces Phase 3 failure rate",
            "detail": "FDA's 2022 Project Optimus initiative requires oncology Phase 1 to optimize dose for efficacy AND tolerability, not just find MTD. Companies that proactively design dose optimization into Phase 1 now have an advantage: they identify the dose that maximizes efficacy:toxicity ratio, which reduces Phase 3 attrition from dose-related toxicity failures.",
            "example_company": "Blueprint Medicines",
            "example_drug": "Avapritinib (Ayvakit) for GIST",
            "what_they_did": "Blueprint ran extensive dose-optimization Phase 1, identifying 300mg QD as optimal for PDGFRa D842V GIST vs the MTD of 400mg. Phase 3 NAVIGATOR trial showed 88% ORR. FDA approved 2020. Dose optimization was critical — higher dose would have had prohibitive toxicity.",
            "how_to_apply": "Design Phase 1 with dose-expansion cohorts at multiple dose levels below MTD. Use PK/PD modeling to identify optimal dose. Pre-specify dose optimization as Phase 1 objective in protocol. FDA will expect dose-response data for any oncology IND submitted after 2022.",
            "source_url": "https://www.fda.gov/drugs/guidance-documents-regulatory-information/optimizing-dosage-oncology-drugs",
        },
    ],
    "biologic_oncology": [
        {
            "category": "Biologic Oncology",
            "strategy": "ADC payload licensing + existing antibody combination — faster than de novo ADC development",
            "detail": "Building a validated payload/linker from scratch takes 3-5 years and $50-100M. Licensing a proven payload platform (DXd from Daiichi Sankyo, MMAE from Seagen, DM1 from ImmunoGen) and attaching to your antibody target cuts ADC development to 18-24 months. Differentiation is in target antigen selection and indication, not payload chemistry.",
            "example_company": "AstraZeneca / Daiichi Sankyo",
            "example_drug": "Trastuzumab deruxtecan (Enhertu)",
            "what_they_did": "AZ paid $6.9B for global rights to Daiichi's DXd ADC platform. Combined with trastuzumab (existing HER2 antibody). ORR 70%+ in HER2+ breast. Platform extended to 6+ additional ADCs in pipeline.",
            "how_to_apply": "License proven payload/linker platform. Focus R&D on antibody target selection and indication. DXd platform available via AZ/Daiichi collaboration; MMAE via Seagen/Pfizer collaboration; proprietary platforms via royalty-bearing licenses.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/31189866/",
        },
        {
            "category": "Biologic Oncology",
            "strategy": "Biosimilar reference product strategy — 12-year exclusivity cliff creates 5-year commercial window with defined endpoint",
            "detail": "Understanding the reference product exclusivity cliff is critical for commercial planning. Keytruda biosimilars launch 2028. Herceptin biosimilars launched 2019 causing 60% price erosion in 2 years. Planning commercial strategy around the exclusivity cliff — including outcomes-based contracts, combination therapy positioning, and line-of-therapy expansion — is essential.",
            "example_company": "Roche / Genentech",
            "example_drug": "Trastuzumab (Herceptin) biosimilar defense",
            "what_they_did": "Roche launched Kadcyla (T-DM1 ADC) and Perjeta (pertuzumab combination) before trastuzumab exclusivity cliff, moving patients to combination regimens with independent IP. Also launched SC formulation with independent patent. Biosimilar impact was mitigated by portfolio strategy.",
            "how_to_apply": "Map reference product exclusivity timeline at market entry. Launch combination therapies and new formulations 3-5 years before biosimilar entry. Use outcomes-based contracts to lock payer formulary position before biosimilar launch.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/32572946/",
        },
    ],
    "gene_therapy_rare": [
        {
            "category": "Gene Therapy",
            "strategy": "One-time curative pricing with outcomes-based installment contract to overcome payer resistance",
            "detail": "Payers resist $2-3M one-time payments due to budget impact and uncertainty about durability. Outcomes-based contracts paying over 3-5 years tied to clinical outcomes (patient stays ambulatory, gene expression persists) solve both problems. Novartis pioneered this for Zolgensma with Medicaid. Required building entirely new payment infrastructure but unlocked coverage in 6 months.",
            "example_company": "AveXis / Novartis",
            "example_drug": "Onasemnogene abeparvovec (Zolgensma)",
            "what_they_did": "Novartis offered 5-year annuity payment model to Medicaid ($425K/year) tied to outcomes. Also offered outcomes-based rebate (refund if patient doesn't meet motor milestone at 30 months). Medicare/Medicaid coverage secured within 6 months despite $2.125M list price.",
            "how_to_apply": "Engage ICER 18 months pre-approval for value-based pricing analysis. Build outcomes tracking infrastructure before launch — need to monitor patients for 5+ years. Negotiate OBC terms with top 5 PBMs and state Medicaid programs simultaneously with NDA review.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/31399232/",
        },
        {
            "category": "Gene Therapy",
            "strategy": "Natural history study as external control to reduce trial size 50-70% in rare diseases",
            "detail": "FDA accepts single-arm trials with historical controls for rare diseases where randomization is unethical or impractical. A prospectively designed natural history study (conducted in parallel with preclinical/Phase 1) becomes the external control arm, cutting Phase 3 size from 100+ to 30-50 patients while preserving statistical validity.",
            "example_company": "Spark Therapeutics",
            "example_drug": "Voretigene neparvovec (Luxturna)",
            "what_they_did": "Spark ran 21-patient randomized trial (delayed treatment design, not placebo). FDA accepted because natural history of RPE65-LCA was well-characterized and blinding was impossible. Approved 2017 on 21-patient trial — one of smallest pivotal trials in FDA history.",
            "how_to_apply": "Establish natural history database as early as Phase 1. Partner with patient registries (NORD, disease foundations, NIH Rare Diseases Clinical Research Network) to collect pre-treatment outcome data. Pre-specify external control methodology in Phase 3 protocol and discuss with FDA at End-of-Phase-2 meeting.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/28873341/",
        },
        {
            "category": "Gene Therapy",
            "strategy": "RMAT designation + rolling BLA review can cut approval timeline by 18-24 months",
            "detail": "RMAT (Regenerative Medicine Advanced Therapy) designation provides rolling BLA review — submit and have FDA review each module as completed rather than waiting for complete package. Combined with early frequent FDA interactions, RMAT reduces total review time from 12 months to 6 months and provides organizational commitment from FDA senior staff.",
            "example_company": "bluebird bio",
            "example_drug": "Betibeglogene (Zynteglo) for beta-thalassemia",
            "what_they_did": "bluebird obtained RMAT designation for Zynteglo. Rolling review allowed parallel submission and review of CMC, clinical, and nonclinical modules. FDA approval 2022. Without RMAT, timeline would have been 18-24 months longer.",
            "how_to_apply": "Apply for RMAT designation as soon as preliminary clinical evidence shows potential for serious condition. Costs only a cover letter and $0 fee. FDA responds within 60 days. Begin rolling submission with CMC module immediately after designation.",
            "source_url": "https://www.fda.gov/vaccines-blood-biologics/cellular-gene-therapy-products/regenerative-medicine-advanced-therapy-designation",
        },
    ],
    "device_cardiovascular": [
        {
            "category": "Device Strategy",
            "strategy": "De Novo pathway creates new product code enabling your company to be the predicate for all future competitors — first-mover IP advantage",
            "detail": "If your device has no predicate (novel Class II), De Novo authorization creates a new product code. You become the predicate for all future 510(k) submissions in your category — competitors must compare to your device, not an older reference. This gives permanent technological leadership as long as your device sets the standard.",
            "example_company": "iRhythm Technologies",
            "example_drug": "Zio XT patch (extended wear cardiac monitor)",
            "what_they_did": "iRhythm sought De Novo for long-wear single-use cardiac monitor. FDA created new product code. All subsequent long-wear patch monitors must use Zio XT or similar as predicate. iRhythm established market leadership as category definer.",
            "how_to_apply": "If no 510(k) predicate exists, consider De Novo vs PMA. De Novo (12-18 months) creates new product code giving first-mover predicate advantage. PMA (2-4 years) provides higher regulatory barrier but no predicate benefit. De Novo is optimal for novel Class II devices.",
            "source_url": "https://www.fda.gov/medical-devices/premarket-submissions-selecting-and-preparing-correct-submission/de-novo-classification-request",
        },
        {
            "category": "Device Strategy",
            "strategy": "Real-world evidence from registry to support label expansion without additional IDE trial",
            "detail": "FDA increasingly accepts real-world evidence (RWE) from post-market registries to support label expansions, new indications, and changes to contraindications. Building a prospective registry at launch with pre-specified endpoints can generate RWE for label expansion in 2-3 years vs 4-6 years for a new IDE trial.",
            "example_company": "Edwards Lifesciences",
            "example_drug": "SAPIEN 3 TAVR — intermediate risk expansion",
            "what_they_did": "Edwards built TVT Registry capturing real-world TAVR outcomes across 700+ US centers. Used registry data to support SAPIEN 3 label expansion from high-risk to intermediate-risk patients, avoiding full randomized IDE trial. Expanded addressable market by 3x.",
            "how_to_apply": "Design post-market registry at PMA submission. Pre-specify endpoints aligned with future label expansion goals. Collect data at 500+ sites. Discuss registry design with FDA at advisory panel — FDA will indicate which data elements would support RWE label expansion.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/31484842/",
        },
    ],
    "diagnostic_molecular": [
        {
            "category": "Diagnostic Strategy",
            "strategy": "LDT commercial launch while pursuing FDA clearance — generate revenue and real-world evidence during regulatory process",
            "detail": "Under CLIA regulations, laboratory-developed tests (LDTs) can be commercially launched without FDA clearance. Under the new FDA LDT rule (2024), existing LDTs have a 4-year phase-in period. Launching as LDT immediately after CLIA validation generates revenue, builds clinical evidence, and funds the FDA clearance process — which then transforms the same test into a scalable IVD.",
            "example_company": "Genomic Health (now Exact Sciences)",
            "example_drug": "Oncotype DX breast recurrence score",
            "what_they_did": "Launched Oncotype DX as LDT in 2004 without FDA clearance. Built $100M+ annual revenue and funded TAILORx trial (10,273 patients) proving clinical utility. FDA cleared 2017 — 13 years after commercial launch. LDT revenue funded the evidence that got FDA clearance.",
            "how_to_apply": "Launch LDT immediately post-CLIA validation. Use revenue to fund analytical and clinical validation studies for FDA submission. Under 2024 LDT rule, existing LDTs have until 2028 for 510(k)/De Novo submission. Plan FDA submission from day 1 but don't wait for it to launch.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/25028123/",
        },
        {
            "category": "Diagnostic Strategy",
            "strategy": "Co-development agreement with pharma CDx partner — they fund your diagnostic development in exchange for exclusive CDx designation",
            "detail": "Pharma companies need FDA-approved companion diagnostics for their drugs. A co-development agreement where pharma funds your CDx development (paying $5-20M in R&D support) in exchange for exclusivity as the CDx for their drug provides non-dilutive funding and a guaranteed commercial launch tied to drug approval.",
            "example_company": "Foundation Medicine",
            "example_drug": "FoundationOne CDx — multi-drug CDx platform",
            "what_they_did": "Foundation Medicine established co-development agreements with Roche, Bristol-Myers Squibb, Pfizer, and others. Each pharma partner funds analytical validation for their specific biomarker in exchange for CDx designation. Platform now covers 300+ biomarkers across multiple drugs.",
            "how_to_apply": "Identify 3-5 pharma companies with late Phase 2/Phase 3 oncology drugs requiring companion diagnostic. Approach BD teams with CDx co-development proposal. Structure as: pharma pays $5-15M for analytical validation and clinical trial testing; diagnostic company receives exclusive CDx designation and milestone payments.",
            "source_url": "https://www.fda.gov/medical-devices/in-vitro-diagnostics/companion-diagnostics",
        },
    ],
    "vaccine_prophylactic": [
        {
            "category": "Vaccine Strategy",
            "strategy": "BARDA OTA contract with procurement guarantee de-risks manufacturing investment before Phase 3 data",
            "detail": "Traditional vaccine development requires committing to manufacturing scale-up before Phase 3 completion — a $200-500M bet on positive results. BARDA OTA contracts include procurement guarantees (e.g., 100M doses at $X/dose) that make manufacturing investment bankable, allowing companies to build commercial-scale manufacturing during Phase 3 rather than after.",
            "example_company": "Moderna",
            "example_drug": "mRNA-1273 (Spikevax)",
            "what_they_did": "Moderna received $955M BARDA OTA for Phase 3 + manufacturing scale-up. Procurement guarantee for 100M doses made Lonza manufacturing partnership financeable. Delivered first doses 11 months after Phase 1 initiation.",
            "how_to_apply": "Apply for BARDA OTA 12 months before Phase 3 for any vaccine targeting pandemic-relevant pathogen. Structure request around: Phase 3 funding + manufacturing scale-up + procurement guarantee. BARDA priority list: pandemic flu, COVID variants, bioterrorism agents, emerging infectious diseases.",
            "source_url": "https://medicalcountermeasures.gov/barda/cbrn/covid-19/",
        },
    ],
}

# ── MASTER STRATEGY LOOKUP ─────────────────────────────────────────────────────

def get_strategies_for_domain(sub_expert_id: str, max_strategies: int = 5) -> list:
    """
    Returns combined universal + domain-specific strategies for a given expert domain.
    Always returns at least 3 universal strategies.
    """
    universal = UNIVERSAL_STRATEGIES[:3]  # Always include top 3 universal
    domain = DOMAIN_SPECIFIC_STRATEGIES.get(sub_expert_id, [])

    # Combine: domain-specific first (most relevant), then universal
    combined = domain[:3] + universal
    return combined[:max_strategies]


def format_strategies_for_report(sub_expert_id: str) -> list:
    """
    Format strategies as list of dicts for report strategic_playbook field.
    """
    strategies = get_strategies_for_domain(sub_expert_id, max_strategies=4)
    return [
        {
            "strategy": s["strategy"][:100],
            "example": s["example_company"] + " - " + s["example_drug"],
            "what_they_did": s["what_they_did"][:150],
            "how_to_apply": s["how_to_apply"][:150],
            "source_url": s["source_url"],
        }
        for s in strategies
    ]
