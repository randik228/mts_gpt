# GPTHub

OpenAI-compatible proxy поверх MWS GPT API с умным роутингом, памятью и дашбордом.

## Что внутри

| Компонент | Адрес | Описание |
|---|---|---|
| **OpenWebUI** | http://localhost:3000 | Чат-интерфейс (OpenWebUI v0.6.5) |
| **Proxy** | http://localhost:8000 | FastAPI прокси: роутинг, память, аналитика |
| **Dashboard** | http://localhost:3001 | Дашборд: Task Chain, Memory, Analytics, Models |

### Ключевые возможности
- **Smart Router** — автоматически выбирает модель по типу запроса (keyword + embedding similarity)
- **Reasoning** — мышление deepseek-r1 / QwQ отображается в свёрнутом `<details>` блоке
- **Память** — факты о пользователе сохраняются через bge-m3 + FAISS, инъектируются в контекст
- **Task Chain** — многошаговые пайплайны (Документ→Анализ, Голос→Код и др.)
- **Аналитика** — история роутинга, латентность, статистика по моделям
- **Виртуальные модели** — `auto`, `auto-code`, `auto-reasoning`, `auto-creative`, `auto-fast`

---

## Быстрый старт

### 1. Требования

| | Минимум | Рекомендуется |
|---|---|---|
| RAM | 4 GB | 8 GB |
| Диск | 6 GB свободно | 10 GB |
| Docker | 24+ | 25+ |
| Docker Compose | v2.20+ | v2.24+ |

### 2. Клонировать репозиторий

```bash
git clone <repo-url>
cd gpthub
```

### 3. Создать `.env`

```bash
cp .env.example .env          # Linux / Mac / Git Bash
copy .env.example .env        # Windows CMD
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

Симптом в логах:
```
$'\r': command not found
set: invalid option
```

Git на Windows по умолчанию конвертирует LF→CRLF при `git clone`.
Начиная с текущей версии это **автоматически решено** в `docker-compose.yml`:
entrypoint запускается через `tr -d '\r' | bash`, то есть файл нечувствителен
к line endings.

Если ошибка всё равно появляется — у вас старый `docker-compose.yml`:
```bash
git pull
docker compose up -d --force-recreate open-webui
```

---

**Причина 1 — не создан `.env`**
```bash
# Убедиться что файл существует и содержит ключ
cat .env
```

---

**Причина 2 — proxy не успел стартовать**

Open WebUI ждёт пока proxy пройдёт health check (`/health`).
При медленной инициализации (первый запуск, загрузка FAISS) Open WebUI
автоматически перезапустится через `restart: unless-stopped`.

Проверить логи proxy:
```bash
docker compose logs proxy --tail 30
```

---

**Причина 3 — долгая загрузка образа**

Образ `ghcr.io/open-webui/open-webui:v0.6.5` весит ~3 GB.
При плохом соединении загрузка может занять 10–20 мин. Следить за прогрессом:
```bash
docker compose pull open-webui
```

---

**Причина 4 — занят порт 3000**
```bash
# Linux/Mac
lsof -i :3000
# Windows PowerShell
netstat -ano | findstr :3000
```

Поменять порт в `docker-compose.yml`: `"3000:8080"` → `"3002:8080"`.

---

**Причина 5 — нехватка памяти**

Open WebUI + Proxy требуют ~2–3 GB RAM. Проверить логи:
```bash
docker compose logs open-webui | tail -20
```

---

### "Только dashboard запустился, чат нет"

Вероятно, сервисы запускались по одному:
```bash
# НЕПРАВИЛЬНО — запускает только dashboard (и proxy как зависимость)
docker compose up dashboard

# ПРАВИЛЬНО — запускает все три сервиса
docker compose up -d
```

---

### Полезные команды

```bash
# Перезапуск одного сервиса
docker compose restart open-webui

# Пересборка после изменений в коде
docker compose build proxy dashboard
docker compose up -d

# Логи в реальном времени
docker compose logs -f
docker compose logs -f open-webui

# Остановить всё
docker compose down

# Остановить и удалить данные (чаты, память, аналитика)
docker compose down -v
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
3. **Keyword** — регулярки, ~0 ms
4. **Embedding** — cosine similarity bge-m3, порог ≥ 0.70
5. **Default** — `gpt-oss-20b`

### Виртуальные модели

| ID | Реальная модель | Назначение |
|---|---|---|
| `auto` | Smart Router | Универсальный автовыбор |
| `auto-code` | qwen3-coder-480b-a35b | Код и программирование |
| `auto-reasoning` | deepseek-r1-distill-qwen-32b | Рассуждения, математика |
| `auto-creative` | Qwen3-235B-A22B-Instruct-2507-FP8 | Творческие и сложные задачи |
| `auto-fast` | gpt-oss-20b | Быстрые ответы |

---

## Данные

| Docker volume | Содержимое |
|---|---|
| `gpthub_webui_data` | БД OpenWebUI (чаты, настройки) |
| `gpthub_memory_data` | FAISS-индекс + SQLite (память, аналитика) |

---

## Переменные окружения

| Переменная | Сервис | Описание |
|---|---|---|
| `MWS_API_KEY` | proxy, open-webui | **Обязателен.** Ключ API MWS GPT |
| `MWS_API_BASE` | proxy | URL API (по умолчанию `https://api.gpt.mws.ru/v1`) |
| `DEFAULT_MODEL` | proxy | Дефолтная модель (`gpt-oss-20b`) |
| `EMBEDDING_MODEL` | proxy | Модель для эмбеддингов (`bge-m3`) |
