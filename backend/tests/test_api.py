from datetime import datetime, timezone
from decimal import Decimal
from fastapi.testclient import TestClient
from app.main import app, get_tools
from app.service import CRMTools
from test_rules import customer, product, NOW


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


def setup_module():
    app.dependency_overrides[get_tools] = lambda: CRMTools(FakeRepo(), clock=lambda: NOW)


def teardown_module():
    app.dependency_overrides.clear()


def test_api_rank_excludes_weak_credit_and_sorts():
    response = TestClient(app).post('/api/tools/prospects/rank', json={'limit':10})
    assert response.status_code == 200, response.text
    data = response.json()['prospects']
    assert [r['customer_id'] for r in data] == [42, 21]
    assert data[0]['suggested_product_code'] == 'PL_PREMIUM'


def test_api_classification_score_products():
    client = TestClient(app)
    assert client.get('/api/tools/customers/42/classification').json()['high_value']
    assert client.get('/api/tools/customers/42/score').json()['propensity_score'] == 100
    assert client.get('/api/tools/customers/42/products').json()['matches'][0]['suitable']
    assert client.get('/api/tools/customers/999/score').status_code == 404
    assert client.get('/api/tools/customers/42/products?product_code=UNKNOWN').status_code == 404


def test_input_validation():
    client = TestClient(app)
    assert client.post('/api/tools/customers/search', json={'limit':1000}).status_code == 422
    assert client.post('/api/tools/prospects/rank', json={'min_credit_score':999}).status_code == 422
