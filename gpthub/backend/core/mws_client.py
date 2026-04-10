"""
MWS GPT API client — thin async wrapper over the openai SDK.

Usage:
    from core.mws_client import chat_stream, chat_complete, embed, list_models

All functions raise openai.APIError subclasses on failure — callers handle them.
"""
import os
from typing import AsyncIterator

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionChunk, ChatCompletion
from openai.types import CreateEmbeddingResponse

# ---------------------------------------------------------------------------
# Singleton client
# ---------------------------------------------------------------------------

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=os.environ.get("MWS_API_BASE", "https://api.gpt.mws.ru/v1"),
            api_key=os.environ["MWS_API_KEY"],
            timeout=120.0,
            max_retries=2,
        )
    return _client


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

async def chat_complete(
    model: str,
    messages: list[dict],
    *,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    extra_body: dict | None = None,
) -> ChatCompletion:
    """Non-streaming chat completion. Returns full response object."""
    return await get_client().chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
        **(extra_body or {}),
    )


async def chat_stream(
    model: str,
    messages: list[dict],
    *,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    extra_body: dict | None = None,
) -> AsyncIterator[ChatCompletionChunk]:
    """
    Streaming chat completion.
    Yields ChatCompletionChunk objects — use chunk.choices[0].delta.content.
    """
    stream = await get_client().chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
        **(extra_body or {}),
    )
    async for chunk in stream:
        yield chunk


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

async def embed(
    texts: list[str],
    model: str | None = None,
) -> list[list[float]]:
    """
    Embed a list of strings with bge-m3 (or override model).
    Returns list of float vectors in the same order as input.
    """
    embedding_model = model or os.environ.get("EMBEDDING_MODEL", "bge-m3")
    response: CreateEmbeddingResponse = await get_client().embeddings.create(
        model=embedding_model,
        input=texts,
    )
    # API returns items sorted by index
    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

async def list_models() -> list[str]:
    """Return model IDs available on MWS API."""
    response = await get_client().models.list()
    return [m.id for m in response.data]


# ---------------------------------------------------------------------------
# Fact extraction helper (used by MemoryManager)
# ---------------------------------------------------------------------------

_EXTRACT_FACTS_PROMPT = """\
Из следующего диалога извлеки ключевые факты о пользователе или контексте задачи.
Верни только список фактов — по одному на строку, без нумерации.
Если фактов нет, верни пустую строку.

Диалог:
{dialogue}"""


async def extract_facts(messages: list[dict]) -> list[str]:
    """
    Call gpt-oss-20b to extract memorable facts from a conversation.
    Returns a (possibly empty) list of fact strings.
    """
    dialogue = "\n".join(
        f"{m['role'].upper()}: {m.get('content', '')}" for m in messages
    )
    response = await chat_complete(
        model="gpt-oss-20b",
        messages=[
            {"role": "user", "content": _EXTRACT_FACTS_PROMPT.format(dialogue=dialogue)}
        ],
        temperature=0.0,
        max_tokens=512,
    )
    raw = response.choices[0].message.content or ""
    return [line.strip() for line in raw.splitlines() if line.strip()]
