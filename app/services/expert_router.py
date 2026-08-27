"""
Expert Router — Mixture of Experts
====================================
Hybrid routing: PI selects a domain hint, Claude independently classifies
the idea text, and the router reconciles them.

Logic:
  1. If PI selected "auto" → use Claude classification only
  2. If PI selected a domain AND Claude agrees → proceed with that domain
  3. If PI selected a domain BUT Claude disagrees → Claude wins,
     but a mismatch warning is returned so the UI can show the PI

Returns:
  RouterResult(domain_id, expert, confidence, mismatch_warning)
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from app.core.config import settings
from app.services.expert_profiles import (
    ExpertProfile, EXPERT_REGISTRY, get_all_keywords, get_expert
)
from app.services.expert_profiles_v2 import get_sub_expert, SubExpertProfile
from app.services.product_archetype import ProductArchetype, resolve_archetype

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ROUTER_MODEL      = "claude-haiku-4-5-20251001"   # fast, cheap for routing
ROUTER_TIMEOUT    = 20.0


@dataclass
class RouterResult:
    domain_id:         str
    expert:            ExpertProfile
    confidence:        float          # 0.0 - 1.0
    pi_selected:       Optional[str]  # what the PI chose
    claude_classified: str            # what Claude classified
    mismatch_warning:  Optional[str]  # shown in UI if domains disagree
    routing_method:    str            # "auto" | "pi_confirmed" | "claude_override"
    # Modality axis — the granular v2 sub-expert that actually authors the report.
    # This is what stops a diagnostic/device/SaMD from being written by the drug
    # (antibiotic) expert. `sub_expert` carries the modality-correct system prompt.
    sub_expert:        Optional[SubExpertProfile] = None
    sub_expert_id:     Optional[str] = None   # e.g. "digital_cds", "device_neurology"
    modality:          Optional[str] = None   # tier1_category, e.g. "digital_health"
    archetype:         ProductArchetype = ProductArchetype.UNKNOWN


ROUTER_SYSTEM = """You are a precision medical domain classifier for a Mixture-of-Experts system. Given a healthcare innovation, classify it into exactly ONE subcategory from the list below. Be specific — choose the most granular match, not the broadest.

SMALL MOLECULE DRUGS:
- drug_amr: IV/oral antibiotics, beta-lactam/BLI combos, antifungals, antivirals for resistant pathogens (CRE, MRSA, VRE, Candida auris, C. diff)
- drug_amr_community: oral antibiotics for community-acquired infections (ABSSSI, CAP, UTI, STI), not hospital/ICU
- drug_oncology: small molecule kinase inhibitors, PARP inhibitors, chemotherapy, oral targeted therapy for solid tumors or hematologic cancers
- drug_cns_neurodegen: Alzheimer's, Parkinson's, ALS, FTD, HD — neurodegeneration drugs (not psychiatric)
- drug_cns_acute: epilepsy, migraine, stroke, headache, acute CNS conditions
- drug_metabolic: GLP-1/SGLT2/DPP4 for T2D/obesity, NASH/MASH, metabolic syndrome, lipid disorders (statins, PCSK9)
- drug_cardiovascular: heart failure (HFrEF/HFpEF), atrial fibrillation, hypertension, anticoagulants, coronary artery disease
- drug_immunology: small molecules for RA, psoriasis, IBD, lupus, atopic dermatitis (JAK inhibitors, PDE4i, S1P modulators)
- drug_respiratory: asthma, COPD, IPF, PAH, cystic fibrosis (inhaled and oral)
- drug_rare_disease: orphan small molecules for rare/ultra-rare genetic disorders
- drug_mental_health: antidepressants, antipsychotics, anxiolytics, ADHD, addiction, psychedelics for psychiatric indications
- drug_infectious_non_amr: antiviral (HIV, HCV, HBV, CMV, RSV), antimalarial, antiparasitic — NOT resistance-focused

BIOLOGICS:
- biologic_oncology: monoclonal antibodies, checkpoint inhibitors, bispecifics, ADCs for cancer
- biologic_immunology: TNF inhibitors, IL-6/IL-17/IL-23 antibodies, fusion proteins for autoimmune/inflammatory
- biologic_hematology: antibodies/proteins for sickle cell, hemophilia, MDS, leukemia/lymphoma (not small molecule)
- biologic_rare_disease: enzyme replacement, protein replacement for rare metabolic/lysosomal diseases
- biologic_cardiology: PCSK9 inhibitors, antibodies for cardiac conditions

GENE & CELL THERAPY:
- gene_therapy_rare: AAV gene therapy for rare monogenic diseases (SMA, DMD, hemophilia, retinal)
- gene_therapy_hematology: gene editing/therapy for hemoglobinopathies (SCD, thal), hemophilia, MDS
- gene_therapy_oncology: CAR-T, TCR-T, TIL therapy for solid tumors or hematologic cancers
- gene_therapy_cns: AAV/ASO/siRNA for CNS diseases (Huntington, SCA, prion, rare CNS)
- gene_therapy_rna: mRNA therapeutics, ASOs, siRNA, RNAi for any indication (non-vaccine)

DEVICES:
- device_cardiovascular: cardiac stents, pacemakers, ICD, EP ablation catheters, TAVI, heart failure devices
- device_neurology: DBS, spinal cord stimulation, BCI, vagus nerve stimulation, neuromodulation
- device_surgical_orthopedic: spinal implants, joint replacement, orthopedic fixation
- device_metabolic: insulin pumps, CGM, artificial pancreas (hardware, not software)
- device_surgical_general: surgical robots, laparoscopic devices, wound care, general surgical implants
- device_ophthalmology: IOLs, glaucoma drainage, retinal devices, ophthalmic surgical tools

DIAGNOSTICS:
- diagnostic_molecular_lab: lab-based NGS panels, PCR, NAAT, liquid biopsy, genomic tests requiring CLIA lab
- diagnostic_companion: FDA co-approved companion diagnostics linked to specific targeted therapies
- diagnostic_poc: point-of-care tests (lateral flow, rapid antigen, bedside devices, CLIA-waived)
- diagnostic_imaging_ai: AI algorithms for radiology (CT, MRI, X-ray), pathology slide analysis, echocardiography AI
- diagnostic_biomarker: blood/urine/CSF biomarker tests (not genomic) for disease monitoring or dx

DIGITAL HEALTH / SaMD:
- digital_cds: AI clinical decision support integrated into hospital EHR workflow (sepsis, deterioration, drug dosing)
- digital_rpm: remote patient monitoring platforms (wearable sensors, cardiac monitoring, COPD management)
- digital_therapeutic: prescription digital therapeutics (FDA-cleared DTx for CBT, substance abuse, chronic disease)
- digital_samd_radiology: standalone AI imaging analysis software for radiology/pathology (not EHR-embedded)

VACCINES & IMMUNOTHERAPY:
- vaccine_prophylactic: preventive vaccines for infectious diseases (RSV, flu, COVID, pneumococcal, meningococcal)
- vaccine_cancer_immuno: therapeutic cancer vaccines, neoantigen vaccines, tumor-infiltrating lymphocyte therapies
- vaccine_infectious_therapeutic: therapeutic vaccines for chronic infections (HIV, HBV, HPV treatment)

PLATFORMS:
- other_crispr: CRISPR-Cas9, base editing, prime editing tools/platforms for any indication
- other_microbiome: live biotherapeutic products (LBPs), microbiome modulation, FMT
- other_delivery: novel drug delivery platforms (LNPs, nanoparticles, antibody conjugates excluding ADCs)

RESEARCH TOOLS & NON-CLINICAL INFRASTRUCTURE:
- research_tool_non_clinical: data logging hardware/software, sync platforms, experimental recording systems, lab wearables, or hardware sold ONLY to academic PIs/labs for research — NOT clinical care. No clinical indication. Buyers are PIs, core facilities, TTOs. Examples: Hublink, Open Ephys, ActiGraph (research tier), Movisens, LabArchives. If the buyer is an academic PI and there is no clinical claim, classify here even if it involves sensors or remote data collection.
- research_tool_agronomy: soil sensors, moisture meters, precision agriculture instruments, crop monitoring hardware, field weather stations, dielectric permittivity probes, nutrient sensors, irrigation control hardware, agronomy data loggers — any sensor or instrument used in agricultural research, precision farming, or soil science. Buyers are agricultural researchers, agronomy departments, extension services, or farmers optimizing crop yield. No clinical indication, no human patient.
- research_infrastructure_saas: LIMS, ELN, scheduling software, data management platforms, TTOmanagement tools sold to academic institutions or research departments. No clinical indication.

CRITICAL DISAMBIGUATION — digital_rpm vs research_tool_non_clinical:
- digital_rpm: sold to HOSPITALS or CLINICIANS for patient monitoring with a reimbursement pathway (CPT 99453-99458). Clinical indication required.
- research_tool_non_clinical: sold to academic LABS or PIs for research data collection. No clinical pathway. If in doubt and the buyer is a PI or research group, choose research_tool_non_clinical.

Respond ONLY with valid JSON (no explanation outside JSON):
{"domain": "<domain_id>", "confidence": <0.0-1.0>, "reasoning": "<one sentence explaining key classification signals>"}

Pick the MOST SPECIFIC matching subcategory. When in doubt between broad and specific, choose specific."""


async def classify_with_claude(idea: str) -> tuple[str, str, float, str]:
    """Classify the idea. Returns (sub_expert_id, top_level_domain, confidence, reasoning).

    - sub_expert_id: the GRANULAR v2 id (e.g. "digital_cds", "device_neurology") that
      selects the modality-correct expert. Never collapsed to a drug default.
    - top_level_domain: a guaranteed-valid v1 EXPERT_REGISTRY key, for disease-context
      callers only.
    """
    try:
        async with httpx.AsyncClient(timeout=ROUTER_TIMEOUT) as client:
            r = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key":         settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":       ROUTER_MODEL,
                    "max_tokens":  150,
                    "temperature": 0,
                    "system":      ROUTER_SYSTEM,
                    "messages":    [{"role": "user", "content": f"Classify this healthcare innovation:\n\n{idea[:1000]}"}],
                }
            )
            r.raise_for_status()
            text = r.json()["content"][0]["text"].strip()
            # Parse JSON
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text.strip())
            raw_domain = data.get("domain", "")
            confidence = float(data.get("confidence", 0.7))
            reasoning  = data.get("reasoning", "")
            # Validate Claude returned a known sub-expert key. If it returned empty,
            # a top-level registry key (e.g. "antibiotic_amr"), or any hallucinated
            # string, those are not in _ROUTER_TO_EXPERT and would produce sub_expert_id
            # values that get_sub_expert() can't resolve — causing a silent fallback to
            # the v1 AMR expert. Keyword classify only returns known valid IDs.
            if raw_domain not in _ROUTER_TO_EXPERT:
                logger.info(
                    "classify_with_claude: domain '%s' not in router map — "
                    "falling back to keyword classify", raw_domain,
                )
                raw_domain = _keyword_classify(idea)
                confidence = min(confidence, 0.60)
            sub_expert_id = _ROUTER_TO_EXPERT.get(raw_domain, raw_domain)
            top_level     = _coerce_to_registry(sub_expert_id)
            return sub_expert_id, top_level, confidence, reasoning
    except Exception as e:
        logger.warning(f"Claude router failed: {e} — falling back to keyword classification")
        raw = _keyword_classify(idea)
        sub_expert_id = _ROUTER_TO_EXPERT.get(raw, raw)
        top_level     = _coerce_to_registry(sub_expert_id)
        return sub_expert_id, top_level, 0.6, "Classified by keyword matching (Claude router unavailable)"


_ROUTER_KEYWORD_MAP: dict[str, list[str]] = {
    "drug_amr":               ["antibiotic","antimicrobial","beta-lactam","carbapenem","ceftazidime","avibactam","meropenem","colistin","cre","mrsa","vre","esbl","acinetobacter","klebsiella","pseudomonas","hospital-acquired","ventilator-associated","bacteremia","sepsis drug","iv antibiotic","gram-negative","gram-positive resistant"],
    "drug_amr_community":     ["oral antibiotic","community-acquired","absssi","skin infection","uti","urinary tract","pneumonia outpatient","sexually transmitted","gonorrhea","chlamydia","strep","community mrsa"],
    "drug_oncology":          ["kinase inhibitor","parp","tyrosine kinase","solid tumor small molecule","oral cancer","ras inhibitor","kras","braf","mek","cdk4","cdk6","palbociclib","ribociclib","chemotherapy","oral targeted"],
    "drug_cns_neurodegen":    ["alzheimer","parkinson","als ","amyloid","tau","alpha-synuclein","neurodegeneration","huntington","frontotemporal","prion","lewy body"],
    "drug_cns_acute":         ["epilepsy","seizure","migraine","stroke","acute cns","headache","anti-epileptic","anticonvulsant"],
    "drug_metabolic":         ["glp-1","semaglutide","sglt2","dpp4","metformin","insulin sensitizer","obesity drug","nash","mash","lipid","statin","pcsk9 small","metabolic drug"],
    "drug_cardiovascular":    ["heart failure drug","hfref","hfpef","atrial fibrillation drug","anticoagulant","antihypertensive","ace inhibitor","arb ","sacubitril","entresto","coronary drug"],
    "drug_immunology":        ["jak inhibitor","jak1","jak2","tyk2","pde4","s1p modulator","ozanimod","ozanimod","small molecule autoimmune","oral immunology"],
    "drug_respiratory":       ["asthma drug","copd drug","ipf","pulmonary fibrosis","cystic fibrosis cftr","tezacaftor","ivacaftor","inhaled","bronchodilator","pah "],
    "drug_rare_disease":      ["rare disease drug","orphan drug","enzyme replacement small","lysosomal small","gaucher small","fabry small","phenylketonuria","pku"],
    "drug_mental_health":     ["antidepressant","ssri","snri","antipsychotic","anxiolytic","adhd drug","bipolar drug","addiction treatment","psilocybin","ketamine","mdma","psychiatric","schizophrenia drug"],
    "drug_infectious_non_amr":["antiviral","hiv drug","hcv drug","hbv drug","cmv","rsv antiviral","influenza antiviral","antimalarial","antiparasitic","herpetic","chronic viral"],
    "biologic_oncology":      ["checkpoint inhibitor","pd-1","pd-l1","ctla-4","her2 antibody","adc","antibody-drug conjugate","bispecific","cancer antibody","monoclonal antibody cancer","t-dxd","enhertu"],
    "biologic_immunology":    ["tnf inhibitor","il-6","il-17","il-23","il-4","il-13","il-31","dupilumab","secukinumab","ixekizumab","ustekinumab","autoimmune biologic","inflammatory biologic"],
    "biologic_hematology":    ["sickle cell biologic","hemophilia antibody","mds biologic","lymphoma antibody","leukemia biologic","blinatumomab","elotuzumab","daratumumab","anti-cd"],
    "biologic_rare_disease":  ["enzyme replacement","elosulfase","alglucosidase","agalsidase","imiglucerase","protein replacement","rare biologic","lysosomal biologic"],
    "biologic_cardiology":    ["pcsk9 antibody","evolocumab","alirocumab","inclisiran","cardiac biologic","heart antibody"],
    "gene_therapy_rare":      ["aav9","aav8","aav5","aav ","aav-","gene therapy","gene replacement","gene correction","sma gene","sma type","spinal muscular atrophy","dmd gene","duchenne gene","hemophilia gene","retinal gene","lca ","zolgensma","luxturna","gene rare","monogenic gene","aav delivered","aav-based","gene editing rare","exon skipping","exon-skipping","dystrophin restore","morpholino"],
    "gene_therapy_hematology":["sickle cell gene","thalassemia gene","casgevy","lyfgenia","hemoglobinopathy gene","gene editing blood","base editing blood","gene therapy blood","bcl11a","globin gene"],
    "gene_therapy_oncology":  ["car-t","car t","tcr therapy","til therapy","tumor-infiltrating","kymriah","yescarta","breyanzi","cilta-cel","ide-cel","adoptive cell","t cell cancer gene","engineered t cell"],
    "gene_therapy_cns":       ["huntington gene","spinocerebellar ataxia","prion gene","rett gene","cns gene therapy","gene editing brain","aav cns","intrathecal gene","neurological gene therapy"],
    "gene_therapy_rna":       ["antisense oligonucleotide","aso ","sirna","rnai","mrna therapeutic","lnp rna","inotersen","patisiran","givosiran","lumasiran","inclisiran rna","rna therapy","base editing","prime editing","exon skipping aso","rna interference"],
    "device_cardiovascular":  ["cardiac stent","pacemaker","icd defibrillator","tavi","tavr","structural heart","ep catheter","ablation catheter","cardiac device","left atrial appendage","watchman","heart valve device"],
    "device_neurology":       ["deep brain stimulation","dbs ","spinal cord stimulator","scs ","vagus nerve","bci ","brain computer interface","neuromodulation device","neuropace","medtronic brain"],
    "device_surgical_orthopedic":["spinal implant","vertebral","spinal fusion device","joint replacement","orthopedic implant","hip implant","knee implant","trauma fixation"],
    "device_metabolic":       ["insulin pump","cgm device","continuous glucose monitor","artificial pancreas","dexcom","omnipod","freestyle libre","glucose device"],
    "device_surgical_general":["surgical robot","laparoscopic device","robotic surgery","wound device","hernia mesh","general surgical implant","davinci"],
    "device_ophthalmology":   ["iol","intraocular lens","glaucoma drain","retinal implant","ophthalmic device","eye implant","intravitreal device","cochlear implant","cochlear device","hearing implant","hearing device"],
    "diagnostic_molecular_lab":["ngs panel","next-generation sequencing","liquid biopsy","genomic test","pcr test","naat","molecular lab","whole exome","whole genome","clia lab","foundationone","guardant"],
    "diagnostic_companion":   ["companion diagnostic","cdx","fda-approved companion","biomarker test linked","her2 test","egfr test","pd-l1 test","msi test","braf test"],
    "diagnostic_poc":         ["point-of-care","rapid test","lateral flow","poc test","clia-waived","bedside test","rapid antigen","home test","dipstick","fingerstick"],
    "diagnostic_imaging_ai":  ["radiology ai","pathology ai","ct scan ai","mri ai","x-ray algorithm","echocardiography ai","imaging algorithm","slide analysis","digital pathology ai"],
    "diagnostic_biomarker":   ["blood biomarker","urine biomarker","csf biomarker","serum test","troponin","bnp","crp test","biomarker test","non-genomic biomarker"],
    "digital_cds":            ["clinical decision support","cds ","ehr integration","sepsis alert","deterioration alert","drug dosing algorithm","epic integration","hospital workflow ai","nurse alert","sepsis detection","early warning score","deterioration prediction","ai icu","ai hospital","samd","saas hospital","health system ai"],
    "digital_rpm":            ["remote patient monitoring","rpm platform","wearable monitor","cardiac monitoring","copd monitoring","telehealth monitor","connected care","home monitoring"],
    "digital_therapeutic":    ["digital therapeutic","dtx","prescription digital","cbt digital","substance abuse app","mental health app","chronic disease app","pear therapeutics","somryst"],
    "digital_samd_radiology": ["radiology samd","pathology samd","imaging samd","ai radiology standalone","diagnostic ai software","image analysis software"],
    "vaccine_prophylactic":   ["prophylactic vaccine","preventive vaccine","rsv vaccine","flu vaccine","covid vaccine","pneumococcal","meningococcal","hpv vaccine","mmr","acip vaccine"],
    "vaccine_cancer_immuno":  ["cancer vaccine","neoantigen vaccine","therapeutic cancer vaccine","mrna cancer","personalized vaccine","mrna-4157","til vaccine","tumor vaccine"],
    "vaccine_infectious_therapeutic":["hiv vaccine therapeutic","hbv therapeutic vaccine","hpv therapeutic","hepatitis therapeutic vaccine"],
    "other_crispr":           ["crispr","cas9","base editor","prime editor","crispr tool","gene editing platform","beam therapeutics","prime medicine"],
    "other_microbiome":       ["microbiome","live biotherapeutic","lbp","fmt","fecal transplant","gut bacteria","microbiota","seres","ferring rebiotix"],
    "other_delivery":         ["lnp platform","lipid nanoparticle","nanoparticle delivery","drug delivery platform","targeted delivery","antibody conjugate non-adc"],
    "research_tool_non_clinical": [
        "data logger","data logging","sync platform","research platform","lab infrastructure",
        "open ephys","recording system","experimental hardware","actiwatch","actigraph research",
        "movisens","empatica research","hublink","neurotech hub","academic pi buyer",
        "per-lab license","nih grant funded","long-duration recording","unattended recording",
        "field research hardware","iot research","pi market","research data platform",
        "lab software","research wearable","ecophysiology","animal research sensor",
        "research tool","not clinical","non-clinical","lab management software",
    ],
    "research_tool_agronomy": [
        "soil moisture","soil sensor","dielectric permittivity","soil water content",
        "precision agriculture","agronomy sensor","crop monitoring","field sensor",
        "irrigation sensor","soil probe","volumetric water content","soil temperature",
        "agricultural sensor","farm sensor","nutrient sensor","soil salinity",
        "tdr probe","tdr soil","capacitance sensor soil","weather station farm",
        "precision farming","soil science instrument","agronomy data logger",
        "soil moisture meter","crop yield sensor","field weather","soil monitoring",
    ],
    "research_infrastructure_saas": [
        "lims","laboratory information management","eln","electronic lab notebook",
        "research scheduling","tto software","tech transfer software","lab notebook",
        "sample tracking","research data management","rdm platform","institutional repository",
    ],
}

# Mapping from router domain IDs to sub_expert_id in expert_profiles_v2
_ROUTER_TO_EXPERT: dict[str, str] = {
    "drug_amr":                    "drug_amr",
    "drug_amr_community":          "drug_amr",
    "drug_oncology":               "drug_oncology",
    "drug_cns_neurodegen":         "drug_cns",
    "drug_cns_acute":              "drug_cns",
    "drug_metabolic":              "drug_metabolic",
    "drug_cardiovascular":         "drug_cardiology",
    "drug_immunology":             "drug_immunology",
    "drug_respiratory":            "drug_infectious_non_amr",
    "drug_rare_disease":           "drug_rare_disease",
    "drug_mental_health":          "drug_mental_health",
    "drug_infectious_non_amr":     "drug_infectious_non_amr",
    "biologic_oncology":           "biologic_oncology",
    "biologic_immunology":         "biologic_immunology",
    "biologic_hematology":         "biologic_hematology",
    "biologic_rare_disease":       "biologic_rare_disease",
    "biologic_cardiology":         "biologic_cardiology",
    "gene_therapy_rare":           "gene_therapy_rare",
    "gene_therapy_hematology":     "gene_therapy_hematology",
    "gene_therapy_oncology":       "gene_therapy_oncology",
    "gene_therapy_cns":            "gene_therapy_cns",
    "gene_therapy_rna":            "gene_therapy_rna",
    "device_cardiovascular":       "device_cardiovascular",
    "device_neurology":            "device_neurology",
    "device_surgical_orthopedic":  "device_neurology",
    "device_metabolic":            "device_metabolic",
    "device_surgical_general":     "device_cardiovascular",
    "device_ophthalmology":        "device_cardiovascular",
    "diagnostic_molecular_lab":    "diagnostic_molecular",
    "diagnostic_companion":        "diagnostic_companion",
    "diagnostic_poc":              "diagnostic_molecular",
    "diagnostic_imaging_ai":       "digital_cds",
    "diagnostic_biomarker":        "diagnostic_molecular",
    "digital_cds":                 "digital_cds",
    "digital_rpm":                 "digital_rpm",
    "digital_therapeutic":         "digital_therapeutic",
    "digital_samd_radiology":      "digital_cds",
    "vaccine_prophylactic":        "vaccine_prophylactic",
    "vaccine_cancer_immuno":       "vaccine_cancer_immuno",
    "vaccine_infectious_therapeutic": "vaccine_prophylactic",
    "other_crispr":                "other_crispr",
    "other_microbiome":            "other_microbiome",
    "other_delivery":              "other_delivery",
    "research_tool_non_clinical":  "research_tool_non_clinical",
    "research_tool_agronomy":      "research_tool_agronomy",
    "research_infrastructure_saas": "research_infrastructure_saas",
}


# Default top-level expert when nothing else resolves (must be a valid EXPERT_REGISTRY key).
_DEFAULT_DOMAIN = "antibiotic_amr"

# Set of all medical modality sub-expert IDs (excludes research-tool categories).
# Used by H-02 to detect when Claude has assigned a clinical expert to a non-clinical product.
_MEDICAL_MODALITIES: frozenset[str] = frozenset(_ROUTER_TO_EXPERT.keys()) - frozenset((
    "research_tool_non_clinical", "research_tool_agronomy",
    "research_infrastructure_saas",
))

# Coarse keyword → one of the 6 top-level EXPERT_REGISTRY domains. Used to coerce
# granular router/sub-expert ids (e.g. "drug_amr", "biologic_oncology") — which are
# NOT registry keys — down to a valid top-level expert, so the registry lookup in
# route() can never KeyError.
_TOPLEVEL_HINTS = [
    ("antibiotic_amr",    ("amr", "antibiotic", "antimicrobial", "infect", "antiviral", "vaccine", "sepsis")),
    ("oncology",          ("oncolog", "cancer", "tumor", "carcinom", "leukemia", "lymphoma", "car-t", "car_t")),
    ("cardiology",        ("cardio", "cardiac", "heart", "vascular", "hematolog", "blood")),
    ("neurology_cns",     ("cns", "neuro", "brain", "alzheimer", "parkinson", "epilep", "psych_cns")),
    ("metabolic_diabetes",("metabolic", "diabet", "obesity", "glp", "nash", "mash", "lipid", "renal", "device_metabolic")),
    ("mental_health",     ("mental", "depress", "psych", "anxiety", "bipolar", "schizo", "addiction")),
]


def _coerce_to_registry(domain: str) -> str:
    """Map ANY classifier output to a valid EXPERT_REGISTRY key. Never raises."""
    if domain in EXPERT_REGISTRY:
        return domain
    d = (domain or "").lower()
    for top, hints in _TOPLEVEL_HINTS:
        if any(h in d for h in hints):
            return top
    return _DEFAULT_DOMAIN


def _keyword_classify(idea: str) -> str:
    """Fast keyword-based fallback classifier using granular subcategory keywords."""
    idea_lower = idea.lower()
    scores: dict[str, int] = {}
    for domain_id, keywords in _ROUTER_KEYWORD_MAP.items():
        score = sum(1 for kw in keywords if kw in idea_lower)
        if score > 0:
            scores[domain_id] = score
    if not scores:
        # Ultimate fallback: try legacy expert registry
        try:
            all_keywords = get_all_keywords()
            for domain_id, keywords in all_keywords.items():
                score = sum(1 for kw in keywords if kw in idea_lower)
                if score > 0:
                    scores[domain_id] = score
        except Exception:
            pass
    if not scores:
        # Before defaulting to any drug modality, check for explicit non-biomedical signals.
        # Agricultural, industrial, environmental, and consumer products must never be
        # routed to a clinical expert just because they had no keyword hits.
        idea_l = idea.lower()
        _NON_BIO_KWS = (
            # Agriculture / agronomy
            "soil moisture", "soil sensor", "soil probe", "precision agriculture",
            "agronomy", "crop monitoring", "crop yield", "irrigation sensor",
            "farm sensor", "farm management", "field weather station",
            "food production", "food safety testing", "agricultural sensor",
            # Energy / physical sciences
            "solar panel", "photovoltaic", "solar cell", "renewable energy",
            "wind turbine", "battery storage", "energy storage", "fuel cell",
            "semiconductor device", "materials testing", "metallurgy",
            "computational fluid", "finite element",
            # Industrial / consumer / civil
            "industrial iot", "smart home", "air quality monitor",
            "environmental sensor", "consumer product", "retail analytics",
            "logistics tracking", "supply chain sensor",
            "water quality sensor", "groundwater", "wastewater",
            "structural health monitoring", "geotechnical",
        )
        if any(kw in idea_l for kw in _NON_BIO_KWS):
            # Distinguish agronomy (USDA buyer) from general non-clinical research tool.
            _AGRONOMY_SIGNALS = (
                "soil", "agronomy", "crop", "irrigation", "farm",
                "precision agri", "agricultural",
            )
            if any(s in idea_l for s in _AGRONOMY_SIGNALS):
                return "research_tool_agronomy"
            return "research_tool_non_clinical"
        return "drug_oncology"
    return max(scores, key=scores.get)


async def route(
    idea:        str,
    pi_domain:   Optional[str] = None,   # what PI selected ("auto" or domain_id)
) -> RouterResult:
    """
    Main routing function.
    Returns a RouterResult with the selected expert and routing metadata.
    """
    # Normalize
    pi_domain = pi_domain or "auto"
    if pi_domain not in EXPERT_REGISTRY and pi_domain != "auto":
        logger.warning(f"Unknown PI domain '{pi_domain}' — treating as auto")
        pi_domain = "auto"

    # Classify with Claude. sub_expert_id is the GRANULAR modality expert (e.g.
    # "digital_cds"); claude_domain is the coerced top-level v1 key (disease context).
    sub_expert_id, claude_domain, confidence, reasoning = await classify_with_claude(idea)
    logger.info(f"Claude classified: sub_expert={sub_expert_id} top_level={claude_domain} (confidence={confidence:.2f})")

    # H-01 lightweight guard: Haiku occasionally misclassifies research data platforms
    # as digital_rpm (both involve "wearable sensors" and "remote"). Check for
    # non-clinical research signals that rule out a clinical RPM product.
    if sub_expert_id in ("digital_rpm", "digital_cds", "digital_therapeutic"):
        _CLINICAL_SIGNALS = ("patient", "clinical", "hospital", "physician", "clinician",
                             "reimburs", "cpt ", "medicare", "medicaid", "ehr", "emr",
                             "payer", "insurance", "billing", "inpatient", "outpatient",
                             "diagnosis", "treatment", "therapy", "drug", "dose")
        _research_kws = _ROUTER_KEYWORD_MAP.get("research_tool_non_clinical", [])
        idea_l = idea.lower()
        _has_research = any(k in idea_l for k in _research_kws)
        _has_clinical = any(k in idea_l for k in _CLINICAL_SIGNALS)
        if _has_research and not _has_clinical:
            logger.info(
                "H-01: %s overridden → research_tool_non_clinical "
                "(research signals present, no clinical signals in idea text)", sub_expert_id
            )
            sub_expert_id = "research_tool_non_clinical"
            claude_domain = _coerce_to_registry(sub_expert_id)
            confidence    = min(confidence, 0.75)
            reasoning     = f"Corrected from {sub_expert_id}: non-clinical research-tool signals, no patient/clinical signals."

    # H-02: Explicit non-biomedical signal guard — catches products whose idea text
    # contains clear non-medical domain signals (agriculture, energy, materials,
    # industrial, consumer) and no clinical signals. The signal list is intentionally
    # broad; H-03 below handles everything outside this list via a different mechanism.
    if sub_expert_id in _MEDICAL_MODALITIES:
        idea_l = idea.lower()
        _NON_BIO_H02 = (
            # Agriculture / agronomy
            "soil moisture", "soil sensor", "soil probe", "soil water", "soil science",
            "precision agriculture", "agronomy", "crop monitoring", "crop yield",
            "irrigation sensor", "farm management", "farm sensor", "field weather",
            "agricultural sensor", "agronomy data", "soil salinity", "soil temperature",
            "food production", "food safety",
            # Energy / physical sciences
            "solar panel", "photovoltaic", "solar cell", "renewable energy", "wind turbine",
            "battery storage", "energy storage", "fuel cell", "thermoelectric",
            "semiconductor device", "materials testing", "metallurgy", "nanotechnology",
            "computational fluid", "finite element", "structural analysis",
            # Industrial / consumer
            "industrial iot", "smart home", "air quality monitor",
            "environmental monitoring sensor", "consumer wearable fitness",
            "retail analytics", "logistics tracking", "supply chain sensor",
            # Civil / environmental engineering
            "water quality sensor", "groundwater", "wastewater treatment",
            "structural health monitoring", "bridge sensor", "geotechnical",
        )
        _CLINICAL_H02 = (
            "patient", "clinical trial", "hospital", "physician", "disease treatment",
            "fda approval", "therapeutic indication", "drug approval", "diagnosis",
            "payer", "reimbursement", "medicare", "medicaid", "ehr", "emr",
            "clinical claim", "prescriber",
        )
        _has_non_bio = any(s in idea_l for s in _NON_BIO_H02)
        _has_clinical = any(s in idea_l for s in _CLINICAL_H02)
        if _has_non_bio and not _has_clinical:
            _prev = sub_expert_id
            sub_expert_id = "research_tool_agronomy" if any(
                s in idea_l for s in ("soil", "agronomy", "crop", "irrigation", "farm", "precision agri")
            ) else "research_tool_non_clinical"
            claude_domain = _coerce_to_registry(sub_expert_id)
            confidence    = min(confidence, 0.65)
            reasoning     = (
                f"H-02 override from '{_prev}': non-biomedical product signals "
                "detected with no clinical indicator — routed to research tool expert."
            )
            logger.info(
                "H-02: '%s' overridden → '%s' (non-biomedical signals, no clinical signals)",
                _prev, sub_expert_id,
            )

    # H-03: Drug modality + no medical language guard.
    # H-02 requires the idea to contain explicit non-medical keywords. H-03 takes
    # the complementary approach: if Claude classified the idea as a DRUG but the
    # idea text contains ZERO recognizable medical language, it is almost certainly
    # a misclassification — real drug candidates mention patients, disease, clinical
    # trials, or drug-mechanism terms. This catches materials science, energy, civil
    # engineering, and any other non-medical product that slips past H-02's keyword list.
    # Confidence gate (< 0.60) prevents overriding genuine drug ideas with unusual wording.
    _DRUG_MODALITIES_H03 = frozenset(k for k in _ROUTER_TO_EXPERT if k.startswith("drug_"))
    if sub_expert_id in _DRUG_MODALITIES_H03 and confidence < 0.60:
        idea_l = idea.lower()
        _MEDICAL_LANGUAGE = (
            "patient", "clinical", "hospital", "disease", "disorder", "syndrome",
            "therapeutic", "treatment", "therapy", "indication", "diagnosis",
            "cancer", "tumor", "infection", "pathogen", "bacteria", "virus",
            "fda", "nda ", "ind ", "investigational", "clinical trial",
            "adverse", "efficacy", "safety", "pharmacology", "pharmacokinetic",
            "receptor", "inhibitor", "kinase", "antibody", "biologic",
            "antimicrobial", "antibiotic", "antiviral", "drug candidate",
            "patients with", "disease prevalence", "standard of care",
        )
        _has_medical = any(s in idea_l for s in _MEDICAL_LANGUAGE)
        if not _has_medical:
            _prev = sub_expert_id
            sub_expert_id = "research_tool_non_clinical"
            claude_domain = _coerce_to_registry(sub_expert_id)
            confidence    = min(confidence, 0.55)
            reasoning     = (
                f"H-03 override from '{_prev}': drug modality with low confidence "
                "and no medical language detected in idea text."
            )
            logger.info(
                "H-03: '%s' overridden → research_tool_non_clinical "
                "(drug modality, confidence=%.2f, no medical language in idea)", _prev, confidence,
            )

    # Routing logic — reconciles the PI-selected top-level disease domain with Claude.
    if pi_domain == "auto":
        # Pure Claude classification
        final_domain    = claude_domain
        routing_method  = "auto"
        mismatch        = None
    elif pi_domain == claude_domain:
        # PI and Claude agree
        final_domain    = pi_domain
        routing_method  = "pi_confirmed"
        confidence      = min(confidence + 0.15, 1.0)   # boost confidence when they agree
        mismatch        = None
    else:
        # Disagreement — Claude wins
        pi_name     = EXPERT_REGISTRY.get(pi_domain, {})
        pi_label    = getattr(pi_name, 'display_name', pi_domain) if pi_name else pi_domain
        claude_name = EXPERT_REGISTRY[_coerce_to_registry(claude_domain)].display_name
        final_domain   = claude_domain
        routing_method = "claude_override"
        mismatch       = (
            f"You selected {pi_label} but this idea appears to be in "
            f"{claude_name} ({reasoning}). Routing to {claude_name}."
        )
        logger.info(f"Domain mismatch: PI={pi_domain}, Claude={claude_domain} — Claude wins")

    final_domain = _coerce_to_registry(final_domain)
    expert = EXPERT_REGISTRY[final_domain]

    # Resolve the modality sub-expert (v2) that will actually author the report. This
    # is the fix for the "diagnostic written by the antibiotic expert" bug: a non-drug
    # idea keeps its own modality expert instead of being coerced to a drug default.
    sub_expert = get_sub_expert(sub_expert_id) if sub_expert_id else None
    if sub_expert is None:
        # Unknown granular id — fall back to the v1 disease expert as the author.
        logger.warning(f"No v2 sub-expert for '{sub_expert_id}' — using v1 expert '{final_domain}'")
    modality = getattr(sub_expert, "tier1_category", None)

    archetype = resolve_archetype(sub_expert_id or "")
    logger.info("ProductArchetype resolved: %s (sub_expert=%s)", archetype.value, sub_expert_id)

    return RouterResult(
        domain_id         = final_domain,
        expert            = expert,
        confidence        = confidence,
        pi_selected       = pi_domain,
        claude_classified = claude_domain,
        mismatch_warning  = mismatch,
        routing_method    = routing_method,
        sub_expert        = sub_expert,
        sub_expert_id     = sub_expert_id,
        modality          = modality,
        archetype         = archetype,
    )
