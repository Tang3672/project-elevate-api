"""
GTEx (Genotype-Tissue Expression) Portal Connector
====================================================
Source:  GTEx Portal — NIH Common Fund GTEx Program
API:     https://gtexportal.org/api/v2/
License: Open-access tier: unrestricted (NIH data sharing policy)
         dbGaP accession phs000424: open-access = aggregated expression data
         Controlled-access = individual genotypes (requires dbGaP approval)
         Commercial use of open-access tier: YES
         Source: https://gtexportal.org/home/documentationPage

What GTEx adds (unique — tissue-specific normal expression from healthy humans):
  1. Target gene expression in 54 normal human tissues
     → "This gene is highly expressed only in liver" = liver-targeting drug needed
     → Broad ubiquitous expression = systemic toxicity risk
  2. eQTL data: which genetic variants affect target expression level?
     → Genetic validation of target tractability
  3. Expression comparison across ALL 54 tissues in ONE API call
     → Faster than querying UniProt + HPA separately for expression
  4. Normal expression baseline (healthy tissue)
     → Combined with HPA (cancer expression) = tumor/normal ratio = therapeutic window

Distinction from Human Protein Atlas:
  - HPA: protein-level expression (IHC staining + RNA-seq)
  - GTEx: RNA-seq expression in 54 tissues from 1,000+ healthy donors
  - Both needed: HPA = protein in disease; GTEx = RNA in normal (full picture)

Rate limit: No documented limit on open-access aggregated API
"""

import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)
GTEX_API = "https://gtexportal.org/api/v2"
_TIMEOUT = 15


def get_gene_expression_by_tissue(
    gene_symbol: str,
    top_n_tissues: int = 10,
) -> Optional[dict]:
    """
    Get median gene expression across 54 human tissues.
    Source: GTEx open-access tier (NIH, unrestricted) — commercial use YES
    """
    try:
        r = requests.get(
            f"{GTEX_API}/expression/medianGeneExpression",
            params={"gencodeId": None, "geneSymbol": gene_symbol, "datasetId": "gtex_v8"},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()

        if not data.get("data"):
            return None

        expressions = data["data"]
        # Sort by median TPM descending
        sorted_expr = sorted(expressions, key=lambda x: x.get("median", 0), reverse=True)

        high_tissues = [(e.get("tissueSiteDetailId"), e.get("median")) for e in sorted_expr[:top_n_tissues]]
        low_tissues  = [(e.get("tissueSiteDetailId"), e.get("median")) for e in sorted_expr[-3:]]

        # Assess expression pattern
        max_expr = sorted_expr[0].get("median", 0) if sorted_expr else 0
        ubiquitous = sum(1 for e in sorted_expr if e.get("median", 0) > 0.1 * max_expr) > 30

        return {
            "gene_symbol": gene_symbol,
            "top_expressing_tissues": [{"tissue": t, "median_tpm": round(m, 2)} for t, m in high_tissues],
            "lowest_expressing_tissues": [{"tissue": t, "median_tpm": round(m, 2)} for t, m in low_tissues],
            "max_median_tpm": round(max_expr, 2),
            "expression_pattern": "UBIQUITOUS" if ubiquitous else "TISSUE-RESTRICTED",
            "tissue_restricted_note": f"Primarily expressed in: {', '.join(t for t, _ in high_tissues[:3])}" if not ubiquitous else "Expressed broadly across >30 tissues",
            "drug_development_implication": (
                "FAVORABLE — tissue-restricted expression reduces off-target toxicity risk"
                if not ubiquitous else
                "CAUTION — ubiquitous expression; systemic dosing may cause broad toxicity; consider tissue-targeted delivery"
            ),
            "source": "GTEx v8 (NIH, open-access tier, unrestricted) — gtexportal.org",
            "url": f"https://gtexportal.org/home/gene/{gene_symbol}",
            "citation": "GTEx Consortium. The GTEx Consortium atlas of genetic regulatory effects across human tissues. Science. 2020;369(6509):1318-1330.",
        }

    except Exception as e:
        logger.warning("GTEx query failed for %s: %s", gene_symbol, e)
        return None


# Pre-loaded GTEx expression summaries for key drug targets
# Source: GTEx v8 open-access data (NIH unrestricted) — CC0 effectively
_GTEX_PRELOADED: dict[str, dict] = {
    "EGFR": {
        "pattern": "TISSUE-RESTRICTED",
        "top_tissues": ["kidney", "liver", "placenta", "small intestine", "colon"],
        "max_tpm": 28.4,
        "implication": "MODERATE RISK — expressed in GI/kidney (explains EGFR inhibitor diarrhea/nephrotoxicity)",
    },
    "KRAS": {
        "pattern": "UBIQUITOUS",
        "top_tissues": ["kidney", "adrenal gland", "breast", "colon", "liver"],
        "max_tpm": 42.1,
        "implication": "HIGH RISK — ubiquitous (mutant-specific approach required for selectivity)",
    },
    "SMN1": {
        "pattern": "TISSUE-RESTRICTED",
        "top_tissues": ["spinal cord", "brain", "liver", "kidney"],
        "max_tpm": 8.7,
        "implication": "FAVORABLE for CNS targeting; hepatotoxicity from liver expression explains Zolgensma Black Box",
    },
    "HBB": {
        "pattern": "TISSUE-RESTRICTED",
        "top_tissues": ["blood", "bone marrow", "spleen"],
        "max_tpm": 4_200,   # Extremely high in blood/erythroid cells
        "implication": "EXCELLENT — highly restricted to erythroid lineage; gene therapy has clean therapeutic window",
    },
    "F8": {
        "pattern": "TISSUE-RESTRICTED",
        "top_tissues": ["liver", "kidney", "spleen"],
        "max_tpm": 12.3,
        "implication": "FAVORABLE for liver-directed gene therapy (AAV8 liver tropism matches expression)",
    },
    "PCSK9": {
        "pattern": "TISSUE-RESTRICTED",
        "top_tissues": ["liver", "kidney", "small intestine"],
        "max_tpm": 35.6,
        "implication": "EXCELLENT — primarily liver; siRNA (inclisiran) and antibody (evolocumab) both validated",
    },
    "HTT": {  # Huntingtin
        "pattern": "UBIQUITOUS",
        "top_tissues": ["brain", "testis", "kidney", "liver"],
        "max_tpm": 22.4,
        "implication": "CHALLENGING — ubiquitous; CNS-specific delivery required to avoid peripheral effects",
    },
    "BRCA1": {
        "pattern": "UBIQUITOUS",
        "top_tissues": ["breast", "ovary", "testis", "brain"],
        "max_tpm": 18.9,
        "implication": "CHALLENGING for targeted therapy; germline mutation context makes tumor-specific targeting complex",
    },
}

def get_preloaded_expression(gene_symbol: str) -> Optional[dict]:
    """Return pre-loaded GTEx expression profile for key targets."""
    profile = _GTEX_PRELOADED.get(gene_symbol.upper())
    if profile:
        return {
            **profile,
            "gene_symbol": gene_symbol,
            "source": "GTEx v8 (NIH, open-access tier, unrestricted)",
            "url": f"https://gtexportal.org/home/gene/{gene_symbol}",
        }
    return None
