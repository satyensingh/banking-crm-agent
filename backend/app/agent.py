"""Chat agent: an LLM (Anthropic or OpenAI) drives the CRM MCP tools in-process and returns the UI shape."""
import json
import logging
from collections import OrderedDict
from typing import Any, Callable

from fastmcp import Client, FastMCP

from .llm import AgentUnavailable, LLMProvider, ToolOutcome, ToolSpec, make_provider
from .mcp_server import build_server

log = logging.getLogger('banking_crm.agent')

MAX_TOOL_ROUNDS = 8
MAX_HISTORY = 20
MAX_SESSIONS = 200

SYSTEM_PROMPT = """You are a banking relationship-manager (RM) assistant for personal-loan outreach.
Use the provided tools for every fact about customers, eligibility, scores and consent; never invent
customer data. Scores are heuristics, not probabilities, and product matches are preliminary
suitability, not credit decisions or offers - say so when relevant.
Only customers with WhatsApp contact permission may be given a WhatsApp draft. When the RM asks for
WhatsApp messages, write a short, warm, compliant draft per customer (no guaranteed approval, no
rates or amounts you were not given) and record them with save_whatsapp_drafts. Drafts are for RM
review; nothing is ever sent. Keep replies concise and do not repeat tables the UI already shows."""

DRAFT_TOOL = {
    'name': 'save_whatsapp_drafts',
    'description': ('Record WhatsApp draft messages for RM review. Nothing is sent. Only customers '
                    'whose WhatsApp permission was confirmed by a tool this turn are accepted.'),
    'input_schema': {
        'type': 'object',
        'properties': {'drafts': {'type': 'array', 'minItems': 1, 'maxItems': 20, 'items': {
            'type': 'object',
            'properties': {'customer_id': {'type': 'integer', 'minimum': 1},
                           'content': {'type': 'string', 'minLength': 1, 'maxLength': 1000}},
            'required': ['customer_id', 'content'], 'additionalProperties': False}}},
        'required': ['drafts'], 'additionalProperties': False},
}


def _initials(name: str) -> str:
    return ''.join(p[0] for p in name.split()[:2]).upper()


def _ui_customer(p: dict) -> dict:
    code = p.get('suggested_product_code') or ''
    return {'id': p['customer_id'], 'name': p['full_name'], 'initials': _initials(p['full_name']),
            'city': p['city'], 'score': p['propensity_score'], 'income': float(p['monthly_income_inr']),
            'creditScore': p['credit_score'], 'balance': float(p['current_balance_inr']),
            'product': code.replace('_', ' ').title(), 'code': code, 'reason': p['reason'],
            'contacted': 'n/a', 'consent': p['whatsapp_contact_permitted']}


class ChatAgent:
    def __init__(self, provider: LLMProvider | None = None,
                 server_factory: Callable[[], FastMCP] = build_server):
        self.provider = provider or make_provider()
        self._server = server_factory()
        self._sessions: OrderedDict[str, list[dict]] = OrderedDict()

    def _history(self, session_id: str) -> list[dict]:
        history = self._sessions.setdefault(session_id, [])
        self._sessions.move_to_end(session_id)
        while len(self._sessions) > MAX_SESSIONS:
            self._sessions.popitem(last=False)
        return history

    async def reply(self, session_id: str, message: str) -> dict:
        provider = self.provider
        history = self._history(session_id)
        messages = provider.start(history, message)
        trace: list[dict] = []
        state = {'prospects': None, 'permitted': set(), 'drafts': {}}
        text = ''
        async with Client(self._server) as mcp:
            described = {t.name: t for t in await mcp.list_tools()}
            specs = [ToolSpec(t.name, t.description or '', t.inputSchema) for t in described.values()]
            specs.append(ToolSpec(DRAFT_TOOL['name'], DRAFT_TOOL['description'], DRAFT_TOOL['input_schema']))
            for _ in range(MAX_TOOL_ROUNDS):
                turn = await provider.complete(messages, SYSTEM_PROMPT, specs)
                if turn.stop == 'refusal':
                    text = 'I cannot help with that request.'
                    break
                if turn.stop != 'tool_use':
                    text = turn.text + ('\n\n(Response was cut off.)' if turn.stop == 'max_tokens' else '')
                    break
                outcomes = [await self._run_tool(mcp, described, call, trace, state) for call in turn.calls]
                provider.add_results(messages, outcomes)
            else:
                text = 'I could not finish within the tool-call limit. Please narrow the request.'

        history += [{'role': 'user', 'content': message}, {'role': 'assistant', 'content': text or '(no reply)'}]
        del history[:-MAX_HISTORY]
        result = None
        if state['prospects'] is not None or state['drafts']:
            customers = [_ui_customer(p) for p in state['prospects'] or []]
            names = {c['id']: c['name'] for c in customers}
            result = {'type': 'prospects', 'customers': customers, 'total': len(customers), 'mode': 'live',
                      'messages': [{'customerId': cid, 'customerName': names.get(cid, f'Customer {cid}'),
                                    'content': content} for cid, content in state['drafts'].items()]}
        return {'text': text, 'tools': trace, 'result': result}

    async def _run_tool(self, mcp, described, call, trace, state) -> ToolOutcome:
        def done(content: str, error: bool) -> ToolOutcome:
            trace.append({'name': call.name, 'status': 'error' if error else 'complete',
                          'detail': (described[call.name].description or '').split('.')[0]
                          if call.name in described else 'Record WhatsApp drafts for RM review'})
            return ToolOutcome(call, content, error)

        if isinstance(call.input, dict) and '__invalid_json__' in call.input:
            return done(json.dumps({'code': 'INVALID_INPUT', 'retryable': False,
                                    'message': 'Tool arguments were not valid JSON; resend them'}), True)
        if call.name == DRAFT_TOOL['name']:
            return done(*self._save_drafts(call.input, state))
        if call.name not in described:
            return done(json.dumps({'code': 'INVALID_INPUT', 'message': f'Unknown tool {call.name}',
                                    'retryable': False}), True)
        result = await mcp.call_tool(call.name, call.input, raise_on_error=False)
        body = result.content[0].text if result.content else ''
        if not result.is_error:
            data = result.structured_content or {}
            if call.name == 'rank_prospects':
                state['prospects'] = data.get('prospects', [])
                state['permitted'] |= {p['customer_id'] for p in state['prospects']
                                       if p['whatsapp_contact_permitted']}
            elif call.name == 'check_whatsapp_permission' and data.get('whatsapp_contact_permitted'):
                state['permitted'].add(data['customer_id'])
        return done(body, bool(result.is_error))

    @staticmethod
    def _save_drafts(args: dict, state: dict) -> tuple[str, bool]:
        saved, rejected = [], []
        for d in args.get('drafts', []) if isinstance(args, dict) else []:
            try:
                cid, content = int(d['customer_id']), str(d['content']).strip()[:1000]
            except (KeyError, TypeError, ValueError):
                continue
            if cid in state['permitted'] and content:
                state['drafts'][cid] = content
                saved.append(cid)
            else:
                rejected.append(cid)
        return json.dumps({'saved': saved, 'rejected_no_confirmed_whatsapp_permission': rejected}), False
