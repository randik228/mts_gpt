"""
Smart Router — classify user intent → pick best model.

Priority (first match wins):
  1. Virtual hint      — user explicitly chose a mode
  2. Multimodal signals — audio/image attachment
  3. Keyword match     — O(n) scan, ~0 ms
  4. LLM intent        — gpt-oss-20b classifies ambiguous requests
  5. Embedding fallback — cosine similarity via bge-m3
  6. Default            → complexity-based general model

Returns (model_id, reason, method).
"""
import logging
import re
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Routing result
# ---------------------------------------------------------------------------

@dataclass
class RoutingDecision:
    model: str
    reason: str
    method: str  # "multimodal" | "keyword" | "embedding" | "default" | etc.


# ---------------------------------------------------------------------------
# Complexity estimator — distributes within a category
# ---------------------------------------------------------------------------

def _estimate_complexity(text: str) -> str:
    """
    Estimate request complexity: 'simple' | 'medium' | 'complex'.

    Heuristics:
    - simple:  short question, single task, <50 chars
    - medium:  moderate length, some structure
    - complex: long, multi-step, technical depth, enumeration
    """
    length = len(text)
    words = len(text.split())

    # Indicators of complexity
    complex_markers = sum([
        # Multi-step / enumeration
        bool(re.search(r'\d+[\.\)]\s', text)),                    # numbered lists
        text.count('\n') >= 3,                                     # multi-line
        bool(re.search(r'(подробн|детальн|разв[её]рн|шаг за шагом|step.by.step|в деталях|пошагов|пошаговый)', text, re.I)),
        bool(re.search(r'(сравни|проанализир|исследуй|разработай|спроектируй|архитектур|обоснов|докажи|философ|с позиций)', text, re.I)),
        bool(re.search(r'(compare|analyze|design|architect|implement.*and|build.*with|prove|theorem)', text, re.I)),
        words > 80,
        length > 500,
        text.count(',') >= 5,                                      # many clauses
        bool(re.search(r'```', text)),                             # code blocks
    ])

    if complex_markers >= 3 or (length > 400 and complex_markers >= 2):
        return "complex"
    elif complex_markers >= 1 or words > 25 or length > 120:
        return "medium"
    else:
        return "simple"


# ---------------------------------------------------------------------------
# Model pools per category — indexed by complexity
# ---------------------------------------------------------------------------
# Each category maps complexity level → (model_id, reason_suffix)

_MODEL_POOLS: dict[str, dict[str, tuple[str, str]]] = {
    "code": {
        "simple":  ("qwen3-32b",               "simple code task"),
        "medium":  ("qwen3-coder-480b-a35b",    "code task"),
        "complex": ("qwen3-coder-480b-a35b",    "complex code task"),
    },
    "reasoning": {
        "simple":  ("QwQ-32B",                          "simple reasoning"),
        "medium":  ("deepseek-r1-distill-qwen-32b",     "reasoning task"),
        "complex": ("deepseek-r1-distill-qwen-32b",     "complex reasoning"),
    },
    "general": {
        "simple":  ("gpt-oss-20b",                           "simple question"),
        "medium":  ("gpt-oss-120b",                          "general task"),
        "complex": ("Qwen3-235B-A22B-Instruct-2507-FP8",    "complex general task"),
    },
    "creative": {
        "simple":  ("gpt-oss-120b",                          "simple creative"),
        "medium":  ("Qwen3-235B-A22B-Instruct-2507-FP8",    "creative task"),
        "complex": ("Qwen3-235B-A22B-Instruct-2507-FP8",    "complex creative task"),
    },
    "search": {
        "simple":  ("gpt-oss-20b",     "simple search"),
        "medium":  ("gpt-oss-120b",    "search task"),
        "complex": ("gpt-oss-120b",    "complex search"),
    },
}


def _pick_from_pool(category: str, text: str) -> tuple[str, str]:
    """Pick model from pool based on estimated complexity."""
    pool = _MODEL_POOLS.get(category, _MODEL_POOLS["general"])
    complexity = _estimate_complexity(text)
    model_id, reason = pool[complexity]
    logger.info("Complexity=%s category=%s → %s", complexity, category, model_id)
    return model_id, reason


# ---------------------------------------------------------------------------
# Keyword rules — each entry: (compiled pattern, category, reason_base)
# Evaluated top-to-bottom; first match wins.
# ---------------------------------------------------------------------------

_KEYWORD_RULES: list[tuple[re.Pattern, str, str]] = [
    # Image generation — verb + visual noun (allow up to 3 words between)
    # "сгенерируй изображение" → image, "создай красивую иллюстрацию" → image
    # "сгенерируй отчёт" → NOT image
    (re.compile(
        r"\b(сгенерируй|создай|generate|create)\s+(\S+\s+){0,3}(изображени|картинк|фото|рисунок|иллюстраци|image|picture|photo|illustration)\w*\b",
        re.I,
    ), "image", "image generation request"),
    # "нарисуй" — keyword match, BUT always verified by LLM to catch metaphors
    (re.compile(
        r"\b(нарисуй|draw\b|paint\b)",
        re.I,
    ), "image", "image generation request"),
    # Image modification — explicit reference to image object
    (re.compile(
        r"\b(измени|поменяй|перерисуй|перегенерируй)\s+(картинк|изображени|рисунок|фото)\w*\b",
        re.I,
    ), "image", "image modification request"),

    # Web search
    (re.compile(
        r"\b(найди\s+(в\s+)?(интернет|сети|google)|поищи|загугли|search\s+(the\s+)?web"
        r"|новости\s+(про|о|об)|актуальн|свежие\s+новости|текущ(ий|ая|ие)\s+(курс|цена|погода|дата)"
        r"|погода\s+(в|на|сейчас)|курс\s+(доллар|евро|валют)|что\s+происход|что\s+случил"
        r"|последние\s+событи|search\s+for|look\s+up|find\s+online)\b",
        re.I,
    ), "search", "web search request"),

    # Code / programming
    (re.compile(
        r"\b(код|code|программ|script|функци[яю]|function|class|класс|алгоритм|algorithm"
        r"|debug|баг|bug|рефактор|refactor|implement|реализу|написать\s+програм"
        r"|python|javascript|typescript|golang|rust|sql|html|css|bash|dockerfile)\b",
        re.I,
    ), "code", "code/programming request"),

    # Reasoning / logic / math
    (re.compile(
        r"\b(почему|объясни\s+почему|докажи|рассуж|логик|логически|математик|math"
        r"|реши\s+задач|prove|reasoning|step.by.step|пошагово|вывод|анализ\s+причин)\b",
        re.I,
    ), "reasoning", "reasoning/logic request"),

    # Creative / complex (no trailing \b — Russian stems need partial match)
    (re.compile(
        r"(напиши\s+(рассказ|стих|эссе|историю|сценари)|creative|story|poem|essay"
        r"|придумай|сочини|фантастик\w*|философ\w*|глубок\w*|подробн\w*|развёрнут\w*)",
        re.I,
    ), "creative", "creative/complex request"),
]


# ---------------------------------------------------------------------------
# LLM intent classification — fast call for ambiguous requests
# ---------------------------------------------------------------------------

_INTENT_CLASSIFY_PROMPT = (
    "Классифицируй намерение пользователя. Ответь ОДНИМ словом — только название категории.\n\n"
    "Категории:\n"
    "- PRESENTATION — пользователь просит СОЗДАТЬ/СДЕЛАТЬ презентацию, слайды, PPTX, pitch deck. "
    "ВАЖНО: если пользователь просто спрашивает про презентации или обсуждает их — это НЕ PRESENTATION, а GENERAL.\n"
    "- IMAGE — пользователь хочет СГЕНЕРИРОВАТЬ/НАРИСОВАТЬ изображение или картинку\n"
    "- CODE — пользователь хочет написать, отладить или разобрать код/программу\n"
    "- SEARCH — пользователю нужна актуальная информация (новости, погода, цены, события)\n"
    "- REASONING — пользователь хочет логический анализ, математику, доказательство\n"
    "- GENERAL — всё остальное: вопросы, перевод, объяснения, общение, творчество\n\n"
    "Сообщение: {message}\n"
    "Категория:"
)

_INTENT_TO_CATEGORY: dict[str, str] = {
    "PRESENTATION": "presentation",
    "IMAGE":        "image",
    "CODE":         "code",
    "SEARCH":       "search",
    "REASONING":    "reasoning",
}


async def _llm_classify_intent(text: str) -> tuple[str | None, str | None]:
    """Use a fast LLM to classify user intent.
    Returns (category, raw_answer) or (None, None)."""
    from core.mws_client import chat_complete

    prompt = _INTENT_CLASSIFY_PROMPT.format(message=text[:500])

    try:
        completion = await chat_complete(
            model="gpt-oss-20b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=500,  # reasoning models need token budget for CoT + answer
        )
        msg = completion.choices[0].message
        content = (msg.content or "").strip()
        reasoning = getattr(msg, "reasoning_content", None) or ""

        # Reasoning models may put answer at end of reasoning_content
        if not content and reasoning:
            import re as _re
            # Find category keywords in reasoning
            _cats = _re.findall(
                r'\b(PRESENTATION|IMAGE|CODE|SEARCH|REASONING|GENERAL)\b',
                reasoning,
            )
            content = _cats[-1] if _cats else ""

        raw_answer = content
        answer = raw_answer.strip().upper()
        logger.info("LLM intent classifier raw='%s' for: %s", raw_answer[:100], text[:80])

        for intent, category in _INTENT_TO_CATEGORY.items():
            if intent in answer:
                logger.info("LLM intent → %s", category)
                return category, raw_answer.strip()

        # GENERAL — no specific category
        if "GENERAL" in answer:
            return "general", raw_answer.strip()

        return None, raw_answer.strip()

    except Exception:
        logger.warning("LLM intent classification failed, falling through", exc_info=True)
        return None, None


# ---------------------------------------------------------------------------
# Image verification — double-check that it's REALLY an image request
# ---------------------------------------------------------------------------

_IMAGE_VERIFY_PROMPT = (
    "Пользователь написал сообщение. Нужно ли СГЕНЕРИРОВАТЬ ИЗОБРАЖЕНИЕ/КАРТИНКУ для ответа?\n"
    "Ответь СТРОГО ОДНИМ СЛОВОМ: ДА или НЕТ.\n\n"
    "Правила:\n"
    "- ДА — ТОЛЬКО если пользователь явно просит НАРИСОВАТЬ, СОЗДАТЬ КАРТИНКУ, СГЕНЕРИРОВАТЬ ИЗОБРАЖЕНИЕ\n"
    "- НЕТ — если просит сгенерировать текст, код, отчёт, таблицу, список, презентацию\n"
    "- НЕТ — если говорит об изображениях абстрактно (обсуждает, спрашивает про них)\n"
    "- НЕТ — если просит изменить/описать уже загруженное изображение\n"
    "- НЕТ — если просит что-то сложное/подробное (анализ, эссе, рассуждение)\n"
    "- НЕТ — если слово 'нарисуй' используется метафорически ('нарисуй картину будущего')\n\n"
    "Примеры:\n"
    "- 'нарисуй кота в космосе' → ДА\n"
    "- 'сгенерируй изображение заката' → ДА\n"
    "- 'сгенерируй список задач' → НЕТ\n"
    "- 'нарисуй мне картину будущего России' → НЕТ\n"
    "- 'представь и опиши подробно архитектуру проекта' → НЕТ\n"
    "- 'создай отчёт с графиками' → НЕТ\n\n"
    "Сообщение: {message}\n"
    "Ответ (ДА или НЕТ):"
)


async def _verify_image_intent(text: str) -> bool:
    """Double-check with LLM that this is really an image generation request.
    Returns True only if confirmed. Used to prevent false positives.

    IMPORTANT: Only checks msg.content, NOT reasoning_content — reasoning models
    put chain-of-thought in reasoning_content which may contain 'ДА' in reasoning.
    """
    from core.mws_client import chat_complete

    # Quick negative check — if text is long (>300 chars) it's likely NOT a simple image request
    if len(text.strip()) > 500:
        logger.info("Image verify: text too long (%d chars), likely NOT image request", len(text))
        return False

    try:
        completion = await chat_complete(
            model="gpt-oss-20b",
            messages=[{"role": "user", "content": _IMAGE_VERIFY_PROMPT.format(message=text[:300])}],
            temperature=0.0,
            max_tokens=500,  # reasoning models need budget for chain-of-thought + answer
        )
        msg = completion.choices[0].message
        content = (msg.content or "").strip()
        reasoning = getattr(msg, "reasoning_content", None) or ""

        # For reasoning models: if content is empty, extract from reasoning
        if not content and reasoning:
            import re as _re
            matches = _re.findall(r'\b(ДА|НЕТ|Да|Нет|да|нет)\b', reasoning)
            content = matches[-1] if matches else ""
            logger.debug("Image verify: extracted '%s' from reasoning (%d chars)", content, len(reasoning))

        raw = content.upper().strip()
        is_image = "ДА" in raw and "НЕТ" not in raw
        logger.info("Image verify: '%s' → %s (for: %s)", raw[:30], is_image, text[:60])
        return is_image
    except Exception:
        logger.warning("Image verification failed, defaulting to NO", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Embedding-based fallback: anchor phrases per category
# ---------------------------------------------------------------------------

_EMBED_ANCHORS: dict[str, list[str]] = {
    "code": [
        "write code", "programming", "implement function", "debug error",
        "написать код", "программирование",
    ],
    "reasoning": [
        "logical reasoning", "step by step analysis", "prove theorem",
        "логическое рассуждение", "докажи", "пошаговый анализ",
    ],
    "creative": [
        "write a story", "creative writing", "detailed essay",
        "напиши рассказ", "творческое задание", "развёрнутый ответ",
    ],
    "image": [
        "generate image", "draw picture", "create illustration",
        "нарисуй картинку", "сгенерируй изображение",
    ],
    "general": [
        "answer question", "explain", "summarize", "translate",
        "ответь на вопрос", "объясни", "переведи",
    ],
}

_anchor_vectors: dict[str, np.ndarray] | None = None  # lazy-loaded


async def _get_anchor_vectors() -> dict[str, np.ndarray]:
    """Embed anchor phrases once and cache."""
    global _anchor_vectors
    if _anchor_vectors is not None:
        return _anchor_vectors

    from core.mws_client import embed

    result: dict[str, np.ndarray] = {}
    for category, phrases in _EMBED_ANCHORS.items():
        vecs = await embed(phrases)
        result[category] = np.mean(np.array(vecs, dtype=np.float32), axis=0)

    _anchor_vectors = result
    logger.info("Smart Router: anchor vectors loaded for %d categories", len(result))
    return _anchor_vectors


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom > 0 else 0.0


# ---------------------------------------------------------------------------
# Resolve category → model
# ---------------------------------------------------------------------------

def _resolve_category(category: str, text: str) -> RoutingDecision:
    """Turn a category into a concrete model via complexity-based pool."""
    # Special categories — fixed model, no complexity split
    if category == "image":
        return RoutingDecision("qwen-image-lightning", "image generation request", "keyword")
    if category == "presentation":
        return RoutingDecision("Qwen3-235B-A22B-Instruct-2507-FP8", "presentation generation request", "llm_intent")

    model_id, reason = _pick_from_pool(category, text)
    return RoutingDecision(model_id, reason, "keyword")


# ---------------------------------------------------------------------------
# Audio transcription helper for chat flow
# ---------------------------------------------------------------------------

async def transcribe_audio_from_message(messages: list[dict]) -> list[dict]:
    """
    If messages contain audio content parts, transcribe them via Whisper
    and replace with text. Returns modified messages.
    """
    import httpx
    import os
    import base64

    base_url = os.environ.get("MWS_API_BASE", "https://api.gpt.mws.ru/v1")
    api_key = os.environ["MWS_API_KEY"]

    result = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            result.append(msg)
            continue

        new_parts = []
        for part in content:
            if not isinstance(part, dict):
                new_parts.append(part)
                continue

            ptype = part.get("type", "")
            if ptype not in ("audio", "input_audio"):
                new_parts.append(part)
                continue

            # Extract audio data
            audio_data = part.get("data") or part.get("input_audio", {}).get("data", "")
            audio_format = part.get("format") or part.get("input_audio", {}).get("format", "wav")

            if not audio_data:
                new_parts.append({"type": "text", "text": "[аудио: данные отсутствуют]"})
                continue

            try:
                audio_bytes = base64.b64decode(audio_data)
                logger.info("Transcribing audio: %d bytes, format=%s", len(audio_bytes), audio_format)

                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(
                        f"{base_url}/audio/transcriptions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        files={"file": (f"audio.{audio_format}", audio_bytes)},
                        data={"model": "whisper-turbo-local"},
                    )
                    resp.raise_for_status()
                    transcript = resp.json().get("text", "")

                logger.info("Audio transcribed: '%s'", transcript[:100])
                new_parts.append({"type": "text", "text": f"[Аудио сообщение]: {transcript}"})

            except Exception:
                logger.warning("Audio transcription failed", exc_info=True)
                new_parts.append({"type": "text", "text": "[аудио: ошибка транскрипции]"})

        # Rebuild message with new parts
        new_msg = dict(msg)
        # If only text parts remain, simplify to string
        text_parts = [p.get("text", "") for p in new_parts if isinstance(p, dict) and p.get("type") == "text"]
        other_parts = [p for p in new_parts if not (isinstance(p, dict) and p.get("type") == "text")]

        if other_parts:
            new_msg["content"] = new_parts
        else:
            new_msg["content"] = " ".join(text_parts)

        result.append(new_msg)

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def route(
    messages: list[dict],
    *,
    has_image: bool = False,
    has_audio: bool = False,
    virtual_hint: str | None = None,
) -> RoutingDecision:
    """
    Classify messages and return a RoutingDecision.
    """
    # 0. Virtual alias hints — user explicitly chose a category
    if virtual_hint and virtual_hint != "auto":
        from core.model_registry import _VIRTUAL_MAP
        if virtual_hint in _VIRTUAL_MAP:
            return RoutingDecision(
                model=_VIRTUAL_MAP[virtual_hint],
                reason=f"user selected {virtual_hint}",
                method="virtual",
            )

    # 1. Multimodal signals
    # Audio: transcription handled separately in openai_compat before routing
    # so has_audio should be False by this point. If somehow still True, route to general.
    if has_audio:
        return RoutingDecision("gpt-oss-120b", "audio message (transcribed)", "multimodal")
    if has_image:
        return RoutingDecision("qwen3-vl-30b-a3b-instruct", "image attachment", "multimodal")

    # Extract plain text from messages for classification
    text = _extract_text(messages)

    if not text.strip():
        return RoutingDecision("gpt-oss-20b", "empty/no text", "default")

    # 2. Keyword match (fast path) — now returns category, resolved via complexity
    keyword_category = None
    for pattern, category, reason_base in _KEYWORD_RULES:
        if pattern.search(text):
            keyword_category = category
            break

    if keyword_category:
        # Image requires double-check to avoid false positives like "сгенерируй отчёт"
        if keyword_category == "image":
            if await _verify_image_intent(text):
                decision = _resolve_category("image", text)
                decision.method = "keyword+verified"
                return decision
            else:
                logger.info("Image keyword matched but verification REJECTED: %s", text[:80])
                # Fall through to LLM classification
        else:
            decision = _resolve_category(keyword_category, text)
            decision.method = "keyword"
            return decision

    # 3. LLM intent classification
    llm_category, _ = await _llm_classify_intent(text)
    if llm_category and llm_category != "general":
        # Image from LLM also requires verification
        if llm_category == "image":
            if await _verify_image_intent(text):
                decision = _resolve_category("image", text)
                decision.method = "llm_intent+verified"
                return decision
            else:
                logger.info("LLM said IMAGE but verification REJECTED: %s", text[:80])
                # Fall through to embedding or default (general)
        else:
            decision = _resolve_category(llm_category, text)
            decision.method = "llm_intent"
            return decision

    # 4. Embedding cosine similarity (final fallback)
    try:
        embed_category = await _embedding_route_category(text)
        if embed_category and embed_category != "general":
            # Image from embedding also requires verification
            if embed_category == "image":
                if await _verify_image_intent(text):
                    decision = _resolve_category("image", text)
                    decision.method = "embedding+verified"
                    return decision
                else:
                    logger.info("Embedding said IMAGE but verification REJECTED: %s", text[:80])
            else:
                decision = _resolve_category(embed_category, text)
                decision.method = "embedding"
                return decision
    except Exception:
        logger.warning("Smart Router: embedding fallback failed", exc_info=True)

    # 5. Default — use complexity to pick general model
    model_id, reason = _pick_from_pool("general", text)
    return RoutingDecision(model_id, reason, "default")


async def _embedding_route_category(text: str) -> str | None:
    """Return best category via cosine similarity, or None if score too low."""
    from core.mws_client import embed

    anchors = await _get_anchor_vectors()
    query_vec = np.array((await embed([text]))[0], dtype=np.float32)

    scores = {cat: _cosine(query_vec, anchor) for cat, anchor in anchors.items()}
    best_cat = max(scores, key=lambda c: scores[c])
    best_score = scores[best_cat]

    logger.debug("Smart Router embedding scores: %s", scores)

    if best_score < 0.70 or best_cat == "general":
        return None

    return best_cat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_text(messages: list[dict]) -> str:
    """Extract text from the LAST user message only."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part.get("text", ""))
            return " ".join(parts)
    return ""


def detect_multimodal(messages: list[dict]) -> tuple[bool, bool]:
    """
    Scan messages for image/audio content parts.
    Returns (has_image, has_audio).
    """
    has_image = False
    has_audio = False
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                t = part.get("type", "")
                if t == "image_url":
                    has_image = True
                elif t in ("audio", "input_audio"):
                    has_audio = True
    return has_image, has_audio
