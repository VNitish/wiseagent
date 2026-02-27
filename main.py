import hashlib
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from twilio.rest import Client

import bridge
import rag
import chunker
from config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER
from database import (
    load_knowledge_base,
    get_chunks_for_kb,
    get_unembedded_chunks,
    get_chunks_with_embeddings,
    save_chunks,
    save_chunk_embedding,
    update_content_hash,
    delete_chunks_for_kb,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def startup_rag_pipeline():
    logger.info("RAG pipeline: loading knowledge base...")
    kb_entries = await load_knowledge_base()

    for entry in kb_entries:
        kb_id = str(entry["id"])
        content = entry["content"]
        current_hash = hashlib.sha256(content.encode()).hexdigest()
        stored_hash = entry.get("content_hash")

        if current_hash != stored_hash:
            logger.info(f"Re-chunking: {entry['title']!r}")
            await delete_chunks_for_kb(kb_id)
            chunks = chunker.chunk_text(content)
            await save_chunks(kb_id, chunks)
            await update_content_hash(kb_id, current_hash)
            logger.info(f"  → {len(chunks)} chunks saved")

    # Embed any chunks that are missing embeddings
    unembedded = await get_unembedded_chunks()
    if unembedded:
        logger.info(f"Embedding {len(unembedded)} unembedded chunks...")
        for chunk in unembedded:
            embedding = await rag.embed(chunk["content"])
            await save_chunk_embedding(str(chunk["id"]), embedding)
        logger.info("Embeddings saved.")

    # Build FAISS index from all embedded chunks
    embedded_chunks = await get_chunks_with_embeddings()
    rag.build_index(embedded_chunks)
    logger.info("RAG pipeline ready.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup_rag_pipeline()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

twilio = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


@app.get("/")
async def index():
    with open("static/index.html") as f:
        return HTMLResponse(f.read())


@app.post("/call")
async def call(request: Request):
    body = await request.json()
    to = body.get("to")
    host = request.headers["host"]
    twilio.calls.create(
        to=to,
        from_=TWILIO_PHONE_NUMBER,
        url=f"https://{host}/incoming-call",
    )
    return JSONResponse({"message": f"Calling {to} — pick up in a moment!"})


@app.post("/incoming-call")
async def incoming_call(request: Request):
    form = await request.form()
    caller = form.get("From", "unknown")
    call_sid = form.get("CallSid", "unknown")
    host = request.headers["host"]
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="wss://{host}/media-stream?caller={caller}&amp;call_sid={call_sid}"/>
    </Connect>
</Response>"""
    return HTMLResponse(content=twiml, media_type="application/xml")


@app.websocket("/media-stream")
async def media_stream(ws: WebSocket):
    await bridge.run(ws)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5050)
