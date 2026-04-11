"""
Memory CRUD API.
GET    /api/memory              — list memories (personal or team)
POST   /api/memory              — create memory manually
GET    /api/memory/search       — semantic search
DELETE /api/memory/{memory_id}  — delete memory

Team memory:
  scope=team  →  memories are shared across all users.
  GET  /api/memory?scope=team          — list all team memories
  POST /api/memory  {scope:"team",...} — save as team memory (user_id forced to "__team__")
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.memory_manager import get_manager

router = APIRouter()

# Special user_id sentinel for team-scoped memories
_TEAM_USER = "__team__"


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

@router.get("")
async def list_memories(
    user_id: str = Query("default"),
    scope: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    List memories.  When scope=team the user_id parameter is ignored and all
    team-scoped memories are returned.
    """
    manager = await get_manager()
    return await manager.list_memories(user_id, scope=scope, limit=limit, offset=offset)


@router.post("")
async def create_memory(req: CreateMemoryRequest):
    """
    Create a memory manually.
    If scope='team', the memory is stored under user_id='__team__' so it is
    visible to all users during semantic search.
    """
    manager = await get_manager()
    effective_user = _TEAM_USER if req.scope == "team" else req.user_id
    memory_id = await manager.save_memory(
        effective_user,
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
    include_team: bool = Query(True),
):
    """
    Semantic search.  By default also returns team-scoped memories
    (include_team=true).  Pass include_team=false for personal-only results.
    """
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
    """
    Bulk delete all memories for a user (or all team memories if scope=team).
    """
    manager = await get_manager()
    memories = await manager.list_memories(user_id, scope=scope, limit=1000)
    count = 0
    for m in memories:
        await manager.delete_memory(m["id"])
        count += 1
    return {"status": "deleted", "count": count}


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str):
    manager = await get_manager()
    deleted = await manager.delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"status": "deleted"}
