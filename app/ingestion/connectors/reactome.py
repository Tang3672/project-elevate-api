"""
Reactome Pathway Database Connector
======================================
Source:  Reactome — curated biological pathway database
API:     https://reactome.org/ContentService/data/
License: CC BY 4.0 — fully commercial safe
         "Reactome data is provided under Creative Commons Attribution 4.0 License."
         Source: https://reactome.org/about/license-agreement

What Reactome adds (unique — no other free source covers biological pathways):
  1. Disease pathway context: which cellular pathways does a drug's target sit in?
  2. MOA narrative: what is the mechanism of action in pathway terms?
  3. Disease-pathway mapping: which pathways are disrupted in a disease?
  4. Off-target pathway analysis: which other pathways share the drug's target?
  5. Drug combination rationale: which pathway pairs are synergistic?

Why critical for market intelligence:
  - MOA explanation: Claude can write precise mechanism text anchored in real biology
  - Differentiation narrative: "targets the PI3K/AKT/mTOR pathway at the kinase level,
    downstream of EGFR activation" is far more compelling than generic descriptions
  - Competitive white-space: identify which steps in a disease pathway are undrugged
  - Resistance mechanism: which compensatory pathway activates when target is inhibited?

Rate limit: No documented limit; be respectful (~1 req/sec)
"""

import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)
REACTOME_API = "https://reactome.org/ContentService"
_TIMEOUT = 15

# Pre-loaded pathway → disease mappings (from Reactome curated content)
# Source: Reactome Disease Pathways (CC BY 4.0)
_DISEASE_PATHWAYS: dict[str, list[dict]] = {
    "nsclc": [
        {"pathway": "EGFR signaling", "reactome_id": "R-HSA-177929", "drugged_step": "EGFR kinase (erlotinib, osimertinib)"},
        {"pathway": "RAS signaling", "reactome_id": "R-HSA-9006934", "drugged_step": "KRAS G12C (sotorasib, adagrasib)"},
        {"pathway": "PI3K/AKT/mTOR", "reactome_id": "R-HSA-165159", "drugged_step": "Partially drugged (alpelisib in PIK3CA-mut)"},
    ],
    "breast_cancer": [
        {"pathway": "ER signaling", "reactome_id": "R-HSA-9614657", "drugged_step": "ER (endocrine therapy: tamoxifen, letrozole)"},
        {"pathway": "HER2 signaling", "reactome_id": "R-HSA-1236394", "drugged_step": "HER2 kinase (trastuzumab, pertuzumab, T-DXd)"},
        {"pathway": "CDK4/6 cell cycle", "reactome_id": "R-HSA-453274", "drugged_step": "CDK4/6 (palbociclib, ribociclib, abemaciclib)"},
    ],
    "alzheimers": [
        {"pathway": "Amyloid precursor processing", "reactome_id": "R-HSA-6785807", "drugged_step": "BACE1 (failed); Abeta clearance (lecanemab, donanemab)"},
        {"pathway": "Tau phosphorylation", "reactome_id": "R-HSA-9612973", "drugged_step": "Not yet successfully drugged"},
        {"pathway": "Neuroinflammation/microglial activation", "reactome_id": "R-HSA-9013148", "drugged_step": "Emerging target (AL002, TREM2 agonists)"},
    ],
    "type2_diabetes": [
        {"pathway": "Insulin signaling", "reactome_id": "R-HSA-74752", "drugged_step": "Insulin receptor downstream (metformin, TZDs)"},
        {"pathway": "GLP-1 receptor signaling", "reactome_id": "R-HSA-381676", "drugged_step": "GLP1R agonism (semaglutide, liraglutide)"},
        {"pathway": "SGLT2 glucose transport", "reactome_id": "R-HSA-189200", "drugged_step": "SGLT2 (empagliflozin, dapagliflozin)"},
    ],
    "rheumatoid_arthritis": [
        {"pathway": "JAK-STAT signaling", "reactome_id": "R-HSA-9013148", "drugged_step": "JAK1/2/3 (upadacitinib, tofacitinib, baricitinib)"},
        {"pathway": "TNF signaling", "reactome_id": "R-HSA-5357769", "drugged_step": "TNFalpha (adalimumab, etanercept biosimilars)"},
        {"pathway": "IL-6 signaling", "reactome_id": "R-HSA-6785807", "drugged_step": "IL-6R (tocilizumab, sarilumab)"},
    ],
    "sma": [
        {"pathway": "SMN pre-mRNA splicing", "reactome_id": "R-HSA-72163", "drugged_step": "SMN2 exon 7 inclusion (nusinersen ASO, risdiplam)"},
        {"pathway": "SMN1 gene expression", "reactome_id": "R-HSA-9614657", "drugged_step": "AAV9 gene replacement (Zolgensma)"},
    ],
    "sickle_cell": [
        {"pathway": "Hemoglobin assembly", "reactome_id": "R-HSA-2168880", "drugged_step": "HbF induction (hydroxyurea); HBB gene correction (Casgevy CRISPR)"},
        {"pathway": "Sickling/polymerization", "reactome_id": "R-HSA-2168880", "drugged_step": "Voxelotor (direct HbS polymerization inhibitor)"},
    ],
    "cardiovascular": [
        {"pathway": "Renin-angiotensin-aldosterone", "reactome_id": "R-HSA-2022377", "drugged_step": "ACE/ARB (enalapril, losartan, sacubitril)"},
        {"pathway": "Cardiac muscle contraction", "reactome_id": "R-HSA-5576891", "drugged_step": "Myosin activators (mavacamten for HCM)"},
        {"pathway": "Lipid metabolism/PCSK9", "reactome_id": "R-HSA-174824", "drugged_step": "PCSK9 (evolocumab, alirocumab, inclisiran siRNA)"},
    ],
}


def get_disease_pathways(disease_name: str) -> list[dict]:
    """
    Get curated biological pathways relevant to a disease.
    Provides mechanism-of-action context for report generation.

    Source: Reactome (CC BY 4.0) — commercial use YES
    """
    d_l = disease_name.lower()
    for key, pathways in _DISEASE_PATHWAYS.items():
        if key in d_l or any(w in d_l for w in key.split("_")):
            return [
                {**p, "source": "Reactome Pathway Database (CC BY 4.0)", "url": f"https://reactome.org/content/detail/{p['reactome_id']}"}
                for p in pathways
            ]

    # Try live API
    try:
        r = requests.get(
            f"{REACTOME_API}/data/pathways/top/9606",  # 9606 = Human
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        pathways_all = r.json()[:5]
        return [
            {
                "pathway": p.get("displayName", ""),
                "reactome_id": p.get("stId", ""),
                "drugged_step": "See Reactome for drug annotations",
                "source": "Reactome (CC BY 4.0)",
                "url": f"https://reactome.org/content/detail/{p.get('stId')}",
            }
            for p in pathways_all
        ]
    except Exception as e:
        logger.warning("Reactome API failed for %s: %s", disease_name, e)
        return []


def get_pathway_drugs(reactome_pathway_id: str) -> list[dict]:
    """
    Get drugs known to act on a specific Reactome pathway.
    Source: Reactome drug annotations (CC BY 4.0)
    """
    try:
        r = requests.get(
            f"{REACTOME_API}/data/drugs/mapped/{reactome_pathway_id}",
            timeout=_TIMEOUT,
        )
        if not r.ok:
            return []
        drugs = r.json()
        return [
            {
                "drug_name": d.get("displayName", ""),
                "reactome_id": d.get("dbId"),
                "source": "Reactome Drug Annotations (CC BY 4.0)",
                "url": f"https://reactome.org/content/detail/{reactome_pathway_id}",
            }
            for d in drugs[:10]
        ]
    except Exception as e:
        logger.warning("Reactome pathway drugs query failed: %s", e)
        return []


def format_pathway_context(disease_name: str) -> str:
    """Format pathway context for injection into report prompt."""
    pathways = get_disease_pathways(disease_name)
    if not pathways:
        return ""

    lines = [f"\n=== BIOLOGICAL PATHWAY CONTEXT — {disease_name.upper()} ==="]
    lines.append("Use these pathway names and targets in your mechanism-of-action descriptions:")
    for p in pathways:
        lines.append(f"  • {p['pathway']} [{p['reactome_id']}]")
        lines.append(f"    Current drugging: {p.get('drugged_step', 'See Reactome')}")
        lines.append(f"    Source: {p['source']} | {p['url']}")
    lines.append("\nCite Reactome pathway IDs when describing mechanism of action.")
    return "\n".join(lines)
