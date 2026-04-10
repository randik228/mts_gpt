"""
Smart Router — classify user intent → pick best model.

Priority (first match wins):
  1. Multimodal signals  — audio/image attachment, image-gen keywords
  2. Keyword match       — O(n) scan, ~0 ms
  3. Embedding fallback  — cosine similarity via bge-m3 (ambiguous cases only)

Returns (model_id, reason, method) where method is "multimodal"|"keyword"|"embedding"|"default".
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
    method: str  # "multimodal" | "keyword" | "embedding" | "default"


# ---------------------------------------------------------------------------
# Keyword rules — each entry: (compiled pattern, model_id, reason)
# Evaluated top-to-bottom; first match wins.
# ---------------------------------------------------------------------------

_KEYWORD_RULES: list[tuple[re.Pattern, str, str]] = [
    # Image generation
    (re.compile(
        r"\b(сгенери(руй)?|нарисуй|создай\s+изображение|draw|generate\s+image|create\s+image|imagine)\b",
        re.I,
    ), "qwen-image-lightning", "image generation request"),

    # Code / programming
    (re.compile(
        r"\b(код|code|программ|script|функци[яю]|function|class|класс|алгоритм|algorithm"
        r"|debug|баг|bug|рефактор|refactor|implement|реализу|написать\s+програм"
        r"|python|javascript|typescript|golang|rust|sql|html|css|bash|dockerfile)\b",
        re.I,
    ), "qwen3-coder-480b-a35b", "code/programming request"),

    # Reasoning / logic / math
    (re.compile(
        r"\b(почему|объясни\s+почему|докажи|рассуж|логик|логически|математик|math"
        r"|реши\s+задач|prove|reasoning|step.by.step|пошагово|вывод|анализ\s+причин)\b",
        re.I,
    ), "deepseek-r1-distill-qwen-32b", "reasoning/logic request"),

    # Creative / complex
    (re.compile(
        r"\b(напиши\s+(рассказ|стих|эссе|историю|сценари)|creative|story|poem|essay"
        r"|придумай|сочини|фантастик|философ|глубок|подробн|развёрнут)\b",
        re.I,
    ), "Qwen3-235B-A22B-Instruct-2507-FP8", "creative/complex request"),

    # МТС
    (re.compile(
        r"\b(мтс|mts|тариф|тарифн|услуга\s+мтс|поддержк[аи]\s+мтс)\b",
        re.I,
    ), "T-pro-it-1.0", "MTS-specific request"),
]

# ---------------------------------------------------------------------------
# Embedding-based fallback: anchor phrases per model
# ---------------------------------------------------------------------------

_EMBED_ANCHORS: dict[str, list[str]] = {
    "qwen3-coder-480b-a35b": [
        "write code", "programming", "implement function", "debug error",
        "написать код", "программирование",
    ],
    "deepseek-r1-distill-qwen-32b": [
        "logical reasoning", "step by step analysis", "prove theorem",
        "логическое рассуждение", "докажи", "пошаговый анализ",
    ],
    "Qwen3-235B-A22B-Instruct-2507-FP8": [
        "write a story", "creative writing", "detailed essay",
        "напиши рассказ", "творческое задание", "развёрнутый ответ",
    ],
    "qwen-image-lightning": [
        "generate image", "draw picture", "create illustration",
        "нарисуй картинку", "сгенерируй изображение",
    ],
    "gpt-oss-20b": [
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

    from core.mws_client import embed  # local import to avoid circular dep at module load

    result: dict[str, np.ndarray] = {}
    for model_id, phrases in _EMBED_ANCHORS.items():
        vecs = await embed(phrases)
        result[model_id] = np.mean(np.array(vecs, dtype=np.float32), axis=0)

    _anchor_vectors = result
    logger.info("Smart Router: anchor vectors loaded for %d models", len(result))
    return _anchor_vectors


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom > 0 else 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def route(
    messages: list[dict],
    *,
    has_image: bool = False,
    has_audio: bool = False,
    virtual_hint: str | None = None,  # e.g. "auto-code" → skip to code model
) -> RoutingDecision:
    """
    Classify messages and return a RoutingDecision.

    Args:
        messages:      OpenAI-format message list.
        has_image:     True if any message contains an image content part.
        has_audio:     True if request has an audio attachment.
        virtual_hint:  The virtual model name the user picked (if any).
    """
    # 0. Virtual alias hints — user explicitly chose a category
    if virtual_hint and virtual_hint != "auto":
        from core.model_registry import _VIRTUAL_MAP  # avoid circular at top level
        if virtual_hint in _VIRTUAL_MAP:
            return RoutingDecision(
                model=_VIRTUAL_MAP[virtual_hint],
                reason=f"user selected {virtual_hint}",
                method="multimodal",
            )

    # 1. Multimodal signals
    if has_audio:
        return RoutingDecision("whisper-turbo-local-preview", "audio attachment", "multimodal")
    if has_image:
        return RoutingDecision("qwen2.5-vl-32b-instruct-awq", "image attachment", "multimodal")

    # Extract plain text from messages for classification
    text = _extract_text(messages)

    if not text.strip():
        return RoutingDecision("gpt-oss-20b", "empty/no text", "default")

    # 2. Keyword match (fast path)
    for pattern, model_id, reason in _KEYWORD_RULES:
        if pattern.search(text):
            logger.debug("Smart Router keyword match: %s → %s", reason, model_id)
            return RoutingDecision(model_id, reason, "keyword")

    # 3. Embedding cosine similarity (ambiguous fallback)
    try:
        decision = await _embedding_route(text)
        if decision:
            return decision
    except Exception:
        logger.warning("Smart Router: embedding fallback failed, using default", exc_info=True)

    # 4. Default
    return RoutingDecision("gpt-oss-20b", "no strong signal", "default")


async def _embedding_route(text: str) -> RoutingDecision | None:
    """Return best model via cosine similarity, or None if score too low."""
    from core.mws_client import embed

    anchors = await _get_anchor_vectors()
    query_vec = np.array((await embed([text]))[0], dtype=np.float32)

    scores = {model_id: _cosine(query_vec, anchor) for model_id, anchor in anchors.items()}
    best_model = max(scores, key=lambda m: scores[m])
    best_score = scores[best_model]

    logger.debug("Smart Router embedding scores: %s", scores)

    # Only trust embedding result if it's clearly above default threshold
    if best_score < 0.55 or best_model == "gpt-oss-20b":
        return None

    return RoutingDecision(best_model, f"embedding similarity {best_score:.2f}", "embedding")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_text(messages: list[dict]) -> str:
    """Concatenate text content from the last few user messages."""
    parts: list[str] = []
    for msg in messages[-4:]:  # look at last 4 messages for context
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            # Vision content parts: [{"type": "text", "text": "..."}, {"type": "image_url", ...}]
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part.get("text", ""))
    return " ".join(parts)


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
