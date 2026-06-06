"""
PubChem Connector — Drug Structure, Bioactivity & Target Data
==============================================================
Source:  NCBI PubChem
API:     https://pubchem.ncbi.nlm.nih.gov/rest/pug/
License: US Public Domain (NCBI/NLM government work) — commercial use YES
         "PubChem data is available in the public domain."
         https://pubchem.ncbi.nlm.nih.gov/docs/downloads

What PubChem adds (unique — not in any other free source):
  1. Drug molecular properties: MW, logP, TPSA, H-bond donors/acceptors
     → Lipinski's Rule of 5 compliance → oral bioavailability prediction
  2. Bioassay data: IC50, Ki, EC50 values for drug-target interactions
     → Selectivity profiling → off-target toxicity risk
  3. Patent coverage: which patents cover the compound
  4. Drug synonyms: all names, CAS numbers, InChI, SMILES
  5. Clinical trial association: CID → NCT linkage
  6. Similar compound search: find structural analogues in development
  7. Safety data: GHS hazard classifications, LD50 values

Why critical for market intelligence:
  - Structure-activity relationships → selectivity → safety profile prediction
  - Patent analysis: does the structure hit existing patent claims?
  - Analogue compounds: what else is in development with similar mechanism?
  - Lipinski compliance → oral vs IV delivery assessment

Rate limit: 5 req/sec; NCBI API key recommended for higher limits
API key: https://www.ncbi.nlm.nih.gov/account/
"""

import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)
BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_TIMEOUT = 15


def get_compound_by_name(drug_name: str) -> Optional[dict]:
    """
    Get PubChem compound data by drug name.
    Returns molecular properties, CID, and key identifiers.
    Source: PubChem (NCBI, US Public Domain)
    """
    try:
        # Get CID from name
        r = requests.get(
            f"{BASE}/compound/name/{requests.utils.quote(drug_name)}/property/"
            "MolecularFormula,MolecularWeight,XLogP,TPSA,HBondDonorCount,"
            "HBondAcceptorCount,RotatableBondCount,Complexity/JSON",
            timeout=_TIMEOUT,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        props = r.json().get("PropertyTable", {}).get("Properties", [{}])[0]

        mw = props.get("MolecularWeight", 0)
        logp = props.get("XLogP", 0)
        tpsa = props.get("TPSA", 0)
        hbd = props.get("HBondDonorCount", 0)
        hba = props.get("HBondAcceptorCount", 0)

        # Lipinski's Rule of 5 for oral bioavailability
        ro5_violations = sum([
            mw > 500,
            logp > 5,
            hbd > 5,
            hba > 10,
        ])
        oral_suitable = ro5_violations <= 1

        return {
            "cid": props.get("CID"),
            "name": drug_name,
            "molecular_formula": props.get("MolecularFormula"),
            "molecular_weight": mw,
            "logp": logp,
            "tpsa": tpsa,
            "hbond_donors": hbd,
            "hbond_acceptors": hba,
            "rotatable_bonds": props.get("RotatableBondCount"),
            "lipinski_violations": ro5_violations,
            "oral_bioavailability_rule5": oral_suitable,
            "delivery_route_prediction": "oral candidate" if oral_suitable else "likely IV/injectable (Ro5 violations)",
            "source": "PubChem (NCBI, US Public Domain)",
            "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{props.get('CID')}",
        }
    except Exception as e:
        logger.warning("PubChem query failed for %s: %s", drug_name, e)
        return None


def get_drug_targets_from_bioassay(drug_name: str) -> list[dict]:
    """
    Get confirmed drug-protein interactions from PubChem bioassays.
    Source: PubChem BioAssay database (NCBI, US Public Domain)
    """
    try:
        # First get CID
        r = requests.get(
            f"{BASE}/compound/name/{requests.utils.quote(drug_name)}/cids/JSON",
            timeout=_TIMEOUT,
        )
        if r.status_code == 404:
            return []
        r.raise_for_status()
        cids = r.json().get("IdentifierList", {}).get("CID", [])
        if not cids:
            return []
        cid = cids[0]

        # Get assay data for this compound
        r2 = requests.get(
            f"{BASE}/compound/cid/{cid}/assaysummary/JSON",
            timeout=_TIMEOUT,
        )
        if not r2.ok:
            return []
        assays = r2.json().get("Table", {}).get("Row", [])[:5]

        results = []
        for assay in assays:
            cells = assay.get("Cell", [])
            if len(cells) >= 3:
                results.append({
                    "target": cells[0] if cells else "Unknown",
                    "activity_type": cells[1] if len(cells) > 1 else "",
                    "value": cells[2] if len(cells) > 2 else "",
                    "source": "PubChem BioAssay (NCBI, US Public Domain)",
                    "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}#section=Biological-Activity",
                })
        return results

    except Exception as e:
        logger.warning("PubChem bioassay query failed for %s: %s", drug_name, e)
        return []


def search_similar_drugs(drug_name: str, threshold: float = 0.8) -> list[dict]:
    """
    Find structurally similar compounds (potential competitors or analogues).
    Source: PubChem 2D similarity search (NCBI, US Public Domain)
    """
    try:
        r = requests.get(
            f"{BASE}/compound/name/{requests.utils.quote(drug_name)}/cids/JSON",
            timeout=_TIMEOUT,
        )
        if r.status_code == 404:
            return []
        r.raise_for_status()
        cids = r.json().get("IdentifierList", {}).get("CID", [])
        if not cids:
            return []
        cid = cids[0]

        # Similarity search
        r2 = requests.get(
            f"{BASE}/compound/fastsimilarity_2d/cid/{cid}/cids/JSON",
            params={"Threshold": int(threshold * 100), "MaxRecords": 5},
            timeout=_TIMEOUT,
        )
        if not r2.ok:
            return []
        similar_cids = r2.json().get("IdentifierList", {}).get("CID", [])[:5]

        results = []
        for scid in similar_cids:
            if scid == cid:
                continue
            results.append({
                "cid": scid,
                "similarity_threshold": threshold,
                "source": "PubChem 2D Similarity Search (NCBI, US Public Domain)",
                "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{scid}",
            })
        return results
    except Exception as e:
        logger.warning("PubChem similarity search failed for %s: %s", drug_name, e)
        return []
