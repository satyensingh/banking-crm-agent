"""LangGraph chat agent. An LLM (Anthropic or OpenAI) drives the CRM tools, which are reached through an
MCP *client* (langchain-mcp-adapters) talking to the MCP server over streamable HTTP.

`await reply(session_id, message) -> {text, tools, result}` where `result` is the UI prospect/draft shape.

    START -> agent --(tool calls)--> tools -> agent ... -> END
                 \\--(round limit)--> limit -> END

Conversation memory is a LangGraph checkpointer keyed by thread_id=session_id. Per-turn bookkeeping
(consent set, prospects, drafts, trace) lives in graph state and is reset at the start of every turn.

Needs: MCP server running with MCP_TRANSPORT=http (see mcp_server.py) and MCP_SERVER_URL pointing at it.
"""
import asyncio
import contextvars
import json
import logging
import os
from typing import Any, Awaitable, Callable

from .guardrails import check_draft

log = logging.getLogger('banking_crm.graph_agent')

DEFAULT_MCP_URL = 'http://127.0.0.1:8001/mcp'
DEFAULT_MODELS = {'anthropic': 'claude-sonnet-5-5', 'openai': 'gpt-5', 'ollama': 'qwen3:8b'}
MAX_TOOL_ROUNDS = 8

# Optional per-request UI hook: `async (name, args, output, is_error) -> None`, awaited after every tool call.
# A ContextVar (not graph config) so the callable never reaches the checkpointer.
ToolHook = Callable[[str, dict, str, bool], Awaitable[None]]
_on_tool: contextvars.ContextVar[ToolHook | None] = contextvars.ContextVar('on_tool', default=None)
MAX_HISTORY = 20
LIMIT_TEXT = 'I could not finish within the tool-call limit. Please narrow the request.'
REFUSAL_TEXT = 'I cannot help with that request.'

SYSTEM_PROMPT = """You are a banking relationship-manager (RM) assistant for personal-loan outreach.
Use the provided tools for every fact about customers, eligibility, scores and consent; never invent
customer data. Customer income, balance, credit score and EMI-to-income ratio are only available as
bands (e.g. "INR 80K-1.2L", "750-799", "15-30%"); never estimate, narrow down or guess an exact figure.
"Likely to convert this month" comes from the score's timing points: get_transaction_insights (and
each prospect's timing_signals) shows the recent life-event spends and income/spending trends behind it.
Mention caution signals (falling income, thin surplus) to the RM rather than hiding them.
Minimum search filters are rounded down to a band edge: when applied_minimums differs from what the RM
asked for, tell them the threshold actually used. Scores are heuristics, not probabilities, and product matches are preliminary
suitability, not credit decisions or offers - say so when relevant.
Only customers with WhatsApp contact permission may be given a WhatsApp draft. When the RM asks for
WhatsApp messages, write a short, warm, compliant draft per customer and record them with
save_whatsapp_drafts. Personalise each draft from that customer's tool data: first name, city,
occupation, years with the bank (tenure_years), the suggested product, and at most one of its
outreach_themes phrased as a general possibility ("if you have education plans coming up"). Never reveal
that the bank looked at their transactions: no "we noticed", no spends, purchases, payments, salary or
dates. Never mention health or medical matters. Every draft must: stay under 600 characters; never promise or imply approval
(no "guaranteed", "pre-approved", "approved", "assured", "instant approval"); never state interest
rates, loan amounts or EMI figures; contain no links, email addresses or phone numbers. Invite the
customer to reply or speak with their RM instead. If a draft is rejected, rewrite it to fix the stated
reason. Drafts are for RM review; nothing is ever sent. Keep replies concise and do not repeat tables
the UI already shows."""

DRAFT_TOOL = {
    'name': 'save_whatsapp_drafts',
    'description': ('Record WhatsApp draft messages for RM review. Nothing is sent. Only customers '
                    'whose WhatsApp permission was confirmed by a tool this turn are accepted, and each '
                    'draft must pass the content rules (no approval promises, rates, amounts, EMI figures, '
                    'links or contact details; max 600 characters). Rejected drafts come back with reasons.'),
    'input_schema': {
        'type': 'object',
        'properties': {'drafts': {'type': 'array', 'minItems': 1, 'maxItems': 20, 'items': {
            'type': 'object',
            'properties': {'customer_id': {'type': 'integer', 'minimum': 1},
                           'content': {'type': 'string', 'minLength': 1, 'maxLength': 1000}},
            'required': ['customer_id', 'content'], 'additionalProperties': False}}},
        'required': ['drafts'], 'additionalProperties': False},
}


class AgentUnavailable(RuntimeError):
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


def _initials(name: str) -> str:
    return ''.join(p[0] for p in name.split()[:2]).upper()


def _ui_customer(p: dict) -> dict:
    code = p.get('suggested_product_code') or ''
    return {'id': p['customer_id'], 'name': p['full_name'], 'initials': _initials(p['full_name']),
            'city': p['city'], 'score': p['propensity_score'], 'income': p['income_band'],
            'credit': p['credit_band'], 'balance': p['balance_band'],
            'product': code.replace('_', ' ').title(), 'code': code, 'reason': p['reason'],
            'timing': p.get('timing_signals', []), 'themes': p.get('outreach_themes', []),
            'occupation': p.get('occupation'), 'tenure': p.get('tenure_years'),
            'contacted': 'n/a', 'consent': p['whatsapp_contact_permitted']}


def _save_drafts(args: dict, state: dict) -> tuple[str, bool]:
    """Two deterministic guards, both must pass:
    consent - WhatsApp permission confirmed by a tool this turn; content - guardrails.check_draft()."""
    saved, no_consent, bad_content = [], [], {}
    for d in args.get('drafts', []) if isinstance(args, dict) else []:
        try:
            cid, content = int(d['customer_id']), str(d['content']).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if cid not in state['permitted'] or not content:
            no_consent.append(cid)
        elif problems := check_draft(content):
            bad_content[str(cid)] = problems
        else:
            state['drafts'][cid] = content
            saved.append(cid)
    result = {'saved': saved, 'rejected_no_confirmed_whatsapp_permission': no_consent,
              'rejected_content': bad_content}
    if bad_content:
        result['instruction'] = 'Rewrite the rejected drafts to fix every listed reason, then save them again.'
    return json.dumps(result), False


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return '\n'.join(b.get('text', '') if isinstance(b, dict) else str(b) for b in content)


def _error_message(call: dict, payload: dict):
    from langchain_core.messages import ToolMessage
    return ToolMessage(content=json.dumps({'retryable': False, **payload}), tool_call_id=call['id'],
                       name=call['name'], status='error')


def _unavailable(exc: Exception) -> AgentUnavailable | None:
    """Map provider SDK failures to AgentUnavailable with a user-facing status; None = not an SDK error."""
    import httpx
    if isinstance(exc, (ConnectionError, httpx.ConnectError)):  # e.g. Ollama server not running
        return AgentUnavailable('The AI model server is unreachable', 502)
    if type(exc).__module__.split('.')[0] == 'ollama' and getattr(exc, 'status_code', None) == 404:
        return AgentUnavailable('The Ollama model is not installed (run `ollama pull <model>`)', 503)
    if type(exc).__module__.split('.')[0] not in ('anthropic', 'openai', 'ollama'):
        return None
    kind = type(exc).__name__
    if kind == 'RateLimitError':
        return AgentUnavailable('The AI service is rate limited; retry shortly', 429)
    if kind == 'AuthenticationError':
        return AgentUnavailable('Backend LLM credentials were rejected', 503)
    log.exception('LLM API failure')
    return AgentUnavailable('The AI service is unavailable', 502)


def make_chat_model(provider: str | None = None):
    provider = (provider or os.getenv('LLM_PROVIDER', 'anthropic')).strip().lower()
    if provider == 'anthropic':
        if not (os.getenv('ANTHROPIC_API_KEY') or os.getenv('ANTHROPIC_AUTH_TOKEN')):
            raise AgentUnavailable('ANTHROPIC_API_KEY is not configured for the backend')
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=os.getenv('CLAUDE_MODEL', DEFAULT_MODELS['anthropic']), max_tokens=16000)
    if provider == 'openai':
        if not os.getenv('OPENAI_API_KEY'):
            raise AgentUnavailable('OPENAI_API_KEY is not configured for the backend')
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=os.getenv('OPENAI_MODEL', DEFAULT_MODELS['openai']), max_tokens=16000,
                          base_url=os.getenv('OPENAI_BASE_URL') or None, use_responses_api=True)
    if provider == 'ollama':
        # Free, local. No API key; the server and the model must already be up (`ollama pull qwen3:8b`).
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=os.getenv('OLLAMA_MODEL', DEFAULT_MODELS['ollama']),
            base_url=os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434'),
            temperature=0,
            # Ollama's default 4k context is too small for the tool schemas + system prompt + history.
            num_ctx=int(os.getenv('OLLAMA_NUM_CTX', '8192')),
            # Explicit (never None): None leaves Qwen3's <think> text inline in the reply shown to the RM.
            # True = think (better tool use, slower); the thinking is kept out of the message content.
            reasoning=os.getenv('OLLAMA_REASONING', 'false').strip().lower() in ('1', 'true', 'yes'))
    raise AgentUnavailable(f"Unsupported LLM_PROVIDER '{provider}' (use 'anthropic', 'openai' or 'ollama')")


class GraphChatAgent:
    def __init__(self, model: Any = None, tools_loader=None, checkpointer: Any = None):
        """model: a LangChain chat model (default from LLM_PROVIDER). tools_loader: async () -> list of
        LangChain tools (default: MultiServerMCPClient against MCP_SERVER_URL). Both injectable for tests."""
        self._model = model
        self._tools_loader = tools_loader or self._load_mcp_tools
        self._checkpointer = checkpointer
        self._graph = None
        self._lock = asyncio.Lock()

    @staticmethod
    async def _load_mcp_tools() -> list:
        from langchain_mcp_adapters.client import MultiServerMCPClient
        url = os.getenv('MCP_SERVER_URL', DEFAULT_MCP_URL)
        try:
            return await MultiServerMCPClient({'crm': {'transport': 'http', 'url': url}}).get_tools()
        except Exception as exc:
            log.exception('Cannot reach MCP server at %s', url)
            raise AgentUnavailable('The CRM tool server is unreachable', 502) from exc

    async def _get_graph(self):
        async with self._lock:  # built once; a failed MCP connect is retried on the next request
            if self._graph is None:
                model = self._model or make_chat_model()
                tools = {t.name: t for t in await self._tools_loader()}
                self._graph = self._build(model, tools)
        return self._graph

    def _build(self, model, tools: dict):
        from langchain_core.messages import AIMessage, ToolMessage, trim_messages
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.graph import END, START, MessagesState, StateGraph

        class State(MessagesState):
            prospects: list | None
            permitted: list
            drafts: dict
            trace: list
            rounds: int
            truncated: bool

        bound = model.bind_tools([*tools.values(), {
            'name': DRAFT_TOOL['name'], 'description': DRAFT_TOOL['description'],
            'parameters': DRAFT_TOOL['input_schema']}])

        async def agent(state: State):
            window = trim_messages(state['messages'], strategy='last', token_counter=len,
                                   max_tokens=MAX_HISTORY * 2, start_on='human', include_system=False)
            try:
                reply = await bound.ainvoke([('system', SYSTEM_PROMPT), *window])
            except Exception as exc:
                raise (_unavailable(exc) or exc) from exc
            meta = reply.response_metadata or {}
            if meta.get('stop_reason') == 'refusal':
                # Never persist an empty/refused assistant turn: it would poison the thread history.
                return {'messages': [AIMessage(content=REFUSAL_TEXT)], 'rounds': state['rounds'] + 1}
            cut = meta.get('stop_reason') == 'max_tokens' or meta.get('finish_reason') == 'length'
            return {'messages': [reply], 'rounds': state['rounds'] + 1, 'truncated': cut}

        async def run_tools(state: State):
            trace, permitted = list(state['trace']), set(state['permitted'])
            prospects, drafts = state['prospects'], dict(state['drafts'])
            out = []
            for call in state['messages'][-1].tool_calls:
                name = call['name']
                if name == DRAFT_TOOL['name']:
                    body, error = _save_drafts(call['args'], {'permitted': permitted, 'drafts': drafts})
                    out.append(ToolMessage(content=body, tool_call_id=call['id'], name=name,
                                           status='error' if error else 'success'))
                    detail = 'Record WhatsApp drafts for RM review'
                elif name not in tools:
                    out.append(_error_message(call, {'code': 'INVALID_INPUT', 'message': f'Unknown tool {name}'}))
                    error, detail = True, ''
                else:
                    detail = (tools[name].description or '').split('.')[0]
                    try:
                        msg = await tools[name].ainvoke(call)
                    except Exception:
                        log.exception('MCP tool %s failed', name)
                        msg = _error_message(call, {'code': 'INTERNAL_ERROR', 'message': 'Tool call failed',
                                                    'retryable': True})
                    out.append(msg)
                    error = msg.status == 'error'
                    data = (getattr(msg, 'artifact', None) or {}).get('structured_content') or {}
                    if not error and name == 'rank_prospects':
                        prospects = data.get('prospects', [])
                        permitted |= {p['customer_id'] for p in prospects if p['whatsapp_contact_permitted']}
                    elif not error and name == 'check_whatsapp_permission' and data.get('whatsapp_contact_permitted'):
                        permitted.add(data['customer_id'])
                entry = {'name': name, 'status': 'error' if error else 'complete', 'detail': detail,
                         'args': call['args']}
                if name == DRAFT_TOOL['name']:
                    entry['outcome'] = json.loads(_text(out[-1].content))
                trace.append(entry)
                if hook := _on_tool.get():
                    try:
                        await hook(name, call['args'], _text(out[-1].content), error)
                    except Exception:  # a UI problem must never break the agent turn
                        log.exception('on_tool hook failed')
            return {'messages': out, 'trace': trace, 'permitted': sorted(permitted),
                    'prospects': prospects, 'drafts': drafts}

        async def limit(state: State):
            # Answer the dangling tool calls so the persisted thread stays a valid conversation.
            calls = state['messages'][-1].tool_calls
            return {'messages': [*(_error_message(c, {'code': 'TOOL_LIMIT', 'message': 'Tool-call limit reached'})
                                   for c in calls), AIMessage(content=LIMIT_TEXT)]}

        def route(state: State):
            if not getattr(state['messages'][-1], 'tool_calls', None):
                return END
            return 'limit' if state['rounds'] >= MAX_TOOL_ROUNDS else 'tools'

        graph = StateGraph(State)
        graph.add_node('agent', agent)
        graph.add_node('tools', run_tools)
        graph.add_node('limit', limit)
        graph.add_edge(START, 'agent')
        graph.add_conditional_edges('agent', route, ['tools', 'limit', END])
        graph.add_edge('tools', 'agent')
        graph.add_edge('limit', END)
        return graph.compile(checkpointer=self._checkpointer or InMemorySaver())

    async def reply(self, session_id: str, message: str, on_tool: ToolHook | None = None) -> dict:
        graph = await self._get_graph()
        _on_tool.set(on_tool)
        final = await graph.ainvoke(
            {'messages': [('user', message)], 'prospects': None, 'permitted': [], 'drafts': {},
             'trace': [], 'rounds': 0, 'truncated': False},
            {'configurable': {'thread_id': session_id}, 'recursion_limit': 4 * MAX_TOOL_ROUNDS})
        text = str(final['messages'][-1].text).strip()
        if final['truncated'] and text:
            text += '\n\n(Response was cut off.)'
        result = None
        if final['prospects'] is not None or final['drafts']:
            customers = [_ui_customer(p) for p in final['prospects'] or []]
            names = {c['id']: c['name'] for c in customers}
            result = {'type': 'prospects', 'customers': customers, 'total': len(customers), 'mode': 'live',
                      'messages': [{'customerId': int(cid), 'customerName': names.get(int(cid), f'Customer {cid}'),
                                    'content': content} for cid, content in final['drafts'].items()]}
        return {'text': text or '(no reply)', 'tools': final['trace'], 'result': result}
