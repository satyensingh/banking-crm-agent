from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field


class CustomerSearch(BaseModel):
    city: str | None = Field(default=None, max_length=100)
    min_income_inr: Decimal | None = Field(default=None, ge=0)
    min_credit_score: int | None = Field(default=None, ge=300, le=900)
    min_balance_inr: Decimal | None = Field(default=None, ge=0)
    occupation: Literal['SALARIED', 'SELF_EMPLOYED'] | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)


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
    monthly_income_inr: Decimal
    credit_score: int | None
    current_balance_inr: Decimal
    propensity_score: int
    suggested_product_code: str | None
    reason: str
    preliminarily_eligible: bool
    whatsapp_contact_permitted: bool


class ProspectResponse(BaseModel):
    total_returned: int
    prospects: list[Prospect]
    explanation: str = 'Heuristic ranking only; scores are NOT conversion probabilities.'


class ContactPermission(BaseModel):
    customer_id: int
    whatsapp_contact_permitted: bool
    blockers: list[str]
    checked_at: datetime


class CustomerSummary(BaseModel):
    """PII-minimised customer view (no phone/email/address/consent flags)."""
    customer_id: int
    full_name: str
    city: str | None = None
    occupation: str | None = None
    monthly_income_inr: Decimal | None = None
    credit_score: int | None = None
    current_balance_inr: Decimal | None = None
    account_status: str | None = None
    kyc_status: str | None = None


class CustomerSearchResponse(BaseModel):
    count: int
    customers: list[CustomerSummary]


class ProductMatchResponse(BaseModel):
    customer_id: int
    matches: list[ProductMatch]


class ToolErrorPayload(BaseModel):
    """Shape of the JSON carried in every MCP tool error message."""
    code: Literal['NOT_FOUND', 'DATABASE_UNAVAILABLE', 'INTERNAL_ERROR', 'INVALID_INPUT']
    message: str
    retryable: bool
