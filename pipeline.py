import hashlib
import json as json_module
import logging
import urllib.parse

import httpx

import chunker
import extractor
import rag
from config import OPENGRAPH_API_KEY
from db import (
    delete_chunks_for_kb,
    get_chunks_with_embeddings,
    get_knowledge_base_by_title,
    get_unembedded_chunks,
    insert_knowledge_base,
    load_knowledge_base,
    save_chunk_embedding,
    save_chunks,
    update_content_hash,
    update_knowledge_base_content,
)

logger = logging.getLogger(__name__)


async def startup():
    """Build FAISS index at app startup — rechunks/re-embeds stale KB entries."""
    logger.info("RAG pipeline: loading knowledge base...")

    for entry in await load_knowledge_base():
        kb_id = str(entry["id"])
        content = entry["content"]
        current_hash = hashlib.sha256(content.encode()).hexdigest()

        if current_hash != entry.get("content_hash"):
            logger.info(f"Re-chunking: {entry['title']!r}")
            await delete_chunks_for_kb(kb_id)
            await save_chunks(kb_id, chunker.chunk_text(content, entry["title"]))
            await update_content_hash(kb_id, current_hash)

    unembedded = await get_unembedded_chunks()
    if unembedded:
        logger.info(f"Embedding {len(unembedded)} chunks...")
        for chunk in unembedded:
            embedding = await rag.embed(chunk["content"])
            await save_chunk_embedding(str(chunk["id"]), embedding)

    rag.build_index(await get_chunks_with_embeddings())
    logger.info("RAG pipeline ready.")


async def ingest_stream(url: str):
    """Async generator yielding SSE events for the full ingestion pipeline."""

    def event(message: str, progress: int, error: bool = False) -> str:
        return f"data: {json_module.dumps({'message': message, 'progress': progress, 'error': error})}\n\n"

    try:
        yield event("Fetching article...", 10)
        encoded = urllib.parse.quote(url, safe="")
        api_url = f"https://opengraph.io/api/1.1/extract/{encoded}?app_id={OPENGRAPH_API_KEY}"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(api_url)
            data = resp.json()

        tags = data.get("tags", [])
        if not tags:
            yield event("No content found at that URL.", 0, error=True)
            return

        yield event("Extracting content...", 25)
        title, content = extractor.extract_content(tags)
        yield event(f'Extracted: "{title}"', 35)

        current_hash = hashlib.sha256(content.encode()).hexdigest()
        existing = await get_knowledge_base_by_title(title)

        if existing:
            kb_id = str(existing[0]["id"])
            if existing[0].get("content_hash") == current_hash:
                yield event("Article already up to date — rebuilding index.", 80)
                rag.build_index(await get_chunks_with_embeddings())
                yield event("Done! Index is current.", 100)
                return
            yield event("Updating existing article...", 42)
            await update_knowledge_base_content(kb_id, title, content)
        else:
            yield event("Saving to knowledge base...", 42)
            kb_id = await insert_knowledge_base(title, content)

        yield event("Chunking content...", 50)
        await delete_chunks_for_kb(kb_id)
        chunks = chunker.chunk_text(content, title)
        saved_chunks = await save_chunks(kb_id, chunks)
        await update_content_hash(kb_id, current_hash)
        yield event(f"Created {len(chunks)} chunks.", 60)

        for i, chunk in enumerate(saved_chunks):
            embedding = await rag.embed(chunk["content"])
            await save_chunk_embedding(str(chunk["id"]), embedding)
            yield event(f"Embedded chunk {i + 1}/{len(chunks)}", 60 + int((i + 1) / len(chunks) * 25))

        yield event("Rebuilding FAISS index...", 90)
        rag.build_index(await get_chunks_with_embeddings())
        yield event(f'"{title}" is now live in the knowledge base.', 100)

    except Exception as e:
        logger.error(f"Ingest error: {e}", exc_info=True)
        yield event(f"Error: {e}", 0, error=True)
