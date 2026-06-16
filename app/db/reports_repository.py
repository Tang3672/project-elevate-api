"""
Reports Registry + Outcome/Feedback Store  (Sprint 7: P7 + P11 + P10-lite)
==========================================================================
Two responsibilities:

1. `reports` — a lightweight per-report metrics registry (report_id, disease,
   modality, commercialization priority, trust metrics, TAM). This is the
   backbone for portfolio benchmarking (percentile + comparables, P7) and the
   evaluation dashboard (P10), without re-running the full report.

2. `report_outcomes` — the brief's P11 feedback schema: what the user/TTO
   actually DID with each recommendation and how it turned out. This is the
   strongest long-term moat — Medlevate learns from real commercialization
   outcomes.

All writes are best-effort and never raise into the report path.
"""

import logging
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger(__name__)

VALID_ACTIONS  = {"accepted", "rejected", "edited", "ignored"}
VALID_OUTCOMES = {"patented", "licensed", "grant_funded", "spun_out",
                  "deprioritized", "investor_meeting", "company_formed", "pending"}


async def init_reports_tables():
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                report_id        TEXT PRIMARY KEY,
                user_id          INTEGER,
                institution_id   TEXT,
                disease_name     TEXT,
                modality         TEXT,
                idea             TEXT,
                overall_priority REAL,
                citation_support REAL,
                retrieval_coverage REAL,
                contradiction_count INTEGER,
                abstention_required BOOLEAN,
                tam_usd          DOUBLE PRECISION,
                scores           JSONB DEFAULT '{}'::jsonb,
                recommendation   TEXT,
                status           TEXT DEFAULT 'triaged',
                assigned_reviewer TEXT,
                next_action      TEXT,
                created_at       TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        # Idempotent column adds for already-deployed tables (TTO workflow, Sprint 5).
        for col, ddl in [
            ("scores", "JSONB DEFAULT '{}'::jsonb"), ("recommendation", "TEXT"),
            ("status", "TEXT DEFAULT 'triaged'"), ("assigned_reviewer", "TEXT"),
            ("next_action", "TEXT"),
        ]:
            await conn.execute(f"ALTER TABLE reports ADD COLUMN IF NOT EXISTS {col} {ddl}")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS report_outcomes (
                id               SERIAL PRIMARY KEY,
                report_id        TEXT,
                user_id          INTEGER,
                institution_id   TEXT,
                recommendation_id TEXT,
                user_action      TEXT,
                outcome          TEXT,
                outcome_date     DATE,
                notes            TEXT,
                used_for_training BOOLEAN DEFAULT TRUE,
                created_at       TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS reports_disease_idx ON reports (disease_name)")
        await conn.execute("CREATE INDEX IF NOT EXISTS reports_user_idx ON reports (user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS outcomes_report_idx ON report_outcomes (report_id)")
    logger.info("reports + report_outcomes tables ready")


async def save_report_metrics(report: dict, user_id: Optional[int] = None,
                              institution_id: Optional[str] = None) -> Optional[str]:
    """Persist a report's key metrics. Returns report_id. Best-effort."""
    try:
        from app.services.world_model_graph import report_id_for
        from app.db.database import get_pool
        rid = report_id_for(report)
        import json
        cs_block = report.get("commercialization_scores") or {}
        cs = cs_block.get("commercialization_scores") or {}
        recommendation = cs_block.get("recommendation")
        trust = report.get("trust") or {}
        ms = report.get("market_sizing") or {}
        di = report.get("disease_intelligence") or {}
        pool = await get_pool()
        async with pool.acquire() as conn:
            # status/assigned_reviewer/next_action are NOT in the UPDATE set, so a
            # re-run never clobbers a reviewer's manual workflow edits.
            await conn.execute("""
                INSERT INTO reports
                  (report_id, user_id, institution_id, disease_name, modality, idea,
                   overall_priority, citation_support, retrieval_coverage,
                   contradiction_count, abstention_required, tam_usd, scores,
                   recommendation, next_action)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb,$14,$15)
                ON CONFLICT (report_id) DO UPDATE SET
                   overall_priority = EXCLUDED.overall_priority,
                   citation_support = EXCLUDED.citation_support,
                   retrieval_coverage = EXCLUDED.retrieval_coverage,
                   contradiction_count = EXCLUDED.contradiction_count,
                   abstention_required = EXCLUDED.abstention_required,
                   scores = EXCLUDED.scores,
                   recommendation = EXCLUDED.recommendation
            """, rid, user_id, institution_id,
                (di.get("condition") or report.get("idea_submitted", "")[:60]),
                report.get("product_type"), report.get("idea_submitted", "")[:300],
                cs.get("overall_priority"), trust.get("citation_support_score"),
                trust.get("retrieval_coverage"), trust.get("contradiction_count"),
                bool(trust.get("abstention_required")),
                ms.get("total_addressable_market_usd"), json.dumps(cs),
                recommendation, recommendation)
        return rid
    except Exception as e:
        logger.warning("save_report_metrics failed (non-fatal): %s", e)
        return None


async def peer_reports(disease_name: str, modality: str = "",
                       exclude_report_id: str = "", user_id: Optional[int] = None,
                       institution_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Prior reports for the SAME owner (institution, else user) in the same disease/
    modality. Portfolio benchmarking must never compare across accounts — that both
    leaks other users' ideas and makes the "internal portfolio" meaningless."""
    if user_id is None and not institution_id:
        return []   # no owner scope -> no portfolio (don't fall back to a global pool)
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        if institution_id:
            owner_clause, owner_val = "institution_id = $5", institution_id
        else:
            owner_clause, owner_val = "user_id = $5", user_id
        async with pool.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT report_id, disease_name, modality, idea, overall_priority, tam_usd, created_at
                FROM reports
                WHERE report_id <> $1
                  AND (lower(disease_name) = lower($2) OR lower(modality) = lower($3))
                  AND {owner_clause}
                ORDER BY (lower(disease_name) = lower($2)) DESC, created_at DESC
                LIMIT $4
            """, exclude_report_id or "", disease_name or "", modality or "", limit, owner_val)
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("peer_reports failed: %s", e)
        return []


async def record_feedback(report_id: str, *, user_action: str = None,
                          outcome: str = None, recommendation_id: str = None,
                          notes: str = None, outcome_date: str = None,
                          user_id: int = None, institution_id: str = None,
                          used_for_training: bool = True) -> dict:
    """Record a P11 feedback/outcome event. Validates the enums."""
    if user_action and user_action not in VALID_ACTIONS:
        raise ValueError(f"user_action must be one of {sorted(VALID_ACTIONS)}")
    if outcome and outcome not in VALID_OUTCOMES:
        raise ValueError(f"outcome must be one of {sorted(VALID_OUTCOMES)}")
    _date = None
    if outcome_date:
        try:
            _date = date.fromisoformat(outcome_date)
        except ValueError:
            _date = None

    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO report_outcomes
              (report_id, user_id, institution_id, recommendation_id, user_action,
               outcome, outcome_date, notes, used_for_training)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            RETURNING id
        """, report_id, user_id, institution_id, recommendation_id, user_action,
            outcome, _date, notes, used_for_training)

    # Feed the outcome back into the world-model graph (P4 x P11): a real
    # institutional decision becomes a permanent node/edge.
    if outcome:
        try:
            await _link_outcome_to_graph(report_id, outcome, institution_id)
        except Exception as e:
            logger.debug("outcome->graph link failed (non-fatal): %s", e)

    return {"id": row["id"], "report_id": report_id,
            "user_action": user_action, "outcome": outcome}


async def _link_outcome_to_graph(report_id: str, outcome: str, institution_id: Optional[str]):
    """Create a tto_decision / licensing_outcome node linked to the report node."""
    from app.db.database import get_pool
    from app.services.world_model_graph import _upsert_node, _upsert_edge, normalize_key
    pool = await get_pool()
    async with pool.acquire() as conn:
        rep = await conn.fetchrow(
            "SELECT id FROM wm_nodes WHERE node_type='report' AND norm_key=$1",
            normalize_key(f"Report {report_id}"))
        if not rep:
            return
        node_type = "licensing_outcome" if outcome in ("licensed", "spun_out", "company_formed") else "tto_decision"
        async with conn.transaction():
            oid = await _upsert_node(conn, node_type, f"{outcome} · {report_id}",
                                     {"outcome": outcome, "institution_id": institution_id})
            await _upsert_edge(conn, rep["id"], oid, "institution_decision", 0.95, {})


async def list_outcomes(report_id: str = "", user_id: int = None, limit: int = 100) -> list[dict]:
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            if report_id:
                rows = await conn.fetch(
                    "SELECT * FROM report_outcomes WHERE report_id=$1 ORDER BY created_at DESC LIMIT $2",
                    report_id, limit)
            elif user_id is not None:
                rows = await conn.fetch(
                    "SELECT * FROM report_outcomes WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2",
                    user_id, limit)
            else:
                rows = await conn.fetch(
                    "SELECT * FROM report_outcomes ORDER BY created_at DESC LIMIT $1", limit)
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("list_outcomes failed: %s", e)
        return []


# ── TTO review queue / invention status tracking (Sprint 5) ─────────────────────

VALID_STATUSES = {"intake", "triaged", "under_review", "decided", "deprioritized"}


def _parse_scores(v) -> dict:
    import json
    if isinstance(v, dict):
        return v
    if isinstance(v, str) and v:
        try:
            return json.loads(v)
        except ValueError:
            return {}
    return {}


def _invention_row(r) -> dict:
    """Shape a reports row into a TTO dashboard record with the brief's columns."""
    sc = _parse_scores(r.get("scores"))
    return {
        "report_id": r["report_id"],
        "idea": r.get("idea"),
        "disease_name": r.get("disease_name"),
        "modality": r.get("modality"),
        "priority_score": r.get("overall_priority"),
        "market_opportunity_usd": r.get("tam_usd"),
        "regulatory_feasibility": sc.get("regulatory_feasibility"),
        "competitive_whitespace": sc.get("competitive_whitespace"),
        "funding_fit": sc.get("sbir_fit"),
        "licensing_fit": sc.get("licensing_likelihood"),
        "recommendation": r.get("recommendation"),
        "next_action": r.get("next_action"),
        "status": r.get("status") or "triaged",
        "assigned_reviewer": r.get("assigned_reviewer"),
        "created_at": r.get("created_at").isoformat() if r.get("created_at") else None,
    }


async def list_review_queue(institution_id: Optional[str] = None, status: str = "",
                            reviewer: str = "", limit: int = 200) -> list[dict]:
    """The TTO review queue: every invention disclosure with its triage scores,
    workflow status, assigned reviewer, and next action."""
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        clauses, args = [], []
        if status:
            args.append(status); clauses.append(f"status = ${len(args)}")
        if reviewer:
            args.append(reviewer); clauses.append(f"assigned_reviewer = ${len(args)}")
        if institution_id:
            args.append(institution_id); clauses.append(f"institution_id = ${len(args)}")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        args.append(limit)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM reports{where} ORDER BY "
                f"abstention_required ASC NULLS LAST, overall_priority DESC NULLS LAST, "
                f"created_at DESC LIMIT ${len(args)}", *args)
            return [_invention_row(dict(r)) for r in rows]
    except Exception as e:
        logger.warning("list_review_queue failed: %s", e)
        return []


async def update_review(report_id: str, *, status: str = None,
                        assigned_reviewer: str = None, next_action: str = None) -> dict:
    """Update an invention's workflow fields. Validates status."""
    if status and status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {sorted(VALID_STATUSES)}")
    sets, args = [], []
    for col, val in (("status", status), ("assigned_reviewer", assigned_reviewer),
                     ("next_action", next_action)):
        if val is not None:
            args.append(val); sets.append(f"{col} = ${len(args)}")
    if not sets:
        return {"report_id": report_id, "updated": False}
    args.append(report_id)
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE reports SET {', '.join(sets)} WHERE report_id = ${len(args)}", *args)
    return {"report_id": report_id, "updated": True, "status": status,
            "assigned_reviewer": assigned_reviewer, "next_action": next_action}


async def get_invention(report_id: str) -> dict:
    """A single invention's full TTO record + decision history."""
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            r = await conn.fetchrow("SELECT * FROM reports WHERE report_id = $1", report_id)
        if not r:
            return {}
        rec = _invention_row(dict(r))
        rec["decision_history"] = await list_outcomes(report_id=report_id)
        return rec
    except Exception as e:
        logger.warning("get_invention failed: %s", e)
        return {}


async def eval_metrics(institution_id: Optional[str] = None) -> dict:
    """Aggregate metrics for the internal evaluation dashboard (P10)."""
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            r = await conn.fetchrow("""
                SELECT COUNT(*) AS n,
                       AVG(citation_support)  AS avg_citation_support,
                       AVG(retrieval_coverage) AS avg_coverage,
                       AVG(overall_priority)  AS avg_priority,
                       AVG(CASE WHEN abstention_required THEN 1.0 ELSE 0.0 END) AS abstention_rate
                FROM reports
            """)
            actions = await conn.fetch(
                "SELECT user_action, COUNT(*) AS c FROM report_outcomes WHERE user_action IS NOT NULL GROUP BY user_action")
            outcomes = await conn.fetch(
                "SELECT outcome, COUNT(*) AS c FROM report_outcomes WHERE outcome IS NOT NULL GROUP BY outcome")
            action_counts = {a["user_action"]: a["c"] for a in actions}
            total_actions = sum(action_counts.values()) or 0
            accepted = action_counts.get("accepted", 0)
            return {
                "report_count": r["n"] or 0,
                "avg_citation_support": round(r["avg_citation_support"] or 0, 3),
                "avg_retrieval_coverage": round(r["avg_coverage"] or 0, 3),
                "avg_overall_priority": round(r["avg_priority"] or 0, 3),
                "abstention_rate": round(r["abstention_rate"] or 0, 3),
                "recommendation_acceptance_rate": round(accepted / total_actions, 3) if total_actions else None,
                "user_action_counts": action_counts,
                "outcome_counts": {o["outcome"]: o["c"] for o in outcomes},
                "generated_at": datetime.utcnow().isoformat(),
            }
    except Exception as e:
        logger.warning("eval_metrics failed: %s", e)
        return {"report_count": 0, "error": str(e)}
