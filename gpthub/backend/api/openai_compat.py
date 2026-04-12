"""
OpenAI-compatible API endpoints.

GET  /v1/models              — virtual (auto-*) + real MWS models
POST /v1/chat/completions    — proxy to MWS, streaming + non-streaming
POST /v1/embeddings          — proxy to bge-m3
"""
import asyncio
import json
import time
import logging
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from core import mws_client
from core.model_registry import MODELS, VIRTUAL_MODELS, _VIRTUAL_MAP
from core.smart_router import route as smart_route, detect_multimodal, RoutingDecision, _extract_text
from core.memory_manager import get_manager
from core.reasoning_parser import StreamingReasoningParser, parse as parse_reasoning, build_reasoning_system_prompt, NATIVE_REASONING_MODELS
from core.analytics_store import get_store as get_analytics
from core.web_search import fetch_page, detect_urls, format_page_content

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers: OpenAI response shapes
# ---------------------------------------------------------------------------

def _ts() -> int:
    return int(time.time())


def _model_object(model_id: str) -> dict:
    return {"id": model_id, "object": "model", "created": 1700000000, "owned_by": "mws"}


# ---------------------------------------------------------------------------
# GET /v1/models
# ---------------------------------------------------------------------------

# Models that should NOT appear in the chat model selector
# (non-chat models, or models unavailable on MWS)
_HIDDEN_MODELS = {
    "bge-m3",                # embedding model, not for chat
    "whisper-turbo-local",   # audio transcription only
    "whisper-medium",        # audio transcription only
    "qwen-image-lightning",  # image generation only (handled by Smart Router)
    "qwen-image",            # image generation only
    "T-pro-it-1.0",          # not available on MWS API for our key
}


@router.get("/v1/models")
async def list_models():
    """
    Returns virtual routing aliases first, then chat-capable real MWS models.
    Non-chat models (embeddings, audio, image-gen) are hidden from the dropdown.
    """
    entries = [_model_object(m) for m in VIRTUAL_MODELS]
    entries += [_model_object(m) for m in MODELS if m not in _HIDDEN_MODELS]
    return {"object": "list", "data": entries}


# ---------------------------------------------------------------------------
# POST /v1/chat/completions — request schema
# ---------------------------------------------------------------------------

class Message(BaseModel):
    role: str
    content: str | list | None = None  # list for vision (content parts)
    name: str | None = None


class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    stream: bool = False
    temperature: float = 0.7
    max_tokens: int | None = None
    # pass-through fields OpenWebUI may send
    top_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    stop: list[str] | str | None = None
    user: str | None = None


# ---------------------------------------------------------------------------
# POST /v1/chat/completions
# ---------------------------------------------------------------------------

@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """
    Proxy chat completions to MWS.

    - Resolves virtual model aliases via Smart Router (keyword + embedding).
    - Supports both streaming (SSE) and non-streaming responses.
    - Adds X-GPTHub-* headers so clients and dashboard can see routing decisions.
    """
    # Parse body manually to tolerate extra fields OpenWebUI sends
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    try:
        req = ChatRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Resolve virtual model → real model via Smart Router
    messages_raw = [m.model_dump(exclude_none=True) for m in req.messages]
    has_image, has_audio = detect_multimodal(messages_raw)

    is_auto = req.model == "auto"
    virtual_hint = req.model if req.model in _VIRTUAL_MAP and not is_auto else None

    if is_auto or req.model in _VIRTUAL_MAP:
        decision: RoutingDecision = await smart_route(
            messages_raw,
            has_image=has_image,
            has_audio=has_audio,
            virtual_hint=virtual_hint,
        )
        real_model = decision.model
        routing_reason = decision.reason
        routing_method = decision.method
    else:
        # User picked a real model explicitly — pass through
        real_model = req.model
        routing_reason = "explicit"
        routing_method = "passthrough"

    # Suppress reasoning_content display for non-reasoning virtual models.
    # Only auto-reasoning (deepseek/QwQ) and explicit reasoning model picks show thinking.
    _REASONING_VIRTUAL = {"auto-reasoning"}
    suppress_reasoning = (
        req.model in _VIRTUAL_MAP
        and req.model not in _REASONING_VIRTUAL
        and real_model not in NATIVE_REASONING_MODELS
    )

    logger.info(
        "chat_completions model=%s → %s [%s: %s] stream=%s",
        req.model, real_model, routing_method, routing_reason, req.stream,
    )

    # --- Memory inject (before request) ---
    user_id = req.user or "default"
    # Skip memory for OpenWebUI internal system requests (title/tag generation etc.)
    _is_system_request = _detect_system_request(messages_raw)
    messages_with_mem = (
        messages_raw if _is_system_request
        else await _inject_memories(messages_raw, user_id)
    )

    # --- URL fetch inject (when user pastes a URL in message) ---
    if not _is_system_request:
        messages_with_mem = await _inject_url_context(messages_with_mem)

    # --- Image generation special handling ---
    if real_model in ("qwen-image-lightning", "qwen-image"):
        return await _handle_image_generation(
            req, messages_raw, real_model, routing_method, routing_reason, user_id,
            stream=req.stream,
        )

    # --- Reasoning system prompt inject ---
    messages_final = _inject_reasoning_prompt(real_model, messages_with_mem)

    routing_meta = {"model": real_model, "reason": routing_reason, "method": routing_method}
    t0 = time.time()

    if req.stream:
        return StreamingResponse(
            _stream_sse(real_model, messages_final, req, routing_meta, user_id,
                        routing_method=routing_method, routing_reason=routing_reason,
                        requested=req.model, t0=t0,
                        suppress_reasoning=suppress_reasoning,
                        skip_memory=_is_system_request),
            media_type="text/event-stream",
            headers={
                "X-GPTHub-Model": real_model,
                "X-GPTHub-Requested-Model": req.model,
                "X-GPTHub-Routing-Method": routing_method,
                "X-GPTHub-Routing-Reason": routing_reason,
                "Cache-Control": "no-cache",
            },
        )

    # Non-streaming
    try:
        completion = await mws_client.chat_complete(
            model=real_model,
            messages=messages_final,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )
    except Exception as e:
        logger.exception("MWS error (non-stream) model=%s", real_model)
        # Return a user-friendly error as a normal chat response (not HTTP error)
        # This prevents OpenWebUI from showing raw JSON error + freezing
        err_msg = str(e)
        if "Invalid model name" in err_msg:
            friendly = f"⚠️ Модель `{real_model}` недоступна на сервере MWS. Попробуйте другую модель."
        elif "404" in err_msg:
            friendly = f"⚠️ Модель `{real_model}` не найдена. Возможно, она временно недоступна."
        elif "500" in err_msg:
            friendly = f"⚠️ Внутренняя ошибка сервера при обращении к модели `{real_model}`. Попробуйте позже."
        else:
            friendly = f"⚠️ Ошибка при обращении к модели `{real_model}`: {err_msg[:200]}"

        return JSONResponse(content={
            "id": f"gpthub-err-{int(time.time())}",
            "object": "chat.completion",
            "model": real_model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": friendly},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }, headers={
            "X-GPTHub-Model": real_model,
            "X-GPTHub-Requested-Model": req.model,
            "X-GPTHub-Routing-Method": routing_method,
            "X-GPTHub-Routing-Reason": routing_reason,
        })

    latency_ms = (time.time() - t0) * 1000

    # --- Merge reasoning_content into content (MWS-specific field) ---
    msg = completion.choices[0].message
    raw_content = msg.content or ""
    reasoning = (getattr(msg, "reasoning_content", None) or "") if not suppress_reasoning else ""
    if reasoning and not raw_content:
        # Model only emitted reasoning, no final answer — treat reasoning as answer
        combined = reasoning
    elif reasoning:
        # Wrap reasoning in <think> so the parser renders it as a blockquote
        combined = f"<think>{reasoning}</think>\n\n{raw_content}"
    else:
        combined = raw_content

    # --- Reasoning parse (non-stream) ---
    parsed_text = parse_reasoning(combined)
    completion.choices[0].message.content = parsed_text
    assistant_text = combined  # raw (pre-parse) for memory

    # --- Analytics + Memory (fire-and-forget) ---
    if not _is_system_request:
        asyncio.create_task(_memorize(user_id, messages_raw, assistant_text))
    asyncio.create_task(_record_analytics(
        user_id=user_id, requested=req.model, routed_to=real_model,
        method=routing_method, reason=routing_reason, latency_ms=latency_ms,
    ))

    data = completion.model_dump()
    data["model"] = real_model
    # Remove MWS-specific fields OpenWebUI doesn't know about
    _strip_extra_fields(data)
    if data.get("choices"):
        data["choices"][0].get("message", {}).pop("reasoning_content", None)
        data["choices"][0].get("message", {}).pop("reasoning", None)
    return JSONResponse(content=data, headers={
        "X-GPTHub-Model": real_model,
        "X-GPTHub-Requested-Model": req.model,
        "X-GPTHub-Routing-Method": routing_method,
        "X-GPTHub-Routing-Reason": routing_reason,
    })


async def _stream_sse(
    model: str,
    messages: list[dict],
    req: ChatRequest,
    routing_meta: dict | None = None,
    user_id: str = "default",
    routing_method: str = "passthrough",
    routing_reason: str = "",
    requested: str = "",
    t0: float = 0.0,
    suppress_reasoning: bool = False,
    skip_memory: bool = False,
) -> AsyncIterator[bytes]:
    """Yield SSE bytes from MWS streaming response."""
    # NOTE: do NOT send a routing metadata chunk — OpenWebUI cannot parse
    # a chunk that lacks 'id' / valid 'choices' and will hang the UI.
    # Routing info is already in X-GPTHub-* response headers.

    rparser = StreamingReasoningParser()
    collected_raw: list[str] = []   # raw text (pre-parse) for memory extraction
    in_reasoning = False             # tracks whether we're inside reasoning_content phase

    try:
        async for chunk in mws_client.chat_stream(
            model=model,
            messages=messages,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        ):
            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            delta_obj = choice.delta

            # MWS models emit reasoning in delta.reasoning_content (content=null).
            # Convert to <think>…</think> so StreamingReasoningParser can wrap it.
            # When suppress_reasoning=True (non-reasoning virtual models), skip the thinking
            # and only forward the final content.
            content: str | None = delta_obj.content
            reasoning: str | None = (
                getattr(delta_obj, "reasoning_content", None)
                if not suppress_reasoning else None
            )

            if reasoning and content is None:
                # Inject opening <think> tag on first reasoning chunk
                if not in_reasoning:
                    in_reasoning = True
                    text_to_feed = "<think>" + reasoning
                else:
                    text_to_feed = reasoning
            elif content is not None and in_reasoning:
                # First real-content chunk after reasoning phase — close <think>
                in_reasoning = False
                text_to_feed = "</think>" + content
            elif suppress_reasoning and content is None and getattr(delta_obj, "reasoning_content", None):
                # Suppressed reasoning chunk — skip entirely, wait for actual content
                continue
            elif content is not None:
                text_to_feed = content
            else:
                # finish_reason / usage chunk — forward as-is with null content
                data = chunk.model_dump()
                data["model"] = model
                _strip_extra_fields(data)
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode()
                continue

            collected_raw.append(text_to_feed)
            transformed = rparser.feed(text_to_feed)

            # Re-pack chunk: replace delta.content with transformed text,
            # strip MWS-specific fields OpenWebUI doesn't understand
            data = chunk.model_dump()
            data["model"] = model
            data["choices"][0]["delta"]["content"] = transformed
            data["choices"][0]["delta"].pop("reasoning_content", None)
            data["choices"][0]["delta"].pop("reasoning", None)
            _strip_extra_fields(data)

            # Skip empty-string chunks while parser is buffering <think> content
            if transformed == "" and not choice.finish_reason:
                continue

            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode()

        # Close unclosed <think> if stream ended mid-reasoning
        if in_reasoning:
            tail_text = rparser.feed("</think>")
            if tail_text:
                yield f"data: {json.dumps(_make_delta_chunk(model, 'close-think', tail_text), ensure_ascii=False)}\n\n".encode()

        # Flush remaining parser buffer
        tail = rparser.flush()
        if tail:
            yield f"data: {json.dumps(_make_delta_chunk(model, 'flush', tail), ensure_ascii=False)}\n\n".encode()

    except Exception as e:
        logger.exception("MWS error (stream)")
        # Emit error as a valid delta chunk so OpenWebUI doesn't freeze
        err_chunk = _make_delta_chunk(model, "error", f"\n\n⚠️ Ошибка: {e}")
        err_chunk["choices"][0]["finish_reason"] = "stop"
        yield f"data: {json.dumps(err_chunk, ensure_ascii=False)}\n\n".encode()
    finally:
        yield b"data: [DONE]\n\n"

    # --- Analytics + Memory after stream ends (fire-and-forget) ---
    latency_ms = (time.time() - t0) * 1000 if t0 else None
    asyncio.create_task(_record_analytics(
        user_id=user_id, requested=requested, routed_to=model,
        method=routing_method, reason=routing_reason, latency_ms=latency_ms,
    ))
    if collected_raw and not skip_memory:
        assistant_text = "".join(collected_raw)
        asyncio.create_task(_memorize(user_id, messages, assistant_text))


# ---------------------------------------------------------------------------
# Reasoning helpers
# ---------------------------------------------------------------------------

def _inject_reasoning_prompt(model: str, messages: list[dict]) -> list[dict]:
    """
    For models that don't natively support <think>, inject a system prompt
    instructing them to reason inside <think>...</think>.
    Returns the same list if no injection needed.
    """
    new_system = build_reasoning_system_prompt(model, _get_system_content(messages))
    if new_system is None:
        return messages  # native model — nothing to do

    result = [m for m in messages if m.get("role") != "system"]
    result.insert(0, {"role": "system", "content": new_system})
    return result


def _get_system_content(messages: list[dict]) -> str | None:
    for m in messages:
        if m.get("role") == "system":
            return m.get("content") or None
    return None


def _make_delta_chunk(model: str, chunk_id: str, content: str) -> dict:
    """Build a minimal SSE chat.completion.chunk dict for injected content."""
    return {
        "id": f"gpthub-{chunk_id}",
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
    }


# Fields from MWS API that OpenWebUI doesn't understand and may trip on
_EXTRA_FIELDS = {"service_tier", "system_fingerprint"}

def _strip_extra_fields(data: dict) -> None:
    """Remove MWS-specific top-level fields in-place."""
    for f in _EXTRA_FIELDS:
        data.pop(f, None)


# ---------------------------------------------------------------------------
# System request detection (OpenWebUI internal calls — skip memory)
# ---------------------------------------------------------------------------

import re as _re_sys

_SYSTEM_REQUEST_PATTERNS = [
    # OpenWebUI auto-generates chat titles and tags after first message
    r"(?i)(generate|create|write).{0,30}(title|tag|heading|name).{0,30}(chat|conversation|message)",
    r"(?i)(придумай|создай|напиши|сгенерируй).{0,30}(заголовок|название|тег).{0,30}(чат|диалог|беседа)",
    r"(?i)^(here is|here are).{0,20}(tag|title)",
    r"(?i)(short title|краткий заголовок|короткий заголовок).{0,30}(emoji|эмодзи)",
    r"(?i)generate (a )?(concise|short|brief) title",
]


def _detect_system_request(messages: list[dict]) -> bool:
    """Return True if this looks like an internal OpenWebUI system request (title/tag generation)."""
    for msg in messages:
        if msg.get("role") not in ("user", "system"):
            continue
        content = msg.get("content") or ""
        if isinstance(content, str):
            for pat in _SYSTEM_REQUEST_PATTERNS:
                if _re_sys.search(pat, content):
                    return True
    return False


# ---------------------------------------------------------------------------
# Memory helpers
# ---------------------------------------------------------------------------

async def _inject_memories(messages: list[dict], user_id: str) -> list[dict]:
    """
    Search for relevant memories and prepend them to the system prompt.
    Returns a new messages list; original is not mutated.
    """
    try:
        manager = await get_manager()
        query = _extract_text(messages)
        memories = await manager.search_memories(user_id, query, top_k=3, min_score=0.50)
    except Exception:
        logger.warning("Memory inject failed, continuing without memories", exc_info=True)
        return messages

    if not memories:
        return messages

    mem_block = (
        "Контекст о пользователе (используй естественно, НЕ упоминай что у тебя есть память/заметки):\n"
        + "\n".join(f"- {m}" for m in memories)
    )

    # Prepend to existing system message or insert a new one at position 0
    result = list(messages)
    if result and result[0].get("role") == "system":
        existing = result[0].get("content") or ""
        result[0] = {**result[0], "content": f"{mem_block}\n\n{existing}".strip()}
    else:
        result.insert(0, {"role": "system", "content": mem_block})

    logger.debug("Injected %d memories for user=%s", len(memories), user_id)
    return result


async def _memorize(user_id: str, messages: list[dict], assistant_reply: str) -> None:
    """Fire-and-forget: extract facts from the completed exchange and save them."""
    try:
        manager = await get_manager()
        full_exchange = messages + [{"role": "assistant", "content": assistant_reply}]
        await manager.extract_and_save(user_id, full_exchange)
    except Exception:
        logger.warning("Background memorise failed for user=%s", user_id, exc_info=True)


async def _record_analytics(
    *, user_id: str, requested: str, routed_to: str,
    method: str, reason: str, latency_ms: float | None,
) -> None:
    try:
        store = await get_analytics()
        await store.record(user_id=user_id, requested=requested, routed_to=routed_to,
                           method=method, reason=reason, latency_ms=latency_ms)
    except Exception:
        logger.warning("Analytics record failed", exc_info=True)


# ---------------------------------------------------------------------------
# POST /v1/embeddings
# ---------------------------------------------------------------------------

class EmbedRequest(BaseModel):
    input: list[str] | str
    model: str = "bge-m3"
    encoding_format: str = "float"


@router.post("/v1/embeddings")
async def embeddings(req: EmbedRequest):
    texts = req.input if isinstance(req.input, list) else [req.input]
    try:
        vectors = await mws_client.embed(texts, model=req.model)
    except Exception as e:
        logger.exception("MWS embed error")
        raise HTTPException(status_code=502, detail=f"Upstream error: {e}")

    data = [
        {"object": "embedding", "index": i, "embedding": vec}
        for i, vec in enumerate(vectors)
    ]
    return {
        "object": "list",
        "data": data,
        "model": req.model,
        "usage": {"prompt_tokens": sum(len(t.split()) for t in texts), "total_tokens": sum(len(t.split()) for t in texts)},
    }


# ---------------------------------------------------------------------------
# URL Fetch injection (when user pastes a link in chat)
# ---------------------------------------------------------------------------

def _last_user_text(messages: list[dict]) -> str:
    """Extract text from the last user message only."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            elif isinstance(content, list):
                return " ".join(
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
    return ""


async def _inject_url_context(messages: list[dict]) -> list[dict]:
    """
    If the user's last message contains URLs, fetch their content and inject
    into the system prompt so the model can read and discuss the page.
    Web search is handled natively by OpenWebUI's built-in search feature.
    """
    user_text = _last_user_text(messages)
    if not user_text.strip():
        return messages

    urls = detect_urls(user_text)
    context_blocks: list[str] = []
    for url in urls[:2]:
        try:
            page_text = await fetch_page(url, max_chars=5000)
            if page_text and not page_text.startswith("[Ошибка"):
                context_blocks.append(format_page_content(url, page_text))
                logger.info("Fetched page content from %s (%d chars)", url, len(page_text))
        except Exception:
            logger.warning("URL fetch failed for %s", url, exc_info=True)

    if not context_blocks:
        return messages

    web_context = "\n\n".join(context_blocks)
    result = list(messages)
    if result and result[0].get("role") == "system":
        existing = result[0].get("content") or ""
        result[0] = {**result[0], "content": f"{existing}\n\n{web_context}".strip()}
    else:
        result.insert(0, {"role": "system", "content": web_context})

    return result


# ---------------------------------------------------------------------------
# Image Generation handler
# ---------------------------------------------------------------------------

async def _handle_image_generation(
    req: "ChatRequest",
    messages: list[dict],
    model: str,
    routing_method: str,
    routing_reason: str,
    user_id: str,
    *,
    stream: bool = False,
) -> JSONResponse | StreamingResponse:
    """
    Handle image generation requests.
    Tries MWS images endpoint; if unsupported, returns clear error.
    Supports both streaming and non-streaming responses so OpenWebUI
    doesn't hang when it sends stream=true.
    """
    # Extract the image prompt from user's last message
    prompt = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            prompt = content if isinstance(content, str) else str(content)
            break

    try:
        result = await mws_client.generate_image(prompt, model=model)
    except Exception as e:
        logger.warning("Image generation failed: %s", e)
        result = (
            f"⚠️ Генерация изображений временно недоступна.\n\n"
            f"Модель `{model}` не поддерживает генерацию через текущий API.\n"
            f"Ошибка: {e}"
        )

    hdrs = {
        "X-GPTHub-Model": model,
        "X-GPTHub-Requested-Model": req.model,
        "X-GPTHub-Routing-Method": routing_method,
        "X-GPTHub-Routing-Reason": routing_reason,
    }

    if stream:
        # OpenWebUI sent stream=true — respond with a proper SSE stream
        async def _img_stream():
            chunk = _make_delta_chunk(model, "img", result)
            chunk["choices"][0]["finish_reason"] = None
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode()
            # Close chunk
            done = _make_delta_chunk(model, "img-done", "")
            done["choices"][0]["finish_reason"] = "stop"
            yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n".encode()
            yield b"data: [DONE]\n\n"

        return StreamingResponse(
            _img_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", **hdrs},
        )

    return JSONResponse(content={
        "id": f"gpthub-img-{int(time.time())}",
        "object": "chat.completion",
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": result},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }, headers=hdrs)


# ---------------------------------------------------------------------------
# POST /v1/audio/transcriptions — proxy to MWS
# ---------------------------------------------------------------------------

@router.post("/v1/audio/transcriptions")
async def audio_transcriptions(request: Request):
    """
    Proxy audio transcription requests to MWS Whisper API.
    Accepts multipart form data with 'file' field.
    """
    try:
        form = await request.form()
        audio_file = form.get("file")
        model = form.get("model", "whisper-turbo-local")

        if audio_file is None:
            raise HTTPException(status_code=400, detail="Missing 'file' field")

        # Read file content
        content = await audio_file.read()

        # Size check (500MB max)
        if len(content) > 500 * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail="Файл слишком большой. Максимальный размер: 500MB",
            )

        import httpx as _httpx
        import os

        base_url = os.environ.get("MWS_API_BASE", "https://api.gpt.mws.ru/v1")
        api_key = os.environ["MWS_API_KEY"]

        async with _httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                f"{base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (audio_file.filename or "audio.wav", content)},
                data={"model": model},
            )
            resp.raise_for_status()
            return JSONResponse(content=resp.json())

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Audio transcription error")
        raise HTTPException(status_code=502, detail=f"Ошибка транскрипции: {e}")
