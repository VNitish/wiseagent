import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import pipeline
from routers import call, ingest

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await pipeline.startup()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(call.router)
app.include_router(ingest.router)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5050)
