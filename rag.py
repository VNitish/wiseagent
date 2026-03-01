from __future__ import annotations

import logging

import faiss
import numpy as np
from openai import AsyncOpenAI

from config import OPENAI_API_KEY

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536
SIMILARITY_THRESHOLD = 0.50

_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
_index: faiss.IndexFlatIP | None = None
_chunk_texts: list[str] = []


def build_index(chunks: list[dict]) -> None:
    """
    Build FAISS IndexFlatIP from chunks that already have embeddings.
    chunks: list of dicts with 'content' and 'embedding' keys.
    """
    global _index, _chunk_texts

    _index = faiss.IndexFlatIP(EMBEDDING_DIM)
    _chunk_texts = []

    if not chunks:
        logger.warning("No embedded chunks — FAISS index is empty")
        return

    vectors = np.array([c["embedding"] for c in chunks], dtype=np.float32)
    faiss.normalize_L2(vectors)
    _index.add(vectors)
    _chunk_texts = [c["content"] for c in chunks]
    logger.info(f"FAISS index built: {len(chunks)} chunks")


async def embed(text: str) -> list[float]:
    response = await _client.embeddings.create(model=EMBEDDING_MODEL, input=text)
    return response.data[0].embedding


async def retrieve(query: str) -> str | None:
    """
    Embed query and search FAISS index.
    Returns concatenated context string if best match >= threshold, else None.
    None signals LLM to handle freely (small talk or deflect).
    """
    if _index is None or _index.ntotal == 0:
        return None

    query_vec = np.array([await embed(query)], dtype=np.float32)
    faiss.normalize_L2(query_vec)

    scores, indices = _index.search(query_vec, k=3)
    top_score = float(scores[0][0])

    hit = top_score >= SIMILARITY_THRESHOLD
    logger.info(f"RAG {'HIT' if hit else 'MISS'} top_score={top_score:.3f} | query={query!r}")

    if not hit:
        return None

    relevant = []
    for score, idx in zip(scores[0], indices[0]):
        if float(score) >= SIMILARITY_THRESHOLD and int(idx) >= 0:
            chunk = _chunk_texts[int(idx)]
            logger.info(f"\033[95mMatched chunk (score={float(score):.3f}):\n{chunk}\033[0m")
            relevant.append(chunk)

    return "\n\n".join(relevant)
