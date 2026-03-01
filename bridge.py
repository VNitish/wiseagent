from __future__ import annotations

import json
import asyncio
import logging
from datetime import datetime, timezone

import websockets
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from config import OPENAI_API_KEY, OPENAI_REALTIME_URL
from prompt import SYSTEM_PROMPT
from db import save_conversation
import rag

logger = logging.getLogger(__name__)

_CYAN  = "\033[96m"
_GREEN = "\033[92m"
_RESET = "\033[0m"

_MIN_WORDS = 2               # skip noise / single-word utterances before RAG
_BARGE_IN_DEBOUNCE_MS = 150  # ms of sustained speech before barge-in triggers

SESSION_CONFIG = {
    "turn_detection": {
        "type": "server_vad",
        "silence_duration_ms": 300,
        "prefix_padding_ms": 100,
        "create_response": False,  # manually triggered after RAG gate
    },
    "input_audio_format": "g711_ulaw",
    "output_audio_format": "g711_ulaw",
    "input_audio_transcription": {"model": "whisper-1"},
    "voice": "coral",
    "instructions": SYSTEM_PROMPT,
    "modalities": ["text", "audio"],
    "temperature": 0.8,
}

_FILLER_INSTRUCTION = (
    "BARGE-IN: the caller interrupted you. "
    "Say EXACTLY one of these — pick one, say nothing else: "
    "'Sure.', 'Of course.', 'Go ahead.', 'Yes?', 'Okay.' "
    "Do NOT continue your previous response. Do NOT add any other words."
)


async def run(twilio_ws: WebSocket):
    await twilio_ws.accept()

    call_sid = twilio_ws.query_params.get("call_sid", "unknown")
    caller_number = twilio_ws.query_params.get("caller", "unknown")
    stream_sid = None
    started_at = datetime.now(timezone.utc)
    transcript = []

    state = {
        "response_active": False,      # OpenAI is currently generating audio
        "playback_active": False,      # Twilio is currently playing audio (lasts longer than response_active)
        "barge_in_active": False,      # True while filler plays after barge-in
        "pending_instructions": None,  # real response queued while filler plays
        "barge_in_task": None,         # asyncio.Task for the debounce timer
        "draining": False,             # True after response.cancel until response.cancelled
        "last_assistant_item_id": None,           # for conversation.item.truncate
        "response_start_timestamp_twilio": None,  # Twilio ms when this response's audio began
        "latest_media_timestamp": 0,              # latest inbound Twilio media timestamp
        "mark_counter": 0,                        # unique mark IDs sent to Twilio
    }

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

            # Fire greeting immediately — overlaps OpenAI setup with audio generation.
            state["response_active"] = True
            await oai_ws.send(json.dumps({"type": "response.create"}))
            _audio_buffer: list[str] = []

            async def _send_response(instructions: str | None = None) -> None:
                """Send response.create only when no response is currently in-flight."""
                if state["response_active"]:
                    return
                state["response_active"] = True
                payload: dict = {"type": "response.create"}
                if instructions:
                    payload["response"] = {"instructions": instructions}
                await oai_ws.send(json.dumps(payload))

            async def twilio_to_openai() -> None:
                nonlocal stream_sid
                try:
                    async for msg in twilio_ws.iter_text():
                        try:
                            data = json.loads(msg)
                        except json.JSONDecodeError:
                            continue
                        event = data.get("event")

                        if event == "start":
                            stream_sid = data["start"]["streamSid"]
                            logger.info(f"Stream started: {stream_sid}")

                        elif event == "media":
                            media = data.get("media", {})
                            ts = media.get("timestamp")
                            if ts is not None:
                                state["latest_media_timestamp"] = int(ts)
                            await oai_ws.send(json.dumps({
                                "type": "input_audio_buffer.append",
                                "audio": media["payload"],
                            }))

                        elif event == "mark":
                            # Twilio echoes our mark back when it finishes playing up to that point.
                            # This is the true end-of-playback signal.
                            mark_name = data.get("mark", {}).get("name", "")
                            if mark_name.startswith("resp_"):
                                state["playback_active"] = False
                                logger.info("Twilio playback complete")

                        elif event == "stop":
                            break
                except Exception as e:
                    logger.error(f"twilio_to_openai error: {e}", exc_info=True)

            async def openai_to_twilio() -> None:
                try:
                    async for msg in oai_ws:
                        try:
                            data = json.loads(msg)
                        except json.JSONDecodeError:
                            continue
                        event_type = data.get("type", "")

                        # ── Error ──────────────────────────────────────────────
                        if event_type == "error":
                            logger.error(f"OpenAI error: {data}")
                            if data.get("error", {}).get("code") != "response_cancel_not_active":
                                state["response_active"] = False

                        # ── Track assistant item ID (for conversation.item.truncate) ─
                        elif event_type == "conversation.item.created":
                            item = data.get("item", {})
                            if item.get("role") == "assistant":
                                state["last_assistant_item_id"] = item.get("id")

                        # ── Old response stopped (cancel confirmed) ─────────────
                        # Kept separate from response.done — barge_in_active must
                        # only flip on response.done (when the FILLER finishes).
                        elif event_type == "response.cancelled":
                            state["response_active"] = False
                            state["draining"] = False

                        # ── Response generation done ────────────────────────────
                        elif event_type == "response.done":
                            state["response_active"] = False
                            state["draining"] = False
                            state["last_assistant_item_id"] = None
                            state["response_start_timestamp_twilio"] = None
                            # Filler just finished — send the queued real response
                            if state["barge_in_active"]:
                                state["barge_in_active"] = False
                                if state["pending_instructions"] is not None:
                                    instructions = state["pending_instructions"]
                                    state["pending_instructions"] = None
                                    logger.info("Filler done — sending queued real response")
                                    await _send_response(instructions)

                        # ── All audio for this response has been sent to Twilio ──
                        elif event_type == "response.audio.done":
                            # Send a mark so Twilio tells us when playback actually ends.
                            # This is the correct end-of-playback signal, not response.done.
                            if stream_sid and not state["draining"]:
                                mark_name = f"resp_{state['mark_counter']}"
                                state["mark_counter"] += 1
                                await twilio_ws.send_json({
                                    "event": "mark",
                                    "streamSid": stream_sid,
                                    "mark": {"name": mark_name},
                                })

                        # ── Barge-in detection ─────────────────────────────────
                        elif event_type == "input_audio_buffer.speech_started":
                            # Barge-in on either OpenAI generation or Twilio playback.
                            # response_active = OpenAI still generating
                            # playback_active = Twilio still playing (lasts longer)
                            is_interruptable = (
                                (state["response_active"] or state["playback_active"])
                                and not state["barge_in_active"]
                            )
                            if is_interruptable:
                                existing = state.get("barge_in_task")
                                if existing and not existing.done():
                                    existing.cancel()

                                async def _do_barge_in() -> None:
                                    try:
                                        await asyncio.sleep(_BARGE_IN_DEBOUNCE_MS / 1000)
                                    except asyncio.CancelledError:
                                        return  # too short — background noise

                                    still_interruptable = (
                                        state["response_active"] or state["playback_active"]
                                    )
                                    if not still_interruptable:
                                        return  # already finished naturally

                                    logger.info("Barge-in confirmed — interrupting playback")

                                    # 1. Cancel OpenAI generation (only if still generating)
                                    if state["response_active"]:
                                        await oai_ws.send(json.dumps({"type": "response.cancel"}))
                                        state["draining"] = True

                                    state["response_active"] = False
                                    state["playback_active"] = False
                                    state["barge_in_active"] = True

                                    # 2. Flush Twilio's audio buffer
                                    if stream_sid:
                                        await twilio_ws.send_json({
                                            "event": "clear",
                                            "streamSid": stream_sid,
                                        })

                                    # 3. Truncate conversation item — syncs model context
                                    #    to what the user actually heard before interruption
                                    if state["last_assistant_item_id"]:
                                        elapsed_ms = (
                                            state["latest_media_timestamp"]
                                            - (state["response_start_timestamp_twilio"] or state["latest_media_timestamp"])
                                        )
                                        await oai_ws.send(json.dumps({
                                            "type": "conversation.item.truncate",
                                            "item_id": state["last_assistant_item_id"],
                                            "content_index": 0,
                                            "audio_end_ms": max(0, elapsed_ms),
                                        }))
                                        logger.info(f"Truncated at {max(0, elapsed_ms)}ms")

                                    # 4. Play filler immediately
                                    state["response_active"] = True
                                    await oai_ws.send(json.dumps({
                                        "type": "response.create",
                                        "response": {"instructions": _FILLER_INSTRUCTION},
                                    }))
                                    state["barge_in_task"] = None

                                state["barge_in_task"] = asyncio.create_task(_do_barge_in())

                        # ── Speech stopped — cancel debounce if too short ──────
                        elif event_type == "input_audio_buffer.speech_stopped":
                            task = state.get("barge_in_task")
                            if task and not task.done():
                                task.cancel()
                                state["barge_in_task"] = None

                        # ── Transcript logging ─────────────────────────────────
                        elif event_type == "response.audio_transcript.done":
                            assistant_text = data.get("transcript", "")
                            transcript.append({
                                "role": "assistant",
                                "text": assistant_text,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })
                            logger.info(f"{_GREEN}Assistant: {assistant_text}{_RESET}")
                            if "human agent" in assistant_text.lower():
                                logger.info("Escalation detected — will hang up after playback")
                                state["should_hangup"] = True

                        # ── User turn — RAG gate ───────────────────────────────
                        elif event_type == "conversation.item.input_audio_transcription.completed":
                            user_text = data.get("transcript", "")

                            if len(user_text.split()) < _MIN_WORDS:
                                continue

                            transcript.append({
                                "role": "user",
                                "text": user_text,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })
                            logger.info(f"{_CYAN}User: {user_text}{_RESET}")

                            try:
                                context = await rag.retrieve(user_text)
                            except Exception as e:
                                logger.error(f"RAG retrieve error: {e}", exc_info=True)
                                context = None

                            if context:
                                instructions = (
                                    f"CONTEXT:\n{context}\n\n"
                                    f"INSTRUCTIONS: Answer using ONLY the context above. "
                                    f"DO NOT add any information from your training data. "
                                    f"If the context does not directly answer the caller's question, "
                                    f"say EXACTLY: 'I\u2019ll need to connect you with a human agent for that. Please hold.' "
                                    f"Do not attempt a partial answer."
                                )
                            else:
                                instructions = (
                                    "MANDATORY SCRIPT — follow exactly, no deviation.\n"
                                    "You have no verified information for this caller's question.\n"
                                    "Say EXACTLY this and nothing else: "
                                    "'I\u2019ll need to connect you with a human agent for that. Please hold for a moment.'\n"
                                    "Do NOT answer the question. Do NOT offer partial help. Do NOT explain.\n"
                                    "ONLY exception: pure greeting with no question (hello, hi, how are you) "
                                    "— respond briefly and naturally."
                                )

                            if state["barge_in_active"]:
                                state["pending_instructions"] = instructions
                                logger.info("Barge-in active — queuing real response")
                            else:
                                await _send_response(instructions)

                        # ── Audio forwarding ───────────────────────────────────
                        elif event_type == "response.audio.delta":
                            if state["draining"]:
                                continue  # drop in-flight packets from cancelled response
                            delta = data["delta"]
                            # Record when this response's audio first started playing
                            if state["response_start_timestamp_twilio"] is None:
                                state["response_start_timestamp_twilio"] = state["latest_media_timestamp"]
                            state["playback_active"] = True
                            if stream_sid:
                                for buffered in _audio_buffer:
                                    await twilio_ws.send_json({
                                        "event": "media",
                                        "streamSid": stream_sid,
                                        "media": {"payload": buffered},
                                    })
                                _audio_buffer.clear()
                                await twilio_ws.send_json({
                                    "event": "media",
                                    "streamSid": stream_sid,
                                    "media": {"payload": delta},
                                })
                            else:
                                _audio_buffer.append(delta)

                except WebSocketDisconnect:
                    pass  # caller hung up — normal exit
                except Exception as e:
                    logger.error(f"openai_to_twilio error: {e}", exc_info=True)

            await asyncio.gather(twilio_to_openai(), openai_to_twilio())

    except Exception as e:
        logger.error(f"Bridge error: {e}", exc_info=True)

    finally:
        task = state.get("barge_in_task")
        if task and not task.done():
            task.cancel()

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
