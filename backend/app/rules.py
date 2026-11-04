"""Business policies are deterministic, reviewable, and unit-testable.

Replicates the seed script's personal_loan_prospects SQL scoring rules so the
Python service stays consistent with the existing demo views.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from .models import Classification, ContactPermission, ProductMatch, ScoreBreakdown, Scoring


def money(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def days_ago(value: date | datetime | None, now: datetime) -> int | None:
    if value is None:
        return None
    anchor = value.date() if isinstance(value, datetime) else value
    return (now.date() - anchor).days


def classify_high_value(customer: dict[str, Any]) -> Classification:
    """Illustrative bank policy: income >= 80k AND balance >= 100k.

    This is a segmentation rule and does not imply eligibility or consent.
    """
    income = money(customer.get('monthly_income_inr'))
    balance = money(customer.get('current_balance_inr'))
    high = income >= 80000 and balance >= 100000
    reasons = [
        ('Monthly income >= INR 80,000' if income >= 80000 else 'Monthly income below INR 80,000'),
        ('Balance >= INR 100,000' if balance >= 100000 else 'Balance below INR 100,000'),
    ]
    return Classification(
        customer_id=customer['customer_id'], high_value=high, reasons=reasons,
        criteria={'min_monthly_income_inr': 80000, 'min_balance_inr': 100000},
    )


def _blockers(customer: dict[str, Any], now: datetime) -> list[str]:
    b = []
    if customer.get('kyc_status') != 'VERIFIED': b.append('KYC_NOT_VERIFIED')
    if customer.get('risk_band') == 'HIGH': b.append('HIGH_RISK')
    if customer.get('credit_score') is None or customer['credit_score'] < 680: b.append('CREDIT_SCORE_BELOW_680')
    if money(customer.get('monthly_income_inr')) < 30000: b.append('INCOME_BELOW_30000')
    if customer.get('account_status') != 'ACTIVE': b.append('ACCOUNT_NOT_ACTIVE')
    if (customer.get('income_credit_months') or 0) < 5: b.append('INSUFFICIENT_INCOME_HISTORY')
    if money(customer.get('monthly_income_inr')) <= 0 or money(customer.get('existing_emi_to_income_ratio')) > Decimal('0.40'):
        b.append('EXISTING_EMI_RATIO_ABOVE_40_PERCENT')
    if customer.get('has_active_personal_loan'): b.append('ACTIVE_PERSONAL_LOAN')
    if customer.get('has_pending_pl_application'): b.append('PENDING_PERSONAL_LOAN_APPLICATION')
    days = days_ago(customer.get('last_pl_declined_at'), now)
    if days is not None and days <= 90: b.append('RECENT_PERSONAL_LOAN_DECLINE')
    return b


def contact_permission(customer: dict[str, Any], now: datetime | None = None) -> ContactPermission:
    now = now or datetime.now(timezone.utc)
    blockers = _blockers(customer, now)
    if not customer.get('whatsapp_opt_in'): blockers.append('WHATSAPP_OPT_IN_MISSING')
    if customer.get('do_not_contact'): blockers.append('DO_NOT_CONTACT')
    last_contact_days = days_ago(customer.get('last_pl_contact_at'), now)
    if last_contact_days is not None and last_contact_days <= 30:
        blockers.append('PERSONAL_LOAN_CONTACTED_WITHIN_30_DAYS')
    return ContactPermission(customer_id=customer['customer_id'],
                             whatsapp_contact_permitted=not blockers,
                             blockers=blockers, checked_at=now)


def score_conversion(customer: dict[str, Any], now: datetime | None = None) -> Scoring:
    """Heuristic score [0,100], not a probability or ML prediction."""
    now = now or datetime.now(timezone.utc)
    income = money(customer.get('monthly_income_inr'))
    credit = customer.get('credit_score') or 0
    balance = money(customer.get('current_balance_inr'))
    emi = money(customer.get('existing_emi_to_income_ratio'))
    contact_age = days_ago(customer.get('last_pl_contact_at'), now)
    # Match threshold semantics of the SQL view (date subtraction is strict).
    breakdown = ScoreBreakdown(
        income=25 if income >= 120000 else 20 if income >= 80000 else 12 if income >= 50000 else 5,
        credit=25 if credit >= 800 else 20 if credit >= 750 else 12 if credit >= 700 else 5,
        balance=20 if balance >= 200000 else 15 if balance >= 100000 else 10 if balance >= 50000 else 3,
        emi=15 if emi < Decimal('0.15') else 10 if emi < Decimal('0.30') else 3,
        interest=10 if customer.get('pl_interest_history') else 0,
        recency=5 if contact_age is None or contact_age > 30 else 0,
    )
    score = sum(breakdown.model_dump().values())
    blockers = _blockers(customer, now)
    contact = contact_permission(customer, now)
    reasons = [f'Monthly income INR {income:,.0f}', f'Credit score {credit}',
               f'Account balance INR {balance:,.0f}', f'Existing EMI/income {emi:.1%}']
    if customer.get('pl_interest_history'): reasons.append('Previous personal-loan interest')
    if contact_age is None or contact_age > 30: reasons.append('No personal-loan contact in last 30 days')
    return Scoring(customer_id=customer['customer_id'], propensity_score=score,
                   breakdown=breakdown, reasons=reasons, blockers=blockers,
                   preliminarily_eligible=not blockers,
                   whatsapp_contact_permitted=contact.whatsapp_contact_permitted)


def match_products(customer: dict[str, Any], products: list[dict[str, Any]],
                   now: datetime | None = None) -> list[ProductMatch]:
    now = now or datetime.now(timezone.utc)
    matches = []
    for product in products:
        blockers = []
        code = product['product_code']
        income = money(customer.get('monthly_income_inr'))
        credit = customer.get('credit_score') or 0
        if customer.get('kyc_status') != 'VERIFIED': blockers.append('KYC_NOT_VERIFIED')
        if customer.get('risk_band') == 'HIGH': blockers.append('HIGH_RISK')
        if customer.get('account_status') != 'ACTIVE': blockers.append('ACCOUNT_NOT_ACTIVE')
        if income < money(product.get('minimum_income_inr')): blockers.append('BELOW_PRODUCT_MINIMUM_INCOME')
        if credit < (product.get('minimum_credit_score') or 0): blockers.append('BELOW_PRODUCT_MINIMUM_CREDIT_SCORE')
        if code.startswith('PL_'):
            blockers.extend(x for x in _blockers(customer, now) if x not in (
                'CREDIT_SCORE_BELOW_680', 'INCOME_BELOW_30000', 'KYC_NOT_VERIFIED',
                'HIGH_RISK', 'ACCOUNT_NOT_ACTIVE'))
        # For demo products without explicit card/vehicle affordability rules,
        # do not imply that a loan has been approved.
        matches.append(ProductMatch(customer_id=customer['customer_id'], product_id=product['product_id'],
                                    product_code=code, product_name=product['product_name'],
                                    suitable=not blockers, reasons=[
                                        f'Income INR {income:,.0f} / minimum INR {money(product.get("minimum_income_inr")):,.0f}',
                                        f'Credit score {credit} / minimum {product.get("minimum_credit_score") or 0}',
                                    ], blockers=sorted(set(blockers)),
                                    maximum_loan_amount_inr=product.get('maximum_loan_amount_inr'),
                                    annual_interest_rate_pct=product.get('annual_interest_rate_pct')))
    # Premium personal loan first for suitable qualified customers, then others.
    return sorted(matches, key=lambda m: (not m.suitable, 0 if m.product_code == 'PL_PREMIUM' else 1, m.product_id))
