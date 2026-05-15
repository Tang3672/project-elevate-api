"""
PI Institutional Memory Service
================================
Extracts and stores key facts from every report a PI saves.
Injects accumulated memory into future report generation.

This is the core moat: after 3+ reports, Project Elevate knows a PI's
competitive landscape, regulatory strategy, and disease area better than
any fresh ChatGPT session ever could.
"""

import json
import logging
from typing import Optional
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
HAIKU_MODEL = "claude-haiku-4-5-20251001"
TIMEOUT = 30.0


# ══════════════════════════════════════════════════════════════════════════════
# DB INIT
# ══════════════════════════════════════════════════════════════════════════════

async def init_pi_memory_table():
    """Create pi_memory table if it doesn't exist."""
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pi_memory (
                id              SERIAL PRIMARY KEY,
                user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                disease_area    VARCHAR(200),
                product_type    VARCHAR(100),
                regulatory_strategy TEXT,
                key_competitors TEXT[],
                tam_estimate    BIGINT,
                development_stage VARCHAR(100),
                prior_ideas     TEXT[],
                report_count    INTEGER DEFAULT 1,
                last_updated    TIMESTAMPTZ DEFAULT NOW(),
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(user_id, disease_area)
            )
        """)
        logger.info("✅ PI memory table ready")


# ══════════════════════════════════════════════════════════════════════════════
# EXTRACT MEMORY FROM REPORT
# ══════════════════════════════════════════════════════════════════════════════

async def extract_and_store_memory(user_id: int, idea: str, report_data: dict):
    """
    After a report is saved, extract key facts and upsert into pi_memory.
    Runs async in background — does not block report generation.
    """
    try:
        facts = await _extract_facts(idea, report_data)
        if facts:
            await _upsert_memory(user_id, facts)
            logger.info(f"✅ PI memory updated for user {user_id}: {facts.get('disease_area')}")
    except Exception as e:
        logger.warning(f"PI memory extraction failed (non-fatal): {e}")


async def _extract_facts(idea: str, report_data: dict) -> Optional[dict]:
    """Use Haiku to extract structured facts from a report."""
    
    # Pull key fields from report
    condition = report_data.get("disease_intelligence", {}).get("condition", "")
    tam = report_data.get("market_sizing", {}).get("total_addressable_market_usd", 0)
    competitors = []
    comp_landscape = report_data.get("competitive_landscape", {})
    if isinstance(comp_landscape, dict):
        for key in ["direct_competitors", "competitors", "approved_drugs"]:
            val = comp_landscape.get(key, [])
            if isinstance(val, list):
                competitors = [str(c.get("name", c)) if isinstance(c, dict) else str(c) for c in val[:5]]
                break
    
    reg_pathway = report_data.get("regulatory_pathway", {})
    designations = reg_pathway.get("special_designations", [])
    if isinstance(designations, list):
        reg_strategy = ", ".join([d.get("name", str(d)) if isinstance(d, dict) else str(d) for d in designations[:3]])
    else:
        reg_strategy = str(designations)

    prompt = f"""Extract key facts from this biotech PI report. Return ONLY valid JSON, no other text.

PI's idea: {idea[:500]}
Disease/condition: {condition}
TAM estimate: ${tam:,} if tam else 'unknown'
Key competitors identified: {competitors}
Regulatory strategy: {reg_strategy}

Return this exact JSON structure:
{{
  "disease_area": "specific disease name",
  "product_type": "drug|biologic|device|diagnostic|digital_health",
  "regulatory_strategy": "key designations and pathway in one sentence",
  "key_competitors": ["competitor1", "competitor2"],
  "tam_estimate": 000000000,
  "development_stage": "preclinical|phase1|phase2|phase3|approved",
  "summary": "one sentence describing what this PI is building"
}}"""

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": HAIKU_MODEL,
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}]
            }
        )
        data = r.json()
        text = data["content"][0]["text"].strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())


async def _upsert_memory(user_id: int, facts: dict):
    """Insert or update PI memory for this user+disease combination."""
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO pi_memory 
                (user_id, disease_area, product_type, regulatory_strategy,
                 key_competitors, tam_estimate, development_stage, report_count, last_updated)
            VALUES ($1, $2, $3, $4, $5, $6, $7, 1, NOW())
            ON CONFLICT (user_id, disease_area) DO UPDATE SET
                regulatory_strategy = EXCLUDED.regulatory_strategy,
                key_competitors     = EXCLUDED.key_competitors,
                tam_estimate        = EXCLUDED.tam_estimate,
                development_stage   = EXCLUDED.development_stage,
                report_count        = pi_memory.report_count + 1,
                last_updated        = NOW()
        """,
            user_id,
            facts.get("disease_area", "unknown"),
            facts.get("product_type", "other"),
            facts.get("regulatory_strategy", ""),
            facts.get("key_competitors", []),
            int(facts.get("tam_estimate", 0) or 0),
            facts.get("development_stage", "preclinical"),
        )


# ══════════════════════════════════════════════════════════════════════════════
# RETRIEVE MEMORY FOR REPORT GENERATION
# ══════════════════════════════════════════════════════════════════════════════

async def get_pi_memory_context(user_id: int) -> str:
    """
    Retrieve accumulated PI memory and format it as context for report generation.
    Returns empty string if no memory exists (first-time PI).
    """
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT disease_area, product_type, regulatory_strategy,
                       key_competitors, tam_estimate, development_stage,
                       report_count, last_updated
                FROM pi_memory
                WHERE user_id = $1
                ORDER BY last_updated DESC
                LIMIT 5
            """, user_id)
        
        if not rows:
            return ""
        
        memories = [dict(r) for r in rows]
        
        lines = ["[PI INSTITUTIONAL MEMORY — use this to personalize the report]"]
        lines.append(f"This PI has generated {sum(m['report_count'] for m in memories)} reports on Project Elevate.")
        lines.append("Their research history:")
        
        for m in memories:
            competitors = m.get("key_competitors") or []
            tam = m.get("tam_estimate") or 0
            lines.append(
                f"- {m['disease_area']} ({m['product_type']}): "
                f"TAM ~${tam/1e6:.0f}M, "
                f"stage={m['development_stage']}, "
                f"competitors=[{', '.join(competitors[:3])}], "
                f"regulatory={m['regulatory_strategy'][:100]}"
            )
        
        lines.append("Use this history to: avoid repeating basics they already know, "
                     "flag if their new idea overlaps with prior research, "
                     "note if competitive landscape has changed since their last report.")
        
        return "\n".join(lines)
    
    except Exception as e:
        logger.warning(f"Could not retrieve PI memory: {e}")
        return ""
