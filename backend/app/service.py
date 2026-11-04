"""Composable deterministic tool functions suitable for later LLM tool wrapping."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from .models import CustomerSearch, Prospect, ProspectQuery, ProspectResponse
from .rules import classify_high_value, contact_permission, match_products, score_conversion


class CustomerNotFound(LookupError):
    pass


class ProductNotFound(LookupError):
    pass


class CRMTools:
    SUMMARY_FIELDS = ('customer_id', 'full_name', 'city', 'occupation', 'monthly_income_inr',
                      'credit_score', 'current_balance_inr', 'account_status', 'kyc_status')

    def __init__(self, repository: Any, clock=None):
        self.repo = repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def search_customers(self, criteria: CustomerSearch) -> list[dict]:
        # PII minimized: only return fields needed by the RM to shortlist.
        allowed = self.SUMMARY_FIELDS
        return [{k: c[k] for k in allowed if k in c} for c in self.repo.search_customers(criteria.model_dump())]

    def get_customer(self, customer_id: int) -> dict:
        customer = self.repo.get_customer(customer_id)
        if customer is None:
            raise CustomerNotFound(f'Customer {customer_id} not found')
        return customer

    def customer_profile(self, customer_id: int) -> dict:
        row = self.get_customer(customer_id)
        return {k: row[k] for k in self.SUMMARY_FIELDS if k in row}

    def classify_high_value(self, customer_id: int):
        return classify_high_value(self.get_customer(customer_id))

    def score_conversion(self, customer_id: int):
        return score_conversion(self.get_customer(customer_id), self.clock())

    def match_products(self, customer_id: int, product_code: str | None = None):
        customer = self.get_customer(customer_id)
        products = self.repo.get_products(product_code)
        if product_code and not products:
            raise ProductNotFound(f'Active product {product_code} not found')
        return match_products(customer, products, self.clock())

    def check_whatsapp_permission(self, customer_id: int):
        return contact_permission(self.get_customer(customer_id), self.clock())

    def rank_prospects(self, criteria: ProspectQuery) -> ProspectResponse:
        if criteria.product_code and not self.repo.get_products(criteria.product_code):
            raise ProductNotFound(f'Active product {criteria.product_code} not found')
        now = self.clock()
        rows = self.repo.list_customers_for_ranking(criteria.model_dump())
        products = self.repo.get_products()
        output = []
        for row in rows:
            if criteria.high_value_only and not classify_high_value(row).high_value:
                continue
            score = score_conversion(row, now)
            if not score.preliminarily_eligible:
                continue
            if criteria.contactable_only and not score.whatsapp_contact_permitted:
                continue
            recommendations = match_products(row, products, now)
            suitable = [p for p in recommendations if p.suitable]
            if criteria.product_code:
                suitable = [p for p in suitable if p.product_code == criteria.product_code]
            if not suitable:
                continue
            selected = suitable[0]
            if criteria.product_code is None:
                # Campaign is personal-loan-focused; ignore other products.
                suitable_pl = [p for p in suitable if p.product_code.startswith('PL_')]
                if not suitable_pl:
                    continue
                selected = suitable_pl[0]
            output.append(Prospect(
                customer_id=row['customer_id'], full_name=row['full_name'], city=row['city'],
                monthly_income_inr=row['monthly_income_inr'], credit_score=row.get('credit_score'),
                current_balance_inr=row['current_balance_inr'],
                propensity_score=score.propensity_score,
                suggested_product_code=selected.product_code,
                reason='; '.join(score.reasons),
                preliminarily_eligible=score.preliminarily_eligible,
                whatsapp_contact_permitted=score.whatsapp_contact_permitted,
            ))
        output.sort(key=lambda p: (-p.propensity_score, p.customer_id))
        selected = output[criteria.offset:criteria.offset + criteria.limit]
        return ProspectResponse(total_returned=len(selected), prospects=selected)
