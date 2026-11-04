-- Banking CRM Agentic AI take-home: synthetic PostgreSQL demo dataset
-- PostgreSQL 14+ recommended. Safe to rerun: the dedicated demo schema is rebuilt.
-- WARNING: Drops banking_crm_demo schema and everything inside it. Never run on production data.
-- Usage: psql -v ON_ERROR_STOP=1 -d your_database -f banking_crm_seed.sql
BEGIN;
DROP SCHEMA IF EXISTS banking_crm_demo CASCADE;
CREATE SCHEMA banking_crm_demo;
SET search_path TO banking_crm_demo, public;

CREATE TABLE customers (
    customer_id BIGINT PRIMARY KEY,
    full_name TEXT NOT NULL,
    phone_e164 VARCHAR(16) NOT NULL UNIQUE,
    city TEXT NOT NULL,
    date_of_birth DATE NOT NULL,
    occupation VARCHAR(40) NOT NULL,
    customer_since DATE NOT NULL,
    kyc_status VARCHAR(15) NOT NULL CHECK (kyc_status IN ('VERIFIED','PENDING','EXPIRED')),
    risk_band VARCHAR(10) NOT NULL CHECK (risk_band IN ('LOW','MEDIUM','HIGH')),
    credit_score INTEGER CHECK (credit_score BETWEEN 300 AND 900),
    monthly_income_inr NUMERIC(12,2) NOT NULL CHECK (monthly_income_inr >= 0),
    whatsapp_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
    do_not_contact BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE accounts (
    account_id BIGINT PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    account_type VARCHAR(15) NOT NULL CHECK (account_type IN ('SAVINGS','CURRENT')),
    status VARCHAR(12) NOT NULL CHECK (status IN ('ACTIVE','DORMANT','CLOSED')),
    current_balance_inr NUMERIC(14,2) NOT NULL,
    opened_on DATE NOT NULL
);

CREATE TABLE transactions (
    transaction_id BIGINT PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES accounts(account_id),
    transaction_at TIMESTAMP NOT NULL,
    direction VARCHAR(6) NOT NULL CHECK (direction IN ('CREDIT','DEBIT')),
    category VARCHAR(30) NOT NULL CHECK (category IN ('SALARY','BUSINESS_INCOME','RENT','SHOPPING','UTILITIES','TRANSFER','LOAN_EMI')),
    amount_inr NUMERIC(12,2) NOT NULL CHECK (amount_inr > 0),
    description TEXT
);

CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    product_code VARCHAR(30) NOT NULL UNIQUE,
    product_name TEXT NOT NULL,
    annual_interest_rate_pct NUMERIC(5,2),
    minimum_income_inr NUMERIC(12,2),
    minimum_credit_score INTEGER,
    maximum_loan_amount_inr NUMERIC(14,2),
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE customer_products (
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    status VARCHAR(12) NOT NULL CHECK (status IN ('ACTIVE','CLOSED')),
    outstanding_inr NUMERIC(14,2) NOT NULL DEFAULT 0,
    monthly_emi_inr NUMERIC(12,2) NOT NULL DEFAULT 0,
    opened_on DATE NOT NULL,
    PRIMARY KEY (customer_id, product_id)
);

CREATE TABLE outreach_history (
    outreach_id BIGINT PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    channel VARCHAR(12) NOT NULL CHECK (channel IN ('WHATSAPP','CALL','EMAIL')),
    contacted_at TIMESTAMP NOT NULL,
    outcome VARCHAR(15) NOT NULL CHECK (outcome IN ('INTERESTED','NO_RESPONSE','DECLINED','CONVERTED')),
    note TEXT
);

CREATE TABLE loan_applications (
    application_id BIGINT PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    applied_at DATE NOT NULL,
    status VARCHAR(15) NOT NULL CHECK (status IN ('PENDING','APPROVED','REJECTED','DISBURSED')),
    requested_amount_inr NUMERIC(14,2) NOT NULL CHECK (requested_amount_inr > 0)
);

INSERT INTO products (product_id,product_code,product_name,annual_interest_rate_pct,minimum_income_inr,minimum_credit_score,maximum_loan_amount_inr) VALUES
(1,'PL_STANDARD','Personal Loan - Standard',13.50,30000,680,1000000),
(2,'PL_PREMIUM','Personal Loan - Premium',11.25,80000,750,2500000),
(3,'CC_REWARDS','Rewards Credit Card',NULL,25000,650,NULL),
(4,'AUTO_LOAN','Vehicle Loan',9.25,40000,700,2000000);

-- 150 fictional customers. Deliberately include edge cases: absent opt-in, DNC, weak KYC,
-- low credit score, high risk, open applications, existing personal loan, and recent declines.
WITH names AS (
  SELECT ARRAY['Aarav','Aditi','Akash','Ananya','Arjun','Bhavna','Deepak','Diya','Ishaan','Kavya','Kiran','Meera','Neha','Nikhil','Pooja','Priya','Rahul','Riya','Rohan','Sanya','Saurabh','Sneha','Tanvi','Varun','Vivek'] AS first_names,
         ARRAY['Sharma','Patel','Mehta','Rao','Gupta','Iyer','Kapoor','Nair','Joshi','Singh','Verma','Desai'] AS last_names,
         ARRAY['Mumbai','Pune','Bengaluru','Hyderabad','Delhi','Chennai'] AS cities
)
INSERT INTO customers (customer_id,full_name,phone_e164,city,date_of_birth,occupation,customer_since,kyc_status,risk_band,credit_score,monthly_income_inr,whatsapp_opt_in,do_not_contact)
SELECT n,
       first_names[1 + ((n - 1) % 25)] || ' ' || last_names[1 + ((n - 1) % 12)],
       '+9190000' || lpad(n::text,5,'0'),
       cities[1 + ((n - 1) % 6)],
       make_date(1972 + ((n * 7) % 31),1 + ((n * 5) % 12),1 + ((n * 11) % 28)),
       CASE WHEN n % 7 = 0 THEN 'SELF_EMPLOYED' ELSE 'SALARIED' END,
       CURRENT_DATE - (365 + (n * 37) % 3600),
       CASE WHEN n % 23 = 0 THEN 'EXPIRED' WHEN n % 19 = 0 THEN 'PENDING' ELSE 'VERIFIED' END,
       CASE WHEN n % 17 = 0 THEN 'HIGH' WHEN n % 8 = 0 THEN 'MEDIUM' ELSE 'LOW' END,
       610 + (n * 37) % 241,
       (25000 + (n * 3791) % 175000)::numeric(12,2),
       (n % 9 <> 0),
       (n % 31 = 0)
FROM generate_series(1,150) AS n CROSS JOIN names;

INSERT INTO accounts (account_id,customer_id,account_type,status,current_balance_inr,opened_on)
SELECT 100000 + customer_id, customer_id,
       CASE WHEN occupation = 'SELF_EMPLOYED' THEN 'CURRENT' ELSE 'SAVINGS' END,
       CASE WHEN customer_id % 29 = 0 THEN 'DORMANT' ELSE 'ACTIVE' END,
       (5000 + (customer_id * 8573) % 420000)::numeric(14,2), customer_since
FROM customers;

-- Six complete prior calendar months, not future-looking data. For each month, record
-- regular income and spending, producing useful behavior for ranking and explanations.
WITH six_months AS (
    SELECT (date_trunc('month',CURRENT_DATE)::date - (m || ' months')::interval)::date AS month_start
    FROM generate_series(1,6) m
), base AS (
    SELECT c.customer_id,c.monthly_income_inr,c.occupation,a.account_id,sm.month_start,
           row_number() OVER (ORDER BY c.customer_id,sm.month_start) AS seq
    FROM customers c JOIN accounts a USING(customer_id) CROSS JOIN six_months sm
)
INSERT INTO transactions (transaction_id,account_id,transaction_at,direction,category,amount_inr,description)
SELECT 1000000 + seq * 10 + k.kind, account_id,
       (month_start + (CASE WHEN k.kind=1 THEN 1 WHEN k.kind=2 THEN 8 WHEN k.kind=3 THEN 14 ELSE 20 END))::timestamp + interval '10 hours',
       CASE WHEN k.kind=1 THEN 'CREDIT' ELSE 'DEBIT' END,
       CASE k.kind WHEN 1 THEN CASE WHEN occupation='SALARIED' THEN 'SALARY' ELSE 'BUSINESS_INCOME' END
                   WHEN 2 THEN 'RENT' WHEN 3 THEN 'SHOPPING' ELSE 'UTILITIES' END,
       round(CASE k.kind WHEN 1 THEN monthly_income_inr * (0.93 + (customer_id % 6) * 0.02)
                        WHEN 2 THEN monthly_income_inr * 0.22
                        WHEN 3 THEN monthly_income_inr * (0.10 + (customer_id % 5) * 0.025)
                        ELSE monthly_income_inr * 0.055 END,2),
       CASE WHEN k.kind = 1 THEN 'Recurring monthly income' ELSE 'Regular monthly expense' END
FROM base CROSS JOIN (VALUES (1),(2),(3),(4)) AS k(kind);

-- Existing loans; these should affect suitability and DTI checks.
INSERT INTO customer_products(customer_id,product_id,status,outstanding_inr,monthly_emi_inr,opened_on)
SELECT customer_id,
       CASE WHEN customer_id % 13 = 0 THEN 1 ELSE 4 END,
       'ACTIVE',
       (150000 + customer_id * 2100)::numeric(14,2),
       (6500 + customer_id % 9 * 1200)::numeric(12,2),
       CURRENT_DATE - (180 + customer_id * 4)::int
FROM customers WHERE customer_id % 6 = 0 OR customer_id % 13 = 0;

-- Historical outreach for both personal loans and credit cards.
INSERT INTO outreach_history(outreach_id,customer_id,product_id,channel,contacted_at,outcome,note)
SELECT 200000 + customer_id, customer_id,
       CASE WHEN customer_id % 5 = 0 THEN 3 ELSE 1 END,
       CASE WHEN customer_id % 3 = 0 THEN 'CALL' ELSE 'WHATSAPP' END,
       CURRENT_DATE::timestamp - ((customer_id * 7) % 110 + 1) * interval '1 day',
       CASE WHEN customer_id % 14 = 0 THEN 'DECLINED'
            WHEN customer_id % 11 = 0 THEN 'INTERESTED'
            WHEN customer_id % 37 = 0 THEN 'CONVERTED' ELSE 'NO_RESPONSE' END,
       'Synthetic campaign history'
FROM customers WHERE customer_id % 4 = 0 OR customer_id % 7 = 0;

-- Loan application records include pending and rejected prospects.
INSERT INTO loan_applications(application_id,customer_id,product_id,applied_at,status,requested_amount_inr)
SELECT 300000 + customer_id, customer_id, 1,
       CURRENT_DATE - ((customer_id % 45) + 1)::int,
       CASE WHEN customer_id % 3 = 0 THEN 'PENDING'
            WHEN customer_id % 3 = 1 THEN 'REJECTED' ELSE 'APPROVED' END,
       150000 + customer_id * 3000
FROM customers WHERE customer_id % 16 = 0;

CREATE INDEX idx_transactions_account_date ON transactions(account_id,transaction_at DESC);
CREATE INDEX idx_outreach_customer_date ON outreach_history(customer_id,contacted_at DESC);
CREATE INDEX idx_loan_applications_customer_status ON loan_applications(customer_id,status);
CREATE INDEX idx_accounts_customer ON accounts(customer_id);

-- Derived view: one row per customer; makes tools easy to implement.
CREATE VIEW customer_features AS
WITH tx AS (
  SELECT a.customer_id,
         round(coalesce(sum(CASE WHEN t.direction='CREDIT' AND t.category IN ('SALARY','BUSINESS_INCOME') THEN t.amount_inr ELSE 0 END),0)/6,2) AS avg_monthly_income_credit_inr,
         count(*) FILTER (WHERE t.direction='CREDIT' AND t.category IN ('SALARY','BUSINESS_INCOME')) AS income_credit_months,
         round(coalesce(sum(CASE WHEN t.direction='DEBIT' THEN t.amount_inr ELSE 0 END),0)/6,2) AS avg_monthly_debits_inr
  FROM accounts a LEFT JOIN transactions t ON t.account_id=a.account_id
  GROUP BY a.customer_id
), loans AS (
  SELECT customer_id,coalesce(sum(monthly_emi_inr) FILTER (WHERE status='ACTIVE'),0) AS total_monthly_emi_inr,
         bool_or(product_id IN (1,2) AND status='ACTIVE') AS has_active_personal_loan
  FROM customer_products GROUP BY customer_id
), contact AS (
  SELECT customer_id,
         max(contacted_at) FILTER (WHERE product_id IN (1,2)) AS last_pl_contact_at,
         max(contacted_at) FILTER (WHERE product_id IN (1,2) AND outcome='DECLINED') AS last_pl_declined_at,
         bool_or(product_id IN (1,2) AND outcome='INTERESTED') AS pl_interest_history
  FROM outreach_history GROUP BY customer_id
), application AS (
  SELECT customer_id,bool_or(product_id IN (1,2) AND status='PENDING') AS has_pending_pl_application
  FROM loan_applications GROUP BY customer_id
)
SELECT c.customer_id,c.full_name,c.city,c.phone_e164,c.occupation,c.monthly_income_inr,
       c.credit_score,c.risk_band,c.kyc_status,c.whatsapp_opt_in,c.do_not_contact,
       a.status AS account_status,a.current_balance_inr,
       tx.avg_monthly_income_credit_inr,tx.income_credit_months,tx.avg_monthly_debits_inr,
       coalesce(loans.total_monthly_emi_inr,0) AS total_monthly_emi_inr,
       round(coalesce(loans.total_monthly_emi_inr,0)/nullif(c.monthly_income_inr,0),3) AS existing_emi_to_income_ratio,
       coalesce(loans.has_active_personal_loan,false) AS has_active_personal_loan,
       contact.last_pl_contact_at,contact.last_pl_declined_at,
       coalesce(contact.pl_interest_history,false) AS pl_interest_history,
       coalesce(application.has_pending_pl_application,false) AS has_pending_pl_application
FROM customers c JOIN accounts a ON a.customer_id=c.customer_id
LEFT JOIN tx ON tx.customer_id=c.customer_id
LEFT JOIN loans ON loans.customer_id=c.customer_id
LEFT JOIN contact ON contact.customer_id=c.customer_id
LEFT JOIN application ON application.customer_id=c.customer_id;

-- Business rules are transparent and testable; score is a heuristic ranking (NOT a
-- calibrated conversion probability). Avoid describing 80/100 as an 80% conversion chance.
CREATE VIEW personal_loan_prospects AS
WITH eligible AS (
 SELECT f.*,CASE WHEN f.kyc_status='VERIFIED'
                      AND f.risk_band <> 'HIGH'
                      AND f.credit_score >= 680
                      AND f.monthly_income_inr >= 30000
                      AND f.account_status='ACTIVE'
                      AND f.income_credit_months >= 5
                      AND f.existing_emi_to_income_ratio <= 0.40
                      AND NOT f.has_active_personal_loan
                      AND NOT f.has_pending_pl_application
                      AND (f.last_pl_declined_at IS NULL OR f.last_pl_declined_at < CURRENT_DATE - interval '90 days')
                 THEN true ELSE false END AS preliminarily_eligible
 FROM customer_features f
), scored AS (
 SELECT e.*,
   (CASE WHEN monthly_income_inr >= 120000 THEN 25 WHEN monthly_income_inr >= 80000 THEN 20 WHEN monthly_income_inr >= 50000 THEN 12 ELSE 5 END
  + CASE WHEN credit_score >= 800 THEN 25 WHEN credit_score >= 750 THEN 20 WHEN credit_score >= 700 THEN 12 ELSE 5 END
  + CASE WHEN current_balance_inr >= 200000 THEN 20 WHEN current_balance_inr >= 100000 THEN 15 WHEN current_balance_inr >= 50000 THEN 10 ELSE 3 END
  + CASE WHEN existing_emi_to_income_ratio < 0.15 THEN 15 WHEN existing_emi_to_income_ratio < 0.30 THEN 10 ELSE 3 END
  + CASE WHEN pl_interest_history THEN 10 ELSE 0 END
  + CASE WHEN last_pl_contact_at IS NULL OR last_pl_contact_at < CURRENT_DATE - interval '30 days' THEN 5 ELSE 0 END
   )::integer AS propensity_score
 FROM eligible e
)
SELECT s.*,
       CASE WHEN monthly_income_inr >= 80000 AND credit_score >= 750 THEN 'PL_PREMIUM' ELSE 'PL_STANDARD' END AS suggested_product_code,
       (s.preliminarily_eligible AND s.whatsapp_opt_in AND NOT s.do_not_contact
        AND (s.last_pl_contact_at IS NULL OR s.last_pl_contact_at < CURRENT_DATE - interval '30 days')) AS whatsapp_contact_permitted
FROM scored s;
COMMIT;

-- Quick verification
SELECT 'customers' AS entity,count(*) AS row_count FROM banking_crm_demo.customers
UNION ALL SELECT 'accounts',count(*) FROM banking_crm_demo.accounts
UNION ALL SELECT 'transactions',count(*) FROM banking_crm_demo.transactions
UNION ALL SELECT 'products',count(*) FROM banking_crm_demo.products
UNION ALL SELECT 'outreach_history',count(*) FROM banking_crm_demo.outreach_history
UNION ALL SELECT 'loan_applications',count(*) FROM banking_crm_demo.loan_applications;

-- USE CASE 1: Top 10 eligible customers for RM review and WhatsApp drafting.
SELECT customer_id,full_name,city,monthly_income_inr,credit_score,
       propensity_score,suggested_product_code,last_pl_contact_at
FROM banking_crm_demo.personal_loan_prospects
WHERE whatsapp_contact_permitted
ORDER BY propensity_score DESC,customer_id LIMIT 10;

-- USE CASE 2: Premium prospects (high-value personal loan campaign).
SELECT customer_id,full_name,monthly_income_inr,current_balance_inr,propensity_score
FROM banking_crm_demo.personal_loan_prospects
WHERE whatsapp_contact_permitted AND suggested_product_code='PL_PREMIUM'
ORDER BY propensity_score DESC,customer_id LIMIT 10;

-- USE CASE 3: Explain why a prospect is excluded; vital for meaningful AI tool output.
SELECT customer_id,full_name,kyc_status,risk_band,credit_score,
       whatsapp_opt_in,do_not_contact,has_active_personal_loan,
       has_pending_pl_application,preliminarily_eligible,whatsapp_contact_permitted
FROM banking_crm_demo.personal_loan_prospects
WHERE NOT whatsapp_contact_permitted ORDER BY customer_id LIMIT 20;
