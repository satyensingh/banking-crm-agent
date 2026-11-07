# Development and extension

[Setup and run](../README.md) · [Documentation index](README.md)

Commands in this guide run from the repository root unless a step changes directory. Python module paths such as `app/rules.py` are relative to `backend/`.

## Project structure

```text
.
├── docker-compose.yml            # postgres, mcp, chainlit
├── .env.example                  # every setting, documented
├── scripts/
│   └── banking_crm_seed_database.sql   # schema + 150 synthetic customers, loaded on first DB start
├── docs/                        # architecture, usage, rules, tools, development and design
├── diagrams/                    # architecture, process flow and database diagrams
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
    │   ├── mcp_server.py         # FastMCP server: 8 read-only tools, validation, structured errors
    │   ├── service.py            # CRMTools: repository + rules
    │   ├── rules.py              # pure business rules (classification, transaction insights, scoring, products, consent)
    │   ├── repository.py         # parameterised, read-only SQL
    │   ├── bands.py              # income/balance/credit/ratio bands: no exact figures leave the service
    │   ├── models.py             # Pydantic request/response models
    │   └── deps.py               # wiring for the repository and tools
    └── tests/                    # pytest suites (no DB, network or API key needed)
```

## Testing

```bash
cd backend && source .venv/bin/activate
pytest -q
```

| Suite | Covers |
|---|---|
| `tests/test_rules.py` | Business rules, eligibility blockers, transaction insights (trends, life events, caution signals, medical exclusion, time window) |
| `tests/fakes.py` | Shared in-memory repository used by the other suites (not a test file) |
| `tests/test_mcp_server.py` | MCP protocol through an in-memory client: schemas, validation, structured errors, masking, one transaction query per ranking |
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
