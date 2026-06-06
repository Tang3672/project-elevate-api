"""
STRING Protein-Protein Interaction Network Connector
======================================================
Source:  STRING — Search Tool for the Retrieval of Interacting Genes/Proteins
API:     https://string-db.org/api/json/network
License: CC BY 4.0 — fully commercial safe
         "STRING data is available under Creative Commons Attribution 4.0 International"
         Source: https://string-db.org/cgi/about?footer_active_subpage=licensing

What STRING adds (unique — not in any other free source):
  1. Protein interaction network: which proteins physically interact with a drug target?
  2. Functional partners: which proteins cooperate in the same cellular process?
  3. Evidence scores: experimental vs computational vs literature-based interactions
  4. Co-expression partners: proteins co-regulated with the target across tissues
  5. Network topology: is the target a hub (many interactors = polypharmacology risk)?

Why critical for market intelligence:
  - Off-target prediction: target interacts with protein X → drug may affect pathway Y
  - Combination therapy rationale: targets A and B interact → combination synergy possible
  - Resistance mechanism: which proteins compensate when target is inhibited?
  - Biomarker discovery: proteins co-expressed with target may be predictive biomarkers

Rate limit: No documented limit; be polite (~1 req/sec)
"""

import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)
STRING_API = "https://string-db.org/api/json"
_TIMEOUT = 15


def get_protein_interactions(
    gene_symbol: str,
    min_score: int = 700,   # 700 = high confidence; 900 = very high
    limit: int = 10,
) -> list[dict]:
    """
    Get high-confidence protein-protein interactions for a drug target.
    Source: STRING v12.0 (CC BY 4.0) — commercial use YES
    """
    try:
        r = requests.post(
            f"{STRING_API}/network",
            data={
                "identifiers": gene_symbol,
                "species": 9606,              # Human
                "required_score": min_score,
                "limit": limit,
                "caller_identity": "projectelevate.io",
            },
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        interactions = r.json()

        results = []
        for interaction in interactions[:limit]:
            results.append({
                "gene_a": interaction.get("preferredName_A"),
                "gene_b": interaction.get("preferredName_B"),
                "combined_score": interaction.get("score"),
                "experimental_score": interaction.get("experimentallyDetermined_interaction"),
                "textmining_score": interaction.get("textmining"),
                "coexpression_score": interaction.get("coexpression"),
                "source": "STRING v12.0 (CC BY 4.0) — string-db.org",
                "url": f"https://string-db.org/cgi/network?identifiers={gene_symbol}&species=9606",
            })
        return results

    except Exception as e:
        logger.warning("STRING query failed for %s: %s", gene_symbol, e)
        return []


def assess_network_liability(gene_symbol: str) -> dict:
    """
    Assess polypharmacology risk from STRING network topology.
    Hub proteins (many interactors) = higher off-target risk.
    Source: STRING (CC BY 4.0)
    """
    interactions = get_protein_interactions(gene_symbol, min_score=700, limit=20)

    if not interactions:
        return {"gene": gene_symbol, "hub_score": "unknown", "off_target_risk": "unknown"}

    high_conf = sum(1 for i in interactions if (i.get("combined_score") or 0) > 900)
    hub_score = len(interactions)

    return {
        "gene": gene_symbol,
        "total_interactors": hub_score,
        "very_high_confidence_interactors": high_conf,
        "hub_score": "HIGH" if hub_score > 15 else "MODERATE" if hub_score > 8 else "LOW",
        "off_target_risk": (
            "ELEVATED — hub protein; drug may affect multiple pathways"
            if hub_score > 15 else
            "MODERATE — typical network connectivity"
            if hub_score > 8 else
            "LOW — limited interactors; clean polypharmacology profile"
        ),
        "top_interactors": [i.get("gene_b") for i in interactions[:5] if i.get("gene_b") != gene_symbol],
        "source": "STRING v12.0 (CC BY 4.0)",
        "url": f"https://string-db.org/cgi/network?identifiers={gene_symbol}&species=9606",
    }
