"""
Analytics Store — SQLite log of routing decisions.
Written to on every /v1/chat/completions call.
Read by /api/analytics/routing for the Dashboard.
"""
import time
import uuid
from pathlib import Path

import aiosqlite

_DDL = """
CREATE TABLE IF NOT EXISTS routing_log (
    id           TEXT PRIMARY KEY,
    ts           REAL NOT NULL,
    user_id      TEXT,
    requested    TEXT NOT NULL,
    routed_to    TEXT NOT NULL,
    method       TEXT NOT NULL,
    reason       TEXT NOT NULL,
    latency_ms   REAL
);
CREATE INDEX IF NOT EXISTS idx_routing_ts ON routing_log(ts DESC);
"""


class AnalyticsStore:
    def __init__(self, db_path: str):
        self._db_path = db_path

    @classmethod
    async def create(cls, db_path: str = "/app/data/analytics.db") -> "AnalyticsStore":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        store = cls(db_path)
        async with aiosqlite.connect(db_path) as db:
            await db.executescript(_DDL)
            await db.commit()
        return store

    async def record(
        self,
        *,
        user_id: str,
        requested: str,
        routed_to: str,
        method: str,
        reason: str,
        latency_ms: float | None = None,
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT INTO routing_log
                   (id, ts, user_id, requested, routed_to, method, reason, latency_ms)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), time.time(), user_id,
                 requested, routed_to, method, reason, latency_ms),
            )
            await db.commit()

    async def list_decisions(self, limit: int = 200) -> list[dict]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM routing_log ORDER BY ts DESC LIMIT ?", (limit,)
            )
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def model_stats(self) -> list[dict]:
        """Aggregated call counts + avg latency per model."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("""
                SELECT
                    routed_to                        AS model,
                    COUNT(*)                         AS calls,
                    AVG(latency_ms)                  AS avg_latency_ms,
                    SUM(CASE WHEN method='keyword'   THEN 1 ELSE 0 END) AS keyword_hits,
                    SUM(CASE WHEN method='embedding' THEN 1 ELSE 0 END) AS embedding_hits,
                    SUM(CASE WHEN method='multimodal' THEN 1 ELSE 0 END) AS multimodal_hits,
                    MAX(ts)                          AS last_used
                FROM routing_log
                GROUP BY routed_to
                ORDER BY calls DESC
            """)
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


_store: AnalyticsStore | None = None


async def get_store() -> AnalyticsStore:
    global _store
    if _store is None:
        _store = await AnalyticsStore.create()
    return _store
