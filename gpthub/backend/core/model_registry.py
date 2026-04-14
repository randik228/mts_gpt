"""
All available models with metadata.
Model IDs verified against MWS API team access list (April 2026).
"""
from dataclasses import dataclass


@dataclass
class ModelInfo:
    id: str
    role: str
    speed_tps: float | None = None
    price_per_1k: float | None = None
    supports_vision: bool = False
    supports_audio: bool = False
    supports_image_gen: bool = False


MODELS: dict[str, ModelInfo] = {
    # General
    "gpt-oss-20b":                          ModelInfo("gpt-oss-20b",                          "default",    3858, 0.55),
    "gpt-oss-120b":                         ModelInfo("gpt-oss-120b",                         "general",    2721, 0.75),
    # Code
    "qwen3-coder-480b-a35b":                ModelInfo("qwen3-coder-480b-a35b",                "code",       8315, 1.70),
    # Reasoning  (deepseek-r1-distill-qwen-32b, QwQ-32B are available; 14b not accessible)
    "deepseek-r1-distill-qwen-32b":         ModelInfo("deepseek-r1-distill-qwen-32b",         "reasoning",  None, 0.90),
    "QwQ-32B":                              ModelInfo("QwQ-32B",                              "reasoning_alt", None, 0.90),
    # Complex / creative
    "Qwen3-235B-A22B-Instruct-2507-FP8":    ModelInfo("Qwen3-235B-A22B-Instruct-2507-FP8",    "complex",    None, 1.00),
    "qwen3-32b":                            ModelInfo("qwen3-32b",                            "general_fast", None, None),
    "qwen2.5-72b-instruct":                 ModelInfo("qwen2.5-72b-instruct",                 "general_large", None, None),
    # Vision
    "qwen3-vl-30b-a3b-instruct":            ModelInfo("qwen3-vl-30b-a3b-instruct",            "vision",     None, 0.85, supports_vision=True),
    "qwen2.5-vl":                           ModelInfo("qwen2.5-vl",                           "vision_alt", None, 0.85, supports_vision=True),
    "qwen2.5-vl-72b":                       ModelInfo("qwen2.5-vl-72b",                       "vision_large", None, None, supports_vision=True),
    "cotype-pro-vl-32b":                    ModelInfo("cotype-pro-vl-32b",                    "vision_cotype", None, None, supports_vision=True),
    # Audio
    "whisper-turbo-local":                  ModelInfo("whisper-turbo-local",                  "audio",      None, None, supports_audio=True),
    "whisper-medium":                       ModelInfo("whisper-medium",                       "audio_alt",  None, None, supports_audio=True),
    # Image generation
    "qwen-image-lightning":                 ModelInfo("qwen-image-lightning",                 "image_gen",  None, None, supports_image_gen=True),
    "qwen-image":                           ModelInfo("qwen-image",                           "image_gen_alt", None, None, supports_image_gen=True),
    # Embeddings
    "bge-m3":                               ModelInfo("bge-m3",                               "embeddings", None, 0.01),
    # Other available
    "llama-3.3-70b-instruct":               ModelInfo("llama-3.3-70b-instruct",               "llama",      None, None),
    "llama-3.1-8b-instruct":                ModelInfo("llama-3.1-8b-instruct",                "llama_fast", None, None),
    "kimi-k2-instruct":                     ModelInfo("kimi-k2-instruct",                     "kimi",       None, None),
    "glm-4.6-357b":                         ModelInfo("glm-4.6-357b",                         "glm",        None, None),
    "gemma-3-27b-it":                       ModelInfo("gemma-3-27b-it",                       "gemma",      None, None),
    "T-pro-it-1.0":                         ModelInfo("T-pro-it-1.0",                         "mts",        None, None),
    "mws-gpt-alpha":                        ModelInfo("mws-gpt-alpha",                        "mws_alpha",  None, None),
}

# Virtual routing aliases shown to user in OpenWebUI
VIRTUAL_MODELS = ["auto", "auto-code", "auto-reasoning", "auto-creative", "auto-fast"]

# Tool-forcing aliases (injected by frontend toolbar, not shown in model picker)
TOOL_ALIASES = ["auto-search", "auto-image", "auto-presentation", "auto-research"]

# Static mapping for explicit virtual model selection (Smart Router uses this too)
_VIRTUAL_MAP: dict[str, str] = {
    "auto":             "gpt-oss-20b",                       # overridden by Smart Router at runtime
    "auto-code":        "qwen3-coder-480b-a35b",
    "auto-reasoning":   "deepseek-r1-distill-qwen-32b",
    "auto-creative":    "Qwen3-235B-A22B-Instruct-2507-FP8",
    "auto-fast":        "gpt-oss-20b",
    # Tool-forcing: these go through special handlers, not model mapping
    "auto-search":        "gpt-oss-120b",
    "auto-image":         "qwen-image-lightning",
    "auto-presentation":  "Qwen3-235B-A22B-Instruct-2507-FP8",
    "auto-research":      "gpt-oss-120b",
}
