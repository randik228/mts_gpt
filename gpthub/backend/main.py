from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import openai_compat, memory, taskchain, analytics, models

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.memory_manager import get_manager
    from core.analytics_store import get_store
    await get_manager()
    await get_store()
    yield


app = FastAPI(title="GPTHub Proxy", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(openai_compat.router)
app.include_router(memory.router, prefix="/api/memory")
app.include_router(taskchain.router, prefix="/api/taskchain")
app.include_router(analytics.router, prefix="/api/analytics")
app.include_router(models.router, prefix="/api/models")


@app.get("/health")
async def health():
    return {"status": "ok"}
