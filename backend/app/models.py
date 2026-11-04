from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field, field_validator
from .bands import BALANCE_EDGES, CREDIT_EDGES, INCOME_EDGES, snap_down

_FILTER_EDGES = {'min_income_inr': INCOME_EDGES, 'min_balance_inr': BALANCE_EDGES,
                 'min_credit_score': CREDIT_EDGES}


class CustomerSearch(BaseModel):
    city: str | None = Field(default=None, max_length=100)
    min_income_inr: Decimal | None = Field(default=None, ge=0)
    min_credit_score: int | None = Field(default=None, ge=300, le=900)
    min_balance_inr: Decimal | None = Field(default=None, ge=0)
    occupation: Literal['SALARIED', 'SELF_EMPLOYED'] | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)

    @field_validator(*_FILTER_EDGES, mode='after')
    @classmethod
    def _snap_to_band_edge(cls, value, info):
        # Snapped down to a band edge so repeated nearby thresholds cannot narrow a figure (see bands.py).
        return snap_down(value, _FILTER_EDGES[info.field_name])

    def applied_minimums(self) -> dict:
        """The minimum filters actually used, after snapping, so the RM can be told what was searched."""
        return {k: getattr(self, k) for k in _FILTER_EDGES if getattr(self, k) is not None}


class ProspectQuery(CustomerSearch):
    product_code: str | None = None
    high_value_only: bool = False
    contactable_only: bool = True


class ScoreBreakdown(BaseModel):
    """Points per factor (max): income 20, credit 20, balance 15, emi 15, interest 10, recency 5, timing 15."""
    income: int
    credit: int
    balance: int
    emi: int
    interest: int
    recency: int
    timing: int = 0  # "this month" signals from transactions (TransactionInsights)


Trend = Literal['RISING', 'STABLE', 'FALLING', 'UNKNOWN']


class LifeEvent(BaseModel):
    category: Literal['EDUCATION', 'TRAVEL', 'HOME_IMPROVEMENT', 'WEDDING']  # health spending is never used
    month: str  # YYYY-MM
    size_vs_monthly_income: str  # a band, e.g. '1-2x monthly income'; never the amount


class TransactionInsights(BaseModel):
    """Behaviour over the last 6 complete months, as trends and bands only (no amounts)."""
    customer_id: int
    months_analyzed: int
    income_months: int
    income_trend: Trend  # latest 3 months vs the 3 before (+/-5%)
    discretionary_spend_trend: Trend  # shopping, latest 3 months vs the 3 before (+/-15%)
    monthly_surplus_band: str | None  # (income - debits) / income
    recent_life_events: list[LifeEvent]  # one-off spends in the last 2 complete months (medical excluded)
    timing_signals: list[str]  # why now is (or is not) a good month to reach out
    timing_points: int  # 0-15, the score's timing component
    outreach_themes: list[str]  # neutral themes a draft may mention in general terms


class Classification(BaseModel):
    customer_id: int
    high_value: bool
    reasons: list[str]
    criteria: dict[str, str | int | float]


class Scoring(BaseModel):
    customer_id: int
    propensity_score: int
    score_type: Literal['heuristic_not_probability'] = 'heuristic_not_probability'
    breakdown: ScoreBreakdown
    reasons: list[str]
    blockers: list[str]
    preliminarily_eligible: bool
    whatsapp_contact_permitted: bool


class ProductMatch(BaseModel):
    customer_id: int
    product_id: int
    product_code: str
    product_name: str
    suitable: bool
    reasons: list[str]
    blockers: list[str]
    maximum_loan_amount_inr: Decimal | None = None
    annual_interest_rate_pct: Decimal | None = None
    disclaimer: str = 'Preliminary suitability only; not a credit decision or approved offer.'


class Prospect(BaseModel):
    customer_id: int
    full_name: str
    city: str
    occupation: str | None = None
    tenure_years: int | None = None  # years as a customer
    income_band: str  # bands only: RMs must never see exact figures (bands.py)
    credit_band: str | None
    balance_band: str
    propensity_score: int
    suggested_product_code: str | None
    reason: str
    timing_signals: list[str] = []
    outreach_themes: list[str] = []
    preliminarily_eligible: bool
    whatsapp_contact_permitted: bool


class ProspectResponse(BaseModel):
    total_returned: int
    prospects: list[Prospect]
    applied_minimums: dict[str, Decimal | int] = {}
    explanation: str = 'Heuristic ranking only; scores are NOT conversion probabilities.'


class ContactPermission(BaseModel):
    customer_id: int
    whatsapp_contact_permitted: bool
    blockers: list[str]
    checked_at: datetime


class CustomerSummary(BaseModel):
    """PII-minimised customer view (no phone/email/address/consent flags; income, credit score and balance
    as bands only)."""
    customer_id: int
    full_name: str
    city: str | None = None
    occupation: str | None = None
    income_band: str | None = None
    credit_band: str | None = None
    balance_band: str | None = None
    account_status: str | None = None
    kyc_status: str | None = None


class CustomerSearchResponse(BaseModel):
    count: int
    customers: list[CustomerSummary]
    applied_minimums: dict[str, Decimal | int] = {}


class ProductMatchResponse(BaseModel):
    customer_id: int
    matches: list[ProductMatch]


class ToolErrorPayload(BaseModel):
    """Shape of the JSON carried in every MCP tool error message."""
    code: Literal['NOT_FOUND', 'DATABASE_UNAVAILABLE', 'INTERNAL_ERROR', 'INVALID_INPUT']
    message: str
    retryable: bool
