"""
Model Catalog API.
GET /api/models/catalog — full model registry with metadata
"""
from fastapi import APIRouter

from core.model_registry import MODELS, VIRTUAL_MODELS, _VIRTUAL_MAP

router = APIRouter()


@router.get("/catalog")
async def get_catalog():
    catalog = []
    for mid, info in MODELS.items():
        catalog.append({
            "id": mid,
            "role": info.role,
            "speed_tps": info.speed_tps,
            "price_per_1k": info.price_per_1k,
            "supports_vision": info.supports_vision,
            "supports_audio": info.supports_audio,
            "supports_image_gen": info.supports_image_gen,
        })

    virtuals = []
    for v in VIRTUAL_MODELS:
        virtuals.append({
            "id": v,
            "maps_to": _VIRTUAL_MAP.get(v, "smart-router"),
            "description": _VIRTUAL_DESC.get(v, ""),
        })

    return {"models": catalog, "virtual": virtuals}


_VIRTUAL_DESC = {
    "auto": "Smart Router — автоматический выбор модели по запросу",
    "auto-code": "Лучшая модель для кода (Qwen3 Coder 480B)",
    "auto-reasoning": "Глубокое рассуждение (DeepSeek R1 32B)",
    "auto-creative": "Творческие и сложные задачи (Qwen3 235B)",
    "auto-fast": "Быстрый ответ (GPT-OSS 20B)",
}
