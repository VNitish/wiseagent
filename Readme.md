# WiseAgent

Voice support agent for Wise — built on Twilio + OpenAI Realtime API.

## Architecture

```
Caller → Twilio PSTN → POST /incoming-call → TwiML <Stream>
       → WS /media-stream → bridge.py → WSS OpenAI Realtime
                                ↑
                         rag.py (FAISS gate, per-turn)
                                ↑
                         db/ (Supabase — KB + transcripts)
```

**Bridge** (`bridge.py`) — bidirectional WebSocket proxy. Inbound g711_ulaw audio forwarded raw to OpenAI; outbound audio forwarded raw to Twilio. No transcoding.

**RAG gate** — on each user turn, transcript is embedded and searched against FAISS IndexFlatIP (cosine similarity, threshold 0.50). Hit → context injected into `response.create` instructions. Miss → mandatory escalation script.

**Ingestion** — `POST /ingest` fetches a URL via OpenGraph.io, extracts content, chunks at 400 tokens (80 overlap), embeds with `text-embedding-3-small`, stores in Supabase, rebuilds FAISS index. SHA256 dedup skips unchanged articles.

## Key Decisions

- **Server VAD + `create_response: False`** — manual response trigger after RAG lookup, not auto-trigger on silence
- **Twilio mark events** — accurate end-of-playback signal (vs `response.done` which fires when generation ends, not playback)
- **`conversation.item.truncate`** — syncs model context to what the caller actually heard on barge-in
- **FAISS in-process** — no vector DB latency; rebuilt on startup and after each ingest

## Setup

```
OPENAI_API_KEY, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
TWILIO_PHONE_NUMBER, SUPABASE_URL, SUPABASE_KEY, OPENGRAPH_API_KEY
```

```bash
pip install -r requirements.txt
uvicorn main:app --port 5050
```

Deploy: Railway — `Procfile` and `runtime.txt` (Python 3.11) included.
