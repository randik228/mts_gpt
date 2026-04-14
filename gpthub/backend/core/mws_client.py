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
Проанализируй диалог. Извлеки ТОЛЬКО долгосрочные факты о пользователе, полезные в будущих диалогах.

СОХРАНЯЙ:
- Имя, возраст, профессия, место работы/учёбы
- Навыки и экспертиза (язык программирования, область знаний)
- Предпочтения (стиль общения, инструменты, технологии)
- Личные обстоятельства (город, семья, проекты)
- Долгосрочные цели и задачи

НЕ СОХРАНЯЙ:
- Разовые запросы (поиск, вычисления, генерация картинок/кода/презентаций)
- Тему текущего разговора
- Факты о языке общения
- Что пользователь тестировал/проверял

Верни JSON-массив (может быть пустой []):
[{{"fact": "краткий факт", "tag": "тег", "importance": 0.0-1.0}}]

Теги: preference, skill, fact, project, context
Важность: 0.9-1.0 = имя/профессия, 0.7-0.8 = навыки/проекты, 0.5-0.6 = предпочтения, <0.5 = не сохранять

Примеры:
[{{"fact": "Зовут Александр", "tag": "fact", "importance": 1.0}},
 {{"fact": "Senior Python разработчик в Яндексе", "tag": "skill", "importance": 0.9}},
 {{"fact": "Предпочитает краткие ответы", "tag": "preference", "importance": 0.6}}]

Если важных фактов НЕТ — верни []

Диалог:
{dialogue}"""


_IMAGE_TIMEOUT = 25  # seconds — fail fast, don't hang the UI


async def generate_image(prompt: str, *, model: str = "qwen-image-lightning") -> str:
    """
    Try to generate an image via MWS API.
    First try /images/generations (with a strict timeout),
    then fallback to chat completions.
    Returns markdown with image URL/base64.
    """
    client = get_client()

    # Attempt 1: OpenAI-compatible images endpoint (strict timeout)
    try:
        logger.info("generate_image: attempting images.generate model=%s prompt=%s", model, prompt[:60])
        response = await asyncio.wait_for(
            client.images.generate(
                model=model,
                prompt=prompt,
                n=1,
                size="1024x1024",
            ),
            timeout=_IMAGE_TIMEOUT,
        )
        logger.info("generate_image: images.generate returned data=%d", len(response.data) if response.data else 0)
        if response.data:
            img = response.data[0]
            url = img.url or ""
            b64 = getattr(img, "b64_json", None) or ""
            if url:
                return f"![Сгенерированное изображение]({url})"
            elif b64:
                return f"![Сгенерированное изображение](data:image/png;base64,{b64})"
    except asyncio.TimeoutError:
        logger.warning("images.generate timed out after %ds (model=%s)", _IMAGE_TIMEOUT, model)
    except Exception as e:
        logger.warning("images.generate failed (model=%s): %s: %s", model, type(e).__name__, e)

    # Attempt 2: Use chat completions with image model (fallback, also with timeout)
    logger.info("generate_image: falling back to chat_complete model=%s", model)
    try:
        completion = await asyncio.wait_for(
            chat_complete(
                model=model,
                messages=[{"role": "user", "content": f"Generate an image: {prompt}"}],
                temperature=0.7,
            ),
            timeout=_IMAGE_TIMEOUT,
        )
        content = completion.choices[0].message.content or ""
        if content:
            return content
    except asyncio.TimeoutError:
        logger.warning("chat_complete with image model timed out after %ds", _IMAGE_TIMEOUT)
    except Exception as e:
        logger.warning("chat_complete with image model failed: %s", e)

    raise RuntimeError(f"Модель {model} не поддерживает генерацию изображений через доступные API endpoints")


import json as _json
import re as _re_facts


# Pre-filter: skip LLM extraction for trivial messages
_TRIVIAL_MSG_PATTERNS = [
    _re_facts.compile(r"^(привет|здравствуй|hi|hello|hey|добр\w+ (утро|день|вечер))[\s!.?]*$", _re_facts.I),
    _re_facts.compile(r"^(спасибо|thanks|thank you|пока|до свидания|bye)[\s!.?]*$", _re_facts.I),
    _re_facts.compile(r"^\d[\d\s+\-*/=.,()]+$"),  # math expressions
    _re_facts.compile(r"^(да|нет|ок|ok|ладно|хорошо|понятно|ясно|угу)[\s!.?]*$", _re_facts.I),
]


def _is_trivial_message(text: str) -> bool:
    """Check if user message is too trivial to extract facts from."""
    t = text.strip()
    if len(t) < 10:
        return True
    for pat in _TRIVIAL_MSG_PATTERNS:
        if pat.match(t):
            return True
    return False


async def extract_facts(messages: list[dict]) -> list[dict]:
    """
    Extract memorable facts from a conversation via LLM.
    Returns list of dicts: [{"fact": str, "tag": str, "importance": float}, ...]
    Pre-filters trivial messages to avoid wasting LLM calls.
    """
    # Find last user message for pre-filter
    last_user = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            last_user = content if isinstance(content, str) else str(content)
            break

    if _is_trivial_message(last_user):
        logger.debug("extract_facts: skipping trivial message: %s", last_user[:40])
        return []

    dialogue = "\n".join(
        f"{m['role'].upper()}: {m.get('content', '')}" for m in messages[-6:]  # last 3 turns max
    )
    response = await chat_complete(
        model="gpt-oss-20b",
        messages=[
            {"role": "user", "content": _EXTRACT_FACTS_PROMPT.format(dialogue=dialogue)}
        ],
        temperature=0.0,
        max_tokens=500,
    )
    msg = response.choices[0].message
    # Only use content (not reasoning_content) — reasoning models put chain-of-thought
    # in reasoning_content which is NOT the actual answer and must not be parsed as facts.
    raw = (msg.content or "").strip()
    rc = getattr(msg, "reasoning_content", None) or ""

    logger.info("extract_facts: content=%d chars, reasoning=%d chars", len(raw), len(rc))
    if raw:
        logger.info("extract_facts: content preview: %s", raw[:200])
    if rc and not raw:
        logger.info("extract_facts: reasoning preview: %s", rc[:200])

    # If content is empty, try to extract JSON from reasoning_content as last resort
    if not raw:
        # Only use reasoning_content if it actually contains a JSON array
        if "[" in rc and "]" in rc:
            raw = rc.strip()
            logger.info("extract_facts: using reasoning_content as fallback")
        else:
            logger.info("extract_facts: model returned empty content, no JSON in reasoning, skipping")
            return []

    # Parse JSON from response (handle markdown fences)
    text = raw
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Find JSON array in the text
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        logger.info("extract_facts: no JSON array found in response: %s", text[:200])
        return []

    try:
        facts = _json.loads(text[start:end + 1])
    except _json.JSONDecodeError:
        logger.warning("extract_facts: failed to parse JSON: %s", text[:200])
        return []

    # Validate and filter
    result = []
    for item in facts:
        if not isinstance(item, dict):
            continue
        fact = item.get("fact", "").strip()
        tag = item.get("tag", "fact")
        importance = float(item.get("importance", 0.5))
        if not fact or len(fact) < 5 or importance < 0.5:
            continue
        if tag not in ("preference", "skill", "fact", "project", "context"):
            tag = "fact"
        result.append({"fact": fact, "tag": tag, "importance": importance})

    return result
