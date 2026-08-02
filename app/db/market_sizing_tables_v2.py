"""
Market Sizing Tables v2  (Build Spec v5, Part A)
=================================================
Seven data-layer tables that back the professional market-sizing engine:
  epi_table           — epidemiology by disease/source (commercial-safe only)
  patient_flow_model  — per-disease treatment funnel (the core proprietary asset)
  indication_sequence — narrow-approval → label-expansion rules
  pricing_ref         — price/reimbursement references per product-type/disease
  assumption_provenance — every assumption's source, confidence, calibration status

adoption_benchmark and monetization_model are loaded from JSON (static config);
no DB table needed.

GBD rows are stored but FLAGGED commercial_ok=false and excluded from all
commercial output paths. Only CDC/WHO-GHO/SEER-derived rows flow through.
"""

import logging

logger = logging.getLogger(__name__)


async def init_market_sizing_tables_v2():
    """Create all v5 market-sizing tables if they don't exist."""
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:

        # ── epi_table ──────────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS epi_table (
                id              SERIAL PRIMARY KEY,
                disease_name    TEXT    NOT NULL,
                disease_mondo_id TEXT,
                geography       TEXT    NOT NULL DEFAULT 'US',
                metric          TEXT    NOT NULL,   -- 'incidence_annual' | 'prevalence' | 'mortality_annual'
                value           BIGINT  NOT NULL,
                value_low       BIGINT,
                value_high      BIGINT,
                source_id       TEXT    NOT NULL,   -- references data_sources.json id
                source_name     TEXT,
                commercial_ok   BOOLEAN NOT NULL DEFAULT TRUE,  -- FALSE = GBD/non-commercial; never flows to reports
                year            INTEGER,
                age_group       TEXT    DEFAULT 'All ages',
                sex             TEXT    DEFAULT 'Both',
                notes           TEXT,
                data_quality    TEXT    DEFAULT 'seed',
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (disease_name, geography, metric, source_id, year, age_group, sex)
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS epi_disease_idx ON epi_table (disease_name)")
        await conn.execute("CREATE INDEX IF NOT EXISTS epi_commercial_idx ON epi_table (commercial_ok) WHERE commercial_ok = TRUE")

        # ── patient_flow_model ────────────────────────────────────────────────
        # The bottom-up epidemiology funnel: disease → treated segment.
        # 'treated_segment' and 'line_of_therapy' steps carry rate=null —
        # the engine fills these from the product description + segment resolver.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS patient_flow_model (
                id                  SERIAL PRIMARY KEY,
                disease_name        TEXT    NOT NULL,
                disease_mondo_id    TEXT,
                geography           TEXT    NOT NULL DEFAULT 'US',
                product_type_hint   TEXT,   -- NULL = applies to all modalities
                funnel              JSONB   NOT NULL DEFAULT '[]',
                persistency_months  INTEGER DEFAULT 12,
                persistency_note    TEXT,
                data_quality        TEXT    DEFAULT 'seed',
                source_type         TEXT    DEFAULT 'literature',
                created_at          TIMESTAMPTZ DEFAULT NOW(),
                updated_at          TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (disease_name, geography, product_type_hint)
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS pfm_disease_idx ON patient_flow_model (disease_name)")

        # ── indication_sequence ───────────────────────────────────────────────
        # Encodes narrow-approval → label-expansion. The engine always presents
        # initial_indication market as base case; expansion is labeled contingent.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS indication_sequence (
                id                  SERIAL PRIMARY KEY,
                disease_name        TEXT    NOT NULL,
                disease_mondo_id    TEXT,
                product_type_hint   TEXT,
                initial_label       TEXT,
                initial_fraction    NUMERIC NOT NULL,   -- fraction of disease population
                initial_source_id   TEXT,
                initial_confidence  TEXT    DEFAULT 'low',
                expansion_path      JSONB   DEFAULT '[]',
                rule_note           TEXT,
                data_quality        TEXT    DEFAULT 'seed',
                created_at          TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (disease_name, product_type_hint)
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS is_disease_idx ON indication_sequence (disease_name)")

        # ── pricing_ref ────────────────────────────────────────────────────────
        # Per-product-type price/reimbursement anchors.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pricing_ref (
                id                  SERIAL PRIMARY KEY,
                disease_name        TEXT,
                product_type        TEXT    NOT NULL,
                price_type          TEXT    NOT NULL,   -- 'wac' | 'net' | 'procedure_reimbursement' | 'site_license' | 'per_test'
                price_usd           NUMERIC NOT NULL,
                net_to_wac_ratio    NUMERIC DEFAULT 0.55,
                source_id           TEXT,
                source_name         TEXT,
                comparator_product  TEXT,   -- e.g. "Keytruda (pembrolizumab)"
                year                INTEGER,
                confidence          TEXT    DEFAULT 'medium',
                notes               TEXT,
                created_at          TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (disease_name, product_type, price_type, source_id)
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS pr_disease_idx ON pricing_ref (disease_name)")
        await conn.execute("CREATE INDEX IF NOT EXISTS pr_product_type_idx ON pricing_ref (product_type)")

        # ── assumption_provenance ─────────────────────────────────────────────
        # Every assumption in every market-sizing run: source, confidence, impact.
        # Drives the "verify with expert" output and calibration over time.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS assumption_provenance (
                id              SERIAL PRIMARY KEY,
                run_id          TEXT,   -- links to market_sizing_runs.id (nullable for seed)
                disease_name    TEXT,
                field_name      TEXT    NOT NULL,   -- which assumption (e.g. 'treated_segment_rate')
                value           TEXT,               -- the actual value used
                source_id       TEXT,               -- data_sources.json id
                source_type     TEXT    NOT NULL,   -- 'public_dataset'|'literature'|'analog'|'analyst_estimate'|'llm_inference'|'expert_verified'
                confidence      TEXT    NOT NULL,   -- 'high'|'medium'|'low'
                impact          TEXT,               -- 'high'|'medium'|'low' (effect on final TAM)
                swing_estimate  TEXT,               -- e.g. "could change TAM 2-3x if wrong"
                expert_question TEXT,               -- the specific question to ask a domain expert
                calibrated      BOOLEAN DEFAULT FALSE,
                created_at      TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS ap_run_idx ON assumption_provenance (run_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS ap_disease_idx ON assumption_provenance (disease_name)")
        await conn.execute("CREATE INDEX IF NOT EXISTS ap_confidence_idx ON assumption_provenance (confidence, impact)")

    logger.info("market_sizing_tables_v2 (epi_table / patient_flow_model / indication_sequence / pricing_ref / assumption_provenance) ready")
