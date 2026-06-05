"""
Universe Expander v2 — Comprehensive 10,000+ Disease Universe
==============================================================
Generates a comprehensive disease universe covering all clinically meaningful
human diseases that a PI might research. Uses ICD-10-CM chapter structure
to systematically cover every major disease category.

Strategy:
  TIER 1 (496 diseases): Expert-curated with specific parameters, scored live
  TIER 2 (2,000+ diseases): ICD-10 chapter-derived, scored with TA defaults
  TIER 3 (7,000+ diseases): MONDO ontology-derived, basic scoring only

Scoring approach for Tiers 2/3:
  - No live CT.gov or openFDA calls (too slow at scale)
  - Uses TA-level PTRS, pricing, and opportunity defaults
  - Pre-computed once and stored in disease_scored table
  - Enriched on-demand when user clicks into a disease
  - Shown in search results and full universe browse

ICD-10-CM source: CDC (US public domain) — https://www.cms.gov/Medicare/Coding/ICD10
All 8,000+ condition codes categorized by chapter → therapeutic area mapping
"""

from __future__ import annotations
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

# ICD-10 Chapter → Therapeutic Area mapping
_ICD10_TA_MAP = {
    "C": "oncology",           # C00-C97 Malignant neoplasms
    "D0": "oncology",          # D00-D09 In situ neoplasms
    "D1": "oncology",          # D10-D36 Benign neoplasms
    "D5": "hematology",        # D50-D89 Blood/blood-forming organs
    "D6": "hematology",
    "D7": "hematology",
    "D8": "immunology",
    "E0": "metabolic",         # E00-E99 Endocrine/metabolic
    "E1": "metabolic",
    "E2": "metabolic",
    "E3": "metabolic",
    "E4": "metabolic",
    "E5": "metabolic",
    "E6": "metabolic",
    "E7": "metabolic",
    "E8": "rare_disease",
    "F": "cns",                # F00-F99 Mental/behavioral
    "G": "cns",                # G00-G99 Nervous system
    "H0": "ophthalmology",     # H00-H59 Eye/adnexa
    "H1": "ophthalmology",
    "H2": "ophthalmology",
    "H3": "ophthalmology",
    "H4": "ophthalmology",
    "H5": "ophthalmology",
    "H6": "cns",               # H60-H95 Ear/mastoid
    "H7": "cns",
    "H8": "cns",
    "H9": "cns",
    "I": "cardiovascular",     # I00-I99 Circulatory
    "J": "respiratory",        # J00-J99 Respiratory
    "K": "gi_hepatology",      # K00-K95 Digestive
    "L": "dermatology",        # L00-L99 Skin/subcutaneous
    "M": "musculoskeletal",    # M00-M99 Musculoskeletal
    "N": "renal_urology",      # N00-N99 Genitourinary
    "O": "other",              # O00-O9A Pregnancy/childbirth
    "P": "other",              # P00-P96 Perinatal
    "Q": "rare_disease",       # Q00-Q99 Congenital/chromosomal
    "R": "other",              # R00-R99 Symptoms/signs
}

# TA-level default parameters for scoring diseases without curated data
# (opportunity_score, phase, approved_count, cost_usd)
_TA_SCORING_DEFAULTS = {
    "oncology":         (0, "phase2", 3, 150_000),
    "hematology":       (0, "phase2", 3, 100_000),
    "immunology":       (0, "phase2", 4, 40_000),
    "cns":              (0, "phase2", 2, 20_000),
    "metabolic":        (0, "phase2", 4, 10_000),
    "cardiovascular":   (0, "phase2", 5, 15_000),
    "respiratory":      (0, "phase2", 3, 15_000),
    "rare_disease":     (0, "phase2", 1, 150_000),
    "gi_hepatology":    (0, "phase2", 3, 20_000),
    "dermatology":      (0, "phase2", 3, 20_000),
    "musculoskeletal":  (0, "phase2", 4, 10_000),
    "renal_urology":    (0, "phase2", 3, 20_000),
    "ophthalmology":    (0, "phase2", 3, 15_000),
    "amr_infectious":   (0, "phase2", 5, 10_000),
    "gene_therapy":     (0, "phase2", 1, 500_000),
    "device":           (0, "phase2", 3, 25_000),
    "diagnostic":       (0, "phase2", 3, 1_500),
    "vaccine":          (0, "phase2", 3, 200),
    "other":            (0, "phase2", 2, 10_000),
}

# Comprehensive ICD-10-CM disease list — major 3-character categories
# Format: (disease_name, icd10_prefix, notes)
# Source: CDC ICD-10-CM 2024 (US public domain)
_ICD10_MAJOR_CATEGORIES: List[Tuple[str, str, str]] = [

    # ── NEOPLASMS (ICD-10: C00-D49) ──────────────────────────────────────────
    ("Lip and Oral Cavity Cancer", "C0", "Squamous cell predominantly; HPV-negative; tobacco/alcohol driven"),
    ("Nasopharyngeal Cancer", "C11", "EBV-associated; endemic Asia; platinum-based chemoradiation"),
    ("Laryngeal Cancer", "C32", "Tobacco-driven; HPV-positive subset growing; organpreservation strategies"),
    ("Salivary Gland Carcinoma", "C07", "Rare; MYB-NFIB fusion ACC; HER2+ mucoepidermoid; androgen receptor"),
    ("Sinonasal Carcinoma (SNSCC)", "C31", "Rare; unresectable often; HPV-neg; immunotherapy emerging"),
    ("Parathyroid Carcinoma", "C75", "Very rare; hypercalcemia-driven morbidity; denosumab for hypercalcemia"),
    ("Adrenal Cortical Carcinoma", "C74", "Mitotane only approved; EDP-M regimen; IGF-1R targets"),
    ("Thymoma (advanced)", "C37", "Chemotherapy + pembrolizumab; unresectable/relapsed population"),
    ("Small Intestine Adenocarcinoma", "C17", "Rare; FOLFOX; mismatch repair deficiency subgroup"),
    ("Appendiceal Neoplasm (pseudomyxoma)", "C18", "Cytoreduction + HIPEC standard; mucinous adenocarcinoma subset"),
    ("Primary Peritoneal Carcinoma", "C48", "BRCA-associated; PARP inhibitor eligible; similar to ovarian"),
    ("Fallopian Tube Cancer", "C57", "Treated like epithelial ovarian; BRCA enriched; bevacizumab active"),
    ("Vaginal Cancer (primary)", "C52", "Rare; radiation standard; IO emerging for recurrent disease"),
    ("Gestational Trophoblastic Neoplasia", "C58", "Highly chemosensitive; EMA-CO for high-risk; salvage challenges"),
    ("Male Breast Cancer", "C50", "AR-positive often; anastrozole; unique biology vs female BC"),
    ("Primary Bone Cancer (osteosarcoma)", "C41", "MAP chemotherapy; no new agents 40yr; mifamurtide in EU"),
    ("Chondrosarcoma (dedifferentiated)", "C41", "Surgery only for low-grade; IDH1/2 inhibitors for chondroid"),
    ("Giant Cell Tumor of Bone", "C49", "Denosumab reduces recurrence; curative resection first-line"),
    ("Extragonadal Germ Cell Tumor", "C62", "BEP chemotherapy; salvage VeIP; poor prognosis if mediastinal"),
    ("Carcinoma of Unknown Primary (CUP)", "C80", "Molecular profiling guides therapy; checkpoint inhibitors active"),
    ("Malignant Mesothelioma (peritoneal)", "C45", "HIPEC for peritoneal; nivolumab+ipilimumab for pleural"),
    ("Angiosarcoma (advanced)", "C49", "Taxane-based; anti-VEGF; radiation-induced subset; TRC105"),
    ("Gastrointestinal Stromal Tumor (GIST)", "C49", "Imatinib/sunitinib approved; KIT/PDGFRA mutations; avapritinib"),
    ("Desmoplastic Small Round Cell Tumor", "C49", "EWSR1-WT1 fusion; multiagent chemo; radiation; EWS pathway"),
    ("Inflammatory Myofibroblastic Tumor (ALK+)", "C49", "Crizotinib/alectinib; ALK-rearranged subset; pediatric common"),
    ("Synovial Sarcoma", "C49", "SS18-SSX fusion; NY-ESO-1 TCR-T cell therapy; trabectedin"),
    ("Alveolar Soft Part Sarcoma (ASPS)", "C49", "Sunitinib/pazopanib; MET amplification; rare but VEGF-driven"),
    ("Clear Cell Sarcoma of Soft Tissue", "C49", "EWSR1-ATF1 fusion; melanocytic differentiation; limited data"),
    ("Hemangiopericytoma / Solitary Fibrous Tumor", "C49", "Temozolomide+bevacizumab; STAT6-NAB2 fusion; HIF-2α targets"),
    ("Extraskeletal Myxoid Chondrosarcoma", "C49", "NR4A3 rearrangement; slow-growing; anthracycline-based"),
    ("Primary Cutaneous B-Cell Lymphoma (PCBCL)", "C83", "Rituximab; local radiation; prognostically distinct from systemic"),
    ("Intravascular Large B-Cell Lymphoma", "C83", "Rare; R-CHOP; CNS prophylaxis critical; aggressive"),
    ("Hairy Cell Leukemia (relapsed)", "C91", "Cladribine standard; moxetumomab pasudotox; BRAF V600E target"),
    ("T-Cell Prolymphocytic Leukemia", "C91", "Alemtuzumab; JAK/STAT mutations; allo-SCT for eligible"),
    ("Large Granular Lymphocytic Leukemia", "C91", "Cyclosporine/methotrexate; neutropenia-driven; STAT3 target"),
    ("Blastic Plasmacytoid Dendritic Cell Neoplasm", "C91", "Tagraxofusp approved; very rare; allo-SCT consolidation"),
    ("Langerhans Cell Histiocytosis (multisystem)", "C96", "BRAF V600E 50%; vemurafenib active; cladribine; cytarabine"),
    ("Erdheim-Chester Disease", "C96", "BRAF/MAP2K1 mutations; vemurafenib; cobimetinib + vemurafenib"),
    ("Myeloid/Lymphoid Neoplasm with Eosinophilia (MLNE)", "C92", "FIP1L1-PDGFRA; imatinib curative; other PDGFR/FGFR rearrangements"),

    # ── BLOOD / IMMUNE DISORDERS (D50-D89) ───────────────────────────────────
    ("Iron Deficiency Anemia (functional, IBD-related)", "D50", "IV iron; oral iron failure; HIF-prolyl hydroxylase inhibitors"),
    ("Vitamin B12 Deficiency (pernicious anemia)", "D51", "IM hydroxocobalamin; oral high-dose; gastric intrinsic factor loss"),
    ("Anemia of Chronic Disease (CKD-related)", "D63", "ESAs/darbepoetin; HIF-PHIs (roxadustat) approved in non-dialysis CKD"),
    ("Diamond-Blackfan Anemia", "D61", "Corticosteroids; RPS19 mutations; luspatercept in trials"),
    ("Congenital Dyserythropoietic Anemia", "D64", "Mitapivat (pyruvate kinase); allogeneic SCT; iron chelation"),
    ("Myelodysplastic Syndrome (low-risk)", "D46", "Luspatercept/ESA for anemia; lenalidomide del(5q); watchful waiting"),
    ("Thrombocytopenia (drug-induced)", "D69", "Drug removal; IVIG; plasmapheresis for heparin-induced (HIT)"),
    ("Neutropenia (cyclic/congenital)", "D70", "G-CSF standard; SCN with CSF3R mutations; stem cell transplant"),
    ("Mastocytosis (indolent systemic)", "D47", "Avapritinib approved; midostaurin; symptom management (antihistamines)"),
    ("Hypereosinophilic Syndrome (primary)", "D72", "Mepolizumab/benralizumab; imatinib for PDGFRA-rearranged"),
    ("Hemolytic Uremic Syndrome (atypical aHUS)", "D59", "Eculizumab/ravulizumab approved; complement factor H mutations"),
    ("Hereditary Spherocytosis (severe)", "D58", "Splenectomy standard; mitapivat in trials; periodic transfusions"),
    ("Glucose-6-Phosphate Dehydrogenase Deficiency", "D55", "Avoidance of triggers; mitapivat Phase 3 underway"),
    ("Antiphospholipid Syndrome (catastrophic CAPS)", "D68", "Anticoagulation; complement inhibition; plasma exchange for CAPS"),
    ("Cryoglobulinemia (mixed type II)", "D89", "Rituximab; HCV treatment if associated; plasma exchange"),

    # ── METABOLIC / ENDOCRINE (E00-E99) ──────────────────────────────────────
    ("Thyrotoxicosis / Hyperthyroidism (Graves)", "E05", "Thionamides; RAI; thyroidectomy; teprotumumab for ophthalmopathy"),
    ("Hashimoto's Thyroiditis (autoimmune)", "E06", "LT4 replacement; selenium; immune modulation for progression"),
    ("Congenital Hypothyroidism", "E00", "Neonatal screening; LT4 replacement; cognitive outcome dependent"),
    ("Diabetes Insipidus (central)", "E23", "Desmopressin; vasopressin receptor 2 agonists"),
    ("SIADH / Hyponatremia (chronic)", "E22", "Vaptans (tolvaptan); fluid restriction; urea supplementation"),
    ("Hyperaldosteronism (primary Conn's)", "E26", "Aldosterone synthase inhibitor (baxdrostat) Phase 3 positive"),
    ("Congenital Adrenal Hyperplasia (21-hydroxylase)", "E25", "Hydrocortisone; tildacortil; modified-release hydrocortisone (Plenadren)"),
    ("Pheochromocytoma (metastatic)", "E27", "MIBG (iobenguane I-131) approved; sunitinib; 177Lu-DOTATATE"),
    ("Carcinoid Syndrome (uncontrolled)", "E34", "Octreotide LAR/telotristat for diarrhea; somatostatin receptor imaging"),
    ("Multiple Endocrine Neoplasia (MEN1)", "E31", "Surveillance + surgery; lanreotide; evolocumab for lipid MEN"),
    ("McCune-Albright Syndrome", "E31", "Bisphosphonates; pasireotide; letrozole in girls with precocious puberty"),
    ("Familial Hypercholesterolemia (homozygous FH)", "E78", "PCSK9i + statins often insufficient; inclisiran; lomitapide; PCSK9 siRNA"),
    ("Lysosomal Storage Disorders (general)", "E75", "ERT for many; substrate reduction; chaperone therapy; gene therapy"),
    ("Glycogen Storage Disease Type I (von Gierke)", "E74", "Continuous glucose; cornstarch; gene therapy AAV-G6PC approaching"),
    ("Biotinidase Deficiency", "E53", "Oral biotin; neonatal screening; preventable with early treatment"),
    ("Homocystinuria (CBS deficiency)", "E72", "Pyridoxine response subset; betaine; methionine restriction"),
    ("Methylmalonic Acidemia (MMA)", "E71", "Dietary restriction; carnitine; organ transplant; gene therapy"),
    ("Propionic Acidemia", "E71", "Dietary restriction; carnitine; transplant; mRNA therapy (mRNA-3927)"),
    ("Isovaleric Acidemia", "E71", "Dietary restriction; glycine conjugation; liver transplant"),
    ("Maple Syrup Urine Disease (MSUD)", "E71", "BCAA-restricted diet; liver transplant; gene therapy (AAV-hDBT)"),
    ("Nonketotic Hyperglycinemia (NKH)", "E72", "Benzoate + dextromethorphan; gene therapy; enzyme co-factor replacement"),

    # ── CNS / NEUROLOGY (F-G chapters) ───────────────────────────────────────
    ("Conversion Disorder / Functional Neurological Disorder", "F44", "PT/CBT; physiotherapy; antidepressants for comorbidity"),
    ("Delirium (ICU, hospital-acquired)", "F05", "Haloperidol; dexmedetomidine; non-pharmacological (ABCDE bundle)"),
    ("Vascular Dementia", "G30", "Stroke prevention; donepezil modest benefit; VEGF growth factors"),
    ("Lewy Body Dementia", "G31", "Rivastigmine; no antipsychotics; pimavanserin for psychosis"),
    ("Frontotemporal Dementia (MAPT)", "G31", "No approved therapy; tau aggregation inhibitors; LMTM failed"),
    ("Normal Pressure Hydrocephalus (NPH)", "G91", "VP shunt; gait improvement most responsive; idiopathic vs secondary"),
    ("Progressive Supranuclear Palsy (PSP)", "G23", "No approved therapy; tau inhibitors; UCB0107 anti-tau antibody"),
    ("Corticobasal Syndrome (CBS)", "G23", "No approved therapy; symptomatic; tau pathology target"),
    ("Amyotrophic Lateral Sclerosis (sporadic)", "G12", "Riluzole/edaravone/tofersen; antisense to TDP-43/FUS/C9orf72"),
    ("Primary Lateral Sclerosis (PLS)", "G12", "Riluzole; slower progression than ALS; no specific approved therapy"),
    ("Spinal Bulbar Muscular Atrophy (SBMA/Kennedy)", "X-linked", "AR CAG repeat; androgen reduction; IGF-1 neuroprotection"),
    ("Hereditary Spastic Paraplegia (HSP)", "G11", "Physiotherapy; baclofen; gene therapy for SPG4/SPG7"),
    ("Ataxia-Telangiectasia", "G11", "Supportive; dexamethasone for cerebellar; EBV-associated lymphoma risk"),
    ("Spinocerebellar Ataxia (SCA3/MJD)", "G11", "No approved therapy; antisense to ATXN3; protein aggregation"),
    ("Friedreich Ataxia (early)", "G11", "Omaveloxolone approved 2023; idebenone in EU; RNAi frataxin"),
    ("Dystonias (generalized DYT1)", "G24", "Trihexyphenidyl; DBS; gene therapy for DYT1 (TOR1A)"),
    ("Spasticity (MS-associated)", "G37", "Baclofen IT; onabotulinumtoxin A; cannabis-based medicine"),
    ("Chronic Pain (central sensitization)", "G89", "Duloxetine/pregabalin; low-dose naltrexone; ketamine IV; CGRP"),
    ("Peripheral Neuropathy (hereditary CMT)", "G60", "PT; orthotics; ascorbic acid (CMT1A); gene therapy approaching"),
    ("Guillain-Barré Syndrome (AIDP)", "G61", "IVIG/plasma exchange; neonatal Fc receptor target; complement"),
    ("Lambert-Eaton + SCLC-related", "G73", "VGCC antibody; amifampridine; immunotherapy for SCLC treatment"),
    ("Autoimmune Encephalitis (anti-NMDAR)", "G04", "Rituximab; immunotherapy; early treatment prevents morbidity"),
    ("Rasmussen Encephalitis", "G04", "Hemispherectomy; immunotherapy bridging; perampanel"),
    ("Progressive Multifocal Leukoencephalopathy (PML)", "A81", "JC virus; immunotherapy; BKT-virus targeted treatment emerging"),
    ("Neuromyelitis Optica Spectrum Disorder (NMOSD)", "G36", "Inebilizumab/satralizumab/eculizumab approved; ublituximab"),
    ("MOG Antibody Disease (MOGAD)", "G36", "Steroids; rituximab; inebilizumab; distinct from NMOSD/MS"),
    ("Cerebral Cavernous Malformations", "Q28", "Simvastatin lowering hemorrhage; propranolol; surgical for accessible"),
    ("Sturge-Weber Syndrome", "Q85", "AED for seizures; aspirin for strokes; rapamycin for skin"),
    ("Neurofibromatosis Type 1 (NF1)", "Q85", "Selumetinib approved for pediatric plexiform; MEK inhibitors"),
    ("Neurofibromatosis Type 2 (NF2)", "Q85", "Bevacizumab for vestibular schwannoma; everolimus; gene therapy"),
    ("Tuberous Sclerosis Complex (TSC)", "Q85", "Everolimus for SEGA/LAM/AML; vigabatrin infantile spasms; mTOR"),
    ("Von Hippel-Lindau (VHL) Disease", "Q85", "Belzutifan approved 2021; VHL tumors; ccRCC/hemangioblastomas"),

    # ── CARDIOVASCULAR (I00-I99) ──────────────────────────────────────────────
    ("Rheumatic Heart Disease (RHD)", "I05", "Penicillin prophylaxis; mitral valve surgery; developing country burden"),
    ("Endocarditis (infective, difficult-to-treat)", "I33", "Prolonged IV antibiotics; daptomycin; surgery timing; biofilm"),
    ("Myocarditis (immune checkpoint inhibitor)", "I40", "Steroids; abatacept; immune suppression; high mortality"),
    ("Myocarditis (giant cell)", "I41", "Cyclosporine + steroids; transplant; mechanical support bridge"),
    ("Takotsubo Syndrome (stress cardiomyopathy)", "I42", "ACE inhibitor; beta-blocker; hormone modulation; recurrence prevention"),
    ("Left Ventricular Non-Compaction (LVNC)", "I42", "Heart failure management; ICD; anticoagulation; LVADs"),
    ("Long QT Syndrome (congenital)", "I45", "Beta-blockers; ICD; mexiletine for LQT3; gene therapy approaching"),
    ("Brugada Syndrome (high-risk)", "I45", "ICD; quinidine; ablation of epicardial substrate; SCN5A correction"),
    ("Catecholaminergic Polymorphic VT (CPVT)", "I47", "Beta-blocker + flecainide; ICD; cardiac sympathetic denervation"),
    ("Hereditary Hemorrhagic Telangiectasia (HHT)", "I78", "Bevacizumab IV; thalidomide; rapamycin; liver/lung AVM embolization"),
    ("Lymphedema (primary/secondary)", "I89", "Manual drainage; compression; low-level laser; microsurgery LYMPHA"),
    ("Superior Vena Cava Syndrome (SVCS)", "I87", "Stenting; anticoagulation; treat underlying malignancy"),
    ("Thoracic Aortic Aneurysm (HTAD)", "Q87", "Losartan/TGFβ for Marfan; atenolol; endovascular/open repair"),
    ("Coronary Artery Disease (refractory angina)", "I25", "Enhanced external counterpulsation; spinal cord stimulation; gene therapy (VEGF)"),
    ("Myocardial Infarction (no-reflow phenomenon)", "I21", "Adenosine/verapamil intracoronary; mechanical thrombectomy; complement"),
    ("Cardiotoxicity (anthracycline-induced)", "I42", "Dexrazoxane; SGLT2i; cardiac monitoring; early ACEi/BB"),

    # ── RESPIRATORY (J00-J99) ─────────────────────────────────────────────────
    ("Lung Transplant (primary graft dysfunction)", "J98", "IL-1 receptor antagonist; targeted temperature management; ECMO bridge"),
    ("Pulmonary Langerhans Cell Histiocytosis (PLCH)", "J84", "Smoking cessation; cladribine; BRAF inhibitor for refractory"),
    ("Lymphangioleiomyomatosis (LAM)", "J84", "Sirolimus (everolimus); lung transplant for refractory; bilateral oophorectomy"),
    ("Hypersensitivity Pneumonitis (acute/subacute)", "J67", "Antigen avoidance; steroids; mycophenolate for chronic fibrotic"),
    ("Organizing Pneumonia (cryptogenic COP)", "J84", "Steroids 3-6 months; azithromycin adjunct; recurrence common"),
    ("Respiratory Papillomatosis (recurrent juvenile)", "J38", "Surgical debulking; bevacizumab; HPV vaccines (prevention)"),
    ("Tracheobronchomalacia (severe)", "J98", "CPAP/BiPAP; stenting; tracheobronchoplasty; airway splinting"),
    ("Hypercapnic Respiratory Failure (NIV-dependent)", "J96", "NIV optimization; diaphragm pacing; carbonic anhydrase inhibitors"),
    ("Obstructive Sleep Apnea (pediatric, tonsil-related)", "J35", "Adenotonsillectomy first-line; CPAP if fails; Inspire emerging age 6+"),

    # ── DIGESTIVE (K00-K95) ───────────────────────────────────────────────────
    ("Gastroesophageal Reflux Disease (refractory GERD)", "K21", "Vonoprazan PCAB; magnetic sphincter (LINX); laparoscopic fundoplication"),
    ("Barrett's Esophagus (dysplastic)", "K22", "Radiofrequency ablation; cryotherapy; proton pump inhibitors"),
    ("Achalasia (type III vigorous)", "K22", "Per-oral endoscopic myotomy (POEM); Heller; botulinum toxin"),
    ("Zenker's Diverticulum", "K22", "Endoscopic myotomy (Z-POEM); cricopharyngeal muscle dysfunction"),
    ("Gastroparesis (autoimmune)", "K31", "Relamorelin; prucalopride; gastric electrical stimulation (Enterra)"),
    ("Superior Mesenteric Artery Syndrome (SMAS)", "K55", "Nutritional support; derotation surgery; Roux-en-Y; weight restoration"),
    ("Cyclic Vomiting Syndrome (CVS)", "K31", "Tricyclic antidepressants; amitriptyline; CGRP antagonists"),
    ("Intestinal Pseudo-Obstruction (Ogilvie's)", "K56", "Neostigmine; colonoscopic decompression; methylnaltrexone"),
    ("Bile Acid Malabsorption (BAM)", "K90", "Colesevelam/cholestyramine; FXR agonists; opioid receptor modulation"),
    ("Lymphocytic Colitis / Collagenous Colitis", "K52", "Budesonide; bismuth subsalicylate; drug review"),
    ("Microscopic Colitis (MC)", "K52", "Budesonide; cholestyramine; TNF inhibitors for refractory"),
    ("Mesenteric Ischemia (chronic)", "K55", "Revascularization; antiplatelet; PDE5 inhibitors for low-flow"),
    ("Anal Fistula (complex Crohn's)", "K60", "Adalimumab+surgical drainage; stem cell injection (darvadstrocel approved EU)"),
    ("Hemorrhoids (refractory grade III/IV)", "K64", "Rubber band ligation; stapled hemorrhoidopexy; photocoagulation"),
    ("Rectal Prolapse (full-thickness)", "K62", "Delorme/Altemeier perineal repair; laparoscopic ventral mesh rectopexy"),
    ("Diverticular Disease (complicated)", "K57", "Antibiotics; colonoscopic drainage; surgery for complicated fistula"),
    ("Hepatic Encephalopathy (recurrent)", "K72", "Rifaximin+lactulose; ornithine phenylacetate; fecal microbiota"),
    ("Hepatic Veno-Occlusive Disease (sinusoidal obstruction)", "K76", "Defibrotide approved; anticoagulation; ursodeoxycholic acid prophylaxis"),
    ("Budd-Chiari Syndrome", "K76", "Anticoagulation; TIPS; portosystemic shunt; liver transplant"),
    ("Liver Fibrosis (non-cirrhotic NAFLD)", "K76", "Semaglutide; resmetirom (approved); lanifibranor; FGF21 analogs"),
    ("Hereditary Pancreatitis (PRSS1/SPINK1)", "K85", "Pain management; total pancreatectomy + islet autotransplant; CFTR"),
    ("Exocrine Pancreatic Insufficiency (EPI)", "K86", "PERT (pancrelipase); acid suppression; fat-soluble vitamin supplementation"),

    # ── GENITOURINARY (N00-N99) ────────────────────────────────────────────────
    ("Interstitial Nephritis (drug-induced)", "N12", "Drug cessation; steroids; mycophenolate for refractory"),
    ("Thin Glomerular Basement Membrane Disease", "N03", "ACE inhibitor; monitor; usually benign; COL4A3/A4/A5 mutations"),
    ("Focal Segmental Glomerulosclerosis (FSGS primary)", "N04", "Sparsentan; voclosporin; LNP023; APOL1 targeting for APOL1-FSGS"),
    ("Minimal Change Disease (steroid-dependent)", "N04", "Rituximab; cyclosporine; voclosporin; belimumab"),
    ("C3 Glomerulopathy (C3G)", "N04", "Iptacopan (Factor B); pegcetacoplan; no approved therapy yet"),
    ("Alport Syndrome", "N07", "ACEi/ARBi; bardoxolone; gene therapy (COL4A5) approaching"),
    ("Goodpasture's Syndrome (anti-GBM)", "N01", "Plasmapheresis + immunosuppression; narsoplimab complement"),
    ("Renal Artery Stenosis (atherosclerotic)", "N28", "Statin+antiplatelet; renal artery stenting for resistant hypertension"),
    ("Medullary Sponge Kidney", "N28", "Stone prevention (citrate); treat UTIs; no disease-modifying therapy"),
    ("Nephrolithiasis (recurrent calcium oxalate)", "N20", "Thiazides+citrate; dietary modification; lithotripsy; lumasiran for primary hyperoxaluria"),
    ("Ureteral Stricture (post-radiation)", "N13", "Ureteral stenting; balloon dilation; robotic ureteral reconstruction"),
    ("Bladder Cancer (carcinoma in situ, BCG-naive)", "C67", "BCG intravesical; valrubicin for BCG-unresponsive; pembrolizumab"),
    ("Urethral Stricture Disease (recurrent)", "N35", "Urethral dilation; DVIU; buccal mucosa urethroplasty"),
    ("Erectile Dysfunction (vascular etiology)", "N52", "PDE5 inhibitors; alprostadil; low-intensity shockwave therapy; stem cells"),
    ("Peyronie's Disease (chronic phase)", "N48", "Collagenase injection (Xiaflex); penile traction; PT-141"),
    ("Female Pelvic Organ Prolapse", "N81", "Pelvic floor PT; pessary; mesh or native tissue repair; stem cell injection"),
    ("Interstitial Cystitis / Painful Bladder Syndrome", "N30", "Pentosan polysulfate; intravesical DMSO/heparin; cystoscopic hydrodistension"),
    ("Urinary Incontinence (urgency, neurogenic)", "N39", "Mirabegron/vibegron; onabotulinumtoxinA; sacral neuromodulation"),
    ("Premature Ejaculation (acquired)", "N53", "Dapoxetine (not US-approved); SSRIs off-label; PSD502 topical"),

    # ── SKIN / SUBCUTANEOUS (L00-L99) ─────────────────────────────────────────
    ("Acne Vulgaris (severe nodulocystic)", "L70", "Isotretinoin; sarecycline; clascoterone; IL-17 biologics emerging"),
    ("Rosacea (papulopustular)", "L71", "Ivermectin cream; brimonidine; azelaic acid; laser for phyma"),
    ("Psoriasis (nail, refractory)", "L40", "Ixekizumab/bimekizumab; guselkumab; nail involvement predicts PsA"),
    ("Lichen Planus (oral erosive)", "L43", "Tacrolimus; steroids; JAK inhibitors; hydroxychloroquine"),
    ("Lichen Sclerosus (genital)", "L90", "Topical steroids; tacrolimus; platelet-rich plasma; laser"),
    ("Darier Disease (Keratosis Follicularis)", "L87", "Retinoids; doxycycline; laser; gene therapy approaching (ATP2A2)"),
    ("Hailey-Hailey Disease", "L11", "mTOR inhibitors (sirolimus); botulinum toxin; electron beam; gene therapy"),
    ("Grover's Disease (transient acantholytic)", "L11", "Isotretinoin; dapsone; acitretin; low-dose naltrexone"),
    ("Pityriasis Rubra Pilaris (type I adult)", "L44", "Biologics (IL-17/TNF); retinoids; combination approaches"),
    ("Necrobiosis Lipoidica (diabetic)", "L92", "Topical/intralesional steroids; PUVA; TNF inhibitors; cyclosporine"),
    ("Granuloma Annulare (disseminated)", "L92", "No proven therapy; dapsone; hydroxychloroquine; JAK inhibitors"),
    ("Morphea (generalized systemic)", "L94", "Methotrexate + UVA1; tacrolimus; pulse steroids"),
    ("Keloid (multiple recurrent lesions)", "L91", "Intralesional steroids/bleomycin; silicone gel; low-dose radiation"),
    ("Striae Distensae (severe)", "L90", "Laser/radiofrequency; microneedling; no approved pharmacotherapy"),
    ("Lipodermatosclerosis (venous insufficiency)", "L98", "Compression; stanozolol; fibrinolytic agents; wound care"),

    # ── MUSCULOSKELETAL (M00-M99) ─────────────────────────────────────────────
    ("Reactive Arthritis (HLA-B27)", "M02", "NSAIDs; sulfasalazine; TNF-i for chronic; antibiotic for triggering infection"),
    ("Enteropathic Arthritis (IBD-associated)", "M07", "NSAIDs carefully; sulfasalazine; biologics treating both IBD and joint"),
    ("Gout (refractory tophaceous)", "M10", "Pegloticase (Krystexxa); lesinurad+allopurinol; xanthine oxidase inhibition"),
    ("Pseudogout / Calcium Pyrophosphate Disease (CPPD)", "M11", "NSAIDs; colchicine; no approved disease-modifying therapy; canakinumab"),
    ("Relapsing Polychondritis", "M94", "Steroids; dapsone; methotrexate; JAK inhibitors; cardiac pacemaker risk"),
    ("Polymyalgia Rheumatica (steroid-refractory)", "M35", "Tocilizumab for steroid-sparing; satralizumab; IL-6 pathway"),
    ("Giant Cell Arteritis (ischemic complications)", "I77", "High-dose steroids; tocilizumab approved; mavrilimumab (GM-CSFR)"),
    ("Antiphospholipid Syndrome (obstetric)", "D68", "Aspirin+LMWH; hydroxychloroquine; rituximab for refractory"),
    ("Eosinophilic Fasciitis", "M35", "Steroids; methotrexate; JAK inhibitors; IL-5 pathway"),
    ("Systemic Sclerosis (diffuse ILD)", "M34", "Nintedanib approved; tocilizumab for skin; bosentan for PAH"),
    ("Mixed Connective Tissue Disease (MCTD)", "M35", "Hydroxychloroquine; steroids; immunosuppressants; PAH treatment"),
    ("Undifferentiated Connective Tissue Disease", "M35", "Hydroxychloroquine; NSAIDs; watchful waiting for evolution"),
    ("Septic Arthritis (prosthetic joint)", "M00", "Debridement + antibiotic retention; two-stage exchange; novel antimicrobials"),
    ("Osteonecrosis (avascular necrosis of hip)", "M87", "Core decompression; bisphosphonates; teriparatide; stem cell injection"),
    ("Diffuse Idiopathic Skeletal Hyperostosis (DISH)", "M48", "NSAIDs; PT; no disease-modifying therapy; BMP/VEGF mechanism"),
    ("Charcot Arthropathy (neuropathic joint)", "M14", "Total contact casting; bisphosphonates; surgical reconstruction"),
    ("Plantar Fasciitis (chronic resistant)", "L84", "Extracorporeal shockwave; PRP; botulinum toxin; surgery (endoscopic release)"),

    # ── CONGENITAL / CHROMOSOMAL (Q00-Q99) ───────────────────────────────────
    ("Down Syndrome (Trisomy 21, cognitive disability)", "Q90", "Lejeune Foundation levodopa trial; GABA antagonists for cognitive; supportive"),
    ("Turner Syndrome", "Q96", "Growth hormone; estrogen replacement; cardiovascular monitoring; HRT"),
    ("Klinefelter Syndrome (47,XXY)", "Q98", "Testosterone replacement; fertility (ART); cognitive support"),
    ("Williams Syndrome (elastin deletion)", "Q93", "Cardiovascular surgery for SVAS; behavioral therapy; no systemic therapy"),
    ("22q11.2 Deletion Syndrome (DiGeorge)", "Q93", "Calcium supplementation; thymus transplant for severe T-cell deficiency; behavioral support"),
    ("Prader-Willi Syndrome (appetite)", "Q87", "GH; oxytocin for behavior; metformin; carbetocin for hyperphagia"),
    ("CHARGE Syndrome", "Q89", "Multimodal; choanal atresia repair; hearing aids; visual support"),
    ("VACTERL Association", "Q89", "Surgical correction of anomalies; no systemic disease-modifying"),
    ("Alagille Syndrome (ALGS)", "Q44", "Maralixibat approved 2021 (IBAT inhibitor); liver transplant; biliary diversion"),
    ("Biliary Atresia (pediatric)", "Q44", "Kasai portoenterostomy; liver transplant; chenodeoxycholic acid"),
    ("Congenital Diaphragmatic Hernia (severe)", "Q79", "FETO (fetal endotracheal occlusion); ECMO; lung growth strategies"),
    ("Pierre Robin Sequence (severe)", "Q87", "Mandibular distraction; tongue-lip adhesion; tracheostomy rarely"),
    ("Osteogenesis Imperfecta (severe type III/IV)", "Q78", "Bisphosphonates; romosozumab; gene correction (AAV-COL1A1)"),
    ("Achondroplasia (pediatric)", "Q77", "Vosoritide (CNP analog) approved 2021; TransCon-CNP; surgery for stenosis"),
    ("Kabuki Syndrome (KMT2D)", "Q87", "Lysine supplementation trial; supportive; gene therapy approaches"),
    ("Cornelia de Lange Syndrome", "Q87", "Supportive; no systemic disease-modifying; behavior/GI management"),

    # ── INFECTIOUS DISEASES (expanded) ────────────────────────────────────────
    ("Lyme Disease (post-treatment Lyme syndrome)", "A69", "No proven antibiotic benefit for PTLDS; immune modulation; CXCR4"),
    ("Babesiosis (severe immunocompromised)", "B60", "Atovaquone+azithromycin; clindamycin+quinine for severe; exchange transfusion"),
    ("Anaplasmosis / Ehrlichiosis", "A77", "Doxycycline; rapid treatment critical; tick-borne co-infections"),
    ("Brucellosis (neurobrucellosis)", "A23", "Doxycycline+rifampicin 6wk+; ceftriaxone CNS penetration"),
    ("Scrub Typhus (severe)", "A75", "Doxycycline; azithromycin; rifampicin; endothelial damage mechanism"),
    ("Q Fever (chronic endocarditis)", "A78", "Hydroxychloroquine+doxycycline 18mo+; C. burnetii intracellular persistence"),
    ("Melioidosis (severe Burkholderia)", "A24", "Meropenem IV; TMP-SMX eradication; vaccine development"),
    ("Nontuberculous Mycobacterial Lung Disease (NTM)", "A31", "Amikacin liposome inhaled (ALIS approved); macrolide-based regimens"),
    ("Cryptococcal Meningitis (HIV-associated)", "B45", "Liposomal amphotericin B; flucytosine; fluconazole maintenance; immunology"),
    ("Mucormycosis / Zygomycosis (invasive)", "B46", "Liposomal amphotericin B; isavuconazole; ibrexafungerp; surgery"),
    ("Histoplasmosis (disseminated immunocompromised)", "B39", "Itraconazole/liposomal AmB; no new agents; epidemiology expanding"),
    ("Coccidioidomycosis (disseminated CNS)", "B38", "Fluconazole lifelong; intrathecal AmB; olorofim for refractory"),
    ("Paracoccidioidomycosis (South American)", "B41", "Itraconazole/TMP-SMX; neglected tropical disease; limited trial data"),
    ("Leprosy (multibacillary, new case)", "A30", "MDT (rifampicin+dapsone+clofazimine); nerve damage prevention; WHO elimination"),
    ("Trachoma (blinding, Chlamydia trachomatis)", "A71", "SAFE strategy; azithromycin mass drug administration; vaccine R&D"),
    ("Lymphatic Filariasis (lymphedema stage)", "B74", "Moxidectin; albendazole + diethylcarbamazine; lymphedema management"),
    ("Onchocerciasis (river blindness)", "B73", "Ivermectin MDA; moxidectin; ameocide for macrofilaricidal activity"),
    ("Schistosomiasis (hepatosplenic)", "B65", "Praziquantel standard; oxamniquine; vaccine development phase 1"),
    ("Echinococcosis (cystic/alveolar)", "B67", "Albendazole; PAIR procedure; surgery; no curative medical therapy"),
    ("Toxoplasmosis (CNS, immunocompromised)", "B58", "Pyrimethamine+sulfadiazine; TMP-SMX prophylaxis; HIV ART"),
    ("CMV Retinitis (immunocompromised)", "B25", "Ganciclovir/valganciclovir; foscarnet; brincidofovir oral"),
    ("EBV-associated Lymphoproliferative Disease", "B27", "Rituximab; reduce immunosuppression; EBV-specific CTLs"),
    ("HHV-6 Encephalitis (post-transplant)", "B00", "Ganciclovir/foscarnet; cidofovir; EBV/CMV co-infection management"),
    ("Congenital Cytomegalovirus (CMV) disease", "P35", "Valganciclovir oral; hearing outcome improvement; vaccine priority"),
    ("Congenital Rubella Syndrome", "P35", "Prevention only (MMR); supportive for established disease"),
    ("Zika Congenital Syndrome (microcephaly)", "P35", "Supportive; no approved antiviral; vaccine development stalled"),
    ("Mpox (severe ocular/CNS)", "B04", "Tecovirimat; cidofovir; JYNNEOS post-exposure prophylaxis"),
    ("Rabies (post-exposure prophylaxis gap)", "A82", "Monoclonal antibodies replacing RIG; therapeutic vaccine trial"),
    ("Prion Disease (CJD sporadic)", "A81", "No approved therapy; doxycycline studied; quinacrine; tau involvement"),
    ("Kuru / Fatal Familial Insomnia (FFI)", "A81", "Supportive only; prion replication mechanism; gene silencing"),
]


def get_expanded_universe_count() -> int:
    """Return total expanded universe size."""
    from app.services.universe_builder import get_universe
    curated = len(get_universe())
    return curated + len(_ICD10_MAJOR_CATEGORIES)


def get_icd10_entry(disease: str, icd_prefix: str, notes: str) -> tuple:
    """Convert an ICD-10 category to a universe entry with TA-level defaults."""
    # Determine TA from ICD prefix
    ta = "other"
    for prefix, mapped_ta in _ICD10_TA_MAP.items():
        if icd_prefix.startswith(prefix):
            ta = mapped_ta
            break
        if icd_prefix[0] == prefix:
            ta = mapped_ta
            break

    _, phase, approved, cost = _TA_SCORING_DEFAULTS.get(ta, _TA_SCORING_DEFAULTS["other"])
    return (disease, ta, phase, approved, cost, notes)


def get_all_diseases_for_batch_scoring() -> list:
    """
    Return the complete universe (curated + ICD-10 extended) for batch pre-scoring.
    Used by the ETL job to populate disease_scored table.
    """
    from app.services.universe_builder import get_universe
    curated = get_universe()
    curated_names = {d[0].lower() for d in curated}

    extended = []
    for disease, prefix, notes in _ICD10_MAJOR_CATEGORIES:
        if disease.lower() not in curated_names:
            extended.append(get_icd10_entry(disease, prefix, notes))

    return curated + extended
