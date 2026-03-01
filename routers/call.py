import functools

from fastapi import APIRouter, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from twilio.request_validator import RequestValidator
from twilio.rest import Client

import bridge
from config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER

router = APIRouter()

_twilio = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
_validator = RequestValidator(TWILIO_AUTH_TOKEN)


@functools.lru_cache(maxsize=1)
def _index_html() -> str:
    with open("static/index.html") as f:
        return f.read()


def _check_twilio_signature(request: Request, params: dict) -> None:
    sig = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)
    if not _validator.validate(url, params, sig):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


@router.get("/")
async def index():
    return HTMLResponse(_index_html())


@router.post("/call")
async def call(request: Request):
    body = await request.json()
    to = body.get("to", "").strip()
    if not to:
        return JSONResponse({"error": "Phone number required"}, status_code=400)
    host = request.headers["host"]
    _twilio.calls.create(
        to=to,
        from_=TWILIO_PHONE_NUMBER,
        url=f"https://{host}/incoming-call",
    )
    return JSONResponse({"message": f"Calling {to} — pick up in a moment!"})


@router.post("/incoming-call")
async def incoming_call(request: Request):
    form = await request.form()
    params = dict(form)
    _check_twilio_signature(request, params)

    caller = params.get("From", "unknown")
    call_sid = params.get("CallSid", "unknown")
    host = request.headers["host"]
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="wss://{host}/media-stream?caller={caller}&amp;call_sid={call_sid}"/>
    </Connect>
</Response>"""
    return HTMLResponse(content=twiml, media_type="application/xml")


@router.websocket("/media-stream")
async def media_stream(ws: WebSocket):
    await bridge.run(ws)
