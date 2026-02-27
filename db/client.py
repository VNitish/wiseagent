import asyncio

from supabase import create_client

from config import SUPABASE_URL, SUPABASE_KEY

_client = create_client(SUPABASE_URL, SUPABASE_KEY)


async def _q(fn) -> list[dict]:
    """Run a synchronous Supabase query in a thread and return .data."""
    return (await asyncio.to_thread(fn)).data


async def _run(fn) -> None:
    """Run a synchronous Supabase mutation in a thread, ignoring result."""
    await asyncio.to_thread(fn)
