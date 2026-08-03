# Medlevate Market-Sizing Validation Report

**Generated:** 2026-07-20 01:37:06 UTC  
**Engine version:** Professional Market-Sizing Engine v5 (patient_flow → monetization → analog → confidence)  
**Benchmarks:** 15 active / 0 skipped  

---

## Verdict

> **✓ ENGINE VALIDATED FOR ESTABLISHED MARKETS**
>
> MdAPE = **9.8%** (≤ 20% target). Safe to surface numbers in reports **WITH confidence ranges**.
> Always present the range alongside the point estimate, and lead with the honesty statement.

**Calibration (87% of cases where truth fell inside confidence band):** 
✓ **CALIBRATED** — confidence bands contain the truth at the target rate (≥ 70%).

---

## Aggregate Metrics

| Metric | Value | Target |
|--------|-------|--------|
| MdAPE (headline) | **9.8%** | ≤ 20% (target) / ≤ 30% (gate) |
| MAPE | 18.7% | — |
| Calibration rate | 87% | ≥ 70% |
| Median engine/actual ratio | 1.00× | ~1.0× |
| PASS (APE ≤ 20%) | 11 / 15 | — |
| WARN (APE 20–30%) | 2 / 15 | — |
| FAIL (APE > 30%) | 2 / 15 | 0 preferred |

---

## Per-Benchmark Results

| ID | Product type | Engine (compare) | Actual | APE | In band | Status |
|----|----|----|----|----|----|-----|
| keytruda_us | biologic | $19.77B (som_peak) | $17.20B (2024) | 14.9% | ✓ | ✓ PASS |
| wegovy_us | drug_small_molecule | $5.99B (som_base) | $6.50B (2024) | 7.9% | ✓ | ✓ PASS |
| spinraza_us | drug_small_molecule | $586M (sam) | $563M (2023) | 4.1% | ✓ | ✓ PASS |
| thrombectomy_devices_us | medical_device | $878M (sam) | $800M (2023) | 9.7% | ✓ | ✓ PASS |
| da_vinci_us | medical_device | $4.91B (sam) | $4.89B (2023) | 0.4% | ✓ | ✓ PASS |
| guardant_dx_us | diagnostic | $420M (som_base) | $416M (2023) | 1.0% | ✓ | ✓ PASS |
| health_catalyst_us | samd | $378M (som_peak) | $306M (2023) | 23.5% | ✓ | ~ WARN |
| nuzyra_us | antibiotic | $60M (som_peak) | $75M (2022) | 20.7% | ✓ | ~ WARN |
| entresto_us | drug_small_molecule | $1.83B (som_base) | $2.02B (2023) | 9.8% | ✓ | ✓ PASS |
| tepezza_us | biologic | $2.02B (sam) | $1.95B (2022) | 3.6% | ✓ | ✓ PASS |
| zolgensma_us | gene_therapy | $662M (sam) | $742M (2023) | 10.8% | ✓ | ✓ PASS |
| dexcom_cgm_us | medical_device | $2.56B (sam) | $2.56B (2023) | 0.0% | ✓ | ✓ PASS |
| trikafta_us | drug_small_molecule | $7.08B (sam) | $6.20B (2023) | 14.3% | ✓ | ✓ PASS |
| her2_dx_orchestrator | diagnostic | $103M (sam) | $550M (2023) | 81.3% | ✗ | ✗ FAIL |
| af_ablation_orchestrator | medical_device | $197M (sam) | $900M (2023) | 78.1% | ✗ | ✗ FAIL |

---

## By Product Type

| Product type | N | MdAPE | MAPE |
|---|---|---|---|
| medical_device | 4 | 5.1% | 22.1% |
| drug_small_molecule | 4 | 8.8% | 9.0% |
| biologic | 2 | 9.3% | 9.3% |
| gene_therapy | 1 | 10.8% | 10.8% |
| antibiotic | 1 | 20.7% | 20.7% |
| samd | 1 | 23.5% | 23.5% |
| diagnostic | 2 | 41.2% | 41.2% |

> **Priority fix:** The following product types have MdAPE > 30% and should be addressed before customer use: **diagnostic**. These monetization models need better price data or population inputs.

---

## Worst Offenders → Expert Questions

Every validation failure is a targeted KOL/expert interview question. These are the highest-priority conversations to have before the next validation run.

### 1. HER2 IHC testing — US breast cancer (ORCHESTRATOR PATH) (81% under)

- **Engine (sam):** $103M  
- **Actual (2023):** $550M  
- **Source:** Market Research — US HER2 IHC/ISH testing market analyst estimate: ~240,000-260,000 BC HER2 tests/yr × $2,000-2,800 blen...  
- **Analog used:** Companion diagnostic / molecular test  

**Likely cause:** `annual_treatment_cost_usd ($2,500) — net price may be higher than estimated`

**KOL question to close the gap:**
> What is the actual payer reimbursement / net acquisition cost for this product? Current estimate $2,500. Market data implies closer to $13,380. Verify against published WAC, gross-to-net benchmarks, or payer contracts.

### 2. AF ablation catheter procedures — US (ORCHESTRATOR PATH) (78% under)

- **Engine (sam):** $197M  
- **Actual (2023):** $900M  
- **Source:** Market Research — US AF ablation catheter market (cryoablation + pulsed-field + RF catheters, device revenue only): Medt...  
- **Analog used:** Interventional single-use device  

**Likely cause:** `annual_treatment_cost_usd ($5,000) — net price may be higher than estimated`

**KOL question to close the gap:**
> What is the actual payer reimbursement / net acquisition cost for this product? Current estimate $5,000. Market data implies closer to $22,788. Verify against published WAC, gross-to-net benchmarks, or payer contracts.

### 3. Health Catalyst — US hospital analytics software revenue (24% over)

- **Engine (som_peak):** $378M  
- **Actual (2023):** $306M  
- **Source:** Health Catalyst Inc FY2023 Annual Report / 10-K — total net revenue ($306.4M). Health Catalyst discloses ~170 health sys...  
- **Analog used:** Hospital enterprise clinical software  

**Likely cause:** `analog penetration curve (peak penetration (30%) from 'Hospital enterprise clinical software')`

**KOL question to close the gap:**
> Is 30% peak penetration realistic for this product at this stage? The actual revenue implies ~24% effective penetration. Ask: what market share does the leading product have today, and what do analogous launches in this class typically achieve at the same year of commercialization?

---

## Case Details

### keytruda_us — Pembrolizumab (Keytruda) — US net sales

| Field | Value |
|-------|-------|
| Product type | biologic |
| Disease | solid tumors (multi-indication PD-1) |
| Pipeline | monetization+analog (direct) |
| Monetization model | per_patient |
| Analog class | Specialty drug — novel mechanism of action |
| Engine SAM | $79.09B |
| Engine SOM (y3/base) | $11.86B |
| Engine SOM (peak) | $19.77B |
| Confidence band | $10.87B — $31.34B |
| **Engine (som_peak)** | **$19.77B** |
| **Actual (2024)** | **$17.20B** |
| APE | 14.9% |
| Direction | over-estimate (1.15×) |
| Truth in band | Yes ✓ |
| Status | **PASS** |

**Ground truth source:** Merck & Co FY2024 Annual Report / 10-K — US Keytruda (pembrolizumab) net revenues (approximate; verify exact line item in filed 10-K). Merck reports Keytruda US separately from ex-US in their segment disclosure.

**Worst assumption:** `None significant`

**Expert question:** Results within 15% — no immediate correction needed.

### wegovy_us — Semaglutide (Wegovy) — US obesity treatment

| Field | Value |
|-------|-------|
| Product type | drug_small_molecule |
| Disease | obesity / overweight with comorbidity |
| Pipeline | monetization+analog (direct) |
| Monetization model | per_patient |
| Analog class | Specialty drug — novel mechanism of action |
| Engine SAM | $39.90B |
| Engine SOM (y3/base) | $5.99B |
| Engine SOM (peak) | $9.97B |
| Confidence band | $3.29B — $9.49B |
| **Engine (som_base)** | **$5.99B** |
| **Actual (2024)** | **$6.50B** |
| APE | 7.9% |
| Direction | under-estimate (0.92×) |
| Truth in band | Yes ✓ |
| Status | **PASS** |

**Ground truth source:** Novo Nordisk FY2024 Annual Report Q4 2024 press release — Wegovy North America region (DKK 46.3B × 0.71 USD/DKK exchange rate × ~85% US of North America). Note: Novo Nordisk does not separately report US vs Canada for Wegovy; this is an approximation. Verify against filed annual report.

**Worst assumption:** `None significant`

**Expert question:** Results within 15% — no immediate correction needed.

### spinraza_us — Nusinersen (Spinraza) — US orphan SMA treatment

| Field | Value |
|-------|-------|
| Product type | drug_small_molecule |
| Disease | spinal muscular atrophy (prevalent on chronic therapy) |
| Pipeline | monetization+analog (direct) |
| Monetization model | per_patient |
| Analog class | Orphan / rare disease drug |
| Engine SAM | $586M |
| Engine SOM (y3/base) | $322M |
| Engine SOM (peak) | $352M |
| Confidence band | $322M — $929M |
| **Engine (sam)** | **$586M** |
| **Actual (2023)** | **$563M** |
| APE | 4.1% |
| Direction | over-estimate (1.04×) |
| Truth in band | Yes ✓ |
| Status | **PASS** |

**Ground truth source:** Biogen Inc FY2023 Annual Report / 10-K — Spinraza United States net revenues ($563M; Biogen discloses US separately from rest-of-world). Filed with SEC Feb 2024.

**Worst assumption:** `None significant`

**Expert question:** Results within 15% — no immediate correction needed.

### thrombectomy_devices_us — Mechanical thrombectomy devices — US procedure market

| Field | Value |
|-------|-------|
| Product type | medical_device |
| Disease | acute ischemic stroke (large vessel occlusion) |
| Pipeline | monetization+analog (direct) |
| Monetization model | per_procedure |
| Analog class | Interventional single-use device |
| Engine SAM | $878M |
| Engine SOM (y3/base) | $132M |
| Engine SOM (peak) | $307M |
| Confidence band | $483M — $1.39B |
| **Engine (sam)** | **$878M** |
| **Actual (2023)** | **$800M** |
| APE | 9.7% |
| Direction | over-estimate (1.10×) |
| Truth in band | Yes ✓ |
| Status | **PASS** |

**Ground truth source:** GlobalData MedTech Intelligence Report 'US Neurovascular Thrombectomy Devices Market' 2023-2024 (analyst estimate; $700M-$900M range, midpoint $800M). No single public company discloses MT device US revenue separately — Stryker Neurovascular + Medtronic Neurovascular + Penumbra share market. Cross-check: 135,000 procedures × $6,500 blended ASP = $877M (consistent with analyst range).

**Worst assumption:** `None significant`

**Expert question:** Results within 15% — no immediate correction needed.

### da_vinci_us — Intuitive Surgical (da Vinci system) — US annual revenue

| Field | Value |
|-------|-------|
| Product type | medical_device |
| Disease | minimally invasive surgery (robotic-assisted) |
| Pipeline | monetization+analog (direct) |
| Monetization model | per_procedure |
| Analog class | Interventional single-use device |
| Engine SAM | $4.91B |
| Engine SOM (y3/base) | $736M |
| Engine SOM (peak) | $1.72B |
| Confidence band | $2.70B — $7.78B |
| **Engine (sam)** | **$4.91B** |
| **Actual (2023)** | **$4.89B** |
| APE | 0.4% |
| Direction | exact-estimate (1.00×) |
| Truth in band | Yes ✓ |
| Status | **PASS** |

**Ground truth source:** Intuitive Surgical Inc FY2023 Annual Report / 10-K — United States segment revenue ($4,886M). Intuitive reports US vs international separately. Filed with SEC Feb 2024. Ticker: ISRG.

**Worst assumption:** `None significant`

**Expert question:** Results within 15% — no immediate correction needed.

### guardant_dx_us — Guardant Health — US liquid biopsy / precision oncology revenue

| Field | Value |
|-------|-------|
| Product type | diagnostic |
| Disease | solid tumor (advanced/metastatic, liquid biopsy) |
| Pipeline | monetization+analog (direct) |
| Monetization model | per_test |
| Analog class | Companion diagnostic / molecular test |
| Engine SAM | $1.50B |
| Engine SOM (y3/base) | $420M |
| Engine SOM (peak) | $705M |
| Confidence band | $231M — $666M |
| **Engine (som_base)** | **$420M** |
| **Actual (2023)** | **$416M** |
| APE | 1.0% |
| Direction | over-estimate (1.01×) |
| Truth in band | Yes ✓ |
| Status | **PASS** |

**Ground truth source:** Guardant Health Inc FY2023 Annual Report / 10-K — Oncology (precision oncology) segment net revenue ($416M out of $554M total; Guardant separately reports oncology vs development). Filed with SEC Feb 2024. Ticker: GH.

**Worst assumption:** `None significant`

**Expert question:** Results within 15% — no immediate correction needed.

### health_catalyst_us — Health Catalyst — US hospital analytics software revenue

| Field | Value |
|-------|-------|
| Product type | samd |
| Disease | hospital clinical analytics (enterprise health data platform) |
| Pipeline | monetization+analog (direct) |
| Monetization model | site_license |
| Analog class | Hospital enterprise clinical software |
| Engine SAM | $1.26B |
| Engine SOM (y3/base) | $126M |
| Engine SOM (peak) | $378M |
| Confidence band | $265M — $525M |
| **Engine (som_peak)** | **$378M** |
| **Actual (2023)** | **$306M** |
| APE | 23.5% |
| Direction | over-estimate (1.24×) |
| Truth in band | Yes ✓ |
| Status | **WARN** |

**Ground truth source:** Health Catalyst Inc FY2023 Annual Report / 10-K — total net revenue ($306.4M). Health Catalyst discloses ~170 health system clients. Ticker: HCAT. Filed with SEC Feb 2024.

**Worst assumption:** `analog penetration curve (peak penetration (30%) from 'Hospital enterprise clinical software')`

**Expert question:** Is 30% peak penetration realistic for this product at this stage? The actual revenue implies ~24% effective penetration. Ask: what market share does the leading product have today, and what do analogous launches in this class typically achieve at the same year of commercialization?

### nuzyra_us — Omadacycline (Nuzyra) — US AMR antibiotic net revenues

| Field | Value |
|-------|-------|
| Product type | antibiotic |
| Disease | community-acquired bacterial pneumonia (CABP) / ABSSSI |
| Pipeline | monetization+analog (direct) |
| Monetization model | per_patient |
| Analog class | Novel antibiotic / antimicrobial |
| Engine SAM | $298M |
| Engine SOM (y3/base) | $36M |
| Engine SOM (peak) | $60M |
| Confidence band | $42M — $83M |
| **Engine (som_peak)** | **$60M** |
| **Actual (2022)** | **$75M** |
| APE | 20.7% |
| Direction | under-estimate (0.79×) |
| Truth in band | Yes ✓ |
| Status | **WARN** |

**Ground truth source:** Paratek Pharmaceuticals Inc FY2022 Annual Report / 10-K — Nuzyra (omadacycline) US net revenues ($75.2M for FY2022). Paratek was acquired by Zai Lab in October 2023; 2022 is the last full fiscal year with publicly reported standalone results. SEC EDGAR filing.

**Worst assumption:** `analog penetration curve (peak penetration (20%) from 'Novel antibiotic / antimicrobial') — penetration underestimated`

**Expert question:** Is 20% peak penetration too conservative? Actual revenue implies ~25%. This product may have higher-than-analog penetration due to unmet need, reimbursement tailwinds, or supply expansion. Verify: what was the actual launch-year ramp trajectory for comparable products? What is the current market share?

### entresto_us — Sacubitril/Valsartan (Entresto) — US heart failure

| Field | Value |
|-------|-------|
| Product type | drug_small_molecule |
| Disease | heart failure with reduced ejection fraction (HFrEF) |
| Pipeline | monetization+analog (direct) |
| Monetization model | per_patient |
| Analog class | Specialty drug — novel mechanism of action |
| Engine SAM | $12.18B |
| Engine SOM (y3/base) | $1.83B |
| Engine SOM (peak) | $3.04B |
| Confidence band | $1.00B — $2.90B |
| **Engine (som_base)** | **$1.83B** |
| **Actual (2023)** | **$2.02B** |
| APE | 9.8% |
| Direction | under-estimate (0.90×) |
| Truth in band | Yes ✓ |
| Status | **PASS** |

**Ground truth source:** Novartis AG FY2023 Annual Report — Entresto United States net sales CHF 2,239M × 0.905 avg USD/CHF rate ≈ $2,026M. Novartis discloses US separately in geographic segment note. Filed 2024.

**Worst assumption:** `None significant`

**Expert question:** Results within 15% — no immediate correction needed.

### tepezza_us — Teprotumumab (Tepezza) — US thyroid eye disease

| Field | Value |
|-------|-------|
| Product type | biologic |
| Disease | thyroid eye disease (TED, active moderate-to-severe) |
| Pipeline | monetization+analog (direct) |
| Monetization model | per_patient |
| Analog class | Orphan / rare disease drug |
| Engine SAM | $2.02B |
| Engine SOM (y3/base) | $1.11B |
| Engine SOM (peak) | $1.21B |
| Confidence band | $1.11B — $3.20B |
| **Engine (sam)** | **$2.02B** |
| **Actual (2022)** | **$1.95B** |
| APE | 3.6% |
| Direction | over-estimate (1.04×) |
| Truth in band | Yes ✓ |
| Status | **PASS** |

**Ground truth source:** Horizon Therapeutics plc FY2022 Annual Report / 10-K — Tepezza (teprotumumab-trbw) US net sales $1,951.3M. FY2022 is the last full public fiscal year before Amgen acquired Horizon (closed Oct 2023 for $27.8B). SEC EDGAR filing.

**Worst assumption:** `None significant`

**Expert question:** Results within 15% — no immediate correction needed.

### zolgensma_us — Onasemnogene abeparvovec (Zolgensma) — US SMA gene therapy

| Field | Value |
|-------|-------|
| Product type | gene_therapy |
| Disease | spinal muscular atrophy type 1 (SMA1, infant-onset) |
| Pipeline | monetization+analog (direct) |
| Monetization model | per_patient |
| Analog class | Orphan / rare disease drug |
| Engine SAM | $662M |
| Engine SOM (y3/base) | $364M |
| Engine SOM (peak) | $397M |
| Confidence band | $364M — $1.05B |
| **Engine (sam)** | **$662M** |
| **Actual (2023)** | **$742M** |
| APE | 10.8% |
| Direction | under-estimate (0.89×) |
| Truth in band | Yes ✓ |
| Status | **PASS** |

**Ground truth source:** Novartis AG FY2023 Annual Report — Zolgensma global net sales CHF 1,349M × 0.905 avg USD/CHF ≈ $1,221M; US proportion estimated at ~55-60% of global (Novartis does not disclose country-level Zolgensma separately). Midpoint: $1,221M × 0.585 = $714M; using analyst consensus range midpoint $742M. Confidence = medium (US figure estimated, not directly disclosed).

**Worst assumption:** `None significant`

**Expert question:** Results within 15% — no immediate correction needed.

### dexcom_cgm_us — Dexcom G6/G7 CGM — US diabetes

| Field | Value |
|-------|-------|
| Product type | medical_device |
| Disease | type 1 diabetes / insulin-dependent type 2 diabetes (CGM) |
| Pipeline | monetization+analog (direct) |
| Monetization model | per_procedure |
| Analog class | Interventional single-use device |
| Engine SAM | $2.56B |
| Engine SOM (y3/base) | $384M |
| Engine SOM (peak) | $897M |
| Confidence band | $1.41B — $4.06B |
| **Engine (sam)** | **$2.56B** |
| **Actual (2023)** | **$2.56B** |
| APE | 0.0% |
| Direction | exact-estimate (1.00×) |
| Truth in band | Yes ✓ |
| Status | **PASS** |

**Ground truth source:** Dexcom Inc FY2023 Annual Report / 10-K — United States segment net revenue $2,561.0M (out of $3,620.5M total global revenue). Dexcom discloses US vs international separately. Ticker: DXCM. Filed with SEC Feb 2024.

**Worst assumption:** `None significant`

**Expert question:** Results within 15% — no immediate correction needed.

### trikafta_us — Trikafta (elexacaftor/tezacaftor/ivacaftor) — US cystic fibrosis

| Field | Value |
|-------|-------|
| Product type | drug_small_molecule |
| Disease | cystic fibrosis (F508del allele, eligible for CFTR modulator) |
| Pipeline | monetization+analog (direct) |
| Monetization model | per_patient |
| Analog class | Orphan / rare disease drug |
| Engine SAM | $7.08B |
| Engine SOM (y3/base) | $3.90B |
| Engine SOM (peak) | $4.25B |
| Confidence band | $3.90B — $11.23B |
| **Engine (sam)** | **$7.08B** |
| **Actual (2023)** | **$6.20B** |
| APE | 14.3% |
| Direction | over-estimate (1.14×) |
| Truth in band | Yes ✓ |
| Status | **PASS** |

**Ground truth source:** Vertex Pharmaceuticals FY2023 Annual Report / 10-K — Total CF net product revenues $9,858M (global). US proportion estimated at ~63% based on Vertex investor day geographic disclosures and CFF patient registry (US: ~32,000 CF patients out of ~93,000 globally). US est: $9,858M × 0.63 = $6,210M. Vertex does not separately report US CF revenues in 10-K; this is an estimate. Confidence = medium.

**Worst assumption:** `None significant`

**Expert question:** Results within 15% — no immediate correction needed.

### her2_dx_orchestrator — HER2 IHC testing — US breast cancer (ORCHESTRATOR PATH)

| Field | Value |
|-------|-------|
| Product type | diagnostic |
| Disease | HER2-low Breast Cancer |
| Pipeline | orchestrator | pf=fallback_cascade |
| Monetization model | per_test |
| Analog class | Companion diagnostic / molecular test |
| Engine SAM | $103M |
| Engine SOM (y3/base) | $29M |
| Engine SOM (peak) | $48M |
| Confidence band | $57M — $163M |
| **Engine (sam)** | **$103M** |
| **Actual (2023)** | **$550M** |
| APE | 81.3% |
| Direction | under-estimate (0.19×) |
| Truth in band | No ✗ |
| Status | **FAIL** |

**Ground truth source:** Market Research — US HER2 IHC/ISH testing market analyst estimate: ~240,000-260,000 BC HER2 tests/yr × $2,000-2,800 blended net reimbursement = $500-700M total. Midpoint $550M. No single public company reports this figure: Roche (cobas), Dako/Agilent, and Quest/LabCorp share the market. Confidence = medium (analyst estimate, not 10-K).

**Worst assumption:** `annual_treatment_cost_usd ($2,500) — net price may be higher than estimated`

**Expert question:** What is the actual payer reimbursement / net acquisition cost for this product? Current estimate $2,500. Market data implies closer to $13,380. Verify against published WAC, gross-to-net benchmarks, or payer contracts.

### af_ablation_orchestrator — AF ablation catheter procedures — US (ORCHESTRATOR PATH)

| Field | Value |
|-------|-------|
| Product type | medical_device |
| Disease | Atrial Fibrillation |
| Pipeline | orchestrator | pf=fallback_cascade |
| Monetization model | per_procedure |
| Analog class | Interventional single-use device |
| Engine SAM | $197M |
| Engine SOM (y3/base) | $30M |
| Engine SOM (peak) | $69M |
| Confidence band | $109M — $313M |
| **Engine (sam)** | **$197M** |
| **Actual (2023)** | **$900M** |
| APE | 78.1% |
| Direction | under-estimate (0.22×) |
| Truth in band | No ✗ |
| Status | **FAIL** |

**Ground truth source:** Market Research — US AF ablation catheter market (cryoablation + pulsed-field + RF catheters, device revenue only): Medtronic Arctic Front cryoablation + Abbott FlexAbility + Biosig combined US catheter revenue estimated $800M-$1.0B FY2023. No single 10-K discloses this slice. Medtronic EP total US ~$2.1B but includes mapping systems and accessories. Confidence = medium.

**Worst assumption:** `annual_treatment_cost_usd ($5,000) — net price may be higher than estimated`

**Expert question:** What is the actual payer reimbursement / net acquisition cost for this product? Current estimate $5,000. Market data implies closer to $22,788. Verify against published WAC, gross-to-net benchmarks, or payer contracts.

---

## Methodology Notes

**What this harness tests:** Given the correct population and net price as inputs, does the monetization → analog pipeline produce a plausible market size?

**What it does NOT test:** Whether the patient_flow_engine can discover the correct population from scratch (that requires seeded patient_flow_model DB rows and is a separate validation concern).

**Comparison methodology:**
- `sam`: compare engine SAM directly against total market size (when engine inputs represent the full addressable universe)
- `som_peak`: compare engine SOM at peak penetration vs actual revenue of a dominant/mature product
- `som_base`: compare engine SOM at year-3 penetration vs actual revenue of a growing product

**Calibration:** The confidence band is generated by confidence_engine.py based on source quality 
and impact of each assumption. A well-calibrated engine should contain the actual value within its band even when the point estimate is off.

**Next steps if MdAPE > 30%:** See worst offenders above. Each failure maps directly to a KOL interview question. Validation failures are your customer-discovery agenda.

*Generated by `app/validation/run_validation.py` — Medlevate Market Sizing Validation Harness*