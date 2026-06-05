"""
DailyMed Drug Label Connector
================================
Source:  DailyMed — National Library of Medicine, NIH
API:     https://lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html
         Drug Label API: https://lhncbc.nlm.nih.gov/LexSysGroup/Projects/dailymed/current/docs/
         SPL Search: https://dailymed.nlm.nih.gov/dailymed/services/v2/
License: US Public Domain (NLM/NIH government work) — commercial use YES
         "DailyMed content is in the public domain."
         Source: https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm

What DailyMed adds (unique — no other free source provides FDA-approved labeling):
  1. Official FDA-approved indications (exact indication text from labeling)
  2. Contraindications and warnings (Black Box warnings)
  3. Dosing regimens (dose, frequency, route — important for market sizing DoT)
  4. Clinical trial data in label (efficacy data used for regulatory approval)
  5. Drug interactions (off-target safety signals)
  6. Population restrictions (pediatric, renal/hepatic impairment adjustments)
  7. NDC (National Drug Code) mapping (connects brand → manufacturer → NDC)
  8. Biosimilar listing (reference product linkage)

Why critical for market intelligence:
  - Indication text = the EXACT label Claude should reference for regulatory pathway
  - Black Box warnings = market access barrier (REMS requirement signal)
  - Trial data in label = the specific endpoints FDA accepted for approval
  - Dosing = Duration of Therapy (DoT) calculation: mg/kg × body weight × frequency × course length
  - NDC = connects to CMS Part D/B pricing by drug and manufacturer

Rate limit: No documented limit; public service
"""

import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)
DAILYMED_API = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
_TIMEOUT = 15


def get_drug_label(drug_name: str) -> Optional[dict]:
    """
    Get FDA-approved drug labeling from DailyMed.
    Source: DailyMed (NLM/NIH, US Public Domain) — commercial use YES
    """
    try:
        # Search for SPL (Structured Product Label) documents
        r = requests.get(
            f"{DAILYMED_API}/spls.json",
            params={"drug_name": drug_name, "labeltype": "human prescription drug"},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        spls = data.get("data", [])
        if not spls:
            return None

        spl = spls[0]
        set_id = spl.get("setid")

        # Get the full label text for this SPL
        label_url = f"{DAILYMED_API}/spls/{set_id}.json"
        lr = requests.get(label_url, timeout=_TIMEOUT)
        if not lr.ok:
            return {"found": True, "drug_name": drug_name, "set_id": set_id,
                    "source": "DailyMed (NLM, US Public Domain)",
                    "url": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}"}

        label_data = lr.json().get("data", {})
        sections = label_data.get("sections", [])

        # Extract key sections
        extracted = {
            "found": True,
            "drug_name": drug_name,
            "set_id": set_id,
            "title": spl.get("title", ""),
            "labeler": spl.get("labeler", ""),
            "ndcs": [n.get("ndc") for n in spl.get("ndcs", [])[:3]],
        }

        for section in sections:
            name = section.get("name", "").lower()
            text = section.get("text", "")[:500]

            if "indication" in name or "use" in name:
                extracted["indications"] = text
            elif "dosage" in name or "administration" in name:
                extracted["dosing"] = text
            elif "warning" in name or "precaution" in name:
                extracted["warnings"] = text
            elif "contraindication" in name:
                extracted["contraindications"] = text
            elif "clinical studies" in name or "clinical trial" in name:
                extracted["clinical_trial_data"] = text

        extracted["source"] = "DailyMed (NLM/NIH, US Public Domain)"
        extracted["url"] = f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}"
        return extracted

    except Exception as e:
        logger.warning("DailyMed query failed for %s: %s", drug_name, e)
        return None


def get_black_box_warnings(drug_name: str) -> Optional[dict]:
    """
    Check if a drug has FDA Black Box (Boxed) warnings.
    Black Box warnings = significant market access constraint (REMS trigger).
    Source: DailyMed (NLM/NIH, US Public Domain)
    """
    label = get_drug_label(drug_name)
    if not label:
        return None

    has_bbw = "black box" in str(label.get("warnings", "")).lower() or \
              "boxed warning" in str(label.get("warnings", "")).lower()

    return {
        "drug_name": drug_name,
        "has_black_box_warning": has_bbw,
        "warning_text": label.get("warnings", "")[:300],
        "market_impact": "SIGNIFICANT — Black Box warning may trigger REMS and restrict prescriber base" if has_bbw else "None identified",
        "source": "DailyMed (NLM/NIH, US Public Domain)",
        "url": label.get("url", "https://dailymed.nlm.nih.gov/"),
    }


def get_dosing_for_dot_calculation(drug_name: str) -> Optional[dict]:
    """
    Extract dosing regimen for Duration of Therapy (DoT) calculation.
    DoT is critical for market sizing — chronic vs acute changes TAM dramatically.
    Source: DailyMed (NLM/NIH, US Public Domain)
    """
    label = get_drug_label(drug_name)
    if not label:
        return None

    dosing_text = label.get("dosing", "")

    # Parse frequency signals
    is_chronic = any(w in dosing_text.lower() for w in ["once daily", "twice daily", "weekly", "monthly", "ongoing", "continuous"])
    is_acute = any(w in dosing_text.lower() for w in ["days", "week course", "single dose", "one-time", "once"])

    return {
        "drug_name": drug_name,
        "dosing_text": dosing_text[:300],
        "chronic_dosing": is_chronic,
        "acute_episodic": is_acute,
        "dot_category": "chronic/maintenance" if is_chronic and not is_acute else "acute/course-based",
        "source": "DailyMed FDA-approved labeling (NLM/NIH, US Public Domain)",
        "url": label.get("url", "https://dailymed.nlm.nih.gov/"),
    }


# Pre-loaded Black Box warning and dosing data for key drugs
# Source: DailyMed FDA-approved labeling (US Public Domain)
_BBW_DATABASE: dict[str, dict] = {
    "pembrolizumab": {
        "bbw": False, "route": "IV", "frequency": "every 3 or 6 weeks",
        "dot_years": 2.0, "approved_indication": "Multiple solid tumors (PD-L1+)",
    },
    "sotorasib": {
        "bbw": False, "route": "oral", "frequency": "once daily",
        "dot_years": 0.7, "approved_indication": "KRAS G12C+ NSCLC (2L+)",
    },
    "lecanemab": {
        "bbw": True, "bbw_text": "ARIA (Amyloid-Related Imaging Abnormalities) — serious and life-threatening",
        "route": "IV", "frequency": "every 2 weeks",
        "dot_years": 18.0,  # Expected long-term treatment
        "approved_indication": "Early Alzheimer's (amyloid-confirmed)",
        "rems_required": False, "mri_monitoring_required": True,
    },
    "ceftazidime-avibactam": {
        "bbw": False, "route": "IV", "frequency": "every 8 hours",
        "dot_days": 14, "dot_years": 0.038,  # 14-day course
        "approved_indication": "cUTI, HAP/VAP (CRE gram-negatives)",
    },
    "onasemnogene": {
        "bbw": True, "bbw_text": "Serious hepatotoxicity — monitor LFTs; transient decrease in platelets",
        "route": "IV", "frequency": "one-time administration",
        "dot_years": None,  # One-time gene therapy
        "approved_indication": "SMA (SMN1 biallelic deletion/mutation, age <2)",
        "rems_required": False,
    },
    "tisagenlecleucel": {
        "bbw": True, "bbw_text": "Cytokine Release Syndrome (CRS) and neurological toxicities — REMS required",
        "route": "IV infusion", "frequency": "single infusion",
        "dot_years": None,  # One-time CAR-T
        "approved_indication": "r/r B-cell ALL ≤25yr; r/r DLBCL ≥2L",
        "rems_required": True, "certified_centers_only": True,
    },
    "semaglutide_sc": {
        "bbw": True, "bbw_text": "Thyroid C-cell tumors in rodents — contraindicated in personal/family history MEN 2 or thyroid cancer",
        "route": "subcutaneous", "frequency": "once weekly",
        "dot_years": 10.0,  # Chronic maintenance
        "approved_indication": "T2D (Ozempic) and obesity (Wegovy)",
    },
    "axicabtagene": {
        "bbw": True, "bbw_text": "CRS and neurological toxicities including fatal events — REMS required; certified centers only",
        "route": "IV infusion", "frequency": "single infusion",
        "dot_years": None,
        "approved_indication": "r/r LBCL ≥2L; r/r MCL",
        "rems_required": True, "certified_centers_only": True,
    },
    "upadacitinib": {
        "bbw": True, "bbw_text": "Serious infections, mortality, malignancy, CV events, thrombosis — FDA class warning for all JAK inhibitors (2021)",
        "route": "oral", "frequency": "once daily",
        "dot_years": 8.0,  # Chronic RA/IBD
        "approved_indication": "RA, PsA, AS, UC, AD (adult)",
    },
}

def get_bbw_profile(drug_name: str) -> Optional[dict]:
    """Return pre-loaded Black Box warning profile for key drugs."""
    return _BBW_DATABASE.get(drug_name.lower().replace(" ", "_").replace("-", "_"))
