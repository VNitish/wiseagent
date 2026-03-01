import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import config
import pipeline
import rag
from routers import call, ingest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.validate()
    await pipeline.startup()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(call.router)
app.include_router(ingest.router)


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "index_size": rag.index_size()})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5050)
