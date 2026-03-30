# 课程 1：向 LLM 问好 -- 你的第一次 AI 对话

**目标：** 用 10 行 Python 和 LLM 对话，然后逐步构建一个多轮聊天机器人。

**你将学到：**
- OpenAI chat completions API 的工作原理
- 消息列表模式（system / user / assistant 角色）
- 如何构建多轮对话循环

**新建文件：**
- `chat.py` -- 一个可以立即运行的单文件聊天机器人

### 步骤 1：安装唯一的依赖

```bash
pip install openai
```

就这样。一个包。不需要项目脚手架，不需要配置文件。

### 步骤 2：向 LLM 打个招呼

创建 `chat.py`：

```python
# chat.py -- 你的第一次 AI 对话
from openai import OpenAI

client = OpenAI()  # 从环境变量读取 OPENAI_API_KEY
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)
```

运行：

```bash
export OPENAI_API_KEY="sk-..."
python chat.py
```

你应该能看到模型返回的友好问候。这就是整个 OpenAI chat API 的六行代码：你发送一个消息列表，得到一个回复。

### 步骤 3：理解消息格式

每个 OpenAI chat 请求接收一个 `messages` 列表。每条消息是一个包含 `role` 和 `content` 的字典：

| 角色        | 用途                                         |
|-------------|----------------------------------------------|
| `system`    | 设定 AI 的性格和规则                          |
| `user`      | 人类说的话                                    |
| `assistant` | AI 说的话（用于对话历史记录）                  |

这是每个 LLM 聊天机器人的基础数据结构。UltraBot 的整个智能体循环（我们将在课程 2 中构建）就是围绕管理这个列表展开的。

### 步骤 4：添加系统提示词

```python
# chat.py -- 现在有了个性
from openai import OpenAI

client = OpenAI()

# 系统提示词设定 AI 的行为 -- 就像 ultrabot 的
# ultrabot/agent/prompts.py 中的 DEFAULT_SYSTEM_PROMPT
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

### 步骤 5：构建多轮对话

关键洞察：要进行对话，你需要维护一个不断增长的 `messages` 列表。每次助手回复后，将其追加到列表，然后追加下一条用户消息。

```python
# chat.py -- 完整的多轮聊天机器人
from openai import OpenAI

client = OpenAI()

SYSTEM_PROMPT = """You are UltraBot, a helpful personal AI assistant.
- Answer concisely and accurately.
- When unsure, say so rather than guessing.
- Use code blocks for any code in your responses."""

# 对话历史 -- 这是核心数据结构
messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

print("UltraBot ready. Type 'exit' to quit.\n")

while True:
    user_input = input("you > ").strip()
    if not user_input:
        continue
    if user_input.lower() in ("exit", "quit"):
        print("Goodbye!")
        break

    # 1. 将用户消息追加到历史记录
    messages.append({"role": "user", "content": user_input})

    # 2. 将完整历史记录发送给 LLM
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
    )

    # 3. 提取助手的回复
    assistant_message = response.choices[0].message.content

    # 4. 将助手的回复追加到历史记录（这就是让对话变成
    #    "多轮"的关键 -- LLM 能看到之前所有内容）
    messages.append({"role": "assistant", "content": assistant_message})

    print(f"\nassistant > {assistant_message}\n")
```

这种模式 -- 追加用户消息、调用 LLM、追加助手回复、循环 -- 是**每一个** AI 聊天机器人的核心。UltraBot 的 `Agent.run()` 方法（在 `ultrabot/agent/agent.py` 中）做的就是同样的事情，只是在上面叠加了更多功能。

### 步骤 6：添加一个最简的 pyproject.toml

后面的课程中需要它来让 `pip install -e .` 生效。现在先保持最简：

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

### 测试

创建 `tests/test_session1.py`：

```python
# tests/test_session1.py
"""课程 1 的测试 -- 消息格式和响应解析。"""
import pytest


def test_message_format():
    """验证我们的消息列表具有正确的结构。"""
    messages = [
        {"role": "system", "content": "You are a helper."},
        {"role": "user", "content": "Hello!"},
    ]
    # 每条消息必须包含 'role' 和 'content'
    for msg in messages:
        assert "role" in msg
        assert "content" in msg
        assert msg["role"] in ("system", "user", "assistant", "tool")


def test_multi_turn_history():
    """验证对话历史记录正确增长。"""
    messages = [{"role": "system", "content": "You are a helper."}]

    # 模拟一个两轮对话
    messages.append({"role": "user", "content": "Hi"})
    messages.append({"role": "assistant", "content": "Hello!"})
    messages.append({"role": "user", "content": "How are you?"})
    messages.append({"role": "assistant", "content": "I'm great!"})

    assert len(messages) == 5
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[2]["role"] == "assistant"
    # 在系统提示词之后，角色交替出现 user/assistant
    for i in range(1, len(messages)):
        expected = "user" if i % 2 == 1 else "assistant"
        assert messages[i]["role"] == expected


def test_response_parsing_mock(monkeypatch):
    """测试我们能否正确解析 OpenAI 响应（使用 mock）。"""
    from unittest.mock import MagicMock

    # 构建一个模拟的响应，看起来像 OpenAI 返回的结果
    mock_message = MagicMock()
    mock_message.content = "Hello! How can I help?"

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    # 这就是我们在 chat.py 中解析它的方式
    result = mock_response.choices[0].message.content
    assert result == "Hello! How can I help?"
```

运行测试：

```bash
pip install pytest
pytest tests/test_session1.py -v
```

### 检查点

```bash
python chat.py
```

预期输出：
```
UltraBot ready. Type 'exit' to quit.

you > What is 2 + 2?

assistant > 2 + 2 equals 4.

you > And multiply that by 10?

assistant > 4 multiplied by 10 equals 40.

you > exit
Goodbye!
```

模型记住了之前的对话轮次，因为我们每次都发送了完整的 `messages` 列表。

### 本课成果

一个完整的单文件多轮聊天机器人。消息列表模式（`system` + 交替的 `user`/`assistant`）是 UltraBot 中一切功能的基础。

---
