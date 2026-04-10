"""
Analytics API.
GET /api/analytics/routing — routing decisions log + aggregated stats
"""
import time
import logging
from fastapi import APIRouter, Query

from core.analytics_store import get_store

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/routing")
async def routing_analytics(limit: int = Query(200, ge=1, le=1000)):
    store = await get_store()
    decisions = await store.list_decisions(limit=limit)
    stats = await store.model_stats()
    return {"decisions": decisions, "stats": stats}
