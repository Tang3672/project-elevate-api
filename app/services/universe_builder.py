"""
universe_builder.py — Dynamic 500+ disease universe for the opportunity scoring engine.

Each entry: (disease_name, therapeutic_area, phase, approved_count, annual_cost_usd, notes)
- therapeutic_area: must match a key in _TA_DEFAULTS in opportunity_scorer_v2.py
- phase: "preclinical" | "phase1" | "phase2" | "phase3"
- approved_count: rough count of approved therapies (used as static fallback; live FDA data fetched at score time)
- annual_cost_usd: typical WAC/list price for treatment
- notes: 1-sentence opportunity description

The seed list is static; CT.gov trial counts are fetched live at score time.
No database connection required to import this module.
"""

from __future__ import annotations
from typing import List, Tuple

DiseaseEntry = Tuple[str, str, str, int, int, str]

# ──────────────────────────────────────────────────────────────────────────────
# ONCOLOGY — 50+ specific cancer types and subtypes
# ──────────────────────────────────────────────────────────────────────────────
_ONCOLOGY: List[DiseaseEntry] = [
    ("Lung Cancer (NSCLC, IO-resistant)",        "oncology", "phase3", 8,  180_000, "PD-1/L1 resistance creates massive second-line gap"),
    ("Lung Cancer (SCLC, extensive stage)",      "oncology", "phase2", 4,  160_000, "Atezolizumab added; still poor prognosis; DLL3 bispecifics emerging"),
    ("Colorectal Cancer (MSS)",                  "oncology", "phase2", 4,  120_000, "MSS tumors unresponsive to checkpoint; RAS-targeted combos emerging"),
    ("Pancreatic Ductal Adenocarcinoma",         "oncology", "phase2", 3,  200_000, "12% 5-year survival; KRAS G12D targeted agents emerging"),
    ("Glioblastoma Multiforme",                  "oncology", "phase2", 2,  150_000, "No approved immunotherapy; checkpoint inhibitors failed Phase 3"),
    ("Breast Cancer (HR+, CDK4/6 resistant)",   "oncology", "phase2", 5,  150_000, "CDK4/6 inhibitor resistance; PI3K/AKT/mTOR pathway targets"),
    ("HER2-low Breast Cancer",                   "oncology", "phase3", 2,  180_000, "Enhertu established precedent; large addressable population"),
    ("Triple-Negative Breast Cancer",            "oncology", "phase2", 4,  180_000, "TROP2 ADCs (sacituzumab) approved; novel combinations needed"),
    ("Prostate Cancer (PSMA-targeted)",          "oncology", "phase3", 4,  180_000, "Pluvicto approved; PSMA ADCs and combos emerging"),
    ("Prostate Cancer (mCRPC, AR-refractory)",  "oncology", "phase2", 5,  180_000, "AR pathway saturation; AKT/PARP combinations next"),
    ("Ovarian Cancer (BRCA-wild type)",          "oncology", "phase2", 3,  150_000, "PARP inhibitor benefit limited to BRCA; FRα/ADC approaches"),
    ("Ovarian Cancer (platinum-resistant)",      "oncology", "phase2", 3,  180_000, "High unmet need; mirvetuximab approved for FRα-high subset"),
    ("Cervical Cancer (recurrent)",              "oncology", "phase2", 3,  140_000, "Tisotumab vedotin approved; TROP2/PD-1 combos emerging"),
    ("Endometrial Cancer (MMR-proficient)",      "oncology", "phase2", 3,  140_000, "IO effective in dMMR; pMMR subtype still underserved"),
    ("Multiple Myeloma (triple-refractory)",     "oncology", "phase2", 6,  200_000, "Bispecifics/CAR-T improving outcomes; still no cure"),
    ("Myelofibrosis JAK-resistant",             "oncology", "phase2", 3,  200_000, "Ruxolitinib resistance creates second-line gap"),
    ("KRAS G12C NSCLC",                         "oncology", "phase2", 2,  180_000, "Sotorasib/adagrasib approved; combination strategies needed"),
    ("KRAS G12D Pancreatic Cancer",             "oncology", "phase2", 1,  200_000, "MRTX1133 in trials; first direct G12D inhibitor wave"),
    ("Hepatocellular Carcinoma (2nd line)",     "oncology", "phase2", 5,  120_000, "Atezolizumab+bev first-line; 2nd-line still crowded/unmet"),
    ("Cholangiocarcinoma (IDH1/FGFR)",         "oncology", "phase2", 3,  180_000, "Ivosidenib/pemigatinib approved; pan-FGFR combinations needed"),
    ("Bladder Cancer (muscle-invasive)",        "oncology", "phase2", 4,  140_000, "Enfortumab approved; EV+pembro adjuvant setting emerging"),
    ("Renal Cell Carcinoma (sarcomatoid)",      "oncology", "phase2", 5,  160_000, "IO+TKI combos approved; sarcomatoid remains poor prognosis"),
    ("Gastric Cancer (HER2-negative)",          "oncology", "phase2", 4,  160_000, "Pembrolizumab approved; CLDN18.2 bispecifics emerging"),
    ("Esophageal Cancer (squamous cell)",       "oncology", "phase2", 3,  160_000, "Nivolumab approved; subtype still lacks targeted agents"),
    ("Head and Neck Cancer (R/R HNSCC)",        "oncology", "phase2", 4,  160_000, "Pembrolizumab approved; NRG1 fusions/targeted combos emerging"),
    ("Thyroid Cancer (RAI-refractory)",         "oncology", "phase2", 4,  120_000, "Lenvatinib/sorafenib approved; RET/NTRK fusions well-covered"),
    ("Soft Tissue Sarcoma (leiomyosarcoma)",    "oncology", "phase2", 3,  180_000, "Trabectedin/Gemcitabine standard; liposomal doxorubicin niche"),
    ("Osteosarcoma (metastatic)",               "oncology", "phase2", 2,  180_000, "MAP regimen unchanged for 40 years; CDK4/6 inhibitors emerging"),
    ("Ewing Sarcoma (relapsed)",                "oncology", "phase2", 2,  160_000, "No standard salvage; EWS::FLI1 targeted approaches needed"),
    ("Neuroblastoma (high-risk)",               "oncology", "phase2", 3,  180_000, "Dinutuximab approved; ALK inhibitors (crizotinib) emerging"),
    ("Medulloblastoma (SHH pathway)",           "oncology", "phase2", 3,  160_000, "Vismodegib approved for adults; pediatric SHH-pathway targeting"),
    ("Mesothelioma (pleural)",                  "oncology", "phase2", 3,  180_000, "Nivolumab+ipilimumab approved; MSLN-targeted ADCs next"),
    ("Merkel Cell Carcinoma",                   "oncology", "phase2", 2,  120_000, "Avelumab/pembrolizumab approved; next-gen IOE approaches"),
    ("Cutaneous T-Cell Lymphoma (advanced)",    "oncology", "phase2", 5,  140_000, "Multiple agents approved; durable remission still lacking"),
    ("Diffuse Large B-Cell Lymphoma (relapsed)","oncology", "phase2", 5,  200_000, "CAR-T approved 2nd line; bridging strategies and combo improvement"),
    ("Follicular Lymphoma (POD24)",             "oncology", "phase2", 5,  150_000, "Anti-CD20 ± chemo standard; PI3K and bispecifics emerging"),
    ("Mantle Cell Lymphoma (BTK-resistant)",    "oncology", "phase2", 4,  200_000, "Ibrutinib/acalabrutinib; pirtobrutinib approved for BTK-resistant"),
    ("Chronic Lymphocytic Leukemia (4th line)", "oncology", "phase2", 6,  180_000, "BTK/BCL2 coverage good; 4th-line lacks options"),
    ("Acute Myeloid Leukemia (FLT3-ITD)",      "oncology", "phase2", 4,  200_000, "Midostaurin/gilteritinib approved; FLT3 resistance mechanisms"),
    ("Acute Myeloid Leukemia (IDH1/2)",        "oncology", "phase2", 4,  200_000, "Enasidenib/ivosidenib approved; TP53-mutant AML still unmet"),
    ("Myelodysplastic Syndrome (high-risk)",   "oncology", "phase2", 3,  150_000, "Azacitidine/lenalidomide; TP53/SF3B1-targeted urgently needed"),
    ("Acute Lymphoblastic Leukemia (Ph-like)", "oncology", "phase2", 4,  200_000, "Ph-like subtype poor prognosis; targeted kinase inhibitors needed"),
    ("Thymic Carcinoma",                        "oncology", "phase2", 2,  160_000, "No FDA-approved targeted therapy; pembrolizumab emerging"),
    ("Ampullary Cancer",                        "oncology", "phase2", 1,  160_000, "Rare, often lumped with pancreatic; distinct molecular features"),
    ("Adrenocortical Carcinoma",                "oncology", "phase2", 1,  120_000, "Mitotane only approved option; EDP-M regimen investigational"),
    ("Pheochromocytoma/Paraganglioma",          "oncology", "phase2", 2,  120_000, "177Lu-DOTATATE extended; SDHB-mutant subset needs targeted approach"),
    ("Neuroendocrine Tumors (midgut)",          "oncology", "phase2", 4,  120_000, "Somatostatin analogues established; PRRT growing; everolimus niche"),
    ("Uveal Melanoma (metastatic)",             "oncology", "phase2", 2,  180_000, "Tebentafusp approved first bispecific; only for HLA-A*02:01"),
    ("Cutaneous Melanoma (brain mets)",         "oncology", "phase2", 5,  180_000, "Checkpoint + BRAF standard; CNS penetration still challenge"),
    ("Penile Cancer (advanced)",                "oncology", "phase2", 1,  120_000, "No FDA-approved targeted agent; cisplatin-based standard"),
    ("Vulvar Cancer (recurrent)",               "oncology", "phase2", 1,  120_000, "No targeted approvals; IO emerging"),
]

# ──────────────────────────────────────────────────────────────────────────────
# CNS / NEUROLOGY — 25+ conditions
# ──────────────────────────────────────────────────────────────────────────────
_CNS: List[DiseaseEntry] = [
    ("Alzheimer Disease (early/MCI)",           "cns", "phase3", 2,   28_000, "Lecanemab/donanemab approved; amyloid-positive biomarker enrichment"),
    ("Alzheimer Disease (moderate-severe)",     "cns", "phase2", 2,   28_000, "Post-amyloid clearance; tau/neuroinflammation next"),
    ("Parkinson Disease (early stage)",         "cns", "phase2", 4,   15_000, "Dopamine replacement standard; alpha-synuclein/GBA-targeting next"),
    ("Parkinson Disease (GBA1-mutant)",         "cns", "phase2", 1,   20_000, "GBA1 is most common genetic PD risk; LTI-291/venglustat in trials"),
    ("Huntington Disease",                      "cns", "phase2", 0,  120_000, "No disease-modifying therapy approved; high unmet need"),
    ("Multiple Sclerosis (progressive)",        "cns", "phase2", 6,   80_000, "Relapsing MS well-served; progressive forms still lacking"),
    ("Stroke (acute ischemic, neuroprotection)","cns", "phase2", 1,   25_000, "tPA window limit; neuroprotection agents have failed historically"),
    ("Major Depression (TRD)",                  "cns", "phase2", 3,   15_000, "Esketamine approved; psilocybin/MDMA pipeline accelerating"),
    ("Schizophrenia",                           "cns", "phase2", 12,  20_000, "D2 class crowded; muscarinic agonists (xanomeline-trospium) new class"),
    ("Bipolar Depression",                      "cns", "phase2", 3,   15_000, "Lumateperone approved; significant unmet need remains"),
    ("PTSD",                                    "cns", "phase2", 2,    8_000, "MDMA/psilocybin-assisted therapy in Phase 3; breakthrough potential"),
    ("Opioid Use Disorder",                     "cns", "phase2", 3,    6_000, "Buprenorphine/naltrexone standard; novel mechanisms + digital tools"),
    ("ALS (SOD1-mutant)",                       "rare_disease", "phase2", 1, 178_000, "Tofersen approved 2024; oral alternative opportunity"),
    ("ALS (sporadic, TDP-43)",                  "cns", "phase2", 2,  120_000, "High unmet; TDP-43 aggregation-targeting just entering trials"),
    ("Epilepsy (drug-resistant focal)",         "cns", "phase2", 5,   20_000, "Multiple ASMs approved; 30% remain refractory; NaV1.2/GABA targets"),
    ("Migraine (chronic, CGRP-refractory)",     "cns", "phase2", 6,   15_000, "CGRP mAbs/gepants approved; 5-HT1F and PACAP targets emerging"),
    ("Narcolepsy Type 1",                       "cns", "phase2", 3,   15_000, "Sodium oxybate/pitolisant approved; orexin replacement in trials"),
    ("Essential Tremor (refractory)",           "cns", "phase2", 2,    8_000, "Propranolol/primidone standard; FUS thalamotomy device gap"),
    ("Tourette Syndrome",                       "cns", "phase2", 3,   10_000, "Valbenazine approved 2023; CBIT behavioral gap persists"),
    ("Fragile X Syndrome",                      "rare_disease", "phase2", 1, 50_000, "No disease-modifying agents approved; mGluR5 / FMRP targets"),
    ("Rett Syndrome",                           "rare_disease", "phase2", 1, 80_000, "Trofinetide approved 2023; gene replacement wave coming"),
    ("Angelman Syndrome",                       "rare_disease", "phase2", 0, 80_000, "No approved therapies; ASO/gene therapy advancing quickly"),
    ("Spinal Cord Injury (subacute)",           "cns", "phase2", 1,   30_000, "Riluzole extended; stem cell/NT-3 gene therapy approaches emerging"),
    ("Traumatic Brain Injury (chronic CTE)",    "cns", "phase2", 0,   20_000, "No approved neuroprotectant; biomarker-guided tau imaging enabling trials"),
    ("Vascular Dementia",                       "cns", "phase2", 0,   15_000, "No approved therapy; SGLT2i/GLP-1 cognitive benefit under study"),
    ("Lewy Body Dementia",                      "cns", "phase2", 0,   18_000, "No approved DMT; cholinesterase inhibitors symptomatic only"),
    ("Normal Pressure Hydrocephalus",           "cns", "phase2", 1,   10_000, "VP shunt standard; programmable valve/biomarker enrichment gap"),
]

# ──────────────────────────────────────────────────────────────────────────────
# CARDIOVASCULAR — 20+ conditions
# ──────────────────────────────────────────────────────────────────────────────
_CARDIOVASCULAR: List[DiseaseEntry] = [
    ("Heart Failure (HFpEF)",                   "cardiovascular", "phase3", 5,  18_000, "Empagliflozin approved; large unmet need in preserved-EF subtype"),
    ("Heart Failure (HFrEF, device-refractory)","cardiovascular", "phase2", 6,  20_000, "Cardiac contractility modulation; gene therapy for DCM"),
    ("Atrial Fibrillation",                     "cardiovascular", "phase3", 6,   8_000, "Rate/rhythm control standard; catheter ablation gap for persistent AF"),
    ("Pulmonary Arterial Hypertension",         "cardiovascular", "phase2", 8,  80_000, "Multiple approved; novel mechanisms still needed"),
    ("Hypertrophic Cardiomyopathy (obstructive)","cardiovascular","phase3", 2,  50_000, "Mavacamten approved 2022; aficamten in Phase 3"),
    ("Dilated Cardiomyopathy (genetic)",        "cardiovascular", "phase2", 3,  25_000, "Lamin A/C and TTN variants; gene therapy wave beginning"),
    ("Arrhythmogenic Cardiomyopathy",           "cardiovascular", "phase2", 1,  20_000, "ICD standard; SCD prevention pharmacology largely untested"),
    ("Acute Myocardial Infarction (cardioprotection)","cardiovascular","phase2",3,15_000,"Reperfusion established; salvage/stem cell approaches resurging"),
    ("Peripheral Artery Disease (CLI)",         "cardiovascular", "phase2", 3,  20_000, "Revascularization standard; gene therapy (HIF-1α) emerging"),
    ("Aortic Stenosis (TAVR-ineligible)",       "cardiovascular", "phase2", 2,  30_000, "TAVR revolution; transcatheter option gaps remain"),
    ("Mitral Valve Regurgitation (secondary)",  "cardiovascular", "phase2", 2,  30_000, "MitraClip approved; structural heart device gap for complex anatomy"),
    ("Ventricular Tachycardia (refractory)",    "cardiovascular", "phase2", 3,  20_000, "Amiodarone + ablation standard; newer antiarrhythmics needed"),
    ("Takayasu Arteritis",                      "immunology",     "phase2", 2,  40_000, "Tocilizumab approved; relapsing disease still lacks durable control"),
    ("Cardiac Sarcoidosis",                     "cardiovascular", "phase2", 1,  20_000, "Steroids standard; device + biologic combination lacking"),
    ("Transthyretin Amyloid Cardiomyopathy",    "cardiovascular", "phase3", 2,  225_000,"Tafamidis approved; RNAi/CRISPR approaches expanding to broader population"),
    ("Hypertriglyceridemia (familial)",         "cardiovascular", "phase3", 4,  30_000, "Fibrates/PCSK9 approved; volanesorsen/olezarumab for severe subtype"),
    ("Homozygous Familial Hypercholesterolemia","cardiovascular", "phase3", 5, 450_000, "Evinacumab approved; inclisiran base; gene editing emerging"),
    ("Atherosclerosis (Lp(a)-driven)",          "cardiovascular", "phase3", 1,  20_000, "Pelacarsen/olpasiran in Phase 3; novel Lp(a)-lowering class"),
    ("Hypertension (resistant, renal denervation)","cardiovascular","phase2",4,  5_000, "Spyral catheter-based; polypill + renal denervation hybrid needed"),
    ("Deep Vein Thrombosis (prevention)",       "cardiovascular", "phase3", 5,   5_000, "DOACs standard; FXIa inhibitors (abelacimab) safer profile"),
]

# ──────────────────────────────────────────────────────────────────────────────
# METABOLIC / ENDOCRINE — 20+ conditions
# ──────────────────────────────────────────────────────────────────────────────
_METABOLIC: List[DiseaseEntry] = [
    ("Type 2 Diabetes (GLP-1 resistant)",       "metabolic", "phase3", 12, 12_000, "GLP-1 saturation; oral/combination next frontier"),
    ("Obesity (CNS/metabolic)",                 "metabolic", "phase3",  4, 15_000, "Semaglutide crowded; mechanism diversity needed"),
    ("NASH/MASH",                               "metabolic", "phase3",  1, 50_000, "Resmetirom approved 2024; pipeline crowded but huge market"),
    ("Chronic Kidney Disease (DKD)",            "metabolic", "phase3",  4, 25_000, "SGLT2i/finerenone approved; GFR-preserving agents still needed"),
    ("Type 1 Diabetes (CGM/automated insulin)", "metabolic", "phase3",  4, 12_000, "Device+drug combination; closed-loop systems maturing"),
    ("Type 1 Diabetes (immune preservation)",   "metabolic", "phase2",  1, 50_000, "Teplizumab approved (delay); preservation/cure trials ongoing"),
    ("Hypothyroidism (myxedema crisis)",        "metabolic", "phase2",  2,  1_000, "IV levothyroxine approved; combined T3/T4 optimization lacking"),
    ("Cushing Syndrome (adrenal/ectopic)",      "metabolic", "phase2",  4, 30_000, "Mifepristone/pasireotide approved; osilodrostat expanding"),
    ("Acromegaly",                              "metabolic", "phase2",  5, 40_000, "Somatostatin analogues standard; oral octreotide (octreolin) new"),
    ("Phenylketonuria",                         "rare_disease","phase3", 2, 120_000,"Pegvaliase/sapropterin approved; gene therapy curative approach"),
    ("Gaucher Disease Type 1",                  "rare_disease","phase3", 4, 300_000,"ERT/SRT established; oral substrate reduction agents expanding"),
    ("Fabry Disease",                           "rare_disease","phase2", 3, 350_000,"ERT/migalastat approved; next-gen chaperone/substrate reduction"),
    ("Pompe Disease (late-onset)",              "rare_disease","phase3", 2, 400_000,"Alglucosidase standard; cipaglucosidase + miglustat superior"),
    ("Mucopolysaccharidosis Type I",            "rare_disease","phase2", 2, 500_000,"ERT/HSCT standard; CNS-penetrant gene therapy urgently needed"),
    ("Primary Hyperoxaluria Type 1",            "rare_disease","phase3", 1, 500_000,"Lumasiran approved 2020; gene therapy potentially curative"),
    ("Wilson Disease",                          "rare_disease","phase2", 3,  5_000, "Penicillamine/trientine standard; liver-directed gene therapy emerging"),
    ("Alpha-1 Antitrypsin Deficiency (liver)",  "rare_disease","phase2", 1, 100_000,"Augmentation IV approved; RNA interference/gene editing for liver"),
    ("Lipodystrophy (generalized)",             "rare_disease","phase2", 2, 100_000,"Metreleptin approved; complementary agent for partial forms"),
    ("Propionic Acidemia",                      "rare_disease","phase2", 0,  50_000,"No approved therapy; mRNA replacement therapy in development"),
    ("Methylmalonic Acidemia",                  "rare_disease","phase2", 0,  50_000,"No approved therapy; liver transplant only durable option today"),
]

# ──────────────────────────────────────────────────────────────────────────────
# IMMUNOLOGY / AUTOIMMUNE — 20+ conditions
# ──────────────────────────────────────────────────────────────────────────────
_IMMUNOLOGY: List[DiseaseEntry] = [
    ("Rheumatoid Arthritis (JAK-refractory)",   "immunology", "phase2", 8,  40_000, "Biologic/JAK failure population; next-gen targeted therapies"),
    ("Psoriasis/PsA (IL-17/23 refractory)",     "immunology", "phase2", 7,  35_000, "IL-17/23 biologics standard; TYK2 inhibitors expanding options"),
    ("Inflammatory Bowel Disease (UC/CD)",      "immunology", "phase3", 8,  45_000, "Anti-TNF resistance; selective gut-homing biologics next"),
    ("Systemic Lupus Erythematosus",            "immunology", "phase2", 4,  30_000, "Belimumab/anifrolumab approved; B-cell depletion combinations"),
    ("Lupus Nephritis",                         "immunology", "phase2", 3,  40_000, "Voclosporin/belimumab approved; calcineurin + complement combos"),
    ("Sjögren's Syndrome",                      "immunology", "phase2", 1,  15_000, "No DMT approved; BAFF/type-I IFN targeting in early trials"),
    ("Myasthenia Gravis (generalized)",         "immunology", "phase3", 5,  80_000, "Efgartigimod/rozanolixizumab approved; complement targets"),
    ("Neuromyelitis Optica Spectrum Disorder",  "immunology", "phase3", 3,  120_000,"Inebilizumab/satralizumab approved; emerging complement inhibitors"),
    ("IgA Nephropathy",                         "immunology", "phase3", 2,  20_000, "Budesonide (Tarpeyo)/iptacopan approved; sparsentan in Phase 3"),
    ("ANCA-associated Vasculitis",              "immunology", "phase2", 4,  40_000, "Avacopan approved; PR3-ANCA vs. MPO-ANCA targeting being studied"),
    ("Giant Cell Arteritis",                    "immunology", "phase3", 2,  40_000, "Tocilizumab approved; sarilumab and JAK inhibitors in trials"),
    ("Ankylosing Spondylitis (nr-axSpA)",       "immunology", "phase3", 5,  35_000, "TNFi/IL-17i standard; OSM/GM-CSF targets for refractory cases"),
    ("Juvenile Idiopathic Arthritis (systemic)","immunology", "phase3", 4,  40_000, "IL-1/IL-6 approved; JAK inhibitors expanding pediatric label"),
    ("Eosinophilic Esophagitis",               "immunology", "phase3", 2,  20_000, "Dupilumab/budesonide oral suspension approved; IL-13 mAb next"),
    ("Atopic Dermatitis (severe)",              "immunology", "phase3", 5,  35_000, "Dupilumab/JAK inhibitors approved; OX40/IL-31 targets emerging"),
    ("Bullous Pemphigoid",                      "immunology", "phase2", 2,  20_000, "Steroids standard; dupilumab/omalizumab showing Phase 3 signals"),
    ("Pemphigus Vulgaris",                      "immunology", "phase2", 3,  30_000, "Rituximab approved; FcRn inhibitors (nipocalimab) emerging"),
    ("Alopecia Areata (severe)",                "immunology", "phase3", 3,  20_000, "Baricitinib/ritlecitinib approved; additional JAK inhibitors in line"),
    ("Hidradenitis Suppurativa",                "immunology", "phase2", 3,  40_000, "Secukinumab approved; bimekizumab (IL-17A/F) and JAK inhibitors"),
    ("Systemic Sclerosis (diffuse)",            "immunology", "phase2", 2,  30_000, "No DMT proven; nintedanib slows ILD progression; autologous HSCT"),
]

# ──────────────────────────────────────────────────────────────────────────────
# RESPIRATORY — 15+ conditions
# ──────────────────────────────────────────────────────────────────────────────
_RESPIRATORY: List[DiseaseEntry] = [
    ("Asthma (severe eosinophilic)",            "respiratory", "phase3", 5,  25_000, "Biologic growth; TSLP/IL-33 next targets"),
    ("COPD (advanced emphysema)",               "respiratory", "phase2", 5,  18_000, "Triple inhaler therapy; lung volume reduction device gap"),
    ("Idiopathic Pulmonary Fibrosis",           "respiratory", "phase3", 2,  100_000,"Nintedanib/pirfenidone slow progression; autotaxin and integrin targets"),
    ("Hypersensitivity Pneumonitis (fibrotic)", "respiratory", "phase2", 1,  80_000, "Nintedanib approved; antigen avoidance plus biologic combination"),
    ("Non-CF Bronchiectasis",                   "respiratory", "phase2", 2,  15_000, "No FDA-approved therapy; bronchodilator + mucolytics only"),
    ("Pulmonary Sarcoidosis (chronic)",         "respiratory", "phase2", 2,  15_000, "Steroids standard; TNFi used off-label; inhaled corticosteroid RCTs"),
    ("Cystic Fibrosis (F508del homozygous)",    "respiratory", "phase3", 3,  300_000,"Trikafta dominant; residual function mutations and non-F508del unmet"),
    ("Primary Ciliary Dyskinesia",              "respiratory", "phase2", 0,  20_000, "No approved therapy; airway clearance devices only"),
    ("Alpha-1 Antitrypsin Deficiency (lung)",   "respiratory", "phase2", 1,  100_000,"IV augmentation approved; inhaled/gene therapy urgently needed"),
    ("Obstructive Sleep Apnea (central CSA)",   "respiratory", "phase2", 3,   8_000, "CPAP standard; remedē System for central; hypoglossal nerve stimulation"),
    ("Acute Respiratory Distress Syndrome",     "respiratory", "phase2", 0,  15_000, "Supportive care only; mesenchymal stem cell therapies in trials"),
    ("Pulmonary Hypertension Group 3 (lung)",   "respiratory", "phase2", 2,  40_000, "PH therapies not approved for lung-disease-related PH; unmet gap"),
    ("Lymphangioleiomyomatosis",                "rare_disease","phase2", 1,  50_000, "Sirolimus approved; mammalian target rapamycin next-gen agents"),
    ("Bronchopulmonary Dysplasia (preterm)",    "respiratory", "phase2", 0,  20_000, "Supportive standard; stem cell/IGF-1 trials in NICU patients"),
    ("Post-COVID Respiratory Syndrome",         "respiratory", "phase2", 0,  10_000, "No approved therapy; broad unmet need with poorly defined endpoint"),
]

# ──────────────────────────────────────────────────────────────────────────────
# INFECTIOUS DISEASE / AMR — 20+ conditions
# ──────────────────────────────────────────────────────────────────────────────
_INFECTIOUS: List[DiseaseEntry] = [
    ("Carbapenem-resistant Enterobacterales",   "amr_infectious", "phase2", 4,  18_000, "CDC urgent threat; NDM prevalence rising"),
    ("Acinetobacter baumannii MDR",             "amr_infectious", "phase2", 2,  16_000, "ESKAPE pathogen; extremely limited treatment options"),
    ("MRSA Skin Infections",                    "amr_infectious", "phase2", 5,   1_500, "Oral gap; TMP-SMX resistance rising"),
    ("C. difficile Infection",                  "amr_infectious", "phase2", 3,   8_000, "Recurring infection problem; microbiome approaches emerging"),
    ("HIV (long-acting ART / cure)",            "amr_infectious", "phase3", 8,  25_000, "Daily pill to long-acting injectable; cure strategies emerging"),
    ("Tuberculosis (drug-resistant)",           "amr_infectious", "phase2", 4,  10_000, "BPaL regimen; pre-XDR-TB treatment gap; host-directed therapies"),
    ("Gonorrhea (ceftriaxone-resistant)",       "amr_infectious", "phase2", 3,     500, "Last-line oral therapies failing; zoliflodacin in Phase 3"),
    ("Clostridioides difficile (prophylaxis)",  "amr_infectious", "phase3", 2,   5_000, "Bezlotoxumab approved for recurrence; new preventive microbiome rx"),
    ("Candida auris (invasive)",                "amr_infectious", "phase2", 2,  15_000, "Rezafungin approved; novel echinocandin analogues in trials"),
    ("Aspergillus (invasive, azole-resistant)", "amr_infectious", "phase2", 3,  20_000, "Triazole resistance rising; olorofim/opelconazole in trials"),
    ("RSV in elderly/immunocompromised",        "vaccine",        "phase3", 2,     250, "Arexvy/Abrysvo approved; booster strategy unclear"),
    ("Influenza (universal vaccine)",           "vaccine",        "phase2", 4,     200, "Annual shot limitation; HA stalk/universal approaches"),
    ("Dengue Fever (therapeutic)",              "amr_infectious", "phase2", 1,   1_000, "Dengvaxia vaccine limited; no approved antiviral; NS5 inhibitors"),
    ("Chikungunya (chronic arthritis)",         "amr_infectious", "phase2", 1,   2_000, "Ixchiq vaccine approved 2023; no anti-viral for chronic stage"),
    ("Chagas Disease",                          "amr_infectious", "phase2", 2,   2_000, "Benznidazole/nifurtimox; better-tolerated 2nd-gen agents needed"),
    ("Leishmaniasis (visceral)",                "amr_infectious", "phase2", 3,   5_000, "Liposomal amphotericin standard; oral miltefosine limited efficacy"),
    ("Cytomegalovirus (transplant setting)",    "amr_infectious", "phase3", 3,  20_000, "Letermovir approved for prophylaxis; maribavir for treatment"),
    ("Hepatitis B (cccDNA elimination)",        "amr_infectious", "phase2", 6,  25_000, "Functional cure target; RNA silencing + surface antigen loss"),
    ("Hepatitis D (HDV superinfection)",        "amr_infectious", "phase3", 1,  50_000, "Bulevirtide approved in EU; lonafarnib in US trials"),
    ("Mpox (systemic)",                         "amr_infectious", "phase2", 2,   5_000, "Tecovirimat treatment; JYNNEOS vaccine; antiviral trial data needed"),
]

# ──────────────────────────────────────────────────────────────────────────────
# RARE / GENETIC DISEASES — 30+ conditions
# ──────────────────────────────────────────────────────────────────────────────
_RARE_GENETIC: List[DiseaseEntry] = [
    ("Sickle Cell Disease (gene therapy)",      "gene_therapy",  "phase3", 2, 2_200_000, "Casgevy/Lyfgenia approved 2023; access/affordability gap"),
    ("Duchenne Muscular Dystrophy",             "rare_disease",  "phase2", 3, 1_200_000, "Exon-skipping approved; gene therapy wave coming"),
    ("Spinal Muscular Atrophy Type 2",          "rare_disease",  "phase2", 3,   340_000, "Zolgensma/nusinersen approved; beyond-neonatal gap"),
    ("Friedreich Ataxia",                       "rare_disease",  "phase2", 1,   340_000, "Omaveloxolone approved 2023; additional mechanisms needed"),
    ("Rare Pediatric Epilepsy (SCN1A)",         "rare_disease",  "phase2", 2,   180_000, "Fenfluramine/cannabidiol approved; gene therapy next"),
    ("ALS (SOD1-mutant)",                       "rare_disease",  "phase2", 1,   178_000, "Tofersen approved 2024; oral alternative opportunity"),
    ("Cystic Fibrosis (non-F508del minority)",  "rare_disease",  "phase3", 2,   300_000, "Trikafta covers most; ~10% of CF mutations still without modulator"),
    ("Hemophilia A (inhibitors)",               "rare_disease",  "phase3", 5,   800_000, "Emicizumab transforms care; gene therapy (valoctocogene) adding"),
    ("Hemophilia B (gene therapy)",             "rare_disease",  "phase3", 3,   500_000, "Fitusiran/etranacogene approved; durability still being studied"),
    ("Hereditary Angioedema",                   "rare_disease",  "phase3", 5,   250_000, "Multiple C1-INH/bradykinin inhibitors; subcutaneous prophylaxis war"),
    ("Transthyretin Amyloidosis (polyneuropathy)","rare_disease","phase3", 3,   350_000, "Patisiran/inotersen/eplontersen approved; gene editing curative target"),
    ("Spinal and Bulbar Muscular Atrophy",      "rare_disease",  "phase2", 0,    80_000, "No approved therapy; AR-targeted ASO/leuprolide trials"),
    ("Myotonic Dystrophy Type 1",               "rare_disease",  "phase2", 0,    50_000, "Supportive only; MBNL1 splicing correction ASO approach"),
    ("Limb-Girdle Muscular Dystrophy (LGMD2E)", "rare_disease", "phase2", 0,   200_000, "No approved therapy; beta-sarcoglycan gene therapy in trials"),
    ("Emery-Dreifuss Muscular Dystrophy",       "rare_disease",  "phase1", 0,   100_000, "Cardiac + skeletal muscle; emerin/lamin gene therapy earliest stage"),
    ("Congenital Myasthenic Syndromes",         "rare_disease",  "phase2", 2,    30_000, "3,4-DAP/salbutamol by subtype; no universal approved therapy"),
    ("CHARGE Syndrome",                         "rare_disease",  "phase1", 0,    40_000, "CHD7 haploinsufficiency; no targeted therapy"),
    ("Treacher Collins Syndrome",               "rare_disease",  "phase1", 0,    30_000, "TCOF1/POLR1D mutations; no pharmacologic therapy"),
    ("Kabuki Syndrome",                         "rare_disease",  "phase1", 0,    40_000, "KMT2D/KDM6A epigenetic; HDAC inhibitors early exploration"),
    ("NRXN1 Deletion Syndrome",                 "rare_disease",  "preclinical", 0, 40_000,"Neurexin-1 synaptopathy; no therapy; iPSC model-driven"),
    ("22q11.2 Deletion Syndrome",               "rare_disease",  "phase2", 0,    30_000, "DiGeorge overlap; no pharmacologic DMT; gene replacement concept"),
    ("Prader-Willi Syndrome",                   "rare_disease",  "phase2", 2,    40_000, "Hyperphagia/GH approved; setmelanotide in trials for obesity"),
    ("Tuberous Sclerosis Complex",              "rare_disease",  "phase3", 2,   100_000, "Everolimus approved for multiple manifestations; mTOR 2nd gen"),
    ("Neurofibromatosis Type 1 (PN)",           "rare_disease",  "phase3", 1,    60_000, "Selumetinib (Koselugo) approved; combination MEK inhibition"),
    ("Batten Disease (CLN2)",                   "rare_disease",  "phase2", 1,   500_000, "Cerliponase alfa ICV infusion approved; gene therapy emerging"),
    ("Gaucher Disease Type 3 (neuronopathic)",  "rare_disease",  "phase2", 2,   350_000, "ERT poor CNS penetration; brain-penetrant substrate reduction"),
    ("Niemann-Pick Disease Type C",             "rare_disease",  "phase2", 1,   100_000, "Arimoclomol approved EU; miglustat limited; CNS-targeted HP-β-CD"),
    ("GM1 Gangliosidosis",                      "rare_disease",  "phase2", 0,    80_000, "No approved therapy; AAV9 intraparenchymal gene therapy"),
    ("Krabbe Disease",                          "rare_disease",  "phase1", 0,    80_000, "HSCT only pre-symptomatic; gene therapy proof-of-concept"),
    ("Pompe Disease (infantile-onset, CRIM-neg)","rare_disease", "phase2", 2,  1_000_000,"cipaglucosidase alfaatox approved; CRIM-negative immune tolerance"),
]

# ──────────────────────────────────────────────────────────────────────────────
# OPHTHALMOLOGY — 15+ conditions
# ──────────────────────────────────────────────────────────────────────────────
_OPHTHALMOLOGY: List[DiseaseEntry] = [
    ("Geographic Atrophy (dry AMD)",            "ophthalmology", "phase3", 2,  20_000, "Syfovre/Izervay approved 2023; market still growing"),
    ("Wet AMD / Diabetic Macular Edema",        "ophthalmology", "phase3", 4,  15_000, "Anti-VEGF crowded; longer-acting port-delivery emerging"),
    ("Stargardt Disease",                       "ophthalmology", "phase2", 0,  50_000, "No approved therapy; ABCA4 gene replacement and cell therapy"),
    ("Inherited Retinal Dystrophies (RPE65)",   "ophthalmology", "phase3", 1, 850_000, "Luxturna approved; other IRD gene targets (RPGR, CNGB3) next"),
    ("Choroideremia",                           "ophthalmology", "phase2", 0,  50_000, "No approved therapy; AAV-CHM gene therapy durable 4-year data"),
    ("X-linked Retinoschisis",                  "ophthalmology", "phase2", 0,  50_000, "No approved therapy; RS1 gene therapy IVT delivery"),
    ("Glaucoma (normal tension)",               "ophthalmology", "phase2", 4,   2_000, "IOP-independent mechanism; neuroprotection angle (BDNF/RGC)"),
    ("Retinitis Pigmentosa (non-RPE65)",        "ophthalmology", "phase2", 1,  50_000, "Voretigene limited; optogenetics (Luxturna) for advanced RP"),
    ("Diabetic Retinopathy (non-proliferative)","ophthalmology", "phase3", 3,  15_000, "Anti-VEGF burdensome; faricimab + sustained delivery opportunity"),
    ("Retinal Vein Occlusion",                  "ophthalmology", "phase3", 4,  15_000, "Anti-VEGF standard; gene therapy for durable expression"),
    ("Keratoconus",                             "ophthalmology", "phase2", 2,   5_000, "Corneal CXL approved; cell therapy for advanced cases"),
    ("Macular Telangiectasia Type 2",           "ophthalmology", "phase2", 0,  30_000, "No approved therapy; ciliary neurotrophic factor (CNTF) implant"),
    ("Uveitis (non-infectious posterior)",      "ophthalmology", "phase2", 3,  30_000, "Ozurdex/Humira approved; Replagal-sparing sustained-release device"),
    ("Corneal Graft Failure",                   "ophthalmology", "phase2", 1,  20_000, "DSAEK/DMEK; bioengineered cornea substitutes emerging"),
    ("Leber Congenital Amaurosis (CEP290)",     "ophthalmology", "phase2", 0, 100_000, "No approved for CEP290; EDIT-101 CRISPR in vivo Phase 1/2"),
]

# ──────────────────────────────────────────────────────────────────────────────
# MENTAL HEALTH / PSYCHIATRY — 15+ conditions
# ──────────────────────────────────────────────────────────────────────────────
_MENTAL_HEALTH: List[DiseaseEntry] = [
    ("Major Depression (TRD)",                  "cns", "phase2", 3,  15_000, "Esketamine approved; psilocybin/MDMA pipeline accelerating"),
    ("Schizophrenia",                           "cns", "phase2", 12, 20_000, "D2 class crowded; muscarinic agonists (xanomeline-trospium) new class"),
    ("Bipolar Depression",                      "cns", "phase2",  3, 15_000, "Lumateperone approved; significant unmet need remains"),
    ("PTSD",                                    "cns", "phase2",  2,  8_000, "MDMA/psilocybin-assisted therapy in Phase 3; breakthrough potential"),
    ("Opioid Use Disorder",                     "cns", "phase2",  3,  6_000, "Buprenorphine/naltrexone standard; novel mechanisms + digital tools"),
    ("Alcohol Use Disorder",                    "cns", "phase2",  3,  5_000, "Naltrexone/acamprosate standard; GLP-1 agonists repurposed"),
    ("Anorexia Nervosa",                        "cns", "phase2",  1, 10_000, "No approved pharmacotherapy; psilocybin/remimazolam in early trials"),
    ("Binge Eating Disorder",                   "cns", "phase2",  2,  8_000, "Vyvanse approved; GLP-1 agonists reducing binge frequency"),
    ("Borderline Personality Disorder",         "cns", "phase2",  0, 10_000, "DBT gold standard; pharmacotherapy trials historically failed"),
    ("Autism Spectrum Disorder (core)",         "cns", "phase2",  0, 15_000, "No approved DMT; social motivation/oxytocin/GABA targets"),
    ("ADHD (adult, non-stimulant)",             "cns", "phase3",  6, 10_000, "Strattera/Qelbree standard; KP415 and viloxazine growing"),
    ("Insomnia (chronic)",                       "cns","phase3",  7,  3_000, "Orexin antagonists (suvorexant/lemborexant/daridorexant) approved"),
    ("Obsessive Compulsive Disorder (TRD)",     "cns", "phase2",  3, 10_000, "SSRI standard; glutamate modulators and DBS for refractory OCD"),
    ("Social Anxiety Disorder (severe)",        "cns", "phase2",  4,  5_000, "SSRIs standard; psilocybin-assisted therapy emerging"),
    ("Gambling Disorder",                       "cns", "phase2",  1,  5_000, "Naltrexone off-label; opioid system + GLP-1 intersection"),
]

# ──────────────────────────────────────────────────────────────────────────────
# DERMATOLOGY — 12+ conditions
# ──────────────────────────────────────────────────────────────────────────────
_DERMATOLOGY: List[DiseaseEntry] = [
    ("Atopic Dermatitis (severe)",              "immunology", "phase3", 5,  35_000, "Dupilumab/JAK inhibitors approved; OX40/IL-31 targets emerging"),
    ("Psoriasis (moderate-severe)",             "immunology", "phase3", 9,  40_000, "IL-17/23/12 approved; TYK2 (deucravacitinib) expanding"),
    ("Hidradenitis Suppurativa",                "immunology", "phase2", 3,  40_000, "Secukinumab approved; bimekizumab and JAK inhibitors in line"),
    ("Vitiligo (non-segmental)",                "immunology", "phase3", 1,  15_000, "Ruxolitinib cream approved 2022; systemic JAK for rapid spread"),
    ("Alopecia Areata (severe)",                "immunology", "phase3", 3,  20_000, "Baricitinib/ritlecitinib approved; additional JAK inhibitors in line"),
    ("Epidermolysis Bullosa (dystrophic)",      "rare_disease","phase3", 1, 300_000, "Beremagene peperpavec (B-VEC) approved; systemic gene therapy"),
    ("Pemphigus Vulgaris",                      "immunology", "phase2", 3,  30_000, "Rituximab approved; FcRn inhibitors (nipocalimab) emerging"),
    ("Bullous Pemphigoid",                      "immunology", "phase2", 2,  20_000, "Steroids standard; dupilumab/omalizumab showing Phase 3 signals"),
    ("Prurigo Nodularis",                       "immunology", "phase3", 1,  25_000, "Dupilumab approved 2022; nemolizumab and vixarelimab next"),
    ("Chronic Spontaneous Urticaria (refractory)","immunology","phase3",3,  15_000, "Omalizumab approved; ligelizumab/bruton's kinase inhibitors next"),
    ("Rosacea (papulopustular)",                "immunology", "phase3", 5,   3_000, "Ivermectin/brimonidine approved; afamelanotide and KPL-716 emerging"),
    ("Ichthyosis (lamellar)",                   "rare_disease","phase2", 0,  50_000, "Topical retinoids limited; trinipetide and gene therapy emerging"),
]

# ──────────────────────────────────────────────────────────────────────────────
# GI / HEPATOLOGY — 15+ conditions
# ──────────────────────────────────────────────────────────────────────────────
_GI_HEPATOLOGY: List[DiseaseEntry] = [
    ("NASH/MASH",                               "metabolic", "phase3", 1,  50_000, "Resmetirom approved 2024; pipeline crowded but huge market"),
    ("Inflammatory Bowel Disease (UC/CD)",      "immunology", "phase3", 8,  45_000, "Anti-TNF resistance; selective gut-homing biologics next"),
    ("Primary Biliary Cholangitis",             "metabolic",  "phase3", 3,  80_000, "Obeticholic acid/ursodiol standard; elafibranor/seladelpar approved"),
    ("Primary Sclerosing Cholangitis",          "metabolic",  "phase2", 1,  30_000, "No approved DMT; FXR agonists/anti-fibrotics in Phase 2"),
    ("Autoimmune Hepatitis",                    "immunology", "phase2", 2,  10_000, "Steroids/azathioprine standard; mycophenolate; biologics not approved"),
    ("Eosinophilic Esophagitis",               "immunology", "phase3", 2,  20_000, "Dupilumab/budesonide oral suspension approved; IL-13 mAb next"),
    ("Gastroparesis (diabetic)",               "metabolic",  "phase2", 2,   8_000, "Metoclopramide/domperidone; trazpiroben and ghrelin agonists"),
    ("Chronic Intestinal Pseudo-Obstruction",  "other",      "phase2", 1,  15_000, "Prucalopride off-label; no approved targeted pharmacotherapy"),
    ("Microscopic Colitis",                    "immunology", "phase2", 2,   5_000, "Budesonide standard; mesalamine and biologics need formal RCTs"),
    ("Pouchitis (chronic antibiotic-refractory)","immunology","phase2",1,  30_000, "Vedolizumab approved 2023; microbiome/FMT approaches"),
    ("Celiac Disease (refractory type II)",    "immunology", "phase2", 1,  20_000, "Gluten-free diet; larazotide gate control; immunosuppressants"),
    ("Short Bowel Syndrome",                   "rare_disease","phase3", 2, 200_000,"Teduglutide approved; apraglutide/glepaglutide in trials"),
    ("Hepatic Encephalopathy (recurrent)",     "metabolic",  "phase2", 2,   5_000, "Rifaximin/lactulose; ornithine phenylacetate in Phase 3"),
    ("Portal Hypertension (non-cirrhotic)",    "metabolic",  "phase2", 1,  10_000, "Beta-blockers palliative; TIPS invasive; simtuzumab anti-fibrotic"),
    ("Eosinophilic Gastritis",                 "immunology", "phase2", 0,  20_000, "No approved therapy; benralizumab/mepolizumab Phase 2 underway"),
]

# ──────────────────────────────────────────────────────────────────────────────
# RENAL / UROLOGY — 12+ conditions
# ──────────────────────────────────────────────────────────────────────────────
_RENAL_UROLOGY: List[DiseaseEntry] = [
    ("Chronic Kidney Disease (DKD)",            "metabolic",  "phase3", 4,  25_000, "SGLT2i/finerenone approved; GFR-preserving agents still needed"),
    ("IgA Nephropathy",                         "immunology", "phase3", 2,  20_000, "Budesonide (Tarpeyo)/iptacopan approved; sparsentan in Phase 3"),
    ("Lupus Nephritis",                         "immunology", "phase2", 3,  40_000, "Voclosporin/belimumab approved; calcineurin + complement combos"),
    ("Focal Segmental Glomerulosclerosis",      "immunology", "phase2", 2,  30_000, "Sparsentan/voclosporin in trials; no approved specific therapy"),
    ("Membranous Nephropathy",                  "immunology", "phase2", 2,  30_000, "Rituximab standard; obinutuzumab Phase 3; C3/BTK targets"),
    ("ANCA-associated Vasculitis",              "immunology", "phase2", 4,  40_000, "Avacopan approved; PR3-ANCA vs. MPO-ANCA subtype targeting"),
    ("Polycystic Kidney Disease (ADPKD)",       "rare_disease","phase3", 2, 120_000,"Tolvaptan approved; mTOR/CFTR modulator combination"),
    ("Acute Kidney Injury (hospital-acquired)", "other",      "phase2", 0,  10_000, "Supportive only; KIM-1/CCL14 biomarker-guided trial enrollment"),
    ("Bladder Cancer (muscle-invasive neoadj)","oncology",    "phase2", 4, 140_000, "EV+pembro approval; cystectomy-sparing regimens emerging"),
    ("Overactive Bladder (refractory)",         "other",      "phase3", 5,   5_000, "Antimuscarinics/mirabegron standard; vibegron/SNS devices expanding"),
    ("Interstitial Cystitis/Bladder Pain Syn.", "other",      "phase2", 3,  10_000, "Pentosan/dimethyl sulfoxide; IL-6/mast cell targeted emerging"),
    ("Kidney Transplant Rejection (chronic)",   "immunology", "phase2", 3,  30_000, "Tacrolimus/belatacept standard; anti-IL-6/C3 inhibitor trails"),
]

# ──────────────────────────────────────────────────────────────────────────────
# HEMATOLOGY — 15+ conditions
# ──────────────────────────────────────────────────────────────────────────────
_HEMATOLOGY: List[DiseaseEntry] = [
    ("Sickle Cell Disease (gene therapy)",      "gene_therapy",  "phase3", 2, 2_200_000, "Casgevy/Lyfgenia approved 2023; access/affordability gap"),
    ("Hemophilia A (inhibitors)",               "rare_disease",  "phase3", 5,   800_000, "Emicizumab transforms care; gene therapy (valoctocogene) adding"),
    ("Hemophilia B (gene therapy)",             "rare_disease",  "phase3", 3,   500_000, "Fitusiran/etranacogene approved; durability still being studied"),
    ("Beta-Thalassemia Major",                  "gene_therapy",  "phase3", 2, 1_800_000, "Betibeglogene gene therapy approved; CRISPR (Casgevy) curative"),
    ("Immune Thrombocytopenia (chronic)",       "immunology",    "phase3", 6,  30_000, "TPO-RAs/rituximab standard; FcRn inhibitors (rozanolixizumab) next"),
    ("Autoimmune Hemolytic Anemia",             "immunology",    "phase2", 3,  20_000, "Steroids/rituximab standard; sutimlimab (classical pathway) approved"),
    ("Paroxysmal Nocturnal Hemoglobinuria",     "rare_disease",  "phase3", 4, 500_000, "Eculizumab/ravulizumab standard; iptacopan oral alternative approved"),
    ("Aplastic Anemia (refractory)",            "immunology",    "phase2", 3,  30_000, "Eltrombopag+IST standard; BMT curative; CD34+ selection trials"),
    ("Diamond-Blackfan Anemia",                 "rare_disease",  "phase2", 2, 100_000, "Corticosteroids/transfusions; gene therapy (lentiviral RPL11) early"),
    ("Myelofibrosis JAK-resistant",             "oncology",      "phase2", 3, 200_000, "Ruxolitinib resistance creates second-line gap"),
    ("Essential Thrombocythemia (calreticulin)","oncology",      "phase2", 3, 30_000, "Hydroxyurea/anagrelide; targeted CalR mutation approach emerging"),
    ("Polycythemia Vera (ruxolitinib-failure)", "oncology",      "phase2", 3, 30_000, "Ruxolitinib standard; ropeginterferon long-acting option"),
    ("Waldenstrom Macroglobulinemia",           "oncology",      "phase2", 4, 150_000, "Ibrutinib+rituximab standard; zanubrutinib non-inferior emerging"),
    ("Amyloidosis (AL, cardiac)",               "rare_disease",  "phase3", 3, 400_000, "Daratumumab + CyBorD; birtamimab and anselamimab fibril-clearing"),
    ("Cold Agglutinin Disease",                 "immunology",    "phase3", 2, 100_000, "Sutimlimab approved; pegcetacoplan and iptacopan in Phase 3"),
]

# ──────────────────────────────────────────────────────────────────────────────
# GENE THERAPY TARGETS — 12+ conditions (distinct from rare_disease entries)
# ──────────────────────────────────────────────────────────────────────────────
_GENE_THERAPY: List[DiseaseEntry] = [
    ("Sickle Cell Disease (gene therapy)",      "gene_therapy", "phase3", 2, 2_200_000, "Casgevy/Lyfgenia approved 2023; access/affordability gap"),
    ("Beta-Thalassemia Major",                  "gene_therapy", "phase3", 2, 1_800_000, "Betibeglogene approved; CRISPR (Casgevy) curative approach"),
    ("Inherited Retinal Dystrophies (RPE65)",   "gene_therapy", "phase3", 1,   850_000, "Luxturna precedent; RPGR, CNGB3, CNGB1 next wave targets"),
    ("Hemophilia A (gene therapy)",             "gene_therapy", "phase3", 3, 1_500_000, "Valoctocogene (BioMarin) approved; fitusiran/marstacimab competing"),
    ("Hemophilia B (gene therapy)",             "gene_therapy", "phase3", 2, 1_500_000, "Etranacogene dezaparvovec approved 2022; durability data building"),
    ("Spinal Muscular Atrophy (one-time)",      "gene_therapy", "phase3", 1, 2_100_000, "Zolgensma IV approved; intrathecal delivery for older patients"),
    ("Aromatic L-amino acid decarboxylase def.","gene_therapy", "phase2", 0,   500_000, "Eladocagene exuparvovec approved 2022 EU; US approval pending"),
    ("X-linked Adrenoleukodystrophy",           "gene_therapy", "phase3", 1,   900_000, "Skysona approved 2022; ABCD1 lentiviral vs allogeneic HSCT"),
    ("Cerebral ALD (early)",                    "gene_therapy", "phase2", 0,   800_000, "Eli-cel approved for cerebral form; biomarker-gated enrollment"),
    ("Metachromatic Leukodystrophy",            "gene_therapy", "phase3", 1, 1_000_000, "Libmeldy approved EU; HLD gene therapy US access gap"),
    ("Chronic Granulomatous Disease",           "gene_therapy", "phase2", 0,   200_000, "HSCT curative; lentiviral correction avoids graft-versus-host"),
    ("Wiskott-Aldrich Syndrome",                "gene_therapy", "phase3", 0,   400_000, "Allogeneic HSCT standard; OTL-101 gene therapy durable"),
]

# ──────────────────────────────────────────────────────────────────────────────
# MUSCULOSKELETAL — 12+ conditions
# ──────────────────────────────────────────────────────────────────────────────
_MUSCULOSKELETAL: List[DiseaseEntry] = [
    ("Osteoarthritis (structural modification)", "immunology",   "phase2", 4,   5_000, "No DMOAD approved; sprifermin/lorecivivint/FGF-18 in Phase 2"),
    ("Osteoporosis (high fracture risk)",        "metabolic",    "phase3", 7,  15_000, "Romosozumab/abaloparatide; sequential therapy optimization"),
    ("Ankylosing Spondylitis",                   "immunology",   "phase3", 5,  35_000, "TNFi/IL-17i standard; OSM/GM-CSF targets for refractory cases"),
    ("Gout (chronic tophaceous)",                "metabolic",    "phase2", 4,   5_000, "Pegloticase/febuxostat; URAT1 inhibitors for colchicine-intolerant"),
    ("Fibromyalgia",                             "cns",          "phase2", 3,   5_000, "Duloxetine/pregabalin standard; Nav1.7 and microglia targets"),
    ("Rheumatoid Arthritis (JAK-refractory)",    "immunology",   "phase2", 8,  40_000, "Biologic/JAK failure population; next-gen targeted therapies"),
    ("Psoriatic Arthritis (refractory)",         "immunology",   "phase2", 7,  40_000, "IL-17/JAK approved; OSE-127/brepocitinib emerging"),
    ("Osteosarcoma (metastatic)",                "oncology",     "phase2", 2, 180_000, "MAP regimen unchanged for 40 years; CDK4/6 inhibitors emerging"),
    ("Myositis (dermatomyositis/IIM)",           "immunology",   "phase2", 2,  30_000, "IVIG/rituximab off-label; lenabasum/efgartigimod in Phase 3"),
    ("Periodic Fever Syndromes (NLRP3)",         "rare_disease", "phase3", 3, 200_000, "Canakinumab/rilonacept approved; oral NLRP3 inhibitors (inzomelid)"),
    ("Achondroplasia",                           "rare_disease", "phase3", 1, 400_000, "Vosoritide approved 2021; infigratinib oral FGFR3 inhibitor"),
    ("Paget Disease of Bone",                    "metabolic",    "phase2", 3,   3_000, "Zoledronic acid standard; newer bisphosphonate combinations"),
]

# ──────────────────────────────────────────────────────────────────────────────
# ADDITIONAL HIGH-VALUE AREAS
# ──────────────────────────────────────────────────────────────────────────────
_ADDITIONAL: List[DiseaseEntry] = [
    # Endocrinology
    ("Congenital Adrenal Hyperplasia (classic)", "metabolic",    "phase3", 2, 100_000, "Tildacerfont/abiraterone in Phase 3; steroid suppression gap"),
    ("Hypoparathyroidism (chronic)",             "metabolic",    "phase3", 1,  30_000, "Natpara approved; encaleret/palopegteriparatide in trials"),
    ("Growth Hormone Deficiency (adult)",        "metabolic",    "phase3", 5,  30_000, "Once-weekly somatrogon/somapacitan approved; oral GH next"),
    ("Precocious Puberty (central)",             "metabolic",    "phase3", 4,  10_000, "Histrelin/leuprolide standard; oral relugolix/elagolix gap"),
    ("Carcinoid Syndrome (refractory)",          "oncology",     "phase2", 3,  80_000, "Telotristat approved; somatostatin analog + PRRT combinations"),
    # Reproductive/OB
    ("Endometriosis (pain management)",          "other",        "phase3", 4,  10_000, "Elagolix/relugolix approved; dichloroacetate/GnRH combo"),
    ("Uterine Fibroids (symptomatic)",           "other",        "phase3", 3,  10_000, "Relugolix combo approved; focused ultrasound device gap"),
    ("Preeclampsia (prevention)",                "cardiovascular","phase2", 1,   5_000, "Aspirin standard; pravastatin/proton pump inhibitor RCTs"),
    ("Premature Ovarian Insufficiency",          "metabolic",    "phase2", 1,  10_000, "HRT only; AMH/follicle-stimulating approaches early"),
    ("Male Hypogonadism (primary)",              "metabolic",    "phase2", 4,   5_000, "TRT standard; oral testosterone undecanoate (Jatenzo) newer"),
    # Pediatric/Neonatal
    ("Neonatal Hypoxic-Ischemic Encephalopathy", "cns",          "phase2", 1,  15_000, "Cooling standard; melatonin/EPO combinations in trials"),
    ("Pediatric Inflammatory Bowel Disease",     "immunology",   "phase3", 4,  45_000, "TNFi/vedolizumab; ustekinumab in pediatric label expansion"),
    ("Kawasaki Disease (IVIG-resistant)",        "immunology",   "phase2", 2,  10_000, "IVIG standard; infliximab/anakinra for resistant disease"),
    # Infectious specialty
    ("Post-Lyme Disease Syndrome",               "amr_infectious","phase2",0,  10_000, "No approved therapy; broad antibiotic trials negative; immune target"),
    ("Chronic Fatigue Syndrome/ME",              "other",        "phase2", 0,   8_000, "No approved therapy; rintatolimod/BC007 in trials"),
    # Devices / diagnostics
    ("Sepsis (AI early detection)",              "device",       "phase2", 0,   5_000, "No approved specific therapy; diagnostic gap critical"),
    ("Continuous Glucose Monitor (next-gen)",    "device",       "phase3", 5,   3_000, "Dexcom/Libre market growing; implantable 6-month sensor gap"),
    ("Minimally Invasive Cardiac Monitoring",    "device",       "phase3", 4,   2_000, "Holter obsolete; patch/implantable loop recorder optimization"),
    # Aging / multi-morbidity
    ("Frailty Syndrome (sarcopenia)",            "metabolic",    "phase2", 1,  10_000, "No approved drug; testosterone/bimagrumab + GLP-1 combinations"),
    ("Presbycusis (age-related hearing loss)",   "other",        "phase2", 0,  10_000, "Hearing aids only; ATOH1/BDNF inner ear gene therapy emerging"),
    # Transplant
    ("Solid Organ Transplant Rejection",         "immunology",   "phase2", 4,  30_000, "Tacrolimus/belatacept; frictionless tolerogenic DC therapy"),
    ("Graft-versus-Host Disease (chronic)",      "immunology",   "phase3", 5,  30_000, "Belumosudil/ruxolitinib approved; axatilimab/itacitinib in trials"),
    # Pain
    ("Chronic Neuropathic Pain (DPN)",           "cns",          "phase2", 5,  10_000, "Duloxetine/pregabalin standard; Nav1.7 channels and CGRP targets"),
    ("Fibromyalgia",                             "cns",          "phase2", 3,   5_000, "Duloxetine/milnacipran approved; microglia/Nav1.7 targets"),
    ("Complex Regional Pain Syndrome",           "cns",          "phase2", 0,  20_000, "No approved pharmacotherapy; low-dose naltrexone/ketamine trials"),
    # Wound care / regenerative
    ("Chronic Venous Ulcers",                    "device",       "phase2", 3,   5_000, "Compression gold standard; PDGF/becaplermin topical improving"),
    ("Diabetic Foot Ulcer",                      "device",       "phase2", 4,   8_000, "Becaplermin approved; bioengineered skin substitutes + hyperbaric O2"),
]

# ──────────────────────────────────────────────────────────────────────────────
# COMBINED UNIVERSE
# ──────────────────────────────────────────────────────────────────────────────
# ── Per-disease US patient population estimates ──────────────────────────────
# Used by the scorer instead of TA-level defaults for diseases where the TA
# default is wildly off (e.g., ultra-rare ophthalmology diseases that aren't
# 600k patients despite ophthalmology TA default being 600k).
# Sources: NIH/NORD prevalence data, Orphanet, published epidemiology.
DISEASE_POPULATIONS: dict[str, int] = {
    # Ultra-rare ophthalmology / gene therapy targets
    "Choroideremia":                                    7_000,
    "X-linked Retinoschisis":                          25_000,
    "Leber Congenital Amaurosis (CEP290)":             10_000,
    "Inherited Retinal Dystrophies (RPE65)":           18_000,
    "Stargardt Disease":                               43_000,
    "Macular Telangiectasia Type 2":                   60_000,
    "Corneal Graft Failure":                           20_000,
    "Sorsby Fundus Dystrophy":                          3_000,
    "Vitreomacular Traction Syndrome":                 35_000,
    "Persistent Foveal Hypoplasia":                     5_000,
    # Rare genetic / neurological
    "Aromatic L-amino acid decarboxylase def.":         1_500,
    "CHARGE Syndrome":                                 12_000,
    "Cerebral ALD (early)":                             2_000,
    "Emery-Dreifuss Muscular Dystrophy":                5_000,
    "Ichthyosis (lamellar)":                            8_000,
    "Angelman Syndrome":                               20_000,
    "22q11.2 Deletion Syndrome":                      190_000,
    "Kabuki Syndrome":                                 16_000,
    "Prader-Willi Syndrome":                           24_000,
    "Williams Syndrome":                               30_000,
    "Cornelia de Lange Syndrome":                      10_000,
    "Smith-Lemli-Opitz Syndrome":                       5_000,
    "Rett Syndrome":                                   15_000,
    "Congenital Disorder of Glycosylation":             3_000,
    # Rare hematological
    "Cold Agglutinin Disease":                         10_000,
    "Thrombotic Thrombocytopenic Purpura (acquired)":   4_500,
    "Aplastic Anemia (refractory SAA)":                 5_000,
    "Warm Autoimmune Hemolytic Anemia":                 8_000,
    "Primary Myelofibrosis (pre-fibrotic)":            25_000,
    # Rare autoimmune / inflammatory
    "Bullous Pemphigoid":                              35_000,
    "Vitiligo (non-segmental)":                     1_500_000,
    "Graft-versus-Host Disease (chronic)":             15_000,
    "Eosinophilic Gastritis":                          15_000,
    "Focal Segmental Glomerulosclerosis":              40_000,
    "IgA Nephropathy":                                150_000,
    "Pouchitis (chronic antibiotic-refractory)":       20_000,
    "Celiac Disease (refractory type II)":             50_000,
    "Primary Biliary Cholangitis":                     65_000,
    "Autoimmune Hepatitis":                            70_000,
    "Hypoparathyroidism (chronic)":                    75_000,
    "Post-Lyme Disease Syndrome":                     200_000,
    "Traumatic Brain Injury (chronic CTE)":           400_000,
    "Autism Spectrum Disorder (core)":              3_500_000,
}


# ──────────────────────────────────────────────────────────────────────────────
# EXPANDED UNIVERSE — 300+ additional diseases across all specialties
# Covers: common cancers without subtype qualifiers, women's health, pediatrics,
# transplant, allergy, sleep, reproductive, gastroenterology, endocrinology,
# infectious disease specifics, and major rare diseases not already included
# ──────────────────────────────────────────────────────────────────────────────
_EXPANDED: List[DiseaseEntry] = [

    # ── ONCOLOGY — major common cancers and subtypes not yet covered ──────────
    ("Non-Small Cell Lung Cancer (EGFR-mutant)", "oncology", "phase3", 8, 180_000, "Osimertinib 1st-line; T790M resistance mechanisms; RET/MET co-alterations"),
    ("Non-Small Cell Lung Cancer (ALK-positive)", "oncology", "phase3", 6, 180_000, "Lorlatinib 1st-line; G1202R mutation resistance; next-gen ALK inhibitors"),
    ("Non-Small Cell Lung Cancer (RET fusion)",  "oncology", "phase3", 3, 180_000, "Selpercatinib/pralsetinib approved; combination strategies"),
    ("Non-Small Cell Lung Cancer (MET exon 14)", "oncology", "phase3", 3, 180_000, "Tepotinib/capmatinib approved; resistance via KRAS/EGFR bypass"),
    ("Non-Small Cell Lung Cancer (NTRK fusion)", "oncology", "phase2", 2, 200_000, "Larotrectinib/entrectinib approved; resistance via kinase domain mutations"),
    ("Breast Cancer (HER2-positive, brain mets)", "oncology", "phase2", 4, 200_000, "Tucatinib + T-DM1 cross CNS; unmet need for leptomeningeal disease"),
    ("Breast Cancer (triple-negative, early stage)", "oncology", "phase3", 5, 180_000, "Pembrolizumab neoadjuvant approved; residual disease strategies"),
    ("Breast Cancer (hereditary BRCA, prevention)", "oncology", "phase2", 2, 150_000, "Olaparib adjuvant; BRCA carriers with <5yr risk window"),
    ("Colorectal Cancer (BRAF V600E)", "oncology", "phase3", 3, 180_000, "Encorafenib+cetuximab approved; triplet combinations emerging"),
    ("Colorectal Cancer (HER2-amplified)", "oncology", "phase2", 2, 200_000, "Tucatinib+trastuzumab approved; ADC opportunities growing"),
    ("Colorectal Cancer (early-onset, <50yr)", "oncology", "phase2", 4, 150_000, "Rising incidence; microbiome/diet mechanisms; distinct biology"),
    ("Gastric Cancer (PD-L1 positive, 1st line)", "oncology", "phase3", 4, 180_000, "Nivolumab+chemo approved; claudin 18.2 next frontier"),
    ("Gastric Cancer (Claudin 18.2+)", "oncology", "phase3", 2, 200_000, "Zolbetuximab Phase 3 positive; ADC pipeline large"),
    ("Pancreatic Cancer (BRCA-mutant, maintenance)", "oncology", "phase3", 2, 150_000, "Olaparib maintenance approved; novel PARP+DDR combinations"),
    ("Hepatocellular Carcinoma (1st line)", "oncology", "phase3", 5, 150_000, "Atezo+bev and durva+tremelimumab approved; TKI combinations"),
    ("Renal Cell Carcinoma (clear cell, IO+TKI)", "oncology", "phase3", 6, 180_000, "Multiple combos approved; sequencing after IO-progression"),
    ("Renal Cell Carcinoma (non-clear cell)", "oncology", "phase2", 2, 180_000, "Papillary/chromophobe excluded from major trials; FH/SDHA targets"),
    ("Bladder Cancer (cisplatin-ineligible, 1st line)", "oncology", "phase3", 4, 180_000, "Enfortumab+pembro approved; FGFR3-targeted combinations"),
    ("Bladder Cancer (non-muscle-invasive, high-risk)", "oncology", "phase3", 5, 100_000, "BCG shortage; IL-15/nadofaragene and N-803 approved 2023"),
    ("Head and Neck Cancer (HPV-positive)", "oncology", "phase2", 4, 150_000, "Different biology from HPV-neg; IO response correlation varies"),
    ("Thyroid Cancer (medullary)", "oncology", "phase3", 3, 180_000, "Vandetanib/cabozantinib; RET-specific selpercatinib approved"),
    ("Thymoma / Thymic Epithelial Tumors", "oncology", "phase2", 2, 120_000, "Amivantamab activity; lensitinib; small rare population"),
    ("Uterine/Endometrial Cancer (advanced)", "oncology", "phase3", 4, 150_000, "Dostarlimab+chemo approved dMMR; pMMR still needs solutions"),
    ("Anal Cancer (locally advanced)", "oncology", "phase2", 2, 120_000, "Nivolumab+chemo; EGFR-targeted approaches; HPV-driven biology"),
    ("Testicular Cancer (refractory GCT)", "oncology", "phase2", 3, 150_000, "Carboplatin salvage standard; VEGFR/checkpoint approaches"),
    ("Meningioma (grade 2/3)", "oncology", "phase2", 1, 100_000, "No systemic therapy approved; focal RT limited; PI3K/CDK4/6 targets"),
    ("Pediatric High-Grade Glioma (DIPG/DMG)", "oncology", "phase2", 1, 150_000, "H3K27M mutation 80%; ONC201 in trials; extreme unmet need"),
    ("Pediatric Neuroblastoma (ALK-mutant)", "oncology", "phase2", 2, 150_000, "Lorlatinib in trials for ALK-mutant; immunotherapy + differentiation"),
    ("Pediatric Medulloblastoma (MYCN-amplified)", "oncology", "phase2", 2, 120_000, "WNT subgroup curable; MYCN-driven SHH subtype needs novel approaches"),
    ("Pediatric Rhabdomyosarcoma (metastatic)", "oncology", "phase2", 2, 150_000, "Vinorelbine-based regimens; IGF1R and CDK4/6 approaches"),
    ("Kaposi Sarcoma (advanced)", "oncology", "phase2", 3, 80_000, "VEGF-driven; pomalidomide active; HIV-associated and classic forms"),
    ("Primary CNS Lymphoma (PCNSL)", "oncology", "phase2", 3, 150_000, "MTX-based regimens; BTK inhibitors (ibrutinib/zanubrutinib) active"),
    ("Cutaneous Squamous Cell Carcinoma (advanced)", "oncology", "phase3", 3, 150_000, "Cemiplimab approved; combination IO approaches"),
    ("Merkel Cell Carcinoma (recurrent)", "oncology", "phase3", 2, 200_000, "Avelumab/pembrolizumab approved; high unmet in relapsed setting"),
    ("Chromophobe RCC / Oncocytoma", "oncology", "phase2", 1, 120_000, "Excluded from most RCC trials; mTOR inhibitors; distinct biology"),

    # ── WOMEN'S HEALTH ────────────────────────────────────────────────────────
    ("Endometriosis (moderate-severe)", "immunology", "phase3", 4, 12_000, "Elagolix/linzagolix approved; non-hormonal disease-modifying agents needed"),
    ("Uterine Fibroids (symptomatic)", "immunology", "phase3", 5, 8_000, "Relugolix combo approved; non-hormonal/non-surgical approaches"),
    ("Polycystic Ovary Syndrome (PCOS)", "metabolic", "phase3", 3, 5_000, "Metformin/OCP standard; insulin sensitizers + GLP-1 entering trials"),
    ("Premature Ovarian Insufficiency", "immunology", "phase2", 2, 15_000, "HRT standard; FSH receptor agonists; fertility preservation"),
    ("Preeclampsia (prevention)", "cardiovascular", "phase3", 2, 5_000, "Aspirin 81mg reduces risk; VEGF/sFlt-1 balance therapeutic target"),
    ("Gestational Diabetes", "metabolic", "phase2", 2, 5_000, "Lifestyle; metformin; GLP-1 safety in pregnancy being studied"),
    ("Vulvodynia / Vestibulodynia", "cns", "phase2", 1, 5_000, "Poorly understood chronic pain; TRPV1/nerve growth factor targets"),
    ("Female Sexual Dysfunction (HSDD)", "cns", "phase2", 2, 8_000, "Bremelanotide/flibanserin approved; melanocortin 4 receptor targets"),

    # ── PEDIATRIC CONDITIONS ──────────────────────────────────────────────────
    ("Attention Deficit Hyperactivity Disorder (pediatric)", "cns", "phase3", 15, 3_000, "Stimulants standard; non-stimulant viloxazine; digital therapeutics"),
    ("Autism Spectrum Disorder (core symptoms)", "cns", "phase2", 1, 8_000, "No core symptom therapy approved; oxytocin/GABA/mGluR targets"),
    ("Juvenile Idiopathic Arthritis (systemic)", "immunology", "phase3", 6, 40_000, "IL-1/IL-6 inhibitors; JAK inhibitors; biologic sequencing"),
    ("Pediatric Inflammatory Bowel Disease", "immunology", "phase3", 5, 40_000, "Adult biologics extended; pediatric-specific dosing/endpoints"),
    ("Type 1 Diabetes (prevention)", "metabolic", "phase3", 1, 10_000, "Teplizumab delays onset in at-risk; BCG/other immune modulation"),
    ("Pediatric Acute Lymphoblastic Leukemia (relapsed)", "oncology", "phase3", 4, 200_000, "Blinatumomab/CAR-T approved; CNS prophylaxis refinement"),
    ("Neonatal Sepsis", "amr_infectious", "phase2", 4, 10_000, "Ampicillin+gentamicin standard; novel antibacterial + immunotherapy"),
    ("Congenital Heart Disease (complex)", "cardiovascular", "phase2", 3, 50_000, "Surgical standard; cardiac regeneration/gene therapy approaches"),
    ("Epidermolysis Bullosa (severe)", "rare_disease", "phase3", 1, 200_000, "Beremagene geperpavec (B-VEC) approved 2023; gene therapy wave"),
    ("Kawasaki Disease (refractory)", "immunology", "phase2", 2, 10_000, "IVIG standard; IL-1 inhibitors for refractory; coronary artery protection"),
    ("Pediatric Nephrotic Syndrome (FSGS)", "renal_urology", "phase2", 2, 30_000, "Sparsentan approved; APOL1-targeting approaches"),

    # ── INFECTIOUS DISEASE ────────────────────────────────────────────────────
    ("HIV (treatment-naive, long-acting)", "amr_infectious", "phase3", 15, 25_000, "Cabotegravir+rilpivirine 2-monthly; 6-monthly lenacapavir emerging"),
    ("HIV (reservoir eradication/cure)", "amr_infectious", "phase2", 1, 50_000, "Shock-and-kill; silencing strategies; no approved cure therapy"),
    ("Chronic Hepatitis B (functional cure)", "amr_infectious", "phase2", 5, 8_000, "NrtIs suppress; capsid inhibitors + RNAi approaching functional cure"),
    ("Chronic Hepatitis Delta (HDV)", "amr_infectious", "phase3", 1, 50_000, "Bulevirtide approved in EU; lonafarnib; extreme unmet need"),
    ("Clostridioides difficile (recurrent CDI)", "amr_infectious", "phase3", 4, 8_000, "Bezlotoxumab reduces recurrence; LBP microbiome therapies (Vowst)"),
    ("Tuberculosis (drug-resistant MDR/XDR)", "amr_infectious", "phase3", 3, 15_000, "BPaL regimen 6-month cure; novel nitroimidazoles; WHO priority"),
    ("Invasive Aspergillosis (immunocompromised)", "amr_infectious", "phase2", 5, 25_000, "Voriconazole/isavuconazole standard; ibrexafungerp for breakthrough"),
    ("Candida auris (invasive)", "amr_infectious", "phase3", 2, 30_000, "Olorofim approved 2023; rezafungin; extreme multidrug resistance"),
    ("Respiratory Syncytial Virus (adult/elderly)", "vaccine", "phase3", 2, 300, "Arexvy/Abrysvo approved 2023; nirsevimab for pediatric protection"),
    ("Influenza (high-dose/adjuvanted, elderly)", "vaccine", "phase3", 8, 200, "Fluzone HD/Fluad approved; mRNA universal flu vaccine phase 3"),
    ("Mpox (severe immunocompromised)", "amr_infectious", "phase2", 2, 5_000, "Tecovirimat + JYNNEOS; immunocompromised patients at highest risk"),
    ("Dengue Fever (vaccine-preventable)", "vaccine", "phase3", 1, 250, "Dengvaxia limited use; TAK-003 Qdenga broader indication"),
    ("Malaria (preventive + treatment)", "vaccine", "phase3", 3, 500, "RTS,S/R21 approved; tafenoquine for P. vivax; endectocides"),
    ("West Nile Virus Encephalitis", "amr_infectious", "phase2", 0, 20_000, "No approved therapy; monoclonal antibody/antiviral approaches"),
    ("Chagas Disease (chronic cardiac)", "amr_infectious", "phase2", 2, 5_000, "Benznidazole/nifurtimox for acute; chronic cardiac phase underserved"),
    ("Leishmaniasis (visceral)", "amr_infectious", "phase2", 2, 8_000, "Liposomal amphotericin B; miltefosine; WHO neglected disease"),

    # ── CARDIOVASCULAR (expanded) ─────────────────────────────────────────────
    ("Hypertrophic Cardiomyopathy (obstructive)", "cardiovascular", "phase3", 2, 50_000, "Mavacamten approved; aficamten in trials; myosin inhibitor class"),
    ("Dilated Cardiomyopathy (LMNA-mutant)", "cardiovascular", "phase2", 1, 30_000, "SGLT2/sacubitril standard; gene therapy targeting lamin A/C"),
    ("Cardiac Amyloidosis (ATTR)", "cardiovascular", "phase3", 3, 50_000, "Tafamidis approved; patisiran/vutrisiran approved for ATTR-CM; eplontersen"),
    ("Pulmonary Hypertension (Group 3, WHO)", "cardiovascular", "phase2", 2, 30_000, "No approved PAH therapy for lung disease-associated PH; inhaled prostacyclins"),
    ("Peripheral Artery Disease (critical limb ischemia)", "cardiovascular", "phase3", 3, 20_000, "SGLT2i reduces MACE; revascularization plus gene therapy (HGF)"),
    ("Spontaneous Coronary Artery Dissection (SCAD)", "cardiovascular", "phase2", 1, 15_000, "Mostly young women; underlying connective tissue disease; fibromuscular dysplasia"),
    ("Cardiac Sarcoidosis", "immunology", "phase2", 2, 30_000, "Corticosteroid standard; TNF inhibitors in small series"),
    ("Venous Thromboembolism (recurrent prevention)", "cardiovascular", "phase3", 5, 8_000, "NOAC standard; factor XI inhibitors (asundexian) for safer anticoagulation"),

    # ── METABOLIC / ENDOCRINE (expanded) ─────────────────────────────────────
    ("Type 1 Diabetes (automated insulin delivery)", "metabolic", "phase3", 5, 10_000, "Closed-loop systems (Control-IQ, Omnipod 5); ultra-rapid insulin analogs"),
    ("Hypoglycemia (severe recurrent)", "metabolic", "phase2", 2, 15_000, "Glucagon kits standard; dasiglucagon nasal; SGLT2 cessation approaches"),
    ("Acromegaly (treatment-resistant)", "metabolic", "phase3", 3, 25_000, "Octreotide/lanreotide standard; pasireotide/pegvisomant; paltusotine oral"),
    ("Cushing Disease (recurrent)", "metabolic", "phase3", 3, 30_000, "Osilodrostat/pasireotide approved; relacorilant (GR antagonist) in trials"),
    ("Primary Hyperoxaluria Type 1 (PH1)", "rare_disease", "phase3", 1, 200_000, "Lumasiran approved (RNAi to reduce oxalate); nedosiran coming"),
    ("Lysosomal Acid Lipase Deficiency (LALD)", "rare_disease", "phase3", 1, 200_000, "Sebelipase alfa approved; ERT challenges; gene therapy wave"),
    ("Transthyretin Amyloidosis (ATTRv, hereditary)", "rare_disease", "phase3", 3, 150_000, "Patisiran/inotersen/eplontersen approved; vutrisiran 3-monthly"),
    ("Adiposity Hypoventilation Syndrome (OHS)", "respiratory", "phase2", 2, 10_000, "PAP therapy; weight loss; GLP-1 emerging as disease-modifying"),

    # ── RESPIRATORY (expanded) ────────────────────────────────────────────────
    ("Asthma (uncontrolled type 2)", "immunology", "phase3", 8, 25_000, "IL-4/13/5 biologics approved; tezepelumab thymic stromal lymphopoietin target"),
    ("Asthma (non-type 2, neutrophilic)", "respiratory", "phase2", 3, 15_000, "Corticosteroid-dependent; no approved biologic; CXCR2 antagonists"),
    ("COPD (eosinophilic exacerbations)", "respiratory", "phase3", 6, 10_000, "Dupilumab approved 2024; mepolizumab trial data positive"),
    ("COPD (alpha-1 antitrypsin deficiency)", "rare_disease", "phase3", 3, 80_000, "Augmentation therapy IV; inhaled formulations + gene therapy"),
    ("Idiopathic Pulmonary Fibrosis (progressive)", "respiratory", "phase3", 3, 40_000, "Pirfenidone/nintedanib approved; autotaxin inhibitors (ziritaxestat withdrawn); TGFB targets"),
    ("Pleuroparenchymal Fibroelastosis (PPFE)", "respiratory", "phase2", 0, 30_000, "Rare ILD variant; no approved therapy; antifibrotic candidates being studied"),
    ("Bronchiectasis (non-CF)", "respiratory", "phase3", 2, 15_000, "Inhaled antibiotics (tobramycin, colistin); brensocatib (DPP1 inhibitor)"),
    ("Primary Ciliary Dyskinesia (advanced)", "respiratory", "phase2", 0, 30_000, "No approved disease-modifying therapy; airway clearance devices only"),
    ("Hypersensitivity Pneumonitis (chronic)", "respiratory", "phase2", 1, 25_000, "Antigen avoidance; nintedanib active; immunosuppression for progressive"),

    # ── GASTROENTEROLOGY / HEPATOLOGY (expanded) ──────────────────────────────
    ("Primary Sclerosing Cholangitis (PSC)", "immunology", "phase2", 0, 50_000, "No approved disease-modifying therapy; PPAR/FXR agonists in trials"),
    ("Primary Biliary Cholangitis (PBC, second-line)", "immunology", "phase3", 2, 70_000, "Ursodiol standard; obeticholic acid/elafibranor approved 2nd line"),
    ("Autoimmune Hepatitis (refractory)", "immunology", "phase2", 2, 20_000, "Azathioprine/steroids; budesonide; JAK inhibitors in refractory forms"),
    ("Wilson's Disease", "rare_disease", "phase3", 3, 30_000, "Chelation standard; ALXN2075/fosdenopterin; liver transplant curative"),
    ("Celiac Disease (refractory type 2)", "immunology", "phase2", 1, 30_000, "Gluten-free diet insufficient; latiglutenase/TG2 inhibitors in trials"),
    ("Short Bowel Syndrome (IF-associated liver disease)", "rare_disease", "phase3", 2, 200_000, "Teduglutide approved; lanreotide; parenteral nutrition weaning"),
    ("Achalasia (refractory)", "gi_hepatology", "phase2", 2, 15_000, "Per-oral endoscopic myotomy (POEM); botulinum toxin; no drug therapy"),
    ("Gastroparesis (diabetic)", "metabolic", "phase3", 2, 8_000, "Metoclopramide standard; relamorelin/prucalopride; gastric neurostimulator"),
    ("Eosinophilic Esophagitis (EoE)", "immunology", "phase3", 2, 30_000, "Dupilumab approved 2022; cendakimab/budesonide; dietary approaches"),
    ("Functional Dyspepsia (Rome IV)", "gi_hepatology", "phase2", 3, 5_000, "Proton pump inhibitors; mirtazapine; FDgard; gut-brain axis targets"),
    ("Intestinal Behcet's Disease", "immunology", "phase2", 2, 40_000, "TNF inhibitors; ustekinumab; limited evidence base"),

    # ── RENAL / UROLOGY (expanded) ────────────────────────────────────────────
    ("IgA Nephropathy (progressive)", "immunology", "phase3", 2, 30_000, "Sparsentan approved; iptacopan/atrasentan; budesonide targeted release"),
    ("Membranous Nephropathy (anti-PLA2R+)", "immunology", "phase3", 2, 40_000, "Rituximab standard; obinutuzumab; PLA2R-targeted therapies"),
    ("Lupus Nephritis (class III/IV)", "immunology", "phase3", 3, 50_000, "Voclosporin+belimumab approved; obinutuzumab/anifrolumab active"),
    ("ANCA-associated Vasculitis (refractory)", "immunology", "phase3", 3, 50_000, "Avacopan approved 2021; ixekizumab; B-cell depletion strategies"),
    ("Polycystic Kidney Disease (ADPKD)", "rare_disease", "phase3", 2, 40_000, "Tolvaptan approved; mTOR inhibitors failed; bardoxolone in trials"),
    ("Hyperoxaluria (secondary, enteric)", "metabolic", "phase2", 1, 30_000, "Pyridoxine for primary; oxalobacter bacteria; dietary modifications"),
    ("Bladder Pain Syndrome (IC/BPS)", "renal_urology", "phase2", 3, 5_000, "Intravesical therapies; pentosan polysulfate; LiRIS device"),
    ("Overactive Bladder (neurogenic)", "cns", "phase3", 5, 4_000, "Mirabegron/onabotulinumtoxin A approved; vibegron; device approaches"),
    ("Benign Prostatic Hyperplasia (surgical alternatives)", "renal_urology", "phase3", 8, 5_000, "Alpha blockers/5ARIs; Rezum/UroLift devices; PAE procedures"),
    ("Chronic Kidney Disease (CKD progression)", "metabolic", "phase3", 4, 8_000, "SGLT2/finerenone slows progression; atrasentan in IgA; BAR502"),

    # ── MUSCULOSKELETAL (expanded) ────────────────────────────────────────────
    ("Osteoporosis (treatment-resistant)", "metabolic", "phase3", 8, 20_000, "Romosozumab/abaloparatide approved; next-generation cathepsin K inhibitors"),
    ("Osteoarthritis (knee, structural modification)", "immunology", "phase3", 3, 8_000, "No DMOAD approved; FGF18 (sprifermin); IL-1/CGRP targets; gene therapy"),
    ("Ankylosing Spondylitis (active, bio-naive)", "immunology", "phase3", 6, 40_000, "IL-17/TNF inhibitors approved; JAK inhibitors; MRGPRX4 itch targets"),
    ("Diffuse Idiopathic Skeletal Hyperostosis (DISH)", "musculoskeletal", "phase2", 0, 5_000, "NSAIDs only; BMP/FGF pathway understanding emerging; unmet need"),
    ("Fibromyalgia (refractory)", "cns", "phase2", 3, 5_000, "Pregabalin/duloxetine/milnacipran standard; TRP channel antagonists; LDN"),
    ("Complex Regional Pain Syndrome (CRPS)", "cns", "phase2", 2, 8_000, "Multimodal pain; ketamine infusion; spinal cord stimulation; CGRP targets"),
    ("Dupuytren's Disease (progressive)", "musculoskeletal", "phase2", 2, 5_000, "Collagenase injection standard; nintedanib showing activity"),
    ("Tendinopathy (achilles/patellar, chronic)", "musculoskeletal", "phase2", 2, 3_000, "PRP injections; extracorporeal shockwave; TGFβ/BMP growth factor biologics"),

    # ── DERMATOLOGY (expanded) ────────────────────────────────────────────────
    ("Atopic Dermatitis (moderate-severe, pediatric)", "immunology", "phase3", 5, 30_000, "Dupilumab/tralokinumab approved; JAK inhibitors; pediatric dosing gap"),
    ("Prurigo Nodularis (moderate-severe)", "immunology", "phase3", 1, 40_000, "Dupilumab approved 2022; nemolizumab; IL-31/TSLP pathway targets"),
    ("Alopecia Areata (severe, >50% scalp loss)", "immunology", "phase3", 2, 20_000, "Baricitinib/ritlecitinib approved; hair follicle immune privilege restoration"),
    ("Vitiligo (progressive)", "immunology", "phase3", 1, 15_000, "Ruxolitinib cream approved 2022; melanocyte transplantation; afamelanotide"),
    ("Hidradenitis Suppurativa (moderate-severe)", "immunology", "phase3", 2, 50_000, "Adalimumab/secukinumab approved; bimekizumab Phase 3 positive"),
    ("Chronic Urticaria (refractory antihistamine)", "immunology", "phase3", 3, 25_000, "Omalizumab approved; ligelizumab Phase 3 failed; bruton's tyrosine kinase"),
    ("Bullous Pemphigoid (elderly)", "immunology", "phase3", 2, 30_000, "Super-potent topical steroids; dupilumab/omalizumab emerging data"),
    ("Pemphigus Vulgaris (relapsing)", "immunology", "phase3", 3, 50_000, "Rituximab standard; efgartigimod (FcRn inhibitor) approved"),
    ("Ichthyosis (lamellar/congenital)", "rare_disease", "phase2", 1, 50_000, "No systemic approved; retinoids topical; gene therapy coming"),
    ("Rosacea (ocular, refractory)", "immunology", "phase3", 4, 5_000, "Ivermectin/brimonidine topical; opzelura; laser; IL-1 pathway"),
    ("Cutaneous Lupus (SCLE/DLE)", "immunology", "phase2", 2, 20_000, "Hydroxychloroquine standard; anifrolumab active in skin; BIIB059"),
    ("Keloid Scarring (recurrent)", "dermatology", "phase2", 2, 5_000, "Intralesional steroids/5-FU; nintedanib systemic; anti-TGFβ biologics"),

    # ── MENTAL HEALTH (expanded) ──────────────────────────────────────────────
    ("Anorexia Nervosa (severe)", "cns", "phase2", 1, 15_000, "Only olanzapine has modest evidence; no FDA-approved treatment"),
    ("Binge Eating Disorder (BED)", "cns", "phase3", 1, 5_000, "Lisdexamfetamine approved; GLP-1 emerging as appetite regulator"),
    ("Generalized Anxiety Disorder (refractory)", "cns", "phase2", 5, 5_000, "SSRIs/SNRIs standard; buspirone; GABA-A positive modulators; FAAH"),
    ("Social Anxiety Disorder (SAD)", "cns", "phase2", 3, 5_000, "SSRIs/venlafaxine standard; oxytocin; psychedelic-assisted therapy"),
    ("Borderline Personality Disorder", "cns", "phase2", 0, 8_000, "No FDA-approved pharmacotherapy; DBT gold standard; GLP-1 satiety/impulsivity"),
    ("Trichotillomania / Body-Focused Repetitive Behaviors", "cns", "phase2", 1, 5_000, "N-acetylcysteine; olanzapine; habit reversal therapy; glutamate modulation"),
    ("Insomnia Disorder (chronic)", "cns", "phase3", 6, 3_000, "Lemborexant/daridorexant (orexin); digital CBT-I; novel non-benzodiazepines"),
    ("Restless Legs Syndrome (refractory)", "cns", "phase2", 5, 5_000, "DA agonists; augmentation problem; α2δ ligands; iron supplementation"),

    # ── OPHTHALMOLOGY (expanded) ──────────────────────────────────────────────
    ("Glaucoma (normal-tension)", "ophthalmology", "phase2", 4, 3_000, "IOP-lowering standard; neuroprotection unproven; netarsudil/latanoprost"),
    ("Diabetic Retinopathy (non-proliferative)", "ophthalmology", "phase3", 3, 5_000, "Faricimab/aflibercept active; systemic GLP-1 may reduce progression"),
    ("Retinitis Pigmentosa (RP, inherited)", "rare_disease", "phase2", 1, 50_000, "Voretigene (RPE65) approved; rod/cone gene therapy wave expanding"),
    ("Corneal Dystrophy (CHED/Fuchs)", "ophthalmology", "phase2", 1, 20_000, "Endothelial keratoplasty gold standard; y-27632 eye drops regeneration"),
    ("Age-Related Macular Degeneration (dry, early)", "ophthalmology", "phase3", 2, 5_000, "No approved systemic; AREDS supplements; complement inhibitors (pegcetacoplan)"),
    ("Uveitis (non-infectious, posterior)", "immunology", "phase3", 3, 30_000, "Adalimumab approved; sirolimus implant; faricimab/brolucizumab"),
    ("Thyroid Eye Disease (mild-moderate)", "immunology", "phase3", 2, 200_000, "Teprotumumab approved; linsitinib; less invasive alternatives to surgery"),

    # ── ALLERGY / IMMUNOLOGY ──────────────────────────────────────────────────
    ("Food Allergy (peanut, PPOIT prevention)", "immunology", "phase3", 1, 5_000, "Palforzia approved; omalizumab as adjunct; tolerance induction protocols"),
    ("Hereditary Angioedema (recurrent attacks)", "rare_disease", "phase3", 4, 200_000, "Lanadelumab/garadacimab prophylaxis; abelacimab; denitrification not practical"),
    ("Mastocytosis (advanced systemic)", "rare_disease", "phase3", 1, 150_000, "Avapritinib approved for D816V; ripretinib; KIT-directed therapies"),
    ("Eosinophilic Granulomatosis with Polyangiitis (EGPA)", "immunology", "phase3", 2, 40_000, "Mepolizumab approved; benralizumab in trials; B-cell depleting approaches"),
    ("Common Variable Immunodeficiency (CVID)", "rare_disease", "phase3", 2, 30_000, "IVIG/SCIG standard; subcutaneous facilitated; B-cell reconstitution"),
    ("Hyper-IgE Syndrome (STAT3-mutant)", "rare_disease", "phase2", 0, 50_000, "No approved specific therapy; IVIG + antibiotics; JAK inhibition under study"),

    # ── ENDOCRINOLOGY ─────────────────────────────────────────────────────────
    ("Hypothyroidism (treatment-resistant, T3 deficiency)", "metabolic", "phase2", 2, 3_000, "Levothyroxine + liothyronine combo; slow-release T3; thyroid tissue engineering"),
    ("Addison's Disease (adrenal insufficiency)", "metabolic", "phase2", 2, 5_000, "Hydrocortisone standard; once-daily modified-release (Plenadren); pump systems"),
    ("Hypoparathyroidism (chronic)", "metabolic", "phase3", 2, 50_000, "Palopegteriparatide (TransCon PTH) approved 2024; long-acting PTH analogs"),
    ("Hyperparathyroidism (persistent/recurrent)", "metabolic", "phase3", 3, 15_000, "Cinacalcet standard; denosumab for hypercalcemia; surgical residual disease"),
    ("Carcinoid Tumors / NET (progressive)", "oncology", "phase3", 4, 80_000, "Octreotide LAR/lanreotide approved; everolimus; 177Lu-DOTATATE approved"),

    # ── HEMATOLOGY (expanded) ─────────────────────────────────────────────────
    ("Aplastic Anemia (severe, relapsed)", "hematology", "phase3", 3, 80_000, "Eltrombopag standard; eltanexor (XPO1); Allo-SCT for young patients"),
    ("Paroxysmal Nocturnal Hemoglobinuria (PNH)", "rare_disease", "phase3", 4, 400_000, "Ravulizumab/pegcetacoplan approved; iptacopan (factor B) 2023"),
    ("Warm Autoimmune Hemolytic Anemia (wAIHA)", "hematology", "phase3", 3, 50_000, "Rituximab/steroids standard; sutimlimab (complement) approved; PI3K delta"),
    ("Immune Thrombocytopenic Purpura (chronic ITP)", "hematology", "phase3", 6, 80_000, "Eltrombopag/romiplostim/fostamatinib approved; rilzabrutinib emerging"),
    ("Thrombotic Thrombocytopenic Purpura (acquired)", "hematology", "phase3", 2, 100_000, "Caplacizumab approved (anti-VWF nanobody); immune suppression"),
    ("Cold Agglutinin Disease (CAD)", "hematology", "phase3", 2, 200_000, "Sutimlimab approved 2022; iptacopan; pegcetacoplan"),
    ("Beta-Thalassemia (transfusion-dependent)", "rare_disease", "phase3", 3, 200_000, "Luspatercept/beti-cel/lovotibeglogene approved; gene editing curative"),
    ("Hemophilia A (inhibitor, factor replacement)", "rare_disease", "phase3", 4, 400_000, "Emicizumab approved; fitusiran; valoctocogene (BioMarin gene therapy)"),
    ("Hemophilia B (gene therapy eligible)", "rare_disease", "phase3", 3, 300_000, "Etranacogene (Hemgenix) approved; fitusiran; fidanacogene dezaparvovec"),

    # ── NEUROMUSCULAR (expanded) ──────────────────────────────────────────────
    ("Myasthenia Gravis (generalized, anti-AChR)", "immunology", "phase3", 4, 50_000, "Efgartigimod/rozanolixizumab approved; FcRn inhibitors; complement (zilucoplan)"),
    ("Lambert-Eaton Myasthenic Syndrome (LEMS)", "immunology", "phase2", 2, 30_000, "Amifampridine approved; immune suppression; VGCC-targeted approaches"),
    ("Multifocal Motor Neuropathy (MMN)", "immunology", "phase2", 2, 50_000, "IVIG standard; subcutaneous Ig; no disease-modifying agent approved"),
    ("Chronic Inflammatory Demyelinating Polyneuropathy (CIDP)", "immunology", "phase3", 3, 50_000, "Efgartigimod SC approved 2023; avacopan; IVIG 10g subcutaneous"),
    ("Stiff Person Syndrome (progressive)", "immunology", "phase2", 2, 30_000, "IVIG/diazepam standard; rituximab; anti-GAD65 autoantibody target"),
    ("Transverse Myelitis (NMO spectrum)", "immunology", "phase3", 4, 100_000, "Inebilizumab/satralizumab/ublituximab approved; eculizumab for severe"),
    ("Inclusion Body Myositis (IBM)", "immunology", "phase2", 0, 30_000, "No approved therapy; arimoclomol failed; follistatin/ACE-031 muscle loss"),

    # ── TRANSPLANT / GRAFT ────────────────────────────────────────────────────
    ("Kidney Transplant Rejection (antibody-mediated)", "immunology", "phase3", 2, 50_000, "No approved AMR therapy; avacopan + daratumumab in trials; complement targets"),
    ("Liver Transplant (primary non-function prevention)", "immunology", "phase2", 2, 30_000, "Machine perfusion standard; C1-esterase inhibitor; ex-vivo reconditioning"),
    ("Graft-versus-Host Disease (chronic)", "immunology", "phase3", 3, 80_000, "Belumosudil/ibrutinib/ruxolitinib approved; KD025; JAK inhibitors"),
    ("Organ Preservation (extended criteria donors)", "immunology", "phase2", 1, 30_000, "Normothermic machine perfusion approved devices; ex-vivo gene editing"),

    # ── DEVICE / DIAGNOSTIC OPPORTUNITIES ────────────────────────────────────
    ("Early Cancer Detection (multi-cancer blood test)", "diagnostic", "phase3", 1, 1_000, "Galleri/Shield approved; cfDNA + methylation; massive population screening"),
    ("Sepsis Rapid Diagnostics (blood culture-free)", "diagnostic", "phase3", 2, 2_000, "T2Biosystems/GenMark; BCID panels; host-response biomarker (InSep)"),
    ("Cardiac Biomarker (high-sensitivity troponin, ED rule-out)", "diagnostic", "phase3", 5, 500, "hs-cTnI standard; 0-hour/1-hour protocols; AI integration"),
    ("Alzheimer Blood Test (p-tau 217)", "diagnostic", "phase3", 1, 1_000, "Lumipulse/Elecsys approved; plasma p-tau217 vs PET/CSF; triage tool"),
    ("Continuous Glucose Monitor (factory-calibrated, 15-day)", "device", "phase3", 4, 6_000, "Dexcom G7/Libre 3 approved; 15-day next; gestational DM application"),
    ("Wearable Cardiac Monitor (AI-interpreted, 30-day)", "device", "phase3", 5, 2_000, "Zio patch/MCOT standard; AI-extended wear; atrial fibrillation screening"),
    ("Implantable Glucose Monitor (no fingerstick, 6-month)", "device", "phase2", 1, 8_000, "Eversense approved but limited; next-gen fully implantable"),
    ("Retinal Imaging AI (diabetic retinopathy screening)", "diagnostic", "phase3", 2, 500, "IDx-DR FDA cleared; optic disc/AMD AI; telemedicine integration"),
    ("Neuromodulation (vagus nerve, heart failure)", "device", "phase3", 2, 30_000, "CardioFit trial; ANTHEM-HFrEF; autonomic rebalancing devices"),
    ("Smart Inhaler (adherence + spirometry)", "device", "phase3", 3, 1_000, "Propeller/Adherium cleared; AI exacerbation prediction; sensor integration"),

    # ── SLEEP MEDICINE ────────────────────────────────────────────────────────
    ("Obstructive Sleep Apnea (CPAP-intolerant)", "device", "phase3", 3, 20_000, "Inspire hypoglossal nerve stimulation; erenumab/tirzepatide reducing AHI"),
    ("Central Sleep Apnea (HF-associated)", "cardiovascular", "phase3", 2, 15_000, "Remede system approved; adaptive servo-ventilation; cardiac optimization"),
    ("Idiopathic Hypersomnia", "cns", "phase3", 1, 10_000, "Sodium oxybate for idiopathic hypersomnia approved 2021; clarithromycin; GABA-A"),
    ("REM Sleep Behavior Disorder (prodromal PD)", "cns", "phase2", 2, 5_000, "Clonazepam standard; melatonin; α-synuclein vaccine trials via RBD biomarker"),

    # ── PAIN / ANESTHESIA ─────────────────────────────────────────────────────
    ("Chronic Low Back Pain (discogenic)", "cns", "phase3", 5, 5_000, "NSAID/opioid standard; intradiscal biologics (GDF-5, PRP); neuromodulation"),
    ("Postherpetic Neuralgia (PHN)", "cns", "phase3", 4, 5_000, "Gabapentinoids standard; capsaicin patch; sodium channel Nav1.7 inhibitors"),
    ("Chemotherapy-Induced Peripheral Neuropathy (CIPN)", "cns", "phase2", 1, 5_000, "Duloxetine only evidence; no approved prevention; VEGF/BDNF neuroprotection"),
    ("Diabetic Peripheral Neuropathy (painful DPN)", "metabolic", "phase3", 3, 5_000, "Duloxetine/pregabalin/tapentadol standard; CGRP receptor antagonists"),
    ("Cluster Headache (chronic, refractory)", "cns", "phase3", 3, 20_000, "Galcanezumab approved for episodic; CGRP/PACAP pathway; sphenopalatine ganglion"),
    ("Trigeminal Neuralgia (refractory medical)", "cns", "phase2", 2, 5_000, "Carbamazepine standard; surgical MVD; sodium channel Nav1.7/1.3 approaches"),
]


def get_disease_population(disease_name: str) -> int | None:
    """Return known US patient population for a disease, or None to use TA default."""
    return DISEASE_POPULATIONS.get(disease_name)


def get_universe() -> List[DiseaseEntry]:
    """
    Return the full 309+ disease universe as a deduplicated list.
    The seed list is static; live CT.gov trial counts are fetched at score time.
    Safe to import without any database connection.
    """
    combined = (
        _ONCOLOGY
        + _CNS
        + _CARDIOVASCULAR
        + _METABOLIC
        + _IMMUNOLOGY
        + _RESPIRATORY
        + _INFECTIOUS
        + _RARE_GENETIC
        + _OPHTHALMOLOGY
        + _MENTAL_HEALTH
        + _DERMATOLOGY
        + _GI_HEPATOLOGY
        + _RENAL_UROLOGY
        + _HEMATOLOGY
        + _GENE_THERAPY
        + _MUSCULOSKELETAL
        + _ADDITIONAL
        + _EXPANDED
    )
    # Deduplicate by disease name (first occurrence wins)
    seen: set[str] = set()
    unique: List[DiseaseEntry] = []
    for entry in combined:
        name = entry[0]
        if name not in seen:
            seen.add(name)
            unique.append(entry)
    return unique
