"""
OpenAI-compatible API endpoints.

GET  /v1/models              — virtual (auto-*) + real MWS models
POST /v1/chat/completions    — proxy to MWS, streaming + non-streaming
POST /v1/embeddings          — proxy to bge-m3
"""
import asyncio
import json
import os
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
from core.web_search import fetch_page, detect_urls, format_page_content, search as web_search
from core.pptx_builder import generate_pptx, parse_presentation_json

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

    # Log extra fields OpenWebUI sends (for debugging user identification)
    _extra_keys = set(body.keys()) - {"model", "messages", "stream", "temperature", "max_tokens", "top_p", "frequency_penalty", "presence_penalty", "stop", "user"}
    if _extra_keys:
        logger.debug("chat_completions extra body keys: %s", {k: str(body[k])[:120] for k in _extra_keys})

    try:
        req = ChatRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    # --- Resolve user_id: prefer req.user, fall back to OpenWebUI metadata ---
    _resolved_user = req.user
    meta = body.get("metadata") or {}
    if not _resolved_user:
        # OpenWebUI sends metadata with user info in newer versions
        # Try multiple fields in priority order
        user_obj = meta.get("user")
        if isinstance(user_obj, dict):
            _resolved_user = user_obj.get("email") or user_obj.get("name") or user_obj.get("id")
        if not _resolved_user:
            _resolved_user = meta.get("user_email") or meta.get("user_id")
    if not _resolved_user:
        _resolved_user = meta.get("chat_id")
    if not _resolved_user:
        _resolved_user = "default"
    # Store resolved user back on req for downstream use
    req.user = _resolved_user
    # Extract chat_id for memory association
    _chat_id = meta.get("chat_id")
    logger.debug("Resolved user=%s chat_id=%s from metadata keys=%s", _resolved_user, _chat_id, list(meta.keys())[:10])

    # Resolve virtual model → real model via Smart Router
    messages_raw = [m.model_dump(exclude_none=True) for m in req.messages]
    has_image, has_audio = detect_multimodal(messages_raw)

    # --- Audio transcription: transcribe audio parts BEFORE routing ---
    if has_audio:
        from core.smart_router import transcribe_audio_from_message
        logger.info("Audio detected in chat — transcribing before routing")
        messages_raw = await transcribe_audio_from_message(messages_raw)
        has_audio = False  # audio replaced with text, re-route as text

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
        "chat_completions model=%s → %s [%s: %s] stream=%s user=%s",
        req.model, real_model, routing_method, routing_reason, req.stream, req.user,
    )

    # --- Memory inject (before request) ---
    user_id = req.user or "default"
    chat_id = _chat_id  # from metadata resolution above
    # Skip memory for OpenWebUI internal system requests (title/tag generation etc.)
    # Also treat requests without a user as system requests (OpenWebUI title/tag gen)
    _is_system_request = _detect_system_request(messages_raw) or user_id == "default"
    messages_with_mem = (
        messages_raw if _is_system_request
        else await _inject_memories(messages_raw, user_id)
    )

    # --- URL fetch inject (when user pastes a URL in message) ---
    if not _is_system_request:
        messages_with_mem = await _inject_url_context(messages_with_mem)

    # --- Core system prompt: file priority + behaviour ---
    if not _is_system_request:
        messages_with_mem = _inject_core_system_prompt(messages_with_mem)

    # --- Image generation special handling ---
    if real_model in ("qwen-image-lightning", "qwen-image"):
        return await _handle_image_generation(
            req, messages_raw, real_model, routing_method, routing_reason, user_id,
            stream=req.stream,
        )

    # --- Presentation generation special handling ---
    if routing_reason == "presentation generation request":
        return await _handle_presentation_generation(
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
                        skip_memory=_is_system_request,
                        chat_id=chat_id),
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

    # --- Uncertainty detection → auto web search retry ---
    if not _is_system_request and _detect_uncertainty(raw_content):
        enriched_answer = await _web_search_and_enrich(
            messages_final, real_model, req.temperature, req.max_tokens,
        )
        if enriched_answer:
            combined = enriched_answer
            raw_content = enriched_answer

    # --- Reasoning parse (non-stream) ---
    parsed_text = parse_reasoning(combined)
    completion.choices[0].message.content = parsed_text
    assistant_text = combined  # raw (pre-parse) for memory

    # --- Analytics + Memory (fire-and-forget) ---
    if not _is_system_request:
        asyncio.create_task(_memorize(user_id, messages_raw, assistant_text, chat_id))
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
    chat_id: str | None = None,
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

    # --- Streaming uncertainty → auto web search append ---
    if collected_raw and not skip_memory:
        _stream_text = "".join(collected_raw)
        if _detect_uncertainty(_stream_text):
            try:
                _search_answer = await _web_search_and_enrich(
                    messages, model, req.temperature, req.max_tokens,
                )
                if _search_answer:
                    _supplement = "\n\n---\n\n🔍 **Нашёл в интернете:**\n\n" + _search_answer
                    yield f"data: {json.dumps(_make_delta_chunk(model, 'search', _supplement), ensure_ascii=False)}\n\n".encode()
                    collected_raw.append(_supplement)
                    logger.info("Stream: appended web search results (%d chars)", len(_supplement))
            except Exception:
                logger.warning("Stream web search retry failed", exc_info=True)

    yield b"data: [DONE]\n\n"

    # --- Analytics + Memory after stream ends (fire-and-forget) ---
    latency_ms = (time.time() - t0) * 1000 if t0 else None
    asyncio.create_task(_record_analytics(
        user_id=user_id, requested=requested, routed_to=model,
        method=routing_method, reason=routing_reason, latency_ms=latency_ms,
    ))
    if collected_raw and not skip_memory:
        assistant_text = "".join(collected_raw)
        asyncio.create_task(_memorize(user_id, messages, assistant_text, chat_id))


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
        memories = await manager.search_memories(user_id, query, top_k=5, min_score=0.30)
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

    logger.info("Injected %d memories for user=%s: %s", len(memories), user_id, [m[:40] for m in memories])
    return result


async def _memorize(user_id: str, messages: list[dict], assistant_reply: str, source_chat: str | None = None) -> None:
    """Fire-and-forget: extract facts from the completed exchange and save them."""
    logger.info("_memorize START user=%s chat=%s msgs=%d reply_len=%d", user_id, source_chat, len(messages), len(assistant_reply))
    try:
        manager = await get_manager()
        full_exchange = messages + [{"role": "assistant", "content": assistant_reply}]
        saved = await manager.extract_and_save(user_id, full_exchange, source_chat=source_chat)
        logger.info("_memorize DONE user=%s saved=%d", user_id, len(saved))
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


# ---------------------------------------------------------------------------
# Core system prompt (file priority, search behaviour)
# ---------------------------------------------------------------------------

_CORE_SYSTEM_PROMPT = (
    "ВАЖНЫЕ ПРАВИЛА:\n"
    "1. Если к ПОСЛЕДНЕМУ сообщению пользователя прикреплены файлы — отвечай ИМЕННО про них. "
    "Предыдущие файлы из истории чата используй только если пользователь явно просит сравнить или вернуться к ним.\n"
    "2. Если ты не уверен в фактической информации или не знаешь ответа — честно скажи что не знаешь, "
    "НЕ выдумывай факты."
)


def _inject_core_system_prompt(messages: list[dict]) -> list[dict]:
    """Inject core behaviour instructions into the system prompt."""
    result = list(messages)
    if result and result[0].get("role") == "system":
        existing = result[0].get("content") or ""
        result[0] = {**result[0], "content": f"{existing}\n\n{_CORE_SYSTEM_PROMPT}".strip()}
    else:
        result.insert(0, {"role": "system", "content": _CORE_SYSTEM_PROMPT})
    return result


# ---------------------------------------------------------------------------
# Uncertainty detection & web search retry
# ---------------------------------------------------------------------------

import re as _re_unc

_UNCERTAINTY_PATTERNS = [
    _re_unc.compile(r"(?i)(я )?(не знаю|не могу (точно )?сказать|не (располагаю|обладаю|имею) (данн|информац|сведен))", _re_unc.I),
    _re_unc.compile(r"(?i)(у меня нет|мне не (известн|доступн)).{0,30}(данн|информац|сведен)", _re_unc.I),
    _re_unc.compile(r"(?i)(не удалось найти|не нашл).{0,20}(информац|данн|ответ)", _re_unc.I),
    _re_unc.compile(r"(?i)(мои (данные|знания) (ограничен|актуальн).{0,30}(до|по состоян))", _re_unc.I),
    _re_unc.compile(r"(?i)(i don'?t (know|have).{0,20}(information|data|answer))", _re_unc.I),
    _re_unc.compile(r"(?i)(не (могу|в состоянии) (проверить|подтвердить|уточнить))", _re_unc.I),
    _re_unc.compile(r"(?i)(к сожалению).{0,40}(не (знаю|могу|имею|располагаю))", _re_unc.I),
]


def _detect_uncertainty(text: str) -> bool:
    """Return True if model's response indicates it doesn't know the answer."""
    for pat in _UNCERTAINTY_PATTERNS:
        if pat.search(text):
            return True
    return False


async def _web_search_and_enrich(
    messages: list[dict], model: str, temperature: float, max_tokens: int | None
) -> str | None:
    """
    Extract a search query from the last user message, search the web,
    and re-ask the model with enriched context. Returns the new answer or None.
    """
    query = _last_user_text(messages).strip()
    if not query or len(query) < 5:
        return None

    # Shorten query for search (first 150 chars, no special chars)
    search_query = query[:150].strip()
    logger.info("Uncertainty detected — searching web for: %s", search_query[:80])

    try:
        results = await web_search(search_query, max_results=3)
    except Exception:
        logger.warning("Web search failed during uncertainty retry", exc_info=True)
        return None

    if not results:
        return None

    # Fetch top result pages for context
    context_parts: list[str] = []
    for r in results[:2]:
        url = r.get("url", "")
        snippet = r.get("snippet", "")
        title = r.get("title", "")
        if snippet:
            context_parts.append(f"**{title}** ({url})\n{snippet}")
        if url:
            try:
                page_text = await fetch_page(url, max_chars=3000)
                if page_text and not page_text.startswith("[Ошибка"):
                    context_parts.append(f"Содержимое {url}:\n{page_text[:3000]}")
            except Exception:
                pass

    if not context_parts:
        return None

    web_context = (
        "Результаты веб-поиска (используй для ответа, указывай источники):\n\n"
        + "\n\n---\n\n".join(context_parts)
    )

    # Rebuild messages with search context
    enriched = list(messages)
    if enriched and enriched[0].get("role") == "system":
        existing = enriched[0].get("content") or ""
        enriched[0] = {**enriched[0], "content": f"{existing}\n\n{web_context}".strip()}
    else:
        enriched.insert(0, {"role": "system", "content": web_context})

    try:
        completion = await mws_client.chat_complete(
            model=model,
            messages=enriched,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = completion.choices[0].message.content or ""
        if content and not _detect_uncertainty(content):
            logger.info("Web search retry succeeded (%d chars)", len(content))
            return content
    except Exception:
        logger.warning("Web search retry LLM call failed", exc_info=True)

    return None


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

import re as _re_img

# Pattern to extract prompt from <details><summary>Промпт</summary>..prompt..</details>
_IMG_PROMPT_RE = _re_img.compile(
    r"<details>\s*<summary>Промпт</summary>\s*\n*(.*?)\n*\s*</details>",
    _re_img.DOTALL,
)

# Pattern to detect image generation keywords in user messages
_IMG_KW_RE = _re_img.compile(
    r"(нарисуй|сгенерируй|создай\s+изображение|draw|generate\s+image|imagine)",
    _re_img.I,
)


def _extract_prev_image_prompt(messages: list[dict]) -> str | None:
    """
    Look through conversation history for the most recent image generation result.
    First tries to extract the prompt from a <details>Промпт</details> block
    in an assistant message. Falls back to finding the most recent user message
    with image-generation keywords.
    Returns the prompt text, or None if no previous image found.
    """
    # Strategy 1: Find prompt in assistant's <details> block (most reliable)
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content", "") or ""
            m = _IMG_PROMPT_RE.search(content)
            if m:
                return m.group(1).strip()

    # Strategy 2: Find previous user message with image keywords
    found_current = False
    for msg in reversed(messages):
        if msg.get("role") == "user":
            if not found_current:
                found_current = True
                continue
            content = msg.get("content", "")
            text = content if isinstance(content, str) else str(content)
            if _IMG_KW_RE.search(text):
                return text
    return None


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

    For follow-up messages ("make it brighter", "change colors"), extracts
    the previous image prompt from conversation history and builds a
    combined prompt so the model can generate an updated version.
    """
    # Extract the image prompt from user's last message
    prompt = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            prompt = content if isinstance(content, str) else str(content)
            break

    # --- Inject previous image context for follow-ups ---
    # If conversation has assistant messages with image markdown, extract the
    # original prompt so user can say "make it brighter" and we re-generate
    # with a modified combined prompt.
    prev_prompt = _extract_prev_image_prompt(messages)
    if prev_prompt and prev_prompt != prompt:
        prompt = (
            f"Предыдущее изображение было сгенерировано по запросу: \"{prev_prompt}\". "
            f"Пользователь хочет изменить его: {prompt}"
        )
        logger.info("Image follow-up: combined prompt = %s", prompt[:120])

    # Store the clean prompt for description (before sending to API)
    _clean_prompt = prompt

    try:
        result = await mws_client.generate_image(prompt, model=model)
        # Append a hidden description so follow-up messages can reference it
        # This appears as small text under the image in the chat
        result += f"\n\n<details><summary>Промпт</summary>\n\n{_clean_prompt}\n\n</details>"
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
# Presentation (PPTX) generation handler
# ---------------------------------------------------------------------------

_PPTX_SYSTEM_PROMPT = """You are a presentation generator. The user wants a PowerPoint presentation.
Generate the content as a JSON object with this EXACT structure (no markdown fences, ONLY raw JSON):
{"title": "Presentation Title", "slides": [{"title": "Slide Title", "content": "Bullet point 1\\nBullet point 2\\nBullet point 3"}, ...]}

Rules:
- Generate 5-10 slides unless the user specifies a number
- Each slide should have 3-5 bullet points
- Content should be informative and well-structured
- Write in the same language as the user's request
- Do NOT wrap in markdown code blocks, output ONLY valid JSON"""


async def _handle_presentation_generation(
    req: "ChatRequest",
    messages: list[dict],
    model: str,
    routing_method: str,
    routing_reason: str,
    user_id: str,
    *,
    stream: bool = False,
) -> JSONResponse | StreamingResponse:
    """Generate a PPTX presentation via LLM + python-pptx."""

    # Build messages with system prompt for structured output
    pptx_messages = [{"role": "system", "content": _PPTX_SYSTEM_PROMPT}]
    for msg in messages:
        if msg.get("role") == "user":
            pptx_messages.append(msg)

    hdrs = {
        "X-GPTHub-Model": model,
        "X-GPTHub-Requested-Model": req.model,
        "X-GPTHub-Routing-Method": routing_method,
        "X-GPTHub-Routing-Reason": routing_reason,
    }

    try:
        completion = await mws_client.chat_complete(
            model=model,
            messages=pptx_messages,
            temperature=0.7,
            max_tokens=4096,
        )
        raw = completion.choices[0].message.content or ""
        logger.info("PPTX raw LLM output length: %d", len(raw))

        title, slides = parse_presentation_json(raw)
        filename = generate_pptx(title, slides)

        # Build response with download link
        result = (
            f"Презентация **\"{title}\"** готова! ({len(slides)} слайдов)\n\n"
            f"[📥 Скачать презентацию (.pptx)](http://localhost:8000/files/{filename})\n\n"
            f"### Содержание:\n"
        )
        for i, s in enumerate(slides, 1):
            result += f"{i}. {s.get('title', '')}\n"

    except Exception as e:
        logger.warning("Presentation generation failed: %s", e, exc_info=True)
        result = (
            f"⚠️ Не удалось создать презентацию.\n\n"
            f"Ошибка: {e}\n\n"
            f"Попробуйте переформулировать запрос."
        )

    if stream:
        async def _pptx_stream():
            chunk = _make_delta_chunk(model, "pptx", result)
            chunk["choices"][0]["finish_reason"] = None
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode()
            done = _make_delta_chunk(model, "pptx-done", "")
            done["choices"][0]["finish_reason"] = "stop"
            yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n".encode()
            yield b"data: [DONE]\n\n"

        return StreamingResponse(
            _pptx_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", **hdrs},
        )

    return JSONResponse(content={
        "id": f"gpthub-pptx-{int(time.time())}",
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
# GET /files/{filename} — serve generated files (PPTX, etc.)
# ---------------------------------------------------------------------------

@router.get("/files/{filename}")
async def serve_file(filename: str):
    """Serve generated files for download."""
    from pathlib import Path
    from fastapi.responses import FileResponse

    # Sanitize filename — prevent path traversal
    safe_name = Path(filename).name
    filepath = Path(os.environ.get("DATA_DIR", "/app/data")) / "files" / safe_name

    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(filepath),
        filename=safe_name,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


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
