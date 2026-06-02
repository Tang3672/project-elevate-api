"""
Open Targets + ChEMBL Mechanism Connector
==========================================
Sources:
  Open Targets Platform GraphQL API (api.platform.opentargets.org)
    License: Apache-2.0 code; data components vary (ChEMBL CC BY-SA, FAERS CC0,
             EFO Apache-2.0). Commercial-safe with attribution.
  ChEMBL REST API (www.ebi.ac.uk/chembl/api/data)
    License: CC BY-SA 3.0 — commercial-safe; share-alike on derivatives.
             Store internally; expose only derived scores + cited snippets.

Provides:
  - disease_target: top drug targets by Open Targets association score
  - drug_mechanism: ChEMBL mechanism of action + max clinical phase per indication
  - drug_disease_indication: ChEMBL drug-indication pairs (supplements FDA approvals)

These feed the PI report mechanism section and give the scoring engine
richer drug-target context for white-space analysis.
"""

import logging
import time
from typing import Optional

import requests

from app.db.database import get_pool

logger = logging.getLogger(__name__)

OT_GRAPHQL   = "https://api.platform.opentargets.org/api/v4/graphql"
CHEMBL_BASE  = "https://www.ebi.ac.uk/chembl/api/data"
_DELAY       = 0.25

# MONDO ID → Open Targets EFO/MONDO ID mapping
# Open Targets accepts MONDO IDs directly since 2023
_OT_DISEASE_IDS: dict[str, str] = {
    "Glioblastoma Multiforme":               "EFO_0000519",
    "Pancreatic Ductal Adenocarcinoma":      "EFO_0002618",
    "ALS (SOD1-mutant)":                     "EFO_0000253",
    "Carbapenem-resistant Enterobacterales": "EFO_0007134",
    "Acinetobacter baumannii MDR":           "EFO_0007134",   # MDR infections
    "Spinal Muscular Atrophy Type 2":        "EFO_0003884",
    "HER2-low Breast Cancer":               "EFO_0000305",
    "KRAS G12C NSCLC":                       "EFO_0003060",
    "Huntington Disease":                    "EFO_0000508",
    "Friedreich Ataxia":                     "EFO_0000508",   # rare neuro proxy
    "C. difficile Infection":               "EFO_0007536",
    "MRSA Skin Infections":                  "EFO_0000514",   # bacterial skin infection
    "Type 1 Diabetes (CGM/automated insulin)": "EFO_0001359",
    "Alzheimer Disease (early/MCI)":        "MONDO_0004975",
    "Pulmonary Arterial Hypertension":       "EFO_0001361",
    "Duchenne Muscular Dystrophy":           "EFO_0003900",
    "Myelofibrosis JAK-resistant":           "EFO_0002475",
    "Geographic Atrophy (dry AMD)":          "EFO_0004683",
    "Sickle Cell Disease (gene therapy)":    "EFO_0000618",
    "RSV in elderly/immunocompromised":      "EFO_0000694",
    "Sepsis (AI early detection)":           "EFO_0000694",   # infectious disease proxy
    "NASH/MASH":                             "EFO_0004197",
    "Prostate Cancer (PSMA-targeted)":       "EFO_0001663",
    "Bipolar Depression":                    "EFO_0000289",
    "Rare Pediatric Epilepsy (SCN1A)":       "EFO_0000474",
}

# ChEMBL indication search terms
_CHEMBL_SEARCH_TERMS: dict[str, str] = {
    "Glioblastoma Multiforme":               "glioblastoma",
    "Alzheimer Disease (early/MCI)":        "alzheimer",
    "Huntington Disease":                    "huntington",
    "Sickle Cell Disease (gene therapy)":    "sickle cell",
    "Spinal Muscular Atrophy Type 2":        "spinal muscular atrophy",
    "Duchenne Muscular Dystrophy":           "duchenne",
    "NASH/MASH":                             "steatohepatitis",
    "Geographic Atrophy (dry AMD)":          "geographic atrophy",
    "Pulmonary Arterial Hypertension":       "pulmonary arterial hypertension",
    "Myelofibrosis JAK-resistant":           "myelofibrosis",
    "Pancreatic Ductal Adenocarcinoma":      "pancreatic cancer",
    "HER2-low Breast Cancer":               "breast cancer HER2",
    "KRAS G12C NSCLC":                       "non-small cell lung",
    "Bipolar Depression":                    "bipolar disorder",
    "Type 1 Diabetes (CGM/automated insulin)": "type 1 diabetes",
}


# ── Open Targets helpers ──────────────────────────────────────────────────────

def _get_top_targets(efo_id: str, n: int = 10) -> list[dict]:
    """Return top associated drug targets for a disease from Open Targets."""
    query = """
    query ($diseaseId: String!, $n: Int!) {
      disease(efoId: $diseaseId) {
        id
        name
        associatedTargets(page: {size: $n}) {
          rows {
            score
            target {
              id
              approvedSymbol
              biotype
              proteinAnnotations { functions }
            }
          }
        }
      }
    }
    """
    try:
        r = requests.post(OT_GRAPHQL, json={"query": query, "variables": {"diseaseId": efo_id, "n": n}}, timeout=15)
        if r.status_code == 200:
            disease = r.json().get("data", {}).get("disease") or {}
            rows = (disease.get("associatedTargets") or {}).get("rows", [])
            return [
                {
                    "target_id":  row["target"]["id"],
                    "symbol":     row["target"]["approvedSymbol"],
                    "biotype":    row["target"]["biotype"],
                    "ot_score":   row["score"],
                    "function":   ((row["target"].get("proteinAnnotations") or {}).get("functions") or [""])[0][:200],
                }
                for row in rows
            ]
    except Exception as e:
        logger.warning("Open Targets failed for %s: %s", efo_id, e)
    return []


def _get_chembl_indications(search_term: str, limit: int = 20) -> list[dict]:
    """Return ChEMBL drug-indication pairs for a disease search term."""
    try:
        r = requests.get(
            f"{CHEMBL_BASE}/drug_indication.json",
            params={"disease_ref_url__icontains": search_term, "limit": limit},
            timeout=15,
        )
        if r.status_code == 200:
            indications = r.json().get("drug_indications", [])
            return [
                {
                    "chembl_id":   ind.get("molecule_chembl_id"),
                    "max_phase":   ind.get("max_phase_for_ind"),
                    "disease_ref": search_term,
                }
                for ind in indications
                if ind.get("molecule_chembl_id")
            ]
    except Exception as e:
        logger.warning("ChEMBL indication failed for '%s': %s", search_term, e)
    return []


def _get_chembl_mechanism(chembl_id: str) -> Optional[dict]:
    """Fetch mechanism of action for a ChEMBL molecule."""
    try:
        r = requests.get(
            f"{CHEMBL_BASE}/mechanism.json",
            params={"molecule_chembl_id": chembl_id, "limit": 5},
            timeout=10,
        )
        if r.status_code == 200:
            mechs = r.json().get("mechanisms", [])
            if mechs:
                m = mechs[0]
                return {
                    "mechanism_of_action": m.get("mechanism_of_action"),
                    "target_chembl_id":    m.get("target_chembl_id"),
                    "action_type":         m.get("action_type"),
                }
    except Exception as e:
        logger.warning("ChEMBL mechanism failed for %s: %s", chembl_id, e)
    return None


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _ensure_target_table(conn) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS disease_target (
            id              SERIAL PRIMARY KEY,
            disease_label   TEXT NOT NULL,
            mondo_id        VARCHAR(20),
            efo_id          TEXT,
            target_id       TEXT,           -- Ensembl gene ID
            symbol          TEXT,           -- gene symbol
            biotype         TEXT,
            ot_score        FLOAT,          -- Open Targets association score
            function_summary TEXT,
            source          TEXT DEFAULT 'open_targets',
            license         TEXT DEFAULT 'CC BY-SA (ChEMBL components) / Apache-2.0 (OT code)',
            fetched_at      TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (disease_label, target_id, source)
        );
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS dt_disease_idx ON disease_target (disease_label);"
    )


async def _upsert_target(conn, disease_label: str, mondo_id: Optional[str],
                          efo_id: str, target: dict) -> None:
    try:
        await conn.execute("""
            INSERT INTO disease_target
                (disease_label, mondo_id, efo_id, target_id, symbol, biotype,
                 ot_score, function_summary)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            ON CONFLICT (disease_label, target_id, source) DO UPDATE SET
                ot_score = EXCLUDED.ot_score, fetched_at = NOW()
        """,
            disease_label, mondo_id, efo_id,
            target["target_id"], target["symbol"], target["biotype"],
            target["ot_score"], target.get("function") or None,
        )
    except Exception as e:
        logger.warning("target upsert failed: %s", e)


# ── Public entry points ───────────────────────────────────────────────────────

async def load_disease_targets(top_n: int = 10) -> dict[str, int]:
    """
    Fetch top drug targets per disease from Open Targets and persist.
    Returns {disease_name: target_count}.
    """
    pool = await get_pool()
    results: dict[str, int] = {}

    async with pool.acquire() as conn:
        await _ensure_target_table(conn)

        for disease, efo_id in _OT_DISEASE_IDS.items():
            targets = _get_top_targets(efo_id, n=top_n)
            time.sleep(_DELAY)

            mondo_id = None
            try:
                row = await conn.fetchrow(
                    "SELECT mondo_id FROM disease WHERE lower(label)=lower($1)", disease
                )
                if row:
                    mondo_id = row["mondo_id"]
            except Exception:
                pass

            for t in targets:
                await _upsert_target(conn, disease, mondo_id, efo_id, t)

            results[disease] = len(targets)
            logger.info("Open Targets: %s → %d targets", disease, len(targets))

    return results


async def load_chembl_indications() -> dict[str, int]:
    """
    Fetch ChEMBL drug-indication pairs and supplement drug_disease_indication table.
    Returns {disease: indication_count}.
    """
    pool = await get_pool()
    results: dict[str, int] = {}

    async with pool.acquire() as conn:
        for disease, search_term in _CHEMBL_SEARCH_TERMS.items():
            indications = _get_chembl_indications(search_term)
            time.sleep(_DELAY)

            mondo_id = None
            try:
                row = await conn.fetchrow(
                    "SELECT mondo_id FROM disease WHERE lower(label)=lower($1)", disease
                )
                if row:
                    mondo_id = row["mondo_id"]
            except Exception:
                pass

            for ind in indications:
                try:
                    await conn.execute("""
                        INSERT INTO drug_disease_indication
                            (drug_label, generic_name, mondo_id, disease_label,
                             application_no, source)
                        VALUES ($1,$1,$2,$3,$4,'chembl')
                        ON CONFLICT (drug_label, disease_label, source) DO NOTHING
                    """,
                        ind["chembl_id"], mondo_id, disease,
                        f"phase_{ind.get('max_phase') or 0}",
                    )
                except Exception:
                    pass

            results[disease] = len(indications)
            logger.info("ChEMBL: %s → %d indications", disease, len(indications))

    return results
