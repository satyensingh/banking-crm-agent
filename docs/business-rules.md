# Data and business rules

[Setup and run](../README.md) · [Documentation index](README.md)

The database is the `banking_crm_demo` schema: `customers`, `accounts`, `transactions`, `products`, `customer_products`, `outreach_history`, `loan_applications` (see [diagrams/database_diagram.md](../diagrams/database_diagram.md)). The seed contains **150 fictional customers** with deliberate edge cases: no WhatsApp opt-in, do-not-contact, weak KYC, low credit score, high risk, open applications, existing personal loans and recent declines.

**Transactions** cover the last 6 complete months: monthly income, rent, shopping and utilities. Some customers have rising or falling income, rising discretionary spend, or a one-off life-event spend (education, home improvement, travel, wedding, medical) in the last two months. All patterns are deterministic by customer ID, and dates are relative to the day the database is seeded.

**Products:** `PL_STANDARD` (personal loan), `PL_PREMIUM` (personal loan, needs income ≥ ₹80k and credit ≥ 750), `CC_REWARDS` (credit card), `AUTO_LOAN`.

**High-value** (an illustrative segmentation rule): monthly income ≥ ₹80,000 **and** balance ≥ ₹100,000.

**Propensity score (0–100, a heuristic)** is the sum of these parts:

| Part | Max | Scale |
|---|---|---|
| Income | 20 | ≥120k: 20 · ≥80k: 16 · ≥50k: 10 · else 4 |
| Credit score | 20 | ≥800: 20 · ≥750: 16 · ≥700: 10 · else 4 |
| Balance | 15 | ≥200k: 15 · ≥100k: 11 · ≥50k: 7 · else 2 |
| Existing EMI / income | 15 | <15%: 15 · <30%: 10 · else 3 |
| Past personal-loan interest | 10 | yes: 10 |
| No personal-loan contact in 30 days | 5 | yes: 5 |
| **Timing ("this month")** | 15 | life-event spend in the last 2 months: 8 · income up: 4 · discretionary spend up: 3 |

**Transaction insights** (`transaction_insights` in `rules.py`) compare the latest 3 complete months with the 3 before. Income is *rising* or *falling* at ±5%, and discretionary (shopping) spend at ±15%. The result adds a surplus band ((income − debits) / income) and recent life events, each sized against monthly income (for example *1–2x monthly income*). Falling income and a surplus below 10% are reported as **caution** signals and earn no points. Only trends and bands leave the service, never amounts.

**Health spending is ignored.** Medical transactions are excluded from insights, scoring and outreach themes, because targeting credit at someone's health event is not acceptable. The seed includes medical spends to show this.

**Eligibility blockers** (any one makes a customer not eligible): KYC not verified · high risk band · credit score < 680 · income < ₹30,000 · account not active · fewer than 5 months of income history · EMI/income > 40% · active personal loan · pending personal-loan application · personal-loan decline in the last 90 days.

**WhatsApp permission** is stricter than eligibility. A customer is contactable only if they have **no eligibility blockers**, **and** have opted in to WhatsApp, **and** are not on the do-not-contact list, **and** have had no personal-loan contact in the last 30 days. Any failure is returned as a named blocker.

Eligibility and the base factors follow the seed script's `personal_loan_prospects` view, which is kept as the dataset's reference ranking. The app's weights are rescaled to make room for timing, which the view doesn't have. `rules.py` is where to change them.
