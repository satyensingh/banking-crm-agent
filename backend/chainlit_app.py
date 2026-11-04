"""Chainlit UI for the banking CRM assistant.

Chainlit -> LangGraph agent (app/graph_agent.py) -> OpenAI | Anthropic | Ollama
                                                 -> FastMCP server over HTTP -> PostgreSQL

Run:  chainlit run chainlit_app.py        (needs the MCP server: MCP_TRANSPORT=http python -m app.mcp_server)
"""
import json

import chainlit as cl
import pandas as pd

from app.graph_agent import AgentUnavailable, GraphChatAgent

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


def get_agent() -> GraphChatAgent:
    global _agent
    if _agent is None:
        _agent = GraphChatAgent()  # model from LLM_PROVIDER, tools from MCP_SERVER_URL
    return _agent


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
        'Monthly income (INR)': c['income'], 'Credit score': c['creditScore'],
        'Balance (INR)': c['balance'], 'Product': c['product'], 'Why': c['reason'],
        'WhatsApp permitted': 'Yes' if c['consent'] else 'No'} for c in customers])


async def run_turn(text: str) -> None:
    try:
        reply = await get_agent().reply(cl.context.session.id, text, on_tool=show_tool)
    except AgentUnavailable as exc:
        await cl.Message(content=f'⚠️ {exc}').send()
        return

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
