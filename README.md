# GPTHub

OpenAI-compatible proxy поверх MWS GPT API с умным роутингом, памятью и дашбордом.

## Что внутри

| Компонент | Адрес | Описание |
|---|---|---|
| **OpenWebUI** | http://localhost:3000 | Чат-интерфейс (OpenWebUI v0.6.5) |
| **Proxy** | http://localhost:8000 | FastAPI прокси: роутинг, память, аналитика |
| **Dashboard** | http://localhost:3001 | Дашборд: Task Chain, Memory, Analytics, Models |

### Ключевые возможности
- **Smart Router** — автоматически выбирает модель по типу запроса (keyword + embedding)
- **Reasoning** — мышление deepseek-r1 и QwQ отображается в свёрнутом `<details>` блоке
- **Память** — факты о пользователе извлекаются через bge-m3 + FAISS, инъектируются в контекст
- **Task Chain** — многошаговые пайплайны (Документ→Анализ, Голос→Код и др.)
- **Аналитика** — история роутинга, латентность, статистика по моделям
- **Виртуальные модели** — `auto`, `auto-code`, `auto-reasoning`, `auto-creative`, `auto-fast`

---

## Быстрый старт

### 1. Требования

| | Минимум | Рекомендуется |
|---|---|---|
| RAM | 4 GB | 8 GB |
| Диск | 6 GB | 10 GB |
| Docker | 24+ | 25+ |
| Docker Compose | v2.20+ | v2.24+ |

### 2. Клонировать репозиторий

```bash
git clone <repo-url>
cd gpthub
```

### 3. Создать `.env`

```bash
cp .env.example .env
```

Открыть `.env` и вставить ключ API MWS GPT:

```
MWS_API_KEY=sk-ваш_ключ_здесь
```

> Ключ получить на https://api.gpt.mws.ru

### 4. Запустить

```bash
docker compose up -d
```

Первый запуск занимает **3–5 минут** — скачивается образ OpenWebUI (~3 GB).

Проверить статус:

```bash
docker compose ps
```

Все три сервиса должны показывать **`Up`** или **`healthy`**:
```
NAME                    STATUS
gpthub-proxy-1          Up (healthy)
gpthub-open-webui-1     Up (healthy)
gpthub-dashboard-1      Up
```

### 5. Открыть

- Чат: http://localhost:3000
- Дашборд: http://localhost:3001

---

## Устранение неполадок

### Чат не запускается (Open WebUI)

**Причина 0 — CRLF line endings (Windows)**

Симптом в логах: `$'\r': command not found` или `set: invalid option`.

Git на Windows по умолчанию конвертирует LF → CRLF при clone. Shell-скрипты в Linux-контейнере ломаются.

Решение — один раз после клонирования:
```bash
# Вариант A: git нормализует файлы согласно .gitattributes
git rm --cached openwebui-entrypoint.sh
git checkout openwebui-entrypoint.sh

# Вариант B: принудительно конвертировать через PowerShell
(Get-Content openwebui-entrypoint.sh -Raw) -replace "`r`n", "`n" | Set-Content openwebui-entrypoint.sh -NoNewline

# Вариант C: через WSL/Git Bash
sed -i 's/\r//' openwebui-entrypoint.sh
```

Затем пересоздать контейнер:
```bash
docker compose up -d --force-recreate open-webui
```

> Этот баг исправлен в `.gitattributes` — на новых клонах не воспроизводится.

**Причина 1 — не создан `.env`**
```bash
# Убедиться что файл существует и содержит ключ
cat .env
```

**Причина 2 — proxy не успел стартовать**

Open WebUI ждёт, пока proxy пройдёт health check (`/health`). Если proxy медленно инициализируется (первый запуск с загрузкой FAISS-индекса), Open WebUI перезапустится автоматически через `restart: unless-stopped`.

Проверить логи proxy:
```bash
docker compose logs proxy --tail 30
```

**Причина 3 — медленная загрузка образа**

Образ `ghcr.io/open-webui/open-webui:v0.6.5` весит ~3 GB. При плохом интернете загрузка может занять 10–20 минут. Следить за прогрессом:
```bash
docker compose pull open-webui
```

**Причина 4 — занят порт 3000**
```bash
# Linux/Mac
lsof -i :3000
# Windows
netstat -ano | findstr :3000
```

Поменять порт в `docker-compose.yml`: `"3000:8080"` → `"3002:8080"`.

**Причина 5 — нехватка памяти**

Open WebUI + Proxy требуют ~2–3 GB RAM. Если система использует swap, контейнер может быть убит OOM:
```bash
docker compose logs open-webui | tail -20
```

### Dashboard запустился, чат нет

Вероятно, запуск был с явным указанием сервиса:
```bash
# НЕ ПРАВИЛЬНО — запускает только dashboard и proxy
docker compose up dashboard

# ПРАВИЛЬНО — запускает всё
docker compose up -d
```

### Перезапуск одного сервиса

```bash
docker compose restart open-webui
docker compose restart proxy
docker compose restart dashboard
```

### Полная пересборка (после изменений в коде)

```bash
docker compose build proxy dashboard
docker compose up -d
```

### Просмотр логов

```bash
# Все сервисы
docker compose logs -f

# Конкретный сервис
docker compose logs -f proxy
docker compose logs -f open-webui
```

---

## Архитектура

```
Browser
  │
  ├── :3000  Open WebUI (ghcr.io image)
  │            └── OPENAI_API_BASE_URL → proxy:8000/v1
  │
  ├── :3001  Dashboard (React + Vite, local build)
  │            └── VITE_PROXY_URL → proxy:8000
  │
  └── :8000  Proxy (FastAPI, local build)
               ├── /v1/chat/completions  → MWS API (smart routing)
               ├── /v1/models            → virtual + real models
               ├── /v1/embeddings        → bge-m3
               ├── /api/memory           → FAISS + SQLite
               ├── /api/taskchain        → Task Chain Engine
               ├── /api/analytics        → routing log
               └── /api/models           → model catalog
```

### Smart Router — приоритет выбора модели

1. **Виртуальный хинт** — пользователь выбрал `auto-code`, `auto-reasoning` и т.д.
2. **Мультимодал** — есть изображение → vision-модель; аудио → whisper
3. **Keyword** — регулярки O(n), ~0 ms
4. **Embedding** — cosine similarity bge-m3, порог ≥ 0.70
5. **Default** — `gpt-oss-20b`

### Виртуальные модели

| ID | Реальная модель | Назначение |
|---|---|---|
| `auto` | Smart Router | Универсальный автовыбор |
| `auto-code` | qwen3-coder-480b-a35b | Код и программирование |
| `auto-reasoning` | deepseek-r1-distill-qwen-32b | Рассуждения, математика |
| `auto-creative` | Qwen3-235B-A22B-Instruct-2507-FP8 | Творческие задачи |
| `auto-fast` | gpt-oss-20b | Быстрые ответы |

---

## Данные

Данные хранятся в Docker volumes (сохраняются между перезапусками):

| Volume | Содержимое |
|---|---|
| `gpthub_webui_data` | База OpenWebUI (чаты, настройки пользователей) |
| `gpthub_memory_data` | FAISS-индекс + SQLite (память, аналитика) |

Очистить всё:
```bash
docker compose down -v
```

---

## Переменные окружения

| Переменная | Сервис | Описание |
|---|---|---|
| `MWS_API_KEY` | proxy, open-webui | **Обязателен.** Ключ API MWS GPT |
| `MWS_API_BASE` | proxy | URL API (по умолчанию `https://api.gpt.mws.ru/v1`) |
| `DEFAULT_MODEL` | proxy | Дефолтная модель (`gpt-oss-20b`) |
| `EMBEDDING_MODEL` | proxy | Модель для эмбеддингов (`bge-m3`) |
