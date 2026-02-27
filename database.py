import asyncio
import logging
from datetime import datetime, timezone

from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger(__name__)

_client = create_client(SUPABASE_URL, SUPABASE_KEY)


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
        await asyncio.to_thread(_client.table("conversations").insert(record).execute)
        logger.info(f"Conversation saved: {call_sid} outcome={outcome}")
    except Exception as e:
        logger.error(f"Failed to save conversation: {e}", exc_info=True)
