# Banking CRM Agent

An AI assistant for banking **relationship managers (RMs)**. The RM asks for personal-loan prospects in plain language; an LLM agent calls deterministic, read-only CRM tools against a PostgreSQL database; the chat UI shows ranked prospects, the tools that ran, and WhatsApp **drafts** for review.

> **Nothing is ever sent to customers.** Drafts are for RM review only.
> Scores are heuristics, **not** conversion probabilities. Product matches are preliminary suitability, **not** credit decisions or offers. All customer data is synthetic.

**Stack:** Chainlit (UI) · LangGraph (agent) · OpenAI / Anthropic / Ollama (LLM) · FastMCP (tool server) · PostgreSQL (data)

## Contents

- [How it works](#how-it-works)
- [Prerequisites](#prerequisites)
- [Quick start (Docker)](#quick-start-docker)
- [Choosing an LLM provider](#choosing-an-llm-provider)
- [Using the app](#using-the-app)
- [Configuration reference](#configuration-reference)
- [Local development (without Docker)](#local-development-without-docker)
- [Project structure](#project-structure)
- [Data and business rules](#data-and-business-rules)
- [Guardrails](#guardrails)
- [Tools and the MCP server](#tools-and-the-mcp-server)
- [Testing](#testing)
- [Extending the app](#extending-the-app)
- [Troubleshooting](#troubleshooting)
- [Design notes and limitations](#design-notes-and-limitations)

## How it works

```mermaid
flowchart LR
    RM([Relationship manager]) --> UI["Chainlit UI<br/>chainlit_app.py :8000"]
    UI -->|in-process call| AG["LangGraph agent<br/>app/graph_agent.py"]
    AG -->|chat + tool calls| LLM{{"LLM<br/>OpenAI | Anthropic | Ollama"}}
    AG -->|"MCP client (streamable HTTP)"| MCP["FastMCP server<br/>app/mcp_server.py :8001"]
    MCP --> SVC["CRMTools + rules.py<br/>deterministic business rules"]
    SVC -->|read-only SQL| DB[("PostgreSQL :5432<br/>schema banking_crm_demo")]
```

**One chat turn:**

1. The RM sends a message in Chainlit. Chainlit calls `GraphChatAgent.reply()` in-process.
2. The LangGraph loop (`agent → tools → agent …`, at most 8 rounds) asks the LLM what to do.
3. When the LLM requests a tool, the agent calls it on the **FastMCP server** over HTTP. The server runs the rule in `rules.py` against PostgreSQL in a read-only transaction.
4. Each tool call appears in the UI as a step. When the LLM stops calling tools, its answer is shown with a prospect table (plus CSV download) and any WhatsApp drafts.

**The LLM never computes a number.** Every score, eligibility decision and consent check comes from `rules.py`. The LLM only chooses tools and writes prose.

**Consent guard:** the agent-local `save_whatsapp_drafts` tool only accepts a draft for a customer whose WhatsApp permission a tool confirmed *in the same turn*. Anything else is rejected.

## Prerequisites

| Need | Why |
|---|---|
| **Docker** with Compose v2 | Runs the whole stack ([install](https://docs.docker.com/get-docker/)) |
| **One LLM option** | An [OpenAI](https://platform.openai.com/api-keys) key, an [Anthropic](https://console.anthropic.com/) key, **or** [Ollama](https://ollama.com) (free, local) |
| Python **3.12** *(only for [local development](#local-development-without-docker))* | The Docker image uses 3.12. Avoid 3.14: Chainlit's websocket layer fails on it |
| ~6 GB free disk *(only for Ollama)* | The `qwen3:8b` model is about 5 GB |

## Quick start (Docker)

```bash
git clone <this-repo-url>
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
docker compose down -v            # stop AND delete the database volume (re-seeds on next start)
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

## Using the app

### What you can ask

Click a starter on the welcome screen, or type your own request:

| Try | What happens |
|---|---|
| *Find the top 5 high-value customers likely to convert for a personal loan this month.* | Ranks prospects and shows a table |
| *Find the top 3 personal loan prospects and generate personalized WhatsApp messages.* | Ranks, checks consent, then writes drafts |
| *Show premium personal loan prospects with the highest conversion scores.* | Filters to the premium product |
| *Explain why customers could be excluded or ineligible for a personal loan.* | Explains the eligibility blockers |
| *Why isn't customer 12 eligible?* · *Score customer 42.* · *Which products suit customer 7?* | Single-customer questions |
| *Show prospects in Pune with income above 80,000.* | Filtered search (city, income, credit score, balance, occupation) |

### What you see

- **Tool steps:** each tool call shows as a collapsible step with its input and output, so you can see exactly where an answer came from.
- **Prospect table:** score, income, credit score, balance, suggested product, the reason, and whether WhatsApp is permitted. A **CSV file** of the table is attached.
- **Draft button:** *Draft WhatsApp messages for these prospects* asks the agent to write drafts for the prospects shown.
- **WhatsApp drafts:** shown in copyable blocks, labelled **not sent**. Only customers with confirmed WhatsApp permission get a draft.
- **Errors** appear as a message in the chat, for example a missing API key, a rate limit, or an unreachable model or tool server.

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
| `DATABASE_URL` | mcp | built by Compose | Set only when running outside Docker |
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
export DATABASE_URL='postgresql://banking_user:banking_dev_password@localhost:5432/banking_crm'
MCP_TRANSPORT=http python -m app.mcp_server        # serves http://localhost:8001/mcp
```

**4. Chat UI** (terminal 2)

```bash
cd backend && source .venv/bin/activate
set -a; source ../.env; set +a      # provider + key, dev secret and demo login (rm / rm-demo-password)
export OLLAMA_BASE_URL=http://localhost:11434   # only with Ollama: .env points at Docker's host.docker.internal
chainlit run chainlit_app.py -w     # http://localhost:8000, reloads on change
```

`MCP_SERVER_URL` defaults to `http://127.0.0.1:8001/mcp`, which is the server from step 3. The audit log goes to `backend/logs/audit.jsonl`.

## Project structure

```text
.
├── docker-compose.yml            # postgres, mcp, chainlit
├── .env.example                  # every setting, documented
├── .mcp.json                     # MCP servers for Claude Code (http + stdio)
├── scripts/
│   └── banking_crm_seed_database.sql   # schema + 150 synthetic customers, loaded on first DB start
├── diagrams/database_diagram.md  # ER diagram
└── backend/
    ├── chainlit_app.py           # Chainlit UI: starters, live tool steps, table + CSV, drafts
    ├── chainlit.md               # welcome screen text
    ├── .chainlit/config.toml     # Chainlit settings (app name, tool-step display)
    ├── Dockerfile                # one image for both the mcp and chainlit services
    ├── requirements.txt          # runtime deps    ·  requirements-dev.txt adds test deps
    ├── app/
    │   ├── graph_agent.py        # LangGraph agent, LLM providers, MCP client, consent guard
    │   ├── guardrails.py         # draft content rules, RM password auth, rate limit, message cap
    │   ├── audit.py              # append-only JSON Lines audit log
    │   ├── mcp_server.py         # FastMCP server: 7 read-only tools, validation, structured errors
    │   ├── service.py            # CRMTools: repository + rules
    │   ├── rules.py              # pure business rules (classification, scoring, products, consent)
    │   ├── repository.py         # parameterised, read-only SQL
    │   ├── models.py             # Pydantic request/response models
    │   └── deps.py               # wiring for the repository and tools
    └── tests/                    # pytest suites (no DB, network or API key needed)
```

## Data and business rules

The database is the `banking_crm_demo` schema: `customers`, `accounts`, `transactions`, `products`, `customer_products`, `outreach_history`, `loan_applications` (see [diagrams/database_diagram.md](diagrams/database_diagram.md)). The seed contains **150 fictional customers** with deliberate edge cases: no WhatsApp opt-in, do-not-contact, weak KYC, low credit score, high risk, open applications, existing personal loans and recent declines.

**Products:** `PL_STANDARD` (personal loan), `PL_PREMIUM` (personal loan, needs income ≥ ₹80k and credit ≥ 750), `CC_REWARDS` (credit card), `AUTO_LOAN`.

**High-value** (an illustrative segmentation rule): monthly income ≥ ₹80,000 **and** balance ≥ ₹100,000.

**Propensity score (0–100, a heuristic)** is the sum of these parts:

| Part | Max | Scale |
|---|---|---|
| Income | 25 | ≥120k: 25 · ≥80k: 20 · ≥50k: 12 · else 5 |
| Credit score | 25 | ≥800: 25 · ≥750: 20 · ≥700: 12 · else 5 |
| Balance | 20 | ≥200k: 20 · ≥100k: 15 · ≥50k: 10 · else 3 |
| Existing EMI / income | 15 | <15%: 15 · <30%: 10 · else 3 |
| Past personal-loan interest | 10 | yes: 10 |
| No personal-loan contact in 30 days | 5 | yes: 5 |

**Eligibility blockers** (any one makes a customer not eligible): KYC not verified · high risk band · credit score < 680 · income < ₹30,000 · account not active · fewer than 5 months of income history · EMI/income > 40% · active personal loan · pending personal-loan application · personal-loan decline in the last 90 days.

**WhatsApp permission** is stricter than eligibility. A customer is contactable only if they have **no eligibility blockers**, **and** have opted in to WhatsApp, **and** are not on the do-not-contact list, **and** have had no personal-loan contact in the last 30 days. Any failure is returned as a named blocker.

These rules mirror the SQL view in the seed script. `rules.py` is where to change them.

## Guardrails

Every guardrail is deterministic code, not an LLM judgement, so it behaves the same every time and is unit-tested.

| Guardrail | Where | What it does |
|---|---|---|
| **RM login** | `chainlit_app.py`, `app/guardrails.py` | Password sign-in is required for the chat. Passwords are stored only as salted PBKDF2-SHA256 hashes (600k iterations) in `RM_USERS`. Unknown usernames take as long to reject as wrong passwords, so timing doesn't reveal valid usernames. Unauthenticated websocket connections are refused. |
| **Consent gate on drafts** | `app/graph_agent.py` | A draft is accepted only for a customer whose WhatsApp permission a tool confirmed in the same turn. |
| **Draft content rules** | `app/guardrails.py` (`check_draft`) | A draft is rejected if it promises or implies approval ("guaranteed", "pre-approved", "approved", "assured", "instant approval", "risk-free"), states a rate, ₹ amount, lakh/crore figure or EMI, contains a link, email or phone number, or is over 600 characters. The model gets the reasons back and rewrites. |
| **Message cap** | `chainlit_app.py` | Messages over `CHAT_MAX_MESSAGE_CHARS` (default 4000) are refused before reaching the LLM. |
| **Rate limit** | `chainlit_app.py`, `app/guardrails.py` | Each RM may send `CHAT_RATE_LIMIT_PER_MIN` messages per minute (default 10, sliding window), to limit runaway API cost. |
| **Audit log** | `app/audit.py` | Every sign-in (success and failure), blocked message, failed turn and completed turn is appended as one JSON line: time, RM, session, prompt, reply, tools with arguments, prospect IDs and saved drafts. Passwords are never logged. |
| **Read-only data access** | `app/mcp_server.py`, `app/repository.py` | Tools are marked read-only and run in `READ ONLY` transactions. Search and profile tools return a fixed allow-list of fields. |
| **Bounded runs** | `app/graph_agent.py` | At most 8 tool rounds per turn, at most 100 rows per tool call, and model output capped at 16k tokens. |

### Replacing the dev logins

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

**Reading the audit log:**

```bash
docker compose exec chainlit tail -n 20 /app/logs/audit.jsonl
docker compose exec chainlit sh -c "grep '\"event\": \"login\"' /app/logs/audit.jsonl"   # sign-ins
```

The audit log contains customer names and draft text, so it is created owner-read/write only (`0600`) and is git-ignored. It lives in the `audit_logs` Docker volume, and `docker compose down -v` deletes it. Rotate and retain it according to your bank's policy. There is no rotation built in.

**Changing the rules:** edit `_DRAFT_RULES` or `DRAFT_MAX_CHARS` in `app/guardrails.py` and add a case to `tests/test_guardrails.py`. Keep the matching instructions in `SYSTEM_PROMPT` in `app/graph_agent.py` in step, so the model usually passes first time.

**Not covered:** these rules catch known wording patterns, not every non-compliant phrasing. An RM still reviews every draft. There's no check that numbers in the final answer match tool outputs, no prompt-injection classifier, and no auth on the MCP endpoint (it's bound to `127.0.0.1` on the host, but other containers on the Docker network can reach it).

## Tools and the MCP server

The seven CRM capabilities are **MCP tools** served by the FastMCP server. The agent reaches them over HTTP, and any other MCP client can use them too.

| MCP tool | What it does |
|---|---|
| `search_customers` | Filter by city, income, credit score, balance, occupation (paginated) |
| `get_customer_profile` | Minimised profile (no contact or consent fields) |
| `classify_high_value` | High-value segmentation |
| `score_conversion` | Explainable 0–100 score with blockers |
| `match_products` | Preliminary suitability, optional `product_code` |
| `check_whatsapp_permission` | Eligibility, opt-in, do-not-contact, 30-day cooldown |
| `rank_prospects` | Eligible, (by default) contactable prospects, ranked |

All tools are read-only (`readOnlyHint`), and queries run in `READ ONLY` transactions. Search and profile tools return a fixed allow-list of fields, so there is no phone, email or consent data.

**Errors** from MCP tools are JSON in the error message: `{"code": "NOT_FOUND" | "DATABASE_UNAVAILABLE" | "INVALID_INPUT" | "INTERNAL_ERROR", "message": "...", "retryable": bool}`. Unexpected exceptions are masked, and details go only to the server logs.

### Use the MCP server from other clients

The MCP server is a standalone, standard MCP endpoint, so you can use it from Claude Desktop, Claude Code or any MCP client:

```bash
cd backend
python -m app.mcp_server                       # stdio (e.g. Claude Desktop)
MCP_TRANSPORT=http python -m app.mcp_server    # http://localhost:8001/mcp
claude mcp add --transport http banking-crm http://localhost:8001/mcp    # Claude Code
```

## Testing

```bash
cd backend && source .venv/bin/activate
pytest -q
```

| Suite | Covers |
|---|---|
| `tests/test_rules.py` | Business rules and eligibility blockers |
| `tests/fakes.py` | Shared in-memory repository used by the other suites (not a test file) |
| `tests/test_mcp_server.py` | MCP protocol through an in-memory client: schemas, validation, structured errors, masking |
| `tests/test_graph_agent.py` | LangGraph agent with a scripted fake model and the real MCP server: tool flow, consent guard, memory, round limit, providers, error mapping |
| `tests/test_guardrails.py` | Draft content rules, password hashing and login, rate limiter, audit log |
| `tests/test_chainlit_app.py` | Prospect table shaping and the login callback (including its audit records) |

The tests use a fake repository and a fake chat model, so they need **no database, network or API key**. They do **not** cover live PostgreSQL, live LLM calls (OpenAI, Anthropic, Ollama), or the Chainlit UI itself, so click through the app after changes to those.

## Extending the app

**Add a tool.** The agent discovers tools from the MCP server, so a new tool needs no agent change:

1. Put the rule in `app/rules.py` (pure function) and any SQL in `app/repository.py`.
2. Expose it on `CRMTools` in `app/service.py`.
3. Register it in `app/mcp_server.py` with the `@tool` decorator inside `build_server()`. Give it a clear docstring, because the LLM reads it to decide when to use the tool.
4. Add tests in `tests/test_rules.py` and `tests/test_mcp_server.py`.
5. Restart the `mcp` service: `docker compose up -d --build mcp`.

If the tool's result should appear in the UI table or feed the consent check, also handle it in `run_tools` in `app/graph_agent.py`.

**Change the assistant's behaviour:** edit `SYSTEM_PROMPT` in `app/graph_agent.py`.

**Add an LLM provider:** add a branch to `make_chat_model()` in `app/graph_agent.py` that returns a LangChain chat model with tool-calling support, and add its package to `requirements.txt`.

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
| Wanted fresh seed data | `docker compose down -v`, then `docker compose up -d`. This deletes the database volume. |
| Port already in use (8000, 8001, 5432) | Stop the other process, or change the host port in `docker-compose.yml`. |
| `Found orphan containers` warning | A service was renamed or removed. Clean up with `docker compose up -d --remove-orphans`. |
| Chainlit log: *Ignoring pre-2.12.0 MCP config sections in /app/.chainlit/config.toml* | Harmless. Chainlit's own MCP feature is off (the app's tools come from the `mcp` service). Newer Chainlit versions flag the old `[features.mcp.*]` sections in `config.toml`, and deleting those sections silences it. |
| Chainlit fails with *"Timeout should be used inside a task"* | You're on Python 3.14. Use Python 3.12 (the Docker image already does). |
| `ModuleNotFoundError` when running tests or Chainlit locally | Activate the venv and run from `backend/`: `cd backend && source .venv/bin/activate`. |
| Claude Code reports `banking-crm-tools-stdio` failed: *"Executable not found: python"* | That `.mcp.json` entry runs `python`, which many systems only provide as `python3`. Edit its `command`, or use the `banking-crm-tools` HTTP entry. |
| Weak or wrong tool use with Ollama | Try `OLLAMA_REASONING=true` or a larger `OLLAMA_MODEL`. 8B models are less reliable than hosted ones. |

## Design notes and limitations

- **Deterministic core:** every number the agent reports comes from `rules.py`. The LLM only selects tools and writes prose.
- **Human in the loop:** WhatsApp drafts are recorded for review and never sent. There is no sending integration. See [Guardrails](#guardrails).
- **Authentication covers the chat only.** The MCP HTTP endpoint has no authentication. The MCP and database ports are bound to `127.0.0.1` on the host, so only the chat (`:8000`) is reachable from other machines. Use HTTPS (a reverse proxy) in front of the chat before exposing it beyond your machine, because the login form is plain HTTP.
- **The rate limit is in-process.** It resets on restart and isn't shared across multiple Chainlit workers. Login sessions are signed tokens, so they survive a restart as long as `CHAINLIT_AUTH_SECRET` stays the same.
- **Chat memory is in-process:** it uses LangGraph's in-memory checkpointer keyed by the Chainlit session. It resets on restart, has no size cap, and doesn't work across multiple workers. Switch to LangGraph's Postgres checkpointer for durability.
- **Chainlit's own history sidebar** is not enabled (it needs a data layer). It is separate from the CRM database.
- **Ranking scalability:** `rank_prospects` scans all matching rows in Python (capped at 10,000). Move scoring into SQL before using large datasets.
- **Dev defaults:** the Postgres password default is for local use only.
- **Not covered by automated tests:** live LLM providers, live PostgreSQL and the Chainlit UI (see [Testing](#testing)).
