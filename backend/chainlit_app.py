"""Chainlit UI for the banking CRM assistant.

Chainlit -> LangGraph agent (app/graph_agent.py) -> OpenAI | Anthropic | Ollama
                                                 -> FastMCP server over HTTP -> PostgreSQL

Run:  chainlit run chainlit_app.py        (needs the MCP server: MCP_TRANSPORT=http python -m app.mcp_server)

Guardrails here: RM login (RM_USERS + CHAINLIT_AUTH_SECRET), message-length cap, per-RM rate limit,
and an audit record for every turn. Draft content rules live in app/guardrails.py and run inside the agent.
"""
import asyncio
import json
import logging
import os

import chainlit as cl
import pandas as pd

from app.audit import write_audit
from app.graph_agent import AgentUnavailable, GraphChatAgent
from app.guardrails import RateLimiter, authenticate, dev_default_warnings, load_users, max_message_chars

log = logging.getLogger('banking_crm.chainlit')
if not load_users():
    log.error('RM_USERS is empty: nobody can log in. Create a hash with: python -m app.guardrails hash-password')
for _warning in dev_default_warnings():
    log.warning('SECURITY: %s', _warning)

STARTERS = [
    ('Find high-value prospects', 'Find the top 5 high-value customers likely to convert for a personal loan this month.'),
    ('Generate WhatsApp drafts', 'Find the top 3 personal loan prospects and generate personalized WhatsApp messages.'),
    ('Premium loan customers', 'Show premium personal loan prospects with the highest conversion scores.'),
    ('Explain eligibility criteria', 'Explain why customers could be excluded or ineligible for a personal loan.'),
]
DRAFT_FOLLOWUP = ('Generate personalized WhatsApp drafts for the prospects you just showed me. '
                  'Only include customers whose WhatsApp permission you confirm with a tool.')
FOOTER = ('_Scores are heuristics, not conversion probabilities, and product matches are preliminary. '
          'Review consent and bank policy before outreach._')

_agent: GraphChatAgent | None = None
_limiter = RateLimiter(limit=int(os.getenv('CHAT_RATE_LIMIT_PER_MIN', '10')), window=60)


def get_agent() -> GraphChatAgent:
    global _agent
    if _agent is None:
        _agent = GraphChatAgent()  # model from LLM_PROVIDER, tools from MCP_SERVER_URL
    return _agent


@cl.password_auth_callback
async def auth_callback(username: str, password: str) -> cl.User | None:
    username = (username or '').strip()
    # PBKDF2 is deliberately slow; run it off the event loop so other RMs' chats stay responsive.
    if await asyncio.to_thread(authenticate, username, password or ''):
        write_audit('login', user=username, ok=True)
        return cl.User(identifier=username, metadata={'role': 'rm', 'provider': 'credentials'})
    write_audit('login', user=username[:100], ok=False)
    return None


def current_user() -> str:
    user = cl.user_session.get('user')
    return user.identifier if user else 'anonymous'


@cl.set_starters
async def set_starters():
    return [cl.Starter(label=label, message=message) for label, message in STARTERS]


async def show_tool(name: str, args: dict, output: str, is_error: bool) -> None:
    """Live tool trace: one collapsible step per tool call."""
    async with cl.Step(name=name, type='tool', show_input='json') as step:
        step.input = json.dumps(args, ensure_ascii=False)
        step.output = output
        step.is_error = is_error


def prospects_frame(customers: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        'Customer': c['name'], 'ID': c['id'], 'City': c['city'], 'Score': c['score'],
        'Monthly income band': c['income'], 'Credit score band': c['credit'],
        'Balance band': c['balance'], 'Product': c['product'], 'Why': c['reason'],
        'WhatsApp permitted': 'Yes' if c['consent'] else 'No'} for c in customers])


async def run_turn(text: str) -> None:
    user, session_id = current_user(), cl.context.session.id
    base = {'user': user, 'session_id': session_id}
    if len(text) > (limit := max_message_chars()):
        write_audit('blocked', **base, reason='message_too_long', chars=len(text))
        await cl.Message(content=f'⚠️ Your message is too long ({len(text):,} characters). '
                                 f'Please keep it under {limit:,}.').send()
        return
    if not _limiter.allow(user):
        write_audit('blocked', **base, reason='rate_limited')
        await cl.Message(content=f'⚠️ You are sending messages too quickly. Please wait '
                                 f'{_limiter.retry_after(user)} seconds and try again.').send()
        return

    try:
        reply = await get_agent().reply(session_id, text, on_tool=show_tool)
    except AgentUnavailable as exc:
        write_audit('turn_failed', **base, prompt=text, error=str(exc))
        await cl.Message(content=f'⚠️ {exc}').send()
        return
    except Exception:
        log.exception('Chat turn failed')
        write_audit('turn_failed', **base, prompt=text, error='internal error')
        await cl.Message(content='⚠️ Something went wrong. Please try again.').send()
        return

    result = reply['result'] or {}
    write_audit('turn', **base, prompt=text, reply=reply['text'],
                tools=[{k: t.get(k) for k in ('name', 'status', 'args', 'outcome') if k in t}
                       for t in reply['tools']],
                prospect_ids=[c['id'] for c in result.get('customers', [])],
                drafts=[{'customer_id': m['customerId'], 'content': m['content']}
                        for m in result.get('messages', [])])

    result, elements, actions = reply['result'], [], []
    content = reply['text']
    if result and result['customers']:
        df = prospects_frame(result['customers'])
        elements = [cl.Dataframe(data=df, display='inline', name='Prospect shortlist'),
                    cl.File(name='personal-loan-prospects.csv', content=df.to_csv(index=False).encode(),
                            display='inline')]
        if not result['messages']:
            actions = [cl.Action(name='draft_whatsapp', payload={}, icon='message-circle',
                                 label='Draft WhatsApp messages for these prospects')]
    if result:
        content += f'\n\n{FOOTER}'
    await cl.Message(content=content, elements=elements, actions=actions).send()

    if result and result['messages']:
        drafts = '\n\n'.join(f"**{m['customerName']}** (ID {m['customerId']})\n```text\n{m['content']}\n```"
                             for m in result['messages'])
        await cl.Message(content=f'### WhatsApp drafts - for RM review, **not sent**\n\n{drafts}').send()


@cl.on_message
async def on_message(message: cl.Message):
    await run_turn(message.content)


@cl.action_callback('draft_whatsapp')
async def on_draft_whatsapp(action: cl.Action):
    await action.remove()
    await run_turn(DRAFT_FOLLOWUP)
