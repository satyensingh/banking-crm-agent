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
    income: int
    credit: int
    balance: int
    emi: int
    interest: int
    recency: int


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
    income_band: str  # bands only: RMs must never see exact figures (bands.py)
    credit_band: str | None
    balance_band: str
    propensity_score: int
    suggested_product_code: str | None
    reason: str
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
