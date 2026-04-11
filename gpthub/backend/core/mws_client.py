"""
MWS GPT API client — thin async wrapper over the openai SDK.

Usage:
    from core.mws_client import chat_stream, chat_complete, embed, list_models

All functions raise openai.APIError subclasses on failure — callers handle them.
"""
import asyncio
import logging
import os
from typing import AsyncIterator

import openai as _openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionChunk, ChatCompletion
from openai.types import CreateEmbeddingResponse

logger = logging.getLogger(__name__)

# Transient errors worth retrying (TCP-level failures, timeouts, 429 / 503)
_RETRYABLE = (_openai.APIConnectionError, _openai.APITimeoutError)
_RETRY_DELAYS = (1.0, 3.0)  # 2 extra attempts → 3 total

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
    """Non-streaming chat completion. Retries on transient network errors."""
    last_exc: Exception | None = None
    for attempt, delay in enumerate([0.0] + list(_RETRY_DELAYS)):
        if attempt > 0:
            logger.warning("chat_complete retry %d/%d after %.1fs (model=%s)",
                           attempt, len(_RETRY_DELAYS), delay, model)
            await asyncio.sleep(delay)
        try:
            return await get_client().chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
                **(extra_body or {}),
            )
        except _RETRYABLE as e:
            last_exc = e
    raise last_exc  # type: ignore[misc]


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
    Retries the whole stream on transient connection errors, but only if no
    chunks have been yielded yet (mid-stream errors are raised immediately to
    avoid sending duplicate tokens to the client).
    """
    last_exc: Exception | None = None
    for attempt, delay in enumerate([0.0] + list(_RETRY_DELAYS)):
        if attempt > 0:
            logger.warning("chat_stream retry %d/%d after %.1fs (model=%s)",
                           attempt, len(_RETRY_DELAYS), delay, model)
            await asyncio.sleep(delay)
        yielded = 0
        try:
            stream = await get_client().chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                **(extra_body or {}),
            )
            async for chunk in stream:
                yielded += 1
                yield chunk
            return  # completed successfully
        except _RETRYABLE as e:
            if yielded > 0:
                raise  # mid-stream — can't safely retry
            last_exc = e
    raise last_exc  # type: ignore[misc]


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
Проанализируй диалог и извлеки ТОЛЬКО важные долгосрочные факты о пользователе.

СОХРАНЯЙ (важно для будущих диалогов):
- Имя, возраст, профессия, место работы/учёбы
- Предпочтения в общении (формальное/неформальное, краткие/подробные ответы)
- Хобби, интересы, любимые вещи
- Навыки и уровень знаний (программист, студент, учёный и т.д.)
- Личные обстоятельства (семья, город, часовой пояс)
- Постоянные предпочтения ("люблю Python", "предпочитаю краткие ответы")

НЕ СОХРАНЯЙ (мусор, одноразовые запросы):
- Что пользователь искал в интернете
- Какие задачи решал (примеры, уравнения)
- Разовые вопросы ("какая погода", "кто победил")
- Тема текущего разговора (это и так видно из истории)
- Запросы на генерацию кода/текста/изображений
- Что пользователь тестировал или проверял
- Факты о языке общения

Формат: по одному факту на строку, без нумерации.
Каждый факт должен быть самодостаточным предложением (не одно слово).
Примеры хороших фактов: "Пользователя зовут Александр", "Работает программистом", "Предпочитает краткие ответы"
Если важных фактов нет — верни пустую строку.
Пиши только на русском языке.

Диалог:
{dialogue}"""


async def generate_image(prompt: str, *, model: str = "qwen-image-lightning") -> str:
    """
    Try to generate an image via MWS API.
    First try /images/generations, then fallback to chat completions.
    Returns markdown with image URL/base64.
    """
    client = get_client()

    # Attempt 1: OpenAI-compatible images endpoint
    try:
        response = await client.images.generate(
            model=model,
            prompt=prompt,
            n=1,
            size="1024x1024",
        )
        if response.data:
            img = response.data[0]
            url = img.url or ""
            b64 = getattr(img, "b64_json", None) or ""
            if url:
                return f"![Сгенерированное изображение]({url})"
            elif b64:
                return f"![Сгенерированное изображение](data:image/png;base64,{b64})"
    except Exception as e:
        logger.warning("images.generate failed (model=%s): %s", model, e)

    # Attempt 2: Use chat completions with image model
    try:
        completion = await chat_complete(
            model=model,
            messages=[{"role": "user", "content": f"Generate an image: {prompt}"}],
            temperature=0.7,
        )
        content = completion.choices[0].message.content or ""
        if content:
            return content
    except Exception as e:
        logger.warning("chat_complete with image model failed: %s", e)

    raise RuntimeError(f"Модель {model} не поддерживает генерацию изображений через доступные API endpoints")


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
