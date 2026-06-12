"""
Commercialization World Model — Knowledge Graph  (Brief Priority 4 / Sprint 3)
==============================================================================
Upgrades the flat per-disease fact cache (`research_world_model`) and the PI
fact store (`pi_memory_service`) into a true **node + edge knowledge graph** that
persists and accumulates across every report.

Why this is the moat: ChatGPT starts every session cold. Medlevate's graph keeps
growing — it learns an institution's diseases, modalities, prior reports,
recommended pathways, KOLs, and (via the P11 feedback loop) TTO decisions and
licensing outcomes. Each new report is linked into that graph and can be
benchmarked against everything seen before.

Schema (two tables):
  wm_nodes(id, node_type, name, norm_key, attributes jsonb, mention_count, first_seen, last_seen)
  wm_edges(id, src_id, dst_id, edge_type, attributes jsonb, confidence, source, created_at)

Node types (from the brief): disease, indication, modality, drug, device,
  diagnostic, company, investor, grant, sbir_award, clinical_trial, patent,
  fda_approval, fda_designation, kol, university, hospital, reimbursement_code,
  report, pi_profile, tto_decision, licensing_outcome, regulatory_pathway.
Edge types: targets, treats, competes_with, funded_by, patented_by, licensed_to,
  approved_for, trial_sponsor, similar_to, same_mechanism_as, same_indication_as,
  higher_risk_than, better_fit_for, recommended_pathway, institution_decision,
  analyzes, concerns, eligible_for, has_kol, authored, focus_area.

`extract_graph_from_report` is a PURE transform (deterministic, unit-testable);
all persistence/normalization helpers degrade gracefully and never raise into
the report path.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

NODE_TYPES = {
    "disease", "indication", "modality", "drug", "device", "diagnostic",
    "company", "investor", "grant", "sbir_award", "clinical_trial", "patent",
    "fda_approval", "fda_designation", "kol", "university", "hospital",
    "reimbursement_code", "report", "pi_profile", "tto_decision",
    "licensing_outcome", "regulatory_pathway",
}
EDGE_TYPES = {
    "targets", "treats", "competes_with", "funded_by", "patented_by",
    "licensed_to", "approved_for", "trial_sponsor", "similar_to",
    "same_mechanism_as", "same_indication_as", "higher_risk_than",
    "better_fit_for", "recommended_pathway", "institution_decision",
    "analyzes", "concerns", "eligible_for", "has_kol", "authored", "focus_area",
}


# ── Normalization ──────────────────────────────────────────────────────────────

def normalize_key(name: str) -> str:
    """Canonical id: lowercased, punctuation→space, whitespace collapsed."""
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _node_ref(node_type: str, name: str) -> str:
    return f"{node_type}::{normalize_key(name)}"


def report_id_for(report: dict) -> str:
    """Stable canonical id for a report — shared by the graph, the reports
    registry, and the outcome/feedback records so they all join cleanly."""
    idea = report.get("idea_submitted", "")
    gen = report.get("generated_at", "")
    return hashlib.sha1(f"{idea}|{gen}".encode()).hexdigest()[:12]


# ── Pure extraction ──────────────────────────────────────────────────────────

def extract_graph_from_report(report: dict, disease_name: str = "",
                              user_id: Optional[int] = None) -> dict:
    """
    Turn a report dict into {"nodes": [...], "edges": [...]}.
    Nodes carry a stable `ref` (node_type::norm_key); edges reference src/dst by ref.
    Deterministic — no I/O.
    """
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def add_node(node_type: str, name: str, **attrs) -> Optional[str]:
        if not name or not normalize_key(name):
            return None
        ref = _node_ref(node_type, name)
        if ref not in nodes:
            nodes[ref] = {"ref": ref, "node_type": node_type, "name": name.strip(),
                          "attributes": {}}
        nodes[ref]["attributes"].update({k: v for k, v in attrs.items() if v not in (None, "")})
        return ref

    def add_edge(src: Optional[str], dst: Optional[str], edge_type: str,
                 confidence: float = 0.8, **attrs):
        if not src or not dst or src == dst:
            return
        edges.append({"src": src, "dst": dst, "edge_type": edge_type,
                      "confidence": confidence, "attributes": attrs})

    di = report.get("disease_intelligence") or {}
    disease = di.get("condition") or disease_name or report.get("idea_submitted", "")[:60]
    disease_ref = add_node("disease", disease, unmet_need=di.get("unmet_need_summary"))

    modality_ref = add_node("modality", report.get("product_type", "") or "other")

    # Report node — keyed by a stable hash of idea + generated_at so re-ingests merge.
    idea = report.get("idea_submitted", "")
    gen = report.get("generated_at", "")
    rid = report_id_for(report)
    cs = (report.get("commercialization_scores") or {}).get("commercialization_scores") or {}
    ms = report.get("market_sizing") or {}
    report_ref = add_node(
        "report", f"Report {rid}",
        idea=idea[:200],
        generated_at=gen,
        tam_usd=ms.get("total_addressable_market_usd"),
        overall_priority=cs.get("overall_priority"),
        recommendation=(report.get("commercialization_scores") or {}).get("recommendation"),
        expert=report.get("expert_name"),
    )

    add_edge(report_ref, disease_ref, "analyzes")
    add_edge(report_ref, modality_ref, "concerns")
    add_edge(modality_ref, disease_ref, "treats", confidence=0.6)

    # Regulatory pathway + designations
    rp = report.get("regulatory_pathway") or {}
    if rp.get("recommended_pathway"):
        path_ref = add_node("regulatory_pathway", rp["recommended_pathway"])
        add_edge(report_ref, path_ref, "recommended_pathway")
        for d in rp.get("designations", []) or []:
            if d.get("name"):
                desig_ref = add_node("fda_designation", d["name"], benefit=d.get("benefit"))
                add_edge(disease_ref, desig_ref, "eligible_for", confidence=0.7)

    # KOLs
    ma = report.get("market_access") or {}
    for kol in (ma.get("key_opinion_leaders") or [])[:10]:
        kol_ref = add_node("kol", kol if isinstance(kol, str) else kol.get("name", ""))
        add_edge(disease_ref, kol_ref, "has_kol", confidence=0.6)

    # PI profile
    if user_id is not None:
        pi_ref = add_node("pi_profile", f"PI {user_id}", user_id=user_id)
        add_edge(pi_ref, report_ref, "authored")
        add_edge(pi_ref, disease_ref, "focus_area", confidence=0.7)

    return {"nodes": list(nodes.values()), "edges": edges, "report_ref": report_ref,
            "disease_ref": disease_ref}


# ── Persistence ────────────────────────────────────────────────────────────────

async def init_world_model_graph():
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS wm_nodes (
                id            SERIAL PRIMARY KEY,
                node_type     TEXT NOT NULL,
                name          TEXT NOT NULL,
                norm_key      TEXT NOT NULL,
                attributes    JSONB DEFAULT '{}'::jsonb,
                mention_count INTEGER DEFAULT 1,
                first_seen    TIMESTAMPTZ DEFAULT NOW(),
                last_seen     TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (node_type, norm_key)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS wm_edges (
                id          SERIAL PRIMARY KEY,
                src_id      INTEGER REFERENCES wm_nodes(id) ON DELETE CASCADE,
                dst_id      INTEGER REFERENCES wm_nodes(id) ON DELETE CASCADE,
                edge_type   TEXT NOT NULL,
                attributes  JSONB DEFAULT '{}'::jsonb,
                confidence  REAL DEFAULT 0.8,
                source      TEXT,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (src_id, dst_id, edge_type)
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS wm_nodes_type_idx ON wm_nodes (node_type)")
        await conn.execute("CREATE INDEX IF NOT EXISTS wm_edges_src_idx ON wm_edges (src_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS wm_edges_dst_idx ON wm_edges (dst_id)")
    logger.info("world-model graph tables ready")


async def _upsert_node(conn, node_type: str, name: str, attributes: dict) -> int:
    import json
    norm = normalize_key(name)
    row = await conn.fetchrow("""
        INSERT INTO wm_nodes (node_type, name, norm_key, attributes)
        VALUES ($1, $2, $3, $4::jsonb)
        ON CONFLICT (node_type, norm_key) DO UPDATE
          SET mention_count = wm_nodes.mention_count + 1,
              last_seen = NOW(),
              attributes = wm_nodes.attributes || EXCLUDED.attributes
        RETURNING id
    """, node_type, name.strip(), norm, json.dumps(attributes or {}))
    return row["id"]


async def _upsert_edge(conn, src_id: int, dst_id: int, edge_type: str,
                       confidence: float, attributes: dict, source: str = "report"):
    import json
    await conn.execute("""
        INSERT INTO wm_edges (src_id, dst_id, edge_type, attributes, confidence, source)
        VALUES ($1, $2, $3, $4::jsonb, $5, $6)
        ON CONFLICT (src_id, dst_id, edge_type) DO UPDATE
          SET confidence = GREATEST(wm_edges.confidence, EXCLUDED.confidence),
              attributes = wm_edges.attributes || EXCLUDED.attributes
    """, src_id, dst_id, edge_type, json.dumps(attributes or {}), confidence, source)


async def ingest_report_to_graph(report: dict, disease_name: str = "",
                                 user_id: Optional[int] = None) -> Optional[int]:
    """Persist a report's extracted subgraph. Best-effort; never raises."""
    try:
        graph = extract_graph_from_report(report, disease_name, user_id)
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                ref_to_id: dict[str, int] = {}
                for n in graph["nodes"]:
                    ref_to_id[n["ref"]] = await _upsert_node(
                        conn, n["node_type"], n["name"], n["attributes"])
                for e in graph["edges"]:
                    src, dst = ref_to_id.get(e["src"]), ref_to_id.get(e["dst"])
                    if src and dst:
                        await _upsert_edge(conn, src, dst, e["edge_type"],
                                           e["confidence"], e["attributes"])

                # Portfolio linking: connect this report to prior reports for the
                # same disease (the basis for portfolio benchmarking, P7).
                disease_id = ref_to_id.get(graph["disease_ref"])
                report_id = ref_to_id.get(graph["report_ref"])
                if disease_id and report_id:
                    prior = await conn.fetch("""
                        SELECT e.src_id FROM wm_edges e
                        JOIN wm_nodes n ON n.id = e.src_id
                        WHERE e.dst_id = $1 AND e.edge_type = 'analyzes'
                          AND n.node_type = 'report' AND e.src_id <> $2
                        LIMIT 25
                    """, disease_id, report_id)
                    for p in prior:
                        await _upsert_edge(conn, report_id, p["src_id"],
                                           "same_indication_as", 0.7, {})
        logger.info("World-model graph: ingested report subgraph (%d nodes, %d edges)",
                    len(graph["nodes"]), len(graph["edges"]))
        return ref_to_id.get(graph["report_ref"])
    except Exception as e:
        logger.warning("ingest_report_to_graph failed (non-fatal): %s", e)
        return None


async def get_disease_subgraph(disease_name: str, limit: int = 60) -> dict:
    """Return the neighborhood of a disease node for the graph UI / API."""
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        norm = normalize_key(disease_name)
        async with pool.acquire() as conn:
            d = await conn.fetchrow(
                "SELECT id, name FROM wm_nodes WHERE node_type='disease' AND norm_key=$1", norm)
            if not d:
                return {"nodes": [], "edges": []}
            rows = await conn.fetch("""
                SELECT e.src_id, e.dst_id, e.edge_type, e.confidence,
                       s.name AS src_name, s.node_type AS src_type,
                       t.name AS dst_name, t.node_type AS dst_type
                FROM wm_edges e
                JOIN wm_nodes s ON s.id = e.src_id
                JOIN wm_nodes t ON t.id = e.dst_id
                WHERE e.src_id = $1 OR e.dst_id = $1
                ORDER BY e.confidence DESC LIMIT $2
            """, d["id"], limit)
            nodes, edges = {}, []
            for r in rows:
                nodes[r["src_id"]] = {"id": r["src_id"], "name": r["src_name"], "type": r["src_type"]}
                nodes[r["dst_id"]] = {"id": r["dst_id"], "name": r["dst_name"], "type": r["dst_type"]}
                edges.append({"src": r["src_id"], "dst": r["dst_id"],
                              "type": r["edge_type"], "confidence": r["confidence"]})
            return {"disease": d["name"], "nodes": list(nodes.values()), "edges": edges}
    except Exception as e:
        logger.warning("get_disease_subgraph failed: %s", e)
        return {"nodes": [], "edges": []}


async def load_graph_context(disease_name: str) -> str:
    """A compact text summary of accumulated graph knowledge for a disease, to
    inject into the next report (complements research_world_model)."""
    sub = await get_disease_subgraph(disease_name, limit=80)
    if not sub.get("nodes"):
        return ""
    by_type: dict[str, list[str]] = {}
    for n in sub["nodes"]:
        if n["type"] == "disease":
            continue
        by_type.setdefault(n["type"], []).append(n["name"])
    report_count = len(by_type.get("report", []))
    lines = [f"ACCUMULATED GRAPH KNOWLEDGE for {sub['disease']} "
             f"({report_count} prior report(s) on file):"]
    for t in ("modality", "regulatory_pathway", "fda_designation", "kol"):
        if by_type.get(t):
            label = t.replace("_", " ")
            lines.append(f"- known {label}s: {', '.join(sorted(set(by_type[t]))[:8])}")
    return "\n".join(lines) if len(lines) > 1 else ""
