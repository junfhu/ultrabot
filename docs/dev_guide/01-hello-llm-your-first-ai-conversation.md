# Session 1: Hello LLM -- Your First AI Conversation

**Goal:** Talk to an LLM in 10 lines of Python, then build up to a multi-turn chatbot.

**What you'll learn:**
- How the OpenAI chat completions API works
- The messages list pattern (system / user / assistant roles)
- How to build a multi-turn conversation loop

**New files:**
- `chat.py` -- a single-file chatbot you can run immediately

### Step 1: Install the only dependency

```bash
pip install openai
```

That's it. One package. No project scaffolding, no config files.

### Step 2: Say hello to the LLM

Create `chat.py`:

```python
# chat.py -- Your first AI conversation
from openai import OpenAI

client = OpenAI()  # reads OPENAI_API_KEY from environment
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)
```

Run it:

```bash
export OPENAI_API_KEY="sk-..."
python chat.py
```

You should see a friendly greeting from the model. That's the entire OpenAI
chat API in six lines: you send a list of messages, you get a response back.

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
from openai import OpenAI

client = OpenAI()

# The system prompt sets the AI's behavior -- just like ultrabot's
# DEFAULT_SYSTEM_PROMPT in ultrabot/agent/prompts.py
SYSTEM_PROMPT = """You are UltraBot, a helpful personal AI assistant.
- Answer concisely and accurately.
- When unsure, say so rather than guessing.
- Use code blocks for any code in your responses."""

response = client.chat.completions.create(
    model="gpt-4o-mini",
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
# chat.py -- full multi-turn chatbot
from openai import OpenAI

client = OpenAI()

SYSTEM_PROMPT = """You are UltraBot, a helpful personal AI assistant.
- Answer concisely and accurately.
- When unsure, say so rather than guessing.
- Use code blocks for any code in your responses."""

# The conversation history -- this is the core data structure
messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

print("UltraBot ready. Type 'exit' to quit.\n")

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
        model="gpt-4o-mini",
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
"""Tests for Session 1 -- message format and response parsing."""
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
python chat.py
```

Expected:
```
UltraBot ready. Type 'exit' to quit.

you > What is 2 + 2?

assistant > 2 + 2 equals 4.

you > And multiply that by 10?

assistant > 4 multiplied by 10 equals 40.

you > exit
Goodbye!
```

The model remembers previous turns because we're sending the full `messages`
list each time.

### What we built

A complete multi-turn chatbot in a single file. The messages list pattern
(`system` + alternating `user`/`assistant`) is the foundation that everything
else in UltraBot builds upon.

---
