"""Integration tests: real FastMCP dispatch/validation/serialisation via an in-memory Client."""
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app.mcp_server import build_server, parse_tool_error
from app.repository import DatabaseUnavailable
from app.service import CRMTools
from fakes import FakeRepo
from test_rules import NOW

EXPECTED_TOOLS = {'search_customers', 'get_customer_profile', 'classify_high_value',
                  'score_conversion', 'match_products', 'check_whatsapp_permission',
                  'rank_prospects'}


@pytest.fixture
async def client():
    server = build_server(lambda: CRMTools(FakeRepo(), clock=lambda: NOW))
    async with Client(server) as c:
        yield c


async def call_error(client, name, args):
    with pytest.raises(ToolError) as info:
        await client.call_tool(name, args)
    return info.value


async def test_exposes_exactly_seven_read_only_tools_with_schemas(client):
    tools = await client.list_tools()
    assert {t.name for t in tools} == EXPECTED_TOOLS
    for t in tools:
        assert t.annotations.readOnlyHint is True
        assert t.inputSchema['type'] == 'object'
        assert t.outputSchema and t.outputSchema['type'] == 'object', t.name


async def test_input_schema_carries_constraints(client):
    schemas = {t.name: t.inputSchema for t in await client.list_tools()}
    cid = schemas['score_conversion']['properties']['customer_id']
    assert cid['minimum'] == 1 and schemas['score_conversion']['required'] == ['customer_id']
    assert 'pattern' in str(schemas['match_products']['properties']['product_code'])
    assert schemas['search_customers']['properties']['limit']['maximum'] == 100


async def test_search_customers_returns_minimised_fields(client):
    result = await client.call_tool('search_customers', {'city': 'Pune', 'limit': 5})
    assert result.structured_content['count'] == 3
    first = result.structured_content['customers'][0]
    assert first['customer_id'] == 42
    assert not {'whatsapp_opt_in', 'do_not_contact', 'risk_band'} & first.keys()


async def test_get_customer_profile_is_minimised(client):
    result = await client.call_tool('get_customer_profile', {'customer_id': 42})
    data = result.structured_content
    assert data['customer_id'] == 42 and data['kyc_status'] == 'VERIFIED'
    assert 'whatsapp_opt_in' not in data and 'do_not_contact' not in data


async def test_classify_high_value(client):
    data = (await client.call_tool('classify_high_value', {'customer_id': 42})).structured_content
    assert data['high_value'] is True and len(data['reasons']) == 2


async def test_score_conversion(client):
    data = (await client.call_tool('score_conversion', {'customer_id': 42})).structured_content
    assert data['propensity_score'] == 100
    assert data['score_type'] == 'heuristic_not_probability'


async def test_match_products_all_and_filtered(client):
    data = (await client.call_tool('match_products', {'customer_id': 42})).structured_content
    assert data['customer_id'] == 42 and data['matches'][0]['suitable']
    one = (await client.call_tool('match_products',
                                  {'customer_id': 42, 'product_code': 'PL_STANDARD'})).structured_content
    assert [m['product_code'] for m in one['matches']] == ['PL_STANDARD']


async def test_check_whatsapp_permission(client):
    data = (await client.call_tool('check_whatsapp_permission', {'customer_id': 42})).structured_content
    assert data['whatsapp_contact_permitted'] is True and data['blockers'] == []


async def test_rank_prospects_sorted_and_excludes_weak_credit(client):
    data = (await client.call_tool('rank_prospects', {'limit': 10})).structured_content
    assert [p['customer_id'] for p in data['prospects']] == [42, 21]
    assert data['prospects'][0]['suggested_product_code'] == 'PL_PREMIUM'
    only = (await client.call_tool('rank_prospects', {'high_value_only': True})).structured_content
    assert all(p['customer_id'] in (42, 21) for p in only['prospects'])


@pytest.mark.parametrize('name,args', [
    ('score_conversion', {'customer_id': 999}),
    ('classify_high_value', {'customer_id': 999}),
    ('check_whatsapp_permission', {'customer_id': 999}),
    ('get_customer_profile', {'customer_id': 999}),
    ('match_products', {'customer_id': 42, 'product_code': 'PL_UNKNOWN'}),
    ('rank_prospects', {'product_code': 'PL_UNKNOWN'}),
])
async def test_not_found_is_structured_error(client, name, args):
    payload = parse_tool_error(str(await call_error(client, name, args)))
    assert payload.code == 'NOT_FOUND' and payload.retryable is False and payload.message


@pytest.mark.parametrize('name,args', [
    ('search_customers', {'limit': 1000}),
    ('search_customers', {'min_credit_score': 100}),
    ('search_customers', {'occupation': 'STUDENT'}),
    ('search_customers', {'min_income_inr': -1}),
    ('rank_prospects', {'min_credit_score': 999}),
    ('rank_prospects', {'offset': -1}),
    ('score_conversion', {'customer_id': 0}),
    ('score_conversion', {'customer_id': 'abc'}),
    ('score_conversion', {}),
    ('match_products', {'customer_id': 42, 'product_code': "x'; DROP TABLE"}),
])
async def test_invalid_input_rejected_before_business_logic(client, name, args):
    err = await call_error(client, name, args)
    assert str(err)


async def test_database_outage_is_retryable_structured_error():
    class DownRepo(FakeRepo):
        def get_customer(self, customer_id):
            raise DatabaseUnavailable('PostgreSQL unavailable or query failed')

    async with Client(build_server(lambda: CRMTools(DownRepo(), clock=lambda: NOW))) as c:
        payload = parse_tool_error(str(await call_error(c, 'score_conversion', {'customer_id': 42})))
    assert (payload.code, payload.retryable) == ('DATABASE_UNAVAILABLE', True)


async def test_unexpected_errors_are_masked():
    class BrokenRepo(FakeRepo):
        def get_customer(self, customer_id):
            raise RuntimeError('secret connection string postgres://u:pw@host')

    async with Client(build_server(lambda: CRMTools(BrokenRepo(), clock=lambda: NOW))) as c:
        err = str(await call_error(c, 'score_conversion', {'customer_id': 42}))
    assert parse_tool_error(err).code == 'INTERNAL_ERROR'
    assert 'secret' not in err and 'pw@' not in err


# FakeRepo's exact figures (customers 42/7: 130000 income, 240000 balance, EMI 10%; 21: 90000, 150000;
# credit 815 / 770; 7's credit 650 is a band edge, so it is not checked) in every formatting the model or UI
# might render. None may leave the tool layer: RMs see bands only.
EXACT_FIGURES = ('130000', '130,000', '1,30,000', '240000', '240,000', '2,40,000',
                 '90000', '90,000', '150000', '150,000', '1,50,000', '815', '770', '10.0%', '0.10', '0.1')
RAW_FIELDS = ('monthly_income_inr', 'current_balance_inr', 'credit_score', 'existing_emi_to_income_ratio')


@pytest.mark.parametrize('name,args', [
    ('search_customers', {}), ('get_customer_profile', {'customer_id': 21}),
    ('classify_high_value', {'customer_id': 42}), ('score_conversion', {'customer_id': 21}),
    ('match_products', {'customer_id': 42}), ('check_whatsapp_permission', {'customer_id': 42}),
    ('rank_prospects', {'contactable_only': False}),
])
async def test_no_tool_output_reveals_exact_income_or_balance(client, name, args):
    result = await client.call_tool(name, args)
    text = ' '.join(getattr(block, 'text', '') for block in result.content) + str(result.structured_content)
    for field in RAW_FIELDS:  # quoted, so policy keys such as 'min_monthly_income_inr' do not match
        assert f'"{field}"' not in text and f"'{field}'" not in text
    for exact in EXACT_FIGURES:
        assert exact not in text, f'{name} leaked {exact}'


async def test_profile_and_prospects_carry_bands(client):
    profile = (await client.call_tool('get_customer_profile', {'customer_id': 21})).structured_content
    assert (profile['income_band'], profile['credit_band'], profile['balance_band']) == \
        ('INR 80K-1.2L', '750-799', 'INR 1L-2L')
    top = (await client.call_tool('rank_prospects', {})).structured_content['prospects'][0]
    assert (top['income_band'], top['credit_band'], top['balance_band']) == ('INR 1.2L-2L', '800+', 'INR 2L-5L')


@pytest.mark.parametrize('name', ['search_customers', 'rank_prospects'])
async def test_minimum_filters_are_snapped_and_reported(name):
    seen = []

    class RecordingRepo(FakeRepo):
        def search_customers(self, filters):
            seen.append(filters); return super().search_customers(filters)

        def list_customers_for_ranking(self, filters):
            seen.append(filters); return super().list_customers_for_ranking(filters)

    async with Client(build_server(lambda: CRMTools(RecordingRepo(), clock=lambda: NOW))) as c:
        data = (await c.call_tool(name, {'min_income_inr': 123457, 'min_credit_score': 777,
                                         'min_balance_inr': 99999})).structured_content
    assert {k: float(v) for k, v in data['applied_minimums'].items()} == \
        {'min_income_inr': 120000, 'min_credit_score': 750, 'min_balance_inr': 50000}
    assert (seen[0]['min_income_inr'], seen[0]['min_credit_score'], seen[0]['min_balance_inr']) == \
        (120000, 750, 50000)
