# Database Diagram

[Setup and run](../README.md) · [Documentation index](../docs/README.md) · [Architecture diagram](architecture_diagram.md) · [Process flow](process_flow.md)

Schema: `banking_crm_demo`

```mermaid
erDiagram
    CUSTOMERS ||--o{ ACCOUNTS : owns
    ACCOUNTS ||--o{ TRANSACTIONS : contains
    CUSTOMERS ||--o{ CUSTOMER_PRODUCTS : holds
    PRODUCTS ||--o{ CUSTOMER_PRODUCTS : assigned
    CUSTOMERS ||--o{ OUTREACH_HISTORY : receives
    PRODUCTS ||--o{ OUTREACH_HISTORY : promoted
    CUSTOMERS ||--o{ LOAN_APPLICATIONS : submits
    PRODUCTS ||--o{ LOAN_APPLICATIONS : requested

    CUSTOMERS {
        bigint customer_id PK
        text full_name
        varchar phone_e164 UK
        text city
        date date_of_birth
        varchar occupation
        date customer_since
        varchar kyc_status "VERIFIED, PENDING, EXPIRED"
        varchar risk_band "LOW, MEDIUM, HIGH"
        int credit_score "300-900, nullable"
        numeric monthly_income_inr
        boolean whatsapp_opt_in
        boolean do_not_contact
        timestamptz created_at
    }

    ACCOUNTS {
        bigint account_id PK
        bigint customer_id FK
        varchar account_type "SAVINGS, CURRENT"
        varchar status "ACTIVE, DORMANT, CLOSED"
        numeric current_balance_inr
        date opened_on
    }

    TRANSACTIONS {
        bigint transaction_id PK
        bigint account_id FK
        timestamp transaction_at
        varchar direction "CREDIT, DEBIT"
        varchar category
        numeric amount_inr
        text description
    }

    PRODUCTS {
        int product_id PK
        varchar product_code UK
        text product_name
        numeric annual_interest_rate_pct
        numeric minimum_income_inr
        int minimum_credit_score
        numeric maximum_loan_amount_inr
        boolean active
    }

    CUSTOMER_PRODUCTS {
        bigint customer_id PK, FK
        int product_id PK, FK
        varchar status "ACTIVE, CLOSED"
        numeric outstanding_inr
        numeric monthly_emi_inr
        date opened_on
    }

    OUTREACH_HISTORY {
        bigint outreach_id PK
        bigint customer_id FK
        int product_id FK
        varchar channel "WHATSAPP, CALL, EMAIL"
        timestamp contacted_at
        varchar outcome "INTERESTED, NO_RESPONSE, DECLINED, CONVERTED"
        text note
    }

    LOAN_APPLICATIONS {
        bigint application_id PK
        bigint customer_id FK
        int product_id FK
        date applied_at
        varchar status "PENDING, APPROVED, REJECTED, DISBURSED"
        numeric requested_amount_inr
    }
```

Views (not shown in the diagram): `customer_features`, `personal_loan_prospects`.

Transaction categories: regular `SALARY`, `BUSINESS_INCOME`, `RENT`, `SHOPPING`, `UTILITIES`, `TRANSFER`, `LOAN_EMI`, plus one-off life events `EDUCATION`, `MEDICAL`, `TRAVEL`, `HOME_IMPROVEMENT`, `WEDDING` (the signals behind `get_transaction_insights`).
