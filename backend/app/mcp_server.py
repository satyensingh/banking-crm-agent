"""FastMCP server exposing the seven deterministic CRM capabilities as read-only MCP tools.

Run over stdio:            python -m app.mcp_server
Run over streamable HTTP:  MCP_TRANSPORT=http python -m app.mcp_server   (port MCP_PORT, default 8001)
"""
import functools
import json
import logging
import os
from typing import Annotated, Callable, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from .deps import get_tools
from .models import (Classification, ContactPermission, CustomerSearch, CustomerSearchResponse,
                     CustomerSummary, ProductMatchResponse, ProspectQuery, ProspectResponse,
                     Scoring, ToolErrorPayload)
from .repository import DatabaseUnavailable
from .service import CRMTools, CustomerNotFound, ProductNotFound

log = logging.getLogger('banking_crm.mcp')

CustomerId = Annotated[int, Field(ge=1, le=2_147_483_647, description='Numeric customer ID')]
ProductCode = Annotated[str, Field(pattern=r'^[A-Z][A-Z0-9_]{1,49}$',
                                   description='Product code, e.g. PL_PREMIUM')]
City = Annotated[str, Field(min_length=1, max_length=100, description='City (case-insensitive match)')]
Income = Annotated[float, Field(ge=0, description='Minimum monthly income in INR')]
Balance = Annotated[float, Field(ge=0, description='Minimum current balance in INR')]
CreditScore = Annotated[int, Field(ge=300, le=900, description='Minimum credit score')]
Occupation = Literal['SALARIED', 'SELF_EMPLOYED']
Limit = Annotated[int, Field(ge=1, le=100, description='Page size')]
Offset = Annotated[int, Field(ge=0, le=10000, description='Rows to skip')]

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                            idempotentHint=True, openWorldHint=False)


def tool_error(code: str, message: str, retryable: bool = False) -> ToolError:
    payload = ToolErrorPayload(code=code, message=message, retryable=retryable)
    return ToolError(payload.model_dump_json())


def parse_tool_error(message: str) -> ToolErrorPayload:
    return ToolErrorPayload.model_validate(json.loads(message))


def _structured_errors(fn: Callable) -> Callable:
    """Translate domain failures into ToolError carrying a ToolErrorPayload JSON document."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except (CustomerNotFound, ProductNotFound) as exc:
            raise tool_error('NOT_FOUND', str(exc)) from exc
        except DatabaseUnavailable as exc:
            raise tool_error('DATABASE_UNAVAILABLE', str(exc), retryable=True) from exc
        except ValidationError as exc:
            raise tool_error('INVALID_INPUT', '; '.join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())) from exc
        except Exception as exc:  # never leak internals to the model
            log.exception('Unhandled error in MCP tool %s', fn.__name__)
            raise tool_error('INTERNAL_ERROR', 'Unexpected server error') from exc
    return wrapper


def build_server(tools_provider: Callable[[], CRMTools] = get_tools) -> FastMCP:
    mcp = FastMCP(
        'banking-crm-tools',
        instructions=('Read-only, deterministic banking CRM tools. Scores are heuristics, not '
                      'probabilities; product matches are preliminary suitability, not credit '
                      'decisions. Errors are JSON: {code, message, retryable}.'),
    )

    def tool(fn):
        return mcp.tool(annotations=READ_ONLY)(_structured_errors(fn))

    @tool
    def search_customers(
        city: City | None = None, min_income_inr: Income | None = None,
        min_credit_score: CreditScore | None = None, min_balance_inr: Balance | None = None,
        occupation: Occupation | None = None, limit: Limit = 20, offset: Offset = 0,
    ) -> CustomerSearchResponse:
        """Search customers by city, income, credit score, balance or occupation (paginated)."""
        criteria = CustomerSearch(city=city, min_income_inr=min_income_inr,
                                  min_credit_score=min_credit_score, min_balance_inr=min_balance_inr,
                                  occupation=occupation, limit=limit, offset=offset)
        rows = tools_provider().search_customers(criteria)
        return CustomerSearchResponse(count=len(rows), customers=rows)

    @tool
    def get_customer_profile(customer_id: CustomerId) -> CustomerSummary:
        """Get one customer's minimised profile (no contact details or consent data)."""
        return CustomerSummary(**tools_provider().customer_profile(customer_id))

    @tool
    def classify_high_value(customer_id: CustomerId) -> Classification:
        """Classify a customer as high-value (income >= 80k and balance >= 100k INR)."""
        return tools_provider().classify_high_value(customer_id)

    @tool
    def score_conversion(customer_id: CustomerId) -> Scoring:
        """Explainable 0-100 personal-loan propensity heuristic with blockers (not a probability)."""
        return tools_provider().score_conversion(customer_id)

    @tool
    def match_products(customer_id: CustomerId,
                       product_code: ProductCode | None = None) -> ProductMatchResponse:
        """Preliminary product suitability for a customer, optionally for one product code."""
        return ProductMatchResponse(customer_id=customer_id,
                                    matches=tools_provider().match_products(customer_id, product_code))

    @tool
    def check_whatsapp_permission(customer_id: CustomerId) -> ContactPermission:
        """Check whether the customer may be contacted on WhatsApp (consent, DND, recency)."""
        return tools_provider().check_whatsapp_permission(customer_id)

    @tool
    def rank_prospects(
        city: City | None = None, min_income_inr: Income | None = None,
        min_credit_score: CreditScore | None = None, min_balance_inr: Balance | None = None,
        occupation: Occupation | None = None, product_code: ProductCode | None = None,
        high_value_only: bool = False, contactable_only: bool = True,
        limit: Limit = 20, offset: Offset = 0,
    ) -> ProspectResponse:
        """Rank eligible, (by default) contactable prospects by heuristic propensity score."""
        query = ProspectQuery(city=city, min_income_inr=min_income_inr,
                              min_credit_score=min_credit_score, min_balance_inr=min_balance_inr,
                              occupation=occupation, product_code=product_code,
                              high_value_only=high_value_only, contactable_only=contactable_only,
                              limit=limit, offset=offset)
        return tools_provider().rank_prospects(query)

    return mcp


mcp = build_server()

if __name__ == '__main__':
    if os.getenv('MCP_TRANSPORT', 'stdio') == 'http':
        mcp.run(transport='http', host='0.0.0.0', port=int(os.getenv('MCP_PORT', '8001')))
    else:
        mcp.run()
