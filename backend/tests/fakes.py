"""Shared test doubles: an in-memory repository with three customers (42 and 21 eligible, 7 weak credit)."""
from test_rules import customer, product


class FakeRepo:
    def __init__(self):
        self.rows = [customer(customer_id=42), customer(customer_id=7, credit_score=650),
                     customer(customer_id=21, monthly_income_inr=90000, current_balance_inr=150000,
                              credit_score=770, pl_interest_history=False)]

    def search_customers(self, filters):
        return self.rows

    def list_customers_for_ranking(self, filters):
        return self.rows

    def get_customer(self, customer_id):
        return next((r for r in self.rows if r['customer_id'] == customer_id), None)

    def get_products(self, code=None):
        rows = [product(), product('PL_STANDARD', 30000, 680)]
        return [r for r in rows if r['product_code'] == code] if code else rows

    def ping(self): return True
