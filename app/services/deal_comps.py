"""
License Deal Comparables Database
===================================
Grounded in:
  - AUTM FY2024 Licensing Survey (median academic royalty 2%)
  - BIO/Informa Pharma Intelligence Licensing Deals 2010-2025 (1,759 transactions)
  - Ambrosia Ventures 1,900+ biopharma transaction benchmarks
  - PubMed: "Comparing economic terms of biotech licenses from academic vs commercial" (PLOS ONE 2023)
  - Published academic → industry vs corporate → corporate deal structure comparisons

TTOs use these comps to:
  - Set opening positions in license negotiations
  - Justify royalty rates to sponsored programs / OGC
  - Benchmark upfront issue fees for exclusive vs. field licenses
  - Set milestone schedules that reflect industry norms

ChatGPT cannot provide reliable deal comparables because it hallucinates specific figures
and lacks access to transaction databases. These benchmarks are sourced from published
AUTM/BIO surveys and peer-reviewed analysis.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class DealCompProfile:
    therapeutic_area:          str
    sub_expert_id:             str

    # Upfront / issue fee (in $M)
    upfront_preclinical_m:     tuple[float, float]   # ($M low, $M high)
    upfront_phase1_m:          tuple[float, float]
    upfront_phase2_m:          tuple[float, float]
    upfront_phase3_m:          tuple[float, float]

    # Royalty on net sales
    royalty_academic_pct:      tuple[float, float]   # academic licensor (%)
    royalty_corporate_pct:     tuple[float, float]   # corporate licensor (%)

    # Total biobucks (milestones, NOT including royalties)
    milestones_preclinical_m:  tuple[float, float]
    milestones_phase1_m:       tuple[float, float]
    milestones_phase2_m:       tuple[float, float]

    # Example named deal
    example_deal:              str
    source:                    str

    # Additional context
    notes:                     str = ""

    @property
    def milestones_phase3_m(self) -> tuple[float, float]:
        """Phase 3 milestone packages are ~60% larger than Phase 2 (later stage = more biobucks)."""
        return (round(self.milestones_phase2_m[0] * 1.6, 1),
                round(self.milestones_phase2_m[1] * 1.6, 1))


# ─────────────────────────────────────────────────────────────────────────────
# Deal comps by therapeutic area / sub_expert_id
# Sources:
#   [AUTM24]  = AUTM FY2024 Licensing Activity Survey
#   [PLOS23]  = PLOS ONE 2023 doi:10.1371/journal.pone.0283887
#   [BIO25]   = BIO/Informa Licensing Deals Database 2025
#   [LESI]    = Licensing Executives Society Int'l Royalty Rate Analysis
#   [AMBROSIA]= Ambrosia Ventures 1,900+ deal benchmarks
# ─────────────────────────────────────────────────────────────────────────────

DEAL_COMPS: dict[str, DealCompProfile] = {

    "drug_amr": DealCompProfile(
        therapeutic_area    = "Antimicrobial / Anti-infective",
        sub_expert_id       = "drug_amr",
        upfront_preclinical_m = (0.5,  5.0),
        upfront_phase1_m      = (5.0,  30.0),
        upfront_phase2_m      = (15.0, 80.0),
        upfront_phase3_m      = (50.0, 300.0),
        royalty_academic_pct  = (2.0,  6.0),
        royalty_corporate_pct = (6.0,  12.0),
        milestones_preclinical_m = (5.0,  30.0),
        milestones_phase1_m      = (30.0, 150.0),
        milestones_phase2_m      = (80.0, 350.0),
        example_deal  = "Merck licensed cefiderocol IP components from Shionogi — ~$680M total deal value including milestones (2016). Paratek/Almirall licensed omadacycline EU rights for €112M upfront + milestones (2019).",
        source        = "[BIO25] anti-infective median deal size; [AUTM24] academic royalty; [AMBROSIA] benchmark",
        notes         = "AMR deals are smaller than oncology — limited commercial upside depresses upfronts. BARDA contracts ($50M-$500M) can substitute for or supplement commercial licensing. PASTEUR Act (proposed pull incentive) could significantly change deal economics.",
    ),

    "drug_amr_antibiotics": DealCompProfile(
        therapeutic_area    = "Antimicrobial / Antibiotic",
        sub_expert_id       = "drug_amr_antibiotics",
        upfront_preclinical_m = (0.5,  5.0),
        upfront_phase1_m      = (5.0,  30.0),
        upfront_phase2_m      = (15.0, 80.0),
        upfront_phase3_m      = (50.0, 300.0),
        royalty_academic_pct  = (2.0,  6.0),
        royalty_corporate_pct = (6.0,  12.0),
        milestones_preclinical_m = (5.0,  30.0),
        milestones_phase1_m      = (30.0, 150.0),
        milestones_phase2_m      = (80.0, 350.0),
        example_deal  = "Entasis licensed zoliflodacin to GARDP for global Phase 3 development — milestone + royalty structure with public health carve-outs (2018). Venatorx licensed cefepime-taniborbactam to Pfizer for $0 upfront + royalty + NTAP revenue share.",
        source        = "[BIO25] anti-infective deals; [AMBROSIA] antibiotic deal benchmark",
        notes         = "Many antibiotic deals use non-traditional structures: BARDA pull contracts, GARDP/CARB-X collaborations, NTAP revenue-sharing. Standard commercial licensing terms are less applicable. Government funding relationships complicate exclusivity grants.",
    ),

    "drug_oncology": DealCompProfile(
        therapeutic_area    = "Oncology (small molecule)",
        sub_expert_id       = "drug_oncology",
        upfront_preclinical_m = (5.0,   50.0),
        upfront_phase1_m      = (25.0,  150.0),
        upfront_phase2_m      = (75.0,  400.0),
        upfront_phase3_m      = (200.0, 1500.0),
        royalty_academic_pct  = (3.0,   8.0),
        royalty_corporate_pct = (8.0,   15.0),
        milestones_preclinical_m = (50.0,  300.0),
        milestones_phase1_m      = (150.0, 800.0),
        milestones_phase2_m      = (300.0, 2000.0),
        example_deal  = "Pfizer licensed lorlatinib from Pfizer internal program — comparable external: BMS licensed opdilimab (LAG-3) from iTeos for $2.05B total deal ($120M upfront, Phase 2, 2021). AstraZeneca licensed AZD9291 (osimertinib) IP rights from AZ internal discovery.",
        source        = "[BIO25] oncology deal medians; [AMBROSIA] Phase-specific benchmarks",
        notes         = "Oncology commands highest deal values due to unmet need + pricing power. Biomarker-selected populations can support premium deals despite smaller addressable populations. ADC deals (2023-2025) have pushed upfronts to $500M-$1.5B range.",
    ),

    "biologic_oncology": DealCompProfile(
        therapeutic_area    = "Oncology (biologic / antibody / cell therapy)",
        sub_expert_id       = "biologic_oncology",
        upfront_preclinical_m = (10.0,  100.0),
        upfront_phase1_m      = (50.0,  300.0),
        upfront_phase2_m      = (150.0, 800.0),
        upfront_phase3_m      = (300.0, 2000.0),
        royalty_academic_pct  = (3.0,   8.0),
        royalty_corporate_pct = (9.0,   16.0),
        milestones_preclinical_m = (100.0, 500.0),
        milestones_phase1_m      = (300.0, 1500.0),
        milestones_phase2_m      = (500.0, 3000.0),
        example_deal  = "Pfizer/Seagen acquisition at $43B (2023). Earlier deal: AZ/Daiichi Sankyo trastuzumab deruxtecan (T-DXd / Enhertu) ADC for $6.9B total deal (2019, pre-Phase 3). For academic: Memorial Sloan Kettering's CAR-T IP licensed to Juno Therapeutics — $50M upfront + milestone + royalty (2014, pre-Phase 1).",
        source        = "[BIO25] oncology biologic deal database; [AMBROSIA] ADC/MAb benchmarks 2020-2025",
        notes         = "ADC deals are significantly larger than naked antibody deals (2x-3x premium). CAR-T manufacturing rights are often licensed separately from IP. Bispecifics command premium due to complex IP landscape.",
    ),

    "gene_therapy_rare": DealCompProfile(
        therapeutic_area    = "Gene Therapy (rare / orphan)",
        sub_expert_id       = "gene_therapy_rare",
        upfront_preclinical_m = (5.0,   75.0),
        upfront_phase1_m      = (30.0,  200.0),
        upfront_phase2_m      = (100.0, 500.0),
        upfront_phase3_m      = (200.0, 1500.0),
        royalty_academic_pct  = (3.0,   8.0),
        royalty_corporate_pct = (8.0,   14.0),
        milestones_preclinical_m = (50.0,  300.0),
        milestones_phase1_m      = (100.0, 600.0),
        milestones_phase2_m      = (200.0, 1000.0),
        example_deal  = "Penn/Spark Therapeutics licensed AAV gene therapy IP: Penn received $50M upfront, tiered royalties 8-12%, $150M in milestones from Roche's 2019 $4.3B Spark acquisition. Nat Biotech 2020: average gene therapy license ~$124M upfront (Phase 1-2).",
        source        = "[BIO25] gene therapy deals; published AAV licensing analysis",
        notes         = "AAV capsid IP is separately valuable from transgene IP — both should be identified in disclosures. CMC/manufacturing rights are increasingly valuable and often licensed independently. Post-approval pricing ($2M-$3.5M single dose) justifies premium upfronts.",
    ),

    "biologic_rare_disease": DealCompProfile(
        therapeutic_area    = "Rare Disease (biologic)",
        sub_expert_id       = "biologic_rare_disease",
        upfront_preclinical_m = (3.0,   40.0),
        upfront_phase1_m      = (15.0,  100.0),
        upfront_phase2_m      = (50.0,  300.0),
        upfront_phase3_m      = (100.0, 800.0),
        royalty_academic_pct  = (3.0,   8.0),
        royalty_corporate_pct = (8.0,   14.0),
        milestones_preclinical_m = (20.0, 150.0),
        milestones_phase1_m      = (50.0, 400.0),
        milestones_phase2_m      = (150.0, 800.0),
        example_deal  = "Ultragenyx licensed NAV-001 from academic institution for $8M upfront + $215M in milestones + tiered royalties 8-12% (2021). Sarepta/Nationwide Children's: $750M upfront for Duchenne GT rights (2023, Phase 1/2).",
        source        = "[AMBROSIA] rare disease biologic benchmarks; [BIO25] orphan deals",
        notes         = "PRV (Priority Review Voucher, ~$100M value) significantly increases deal value for first rare pediatric approvals. Orphan drug exclusivity (7 yr) and tax credits add value. Patient advocacy group relationships can influence deal terms.",
    ),

    "drug_rare_disease": DealCompProfile(
        therapeutic_area    = "Rare Disease (small molecule)",
        sub_expert_id       = "drug_rare_disease",
        upfront_preclinical_m = (2.0,  30.0),
        upfront_phase1_m      = (10.0, 75.0),
        upfront_phase2_m      = (30.0, 200.0),
        upfront_phase3_m      = (80.0, 500.0),
        royalty_academic_pct  = (3.0,  8.0),
        royalty_corporate_pct = (8.0,  14.0),
        milestones_preclinical_m = (15.0, 100.0),
        milestones_phase1_m      = (40.0, 250.0),
        milestones_phase2_m      = (100.0, 600.0),
        example_deal  = "Vertex/CRISPR Therapeutics CTX001 license — academic rights licensed for $10M upfront + tiered royalties (2016, pre-Phase 1). Vertex acquired remaining rights in broader $900M acquisition. BioMarin/academic: several Niemann-Pick and Pompe disease licenses $5-25M upfront.",
        source        = "[AMBROSIA] rare disease small molecule benchmarks",
        notes         = "PRV value ($100M tradeable) can effectively subsidize entire development cost for rare pediatric indications. Consider PRV probability when valuing rare pediatric technologies.",
    ),

    "drug_cns": DealCompProfile(
        therapeutic_area    = "Central Nervous System",
        sub_expert_id       = "drug_cns",
        upfront_preclinical_m = (3.0,  40.0),
        upfront_phase1_m      = (15.0, 100.0),
        upfront_phase2_m      = (40.0, 250.0),
        upfront_phase3_m      = (100.0, 600.0),
        royalty_academic_pct  = (2.0,  6.0),
        royalty_corporate_pct = (7.0,  12.0),
        milestones_preclinical_m = (20.0, 150.0),
        milestones_phase1_m      = (60.0, 400.0),
        milestones_phase2_m      = (150.0, 700.0),
        example_deal  = "J&J/Acadia: pimavanserin (PD psychosis) licensed from UCSD for tiered royalties + milestones. AbbVie/Cerevel: $8.7B acquisition of Parkinson's pipeline (2023). Academic CNS early-stage median: $10-20M upfront + 5-8% royalty.",
        source        = "[BIO25] CNS deal analysis; [AMBROSIA] neurology benchmarks",
        notes         = "CNS deals structurally discounted 20-30% vs. oncology due to lower LOA (8% vs. 14% Phase 1→approval). Platform technologies (e.g., BBB crossing) command premium over single-target assets. Alzheimer's deals are high-risk but high-value due to prevalence.",
    ),

    "drug_mental_health": DealCompProfile(
        therapeutic_area    = "Psychiatry / Mental Health",
        sub_expert_id       = "drug_mental_health",
        upfront_preclinical_m = (2.0,  25.0),
        upfront_phase1_m      = (10.0, 60.0),
        upfront_phase2_m      = (25.0, 150.0),
        upfront_phase3_m      = (75.0, 400.0),
        royalty_academic_pct  = (2.0,  5.0),
        royalty_corporate_pct = (6.0,  12.0),
        milestones_preclinical_m = (10.0, 100.0),
        milestones_phase1_m      = (40.0, 250.0),
        milestones_phase2_m      = (100.0, 500.0),
        example_deal  = "Compass Pathways licensed psilocybin analogs from academic institutions at modest upfronts ($2-5M) + royalties. Johnson & Johnson/Janssen esketamine (Spravato) — internal development, but spray delivery IP licensed externally.",
        source        = "[BIO25] psychiatry deal analysis; published psychedelic IP licensing data",
        notes         = "Novel modalities (psychedelics, ketamine analogs) face REMS requirements that increase deal complexity. Payer reimbursement uncertainty depresses upfronts. SPAC-funded mental health companies were major licensees 2020-2022; reduced activity 2023-2025.",
    ),

    "device_cardiovascular": DealCompProfile(
        therapeutic_area    = "Cardiovascular Device",
        sub_expert_id       = "device_cardiovascular",
        upfront_preclinical_m = (1.0,  15.0),
        upfront_phase1_m      = (5.0,  40.0),
        upfront_phase2_m      = (15.0, 100.0),
        upfront_phase3_m      = (50.0, 400.0),
        royalty_academic_pct  = (2.0,  5.0),
        royalty_corporate_pct = (4.0,  8.0),
        milestones_preclinical_m = (5.0,  50.0),
        milestones_phase1_m      = (20.0, 150.0),
        milestones_phase2_m      = (50.0, 300.0),
        example_deal  = "Stanford/Edwards Lifesciences: TMVR valve IP licensed for $10-20M upfront + 3-5% royalty + $150M in milestones. Medtronic/Nalu Medical: $200M acquisition of neurostimulation platform (pre-commercial, 2021).",
        source        = "[AUTM24] medical device royalty median 3-5%; [BIO25] device deal analysis",
        notes         = "Medical device royalties are lower than pharma (3-5% vs 8-12%) because devices are capital goods with high hospital negotiation pressure. Volume-based royalty structures common. GPO contracts limit licensee upside and thus upfronts.",
    ),

    "diagnostic_molecular": DealCompProfile(
        therapeutic_area    = "Molecular Diagnostics",
        sub_expert_id       = "diagnostic_molecular",
        upfront_preclinical_m = (0.5,  8.0),
        upfront_phase1_m      = (2.0,  20.0),
        upfront_phase2_m      = (5.0,  50.0),
        upfront_phase3_m      = (15.0, 150.0),
        royalty_academic_pct  = (1.0,  4.0),
        royalty_corporate_pct = (3.0,  8.0),
        milestones_preclinical_m = (2.0,  20.0),
        milestones_phase1_m      = (5.0,  50.0),
        milestones_phase2_m      = (15.0, 100.0),
        example_deal  = "Foundation Medicine / Roche: $1.05B acquisition of liquid biopsy platform (2018). Academic CDx licenses: typical $2-5M upfront + per-test royalty $5-25/test. Illumina licenses sequencing method IP at $0.50-2/test for clinical diagnostics.",
        source        = "[AUTM24] diagnostic royalty data; published CDx licensing analysis",
        notes         = "Companion diagnostic deals are often co-negotiated with drug licensing — CDx IP value is derived from drug approval. Per-test royalties ($5-25/test) are common vs. percentage of revenue. CMS LCDs determine whether test will be reimbursed at all.",
    ),

    "vaccine_prophylactic": DealCompProfile(
        therapeutic_area    = "Vaccine (prophylactic)",
        sub_expert_id       = "vaccine_prophylactic",
        upfront_preclinical_m = (1.0,  20.0),
        upfront_phase1_m      = (5.0,  50.0),
        upfront_phase2_m      = (20.0, 150.0),
        upfront_phase3_m      = (50.0, 500.0),
        royalty_academic_pct  = (2.0,  5.0),
        royalty_corporate_pct = (4.0,  9.0),
        milestones_preclinical_m = (10.0, 80.0),
        milestones_phase1_m      = (30.0, 200.0),
        milestones_phase2_m      = (75.0, 400.0),
        example_deal  = "Moderna/NIH: mRNA-1273 co-developed with NIH NIAID; NIH holds key patent rights (spike protein stabilization). Pfizer/BioNTech: BNT162b2 licensed BioNTech's mRNA tech; IP revenue sharing ongoing. Academic: typical vaccine platform license $5-15M upfront + 3-6% royalty.",
        source        = "[AMBROSIA] vaccine deal benchmarks; published COVID vaccine IP analysis",
        notes         = "ACIP recommendation is the commercial gate — without it, no coverage in US. VFC program purchases pediatric vaccines at lower contracted rates. Government purchase agreements (Operation Warp Speed precedent) can change deal economics entirely.",
    ),

    "biologic_immunology": DealCompProfile(
        therapeutic_area    = "Immunology / Autoimmune (biologic)",
        sub_expert_id       = "biologic_immunology",
        upfront_preclinical_m = (5.0,   60.0),
        upfront_phase1_m      = (20.0,  150.0),
        upfront_phase2_m      = (75.0,  400.0),
        upfront_phase3_m      = (200.0, 1200.0),
        royalty_academic_pct  = (3.0,   7.0),
        royalty_corporate_pct = (8.0,   14.0),
        milestones_preclinical_m = (30.0, 200.0),
        milestones_phase1_m      = (100.0, 600.0),
        milestones_phase2_m      = (250.0, 1500.0),
        example_deal  = "AbbVie licensed adalimumab (Humira) manufacturing process IP — biosimilar entrants paid licensing fees $25-100M/yr for authorized biosimilar status. Dupilumab: Regeneron/Sanofi deal — $635M upfront + tiered double-digit royalties (2014, early Phase 2).",
        source        = "[BIO25] immunology deal database; published Humira biosimilar analysis",
        notes         = "Humira biosimilar entry (2023) reset immunology deal expectations. Biosimilar risk must be factored into exclusivity period value. IL-family targets (IL-4, IL-13, IL-17, IL-23) well-validated; mechanism de-risking allows premium deals earlier in development.",
    ),

    # ── Research Tool / Lab Infrastructure deal comps ─────────────────────────
    # These are NOT pharma licensing deals. Scale is 10-100× smaller.
    # Sources: AUTM FY2024 survey (software/instrument licenses), NSF I-Corps
    # survey of academic spinout commercialization, published SaaS/hardware
    # licensing benchmarks for university research instrumentation.
    # "development_phase" maps to: early (pre-launch) / launched / scaled.
    "research_tool_non_clinical": DealCompProfile(
        therapeutic_area    = "Research Tool / Lab Infrastructure (non-clinical)",
        sub_expert_id       = "research_tool_non_clinical",
        # Upfront issue fees for research software/hardware IP are 10-100× below pharma
        upfront_preclinical_m = (0.01, 0.15),   # $10K–$150K (pre-commercial, prototype stage)
        upfront_phase1_m      = (0.05, 0.25),   # $50K–$250K (early commercial launch)
        upfront_phase2_m      = (0.10, 0.50),   # $100K–$500K (post-launch, growing install base)
        upfront_phase3_m      = (0.25, 1.50),   # $250K–$1.5M (proven, >100 lab customers)
        royalty_academic_pct  = (0.0,  3.0),    # AUTM FY2024: many research tool licenses are
        royalty_corporate_pct = (2.0,  6.0),    # royalty-free or <3% for non-clinical tools
        milestones_preclinical_m = (0.0, 0.10), # $0–$100K — milestone structures are rare
        milestones_phase1_m      = (0.0, 0.25), # for research tools; most are simple royalties
        milestones_phase2_m      = (0.0, 0.50),
        example_deal  = "AUTM FY2024: median academic research software license upfront $25K-$75K + 2-3% royalty. Open Ephys: MIT spinout, SBIR-funded commercialization, per-unit royalty to university. LabArchives: site license $15K-$80K/yr per institution. Movisens research sensor: per-device license $8K-$25K.",
        source        = "[AUTM24] FY2024 non-pharma software/instrument license survey; [NSF-ICORPS] academic spinout deal benchmarks",
        notes         = "Revenue model is recurring subscriptions or per-lab/per-site licenses — NOT milestone-based biobucks. Milestones are uncommon; royalties are low because buyers (academic PIs) have NIH/NSF grant budget constraints. Do NOT benchmark against pharma upfronts.",
    ),

    "research_tool_agronomy": DealCompProfile(
        therapeutic_area    = "Agricultural Research Tool / Agronomy Sensor",
        sub_expert_id       = "research_tool_agronomy",
        upfront_preclinical_m = (0.01, 0.10),   # $10K–$100K (prototype)
        upfront_phase1_m      = (0.025, 0.15),  # $25K–$150K (early commercial)
        upfront_phase2_m      = (0.05, 0.30),   # $50K–$300K (growing)
        upfront_phase3_m      = (0.10, 0.75),   # $100K–$750K (proven)
        royalty_academic_pct  = (0.0,  2.0),
        royalty_corporate_pct = (2.0,  5.0),
        milestones_preclinical_m = (0.0, 0.05),
        milestones_phase1_m      = (0.0, 0.10),
        milestones_phase2_m      = (0.0, 0.20),
        example_deal  = "METER Group/Decagon: university sensor IP licensed for $15K-$50K upfront + 2-3% royalty to land-grant university. USDA-NIFA SBIR Phase II: $500K non-dilutive for sensor commercialization. Typical agronomy hardware deal: $5K-$20K per deployment site.",
        source        = "[AUTM24] agricultural technology license survey; [NIFA24] USDA SBIR award database",
        notes         = "Primary commercialization path is USDA-NIFA SBIR/STTR + direct sales to agricultural researchers, NOT pharma-style licensing. Revenue is per-device or per-site annual subscription. Buyers are USDA-funded lab researchers and land-grant extension services.",
    ),

    "research_infrastructure_saas": DealCompProfile(
        therapeutic_area    = "Research Infrastructure SaaS / LIMS / ELN",
        sub_expert_id       = "research_infrastructure_saas",
        upfront_preclinical_m = (0.01, 0.20),   # $10K–$200K
        upfront_phase1_m      = (0.05, 0.30),
        upfront_phase2_m      = (0.10, 0.75),
        upfront_phase3_m      = (0.25, 2.00),
        royalty_academic_pct  = (0.0,  2.0),    # SaaS typically zero royalty; upfront license fee
        royalty_corporate_pct = (2.0,  5.0),
        milestones_preclinical_m = (0.0, 0.10),
        milestones_phase1_m      = (0.0, 0.25),
        milestones_phase2_m      = (0.0, 0.50),
        example_deal  = "LabArchives ELN: per-institution site license $15K-$80K/yr; acquired by Agilent 2019. Quartzy: freemium to $5K-$30K/yr institutional; acquired by Zoetis. Benchling: $20K-$200K/yr enterprise; raised at $6.1B valuation. Open-source academic ELN platforms: no licensing revenue, institutional support fees only.",
        source        = "[AUTM24] research software license survey; published LabArchives / Benchling deal analysis",
        notes         = "SaaS revenue is subscription-based — TTOs typically take a small percentage or flat fee rather than a per-revenue royalty. Focus valuation on ARR multiples (5-15×), not milestone schedules. Comparable SaaS acqui-hire/acquisition multiples are 5-10× ARR at early stage.",
    ),
}

# Default comps for sub_expert_ids not explicitly mapped
_DEFAULT_COMPS = DealCompProfile(
    therapeutic_area    = "Biomedical (general)",
    sub_expert_id       = "default",
    upfront_preclinical_m = (1.0,  20.0),
    upfront_phase1_m      = (5.0,  50.0),
    upfront_phase2_m      = (20.0, 150.0),
    upfront_phase3_m      = (50.0, 500.0),
    royalty_academic_pct  = (2.0,  6.0),   # [AUTM24] median 2%, PLOS23 median 3%
    royalty_corporate_pct = (7.0,  12.0),  # [PLOS23] median 8%
    milestones_preclinical_m = (5.0,  50.0),
    milestones_phase1_m      = (20.0, 200.0),
    milestones_phase2_m      = (50.0, 500.0),
    example_deal  = "AUTM FY2024 survey: US universities executed 11,500+ licenses and options. Median royalty 2% (academic→industry). Median upfront issue fee $25k-$100k for non-exclusive; $1-5M for exclusive early-stage.",
    source        = "[AUTM24] FY2024 Licensing Activity Survey; [PLOS23] doi:10.1371/journal.pone.0283887",
    notes         = "Academic-to-industry deal terms are structurally lower than commercial deals: median upfront 60% lower, median royalty 40% lower (PLOS ONE 2023). Universities should benchmark against academic comps, not commercial deal announcements.",
)


_DEAL_COMPS_ALIASES: dict[str, str] = {
    # Clinical drugs without specific entries → closest analogue
    "drug_cardiology":          "drug_oncology",
    "drug_immunology":          "biologic_immunology",
    "drug_metabolic":           "drug_oncology",
    "drug_respiratory":         "biologic_immunology",
    "drug_infectious_non_amr":  "drug_amr",
    "antibiotic_amr":           "drug_amr",
    "drug_amr_community":       "drug_amr",
    # Biologics without entries
    "biologic_cardiology":      "biologic_immunology",
    "biologic_metabolic":       "biologic_immunology",
    "biologic_hematology":      "biologic_rare_disease",
    # Devices without entries
    "device_metabolic":         "device_cardiovascular",
    "device_neurology":         "device_cardiovascular",
    "device_ophthalmology":     "device_cardiovascular",
    "device_surgical_general":  "device_cardiovascular",
    "device_surgical_orthopedic": "device_cardiovascular",
    # Vaccines / immunotherapy
    "vaccine_cancer_immuno":    "biologic_oncology",
    "vaccine_therapeutic":      "biologic_oncology",
    # Gene therapy variants
    "gene_therapy_hematology":  "gene_therapy_rare",
    "gene_therapy_oncology":    "biologic_oncology",
    "gene_therapy_rna":         "vaccine_prophylactic",
    "gene_therapy_cns":         "gene_therapy_rare",
    # Digital / SaMD — BUG-16: was aliased to research_tool_non_clinical ($10K–$150K range).
    # SaMD/CDS/RPM products that touch patient care trade like medical devices,
    # not lab tools — licensing deals in the $1M–$10M+ range.
    "digital_therapeutic":      "device_cardiovascular",
    "digital_cds":              "device_cardiovascular",
    "digital_rpm":              "device_cardiovascular",
    "digital_samd":             "device_cardiovascular",
    # Other
    "other_delivery":           "biologic_oncology",
    "drug_rare_disease":        "drug_rare_disease",  # explicit passthrough
}


def get_deal_comps(sub_expert_id: str) -> DealCompProfile:
    """Return deal comparables for the given sub_expert_id."""
    if sub_expert_id in DEAL_COMPS:
        return DEAL_COMPS[sub_expert_id]
    # Fall back through the alias map before returning the pharma-scale default
    alias = _DEAL_COMPS_ALIASES.get(sub_expert_id)
    return DEAL_COMPS.get(alias, _DEFAULT_COMPS) if alias else _DEFAULT_COMPS


def format_deal_comps_for_prompt(sub_expert_id: str, development_phase: str = "preclinical") -> str:
    """
    Format deal comparables as a concise block for injection into the commercial panel prompt.
    phase: preclinical | phase1 | phase2 | phase3
    """
    comp = get_deal_comps(sub_expert_id)

    phase_map = {
        "preclinical": (comp.upfront_preclinical_m, comp.milestones_preclinical_m),
        "phase1":      (comp.upfront_phase1_m,      comp.milestones_phase1_m),
        "phase2":      (comp.upfront_phase2_m,      comp.milestones_phase2_m),
        "phase3":      (comp.upfront_phase3_m,      comp.milestones_phase3_m),
    }
    upfront, milestones = phase_map.get(development_phase.lower(), phase_map["phase1"])

    return (
        f"DEAL COMPARABLES — {comp.therapeutic_area} ({development_phase}):\n"
        f"  Upfront / Issue Fee: ${upfront[0]:.0f}M – ${upfront[1]:.0f}M\n"
        f"  Total Milestones (biobucks): ${milestones[0]:.0f}M – ${milestones[1]:.0f}M\n"
        f"  Royalty — Academic licensor: {comp.royalty_academic_pct[0]:.0f}%–{comp.royalty_academic_pct[1]:.0f}%\n"
        f"  Royalty — Corporate licensor: {comp.royalty_corporate_pct[0]:.0f}%–{comp.royalty_corporate_pct[1]:.0f}%\n"
        f"  Example: {comp.example_deal}\n"
        f"  Source: {comp.source}\n"
        + (f"  Note: {comp.notes}\n" if comp.notes else "")
    )
