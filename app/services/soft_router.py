"""
Soft Router — Mixture-of-Experts Weight Vector
===============================================
Instead of hard-routing every innovation to exactly one expert (which forces
a single market sizing formula), the soft router returns a weight vector
across multiple relevant subcategories. The formula engine then blends
parameters proportionally.

Example:
  "An AAV9 gene therapy for SMA with biomarker-confirmed SMN1 deletion"
  Hard routing: gene_therapy_rare (100%)
  Soft routing: {
      "gene_therapy_rare": 0.70,   # primary: rare monogenic AAV
      "gene_therapy_rna":  0.20,   # secondary: ASO comparison considered
      "drug_rare_disease": 0.10,   # context: rare disease epidemiology/pricing
  }

The blended PTRS = 0.70 × LOA(gene_therapy_rare) + 0.20 × LOA(gene_therapy_rna)
              + 0.10 × LOA(drug_rare_disease)

This captures multi-modal innovations more accurately than any single expert.

Architecture:
  1. Signal extraction — parse idea text for 30+ domain signals
  2. Prior weight table — baseline weight per subcategory for each signal
  3. Weight normalization — sum to 1.0, filter out subcategories below threshold
  4. (Optional) Claude Haiku refinement — for ambiguous cases
"""

from __future__ import annotations
import math
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SoftRoutingResult:
    weights:          dict[str, float]   # subcategory_id → weight (sum = 1.0)
    primary:          str                # highest-weight subcategory
    secondary:        Optional[str]      # second highest (if > 0.15)
    is_multi_modal:   bool               # True if top-2 both > 0.20
    signals_detected: list[str]          # human-readable signals found
    confidence:       float              # how clearly it routes (1.0 = perfectly clear)
    blend_note:       str                # explanation for UI


# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

_SIGNALS: dict[str, list[str]] = {
    # Modality signals
    "aav_vector":          ["aav9","aav8","aav5","aav6","aav ","aav-","rh74","rh10","adeno-associated"],
    "lentiviral":          ["lentiviral","lentivirus","lv vector","retroviral","transduction ex vivo"],
    "car_t":               ["car-t","car t","chimeric antigen receptor t","car t-cell","il2rg car"],
    "crispr":              ["crispr","cas9 ","cas12","base editing","prime editing","base editor","pegRNA","adenine base editor","cytosine base editor"],
    "aso_sirna":           ["antisense oligonucleotide","aso ","sirna","rnai","gapmers","phosphorothioate","2'-moe","exon skipping","exon-skipping"],
    "mrna":                ["mrna","messenger rna","ionizable lipid","lnp mrna"],
    "antibody_naked":      ["monoclonal antibody","mab ","naked antibody","igg1","igg4","antibody therapy"],
    "adc":                 ["antibody-drug conjugate","adc ","drug conjugate","t-dxd","dxd payload","maytansine","vcmmae"],
    "bispecific":          ["bispecific","bsab","blinatumomab","catumaxomab","dual targeting","crossmab"],
    "small_molecule_oral": ["oral","once daily","twice daily","pill","tablet","capsule","small molecule"],
    "iv_drug":             ["intravenous","iv antibiotic","iv infusion","parenteral drug","iv drug","intravascular"],
    "checkpoint":          ["pd-1","pd-l1","ctla-4","checkpoint inhibitor","anti-pd","pembrolizumab","nivolumab","ipilimumab"],
    "enzyme":              ["enzyme replacement","elosulfase","alglucosidase","enzyme therapy","protein replacement"],
    "vaccine_mrna":        ["mrna vaccine","lipid nanoparticle vaccine","bnt162","mrna immunogen"],
    "vaccine_protein":     ["protein subunit vaccine","adjuvanted vaccine","rsv vaccine","recombinant vaccine","polysaccharide conjugate"],
    "vaccine_cancer":      ["cancer vaccine","tumor vaccine","neoantigen","personalized vaccine","therapeutic vaccine","tav "],
    "device_implant":      ["implant","stent","pacemaker","cochlear","icd ","defibrillator","neurostimulator"],
    "device_capital":      ["robotic surgery","imaging system","ct scanner","mri machine","radiation therapy system"],
    "samd_ai":             ["ai algorithm","machine learning model","clinical decision support","samd","software medical device","digital therapeutic"],
    "diagnostic_ngs":      ["ngs panel","next-generation sequencing","liquid biopsy","whole exome","whole genome","ctdna"],
    "diagnostic_poc":      ["point-of-care","lateral flow","rapid test","clia-waived","bedside test","home test"],

    # Target / disease area signals
    "amr_hospital":        ["carbapenem","cre ","klebsiella","acinetobacter","pseudomonas","esbl","mdr gram-negative","hospital-acquired infection","icu infection","bacteremia","ventilator-associated","ndm"],
    "amr_community":       ["mrsa skin","absssi","community-acquired pneumonia","cap ","uti ","urinary tract infection","gonorrhea","chlamydia","staphylococcus aureus outpatient"],
    "oncology_solid":      ["nsclc","lung cancer","breast cancer","colorectal","pancreatic cancer","gastric cancer","hepatocellular","ovarian cancer","prostate cancer","bladder cancer","solid tumor","glioblastoma","gbm "],
    "oncology_heme":       ["leukemia","lymphoma","myeloma","aml ","cll ","dlbcl","multiple myeloma","myelofibrosis","mds ","hematologic malignancy"],
    "biomarker_selected":  ["her2","egfr","kras g12","braf v600","pd-l1 positive","msi-h","tmb-h","brca","alk+","ros1","ntrk","ret ","met exon 14","fgfr","idh1","idh2","bcr-abl","npm1","flt3"],
    "alzheimers":          ["alzheimer","amyloid","tau pathology","lecanemab","aducanumab","donanemab","amyloid beta","apolipoprotein e4","apoe4","cognitive decline"],
    "parkinson":           ["parkinson","lewy body","alpha-synuclein","substantia nigra","dopaminergic neuron"],
    "als_motor":           ["als ","amyotrophic lateral sclerosis","sod1","tdp-43","fus protein","motor neuron disease"],
    "epilepsy":            ["epilepsy","seizure","scn1a","dravet","lennox-gastaut","kcnq2","intractable epilepsy"],
    "migraine":            ["migraine","cgrp","cluster headache","chronic migraine","calcitonin gene"],
    "diabetes":            ["type 2 diabetes","t2d ","glp-1","semaglutide","tirzepatide","sglt2","dpp-4","insulin resistance","hba1c"],
    "obesity":             ["obesity","bmi ","weight loss drug","qsymia","wegovy","zepbound","adiposity"],
    "nash_mash":           ["nash","mash","nonalcoholic steatohepatitis","metabolic-associated steatohepatitis","fibrosis stage","liver biopsy","ast/alt"],
    "heart_failure":       ["heart failure","hfref","hfpef","lvef","left ventricular","entresto","sacubitril","bnp elevation","ejection fraction"],
    "atrial_fib":          ["atrial fibrillation","afib","afib ","watchman","left atrial appendage","rhythm control","rate control"],
    "ra_autoimmune":       ["rheumatoid arthritis","tnf","jak inhibitor","mtx failure","das28","acr/eular","cdai","sdai"],
    "ibd":                 ["inflammatory bowel","crohn","ulcerative colitis","tnf failure","biologics ibd","vedolizumab","upadacitinib"],
    "psoriasis":           ["psoriasis","psa ","il-17","il-23","pasi score","nail psoriasis"],
    "sma":                 ["spinal muscular atrophy","sma ","smn1","smn2","onasemnogene","zolgensma","nusinersen","risdiplam"],
    "dmd":                 ["duchenne","dmd ","dystrophin","exon 51","eteplirsen","golodirsen","casimersen","viltolarsen"],
    "hemophilia":          ["hemophilia","factor viii","factor ix","fviii","fix","von willebrand","emicizumab","fitusiran"],
    "sickle_cell":         ["sickle cell","scd ","hbss","vaso-occlusive","fetal hemoglobin","hbf","casgevy","lyfgenia","hydroxyurea"],
    "rare_genetic":        ["lysosomal storage","gaucher","fabry","pompe","niemann-pick","mps ","mucopolysaccharidosis","phenylketonuria","pku","ornithine","urea cycle"],
    "rsv":                 ["rsv ","respiratory syncytial virus","arexvy","abrysvo","nirsevimab","beyfortus"],
    "flu_influenza":       ["influenza","flu vaccine","h3n2","h1n1","vaxigip","quadrivalent flu","fluzone"],
    "covid_vaccine":       ["covid vaccine","covid-19 vaccine","mrna-1273","bnt162b2","updated booster"],
    "cgm_device":          ["continuous glucose monitor","cgm ","dexcom","freestyle libre","flash glucose","sensor glucose"],
    "retina":              ["wet amd","dry amd","diabetic macular edema","dme ","geographic atrophy","ranibizumab","aflibercept","faricimab"],
    "sepsis_digital":      ["sepsis detection","early warning","deterioration","ai icu","samd sepsis","ai triage"],
    "mental_health_dig":   ["digital therapeutic","dtx ","mental health app","dbt digital","prescription digital","pear therapeutics"],
    "rpm_cardiac":         ["remote cardiac monitoring","mcot","holter ai","ambulatory ecg","wearable ecg","cardiac rhythm monitoring"],
}

# ══════════════════════════════════════════════════════════════════════════════
# PRIOR WEIGHT TABLE
# Maps each detected signal to probability mass across subcategories.
# Row sums to 1.0 (before combining with other signals).
# ══════════════════════════════════════════════════════════════════════════════

_SIGNAL_PRIORS: dict[str, dict[str, float]] = {
    "aav_vector":          {"gene_therapy_rare": 0.65, "gene_therapy_cns": 0.20, "gene_therapy_hematology": 0.15},
    "lentiviral":          {"gene_therapy_hematology": 0.70, "gene_therapy_rare": 0.20, "gene_therapy_oncology": 0.10},
    "car_t":               {"gene_therapy_oncology": 0.80, "gene_therapy_hematology": 0.20},
    "crispr":              {"gene_therapy_rare": 0.45, "gene_therapy_hematology": 0.35, "gene_therapy_cns": 0.20},
    "aso_sirna":           {"gene_therapy_rna": 0.55, "gene_therapy_cns": 0.25, "gene_therapy_rare": 0.20},
    "mrna":                {"vaccine_prophylactic": 0.50, "gene_therapy_rna": 0.30, "vaccine_cancer_immuno": 0.20},
    "antibody_naked":      {"biologic_oncology": 0.40, "biologic_immunology": 0.35, "biologic_hematology": 0.25},
    "adc":                 {"biologic_oncology": 0.85, "biologic_hematology": 0.15},
    "bispecific":          {"biologic_oncology": 0.60, "biologic_hematology": 0.25, "biologic_immunology": 0.15},
    "small_molecule_oral": {"drug_oncology": 0.25, "drug_metabolic": 0.25, "drug_immunology": 0.20, "drug_cardiovascular": 0.15, "drug_cns_neurodegen": 0.15},
    "iv_drug":             {"drug_amr": 0.50, "drug_oncology": 0.25, "biologic_oncology": 0.25},
    "checkpoint":          {"biologic_oncology": 0.75, "vaccine_cancer_immuno": 0.25},
    "enzyme":              {"biologic_rare_disease": 0.80, "drug_rare_disease": 0.20},
    "vaccine_mrna":        {"vaccine_prophylactic": 0.65, "vaccine_cancer_immuno": 0.25, "gene_therapy_rna": 0.10},
    "vaccine_protein":     {"vaccine_prophylactic": 0.85, "vaccine_infectious_therapeutic": 0.15},
    "vaccine_cancer":      {"vaccine_cancer_immuno": 0.80, "biologic_oncology": 0.20},
    "device_implant":      {"device_cardiovascular": 0.45, "device_neurology": 0.30, "device_surgical_orthopedic": 0.25},
    "device_capital":      {"device_surgical_general": 0.60, "device_cardiovascular": 0.40},
    "samd_ai":             {"digital_cds": 0.50, "digital_therapeutic": 0.25, "digital_rpm": 0.25},
    "diagnostic_ngs":      {"diagnostic_molecular_lab": 0.60, "diagnostic_companion": 0.30, "diagnostic_biomarker": 0.10},
    "diagnostic_poc":      {"diagnostic_poc": 0.80, "diagnostic_molecular_lab": 0.20},

    # Disease area signals
    "amr_hospital":        {"drug_amr": 0.90, "drug_infectious_non_amr": 0.10},
    "amr_community":       {"drug_amr_community": 0.80, "drug_amr": 0.20},
    "oncology_solid":      {"drug_oncology": 0.45, "biologic_oncology": 0.45, "vaccine_cancer_immuno": 0.10},
    "oncology_heme":       {"biologic_hematology": 0.50, "gene_therapy_oncology": 0.30, "biologic_oncology": 0.20},
    "biomarker_selected":  {"biologic_oncology": 0.55, "drug_oncology": 0.25, "diagnostic_companion": 0.20},
    "alzheimers":          {"drug_cns_neurodegen": 0.55, "biologic_oncology": 0.20, "gene_therapy_cns": 0.15, "diagnostic_biomarker": 0.10},
    "parkinson":           {"drug_cns_neurodegen": 0.60, "gene_therapy_cns": 0.25, "gene_therapy_rna": 0.15},
    "als_motor":           {"drug_cns_neurodegen": 0.45, "gene_therapy_rna": 0.35, "gene_therapy_cns": 0.20},
    "epilepsy":            {"drug_cns_acute": 0.50, "gene_therapy_rare": 0.30, "gene_therapy_rna": 0.20},
    "migraine":            {"drug_cns_acute": 0.60, "biologic_immunology": 0.25, "drug_rare_disease": 0.15},
    "diabetes":            {"drug_metabolic": 0.60, "device_metabolic": 0.25, "digital_rpm": 0.15},
    "obesity":             {"drug_metabolic": 0.75, "digital_therapeutic": 0.15, "drug_cns_neurodegen": 0.10},
    "nash_mash":           {"drug_metabolic": 0.65, "biologic_immunology": 0.25, "diagnostic_biomarker": 0.10},
    "heart_failure":       {"drug_cardiovascular": 0.50, "device_cardiovascular": 0.30, "biologic_cardiology": 0.20},
    "atrial_fib":          {"device_cardiovascular": 0.55, "drug_cardiovascular": 0.35, "digital_rpm": 0.10},
    "ra_autoimmune":       {"biologic_immunology": 0.55, "drug_immunology": 0.35, "diagnostic_biomarker": 0.10},
    "ibd":                 {"biologic_immunology": 0.55, "drug_immunology": 0.30, "drug_rare_disease": 0.15},
    "psoriasis":           {"biologic_immunology": 0.60, "drug_immunology": 0.30, "diagnostic_biomarker": 0.10},
    "sma":                 {"gene_therapy_rare": 0.50, "gene_therapy_rna": 0.35, "drug_rare_disease": 0.15},
    "dmd":                 {"gene_therapy_rare": 0.50, "gene_therapy_rna": 0.35, "drug_rare_disease": 0.15},
    "hemophilia":          {"gene_therapy_hematology": 0.55, "biologic_hematology": 0.30, "biologic_rare_disease": 0.15},
    "sickle_cell":         {"gene_therapy_hematology": 0.55, "biologic_hematology": 0.30, "drug_rare_disease": 0.15},
    "rare_genetic":        {"biologic_rare_disease": 0.45, "drug_rare_disease": 0.30, "gene_therapy_rare": 0.25},
    "rsv":                 {"vaccine_prophylactic": 0.80, "drug_infectious_non_amr": 0.20},
    "flu_influenza":       {"vaccine_prophylactic": 0.90, "drug_infectious_non_amr": 0.10},
    "covid_vaccine":       {"vaccine_prophylactic": 0.85, "gene_therapy_rna": 0.15},
    "cgm_device":          {"device_metabolic": 0.70, "digital_rpm": 0.20, "diagnostic_poc": 0.10},
    "retina":              {"biologic_cardiology": 0.40, "biologic_immunology": 0.30, "device_ophthalmology": 0.30},
    "sepsis_digital":      {"digital_cds": 0.75, "diagnostic_biomarker": 0.15, "digital_rpm": 0.10},
    "mental_health_dig":   {"digital_therapeutic": 0.70, "drug_mental_health": 0.20, "digital_rpm": 0.10},
    "rpm_cardiac":         {"digital_rpm": 0.65, "device_cardiovascular": 0.25, "digital_cds": 0.10},
}

# Minimum weight to include in output (below this, subcategory is irrelevant)
_MIN_WEIGHT_THRESHOLD = 0.05

# Maximum number of subcategories to return
_MAX_SUBCATEGORIES = 5

# Signal confidence multipliers (some signals are stronger classifiers than others)
_SIGNAL_STRENGTH = {
    "aav_vector": 1.5,      # Very specific — almost certainly gene therapy
    "car_t": 1.6,           # Unmistakable
    "adc": 1.4,             # Highly specific
    "crispr": 1.4,
    "checkpoint": 1.3,
    "enzyme": 1.4,
    "amr_hospital": 1.3,
    "sma": 1.5,
    "dmd": 1.5,
    "sickle_cell": 1.4,
    "sepsis_digital": 1.4,
    "cgm_device": 1.3,
    "diagnostic_poc": 1.3,
    "diagnostic_ngs": 1.3,
}


def extract_signals(idea: str) -> list[str]:
    """Detect all domain signals present in the idea text."""
    idea_l = idea.lower()
    detected = []
    for signal_name, keywords in _SIGNALS.items():
        if any(kw in idea_l for kw in keywords):
            detected.append(signal_name)
    return detected


def compute_soft_weights(idea: str) -> dict[str, float]:
    """
    Compute a weight vector over subcategories using detected signals.
    Uses signal strength multipliers and Bayesian-style combination.
    Returns normalized weights (sum = 1.0).
    """
    detected_signals = extract_signals(idea)
    if not detected_signals:
        return {"drug_oncology": 1.0}  # Safe default

    # Accumulate unnormalized weights
    raw: dict[str, float] = {}
    for signal in detected_signals:
        priors = _SIGNAL_PRIORS.get(signal, {})
        strength = _SIGNAL_STRENGTH.get(signal, 1.0)
        for sub_id, prior_weight in priors.items():
            raw[sub_id] = raw.get(sub_id, 0.0) + prior_weight * strength

    # Filter below threshold
    raw = {k: v for k, v in raw.items() if v > 0}
    if not raw:
        return {"drug_oncology": 1.0}

    # Normalize to sum = 1.0
    total = sum(raw.values())
    normalized = {k: round(v / total, 4) for k, v in raw.items()}

    # Keep only top-N above threshold
    sorted_weights = sorted(normalized.items(), key=lambda x: -x[1])
    filtered = {k: v for k, v in sorted_weights if v >= _MIN_WEIGHT_THRESHOLD}

    # Re-normalize after filtering
    total2 = sum(filtered.values())
    final = {k: round(v / total2, 4) for k, v in filtered.items()}

    # Limit to top-N
    top_n = dict(sorted(final.items(), key=lambda x: -x[1])[:_MAX_SUBCATEGORIES])
    total3 = sum(top_n.values())
    return {k: round(v / total3, 4) for k, v in top_n.items()}


def soft_route(idea: str) -> SoftRoutingResult:
    """
    Main soft routing function. Returns a SoftRoutingResult with weight vector
    and metadata for blending formula parameters.
    """
    detected_signals = extract_signals(idea)
    weights = compute_soft_weights(idea)

    sorted_w = sorted(weights.items(), key=lambda x: -x[1])
    primary = sorted_w[0][0] if sorted_w else "drug_oncology"
    secondary = sorted_w[1][0] if len(sorted_w) > 1 and sorted_w[1][1] >= 0.15 else None
    is_multi_modal = len(sorted_w) >= 2 and sorted_w[1][1] >= 0.20

    # Confidence: how concentrated the weight is on the primary
    primary_weight = weights.get(primary, 1.0)
    confidence = primary_weight  # 1.0 = perfectly concentrated, 0.5 = two equal options

    # Build blend note
    top3_str = ", ".join(f"{k}({v:.0%})" for k, v in sorted_w[:3])
    if is_multi_modal:
        blend_note = f"Multi-modal blend: {top3_str}. Formula parameters weighted across experts."
    else:
        blend_note = f"Primary routing: {primary}({primary_weight:.0%}). {'Secondary signal: ' + secondary if secondary else 'Clear classification.'}"

    return SoftRoutingResult(
        weights=weights,
        primary=primary,
        secondary=secondary,
        is_multi_modal=is_multi_modal,
        signals_detected=detected_signals,
        confidence=round(confidence, 3),
        blend_note=blend_note,
    )


def blend_scoring_profile(weights: dict[str, float]) -> dict:
    """
    Return blended scoring parameters from multiple subcategory profiles.
    Used by the opportunity scorer to apply weighted weights instead of
    hard-switching on a single profile.
    """
    from app.services.opportunity_scorer_v2 import _SUBCATEGORY_PROFILES, _ScoringProfile

    # Weighted blend of w_opp, w_prob, w_val, w_inn, unmet_boost, ptrs_mult
    w_opp_blend   = 0.0
    w_prob_blend  = 0.0
    w_val_blend   = 0.0
    w_inn_blend   = 0.0
    unmet_blend   = 0.0
    ptrs_blend    = 0.0
    ceil_blend    = 0.0

    total = sum(weights.values())

    for sub_id, w in weights.items():
        norm_w = w / total
        profile = _SUBCATEGORY_PROFILES.get(sub_id, _ScoringProfile())
        w_opp_blend  += norm_w * profile.w_opp
        w_prob_blend += norm_w * profile.w_prob
        w_val_blend  += norm_w * profile.w_val
        w_inn_blend  += norm_w * profile.w_inn
        unmet_blend  += norm_w * profile.unmet_boost
        ptrs_blend   += norm_w * profile.ptrs_mult
        ceil_blend   += norm_w * profile.value_ceiling_usd

    return {
        "w_opp":            round(w_opp_blend, 3),
        "w_prob":           round(w_prob_blend, 3),
        "w_val":            round(w_val_blend, 3),
        "w_inn":            round(w_inn_blend, 3),
        "unmet_boost":      round(unmet_blend, 2),
        "ptrs_mult":        round(ptrs_blend, 3),
        "value_ceiling_usd": round(ceil_blend),
        "blend_components": dict(sorted(weights.items(), key=lambda x: -x[1])[:3]),
    }
