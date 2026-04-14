"""
Memory CRUD API.
GET    /api/memory              — list personal memories
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
    user_id: str = "default"
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

@router.get("/users")
async def list_memory_users():
    """Return distinct user_ids that have at least one personal memory."""
    manager = await get_manager()
    users = await manager.list_users()
    return {"users": users}


@router.get("")
async def list_memories(
    user_id: str = Query("default"),
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
        scope="personal",
        source_chat=req.source_chat,
    )
    return {"id": memory_id, "status": "saved"}


@router.get("/search")
async def search_memories(
    user_id: str = Query(...),
    query: str = Query(...),
    top_k: int = Query(5, ge=1, le=20),
    include_team: bool = Query(False),
):
    manager = await get_manager()
    results = await manager.search_memories(
        user_id, query, top_k=top_k, include_team=include_team
    )
    return {"results": results}


@router.get("/{memory_id}")
async def get_memory(memory_id: str):
    manager = await get_manager()
    memory = await manager.get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


@router.delete("")
async def delete_all_memories(
    user_id: str = Query("default"),
    scope: str | None = Query(None),
):
    manager = await get_manager()
    count = await manager.purge_all(user_id, scope=scope)
    return {"status": "deleted", "count": count}


@router.delete("/by-chat/{chat_id}")
async def delete_memories_by_chat(chat_id: str):
    """Delete all memories associated with a specific chat_id."""
    manager = await get_manager()
    count = await manager.delete_by_chat(chat_id)
    return {"status": "deleted", "count": count}


@router.get("/by-chat/{chat_id}")
async def get_memories_by_chat(chat_id: str):
    """Get all memories associated with a specific chat_id."""
    manager = await get_manager()
    memories = await manager.list_by_chat(chat_id)
    return {"memories": memories}


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str):
    manager = await get_manager()
    deleted = await manager.delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"status": "deleted"}
