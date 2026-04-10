"""
Memory CRUD API.
GET    /api/memory              — list memories for user_id
POST   /api/memory              — create memory manually
GET    /api/memory/search       — semantic search
DELETE /api/memory/{memory_id}  — delete memory
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.memory_manager import get_manager

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CreateMemoryRequest(BaseModel):
    user_id: str
    content: str
    scope: str = "personal"
    source_chat: str | None = None


class MemorySearchRequest(BaseModel):
    user_id: str
    query: str
    top_k: int = 5


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_memories(
    user_id: str = Query(...),
    scope: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    manager = await get_manager()
    return await manager.list_memories(user_id, scope=scope, limit=limit, offset=offset)


@router.post("")
async def create_memory(req: CreateMemoryRequest):
    manager = await get_manager()
    memory_id = await manager.save_memory(
        req.user_id,
        req.content,
        scope=req.scope,
        source_chat=req.source_chat,
    )
    return {"id": memory_id, "status": "saved"}


@router.get("/search")
async def search_memories(
    user_id: str = Query(...),
    query: str = Query(...),
    top_k: int = Query(5, ge=1, le=20),
):
    manager = await get_manager()
    results = await manager.search_memories(user_id, query, top_k=top_k)
    return {"results": results}


@router.get("/{memory_id}")
async def get_memory(memory_id: str):
    manager = await get_manager()
    memory = await manager.get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str):
    manager = await get_manager()
    deleted = await manager.delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"status": "deleted"}
