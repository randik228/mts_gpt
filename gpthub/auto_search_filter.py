"""
title: Auto Web Search
description: Automatically enables OpenWebUI native web search when the query needs current information
"""
from typing import Optional


class Function:
    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        messages = body.get("messages", [])
        if not messages:
            return body

        # Extract last user message text
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            content = part.get("text", "")
                            break
                last_user_msg = str(content)
                break

        # Skip very short messages
        if len(last_user_msg.strip()) < 15:
            return body

        # Already has web search enabled (user clicked the button)
        if body.get("features", {}).get("web_search"):
            return body

        SEARCH_KEYWORDS = [
            "найди", "поищи", "поиск", "найти",
            "актуальный", "актуально", "актуальн",
            "последние новости", "новости о ", "свежие",
            "погода", "курс валют", "курс доллара", "цена на ",
            "сколько стоит", "где купить",
            "что сейчас", "что происходит", "когда выйдет", "когда выходит",
            "рейтинг", "в интернете", "в сети",
            "search for", "find online", "latest news", "current price",
            "what is happening",
        ]

        text = last_user_msg.lower()
        needs_search = any(kw in text for kw in SEARCH_KEYWORDS)

        if needs_search:
            if "features" not in body:
                body["features"] = {}
            body["features"]["web_search"] = True

        return body
