# Architecture and execution flow

[Setup and run](../README.md) · [Documentation index](README.md)

See the [architecture diagram](../diagrams/architecture_diagram.md) for component boundaries and the [process flow](../diagrams/process_flow.md) for turn execution and draft validation.

## Execution flow (one chat turn)

1. The RM sends a message in Chainlit. Chainlit calls `GraphChatAgent.reply()` in-process.
2. The LangGraph loop (`agent → tools → agent …`, at most 8 rounds) asks the LLM what to do.
3. When the LLM requests a tool, the agent calls it on the **FastMCP server** over HTTP. The server runs the rule in `rules.py` against PostgreSQL in a read-only transaction.
4. Each tool call appears in the UI as a step. When the LLM stops calling tools, its answer is shown with a prospect table (plus CSV download) and any WhatsApp drafts.

## How the agent breaks down the main request

*"Find high-value customers likely to convert for a personal loan this month and generate personalized WhatsApp messages"* typically runs as:

| Step | Tool | What it decides |
|---|---|---|
| 1. Retrieve and rank | `rank_prospects(high_value_only=true)` | Loads customer features and the last 6 months of **transactions**, drops anyone with an eligibility blocker or no WhatsApp permission, scores the rest, and suggests a product. |
| 2. Why this month | (in the ranking) or `get_transaction_insights` | Recent life-event spends and income or spending trends become the score's **timing** points and each prospect's `timing_signals`. |
| 3. Product fit | (in the ranking) or `match_products` | The suitable personal-loan product, premium first. |
| 4. Personalise and draft | `save_whatsapp_drafts` (agent-local) | The LLM writes one draft per customer from their name, city, occupation, tenure, product and an `outreach_theme`. The consent gate and content rules run, and rejected drafts come back with reasons for a rewrite. |
| 5. Answer | – | A short summary. The UI adds the prospect table, the *This month* column and the drafts. |

The LLM chooses the order and the parameters. For a single customer (*"Why isn't customer 12 eligible?"*) it calls `score_conversion` or `get_transaction_insights` directly instead.

**The LLM never computes a number.** Every score, eligibility decision and consent check comes from `rules.py`. The LLM only chooses tools and writes prose.

**Follow-up context:** the latest ranked shortlist is retained per session, so "these customers" refers to the same IDs. Historical shortlist data does not carry consent into the next turn: permission must be rechecked before follow-up drafts. History is trimmed only at complete turn boundaries; the active user request and its tool exchange are always kept.

**Consent guard:** the agent-local `save_whatsapp_drafts` tool only accepts a draft for a customer whose WhatsApp permission a tool confirmed *in the same turn*. Anything else is rejected.
