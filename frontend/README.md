# Relationship AI — Banking CRM Conversational UI

A responsive React + Vite frontend for the *Agentic AI for Banking CRM* take-home assignment. It is a **frontend**, not the agent/backend implementation. It works in mock/demo mode out of the box and provides a clearly documented contract for a Spring Boot agent service.

## Run

```bash
npm install
cp .env.example .env
npm run dev
```

Visit http://localhost:5173. To build a production bundle, run `npm run build`.

## Features

- Conversation UI with multi-session history in browser localStorage
- Sample natural-language prompts (customer discovery, prospect scoring, product matching, outreach)
- Renderable ranked prospect tables with search, pagination, CSV export and customer detail drawers
- WhatsApp **drafts**, never automatic sending
- Expandable tool-execution traces for agent observability
- Responsive layout with collapsed/overlay navigation
- Demo badge clearly distinguishes illustrative data from real customer data
- API adapter and human review messaging

**Important:** Demo prospect names and scores in `src/demo.js` are synthetic illustrative fixture values, *not* the rows produced by your `banking_crm_seed.sql` file. No eligibility, permission, or transaction validation is performed in the browser. The backend must enforce all such controls.

## Connect your Spring Boot backend

Set `VITE_DEMO_MODE=false` in `.env`, restart Vite, and implement:

`POST /api/chat` (content type `application/json`)

Request:

```json
{
  "sessionId": "some-conversation-id",
  "message": "Find my top 5 personal loan prospects and draft WhatsApp messages"
}
```

Example response:

```json
{
  "text": "I found 2 preliminarily eligible customers, both opted in for WhatsApp outreach.",
  "tools": [
    {"name": "get_customer_features", "detail": "Queried seeded PostgreSQL", "status": "complete"},
    {"name": "score_loan_prospects", "detail": "Applied SQL scoring view", "status": "complete"}
  ],
  "result": {
    "type": "prospects",
    "mode": "live",
    "customers": [
      {"customer_id": 10021, "full_name": "Example Customer", "city": "Mumbai", "propensity_score": 88, "monthly_income_inr": 125000, "credit_score": 790, "suggested_product_code": "PL_PREMIUM", "reason": "High income and a good payment profile"}
    ],
    "messages": [
      {"customerId": 10021, "customerName": "Example Customer", "content": "Hello ..."}
    ]
  }
}
```

The frontend accepts these field names from the SQL view: `customer_id`, `full_name`, `city`, `propensity_score`, `monthly_income_inr`, `credit_score`, `suggested_product_code`. API-specific optional fields include `reason` and generated `messages`. The score is a **heuristic score**, not conversion probability.

The Vite dev server proxies `/api` to `http://localhost:8080`. Change `vite.config.js` for a different Spring Boot port. For production, set `VITE_API_BASE_URL` or configure a reverse proxy. Avoid putting backend/API secrets in `VITE_` environment variables because they are included in the browser bundle.

## Architecture

```text
Relationship Manager
        |
        v
 React conversation UI
        |
        v
  src/api.js (POST /api/chat)
        |
        v
  Spring Boot / Spring AI Orchestrator  <-- to implement
        |
        +--> Customer retrieval tool --> PostgreSQL `banking_crm_demo.customer_features`
        +--> Prospect scoring tool --> PostgreSQL `banking_crm_demo.personal_loan_prospects`
        +--> Product recommendation tool
        +--> Consent/frequency-check tool
        +--> WhatsApp draft generation tool
```

## Guardrails and current limitations

- All names in demo mode are fictional. Never place real banking data in `src/demo.js`.
- No message delivery, credit approvals, or customer mutations in this UI.
- The demo mode uses keyword routing as an offline mock; this is **not actual agentic decision-making**. For assignment evaluation, connect a tool-calling agent backend.
- The chat backend is responsible for authoritative permissions, eligibility checks, scoring, auditing, session memory and safe prompt construction.
- Browser localStorage session history is for a local take-home demo only, not production storage for sensitive financial information.
- There is no authentication/RBAC yet; add your bank's approved authentication provider before connecting real customer data.

## Suggested live query

```sql
SELECT customer_id, full_name, city, monthly_income_inr, credit_score,
       propensity_score, suggested_product_code
FROM banking_crm_demo.personal_loan_prospects
WHERE whatsapp_contact_permitted = TRUE
ORDER BY propensity_score DESC
LIMIT 5;
```

Never trust the UI to filter contacts for compliance — the backend should enforce this constraint independently.
