import json
import asyncio
import logging
from datetime import datetime, timezone

import websockets
from fastapi import WebSocket

from config import OPENAI_API_KEY, OPENAI_REALTIME_URL
from prompt import SYSTEM_PROMPT
from database import save_conversation

logger = logging.getLogger(__name__)

SESSION_CONFIG = {
    "turn_detection": {
        "type": "server_vad",
        "silence_duration_ms": 300,
        "prefix_padding_ms": 100,
    },
    "input_audio_format": "g711_ulaw",
    "output_audio_format": "g711_ulaw",
    "input_audio_transcription": {"model": "whisper-1"},
    "voice": "coral",
    "instructions": SYSTEM_PROMPT,
    "modalities": ["text", "audio"],
    "temperature": 0.7,
}


async def run(twilio_ws: WebSocket):
    await twilio_ws.accept()

    call_sid = twilio_ws.query_params.get("call_sid", "unknown")
    caller_number = twilio_ws.query_params.get("caller", "unknown")
    stream_sid = None
    started_at = datetime.now(timezone.utc)
    transcript = []

    try:
        async with websockets.connect(
            OPENAI_REALTIME_URL,
            additional_headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "OpenAI-Beta": "realtime=v1",
            },
        ) as oai_ws:
            logger.info("Connected to OpenAI Realtime")
            await oai_ws.send(json.dumps({"type": "session.update", "session": SESSION_CONFIG}))

            async def twilio_to_openai():
                nonlocal stream_sid
                async for msg in twilio_ws.iter_text():
                    data = json.loads(msg)
                    if data["event"] == "start":
                        stream_sid = data["start"]["streamSid"]
                        logger.info(f"Stream started: {stream_sid}")
                        await oai_ws.send(json.dumps({"type": "response.create"}))
                    elif data["event"] == "media":
                        await oai_ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": data["media"]["payload"],
                        }))
                    elif data["event"] == "stop":
                        break

            async def openai_to_twilio():
                try:
                    async for msg in oai_ws:
                        data = json.loads(msg)
                        event_type = data.get("type", "")

                        if event_type == "error":
                            logger.error(f"OpenAI error: {data}")

                        elif event_type == "response.audio_transcript.done":
                            transcript.append({
                                "role": "assistant",
                                "text": data.get("transcript", ""),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })

                        elif event_type == "conversation.item.input_audio_transcription.completed":
                            transcript.append({
                                "role": "user",
                                "text": data.get("transcript", ""),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })

                        elif event_type == "response.audio.delta" and stream_sid:
                            await twilio_ws.send_json({
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {"payload": data["delta"]},
                            })

                except Exception as e:
                    logger.error(f"openai_to_twilio error: {e}", exc_info=True)

            await asyncio.gather(twilio_to_openai(), openai_to_twilio())

    except Exception as e:
        logger.error(f"Bridge error: {e}", exc_info=True)

    finally:
        outcome = "deflected" if any(
            "human agent" in m["text"].lower()
            for m in transcript if m["role"] == "assistant"
        ) else "answered"
        await save_conversation(
            call_sid=call_sid,
            caller_number=caller_number,
            started_at=started_at,
            transcript=transcript,
            outcome=outcome,
        )
