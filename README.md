# Banking CRM — Python Deterministic Business Tools

FastAPI + psycopg 3 service implementing **real, read-only business tools** for the Agentic AI banking take-home. No LLM or hardcoded customer response is involved. Tools query the **existing** `banking_crm_demo` schema from `banking_crm_seed.sql`, return structured results, and can later be wrapped as agent tools (LangGraph, OpenAI tool calls, etc.).

## What you get

| Tool | Endpoint | Implementation |
|---|---|---|
| Search customers | `POST /api/tools/customers/search` | Parameterized SQL against `customer_features` |
| High-value classification | `GET /api/tools/customers/{id}/classification` | Income >= ₹80k AND balance >= ₹100k (illustrative rule) |
| Conversion scoring | `GET /api/tools/customers/{id}/score` | Explainable 0–100 score, matching SQL view scoring thresholds |
| Product matching | `GET /api/tools/customers/{id}/products` | Product minimums + personal-loan eligibility blockers |
| Outreach consent check | `GET /api/tools/customers/{id}/whatsapp-permission` | Opt-in, DNC, product-contact cooldown, loan eligibility |
| Ranked prospects | `POST /api/tools/prospects/rank` | Joins above deterministic logic, filters then ranks |

**Score != conversion probability.** No ML training or calibration is claimed. All product matches are preliminary; not approvals, rates offered, or underwriting decisions.

## Start

1. In this folder (which includes `docker-compose.yml` and `banking_crm_seed.sql`), run `docker compose up -d` (initial volume creation seeds the data). Verify the database is reachable.
2. Inside this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL='postgresql://banking_user:banking_dev_password@localhost:5432/banking_crm'
uvicorn app.main:app --reload --port 8000
```

3. Open http://localhost:8000/docs to run each tool interactively.

### Examples

```bash
curl -s http://localhost:8000/api/tools/customers/1/score | python -m json.tool
curl -s http://localhost:8000/api/tools/customers/1/classification | python -m json.tool
curl -s http://localhost:8000/api/tools/customers/1/products | python -m json.tool
curl -s http://localhost:8000/api/tools/customers/1/whatsapp-permission | python -m json.tool
curl -s -X POST http://localhost:8000/api/tools/customers/search \
  -H 'Content-Type: application/json' \
  -d '{"city":"Mumbai","min_income_inr":80000,"limit":10}' | python -m json.tool
curl -s -X POST http://localhost:8000/api/tools/prospects/rank \
  -H 'Content-Type: application/json' \
  -d '{"high_value_only":true,"contactable_only":true,"limit":5}' | python -m json.tool
curl -s -X POST http://localhost:8000/api/tools/prospects/rank \
  -H 'Content-Type: application/json' \
  -d '{"product_code":"PL_PREMIUM","limit":10}' | python -m json.tool
```

## Tests

```bash
pytest -q
```

Tests are isolated using an in-memory fake repository (so a live DB isn't needed for unit/API contract tests). A live PostgreSQL integration smoke-test is recommended before submission.

## Structure

```text
app/
  main.py        # HTTP tool endpoints, dependency injection, HTTP error handling
  repository.py  # parameterized read-only PostgreSQL queries
  rules.py       # pure domain rules + scoring + contact restrictions
  service.py     # orchestrates the pure tools; read-only
  models.py      # request/response contracts (Pydantic)
tests/
  test_rules.py  # rule and edge-case testing
  test_api.py    # HTTP and validation testing
```

## Design choices and trade-offs

- **Deterministic business decisions:** LLM should decide *which* tool to call, not calculate eligibility, scores, or bypass consent.
- **Explainability:** scores expose weighted components (income 25, credit 25, balance 20, EMI 15, prior interest 10, recency 5); exclusion reasons are machine-readable blocker codes.
- **Read-only database:** the connection opens a read-only transaction and uses bound SQL parameters. No arbitrary SQL execution or customer-data changes.
- **Privacy:** customer search hides phone numbers; the full internal customer feature record is used only within service functions. Do not expose these endpoints without auth/permissions for a real bank.
- **Personal loan focused:** campaign ranking defaults to personal-loan offers; non-personal-loan matching is preliminary and does not model full underwriting.
- **Scale limitation:** ranking scans at most 10,000 matching customers in batches and then sorts in memory. For production replace with an indexed materialized feature table plus database-side scoring and keyset pagination.
- **Data model limitation:** the demo seed creates one account per customer. `customer_features` assumes a single account per customer; adjust the view to aggregate accounts before real multi-account usage.
- **No conversational agent yet:** This is precisely the deterministic tool layer. Next step: a Python agentic orchestrator + conversational API endpoint compatible with the React `POST /api/chat` contract.

## Local UI integration

The React frontend's `POST /api/chat` requires conversational orchestration and is **not implemented here**. To connect this service without a proxy, call port 8000 directly through curl/OpenAPI. Later, the orchestrator should expose `/api/chat` and have the agent invoke `CRMTools` functions, not raw SQL. If using the provided Vite UI, update its proxy from port 8080 to 8000 when that chat endpoint exists.

## Security / limitations

Demo data is synthetic. Contact permission is for **outreach drafting** only; no sending endpoint is provided. Eligibility/contact status is time-dependent and should be checked again immediately before any actual outreach. In production add role/record-level access control, audit logging, policy versioning, bank-approved marketing preferences, data minimization, and real underwriting rules.
