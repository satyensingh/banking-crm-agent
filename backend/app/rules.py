"""Business policies are deterministic, reviewable, and unit-testable.

Eligibility and the base scoring factors follow the seed script's personal_loan_prospects view. The
score is rescaled to leave 15 of 100 points for a "this month" timing component derived from the
customer's transactions (transaction_insights), which the view does not have.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from .bands import (balance_band, credit_band, emi_band, income_band, multiple_band,  # noqa: F401 (re-exported)
                    surplus_band)
from .models import (Classification, ContactPermission, LifeEvent, ProductMatch, ScoreBreakdown, Scoring,
                     TransactionInsights)


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


INCOME_CATEGORIES = ('SALARY', 'BUSINESS_INCOME')
DISCRETIONARY_CATEGORIES = ('SHOPPING',)
# One-off spends that commonly precede a personal loan, and the neutral theme a draft may mention.
LIFE_EVENT_THEMES = {'EDUCATION': 'education plans', 'HOME_IMPROVEMENT': 'home improvement plans',
                     'TRAVEL': 'travel plans', 'WEDDING': 'family celebrations'}
# Health spending is never used for scoring or outreach: targeting credit at a health event is not acceptable.
EXCLUDED_CATEGORIES = ('MEDICAL',)
_LABELS = {'EDUCATION': 'Education', 'HOME_IMPROVEMENT': 'Home improvement', 'TRAVEL': 'Travel',
           'WEDDING': 'Wedding'}


def _months_back(value: date | datetime, now: datetime) -> int:
    """0 = the current month, 1 = last complete month, and so on."""
    return (now.year * 12 + now.month) - (value.year * 12 + value.month)


def _trend(recent: Decimal, prior: Decimal, threshold: Decimal) -> str:
    if prior <= 0:
        return 'UNKNOWN'
    change = (recent - prior) / prior
    return 'RISING' if change >= threshold else 'FALLING' if change <= -threshold else 'STABLE'


def transaction_insights(customer: dict[str, Any], transactions: list[dict[str, Any]],
                         now: datetime | None = None) -> TransactionInsights:
    """Turn the last 6 complete months of transactions into trends, bands and timing signals.

    Latest 3 months are compared with the 3 before. Timing points (max 15): a recent life-event spend 8,
    rising income 4, rising discretionary spend 3. Only bands and trends leave this function, never amounts.
    """
    now = now or datetime.now(timezone.utc)
    income, shopping, debits = [Decimal(0)] * 7, [Decimal(0)] * 7, Decimal(0)
    income_months, events = set(), []
    for t in transactions:
        back = _months_back(t['transaction_at'], now)
        if not 1 <= back <= 6 or t['category'] in EXCLUDED_CATEGORIES:
            continue
        amount = money(t['amount_inr'])
        if t['direction'] == 'CREDIT' and t['category'] in INCOME_CATEGORIES:
            income[back] += amount
            income_months.add(back)
        elif t['direction'] == 'DEBIT':
            debits += amount
            if t['category'] in DISCRETIONARY_CATEGORIES:
                shopping[back] += amount
            elif t['category'] in LIFE_EVENT_THEMES and back <= 2:
                events.append((back, t))
    total_income = sum(income)
    monthly_income = total_income / len(income_months) if income_months else money(customer.get('monthly_income_inr'))
    income_trend = _trend(sum(income[1:4]), sum(income[4:7]), Decimal('0.05'))
    spend_trend = _trend(sum(shopping[1:4]), sum(shopping[4:7]), Decimal('0.15'))
    life_events, signals, points = [], [], 0
    for back, t in sorted(events, key=lambda e: e[0]):
        size = multiple_band(money(t['amount_inr']) / monthly_income if monthly_income else 0)
        life_events.append(LifeEvent(category=t['category'], month=f"{t['transaction_at']:%Y-%m}",
                                     size_vs_monthly_income=size))
        signals.append(f"{_LABELS[t['category']]} spend {'last month' if back == 1 else '2 months ago'} ({size})")
    if life_events:
        points += 8
    if income_trend == 'RISING':
        points += 4
        signals.append('Income up over the last 3 months')
    elif income_trend == 'FALLING':
        signals.append('Income down over the last 3 months (caution)')
    if spend_trend == 'RISING':
        points += 3
        signals.append('Discretionary spending up over the last 3 months')
    surplus = (total_income - debits) / total_income if total_income else None
    if surplus is not None and surplus < Decimal('0.10'):
        signals.append('Monthly surplus below 10% of income (caution)')
    themes = list(dict.fromkeys(LIFE_EVENT_THEMES[e.category] for e in life_events))
    return TransactionInsights(
        customer_id=customer['customer_id'], months_analyzed=6, income_months=len(income_months),
        income_trend=income_trend, discretionary_spend_trend=spend_trend,
        monthly_surplus_band=surplus_band(surplus), recent_life_events=life_events,
        timing_signals=signals, timing_points=min(points, 15), outreach_themes=themes)


def score_conversion(customer: dict[str, Any], now: datetime | None = None,
                     insights: TransactionInsights | None = None) -> Scoring:
    """Heuristic score [0,100], not a probability or ML prediction. Without insights, timing scores 0."""
    now = now or datetime.now(timezone.utc)
    income = money(customer.get('monthly_income_inr'))
    credit = customer.get('credit_score') or 0
    balance = money(customer.get('current_balance_inr'))
    emi = money(customer.get('existing_emi_to_income_ratio'))
    contact_age = days_ago(customer.get('last_pl_contact_at'), now)
    # Same thresholds as the SQL view (date subtraction is strict); weights rescaled to make room for timing.
    breakdown = ScoreBreakdown(
        income=20 if income >= 120000 else 16 if income >= 80000 else 10 if income >= 50000 else 4,
        credit=20 if credit >= 800 else 16 if credit >= 750 else 10 if credit >= 700 else 4,
        balance=15 if balance >= 200000 else 11 if balance >= 100000 else 7 if balance >= 50000 else 2,
        emi=15 if emi < Decimal('0.15') else 10 if emi < Decimal('0.30') else 3,
        interest=10 if customer.get('pl_interest_history') else 0,
        recency=5 if contact_age is None or contact_age > 30 else 0,
        timing=insights.timing_points if insights else 0,
    )
    score = sum(breakdown.model_dump().values())
    blockers = _blockers(customer, now)
    contact = contact_permission(customer, now)
    reasons = [f'Monthly income {income_band(income)}', f'Credit score {credit_band(customer.get("credit_score")) or "unavailable"}',
               f'Account balance {balance_band(balance)}', f'Existing EMI/income {emi_band(emi)}']
    if customer.get('pl_interest_history'): reasons.append('Previous personal-loan interest')
    if contact_age is None or contact_age > 30: reasons.append('No personal-loan contact in last 30 days')
    if insights:
        reasons.extend(insights.timing_signals)
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
        minimum_income = money(product.get('minimum_income_inr'))
        credit = customer.get('credit_score') or 0
        minimum_credit = product.get('minimum_credit_score') or 0
        if customer.get('kyc_status') != 'VERIFIED': blockers.append('KYC_NOT_VERIFIED')
        if customer.get('risk_band') == 'HIGH': blockers.append('HIGH_RISK')
        if customer.get('account_status') != 'ACTIVE': blockers.append('ACCOUNT_NOT_ACTIVE')
        if income < minimum_income: blockers.append('BELOW_PRODUCT_MINIMUM_INCOME')
        if credit < minimum_credit: blockers.append('BELOW_PRODUCT_MINIMUM_CREDIT_SCORE')
        if code.startswith('PL_'):
            blockers.extend(x for x in _blockers(customer, now) if x not in (
                'CREDIT_SCORE_BELOW_680', 'INCOME_BELOW_30000', 'KYC_NOT_VERIFIED',
                'HIGH_RISK', 'ACCOUNT_NOT_ACTIVE'))
        # For demo products without explicit card/vehicle affordability rules,
        # do not imply that a loan has been approved.
        matches.append(ProductMatch(customer_id=customer['customer_id'], product_id=product['product_id'],
                                    product_code=code, product_name=product['product_name'],
                                    suitable=not blockers, reasons=[
                                        # Product minimums are public product data; the customer's figures are not (bands.py).
                                        f'Income {"meets" if income >= minimum_income else "below"} '
                                        f'product minimum INR {minimum_income:,.0f}',
                                        f'Credit score {"meets" if credit >= minimum_credit else "below"} '
                                        f'product minimum {minimum_credit}',
                                    ], blockers=sorted(set(blockers)),
                                    maximum_loan_amount_inr=product.get('maximum_loan_amount_inr'),
                                    annual_interest_rate_pct=product.get('annual_interest_rate_pct')))
    # Premium personal loan first for suitable qualified customers, then others.
    return sorted(matches, key=lambda m: (not m.suitable, 0 if m.product_code == 'PL_PREMIUM' else 1, m.product_id))
