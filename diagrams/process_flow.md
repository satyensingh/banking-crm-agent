# Process flow

[Setup and run](../README.md) · [Architecture guide](../docs/architecture.md) · [Architecture diagram](architecture_diagram.md)

## One chat turn

The model chooses tools and their order. This diagram shows the orchestration and enforcement boundaries, rather than a fixed sequence of tool calls.

```mermaid
flowchart TD
    RM["Authenticated RM submits a message"] --> INPUT{"Within message cap<br/>and rate limit?"}
    INPUT -->|No| BLOCK["Audit blocked message<br/>Show explanation"]
    INPUT -->|Yes| INIT["Load session conversation and selected shortlist<br/>Reset permission, drafts, trace and round count"]
    INIT --> WINDOW["Build model context<br/>Retain complete active turn<br/>Include historical selected shortlist"]
    WINDOW --> MODEL["Invoke model with tool schemas<br/>Increment model round count"]
    MODEL --> CALLS{"Tool calls requested?"}
    CALLS -->|No| RESULT["Build reply, prospect table and CSV<br/>Include accepted drafts"]
    CALLS -->|Yes| LIMIT{"Model round count below 8?"}
    LIMIT -->|No| STOP["Answer pending calls with TOOL_LIMIT<br/>Return limit explanation"]
    LIMIT -->|Yes| EACH["Process each requested tool call"]
    EACH --> KIND{"Tool type?"}
    KIND -->|CRM tool| MCP["Call typed MCP tool over HTTP<br/>Read database and apply rules"]
    MCP --> UPDATE["Record tool result or structured error<br/>Ranking replaces selected shortlist<br/>Record confirmed contact permission"]
    KIND -->|Save drafts| CONSENT{"Customer permission<br/>confirmed this turn?"}
    CONSENT -->|No| REJECT["Return rejection reasons<br/>Do not save rejected draft"]
    CONSENT -->|Yes| CONTENT{"Draft passes<br/>content checks?"}
    CONTENT -->|No| REJECT
    CONTENT -->|Yes| SAVE["Save accepted draft in turn state<br/>No customer message is sent"]
    KIND -->|Unknown tool| UNKNOWN["Return INVALID_INPUT"]
    UPDATE --> TRACE["Append tool result to conversation<br/>Record trace and show UI tool step"]
    REJECT --> TRACE
    SAVE --> TRACE
    UNKNOWN --> TRACE
    TRACE --> MORE{"More calls in this batch?"}
    MORE -->|Yes| EACH
    MORE -->|No| WINDOW
    STOP --> AUDIT["Audit completed turn and show response"]
    RESULT --> AUDIT
```

A rejected draft is returned to the model with reasons so it can rewrite within the remaining rounds. Errors from a tool are also returned to the model. Provider failures and unexpected turn failures are caught by Chainlit, audited as failed turns, and shown as error messages; they do not produce a successful-turn record.

## Main campaign and follow-up

```mermaid
sequenceDiagram
    actor RM as Relationship manager
    participant UI as Chainlit UI
    participant Agent as LangGraph agent
    participant Model as Configured LLM
    participant MCP as FastMCP tools
    participant DB as PostgreSQL
    RM->>UI: Find top 3 high-value prospects and draft WhatsApp messages
    UI->>Agent: Start turn, clear per-turn permission and drafts
    Agent->>Model: Request, history and tool schemas
    Model-->>Agent: rank_prospects(high_value_only=true, limit=3)
    Agent->>MCP: Call ranking tool over HTTP
    MCP->>DB: Read customer features, products and transactions
    DB-->>MCP: Synthetic CRM rows
    Note over MCP: Filter eligibility and contact permission<br/>Calculate timing, score and product fit
    MCP-->>Agent: Ranked prospects with permission and personalization data
    Note over Agent: Retain selected shortlist in session<br/>Record this turn's confirmed permission
    Agent->>Model: Ranking result
    Model-->>Agent: save_whatsapp_drafts with generated content
    Note over Agent: Check same-turn permission and content<br/>Save accepted drafts locally
    Agent->>Model: Saved IDs or rejection reasons
    Model-->>Agent: Final summary
    Agent-->>UI: Summary, shortlist and accepted drafts
    Note over UI: Audit turn, display table, CSV and drafts
    UI-->>RM: Drafts for review, not sent
    RM->>UI: Rewrite drafts for those same customers
    UI->>Agent: New turn, retain shortlist, clear permission and drafts
    Agent->>Model: Follow-up plus selected shortlist context
    Model-->>Agent: check_whatsapp_permission for selected IDs
    Agent->>MCP: Recheck permission for each customer
    MCP->>DB: Read current eligibility and contact data
    DB-->>MCP: Current CRM rows
    MCP-->>Agent: Permission results and blockers
    Agent->>Model: Fresh permission results
    Model-->>Agent: save_whatsapp_drafts for permitted customers
    Note over Agent: Validate and save, reject unconfirmed or blocked IDs
    Agent->>Model: Draft outcomes
    Model-->>Agent: Final summary
    Agent-->>UI: Revised drafts with retained shortlist names
    UI-->>RM: Review revised drafts
```

This is the efficient expected path, not a hardcoded workflow: the model can request more detail, retry rejected drafts, or answer a single-customer question using other tools. A ranking already contains timing, product fit and permission, so duplicate lookups are unnecessary for the initial campaign. Fresh permission checks are required before follow-up drafts, the retained shortlist alone never grants permission.
