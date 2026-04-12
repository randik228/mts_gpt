# GPTHub — Полный контекст проекта
> Используй этот файл в начале нового чата: «Вот контекст проекта GPTHub, продолжи работу»

---

## Что это такое

**GPTHub** — корпоративный AI-портал на базе MTS (MWS) GPT API.  
Три сервиса в Docker Compose:

| Сервис | Порт | Роль |
|---|---|---|
| `proxy` (FastAPI) | 8000 | Умный роутер, память, аналитика, совместимый с OpenAI API |
| `open-webui` | 3000 | Готовый чат-интерфейс (v0.6.5), настроен через прокси |
| `dashboard` (React/Vite) | 3001 | Внутренняя панель: память, аналитика, модели, TaskChain |

**Стек:** Python 3.11, FastAPI, OpenWebUI v0.6.5, React + TypeScript, FAISS + SQLite, Docker.

---

## Структура файлов

```
D:/mts_gpt/gpthub/
├── docker-compose.yml
├── .env                          # MWS_API_KEY=...
├── openwebui-custom.css          # Кастомная тема (монтируется в контейнер)
├── openwebui-entrypoint.sh       # Скрипт запуска: инжектит CSS/JS + регистрирует filter
├── auto_search_filter.py         # Исходник OpenWebUI filter (для справки)
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── api/
│   │   ├── openai_compat.py      # /v1/chat/completions, /v1/models, /v1/embeddings
│   │   ├── memory.py             # /api/memory CRUD
│   │   ├── analytics.py          # /api/analytics
│   │   ├── models.py             # /api/models
│   │   └── taskchain.py          # /api/taskchain
│   └── core/
│       ├── model_registry.py     # Все модели + виртуальные алиасы
│       ├── smart_router.py       # Keyword + embedding роутинг
│       ├── memory_manager.py     # FAISS + SQLite память
│       ├── mws_client.py         # Клиент MWS API (openai SDK)
│       ├── reasoning_parser.py   # <think>...</think> → <details> блоки
│       ├── analytics_store.py    # SQLite аналитика запросов
│       ├── web_search.py         # DuckDuckGo + URL fetch (proxy уровень)
│       └── taskchain_engine.py   # TaskChain исполнитель
└── dashboard/
    ├── Dockerfile
    ├── vite.config.ts            # proxy /api → http://proxy:8000
    ├── src/
    │   ├── App.tsx               # Роутер: Memory / Analytics / Models / TaskChain
    │   ├── app.css               # Дизайн-система dashboard
    │   └── pages/
    │       ├── MemoryViewer.tsx
    │       ├── RoutingAnalytics.tsx
    │       ├── ModelCatalog.tsx
    │       └── TaskChainBuilder.tsx
```

---

## docker-compose.yml (полный)

```yaml
services:
  proxy:
    build: ./backend
    ports: ["8000:8000"]
    environment:
      - MWS_API_BASE=https://api.gpt.mws.ru/v1
      - MWS_API_KEY=${MWS_API_KEY}
      - DEFAULT_MODEL=gpt-oss-20b
      - EMBEDDING_MODEL=bge-m3
    volumes: [memory_data:/app/data]
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "python3 -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\""]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 15s

  open-webui:
    image: ghcr.io/open-webui/open-webui:v0.6.5
    ports: ["3000:8080"]
    environment:
      - ENABLE_OLLAMA_API=false
      - OPENAI_API_BASE_URL=http://proxy:8000/v1
      - OPENAI_API_KEY=${MWS_API_KEY}
      - WEBUI_AUTH=false
      - HF_HUB_DISABLE_XET=1
      - ENABLE_WEB_SEARCH=true
      - WEB_SEARCH_ENGINE=duckduckgo
    volumes:
      - webui_data:/app/backend/data
      - ./openwebui-custom.css:/app/custom-theme.css:ro
      - ./openwebui-entrypoint.sh:/app/gpthub-entrypoint.sh:ro
    entrypoint: ["/bin/sh", "-c", "tr -d '\\r' < /app/gpthub-entrypoint.sh | bash"]
    depends_on:
      proxy:
        condition: service_healthy
    restart: unless-stopped

  dashboard:
    build: ./dashboard
    ports: ["3001:3001"]
    environment:
      - PROXY_URL=http://proxy:8000
      - VITE_PROXY_URL=
    depends_on:
      proxy:
        condition: service_healthy
    restart: unless-stopped

volumes:
  webui_data:
  memory_data:
```

---

## Модели (model_registry.py)

### Виртуальные алиасы (показываются пользователю)
| Алиас | Дефолтная модель | Описание |
|---|---|---|
| `auto` | gpt-oss-20b (Smart Router переопределяет) | Универсальный |
| `auto-code` | qwen3-coder-480b-a35b | Программирование |
| `auto-reasoning` | deepseek-r1-distill-qwen-32b | Глубокий анализ |
| `auto-creative` | Qwen3-235B-A22B-Instruct-2507-FP8 | Творчество |
| `auto-fast` | gpt-oss-20b | Быстрый |

### Реальные модели на MWS API
```
gpt-oss-20b               — default, 3858 tps
gpt-oss-120b              — general, 2721 tps
qwen3-coder-480b-a35b     — code, 8315 tps
deepseek-r1-distill-qwen-32b — reasoning (нативный <think>)
QwQ-32B                   — reasoning_alt (нативный <think>)
Qwen3-235B-A22B-Instruct-2507-FP8 — complex/creative
qwen3-32b, qwen2.5-72b-instruct
qwen3-vl-30b-a3b-instruct, qwen2.5-vl  — vision
whisper-turbo-local, whisper-medium      — audio (скрыты в UI)
qwen-image-lightning, qwen-image         — image gen (скрыты в UI)
bge-m3                    — embeddings (скрыт в UI)
llama-3.3-70b, llama-3.1-8b, kimi-k2-instruct
glm-4.6-357b, gemma-3-27b-it
T-pro-it-1.0              — СКРЫТ (недоступна для нашего ключа)
```

**Скрытые от UI:** `bge-m3`, `whisper-*`, `qwen-image-*`, `T-pro-it-1.0`

---

## Smart Router (smart_router.py)

Приоритеты (первое совпадение побеждает):
1. **Виртуальный алиас** — пользователь явно выбрал `auto-code` и т.д.
2. **Multimodal** — есть изображение → `qwen3-vl-30b`, аудио → `whisper-turbo-local`
3. **Keyword rules** (O(n), ~0ms):
   - image gen → `qwen-image-lightning`
   - web search → `gpt-oss-120b`
   - code/programming → `qwen3-coder-480b-a35b`
   - reasoning/math → `deepseek-r1-distill-qwen-32b`
   - creative/complex → `Qwen3-235B-A22B-Instruct-2507-FP8`
4. **Embedding cosine** (bge-m3, threshold 0.70) — fallback для неоднозначных запросов
5. **Default** → `gpt-oss-20b`

**Важно:** роутер смотрит ТОЛЬКО на ПОСЛЕДНЕЕ сообщение пользователя (не историю) — иначе модель «залипает» на предыдущем типе запроса.

---

## Память (memory_manager.py + mws_client.py)

### Архитектура
- **FAISS IndexFlatIP** (inner product = cosine после нормализации) + **SQLite** метаданные
- Данные в Docker volume `memory_data:/app/data/` (`memory.db` + `faiss.index`)
- `faiss_map` таблица: `row_id ↔ memory_id` (нужна для удаления без перестройки индекса)

### Поток данных
1. После каждого ответа модели → `extract_and_save()` (fire-and-forget)
2. `gpt-oss-20b` извлекает факты по промпту `_EXTRACT_FACTS_PROMPT`
3. Фильтрация: `_is_trivial_fact()` (20+ паттернов), минимум 5 символов
4. Дедупликация: если косинусное сходство ≥ 0.92 с существующим — пропускаем
5. Перед каждым запросом: `search_memories()` → вставляем в system prompt

### Инжекция памяти в промпт
```
Контекст о пользователе (используй естественно, НЕ упоминай что у тебя есть память/заметки):
- факт 1
- факт 2
```
top_k=3, min_score=0.50

### API памяти
```
GET  /api/memory?user_id=default&scope=personal&limit=100
POST /api/memory  {user_id, content, scope}
GET  /api/memory/search?user_id=&query=&top_k=5
DELETE /api/memory/{id}
DELETE /api/memory?user_id=default          ← bulk delete (добавлен нами)
```

### Что сохраняется vs нет
**СОХРАНЯТЬ:** имя, возраст, профессия, место работы, предпочтения в общении, хобби, навыки, личные обстоятельства  
**НЕ СОХРАНЯТЬ:** что искал, задачи, математика, тема разговора, код, тестирования

---

## Веб-поиск

### Архитектура (текущая — нативный OpenWebUI)
Поиск полностью делегирован OpenWebUI. Наш прокси поиск НЕ делает.

**OpenWebUI Filter `auto_web_search`** (зарегистрирован как глобальный):
- Перехватывает входящий запрос (inlet)
- Проверяет ключевые слова в последнем сообщении
- Если нашёл → ставит `features.web_search = True`
- OpenWebUI сам делает DuckDuckGo поиск и показывает нативный UI (анимация, ссылки-бейджи, список источников)

**Ключевые слова для trigger:** найди, поищи, поиск, найти, актуальный, последние новости, новости о, свежие, погода, курс валют, рейтинг, в интернете, в сети, и др.

**Регистрация фильтра** автоматически при старте контейнера (через `openwebui-entrypoint.sh`):
- Логин: `admin@localhost` / `admin`
- `POST /api/v1/functions/create` → `POST /api/v1/functions/id/auto_web_search/toggle` (active) + `/toggle/global`

### URL fetch (прокси уровень — остался)
Если пользователь вставляет URL в сообщение → прокси скачивает страницу и добавляет текст в system prompt.

---

## Reasoning / Think блоки

- `deepseek-r1-distill-qwen-32b` и `QwQ-32B` — нативно эмитируют `<think>` через поле `reasoning_content` в дельтах
- **StreamingReasoningParser** (состояние: NORMAL/BUFFERING) оборачивает контент в `<details><summary>🧠 Процесс мышления</summary>...`
- Для `auto-reasoning` thinking показывается, для других `auto-*` — подавляется (`suppress_reasoning=True`)
- CSS делает thinking italic, мельче, серее

---

## CSS кастомизация (openwebui-custom.css)

Файл монтируется и инжектируется в `index.html` при старте контейнера через `openwebui-entrypoint.sh`.

### Ключевые правила

**Тема (только `html.dark`):**
- Основной акцент: `--mts: #e30611`, `--mts-glow: rgba(227,6,17,.18)`
- Фон: `#0d0d0d`, карточки `rgba(255,255,255,.04)`, рамки `rgba(255,255,255,.09)`

**Аватарки моделей** (CSS content trick):
```css
img[alt="Model"]:not([src]),
img[alt="logo"][src=""] {
  content: url('/static/favicon.png');
}
```

**Скрытые элементы:**
- Тема "Her": `option[value="her"] { display: none }`
- Кнопка обновления: `.absolute.bottom-8.right-8[class*="z-50"] { display: none }`
- Поисковая строка в настройках: `.modal .tabs input { display: none }`
- Кнопка «Интерпретатор кода» (`button[aria-label="Code Interpreter"]` и др.) — дублируется JS в entrypoint.sh (MutationObserver)

**Настройки модал:**
- Ширина: `max-width: 66rem; width: 66rem`
- Сайдбар: `.modal .tabs { width: 250px }`

**Select/Dropdown** (тёмная тема):
```css
html.dark select { background-color: #1e1e22; border: 1.5px solid rgba(255,255,255,.13); }
html.dark select option { background-color: #1e1e22; color: #e0e0e0; }
html.dark select option:checked { background-color: #e30611; color: #fff; }
```

**Thinking блоки:**
```css
/* Заголовок — сливается с чатом */
html.dark details > summary { opacity: .55; font-size: .78rem; }
/* Контент — серый, мельче, курсив */
html.dark details > div { font-size: .82rem; color: rgba(255,255,255,.42); font-style: italic; }
```

---

## openwebui-entrypoint.sh

Выполняет при каждом старте контейнера:
1. Инжектирует CSS и JS vars в `index.html`
2. JS скрывает кнопку «Интерпретатор кода» через MutationObserver (строки закодированы `String.fromCharCode()`)
3. Фоновый процесс: ждёт готовности API → регистрирует/активирует `auto_web_search` filter
4. `exec bash start.sh` — запускает OpenWebUI

---

## Proxy flow (openai_compat.py)

```
POST /v1/chat/completions
  │
  ├─ Detect system request? (title/tag generation by OpenWebUI) → skip memory/URL
  │
  ├─ Smart Router → real_model
  │
  ├─ inject_memories() → prepend to system prompt
  │
  ├─ inject_url_context() → fetch URLs from user message
  │
  ├─ image gen? → handle_image_generation()
  │
  ├─ inject_reasoning_prompt() (for REASONING_INJECTION_MODELS — сейчас пустой set)
  │
  ├─ stream=True  → StreamingResponse(_stream_sse())
  │     └─ StreamingReasoningParser: <think> → <details>
  │     └─ fire-and-forget: analytics + memorize
  │
  └─ stream=False → chat_complete() + parse_reasoning() + analytics + memorize
```

**System request detection** — паттерны `r"(?i)(generate|create).{0,30}(title|tag)"` и др. пропускают память и URL-fetch для внутренних запросов OpenWebUI (генерация названий/тегов чатов).

**Обработка ошибок:**
- Streaming: эмитирует delta-чанк с ошибкой + `finish_reason: stop` (UI не зависает)
- Non-streaming: возвращает `JSONResponse` с дружественным текстом вместо HTTP 502

---

## Dashboard (React, порт 3001)

**Vite proxy:** все `/api/*` запросы → `http://proxy:8000`  
**Страницы:**
- `/memory` — Memory Viewer (личная + командная память, семантический поиск, удаление)
- `/analytics` — Routing Analytics (какие модели, методы, latency)
- `/models` — Model Catalog (все модели с метаданными)
- `/` — TaskChain Builder

**Memory Viewer ключевые детали:**
- Bulk delete: `DELETE /api/memory?user_id=...` (не sequential loop)
- `deletingAll` state вместо `confirm()` (confirm() блокирует браузер в автоматизации)
- Scope toggle: personal / team

---

## Запуск проекта

```bash
# Первый запуск
cd D:/mts_gpt/gpthub
echo "MWS_API_KEY=ваш_ключ" > .env
docker compose up -d --build

# Перезапуск после изменений в прокси
docker compose up -d --build proxy

# Перезапуск OpenWebUI (после изменений CSS/entrypoint)
docker compose restart open-webui

# Логи
docker compose logs proxy -f
docker compose logs open-webui -f

# Полная пересборка
docker compose down && docker compose up -d --build
```

**URLs:**
- OpenWebUI чат: http://localhost:3000
- Dashboard: http://localhost:3001
- Proxy API: http://localhost:8000

---

## Что было сделано (история изменений)

### UI / CSS
- ✅ Исправлены аватарки моделей (CSS `content: url()` trick для `img[src=""]`)
- ✅ Кнопки: `border-radius: 10px` но исключены `rounded-full` (иначе кружки превращались в прямоугольники)
- ✅ Все CSS правила обёрнуты в `html.dark` — работают все темы (Light/Dark/OLED)
- ✅ Настройки модал: шире (66rem), сайдбар шире (250px), текст разделов не переносится
- ✅ Убрана строка поиска в настройках
- ✅ Убрана тема "Her"
- ✅ Убрана плашка обновления до новой версии
- ✅ Thinking блоки: анимированные, серые, мельче, italic; заголовок сливается с чатом
- ✅ Select/dropdown: тёмный фон `#1e1e22`, читабельные option-ы

### Функциональность
- ✅ Веб-поиск: нативный OpenWebUI (DuckDuckGo, с анимацией и ссылками в UI)
  - OpenWebUI Filter `auto_web_search` (global, active) — keyword detection
  - Прокси-уровневый поиск убран
- ✅ Smart Router: смотрит только на ПОСЛЕДНЕЕ сообщение (не историю)
- ✅ Память: только важные личные факты (имя, профессия, предпочтения)
- ✅ Память: `_TRIVIAL_PATTERNS` — 20+ паттернов для фильтрации мусора
- ✅ Память: дедупликация с порогом 0.92
- ✅ Память: удаление из `faiss_map` при `delete_memory()` (иначе удалённые всплывали)
- ✅ Dashboard Memory Viewer: bulk delete кнопка работает
- ✅ Скрыты сломанные модели из dropdown (T-pro-it-1.0, bge-m3, whisper-*, qwen-image-*)
- ✅ Ошибки API: дружественный текст вместо HTTP 502 / зависшего UI
- ✅ URL fetch: если пользователь вставляет ссылку — страница читается и добавляется в контекст
- ✅ Кнопка «Интерпретатор кода» скрыта: JS (MutationObserver в entrypoint) + CSS (aria-label + title селекторы)

### Reasoning
- ✅ `<think>` → `<details>` блоки (нативные deepseek/QwQ)
- ✅ Для `auto` (не `auto-reasoning`) thinking подавляется

---

## Известные нюансы / потенциальные улучшения

1. **Near-duplicates в памяти**: порог 0.92 иногда пропускает немного разные формулировки одного факта. Можно снизить до 0.87-0.88.

2. **Auto-search filter keywords**: только простые ключевые слова. Нет LLM-классификатора (он был убран из прокси). Для более умного определения можно добавить LLM classifier прямо в OpenWebUI filter через `requests` к прокси API.

3. **OpenWebUI auth=false**: `WEBUI_AUTH=false` — нет авторизации. `user_id` в памяти всегда `"default"`. Если нужны multi-user — включить auth и передавать реальный user_id.

4. **FAISS deletions**: при удалении вектор остаётся в FAISS индексе (IndexFlatIP не поддерживает удаление), но `faiss_map` запись удаляется → вектор недостижим. Индекс постепенно накапливает «мёртвые» векторы. Решение: периодически пересобирать индекс.

5. **Image generation**: `qwen-image` / `qwen-image-lightning` — возвращают информативное сообщение об ошибке (API endpoint недоступен). Можно доработать когда MWS откроет endpoint.

6. **web_search.py**: файл остался в проекте (используется для URL fetch). Функция `classify_needs_search()` и `search()` там есть, но в `openai_compat.py` НЕ импортируются — только `fetch_page`, `detect_urls`, `format_page_content`.

---

## Полный код ключевых файлов

### backend/requirements.txt
```
fastapi==0.115.0
uvicorn[standard]==0.30.6
openai==1.51.0
faiss-cpu==1.8.0
pydantic==2.9.2
httpx==0.27.2
sse-starlette==2.1.3
aiosqlite==0.20.0
numpy==1.26.4
packaging>=23.0
duckduckgo-search>=7.0.0
python-multipart>=0.0.9
```

### auto_search_filter.py (OpenWebUI Filter, зарегистрирован как `auto_web_search`)
```python
"""
title: Auto Web Search
description: Automatically enables OpenWebUI native web search when the query needs current information
"""
from typing import Optional


class Filter:
    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        messages = body.get("messages", [])
        if not messages:
            return body

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

        if len(last_user_msg.strip()) < 15:
            return body
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
        ]
        text = last_user_msg.lower()
        if any(kw in text for kw in SEARCH_KEYWORDS):
            if "features" not in body:
                body["features"] = {}
            body["features"]["web_search"] = True
        return body
```

### OpenWebUI API для управления filter (на случай пересоздания)
```python
import json, urllib.request

# Логин (WEBUI_AUTH=false, дефолтный admin)
req = urllib.request.Request(
    'http://localhost:3000/api/v1/auths/signin',
    data=json.dumps({'email':'admin@localhost','password':'admin'}).encode(),
    headers={'Content-Type':'application/json'}
)
token = json.loads(urllib.request.urlopen(req).read())['token']
headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

# Создать filter
code = open('auto_search_filter.py', encoding='utf-8').read()
payload = json.dumps({'id':'auto_web_search','name':'Auto Web Search','content':code,
    'meta':{'description':'Auto web search filter','manifest':{}}}).encode()
urllib.request.urlopen(urllib.request.Request(
    'http://localhost:3000/api/v1/functions/create', data=payload, headers=headers, method='POST'))

# Активировать + сделать глобальным
urllib.request.urlopen(urllib.request.Request(
    'http://localhost:3000/api/v1/functions/id/auto_web_search/toggle',
    data=b'{}', headers=headers, method='POST'))
urllib.request.urlopen(urllib.request.Request(
    'http://localhost:3000/api/v1/functions/id/auto_web_search/toggle/global',
    data=b'{}', headers=headers, method='POST'))
```

---

## Диагностика

```bash
# Проверить что proxy работает
curl http://localhost:8000/health

# Список моделей (должны быть виртуальные + реальные без скрытых)
curl http://localhost:8000/v1/models | python -m json.tool

# Проверить память
curl "http://localhost:8000/api/memory?user_id=default"

# Посмотреть логи в реальном времени
docker compose logs proxy -f --tail=50

# Проверить filter в OpenWebUI
curl -s -X POST http://localhost:3000/api/v1/auths/signin \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@localhost","password":"admin"}' | python -c "import sys,json; print(json.load(sys.stdin)['token'])"
# затем с токеном:
curl http://localhost:3000/api/v1/functions/ -H "Authorization: Bearer TOKEN"
```

---

*Дата последнего обновления контекста: апрель 2026*  
*Проект: D:/mts_gpt/gpthub/*
