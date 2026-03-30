# Session 2: Streaming + The Agent Loop

**Goal:** Stream tokens in real-time and refactor our chatbot into a proper Agent class with a run loop.

**What you'll learn:**
- How LLM streaming works (tokens arrive one at a time)
- The agent loop pattern: system prompt -> user -> LLM -> (tools?) -> respond
- Max iterations guard to prevent infinite loops
- Separating concerns into an `Agent` class

**New files:**
- `ultrabot/agent.py` -- the Agent class with `run()` method

### Step 1: Add streaming to our chatbot

Instead of waiting for the full response, we can stream tokens as they
arrive. This is how ChatGPT shows text appearing word-by-word:

```python
# chat_stream.py -- streaming version
from openai import OpenAI

client = OpenAI()

SYSTEM_PROMPT = """You are UltraBot, a helpful personal AI assistant."""

messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

print("UltraBot (streaming). Type 'exit' to quit.\n")

while True:
    user_input = input("you > ").strip()
    if not user_input:
        continue
    if user_input.lower() in ("exit", "quit"):
        break

    messages.append({"role": "user", "content": user_input})

    # stream=True returns an iterator of chunks instead of one response
    print("assistant > ", end="", flush=True)
    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        stream=True,  # <-- the magic flag
    )

    # Collect the full response as we stream it
    full_response = ""
    for chunk in stream:
        # Each chunk has a delta with a content fragment
        delta = chunk.choices[0].delta
        if delta.content:
            print(delta.content, end="", flush=True)
            full_response += delta.content

    print("\n")  # newline after streaming finishes

    messages.append({"role": "assistant", "content": full_response})
```

The key difference: with `stream=True`, you get a generator of `chunk`
objects. Each chunk's `delta.content` is a small piece of text (often a
single word or token). Print them immediately and the user sees the response
build up in real-time.

### Step 2: Build the Agent class

Now let's extract the loop logic into a proper class. This mirrors
`ultrabot/agent/agent.py` from the real codebase:

```python
# ultrabot/agent.py
"""Core agent loop -- orchestrates LLM calls and conversation state.

Simplified from ultrabot/agent/agent.py for teaching purposes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from openai import OpenAI


# -- Data classes (same pattern as ultrabot/providers/base.py) --

@dataclass
class LLMResponse:
    """Normalised response from any LLM provider."""
    content: str | None = None
    tool_calls: list[dict] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


# -- The Agent --

SYSTEM_PROMPT = """\
You are **UltraBot**, a helpful personal AI assistant.
- Answer concisely and accurately.
- When unsure, say so rather than guessing.
- Use code blocks for any code in your responses.
"""


class Agent:
    """High-level agent that manages conversation state and drives the
    LLM call loop.

    This is a simplified version of ultrabot.agent.agent.Agent.
    The real one also has tool execution, security guards, and
    session persistence -- we'll add those in later sessions.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        system_prompt: str = SYSTEM_PROMPT,
        max_iterations: int = 10,
    ) -> None:
        self._client = OpenAI()
        self._model = model
        self._system_prompt = system_prompt
        self._max_iterations = max_iterations

        # Conversation history (mirrors session.get_messages() in the real code)
        self._messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt}
        ]

    def run(
        self,
        user_message: str,
        on_content_delta: Callable[[str], None] | None = None,
    ) -> str:
        """Process a user message and return the assistant's reply.

        This is the core agent loop from ultrabot/agent/agent.py lines 65-174.
        The real version is async and supports tools -- we'll get there.

        Parameters
        ----------
        user_message:
            What the user said.
        on_content_delta:
            Optional callback invoked with each streamed text chunk.
            This is how the CLI shows tokens in real-time.
        """
        # 1. Append the user message
        self._messages.append({"role": "user", "content": user_message})

        # 2. Enter the agent loop
        #    In Session 3 we'll add tool calling here. For now the loop
        #    always exits on the first iteration (no tools = final answer).
        final_content = ""
        for iteration in range(1, self._max_iterations + 1):
            # Call the LLM with streaming
            response = self._chat_stream(on_content_delta)

            # Append assistant message to history
            self._messages.append({
                "role": "assistant",
                "content": response.content or "",
            })

            if not response.has_tool_calls:
                # No tool calls -- this is the final answer
                final_content = response.content or ""
                break

            # (Tool execution will go here in Session 3)
        else:
            # Safety valve: exhausted all iterations
            final_content = (
                "I have reached the maximum number of iterations. "
                "Please try simplifying your request."
            )

        return final_content

    def _chat_stream(
        self,
        on_content_delta: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        """Send messages to the LLM with streaming enabled.

        Mirrors the streaming logic in ultrabot/providers/openai_compat.py
        lines 109-200 (the chat_stream method).
        """
        stream = self._client.chat.completions.create(
            model=self._model,
            messages=self._messages,
            stream=True,
        )

        content_parts: list[str] = []
        tool_calls: list[dict] = []

        for chunk in stream:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            # -- content delta --
            if delta.content:
                content_parts.append(delta.content)
                if on_content_delta:
                    on_content_delta(delta.content)

            # -- tool call deltas (we'll use this in Session 3) --
            # For now, tool_calls stays empty.

        return LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
        )

    def clear(self) -> None:
        """Reset conversation history."""
        self._messages = [{"role": "system", "content": self._system_prompt}]
```

### Step 3: Use the Agent

```python
# main.py -- using the Agent class
from ultrabot.agent import Agent

agent = Agent(model="gpt-4o-mini")

print("UltraBot (Agent class). Type 'exit' to quit.\n")

while True:
    user_input = input("you > ").strip()
    if not user_input:
        continue
    if user_input.lower() in ("exit", "quit"):
        print("Goodbye!")
        break

    # The streaming callback prints tokens as they arrive
    print("assistant > ", end="", flush=True)
    response = agent.run(
        user_input,
        on_content_delta=lambda chunk: print(chunk, end="", flush=True),
    )
    print("\n")
```

### Tests

```python
# tests/test_session2.py
"""Tests for Session 2 -- Agent class and streaming."""
import pytest
from unittest.mock import MagicMock, patch


def test_agent_init():
    """Agent initializes with system prompt in messages."""
    from ultrabot.agent import Agent

    with patch("ultrabot.agent.OpenAI"):
        agent = Agent(model="gpt-4o-mini")
        assert len(agent._messages) == 1
        assert agent._messages[0]["role"] == "system"


def test_agent_appends_user_message():
    """Agent.run() appends the user message to history."""
    from ultrabot.agent import Agent, LLMResponse

    with patch("ultrabot.agent.OpenAI"):
        agent = Agent()

        # Mock _chat_stream to return a simple response
        mock_response = LLMResponse(content="Hello!", tool_calls=[])
        agent._chat_stream = MagicMock(return_value=mock_response)

        result = agent.run("Hi there")

        assert result == "Hello!"
        # Should have: system, user, assistant
        assert len(agent._messages) == 3
        assert agent._messages[1] == {"role": "user", "content": "Hi there"}
        assert agent._messages[2]["role"] == "assistant"


def test_agent_max_iterations():
    """Agent stops after max_iterations even with tool calls."""
    from ultrabot.agent import Agent, LLMResponse

    with patch("ultrabot.agent.OpenAI"):
        agent = Agent(max_iterations=2)

        # Simulate the LLM always requesting tool calls (infinite loop scenario)
        response_with_tools = LLMResponse(
            content="",
            tool_calls=[{"id": "1", "function": {"name": "test", "arguments": "{}"}}],
        )
        agent._chat_stream = MagicMock(return_value=response_with_tools)

        result = agent.run("Do something")
        assert "maximum number of iterations" in result


def test_streaming_callback():
    """Verify on_content_delta is called for each chunk."""
    from ultrabot.agent import Agent, LLMResponse

    with patch("ultrabot.agent.OpenAI"):
        agent = Agent()

        chunks_received = []

        # We'll just test that the callback plumbing works
        mock_response = LLMResponse(content="Hello world", tool_calls=[])
        agent._chat_stream = MagicMock(return_value=mock_response)

        agent.run("Hi", on_content_delta=lambda c: chunks_received.append(c))
        # _chat_stream was called with our callback
        agent._chat_stream.assert_called_once()


def test_agent_clear():
    """Agent.clear() resets to just the system prompt."""
    from ultrabot.agent import Agent, LLMResponse

    with patch("ultrabot.agent.OpenAI"):
        agent = Agent()
        mock_response = LLMResponse(content="Hi!", tool_calls=[])
        agent._chat_stream = MagicMock(return_value=mock_response)

        agent.run("Hello")
        assert len(agent._messages) == 3  # system + user + assistant

        agent.clear()
        assert len(agent._messages) == 1
        assert agent._messages[0]["role"] == "system"
```

### Checkpoint

```bash
python main.py
```

Expected -- tokens stream in real-time:
```
UltraBot (Agent class). Type 'exit' to quit.

you > Write a haiku about Python

assistant > Indented with care,
Snakes of logic twist and turn,
Code blooms line by line.

you > exit
Goodbye!
```

You should see each word appear individually, not all at once.

### What we built

An `Agent` class with a `run()` method that implements the core agent loop:
append user message -> call LLM with streaming -> append assistant reply -> loop.
The max iterations guard prevents infinite loops. This is the skeleton of
`ultrabot/agent/agent.py` -- we'll add tool calling next.

---
