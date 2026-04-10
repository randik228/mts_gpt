# GPTHub

Unified AI gateway for [MWS GPT API](https://api.gpt.mws.ru) — built for True Tech Hack 2026.

Three services in one `docker compose up`:

| Service | Port | What it does |
|---|---|---|
| **OpenWebUI** | 3000 | Chat interface — talk to any model |
| **Proxy** | 8000 | FastAPI backend — routing, memory, reasoning |
| **Dashboard** | 3001 | Admin panel — task chains, analytics, model catalog |

---

## Quick start

### Requirements

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose)
- MWS GPT API key — get one at [api.gpt.mws.ru](https://api.gpt.mws.ru)

### 1. Clone

```bash
git clone https://github.com/YOUR_USERNAME/gpthub.git
cd gpthub
```

### 2. Create `.env`

```bash
cp .env.example .env
```

Open `.env` and paste your key:

```env
MWS_API_KEY=your_api_key_here
```

### 3. Start

```bash
docker compose up --build
```

First run downloads ~2 GB of images. Subsequent starts take ~10 seconds.

### 4. Open

| URL | Service |
|---|---|
| http://localhost:3000 | Chat (OpenWebUI) |
| http://localhost:3001 | Dashboard |
| http://localhost:8000/docs | Proxy API docs |

---

## Features

### Chat (OpenWebUI — port 3000)
- All 22 MWS GPT models available
- **Smart aliases**: `auto`, `auto-code`, `auto-reasoning`, `auto-creative`, `auto-fast` — automatically route to the best model for the task
- Reasoning/thinking blocks from models like DeepSeek-R1 are shown as collapsible purple blocks
- Custom MTS-branded dark theme

### Proxy API (port 8000)
- **OpenAI-compatible** `/v1/chat/completions` endpoint — drop-in replacement
- **Semantic memory** — `/api/memory/add`, `/api/memory/search` with FAISS vector search
- **Task chains** — `/api/taskchain/run` — pipeline multiple models (transcribe → analyze → summarize)
- **Routing analytics** — `/api/analytics` — see which models are used and latencies

### Dashboard (port 3001)
- **Task Chain Builder** — visual pipeline builder, run multi-step AI workflows
- **Memory Viewer** — browse and search the semantic memory store
- **Routing Analytics** — model usage stats with latency breakdown
- **Model Catalog** — all 22 models with capabilities, speed, and pricing tiers

---

## Model aliases

| Alias | Routes to | Use for |
|---|---|---|
| `auto` | gpt-oss-20b | General purpose |
| `auto-code` | qwen3-coder-480b-a35b | Code generation |
| `auto-reasoning` | deepseek-r1-distill-qwen-32b | Complex reasoning |
| `auto-creative` | Qwen3-235B-A22B-Instruct | Creative writing |
| `auto-fast` | gpt-oss-7b | Fast, lightweight tasks |

---

## Project structure

```
gpthub/
├── backend/                  # FastAPI proxy
│   ├── main.py               # App entry + router setup
│   ├── requirements.txt
│   ├── api/
│   │   ├── openai_compat.py  # /v1/chat/completions (OpenAI-compatible, SSE)
│   │   ├── memory.py         # Semantic memory (FAISS)
│   │   ├── taskchain.py      # Multi-step task pipelines
│   │   ├── analytics.py      # Request routing stats
│   │   └── models.py         # Model catalog
│   └── core/
│       ├── client.py         # MWS GPT API client
│       ├── router.py         # Model alias resolution
│       ├── memory_store.py   # FAISS vector store
│       └── reasoning_parser.py # Extract <think> blocks from responses
├── dashboard/                # React + Vite admin panel
│   └── src/
│       ├── App.tsx
│       └── pages/
│           ├── TaskChainBuilder.tsx
│           ├── MemoryViewer.tsx
│           ├── RoutingAnalytics.tsx
│           └── ModelCatalog.tsx
├── openwebui-custom.css      # MTS dark theme for OpenWebUI
├── openwebui-entrypoint.sh   # CSS injection script (runs on container start)
├── docker-compose.yml
└── .env.example
```

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `MWS_API_KEY` | ✅ | — | MWS GPT API key |
| `MWS_API_BASE` | | `https://api.gpt.mws.ru/v1` | API base URL |
| `DEFAULT_MODEL` | | `gpt-oss-20b` | Fallback model |
| `EMBEDDING_MODEL` | | `bge-m3` | Model for memory embeddings |

---

## Useful commands

```bash
# Start everything
docker compose up --build

# Start in background
docker compose up -d --build

# View logs
docker compose logs -f proxy
docker compose logs -f open-webui

# Restart a single service after code change
docker compose up -d --build proxy

# Stop everything
docker compose down

# Stop and wipe all data (memory, chat history)
docker compose down -v
```

---

## Troubleshooting

**Port already in use**
```bash
# Find what's using the port
netstat -ano | findstr :3000   # Windows
lsof -i :3000                  # Mac/Linux
```

**Models not showing in OpenWebUI**
- Check that the proxy is healthy: `curl http://localhost:8000/v1/models`
- Make sure `MWS_API_KEY` is set in `.env`

**Chat history lost after restart**
- This is normal if you ran `docker compose down -v`
- Use `docker compose down` (without `-v`) to keep data

---

## License

MIT
