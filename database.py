import asyncio
import logging
from datetime import datetime, timezone

from supabase import create_client

from config import SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger(__name__)

_client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ── Conversations ─────────────────────────────────────────────────────────────

async def save_conversation(*, call_sid, caller_number, started_at, transcript, outcome):
    record = {
        "call_sid": call_sid,
        "caller_number": caller_number,
        "started_at": started_at.isoformat(),
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "outcome": outcome,
        "transcript": transcript,
    }
    try:
        await asyncio.to_thread(
            lambda: _client.table("conversations").insert(record).execute()
        )
        logger.info(f"Conversation saved: {call_sid} outcome={outcome}")
    except Exception as e:
        logger.error(f"Failed to save conversation: {e}", exc_info=True)


# ── Knowledge Base ────────────────────────────────────────────────────────────

async def load_knowledge_base() -> list[dict]:
    result = await asyncio.to_thread(
        lambda: _client.table("knowledge_base").select("*").eq("active", True).execute()
    )
    return result.data


async def update_content_hash(kb_id: str, content_hash: str) -> None:
    await asyncio.to_thread(
        lambda: _client.table("knowledge_base")
        .update({"content_hash": content_hash})
        .eq("id", kb_id)
        .execute()
    )


# ── Chunks ────────────────────────────────────────────────────────────────────

async def get_chunks_for_kb(kb_id: str) -> list[dict]:
    result = await asyncio.to_thread(
        lambda: _client.table("chunks")
        .select("*")
        .eq("knowledge_base_id", kb_id)
        .execute()
    )
    return result.data


async def get_unembedded_chunks() -> list[dict]:
    result = await asyncio.to_thread(
        lambda: _client.table("chunks")
        .select("id, content, knowledge_base_id")
        .is_("embedding", "null")
        .execute()
    )
    return result.data


async def get_chunks_with_embeddings() -> list[dict]:
    result = await asyncio.to_thread(
        lambda: _client.table("chunks")
        .select("id, content, embedding")
        .not_.is_("embedding", "null")
        .execute()
    )
    return result.data


async def save_chunks(kb_id: str, chunks: list[dict]) -> list[dict]:
    records = [
        {
            "knowledge_base_id": kb_id,
            "chunk_index": c["chunk_index"],
            "content": c["content"],
            "token_count": c["token_count"],
        }
        for c in chunks
    ]
    result = await asyncio.to_thread(
        lambda: _client.table("chunks").insert(records).execute()
    )
    return result.data


async def save_chunk_embedding(chunk_id: str, embedding: list[float]) -> None:
    await asyncio.to_thread(
        lambda: _client.table("chunks")
        .update({"embedding": embedding})
        .eq("id", chunk_id)
        .execute()
    )


async def delete_chunks_for_kb(kb_id: str) -> None:
    await asyncio.to_thread(
        lambda: _client.table("chunks").delete().eq("knowledge_base_id", kb_id).execute()
    )
