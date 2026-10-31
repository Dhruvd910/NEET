"""Text embeddings for semantic search (Voyage AI). Disabled when VOYAGE_API_KEY is empty.

Vectors are stored as JSON on document_chunks and compared in Python, which is fine for tens of
thousands of chunks. Beyond that, move them to a pgvector column with an HNSW index on PostgreSQL;
`retrieval.search_documents` is the only caller that needs to change.
"""
import logging
import math

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)
VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
BATCH = 64


def embeddings_enabled() -> bool:
    s = get_settings()
    return s.embedding_provider == "voyage" and bool(s.voyage_api_key)


def embed(texts: list[str], input_type: str) -> list[list[float]] | None:
    """Embed texts ("document" or "query"). Returns None on any provider error (callers fall back to BM25)."""
    if not embeddings_enabled() or not texts:
        return None
    s = get_settings()
    vectors: list[list[float]] = []
    try:
        with httpx.Client(timeout=30) as client:
            for i in range(0, len(texts), BATCH):
                r = client.post(VOYAGE_URL, headers={"Authorization": f"Bearer {s.voyage_api_key}"},
                                json={"input": texts[i:i + BATCH], "model": s.embedding_model,
                                      "input_type": input_type})
                r.raise_for_status()
                vectors.extend(d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"]))
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        log.warning("embedding request failed: %s", exc)
        return None
    return vectors


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
