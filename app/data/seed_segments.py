"""
Seed Market Segments  (Part F of Build Spec v2)
================================================
Source-stamped treatable-segment funnels for ~12 disease/indication pairs.
All rates marked "REVIEW" are analyst estimates requiring KOL validation.
GBD-derived figures are labeled — replace with CDC/WHO-GHO before commercial use.

Run:  python -m app.data.seed_segments
or call seed_market_segments() from any async context.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

# Each entry is one treatable segment. A disease may have multiple entries.
# Funnel walks: absolute (top-line count) → rate gates → access gate → SAM.
# TAM = population BEFORE the "access" gate × price.
# SAM = population AFTER all gates × price.
# SOM = SAM × som_penetration_pct.

SEED_SEGMENTS = [

    # ── Stroke: LVO thrombectomy (reference implementation from spec) ─────────
    {
        "disease_name": "Stroke (acute ischemic, neuroprotection)",
        "disease_mondo_id": "MONDO:0005098",
        "segment_name": "LVO thrombectomy-eligible acute ischemic stroke",
        "pathway_tag": "mechanical_thrombectomy",
        "product_fit_keywords": [
            "thrombectomy", "LVO", "large vessel occlusion", "clot retrieval",
            "stentriever", "aspiration catheter", "neurointervention", "mechanical",
            "endovascular", "TICI", "recanalization",
        ],
        "funnel": [
            {"gate": "total_incidence", "label": "US ischemic stroke incidence/yr",
             "value": 690000, "type": "absolute",
             "source": "CDC/AHA Heart & Stroke Statistics 2024"},
            {"gate": "lvo_fraction", "label": "large-vessel occlusion share",
             "rate": 0.33, "type": "rate",
             "source": "Malhotra et al. 2017 (lit)"},
            {"gate": "eligibility", "label": "thrombectomy-eligible (imaging + time window)",
             "rate": 0.48, "type": "rate",
             "source": "DAWN/DEFUSE-3 extrapolation — REVIEW"},
            {"gate": "access", "label": "reachable at comprehensive stroke centers",
             "rate": 0.70, "type": "rate",
             "source": "analyst estimate — CSC coverage — REVIEW"},
        ],
        "som_penetration_pct": 0.35,
        "som_penetration_src": "analyst estimate — adoption vs incumbents — REVIEW",
        "care_setting": "comprehensive_stroke_center",
        "site_count": 300,
        "site_count_src": "Joint Commission CSC count (approx 2024)",
        "source_type": "literature",
        "data_quality": "seed",
        "notes": (
            "Sizing MUST start here, not at 'all stroke patients'. "
            "Whole-disease TAM is the failure mode this segment exists to prevent."
        ),
    },

    # ── Stroke: neuroprotection / tPA-adjunct ─────────────────────────────────
    {
        "disease_name": "Stroke (acute ischemic, neuroprotection)",
        "disease_mondo_id": "MONDO:0005098",
        "segment_name": "tPA/acute-treatment-eligible ischemic stroke (neuroprotection window)",
        "pathway_tag": "iv_thrombolytic_plus_neuroprotection",
        "product_fit_keywords": [
            "neuroprotection", "tPA", "alteplase", "thrombolytic", "acute ischemic",
            "penumbra", "NIHSS", "salvageable tissue", "IV thrombolysis", "tenecteplase",
        ],
        "funnel": [
            {"gate": "total_incidence", "label": "US ischemic stroke incidence/yr",
             "value": 690000, "type": "absolute",
             "source": "CDC/AHA Heart & Stroke Statistics 2024"},
            {"gate": "acute_presentation", "label": "arrive within 4.5h treatment window",
             "rate": 0.35, "type": "rate",
             "source": "NINDS data — ~35% within tPA window — REVIEW"},
            {"gate": "tpa_eligible", "label": "eligible for IV tPA (no contraindications)",
             "rate": 0.60, "type": "rate",
             "source": "AHA/ASA guidelines 2023 — REVIEW"},
            {"gate": "access", "label": "treated at stroke-ready or comprehensive hospital",
             "rate": 0.80, "type": "rate",
             "source": "analyst estimate — stroke center coverage — REVIEW"},
        ],
        "som_penetration_pct": 0.25,
        "som_penetration_src": "analyst estimate — adjunct therapy adoption — REVIEW",
        "care_setting": "stroke_ready_hospital",
        "site_count": 2000,
        "site_count_src": "Joint Commission stroke-ready hospital count (approx 2024)",
        "source_type": "literature",
        "data_quality": "seed",
        "notes": "Neuroprotection segment — for drugs/biologics given alongside or after tPA.",
    },

    # ── NSCLC: KRAS G12C targeted therapy ─────────────────────────────────────
    {
        "disease_name": "KRAS G12C NSCLC",
        "disease_mondo_id": "MONDO:0005120",
        "segment_name": "KRAS G12C-mutant NSCLC (2nd+ line, sotorasib/adagrasib precedent)",
        "pathway_tag": "kras_g12c_targeted",
        "product_fit_keywords": [
            "KRAS G12C", "KRAS mutation", "sotorasib", "adagrasib", "CodeBreaK",
            "KRYSTAL", "KRAS-targeted", "KRAS inhibitor", "G12C", "KRAS oncogene",
        ],
        "funnel": [
            {"gate": "total_incidence", "label": "US NSCLC new cases/yr",
             "value": 235000, "type": "absolute",
             "source": "SEER Cancer Statistics 2023"},
            {"gate": "kras_g12c_fraction", "label": "KRAS G12C mutation prevalence in NSCLC",
             "rate": 0.13, "type": "rate",
             "source": "Hallin et al. 2020 (Cancer Discovery) — REVIEW"},
            {"gate": "eligibility", "label": "2nd+ line eligible (ECOG 0-2, prior platinum)",
             "rate": 0.70, "type": "rate",
             "source": "analyst estimate — NSCLC treatment sequence — REVIEW"},
            {"gate": "access", "label": "at center with KRAS biomarker testing",
             "rate": 0.80, "type": "rate",
             "source": "analyst estimate — comprehensive genomic profiling access — REVIEW"},
        ],
        "som_penetration_pct": 0.30,
        "som_penetration_src": "analyst estimate — vs sotorasib/adagrasib incumbents — REVIEW",
        "care_setting": "comprehensive_cancer_center",
        "site_count": 1800,
        "site_count_src": "ASCO/NCI cancer center + community oncology estimate (approx)",
        "source_type": "literature",
        "data_quality": "seed",
        "notes": "Biomarker-selected segment — requires KRAS G12C testing.",
    },

    # ── NSCLC: IO-resistant second line ───────────────────────────────────────
    {
        "disease_name": "Lung Cancer (NSCLC, IO-resistant)",
        "disease_mondo_id": "MONDO:0005120",
        "segment_name": "IO-resistant NSCLC (2nd-line post-checkpoint inhibitor progression)",
        "pathway_tag": "io_resistant_second_line",
        "product_fit_keywords": [
            "IO-resistant", "checkpoint resistant", "PD-1 resistant", "PD-L1 resistant",
            "pembrolizumab resistant", "post-IO", "anti-PD1 failure", "second line NSCLC",
            "checkpoint progression", "immunotherapy refractory",
        ],
        "funnel": [
            {"gate": "total_incidence", "label": "US NSCLC new cases/yr",
             "value": 235000, "type": "absolute",
             "source": "SEER Cancer Statistics 2023"},
            {"gate": "io_treated_fraction", "label": "receive first-line IO (mono or combo)",
             "rate": 0.55, "type": "rate",
             "source": "analyst estimate based on NCCN guidelines uptake — REVIEW"},
            {"gate": "progression_fraction", "label": "progress within 24 months (IO-resistant)",
             "rate": 0.60, "type": "rate",
             "source": "KEYNOTE-024 long-term follow-up extrapolation — REVIEW"},
            {"gate": "eligible_second_line", "label": "ECOG 0-2, eligible for 2nd-line therapy",
             "rate": 0.75, "type": "rate",
             "source": "analyst estimate — REVIEW"},
            {"gate": "access", "label": "at facility with genomic profiling capability",
             "rate": 0.80, "type": "rate",
             "source": "analyst estimate — REVIEW"},
        ],
        "som_penetration_pct": 0.20,
        "som_penetration_src": "analyst estimate — highly competitive second-line space — REVIEW",
        "care_setting": "comprehensive_cancer_center",
        "site_count": 1800,
        "site_count_src": "ASCO/NCI cancer center count (approx)",
        "source_type": "literature",
        "data_quality": "seed",
        "notes": "Second-line segment — IO-resistant patients represent large unmet need.",
    },

    # ── HER2-low breast cancer: ADC-eligible ──────────────────────────────────
    {
        "disease_name": "HER2-low Breast Cancer",
        "disease_mondo_id": "MONDO:0007254",
        "segment_name": "HER2-low metastatic breast cancer (ADC-eligible, Enhertu precedent)",
        "pathway_tag": "her2_low_adc",
        "product_fit_keywords": [
            "HER2-low", "IHC 1+", "IHC 2+", "antibody-drug conjugate", "ADC",
            "trastuzumab deruxtecan", "Enhertu", "T-DXd", "HER2-targeted", "payload",
            "topoisomerase", "HER2 expression",
        ],
        "funnel": [
            {"gate": "total_incidence", "label": "US breast cancer new cases/yr",
             "value": 310000, "type": "absolute",
             "source": "ACS Cancer Facts & Figures 2024"},
            {"gate": "her2_low_fraction", "label": "HER2-low (IHC 1+ or 2+/ISH-)",
             "rate": 0.55, "type": "rate",
             "source": "Modi et al. DESTINY-Breast04 (NEJM 2022) — REVIEW"},
            {"gate": "metastatic_fraction", "label": "develop metastatic disease (cumulative)",
             "rate": 0.30, "type": "rate",
             "source": "SEER 5-yr metastatic rate estimate — REVIEW"},
            {"gate": "prior_chemo_eligible", "label": "2+ prior lines, ADC-eligible",
             "rate": 0.70, "type": "rate",
             "source": "analyst estimate — DESTINY-Breast04 eligibility pattern — REVIEW"},
            {"gate": "access", "label": "at cancer center with HER2 IHC testing",
             "rate": 0.85, "type": "rate",
             "source": "analyst estimate — REVIEW"},
        ],
        "som_penetration_pct": 0.25,
        "som_penetration_src": "analyst estimate — vs Enhertu incumbent — REVIEW",
        "care_setting": "comprehensive_cancer_center",
        "site_count": 1800,
        "site_count_src": "NCI cancer center count (approx)",
        "source_type": "literature",
        "data_quality": "seed",
        "notes": "HER2-low is a recently recognized biomarker category distinct from HER2-positive.",
    },

    # ── Carbapenem-resistant Enterobacterales ─────────────────────────────────
    {
        "disease_name": "Carbapenem-resistant Enterobacterales",
        "disease_mondo_id": "MONDO:0021697",
        "segment_name": "Hospitalized CRE infection requiring systemic antibiotic treatment",
        "pathway_tag": "cre_hospital_treatment",
        "product_fit_keywords": [
            "CRE", "carbapenem-resistant", "KPC", "NDM", "OXA-48", "meropenem-resistant",
            "CRKP", "CREC", "Klebsiella pneumoniae resistant", "Enterobacterales resistant",
            "carbapenemase", "NDM-1",
        ],
        "funnel": [
            {"gate": "total_incidence", "label": "US CRE infections per year",
             "value": 13100, "type": "absolute",
             "source": "CDC AR Threats Report 2019"},
            {"gate": "hospitalized_fraction", "label": "requiring hospitalization / systemic Tx",
             "rate": 0.92, "type": "rate",
             "source": "CDC / NHSN — CRE is predominantly healthcare-associated — REVIEW"},
            {"gate": "treatable_fraction", "label": "susceptibility confirmed, guiding therapy",
             "rate": 0.75, "type": "rate",
             "source": "analyst estimate — rapid diagnostics penetration — REVIEW"},
            {"gate": "access", "label": "at hospital with ID consult and novel antibiotic formulary",
             "rate": 0.65, "type": "rate",
             "source": "analyst estimate — ID stewardship program access — REVIEW"},
        ],
        "som_penetration_pct": 0.45,
        "som_penetration_src": "analyst estimate — high unmet need, few alternatives — REVIEW",
        "care_setting": "hospital_inpatient",
        "site_count": 6000,
        "site_count_src": "AHA hospital count (acute care with ID programs, approx)",
        "source_type": "literature",
        "data_quality": "seed",
        "notes": "Small but high-value segment — per-course pricing $15K-$50K range.",
    },

    # ── Type 1 Diabetes: automated insulin delivery ────────────────────────────
    {
        "disease_name": "Type 1 Diabetes (CGM/automated insulin)",
        "disease_mondo_id": "MONDO:0005147",
        "segment_name": "T1D eligible for automated insulin delivery (closed-loop AID systems)",
        "pathway_tag": "automated_insulin_delivery",
        "product_fit_keywords": [
            "automated insulin delivery", "closed-loop", "AID", "hybrid closed-loop",
            "CGM", "continuous glucose monitor", "insulin pump", "T1D technology",
            "artificial pancreas", "Control-IQ", "Omnipod", "Guardian",
        ],
        "funnel": [
            {"gate": "total_prevalence", "label": "US T1D adults + adolescents",
             "value": 1600000, "type": "absolute",
             "source": "CDC Diabetes Statistics 2022 — REVIEW"},
            {"gate": "insulin_dependent_fraction", "label": "on intensive insulin therapy (MDI or pump)",
             "rate": 0.90, "type": "rate",
             "source": "ADA Standards of Care 2024 — virtually all T1D require insulin — REVIEW"},
            {"gate": "technology_eligible", "label": "motivated, HbA1c not at goal or hypoglycemia risk",
             "rate": 0.55, "type": "rate",
             "source": "analyst estimate — AID clinical trial eligibility extrapolation — REVIEW"},
            {"gate": "access", "label": "covered by insurance / can afford CGM+pump system",
             "rate": 0.60, "type": "rate",
             "source": "analyst estimate — payer coverage gap — REVIEW"},
        ],
        "som_penetration_pct": 0.15,
        "som_penetration_src": "analyst estimate — vs Tandem/Omnipod/Medtronic incumbents — REVIEW",
        "care_setting": "outpatient",
        "site_count": 8000,
        "site_count_src": "Endocrinology practices with diabetes technology programs (analyst est.)",
        "source_type": "literature",
        "data_quality": "seed",
        "notes": "Device+digital health segment — access gate dominated by insurance coverage.",
    },

    # ── Alzheimer Disease: amyloid-positive MCI ───────────────────────────────
    {
        "disease_name": "Alzheimer Disease (early/MCI)",
        "disease_mondo_id": "MONDO:0004975",
        "segment_name": "Amyloid-positive MCI/early Alzheimer (lecanemab/donanemab-eligible)",
        "pathway_tag": "amyloid_clearance_therapy",
        "product_fit_keywords": [
            "amyloid", "lecanemab", "Leqembi", "donanemab", "Kisunla", "anti-amyloid",
            "amyloid PET", "CSF biomarker", "MCI", "mild cognitive impairment",
            "early Alzheimer", "ARIA", "amyloid beta", "tau",
        ],
        "funnel": [
            {"gate": "total_prevalence", "label": "US Alzheimer/dementia prevalence",
             "value": 6900000, "type": "absolute",
             "source": "Alzheimer's Association Facts & Figures 2024"},
            {"gate": "early_stage_fraction", "label": "MCI or mild AD stage (anti-amyloid eligible)",
             "rate": 0.35, "type": "rate",
             "source": "Alzheimer's Association staging data — REVIEW"},
            {"gate": "amyloid_positive_fraction", "label": "confirmed amyloid-positive (PET or CSF)",
             "rate": 0.55, "type": "rate",
             "source": "van der Flier et al. 2018 — amyloid prevalence in MCI — REVIEW"},
            {"gate": "eligibility", "label": "no ARIA risk factors, suitable for infusion",
             "rate": 0.70, "type": "rate",
             "source": "CLARITY-AD eligibility extrapolation — REVIEW"},
            {"gate": "access", "label": "at center with amyloid PET/CSF + infusion capacity",
             "rate": 0.35, "type": "rate",
             "source": "analyst estimate — major access bottleneck 2024-2026 — REVIEW"},
        ],
        "som_penetration_pct": 0.12,
        "som_penetration_src": "analyst estimate — early market, limited infusion sites — REVIEW",
        "care_setting": "academic_medical_center",
        "site_count": 500,
        "site_count_src": "Analyst estimate — qualified Alzheimer treatment centers — REVIEW",
        "source_type": "literature",
        "data_quality": "seed",
        "notes": "Access gate is the dominant bottleneck — infusion capacity severely limits uptake.",
    },

    # ── NASH/MASH: advanced fibrosis ──────────────────────────────────────────
    {
        "disease_name": "NASH/MASH",
        "disease_mondo_id": "MONDO:0017311",
        "segment_name": "MASH with moderate-advanced fibrosis (F2-F4, resmetirom-class eligible)",
        "pathway_tag": "mash_fibrosis_targeted",
        "product_fit_keywords": [
            "MASH", "NASH", "steatohepatitis", "liver fibrosis", "F2", "F3", "F4",
            "resmetirom", "Rezdiffra", "THRβ", "thyroid hormone receptor beta",
            "NASH fibrosis", "liver stiffness", "FIB-4",
        ],
        "funnel": [
            {"gate": "total_prevalence", "label": "US MASH (metabolic steatohepatitis) prevalence",
             "value": 8000000, "type": "absolute",
             "source": "Younossi et al. 2023 (Hepatology) — REVIEW"},
            {"gate": "fibrosis_stage_eligible", "label": "fibrosis stage F2-F4 (moderate-advanced)",
             "rate": 0.38, "type": "rate",
             "source": "NASH CRN consortium data — ~38% of MASH has F2+ fibrosis — REVIEW"},
            {"gate": "diagnosed_fraction", "label": "clinically diagnosed / liver biopsy confirmed",
             "rate": 0.25, "type": "rate",
             "source": "analyst estimate — vast underdiagnosis of MASH — REVIEW"},
            {"gate": "access", "label": "under care of hepatologist with biopsy capability",
             "rate": 0.55, "type": "rate",
             "source": "analyst estimate — REVIEW"},
        ],
        "som_penetration_pct": 0.18,
        "som_penetration_src": "analyst estimate — vs resmetirom (Rezdiffra) incumbent — REVIEW",
        "care_setting": "outpatient_hepatology",
        "site_count": 5000,
        "site_count_src": "Hepatology/GI practices with MASH management programs (analyst est.)",
        "source_type": "literature",
        "data_quality": "seed",
        "notes": "Diagnosis rate (0.25) is the key bottleneck — most MASH is undiagnosed.",
    },

    # ── Heart Failure HFrEF: device-refractory / CRT ─────────────────────────
    {
        "disease_name": "Heart Failure (HFrEF, device-refractory)",
        "disease_mondo_id": "MONDO:0005009",
        "segment_name": "HFrEF with dyssynchrony eligible for cardiac resynchronization (CRT/CCM)",
        "pathway_tag": "cardiac_resynchronization",
        "product_fit_keywords": [
            "CRT", "cardiac resynchronization", "LBBB", "QRS prolongation", "dyssynchrony",
            "biventricular pacing", "CCM", "cardiac contractility modulation",
            "device refractory heart failure", "ICD", "HFrEF device", "implantable",
        ],
        "funnel": [
            {"gate": "total_prevalence", "label": "US heart failure prevalence",
             "value": 6700000, "type": "absolute",
             "source": "AHA Heart & Stroke Statistics 2024"},
            {"gate": "hfref_fraction", "label": "HFrEF (ejection fraction <40%)",
             "rate": 0.50, "type": "rate",
             "source": "AHA/ACC HF guidelines 2022 — approximately half of HF is HFrEF — REVIEW"},
            {"gate": "device_eligible", "label": "QRS ≥130ms with LBBB or NYHA 2-3 on GDMT",
             "rate": 0.30, "type": "rate",
             "source": "ESC/ACC CRT guidelines criteria extrapolation — REVIEW"},
            {"gate": "not_already_implanted", "label": "device-naive (no current CRT)",
             "rate": 0.55, "type": "rate",
             "source": "analyst estimate — CRT penetration ~45% of eligible — REVIEW"},
            {"gate": "access", "label": "at EP center with device implant capability",
             "rate": 0.80, "type": "rate",
             "source": "analyst estimate — REVIEW"},
        ],
        "som_penetration_pct": 0.20,
        "som_penetration_src": "analyst estimate — vs Medtronic/Abbott/Boston Scientific — REVIEW",
        "care_setting": "hospital_ep_lab",
        "site_count": 1500,
        "site_count_src": "Electrophysiology labs in US (analyst estimate)",
        "source_type": "literature",
        "data_quality": "seed",
        "notes": "Device segment — FDA class III PMA pathway, not drug approval.",
    },

    # ── Atrial Fibrillation: catheter ablation ────────────────────────────────
    {
        "disease_name": "Atrial Fibrillation",
        "disease_mondo_id": "MONDO:0004981",
        "segment_name": "Persistent/long-standing persistent AF eligible for catheter ablation",
        "pathway_tag": "catheter_ablation_af",
        "product_fit_keywords": [
            "catheter ablation", "pulmonary vein isolation", "PVI", "cryoablation",
            "radiofrequency ablation", "electrophysiology", "AF ablation", "persistent AF",
            "atrial fibrillation rhythm control", "cardiac mapping", "3D mapping",
        ],
        "funnel": [
            {"gate": "total_prevalence", "label": "US atrial fibrillation prevalence",
             "value": 6000000, "type": "absolute",
             "source": "AHA Heart & Stroke Statistics 2024"},
            {"gate": "persistent_fraction", "label": "persistent or long-standing persistent AF",
             "rate": 0.40, "type": "rate",
             "source": "Chugh et al. 2014 (Circulation) — REVIEW"},
            {"gate": "symptomatic_eligible", "label": "symptomatic, antiarrhythmic drug failure/intolerance",
             "rate": 0.45, "type": "rate",
             "source": "CABANA trial eligibility criteria extrapolation — REVIEW"},
            {"gate": "access", "label": "at EP lab with ablation capability, no contraindications",
             "rate": 0.65, "type": "rate",
             "source": "analyst estimate — REVIEW"},
        ],
        "som_penetration_pct": 0.25,
        "som_penetration_src": "analyst estimate — vs cryoballoon/RF ablation incumbents — REVIEW",
        "care_setting": "hospital_ep_lab",
        "site_count": 1200,
        "site_count_src": "EP labs performing AF ablation in US (analyst estimate)",
        "source_type": "literature",
        "data_quality": "seed",
        "notes": "EP device/catheter segment — maps to tools/technologies used in the ablation procedure.",
    },

    # ── Sepsis: AI early detection ─────────────────────────────────────────────
    {
        "disease_name": "Sepsis (AI early detection)",
        "disease_mondo_id": "MONDO:0021117",
        "segment_name": "Inpatient sepsis-at-risk patients (AI early warning system target)",
        "pathway_tag": "sepsis_early_detection_ai",
        "product_fit_keywords": [
            "sepsis detection", "early warning", "AI sepsis", "sepsis prediction",
            "SOFA score", "qSOFA", "sepsis alert", "clinical decision support",
            "ICU sepsis", "machine learning sepsis", "real-time monitoring",
            "EHR integration", "sepsis bundle",
        ],
        "funnel": [
            {"gate": "total_incidence", "label": "US sepsis hospitalizations per year",
             "value": 1700000, "type": "absolute",
             "source": "Rhee et al. 2017 (JAMA) — REVIEW"},
            {"gate": "icu_admitted_fraction", "label": "ICU admission (primary AI target)",
             "rate": 0.40, "type": "rate",
             "source": "HCUP NIS data — REVIEW"},
            {"gate": "early_detection_opportunity", "label": "cases where early AI detection improves outcome",
             "rate": 0.55, "type": "rate",
             "source": "analyst estimate — REVIEW"},
            {"gate": "access", "label": "at hospital with EHR capable of real-time AI integration",
             "rate": 0.60, "type": "rate",
             "source": "analyst estimate — Epic/Cerner AI readiness — REVIEW"},
        ],
        "som_penetration_pct": 0.20,
        "som_penetration_src": "analyst estimate — vs Epic Sepsis Model/Sepsis Sniffer — REVIEW",
        "care_setting": "hospital_icu",
        "site_count": 4000,
        "site_count_src": "ICUs in US acute care hospitals (approx — AHA 2024)",
        "source_type": "literature",
        "data_quality": "seed",
        "notes": "SaMD/digital health segment — FDA De Novo or 510(k), not drug pathway.",
    },

]


async def seed_market_segments() -> int:
    """
    Insert all SEED_SEGMENTS into the market_segment table.
    Skips rows that already exist (ON CONFLICT DO NOTHING).
    Returns the count of rows inserted.
    """
    from app.db.market_segment_repository import upsert_segment
    inserted = 0
    for seg in SEED_SEGMENTS:
        seg_id = await upsert_segment(seg)
        if seg_id is not None:
            inserted += 1
            logger.info("Seeded segment: %s", seg["segment_name"])
        else:
            logger.debug("Segment already exists (skipped): %s", seg["segment_name"])
    logger.info("Seed complete: %d / %d segments inserted", inserted, len(SEED_SEGMENTS))
    return inserted


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

    async def _main():
        from app.db.market_segment_repository import init_market_segment_tables
        await init_market_segment_tables()
        count = await seed_market_segments()
        print(f"Seeded {count} market segments.")

    asyncio.run(_main())
