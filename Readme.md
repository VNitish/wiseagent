# WiseAgent

AI voice agent for Wise support — handles "Where is my money?" calls.

## Architecture

```
Caller → Twilio → /incoming-call → WS /media-stream → bridge.py
                                                           ↕
                                                  OpenAI Realtime API
                                                  (gpt-4o-realtime)
                                                           ↑
                                                   rag.py (FAISS gate)
                                                           ↑
                                                    db/ (Supabase)
```

**RAG** — `pipeline.startup()` loads `knowledge_base`, rechunks stale entries (400 tokens, 20% overlap), embeds via `text-embedding-3-small`, builds FAISS `IndexFlatIP`. Per turn, the transcript is searched at threshold 0.75 and context injected into `response.create`. Below threshold, LLM decides (small talk or deflect).

**Ingestion** — `POST /ingest` fetches a Wise Help URL via OpenGraph.io, chunks, embeds, rebuilds index with SSE progress.

## Stack
FastAPI · Twilio Media Streams · OpenAI Realtime · FAISS · Supabase pgvector

## Run
```bash
pip install -r requirements.txt
ngrok http 5050
python main.py
```