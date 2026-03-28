# ultrabot：稳健的个人 AI 助手框架

[English README](README_EN.md)

**ultrabot** 是一个功能丰富、可用于生产环境的个人 AI 助手框架，灵感来自 [nanobot](https://github.com/HKUDS/nanobot)。它保留了核心 Agent 能力，并在此基础上提供了更强的工程化特性：熔断与故障转移、优先级消息队列、持久化会话、并行工具执行、支持热重载的插件、MCP 支持、内置安全层，以及覆盖 17 个专业领域的 170 个专家人格系统。

## 核心特性

| 特性 | 说明 |
|------|------|
| **熔断器 + 故障转移** | 当某个 LLM 提供商不可用时自动切换。可追踪失败次数、打开熔断，并将请求路由到健康提供商。 |
| **优先级消息总线** | 基于优先级的异步消息队列，并带有失败消息的死信处理。 |
| **持久化会话** | 基于 JSON 的会话存储，支持 TTL 淘汰和按 token 感知的上下文窗口裁剪。 |
| **并行工具执行** | 多个工具调用通过 `asyncio.gather` 并发执行，加快 Agent 循环。 |
| **专家系统** | 内置 17 个部门、170 个领域专家人格。支持 `@slug` 激活、粘性会话以及可选的 LLM 自动路由。 |
| **热重载插件** | 技能可从磁盘加载并支持热重载。放入 `SKILL.md` 和工具后即可重新加载。 |
| **MCP 客户端** | 支持 stdio 和 HTTP 两种 Model Context Protocol 传输方式，可连接外部工具服务。 |
| **安全层** | 具备限流、按频道访问控制、输入清洗、阻断模式检测等能力。 |
| **多提供商** | 支持 12+ LLM 提供商：OpenRouter、Anthropic、OpenAI、DeepSeek、Gemini、Groq、Ollama、vLLM、Moonshot、MiniMax、Mistral，以及自定义端点。 |
| **多聊天渠道** | 支持 7 个聊天平台：Telegram、Discord、Slack、飞书、QQ、企业微信、微信。可通过基类扩展。 |
| **Web UI 控制台** | 现代化深色风格 Web 界面，支持实时流式聊天、提供商健康监控、会话管理、工具查看和配置编辑。 |
| **配置热重载** | 基于文件监听的配置重载，并支持通过 Pydantic Settings 叠加环境变量。 |
| **Cron 调度器** | 可用 cron 表达式调度周期性 Agent 任务。 |
| **健康监控** | 提供心跳服务，定期检查各 LLM 提供商健康状态。 |

## 架构

```text
ultrabot/
├── agent/          # 核心 Agent 与工具调用循环
│   ├── agent.py    # 支持并行工具执行的 Agent 类
│   └── prompts.py  # 系统提示词构建 + 专家提示词注入
├── bus/            # 带死信队列的优先级消息总线
│   ├── events.py   # InboundMessage / OutboundMessage
│   └── queue.py    # MessageBus 与优先级队列
├── channels/       # 聊天平台集成（7 个适配器）
│   ├── base.py     # BaseChannel ABC + ChannelManager
│   ├── telegram.py # Telegram（python-telegram-bot，轮询）
│   ├── discord_channel.py  # Discord（discord.py）
│   ├── slack_channel.py    # Slack（slack-sdk，Socket Mode）
│   ├── feishu.py   # 飞书 / Lark（lark-oapi，WebSocket）
│   ├── qq.py       # QQ Bot（qq-botpy，WebSocket）
│   ├── wecom.py    # 企业微信（wecom-aibot-sdk，WebSocket）
│   └── weixin.py   # 微信（HTTP long-poll，AES 媒体）
├── cli/            # CLI 命令（Typer）
│   ├── commands.py # onboard、agent、gateway、status、experts
│   └── stream.py   # 终端流式渲染器
├── config/         # 基于 Pydantic 的配置与热重载
│   ├── schema.py   # 全部配置 schema
│   ├── loader.py   # 加载 / 保存 / 监听配置
│   └── paths.py    # 路径工具
├── cron/           # Cron 任务调度器
├── experts/        # 专家人格系统（内置 170 个专家）
│   ├── parser.py   # 将 Markdown 人格解析为 ExpertPersona
│   ├── registry.py # 加载、索引、搜索专家
│   ├── router.py   # 按消息路由到专家（@slug、粘性、自动）
│   ├── sync.py     # 从 GitHub 同步人格
│   └── personas/   # 170 个内置 .md 文件（17 个部门）
├── gateway/        # 网关服务编排
├── heartbeat/      # 提供商健康监控
├── mcp/            # MCP 客户端（stdio + HTTP）
├── providers/      # LLM 提供商抽象层
│   ├── base.py     # 带重试的 LLMProvider ABC
│   ├── circuit_breaker.py  # 熔断器模式
│   ├── manager.py  # 带故障转移的 ProviderManager
│   ├── registry.py # 提供商注册表（12+ 提供商）
│   ├── openai_compat.py    # OpenAI 兼容提供商
│   └── anthropic_provider.py # Anthropic 原生提供商
├── security/       # 限流、访问控制、输入清洗
├── session/        # 持久化会话管理
├── skills/         # 支持热重载的插件系统
├── tools/          # 内置工具 + 注册表
│   ├── base.py     # Tool ABC + ToolRegistry
│   └── builtin.py  # 8 个内置工具
├── utils/          # 帮助函数与通用工具
├── webui/          # Web UI 控制台（FastAPI + WebSocket）
│   ├── app.py      # REST API + WebSocket 流式后端
│   └── static/     # 前端（HTML/CSS/JS，零构建步骤）
└── templates/      # 默认配置模板
```

## 安装

**从源码安装**（推荐开发时使用）：
```bash
git clone https://github.com/junfhu/ultrabot.git
cd ultrabot
pip install -e .
```

**按渠道安装可选依赖：**
```bash
pip install -e ".[telegram]"   # Telegram
pip install -e ".[discord]"    # Discord
pip install -e ".[slack]"      # Slack
pip install -e ".[feishu]"     # 飞书 / Lark
pip install -e ".[qq]"         # QQ Bot
pip install -e ".[wecom]"      # 企业微信
pip install -e ".[weixin]"     # 微信
pip install -e ".[mcp]"        # MCP 支持
pip install -e ".[all]"        # 全量安装
```

**开发依赖：**
```bash
pip install -e ".[dev]"
```

## 快速开始

### 1. 初始化

```bash
ultrabot onboard
```

### 2. 配置（`~/.ultrabot/config.json`）

设置 API Key（例如 OpenRouter）：
```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  }
}
```

设置模型：
```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4-20250514",
      "provider": "auto"
    }
  }
}
```

### 3. 聊天

```bash
# 交互模式
ultrabot agent

# 单次消息
ultrabot agent -m "What is the capital of France?"

# 查看状态
ultrabot status
```

### 4. 启动 Gateway（用于聊天渠道）

```bash
ultrabot gateway
```

### 5. 启动 Web UI

```bash
# 安装 Web UI 依赖
pip install -e ".[webui]"

# 启动控制台
ultrabot webui

# 自定义主机 / 端口
ultrabot webui --host 0.0.0.0 --port 9000
```

在浏览器中打开 `http://127.0.0.1:18800`，即可访问：
- **Chat**：与 AI 助手进行实时流式对话
- **Providers**：查看所有已配置 LLM 提供商的实时健康状态
- **Sessions**：浏览、切换和管理会话
- **Tools**：查看所有已注册工具及其参数 schema
- **Config**：直接在浏览器中编辑配置

## 专家系统

ultrabot 内置了覆盖 **17 个专业部门** 的 **170 个领域专家人格**，由 [agency-agents-zh](https://github.com/jnMetaCode/agency-agents-zh) 提供支持，开箱即用，无需额外配置。

### 部门

| 部门 | 专家数 | 示例 |
|------|--------|------|
| engineering | 27 | frontend-developer、backend-architect、devops-automator、security-engineer、SRE |
| marketing | 32 | growth-hacker、seo-specialist、content-creator、tiktok-strategist、xiaohongshu-operator |
| specialized | 33 | prompt-engineer、mcp-builder、agents-orchestrator、blockchain-security-auditor |
| design | 8 | ui-designer、ux-architect、brand-guardian、visual-storyteller |
| testing | 9 | evidence-collector、reality-checker、performance-benchmarker、api-tester |
| sales | 8 | deal-strategist、pipeline-analyst、outbound-strategist、proposal-strategist |
| paid-media | 7 | ppc-strategist、programmatic-buyer、tracking-specialist |
| academic | 6 | anthropologist、historian、psychologist、study-planner |
| spatial-computing | 6 | xr-interface-architect、visionos-engineer、xr-immersive-developer |
| project-management | 6 | studio-producer、sprint-prioritizer、jira-workflow-steward |
| product | 5 | product-manager、trend-researcher、feedback-synthesizer |
| game-development | 5 | game-designer、level-designer、narrative-designer、technical-artist |
| support | 8 | customer-responder、data-analyst、infrastructure-operator |
| finance | 3 | financial-forecaster、fraud-detector、invoice-manager |
| supply-chain | 3 | logistics、procurement、warehouse |
| hr | 2 | recruiter、performance-reviewer |
| legal | 2 | contract-reviewer、policy-writer |

### 使用专家

**CLI 管理：**
```bash
# 列出所有专家
ultrabot experts list

# 按部门筛选
ultrabot experts list -d engineering

# 按关键词搜索
ultrabot experts search "frontend"

# 查看详细信息
ultrabot experts info engineering-frontend-developer

# 从 GitHub 同步最新人格（可选，项目已内置）
ultrabot experts sync
```

**在聊天中使用（交互模式或渠道内）：**
```text
# 使用 @slug 激活专家
@engineering-frontend-developer How do I optimize React performance?

# 或通过 /expert 命令
/expert product-manager What's the roadmap for Q2?

# 专家会在后续消息中持续生效（粘性会话）
What about Vue performance?          # 仍然使用 frontend-developer

# 列出所有可用专家
/experts

# 在聊天中搜索专家
/experts database

# 切换专家
@marketing-seo-specialist Audit my site's SEO

# 返回默认 ultrabot
/expert off
```

### 专家配置

```json
{
  "experts": {
    "enabled": true,
    "directory": "~/.ultrabot/experts",
    "autoRoute": false,
    "autoSync": false,
    "departments": []
  }
}
```

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `enabled` | `true` | 启用或禁用专家系统 |
| `directory` | `~/.ultrabot/experts` | 自定义人格目录（会覆盖内置人格） |
| `autoRoute` | `false` | 由 LLM 自动为每条消息选择最合适的专家 |
| `autoSync` | `false` | 启动时自动从 GitHub 下载最新人格 |
| `departments` | `[]`（全部） | 过滤加载的部门，例如 `["engineering", "design"]` |

## Providers

ultrabot 会根据模型名自动识别 provider，你也可以显式设置 `provider`。

| Provider | 关键词 | API Base |
|----------|--------|----------|
| `openrouter` | openrouter | openrouter.ai/api/v1 |
| `anthropic` | anthropic、claude | （原生 SDK） |
| `openai` | openai、gpt | （原生 SDK） |
| `deepseek` | deepseek | api.deepseek.com |
| `gemini` | gemini | generativelanguage.googleapis.com |
| `groq` | groq | api.groq.com/openai/v1 |
| `moonshot` | moonshot、kimi | api.moonshot.cn/v1 |
| `minimax` | minimax | api.minimax.chat/v1 |
| `mistral` | mistral | api.mistral.ai/v1 |
| `ollama` | ollama | localhost:11434/v1 |
| `vllm` | vllm | localhost:8000/v1 |
| `custom` | （任意） | （用户自定义） |

### 添加自定义 Provider

```json
{
  "providers": {
    "custom": {
      "apiKey": "your-key",
      "apiBase": "https://api.your-provider.com/v1"
    }
  },
  "agents": {
    "defaults": {
      "model": "your-model-name"
    }
  }
}
```

### 熔断故障转移

配置多个 provider。当主 provider 失败时（连续 5 次错误），ultrabot 会自动路由到下一个健康 provider：

```json
{
  "providers": {
    "anthropic": { "apiKey": "sk-ant-xxx", "priority": 1 },
    "openai": { "apiKey": "sk-xxx", "priority": 2 },
    "deepseek": { "apiKey": "sk-xxx", "priority": 3 }
  }
}
```

## 聊天渠道

| 渠道 | 传输方式 | 依赖要求 | 安装方式 |
|------|----------|----------|----------|
| **Telegram** | Bot API（轮询） | 通过 @BotFather 获取 Bot Token | `pip install -e ".[telegram]"` |
| **Discord** | discord.py | Bot Token + Message Content intent | `pip install -e ".[discord]"` |
| **Slack** | Socket Mode | Bot Token + App-Level Token | `pip install -e ".[slack]"` |
| **飞书** | WebSocket（lark-oapi） | App ID + App Secret | `pip install -e ".[feishu]"` |
| **QQ** | WebSocket（qq-botpy） | Bot AppID + Token | `pip install -e ".[qq]"` |
| **企业微信** | WebSocket（wecom-aibot-sdk） | Corp ID + Agent ID + Secret | `pip install -e ".[wecom]"` |
| **微信** | HTTP long-poll（ilinkai） | ilinkai API token | `pip install -e ".[weixin]"` |

### 渠道配置示例

**Telegram：**
```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

**飞书：**
```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxxxx",
      "appSecret": "xxxxx"
    }
  }
}
```

**QQ：**
```json
{
  "channels": {
    "qq": {
      "enabled": true,
      "appId": "102xxxxx",
      "token": "xxxxx"
    }
  }
}
```

**企业微信：**
```json
{
  "channels": {
    "wecom": {
      "enabled": true,
      "corpId": "wwxxxxx",
      "agentId": 1000002,
      "secret": "xxxxx"
    }
  }
}
```

**微信：**
```json
{
  "channels": {
    "weixin": {
      "enabled": true,
      "token": "YOUR_ILINKAI_TOKEN"
    }
  }
}
```

## 内置工具

| 工具 | 说明 |
|------|------|
| `web_search` | 通过 DuckDuckGo（或已配置 provider）进行网页搜索 |
| `fetch_url` | 获取 URL 内容并返回（可选转换为 Markdown） |
| `read_file` | 读取文件内容，支持 offset / limit |
| `write_file` | 写入文件内容 |
| `list_files` | 列出目录内容及文件信息 |
| `delete_file` | 删除文件 |
| `exec_shell` | 在超时控制下执行 shell 命令 |
| `python_repl` | 在隔离子进程中执行 Python 代码 |

所有文件与 shell 工具都被限制在配置的工作区目录中运行。

## MCP（Model Context Protocol）

连接外部工具服务：

```json
{
  "tools": {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
      },
      "remote-server": {
        "url": "https://example.com/mcp/",
        "headers": { "Authorization": "Bearer xxx" }
      }
    }
  }
}
```

## 安全

内置安全层，提供：

- **限流**：滑动窗口 token bucket 算法（可配置 RPM 与 burst）
- **访问控制**：按频道设置 allow list，并支持通配符
- **输入清洗**：长度限制、阻断正则模式、控制字符剔除
- **工作区沙箱**：文件与 shell 工具仅允许访问工作区目录

```json
{
  "security": {
    "rateLimitRpm": 60,
    "rateLimitBurst": 10,
    "maxInputLength": 100000,
    "blockedPatterns": ["password\\s*="]
  }
}
```

## Cron 调度器

在 `~/.ultrabot/cron/` 中创建计划任务：

```json
{
  "name": "daily-summary",
  "schedule": "0 9 * * *",
  "message": "Give me a summary of today's news",
  "channel": "telegram",
  "chatId": "123456",
  "enabled": true
}
```

## 配置参考

配置文件：`~/.ultrabot/config.json`

| 配置段 | 关键项 |
|--------|--------|
| `providers` | 各 provider 的 API key、base URL、优先级 |
| `agents.defaults` | model、provider、maxTokens、temperature、maxToolIterations、reasoningEffort、timezone |
| `experts` | enabled、directory、autoRoute、autoSync、departments |
| `channels` | sendProgress、sendToolHints、sendMaxRetries、各渠道配置 |
| `gateway` | host、port、heartbeat 设置 |
| `tools` | Web 搜索、命令执行、工作区限制、MCP servers |
| `security` | 限流、输入长度、阻断模式 |

环境变量可通过 `ULTRABOT_` 前缀与 `__` 嵌套覆盖配置：
```bash
export ULTRABOT_PROVIDERS__OPENROUTER__API_KEY=sk-or-v1-xxx
export ULTRABOT_EXPERTS__AUTO_ROUTE=true
```

## 设计文档

- **[高层设计（HLD）](docs/HLD.md)**：系统架构、组件概览、数据流、设计模式
- **[低层设计（LLD）](docs/LLD.md)**：详细类设计、算法、状态机、时序图

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试（196 个测试）
pytest

# 带覆盖率运行
pytest --cov=ultrabot

# Lint
ruff check ultrabot/
```

## 项目统计

| 指标 | 数值 |
|------|------|
| Python 源码文件 | 57 |
| 代码行数 | ~11,765 |
| 测试文件 | 13 |
| 测试用例 | 196 |
| LLM providers | 12+ |
| 聊天渠道 | 7 |
| 内置工具 | 8 |
| 专家人格 | 170 |
| 专家部门 | 17 |

## 与 nanobot 对比

| 特性 | nanobot | ultrabot |
|------|---------|----------|
| 熔断故障转移 | 否 | 是 |
| 优先级消息队列 | 否 | 是（带死信） |
| 会话持久化 | JSON 文件 | JSON 文件 + TTL + 上下文裁剪 |
| 并行工具执行 | 串行 | 并发（`asyncio.gather`） |
| 插件热重载 | 否 | 是 |
| 安全层 | 基础 allowFrom | 限流 + 清洗 + ACL |
| 配置热重载 | 否 | 是（文件监听） |
| MCP 支持 | 是 | 是（stdio + HTTP） |
| Provider 数量 | 20+ | 12+（可扩展） |
| 渠道数量 | 12+ | 7（基础类可扩展） |
| 专家系统 | 否 | 170 个专家，17 个部门 |
| Web UI | 否 | 是（FastAPI + WebSocket 流式） |
| 代码规模 | ~5000 行 | ~11,765 行 |
| Python | >=3.11 | >=3.11 |

## 许可证

MIT
