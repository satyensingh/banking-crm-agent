# Tools and the MCP server

[Setup and run](../README.md) · [Documentation index](README.md)

The eight CRM capabilities are **MCP tools** served by the FastMCP server, which the agent reaches over HTTP. Each tool does one job, so the LLM decomposes a request by choosing tools. Each has a typed input schema, a typed output, and a docstring the LLM reads to decide when to call it.

| MCP tool | What it does |
|---|---|
| `search_customers` | Filter by city, income, credit score, balance, occupation (paginated) |
| `get_customer_profile` | Minimised profile (no contact or consent fields) |
| `get_transaction_insights` | Last 6 months of transactions as trends and bands: income and spending trends, surplus band, recent life events, timing signals, outreach themes |
| `classify_high_value` | High-value segmentation |
| `score_conversion` | Explainable 0–100 score with a per-factor breakdown (including timing) and blockers |
| `match_products` | Preliminary suitability, optional `product_code` |
| `check_whatsapp_permission` | Eligibility, opt-in, do-not-contact, 30-day cooldown |
| `rank_prospects` | Eligible, (by default) contactable prospects, ranked, with suggested product, occupation, tenure, timing signals and outreach themes. Transactions for all candidates are fetched in one query |

The agent adds one local tool, `save_whatsapp_drafts`, because it enforces the consent gate against what other tools confirmed earlier in the same turn.

All tools are read-only (`readOnlyHint`), and queries run in `READ ONLY` transactions. Search and profile tools return a fixed allow-list of fields, so there is no phone, email or consent data.

**Errors** from MCP tools are JSON in the error message: `{"code": "NOT_FOUND" | "DATABASE_UNAVAILABLE" | "INVALID_INPUT" | "INTERNAL_ERROR", "message": "...", "retryable": bool}`. Unexpected exceptions are masked, and details go only to the server logs.
