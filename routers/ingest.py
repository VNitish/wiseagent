from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

import pipeline

router = APIRouter()


@router.post("/ingest")
async def ingest(request: Request):
    body = await request.json()
    url = body.get("url", "").strip()
    if not url:
        return JSONResponse({"error": "URL required"}, status_code=400)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return JSONResponse({"error": "Invalid URL — must be http or https"}, status_code=400)
    return StreamingResponse(
        pipeline.ingest_stream(url),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
