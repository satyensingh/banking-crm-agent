"""LLM provider adapters (Anthropic Messages API, OpenAI Responses API) behind one tiny interface.

Each adapter owns its wire format: it builds the message list, appends the assistant turn and the
tool results, and maps SDK errors to AgentUnavailable. The agent loop in agent.py is provider-neutral.
"""
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

log = logging.getLogger('banking_crm.llm')

DEFAULT_PROVIDER = 'anthropic'
DEFAULT_MODELS = {'anthropic': 'claude-sonnet-5-5', 'openai': 'gpt-5'}


class AgentUnavailable(RuntimeError):
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict


@dataclass
class Call:
    id: str
    name: str
    input: dict


@dataclass
class Turn:
    text: str
    calls: list[Call] = field(default_factory=list)
    stop: Literal['end', 'tool_use', 'refusal', 'max_tokens'] = 'end'


@dataclass
class ToolOutcome:
    call: Call
    content: str
    is_error: bool


class LLMProvider(Protocol):
    name: str
    model: str

    def start(self, history: list[dict], message: str) -> list: ...
    async def complete(self, messages: list, system: str, tools: list[ToolSpec]) -> Turn: ...
    def add_results(self, messages: list, outcomes: list[ToolOutcome]) -> None: ...


class AnthropicProvider:
    name = 'anthropic'

    def __init__(self, client: Any = None, model: str | None = None, effort: str | None = None):
        self._client = client
        self.model = model or os.getenv('CLAUDE_MODEL', DEFAULT_MODELS['anthropic'])
        self.effort = effort or os.getenv('CLAUDE_EFFORT', 'medium')

    @property
    def client(self):
        if self._client is None:
            if not (os.getenv('ANTHROPIC_API_KEY') or os.getenv('ANTHROPIC_AUTH_TOKEN')):
                raise AgentUnavailable('ANTHROPIC_API_KEY is not configured for the backend')
            import anthropic
            self._client = anthropic.AsyncAnthropic()
        return self._client

    def start(self, history, message):
        return [*history, {'role': 'user', 'content': message}]

    async def complete(self, messages, system, tools):
        import anthropic
        client = self.client
        try:
            response = await client.messages.create(
                model=self.model, max_tokens=16000, system=system, messages=messages,
                tools=[{'name': t.name, 'description': t.description, 'input_schema': t.schema}
                       for t in tools],
                output_config={'effort': self.effort})
        except anthropic.RateLimitError as exc:
            raise AgentUnavailable('The AI service is rate limited; retry shortly', 429) from exc
        except anthropic.AuthenticationError as exc:
            raise AgentUnavailable('Backend Anthropic credentials were rejected', 503) from exc
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
            log.exception('Anthropic API failure')
            raise AgentUnavailable('The AI service is unavailable', 502) from exc
        if response.stop_reason == 'refusal':
            return Turn('', stop='refusal')
        # Replay the full content (including thinking blocks) unchanged on the next request.
        messages.append({'role': 'assistant', 'content': response.content})
        calls = [Call(b.id, b.name, b.input) for b in response.content if b.type == 'tool_use']
        text = '\n'.join(b.text for b in response.content if b.type == 'text').strip()
        if response.stop_reason == 'tool_use' and calls:
            return Turn(text, calls, 'tool_use')
        return Turn(text, stop='max_tokens' if response.stop_reason == 'max_tokens' else 'end')

    def add_results(self, messages, outcomes):
        blocks = []
        for o in outcomes:
            block = {'type': 'tool_result', 'tool_use_id': o.call.id, 'content': o.content}
            blocks.append({**block, 'is_error': True} if o.is_error else block)
        messages.append({'role': 'user', 'content': blocks})


class OpenAIProvider:
    """OpenAI Responses API, stateless (store=False). Responses is required for tool calling on
    the newest OpenAI models. Set OPENAI_BASE_URL to target an OpenAI-compatible gateway."""
    name = 'openai'

    def __init__(self, client: Any = None, model: str | None = None, effort: str | None = None):
        self._client = client
        self.model = model or os.getenv('OPENAI_MODEL', DEFAULT_MODELS['openai'])
        self.effort = effort or os.getenv('OPENAI_REASONING_EFFORT', 'medium')

    @property
    def client(self):
        if self._client is None:
            if not os.getenv('OPENAI_API_KEY'):
                raise AgentUnavailable('OPENAI_API_KEY is not configured for the backend')
            import openai
            self._client = openai.AsyncOpenAI()
        return self._client

    def start(self, history, message):
        return [*history, {'role': 'user', 'content': message}]

    async def complete(self, messages, system, tools):
        import openai
        client = self.client
        try:
            response = await client.responses.create(
                model=self.model, instructions=system, input=messages, store=False,
                max_output_tokens=16000, reasoning={'effort': self.effort},
                include=['reasoning.encrypted_content'],
                tools=[{'type': 'function', 'name': t.name, 'description': t.description,
                        'parameters': t.schema, 'strict': False} for t in tools])
        except openai.RateLimitError as exc:
            raise AgentUnavailable('The AI service is rate limited; retry shortly', 429) from exc
        except openai.AuthenticationError as exc:
            raise AgentUnavailable('Backend OpenAI credentials were rejected', 503) from exc
        except (openai.APIConnectionError, openai.APIStatusError) as exc:
            log.exception('OpenAI API failure')
            raise AgentUnavailable('The AI service is unavailable', 502) from exc

        # Replay every output item (reasoning included) as input for the next request.
        messages.extend(i.model_dump(exclude_none=True) if hasattr(i, 'model_dump') else i
                        for i in response.output)
        calls, texts, refused = [], [], False
        for item in response.output:
            if item.type == 'function_call':
                try:
                    args = json.loads(item.arguments or '{}')
                except json.JSONDecodeError:
                    args = {'__invalid_json__': item.arguments}
                calls.append(Call(item.call_id, item.name, args))
            elif item.type == 'message':
                for part in item.content:
                    if part.type == 'output_text':
                        texts.append(part.text)
                    elif part.type == 'refusal':
                        refused = True
        text = '\n'.join(texts).strip()
        if calls:
            return Turn(text, calls, 'tool_use')
        if refused and not text:
            return Turn('', stop='refusal')
        incomplete = getattr(response, 'incomplete_details', None)
        if getattr(response, 'status', 'completed') == 'incomplete' and \
                getattr(incomplete, 'reason', None) == 'max_output_tokens':
            return Turn(text, stop='max_tokens')
        return Turn(text)

    def add_results(self, messages, outcomes):
        for o in outcomes:
            messages.append({'type': 'function_call_output', 'call_id': o.call.id, 'output': o.content})


def make_provider(name: str | None = None) -> LLMProvider:
    name = (name or os.getenv('LLM_PROVIDER', DEFAULT_PROVIDER)).strip().lower()
    if name == 'anthropic':
        return AnthropicProvider()
    if name == 'openai':
        return OpenAIProvider()
    raise AgentUnavailable(f"Unsupported LLM_PROVIDER '{name}' (use 'anthropic' or 'openai')")
