# Banking CRM Agent — demo recording script

Target duration: **8 minutes**, including live response time.

Use one chat for all three scenarios so the follow-up demonstrates retained context.

Before recording, open http://localhost:8000, sign in, and start a new chat. Keep the repository README open in another tab at the architecture diagram. Keep `.env`, credentials, and terminal history off-screen.

## 0:00–0:40 — Introduce the problem

**Show:** The app’s welcome screen and prompt box.

**Say:**

> “This is an agentic banking CRM assistant for relationship managers. It helps an RM identify high-value personal-loan prospects, understand why they may be relevant this month, and prepare personalized WhatsApp outreach.
>
> I’ll demonstrate three scenarios: finding prospects and drafting messages, refining those messages using conversational context, and preventing outreach when contact permission is missing.
>
> All customer data is synthetic. The system creates drafts for RM review; it never sends messages.”

## 0:40–2:30 — Use case 1: Find prospects and draft outreach

**Show:** Paste and submit this exact prompt:

```text
Find the top 3 high-value customers likely to convert for a personal loan this month and generate personalized WhatsApp messages.
```

**While it runs, say:**

> “The agent decides which tools to call. For this request, the ranking tool combines customer information, transaction insights, eligibility rules, product suitability, and contact permission.
>
> The calculations happen in deterministic code. The language model orchestrates the tools and writes the customer-facing text.”

**Show:** Expand `rank_prospects`. Point to its arguments, especially `high_value_only`, `contactable_only`, and `limit`.

**Say:**

> “These inputs show how the natural-language request became a structured tool call: high-value customers, contactable prospects, and a limit of three.”

**Show:** The prospect table. Point to the names, scores, products, and **This month** column.

With the refreshed dataset, the verified ranking was:

| Customer | ID | Score |
|---|---:|---:|
| Aditi Gupta | 77 | 100 |
| Rohan Nair | 44 | 84 |
| Vivek Sharma | 25 | 83 |

**Say:**

> “The shortlist includes Aditi, Rohan, and Vivek. These scores are heuristic rankings, not conversion probabilities. A score of 100 does not mean a customer is guaranteed to convert.
>
> The ‘This month’ column explains the timing. Aditi has recent transaction signals alongside rising income and discretionary spending. Rohan has rising discretionary spending, while Vivek has travel-related activity and rising income.
>
> Financial information is exposed as bands rather than exact customer amounts.”

**Show:** Expand `save_whatsapp_drafts`, then scroll to the three rendered drafts.

**Say:**

> “The agent then generates and records a personalized draft for each customer. The drafts use relevant context such as name, city, occupation, tenure, and a possible planning theme.
>
> Notice that the customer-facing text does not say the bank monitored a transaction. It frames a theme as a possibility, such as upcoming travel or family celebrations.
>
> A deterministic validator checks the drafts for approval promises, rates, amounts, contact details, and other prohibited content. These remain drafts, clearly marked ‘not sent.’”

## 2:30–4:00 — Use case 2: Follow up without repeating customer IDs

**Show:** In the **same chat**, submit:

```text
For those same three customers, rewrite the WhatsApp drafts in a warmer tone and explain why this month is relevant. Keep the same shortlist.
```

**Say:**

> “This request deliberately contains no customer IDs. The assistant must resolve ‘those same three customers’ from the conversation and preserve the shortlist.”

**Show:** The three fresh `check_whatsapp_permission` steps. Expand one to show its customer ID and result.

**Say:**

> “The shortlist is retained, but contact authorization is not carried over from the previous turn. The agent checks WhatsApp permission again before saving the revised drafts.
>
> This separates conversational memory from permission: remembering a customer is not the same as being authorized to contact them.”

**Show:** The revised drafts and their names or IDs. Briefly compare one with its earlier version.

**Say:**

> “The revised messages still belong to Aditi, Rohan, and Vivek. The assistant has changed the wording without asking me to re-enter the shortlist or running a replacement search.
>
> The current user request and its tool exchange are preserved even when a turn contains many tool messages. Older history is trimmed at complete conversation-turn boundaries, and the selected shortlist is stored separately within the session.”

## 4:00–5:15 — Use case 3: Block outreach without permission

**Show:** Submit:

```text
Check personal-loan eligibility and WhatsApp permission for customer 9 and customer 31. Generate a WhatsApp draft only if permission is confirmed; explain any exclusions.
```

**Say:**

> “The third scenario checks whether the assistant distinguishes product suitability from permission to contact a customer.”

**Show:** The profile, product-matching, and permission tool steps. Then show the final explanation.

**Say:**

> “Customer 9 is excluded from WhatsApp outreach because opt-in is missing. Customer 31 is excluded because the do-not-contact flag is set.
>
> A customer may meet a product’s preliminary suitability rules and still be unavailable for outreach. The system treats those as separate decisions.
>
> No new WhatsApp drafts are generated for either customer. The restriction is enforced in code at the draft-saving boundary, so the language model cannot bypass it simply by writing a message.”

## 5:15–6:35 — Explain the architecture

**Show:** Switch to the README architecture diagram. Keep the entire diagram visible.

**Say:**

> “The architecture separates the user interface, orchestration, tools, and business logic.
>
> Chainlit provides the RM chat interface, including tool steps, prospect tables, CSV downloads, and draft display.
>
> LangGraph manages the agent loop. The model can request tools, inspect their results, and continue until it can answer. The loop has a maximum of eight model rounds to bound execution.
>
> The agent discovers typed CRM tools from a separate FastMCP server over HTTP. Those tools cover customer search, high-value classification, transaction insights, scoring, product matching, permission checks, and ranking.
>
> Behind the tool server, a service layer combines reusable business rules with a PostgreSQL repository. Queries are parameterized and run in read-only transactions. The language model never generates SQL.
>
> Draft saving is an agent-local tool because it needs to check which customers had permission confirmed during the current turn.
>
> This separation makes the system extensible: a new capability can be added through a rule, repository access if needed, and a typed MCP tool.”

## 6:35–7:40 — Explain trade-offs and limitations

**Show:** Scroll to the README’s **Key design decisions** and **Trade-offs and limitations** sections.

**Say:**

> “There are four main trade-offs.
>
> First, I chose explainable heuristics rather than a trained conversion model because this dataset has no labelled conversion outcomes. Each score can be explained, but the weights are illustrative and would need validation against real outcomes.
>
> Second, financial bands reduce data exposure, at the cost of precision. Search thresholds also snap to band boundaries, which the assistant should disclose when they differ from the request.
>
> Third, conversation state is in memory. That keeps the demo simple, but it resets on restart. A production deployment would need durable state and support for multiple workers.
>
> Fourth, outreach stops at draft creation. Human review remains necessary because rule-based text checks cannot catch every misleading phrase.
>
> Other production work includes authentication on the MCP endpoint, stronger operational monitoring, and database-side ranking for larger datasets. These are documented limitations rather than claims of production readiness.”

## 7:40–8:15 — Close with verification and outcome

**Show:** Return to the chat’s blocked-contact result. If you already have the test summary visible in a terminal tab, briefly show `155 passed`; otherwise, keep the app on screen.

**Say:**

> “The automated suite currently passes 155 tests, covering business rules, MCP tools, agent behavior, consent gates, draft validation, and authentication helpers.
>
> I also verified these three scenarios against the live model, HTTP MCP server, and PostgreSQL database, and rehearsed them through the Chainlit interface.
>
> The result is a conversational assistant that can retrieve and rank prospects, explain timing and product fit, retain context for follow-ups, and prepare personalized outreach while enforcing contact restrictions.
>
> The RM remains in control of the final customer communication.”

**Recording cue:** Allow roughly 20–30 seconds per live response, though latency and wording vary. If a response is still running when you finish the accompanying narration, pause quietly rather than submitting the next prompt.
