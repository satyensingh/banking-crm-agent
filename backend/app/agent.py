"""Chat agent: Claude drives the CRM MCP tools (in-process) and returns the UI's reply shape."""
import json
import logging
import os
from collections import OrderedDict
from typing import Any, Callable

import anthropic
from fastmcp import Client, FastMCP

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


class AgentUnavailable(RuntimeError):
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


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
    def __init__(self, client: Any = None, server_factory: Callable[[], FastMCP] = build_server,
                 model: str | None = None):
        self._client = client
        self._server = server_factory()
        self.model = model or os.getenv('CLAUDE_MODEL', 'claude-sonnet-5-5')
        self.effort = os.getenv('CLAUDE_EFFORT', 'medium')
        self._sessions: OrderedDict[str, list[dict]] = OrderedDict()

    @property
    def client(self):
        if self._client is None:
            if not (os.getenv('ANTHROPIC_API_KEY') or os.getenv('ANTHROPIC_AUTH_TOKEN')):
                raise AgentUnavailable('ANTHROPIC_API_KEY is not configured for the backend')
            self._client = anthropic.AsyncAnthropic()
        return self._client

    def _history(self, session_id: str) -> list[dict]:
        history = self._sessions.setdefault(session_id, [])
        self._sessions.move_to_end(session_id)
        while len(self._sessions) > MAX_SESSIONS:
            self._sessions.popitem(last=False)
        return history

    async def reply(self, session_id: str, message: str) -> dict:
        client = self.client
        history = self._history(session_id)
        messages: list[Any] = [*history, {'role': 'user', 'content': message}]
        trace: list[dict] = []
        state = {'prospects': None, 'permitted': set(), 'drafts': {}}
        text = ''
        try:
            async with Client(self._server) as mcp:
                described = {t.name: t for t in await mcp.list_tools()}
                tools = [{'name': t.name, 'description': t.description or '', 'input_schema': t.inputSchema}
                         for t in described.values()] + [DRAFT_TOOL]
                for _ in range(MAX_TOOL_ROUNDS):
                    response = await client.messages.create(
                        model=self.model, max_tokens=16000, system=SYSTEM_PROMPT, tools=tools,
                        messages=messages, output_config={'effort': self.effort})
                    if response.stop_reason == 'refusal':
                        text = 'I cannot help with that request.'
                        break
                    messages.append({'role': 'assistant', 'content': response.content})
                    calls = [b for b in response.content if b.type == 'tool_use']
                    if response.stop_reason != 'tool_use' or not calls:
                        text = '\n'.join(b.text for b in response.content if b.type == 'text').strip()
                        if response.stop_reason == 'max_tokens':
                            text += '\n\n(Response was cut off.)'
                        break
                    results = []
                    for call in calls:
                        results.append(await self._run_tool(mcp, described, call, trace, state))
                    messages.append({'role': 'user', 'content': results})
                else:
                    text = 'I could not finish within the tool-call limit. Please narrow the request.'
        except anthropic.RateLimitError as exc:
            raise AgentUnavailable('The AI service is rate limited; retry shortly', 429) from exc
        except anthropic.AuthenticationError as exc:
            raise AgentUnavailable('Backend Anthropic credentials were rejected', 503) from exc
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
            log.exception('Anthropic API failure')
            raise AgentUnavailable('The AI service is unavailable', 502) from exc

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

    async def _run_tool(self, mcp, described, call, trace, state) -> dict:
        def done(content: str, error: bool) -> dict:
            trace.append({'name': call.name, 'status': 'error' if error else 'complete',
                          'detail': (described[call.name].description or '').split('.')[0]
                          if call.name in described else 'Record WhatsApp drafts for RM review'})
            block = {'type': 'tool_result', 'tool_use_id': call.id, 'content': content}
            return {**block, 'is_error': True} if error else block

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
