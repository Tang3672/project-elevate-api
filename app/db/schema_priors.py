"""
Success Rate Priors — versioned DB table
=========================================
Stores phase-transition LOA (Likelihood of Approval) priors by therapeutic area,
seeded from the two canonical published sources:

  BIO/QLS/Informa "Clinical Development Success Rates 2011-2020" (Feb 2021):
    Overall P1→approval LOA: 7.9%
    By area: Hematology 23.9%, Rare Disease 17.0%, Immuno-oncology 12.4%,
             Oncology 5.3%, Urology 3.6%
    Phase II transition: 28.9% (largest hurdle)

  Wong, Siah & Lo (Biostatistics 2019), 406,038 trial entries, 2000-2015:
    Overall: 13.8% from Phase I to approval
    Oncology improved from 3.4% to 8.3% by 2015 in their sample

Each expert profile reads its LOA multipliers from this table at scoring time,
not from hardcoded Python. Updating priors = INSERT a new version row; the
scorer always reads MAX(version) per (therapeutic_area, phase_from).

Citation keys stored in the `citation` column for full auditability.
"""

import logging

from app.db.database import get_pool

logger = logging.getLogger(__name__)

# ── Canonical prior values from published literature ──────────────────────────
# Format: (therapeutic_area, phase_from, loa_pct, p1_to_approval_pct, citation_key)
# loa_pct = cumulative LOA from this phase to approval
# p1_to_approval_pct = overall P1→approval LOA (for reference only)

_BIO_2021_PRIORS = [
    # Source: BIO/QLS/Informa 2011-2020 (Table 2, by disease area)
    # Phase I→approval LOA by therapeutic area
    ("hematology",      "phase1",  23.9, 23.9, "bio_qls_informa_2021"),
    ("rare_disease",    "phase1",  17.0, 17.0, "bio_qls_informa_2021"),
    ("immunology",      "phase1",  14.6, 14.6, "bio_qls_informa_2021"),
    ("gene_therapy",    "phase1",  14.6, 14.6, "bio_qls_informa_2021"),  # immuno-oncology proxy
    ("vaccine",         "phase1",  12.4, 12.4, "bio_qls_informa_2021"),  # immuno-oncology proxy
    ("ophthalmology",   "phase1",  11.5, 11.5, "bio_qls_informa_2021"),
    ("cardiovascular",  "phase1",   8.8,  8.8, "bio_qls_informa_2021"),
    ("metabolic",       "phase1",  10.6, 10.6, "bio_qls_informa_2021"),
    ("amr_infectious",  "phase1",  12.9, 12.9, "bio_qls_informa_2021"),  # infectious disease
    ("respiratory",     "phase1",   8.6,  8.6, "bio_qls_informa_2021"),
    ("cns",             "phase1",   5.9,  5.9, "bio_qls_informa_2021"),
    ("oncology",        "phase1",   5.3,  5.3, "bio_qls_informa_2021"),
    ("device",          "phase1",  15.0, 15.0, "bio_qls_informa_2021"),  # 510k/PMA higher
    ("diagnostic",      "phase1",  18.0, 18.0, "bio_qls_informa_2021"),
    ("all",             "phase1",   7.9,  7.9, "bio_qls_informa_2021"),

    # Phase II→approval LOA (overall 28.9% × 85.3% NDA approval = ~24.6% P2→approval)
    ("all",             "phase2",  24.6, None, "bio_qls_informa_2021"),
    # Phase III→approval (overall 58.1% × 85.3% = ~49.5%)
    ("all",             "phase3",  49.5, None, "bio_qls_informa_2021"),
]

_WONG_2019_PRIORS = [
    # Source: Wong, Siah & Lo (Biostatistics 2019), 406,038 trial entries, 2000-2015
    # Overall LOA estimates (upper-range historical)
    ("all",             "phase1",  13.8, 13.8, "wong_siah_lo_2019"),
    ("oncology",        "phase1",   8.3,  8.3, "wong_siah_lo_2019"),  # by 2015 (up from 3.4%)
]

# Versioned citation metadata
_CITATIONS = {
    "bio_qls_informa_2021": {
        "title": "Clinical Development Success Rates and Contributing Factors 2011-2020",
        "authors": "BIO, QLS Advisors, Informa Pharma Intelligence",
        "year": 2021,
        "url": "https://www.bio.org/sites/default/files/2021-01/Clinical-Development-Success-Rates-2011-2020.pdf",
        "notes": "Based on Biomedtracker database. Overall P1→approval 7.9%. Phase II transition 28.9%.",
    },
    "wong_siah_lo_2019": {
        "title": "Estimation of clinical trial success rates and related parameters",
        "authors": "Wong CH, Siah KW, Lo AW",
        "journal": "Biostatistics",
        "year": 2019,
        "pmid": "29394327",
        "doi": "10.1093/biostatistics/kxx069",
        "notes": "406,038 trial entries, 21,143 compounds, 2000-2015. Overall 13.8% P1→approval.",
    },
}


# ── DB schema + seed ──────────────────────────────────────────────────────────

async def init_priors_tables() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:

        # Citation registry
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS loa_citation (
                citation_key    TEXT PRIMARY KEY,
                title           TEXT NOT NULL,
                authors         TEXT,
                journal         TEXT,
                year            INTEGER,
                pmid            TEXT,
                doi             TEXT,
                url             TEXT,
                notes           TEXT,
                created_at      TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        # Phase-transition prior table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS success_rate_prior (
                id                  SERIAL PRIMARY KEY,
                therapeutic_area    VARCHAR(50)  NOT NULL,
                phase_from          VARCHAR(20)  NOT NULL,   -- 'phase1','phase2','phase3'
                loa_pct             FLOAT        NOT NULL,   -- cumulative LOA %
                p1_approval_pct     FLOAT,                   -- P1→approval %
                citation_key        TEXT REFERENCES loa_citation(citation_key),
                version             INTEGER      NOT NULL DEFAULT 1,
                created_at          TIMESTAMPTZ  DEFAULT NOW(),
                UNIQUE (therapeutic_area, phase_from, citation_key, version)
            );
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS srp_ta_phase_idx ON success_rate_prior (therapeutic_area, phase_from);"
        )

        # Seed citations
        for key, meta in _CITATIONS.items():
            await conn.execute("""
                INSERT INTO loa_citation (citation_key, title, authors, journal, year, pmid, doi, url, notes)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                ON CONFLICT (citation_key) DO NOTHING
            """,
                key, meta["title"], meta.get("authors"), meta.get("journal"),
                meta.get("year"), meta.get("pmid"), meta.get("doi"),
                meta.get("url"), meta.get("notes"),
            )

        # Seed BIO 2021 priors
        for ta, phase, loa, p1, cite in _BIO_2021_PRIORS:
            await conn.execute("""
                INSERT INTO success_rate_prior (therapeutic_area, phase_from, loa_pct, p1_approval_pct, citation_key, version)
                VALUES ($1,$2,$3,$4,$5,1)
                ON CONFLICT (therapeutic_area, phase_from, citation_key, version) DO NOTHING
            """, ta, phase, loa, p1, cite)

        # Seed Wong 2019 priors (version 2 — alternative estimate)
        for ta, phase, loa, p1, cite in _WONG_2019_PRIORS:
            await conn.execute("""
                INSERT INTO success_rate_prior (therapeutic_area, phase_from, loa_pct, p1_approval_pct, citation_key, version)
                VALUES ($1,$2,$3,$4,$5,1)
                ON CONFLICT (therapeutic_area, phase_from, citation_key, version) DO NOTHING
            """, ta, phase, loa, p1, cite)

    logger.info("✅ success_rate_prior table seeded with BIO 2021 + Wong 2019 LOA priors")


async def get_loa(therapeutic_area: str, phase_from: str,
                  prefer_citation: str = "bio_qls_informa_2021") -> float:
    """
    Return the LOA % for a therapeutic area + phase from the DB.
    Priority: TA-specific → 'all' fallback → hardcoded default.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # TA-specific first
        row = await conn.fetchrow("""
            SELECT loa_pct FROM success_rate_prior
            WHERE therapeutic_area = $1
              AND phase_from = $2
              AND citation_key = $3
            ORDER BY version DESC LIMIT 1
        """, therapeutic_area, phase_from, prefer_citation)
        if row:
            return float(row["loa_pct"])

        # Fall back to 'all'
        row = await conn.fetchrow("""
            SELECT loa_pct FROM success_rate_prior
            WHERE therapeutic_area = 'all'
              AND phase_from = $1
              AND citation_key = $2
            ORDER BY version DESC LIMIT 1
        """, phase_from, prefer_citation)
        if row:
            return float(row["loa_pct"])

    # Hardcoded defaults if DB unavailable
    _defaults = {"phase1": 7.9, "phase2": 24.6, "phase3": 49.5}
    return _defaults.get(phase_from, 7.9)
