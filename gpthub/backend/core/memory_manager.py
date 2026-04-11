"""
Memory Manager — FAISS vector store + SQLite metadata + bge-m3 embeddings.

Public API:
    manager = await MemoryManager.create()

    # Store a single fact
    await manager.save_memory(user_id, content, scope="personal")

    # Retrieve relevant memories for a query
    memories = await manager.search_memories(user_id, query_text, top_k=5)

    # Extract facts from a conversation and store them (async, called after response)
    await manager.extract_and_save(user_id, messages)

    # CRUD for dashboard
    all_mems = await manager.list_memories(user_id)
    await manager.delete_memory(memory_id)

SQLite schema (memories table) is defined in _DDL below.
FAISS index is a flat L2 index; IDs are mapped via a parallel list stored in SQLite.
"""
import asyncio
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

import aiosqlite
import faiss
import numpy as np

from core.mws_client import embed, extract_facts

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    scope       TEXT NOT NULL DEFAULT 'personal',
    content     TEXT NOT NULL,
    source_chat TEXT,
    relevance   REAL NOT NULL DEFAULT 1.0,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);
"""

# Embedding dimension for bge-m3
_DIM = 1024

# Patterns for trivial facts that pollute memory
_TRIVIAL_PATTERNS = [
    # Language facts
    r"(?i)(user|пользователь).{0,30}(speaks?|говорит|пишет|общается).{0,30}(russian|english|русск|английск)",
    r"(?i)(conversation|диалог|чат).{0,20}(in|на).{0,20}(russian|english|русск|английск)",
    r"(?i)^(user speaks|пользователь говорит|conversation is in|пользователь общается)",
    # OpenWebUI internal requests
    r"(?i)(пользователь|user).{0,40}(теги|tags|заголовок|title|название чата)",
    r"(?i)(просит|asks?|requests?).{0,40}(сгенерир|generat).{0,40}(теги|tags|заголовок|title)",
    r"(?i)(история чата|chat history|чат содержит|conversation contains)",
    # One-time tasks / queries (NOT about the user)
    r"(?i)^пользователь (просит|хочет|запрашивает|спрашивает|ищет|искал|решал|решает|проверя)",
    r"(?i)^пользователь (задал|задаёт|отправил|написал|спросил|попросил|тестирует|тестировал)",
    r"(?i)(спрашивает|интересуется|ищет).{0,30}(информаци|данные|результат|ответ|новост|погод|курс)",
    r"(?i)(решал?|вычисл|считал?).{0,30}(задач[аеу]|пример|уравнени|умножени|деление|сложени)",
    r"(?i)(задач[аеу]|уравнени|вычислени|умножени)\b",
    r"(?i)(веб.поиск|web.search|искал в интернете|нашёл в интернете|результат.* поиска)",
    r"(?i)(генераци[яю]|сгенерировал|нарисовал|создал изображение|image generat)",
    r"(?i)(тестиру|проверя|работаешь|работает ли|test|check)",
    r"(?i)(код|code|script|function|функци).{0,20}(написал|создал|запросил|просит)",
    r"(?i)^(the user|user asked|user wants|user is asking|user requested)",
    # Facts about the conversation itself, not the person
    r"(?i)(в (этом|данном|текущем) (чате|диалоге|разговоре)|in this (chat|conversation))",
    r"(?i)(обсуждали|обсуждает|discussed|talking about)",
]

import re as _re

def _is_trivial_fact(fact: str) -> bool:
    """Return True if the fact is low-signal and should not be stored."""
    f = fact.strip()
    for pattern in _TRIVIAL_PATTERNS:
        if _re.search(pattern, f):
            return True
    return False

# Sentinel: index row → memory id (stored in a helper table so it survives restarts)
_FAISS_MAP_DDL = """
CREATE TABLE IF NOT EXISTS faiss_map (
    row_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id  TEXT NOT NULL
);
"""


class MemoryManager:
    """
    Thread-safe async memory store.
    Use MemoryManager.create() instead of __init__ — async initialisation needed.
    """

    def __init__(self, db_path: str, index_path: str):
        self._db_path = db_path
        self._index_path = index_path
        self._index: faiss.IndexFlatIP | None = None  # inner-product (cosine after norm)
        self._lock = asyncio.Lock()                    # serialise FAISS writes

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    async def create(
        cls,
        db_path: str = "/app/data/memory.db",
        index_path: str = "/app/data/faiss.index",
    ) -> "MemoryManager":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        mgr = cls(db_path, index_path)
        await mgr._init_db()
        await mgr._load_index()
        return mgr

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    async def _init_db(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_DDL + _FAISS_MAP_DDL)
            await db.commit()

    async def _load_index(self) -> None:
        """Load FAISS index from disk, or create a fresh one."""
        if os.path.exists(self._index_path):
            self._index = faiss.read_index(self._index_path)
            logger.info("FAISS index loaded: %d vectors", self._index.ntotal)
        else:
            self._index = faiss.IndexFlatIP(_DIM)
            logger.info("FAISS index created (empty)")

    def _save_index(self) -> None:
        """Persist FAISS index to disk (call inside _lock)."""
        faiss.write_index(self._index, self._index_path)

    # ------------------------------------------------------------------
    # save_memory
    # ------------------------------------------------------------------

    async def save_memory(
        self,
        user_id: str,
        content: str,
        *,
        scope: str = "personal",
        source_chat: str | None = None,
        relevance: float = 1.0,
    ) -> str:
        """
        Embed `content` via bge-m3, add to FAISS, persist metadata in SQLite.
        Returns the new memory id.
        """
        memory_id = str(uuid.uuid4())

        # Embed
        vectors = await embed([content])
        vec = _normalise(np.array(vectors[0], dtype=np.float32))

        async with self._lock:
            # FAISS: add vector; its row_id will be assigned by SQLite autoincrement
            async with aiosqlite.connect(self._db_path) as db:
                # Insert faiss_map row first to get row_id
                cursor = await db.execute(
                    "INSERT INTO faiss_map (memory_id) VALUES (?)", (memory_id,)
                )
                row_id = cursor.lastrowid  # 1-based

                await db.execute(
                    """INSERT INTO memories (id, user_id, scope, content, source_chat, relevance)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (memory_id, user_id, scope, content, source_chat, relevance),
                )
                await db.commit()

            # FAISS row index must match SQLite row_id - 1 (0-based)
            # Pad with zeros if there are gaps (shouldn't happen in normal flow)
            expected = self._index.ntotal
            if row_id - 1 > expected:
                padding = np.zeros((row_id - 1 - expected, _DIM), dtype=np.float32)
                self._index.add(padding)  # type: ignore[arg-type]

            self._index.add(vec.reshape(1, -1))  # type: ignore[arg-type]
            self._save_index()

        logger.debug("Saved memory %s for user=%s: %.60s", memory_id, user_id, content)
        return memory_id

    # ------------------------------------------------------------------
    # search_memories
    # ------------------------------------------------------------------

    async def search_memories(
        self,
        user_id: str,
        query: str,
        *,
        top_k: int = 5,
        min_score: float = 0.30,
        include_team: bool = True,
    ) -> list[str]:
        """
        Return up to top_k relevant memory strings for the given query.
        Filters by user_id in SQLite after FAISS retrieval.
        When include_team=True (default) also includes scope='team' memories.
        """
        if self._index.ntotal == 0:
            return []

        vectors = await embed([query])
        q_vec = _normalise(np.array(vectors[0], dtype=np.float32)).reshape(1, -1)

        # Search more candidates than needed — we'll filter by user_id
        k = min(top_k * 5, self._index.ntotal)
        scores, indices = self._index.search(q_vec, k)  # type: ignore[arg-type]

        # indices is shape (1, k); scores is cosine similarity (IP on normalised vecs)
        candidates = [
            (int(idx), float(score))
            for idx, score in zip(indices[0], scores[0])
            if idx >= 0 and score >= min_score
        ]

        if not candidates:
            return []

        # Map FAISS row_ids (0-based) → memory_ids via faiss_map (row_id is 1-based)
        row_ids = [c[0] + 1 for c in candidates]
        placeholders = ",".join("?" * len(row_ids))
        score_map = {c[0] + 1: c[1] for c in candidates}

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                f"SELECT row_id, memory_id FROM faiss_map WHERE row_id IN ({placeholders})",
                row_ids,
            )
            rows = await cursor.fetchall()

        memory_ids = [r["memory_id"] for r in rows]
        if not memory_ids:
            return []

        id_placeholders = ",".join("?" * len(memory_ids))
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            if include_team:
                # Include personal memories for this user AND all team-scoped memories
                cursor = await db.execute(
                    f"""SELECT id, content FROM memories
                        WHERE id IN ({id_placeholders})
                          AND (user_id = ? OR scope = 'team')""",
                    (*memory_ids, user_id),
                )
            else:
                cursor = await db.execute(
                    f"""SELECT id, content FROM memories
                        WHERE id IN ({id_placeholders}) AND user_id = ?""",
                    (*memory_ids, user_id),
                )
            mem_rows = await cursor.fetchall()

        # Sort by original FAISS score (best first)
        id_to_content = {r["id"]: r["content"] for r in mem_rows}
        ordered = sorted(
            [(score_map[rid], mid) for rid, mid in zip(
                [r["row_id"] for r in rows], memory_ids
            ) if mid in id_to_content],
            reverse=True,
        )

        return [id_to_content[mid] for _, mid in ordered[:top_k]]

    # ------------------------------------------------------------------
    # extract_and_save
    # ------------------------------------------------------------------

    async def extract_and_save(
        self,
        user_id: str,
        messages: list[dict],
        *,
        source_chat: str | None = None,
    ) -> list[str]:
        """
        Extract memorable facts from a conversation via gpt-oss-20b,
        embed each fact, and store in FAISS + SQLite.
        Returns the list of extracted fact strings.
        Designed to be called fire-and-forget after streaming finishes.
        """
        try:
            facts = await extract_facts(messages)
        except Exception:
            logger.warning("extract_and_save: fact extraction failed", exc_info=True)
            return []

        if not facts:
            return []

        saved: list[str] = []
        logger.info("extract_and_save: extracted %d raw facts: %s",
                     len(facts), [f[:50] for f in facts])
        for fact in facts:
            # Filter out trivial / low-signal facts
            if _is_trivial_fact(fact):
                logger.info("  SKIP trivial: %s", fact[:60])
                continue
            # Skip very short facts (noise) — but allow names (5+ chars)
            if len(fact.strip()) < 5:
                logger.info("  SKIP short: %s", fact[:60])
                continue
            try:
                # Deduplication: skip if nearly identical memory already exists
                is_dup = await self._is_duplicate(user_id, fact)
                if is_dup:
                    logger.debug("Skipping duplicate fact: %s", fact)
                    continue
                await self.save_memory(
                    user_id,
                    fact,
                    scope="personal",
                    source_chat=source_chat,
                )
                saved.append(fact)
            except Exception:
                logger.warning("extract_and_save: failed to save fact: %s", fact, exc_info=True)

        logger.info("extract_and_save: saved %d/%d facts for user=%s", len(saved), len(facts), user_id)
        return saved

    async def _is_duplicate(self, user_id: str, fact: str, threshold: float = 0.92) -> bool:
        """Return True if a very similar memory already exists for this user."""
        if self._index.ntotal == 0:
            return False
        existing = await self.search_memories(user_id, fact, top_k=1, min_score=threshold)
        return len(existing) > 0

    # ------------------------------------------------------------------
    # Dashboard CRUD
    # ------------------------------------------------------------------

    async def list_memories(
        self,
        user_id: str,
        *,
        scope: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """
        Return memories for a user, newest first.
        Special case: scope='team' returns ALL team-scoped memories across all users
        (team memories are shared — user_id filter is skipped).
        """
        if scope == "team":
            # Team memories are global — list all regardless of who created them
            sql = "SELECT * FROM memories WHERE scope = 'team' ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params: list = [limit, offset]
        else:
            sql = "SELECT * FROM memories WHERE user_id = ?"
            params = [user_id]
            if scope:
                sql += " AND scope = ?"
                params.append(scope)
            sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params += [limit, offset]

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(sql, params)
            rows = await cursor.fetchall()

        return [dict(r) for r in rows]

    async def delete_memory(self, memory_id: str) -> bool:
        """
        Remove a memory from SQLite (both memories and faiss_map tables).
        Note: FAISS IndexFlatIP doesn't support vector deletion — the vector
        remains but becomes unreachable since its faiss_map entry is gone.
        Returns True if a row was deleted.
        """
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM memories WHERE id = ?", (memory_id,)
            )
            # Also remove from faiss_map so the orphaned vector can't be found
            await db.execute(
                "DELETE FROM faiss_map WHERE memory_id = ?", (memory_id,)
            )
            await db.commit()
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info("Deleted memory %s (SQLite + faiss_map)", memory_id)

        return deleted

    async def get_memory(self, memory_id: str) -> dict | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            )
            row = await cursor.fetchone()
        return dict(row) if row else None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _normalise(vec: np.ndarray) -> np.ndarray:
    """L2-normalise a vector so inner-product == cosine similarity."""
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


# ------------------------------------------------------------------
# Module-level singleton (initialised on first import via lifespan)
# ------------------------------------------------------------------

_manager: MemoryManager | None = None


async def get_manager() -> MemoryManager:
    """Return the module-level singleton, creating it on first call."""
    global _manager
    if _manager is None:
        _manager = await MemoryManager.create()
    return _manager
