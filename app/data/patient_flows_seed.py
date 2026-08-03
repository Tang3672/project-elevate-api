"""
Patient Flow Seed Data  (Build Spec v5, Part B2/B3 + Part E)
=============================================================
Populates patient_flow_model, indication_sequence, epi_table, and pricing_ref
for five representative disease/product-type pairs required by the spec:
  1. Stroke neuroprotection drug (per-patient, 0.20 initial-indication gate)
  2. Sepsis AI early warning (hospital software — site-license, NOT per-patient)
  3. AF catheter ablation device (per-procedure)
  4. HER2-low companion diagnostic (per-test)
  5. SMA gene therapy (orphan analog)

Run: python -m app.data.patient_flows_seed
"""

import asyncio
import json
import logging

logger = logging.getLogger(__name__)


# ── Patient flow models (B2) ──────────────────────────────────────────────────
# The treated_segment and line_of_therapy steps carry rate=null — the engine
# fills these from the product description and segment resolver at runtime.

PATIENT_FLOW_MODELS = [

    # 1. Stroke — neuroprotection drug (per-patient)
    {
        "disease_name": "Stroke (acute ischemic, neuroprotection)",
        "disease_mondo_id": "MONDO:0005098",
        "geography": "US",
        "product_type_hint": "drug_small_molecule",
        "persistency_months": 1,   # acute, single-episode treatment
        "persistency_note": "Acute one-time administration; incident population drives TAM, not prevalent",
        "funnel": [
            {"step": "incidence", "label": "US ischemic stroke incidence/yr",
             "value": 690000, "type": "absolute",
             "source_id": "cdc_wonder", "confidence": "high"},
            {"step": "diagnosed", "label": "clinically diagnosed and admitted to hospital",
             "rate": 0.95, "type": "rate",
             "source_id": "nhanes", "confidence": "medium",
             "note": "Most ischemic strokes reach hospital; ~5% die pre-hospital"},
            {"step": "treated_segment", "label": "eligible for THIS treatment pathway",
             "rate": None, "type": "rate",
             "source_id": "expert", "confidence": "low",
             "note": "FILL-IN: 0.20 for neuroprotection/tPA-adjunct window; 0.16 for LVO thrombectomy. Must be set per product — this is the narrow-responder gate."},
            {"step": "line_of_therapy", "label": "acute treatment window (time-sensitive gate)",
             "rate": None, "type": "rate",
             "source_id": "expert", "confidence": "low",
             "note": "FILL-IN: fraction that can be treated in time (hospital arrival timing). ~0.60 for tPA-eligible acute window."},
            {"step": "product_share", "label": "realistic share for a new entrant",
             "rate": None, "type": "rate",
             "source_id": "adoption_benchmark", "confidence": "low"}
        ],
        "data_quality": "seed",
        "source_type": "literature",
    },

    # 2. Sepsis — AI early warning (hospital software: site-license, NOT per-patient)
    {
        "disease_name": "Sepsis (AI early detection)",
        "disease_mondo_id": "MONDO:0021117",
        "geography": "US",
        "product_type_hint": "samd",
        "persistency_months": 12,  # annual site license
        "persistency_note": "Site-license model: one contract per hospital, not per patient. Patient count is informational only.",
        "funnel": [
            {"step": "total_sites", "label": "US acute-care hospitals with ICU",
             "value": 4000, "type": "absolute",
             "source_id": "cms_physician", "confidence": "high",
             "note": "AHA ~6100 hospitals; ~4000 have ICU + EHR capable of real-time AI feed"},
            {"step": "treated_segment", "label": "hospitals with compatible EHR + sepsis protocol",
             "rate": None, "type": "rate",
             "source_id": "expert", "confidence": "low",
             "note": "FILL-IN: ~0.60 for Epic/Cerner integrated systems with sepsis bundles. This is the addressable site fraction."},
            {"step": "line_of_therapy", "label": "addressable fraction (budget-approved for clinical AI)",
             "rate": None, "type": "rate",
             "source_id": "expert", "confidence": "low",
             "note": "FILL-IN: ~0.40 realistic over 3-yr procurement cycle for hospital AI."},
            {"step": "product_share", "label": "site-level market share for a new entrant",
             "rate": None, "type": "rate",
             "source_id": "adoption_benchmark", "confidence": "low"}
        ],
        "data_quality": "seed",
        "source_type": "literature",
    },

    # 3. AF — catheter ablation device (per-procedure)
    {
        "disease_name": "Atrial Fibrillation",
        "disease_mondo_id": "MONDO:0004981",
        "geography": "US",
        "product_type_hint": "medical_device",
        "persistency_months": 1,   # one-time procedure
        "persistency_note": "Per-procedure: incident ablation volume drives TAM, not prevalent AF population",
        "funnel": [
            {"step": "incidence", "label": "US AF ablation procedures performed/yr",
             "value": 185000, "type": "absolute",
             "source_id": "cms_physician", "confidence": "high",
             "note": "CMS CPT 93656 (AF ablation) Medicare claims extrapolated to all-payer"},
            {"step": "diagnosed", "label": "performed at EP-capable facility",
             "rate": 0.95, "type": "rate",
             "source_id": "cms_physician", "confidence": "high"},
            {"step": "treated_segment", "label": "using THIS catheter/mapping system type",
             "rate": None, "type": "rate",
             "source_id": "expert", "confidence": "low",
             "note": "FILL-IN: e.g. 0.60 for cryoablation systems, 0.40 for novel pulsed-field ablation"},
            {"step": "product_share", "label": "procedure-level market share for a new device",
             "rate": None, "type": "rate",
             "source_id": "adoption_benchmark", "confidence": "low"}
        ],
        "data_quality": "seed",
        "source_type": "literature",
    },

    # 4. HER2-low breast cancer — companion diagnostic (per-test)
    {
        "disease_name": "HER2-low Breast Cancer",
        "disease_mondo_id": "MONDO:0007254",
        "geography": "US",
        "product_type_hint": "diagnostic",
        "persistency_months": 12,   # annual incident testing volume
        "persistency_note": "Per-test: incident breast cancer cases eligible for HER2-low testing drives TAM",
        "funnel": [
            {"step": "incidence", "label": "US breast cancer new cases/yr",
             "value": 310000, "type": "absolute",
             "source_id": "seer", "confidence": "high"},
            {"step": "diagnosed", "label": "with pathology confirmed (all staged cancers)",
             "rate": 0.99, "type": "rate",
             "source_id": "seer", "confidence": "high"},
            {"step": "treated_segment", "label": "HER2 IHC tested (eligible for HER2-low classification)",
             "rate": None, "type": "rate",
             "source_id": "expert", "confidence": "medium",
             "note": "FILL-IN: ~0.85 — most breast cancers are now HER2-tested; HER2-low diagnosis requires IHC 1+ or 2+/ISH-"},
            {"step": "line_of_therapy", "label": "metastatic or HER2-low eligible for re-testing",
             "rate": None, "type": "rate",
             "source_id": "expert", "confidence": "low",
             "note": "FILL-IN: 0.30 metastatic fraction that would be re-tested; plus incident new HER2-low tests"},
            {"step": "product_share", "label": "test-level market share vs competitor assays",
             "rate": None, "type": "rate",
             "source_id": "adoption_benchmark", "confidence": "low"}
        ],
        "data_quality": "seed",
        "source_type": "literature",
    },

    # 5. SMA — gene therapy (orphan drug, per-patient, one-time curative)
    {
        "disease_name": "Spinal Muscular Atrophy Type 2",
        "disease_mondo_id": "MONDO:0011429",
        "geography": "US",
        "product_type_hint": "gene_therapy",
        "persistency_months": 12,   # one-time curative; steady-state annual incident cohort
        "persistency_note": "Gene therapy: incident cases/yr (not prevalent) drives annual revenue. One-time treatment.",
        "funnel": [
            {"step": "incidence", "label": "US SMA Type 1+2 combined births/yr (incident eligible cohort)",
             "value": 600, "type": "absolute",
             "source_id": "nhanes", "confidence": "medium",
             "note": "SMA incidence ~1:10,000 births; ~3.8M US births/yr → ~380 SMA Type 1/yr; Type 2 similar. Use 600/yr for SMA 1+2 combined eligible for gene therapy."},
            {"step": "diagnosed", "label": "diagnosed via newborn screening (NBS) or clinical",
             "rate": 0.90, "type": "rate",
             "source_id": "nhanes", "confidence": "medium",
             "note": "NBS now mandated in ~48 states; some late diagnoses persist"},
            {"step": "treated_segment", "label": "eligible for gene therapy (age/weight criteria)",
             "rate": None, "type": "rate",
             "source_id": "expert", "confidence": "low",
             "note": "FILL-IN: ~0.70 for Zolgensma-class (age <2, weight <21kg); broader for next-gen therapies"},
            {"step": "product_share", "label": "market share vs Zolgensma + nusinersen incumbents",
             "rate": None, "type": "rate",
             "source_id": "adoption_benchmark", "confidence": "low"}
        ],
        "data_quality": "seed",
        "source_type": "literature",
    },

]


# ── Indication sequences (B3) ─────────────────────────────────────────────────

INDICATION_SEQUENCES = [

    {
        "disease_name": "Stroke (acute ischemic, neuroprotection)",
        "product_type_hint": "drug_small_molecule",
        "initial_label": "tPA/acute-treatment-eligible window (initial approval)",
        "initial_fraction": 0.20,
        "initial_source_id": "expert",
        "initial_confidence": "low",
        "expansion_path": [
            {"label": "broader ischemic stroke (e.g. extended window or all comers)",
             "timing_years": 4, "contingent": True, "confidence": "low",
             "note": "Contingent on positive Phase 3 in broader population"}
        ],
        "rule_note": "Present 20% initial gate as base case; expansion as contingent upside labeled '(contingent, 4yr)'",
    },
    {
        "disease_name": "Sepsis (AI early detection)",
        "product_type_hint": "samd",
        "initial_label": "Epic/Cerner-integrated ICU hospitals (initial launch)",
        "initial_fraction": 0.24,  # 4000 sites × 0.60 compatible × 0.40 budget-approved = 960 sites ≈ 24% of total
        "initial_source_id": "expert",
        "initial_confidence": "low",
        "expansion_path": [
            {"label": "community hospitals + Meditech EHR integration",
             "timing_years": 3, "contingent": True, "confidence": "low"}
        ],
        "rule_note": "Initial market = ICU hospitals with compatible EHR; expansion = broader hospital set",
    },
    {
        "disease_name": "Atrial Fibrillation",
        "product_type_hint": "medical_device",
        "initial_label": "persistent AF + antiarrhythmic drug failure (guideline-directed ablation)",
        "initial_fraction": 0.18,  # ~185K ablations / 1.05M newly diagnosed per year ≈ 18%
        "initial_source_id": "cms_physician",
        "initial_confidence": "medium",
        "expansion_path": [
            {"label": "paroxysmal AF (first-line ablation if guideline shift)",
             "timing_years": 3, "contingent": True, "confidence": "low"}
        ],
        "rule_note": "Initial market = current ablation procedure volume; expansion = guideline shift to earlier ablation",
    },
    {
        "disease_name": "HER2-low Breast Cancer",
        "product_type_hint": "diagnostic",
        "initial_label": "metastatic breast cancer HER2-low re-testing",
        "initial_fraction": 0.30,  # metastatic fraction of incident cases
        "initial_source_id": "seer",
        "initial_confidence": "medium",
        "expansion_path": [
            {"label": "all incident breast cancer HER2-low testing (pathology workflow)",
             "timing_years": 2, "contingent": True, "confidence": "medium",
             "note": "Near-term: FDA companion Dx expands to all newly diagnosed breast cancer"}
        ],
        "rule_note": "Initial = metastatic re-testing market; rapid expansion to all incident testing as standard of care",
    },
    {
        "disease_name": "Spinal Muscular Atrophy Type 2",
        "product_type_hint": "gene_therapy",
        "initial_label": "SMA Type 1/2 gene therapy eligible (age + weight criteria)",
        "initial_fraction": 0.63,  # 600 incident × 0.90 diagnosed × 0.70 eligible ≈ 378 ÷ 600 total = 63%
        "initial_source_id": "expert",
        "initial_confidence": "low",
        "expansion_path": [
            {"label": "older/heavier SMA patients (next-gen delivery vector)",
             "timing_years": 5, "contingent": True, "confidence": "low"}
        ],
        "rule_note": "Small, well-defined orphan population; expansion contingent on next-gen vector overcoming weight limit",
    },

]


# ── Epidemiology seed (epi_table) ─────────────────────────────────────────────

EPI_SEED = [
    {"disease_name": "Stroke (acute ischemic, neuroprotection)", "geography": "US",
     "metric": "incidence_annual", "value": 690000, "source_id": "cdc_wonder",
     "source_name": "CDC WONDER / AHA Heart & Stroke Statistics 2024",
     "commercial_ok": True, "year": 2024, "confidence": "high"},
    {"disease_name": "Sepsis (AI early detection)", "geography": "US",
     "metric": "incidence_annual", "value": 1700000, "source_id": "nhanes",
     "source_name": "Rhee et al. 2017 JAMA / CDC — REVIEW", "commercial_ok": True,
     "year": 2017, "confidence": "medium"},
    {"disease_name": "Atrial Fibrillation", "geography": "US",
     "metric": "prevalence", "value": 6000000, "source_id": "cdc_wonder",
     "source_name": "AHA Heart & Stroke Statistics 2024", "commercial_ok": True,
     "year": 2024, "confidence": "high"},
    {"disease_name": "HER2-low Breast Cancer", "geography": "US",
     "metric": "incidence_annual", "value": 310000, "source_id": "seer",
     "source_name": "SEER Cancer Statistics 2023 (all breast cancer)", "commercial_ok": True,
     "year": 2023, "confidence": "high"},
    {"disease_name": "Spinal Muscular Atrophy Type 2", "geography": "US",
     "metric": "incidence_annual", "value": 600, "source_id": "nhanes",
     "source_name": "SMA Foundation / population genetics estimate — REVIEW",
     "commercial_ok": True, "year": 2023, "confidence": "medium"},
]


# ── Pricing references (pricing_ref) ─────────────────────────────────────────

PRICING_SEED = [
    {"disease_name": "Stroke (acute ischemic, neuroprotection)", "product_type": "drug_small_molecule",
     "price_type": "wac", "price_usd": 25000, "net_to_wac_ratio": 0.65,
     "source_id": "nadac", "source_name": "tPA (alteplase) price benchmark + premium",
     "comparator_product": "alteplase (Activase) + novel neuroprotective premium",
     "year": 2024, "confidence": "low",
     "notes": "No approved neuroprotection drug; tPA ~$10K + premium for novel MoA"},
    {"disease_name": "Sepsis (AI early detection)", "product_type": "samd",
     "price_type": "site_license", "price_usd": 75000, "net_to_wac_ratio": 1.0,
     "source_id": "sec_edgar", "source_name": "Viz.ai / Epic Sepsis Model disclosed pricing range",
     "comparator_product": "Viz.ai site license benchmark; Epic Sepsis Model ~$50-100K/yr",
     "year": 2024, "confidence": "low",
     "notes": "Wide range $30K-$150K/site depending on hospital size; use $75K median"},
    {"disease_name": "Atrial Fibrillation", "product_type": "medical_device",
     "price_type": "procedure_reimbursement", "price_usd": 8500, "net_to_wac_ratio": 1.0,
     "source_id": "cms_physician", "source_name": "CMS CPT 93656 AF ablation physician + facility reimbursement",
     "comparator_product": "Boston Scientific Arctic Front cryoablation catheter ~$5-10K device component",
     "year": 2024, "confidence": "medium",
     "notes": "Device revenue per ablation procedure; facility + physician separate"},
    {"disease_name": "HER2-low Breast Cancer", "product_type": "diagnostic",
     "price_type": "per_test", "price_usd": 350, "net_to_wac_ratio": 1.0,
     "source_id": "cms_physician", "source_name": "CMS Clinical Lab Fee Schedule 2024 — IHC stain codes",
     "comparator_product": "IHC HER2 test (88360) CMS CLFS 2024",
     "year": 2024, "confidence": "medium",
     "notes": "Per-test price; companion Dx may command premium of $800-2500 with CDx premium"},
    {"disease_name": "Spinal Muscular Atrophy Type 2", "product_type": "gene_therapy",
     "price_type": "wac", "price_usd": 2100000, "net_to_wac_ratio": 0.85,
     "source_id": "sec_edgar", "source_name": "Novartis Zolgensma WAC 2019 — industry price anchor",
     "comparator_product": "Zolgensma (onasemnogene abeparvovec-xioi) WAC $2.125M",
     "year": 2023, "confidence": "high",
     "notes": "Next-gen SMA gene therapy would price at or below Zolgensma for competitive positioning"},
]


async def seed_patient_flows() -> dict:
    """Seed all patient_flow_model, indication_sequence, epi_table, and pricing_ref rows."""
    from app.db.database import get_pool
    pool = await get_pool()
    counts = {"patient_flow": 0, "indication_sequence": 0, "epi": 0, "pricing": 0}

    async with pool.acquire() as conn:
        for pf in PATIENT_FLOW_MODELS:
            try:
                await conn.execute("""
                    INSERT INTO patient_flow_model
                        (disease_name, disease_mondo_id, geography, product_type_hint,
                         funnel, persistency_months, persistency_note, data_quality, source_type)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    ON CONFLICT (disease_name, geography, product_type_hint) DO NOTHING
                """, pf["disease_name"], pf.get("disease_mondo_id"),
                    pf.get("geography", "US"), pf.get("product_type_hint"),
                    json.dumps(pf["funnel"]),
                    pf.get("persistency_months", 12), pf.get("persistency_note"),
                    pf.get("data_quality", "seed"), pf.get("source_type", "literature"))
                counts["patient_flow"] += 1
            except Exception as e:
                logger.warning("patient_flow seed failed for '%s': %s", pf["disease_name"], e)

        for is_ in INDICATION_SEQUENCES:
            try:
                await conn.execute("""
                    INSERT INTO indication_sequence
                        (disease_name, product_type_hint, initial_label, initial_fraction,
                         initial_source_id, initial_confidence, expansion_path, rule_note, data_quality)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    ON CONFLICT (disease_name, product_type_hint) DO NOTHING
                """, is_["disease_name"], is_.get("product_type_hint"),
                    is_["initial_label"], float(is_["initial_fraction"]),
                    is_.get("initial_source_id"), is_.get("initial_confidence", "low"),
                    json.dumps(is_.get("expansion_path", [])),
                    is_.get("rule_note"), "seed")
                counts["indication_sequence"] += 1
            except Exception as e:
                logger.warning("indication_sequence seed failed: %s", e)

        for ep in EPI_SEED:
            try:
                await conn.execute("""
                    INSERT INTO epi_table
                        (disease_name, geography, metric, value, source_id, source_name,
                         commercial_ok, year, data_quality)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    ON CONFLICT (disease_name, geography, metric, source_id, year, age_group, sex) DO NOTHING
                """, ep["disease_name"], ep.get("geography", "US"), ep["metric"],
                    int(ep["value"]), ep["source_id"], ep.get("source_name"),
                    ep.get("commercial_ok", True), ep.get("year"), "seed")
                counts["epi"] += 1
            except Exception as e:
                logger.warning("epi_table seed failed: %s", e)

        for pr in PRICING_SEED:
            try:
                await conn.execute("""
                    INSERT INTO pricing_ref
                        (disease_name, product_type, price_type, price_usd, net_to_wac_ratio,
                         source_id, source_name, comparator_product, year, confidence, notes)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                    ON CONFLICT (disease_name, product_type, price_type, source_id) DO NOTHING
                """, pr["disease_name"], pr["product_type"], pr["price_type"],
                    float(pr["price_usd"]), float(pr.get("net_to_wac_ratio", 0.55)),
                    pr.get("source_id"), pr.get("source_name"),
                    pr.get("comparator_product"), pr.get("year"),
                    pr.get("confidence", "medium"), pr.get("notes"))
                counts["pricing"] += 1
            except Exception as e:
                logger.warning("pricing_ref seed failed: %s", e)

    logger.info("Patient flow seed: %s", counts)
    return counts


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

    async def _main():
        from app.db.market_sizing_tables_v2 import init_market_sizing_tables_v2
        await init_market_sizing_tables_v2()
        counts = await seed_patient_flows()
        print(f"Seeded: {counts}")

    asyncio.run(_main())
