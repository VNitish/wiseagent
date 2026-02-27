import logging
import uvicorn
from fastapi import FastAPI, Request, WebSocket

logging.basicConfig(level=logging.INFO)
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from twilio.rest import Client

import bridge
from config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER

app = FastAPI()
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
