"""
Task Chain Engine — execute a sequential pipeline of steps.

Each step consumes a context dict of named outputs from previous steps
and produces its own output under `output_key`.

Supported step types:
  chat        — POST /v1/chat/completions (streaming, collects full text)
  transcribe  — POST /v1/audio/transcriptions via MWS (file path or URL)
  embed       — POST /v1/embeddings, stores vector list under output_key

Step schema:
{
  "type":           "chat" | "transcribe" | "embed",
  "model":          "<model_id>",
  "input_template": "Prompt with {{prev_output_key}} placeholders",
  "output_key":     "my_result",          # required, unique per chain
  "temperature":    0.7,                  # optional, chat only
  "max_tokens":     null,                 # optional, chat only
  "system":         "system prompt",      # optional, chat only
}

SSE event shapes (JSON):
  {"event": "step_start",    "step": 0, "total": 3, "type": "chat", "model": "..."}
  {"event": "step_delta",    "step": 0, "delta": "partial text chunk"}
  {"event": "step_done",     "step": 0, "output_key": "code", "output": "full text"}
  {"event": "step_error",    "step": 0, "error": "message"}
  {"event": "chain_done",    "context": {"code": "...", "explanation": "..."}}
  {"event": "chain_error",   "error": "message"}
"""
import re
from typing import AsyncGenerator

from core.mws_client import chat_stream, embed, get_client

# Strip <think>...</think> blocks from model output before storing in context
_THINK_STRIP_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Event = dict  # SSE payload dict — serialised to JSON by the API layer

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class TaskChainEngine:

    async def run(self, chain: dict) -> AsyncGenerator[Event, None]:
        """
        Execute the chain and yield SSE event dicts.
        Caller is responsible for JSON-serialising and framing as SSE.
        """
        steps: list[dict] = chain.get("steps", [])
        if not steps:
            yield _ev("chain_error", error="Chain has no steps")
            return

        total = len(steps)
        context: dict[str, str] = dict(chain.get("context", {}))   # output_key → result string

        for idx, step in enumerate(steps):
            step_type = step.get("type", "chat")
            model = step.get("model", "gpt-oss-20b")
            output_key = step.get("output_key") or f"step_{idx}"

            yield _ev("step_start", step=idx, total=total, type=step_type, model=model)

            try:
                if step_type == "chat":
                    output = ""
                    async for event in self._run_chat(idx, step, context):
                        yield event
                        if event.get("event") == "step_done":
                            output = event.get("output", "")
                        elif event.get("event") == "step_error":
                            raise StepError(event.get("error", "unknown error"))

                elif step_type == "transcribe":
                    output = await self._run_transcribe(step, context)
                    yield _ev("step_done", step=idx, output_key=output_key, output=output)

                elif step_type == "embed":
                    output = await self._run_embed(step, context)
                    yield _ev("step_done", step=idx, output_key=output_key, output=output)

                else:
                    raise StepError(f"Unknown step type: {step_type!r}")

            except StepError as e:
                yield _ev("step_error", step=idx, error=str(e))
                yield _ev("chain_error", error=f"Step {idx} failed: {e}")
                return

            context[output_key] = output

        yield _ev("chain_done", context=context)

    # ------------------------------------------------------------------
    # Step runners
    # ------------------------------------------------------------------

    async def _run_chat(
        self, idx: int, step: dict, context: dict
    ) -> AsyncGenerator[Event, None]:
        output_key = step.get("output_key") or f"step_{idx}"
        prompt = _resolve(step.get("input_template", ""), context)
        system = step.get("system")
        temperature = float(step.get("temperature", 0.7))
        max_tokens = step.get("max_tokens")

        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        collected: list[str] = []
        try:
            async for chunk in chat_stream(
                model=step["model"],
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    collected.append(delta)
                    yield _ev("step_delta", step=idx, delta=delta)
        except Exception as e:
            raise StepError(str(e)) from e

        full_output = "".join(collected)
        # Strip <think>...</think> reasoning blocks from output before storing in context.
        # Reasoning content is useful for the UI log but should not pollute downstream steps.
        clean_output = _THINK_STRIP_RE.sub("", full_output).strip()
        yield _ev("step_done", step=idx, output_key=output_key, output=clean_output)

    async def _run_transcribe(self, step: dict, context: dict) -> str:
        """
        Transcribe audio via MWS Whisper API.
        Expects context to have a key referenced in input_template,
        whose value is a local file path.
        """
        file_path = _resolve(step.get("input_template", ""), context).strip()
        if not file_path:
            raise StepError("transcribe step: input_template resolved to empty string")

        client = get_client()
        try:
            with open(file_path, "rb") as f:
                response = await client.audio.transcriptions.create(
                    model=step.get("model", "whisper-turbo-local-preview"),
                    file=f,
                )
            return response.text
        except FileNotFoundError:
            raise StepError(f"Audio file not found: {file_path}")
        except Exception as e:
            raise StepError(f"Transcription failed: {e}") from e

    async def _run_embed(self, step: dict, context: dict) -> str:
        """
        Embed text and return JSON-serialised vector list as string.
        Stored as string in context so templates can reference it.
        """
        import json
        text = _resolve(step.get("input_template", ""), context)
        if not text.strip():
            raise StepError("embed step: input_template resolved to empty string")

        try:
            vectors = await embed([text], model=step.get("model", "bge-m3"))
        except Exception as e:
            raise StepError(f"Embedding failed: {e}") from e

        return json.dumps(vectors[0])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _resolve(template: str, context: dict[str, str]) -> str:
    """Replace {{key}} placeholders with values from context."""
    def _sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in context:
            raise StepError(f"Placeholder '{{{{{key}}}}}' not found in context. "
                            f"Available keys: {list(context.keys())}")
        return context[key]
    return _PLACEHOLDER_RE.sub(_sub, template)


def _ev(event: str, **kwargs) -> Event:
    return {"event": event, **kwargs}


class StepError(Exception):
    pass
