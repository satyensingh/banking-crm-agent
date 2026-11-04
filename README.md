# Banking CRM Agent

An agentic assistant for banking relationship managers (RMs). An RM asks for personal-loan prospects in plain language; Claude calls deterministic, read-only CRM tools, and the UI shows ranked prospects, tool traces and WhatsApp **drafts** for review. Nothing is ever sent to customers.

> Scores are heuristics, **not** conversion probabilities. Product matches are preliminary suitability, **not** credit decisions or offers. All customer data is synthetic.

## Architecture

```text
 Chainlit UI (:8000)  ── chainlit_app.py
        │  in-process call
        ▼
 LangGraph agent (app/graph_agent.py) ──► LLM: OpenAI | Anthropic | Ollama (Qwen3 8B, free/local)
        │  MCP client (langchain-mcp-adapters, streamable HTTP)
        ▼
 mcp service (:8001) ── FastMCP server (app/mcp_server.py) ── 7 read-only tools
        ▼
 CRMTools (service.py) → rules.py (pure business rules)
        ▼
 PostgresRepository (read-only transactions) ──► PostgreSQL 16 (:5432)

 backend service (:8080) ── optional FastAPI REST adapter over the same CRMTools (not used by the chat)
```

| Path | Purpose |
|---|---|
| [backend/app/rules.py](backend/app/rules.py) | Pure, unit-tested business rules (classification, scoring, product match, consent) |
| [backend/app/service.py](backend/app/service.py) | `CRMTools`: orchestrates repository + rules |
| [backend/app/repository.py](backend/app/repository.py) | Parameterised, read-only SQL against `banking_crm_demo` |
| [backend/app/mcp_server.py](backend/app/mcp_server.py) | FastMCP server: typed inputs/outputs, validation, structured errors |
| [backend/app/graph_agent.py](backend/app/graph_agent.py) | LangGraph agent: MCP client tools, consent guard, session memory, UI response shaping |
| [backend/chainlit_app.py](backend/chainlit_app.py) | Chainlit chat UI: starters, live tool steps, prospect table + CSV, WhatsApp drafts |
| [backend/app/main.py](backend/app/main.py) | Optional FastAPI REST adapter: `/health`, `/api/tools/*` |
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
| http://localhost:8000 | Chat UI (Chainlit) |
| http://localhost:8080/docs | REST adapter OpenAPI docs (optional) |
| http://localhost:8080/health | REST adapter + DB health |
| http://localhost:8001/mcp | MCP server (streamable HTTP, bound to localhost) |

The seed script only runs when the Postgres volume is empty; to re-seed run `docker compose down -v` (this deletes the database volume).

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
| `MCP_SERVER_URL` | backend | `http://127.0.0.1:8001/mcp` | Where the chat agent reaches the MCP server (compose sets `http://mcp:8001/mcp`) |
| `MCP_TRANSPORT` / `MCP_PORT` | mcp | `stdio` / `8001` | `http` for network serving |

## Local development (without Docker for the backend)

```bash
docker compose up -d postgres                 # database only

cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL='postgresql://banking_user:banking_dev_password@localhost:5432/banking_crm'
MCP_TRANSPORT=http python -m app.mcp_server   # terminal 1: FastMCP server on :8001

# terminal 2 (same venv): pick one provider
export LLM_PROVIDER=ollama OLLAMA_BASE_URL=http://localhost:11434   # free: `ollama pull qwen3:8b`
# export LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=...   or   LLM_PROVIDER=openai OPENAI_API_KEY=...
chainlit run chainlit_app.py -w                # UI on http://localhost:8000
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

### Chat agent (Chainlit + LangGraph)

- Each tool call appears live as a collapsible step. Ranked prospects are shown as a table with a CSV download, and an action button asks the agent for WhatsApp drafts.
- Session memory is a LangGraph in-memory checkpointer keyed by the Chainlit session id: it resets on restart, is unbounded, and does not work across multiple workers. Use the Postgres checkpointer for durability.
- The provider is chosen once at startup via `LLM_PROVIDER`. OpenAI runs through the Responses API. All providers use the same tools, prompt and response shape.
- `save_whatsapp_drafts` is an agent-local tool that records drafts for review; nothing is ever sent. It rejects customers whose WhatsApp permission was not confirmed by a tool in the same turn.
- Failures show as a message in the chat: missing or invalid API key, rate limit, model or MCP server unreachable, Ollama model not pulled.

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
| `tests/test_graph_agent.py` | LangGraph agent with a scripted fake chat model and the real MCP server via `langchain-mcp-adapters`: tool flow, consent guard, memory, limits, providers |
| `tests/test_chainlit_app.py` | Prospect table shaping for the Chainlit UI |

Tests use a fake repository and a fake chat model: no database, network or API key needed. The live Postgres, Anthropic, OpenAI and Ollama paths, and the Chainlit UI itself, are not covered by automated tests.

## Design notes and limitations

- **Deterministic core:** every number the agent reports comes from `rules.py`; the LLM only selects tools and writes prose.
- **PII:** search and profile tools return a fixed allow-list of fields (no phone, email or consent flags).
- **Ranking scalability:** `rank_prospects` scans all matching rows in Python (capped at 10,000). Move scoring into SQL before using large datasets.
- **No auth** on the Chainlit UI, the REST adapter or the MCP HTTP endpoint: local development only. Add authentication (Chainlit supports password/OAuth) before exposing any of them.
- **Dev defaults:** the Postgres password default is for local use only.
