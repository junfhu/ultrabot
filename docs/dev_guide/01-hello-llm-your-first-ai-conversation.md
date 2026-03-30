# Session 1: Hello LLM -- Your First AI Conversation

**Goal:** Talk to an LLM in 10 lines of Python, then build up to a multi-turn chatbot that works with any OpenAI-compatible provider.

**What you'll learn:**
- How the OpenAI chat completions API works
- The messages list pattern (system / user / assistant roles)
- How to point the client at **any** OpenAI-compatible provider (DeepSeek, Ollama, vLLM, LiteLLM, etc.)
- How to build a multi-turn conversation loop

**New files:**
- `chat.py` -- a single-file chatbot you can run immediately

### Step 0: Set up Python 3.12 with pyenv

We use `pyenv` to manage Python versions throughout this guide. If you
haven't set it up yet, see the [Introduction](00-introduction.md#why-pyenv).

```bash
# Install Python 3.12 (skip if already installed)
pyenv install 3.12
pyenv global 3.12

# Create the project directory and a virtual environment
mkdir -p ultrabot && cd ultrabot
python -m venv .venv
source .venv/bin/activate

# Verify
python --version  # Python 3.12.x
```

> **Always activate the venv** before working: `source .venv/bin/activate`

### Step 1: Install the only dependency

```bash
pip install openai
```

That's it. One package. No project scaffolding, no config files. The `openai`
Python SDK works with any provider that exposes an OpenAI-compatible API --
not just OpenAI itself.

### Step 2: Say hello to the LLM

Create `chat.py`:

```python
# chat.py -- Your first AI conversation
import os
from openai import OpenAI

# Three environment variables control which LLM you talk to:
#   OPENAI_API_KEY  -- your API key (required)
#   OPENAI_BASE_URL -- base URL of the provider (optional, defaults to OpenAI)
#   MODEL           -- model name (optional, defaults to gpt-4o-mini)
#
# This means the SAME code works with:
#   - OpenAI          (default)
#   - DeepSeek        (OPENAI_BASE_URL=https://api.deepseek.com)
#   - Ollama          (OPENAI_BASE_URL=http://localhost:11434/v1)
#   - vLLM            (OPENAI_BASE_URL=http://localhost:8000/v1)
#   - Any compatible   provider

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY", "sk-placeholder"),
    base_url=os.getenv("OPENAI_BASE_URL"),  # None = default OpenAI endpoint
)
model = os.getenv("MODEL", "gpt-4o-mini")

response = client.chat.completions.create(
    model=model,
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)
```

Run it:

```bash
# Option A: OpenAI (default)
export OPENAI_API_KEY="sk-..."
python chat.py

# Option B: DeepSeek
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="https://api.deepseek.com"
export MODEL="deepseek-chat"
python chat.py

# Option C: Local Ollama
export OPENAI_API_KEY="ollama"
export OPENAI_BASE_URL="http://localhost:11434/v1"
export MODEL="llama3.2"
python chat.py
```

You should see a friendly greeting from the model. That's the entire OpenAI-
compatible chat API: you send a list of messages, you get a response back.
The same code works whether you're calling OpenAI, DeepSeek, or a local model.

### Step 3: Understand the message format

Every OpenAI chat request takes a `messages` list. Each message is a dict
with a `role` and `content`:

| Role        | Purpose                                      |
|-------------|----------------------------------------------|
| `system`    | Sets the AI's personality and rules           |
| `user`      | What the human says                           |
| `assistant` | What the AI said (used for conversation history) |

This is the fundamental data structure of every LLM chatbot. UltraBot's
entire agent loop (which we'll build in Session 2) revolves around managing
this list.

### Step 4: Add a system prompt

```python
# chat.py -- now with personality
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY", "sk-placeholder"),
    base_url=os.getenv("OPENAI_BASE_URL"),
)
model = os.getenv("MODEL", "gpt-4o-mini")

# The system prompt sets the AI's behavior -- just like ultrabot's
# DEFAULT_SYSTEM_PROMPT in ultrabot/agent/prompts.py
SYSTEM_PROMPT = """You are UltraBot, a helpful personal AI assistant.
- Answer concisely and accurately.
- When unsure, say so rather than guessing.
- Use code blocks for any code in your responses."""

response = client.chat.completions.create(
    model=model,
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "What is Python's GIL?"},
    ],
)
print(response.choices[0].message.content)
```

### Step 5: Build a multi-turn conversation

The key insight: to have a conversation, you keep a growing `messages` list.
After each assistant reply, you append it, then append the next user message.

```python
# chat.py -- full multi-turn chatbot (works with any OpenAI-compatible provider)
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY", "sk-placeholder"),
    base_url=os.getenv("OPENAI_BASE_URL"),
)
model = os.getenv("MODEL", "gpt-4o-mini")

SYSTEM_PROMPT = """You are UltraBot, a helpful personal AI assistant.
- Answer concisely and accurately.
- When unsure, say so rather than guessing.
- Use code blocks for any code in your responses."""

# The conversation history -- this is the core data structure
messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

print(f"UltraBot ready (model={model}). Type 'exit' to quit.\n")

while True:
    user_input = input("you > ").strip()
    if not user_input:
        continue
    if user_input.lower() in ("exit", "quit"):
        print("Goodbye!")
        break

    # 1. Append the user's message to history
    messages.append({"role": "user", "content": user_input})

    # 2. Send the full history to the LLM
    response = client.chat.completions.create(
        model=model,
        messages=messages,
    )

    # 3. Extract the assistant's reply
    assistant_message = response.choices[0].message.content

    # 4. Append the assistant's reply to history (this is what makes
    #    the conversation "multi-turn" -- the LLM sees everything)
    messages.append({"role": "assistant", "content": assistant_message})

    print(f"\nassistant > {assistant_message}\n")
```

This pattern -- append user, call LLM, append assistant, loop -- is the
heart of **every** AI chatbot. UltraBot's `Agent.run()` method in
`ultrabot/agent/agent.py` does exactly this, just with more features
layered on top.

### Step 6: Add a minimal pyproject.toml

We'll need this in later sessions so `pip install -e .` works. Keep it
minimal for now:

```toml
# pyproject.toml
[project]
name = "ultrabot"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["openai>=1.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### Tests

Create `tests/test_session1.py`:

```python
# tests/test_session1.py
"""Tests for Session 1 -- message format, env config, and response parsing."""
import os
import pytest


def test_message_format():
    """Verify our messages list has the right structure."""
    messages = [
        {"role": "system", "content": "You are a helper."},
        {"role": "user", "content": "Hello!"},
    ]
    # Every message must have 'role' and 'content'
    for msg in messages:
        assert "role" in msg
        assert "content" in msg
        assert msg["role"] in ("system", "user", "assistant", "tool")


def test_multi_turn_history():
    """Verify conversation history grows correctly."""
    messages = [{"role": "system", "content": "You are a helper."}]

    # Simulate a two-turn conversation
    messages.append({"role": "user", "content": "Hi"})
    messages.append({"role": "assistant", "content": "Hello!"})
    messages.append({"role": "user", "content": "How are you?"})
    messages.append({"role": "assistant", "content": "I'm great!"})

    assert len(messages) == 5
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[2]["role"] == "assistant"
    # Roles alternate user/assistant after the system prompt
    for i in range(1, len(messages)):
        expected = "user" if i % 2 == 1 else "assistant"
        assert messages[i]["role"] == expected


def test_default_model():
    """MODEL env var defaults to gpt-4o-mini when unset."""
    orig = os.environ.pop("MODEL", None)
    try:
        model = os.getenv("MODEL", "gpt-4o-mini")
        assert model == "gpt-4o-mini"
    finally:
        if orig is not None:
            os.environ["MODEL"] = orig


def test_custom_model(monkeypatch):
    """MODEL env var overrides the default model."""
    monkeypatch.setenv("MODEL", "deepseek-chat")
    model = os.getenv("MODEL", "gpt-4o-mini")
    assert model == "deepseek-chat"


def test_custom_base_url(monkeypatch):
    """OPENAI_BASE_URL env var configures the provider endpoint."""
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com")
    base_url = os.getenv("OPENAI_BASE_URL")
    assert base_url == "https://api.deepseek.com"


def test_base_url_none_when_unset():
    """OPENAI_BASE_URL defaults to None (uses OpenAI endpoint)."""
    orig = os.environ.pop("OPENAI_BASE_URL", None)
    try:
        base_url = os.getenv("OPENAI_BASE_URL")
        assert base_url is None
    finally:
        if orig is not None:
            os.environ["OPENAI_BASE_URL"] = orig


def test_response_parsing_mock(monkeypatch):
    """Test that we correctly parse an OpenAI response (mocked)."""
    from unittest.mock import MagicMock

    # Build a mock response that looks like what OpenAI returns
    mock_message = MagicMock()
    mock_message.content = "Hello! How can I help?"

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    # This is exactly how we parse it in chat.py
    result = mock_response.choices[0].message.content
    assert result == "Hello! How can I help?"
```

Run tests:

```bash
pip install pytest
pytest tests/test_session1.py -v
```

### Checkpoint

```bash
# With any provider -- set your env vars and run:
python chat.py
```

Expected:
```
UltraBot ready (model=gpt-4o-mini). Type 'exit' to quit.

you > What is 2 + 2?

assistant > 2 + 2 equals 4.

you > And multiply that by 10?

assistant > 4 multiplied by 10 equals 40.

you > exit
Goodbye!
```

The model remembers previous turns because we're sending the full `messages`
list each time. And because we read `OPENAI_BASE_URL` and `MODEL` from the
environment, the same code works with OpenAI, DeepSeek, Ollama, or any
compatible provider.

### What we built

A complete multi-turn chatbot in a single file that works with **any**
OpenAI-compatible provider. Three env vars (`OPENAI_API_KEY`,
`OPENAI_BASE_URL`, `MODEL`) let you switch providers without changing code.
The messages list pattern (`system` + alternating `user`/`assistant`) is the
foundation that everything else in UltraBot builds upon.

---
