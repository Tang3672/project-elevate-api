"""
Canonical entity schema — hub-and-spoke PostgreSQL design.

Tables:
  disease          — keyed on MONDO ID (primary disease join key)
  drug             — keyed on RxCUI + ChEMBL ID
  xref_map         — source_id → canonical_id crosswalk with provenance
  disease_burden   — burden metrics from commercial-safe sources (WHO GHO, CDC)
  etl_run          — ledger of every ingestion job (deduplication + freshness)

All raw API payloads land in JSONB `raw_*` staging tables first, then ETL
normalizes into canonical tables via idempotent upserts.
"""

from app.db.database import get_pool


async def init_ontology_tables() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:

        # ── Canonical disease entity ───────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS disease (
                mondo_id        VARCHAR(20)  PRIMARY KEY,   -- e.g. 'MONDO:0005148'
                label           TEXT         NOT NULL,
                synonyms        TEXT[]       DEFAULT '{}',
                definition      TEXT,
                -- Cross-reference IDs (denormalized for fast lookup)
                icd10_ids       TEXT[]       DEFAULT '{}',
                icd11_ids       TEXT[]       DEFAULT '{}',
                mesh_ids        TEXT[]       DEFAULT '{}',
                omim_ids        TEXT[]       DEFAULT '{}',
                orphanet_ids    TEXT[]       DEFAULT '{}',
                ncit_ids        TEXT[]       DEFAULT '{}',
                -- Hierarchy
                parent_mondo_id VARCHAR(20),
                therapeutic_area VARCHAR(50), -- our TA classification
                is_rare         BOOLEAN      DEFAULT FALSE,
                -- Metadata
                created_at      TIMESTAMPTZ  DEFAULT NOW(),
                updated_at      TIMESTAMPTZ  DEFAULT NOW()
            );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS disease_label_idx ON disease (lower(label));")
        await conn.execute("CREATE INDEX IF NOT EXISTS disease_ta_idx ON disease (therapeutic_area);")
        await conn.execute("CREATE INDEX IF NOT EXISTS disease_mesh_idx ON disease USING gin(mesh_ids);")
        await conn.execute("CREATE INDEX IF NOT EXISTS disease_icd10_idx ON disease USING gin(icd10_ids);")

        # ── Canonical drug entity ──────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS drug (
                rxcui           VARCHAR(20)  PRIMARY KEY,   -- RxNorm CUI
                chembl_id       VARCHAR(20),
                label           TEXT         NOT NULL,
                generic_name    TEXT,
                brand_names     TEXT[]       DEFAULT '{}',
                drug_class      TEXT,                       -- ATC L1
                atc_codes       TEXT[]       DEFAULT '{}',
                mechanism       TEXT,
                -- Metadata
                created_at      TIMESTAMPTZ  DEFAULT NOW(),
                updated_at      TIMESTAMPTZ  DEFAULT NOW()
            );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS drug_label_idx ON drug (lower(label));")
        await conn.execute("CREATE INDEX IF NOT EXISTS drug_chembl_idx ON drug (chembl_id);")

        # ── Cross-reference map ────────────────────────────────────────────────
        # Every source_id → canonical_id mapping stored with full provenance.
        # method: 'exact', 'normalized', 'rxnorm_approx', 'embedding', 'manual'
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS xref_map (
                id              SERIAL       PRIMARY KEY,
                source_name     VARCHAR(50)  NOT NULL,  -- 'clinicaltrials', 'openfda', 'nih_reporter'
                source_id       TEXT         NOT NULL,  -- raw ID from that source
                canonical_type  VARCHAR(10)  NOT NULL,  -- 'disease' | 'drug'
                canonical_id    TEXT         NOT NULL,  -- MONDO ID or RxCUI
                canonical_label TEXT,
                method          VARCHAR(30)  NOT NULL,  -- how we resolved it
                confidence      FLOAT        DEFAULT 1.0,
                curated         BOOLEAN      DEFAULT FALSE,
                created_at      TIMESTAMPTZ  DEFAULT NOW(),
                UNIQUE (source_name, source_id, canonical_type)
            );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS xref_source_idx ON xref_map (source_name, source_id);")
        await conn.execute("CREATE INDEX IF NOT EXISTS xref_canonical_idx ON xref_map (canonical_id);")

        # ── Disease burden ─────────────────────────────────────────────────────
        # Commercial-safe burden metrics from WHO GHO, CDC WONDER, CDC PLACES.
        # GBD data MUST NOT be inserted here (commercial_use_restricted = true).
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS disease_burden (
                id              SERIAL       PRIMARY KEY,
                mondo_id        VARCHAR(20)  REFERENCES disease(mondo_id) ON DELETE CASCADE,
                disease_label   TEXT         NOT NULL,  -- denormalized for unresolved diseases
                source_name     VARCHAR(50)  NOT NULL,  -- 'who_gho', 'cdc_wonder', 'cdc_places'
                source_code     VARCHAR(50),            -- WHO GHO indicator code, etc.
                commercial_safe BOOLEAN      NOT NULL DEFAULT TRUE,
                metric          VARCHAR(100) NOT NULL,  -- 'dalys_per_100k', 'mortality_per_100k', 'prevalence'
                value           FLOAT        NOT NULL,
                unit            TEXT,
                location        VARCHAR(100) DEFAULT 'United States',
                year            INTEGER,
                age_group       TEXT         DEFAULT 'All ages',
                sex             TEXT         DEFAULT 'Both sexes',
                raw_data        JSONB,
                fetched_at      TIMESTAMPTZ  DEFAULT NOW(),
                UNIQUE (mondo_id, source_name, metric, location, year, age_group, sex)
            );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS burden_mondo_idx ON disease_burden (mondo_id);")
        await conn.execute("CREATE INDEX IF NOT EXISTS burden_source_idx ON disease_burden (source_name);")
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS burden_commercial_idx
            ON disease_burden (commercial_safe)
            WHERE commercial_safe = TRUE;
        """)

        # ── Raw staging tables ─────────────────────────────────────────────────
        # Land verbatim API payloads here first; ETL normalizes into canonical tables.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS raw_ingest (
                id              SERIAL       PRIMARY KEY,
                source_name     VARCHAR(50)  NOT NULL,
                source_record_id TEXT,
                payload         JSONB        NOT NULL,
                payload_hash    VARCHAR(64),            -- SHA-256 for dedup
                fetched_at      TIMESTAMPTZ  DEFAULT NOW(),
                normalized      BOOLEAN      DEFAULT FALSE,
                UNIQUE (source_name, payload_hash)
            );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS raw_source_idx ON raw_ingest (source_name, normalized);")

        # ── ETL run ledger ─────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS etl_run (
                id              SERIAL       PRIMARY KEY,
                source_name     VARCHAR(50)  NOT NULL,
                job_name        TEXT         NOT NULL,
                status          VARCHAR(20)  NOT NULL DEFAULT 'running',  -- running/completed/failed
                rows_fetched    INTEGER      DEFAULT 0,
                rows_upserted   INTEGER      DEFAULT 0,
                rows_skipped    INTEGER      DEFAULT 0,
                error_message   TEXT,
                started_at      TIMESTAMPTZ  DEFAULT NOW(),
                completed_at    TIMESTAMPTZ
            );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS etl_source_idx ON etl_run (source_name, started_at DESC);")

    print("✅ Ontology/canonical tables initialized")
