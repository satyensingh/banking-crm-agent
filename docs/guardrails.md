# Guardrails and audit logging

[Setup and run](../README.md) · [Documentation index](README.md)

Every guardrail is deterministic code, not an LLM judgement, so it behaves the same every time and is unit-tested.

| Guardrail | Where | What it does |
|---|---|---|
| **RM login** | `chainlit_app.py`, `app/guardrails.py` | Password sign-in is required for the chat. Passwords are stored only as salted PBKDF2-SHA256 hashes (600k iterations) in `RM_USERS`. Unknown usernames take as long to reject as wrong passwords, so timing doesn't reveal valid usernames. Unauthenticated websocket connections are refused. |
| **Consent gate on drafts** | `app/graph_agent.py` | A draft is accepted only for a customer whose WhatsApp permission a tool confirmed in the same turn. |
| **Draft content rules** | `app/guardrails.py` (`check_draft`) | A draft is rejected if it promises or implies approval ("guaranteed", "pre-approved", "approved", "assured", "instant approval", "risk-free"), states a rate, ₹ amount, lakh/crore figure or EMI, **reveals that the bank looked at the customer's transactions** ("we noticed", "your recent spending", "spent on"), **mentions health or medical matters**, contains a link, email or phone number, or is over 600 characters. The model gets the reasons back and rewrites. |
| **Message cap** | `chainlit_app.py` | Messages over `CHAT_MAX_MESSAGE_CHARS` (default 4000) are refused before reaching the LLM. |
| **Rate limit** | `chainlit_app.py`, `app/guardrails.py` | Each RM may send `CHAT_RATE_LIMIT_PER_MIN` messages per minute (default 10, sliding window), to limit runaway API cost. |
| **Audit log** | `app/audit.py` | Every sign-in (success and failure), blocked message, failed turn and completed turn is appended as one JSON line: time, RM, session, prompt, reply, tools with arguments, prospect IDs and saved drafts. Passwords are never logged. |
| **Read-only data access** | `app/mcp_server.py`, `app/repository.py` | Tools are marked read-only and run in `READ ONLY` transactions. Search and profile tools return a fixed allow-list of fields. |
| **Bounded runs** | `app/graph_agent.py` | At most 8 tool rounds per turn, at most 100 rows per tool call, and model output capped at 16k tokens. |

See [Replacing the dev logins](../README.md#replacing-the-dev-logins) for credential setup.

**Reading the audit log:**

```bash
docker compose exec chainlit tail -n 20 /app/logs/audit.jsonl
docker compose exec chainlit sh -c "grep '\"event\": \"login\"' /app/logs/audit.jsonl"   # sign-ins
```

The audit log contains customer names and draft text, so it is created owner-read/write only (`0600`) and is git-ignored. It lives in the `audit_logs` Docker volume, and `docker compose down -v` deletes it. Rotate and retain it according to your bank's policy. There is no rotation built in.

**Changing the rules:** edit `_DRAFT_RULES` or `DRAFT_MAX_CHARS` in `app/guardrails.py` and add a case to `tests/test_guardrails.py`. Keep the matching instructions in `SYSTEM_PROMPT` in `app/graph_agent.py` in step, so the model usually passes first time.

**Not covered:** these rules catch known wording patterns, not every non-compliant phrasing. An RM still reviews every draft. There's no check that numbers in the final answer match tool outputs, no prompt-injection classifier, and no auth on the MCP endpoint (it's bound to `127.0.0.1` on the host, but other containers on the Docker network can reach it).
