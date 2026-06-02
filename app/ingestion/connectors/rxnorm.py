"""
RxNorm Drug Normalizer
======================
Source:  RxNav REST API (rxnav.nlm.nih.gov/REST)
License: Free, no license — commercial safe
Rate:    20 req/sec (we target 5 to be safe)

Used as the canonical drug join key across openFDA, NIH RePORTER, and
ClinicalTrials.gov, which all use inconsistent drug naming.

Resolution cascade:
  1. Exact RxCUI lookup (if caller already has an ID)
  2. Exact name match  → /drugs.json?name=<name>
  3. Approximate match → /approximateTerm.json?term=<name>&maxEntries=5
  4. Fallback: store raw name with confidence=0 for manual curation
"""

import logging
import time
from typing import Optional

import requests

from app.db.database import get_pool

logger = logging.getLogger(__name__)

RXNAV = "https://rxnav.nlm.nih.gov/REST"
_DELAY = 0.2   # 5 req/sec

# Term types we care about (preferred → clinical drug → ingredient)
_PREFERRED_TTY = {"IN", "PIN", "MIN", "BN", "SCD", "SBD"}


# ── Low-level API helpers ─────────────────────────────────────────────────────

def _get(path: str, params: dict = None) -> Optional[dict]:
    try:
        r = requests.get(f"{RXNAV}/{path}", params=params, timeout=8)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.warning("RxNav %s failed: %s", path, e)
    return None


def _extract_best_concept(data: dict) -> Optional[dict]:
    """From a /drugs.json response, extract the best RxCUI concept."""
    groups = data.get("drugGroup", {}).get("conceptGroup", [])
    for tty_pref in ("IN", "PIN", "MIN", "BN", "SCD"):
        for g in groups:
            if g.get("tty") == tty_pref:
                props = g.get("conceptProperties", [])
                if props:
                    return props[0]
    # Fallback: first available concept
    for g in groups:
        props = g.get("conceptProperties", [])
        if props:
            return props[0]
    return None


# ── Drug row builder ──────────────────────────────────────────────────────────

def _build_drug_row(rxcui: str, name: str, tty: str = "") -> dict:
    """Fetch properties for an RxCUI and build a DB row dict."""
    props_data = _get(f"rxcui/{rxcui}/properties.json")
    time.sleep(_DELAY)

    label = name
    drug_class = None
    brand_names: list[str] = []

    if props_data:
        p = props_data.get("properties", {})
        label = p.get("name", name)

    # Try to get related brand names
    related = _get(f"rxcui/{rxcui}/related.json", {"tty": "BN"})
    if related:
        for g in related.get("relatedGroup", {}).get("conceptGroup", []):
            brand_names += [c["name"] for c in g.get("conceptProperties", [])]
    time.sleep(_DELAY)

    return {
        "rxcui":       rxcui,
        "label":       label,
        "generic_name": label if tty in ("IN", "PIN", "MIN", "SCD") else None,
        "brand_names":  brand_names[:10],
        "drug_class":   drug_class,
        "atc_codes":   [],
    }


# ── DB upsert ─────────────────────────────────────────────────────────────────

async def _upsert_drug(conn, row: dict) -> bool:
    try:
        await conn.execute("""
            INSERT INTO drug (rxcui, label, generic_name, brand_names, drug_class, atc_codes, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW())
            ON CONFLICT (rxcui) DO UPDATE SET
                label        = EXCLUDED.label,
                generic_name = COALESCE(EXCLUDED.generic_name, drug.generic_name),
                brand_names  = EXCLUDED.brand_names,
                updated_at   = NOW()
        """,
            row["rxcui"], row["label"], row.get("generic_name"),
            row["brand_names"], row.get("drug_class"), row["atc_codes"],
        )
        return True
    except Exception as e:
        logger.error("Drug upsert failed for rxcui=%s: %s", row.get("rxcui"), e)
        return False


async def _upsert_xref(conn, source_name: str, source_id: str,
                       rxcui: str, label: str, method: str, confidence: float) -> None:
    try:
        await conn.execute("""
            INSERT INTO xref_map (source_name, source_id, canonical_type, canonical_id, canonical_label, method, confidence)
            VALUES ($1, $2, 'drug', $3, $4, $5, $6)
            ON CONFLICT (source_name, source_id, canonical_type) DO UPDATE SET
                canonical_id    = EXCLUDED.canonical_id,
                canonical_label = EXCLUDED.canonical_label,
                method          = EXCLUDED.method,
                confidence      = EXCLUDED.confidence
        """, source_name, source_id, rxcui, label, method, confidence)
    except Exception as e:
        logger.warning("xref upsert failed: %s", e)


# ── Public API ────────────────────────────────────────────────────────────────

def resolve_drug_name(name: str) -> Optional[dict]:
    """
    Resolve a free-text drug name to RxNorm. Returns dict with rxcui, label,
    tty, confidence. Does NOT touch the DB — pure lookup.
    """
    # 1. Exact match
    data = _get("drugs.json", {"name": name})
    time.sleep(_DELAY)
    if data:
        concept = _extract_best_concept(data)
        if concept:
            return {"rxcui": concept["rxcui"], "label": concept["name"],
                    "tty": concept.get("tty", ""), "method": "exact", "confidence": 1.0}

    # 2. Approximate match
    approx = _get("approximateTerm.json", {"term": name, "maxEntries": 5})
    time.sleep(_DELAY)
    if approx:
        candidates = approx.get("approximateGroup", {}).get("candidate", [])
        if candidates:
            best = max(candidates, key=lambda c: float(c.get("score", 0)))
            score = float(best.get("score", 0))
            if score >= 80:
                rxcui = best.get("rxcui")
                # Fetch name for this rxcui
                props = _get(f"rxcui/{rxcui}/properties.json")
                time.sleep(_DELAY)
                label = props.get("properties", {}).get("name", name) if props else name
                return {"rxcui": rxcui, "label": label,
                        "tty": best.get("rank", ""), "method": "approximate",
                        "confidence": min(score / 100, 0.95)}

    return None


async def load_drugs_for_names(drug_names: list[str],
                               source_name: str = "manual") -> dict[str, str]:
    """
    Resolve and persist a list of drug names. Returns {name: rxcui}.
    """
    pool = await get_pool()
    resolved: dict[str, str] = {}

    async with pool.acquire() as conn:
        for name in drug_names:
            result = resolve_drug_name(name)
            if not result:
                logger.warning("RxNorm: no match for '%s'", name)
                continue

            rxcui = result["rxcui"]
            row   = _build_drug_row(rxcui, result["label"], result["tty"])
            if await _upsert_drug(conn, row):
                await _upsert_xref(conn, source_name, name, rxcui,
                                   result["label"], result["method"], result["confidence"])
                resolved[name] = rxcui
                logger.info("RxNorm: '%s' → %s (%s, conf=%.2f)",
                            name, rxcui, result["method"], result["confidence"])

    return resolved


async def normalize_drug_id(rxcui_or_name: str) -> Optional[str]:
    """
    Fast path: if input looks like a RxCUI (numeric), verify it exists.
    Otherwise resolve by name. Returns RxCUI string or None.
    """
    if rxcui_or_name.isdigit():
        data = _get(f"rxcui/{rxcui_or_name}/status.json")
        if data and data.get("rxcuiStatus", {}).get("status") not in ("NotCurrent", "Unknown", ""):
            return rxcui_or_name
    result = resolve_drug_name(rxcui_or_name)
    return result["rxcui"] if result else None
