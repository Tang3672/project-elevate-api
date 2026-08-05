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
        "detail": "Most companies apply for one designation at a time. The optimal approach is to apply for BTD, Fast Track, Orphan Drug, and Priority Review simultaneously if eligible. Each has independent eligibility criteria and independent benefits that compound.",
        "example_company": "Vertex Pharmaceuticals",
        "example_drug": "Ivacaftor (Kalydeco) for cystic fibrosis",
        "what_they_did": "Vertex obtained Breakthrough Therapy + Fast Track + Priority Review + Orphan Drug simultaneously for ivacaftor. FDA approved in 4 months after NDA submission. The NEJM Phase 3 paper (Ramsey et al. 2011) demonstrated 10.6% FEV1 improvement, supporting all designations simultaneously.",
        "how_to_apply": "At Phase 1 data readout, assess eligibility for all 4 designations simultaneously. File within 30 days of each other. Total incremental cost ~$200K; potential timeline savings 12-24 months.",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/22047561/",
        "applicability": "Any drug with serious/life-threatening indication and preliminary evidence of substantial improvement over available therapy."
    },
    {
        "category": "Regulatory Acceleration",
        "strategy": "Pediatric exclusivity extension adds 6 months to all existing exclusivity — often worth $500M-2B in additional revenue",
        "detail": "The Best Pharmaceuticals for Children Act (BPCA) grants 6 months of additional exclusivity for conducting FDA-requested pediatric studies. This extension applies to ALL existing exclusivities simultaneously.",
        "example_company": "AbbVie",
        "example_drug": "Humira (adalimumab)",
        "what_they_did": "AbbVie secured pediatric exclusivity extension for adalimumab worth billions in additional revenue. The pediatric JIA studies (Lovell et al., NEJM 2008, PMID 18784101) generated the required data and triggered automatic 6-month exclusivity extension per BPCA statute.",
        "how_to_apply": "Request FDA Written Request (WR) for pediatric studies at NDA submission. Even if pediatric indication is not your target market, the exclusivity extension applies to adult indications. Budget $5-15M for pediatric PK and safety studies.",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/18784101/",
        "applicability": "Any drug that may have pediatric use. FDA issues Written Requests for ~100 drugs/year. Exclusivity extension value scales with adult market size."
    },
    {
        "category": "Regulatory Acceleration",
        "strategy": "Type B pre-NDA meeting 12 months before submission prevents Complete Response Letters — 50% of CRLs cite issues never discussed with FDA",
        "detail": "A Type B pre-NDA meeting held 12 months before submission locks in FDA agreement on data package sufficiency, labeling, CMC, and risk management. Companies that skip this meeting receive CRLs at 2x the rate of those who hold it.",
        "example_company": "Pfizer",
        "example_drug": "Paxlovid (nirmatrelvir/ritonavir) for COVID-19",
        "what_they_did": "Pfizer held extensive Type A/B meetings with FDA throughout EPIC-HR trial, pre-aligning on EUA data package and NDA pathway. Result: EUA granted December 2021 within weeks of data submission; traditional NDA approved May 2023 without CRL. Published NEJM trial (Hammond et al. 2022, PMID 35172054) was pre-aligned with FDA on endpoints.",
        "how_to_apply": "Request Type B pre-NDA meeting at least 15 months before planned NDA submission. Submit detailed meeting package including proposed labeling, clinical summary, CMC overview. FDA must respond within 30 days and hold meeting within 90 days.",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/35172054/",
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
        "source_url": "https://www.fda.gov/patients/rare-diseases-fda/pediatric-rare-disease-priority-review-vouchers",
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
        "source_url": "https://www.fda.gov/news-events/press-announcements/fda-approves-xalkori-new-kind-lung-cancer-drug",
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

# Device/diagnostic/SaMD universal strategies — used to pad NON-DRUG modalities so they
# never inherit the drug playbook (Fast Track / pediatric exclusivity / pre-NDA meeting).
UNIVERSAL_STRATEGIES_DEVICE = [
    {
        "category": "Regulatory Acceleration",
        "strategy": "Stack Breakthrough Device Designation (BDD) with an early Q-Sub (pre-submission) meeting",
        "detail": "For a novel device/SaMD, BDD grants priority FDA interaction and a sprint-team review; pairing it with a Q-Sub locks in agreement on the validation study design and endpoints before you build the pivotal dataset.",
        "example_company": "Viz.ai",
        "example_drug": "Viz ContaCT (LVO stroke triage AI)",
        "what_they_did": "Viz.ai took ContaCT through FDA De Novo (2018) as the first AI stroke-triage tool, using early FDA engagement to define the clinical validation package.",
        "how_to_apply": "Request BDD as soon as you have preliminary performance data; file a Q-Sub 3-6 months before the pivotal validation study to pre-align on sensitivity/specificity endpoints and reference standard.",
        "source_url": "https://www.fda.gov/medical-devices/breakthrough-devices-program",
        "applicability": "Any novel device/SaMD addressing a serious condition with no cleared predicate.",
    },
    {
        "category": "Reimbursement",
        "strategy": "Pursue a New Technology Add-on Payment (NTAP) so hospitals are paid for using the software on top of the DRG",
        "detail": "AI/SaMD historically had no dedicated payment. NTAP (and now the outpatient NTCAP equivalent) lets hospitals recover incremental cost above the DRG bundle — the single biggest unlock for adoption.",
        "example_company": "Viz.ai",
        "example_drug": "Viz ContaCT — first CMS NTAP for AI software",
        "what_they_did": "Viz.ai secured the first-ever CMS NTAP for AI software (FY2021, up to ~$1,040 per use), establishing the reimbursement template later followed by other imaging-AI vendors.",
        "how_to_apply": "Apply to CMS for NTAP with cost + substantial-clinical-improvement evidence ~1 year before your target fiscal year; in parallel pursue a Category III CPT and payer LCDs.",
        "source_url": "https://www.cms.gov/medicare/payment/prospective-payment-systems/acute-inpatient-pps/new-medical-services-and-new-technologies",
        "applicability": "Device/SaMD used in the inpatient setting with a demonstrable outcome or cost benefit.",
    },
    {
        "category": "Product Lifecycle",
        "strategy": "Use a Predetermined Change Control Plan (PCCP) to update the algorithm without a new submission",
        "detail": "FDA's PCCP (2023) lets an AI/ML developer pre-specify how the model will be retrained and updated, so post-market improvements don't each require a new 510(k)/De Novo — a decisive moat and cost saver for adaptive software.",
        "example_company": "FDA AI/ML Action Plan",
        "example_drug": "Predetermined Change Control Plan (PCCP)",
        "what_they_did": "FDA finalized PCCP guidance so cleared AI/ML devices can iterate within an authorized envelope; early adopters lock in a durable update pathway competitors lack.",
        "how_to_apply": "Include a PCCP in your De Novo/510(k) specifying the modification protocol, performance bounds, and re-validation approach for model updates.",
        "source_url": "https://www.fda.gov/medical-devices/software-medical-device-samd/artificial-intelligence-and-machine-learning-software-medical-device",
        "applicability": "Any adaptive AI/ML SaMD expected to retrain or improve post-market.",
    },
    {
        "category": "Go-to-Market",
        "strategy": "Land-and-expand: pilot at academic centers, publish outcomes, then expand across the IDN",
        "detail": "Enterprise health-system sales are slow and committee-gated. Winning a lighthouse academic site, generating peer-reviewed outcome/ROI data, then expanding across the integrated delivery network is the proven SaMD commercial motion.",
        "example_company": "Aidoc / RapidAI",
        "example_drug": "Enterprise imaging-AI deployment",
        "what_they_did": "Modern imaging-AI vendors landed flagship stroke centers, published time-to-treatment and outcome improvements, and used that evidence to expand enterprise-wide.",
        "how_to_apply": "Sign 2-3 lighthouse academic sites at a pilot price; instrument LOS/time-to-treatment/readmission outcomes; convert the published data into an enterprise value-based contract.",
        "source_url": "https://www.himss.org/",
        "applicability": "Any enterprise-sold device/SaMD dependent on clinician adoption and hospital procurement.",
    },
]


def _universal_for(sub_expert_id: str) -> list:
    """Pick the modality-appropriate universal strategy set.

    Research tools never inherit the drug or device playbook — padding a
    research-tool report with Vertex/AbbVie drug strategies is the exact
    failure this gate exists to prevent.
    """
    sid = (sub_expert_id or "").lower()
    if sid.startswith(("research_tool", "research_infrastructure")):
        return []   # No universal supplements — only domain-specific entries apply
    if sid.startswith(("device_", "diagnostic_", "digital_")):
        return UNIVERSAL_STRATEGIES_DEVICE
    return UNIVERSAL_STRATEGIES


def get_strategies_for_domain(sub_expert_id: str, max_strategies: int = 4) -> list:
    """
    Returns domain-specific strategies for the given archetype.

    B-04: No minimum-count — return however many accurate domain-specific
    strategies exist, capped at max_strategies. Never pad with universals to
    reach a count target; two accurate strategies beat four with filler.
    """
    domain = DOMAIN_SPECIFIC_STRATEGIES.get(sub_expert_id, [])
    return domain[:max_strategies]


_TYPED_ARCHETYPES = {"research_tool_non_clinical", "research_infrastructure_saas"}


def format_strategies_for_report(sub_expert_id: str) -> list:
    """
    Format strategies as list of dicts for report strategic_playbook field.

    E.1: research_tool and research_infrastructure archetypes are routed through
    the typed Strategy library (strategy_model.py) so the output includes typed
    gating fields (id, archetypes, domains, buyer_personas, apply_template).
    All other archetypes continue to use the existing dict lookup.
    """
    if (sub_expert_id or "").lower() in _TYPED_ARCHETYPES:
        from app.services.strategy_model import format_typed_strategies_for_report
        return format_typed_strategies_for_report(
            archetype=sub_expert_id,
            domain="LIFE_SCIENCES_RESEARCH",
            context={},
            max_strategies=4,
        )

    strategies = get_strategies_for_domain(sub_expert_id, max_strategies=4)
    return [
        {
            "strategy":    s["strategy"],
            "example":     s["example_company"] + " — " + s["example_drug"],
            "what_they_did": s["what_they_did"],
            "how_to_apply":  s.get("how_to_apply", s.get("applicability", "")),
            "source_url":  s["source_url"],
        }
        for s in strategies
    ]

# ── ADDITIONAL DOMAIN STRATEGIES ─────────────────────────────────────────────
# Covers all 32 sub_expert_ids

DOMAIN_SPECIFIC_STRATEGIES.update({

    "drug_rare_disease": [
        {
            "category": "Rare Disease",
            "strategy": "Umbrella IND across multiple rare disease subtypes to pool enrollment and share Phase 1 safety data",
            "example_company": "Ultragenyx Pharmaceutical",
            "example_drug": "Crysvita (burosumab) for XLH",
            "what_they_did": "Ultragenyx ran parallel IND programs for multiple FGF23-related rare diseases under shared platform, cutting Phase 1 costs by ~40% and enabling simultaneous orphan designations across 3 indications.",
            "applicability": "If your mechanism applies to multiple rare disease subtypes, file a platform IND covering all variants. Each gets independent Orphan designation and exclusivity.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/28304189/",
        },
        {
            "category": "Rare Disease",
            "strategy": "Natural history study as FDA-accepted external control eliminates placebo arm in rare disease trials",
            "example_company": "Alexion Pharmaceuticals",
            "example_drug": "Eculizumab (Soliris) for PNH",
            "what_they_did": "Alexion used natural history data as external control for PNH trials, avoiding unethical placebo. Single-arm trial approved on ORR and transfusion independence. No randomized comparator required.",
            "applicability": "Establish natural history registry 2 years before Phase 3. Partner with patient foundations (NORD, disease-specific) for historical controls. Pre-agree with FDA at EOP2 meeting.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/16951163/",
        },
        {
            "category": "Rare Disease",
            "strategy": "Expanded Access (compassionate use) program generates real-world evidence while Phase 3 enrolls",
            "example_company": "BioMarin Pharmaceutical",
            "example_drug": "Voxzogo (vosoritide) for achondroplasia",
            "what_they_did": "BioMarin ran expanded access program for achondroplasia patients ineligible for trial. Generated real-world safety data across 200+ patients that supplemented Phase 3 safety database, strengthening NDA package.",
            "applicability": "Open expanded access at Phase 2 initiation for patients who don't meet trial criteria. Use to collect long-term safety data. FDA views compassionate use data favorably for rare diseases.",
            "source_url": "https://www.fda.gov/patients/learn-about-expanded-access-and-other-treatment-options/expanded-access",
        },
    ],

    "biologic_rare_disease": [
        {
            "category": "Biologic Rare Disease",
            "strategy": "Enzyme replacement therapy pricing model — set price based on cost-per-QALY not cost-of-goods",
            "example_company": "Genzyme (Sanofi)",
            "example_drug": "Alglucosidase alfa (Myozyme/Lumizyme) for Pompe disease",
            "what_they_did": "Genzyme priced Myozyme at $300,000/year based on QALY value, not manufacturing cost. Demonstrated that cost-effectiveness threshold justifies premium pricing for life-saving enzyme replacement in ultra-rare disease.",
            "applicability": "Commission ICER health economic analysis 18 months pre-approval. Model cost per QALY gained vs natural history. Use QALY data to justify pricing in payer negotiations.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/16400610/",
        },
        {
            "category": "Biologic Rare Disease",
            "strategy": "Platform biologic manufacturing — use same CHO cell line and purification process across multiple rare disease programs",
            "example_company": "Argenx",
            "example_drug": "Efgartigimod (Vyvgart) platform across MG, ITP, PV, CIDP",
            "what_they_did": "Argenx developed single FcRn antagonist platform and expanded same molecule to 8+ rare autoimmune diseases. Same manufacturing, different formulations. Each indication gets independent Orphan exclusivity.",
            "applicability": "If your biologic mechanism applies to multiple rare autoimmune diseases, file separate IND for each indication reusing Phase 1 safety data. Each gets independent Orphan designation.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/34309732/",
        },
    ],

    "biologic_cardiology": [
        {
            "category": "Cardiology Biologic",
            "strategy": "Cardiovascular outcomes trial (CVOT) design with surrogate primary endpoint for accelerated approval, MACE confirmatory",
            "example_company": "Regeneron/Sanofi",
            "example_drug": "Alirocumab (Praluent) PCSK9 inhibitor",
            "what_they_did": "Got accelerated approval on LDL-C reduction (surrogate), ran ODYSSEY OUTCOMES CVOT simultaneously. CVOT showed 15% MACE reduction, converted to full approval. Strategy avoided waiting 5 years for CVOT results before first approval.",
            "applicability": "Negotiate LDL-C, HbA1c, or blood pressure as surrogate endpoint for accelerated approval. Run CVOT in parallel. Surrogate approval generates revenue while CVOT runs.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/29141957/",
        },
        {
            "category": "Cardiology Biologic",
            "strategy": "Heart failure device-drug combination — biologic that improves device outcomes gets faster approval and premium pricing",
            "example_company": "Novartis",
            "example_drug": "Sacubitril/valsartan (Entresto)",
            "what_they_did": "Novartis designed PARADIGM-HF to show superiority over enalapril (not just non-inferiority). 20% reduction in CV death/HF hospitalization enabled breakthrough designation and premium $4,500/year pricing vs generic ACE inhibitor.",
            "applicability": "Design Phase 3 for superiority not just non-inferiority. If you show 15-20% MACE reduction vs standard of care, BTD is achievable and justifies 5-10x premium over generics.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/25176015/",
        },
    ],

    "biologic_hematology": [
        {
            "category": "Hematology Biologic",
            "strategy": "Bispecific antibody for hematologic malignancy — single molecule replaces CAR-T at fraction of manufacturing cost",
            "example_company": "Amgen",
            "example_drug": "Blinatumomab (Blincyto) for ALL",
            "what_they_did": "Amgen developed BiTE bispecific engaging CD3xCD19. 43% ORR in Ph-neg relapsed/refractory ALL. Accelerated approval 2014 on ORR. Off-the-shelf vs CAR-T (autologous). Now standard of care in MRD+ ALL.",
            "applicability": "For hematologic malignancies, bispecific antibodies offer CAR-T-like efficacy without autologous manufacturing. Target CD3 engagement on one arm plus tumor antigen on other. Off-the-shelf enables community oncology distribution.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/28087395/",
        },
        {
            "category": "Hematology Biologic",
            "strategy": "MRD negativity as accelerated approval surrogate in hematology — validated endpoint cuts trial size 60%",
            "example_company": "Janssen",
            "example_drug": "Daratumumab (Darzalex) for multiple myeloma",
            "what_they_did": "Janssen used MRD negativity rate as primary endpoint in multiple myeloma trials. FDA accepted MRD as reasonably likely to predict PFS/OS. Enabled single-arm 100-patient trials vs traditional 400+ patient RCTs.",
            "applicability": "For hematologic cancers, establish MRD assay validation early. Negotiate MRD negativity as primary accelerated approval endpoint at EOP2 meeting. Reduces Phase 3 size by 60-70%.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/27915309/",
        },
    ],

    "biologic_immunology": [
        {
            "category": "Immunology Biologic",
            "strategy": "Indication stacking — approve in most severe rare form first, then expand to common moderate form via sNDA",
            "example_company": "AbbVie",
            "example_drug": "Risankizumab (Skyrizi) for psoriasis → PsA → Crohn's",
            "what_they_did": "AbbVie approved Skyrizi in moderate-severe plaque psoriasis (2019), then PsA (2022), then Crohn's (2022), then UC (2024). Each sNDA used existing safety database. Revenue grew from $500M to $3.5B as indications expanded.",
            "applicability": "Map all IL-23/IL-17/JAK pathway indications at IND stage. File first in indication with fastest enrollment and highest ORR. Use bridging studies for subsequent indications sharing safety database.",
            "source_url": "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo=761105",
        },
        {
            "category": "Immunology Biologic",
            "strategy": "Head-to-head superiority trial vs. adalimumab biosimilar generates premium pricing data",
            "example_company": "Eli Lilly",
            "example_drug": "Ixekizumab (Taltz) for psoriasis",
            "what_they_did": "Lilly ran IXORA-S head-to-head vs Humira showing 42% PASI 100 vs 25% for adalimumab. Published NEJM 2017. Justified $45,000/year pricing vs biosimilar adalimumab at $6,000/year by demonstrating 1.7x higher complete clearance.",
            "applicability": "Design Phase 3 with active comparator arm vs current standard (adalimumab/ustekinumab). Head-to-head superiority data justifies premium pricing and enables formulary differentiation from biosimilars.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/28273456/",
        },
    ],

    "drug_oncology": [
        {
            "category": "Oncology Drug",
            "strategy": "Tumor-agnostic approval via basket trial — one biomarker, all cancers simultaneously",
            "example_company": "Merck",
            "example_drug": "Pembrolizumab (Keytruda) MSI-H/dMMR",
            "what_they_did": "KEYNOTE-158 basket trial enrolled 10+ tumor types in MSI-H patients. First ever tumor-agnostic FDA approval 2017. Now covers 40+ indications from one biomarker approval.",
            "applicability": "If your drug targets a pan-tumor biomarker (MSI, TMB, NTRK, RET), design basket trial at Phase 2. Include 6-10 tumor types. Pre-specify primary analysis by biomarker status not tumor type.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/28967792/",
        },
        {
            "category": "Oncology Drug",
            "strategy": "Adjuvant expansion after metastatic approval — 5-10x patient population at same price point",
            "example_company": "AstraZeneca",
            "example_drug": "Olaparib (Lynparza) metastatic → adjuvant breast",
            "what_they_did": "Approved Lynparza metastatic BRCA+ ovarian (2014), then adjuvant breast (OlympiA, 2021). Revenue grew from $500M to $2.7B. Adjuvant market is 5x larger by patient volume.",
            "applicability": "File Phase 3 in metastatic setting first (faster enrollment, shorter follow-up). Simultaneously initiate adjuvant trial. Use metastatic approval revenue to fund adjuvant trial.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/34081848/",
        },
        {
            "category": "Oncology Drug",
            "strategy": "Project Optimus dose optimization avoids Phase 3 failure from dose-related toxicity",
            "example_company": "Blueprint Medicines",
            "example_drug": "Avapritinib (Ayvakit) for GIST",
            "what_they_did": "Ran extensive dose-optimization Phase 1, identifying 300mg QD optimal vs MTD 400mg. Phase 3 NAVIGATOR trial showed 88% ORR. Without dose optimization, higher dose would have had prohibitive CNS toxicity.",
            "applicability": "Design Phase 1 with dose-expansion cohorts at multiple sub-MTD levels. Use PK/PD modeling for optimal dose. FDA requires dose-response data for all oncology INDs submitted after 2022.",
            "source_url": "https://www.fda.gov/drugs/guidance-documents-regulatory-information/optimizing-dosage-oncology-drugs",
        },
    ],

    "drug_cns": [
        {
            "category": "CNS Drug",
            "strategy": "Biomarker-enriched trial in CNS — patient stratification by genetic or imaging biomarker cuts trial size 50%",
            "example_company": "Biogen",
            "example_drug": "Lecanemab (Leqembi) for Alzheimer's",
            "what_they_did": "Biogen enriched CLARITY AD trial for amyloid-positive patients using PET imaging. 1,795 patients vs what would have been 3,000+ in unenriched trial. 27% slowing of cognitive decline. FDA accelerated approval Jan 2023.",
            "applicability": "Identify imaging or CSF biomarker that predicts drug response. Enrich Phase 3 enrollment using validated biomarker. Reduces sample size and improves ORR signal. Pre-agree biomarker with FDA at EOP2.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/36449413/",
        },
        {
            "category": "CNS Drug",
            "strategy": "Digital endpoint strategy — FDA-qualified cognitive digital endpoints reduce trial cost and enable decentralized enrollment",
            "example_company": "Eli Lilly",
            "example_drug": "Donanemab for Alzheimer's",
            "what_they_did": "Lilly used tablet-based cognitive assessments (iADRS) as digital endpoints. Enabled remote assessments reducing site visit burden. 30% faster enrollment vs traditional in-clinic assessments.",
            "applicability": "Engage FDA's Digital Health Center of Excellence at IND stage. Use FDA-qualified digital endpoints (ADAS-Cog digital, voice biomarkers) to enable decentralized trial components. Reduces site visit burden and enrollment time.",
            "source_url": "https://www.fda.gov/medical-devices/digital-health-center-excellence",
        },
    ],

    "drug_cardiology": [
        {
            "category": "Cardiology Drug",
            "strategy": "CVOT platform approach — run multiple MACE trials simultaneously sharing DSMB and statistical infrastructure",
            "example_company": "AstraZeneca",
            "example_drug": "Dapagliflozin (Farxiga) DAPA-HF + DECLARE",
            "what_they_did": "AZ ran DECLARE (T2D CVOT) and DAPA-HF (heart failure) simultaneously using shared DSMB and statistical infrastructure. Approved for T2D 2014, HF 2020, CKD 2021. Three CVOTs cost less than two due to infrastructure sharing.",
            "applicability": "Design CVOT platform at Phase 3 initiation. Share DSMB, adjudication committee, and statistical team across multiple indication CVOTs. Each CVOT uses same endpoints, reducing per-trial infrastructure cost 30-40%.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/31535100/",
        },
    ],

    "drug_metabolic": [
        {
            "category": "Metabolic Drug",
            "strategy": "Combination GLP-1 mechanism stacking — add second mechanism to existing GLP-1 for differentiated efficacy",
            "example_company": "Eli Lilly",
            "example_drug": "Tirzepatide (Mounjaro/Zepbound) GIP/GLP-1",
            "what_they_did": "Combined GIP and GLP-1 agonism in single molecule. SURMOUNT-1 showed 22.5% weight loss vs 15% for semaglutide. Superior efficacy justified premium $1,000/month vs semaglutide biosimilar competition.",
            "applicability": "If developing metabolic drug, evaluate dual/triple agonist mechanism vs single agonist. Clinical differentiation from GLP-1 monotherapy requires >5% additional weight loss to justify premium pricing.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/35441470/",
        },
    ],

    "drug_immunology": [
        {
            "category": "Immunology Drug",
            "strategy": "JAK inhibitor label expansion — approve in one autoimmune indication, expand to 5+ via sNDA",
            "example_company": "Pfizer",
            "example_drug": "Tofacitinib (Xeljanz) RA → UC → PsA → JIA",
            "what_they_did": "Approved tofacitinib in RA (2012), then UC (2018), PsA (2017), JIA (2020). Each sNDA used existing safety database with indication-specific efficacy data. Revenue grew from $1B to $2.5B across indications.",
            "applicability": "File in indication with strongest Phase 2 data first. Each subsequent sNDA costs ~$20-40M vs $200M+ for new molecule. Safety database grows with each approval, de-risking subsequent filings.",
            "source_url": "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo=203214",
        },
    ],

    "drug_infectious_non_amr": [
        {
            "category": "Infectious Disease Drug",
            "strategy": "Prophylaxis indication expansion after treatment approval — 3-10x patient population",
            "example_company": "Gilead Sciences",
            "example_drug": "Emtricitabine/tenofovir (Truvada) HIV treatment → PrEP",
            "what_they_did": "Truvada approved for HIV treatment 2004. PrEP indication filed 2012 using existing safety data plus iPrEx trial. PrEP market 10x treatment market by patient volume. Revenue doubled.",
            "applicability": "After treatment approval, evaluate prophylaxis indication. PrEP, post-exposure prophylaxis, and seasonal prophylaxis trials can use existing safety database with small (500-1,000 patient) efficacy trial.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/20505210/",
        },
    ],

    "drug_mental_health": [
        {
            "category": "Mental Health Drug",
            "strategy": "Treatment-resistant indication approval first, then expand to first-line via sNDA",
            "example_company": "Janssen",
            "example_drug": "Esketamine (Spravato) for TRD",
            "what_they_did": "Janssen approved esketamine specifically for treatment-resistant depression (TRD) where no approved options exist. BTD + accelerated approval based on MADRS improvement. First new MDD mechanism in 30 years. Expanding to MDD with acute suicidal ideation.",
            "applicability": "Target treatment-resistant population first — smaller trial needed, BTD achievable, no comparator required. Use TRD approval to fund first-line MDD trial which is 10x larger market.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/30441944/",
        },
    ],

    "gene_therapy_oncology": [
        {
            "category": "Gene Therapy Oncology",
            "strategy": "CAR-T allogeneic (off-the-shelf) manufacturing eliminates 3-4 week vein-to-vein time barrier",
            "example_company": "Allogene Therapeutics",
            "example_drug": "Cabtagene autoleucel → ALLO-501A allogeneic",
            "what_they_did": "Allogene developed allogeneic CAR-T using CRISPR-edited donor T-cells. Eliminates patient-specific manufacturing. Reduces vein-to-vein from 3-4 weeks to immediate. Enables community oncology administration.",
            "applicability": "Design allogeneic CAR-T platform at IND stage. Address HvGD via TRAC knockout. Allogeneic enables multiple doses (1st gen products gave single dose). Community oncology distribution vs academic center-only.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/32929220/",
        },
    ],

    "gene_therapy_cns": [
        {
            "category": "Gene Therapy CNS",
            "strategy": "Intrathecal delivery bypasses blood-brain barrier for CNS gene therapy — 100x dose reduction vs IV",
            "example_company": "Biogen/Ionis",
            "example_drug": "Nusinersen (Spinraza) intrathecal ASO for SMA",
            "what_they_did": "Biogen/Ionis chose intrathecal delivery for nusinersen, achieving therapeutic CSF concentrations with 12mg dose vs estimated 1,200mg+ required IV. Validated intrathecal delivery for CNS rare diseases.",
            "applicability": "For CNS gene therapy, evaluate intrathecal vs IV delivery at IND stage. Intrathecal requires specialized administration (Ommaya reservoir or lumbar puncture) but dramatically reduces dose, toxicity, and manufacturing cost.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/29091570/",
        },
    ],

    "gene_therapy_hematology": [
        {
            "category": "Hematology Gene Therapy",
            "strategy": "Functional cure endpoint negotiation — achieve regulatory approval on transfusion independence, not OS",
            "example_company": "bluebird bio",
            "example_drug": "Betibeglogene (Zynteglo) for beta-thalassemia",
            "what_they_did": "bluebird negotiated transfusion independence (TI) as primary endpoint for Zynteglo. 89% of patients achieved TI at 2 years in Phase 3. FDA accepted TI as reasonably likely to predict long-term OS benefit. Approved 2022.",
            "applicability": "For hemoglobinopathies, negotiate transfusion independence (>12 months) as primary endpoint. For hemophilia, negotiate bleed-free status. These are FDA-accepted surrogates that enable approval on 50-100 patient trials.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/35202560/",
        },
    ],

    "gene_therapy_rna": [
        {
            "category": "RNA Therapy",
            "strategy": "GalNAc conjugation enables subcutaneous delivery of siRNA — removes need for LNP and IV infusion",
            "example_company": "Alnylam Pharmaceuticals",
            "example_drug": "Inclisiran (Leqvio) GalNAc-siRNA for hypercholesterolemia",
            "what_they_did": "Alnylam developed GalNAc-siRNA conjugate enabling SC injection q6months vs LNP IV infusion. Two doses/year vs daily statin. Novartis licensed for $9.7B. FDA approved 2021. Differentiated on dosing convenience.",
            "applicability": "If targeting liver-expressed genes, evaluate GalNAc conjugation vs LNP. GalNAc enables SC dosing q3-6months, dramatically improving patient compliance and enabling primary care distribution.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/31226236/",
        },
    ],

    "other_crispr": [
        {
            "category": "CRISPR/Gene Editing",
            "strategy": "Ex vivo editing for hematologic disease — edit cells outside body to avoid in vivo delivery challenges",
            "example_company": "Vertex/CRISPR Therapeutics",
            "example_drug": "Exagamglogene (Casgevy) for sickle cell/beta-thal",
            "what_they_did": "Vertex/CRISPR chose ex vivo approach — edit patient HSCs outside body, reinfuse. Avoids in vivo delivery completely. FDA approved Dec 2023. First approved CRISPR therapy globally. 29/29 patients transfusion-free.",
            "applicability": "For hematologic diseases, ex vivo editing is the clearest regulatory path. Avoids in vivo off-target concerns. HSC editing platform can be applied to multiple diseases. Manufacturing is the key bottleneck to address early.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/38232735/",
        },
    ],

    "other_microbiome": [
        {
            "category": "Microbiome",
            "strategy": "Live biotherapeutic product (LBP) regulatory pathway — CDER biologics route with streamlined CMC",
            "example_company": "Seres Therapeutics",
            "example_drug": "Vowst (fecal microbiota spores) for C. diff",
            "what_they_did": "Seres developed standardized microbiome product for rCDI. FDA approved as LBP under BLA pathway 2023. First oral microbiome drug approved. Demonstrated that standardized manufacturing and Phase 3 RCT is sufficient without full characterization.",
            "applicability": "File as Live Biotherapeutic Product (LBP) under CDER biologics. FDA has LBP guidance since 2022. Oral route preferred. Standardized manufacturing (not fecal) is required for BLA. Partner with academic microbiome labs for strain identification.",
            "source_url": "https://www.fda.gov/vaccines-blood-biologics/biologics-guidances/guidance-industry-early-clinical-trials-live-biotherapeutic-products",
        },
    ],

    "other_delivery": [
        {
            "category": "Drug Delivery Platform",
            "strategy": "505(b)(2) for reformulation using existing safety database — get new IP with fraction of development cost",
            "example_company": "Pacira BioSciences",
            "example_drug": "Exparel (bupivacaine liposome) for post-surgical pain",
            "what_they_did": "Pacira used 505(b)(2) relying on bupivacaine safety data. Novel liposome formulation provided 72-hour duration vs 8-hour standard. Filed as new formulation, not new drug. Full NDA exclusivity + formulation patents.",
            "applicability": "Identify off-patent drugs with suboptimal delivery (short half-life, poor tolerability, injection-only). Develop novel formulation using 505(b)(2). Existing safety data dramatically reduces development cost. New delivery IP provides exclusivity.",
            "source_url": "https://www.fda.gov/drugs/types-applications/505b2-applications",
        },
    ],

    "digital_therapeutic": [
        {
            "category": "Digital Therapeutic",
            "strategy": "De Novo SaMD authorization creates first-of-kind product code — you become the regulatory benchmark",
            "example_company": "Pear Therapeutics",
            "example_drug": "Somryst (reSET) for insomnia/SUD",
            "what_they_did": "Pear obtained De Novo authorization for prescription digital therapeutics, creating new SaMD product codes. Became regulatory precedent for CBT-based digital therapeutics. All subsequent SaMD in category must reference Pear's authorization.",
            "applicability": "If your digital therapeutic has no SaMD predicate, pursue De Novo rather than 510(k). De Novo creates new product code making you the regulatory standard. All competitors must show equivalence to your product.",
            "source_url": "https://www.fda.gov/medical-devices/software-medical-device-samd/digital-health-software-precertification-pre-cert-program",
        },
    ],

    "digital_rpm": [
        {
            "category": "Remote Patient Monitoring",
            "strategy": "CMS CPT code coverage is the commercial unlock for RPM — pursue reimbursement before FDA clearance",
            "example_company": "Livongo Health (Teladoc)",
            "example_drug": "Livongo for Diabetes RPM platform",
            "what_they_did": "Livongo pursued CMS reimbursement codes (CPT 99453, 99454, 99457) before formal FDA registration. RPM codes cover $50-150/patient/month. Built $1B revenue entirely on CMS RPM reimbursement without FDA device clearance.",
            "applicability": "For remote monitoring devices, pursue CMS CPT codes (99453-99458) as primary commercial path. Reimbursement generates revenue immediately. FDA clearance adds clinical validation and enables hospital system contracts.",
            "source_url": "https://www.cms.gov/Medicare/Coverage/center-for-connected-care-and-telehealth/rpm",
        },
    ],

    "digital_cds": [
        {
            "category": "Clinical Decision Support",
            "strategy": "Non-device CDS software avoids FDA regulation — design to advisory not diagnostic to stay out of SaMD",
            "example_company": "Epic Systems",
            "example_drug": "Epic Sepsis Model (CDS alert)",
            "what_they_did": "Epic designed sepsis prediction model as clinical decision support (CDS) providing advisory alerts, not automated diagnosis. Exempted from FDA regulation as non-device CDS under 21st Century Cures Act. Deployed in 400+ hospitals without FDA clearance.",
            "applicability": "If your AI/ML tool provides clinical insights to clinicians (not autonomous decisions), design as advisory CDS to avoid FDA SaMD regulation. Use IMDRF CDS criteria to confirm non-device status. Enables faster deployment but limits clinical claim scope.",
            "source_url": "https://www.fda.gov/medical-devices/software-medical-device-samd/clinical-decision-support-software",
        },
    ],

    "device_metabolic": [
        {
            "category": "Metabolic Device",
            "strategy": "CGM-insulin pump closed loop system (artificial pancreas) — combination product pathway enables premium pricing",
            "example_company": "Insulet Corporation",
            "example_drug": "Omnipod 5 automated insulin delivery system",
            "what_they_did": "Insulet combined CGM + insulin pump in closed-loop system. Filed as combination product with FDA. Single integrated submission vs two separate PMAs. Premium $3,000/year above pump alone justified by outcomes data (Time-in-Range +15%).",
            "applicability": "Combination CGM-pump-algorithm products file as combination product under CDRH lead. Single PMA covers all components. Outcomes data (TIR improvement) justifies $2,000-4,000 annual premium over components alone.",
            "source_url": "https://www.fda.gov/medical-devices/premarket-submissions-selecting-and-preparing-correct-submission/combination-products",
        },
    ],

    "device_neurology": [
        {
            "category": "Neurology Device",
            "strategy": "Breakthrough Device Designation for neurological conditions cuts PMA review from 180 to 90 days",
            "example_company": "Nalu Medical",
            "example_drug": "Nalu Neurostimulation System for chronic pain",
            "what_they_did": "Nalu obtained FDA Breakthrough Device Designation for spinal cord stimulation system. FDA review completed in 90 days vs standard 180-day PMA timeline. First approval for miniaturized SCS without implantable pulse generator.",
            "applicability": "For neuro-stimulation devices, evaluate Breakthrough Device Designation eligibility. Requires more effective treatment for life-threatening or irreversibly debilitating disease. FDA provides interactive review and senior staff priority access.",
            "source_url": "https://www.fda.gov/medical-devices/how-study-and-market-your-device/breakthrough-devices-program",
        },
    ],

    "diagnostic_companion": [
        {
            "category": "Companion Diagnostic",
            "strategy": "Co-development agreement with pharma CDx partner — they fund your diagnostic in exchange for exclusive CDx designation",
            "example_company": "Foundation Medicine",
            "example_drug": "FoundationOne CDx multi-drug companion diagnostic",
            "what_they_did": "Foundation Medicine signed co-development deals with Roche, BMS, Pfizer. Each pharma pays $5-15M for biomarker validation in exchange for exclusive CDx designation. Platform covers 300+ biomarkers across multiple drugs.",
            "applicability": "Identify 3-5 pharma partners with late Phase 2 oncology drugs needing CDx. Pharma pays R&D costs in exchange for CDx designation. You receive milestone payments and per-test royalties at commercialization.",
            "source_url": "https://www.fda.gov/medical-devices/in-vitro-diagnostics/companion-diagnostics",
        },
        {
            "category": "Companion Diagnostic",
            "strategy": "LDT commercial launch while pursuing FDA clearance — generate revenue and RWE during regulatory process",
            "example_company": "Genomic Health (Exact Sciences)",
            "example_drug": "Oncotype DX breast recurrence score",
            "what_they_did": "Launched Oncotype DX as LDT in 2004 without FDA clearance. Built $100M revenue and funded TAILORx trial (10,273 patients). FDA cleared 2017. LDT revenue funded the evidence that got FDA clearance.",
            "applicability": "Launch as CLIA-certified LDT immediately. Under 2024 FDA LDT rule, existing LDTs have until 2028 for 510(k) submission. Use LDT revenue to fund analytical validation studies for FDA clearance.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/25028123/",
        },
    ],

    "vaccine_cancer_immuno": [
        {
            "category": "Cancer Immunotherapy/Vaccine",
            "strategy": "Personalized neoantigen vaccine combined with checkpoint inhibitor — regulatory de-risked by PD-1 combination",
            "example_company": "Moderna/Merck",
            "example_drug": "mRNA-4157/V940 + pembrolizumab for melanoma",
            "what_they_did": "Moderna combined personalized neoantigen mRNA vaccine with Keytruda. KEYNOTE-942 Phase 2 showed 44% reduction in recurrence vs Keytruda alone in resected melanoma. BLA filing 2025. Combination de-risks regulatory path by adding to approved drug.",
            "applicability": "Design cancer vaccine trials in combination with approved checkpoint inhibitor. Combination de-risks regulatory approval (adding to approved drug). Merck shares development costs and provides commercial infrastructure.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/37477855/",
        },
    ],

})

# Override drug_cns with more specific rare neurological disease strategies
DOMAIN_SPECIFIC_STRATEGIES["drug_cns"] = [
    {
        "category": "CNS Drug",
        "strategy": "Use tofersen (Qalsody) natural history data as FDA-accepted external control — eliminates placebo arm",
        "example_company": "Biogen",
        "example_drug": "Tofersen (Qalsody) for SOD1-ALS",
        "what_they_did": "Biogen used VALOR trial placebo arm and OLE data as external comparator for accelerated approval on plasma NfL reduction. FDA accepted single-arm design given rare disease ethics and established natural history data. Full approval granted April 2024.",
        "applicability": "Request FDA acceptance of VALOR/OLE natural history data as external control at pre-IND meeting. This eliminates the need for a placebo arm, cutting Phase 3 size from 300+ to 100-150 patients. Precedent is established.",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/36847528/",
    },
    {
        "category": "CNS Drug",
        "strategy": "Plasma neurofilament light chain (NfL) as FDA-validated surrogate endpoint — enables accelerated approval on 100-150 patients",
        "example_company": "Biogen/Ionis",
        "example_drug": "Tofersen (Qalsody) accelerated approval 2023",
        "what_they_did": "FDA granted accelerated approval for tofersen based solely on plasma NfL reduction as surrogate endpoint reasonably likely to predict clinical benefit. This precedent means any SOD1-targeting drug can use plasma NfL as primary endpoint without waiting for ALSFRS-R clinical outcomes.",
        "applicability": "Design Phase 2 primary endpoint around plasma NfL reduction (>40% is meaningful threshold per VALOR data). Pre-agree NfL threshold with FDA at Type B meeting. Accelerated approval possible at ~18 months Phase 2 completion.",
        "source_url": "https://www.fda.gov/drugs/news-events-human-drugs/fda-approves-treatment-amyotrophic-lateral-sclerosis-associated-mutation-sod1-gene",
    },
    {
        "category": "CNS Drug",
        "strategy": "Enroll presymptomatic SOD1 carriers as prevention cohort — expands trial population 3-4x and enables prevention label",
        "example_company": "Biogen",
        "example_drug": "Tofersen ATLAS trial for presymptomatic SOD1-ALS",
        "what_they_did": "Biogen initiated ATLAS trial enrolling presymptomatic SOD1 carriers (genetic test positive, no symptoms). Prevention trial population is 3-4x the symptomatic population. FDA accepted presymptomatic enrollment using time to onset as endpoint.",
        "applicability": "Partner with Answer ALS consortium and CureSMA for presymptomatic carrier identification through genetic testing programs. Prevention cohort enrollment dramatically expands your addressable trial population beyond the ~640 symptomatic SOD1-ALS patients.",
        "source_url": "https://clinicaltrials.gov/study/NCT04856982",
    },
    {
        "category": "CNS Drug",
        "strategy": "Biomarker enrichment using genetic stratification cuts Phase 3 size 60-80% in neurodegeneration",
        "example_company": "Eli Lilly",
        "example_drug": "Donanemab for Amyloid+ Alzheimer's",
        "what_they_did": "Lilly enriched TRAILBLAZER-ALZ 2 for amyloid-positive, tau-intermediate patients using PET imaging. 1,736 patients vs estimated 4,000+ unenriched. 35% slowing of decline. FDA full approval 2024. Biomarker enrichment was critical to trial success.",
        "applicability": "For any CNS neurodegeneration program, identify imaging or CSF/plasma biomarker that predicts drug response. Enrich Phase 3 enrollment. Pre-agree biomarker threshold with FDA at EOP2 meeting. Typically reduces Phase 3 size 50-70%.",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/37459244/",
    },
]

# ── RESEARCH TOOL & NON-CLINICAL INFRASTRUCTURE STRATEGIES ──────────────────

DOMAIN_SPECIFIC_STRATEGIES.update({

    "research_tool_non_clinical": [
        {
            "category": "Research Tool Commercialization",
            "strategy": "Publish in Nature Methods or PLOS ONE before commercial launch — peer-reviewed protocol papers are the highest-ROI marketing spend for academic research tools",
            "example_company": "10x Genomics",
            "example_drug": "Chromium scRNA-seq platform",
            "what_they_did": "10x Genomics co-authored the foundational Chromium single-cell RNA-seq workflow paper (Zheng et al., Science 2017, PMID 28091601) before aggressive commercial rollout. The citation became the most-cited paper in the field. Academic labs adopted the platform because it was the standard-of-record in the published literature.",
            "how_to_apply": "Prioritize a methods paper with ≥2 academic PI co-authors before any direct sales motion. It compresses the sales cycle from months to weeks because the PI's peers have already endorsed the methodology in print. Target Nature Methods, HardwareX, or PLOS ONE. Budget 3–6 months and include the data pipeline and reproducibility protocol, not just the hardware.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/28091601/",
            "applicability": "Research tools sold to academic PIs. Citation count on the methods paper directly predicts adoption rate in the academic market.",
        },
        {
            "category": "Core Facility Beachhead",
            "strategy": "Win one core facility director and sell to the facility's entire user base — core facilities are the distribution channel with no clinical-sales equivalent",
            "example_company": "Zeiss (Carl Zeiss AG)",
            "example_drug": "LSM 880 Airyscan confocal system",
            "what_they_did": "Zeiss targets institutional core facility directors with multi-year service contracts and structured training programs. One core facility sale (typically $250k–$2M capital) serves 50–200 individual PI labs and converts each PI into a trained user and active recommender to peer institutions.",
            "how_to_apply": "Map the 5–10 core facilities serving your target modality nationally. Offer the first facility a founding-partner price (30–40% discount) in exchange for co-authorship on a methods paper, a cohort training commitment, and a reference call. This converts a $15k per-lab license into a $100k–$500k facility contract with 50+ downstream trained users.",
            "source_url": "https://abrf.org/core-facilities",
            "applicability": "Research hardware and software tools with multi-user deployment. Most effective when workflow complexity benefits from centralized training and the PI is not also the engineer.",
        },
        {
            "category": "SBIR / STTR Non-Dilutive Bridge",
            "strategy": "SBIR Phase I establishes NIH credibility and pays for the first validated prototype — do not raise pre-seed until after a Phase I award",
            "example_company": "Open Ephys Productions",
            "example_drug": "Open Ephys neural acquisition system",
            "what_they_did": "Open Ephys started as open-source lab hardware at MIT (Siegle et al., Nat Neurosci 2017). Bootstrapped commercialization through SBIR grants and a university core-facility model without VC dilution. Reached 300+ labs worldwide before raising outside capital.",
            "how_to_apply": "Submit SBIR Phase I ($300k, 6 months) before a pre-seed round. The NIH/NSF award validates the scientific problem, which reduces investor dilution at the next round. Phase II ($1.5M–$2M, 2 years) can fund a full commercial-grade build. The key constraint: SBIR requires a for-profit entity — file the company before submitting.",
            "source_url": "https://www.sbir.gov/about",
            "applicability": "Research tools where NIH/NSF grant alignment is natural. SBIR credentialing is particularly valuable for institutional procurement which is risk-averse and grant-funded.",
        },
        {
            "category": "Open-Source Core / Commercial Services",
            "strategy": "Open-source the core protocol and SDK, sell the commercial services layer — the academic research market rewards transparency and punishes lock-in",
            "example_company": "Plexon Inc.",
            "example_drug": "OmniPlex neural data acquisition system",
            "what_they_did": "Plexon open-sourced its offline sorter and OmniPlex SDK while maintaining closed-source hardware drivers and cloud analytics. Open-source components built ecosystem adoption in 1,000+ labs; proprietary hardware remained the revenue vehicle.",
            "how_to_apply": "Release firmware, data format specification, and Python/MATLAB SDK under MIT or Apache license before launch. File a provisional patent on the specific hardware implementation first. Open access generates inbound interest from technically capable PI labs that become organic champions. Retain commercial value in hardware, support contracts, and managed cloud sync services.",
            "source_url": "https://plexon.com/products/plexon-omniplex-neural-data-acquisition-system/",
            "applicability": "Research infrastructure with a protocol layer (data format, API) that benefits from ecosystem adoption. Particularly effective when the PI is also the engineer and will evaluate the implementation.",
        },
    ],

    "research_infrastructure_saas": [
        {
            "category": "Research SaaS — Institutional Site License",
            "strategy": "Land in one department; expand via the research computing office — the IT buying unit is higher-value and faster than PI-by-PI expansion",
            "example_company": "LabArchives",
            "example_drug": "LabArchives Electronic Lab Notebook",
            "what_they_did": "LabArchives shifted from individual PI sales ($10–30/user/month) to institutional site licenses ($20k–$100k/yr) by partnering with university IT and research computing offices rather than PIs. One institutional sale covers hundreds to thousands of users and is renewable on the institution's fiscal cycle, not the PI's grant cycle.",
            "how_to_apply": "After initial traction (≥5 active labs, ≥3 testimonials), approach the VP Research or CIO with an institutional site-license proposal. Lead with compliance arguments — NSF data management plans, NIH data sharing policy — that matter to the institution beyond individual PIs. The compliance angle often unlocks a budget line that individual PI grant funds cannot.",
            "source_url": "https://www.labarchives.com",
            "applicability": "Research SaaS with data management, compliance, or collaboration use cases where institutional IT buyers also benefit, not only individual PIs.",
        },
        {
            "category": "Grant Renewal Timing",
            "strategy": "Time the enterprise sales pitch to align with R01 renewal cycles — a PI at the start of a new grant period has budget authority; a PI in the no-cost extension period does not",
            "example_company": "Benchling",
            "example_drug": "Benchling R&D Cloud (life science SaaS)",
            "what_they_did": "Benchling's academic sales motion anchors to grant budget periods (typically 5-year R01 cycles). Outreach timed to the start of new award periods, when PIs have full discretion over equipment and software budget lines, converts at 3–5× the rate of outreach timed to the final year.",
            "how_to_apply": "Build a data layer from NIH RePORTER: pull active awards with start dates, project end dates, and abstract text. Flag labs in year 1–2 of a new award for priority outreach. Suppress or reduce outreach frequency for labs in year 4–5. The sales cycle shrinks from months to weeks when the PI has current budget authority.",
            "source_url": "https://reporter.nih.gov",
            "applicability": "Research SaaS priced above $5k/yr per lab where the PI's grant budget is the purchase vehicle. Does not apply to sub-$1k tools bought from lab discretionary funds.",
        },
    ],

})


# Aliases mapping expert_domain IDs to strategy database keys
DOMAIN_ALIASES = {
    "antibiotic_amr": "drug_amr",
    "oncology_small_molecule": "drug_oncology",
    "oncology_biologic": "biologic_oncology",
    "biologic_rare": "biologic_rare_disease",
    "gene_therapy": "gene_therapy_rare",
    "cns_neurodegeneration": "drug_cns",
    "rare_neurological": "drug_cns",
    "infectious_non_amr": "drug_infectious_non_amr",
    "cardiovascular_biologic": "biologic_cardiology",
    "hematology_biologic": "biologic_hematology",
    "autoimmune_biologic": "biologic_immunology",
    "device_cgm": "device_metabolic",
    "device_wearable": "device_metabolic",
    "cancer_immunotherapy": "vaccine_cancer_immuno",
    "digital_samd": "digital_therapeutic",
    "companion_diagnostic": "diagnostic_companion",
}

# Apply aliases to DOMAIN_SPECIFIC_STRATEGIES
for alias, target in DOMAIN_ALIASES.items():
    if target in DOMAIN_SPECIFIC_STRATEGIES and alias not in DOMAIN_SPECIFIC_STRATEGIES:
        DOMAIN_SPECIFIC_STRATEGIES[alias] = DOMAIN_SPECIFIC_STRATEGIES[target]
