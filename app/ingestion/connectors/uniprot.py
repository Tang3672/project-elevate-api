"""
UniProt Protein Database Connector
=====================================
Source:  UniProt Consortium (EMBL-EBI, SIB, PIR)
API:     https://rest.uniprot.org/uniprotkb/search
License: CC BY 4.0 — fully commercial safe
         "UniProt data is freely available under the Creative Commons
          Attribution (CC BY 4.0) License."
         Source: https://www.uniprot.org/help/license

What UniProt adds (unique — no other free source covers this):
  1. Canonical drug target protein sequences (the molecular anchor for drug design)
  2. Active site annotation: exactly where in the protein the drug binds
  3. Disease associations: which mutations cause which diseases (from UniProt/SwissProt curation)
  4. Protein function: subcellular location, tissue expression, interaction partners
  5. Cross-references: OMIM, MIM gene IDs, PDB structures, ChEMBL target IDs
  6. Sequence variants: natural variants that affect drug binding

Why critical for market intelligence:
  - Target validation: is this a well-characterized druggable target?
  - Selectivity prediction: how similar is this target to off-targets?
  - Tissue expression: does the target express in the right tissue?
  - Patent context: sequence identity to existing patented proteins
  - Biosimilar analysis: reference protein sequence for similarity scoring

Druggability signals:
  - Active site annotation → "tractable" by small molecule
  - Transmembrane domain → antibody may not access; small molecule needed
  - Secreted protein → antibody accessible
  - Kinase domain → tyrosine kinase inhibitor approach feasible
"""

import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)
UNIPROT_API = "https://rest.uniprot.org/uniprotkb/search"
_TIMEOUT = 15


def get_target_biology(gene_symbol: str, species: str = "Homo sapiens") -> Optional[dict]:
    """
    Get protein biology for a drug target gene.
    Returns druggability signals, disease associations, tissue expression.

    Source: UniProt (CC BY 4.0) — commercial use YES
    """
    try:
        params = {
            "query": f"gene:{gene_symbol} AND organism_id:9606",  # 9606 = Human
            "format": "json",
            "size": 1,
            "fields": "id,gene_names,protein_name,organism_name,cc_disease,cc_function,"
                      "cc_subcellular_location,cc_tissue_specificity,feature_count,"
                      "xref_chembl,keyword,length,mass",
        }
        r = requests.get(UNIPROT_API, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            return None

        entry = results[0]
        accession = entry.get("primaryAccession")
        protein_name = entry.get("proteinDescription", {}).get("recommendedName", {}).get("fullName", {}).get("value", "")
        gene_names = [g.get("value") for g in entry.get("genes", []) if g.get("value")]
        diseases = [d.get("disease", {}).get("diseaseId") for d in entry.get("diseases", []) if d.get("disease")]
        function_text = next(
            (c.get("texts", [{}])[0].get("value", "") for c in entry.get("comments", []) if c.get("commentType") == "FUNCTION"),
            ""
        )
        subcell = next(
            (c.get("subcellularLocations", [{}])[0].get("location", {}).get("value", "") for c in entry.get("comments", []) if c.get("commentType") == "SUBCELLULAR_LOCATION"),
            ""
        )
        keywords = [k.get("value") for k in entry.get("keywords", [])]

        # Druggability signals from keywords
        is_kinase = any(k in keywords for k in ["Kinase", "Tyrosine-protein kinase", "Serine/threonine-protein kinase"])
        is_gpcr = "G-protein coupled receptor" in keywords
        is_secreted = "Secreted" in keywords
        is_transmembrane = "Transmembrane" in keywords
        is_nuclear = "Nucleus" in keywords or "nuclear" in subcell.lower()

        modality_signal = []
        if is_kinase:
            modality_signal.append("Small molecule (kinase inhibitor)")
        if is_secreted or (not is_transmembrane and not is_nuclear):
            modality_signal.append("Biologic/antibody accessible")
        if is_transmembrane:
            modality_signal.append("Caution: transmembrane — antibody access limited")
        if is_nuclear:
            modality_signal.append("Nuclear target — consider ASO/siRNA approach")

        chembl_ids = [x.get("id") for x in entry.get("uniProtKBCrossReferences", []) if x.get("database") == "ChEMBL"]

        return {
            "uniprot_accession": accession,
            "gene_symbol": gene_symbol,
            "protein_name": protein_name,
            "gene_names": gene_names[:3],
            "associated_diseases": diseases[:5],
            "function_summary": function_text[:300],
            "subcellular_location": subcell,
            "is_kinase": is_kinase,
            "is_gpcr": is_gpcr,
            "is_secreted": is_secreted,
            "is_transmembrane": is_transmembrane,
            "modality_recommendation": modality_signal,
            "chembl_target_ids": chembl_ids[:2],
            "keyword_tags": keywords[:8],
            "source": "UniProt (CC BY 4.0) — https://www.uniprot.org/",
            "url": f"https://www.uniprot.org/uniprotkb/{accession}",
        }

    except Exception as e:
        logger.warning("UniProt query failed for %s: %s", gene_symbol, e)
        return None


def get_druggability_assessment(gene_symbol: str) -> dict:
    """
    Return a druggability assessment for a drug target.
    Based on UniProt protein class annotations.
    Source: UniProt (CC BY 4.0)
    """
    target = get_target_biology(gene_symbol)
    if not target:
        return {"gene": gene_symbol, "druggable": "unknown", "modalities": []}

    modalities = target.get("modality_recommendation", [])
    is_druggable = bool(target.get("is_kinase") or target.get("is_gpcr") or target.get("is_secreted"))

    return {
        "gene": gene_symbol,
        "protein": target.get("protein_name"),
        "druggable": "YES" if is_druggable else "REQUIRES_INVESTIGATION",
        "preferred_modalities": modalities,
        "subcellular_location": target.get("subcellular_location"),
        "diseases": target.get("associated_diseases"),
        "source": "UniProt (CC BY 4.0)",
        "url": target.get("url"),
    }
