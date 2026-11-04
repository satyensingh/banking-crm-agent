# Banking CRM Agent

An agentic assistant for banking relationship managers (RMs). An RM asks for personal-loan prospects in plain language; Claude calls deterministic, read-only CRM tools, and the UI shows ranked prospects, tool traces and WhatsApp **drafts** for review. Nothing is ever sent to customers.

> Scores are heuristics, **not** conversion probabilities. Product matches are preliminary suitability, **not** credit decisions or offers. All customer data is synthetic.

## Architecture

```text
 React + Vite UI (:5173)
        │  POST /api/chat  {sessionId, message}   (Vite proxies /api → backend)
        ▼
 FastAPI backend (:8000 in container, :8080 on host)
   ├─ /api/chat ── LangGraph agent (app/graph_agent.py) ──► LLM (Anthropic, OpenAI or local Ollama)
   │                    │ MCP client (langchain-mcp-adapters, streamable HTTP)
   │                    ▼
   │               mcp service (:8001) ── FastMCP server (app/mcp_server.py) ── 7 read-only tools
   ├─ /api/tools/*  REST adapter over the same tools
   │                    ▼
   │               CRMTools (service.py) → rules.py (pure business rules)
   │                    ▼
   └──────────────► PostgresRepository (read-only transactions) ──► PostgreSQL 16 (:5432)

 mcp service (:8001) ── the FastMCP server over streamable HTTP; used by the chat agent and by external MCP clients
```

| Path | Purpose |
|---|---|
| [backend/app/rules.py](backend/app/rules.py) | Pure, unit-tested business rules (classification, scoring, product match, consent) |
| [backend/app/service.py](backend/app/service.py) | `CRMTools`: orchestrates repository + rules |
| [backend/app/repository.py](backend/app/repository.py) | Parameterised, read-only SQL against `banking_crm_demo` |
| [backend/app/mcp_server.py](backend/app/mcp_server.py) | FastMCP server: typed inputs/outputs, validation, structured errors |
| [backend/app/graph_agent.py](backend/app/graph_agent.py) | LangGraph agent: MCP client tools, consent guard, session memory, UI response shaping |
| [backend/app/main.py](backend/app/main.py) | FastAPI app: `/health`, `/api/tools/*`, `/api/chat` |
| [frontend/](frontend/) | React UI (see [frontend/README.md](frontend/README.md)) |
| [scripts/banking_crm_seed_database.sql](scripts/banking_crm_seed_database.sql) | Schema + synthetic seed data, loaded on first DB start |
| [diagrams/database_diagram.md](diagrams/database_diagram.md) | ER diagram |

## Quick start (Docker)

Requires Docker with Compose v2 and either an Anthropic or OpenAI API key, or a local [Ollama](https://ollama.com) for free use (`ollama pull qwen3:8b`, then set `LLM_PROVIDER=ollama`).

```bash
cp .env.example .env          # set LLM_PROVIDER and the matching API key
docker compose up -d --build
```

| URL | What |
|---|---|
| http://localhost:5173 | UI |
| http://localhost:8080/docs | Backend OpenAPI docs |
| http://localhost:8080/health | Backend + DB health |
| http://localhost:8001/mcp | MCP server (streamable HTTP, bound to localhost) |

The UI uses **demo fixtures** unless `VITE_DEMO_MODE=false` (set in `.env.example`). The seed script only runs when the Postgres volume is empty; to re-seed run `docker compose down -v` (this deletes the database volume).

## Configuration

All variables live in [.env.example](.env.example).

| Variable | Used by | Default | Description |
|---|---|---|---|
| `LLM_PROVIDER` | backend | `anthropic` | `anthropic`, `openai` or `ollama` (free, local) |
| `ANTHROPIC_API_KEY` | backend | – | Required when provider is `anthropic` (503 without it) |
| `CLAUDE_MODEL` | backend | `claude-sonnet-5-5` | Model for the chat agent |
| `OPENAI_API_KEY` | backend | – | Required when provider is `openai` |
| `OPENAI_MODEL` | backend | `gpt-5` | OpenAI model for the chat agent |
| `OPENAI_BASE_URL` | backend | OpenAI | Point at an OpenAI-compatible gateway |
| `OLLAMA_MODEL` | backend | `qwen3:8b` | Local model; run `ollama pull qwen3:8b` first |
| `OLLAMA_BASE_URL` | backend | `http://localhost:11434` | Compose sets `http://host.docker.internal:11434` |
| `OLLAMA_NUM_CTX` | backend | `8192` | Context window (Ollama's 4k default is too small for the tools) |
| `OLLAMA_REASONING` | backend | `false` | `true` makes Qwen3 think first: better tool use, slower |
| `POSTGRES_PASSWORD` | postgres, backend, mcp | `banking_dev_password` | Dev-only default; change outside local use |
| `DATABASE_URL` | backend, mcp | built by compose | Set only when running outside Docker |
| `VITE_DEMO_MODE` | frontend | `true` | `false` calls the real backend |
| `API_PROXY_TARGET` | frontend | `http://backend:8000` | Vite dev-proxy target for `/api` |
| `VITE_API_BASE_URL` | frontend | – | Direct API base URL (skips the proxy) |
| `MCP_SERVER_URL` | backend | `http://127.0.0.1:8001/mcp` | Where the chat agent reaches the MCP server (compose sets `http://mcp:8001/mcp`) |
| `MCP_TRANSPORT` / `MCP_PORT` | mcp | `stdio` / `8001` | `http` for network serving |

Never put secrets in `VITE_*` variables; they are bundled into the browser.

## Local development (without Docker for the backend)

```bash
docker compose up -d postgres                 # database only

cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL='postgresql://banking_user:banking_dev_password@localhost:5432/banking_crm'
export ANTHROPIC_API_KEY=...                  # or LLM_PROVIDER=openai + OPENAI_API_KEY
uvicorn app.main:app --reload --port 8080

# second terminal
cd frontend && npm install
API_PROXY_TARGET=http://localhost:8080 VITE_DEMO_MODE=false npm run dev
```

## Tools

The same seven capabilities are exposed as MCP tools (used by the agent) and, except the profile lookup, as REST endpoints.

| MCP tool | REST | Rule |
|---|---|---|
| `search_customers` | `POST /api/tools/customers/search` | Filter by city, income, credit score, balance, occupation (paginated) |
| `get_customer_profile` | – | Minimised profile (no contact or consent fields) |
| `classify_high_value` | `GET /api/tools/customers/{id}/classification` | Income ≥ ₹80k and balance ≥ ₹100k (illustrative policy) |
| `score_conversion` | `GET /api/tools/customers/{id}/score` | Explainable 0–100 heuristic with blockers |
| `match_products` | `GET /api/tools/customers/{id}/products` | Preliminary suitability, optional `product_code` |
| `check_whatsapp_permission` | `GET /api/tools/customers/{id}/whatsapp-permission` | Opt-in, do-not-contact, contact cooldown |
| `rank_prospects` | `POST /api/tools/prospects/rank` | Eligible, (by default) contactable prospects, ranked by score |

All tools are read-only (`readOnlyHint`) and queries run in `READ ONLY` transactions.

**Errors** from MCP tools are JSON in the error message: `{"code": "NOT_FOUND" | "DATABASE_UNAVAILABLE" | "INVALID_INPUT" | "INTERNAL_ERROR", "message": "...", "retryable": bool}`. Unexpected exceptions are masked; details go to server logs only.

### Using the MCP server directly

```bash
cd backend
python -m app.mcp_server                       # stdio (e.g. for Claude Desktop / Claude Code)
MCP_TRANSPORT=http python -m app.mcp_server    # http://localhost:8001/mcp
```

Claude Code example: `claude mcp add --transport http banking-crm http://localhost:8001/mcp`.

### `/api/chat`

```bash
curl -s localhost:8080/api/chat -H 'content-type: application/json' \
  -d '{"sessionId":"demo-1","message":"Top 3 personal loan prospects with WhatsApp drafts"}'
```

Returns `{text, tools: [{name, detail, status}], result: {type, customers, messages, total, mode}}`. Notes:

- Session history (last 20 messages, 200 sessions) is **in memory**: it resets on restart and does not work across multiple backend workers.
- The provider is chosen once at startup via `LLM_PROVIDER`. OpenAI runs through the stateless Responses API (`store=false`), which the newest OpenAI models require for tool calling. Both providers use the same tools, prompt and response shape.
- `save_whatsapp_drafts` is an agent-local tool that records drafts for review. It rejects customers whose WhatsApp permission was not confirmed by a tool in the same turn.
- Errors: 503 (no/invalid API key or unknown `LLM_PROVIDER`), 429 (rate limited), 502 (Anthropic API failure).

## Testing

```bash
cd backend && source .venv/bin/activate
pytest -q
```

| Suite | Covers |
|---|---|
| `tests/test_rules.py` | Business rules, eligibility blockers |
| `tests/test_api.py` | REST adapter, status codes, validation |
| `tests/test_mcp_server.py` | MCP protocol via in-memory FastMCP client: schemas, validation, structured errors, masking |
| `tests/test_chat.py` | `/api/chat` with scripted fake Anthropic and OpenAI clients and the real MCP server |

Tests use a fake repository and fake LLM clients: no database, network or API key needed. The live Postgres, Anthropic and OpenAI paths are not covered by automated tests.

## Design notes and limitations

- **Deterministic core:** every number the agent reports comes from `rules.py`; the LLM only selects tools and writes prose.
- **PII:** search and profile tools return a fixed allow-list of fields (no phone, email or consent flags).
- **Ranking scalability:** `rank_prospects` scans all matching rows in Python (capped at 10,000). Move scoring into SQL before using large datasets.
- **No auth** on the backend or MCP HTTP endpoint: local development only. Add authentication before exposing either.
- **Dev defaults:** the Postgres password default and the frontend dev server are for local use only.
