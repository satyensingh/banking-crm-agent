"""FastAPI adapter exposing the deterministic CRM tools as REST. The chat UI is Chainlit (chainlit_app.py)."""
from __future__ import annotations
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from .models import CustomerSearch, ProspectQuery
from .deps import get_tools
from .repository import DatabaseUnavailable
from .service import CRMTools, CustomerNotFound, ProductNotFound

app = FastAPI(title='Banking CRM Deterministic Tools', version='1.0.0',
              description='Read-only, explainable business tools for an agentic banking CRM demo.')


@app.exception_handler(CustomerNotFound)
async def handle_customer_not_found(request, exc):
    return JSONResponse(status_code=404, content={'detail': str(exc)})


@app.exception_handler(ProductNotFound)
async def handle_product_not_found(request, exc):
    return JSONResponse(status_code=404, content={'detail': str(exc)})


@app.exception_handler(DatabaseUnavailable)
async def handle_database_unavailable(request, exc):
    return JSONResponse(status_code=503, content={'detail': str(exc)})


@app.get('/health')
def health(tools: CRMTools = Depends(get_tools)):
    return {'status': 'ok' if tools.repo.ping() else 'unavailable'}


@app.post('/api/tools/customers/search')
def search_customers(criteria: CustomerSearch, tools: CRMTools = Depends(get_tools)):
    return {'customers': tools.search_customers(criteria)}


@app.get('/api/tools/customers/{customer_id}/classification')
def classify(customer_id: int, tools: CRMTools = Depends(get_tools)):
    return tools.classify_high_value(customer_id)


@app.get('/api/tools/customers/{customer_id}/score')
def score(customer_id: int, tools: CRMTools = Depends(get_tools)):
    return tools.score_conversion(customer_id)


@app.get('/api/tools/customers/{customer_id}/products')
def products(customer_id: int, product_code: str | None = None,
             tools: CRMTools = Depends(get_tools)):
    return {'matches': tools.match_products(customer_id, product_code)}


@app.get('/api/tools/customers/{customer_id}/whatsapp-permission')
def whatsapp_permission(customer_id: int, tools: CRMTools = Depends(get_tools)):
    return tools.check_whatsapp_permission(customer_id)


@app.post('/api/tools/prospects/rank')
def rank(criteria: ProspectQuery, tools: CRMTools = Depends(get_tools)):
    return tools.rank_prospects(criteria)
