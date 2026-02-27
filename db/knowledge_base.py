from .client import _client, _q, _run


async def load_knowledge_base() -> list[dict]:
    return await _q(
        lambda: _client.table("knowledge_base").select("*").eq("active", True).execute()
    )


async def get_knowledge_base_by_title(title: str) -> list[dict]:
    return await _q(
        lambda: _client.table("knowledge_base").select("*").eq("title", title).execute()
    )


async def insert_knowledge_base(title: str, content: str) -> str:
    rows = await _q(
        lambda: _client.table("knowledge_base")
        .insert({"title": title, "content": content, "active": True})
        .execute()
    )
    return str(rows[0]["id"])


async def update_knowledge_base_content(kb_id: str, title: str, content: str) -> None:
    await _run(
        lambda: _client.table("knowledge_base")
        .update({"title": title, "content": content})
        .eq("id", kb_id)
        .execute()
    )


async def update_content_hash(kb_id: str, content_hash: str) -> None:
    await _run(
        lambda: _client.table("knowledge_base")
        .update({"content_hash": content_hash})
        .eq("id", kb_id)
        .execute()
    )
