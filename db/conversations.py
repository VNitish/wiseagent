import logging
from datetime import datetime, timezone

from .client import _client, _run

logger = logging.getLogger(__name__)


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
        await _run(lambda: _client.table("conversations").insert(record).execute())
        logger.info(f"Conversation saved: {call_sid} outcome={outcome}")
    except Exception as e:
        logger.error(f"Failed to save conversation: {e}", exc_info=True)
