"""
Embedding service: generates vector embeddings for text using OpenAI.

We use text-embedding-3-small (1536 dimensions) — it's fast, cheap,
and accurate enough for semantic similarity at this scale.

text-embedding-3-large would give better results at ~6x the cost.
Switch when you have 10k+ needs in the index.
"""

from openai import AsyncOpenAI
from typing import List
from app.core.config import settings

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


async def embed_text(text: str) -> List[float]:
    """
    Generate an embedding vector for a single text string.
    Returns a list of 1536 floats.
    """
    # Truncate to ~8000 tokens max (model limit)
    text = text[:8000].strip()

    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
        dimensions=EMBEDDING_DIMENSIONS
    )
    return response.data[0].embedding


async def embed_batch(texts: List[str]) -> List[List[float]]:
    """
    Generate embeddings for multiple texts in one API call.
    More efficient than calling embed_text() in a loop.
    Max 2048 inputs per batch.
    """
    cleaned = [t[:8000].strip() for t in texts]
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=cleaned,
        dimensions=EMBEDDING_DIMENSIONS
    )
    # API returns embeddings in the same order as inputs
    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
