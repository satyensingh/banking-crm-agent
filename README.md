# Banking CRM Agent

An AI assistant for banking **relationship managers (RMs)**. The RM asks for personal-loan prospects in plain language; an LLM agent calls deterministic, read-only CRM tools against a PostgreSQL database; the chat UI shows ranked prospects, the tools that ran, and WhatsApp **drafts** for review.

> **Nothing is ever sent to customers.** Drafts are for RM review only.
> Scores are heuristics, **not** conversion probabilities. Product matches are preliminary suitability, **not** credit decisions or offers. All customer data is synthetic.

**Stack:** Chainlit (UI) · LangGraph (agent) · OpenAI / Anthropic / Ollama (LLM) · FastMCP (tool server) · PostgreSQL (data)

## Setup contents

- [Prerequisites](#prerequisites)
- [Quick start (Docker)](#quick-start-docker)
- [Choosing an LLM provider](#choosing-an-llm-provider)
- [Configuration reference](#configuration-reference)
- [Local development (without Docker)](#local-development-without-docker)
- [Replacing the dev logins](#replacing-the-dev-logins)
- [Run tests](#run-tests)
- [Troubleshooting](#troubleshooting)
- [Documentation and diagrams](#documentation-and-diagrams)

For architecture, execution flow, tool design, business rules and trade-offs, see the [documentation index](docs/README.md). For example prompts and UI behavior, see [Using the app](docs/usage.md).

## Prerequisites

| Need | Why |
|---|---|
| **Docker** with Compose v2 | Runs the whole stack ([install](https://docs.docker.com/get-docker/)) |
| **One LLM option** | An [OpenAI](https://platform.openai.com/api-keys) key, an [Anthropic](https://console.anthropic.com/) key, **or** [Ollama](https://ollama.com) (free, local) |
| Python **3.12** *(only for [local development](#local-development-without-docker))* | The Docker image uses 3.12. Avoid 3.14: Chainlit's websocket layer fails on it |
| ~6 GB free disk *(only for Ollama)* | The `qwen3:8b` model is about 5 GB |

## Quick start (Docker)

```bash
git clone https://github.com/satyensingh/banking-crm-agent.git
cd banking-crm-agent

cp .env.example .env
```

Edit `.env` and set the provider and its key. For example, with OpenAI:

```ini
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

(For Anthropic or free local Ollama, see [Choosing an LLM provider](#choosing-an-llm-provider).)

**Sign-in works out of the box.** `.env.example` includes a dev-only session secret and a demo login, so there's nothing else to set up:

| Username | Password |
|---|---|
| `rm` | `rm-demo-password` |

These defaults are public (they're in this repo), so the app logs a `SECURITY` warning while they're in use. Replace them before anyone else can reach the app: see [Replacing the dev logins](#replacing-the-dev-logins).

Start everything:

```bash
docker compose up -d --build
```

The first build takes a few minutes. PostgreSQL seeds itself with 150 synthetic customers on first start.

| URL | What |
|---|---|
| **http://localhost:8000** | **Chat UI (Chainlit): start here** |
| http://localhost:8001/mcp | MCP server (streamable HTTP, bound to localhost) |

**Verify it works:** open http://localhost:8000, sign in as `rm` / `rm-demo-password`, and click a starter such as *Find high-value prospects*. You should see tool steps run, then a prospect table.

```bash
docker compose ps                 # postgres (healthy), mcp and chainlit should be "Up"
docker compose logs -f chainlit   # follow the chat service logs
docker compose down               # stop (keeps the database)
docker compose down -v            # stop AND delete database and audit volumes (re-seeds next start)
```

The seed script only runs when the Postgres volume is empty, so use `down -v` if you want fresh data.

## Choosing an LLM provider

Set `LLM_PROVIDER` in `.env`, then restart the chat service: `docker compose up -d chainlit`. The provider is read once at startup.

| Provider | `.env` settings | Cost | Notes |
|---|---|---|---|
| **OpenAI** | `LLM_PROVIDER=openai`<br/>`OPENAI_API_KEY=...` | Paid | Default model `gpt-5` (`OPENAI_MODEL`). Uses the Responses API. `OPENAI_BASE_URL` can point at an OpenAI-compatible gateway. |
| **Anthropic** | `LLM_PROVIDER=anthropic`<br/>`ANTHROPIC_API_KEY=...` | Paid | Default model `claude-sonnet-5-5` (`CLAUDE_MODEL`). |
| **Ollama** | `LLM_PROVIDER=ollama` | **Free**, runs locally | Default model `qwen3:8b` (`OLLAMA_MODEL`). No API key, and customer data never leaves your machine. |

> If `LLM_PROVIDER` is unset, the code defaults to `anthropic`. `.env.example` ships with `openai`.

### Using Ollama (free, local)

```bash
# 1. Install Ollama: https://ollama.com  (macOS: brew install ollama)
# 2. Download the model (~5 GB) and make sure the server is running
ollama pull qwen3:8b

# 3. In .env
#    LLM_PROVIDER=ollama

# 4. Restart the chat service
docker compose up -d chainlit
```

- **Docker reaching Ollama:** the container connects to your machine's Ollama at `http://host.docker.internal:11434` (already set in `docker-compose.yml`). If Ollama listens only on localhost and the container can't connect, start it with `OLLAMA_HOST=0.0.0.0 ollama serve`.
- **Quality:** an 8B model calls tools less reliably than Claude or GPT. Set `OLLAMA_REASONING=true` to make Qwen3 think before acting (better tool use, slower), or try a larger model via `OLLAMA_MODEL`. The consent guard still blocks any draft for a customer whose permission wasn't confirmed, whatever the model does.
- **Context window:** `OLLAMA_NUM_CTX` defaults to 8192 because Ollama's 4k default is too small for the tool schemas plus the system prompt.
- **Status:** the Ollama path is covered by tests with a fake model, but has not been run against a live Qwen3 here. Try a few prompts and expect to tune `OLLAMA_REASONING` or the model.

## Configuration reference

All variables live in [.env.example](.env.example). Docker Compose reads `.env` automatically. Never commit `.env`.

| Variable | Used by | Default | Description |
|---|---|---|---|
| `LLM_PROVIDER` | chainlit | `anthropic` (code) | `anthropic`, `openai` or `ollama` |
| `ANTHROPIC_API_KEY` | chainlit | – | Required for `anthropic` |
| `CLAUDE_MODEL` | chainlit | `claude-sonnet-5-5` | Anthropic model |
| `OPENAI_API_KEY` | chainlit | – | Required for `openai` |
| `OPENAI_MODEL` | chainlit | `gpt-5` | OpenAI model |
| `OPENAI_BASE_URL` | chainlit | OpenAI | OpenAI-compatible gateway or proxy |
| `OLLAMA_MODEL` | chainlit | `qwen3:8b` | Local model name (must be pulled first) |
| `OLLAMA_BASE_URL` | chainlit | `http://localhost:11434` | Compose sets `http://host.docker.internal:11434` |
| `OLLAMA_NUM_CTX` | chainlit | `8192` | Context window in tokens |
| `OLLAMA_REASONING` | chainlit | `false` | `true` makes Qwen3 think first (slower, better tool use) |
| `MCP_SERVER_URL` | chainlit | `http://127.0.0.1:8001/mcp` | Where the agent's MCP client finds the tool server. Compose sets `http://mcp:8001/mcp` |
| `MCP_TRANSPORT` | mcp | `stdio` | `http` to serve over the network (Compose sets it) |
| `MCP_PORT` | mcp | `8001` | MCP server port |
| `DATABASE_URL` | mcp | `postgresql://banking_user:banking_dev_password@localhost:5432/banking_crm` | Compose sets it to the `postgres` container. The default suits local development, so set it only for a different database |
| `CHAINLIT_AUTH_SECRET` | chainlit | dev default in `.env.example` (**required**) | Signs login sessions. Compose won't start without it. Replace the dev default before sharing the app |
| `RM_USERS` | chainlit | `rm` / `rm-demo-password` in `.env.example` | RM logins as `user=<hash>,user2=<hash>`. Empty = nobody can sign in. Replace the demo login before sharing the app |
| `CHAT_MAX_MESSAGE_CHARS` | chainlit | `4000` | Longest chat message accepted |
| `CHAT_RATE_LIMIT_PER_MIN` | chainlit | `10` | Messages per RM per minute |
| `AUDIT_LOG_PATH` | chainlit | `logs/audit.jsonl` | Audit log file. Compose writes to the `audit_logs` volume at `/app/logs/audit.jsonl` |
| `POSTGRES_PASSWORD` | postgres, mcp | `banking_dev_password` | **Dev-only default. Change it outside local use** |

## Local development (without Docker)

Run PostgreSQL in Docker and the Python services on your machine, so you get fast reloads and a debugger.

**1. Database**

```bash
docker compose up -d postgres
```

**2. Python environment** (Python 3.12)

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

**3. MCP server** (terminal 1)

```bash
cd backend && source .venv/bin/activate
MCP_TRANSPORT=http python -m app.mcp_server        # serves http://localhost:8001/mcp
```

It connects to the database from step 1 by default. Set `DATABASE_URL` only if yours is elsewhere.

**4. Chat UI** (terminal 2)

```bash
cd backend && source .venv/bin/activate
set -a; source ../.env; set +a      # provider + key, dev secret and demo login (rm / rm-demo-password)
export OLLAMA_BASE_URL=http://localhost:11434   # only with Ollama: .env points at Docker's host.docker.internal
chainlit run chainlit_app.py -w     # http://localhost:8000, reloads on change
```

`MCP_SERVER_URL` defaults to `http://127.0.0.1:8001/mcp`, which is the server from step 3. The audit log goes to `backend/logs/audit.jsonl`.

## Replacing the dev logins

Do this before the app is reachable by anyone but you. It needs the backend Python environment (see [Local development](#local-development-without-docker)), or run the same commands in the container with `docker compose run --rm --no-deps chainlit <command>`.

```bash
cd backend
chainlit create-secret                     # put the value in CHAINLIT_AUTH_SECRET in .env
python -m app.guardrails hash-password     # prompts for a password (12+ chars), prints a hash
```

Then list your RMs in `.env` as `username=<hash>`, comma-separated, and restart with `docker compose up -d chainlit`:

```ini
RM_USERS=asha=pbkdf2_sha256:600000:...,ravi=pbkdf2_sha256:600000:...
```

The `SECURITY` warnings in `docker compose logs chainlit` disappear once both defaults are replaced. Changing the secret signs everyone out.

## Run tests

After installing the development dependencies using the local setup above:

```bash
cd backend && source .venv/bin/activate
pytest -q
```

Tests need no database, network or API key. See [test coverage and extension guidance](docs/development.md#testing) for details; live providers, PostgreSQL and browser behavior require separate verification.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `docker compose up` fails: *required variable CHAINLIT_AUTH_SECRET is missing* | Your `.env` predates the login feature, or has no secret. Copy the `CHAINLIT_AUTH_SECRET` and `RM_USERS` lines from `.env.example` into `.env`. |
| Login page always says the credentials are wrong | With the defaults, use `rm` / `rm-demo-password`. Otherwise `RM_USERS` is empty or malformed (the chainlit log says *RM_USERS is empty*), or the hash was copied incompletely. Each entry is `username=pbkdf2_sha256:...`, comma-separated. Restart with `docker compose up -d chainlit` after editing `.env`. |
| `SECURITY:` warnings in the chainlit log | You're using the dev defaults from `.env.example`. Fine locally. See [Replacing the dev logins](#replacing-the-dev-logins) before sharing. |
| Everyone was logged out after a restart | `CHAINLIT_AUTH_SECRET` changed. Keep it stable. |
| *"You are sending messages too quickly"* | The per-RM rate limit. Wait, or raise `CHAT_RATE_LIMIT_PER_MIN`. |
| *"Your message is too long"* | Over `CHAT_MAX_MESSAGE_CHARS`. Shorten it, or raise the limit. |
| Drafts keep getting rejected | The content rules caught something. The tool step for `save_whatsapp_drafts` shows the exact reasons. If a rule is too strict for your wording, adjust it in `app/guardrails.py`. |
| Chat shows *"OPENAI_API_KEY is not configured"* (or the Anthropic equivalent) | The key is missing in `.env`, or `LLM_PROVIDER` points at the wrong provider. Fix `.env`, then `docker compose up -d chainlit`. |
| Chat shows *"The CRM tool server is unreachable"* | The MCP server isn't running or `MCP_SERVER_URL` is wrong. Check `docker compose ps` and `docker compose logs mcp`. Outside Docker, start it with `MCP_TRANSPORT=http`. |
| Chat shows *"The AI model server is unreachable"* | With Ollama: it isn't running, or the container can't reach it. Check `curl http://localhost:11434`. See [Using Ollama](#using-ollama-free-local). |
| Chat shows *"The Ollama model is not installed"* | Run `ollama pull qwen3:8b`, or set `OLLAMA_MODEL` to a model you have. |
| *"rate limited"* | Your provider's rate limit. Retry shortly. |
| Changed `.env` but nothing changed | Compose reads `.env` when containers are created: `docker compose up -d chainlit`. |
| Wanted fresh seed data | `docker compose down -v`, then `docker compose up -d`. This deletes the database and audit log volumes. |
| *This month* column is empty for everyone, or tenure is missing | The database was seeded before transaction trends and life events were added, or so long ago that the 6-month window has moved past the seeded months. Reseed: `docker compose down -v && docker compose up -d`. |
| Port already in use (8000, 8001, 5432) | Stop the other process, or change the host port in `docker-compose.yml`. |
| `Found orphan containers` warning | A service was renamed or removed. Clean up with `docker compose up -d --remove-orphans`. |
| Chainlit log: *Ignoring pre-2.12.0 MCP config sections in /app/.chainlit/config.toml* | Harmless. Chainlit's own MCP feature is off (the app's tools come from the `mcp` service). Newer Chainlit versions flag the old `[features.mcp.*]` sections in `config.toml`, and deleting those sections silences it. |
| Chainlit fails with *"Timeout should be used inside a task"* | You're on Python 3.14. Use Python 3.12 (the Docker image already does). |
| `ModuleNotFoundError` when running tests or Chainlit locally | Activate the venv and run from `backend/`: `cd backend && source .venv/bin/activate`. |
| Weak or wrong tool use with Ollama | Try `OLLAMA_REASONING=true` or a larger `OLLAMA_MODEL`. 8B models are less reliable than hosted ones. |

## Documentation and diagrams

| Topic | Guide |
|---|---|
| Architecture, execution flow and state | [Architecture](docs/architecture.md) |
| Prompts and UI behavior | [Using the app](docs/usage.md) |
| Scoring, data and eligibility | [Business rules](docs/business-rules.md) |
| Consent, draft validation and audit logs | [Guardrails](docs/guardrails.md) |
| Tool design and usage | [MCP tools](docs/tools.md) |
| Project layout, tests and extension | [Development](docs/development.md) |
| Key design decisions, trade-offs and limitations | [Design decisions](docs/design-decisions.md) |
| Component architecture | [Architecture diagram](diagrams/architecture_diagram.md) |
| Agent execution and draft gates | [Process flow](diagrams/process_flow.md) |
| Database entities and relationships | [Database diagram](diagrams/database_diagram.md) |

Browse all guides in the [documentation index](docs/README.md).
