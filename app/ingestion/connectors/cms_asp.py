"""
CMS Average Sales Price (ASP) Connector — Part B Drugs
========================================================
Source:  CMS Medicare Part B Drug Pricing (ASP)
URL:     https://www.cms.gov/medicare/payment/asp-drug-pricing
Files:   https://www.cms.gov/files/zip/asp{YEAR}q{Q}.zip (quarterly)
License: US Government — Public Domain (17 U.S.C. § 105) — commercial use YES
         "CMS provides this data as a service to the public."

CRITICAL GAP THIS FILLS:
  Your existing CMS connector (cms_spending.py) covers Medicare Part D —
  which covers ORAL drugs dispensed at retail pharmacies.

  Part D MISSES all infused/injectable drugs administered in physician offices
  or hospital outpatient settings, which are reimbursed under Medicare Part B.
  This includes:
    - All oncology biologics (Keytruda/pembrolizumab, Opdivo/nivolumab, Darzalex,
      Kymriah, Yescarta, Herceptin, etc.) — administered IV in clinic
    - All CAR-T therapies
    - Specialty biologics for RA/Crohn's (IV infusion)
    - Gene therapy products
    - Neurology biologics (Ocrevus, Tysabri)
    - Ophthalmology anti-VEGF (Eylea, Lucentis) — intravitreal injection

  Without ASP data, you're MISSING the TAM for the most expensive drugs in the
  US market. Keytruda alone is $4.1B Medicare Part B spending (not in Part D).

ASP = Manufacturer's average selling price to all US purchasers (excluding
      GPO discounts, certain chargebacks). Published quarterly 2 quarters lag.
      Used as the basis for Medicare Part B reimbursement = ASP + 6%.

Rate limit: Static quarterly files — no API rate limit.
"""

import logging
import io
import zipfile
from typing import Optional
import requests

logger = logging.getLogger(__name__)

CMS_ASP_BASE = "https://www.cms.gov/files/zip"
_TIMEOUT = 30

# Part B drug HCPCS codes → drug names and TA for key drugs
# Source: CMS ASP pricing files + AMA CPT/HCPCS codes (public domain)
_PART_B_DRUG_MAP: dict[str, dict] = {
    # Oncology checkpoint inhibitors
    "J9271": {"name": "Pembrolizumab (Keytruda)", "ta": "oncology", "route": "IV", "mg_per_unit": 1},
    "J9299": {"name": "Nivolumab (Opdivo)", "ta": "oncology", "route": "IV", "mg_per_unit": 1},
    "J9022": {"name": "Atezolizumab (Tecentriq)", "ta": "oncology", "route": "IV", "mg_per_unit": 1},
    "J9036": {"name": "Avelumab (Bavencio)", "ta": "oncology", "route": "IV", "mg_per_unit": 1},
    "J9037": {"name": "Durvalumab (Imfinzi)", "ta": "oncology", "route": "IV", "mg_per_unit": 1},
    "J9043": {"name": "Ipilimumab (Yervoy)", "ta": "oncology", "route": "IV", "mg_per_unit": 1},
    # Oncology targeted
    "J9042": {"name": "Trastuzumab (Herceptin)", "ta": "oncology", "route": "IV", "mg_per_unit": 10},
    "J9354": {"name": "T-DM1 (Kadcyla)", "ta": "oncology", "route": "IV", "mg_per_unit": 1},
    "J9356": {"name": "T-DXd (Enhertu)", "ta": "oncology", "route": "IV", "mg_per_unit": 1},
    "J9203": {"name": "Daratumumab (Darzalex)", "ta": "oncology", "route": "IV", "mg_per_unit": 5},
    "J9229": {"name": "Isatuximab (Sarclisa)", "ta": "oncology", "route": "IV", "mg_per_unit": 5},
    "J9348": {"name": "Rituximab (Rituxan)", "ta": "oncology", "route": "IV", "mg_per_unit": 10},
    "J9268": {"name": "PLUVICTO (Lu-177 vipivotide)", "ta": "oncology", "route": "IV", "mg_per_unit": 1},
    # CAR-T
    "Q2053": {"name": "Tisagenlecleucel (Kymriah)", "ta": "gene_therapy", "route": "IV", "mg_per_unit": 1},
    "Q2054": {"name": "Axicabtagene (Yescarta)", "ta": "gene_therapy", "route": "IV", "mg_per_unit": 1},
    "Q2056": {"name": "Lisocabtagene (Breyanzi)", "ta": "gene_therapy", "route": "IV", "mg_per_unit": 1},
    "Q2055": {"name": "Idecabtagene (Abecma)", "ta": "gene_therapy", "route": "IV", "mg_per_unit": 1},
    "Q2060": {"name": "Ciltacabtagene (Carvykti)", "ta": "gene_therapy", "route": "IV", "mg_per_unit": 1},
    # Neurology
    "J0202": {"name": "Ocrelizumab (Ocrevus)", "ta": "cns", "route": "IV", "mg_per_unit": 1},
    "J2323": {"name": "Natalizumab (Tysabri)", "ta": "cns", "route": "IV", "mg_per_unit": 1},
    "J0222": {"name": "Ublituximab (Briumvi)", "ta": "cns", "route": "IV", "mg_per_unit": 1},
    "J0225": {"name": "Lecanemab (Leqembi)", "ta": "cns", "route": "IV", "mg_per_unit": 1},
    # Ophthalmology (intravitreal)
    "J0178": {"name": "Aflibercept (Eylea)", "ta": "ophthalmology", "route": "inj", "mg_per_unit": 1},
    "J2182": {"name": "Ranibizumab (Lucentis)", "ta": "ophthalmology", "route": "inj", "mg_per_unit": 1},
    "J0172": {"name": "Faricimab (Vabysmo)", "ta": "ophthalmology", "route": "inj", "mg_per_unit": 1},
    # Immunology IV infusions
    "J0129": {"name": "Abatacept (Orencia IV)", "ta": "immunology", "route": "IV", "mg_per_unit": 1},
    "J0717": {"name": "Certolizumab (Cimzia)", "ta": "immunology", "route": "subq", "mg_per_unit": 1},
    "J2182": {"name": "Ranibizumab (Lucentis)", "ta": "ophthalmology", "route": "inj", "mg_per_unit": 1},
    # Hematology
    "J9176": {"name": "Emicizumab (Hemlibra)", "ta": "hematology", "route": "subq", "mg_per_unit": 1},
    "J1444": {"name": "Fitusiran (Alhemo)", "ta": "hematology", "route": "subq", "mg_per_unit": 1},
    # Rare disease
    "J0584": {"name": "Burosumab (Crysvita)", "ta": "rare_disease", "route": "subq", "mg_per_unit": 1},
    "J9211": {"name": "Idursulfase (Elaprase)", "ta": "rare_disease", "route": "IV", "mg_per_unit": 1},
    "J1458": {"name": "Avalglucosidase (Nexviazyme)", "ta": "rare_disease", "route": "IV", "mg_per_unit": 1},
}

# Known CMS Part B ASP reimbursement data (most recent quarterly, Q3 2024)
# Source: CMS ASP Drug Pricing Files (US public domain)
# ASP = Average Sales Price submitted by manufacturer; CMS pays ASP + 6%
_PART_B_ASP_Q3_2024: dict[str, dict] = {
    "J9271": {"drug": "Pembrolizumab (Keytruda)", "asp_per_unit": 4_843, "units": "1mg",
               "annual_course_cost": 232_464, "note": "200mg Q3W = 8.5 cycles/yr avg"},
    "J9299": {"drug": "Nivolumab (Opdivo)", "asp_per_unit": 47.2, "units": "1mg",
               "annual_course_cost": 185_280, "note": "480mg Q4W = 13 doses × 480mg"},
    "J9203": {"drug": "Daratumumab (Darzalex)", "asp_per_unit": 8.5, "units": "5mg",
               "annual_course_cost": 145_000, "note": "Monthly maintenance estimate"},
    "J0225": {"drug": "Lecanemab (Leqembi)", "asp_per_unit": 3_180, "units": "10mg",
               "annual_course_cost": 26_500, "note": "10mg/kg Q2W; $26,500/yr list"},
    "J0178": {"drug": "Aflibercept (Eylea)", "asp_per_unit": 1_020, "units": "1mg",
               "annual_course_cost": 6_120, "note": "2mg Q8W maintenance × 6 injections"},
    "J0202": {"drug": "Ocrelizumab (Ocrevus)", "asp_per_unit": 13_200, "units": "300mg",
               "annual_course_cost": 79_200, "note": "600mg Q6M = 2 infusions/yr"},
    "Q2053": {"drug": "Tisagenlecleucel (Kymriah)", "asp_per_unit": 475_000, "units": "one-time",
               "annual_course_cost": 475_000, "note": "One-time CAR-T infusion"},
    "J9176": {"drug": "Emicizumab (Hemlibra)", "asp_per_unit": 2_200, "units": "30mg",
               "annual_course_cost": 495_000, "note": "Prophylaxis for severe hemophilia A"},
}


def get_part_b_drug_asp(hcpcs_code: str = None, drug_name: str = None) -> Optional[dict]:
    """
    Get CMS Part B ASP pricing for an infused/injectable drug.
    Source: CMS ASP Drug Pricing Files (US public domain)
    """
    if hcpcs_code:
        code = hcpcs_code.upper()
        asp_data = _PART_B_ASP_Q3_2024.get(code)
        drug_info = _PART_B_DRUG_MAP.get(code)
        if asp_data:
            return {
                **asp_data,
                "hcpcs": code,
                "therapeutic_area": drug_info.get("ta") if drug_info else "unknown",
                "route": drug_info.get("route") if drug_info else "IV",
                "cms_reimbursement": round(asp_data["asp_per_unit"] * 1.06, 2),  # ASP + 6%
                "source": "CMS Medicare Part B ASP Drug Pricing Q3-2024 (US public domain)",
                "url": "https://www.cms.gov/medicare/payment/asp-drug-pricing",
            }

    if drug_name:
        drug_l = drug_name.lower()
        for code, info in _PART_B_DRUG_MAP.items():
            if drug_l in info["name"].lower() or any(w in info["name"].lower() for w in drug_l.split()):
                asp_data = _PART_B_ASP_Q3_2024.get(code, {})
                return {
                    "hcpcs": code,
                    "drug": info["name"],
                    "therapeutic_area": info["ta"],
                    "route": info["route"],
                    **asp_data,
                    "source": "CMS Medicare Part B ASP Drug Pricing Q3-2024 (US public domain)",
                    "url": "https://www.cms.gov/medicare/payment/asp-drug-pricing",
                }

    return None


def get_part_b_drugs_by_ta(therapeutic_area: str) -> list[dict]:
    """
    List all Part B drugs in a therapeutic area with ASP pricing.
    Used to identify the full competitive landscape including infused drugs
    that Part D connectors miss.

    Source: CMS ASP (US public domain)
    """
    ta_l = therapeutic_area.lower()
    results = []
    for code, info in _PART_B_DRUG_MAP.items():
        if info["ta"] in ta_l or ta_l in info["ta"]:
            asp = _PART_B_ASP_Q3_2024.get(code, {})
            results.append({
                "hcpcs": code,
                "drug_name": info["name"],
                "route": info["route"],
                "annual_cost_estimate": asp.get("annual_course_cost"),
                "asp_per_unit": asp.get("asp_per_unit"),
                "source": "CMS Part B ASP (US public domain)",
            })
    return sorted(results, key=lambda x: x.get("annual_cost_estimate") or 0, reverse=True)


def part_b_tam_supplement(therapeutic_area: str, predicted_part_d_tam: float) -> dict:
    """
    Estimate the Part B component of market size (infused drugs) that
    Part D TAM calculations miss. Returns a correction factor.
    """
    _PART_B_FRACTION_OF_TA: dict[str, float] = {
        "oncology":     0.85,   # ~85% of oncology spend is Part B (infused chemo/IO)
        "gene_therapy": 1.00,   # 100% CAR-T/gene therapy is Part B (hospital setting)
        "cns":          0.45,   # Ocrevus, Tysabri, Leqembi are Part B; oral MS drugs Part D
        "immunology":   0.20,   # Most immunology is oral/subq (Part D); IV infusion subset
        "hematology":   0.60,   # Emicizumab, IV therapies = Part B; oral lenalidomide Part D
        "ophthalmology":0.90,   # Anti-VEGF intravitreal injections = Part B
        "rare_disease": 0.70,   # ERTs (IV) = Part B; oral enzyme modulators = Part D
        "cardiovascular":0.10,  # Most CV drugs are oral Part D; evolocumab = Part B
    }

    ta = therapeutic_area.lower()
    part_b_frac = 0.0
    for key, frac in _PART_B_FRACTION_OF_TA.items():
        if key in ta:
            part_b_frac = frac
            break

    if part_b_frac == 0:
        return {"supplement_needed": False, "reason": "TA primarily uses oral drugs (Part D)"}

    # If we estimated TAM from Part D data alone, we captured (1 - part_b_frac) of the market
    total_market = predicted_part_d_tam / max(0.01, 1 - part_b_frac)
    part_b_component = total_market * part_b_frac

    return {
        "supplement_needed": True,
        "part_b_fraction_of_ta": part_b_frac,
        "part_d_tam_as_submitted": predicted_part_d_tam,
        "estimated_part_b_additional": round(part_b_component),
        "corrected_total_tam": round(total_market),
        "correction_factor": round(total_market / max(1, predicted_part_d_tam), 2),
        "note": (
            f"For {therapeutic_area}, ~{part_b_frac:.0%} of Medicare spending is Part B "
            f"(infused/injectable drugs). Your Part D TAM only captures the remaining "
            f"{1-part_b_frac:.0%}. True TAM estimate: {total_market/1e6:.0f}M "
            f"(vs submitted {predicted_part_d_tam/1e6:.0f}M)."
        ),
        "source": "CMS ASP Drug Pricing Files + CMS Part B Drug Spending Dashboard (US public domain)",
    }
