"""
Web Search & URL Fetching for GPTHub.

- DuckDuckGo Lite search (no API key needed)
- Page content fetching with HTML stripping
- URL detection in user messages
"""
import logging
import re
from typing import Optional
from html import unescape

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTTP client (shared, reused across requests)
# ---------------------------------------------------------------------------

_http: httpx.AsyncClient | None = None


def _get_http() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "ru,en;q=0.9",
            },
        )
    return _http


# ---------------------------------------------------------------------------
# HTML → plain text  (regex-based, no external deps)
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>", re.S)
_WS_RE = re.compile(r"[ \t]+")
_NL_RE = re.compile(r"\n{3,}")
_SCRIPT_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)


def strip_html(html: str) -> str:
    """Convert HTML to readable plain text."""
    text = _SCRIPT_RE.sub("", html)
    text = text.replace("<br", "\n<br")
    text = text.replace("</p>", "\n</p>")
    text = text.replace("</div>", "\n</div>")
    text = text.replace("</li>", "\n</li>")
    text = text.replace("</tr>", "\n</tr>")
    text = text.replace("</h", "\n</h")
    text = _TAG_RE.sub("", text)
    text = unescape(text)
    text = _WS_RE.sub(" ", text)
    text = _NL_RE.sub("\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# DuckDuckGo Lite search
# ---------------------------------------------------------------------------

async def search(query: str, max_results: int = 5) -> list[dict]:
    """
    Search DuckDuckGo via duckduckgo-search library.
    Returns list of dicts: [{"title": str, "url": str, "snippet": str}, ...]
    """
    import asyncio

    def _sync_search():
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                raw = list(ddgs.text(query, region="ru-ru", max_results=max_results))
                return [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href", r.get("link", "")),
                        "snippet": r.get("body", r.get("snippet", "")),
                    }
                    for r in raw
                    if r.get("href") or r.get("link")
                ]
        except Exception as e:
            logger.warning("duckduckgo-search failed: %s", e)
            return []

    # Run sync library in thread pool to avoid blocking event loop
    results = await asyncio.to_thread(_sync_search)
    logger.info("Web search '%s' → %d results", query[:60], len(results))
    return results


# ---------------------------------------------------------------------------
# Fetch page content
# ---------------------------------------------------------------------------

async def fetch_page(url: str, max_chars: int = 5000) -> str:
    """
    Download a web page and extract plain text content.
    Returns truncated text (max_chars) or error message.
    """
    try:
        http = _get_http()
        resp = await http.get(url)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type or "text/plain" in content_type:
            text = strip_html(resp.text)
        else:
            return f"[Не удалось прочитать: тип контента {content_type}]"

        if len(text) > max_chars:
            text = text[:max_chars] + "\n... [текст обрезан]"

        return text

    except httpx.TimeoutException:
        return "[Ошибка: таймаут при загрузке страницы]"
    except httpx.HTTPStatusError as e:
        return f"[Ошибка HTTP {e.response.status_code} при загрузке страницы]"
    except Exception as e:
        logger.warning("fetch_page %s failed: %s", url, e)
        return f"[Ошибка при загрузке страницы: {e}]"


# ---------------------------------------------------------------------------
# URL detection in user messages
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")


def detect_urls(text: str) -> list[str]:
    """Find all URLs in text."""
    return _URL_RE.findall(text)


# ---------------------------------------------------------------------------
# Format search results for system prompt injection
# ---------------------------------------------------------------------------

def format_search_results(results: list[dict], query: str) -> str:
    """Format search results as a text block for injection into system prompt."""
    if not results:
        return ""

    lines = [f'[Результаты веб-поиска для "{query}":']
    for i, r in enumerate(results, 1):
        snippet = f": {r['snippet']}" if r.get("snippet") else ""
        lines.append(f"  {i}. {r['title']} ({r['url']}){snippet}")
    lines.append("]")
    lines.append("")
    lines.append("Используй эти данные для ответа. Укажи источники.")
    return "\n".join(lines)


def format_page_content(url: str, text: str) -> str:
    """Format fetched page content for injection into system prompt."""
    return f"[Содержимое страницы {url}:\n{text}\n]"


# ---------------------------------------------------------------------------
# LLM-based search intent classifier
# ---------------------------------------------------------------------------

_CLASSIFY_PROMPT = (
    "Нужен ли интернет-поиск чтобы ответить на этот вопрос? "
    "Поиск нужен для: актуальных событий, новостей, цен, курсов, погоды, рейтингов, "
    "свежих данных после 2024, конкретных фактов о людях/компаниях/продуктах. "
    "Поиск НЕ нужен для: кода, перевода, творчества, математики, общих знаний, приветствий. "
    "Вопрос: \"{question}\" "
    "Ответ (только ДА или НЕТ):"
)


async def classify_needs_search(user_text: str) -> bool:
    """
    Use a lightweight LLM to classify whether a query needs web search.
    Strategy: fast model, minimal prompt, generous tokens for reasoning models.
    """
    from core import mws_client

    try:
        response = await mws_client.chat_complete(
            model="gpt-oss-20b",
            messages=[
                {
                    "role": "system",
                    "content": "Ты классификатор. Отвечай ТОЛЬКО одним словом: ДА или НЕТ. Никаких пояснений.",
                },
                {
                    "role": "user",
                    "content": _CLASSIFY_PROMPT.format(question=user_text[:200]),
                },
            ],
            temperature=0.0,
            max_tokens=200,  # enough for reasoning models to finish thinking + answer
        )
        msg = response.choices[0].message
        content = (msg.content or "").strip().lower()
        reasoning = (getattr(msg, "reasoning_content", None) or "").strip().lower()

        # Combine both fields and look for the answer
        full = content + " " + reasoning

        # Look for explicit ДА/НЕТ in the full response
        # Check content first (the actual answer), then reasoning
        if content:
            needs = "да" in content[:10] or "yes" in content[:10]
        else:
            # Model only produced reasoning — scan the whole thing
            # If reasoning mentions "нужен поиск" / "да" as conclusion
            needs = (
                full.rstrip().endswith("да")
                or full.rstrip().endswith("да.")
                or "ответ: да" in full
                or "answer: yes" in full
                or "нужен поиск" in full
                or "нужен интернет" in full
                or "требуется поиск" in full
                or "поиск нужен" in full
                or ("да" in full[-30:] and "нет" not in full[-15:])
            )

        logger.info("Search classifier: '%s' → %s (content=%s, reasoning_tail=%s)",
                     user_text[:50], "SEARCH" if needs else "SKIP",
                     content[:20] or "empty", reasoning[-30:] if reasoning else "empty")
        return needs
    except Exception as e:
        logger.warning("Search classifier failed: %s — defaulting to no search", e)
        return False
