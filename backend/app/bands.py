"""Coarse bands for sensitive customer figures. RMs must never see an exact income, balance, credit score
or EMI-to-income ratio.

Policy code (rules.py) uses the raw values; everything that leaves the service (tool output -> LLM, UI,
audit log) carries only these bands. Band edges line up with the scoring, eligibility and seeded product
thresholds, so a band never hides why a rule fired.

Search filters on these figures are snapped DOWN to a band edge (see snap_down), so repeated searches
with nearby thresholds cannot be used to narrow a customer's figure below its band.
"""
from __future__ import annotations
from decimal import Decimal
from typing import Any

INCOME_EDGES = (30000, 50000, 80000, 120000, 200000)
BALANCE_EDGES = (50000, 100000, 200000, 500000)
CREDIT_EDGES = (650, 680, 700, 750, 800)


def _amount(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _band(value: Any, edges: tuple, labels: tuple) -> str | None:
    """labels[i] covers [edges[i-1], edges[i]); labels[0] is below the first edge, labels[-1] the top."""
    if value is None:
        return None
    amount = _amount(value)
    return next((labels[i] for i, edge in enumerate(edges) if amount < edge), labels[-1])


def income_band(value: Any) -> str | None:
    """Monthly income band, e.g. 'INR 80K-1.2L' (None when unknown)."""
    return _band(value, INCOME_EDGES, ('< INR 30K', 'INR 30K-50K', 'INR 50K-80K', 'INR 80K-1.2L',
                                       'INR 1.2L-2L', 'INR 2L+'))


def balance_band(value: Any) -> str | None:
    """Current balance band, e.g. 'INR 1L-2L' (None when unknown)."""
    return _band(value, BALANCE_EDGES, ('< INR 50K', 'INR 50K-1L', 'INR 1L-2L', 'INR 2L-5L', 'INR 5L+'))


def credit_band(value: Any) -> str | None:
    """Credit score band, e.g. '750-799' (None when there is no score)."""
    return _band(value, CREDIT_EDGES, ('< 650', '650-679', '680-699', '700-749', '750-799', '800+'))


def emi_band(value: Any) -> str | None:
    """Existing EMI-to-income ratio band. Edges follow the scoring (<15%, <30%) and the 40% eligibility cap,
    which is inclusive (exactly 40% is still eligible), hence '30-40%' and '> 40%'."""
    if value is None:
        return None
    ratio = _amount(value)
    if ratio < Decimal('0.15'):
        return '< 15%'
    if ratio < Decimal('0.30'):
        return '15-30%'
    return '30-40%' if ratio <= Decimal('0.40') else '> 40%'


def surplus_band(ratio: Any) -> str | None:
    """Share of income left after all debits, (income - debits) / income."""
    if ratio is None:
        return None
    r = _amount(ratio)
    return '< 10%' if r < Decimal('0.10') else '10-25%' if r < Decimal('0.25') else \
        '25-40%' if r < Decimal('0.40') else '40%+'


def multiple_band(ratio: Any) -> str:
    """A one-off amount relative to monthly income, e.g. '1-2x monthly income'."""
    r = _amount(ratio)
    return '< 1x monthly income' if r < 1 else '1-2x monthly income' if r < 2 else '2x+ monthly income'


def snap_down(value: Any, edges: tuple):
    """Round a minimum filter down to the nearest band edge; below the lowest edge means no filter (None).
    Rounding down keeps results a superset of what was asked, never hiding an eligible customer."""
    if value is None:
        return None
    amount = _amount(value)
    lower = [edge for edge in edges if edge <= amount]
    return lower[-1] if lower else None
