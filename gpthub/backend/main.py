from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import openai_compat, memory, taskchain, analytics, models, settings, suggestions

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.memory_manager import get_manager
    from core.analytics_store import get_store
    from api.settings import load_persisted_key
    load_persisted_key()
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
app.include_router(settings.router, prefix="/api/settings")
app.include_router(suggestions.router, prefix="/api/suggestions")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/imgproxy")
async def imgproxy(url: str):
    """Proxy external image to bypass CORS for canvas/download."""
    import httpx
    from fastapi import HTTPException
    from fastapi.responses import Response

    allowed = ("https://imagegen.gpt.mws.ru/", "https://api.gpt.mws.ru/")
    if not any(url.startswith(d) for d in allowed):
        raise HTTPException(400, "Domain not allowed")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, "Upstream error")
        return Response(
            content=resp.content,
            media_type=resp.headers.get("content-type", "image/png"),
        )
