"""Composable deterministic tool functions suitable for later LLM tool wrapping."""
from __future__ import annotations
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any
from .models import CustomerSearch, Prospect, ProspectQuery, ProspectResponse, TransactionInsights
from .rules import (balance_band, classify_high_value, contact_permission, credit_band, income_band,
                    match_products, score_conversion, transaction_insights)

INSIGHT_MONTHS = 6


def _window_start(now: datetime) -> date:
    """First day of the month INSIGHT_MONTHS complete months before the current one."""
    index = now.year * 12 + now.month - 1 - INSIGHT_MONTHS
    return date(index // 12, index % 12 + 1, 1)


def _tenure_years(row: dict, now: datetime) -> int | None:
    since = row.get('customer_since')
    return (now.date() - since).days // 365 if since else None


class CustomerNotFound(LookupError):
    pass


class ProductNotFound(LookupError):
    pass


class CRMTools:
    SUMMARY_FIELDS = ('customer_id', 'full_name', 'city', 'occupation', 'account_status', 'kyc_status')

    def __init__(self, repository: Any, clock=None):
        self.repo = repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @classmethod
    def summary(cls, row: dict) -> dict:
        """PII minimised: only fields the RM needs to shortlist, with income, credit score and balance as bands."""
        out = {k: row[k] for k in cls.SUMMARY_FIELDS if k in row}
        out['income_band'] = income_band(row.get('monthly_income_inr'))
        out['credit_band'] = credit_band(row.get('credit_score'))
        out['balance_band'] = balance_band(row.get('current_balance_inr'))
        return out

    def search_customers(self, criteria: CustomerSearch) -> list[dict]:
        return [self.summary(c) for c in self.repo.search_customers(criteria.model_dump())]

    def get_customer(self, customer_id: int) -> dict:
        customer = self.repo.get_customer(customer_id)
        if customer is None:
            raise CustomerNotFound(f'Customer {customer_id} not found')
        return customer

    def customer_profile(self, customer_id: int) -> dict:
        return self.summary(self.get_customer(customer_id))

    def classify_high_value(self, customer_id: int):
        return classify_high_value(self.get_customer(customer_id))

    def _insights(self, rows: list[dict], now: datetime) -> dict[int, TransactionInsights]:
        by_customer = defaultdict(list)
        for t in self.repo.get_transactions([r['customer_id'] for r in rows], _window_start(now)):
            by_customer[t['customer_id']].append(t)
        return {r['customer_id']: transaction_insights(r, by_customer[r['customer_id']], now) for r in rows}

    def transaction_insights(self, customer_id: int) -> TransactionInsights:
        now = self.clock()
        return self._insights([self.get_customer(customer_id)], now)[customer_id]

    def score_conversion(self, customer_id: int):
        customer, now = self.get_customer(customer_id), self.clock()
        return score_conversion(customer, now, self._insights([customer], now)[customer_id])

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
        candidates = []
        for row in rows:  # eligibility and consent do not depend on transactions: filter first
            if criteria.high_value_only and not classify_high_value(row).high_value:
                continue
            base = score_conversion(row, now)
            if not base.preliminarily_eligible:
                continue
            if criteria.contactable_only and not base.whatsapp_contact_permitted:
                continue
            candidates.append(row)
        insights = self._insights(candidates, now)  # one transactions query for all candidates
        output = []
        for row in candidates:
            score = score_conversion(row, now, insights[row['customer_id']])
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
                occupation=row.get('occupation'), tenure_years=_tenure_years(row, now),
                income_band=income_band(row['monthly_income_inr']), credit_band=credit_band(row.get('credit_score')),
                balance_band=balance_band(row['current_balance_inr']),
                propensity_score=score.propensity_score,
                suggested_product_code=selected.product_code,
                reason='; '.join(score.reasons),
                timing_signals=insights[row['customer_id']].timing_signals,
                outreach_themes=insights[row['customer_id']].outreach_themes,
                preliminarily_eligible=score.preliminarily_eligible,
                whatsapp_contact_permitted=score.whatsapp_contact_permitted,
            ))
        output.sort(key=lambda p: (-p.propensity_score, p.customer_id))
        selected = output[criteria.offset:criteria.offset + criteria.limit]
        return ProspectResponse(total_returned=len(selected), prospects=selected,
                                applied_minimums=criteria.applied_minimums())
