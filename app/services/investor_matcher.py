"""
Investor Matcher — curated VC / funder database for biotech commercialization
=============================================================================
This is what PitchBook charges $24,000/user/year for in the investor-intelligence
layer: who is actively deploying capital into your specific therapeutic area and
development stage, and what they want to hear.

Sources:
  - AUTM Tech Transfer Practice Manual (university spinout pathways)
  - Fierce Biotech Fundraising Tracker 2025-2026
  - OpenVC / VC-mapping.gilion.com biotech investor lists
  - Published fund announcements and LP disclosures
  - BARDA / NIH / SBIR.gov grant data

Why this beats ChatGPT: ChatGPT will list the same 5 generic VCs regardless of
what you're building. This matcher routes on therapeutic area, development stage,
TRL, and whether it's an academic spinout — and returns personalized pitch rationale
for each investor.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class InvestorProfile:
    id:                  str
    name:                str
    type:                str          # vc | corporate_vc | government | family_office | crossover
    aum_bn:              Optional[float]   # AUM in $B
    therapeutic_areas:   List[str]   # sub_expert_ids or TA strings it focuses on
    stage_focus:         List[str]   # trl_range or "seed"/"seriesA"/"crossover"/"government_grant"
    trl_min:             int
    trl_max:             int
    check_size_m:        tuple[float, float]  # typical check ($M low, $M high)
    thesis:              str         # 1-2 sentence investment thesis
    notable_portfolio:   List[str]   # 3-5 known portfolio companies
    pitch_emphasis:      str         # what to emphasize when pitching THIS firm
    website:             str
    academic_friendly:   bool        # actively invests in university spinouts
    government_partner:  bool        # government grants / contracts not VC
    notes:               str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Investor Database
# ─────────────────────────────────────────────────────────────────────────────

INVESTORS: dict[str, InvestorProfile] = {

    # ── DEDICATED EARLY-STAGE BIOTECH VCs ─────────────────────────────────

    "arch_venture": InvestorProfile(
        id="arch_venture", name="ARCH Venture Partners", type="vc",
        aum_bn=9.0,
        therapeutic_areas=["all"],
        stage_focus=["inception", "seed", "series_a"],
        trl_min=1, trl_max=5,
        check_size_m=(5.0, 50.0),
        thesis="No molecule too early, no science too bold. ARCH co-founds companies around paradigm-shifting science — genomics, synthetic biology, gene therapy, novel mechanisms. They write the first check when a company is just an idea in a PI's lab.",
        notable_portfolio=["Juno Therapeutics", "Relay Therapeutics", "Lyell Immunopharma", "Caris Life Sciences", "Revolution Medicines"],
        pitch_emphasis="Emphasize the fundamental biology breakthrough. ARCH bets on scientific paradigm shifts, not incremental improvements. Show them why the mechanism is categorically different from current approaches, not just better.",
        website="archventure.com",
        academic_friendly=True,
        government_partner=False,
        notes="ARCH frequently co-founds companies with academic inventors. Direct relationship with TTO is a plus.",
    ),

    "flagship_pioneering": InvestorProfile(
        id="flagship_pioneering", name="Flagship Pioneering", type="vc",
        aum_bn=10.0,
        therapeutic_areas=["drug_oncology", "biologic_oncology", "gene_therapy_rare", "biologic_immunology", "drug_metabolic"],
        stage_focus=["inception", "company_creation"],
        trl_min=1, trl_max=4,
        check_size_m=(20.0, 200.0),
        thesis="Flagship creates companies from scratch around a 'protocompany' thesis — they identify a white space, assemble a team, and build. They rarely license in academic IP; instead they co-develop with inventors.",
        notable_portfolio=["Moderna", "Sana Biotechnology", "Larimar Therapeutics", "Generate:Biomedicines", "Tessera Therapeutics"],
        pitch_emphasis="Flagship doesn't respond well to standard pitch decks. Best approach: share the scientific insight and ask for a conversation about whether it aligns with a protocompany thesis they're developing. Don't focus on your company — focus on the insight.",
        website="flagshippioneeringcom",
        academic_friendly=True,
        government_partner=False,
        notes="Flagship rarely licenses academic IP directly — they prefer to co-found and own the IP. Best approached by the PI directly, not through TTO channels.",
    ),

    "third_rock": InvestorProfile(
        id="third_rock", name="Third Rock Ventures", type="vc",
        aum_bn=2.5,
        therapeutic_areas=["drug_oncology", "biologic_oncology", "drug_rare_disease", "biologic_rare_disease", "gene_therapy_rare", "biologic_immunology"],
        stage_focus=["seed", "series_a"],
        trl_min=3, trl_max=6,
        check_size_m=(10.0, 50.0),
        thesis="Company creation and seed stage. Third Rock builds transformative medicines companies from early science — they want to see a validated target, a mechanistic hypothesis, and a founding team that can execute.",
        notable_portfolio=["Blueprint Medicines", "Relay Therapeutics", "Imago BioSciences", "Accent Therapeutics", "Scholar Rock"],
        pitch_emphasis="Third Rock values rigorous genetics validation. Show them: (1) human genetic evidence linking target to disease, (2) a clear path to a clinically actionable biomarker, (3) scalability of the approach. They care deeply about team — who will lead this company.",
        website="thirdrock.vc",
        academic_friendly=True,
        government_partner=False,
    ),

    "orbimed": InvestorProfile(
        id="orbimed", name="OrbiMed Advisors", type="vc",
        aum_bn=18.3,
        therapeutic_areas=["all"],
        stage_focus=["series_a", "series_b", "crossover"],
        trl_min=4, trl_max=8,
        check_size_m=(20.0, 150.0),
        thesis="The largest dedicated healthcare investment firm globally. Invests across all stages (private venture through public equity) with deep expertise in oncology, rare disease, and immunology. Very analytical — they build their own financial models.",
        notable_portfolio=["Protagonist Therapeutics", "Turning Point Therapeutics", "Global Blood Therapeutics", "Syndax Pharmaceuticals"],
        pitch_emphasis="OrbiMed does thorough due diligence. Lead with your clinical data or, if pre-clinical, a very clear translational path to Phase 1. They want to understand approval probability, competitive differentiation, and market size — come prepared with all three.",
        website="orbimed.com",
        academic_friendly=False,
        government_partner=False,
        notes="OrbiMed manages both venture and public funds. For later-stage assets, they may invest both privately and in public market follow-ons.",
    ),

    "versant_ventures": InvestorProfile(
        id="versant_ventures", name="Versant Ventures", type="vc",
        aum_bn=2.4,
        therapeutic_areas=["drug_oncology", "biologic_oncology", "biologic_rare_disease", "drug_rare_disease", "biologic_immunology"],
        stage_focus=["inception", "seed", "series_a"],
        trl_min=2, trl_max=6,
        check_size_m=(5.0, 40.0),
        thesis="Company creation mode. Versant builds biotech companies from academic science, often serving as the founding incubator. They look for transformative biology with a clear path to a first-in-class medicine.",
        notable_portfolio=["Protagonist Therapeutics", "Morphic Therapeutic", "Turning Point Therapeutics", "Foresight Visions"],
        pitch_emphasis="Versant wants to understand the biology deeply. Come with a specific founding thesis — what company would be built around this technology? They prefer academic founders who are willing to step back and let a professional CEO build the company.",
        website="versantventures.com",
        academic_friendly=True,
        government_partner=False,
    ),

    "atlas_venture": InvestorProfile(
        id="atlas_venture", name="Atlas Venture", type="vc",
        aum_bn=0.7,
        therapeutic_areas=["drug_oncology", "biologic_oncology", "drug_rare_disease", "gene_therapy_rare", "drug_cns"],
        stage_focus=["seed", "series_a"],
        trl_min=3, trl_max=5,
        check_size_m=(5.0, 25.0),
        thesis="Genetics-enabled medicines. Atlas focuses on targets with human genetic validation — GWAS, Mendelian disease, somatic mutation in cancer. They heavily weight the strength of genetic evidence for the target.",
        notable_portfolio=["Vividion Therapeutics", "Actuate Therapeutics", "Imara", "Relay Therapeutics (co-founder)", "Proteovant Therapeutics"],
        pitch_emphasis="Genetics is everything to Atlas. If you have a variant of known pathogenic significance, a GWAS hit, or a somatic driver mutation — lead with that. Show them the genetic architecture linking your target to disease. Clean, validated human genetics can get you a first meeting.",
        website="atlasventure.com",
        academic_friendly=True,
        government_partner=False,
    ),

    "5am_ventures": InvestorProfile(
        id="5am_ventures", name="5AM Ventures", type="vc",
        aum_bn=1.0,
        therapeutic_areas=["drug_oncology", "biologic_oncology", "drug_rare_disease", "biologic_rare_disease", "drug_amr", "biologic_immunology"],
        stage_focus=["seed", "series_a"],
        trl_min=2, trl_max=5,
        check_size_m=(3.0, 20.0),
        thesis="Early-stage company builder focused on transformative medicines. 5AM invests at the seed and Series A stages, often co-founding with academic inventors. They have particular depth in oncology and rare disease.",
        notable_portfolio=["Corvus Pharmaceuticals", "Protagonist Therapeutics", "Nurix Therapeutics"],
        pitch_emphasis="5AM values scientific clarity and a specific first product. Come with: (1) a well-defined first indication with clear regulatory path, (2) the 2-3 experiments needed to validate the target, (3) a realistic estimate of what it takes to get to IND. They're practical operators, not just scientists.",
        website="5amventures.com",
        academic_friendly=True,
        government_partner=False,
    ),

    "ra_capital": InvestorProfile(
        id="ra_capital", name="RA Capital Management", type="vc",
        aum_bn=3.5,
        therapeutic_areas=["drug_oncology", "biologic_oncology", "drug_rare_disease", "biologic_rare_disease", "gene_therapy_rare", "biologic_immunology", "drug_cns"],
        stage_focus=["series_b", "crossover", "series_c"],
        trl_min=6, trl_max=8,
        check_size_m=(20.0, 150.0),
        thesis="Data-driven late private and crossover investing. RA Capital makes investment decisions based on rigorous clinical data analysis. They often lead crossover rounds just before IPO and are known for their deep clinical diligence.",
        notable_portfolio=["Imago BioSciences", "Protagonist Therapeutics", "Karuna Therapeutics", "Passage Bio"],
        pitch_emphasis="RA Capital will read every paper you've published. They want Phase 1/2 data with a clear interpretation of efficacy signal. Lead with your best clinical data point, explain exactly how it compares to approved drugs, and have a specific use-of-proceeds plan for the raised capital.",
        website="racap.com",
        academic_friendly=False,
        government_partner=False,
        notes="RA Capital is most active at late-stage private and crossover. Not a good fit for TRL < 6 or pre-IND assets.",
    ),

    "novo_ventures": InvestorProfile(
        id="novo_ventures", name="Novo Ventures (Novo Holdings)", type="vc",
        aum_bn=5.0,
        therapeutic_areas=["drug_metabolic", "biologic_immunology", "drug_oncology", "biologic_rare_disease", "drug_rare_disease", "biologic_oncology"],
        stage_focus=["seed", "series_a", "series_b"],
        trl_min=3, trl_max=7,
        check_size_m=(5.0, 75.0),
        thesis="The venture arm of Novo Holdings (which owns Novo Nordisk). Invests globally with particular strength in metabolic disease, obesity, and diabetes — areas where Novo Nordisk has strategic interest. Also active in rare disease and oncology.",
        notable_portfolio=["Protagonist Therapeutics", "Bicycle Therapeutics", "Cardior Pharmaceuticals"],
        pitch_emphasis="If your technology has any relationship to GLP-1, metabolic disease, obesity, or diabetes, Novo Ventures is your most natural investor — they have both financial and strategic reasons to invest. For other areas, emphasize scientific rigor and a clear clinical path.",
        website="novoholdings.dk/investments",
        academic_friendly=True,
        government_partner=False,
        notes="Novo Holdings has $100B+ AUM total; Novo Ventures is the early-stage venture arm. Strategic fit with Novo Nordisk's therapeutic areas is a major plus.",
    ),

    # ── CROSSOVER INVESTORS ────────────────────────────────────────────────

    "foresite_capital": InvestorProfile(
        id="foresite_capital", name="Foresite Capital", type="crossover",
        aum_bn=1.5,
        therapeutic_areas=["drug_oncology", "biologic_oncology", "gene_therapy_rare", "biologic_rare_disease", "drug_cns"],
        stage_focus=["series_b", "series_c", "crossover"],
        trl_min=6, trl_max=8,
        check_size_m=(25.0, 150.0),
        thesis="Crossover investor that bridges late private rounds and IPO. Foresite invests in companies with Phase 1/2 data showing proof of concept, and often leads the final private round before a public offering.",
        notable_portfolio=["Passage Bio", "Turning Point Therapeutics", "Scholar Rock"],
        pitch_emphasis="Foresite wants to see a clear path to an IPO within 18-24 months. Show them: Phase 2 data with a meaningful efficacy signal, a defined Phase 3 design, and evidence that the market will value the company at $500M+ on a public basis.",
        website="foresitecapital.com",
        academic_friendly=False,
        government_partner=False,
        notes="Crossover investors are not appropriate for early-stage academic spinouts. Best for TRL 7-8 with clinical data.",
    ),

    # ── CORPORATE VENTURE ──────────────────────────────────────────────────

    "johnson_innovation": InvestorProfile(
        id="johnson_innovation", name="Johnson & Johnson Innovation (JLABS)", type="corporate_vc",
        aum_bn=None,
        therapeutic_areas=["drug_oncology", "biologic_oncology", "biologic_immunology", "drug_rare_disease", "device_cardiovascular", "diagnostic_molecular"],
        stage_focus=["incubation", "seed", "series_a"],
        trl_min=2, trl_max=6,
        check_size_m=(0.5, 20.0),
        thesis="J&J Innovation provides incubation space (JLABS), strategic collaboration, and equity investment to companies that could become J&J acquisition or partnership targets. Strong in oncology, immunology, and med tech.",
        notable_portfolio=["Protagonist Therapeutics (early)", "Imago BioSciences (early collaboration)"],
        pitch_emphasis="J&J looks for strategic fit with their business units (Janssen for pharma, DePuy Synthes for orthopedics, etc.). Emphasize how your technology fills a gap in their current portfolio. JLABS residency is a non-dilutive option before seeking equity investment.",
        website="jnjinnovation.com",
        academic_friendly=True,
        government_partner=False,
        notes="JLABS incubator offers no-strings lab space in major biotech hubs. Good first step for early-stage university spinouts before raising a Series A.",
    ),

    "leaps_bayer": InvestorProfile(
        id="leaps_bayer", name="Leaps by Bayer", type="corporate_vc",
        aum_bn=0.4,
        therapeutic_areas=["gene_therapy_rare", "gene_therapy_oncology", "biologic_rare_disease", "drug_metabolic", "diagnostic_molecular"],
        stage_focus=["seed", "series_a", "series_b"],
        trl_min=2, trl_max=6,
        check_size_m=(5.0, 40.0),
        thesis="Bayer's impact investment arm focused on revolutionary advances in health and agriculture. Leaps takes high-risk bets on transformative biology — cell therapy, gene editing, organ regeneration, synthetic biology.",
        notable_portfolio=["BlueRock Therapeutics", "AskBio (gene therapy)", "Recursion Pharmaceuticals"],
        pitch_emphasis="Leaps wants to see a genuine paradigm shift — a technology that Bayer couldn't develop internally. Emphasize the transformative potential and why existing approaches are fundamentally limited. Their check is small ($5-40M) but their strategic value (access to Bayer's pharma infrastructure, global regulatory expertise) is significant.",
        website="leaps.bayer.com",
        academic_friendly=True,
        government_partner=False,
    ),

    "sr_one": InvestorProfile(
        id="sr_one", name="SR One (GSK Venture)", type="corporate_vc",
        aum_bn=0.8,
        therapeutic_areas=["biologic_immunology", "drug_oncology", "biologic_oncology", "drug_amr", "vaccine_prophylactic"],
        stage_focus=["series_a", "series_b"],
        trl_min=3, trl_max=6,
        check_size_m=(5.0, 30.0),
        thesis="GSK's independent venture arm. Invests in companies with potential for GSK partnership or acquisition — oncology, immunology, infectious disease, vaccines. Operates independently with its own financial returns mandate.",
        notable_portfolio=["Passage Bio", "Prelude Therapeutics"],
        pitch_emphasis="SR One acts independently but potential GSK strategic fit is a plus. Emphasize the competitive differentiation vs. approved products and a clear clinical development roadmap. Mention any overlap with GSK's current therapeutic focus areas.",
        website="srone.com",
        academic_friendly=True,
        government_partner=False,
    ),

    # ── ACADEMIC SPINOUT SPECIALISTS ───────────────────────────────────────

    "osage_university": InvestorProfile(
        id="osage_university", name="Osage University Partners", type="vc",
        aum_bn=0.35,
        therapeutic_areas=["all"],
        stage_focus=["inception", "seed"],
        trl_min=1, trl_max=4,
        check_size_m=(0.25, 3.0),
        thesis="The only VC firm specifically designed to invest in university spinouts at inception. Osage writes the first institutional check — $250k-$3M — specifically for technologies coming out of university TTO processes. They invest across all sectors and TRL 1-4.",
        notable_portfolio=["Multiple early-stage university spinouts across therapeutics, diagnostics, and medical devices"],
        pitch_emphasis="This is the most TTO-friendly investor on this list. They understand the TTO process, patent licenses, and exclusive licensing agreements intimately. Come with: (1) your patent filing status, (2) the exclusive license agreement terms, (3) what the first $1-2M will accomplish toward a Series A. They are specifically designed to bridge university IP to venture-fundable companies.",
        website="osagebio.com",
        academic_friendly=True,
        government_partner=False,
        notes="Osage University Partners is THE target investor for university TTOs. They explicitly co-invest with TTO exclusive licenses and know the academic IP commercialization process. Should be on every TTO's first-call list for early-stage spinouts.",
    ),

    "a16z_bio": InvestorProfile(
        id="a16z_bio", name="a16z Bio + Health", type="vc",
        aum_bn=2.7,
        therapeutic_areas=["digital_therapeutic", "digital_cds", "diagnostic_molecular", "drug_oncology", "biologic_oncology"],
        stage_focus=["seed", "series_a", "series_b"],
        trl_min=3, trl_max=7,
        check_size_m=(5.0, 75.0),
        thesis="Andreessen Horowitz's life sciences and health fund. Backs companies at the intersection of biology and technology — computational drug discovery, AI-enabled diagnostics, digital therapeutics, health tech platforms. Strong preference for software-enabled biology.",
        notable_portfolio=["Eikon Therapeutics", "Arc Institute", "Veritas Genetics", "Color Genomics"],
        pitch_emphasis="a16z values technology leverage. Lead with how software, AI, or computation enables your biology in a way that wasn't possible before. They are less interested in pure biology plays and more interested in how technology creates a durable competitive advantage. Have a clear data-driven story.",
        website="a16z.com/bio",
        academic_friendly=False,
        government_partner=False,
        notes="a16z is more likely to fund digital health or computational biology than traditional drug discovery at early stage. For pure biology, Third Rock or ARCH are better fits.",
    ),

    "gv_google": InvestorProfile(
        id="gv_google", name="GV (Google Ventures)", type="corporate_vc",
        aum_bn=8.0,
        therapeutic_areas=["diagnostic_molecular", "digital_therapeutic", "drug_oncology", "biologic_oncology"],
        stage_focus=["series_a", "series_b"],
        trl_min=4, trl_max=7,
        check_size_m=(5.0, 50.0),
        thesis="Google's venture arm. Focuses on technology-enabled biotech — precision medicine, diagnostics, computational drug discovery, and digital health. They value data assets and network effects in addition to pure science.",
        notable_portfolio=["Foundation Medicine", "Flatiron Health", "Editas Medicine (early)", "Verily Life Sciences"],
        pitch_emphasis="GV wants to see a data moat — a unique dataset, computational advantage, or technology platform that improves with scale. Show them the technology angle alongside the biology. If your approach has a platform potential (not just a single drug), that's a major plus.",
        website="gv.com",
        academic_friendly=False,
        government_partner=False,
    ),

    # ── GOVERNMENT / NON-DILUTIVE FUNDERS ─────────────────────────────────

    "barda": InvestorProfile(
        id="barda", name="BARDA (Biomedical Advanced Research and Development Authority)", type="government",
        aum_bn=None,
        therapeutic_areas=["drug_amr", "drug_amr_antibiotics", "vaccine_prophylactic"],
        stage_focus=["phase1", "phase2", "phase3"],
        trl_min=5, trl_max=8,
        check_size_m=(50.0, 500.0),
        thesis="BARDA provides non-dilutive US government contracts (OTAs, BAAs) for development of medical countermeasures including antibiotics, antivirals, vaccines, and diagnostics for public health emergencies and CBRN threats.",
        notable_portfolio=["Ceftazidime-avibactam (Avycaz)", "Cefiderocol (Fetroja)", "Multiple COVID-19 vaccines"],
        pitch_emphasis="BARDA is the key funding partner for Phase 2-3 antibiotic development. Your pitch must address: (1) the specific pathogen threat (ESKAPE pathogens, pandemic preparedness, CBRN), (2) alignment with BARDA's current BAA priorities, (3) manufacturing scale-up plan. BARDA contracts ($50M-$500M) can substitute for large commercial licensing deals.",
        website="medicalcountermeasures.gov",
        academic_friendly=True,
        government_partner=True,
        notes="BARDA is not a traditional investor — it's a US government contractor. Non-dilutive. Requires a US government security clearance process for some programs.",
    ),

    "carb_x": InvestorProfile(
        id="carb_x", name="CARB-X (Combating Antibiotic Resistant Bacteria Biopharmaceutical Accelerator)", type="government",
        aum_bn=None,
        therapeutic_areas=["drug_amr", "drug_amr_antibiotics"],
        stage_focus=["seed", "phase1"],
        trl_min=3, trl_max=6,
        check_size_m=(1.0, 12.0),
        thesis="CARB-X provides non-dilutive grants for early-stage antibiotic development. Funded by US BARDA, UK Wellcome Trust, and other partners. Covers Discovery through Phase 1 only — does NOT fund Phase 2 or later.",
        notable_portfolio=["Entasis Therapeutics", "Spero Therapeutics", "Bugworks Research"],
        pitch_emphasis="CARB-X requires ESKAPE pathogen or C.diff relevance + novel mechanism of action. Come with: (1) in vitro MIC data against the target pathogen, (2) proof that the mechanism is novel (not an analogue of existing drugs), (3) a clear path to Phase 1 IND. They fund up to $4.5M Phase 1 and $12M Phase 2 milestones.",
        website="carb-x.org",
        academic_friendly=True,
        government_partner=True,
        notes="CARB-X is the first call for any early-stage antibiotic program. Non-dilutive. Does NOT fund Phase 3.",
    ),

    "nih_sbir": InvestorProfile(
        id="nih_sbir", name="NIH SBIR/STTR Program", type="government",
        aum_bn=None,
        therapeutic_areas=["all"],
        stage_focus=["seed", "phase1"],
        trl_min=1, trl_max=5,
        check_size_m=(0.3, 2.5),
        thesis="The largest US federal small business innovation research program. SBIR Phase I: up to $300k for proof-of-concept. SBIR Phase II: up to $2M for full development. STTR version requires university subcontract (ideal for academic spinouts). Over $4B awarded annually.",
        notable_portfolio=["Thousands of early-stage biotech companies — many Series A companies had SBIR Phase II funding"],
        pitch_emphasis="SBIR proposals require: (1) Specific Aims page (1 page summary), (2) commercial potential section, (3) technical approach. For NIH, emphasize unmet medical need and innovation over standard of care. Phase I funds the proof-of-concept experiment. Phase II funds the development work. STTR is specifically for university-licensed technologies.",
        website="sbir.nih.gov",
        academic_friendly=True,
        government_partner=True,
        notes="SBIR is non-dilutive and the most accessible first funding source for academic spinouts. Every TTO should help PIs apply for SBIR Phase I before seeking venture capital.",
    ),

    "nci_sbir": InvestorProfile(
        id="nci_sbir", name="NCI SBIR Development Center", type="government",
        aum_bn=None,
        therapeutic_areas=["drug_oncology", "biologic_oncology", "diagnostic_molecular", "gene_therapy_oncology"],
        stage_focus=["seed", "series_a"],
        trl_min=2, trl_max=6,
        check_size_m=(0.3, 2.5),
        thesis="The National Cancer Institute's SBIR program is the largest cancer-focused small business grant program, awarding ~$150M/year. Unlike general NIH SBIR, NCI SBIR has bridge award and SBIR Phase IIB (commercialization) programs.",
        notable_portfolio=["Foundation Medicine (early SBIR)", "Multiple liquid biopsy and immunotherapy companies"],
        pitch_emphasis="NCI SBIR reviewers care deeply about: (1) unmet need in cancer (state the incidence, survival rate, current treatments), (2) novelty of approach vs. current standard of care, (3) technical feasibility (preliminary data). NCI also has the SBIR/STTR Program Contract Mechanism for more applied cancer drug development.",
        website="sbir.cancer.gov",
        academic_friendly=True,
        government_partner=True,
    ),

    "deerfield": InvestorProfile(
        id="deerfield", name="Deerfield Management", type="vc",
        aum_bn=15.1,
        therapeutic_areas=["all"],
        stage_focus=["series_a", "series_b", "crossover"],
        trl_min=4, trl_max=8,
        check_size_m=(20.0, 200.0),
        thesis="One of the largest healthcare-dedicated investment firms. Invests across all stages from venture through public, with a focus on healthcare transformation. Known for complex transactions: royalty financing, venture debt, structured equity.",
        notable_portfolio=["Widespread healthcare portfolio across therapeutics, devices, and healthcare services"],
        pitch_emphasis="Deerfield is interested in both financial returns and healthcare impact. They're known for creative deal structures — if traditional equity doesn't fit, explore royalty financing or venture debt. Show them a credible path to value creation and the capital efficiency of your plan.",
        website="deerfield.com",
        academic_friendly=False,
        government_partner=False,
        notes="Deerfield has multiple fund types including venture, royalty, and public equity. For early-stage, engage their venture team. For later-stage, royalty or debt financing may be appropriate.",
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# TA mapping: sub_expert_id → relevant investor IDs
# ─────────────────────────────────────────────────────────────────────────────

_TA_INVESTOR_MAP: dict[str, list[str]] = {
    "drug_amr":            ["arch_venture", "5am_ventures", "sr_one", "barda", "carb_x", "nih_sbir"],
    "drug_amr_antibiotics":["arch_venture", "5am_ventures", "sr_one", "barda", "carb_x", "nih_sbir"],
    "drug_oncology":       ["third_rock", "atlas_venture", "versant_ventures", "arch_venture", "orbimed", "5am_ventures", "ra_capital", "nci_sbir"],
    "biologic_oncology":   ["third_rock", "atlas_venture", "orbimed", "ra_capital", "foresite_capital", "johnson_innovation", "nci_sbir"],
    "gene_therapy_rare":   ["arch_venture", "versant_ventures", "third_rock", "leaps_bayer", "orbimed", "nih_sbir"],
    "gene_therapy_oncology":["arch_venture", "third_rock", "orbimed", "leaps_bayer", "nci_sbir"],
    "biologic_rare_disease":["arch_venture", "third_rock", "versant_ventures", "orbimed", "novo_ventures", "nih_sbir"],
    "drug_rare_disease":   ["arch_venture", "atlas_venture", "third_rock", "orbimed", "5am_ventures", "nih_sbir"],
    "drug_cns":            ["arch_venture", "atlas_venture", "versant_ventures", "ra_capital", "orbimed", "nih_sbir"],
    "drug_mental_health":  ["arch_venture", "5am_ventures", "orbimed", "nih_sbir"],
    "drug_metabolic":      ["novo_ventures", "arch_venture", "orbimed", "nih_sbir"],
    "drug_cardiology":     ["arch_venture", "orbimed", "deerfield", "nih_sbir"],
    "biologic_immunology": ["third_rock", "atlas_venture", "orbimed", "sr_one", "novo_ventures", "ra_capital"],
    "biologic_hematology": ["arch_venture", "third_rock", "orbimed", "ra_capital", "nih_sbir"],
    "device_cardiovascular":["orbimed", "gv_google", "deerfield", "johnson_innovation", "nih_sbir"],
    "device_metabolic":    ["orbimed", "novo_ventures", "deerfield", "nih_sbir"],
    "diagnostic_molecular":["a16z_bio", "gv_google", "orbimed", "johnson_innovation", "nci_sbir", "nih_sbir"],
    "digital_therapeutic": ["a16z_bio", "gv_google", "deerfield", "nih_sbir"],
    "digital_cds":         ["a16z_bio", "gv_google", "deerfield"],
    "vaccine_prophylactic":["arch_venture", "novo_ventures", "sr_one", "barda", "nih_sbir"],
}

_DEFAULT_INVESTORS = ["arch_venture", "orbimed", "nih_sbir", "osage_university", "deerfield"]


def get_matched_investors(
    sub_expert_id: str,
    trl_level: int,
    is_academic_spinout: bool = True,
    development_phase: str = "preclinical",
    top_n: int = 6,
) -> list[InvestorProfile]:
    """
    Return the top N most relevant investors for the given profile.
    Filters by:
      1. Therapeutic area alignment
      2. TRL / development stage fit
      3. Academic spinout friendliness (if applicable)
    """
    candidate_ids = list(dict.fromkeys(
        _TA_INVESTOR_MAP.get(sub_expert_id, _DEFAULT_INVESTORS)
        + (["osage_university"] if is_academic_spinout else [])
    ))

    candidates = [INVESTORS[cid] for cid in candidate_ids if cid in INVESTORS]

    # Filter by TRL fit
    def trl_score(inv: InvestorProfile) -> float:
        if inv.government_partner:
            return 1.5  # gov funders always relevant, boost them
        if inv.trl_min <= trl_level <= inv.trl_max:
            # Perfect match — prefer investors centered on this TRL
            center = (inv.trl_min + inv.trl_max) / 2
            return 1.0 - abs(trl_level - center) / max(1, inv.trl_max - inv.trl_min)
        # Partial match (within 1 level)
        elif abs(trl_level - inv.trl_min) <= 1 or abs(trl_level - inv.trl_max) <= 1:
            return 0.4
        return 0.0  # exclude

    scored = [(inv, trl_score(inv)) for inv in candidates]
    scored = [(inv, s) for inv, s in scored if s > 0]
    scored.sort(key=lambda x: (
        -x[1],
        -(1 if x[0].academic_friendly and is_academic_spinout else 0),
        -(1 if x[0].government_partner else 0),
    ))

    return [inv for inv, _ in scored[:top_n]]


def format_investors_for_prompt(
    sub_expert_id: str,
    trl_level: int,
    is_academic_spinout: bool = True,
    development_phase: str = "preclinical",
) -> str:
    """Format matched investors as a structured block for injection into the report."""
    investors = get_matched_investors(sub_expert_id, trl_level, is_academic_spinout, development_phase)
    if not investors:
        return ""

    lines = [
        "=== MATCHED INVESTOR & FUNDER INTELLIGENCE ===",
        "Based on therapeutic area, development stage, and academic spinout status.",
        "These are the investors/funders most likely to be receptive RIGHT NOW.",
        "",
    ]
    for i, inv in enumerate(investors, 1):
        check_fmt = (
            f"${inv.check_size_m[0]:.0f}M–${inv.check_size_m[1]:.0f}M"
            if inv.check_size_m[0] > 0 else "Variable (govt contract)"
        )
        aum_fmt = f"${inv.aum_bn:.1f}B AUM" if inv.aum_bn else "Government program"
        lines += [
            f"{i}. {inv.name} [{inv.type.replace('_', ' ').title()}] | {aum_fmt} | Check: {check_fmt}",
            f"   Thesis: {inv.thesis[:200]}",
            f"   Pitch emphasis: {inv.pitch_emphasis[:200]}",
            f"   Portfolio: {', '.join(inv.notable_portfolio[:3])}",
            f"   Website: {inv.website}",
            "",
        ]

    lines.append("=== END INVESTOR INTELLIGENCE ===")
    return "\n".join(lines)
