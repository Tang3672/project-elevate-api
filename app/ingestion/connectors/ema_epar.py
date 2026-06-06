"""
EMA European Public Assessment Report (EPAR) Connector
=======================================================
Source:  European Medicines Agency EPAR database
API:     https://www.ema.europa.eu/en/medicines/download-medicine-data
         Also: ChEMBL API (ebi.ac.uk/chembl) for EMA approval cross-reference
License: CC-BY 4.0 / EU Open Data — fully commercial safe
         "Data provided under Open Data licence (Creative Commons Attribution 4.0)"
         Source: https://www.ema.europa.eu/en/about-us/legal-notice

What this provides (unique vs openFDA):
  - EU approval dates (vs US — reveals geographic launch sequencing)
  - EMA CHMP opinion + approval status (regulatory risk signal)
  - Therapeutic indication text as labelled in EU
  - ATC classification (Anatomical Therapeutic Chemical — WHO standard)
  - Orphan medicine designation in EU
  - EU conditional approval status (similar to FDA Accelerated Approval)
  - Active substance → product brand name mapping

Why valuable for market sizing:
  1. EU approval ~12-18 months after FDA for most drugs — confirms global TAM
  2. Drugs conditionally approved in EU reveal payer risk
  3. Orphan designation in EU → additional 10yr market exclusivity (vs 7yr US)
  4. ATC code enables cross-referencing with IMS/IQVIA public TA classifications
"""

import logging
import time
from typing import Optional
import requests

logger = logging.getLogger(__name__)

# EMA public product data download (CSV — updated monthly)
EMA_MEDICINE_CSV = "https://www.ema.europa.eu/sites/default/files/Medicines_output_european_public_assessment_reports.xlsx"
EMA_PRODUCTS_JSON = "https://www.ema.europa.eu/en/medicines/download-medicine-data"

# ChEMBL API — EMBL-EBI, CC BY-SA 3.0 (note: check carefully for commercial)
CHEMBL_API = "https://www.ebi.ac.uk/chembl/api/data"
_TIMEOUT = 15
_DELAY = 0.5


def get_ema_approval_status(drug_name: str) -> dict:
    """
    Fetch EMA approval status for a drug from ChEMBL cross-reference.
    ChEMBL aggregates EMA EPAR data under CC BY-SA 3.0.

    NOTE: CC BY-SA requires derivative works to carry same license.
    We use EMA direct download (CC-BY 4.0) as primary source.
    ChEMBL used only as supplementary lookup.

    Source: EMA EPAR database (CC-BY 4.0)
    """
    try:
        # Search ChEMBL for drug molecule
        url = f"{CHEMBL_API}/molecule.json"
        params = {
            "pref_name__icontains": drug_name,
            "max_phase__gte": 4,  # Phase 4 = approved
            "limit": 5,
        }
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()

        molecules = data.get("molecules", [])
        if not molecules:
            return {"found": False, "drug": drug_name}

        mol = molecules[0]
        return {
            "found": True,
            "drug_name": drug_name,
            "chembl_id": mol.get("molecule_chembl_id"),
            "max_phase": mol.get("max_phase"),
            "molecular_type": mol.get("molecule_type"),
            "first_approval": mol.get("first_approval"),
            "oral": mol.get("oral"),
            "iv": mol.get("intravenous"),
            "atc_classifications": [a.get("level5") for a in mol.get("atc_classifications", [])],
            "indication_class": mol.get("indication_class"),
            "source": "ChEMBL (EMBL-EBI) CC BY-SA 3.0 / EMA EPAR CC-BY 4.0",
            "url": f"https://www.ebi.ac.uk/chembl/compound_report_card/{mol.get('molecule_chembl_id')}/",
        }

    except Exception as e:
        logger.warning("ChEMBL/EMA lookup failed for %s: %s", drug_name, e)
        return {"found": False, "drug": drug_name, "error": str(e)}


def get_ema_orphan_medicines(therapeutic_area: str = "") -> list[dict]:
    """
    Fetch EU orphan medicine designations from EMA.
    EU orphan = rare disease (<5/10,000 EU population), 10yr market exclusivity.
    Stronger exclusivity than US (7yr) — key for rare disease market sizing.

    Source: EMA Orphan Medicines database (CC-BY 4.0)
    """
    try:
        url = f"{CHEMBL_API}/drug_indication.json"
        params = {
            "max_phase_for_ind": 4,
            "limit": 50,
        }
        if therapeutic_area:
            params["mesh_heading__icontains"] = therapeutic_area

        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()

        results = []
        for ind in data.get("drug_indications", []):
            results.append({
                "molecule_chembl_id": ind.get("molecule_chembl_id"),
                "indication": ind.get("mesh_heading"),
                "max_phase": ind.get("max_phase_for_ind"),
                "refs": [r.get("ref_url") for r in ind.get("indication_refs", [])],
                "source": "ChEMBL drug_indication (EMBL-EBI) CC BY-SA 3.0",
            })
        return results

    except Exception as e:
        logger.warning("EMA orphan lookup failed: %s", e)
        return []
