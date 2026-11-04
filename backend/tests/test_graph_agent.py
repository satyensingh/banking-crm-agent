"""GraphChatAgent: scripted fake chat model + the real MCP server (in-memory) reached via langchain-mcp-adapters."""
import json

import pytest

pytest.importorskip('langgraph')
pytest.importorskip('langchain_mcp_adapters')

from fastmcp import Client
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_mcp_adapters.tools import load_mcp_tools

from app.graph_agent import LIMIT_TEXT, REFUSAL_TEXT, GraphChatAgent
from app.mcp_server import build_server
from app.service import CRMTools
from test_api import FakeRepo
from test_rules import NOW


class FakeChat(BaseChatModel):
    responses: list
    calls: list = []

    @property
    def _llm_type(self): return 'fake'

    def bind_tools(self, tools, **kwargs):
        self.calls.append({'tools': [getattr(t, 'name', None) or t['name'] for t in tools]})
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append({'messages': list(messages)})
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])


def use(i, name, **args): return {'id': i, 'name': name, 'args': args, 'type': 'tool_call'}
def call_msg(*calls): return AIMessage(content='', tool_calls=list(calls))
def say(t, **meta): return AIMessage(content=t, response_metadata=meta)


@pytest.fixture
async def tools():
    server = build_server(lambda: CRMTools(FakeRepo(), clock=lambda: NOW))
    async with Client(server) as client:
        yield await load_mcp_tools(client.session)


def make_agent(tools, *responses):
    model = FakeChat(responses=list(responses), calls=[])

    async def loader(): return tools
    return GraphChatAgent(model=model, tools_loader=loader), model


async def test_prospects_flow_returns_ui_shape_and_trace(tools):
    agent, model = make_agent(tools, call_msg(use('t1', 'rank_prospects', limit=5)), say('Here are 2 prospects.'))
    body = await agent.reply('s', 'top prospects')
    assert body['text'] == 'Here are 2 prospects.'
    assert body['tools'] == [{'name': 'rank_prospects', 'status': 'complete', 'args': {'limit': 5},
                              'detail': 'Rank eligible, (by default) contactable prospects by heuristic propensity score'}]
    assert [c['id'] for c in body['result']['customers']] == [42, 21]
    assert body['result']['customers'][0]['code'] == 'PL_PREMIUM'
    assert set(model.calls[0]['tools']) >= {'rank_prospects', 'save_whatsapp_drafts'}


async def test_tool_error_is_surfaced_to_model(tools):
    agent, model = make_agent(tools, call_msg(use('t1', 'score_conversion', customer_id=999)), say('Not found.'))
    body = await agent.reply('s', 'score 999')
    tool_msg = model.calls[-1]['messages'][-1]
    assert tool_msg.status == 'error' and 'NOT_FOUND' in str(tool_msg.content)
    assert body['tools'][0]['status'] == 'error' and body['result'] is None


async def test_drafts_only_for_permitted_customers(tools):
    agent, model = make_agent(
        tools, call_msg(use('t1', 'rank_prospects')),
        call_msg(use('t2', 'save_whatsapp_drafts', drafts=[{'customer_id': 42, 'content': 'Hi!'},
                                                           {'customer_id': 7, 'content': 'sneaky'}])),
        say('Drafted.'))
    body = await agent.reply('s', 'drafts')
    assert [m['customerId'] for m in body['result']['messages']] == [42]
    assert 'rejected' in str(model.calls[-1]['messages'][-1].content)


async def test_noncompliant_draft_content_is_rejected_with_reasons_then_rewrite_accepted(tools):
    agent, model = make_agent(
        tools, call_msg(use('t1', 'rank_prospects')),
        call_msg(use('t2', 'save_whatsapp_drafts', drafts=[
            {'customer_id': 42, 'content': 'You are pre-approved for Rs. 5 lakh at 10.5%! Call 9876543210'}])),
        call_msg(use('t3', 'save_whatsapp_drafts', drafts=[
            {'customer_id': 42, 'content': 'Hi, a personal loan could suit your plans. Reply to know more.'}])),
        say('Drafted.'))
    body = await agent.reply('s', 'drafts')
    from app.graph_agent import _text
    rejected = json.loads(_text(model.calls[3]['messages'][-1].content))
    reasons = ' '.join(rejected['rejected_content']['42'])
    assert rejected['saved'] == [] and 'instruction' in rejected
    assert {'PROMISE_OF_APPROVAL', 'RATE_OR_AMOUNT', 'CONTACT_OR_LINK'} <= {r.split(':')[0] for r in rejected['rejected_content']['42']}
    assert [m['content'] for m in body['result']['messages']] == [
        'Hi, a personal loan could suit your plans. Reply to know more.']
    assert body['tools'][1]['outcome']['rejected_content'] and body['tools'][2]['outcome']['saved'] == [42]


async def test_consent_does_not_leak_across_turns(tools):
    agent, _ = make_agent(
        tools, call_msg(use('t1', 'rank_prospects')), say('ranked'),
        call_msg(use('t2', 'save_whatsapp_drafts', drafts=[{'customer_id': 42, 'content': 'Hi!'}])), say('done'))
    await agent.reply('s', 'rank')
    body = await agent.reply('s', 'draft without re-checking consent')
    assert body['result'] is None


async def test_unknown_tool_and_session_memory(tools):
    agent, model = make_agent(tools, say('one'), call_msg(use('t1', 'nope')), say('two'))
    await agent.reply('s', 'first')
    await agent.reply('s', 'second')
    humans = [m.content for m in model.calls[-1]['messages'] if m.type == 'human']
    assert humans == ['first', 'second']
    assert model.calls[-1]['messages'][-1].status == 'error'
    other = await make_agent(tools, say('x'))[0].reply('other', 'hi')
    assert other['text'] == 'x'


async def test_refusal_and_tool_limit_keep_thread_valid(tools):
    agent, model = make_agent(tools, say('', stop_reason='refusal'), say('ok'))
    assert (await agent.reply('s', 'bad'))['text'] == REFUSAL_TEXT
    assert (await agent.reply('s', 'again'))['text'] == 'ok'

    loop = [call_msg(use(f't{i}', 'rank_prospects')) for i in range(8)]  # MAX_TOOL_ROUNDS
    agent, model = make_agent(tools, *loop, say('after'))
    body = await agent.reply('s', 'loop')
    assert body['text'] == LIMIT_TEXT and len(body['tools']) == 7
    assert (await agent.reply('s', 'next'))['text'] == 'after'
    # every tool call in the persisted thread was answered
    msgs = model.calls[-1]['messages']
    answered = {m.tool_call_id for m in msgs if m.type == 'tool'}
    assert {c['id'] for m in msgs if m.type == 'ai' for c in m.tool_calls} <= answered


# ---- provider configuration and the UI hook ----

async def test_missing_api_key_is_a_clean_503(monkeypatch):
    from app.graph_agent import AgentUnavailable
    for provider, var in (('anthropic', 'ANTHROPIC_API_KEY'), ('openai', 'OPENAI_API_KEY')):
        monkeypatch.setenv('LLM_PROVIDER', provider)
        for v in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'OPENAI_API_KEY'):
            monkeypatch.delenv(v, raising=False)
        with pytest.raises(AgentUnavailable) as e:
            await GraphChatAgent().reply('s', 'hi')
        assert e.value.status_code == 503 and var in str(e.value)


async def test_on_tool_hook_reports_each_call_and_survives_hook_errors(tools):
    seen = []

    async def hook(name, args, output, is_error):
        seen.append((name, args, is_error, 'prospects' in output))
        raise RuntimeError('UI exploded')

    agent, _ = make_agent(tools, call_msg(use('t1', 'rank_prospects', limit=2)), say('ok'))
    body = await agent.reply('s', 'top', on_tool=hook)
    assert body['text'] == 'ok' and seen == [('rank_prospects', {'limit': 2}, False, True)]


def test_unsupported_provider_and_unreachable_mcp(monkeypatch):
    import asyncio
    from app.graph_agent import AgentUnavailable, make_chat_model
    with pytest.raises(AgentUnavailable):
        make_chat_model('gemini')
    monkeypatch.setenv('MCP_SERVER_URL', 'http://127.0.0.1:9/mcp')
    agent = GraphChatAgent(model=FakeChat(responses=[], calls=[]))
    with pytest.raises(AgentUnavailable) as err:
        asyncio.run(agent.reply('s', 'hi'))
    assert err.value.status_code == 502


# ---- Ollama (free, local) ----

def test_ollama_model_config(monkeypatch):
    from app.graph_agent import make_chat_model
    for v in ('OLLAMA_MODEL', 'OLLAMA_BASE_URL', 'OLLAMA_NUM_CTX', 'OLLAMA_REASONING'):
        monkeypatch.delenv(v, raising=False)
    m = make_chat_model('Ollama')  # no API key, no server needed to construct
    assert (m.model, m.base_url, m.num_ctx, m.reasoning, m.temperature) == \
           ('qwen3:8b', 'http://localhost:11434', 8192, False, 0)
    monkeypatch.setenv('OLLAMA_MODEL', 'llama3.1:8b')
    monkeypatch.setenv('OLLAMA_REASONING', 'true')
    monkeypatch.setenv('OLLAMA_BASE_URL', 'http://host.docker.internal:11434')
    m = make_chat_model('ollama')
    assert (m.model, m.reasoning, m.base_url) == ('llama3.1:8b', True, 'http://host.docker.internal:11434')


async def test_ollama_down_or_model_missing_map_to_clean_errors(tools):
    import httpx
    from ollama import ResponseError
    from app.graph_agent import AgentUnavailable

    class Boom(FakeChat):
        err: Exception

        def _generate(self, *a, **k): raise self.err

    for err, status, hint in ((ConnectionError('refused'), 502, 'unreachable'),
                              (httpx.ConnectError('refused'), 502, 'unreachable'),
                              (ResponseError('model not found', 404), 503, 'ollama pull')):
        async def loader(): return tools
        agent = GraphChatAgent(model=Boom(responses=[], calls=[], err=err), tools_loader=loader)
        with pytest.raises(AgentUnavailable) as e:
            await agent.reply('s', 'hi')
        assert e.value.status_code == status and hint in str(e.value)
