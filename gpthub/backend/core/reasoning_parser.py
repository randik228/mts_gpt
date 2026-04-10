"""
Reasoning Parser — transform <think>...</think> into collapsible thinking blocks.

Uses a fenced code block with language "thinking" which OpenWebUI renders as
a <pre><code class="language-thinking"> element. Custom CSS (injected via
Admin → Settings → Interface → Custom CSS) hides the block behind a clickable
toggle arrow.

    ```thinking
    🧠 Процесс мышления
    line 1 of thinking
    line 2 of thinking
    ```

    Final answer follows after a blank line.

Two modes:
  parse(text)                  — complete string, replaces all <think> blocks at once
  StreamingReasoningParser      — stateful, fed chunk-by-chunk from an SSE stream

State machine for streaming:
  NORMAL  →  sees "<think>"   → BUFFERING
  BUFFERING → sees "</think>" → emits blockquote block, back to NORMAL
  BUFFERING → stream ends     → emits raw buffered text (unclosed tag fallback)

Edge cases handled:
  - Tag split across multiple chunks ("</th" … "ink>")
  - Nested angle brackets inside <think> content
  - Multiple <think> blocks in one response
  - Models that emit <think> with leading/trailing whitespace variants
  - System prompt injection for non-reasoning models (build_reasoning_system_prompt)
"""
import re
from enum import Enum, auto

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_OPEN_TAG = "<think>"
_CLOSE_TAG = "</think>"

# Max partial-tag tail we keep in the lookahead buffer (len of longest tag - 1)
_MAX_TAIL = max(len(_OPEN_TAG), len(_CLOSE_TAG)) - 1

# Regex for the non-streaming helper
_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)


def _format_thinking(content: str) -> str:
    """
    Format think-block as a collapsible <details>/<summary> HTML element.
    Browsers collapse <details> by default — user clicks to expand.
    OpenWebUI passes HTML through its markdown renderer so this renders correctly.

    Output:
        <details>
        <summary>🧠 Процесс мышления</summary>

        thinking content here

        </details>

        ---

    """
    if not content:
        return ""
    body = content.strip()
    return f"<details>\n<summary>🧠 Процесс мышления</summary>\n\n{body}\n\n</details>\n\n---\n\n"

# System prompt snippet injected for models that don't natively support <think>
REASONING_SYSTEM_PROMPT = (
    "Перед ответом рассуждай пошагово. "
    "Покажи свои размышления внутри тегов <think>...</think>, "
    "затем дай финальный ответ после закрывающего тега."
)

# Models that natively emit <think> — no system prompt injection needed
NATIVE_REASONING_MODELS = {"deepseek-r1-distill-qwen-32b", "QwQ-32B"}

# Models where we actively WANT to inject the reasoning system prompt.
# All other models respond faster and better WITHOUT forced thinking.
# (Empty by default — only native reasoning models show <think> blocks.)
REASONING_INJECTION_MODELS: set[str] = set()


# ---------------------------------------------------------------------------
# Complete-string helper
# ---------------------------------------------------------------------------

def parse(text: str) -> str:
    """Replace all <think>…</think> blocks in a complete string."""
    def _replace(m: re.Match) -> str:
        content = m.group(1).strip()
        return _format_thinking(content)

    return _THINK_RE.sub(_replace, text)


# ---------------------------------------------------------------------------
# Streaming parser
# ---------------------------------------------------------------------------

class _State(Enum):
    NORMAL = auto()      # outside any <think> block
    BUFFERING = auto()   # inside <think>…, collecting content


class StreamingReasoningParser:
    """
    Stateful chunk-by-chunk parser.

    Usage:
        parser = StreamingReasoningParser()
        for raw_chunk in sse_chunks:
            output = parser.feed(raw_chunk)
            if output:
                forward_to_client(output)
        tail = parser.flush()   # call once after stream ends
        if tail:
            forward_to_client(tail)
    """

    def __init__(self) -> None:
        self._state = _State.NORMAL
        # In NORMAL: holds the tail of the last chunk that might be a partial open-tag
        # In BUFFERING: accumulates think-block content
        self._buf = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def feed(self, chunk: str) -> str:
        """
        Process one SSE text delta.
        Returns the transformed string to forward to the client immediately.
        May return an empty string if data is being buffered.
        """
        if not chunk:
            return ""

        if self._state == _State.NORMAL:
            return self._feed_normal(chunk)
        else:
            return self._feed_buffering(chunk)

    def flush(self) -> str:
        """
        Call after the stream ends.
        If we're still inside a <think> block (unclosed tag), emit whatever
        was buffered as a <details> block anyway.
        Returns any remaining output.
        """
        if self._state == _State.BUFFERING and self._buf:
            content = self._buf.strip()
            self._buf = ""
            self._state = _State.NORMAL
            return _format_thinking(content)

        # Flush any held normal-mode tail
        tail = self._buf
        self._buf = ""
        return tail

    @property
    def inside_think(self) -> bool:
        return self._state == _State.BUFFERING

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _feed_normal(self, chunk: str) -> str:
        """Handle a chunk while in NORMAL state."""
        text = self._buf + chunk  # prepend any held tail
        self._buf = ""
        output_parts: list[str] = []

        while text:
            idx = text.lower().find(_OPEN_TAG)
            if idx == -1:
                # No open tag found — but keep a tail in case it's split
                safe_len = max(0, len(text) - _MAX_TAIL)
                output_parts.append(text[:safe_len])
                self._buf = text[safe_len:]
                break

            # Emit everything before the tag
            output_parts.append(text[:idx])
            text = text[idx + len(_OPEN_TAG):]
            # Switch to buffering mode; remaining text is think-content
            self._state = _State.BUFFERING
            remainder = self._feed_buffering(text)
            output_parts.append(remainder)
            # _feed_buffering may switch back to NORMAL if </think> was found
            text = ""  # all consumed

        return "".join(output_parts)

    def _feed_buffering(self, chunk: str) -> str:
        """Handle a chunk while in BUFFERING (inside <think>) state."""
        text = self._buf + chunk
        self._buf = ""
        output_parts: list[str] = []

        while text:
            idx = text.lower().find(_CLOSE_TAG)
            if idx == -1:
                # No close tag yet — keep a tail in case it's split, buffer the rest
                safe_len = max(0, len(text) - _MAX_TAIL)
                self._buf = text  # entire text stays buffered
                # Don't emit anything while buffering think content
                break

            # Found </think> — emit the <details> block
            content = (self._buf + text[:idx]).strip()
            self._buf = ""
            self._state = _State.NORMAL

            block = _format_thinking(content)
            output_parts.append(block)

            # Process remainder after </think> as normal text
            text = text[idx + len(_CLOSE_TAG):]
            remainder = self._feed_normal(text)
            output_parts.append(remainder)
            text = ""  # all consumed

        return "".join(output_parts)


# ---------------------------------------------------------------------------
# System prompt helper
# ---------------------------------------------------------------------------

def build_reasoning_system_prompt(model: str, existing_system: str | None = None) -> str | None:
    """
    Returns an augmented system prompt instructing the model to use <think> tags,
    but ONLY for models in REASONING_INJECTION_MODELS.
    Native reasoning models (deepseek, QwQ) already emit <think> on their own.
    All other models (gpt-oss-20b, qwen-coder, etc.) respond cleaner without forced thinking.
    Returns None if no injection is needed.
    """
    if model in NATIVE_REASONING_MODELS:
        return None  # model already emits <think> natively — no injection needed

    if model not in REASONING_INJECTION_MODELS:
        return None  # not a thinking model — skip injection, keep responses clean

    injection = REASONING_SYSTEM_PROMPT
    if existing_system:
        return f"{existing_system}\n\n{injection}"
    return injection
