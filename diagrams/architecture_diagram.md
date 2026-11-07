# Architecture diagram

[Setup and run](../README.md) · [Architecture guide](../docs/architecture.md) · [Process flow](process_flow.md) · [Database diagram](database_diagram.md)

```mermaid
flowchart TB
    RM["Relationship manager"]
    subgraph CHAT["Chainlit service - port 8000"]
        UI["Chat UI<br/>Login, message cap, rate limit<br/>Tool steps, table, CSV and drafts"]
        AG["LangGraph agent<br/>Model-driven tool loop<br/>Maximum 8 model rounds"]
        MCPCLIENT["MCP client<br/>Runtime tool discovery"]
        DRAFT["Agent-local save_whatsapp_drafts<br/>Same-turn permission gate<br/>Deterministic content validation"]
        STATE["In-memory session state<br/>Conversation and selected shortlist<br/>Per-turn permission, drafts and trace"]
        AUDIT["JSON Lines audit log<br/>Login, blocked messages, turns and failures"]
        UI -->|"reply(session_id, message)"| AG
        AG --> MCPCLIENT
        AG --> DRAFT
        AG <--> STATE
        UI --> AUDIT
        AG -.->|"Tool results shown as steps"| UI
    end
    LLM["Configured model provider<br/>OpenAI or local Ollama<br/>Tool selection and prose"]
    subgraph TOOLS["FastMCP service - port 8001"]
        MCP["Eight typed, read-only MCP tools<br/>Input validation and structured errors"]
        SVC["CRMTools service<br/>Compose ranking and customer lookups"]
        RULES["Pure business rules<br/>High-value, timing, score<br/>Eligibility, product fit and consent"]
        REPO["PostgresRepository<br/>Parameterized SQL<br/>Read-only transactions"]
        MCP --> SVC
        SVC --> RULES
        SVC --> REPO
    end
    DB[("PostgreSQL - port 5432<br/>banking_crm_demo schema<br/>Synthetic customers and transactions")]
    RM --> UI
    AG <-->|"Chat messages and tool calls/results"| LLM
    MCPCLIENT <-->|"Streamable HTTP /mcp"| MCP
    REPO <-->|"Queries and rows"| DB
    UI -->|"Drafts for human review; nothing sent"| RM
```

## Boundaries and responsibilities

- **Model versus rules:** the model chooses tools and writes prose; deterministic code calculates scores, eligibility and permission. Customer financial figures are returned to the model and UI as bands. There is no agent-generated SQL.
- **Tool server versus agent-local draft tool:** database capabilities live behind MCP. Draft acceptance lives in the agent because it depends on permission confirmed within the current turn. Drafts live in graph state and are included in the audit record; no message-sending integration exists.
- **Session versus turn:** the in-memory checkpointer uses `session_id` as the thread key. Conversation messages and the selected shortlist persist across turns; permission, drafts, trace and round count reset on each request. State does not survive a process restart.
- **Network exposure:** Compose binds the database and MCP host ports to `127.0.0.1`; the chat port is published on all host interfaces. The chat requires login, but the MCP endpoint has no authentication. Other containers on the network can reach MCP.
- **Storage:** PostgreSQL uses the `postgres_data` volume; the audit file uses `audit_logs`. Conversation state is in memory rather than either volume.

See [design decisions and limitations](../docs/design-decisions.md) for alternatives and production gaps.
