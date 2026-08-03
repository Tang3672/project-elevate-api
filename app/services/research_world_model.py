"""
Research World Model — persistent structured knowledge across sessions
======================================================================
This is the core architectural innovation from Edison Scientific's Kosmos:
a structured database of entities, relationships, and open questions that
PERSISTS across report runs and accumulates knowledge over time.

Unlike RAG/vector search (which retrieves from a static corpus), the world
model WRITES new knowledge after every report run and READS prior knowledge
at the start of the next run for the same disease. The system gets smarter
with each report.

Edison's implementation:
  - Entities: genes, proteins, companies, people, concepts
  - Relationships: Company A licensed Gene X from University B
  - Experimental results: Drug X showed 80% efficacy in model Y
  - Open questions: Does mechanism X work in patient subtype Z?
  - Updated after every analysis cycle, survives context window limits

Our implementation:
  - Per-disease structured cache of key intelligence facts
  - Survives across user sessions and report runs
  - Each fact has: type, content, source, confidence, expiry
  - Loaded as "PRIOR RESEARCH CONTEXT" at the top of the next report
  - New facts extracted from each completed report and stored back

Table: research_world_model
  disease_name        TEXT (normalized lowercase, indexed)
  entity_type         TEXT (company | drug | trial | finding | open_question | investor | market_fact)
  entity_name         TEXT (the named entity, e.g. "Pfizer", "NCT12345", "ceftazidime-avibactam")
  fact                TEXT (the specific fact/relationship/finding)
  source              TEXT (PMID, NCT#, SEC filing, etc.)
  confidence          REAL (0.0-1.0)
  created_at          TIMESTAMPTZ
  expires_at          TIMESTAMPTZ (facts expire after 90 days to stay fresh)
"""

import logging
from typing import Optional, List
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_FACT_EXPIRY_DAYS = 90  # world model facts expire after 90 days


async def init_world_model_table():
    """Create the research_world_model table if it doesn't exist.

    H-03: user_id column is REQUIRED — all reads/writes are scoped by it.
    Facts without a user_id are never surfaced to any user's report.
    """
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS research_world_model (
                id              SERIAL PRIMARY KEY,
                user_id         TEXT NOT NULL DEFAULT '__unscoped__',
                disease_name    TEXT NOT NULL,
                entity_type     TEXT NOT NULL,
                entity_name     TEXT,
                fact            TEXT NOT NULL,
                source          TEXT,
                confidence      REAL DEFAULT 0.8,
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                expires_at      TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '90 days')
            )
        """)
        # H-03: add user_id column to existing tables (idempotent migration)
        await conn.execute("""
            ALTER TABLE research_world_model
            ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT '__unscoped__'
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS rwm_disease_idx ON research_world_model (disease_name)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS rwm_expiry_idx ON research_world_model (expires_at)
        """)
        # Composite index so user-scoped reads are fast
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS rwm_user_disease_idx
            ON research_world_model (user_id, disease_name)
        """)
    logger.info("research_world_model table ready (H-03: user_id-scoped)")


async def load_world_model(disease_name: str, user_id: Optional[str] = None) -> str:
    """
    Load prior research context for a disease from the world model.
    Returns a formatted string to inject at the top of the next report.
    Empty string if no prior knowledge.

    H-03: user_id MUST be provided and is enforced as a query filter.
    Never returns facts belonging to a different user. If user_id is None,
    returns empty string (no cross-user reads, ever).
    """
    if not user_id:
        # H-03: no user_id → no cross-user reads. Return empty.
        return ""
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT entity_type, entity_name, fact, source, confidence
                FROM research_world_model
                WHERE lower(disease_name) = lower($1)
                  AND user_id = $2
                  AND expires_at > NOW()
                ORDER BY confidence DESC, created_at DESC
                LIMIT 40
            """, disease_name, user_id)

        if not rows:
            return ""

        by_type: dict[str, list] = {}
        for row in rows:
            t = row["entity_type"]
            by_type.setdefault(t, []).append(row)

        lines = [
            "=== PRIOR RESEARCH CONTEXT (from previous analyses of this disease) ===",
            "The system has analyzed this disease area before. Use this prior knowledge",
            "as context — it complements but does not replace the fresh data fetched above.",
            "",
        ]

        type_labels = {
            "company":       "COMPETING COMPANIES IDENTIFIED",
            "drug":          "KEY DRUGS / PROGRAMS IN THIS SPACE",
            "trial":         "CLINICAL TRIALS PREVIOUSLY IDENTIFIED",
            "finding":       "KEY RESEARCH FINDINGS",
            "open_question": "OPEN RESEARCH QUESTIONS (WHITE SPACE)",
            "market_fact":   "MARKET INTELLIGENCE",
            "investor":      "INVESTORS ACTIVE IN THIS SPACE",
        }

        for entity_type, label in type_labels.items():
            entries = by_type.get(entity_type, [])
            if not entries:
                continue
            lines.append(f"{label}:")
            for e in entries[:6]:
                src = f" [{e['source']}]" if e.get("source") else ""
                name = f" ({e['entity_name']})" if e.get("entity_name") else ""
                lines.append(f"  • {e['fact']}{name}{src}")
            lines.append("")

        lines.append("=== END PRIOR RESEARCH CONTEXT ===")
        logger.info("World model loaded: %d facts for '%s'", len(rows), disease_name)
        return "\n".join(lines)

    except Exception as e:
        logger.warning("World model load failed (non-fatal): %s", e)
        return ""


async def update_world_model(
    disease_name: str,
    report_data: dict,
    pub_data: dict = None,
    ci_data: dict = None,
    user_id: Optional[str] = None,
):
    """
    After a report is generated, extract key entities and facts and write them
    to the world model for use in ONLY THIS USER's future reports on the same disease.

    H-03: user_id MUST be provided. Facts without a user_id are tagged
    '__unscoped__' and are never returned to any real user via load_world_model.
    """
    _uid = user_id or "__unscoped__"
    try:
        facts = _extract_facts_from_report(disease_name, report_data, pub_data, ci_data)
        if not facts:
            return

        from app.db.database import get_pool
        pool = await get_pool()
        expires = datetime.now(timezone.utc) + timedelta(days=_FACT_EXPIRY_DAYS)

        async with pool.acquire() as conn:
            for fact in facts:
                # H-03: include user_id in every insert
                await conn.execute("""
                    INSERT INTO research_world_model
                        (user_id, disease_name, entity_type, entity_name, fact, source, confidence, expires_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT DO NOTHING
                """,
                    _uid,
                    disease_name.lower(),
                    fact["entity_type"],
                    fact.get("entity_name"),
                    fact["fact"][:500],
                    fact.get("source"),
                    fact.get("confidence", 0.8),
                    expires,
                )

        logger.info("World model updated: %d facts stored for '%s'", len(facts), disease_name)

    except Exception as e:
        logger.warning("World model update failed (non-fatal): %s", e)


def _extract_facts_from_report(
    disease_name: str,
    report_data: dict,
    pub_data: dict = None,
    ci_data: dict = None,
) -> list[dict]:
    """Extract structured facts from report data for world model storage."""
    facts = []

    # Extract competing companies from CI data
    if ci_data:
        trials = ci_data.get("competitor_trials", {}).get("trials", [])
        for t in trials[:10]:
            sponsor = t.get("sponsor", "")
            nct = t.get("nct_id", "")
            phase = t.get("phase", "")
            if sponsor:
                facts.append({
                    "entity_type": "company",
                    "entity_name": sponsor,
                    "fact": f"{sponsor} has a {phase} trial for {disease_name}",
                    "source": nct,
                    "confidence": 0.95,
                })
            if nct:
                facts.append({
                    "entity_type": "trial",
                    "entity_name": nct,
                    "fact": f"{nct}: {phase} trial by {sponsor} for {disease_name}",
                    "source": nct,
                    "confidence": 0.95,
                })

    # Extract key market facts from report
    if report_data:
        # Market size
        tam = report_data.get("tam") or report_data.get("total_addressable_market")
        sam = report_data.get("sam") or report_data.get("serviceable_addressable_market")
        if tam:
            facts.append({
                "entity_type": "market_fact",
                "entity_name": None,
                "fact": f"TAM for {disease_name}: {tam}",
                "source": "Medlevate market analysis",
                "confidence": 0.75,
            })
        if sam:
            facts.append({
                "entity_type": "market_fact",
                "entity_name": None,
                "fact": f"SAM for {disease_name}: {sam}",
                "source": "Medlevate market analysis",
                "confidence": 0.75,
            })

        # Regulatory pathway
        reg = (report_data.get("regulatory") or {})
        pathway = reg.get("pathway") or reg.get("recommended_pathway")
        if pathway:
            facts.append({
                "entity_type": "market_fact",
                "entity_name": None,
                "fact": f"Regulatory pathway for {disease_name}: {pathway}",
                "source": "Medlevate regulatory analysis",
                "confidence": 0.80,
            })

    # Extract findings from PubMed papers
    if pub_data:
        papers = pub_data.get("publications", [])[:5]
        for p in papers:
            title = p.get("title", "")[:120]
            pmid = p.get("pmid", "")
            year = p.get("year", "")
            if title and pmid:
                facts.append({
                    "entity_type": "finding",
                    "entity_name": None,
                    "fact": f"{title} ({p.get('authors','?')}, {year})",
                    "source": f"PMID {pmid}",
                    "confidence": 0.90,
                })

    return facts
