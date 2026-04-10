"""
Task Chain API.
POST /api/taskchain/run       — run a chain, stream progress via SSE
GET  /api/taskchain/templates — list preset chain templates
"""
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from core.taskchain_engine import TaskChainEngine

logger = logging.getLogger(__name__)
router = APIRouter()

_engine = TaskChainEngine()

# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------

class StepSchema(BaseModel):
    type: str = "chat"
    model: str
    input_template: str = ""
    output_key: str
    temperature: float = 0.7
    max_tokens: int | None = None
    system: str | None = None

    @field_validator("type")
    @classmethod
    def valid_type(cls, v: str) -> str:
        if v not in ("chat", "transcribe", "embed"):
            raise ValueError(f"Unknown step type: {v!r}")
        return v


class ChainRequest(BaseModel):
    steps: list[StepSchema]
    context: dict[str, str] = {}   # initial context: user-supplied inputs

    @field_validator("steps")
    @classmethod
    def non_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("steps must not be empty")
        return v


# ---------------------------------------------------------------------------
# POST /api/taskchain/run
# ---------------------------------------------------------------------------

@router.post("/run")
async def run_taskchain(req: ChainRequest):
    chain_dict = {"steps": [s.model_dump() for s in req.steps], "context": req.context}
    return StreamingResponse(
        _sse_generator(chain_dict),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


async def _sse_generator(chain: dict) -> AsyncIterator[bytes]:
    try:
        async for event in _engine.run(chain):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode()
    except Exception as e:
        logger.exception("TaskChain unhandled error")
        err = {"event": "chain_error", "error": str(e)}
        yield f"data: {json.dumps(err)}\n\n".encode()
    finally:
        yield b"data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# GET /api/taskchain/templates
# ---------------------------------------------------------------------------

TEMPLATES: list[dict] = [
    {
        "id": "audio_to_explained_code",
        "name": "Аудио → Код → Объяснение",
        "description": "Транскрибирует аудио, генерирует код, объясняет его",
        "steps": [
            {
                "type": "transcribe",
                "model": "whisper-turbo-local",
                "input_template": "{{audio_path}}",
                "output_key": "transcription",
            },
            {
                "type": "chat",
                "model": "qwen3-coder-480b-a35b",
                "input_template": "Напиши код для следующей задачи:\n\n{{transcription}}",
                "output_key": "code",
            },
            {
                "type": "chat",
                "model": "gpt-oss-20b",
                "input_template": "Объясни следующий код простыми словами:\n\n{{code}}",
                "output_key": "explanation",
            },
        ],
    },
    {
        "id": "research_and_summarize",
        "name": "Исследование → Резюме",
        "description": "Глубокий анализ темы с последующим кратким резюме",
        "steps": [
            {
                "type": "chat",
                "model": "Qwen3-235B-A22B-Instruct-2507-FP8",
                "input_template": "Проведи детальный анализ темы: {{topic}}",
                "output_key": "research",
            },
            {
                "type": "chat",
                "model": "gpt-oss-20b",
                "input_template": "Сократи следующий текст до 3–5 ключевых пунктов:\n\n{{research}}",
                "output_key": "summary",
            },
        ],
    },
    {
        "id": "code_review",
        "name": "Code Review",
        "description": "Разбор кода с рассуждением и итоговыми рекомендациями",
        "steps": [
            {
                "type": "chat",
                "model": "deepseek-r1-distill-qwen-32b",
                "input_template": "Проанализируй код и найди проблемы:\n\n```\n{{code}}\n```",
                "output_key": "analysis",
                "system": "Ты опытный code reviewer. Рассуждай пошагово.",
            },
            {
                "type": "chat",
                "model": "qwen3-coder-480b-a35b",
                "input_template": (
                    "На основе анализа:\n\n{{analysis}}\n\n"
                    "Предложи исправленную версию кода:\n\n```\n{{code}}\n```"
                ),
                "output_key": "fixed_code",
            },
        ],
    },
    {
        "id": "translate_and_embed",
        "name": "Перевод → Эмбеддинг",
        "description": "Переводит текст и создаёт векторное представление",
        "steps": [
            {
                "type": "chat",
                "model": "gpt-oss-20b",
                "input_template": "Переведи на английский:\n\n{{text}}",
                "output_key": "translated",
            },
            {
                "type": "embed",
                "model": "bge-m3",
                "input_template": "{{translated}}",
                "output_key": "embedding",
            },
        ],
    },
]


@router.get("/templates")
async def list_templates():
    return {"templates": TEMPLATES}


@router.get("/templates/{template_id}")
async def get_template(template_id: str):
    for t in TEMPLATES:
        if t["id"] == template_id:
            return t
    raise HTTPException(status_code=404, detail="Template not found")
