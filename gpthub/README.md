# GPTHub

Корпоративный AI-портал поверх MWS GPT API — умный роутинг, память, веб-поиск, генерация изображений, аналитика.

## Что внутри

| Компонент | Адрес | Описание |
|---|---|---|
| **OpenWebUI** | http://localhost:3000 | Чат-интерфейс (OpenWebUI v0.6.5) |
| **Proxy** | http://localhost:8000 | FastAPI прокси: роутинг, память, аналитика |
| **Dashboard** | http://localhost:3001 | Дашборд: Memory, Analytics, Models, TaskChain |

### Возможности

| Функция | Описание |
|---|---|
| **Smart Router** | Автоматически выбирает модель по типу запроса (keyword + embedding similarity) |
| **Виртуальные модели** | ⚡ auto, 💻 auto-code, 🧠 auto-reasoning, ✨ auto-creative, 🚀 auto-fast |
| **Веб-поиск** | Автоматически включается по ключевым словам («найди», «погода», «курс» и др.) |
| **Память** | Факты о пользователе сохраняются через bge-m3 + FAISS, инъектируются в контекст |
| **Reasoning** | Мышление DeepSeek-R1 / QwQ отображается в свёрнутом блоке `<details>` |
| **Изображения** | Генерация через qwen-image-lightning (маршрутизация по словам «нарисуй» и т.д.) |
| **Аудио** | Транскрипция через Whisper (голосовые сообщения в OpenWebUI) |
| **URL-fetch** | Если в сообщении есть ссылка — страница читается и добавляется в контекст |
| **Task Chain** | Многошаговые пайплайны: Документ→Анализ, Голос→Код и др. |
| **Аналитика** | История роутинга, латентность, статистика по моделям |

---

## Быстрый старт

### Требования

| | Минимум | Рекомендуется |
|---|---|---|
| RAM | 4 GB | 8 GB |
| Диск | 6 GB | 10 GB |
| Docker | 24+ | 25+ |
| Docker Compose | v2.20+ | v2.24+ |

### 1. Клонировать

```bash
git clone https://github.com/randik228/mts_gpt.git
cd mts_gpt/gpthub
```

### 2. Создать `.env`

```bash
cp .env.example .env          # Linux / Mac / Git Bash
copy .env.example .env        # Windows CMD
```

Открыть `.env` и вставить ключ API MWS GPT:

```
MWS_API_KEY=sk-ваш_ключ_здесь
```

> Ключ получить на https://api.gpt.mws.ru

### 3. Запустить

```bash
docker compose up -d
```

Первый запуск занимает **3–5 минут** — скачивается образ OpenWebUI (~3 GB).

```bash
docker compose ps
```

Все сервисы должны показывать **`Up`** или **`healthy`**:
```
NAME                    STATUS
gpthub-proxy-1          Up (healthy)
gpthub-open-webui-1     Up
gpthub-dashboard-1      Up
```

### 4. Открыть

- **Чат:** http://localhost:3000
- **Дашборд:** http://localhost:3001

### 5. Войти

На странице логина OpenWebUI есть **кнопки быстрого входа**:

| Кнопка | Email | Пароль | Роль |
|---|---|---|---|
| Admin | `admin@localhost` | `admin` | Администратор (полный доступ, настройки) |
| User | `user@localhost` | `user` | Обычный пользователь |

Оба аккаунта создаются автоматически при первом запуске.

> При первом старте OpenWebUI автоматически настраивается: модели с именами, фильтр поиска, тема, аккаунты — всё готово сразу.

---

## Виртуальные модели

| Модель | Реальная модель | Назначение |
|---|---|---|
| ⚡ `auto` | Smart Router (динамически) | Универсальный — для большинства задач |
| 💻 `auto-code` | qwen3-coder-480b-a35b | Написание, отладка и анализ кода |
| 🧠 `auto-reasoning` | deepseek-r1-distill-qwen-32b | Пошаговые рассуждения, математика |
| ✨ `auto-creative` | Qwen3-235B-A22B-Instruct-2507-FP8 | Творческое письмо, идеи, сторителлинг |
| 🚀 `auto-fast` | gpt-oss-20b | Молниеносные ответы на простые вопросы |

### Smart Router — как выбирается модель

1. **Виртуальный хинт** — пользователь явно выбрал `auto-code` и т.д.
2. **Мультимодал** — есть изображение → vision-модель; аудио → whisper
3. **Keyword** — регулярки по типу запроса (~0 ms)
4. **Embedding** — cosine similarity bge-m3, порог ≥ 0.70
5. **Default** → `gpt-oss-20b`

---

## Веб-поиск

Поиск включается **автоматически** при ключевых словах в запросе:

```
найди, поищи, актуальный, последние новости, погода, курс валют,
сколько стоит, что сейчас, рейтинг, в интернете, search for, ...
```

Используется нативный поиск OpenWebUI (DuckDuckGo) — с анимацией запроса,
ссылками-бейджами и списком источников прямо в чате.

Поиск также можно включить вручную кнопкой 🔍 в панели чата.

---

## Архитектура

```
Browser
  │
  ├── :3000  Open WebUI (ghcr.io image)
  │            └── OPENAI_API_BASE_URL → proxy:8000/v1
  │
  ├── :3001  Dashboard (React + Vite)
  │            └── /api/* → proxy:8000
  │
  └── :8000  Proxy (FastAPI)
               ├── POST /v1/chat/completions  → MWS API (smart routing)
               ├── GET  /v1/models            → virtual + real models
               ├── POST /v1/embeddings        → bge-m3
               ├── POST /v1/audio/transcriptions → Whisper
               ├── GET/POST/DELETE /api/memory   → FAISS + SQLite
               ├── GET  /api/analytics           → routing log
               ├── GET  /api/models              → model catalog
               └── GET/POST /api/taskchain       → Task Chain Engine
```

---

## Данные

| Docker volume | Содержимое |
|---|---|
| `gpthub_webui_data` | БД OpenWebUI (чаты, настройки) |
| `gpthub_memory_data` | FAISS-индекс + SQLite (память пользователя, аналитика) |

> Чтобы полностью сбросить все данные: `docker compose down -v`

---

## Переменные окружения

| Переменная | Сервис | Описание |
|---|---|---|
| `MWS_API_KEY` | proxy, open-webui | **Обязателен.** Ключ API MWS GPT |
| `MWS_API_BASE` | proxy | URL API (по умолчанию `https://api.gpt.mws.ru/v1`) |
| `DEFAULT_MODEL` | proxy | Дефолтная модель (`gpt-oss-20b`) |
| `EMBEDDING_MODEL` | proxy | Модель для эмбеддингов (`bge-m3`) |

---

## Обновление

Если у вас уже развёрнут GPTHub и нужно обновиться до последней версии:

```bash
cd mts_gpt

# 1. Получить последний код
git pull origin main

# 2. Пересобрать и перезапустить все сервисы
cd gpthub
docker compose up -d --build

# 3. Проверить что всё работает
docker compose ps
```

Все данные (чаты, память, аналитика) сохраняются в Docker volumes и **не теряются** при обновлении.

> **Если что-то сломалось** после обновления — полный сброс:
> ```bash
> docker compose down -v          # удалить контейнеры + данные
> docker compose up -d --build    # поднять заново с нуля
> ```

---

## Полезные команды

```bash
# Перезапустить один сервис
docker compose restart open-webui

# Пересобрать после изменений в коде
docker compose up -d --build proxy
docker compose up -d --build dashboard

# Логи в реальном времени
docker compose logs -f
docker compose logs proxy -f

# Остановить всё
docker compose down

# Остановить и удалить все данные
docker compose down -v
```

---

## Устранение неполадок

### `$'\r': command not found` — CRLF на Windows

Git на Windows конвертирует LF→CRLF. Это **автоматически решено**: entrypoint запускается через `tr -d '\r' | bash`. Если ошибка всё равно есть — обновите:
```bash
git pull && docker compose up -d --force-recreate open-webui
```

### Прокси не отвечает — нет `.env`

```bash
cat .env   # убедиться что файл существует и содержит MWS_API_KEY
```

### Open WebUI запускается, но модели не загружаются

Прокси ещё не прошёл healthcheck. Подождать 30–60 секунд или проверить:
```bash
docker compose logs proxy --tail 30
```

### Занят порт 3000 или 3001

Поменять в `docker-compose.yml`: `"3000:8080"` → `"3002:8080"`.

### Первый запуск очень долгий

Образ `open-webui:v0.6.5` весит ~3 GB. При медленном интернете — 10–20 минут:
```bash
docker compose pull   # скачать образы заранее
docker compose up -d  # затем запустить
```
