from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pytest
from app.models import CustomerSearch, ProspectQuery
from app.rules import (balance_band, classify_high_value, contact_permission, credit_band, emi_band, income_band,
                       match_products, score_conversion, transaction_insights)

NOW = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)


def customer(**changes):
    c = dict(customer_id=42, full_name='Synthetic Customer', city='Pune', occupation='SALARIED',
             monthly_income_inr=Decimal('130000'), credit_score=815,
             current_balance_inr=Decimal('240000'), account_status='ACTIVE',
             kyc_status='VERIFIED', risk_band='LOW', income_credit_months=6,
             existing_emi_to_income_ratio=Decimal('0.10'),
             has_active_personal_loan=False, has_pending_pl_application=False,
             last_pl_declined_at=None, last_pl_contact_at=None,
             pl_interest_history=True, whatsapp_opt_in=True, do_not_contact=False,
             customer_since=date(2019, 6, 1))
    c.update(changes)
    return c


def product(code='PL_PREMIUM', min_income=80000, min_score=750):
    return dict(product_id=2, product_code=code, product_name=code, active=True,
                minimum_income_inr=Decimal(min_income), minimum_credit_score=min_score,
                annual_interest_rate_pct=Decimal('11.25'), maximum_loan_amount_inr=2500000)


def test_best_score_is_explainable_not_probability():
    from fakes import TRANSACTIONS
    base = score_conversion(customer(), NOW)
    assert base.propensity_score == 85 and base.breakdown.timing == 0  # no transaction insights: no timing
    insights = transaction_insights(customer(), [t for t in TRANSACTIONS if t['customer_id'] == 42], NOW)
    result = score_conversion(customer(), NOW, insights)
    assert result.propensity_score == 100 and result.breakdown.timing == 15
    assert sum(result.breakdown.model_dump().values()) == 100
    assert 'Income up over the last 3 months' in result.reasons
    assert result.score_type == 'heuristic_not_probability'
    assert result.preliminarily_eligible and result.whatsapp_contact_permitted


@pytest.mark.parametrize('change,blocker', [
    ({'kyc_status':'EXPIRED'}, 'KYC_NOT_VERIFIED'),
    ({'risk_band':'HIGH'}, 'HIGH_RISK'),
    ({'credit_score':620}, 'CREDIT_SCORE_BELOW_680'),
    ({'monthly_income_inr':25000}, 'INCOME_BELOW_30000'),
    ({'account_status':'DORMANT'}, 'ACCOUNT_NOT_ACTIVE'),
    ({'income_credit_months':4}, 'INSUFFICIENT_INCOME_HISTORY'),
    ({'existing_emi_to_income_ratio':Decimal('0.41')}, 'EXISTING_EMI_RATIO_ABOVE_40_PERCENT'),
    ({'has_active_personal_loan':True}, 'ACTIVE_PERSONAL_LOAN'),
    ({'has_pending_pl_application':True}, 'PENDING_PERSONAL_LOAN_APPLICATION'),
    ({'last_pl_declined_at':NOW-timedelta(days=20)}, 'RECENT_PERSONAL_LOAN_DECLINE'),
])
def test_eligibility_blocks(change, blocker):
    scored = score_conversion(customer(**change), NOW)
    assert not scored.preliminarily_eligible
    assert blocker in scored.blockers


def test_consent_frequency_do_not_contact():
    for change, blocker in [
        ({'whatsapp_opt_in':False}, 'WHATSAPP_OPT_IN_MISSING'),
        ({'do_not_contact':True}, 'DO_NOT_CONTACT'),
        ({'last_pl_contact_at':NOW-timedelta(days=5)}, 'PERSONAL_LOAN_CONTACTED_WITHIN_30_DAYS'),
    ]:
        permission = contact_permission(customer(**change), NOW)
        assert not permission.whatsapp_contact_permitted
        assert blocker in permission.blockers


def test_high_value_is_distinct_from_eligibility():
    result = classify_high_value(customer(kyc_status='EXPIRED'))
    assert result.high_value
    assert not score_conversion(customer(kyc_status='EXPIRED'), NOW).preliminarily_eligible
    assert not classify_high_value(customer(current_balance_inr=99999)).high_value


def test_product_matching_enforces_product_thresholds():
    matches = match_products(customer(monthly_income_inr=60000, credit_score=710),
                             [product(), product('PL_STANDARD', 30000, 680)], NOW)
    assert matches[0].product_code == 'PL_STANDARD' and matches[0].suitable
    assert not next(p for p in matches if p.product_code == 'PL_PREMIUM').suitable
    assert 'BELOW_PRODUCT_MINIMUM_INCOME' in matches[1].blockers


def test_30_day_contact_boundary_not_permitted():
    assert not contact_permission(customer(last_pl_contact_at=NOW-timedelta(days=30)), NOW).whatsapp_contact_permitted
    assert contact_permission(customer(last_pl_contact_at=NOW-timedelta(days=31)), NOW).whatsapp_contact_permitted


@pytest.mark.parametrize('amount,band', [
    (0, '< INR 30K'), (29999, '< INR 30K'), (30000, 'INR 30K-50K'), (79999, 'INR 50K-80K'),
    (80000, 'INR 80K-1.2L'), (119999, 'INR 80K-1.2L'), (120000, 'INR 1.2L-2L'), (200000, 'INR 2L+'),
])
def test_income_band_edges_match_policy_thresholds(amount, band):
    assert income_band(Decimal(amount)) == band


@pytest.mark.parametrize('amount,band', [
    (49999, '< INR 50K'), (50000, 'INR 50K-1L'), (100000, 'INR 1L-2L'), (200000, 'INR 2L-5L'),
    (500000, 'INR 5L+'), (-1500, '< INR 50K'),
])
def test_balance_band_edges_match_policy_thresholds(amount, band):
    assert balance_band(Decimal(amount)) == band


@pytest.mark.parametrize('score,band', [
    (300, '< 650'), (649, '< 650'), (650, '650-679'), (680, '680-699'), (699, '680-699'), (700, '700-749'),
    (750, '750-799'), (799, '750-799'), (800, '800+'), (900, '800+'),
])
def test_credit_band_edges_match_policy_and_product_thresholds(score, band):
    assert credit_band(score) == band


@pytest.mark.parametrize('ratio,band', [
    ('0', '< 15%'), ('0.149', '< 15%'), ('0.15', '15-30%'), ('0.299', '15-30%'), ('0.30', '30-40%'),
    ('0.40', '30-40%'), ('0.401', '> 40%'),  # 40% exactly is still eligible, so it sits in the lower band
])
def test_emi_band_edges_match_scoring_and_eligibility_cap(ratio, band):
    assert emi_band(Decimal(ratio)) == band


def test_bands_are_none_when_value_unknown():
    assert income_band(None) is None and balance_band(None) is None
    assert credit_band(None) is None and emi_band(None) is None
    assert 'Credit score unavailable' in score_conversion(customer(credit_score=None), NOW).reasons


@pytest.mark.parametrize('model', [CustomerSearch, ProspectQuery])
def test_minimum_filters_snap_down_to_band_edges(model):
    q = model(min_income_inr=123457, min_balance_inr=234568, min_credit_score=777)
    assert (q.min_income_inr, q.min_balance_inr, q.min_credit_score) == (120000, 200000, 750)
    assert q.applied_minimums() == {'min_income_inr': 120000, 'min_balance_inr': 200000, 'min_credit_score': 750}
    exact = model(min_income_inr=80000, min_balance_inr=100000, min_credit_score=680)
    assert (exact.min_income_inr, exact.min_balance_inr, exact.min_credit_score) == (80000, 100000, 680)
    low = model(min_income_inr=25000, min_balance_inr=10, min_credit_score=600)
    assert (low.min_income_inr, low.min_balance_inr, low.min_credit_score) == (None, None, None)
    assert low.applied_minimums() == {} and model().applied_minimums() == {}


def test_nearby_probe_thresholds_return_identical_filters():
    # Binary-searching a customer's income with close thresholds gains nothing below the band.
    assert len({CustomerSearch(min_income_inr=v).min_income_inr for v in range(120000, 200000, 997)}) == 1


def test_reasons_never_carry_exact_figures():
    c = customer(monthly_income_inr=Decimal('123457'), current_balance_inr=Decimal('234568'),
                 credit_score=777, existing_emi_to_income_ratio=Decimal('0.123'))
    text = ' '.join(score_conversion(c, NOW).reasons
                    + [r for m in match_products(c, [product()], NOW) for r in m.reasons])
    assert 'INR 1.2L-2L' in text and 'INR 2L-5L' in text and 'meets product minimum INR 80,000' in text
    assert 'Credit score 750-799' in text and 'Credit score meets product minimum 750' in text
    assert 'Existing EMI/income < 15%' in text
    for exact in ('123457', '123,457', '1,23,457', '234568', '234,568', '2,34,568', '777', '12.3%', '0.123'):
        assert exact not in text


# ---- transaction insights ("this month" timing) ----

def tx(back, category, amount, direction='DEBIT', day=10):
    from fakes import month_start
    return dict(customer_id=42, transaction_at=month_start(back).replace(day=day), direction=direction,
                category=category, amount_inr=Decimal(amount))


def history(income=100000, recent_income=None, shopping=10000, recent_shopping=None):
    rows = []
    for back in range(1, 7):
        recent = back <= 3
        rows.append(tx(back, 'SALARY', recent_income if recent and recent_income else income, 'CREDIT', day=1))
        rows.append(tx(back, 'RENT', 22000))
        rows.append(tx(back, 'SHOPPING', recent_shopping if recent and recent_shopping else shopping))
    return rows


def test_flat_history_has_no_timing_points():
    i = transaction_insights(customer(), history(), NOW)
    assert (i.income_trend, i.discretionary_spend_trend, i.timing_points) == ('STABLE', 'STABLE', 0)
    assert i.income_months == 6 and i.monthly_surplus_band == '40%+' and i.timing_signals == []


def test_each_timing_signal_and_the_cap():
    assert transaction_insights(customer(), history(recent_income=106000), NOW).timing_points == 4
    assert transaction_insights(customer(), history(recent_shopping=12000), NOW).timing_points == 3
    event = transaction_insights(customer(), history() + [tx(2, 'WEDDING', 250000)], NOW)
    assert event.timing_points == 8 and event.outreach_themes == ['family celebrations']
    assert event.timing_signals == ['Wedding spend 2 months ago (2x+ monthly income)']
    full = transaction_insights(customer(), history(recent_income=120000, recent_shopping=20000)
                                + [tx(1, 'TRAVEL', 50000), tx(1, 'EDUCATION', 90000)], NOW)
    assert full.timing_points == 15 and full.outreach_themes == ['travel plans', 'education plans']


def test_caution_signals_score_nothing():
    i = transaction_insights(customer(), history(recent_income=80000, shopping=70000), NOW)
    assert i.income_trend == 'FALLING' and i.timing_points == 0 and i.monthly_surplus_band == '< 10%'
    assert 'Income down over the last 3 months (caution)' in i.timing_signals
    assert 'Monthly surplus below 10% of income (caution)' in i.timing_signals


def test_health_spending_is_ignored_entirely():
    i = transaction_insights(customer(), history() + [tx(1, 'MEDICAL', 300000)], NOW)
    assert i.recent_life_events == [] and i.timing_points == 0 and i.monthly_surplus_band == '40%+'
    assert 'medical' not in str(i.model_dump()).lower()


def test_only_the_last_six_complete_months_count():
    current_month = dict(tx(1, 'EDUCATION', 90000), transaction_at=NOW.replace(day=2))
    old = [tx(3, 'EDUCATION', 90000), tx(7, 'SALARY', 999999, 'CREDIT')]  # 3 back: not "recent"; 7 back: outside
    i = transaction_insights(customer(), history() + [current_month] + old, NOW)
    assert i.recent_life_events == [] and i.income_trend == 'STABLE'


def test_no_transactions_is_unknown_not_an_error():
    i = transaction_insights(customer(), [], NOW)
    assert (i.income_trend, i.income_months, i.monthly_surplus_band, i.timing_points) == ('UNKNOWN', 0, None, 0)
