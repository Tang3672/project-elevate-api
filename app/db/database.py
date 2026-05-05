import asyncpg
from app.core.config import settings

_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.DATABASE_URL)
    return _pool

async def init_db():
    """Initialize database tables and pgvector extension."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Enable pgvector
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")

        # Hospital needs table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS hospital_needs (
                id SERIAL PRIMARY KEY,
                raw_text TEXT NOT NULL,
                department VARCHAR(255),
                category VARCHAR(255),
                subcategory VARCHAR(255),
                urgency_score INTEGER CHECK (urgency_score BETWEEN 1 AND 5),
                patient_impact_score INTEGER CHECK (patient_impact_score BETWEEN 1 AND 5),
                keywords TEXT[],
                hospital_id VARCHAR(255),
                submitted_by VARCHAR(255),
                source VARCHAR(50) DEFAULT 'manual',  -- 'manual', 'scraper', 'review'
                embedding vector(1536),               -- OpenAI text-embedding-3-small
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        # Index for fast vector similarity search
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS hospital_needs_embedding_idx
            ON hospital_needs
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 50);
        """)

        # Index for common filters
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS hospital_needs_category_idx
            ON hospital_needs (category);
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS hospital_needs_department_idx
            ON hospital_needs (department);
        """)

        print("✅ Database initialized successfully")

async def close_db():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
