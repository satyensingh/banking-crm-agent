# Design decisions and limitations

[Setup and run](../README.md) · [Documentation index](README.md)

## Key design decisions

| Decision | Why | Alternative considered |
|---|---|---|
| **Deterministic tools, LLM for orchestration and prose** | Every score, eligibility decision and consent check is reproducible, unit-tested and explainable to compliance. The LLM only picks tools and writes text, so it can't invent a number. | Let the LLM reason over raw data: more flexible, but unauditable, and prone to invented figures. |
| **Heuristic score, not ML** | No labelled conversion outcomes exist in the data, and a points table is explainable line by line. | A trained propensity model: better ranking once outcome data exists, at the cost of explainability. The score is one function in `rules.py`, so it can be swapped. |
| **"This month" from transaction signals** | Life-event spends and income or spending trends are why *now* is a good time to call, not just whether the customer qualifies. | Seasonality or campaign calendars: not in the data. |
| **Tools behind an MCP server** | Tools are discovered at runtime, so adding one needs no agent change. Typed schemas reject bad input before business logic runs, and the tool layer is a separate process from the agent. | In-process LangChain tools: simpler, but couples tools to the agent and gives no schema boundary. |
| **LangGraph state machine** | An explicit `agent → tools → agent` loop with a round limit, per-session memory (a checkpointer) and per-turn state (consent set, drafts) that resets every turn. | A plain prompt loop or a prebuilt ReAct agent: less control over state and limits. |
| **Bands, never exact figures** | RMs and the LLM see income, balance and credit score only as bands, and search minimums snap to band edges. That limits data exposure without hiding why a rule fired. | Raw figures: more precise, but needless exposure of sensitive data. |
| **Consent gate and content rules in code** | A draft is only accepted for a customer whose WhatsApp permission a tool confirmed this turn, and it must pass `check_draft`. Rejections go back to the model with reasons, so it rewrites. | Trusting the prompt: models drift, and compliance can't rely on that. |
| **Personalise without revealing monitoring** | Drafts use name, city, occupation, tenure, product and a neutral theme ("if you have education plans coming up"). A message that says "we noticed your tuition payment" feels like surveillance, so the content rules reject it. Health is never used. | Quoting the transaction: more specific, but intrusive and a compliance risk. |
| **Security for a banking context** | RM login (PBKDF2 hashes), per-RM rate limit, message cap and an audit log of every turn. An assistant over customer data must know who asked what. | No auth: fine for a demo, but not credible for a bank. |
| **Pluggable LLM provider** | OpenAI provides the hosted model option. Ollama runs locally for free, and keeps customer data on the machine. One `make_chat_model()` switch. | A single provider: less code, but locks in cost and data residency. |
| **Human in the loop** | Drafts are recorded for RM review and never sent. There is no sending integration. | Auto-send: not acceptable for regulated outreach. |

## Trade-offs and limitations

- **Scores are heuristics, not probabilities.** The weights and thresholds are illustrative policy, not fitted to outcomes. Treat 80/100 as a ranking, not an 80% chance.
- **Transaction signals are coarse.** They use category totals and fixed thresholds (±5% income, ±15% spend, one-offs in the last 2 months). Categories come from the seed. Real data needs merchant categorisation, and the thresholds need tuning against conversion outcomes.
- **Rule-based content checks** catch known wording patterns, not every non-compliant phrasing. An RM still reviews every draft. There's no check that numbers in the final answer match tool outputs, and no prompt-injection classifier.
- **Authentication covers the chat only.** The MCP HTTP endpoint has no authentication. The MCP and database ports are bound to `127.0.0.1` on the host, so only the chat (`:8000`) is reachable from other machines, but other containers on the Docker network can reach the MCP server. Put HTTPS (a reverse proxy) in front of the chat before exposing it, because the login form is plain HTTP.
- **State is in-process.** Chat memory (LangGraph's in-memory checkpointer) and the rate limit reset on restart and aren't shared across Chainlit workers. Switch to LangGraph's Postgres checkpointer for durability. Login sessions are signed tokens, so they survive a restart while `CHAINLIT_AUTH_SECRET` stays the same.
- **Chainlit's own history sidebar** is not enabled (it needs a data layer). It is separate from the CRM database.
- **Ranking scalability:** `rank_prospects` scans all matching rows in Python (capped at 10,000), then fetches transactions for the candidates in one query. Move scoring into SQL before using large datasets.
- **Two copies of the base scoring rules.** The seed's `personal_loan_prospects` view keeps the dataset's original ranking for SQL exploration. The app's score lives in `rules.py`, with rescaled weights and timing. Only `rules.py` drives the app.
- **Dev defaults:** the Postgres password and demo login are for local use only.
- **Not covered by automated tests:** live LLM providers, live PostgreSQL and the Chainlit UI (see [Testing](development.md#testing)).
