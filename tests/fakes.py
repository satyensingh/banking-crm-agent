"""Shared test doubles: an in-memory repository with three customers (42 and 21 eligible, 7 weak credit).

Transactions (relative to test_rules.NOW, 2026-11-04): 42 has rising income and shopping plus an education
spend last month (full 15 timing points); 21 is flat and has a medical spend, which must be ignored.
"""
from datetime import date, datetime
from decimal import Decimal

from test_rules import customer, product


def month_start(back: int) -> datetime:
    index = 2026 * 12 + 11 - 1 - back  # NOW is November 2026
    return datetime(index // 12, index % 12 + 1, 1, 10)


def monthly(cid, income, shopping, rise=Decimal('1'), spend_rise=Decimal('1')):
    rows = []
    for back in range(1, 7):
        recent = back <= 3
        rows += [dict(customer_id=cid, transaction_at=month_start(back), direction='CREDIT', category='SALARY',
                      amount_inr=income * (rise if recent else 1)),
                 dict(customer_id=cid, transaction_at=month_start(back), direction='DEBIT', category='RENT',
                      amount_inr=income * Decimal('0.22')),
                 dict(customer_id=cid, transaction_at=month_start(back), direction='DEBIT', category='SHOPPING',
                      amount_inr=shopping * (spend_rise if recent else 1))]
    return rows


TRANSACTIONS = (
    monthly(42, Decimal(130000), Decimal(15000), rise=Decimal('1.12'), spend_rise=Decimal('1.4'))
    + [dict(customer_id=42, transaction_at=month_start(1).replace(day=12), direction='DEBIT', category='EDUCATION',
            amount_inr=Decimal(180000))]
    + monthly(21, Decimal(90000), Decimal(10000))
    + [dict(customer_id=21, transaction_at=month_start(1).replace(day=5), direction='DEBIT', category='MEDICAL',
            amount_inr=Decimal(120000))]
)


class FakeRepo:
    def __init__(self):
        self.rows = [customer(customer_id=42), customer(customer_id=7, credit_score=650),
                     customer(customer_id=21, monthly_income_inr=90000, current_balance_inr=150000,
                              credit_score=770, pl_interest_history=False)]
        self.transaction_queries = 0

    def search_customers(self, filters):
        return self.rows

    def list_customers_for_ranking(self, filters):
        return self.rows

    def get_customer(self, customer_id):
        return next((r for r in self.rows if r['customer_id'] == customer_id), None)

    def get_products(self, code=None):
        rows = [product(), product('PL_STANDARD', 30000, 680)]
        return [r for r in rows if r['product_code'] == code] if code else rows

    def get_transactions(self, customer_ids, since):
        self.transaction_queries += 1
        return [t for t in TRANSACTIONS if t['customer_id'] in customer_ids and t['transaction_at'].date() >= since]

    def ping(self): return True
