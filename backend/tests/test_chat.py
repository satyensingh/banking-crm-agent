"""/api/chat integration: scripted fake Claude + real MCP server (in-process) + fake repository."""
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from app.agent import ChatAgent
from app.llm import AnthropicProvider, OpenAIProvider
from app.main import app, get_agent
from app.mcp_server import build_server
from app.service import CRMTools
from test_api import FakeRepo
from test_rules import NOW


def text(t): return NS(type='text', text=t)
def use(i, name, **inp): return NS(type='tool_use', id=i, name=name, input=inp)
def resp(stop, *blocks): return NS(stop_reason=stop, content=list(blocks))


class FakeClaude:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []
        self.messages = self

    async def create(self, **kwargs):
        self.calls.append({**kwargs, 'messages': list(kwargs['messages'])})
        return self.responses.pop(0)


def make_client(fake):
    server = lambda: build_server(lambda: CRMTools(FakeRepo(), clock=lambda: NOW))
    app.dependency_overrides[get_agent] = lambda: ChatAgent(AnthropicProvider(client=fake), server_factory=server)
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_prospects_flow_returns_ui_shape_and_trace():
    fake = FakeClaude(resp('tool_use', use('t1', 'rank_prospects', limit=5)),
                      resp('end_turn', text('Here are 2 prospects.')))
    body = make_client(fake).post('/api/chat', json={'sessionId': 's', 'message': 'top prospects'}).json()
    assert body['text'] == 'Here are 2 prospects.'
    assert body['tools'] == [{'name': 'rank_prospects', 'status': 'complete',
                              'detail': 'Rank eligible, (by default) contactable prospects by heuristic propensity score'}]
    assert [c['id'] for c in body['result']['customers']] == [42, 21]
    assert body['result']['customers'][0]['code'] == 'PL_PREMIUM'
    assert fake.calls[0]['model'] == 'claude-sonnet-5-5'
    assert {t['name'] for t in fake.calls[0]['tools']} >= {'rank_prospects', 'save_whatsapp_drafts'}
    assert 'tool_choice' not in fake.calls[0]


def test_tool_error_is_returned_to_model_as_is_error():
    fake = FakeClaude(resp('tool_use', use('t1', 'score_conversion', customer_id=999)),
                      resp('end_turn', text('Customer not found.')))
    body = make_client(fake).post('/api/chat', json={'sessionId': 's', 'message': 'score 999'}).json()
    block = fake.calls[1]['messages'][-1]['content'][0]
    assert block['is_error'] is True and 'NOT_FOUND' in block['content']
    assert body['tools'][0]['status'] == 'error' and body['result'] is None


def test_drafts_only_for_permitted_customers():
    fake = FakeClaude(
        resp('tool_use', use('t1', 'rank_prospects')),
        resp('tool_use', use('t2', 'save_whatsapp_drafts', drafts=[
            {'customer_id': 42, 'content': 'Hi!'}, {'customer_id': 7, 'content': 'sneaky'}])),
        resp('end_turn', text('Drafted.')))
    body = make_client(fake).post('/api/chat', json={'sessionId': 's', 'message': 'drafts'}).json()
    assert [m['customerId'] for m in body['result']['messages']] == [42]
    assert 'rejected' in fake.calls[2]['messages'][-1]['content'][0]['content']


def test_session_history_is_kept_and_unknown_tool_handled():
    fake = FakeClaude(resp('end_turn', text('one')),
                      resp('tool_use', use('t1', 'nope')), resp('end_turn', text('two')))
    client = make_client(fake)
    client.post('/api/chat', json={'sessionId': 's', 'message': 'first'})
    # ChatAgent is rebuilt per override call; reuse one instance to check memory
    agent = ChatAgent(AnthropicProvider(client=fake), server_factory=lambda: build_server(lambda: CRMTools(FakeRepo(), clock=lambda: NOW)))
    app.dependency_overrides[get_agent] = lambda: agent
    fake.responses = [resp('end_turn', text('one')), resp('tool_use', use('t1', 'nope')), resp('end_turn', text('two'))]
    client.post('/api/chat', json={'sessionId': 's', 'message': 'first'})
    client.post('/api/chat', json={'sessionId': 's', 'message': 'second'})
    msgs = fake.calls[-1]['messages']
    assert msgs[0]['content'] == 'first' and msgs[1]['content'] == 'one' and msgs[2]['content'] == 'second'


def test_validation_and_missing_api_key(monkeypatch):
    client = TestClient(app)
    assert client.post('/api/chat', json={'sessionId': 's', 'message': ''}).status_code == 422
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('ANTHROPIC_AUTH_TOKEN', raising=False)
    app.dependency_overrides[get_agent] = lambda: ChatAgent(AnthropicProvider(), server_factory=lambda: build_server(lambda: None))
    r = client.post('/api/chat', json={'sessionId': 's', 'message': 'hi'})
    assert r.status_code == 503 and 'ANTHROPIC_API_KEY' in r.json()['detail']


# ---- OpenAI (Responses API) ----

def o_text(t): return NS(type='message', content=[NS(type='output_text', text=t)])
def o_call(i, name, args): return NS(type='function_call', call_id=i, name=name, arguments=args)
def o_resp(*items, status='completed'): return NS(output=list(items), status=status, incomplete_details=None)


class FakeOpenAI:
    def __init__(self, *responses):
        self.responses_list, self.calls = list(responses), []
        self.responses = self

    async def create(self, **kwargs):
        self.calls.append({**kwargs, 'input': list(kwargs['input'])})
        return self.responses_list.pop(0)


def make_openai_client(fake):
    server = lambda: build_server(lambda: CRMTools(FakeRepo(), clock=lambda: NOW))
    app.dependency_overrides[get_agent] = lambda: ChatAgent(OpenAIProvider(client=fake), server_factory=server)
    return TestClient(app)


def test_openai_tool_loop_uses_responses_api_and_function_call_output():
    fake = FakeOpenAI(o_resp(o_call('c1', 'rank_prospects', '{"limit": 5}')),
                      o_resp(o_text('Two prospects.')))
    body = make_openai_client(fake).post('/api/chat', json={'sessionId': 's', 'message': 'top'}).json()
    assert body['text'] == 'Two prospects.'
    assert [c['id'] for c in body['result']['customers']] == [42, 21]
    first, second = fake.calls
    assert first['model'] == 'gpt-5' and first['store'] is False
    assert first['tools'][0]['type'] == 'function' and 'parameters' in first['tools'][0]
    assert {t['name'] for t in first['tools']} >= {'rank_prospects', 'save_whatsapp_drafts'}
    outputs = [i for i in second['input'] if isinstance(i, dict) and i.get('type') == 'function_call_output']
    assert outputs and outputs[0]['call_id'] == 'c1'


def test_openai_invalid_json_args_and_tool_errors_reach_model():
    fake = FakeOpenAI(o_resp(o_call('c1', 'score_conversion', '{not json')),
                      o_resp(o_call('c2', 'score_conversion', '{"customer_id": 999}')),
                      o_resp(o_text('done')))
    body = make_openai_client(fake).post('/api/chat', json={'sessionId': 's', 'message': 'x'}).json()
    outs = [i['output'] for c in fake.calls for i in c['input']
            if isinstance(i, dict) and i.get('type') == 'function_call_output']
    assert any('INVALID_INPUT' in o for o in outs) and any('NOT_FOUND' in o for o in outs)
    assert [t['status'] for t in body['tools']] == ['error', 'error']


def test_openai_missing_key_and_bad_provider(monkeypatch):
    from app.llm import make_provider, AgentUnavailable
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    client = TestClient(app)
    app.dependency_overrides[get_agent] = lambda: ChatAgent(OpenAIProvider(), server_factory=lambda: build_server(lambda: None))
    r = client.post('/api/chat', json={'sessionId': 's', 'message': 'hi'})
    assert r.status_code == 503 and 'OPENAI_API_KEY' in r.json()['detail']
    with pytest.raises(AgentUnavailable):
        make_provider('gemini')
    assert make_provider('OpenAI').name == 'openai' and make_provider('anthropic').model == 'claude-sonnet-5-5'
