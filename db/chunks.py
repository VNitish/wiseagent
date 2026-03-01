import json

from .client import _client, _q, _run


async def get_chunks_for_kb(kb_id: str) -> list[dict]:
    return await _q(
        lambda: _client.table("chunks").select("*").eq("knowledge_base_id", kb_id).execute()
    )


async def get_unembedded_chunks() -> list[dict]:
    return await _q(
        lambda: _client.table("chunks")
        .select("id, content, knowledge_base_id")
        .is_("embedding", "null")
        .execute()
    )


async def get_chunks_with_embeddings() -> list[dict]:
    rows = await _q(
        lambda: _client.table("chunks")
        .select("id, content, embedding")
        .not_.is_("embedding", "null")
        .execute()
    )
    for row in rows:
        if isinstance(row["embedding"], str):
            row["embedding"] = json.loads(row["embedding"])
    return rows


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
    return await _q(lambda: _client.table("chunks").insert(records).execute())


async def save_chunk_embedding(chunk_id: str, embedding: list[float]) -> None:
    await _run(
        lambda: _client.table("chunks")
        .update({"embedding": embedding})
        .eq("id", chunk_id)
        .execute()
    )


async def delete_chunks_for_kb(kb_id: str) -> None:
    await _run(
        lambda: _client.table("chunks").delete().eq("knowledge_base_id", kb_id).execute()
    )
