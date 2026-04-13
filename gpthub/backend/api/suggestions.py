"""
Prompt suggestions API — generates up to 3 autocomplete suggestions
based on what the user is typing, their memory profile, and chat context.
"""
import json
import logging
import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.mws_client import chat_complete
from core.memory_manager import get_manager

logger = logging.getLogger(__name__)
router = APIRouter()

_SUGGESTION_SYSTEM = """Ты — помощник для автодополнения промптов. Пользователь начал вводить сообщение в чат с ИИ-ассистентом.

Твоя задача: предложить 1-3 варианта ЗАВЕРШЕНИЯ или УЛУЧШЕНИЯ того что пользователь начал вводить.

ПРАВИЛА:
- Каждый вариант — полное сообщение (не продолжение, а ЦЕЛИКОМ, включая то что уже набрано)
- Варианты должны быть разными по смыслу/направлению
- Короткие и конкретные (1-2 предложения максимум)
- На том же языке что и ввод пользователя
- Если есть контекст о пользователе — учитывай его для персонализации
- Если ввод пустой или слишком короткий — предложи популярные запросы

Ответь ТОЛЬКО JSON-массивом строк, без пояснений:
["вариант 1", "вариант 2", "вариант 3"]"""


@router.post("/")
async def get_suggestions(request: Request):
    """
    Generate prompt suggestions based on partial user input.

    Body: {
        "text": "partial user input",
        "user_id": "user email or id",
        "messages": [optional recent chat messages for context]
    }
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"suggestions": []})

    text = (body.get("text") or "").strip()
    user_id = body.get("user_id") or "default"
    messages_ctx = body.get("messages") or []

    # Empty input — no suggestions
    if not text:
        return JSONResponse({"suggestions": []})

    # Word count check (frontend should also check, but double-check here)
    word_count = len(text.split())
    if word_count >= 10:
        return JSONResponse({"suggestions": []})

    # Build context from user memory
    memory_context = ""
    try:
        manager = await get_manager()
        if user_id and user_id != "default":
            # Get recent memories for personalization
            query = text if text else "интересы пользователя предпочтения"
            memories = await manager.search_memories(
                user_id, query, top_k=3, min_score=0.25,
            )
            if memories:
                memory_context = (
                    "Известные факты о пользователе:\n"
                    + "\n".join(f"- {m}" for m in memories)
                )
    except Exception:
        logger.debug("Memory fetch for suggestions failed", exc_info=True)

    # Build chat context (last 2 messages only for speed)
    chat_context = ""
    if messages_ctx:
        recent = messages_ctx[-2:]
        parts = []
        for msg in recent:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                parts.append(f"{role}: {content[:200]}")
        if parts:
            chat_context = "Последние сообщения в чате:\n" + "\n".join(parts)

    # Build the prompt
    user_prompt_parts = []
    if memory_context:
        user_prompt_parts.append(memory_context)
    if chat_context:
        user_prompt_parts.append(chat_context)
    if text:
        user_prompt_parts.append(f'Пользователь начал вводить: "{text}"')
    else:
        user_prompt_parts.append("Пользователь открыл новый чат и ещё ничего не ввёл.")

    user_prompt = "\n\n".join(user_prompt_parts)

    try:
        completion = await chat_complete(
            model="gpt-oss-20b",
            messages=[
                {"role": "system", "content": _SUGGESTION_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            max_tokens=300,
        )

        msg = completion.choices[0].message
        content = (msg.content or "").strip()
        reasoning = getattr(msg, "reasoning_content", None) or ""

        # For reasoning models: extract from reasoning if content is empty
        if not content and reasoning:
            # Find JSON array in reasoning
            matches = re.findall(r'\[.*?\]', reasoning, re.DOTALL)
            content = matches[-1] if matches else ""

        # Parse JSON array
        if not content:
            return JSONResponse({"suggestions": []})

        # Extract JSON array from response (may have extra text around it)
        json_match = re.search(r'\[.*?\]', content, re.DOTALL)
        if not json_match:
            return JSONResponse({"suggestions": []})

        suggestions = json.loads(json_match.group())

        # Filter and clean
        suggestions = [
            s.strip() for s in suggestions
            if isinstance(s, str) and s.strip() and len(s.strip()) > 3
        ][:3]

        return JSONResponse({"suggestions": suggestions})

    except Exception:
        logger.warning("Suggestion generation failed", exc_info=True)
        return JSONResponse({"suggestions": []})
