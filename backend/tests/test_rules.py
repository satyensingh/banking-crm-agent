from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from app.rules import classify_high_value, contact_permission, match_products, score_conversion

NOW = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)


def customer(**changes):
    c = dict(customer_id=42, full_name='Synthetic Customer', city='Pune', occupation='SALARIED',
             monthly_income_inr=Decimal('130000'), credit_score=815,
             current_balance_inr=Decimal('240000'), account_status='ACTIVE',
             kyc_status='VERIFIED', risk_band='LOW', income_credit_months=6,
             existing_emi_to_income_ratio=Decimal('0.10'),
             has_active_personal_loan=False, has_pending_pl_application=False,
             last_pl_declined_at=None, last_pl_contact_at=None,
             pl_interest_history=True, whatsapp_opt_in=True, do_not_contact=False)
    c.update(changes)
    return c


def product(code='PL_PREMIUM', min_income=80000, min_score=750):
    return dict(product_id=2, product_code=code, product_name=code, active=True,
                minimum_income_inr=Decimal(min_income), minimum_credit_score=min_score,
                annual_interest_rate_pct=Decimal('11.25'), maximum_loan_amount_inr=2500000)


def test_best_score_is_explainable_not_probability():
    result = score_conversion(customer(), NOW)
    assert result.propensity_score == 100
    assert sum(result.breakdown.model_dump().values()) == 100
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
