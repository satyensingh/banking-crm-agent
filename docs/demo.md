# Demo recording guide

Use the existing Docker stack at http://localhost:8000. Sign in with the configured RM login (the local demo defaults are `rm` / `rm-demo-password`). Start a new chat before the first scenario, then use that same chat for all three prompts.

## 1. Find prospects and generate outreach

> Find the top 3 high-value customers likely to convert for a personal loan this month and generate personalized WhatsApp messages.

Show the `rank_prospects` step, three rows, the **This month** column and three personalized drafts marked **not sent**. Explain that the 0–100 scores are deterministic heuristics, not conversion probabilities, and product fit is preliminary suitability.

## 2. Follow up using the same shortlist

> For those same three customers, rewrite the WhatsApp drafts in a warmer tone and explain why this month is relevant. Keep the same shortlist.

Show that the IDs and names stay the same without retyping them. Expand the fresh permission checks and the draft-saving result. Previous-turn consent is never reused as authorization. Contrast Aditi's timing signals with the other prospects' signals using the tool data, without disclosing monitoring in the customer-facing drafts.

## 3. Explain blocked outreach

> Check personal-loan eligibility and WhatsApp permission for customer 9 and customer 31. Generate a WhatsApp draft only if permission is confirmed; explain any exclusions.

Expected: customer 9 lacks WhatsApp opt-in; customer 31 is on do-not-contact. Neither gets a draft. Eligibility and contact permission are separate checks.

## Architecture and trade-offs (about 2 minutes)

Use the README architecture diagram. Chainlit calls the LangGraph loop; the LLM chooses tools and writes text; FastMCP serves typed tools; PostgreSQL supplies synthetic customer and transaction data. Business rules calculate scores, eligibility and permission. Content rules check drafts, and the RM reviews everything.

Explain the main trade-offs: explainable heuristics versus a trained model without labelled outcomes; data bands versus precise amounts; in-memory conversation state versus durable storage; and read-only draft creation versus automatic outreach. The history window keeps whole turns, always retaining the active request; a separate session shortlist supports references such as "those customers".

## Before recording

- Check `docker compose ps`: database healthy, MCP and Chainlit running.
- Use the refreshed November 2026 demo dataset. Do not reset Docker volumes: that would also erase audit logs. Re-seeding the SQL script replaces the CRM schema; back up first if it contains work you want to keep.
- Keep API keys and `.env` off-screen.
- Show meaningful tool steps, the shortlist and drafts, and both blocked-contact outcomes.
- Allow time for live model responses. Keep the finished video within the assignment's 5–10 minute requirement.

## Verification on 7 November 2026

Verified against the running OpenAI `gpt-5` → HTTP MCP → PostgreSQL stack, using one session for all three scenarios. These are observed runs, not canned application responses.

| Scenario | Observed result | Agent time | Tool calls |
|---|---|---:|---:|
| Campaign | Aditi Gupta (77, score 100), Rohan Nair (44, score 84), Vivek Sharma (25, score 83); three accepted drafts; timing signals and tenure present | 22.8 s | 2 |
| Follow-up | Same three IDs and names; three revised drafts; permission rechecked individually before saving | 19.2 s | 4 |
| Blocked contact | Customer 9: missing opt-in; customer 31: do-not-contact; zero drafts | 22.1 s | 6 |

A second rehearsal through the Chainlit browser UI also passed all three scenarios: login, rendered shortlist and CSV attachment, personalized drafts, follow-up consent checks with the same names and IDs, and blocked-contact explanations with no new drafts.

All six generated drafts passed the deterministic content validator. Automated suite: **155 passed**, including regressions for a tool-heavy turn exceeding the old 40-message history budget, follow-up shortlist retention, session isolation, empty-shortlist replacement, and consent reset between turns. Live wording and latency vary by model run.

The CRM seed refresh retained 150 synthetic customers and created 3,650 transactions, including trend changes and life-event spending. A pre-refresh database backup is stored locally at `/tmp/banking-crm-review/before-demo-refresh.dump` (temporary, not part of the submission).
