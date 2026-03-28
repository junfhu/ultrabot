/**
 * Ultrabot Web UI - Single Page Application
 *
 * A client-side SPA for the Ultrabot personal AI assistant.
 * Connects to a FastAPI backend via REST and WebSocket APIs.
 *
 * No external dependencies. Pure ES6+ JavaScript.
 */
(function () {
    "use strict";

    // =========================================================================
    // Section 1: Utilities
    // =========================================================================

    function escapeHtml(str) {
        if (typeof str !== "string") return "";
        var map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" };
        return str.replace(/[&<>"']/g, function (ch) { return map[ch]; });
    }

    function formatTimestamp(date) {
        try {
            var d = date instanceof Date ? date : new Date(date);
            if (isNaN(d.getTime())) return "";
            var now = new Date();
            var diff = now - d;
            if (diff < 60000) return "just now";
            if (diff < 3600000) return Math.floor(diff / 60000) + "m ago";
            if (diff < 86400000) return Math.floor(diff / 3600000) + "h ago";
            return d.toLocaleDateString() + " " + d.toLocaleTimeString();
        } catch (e) { return ""; }
    }

    function debounce(fn, delay) {
        var timer = null;
        return function () {
            var ctx = this, args = arguments;
            clearTimeout(timer);
            timer = setTimeout(function () { fn.apply(ctx, args); }, delay);
        };
    }

    /** Get a nested value from an object by dot-separated path. */
    function getNestedValue(obj, path) {
        if (!obj || !path) return undefined;
        var parts = path.split(".");
        var cur = obj;
        for (var i = 0; i < parts.length; i++) {
            if (cur == null) return undefined;
            cur = cur[parts[i]];
        }
        return cur;
    }

    /** Set a nested value in an object by dot-separated path. */
    function setNestedValue(obj, path, value) {
        if (!obj || !path) return;
        var parts = path.split(".");
        var cur = obj;
        for (var i = 0; i < parts.length - 1; i++) {
            if (cur[parts[i]] == null || typeof cur[parts[i]] !== "object") cur[parts[i]] = {};
            cur = cur[parts[i]];
        }
        cur[parts[parts.length - 1]] = value;
    }

    /** Deep clone a plain object. */
    function deepClone(obj) {
        return JSON.parse(JSON.stringify(obj));
    }

    // =========================================================================
    // Section 2: i18n (Internationalisation)
    // =========================================================================

    var TRANSLATIONS = {
        "zh-CN": {
            "nav.chat": "对话", "nav.providers": "提供商", "nav.sessions": "会话",
            "nav.tools": "工具", "nav.config": "配置",
            "common.save": "保存", "common.reload": "重新加载", "common.refresh": "刷新",
            "common.delete": "删除", "common.cancel": "取消", "common.confirm": "确认",
            "common.close": "关闭", "common.view": "查看", "common.switch": "切换",
            "common.loading": "加载中...", "common.saving": "保存中...",
            "chat.title": "对话", "chat.newChat": "新对话",
            "chat.welcome.title": "欢迎使用 ultrabot",
            "chat.welcome.desc": "您的个人 AI 助手，在下方开始对话。",
            "chat.input.placeholder": "发送消息给 ultrabot...",
            "chat.notConnected": "未连接到服务器，正在重连...",
            "chat.waitResponse": "请等待当前回复完成。",
            "providers.title": "提供商", "providers.noProviders": "未配置提供商。",
            "providers.healthy": "正常", "providers.unhealthy": "异常",
            "providers.loadFailed": "加载提供商失败: ", "providers.status": "状态: ",
            "sessions.title": "会话", "sessions.noSessions": "没有活跃会话。",
            "sessions.current": "当前", "sessions.messages": "消息",
            "sessions.switchedTo": "已切换到会话: ", "sessions.deleted": "会话已删除: ",
            "sessions.cannotDeleteActive": "无法删除当前会话，请先切换到其他会话。",
            "sessions.noMessages": "此会话没有消息。",
            "sessions.loadFailed": "加载会话失败: ", "sessions.deleteFailed": "删除会话失败: ",
            "sessions.messagesFailed": "加载消息失败: ",
            "tools.title": "工具", "tools.noTools": "没有可用工具。",
            "tools.parameters": "参数", "tools.required": "必填",
            "tools.loadFailed": "加载工具失败: ",
            "config.title": "配置", "config.saved": "配置保存成功。",
            "config.saveFailed": "保存配置失败: ", "config.loaded": "配置已加载。",
            "config.loadFailed": "加载配置失败: ", "config.invalidJson": "无效的 JSON: ",
            "config.tab.agents": "代理", "config.tab.providers": "提供商",
            "config.tab.channels": "渠道", "config.tab.gateway": "网关",
            "config.tab.tools": "工具", "config.tab.security": "安全",
            "config.tab.experts": "专家", "config.tab.json": "JSON",
            "config.agents.title": "代理默认设置",
            "config.agents.workspace": "工作空间", "config.agents.workspace.hint": "代理的默认工作目录",
            "config.agents.model": "模型", "config.agents.model.hint": "默认使用的 AI 模型",
            "config.agents.provider": "提供商", "config.agents.provider.hint": "默认模型提供商",
            "config.agents.maxTokens": "最大 Token 数", "config.agents.maxTokens.hint": "单次回复的最大 Token 数量",
            "config.agents.contextWindowTokens": "上下文窗口", "config.agents.contextWindowTokens.hint": "模型的上下文窗口大小",
            "config.agents.temperature": "温度", "config.agents.temperature.hint": "采样温度，0-2，越高越随机",
            "config.agents.maxToolIterations": "最大工具迭代", "config.agents.maxToolIterations.hint": "单次对话中工具调用的最大次数",
            "config.agents.reasoningEffort": "推理力度", "config.agents.reasoningEffort.hint": "推理时投入的计算力度",
            "config.agents.timezone": "时区", "config.agents.timezone.hint": "代理使用的时区",
            "config.providers.title": "模型提供商设置",
            "config.providers.apiKey": "API 密钥", "config.providers.apiBase": "API 地址",
            "config.providers.enabled": "启用", "config.providers.priority": "优先级",
            "config.providers.priority.hint": "数字越小优先级越高",
            "config.providers.extraHeaders": "额外请求头 (JSON)",
            "config.channels.title": "渠道设置",
            "config.channels.sendProgress": "发送进度信息",
            "config.channels.sendToolHints": "发送工具提示",
            "config.channels.sendMaxRetries": "最大发送重试次数",
            "config.gateway.title": "网关设置",
            "config.gateway.host": "主机地址", "config.gateway.port": "端口",
            "config.gateway.heartbeat": "心跳设置",
            "config.gateway.heartbeat.enabled": "启用心跳",
            "config.gateway.heartbeat.intervalS": "心跳间隔（秒）",
            "config.gateway.heartbeat.keepRecentMessages": "保留最近消息数",
            "config.tools.title": "工具设置",
            "config.tools.restrictToWorkspace": "限制到工作空间",
            "config.tools.web": "网页搜索", "config.tools.web.proxy": "代理地址",
            "config.tools.web.search.provider": "搜索提供商",
            "config.tools.web.search.apiKey": "搜索 API 密钥",
            "config.tools.web.search.baseUrl": "搜索基础 URL",
            "config.tools.web.search.maxResults": "最大结果数",
            "config.tools.exec": "命令执行", "config.tools.exec.enable": "启用命令执行",
            "config.tools.exec.timeout": "超时时间（秒）",
            "config.tools.exec.pathAppend": "PATH 追加（逗号分隔）",
            "config.tools.mcpServers": "MCP 服务",
            "config.tools.mcpServers.command": "命令",
            "config.tools.mcpServers.args": "参数（逗号分隔）",
            "config.tools.mcpServers.env": "环境变量 (JSON)",
            "config.tools.mcpServers.add": "添加 MCP 服务",
            "config.tools.mcpServers.remove": "删除",
            "config.security.title": "安全设置",
            "config.security.rateLimitRpm": "速率限制（请求/分钟）",
            "config.security.rateLimitBurst": "速率限制突发量",
            "config.security.maxInputLength": "最大输入长度",
            "config.security.blockedPatterns": "屏蔽模式（逗号分隔）",
            "config.experts.title": "专家设置",
            "config.experts.enabled": "启用专家系统", "config.experts.directory": "专家目录",
            "config.experts.autoRoute": "自动路由", "config.experts.autoSync": "自动同步",
            "option.low": "低", "option.medium": "中", "option.high": "高",
            "theme.light": "浅色", "theme.dark": "深色",
            "lang.label": "中文",
            "toast.connected": "已连接到服务器",
            "toast.backendUnreachable": "后端不可达: ",
            "version": "ultrabot v0.1.0"
        },
        "en": {
            "nav.chat": "Chat", "nav.providers": "Providers", "nav.sessions": "Sessions",
            "nav.tools": "Tools", "nav.config": "Config",
            "common.save": "Save", "common.reload": "Reload", "common.refresh": "Refresh",
            "common.delete": "Delete", "common.cancel": "Cancel", "common.confirm": "Confirm",
            "common.close": "Close", "common.view": "View", "common.switch": "Switch",
            "common.loading": "Loading...", "common.saving": "Saving...",
            "chat.title": "Chat", "chat.newChat": "New Chat",
            "chat.welcome.title": "Welcome to ultrabot",
            "chat.welcome.desc": "Your personal AI assistant. Start a conversation below.",
            "chat.input.placeholder": "Message ultrabot...",
            "chat.notConnected": "Not connected. Reconnecting...",
            "chat.waitResponse": "Please wait for the current response.",
            "providers.title": "Providers", "providers.noProviders": "No providers configured.",
            "providers.healthy": "Healthy", "providers.unhealthy": "Unhealthy",
            "providers.loadFailed": "Failed to load providers: ", "providers.status": "Status: ",
            "sessions.title": "Sessions", "sessions.noSessions": "No active sessions.",
            "sessions.current": "Current", "sessions.messages": "Messages",
            "sessions.switchedTo": "Switched to session: ", "sessions.deleted": "Session deleted: ",
            "sessions.cannotDeleteActive": "Cannot delete active session. Switch first.",
            "sessions.noMessages": "No messages in this session.",
            "sessions.loadFailed": "Failed to load sessions: ",
            "sessions.deleteFailed": "Failed to delete session: ",
            "sessions.messagesFailed": "Failed to load messages: ",
            "tools.title": "Tools", "tools.noTools": "No tools available.",
            "tools.parameters": "Parameters", "tools.required": "required",
            "tools.loadFailed": "Failed to load tools: ",
            "config.title": "Configuration", "config.saved": "Configuration saved.",
            "config.saveFailed": "Failed to save: ", "config.loaded": "Configuration loaded.",
            "config.loadFailed": "Failed to load: ", "config.invalidJson": "Invalid JSON: ",
            "config.tab.agents": "Agents", "config.tab.providers": "Providers",
            "config.tab.channels": "Channels", "config.tab.gateway": "Gateway",
            "config.tab.tools": "Tools", "config.tab.security": "Security",
            "config.tab.experts": "Experts", "config.tab.json": "JSON",
            "config.agents.title": "Agent Defaults",
            "config.agents.workspace": "Workspace", "config.agents.workspace.hint": "Default working directory",
            "config.agents.model": "Model", "config.agents.model.hint": "Default AI model",
            "config.agents.provider": "Provider", "config.agents.provider.hint": "Default model provider",
            "config.agents.maxTokens": "Max Tokens", "config.agents.maxTokens.hint": "Max tokens per response",
            "config.agents.contextWindowTokens": "Context Window", "config.agents.contextWindowTokens.hint": "Model context window size",
            "config.agents.temperature": "Temperature", "config.agents.temperature.hint": "Sampling temperature, 0-2",
            "config.agents.maxToolIterations": "Max Tool Iterations", "config.agents.maxToolIterations.hint": "Max tool calls per turn",
            "config.agents.reasoningEffort": "Reasoning Effort", "config.agents.reasoningEffort.hint": "Computation effort for reasoning",
            "config.agents.timezone": "Timezone", "config.agents.timezone.hint": "Agent timezone",
            "config.providers.title": "Provider Settings",
            "config.providers.apiKey": "API Key", "config.providers.apiBase": "API Base URL",
            "config.providers.enabled": "Enabled", "config.providers.priority": "Priority",
            "config.providers.priority.hint": "Lower number = higher priority",
            "config.providers.extraHeaders": "Extra Headers (JSON)",
            "config.channels.title": "Channel Settings",
            "config.channels.sendProgress": "Send Progress",
            "config.channels.sendToolHints": "Send Tool Hints",
            "config.channels.sendMaxRetries": "Max Send Retries",
            "config.gateway.title": "Gateway Settings",
            "config.gateway.host": "Host", "config.gateway.port": "Port",
            "config.gateway.heartbeat": "Heartbeat",
            "config.gateway.heartbeat.enabled": "Enable Heartbeat",
            "config.gateway.heartbeat.intervalS": "Interval (seconds)",
            "config.gateway.heartbeat.keepRecentMessages": "Keep Recent Messages",
            "config.tools.title": "Tool Settings",
            "config.tools.restrictToWorkspace": "Restrict to Workspace",
            "config.tools.web": "Web Search", "config.tools.web.proxy": "Proxy URL",
            "config.tools.web.search.provider": "Search Provider",
            "config.tools.web.search.apiKey": "Search API Key",
            "config.tools.web.search.baseUrl": "Search Base URL",
            "config.tools.web.search.maxResults": "Max Results",
            "config.tools.exec": "Command Execution",
            "config.tools.exec.enable": "Enable Execution",
            "config.tools.exec.timeout": "Timeout (seconds)",
            "config.tools.exec.pathAppend": "PATH Append (comma-separated)",
            "config.tools.mcpServers": "MCP Servers",
            "config.tools.mcpServers.command": "Command",
            "config.tools.mcpServers.args": "Args (comma-separated)",
            "config.tools.mcpServers.env": "Env (JSON)",
            "config.tools.mcpServers.add": "Add MCP Server",
            "config.tools.mcpServers.remove": "Remove",
            "config.security.title": "Security Settings",
            "config.security.rateLimitRpm": "Rate Limit (req/min)",
            "config.security.rateLimitBurst": "Rate Limit Burst",
            "config.security.maxInputLength": "Max Input Length",
            "config.security.blockedPatterns": "Blocked Patterns (comma-separated)",
            "config.experts.title": "Expert Settings",
            "config.experts.enabled": "Enable Experts", "config.experts.directory": "Experts Directory",
            "config.experts.autoRoute": "Auto Route", "config.experts.autoSync": "Auto Sync",
            "option.low": "Low", "option.medium": "Medium", "option.high": "High",
            "theme.light": "Light", "theme.dark": "Dark",
            "lang.label": "EN",
            "toast.connected": "Connected to server",
            "toast.backendUnreachable": "Backend unreachable: ",
            "version": "ultrabot v0.1.0"
        }
    };

    /**
     * Translate a key to the current language.
     * Falls back to English, then to the key itself.
     */
    function t(key) {
        var lang = state ? state.language : "zh-CN";
        var dict = TRANSLATIONS[lang] || TRANSLATIONS["zh-CN"];
        if (dict[key] !== undefined) return dict[key];
        var fallback = TRANSLATIONS["en"];
        if (fallback && fallback[key] !== undefined) return fallback[key];
        return key;
    }

    // =========================================================================
    // Section 3: Markdown Renderer
    // =========================================================================

    function renderMarkdown(text) {
        if (typeof text !== "string" || text.length === 0) return "";
        var codeStash = [];
        function stash(content) { var idx = codeStash.length; codeStash.push(content); return "\x00CODE" + idx + "\x00"; }

        text = text.replace(/```(\w*)\n([\s\S]*?)```/g, function (_, lang, code) {
            var cls = lang ? ' class="language-' + escapeHtml(lang) + '"' : "";
            return stash("<pre><code" + cls + ">" + escapeHtml(code.replace(/\n$/, "")) + "</code></pre>");
        });
        text = text.replace(/`([^`\n]+)`/g, function (_, code) {
            return stash("<code>" + escapeHtml(code) + "</code>");
        });

        var lines = text.split("\n");
        var html = [];
        var i = 0;

        while (i < lines.length) {
            var line = lines[i];

            if (line.indexOf("|") !== -1 && i + 1 < lines.length && /^\|?[\s\-:|]+\|/.test(lines[i + 1])) {
                var tableRows = [];
                while (i < lines.length && lines[i].indexOf("|") !== -1) { tableRows.push(lines[i]); i++; }
                html.push(buildTable(tableRows));
                continue;
            }

            var headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
            if (headingMatch) {
                var level = headingMatch[1].length;
                html.push("<h" + level + ">" + inlineFormat(headingMatch[2]) + "</h" + level + ">");
                i++; continue;
            }

            if (/^[\s]*[-*+]\s+/.test(line)) {
                var listItems = [];
                while (i < lines.length && /^[\s]*[-*+]\s+/.test(lines[i])) { listItems.push(lines[i].replace(/^[\s]*[-*+]\s+/, "")); i++; }
                html.push("<ul>" + listItems.map(function (li) { return "<li>" + inlineFormat(li) + "</li>"; }).join("") + "</ul>");
                continue;
            }

            if (/^[\s]*\d+\.\s+/.test(line)) {
                var olItems = [];
                while (i < lines.length && /^[\s]*\d+\.\s+/.test(lines[i])) { olItems.push(lines[i].replace(/^[\s]*\d+\.\s+/, "")); i++; }
                html.push("<ol>" + olItems.map(function (li) { return "<li>" + inlineFormat(li) + "</li>"; }).join("") + "</ol>");
                continue;
            }

            if (/^[-*_]{3,}\s*$/.test(line)) { html.push("<hr>"); i++; continue; }
            if (line.trim() === "") { html.push(""); i++; continue; }

            var paraLines = [];
            while (i < lines.length && lines[i].trim() !== "" &&
                !/^#{1,6}\s+/.test(lines[i]) && !/^[\s]*[-*+]\s+/.test(lines[i]) &&
                !/^[\s]*\d+\.\s+/.test(lines[i]) && !/^[-*_]{3,}\s*$/.test(lines[i]) &&
                !(lines[i].indexOf("|") !== -1 && i + 1 < lines.length && /^\|?[\s\-:|]+\|/.test(lines[i + 1]))
            ) { paraLines.push(lines[i]); i++; }
            if (paraLines.length > 0) html.push("<p>" + inlineFormat(paraLines.join("\n")) + "</p>");
        }

        var result = html.join("\n");
        result = result.replace(/\x00CODE(\d+)\x00/g, function (_, idx) { return codeStash[parseInt(idx, 10)]; });
        return result;

        function inlineFormat(s) {
            s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
            s = s.replace(/__(.+?)__/g, "<strong>$1</strong>");
            s = s.replace(/\*(.+?)\*/g, "<em>$1</em>");
            s = s.replace(/(?<!\w)_(.+?)_(?!\w)/g, "<em>$1</em>");
            s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function (_, txt, url) {
                return '<a href="' + escapeHtml(url) + '" target="_blank" rel="noopener">' + txt + "</a>";
            });
            s = s.replace(/  \n/g, "<br>");
            s = s.replace(/\n/g, "<br>");
            return s;
        }

        function buildTable(rows) {
            function parseCells(row) { return row.replace(/^\|/, "").replace(/\|$/, "").split("|").map(function (c) { return c.trim(); }); }
            if (rows.length < 2) return escapeHtml(rows.join("\n"));
            var headerCells = parseCells(rows[0]);
            var bodyRows = rows.slice(2);
            var out = "<table><thead><tr>";
            headerCells.forEach(function (cell) { out += "<th>" + inlineFormat(cell) + "</th>"; });
            out += "</tr></thead><tbody>";
            bodyRows.forEach(function (row) {
                if (/^\|?[\s\-:|]+\|?$/.test(row)) return;
                var cells = parseCells(row);
                out += "<tr>";
                cells.forEach(function (cell) { out += "<td>" + inlineFormat(cell) + "</td>"; });
                out += "</tr>";
            });
            out += "</tbody></table>";
            return out;
        }
    }

    // =========================================================================
    // Section 4: Toast Notification System
    // =========================================================================

    var toastContainer = null;

    function ensureToastContainer() {
        if (toastContainer) return;
        toastContainer = document.getElementById("toast-container");
        if (!toastContainer) {
            toastContainer = document.createElement("div");
            toastContainer.id = "toast-container";
            toastContainer.setAttribute("style", "position:fixed;top:16px;right:16px;z-index:10000;display:flex;flex-direction:column;gap:8px;");
            document.body.appendChild(toastContainer);
        }
    }

    function showToast(message, type) {
        type = type || "info";
        ensureToastContainer();
        var toast = document.createElement("div");
        toast.className = "toast toast-" + type;
        toast.textContent = message;
        toastContainer.appendChild(toast);
        toast.offsetHeight;
        toast.classList.add("toast-visible");
        setTimeout(function () {
            toast.classList.remove("toast-visible");
            toast.classList.add("toast-hiding");
            setTimeout(function () { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 300);
        }, 3000);
    }

    // =========================================================================
    // Section 5: Application State
    // =========================================================================

    var state = {
        currentPage: "chat",
        currentSessionKey: "web:default",
        ws: null,
        isStreaming: false,
        messages: [],
        reconnectAttempts: 0,
        reconnectTimer: null,
        providersRefreshTimer: null,
        language: localStorage.getItem("ultrabot-lang") || "zh-CN",
        configData: null,
        configTab: "agents",
    };

    // =========================================================================
    // Section 6: API Helpers
    // =========================================================================

    var API_BASE = "";

    function apiFetch(url, options) {
        options = options || {};
        options.headers = options.headers || {};
        if (options.body && typeof options.body === "string") {
            options.headers["Content-Type"] = options.headers["Content-Type"] || "application/json";
        }
        return fetch(API_BASE + url, options).then(function (res) {
            if (!res.ok) {
                return res.text().then(function (body) {
                    var errMsg = "API error " + res.status;
                    try { var parsed = JSON.parse(body); if (parsed.detail) errMsg = parsed.detail; else if (parsed.message) errMsg = parsed.message; } catch (e) { if (body) errMsg = body; }
                    throw new Error(errMsg);
                });
            }
            return res.json();
        });
    }

    // =========================================================================
    // Section 7: WebSocket Management
    // =========================================================================

    var MAX_RECONNECT_DELAY = 30000;

    function connectWebSocket() {
        if (state.ws && (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)) return;
        var protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        var wsUrl = protocol + "//" + window.location.host + "/ws/chat";
        try { state.ws = new WebSocket(wsUrl); } catch (err) { console.error("[WS] Failed:", err); scheduleReconnect(); return; }

        state.ws.onopen = function () {
            console.log("[WS] Connected");
            state.reconnectAttempts = 0;
            showToast(t("toast.connected"), "success");
            updateConnectionIndicator(true);
        };

        state.ws.onmessage = function (event) {
            try { handleWsMessage(JSON.parse(event.data)); } catch (err) { console.error("[WS] Parse error:", err); }
        };

        state.ws.onclose = function (event) {
            console.log("[WS] Closed:", event.code, event.reason);
            state.ws = null;
            updateConnectionIndicator(false);
            if (state.isStreaming) { state.isStreaming = false; removeStreamingCursor(); enableInput(); }
            scheduleReconnect();
        };

        state.ws.onerror = function (err) { console.error("[WS] Error:", err); };
    }

    function scheduleReconnect() {
        if (state.reconnectTimer) return;
        var delay = Math.min(1000 * Math.pow(2, state.reconnectAttempts), MAX_RECONNECT_DELAY);
        state.reconnectAttempts++;
        state.reconnectTimer = setTimeout(function () { state.reconnectTimer = null; connectWebSocket(); }, delay);
    }

    function sendMessage(content) {
        if (!content || !content.trim()) return;
        content = content.trim();
        if (!state.ws || state.ws.readyState !== WebSocket.OPEN) { showToast(t("chat.notConnected"), "error"); connectWebSocket(); return; }
        if (state.isStreaming) { showToast(t("chat.waitResponse"), "info"); return; }

        var userMsg = { role: "user", content: content };
        state.messages.push(userMsg);
        appendMessageToChat(userMsg);

        try { state.ws.send(JSON.stringify({ type: "message", content: content, session_key: state.currentSessionKey })); }
        catch (err) { showToast(t("chat.sendFailed") + err.message, "error"); return; }

        state.isStreaming = true;
        disableInput();
        var assistantMsg = { role: "assistant", content: "" };
        state.messages.push(assistantMsg);
        appendMessageToChat(assistantMsg, true);
    }

    function handleWsMessage(data) {
        switch (data.type) {
            case "content_delta": handleContentDelta(data.content || ""); break;
            case "tool_start": handleToolStart(data.tool_name || "unknown", data.tool_call_id || ""); break;
            case "content_done": handleContentDone(data.content || ""); break;
            case "error": handleStreamError(data.message || "Unknown error"); break;
            default: console.warn("[WS] Unknown:", data.type);
        }
    }

    function handleContentDelta(chunk) {
        if (state.messages.length === 0) return;
        var lastMsg = state.messages[state.messages.length - 1];
        if (lastMsg.role !== "assistant") return;
        lastMsg.content += chunk;
        updateStreamingMessage(lastMsg.content);
    }

    function handleToolStart(toolName, toolCallId) {
        var container = document.getElementById("chat-messages");
        if (!container) return;
        var existing = document.getElementById("tool-indicator-" + toolCallId);
        if (existing) existing.parentNode.removeChild(existing);
        var indicator = document.createElement("div");
        indicator.className = "tool-indicator";
        indicator.id = "tool-indicator-" + escapeHtml(toolCallId);
        indicator.innerHTML = '<span class="tool-indicator-dot"></span> Running <strong>' + escapeHtml(toolName) + "</strong>...";
        var streamingMsg = container.querySelector(".message-streaming");
        if (streamingMsg) container.insertBefore(indicator, streamingMsg);
        else container.appendChild(indicator);
        scrollChatToBottom();
    }

    function handleContentDone(fullContent) {
        if (state.messages.length > 0) {
            var lastMsg = state.messages[state.messages.length - 1];
            if (lastMsg.role === "assistant") lastMsg.content = fullContent;
        }
        state.isStreaming = false;
        finaliseStreamingMessage(fullContent);
        removeToolIndicators();
        removeStreamingCursor();
        enableInput();
        scrollChatToBottom();
    }

    function handleStreamError(message) {
        state.isStreaming = false;
        removeStreamingCursor();
        removeToolIndicators();
        enableInput();
        showToast("Error: " + message, "error");
        var container = document.getElementById("chat-messages");
        if (container) {
            var errorDiv = document.createElement("div");
            errorDiv.className = "message message-error";
            errorDiv.innerHTML = '<div class="message-content"><p class="error-text">' + escapeHtml(message) + "</p></div>";
            container.appendChild(errorDiv);
            scrollChatToBottom();
        }
    }

    // =========================================================================
    // Section 8: Chat UI Helpers
    // =========================================================================

    function appendMessageToChat(msg, isStreaming) {
        var container = document.getElementById("chat-messages");
        if (!container) return;
        var msgDiv = document.createElement("div");
        msgDiv.className = "message message-" + escapeHtml(msg.role);
        if (isStreaming) msgDiv.classList.add("message-streaming");
        var avatarDiv = document.createElement("div");
        avatarDiv.className = "message-avatar";
        avatarDiv.textContent = msg.role === "user" ? "U" : "A";
        var contentDiv = document.createElement("div");
        contentDiv.className = "message-content";
        var markdownDiv = document.createElement("div");
        markdownDiv.className = "markdown-content";
        if (isStreaming) markdownDiv.innerHTML = '<span class="streaming-cursor"></span>';
        else markdownDiv.innerHTML = renderMarkdown(msg.content);
        contentDiv.appendChild(markdownDiv);
        msgDiv.appendChild(avatarDiv);
        msgDiv.appendChild(contentDiv);
        container.appendChild(msgDiv);
        scrollChatToBottom();
    }

    function updateStreamingMessage(content) {
        var container = document.getElementById("chat-messages");
        if (!container) return;
        var streamingMsg = container.querySelector(".message-streaming");
        if (!streamingMsg) return;
        var markdownDiv = streamingMsg.querySelector(".markdown-content");
        if (!markdownDiv) return;
        markdownDiv.innerHTML = renderMarkdown(content) + '<span class="streaming-cursor"></span>';
        scrollChatToBottom();
    }

    function finaliseStreamingMessage(fullContent) {
        var container = document.getElementById("chat-messages");
        if (!container) return;
        var streamingMsg = container.querySelector(".message-streaming");
        if (!streamingMsg) return;
        streamingMsg.classList.remove("message-streaming");
        var markdownDiv = streamingMsg.querySelector(".markdown-content");
        if (markdownDiv) markdownDiv.innerHTML = renderMarkdown(fullContent);
    }

    function removeStreamingCursor() {
        var cursors = document.querySelectorAll(".streaming-cursor");
        for (var i = 0; i < cursors.length; i++) cursors[i].parentNode.removeChild(cursors[i]);
    }

    function removeToolIndicators() {
        var indicators = document.querySelectorAll(".tool-indicator");
        for (var i = 0; i < indicators.length; i++) indicators[i].parentNode.removeChild(indicators[i]);
    }

    function scrollChatToBottom() {
        var container = document.getElementById("chat-messages");
        if (container) container.scrollTop = container.scrollHeight;
    }

    function disableInput() {
        var input = document.getElementById("chat-input");
        var btn = document.getElementById("send-btn");
        if (input) input.disabled = true;
        if (btn) btn.disabled = true;
    }

    function enableInput() {
        var input = document.getElementById("chat-input");
        var btn = document.getElementById("send-btn");
        if (input) { input.disabled = false; input.focus(); }
        if (btn) btn.disabled = false;
    }

    function updateConnectionIndicator(connected) {
        var wrapper = document.getElementById("connection-status");
        if (!wrapper) return;
        var dot = wrapper.querySelector(".status-dot");
        if (!dot) dot = wrapper;
        dot.className = "status-dot " + (connected ? "connected" : "disconnected");
        wrapper.title = connected ? t("chat.connected") : t("chat.disconnected");
    }

    function autoResizeTextarea(textarea) {
        textarea.style.height = "auto";
        textarea.style.height = Math.min(textarea.scrollHeight, 200) + "px";
    }

    // =========================================================================
    // Section 9: Router / Navigation
    // =========================================================================

    function navigateTo(page) {
        var validPages = ["chat", "providers", "sessions", "tools", "config"];
        if (validPages.indexOf(page) === -1) page = "chat";
        state.currentPage = page;
        var navItems = document.querySelectorAll(".nav-item");
        for (var i = 0; i < navItems.length; i++) {
            navItems[i].classList.toggle("active", navItems[i].dataset.page === page);
        }
        renderPage(page);
        if (page !== "providers" && state.providersRefreshTimer) {
            clearInterval(state.providersRefreshTimer);
            state.providersRefreshTimer = null;
        }
    }

    function renderPage(page) {
        switch (page) {
            case "chat": renderChatPage(); break;
            case "providers": renderProvidersPage(); break;
            case "sessions": renderSessionsPage(); break;
            case "tools": renderToolsPage(); break;
            case "config": renderConfigPage(); break;
        }
    }

    // =========================================================================
    // Section 10: Page Renderers
    // =========================================================================

    // ---- 10.1 Chat Page ----

    function renderChatPage() {
        var main = document.getElementById("main-content");
        if (!main) return;
        main.innerHTML =
            '<div class="page" style="display:flex;flex-direction:column;height:100%;">' +
                '<div class="page-header">' +
                    '<h1 class="page-title">' + escapeHtml(t("chat.title")) + '</h1>' +
                    '<div class="header-actions">' +
                        '<span class="session-selector"><span id="current-session-label" class="session-label">' + escapeHtml(state.currentSessionKey) + '</span></span>' +
                    '</div>' +
                '</div>' +
                '<div id="chat-messages" class="chat-container"></div>' +
                '<div class="input-area"><div class="input-wrapper">' +
                    '<textarea id="chat-input" class="chat-input" placeholder="' + escapeHtml(t("chat.input.placeholder")) + '" rows="1"></textarea>' +
                    '<button id="send-btn" class="send-btn" title="Send"><svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg></button>' +
                '</div></div>' +
            '</div>';

        var container = document.getElementById("chat-messages");
        if (container) {
            if (state.messages.length === 0) {
                container.innerHTML =
                    '<div class="welcome-message"><h2>' + escapeHtml(t("chat.welcome.title")) + '</h2>' +
                    '<p>' + escapeHtml(t("chat.welcome.desc")) + '</p></div>';
            } else {
                state.messages.forEach(function (msg) { appendMessageToChat(msg); });
                if (state.isStreaming && state.messages.length > 0) {
                    var lastChild = container.lastElementChild;
                    if (lastChild) {
                        lastChild.classList.add("message-streaming");
                        var md = lastChild.querySelector(".markdown-content");
                        if (md) md.innerHTML = renderMarkdown(state.messages[state.messages.length - 1].content) + '<span class="streaming-cursor"></span>';
                    }
                    disableInput();
                }
            }
        }

        var input = document.getElementById("chat-input");
        var sendBtn = document.getElementById("send-btn");
        if (input) {
            input.addEventListener("keydown", function (e) {
                if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    if (input.value.trim()) { sendMessage(input.value); input.value = ""; autoResizeTextarea(input); }
                }
            });
            input.addEventListener("input", function () { autoResizeTextarea(input); });
            if (!state.isStreaming) input.focus();
        }
        if (sendBtn) {
            sendBtn.addEventListener("click", function () {
                if (input && input.value.trim()) { sendMessage(input.value); input.value = ""; autoResizeTextarea(input); }
            });
        }
        scrollChatToBottom();
    }

    // ---- 10.2 Providers Page ----

    function renderProvidersPage() {
        var main = document.getElementById("main-content");
        if (!main) return;
        main.innerHTML =
            '<div class="page" style="display:flex;flex-direction:column;height:100%;">' +
                '<div class="page-header"><h1 class="page-title">' + escapeHtml(t("providers.title")) + '</h1>' +
                '<div class="header-actions"><button id="providers-refresh-btn" class="btn btn-ghost">' + escapeHtml(t("common.refresh")) + '</button></div></div>' +
                '<div class="page-content"><div id="providers-grid" class="providers-grid"><div class="loading-spinner"></div></div></div>' +
            '</div>';
        loadProviders();
        var refreshBtn = document.getElementById("providers-refresh-btn");
        if (refreshBtn) refreshBtn.addEventListener("click", loadProviders);
        if (state.providersRefreshTimer) clearInterval(state.providersRefreshTimer);
        state.providersRefreshTimer = setInterval(function () { if (state.currentPage === "providers") loadProviders(); }, 30000);
    }

    function loadProviders() {
        apiFetch("/api/providers").then(function (data) {
            var grid = document.getElementById("providers-grid");
            if (!grid || state.currentPage !== "providers") return;
            var providers = data.providers || {};
            var keys = Object.keys(providers);
            if (keys.length === 0) { grid.innerHTML = '<p class="empty-state">' + escapeHtml(t("providers.noProviders")) + '</p>'; return; }
            var html = "";
            keys.forEach(function (name) {
                var healthy = providers[name];
                html += '<div class="provider-card"><div class="provider-card-header">' +
                    '<span class="status-dot ' + (healthy ? "healthy" : "unhealthy") + '"></span>' +
                    '<h3>' + escapeHtml(name) + '</h3></div>' +
                    '<div class="provider-card-body"><p class="provider-status">' +
                    escapeHtml(t("providers.status")) + (healthy ? t("providers.healthy") : t("providers.unhealthy")) +
                    '</p></div></div>';
            });
            grid.innerHTML = html;
        }).catch(function (err) {
            var grid = document.getElementById("providers-grid");
            if (grid) grid.innerHTML = '<p class="error-text">' + escapeHtml(t("providers.loadFailed") + err.message) + '</p>';
        });
    }

    // ---- 10.3 Sessions Page ----

    function renderSessionsPage() {
        var main = document.getElementById("main-content");
        if (!main) return;
        main.innerHTML =
            '<div class="page" style="display:flex;flex-direction:column;height:100%;">' +
                '<div class="page-header"><h1 class="page-title">' + escapeHtml(t("sessions.title")) + '</h1>' +
                '<div class="header-actions"><button id="sessions-refresh-btn" class="btn btn-ghost">' + escapeHtml(t("common.refresh")) + '</button></div></div>' +
                '<div class="page-content">' +
                    '<div id="sessions-list" class="sessions-list"><div class="loading-spinner"></div></div>' +
                    '<div id="session-messages-panel" class="session-messages-panel" style="display:none;">' +
                        '<div class="page-header" style="height:auto;padding:12px 16px;">' +
                            '<h3 id="session-messages-title" class="page-title" style="font-size:0.9375rem;">' + escapeHtml(t("sessions.messages")) + '</h3>' +
                            '<div class="header-actions"><button id="session-messages-close" class="btn btn-ghost">' + escapeHtml(t("common.close")) + '</button></div>' +
                        '</div>' +
                        '<div id="session-messages-content" class="session-messages-content"></div>' +
                    '</div>' +
                '</div>' +
            '</div>';
        loadSessions();
        var refreshBtn = document.getElementById("sessions-refresh-btn");
        if (refreshBtn) refreshBtn.addEventListener("click", loadSessions);
        var closeBtn = document.getElementById("session-messages-close");
        if (closeBtn) closeBtn.addEventListener("click", function () {
            var panel = document.getElementById("session-messages-panel");
            if (panel) panel.style.display = "none";
        });
    }

    function loadSessions() {
        apiFetch("/api/sessions").then(function (data) {
            var list = document.getElementById("sessions-list");
            if (!list || state.currentPage !== "sessions") return;
            var sessions = data.sessions || [];
            if (sessions.length === 0) { list.innerHTML = '<p class="empty-state">' + escapeHtml(t("sessions.noSessions")) + '</p>'; return; }
            var html = "";
            sessions.forEach(function (sessionKey) {
                var isActive = sessionKey === state.currentSessionKey;
                html += '<div class="session-item' + (isActive ? " active" : "") + '" data-session="' + escapeHtml(sessionKey) + '">' +
                    '<div class="session-item-info"><span class="session-item-name">' + escapeHtml(sessionKey) + '</span>' +
                    (isActive ? '<span class="session-item-badge">' + escapeHtml(t("sessions.current")) + '</span>' : '') + '</div>' +
                    '<div class="session-item-actions">' +
                        '<button class="btn btn-ghost session-view-btn" data-session="' + escapeHtml(sessionKey) + '">' + escapeHtml(t("common.view")) + '</button>' +
                        '<button class="btn btn-ghost session-switch-btn" data-session="' + escapeHtml(sessionKey) + '">' + escapeHtml(t("common.switch")) + '</button>' +
                        '<button class="btn btn-danger session-delete-btn" data-session="' + escapeHtml(sessionKey) + '">' + escapeHtml(t("common.delete")) + '</button>' +
                    '</div></div>';
            });
            list.innerHTML = html;
            list.querySelectorAll(".session-view-btn").forEach(function (btn) { btn.addEventListener("click", function (e) { e.stopPropagation(); viewSessionMessages(btn.dataset.session); }); });
            list.querySelectorAll(".session-switch-btn").forEach(function (btn) { btn.addEventListener("click", function (e) { e.stopPropagation(); switchSession(btn.dataset.session); }); });
            list.querySelectorAll(".session-delete-btn").forEach(function (btn) { btn.addEventListener("click", function (e) { e.stopPropagation(); deleteSession(btn.dataset.session); }); });
        }).catch(function (err) {
            var list = document.getElementById("sessions-list");
            if (list) list.innerHTML = '<p class="error-text">' + escapeHtml(t("sessions.loadFailed") + err.message) + '</p>';
        });
    }

    function viewSessionMessages(sessionKey) {
        var panel = document.getElementById("session-messages-panel");
        var title = document.getElementById("session-messages-title");
        var content = document.getElementById("session-messages-content");
        if (!panel || !content) return;
        if (title) title.textContent = t("sessions.messages") + ": " + sessionKey;
        content.innerHTML = '<div class="loading-spinner"></div>';
        panel.style.display = "block";
        apiFetch("/api/sessions/" + encodeURIComponent(sessionKey) + "/messages").then(function (data) {
            var messages = data.messages || [];
            if (messages.length === 0) { content.innerHTML = '<p class="empty-state">' + escapeHtml(t("sessions.noMessages")) + '</p>'; return; }
            var html = "";
            messages.forEach(function (msg) {
                html += '<div class="message message-' + escapeHtml(msg.role) + '">' +
                    '<div class="message-avatar">' + (msg.role === "user" ? "U" : "A") + '</div>' +
                    '<div class="message-content"><div class="markdown-content">' + renderMarkdown(msg.content) + '</div></div></div>';
            });
            content.innerHTML = html;
        }).catch(function (err) {
            content.innerHTML = '<p class="error-text">' + escapeHtml(t("sessions.messagesFailed") + err.message) + '</p>';
        });
    }

    function switchSession(sessionKey) {
        state.currentSessionKey = sessionKey;
        state.messages = [];
        showToast(t("sessions.switchedTo") + sessionKey, "info");
        loadSessions();
        var label = document.getElementById("current-session-label");
        if (label) label.textContent = sessionKey;
    }

    function deleteSession(sessionKey) {
        if (sessionKey === state.currentSessionKey) { showToast(t("sessions.cannotDeleteActive"), "error"); return; }
        apiFetch("/api/sessions/" + encodeURIComponent(sessionKey), { method: "DELETE" }).then(function () {
            showToast(t("sessions.deleted") + sessionKey, "success");
            loadSessions();
        }).catch(function (err) { showToast(t("sessions.deleteFailed") + err.message, "error"); });
    }

    // ---- 10.4 Tools Page ----

    function renderToolsPage() {
        var main = document.getElementById("main-content");
        if (!main) return;
        main.innerHTML =
            '<div class="page" style="display:flex;flex-direction:column;height:100%;">' +
                '<div class="page-header"><h1 class="page-title">' + escapeHtml(t("tools.title")) + '</h1>' +
                '<div class="header-actions"><button id="tools-refresh-btn" class="btn btn-ghost">' + escapeHtml(t("common.refresh")) + '</button></div></div>' +
                '<div class="page-content"><div id="tools-grid" class="tools-grid"><div class="loading-spinner"></div></div></div>' +
            '</div>';
        loadTools();
        var refreshBtn = document.getElementById("tools-refresh-btn");
        if (refreshBtn) refreshBtn.addEventListener("click", loadTools);
    }

    function loadTools() {
        apiFetch("/api/tools").then(function (data) {
            var grid = document.getElementById("tools-grid");
            if (!grid || state.currentPage !== "tools") return;
            var tools = data.tools || [];
            if (tools.length === 0) { grid.innerHTML = '<p class="empty-state">' + escapeHtml(t("tools.noTools")) + '</p>'; return; }
            var html = "";
            tools.forEach(function (tool) {
                var fn = tool.function || tool || {};
                var name = fn.name || "unknown";
                var description = fn.description || "";
                var parameters = fn.parameters || null;
                var paramsHtml = "";
                if (parameters && parameters.properties) {
                    var props = parameters.properties;
                    var required = parameters.required || [];
                    paramsHtml = '<div class="tool-params"><h4>' + escapeHtml(t("tools.parameters")) + '</h4><ul>';
                    Object.keys(props).forEach(function (key) {
                        var prop = props[key];
                        paramsHtml += "<li><span class=\"param-name\">" + escapeHtml(key) + "</span>" +
                            '<span class="param-type">' + escapeHtml(prop.type || "any") + "</span>" +
                            (required.indexOf(key) !== -1 ? '<span class="param-required">' + escapeHtml(t("tools.required")) + "</span>" : "") +
                            (prop.description ? '<span class="param-desc"> - ' + escapeHtml(prop.description) + "</span>" : "") + "</li>";
                    });
                    paramsHtml += "</ul></div>";
                }
                html += '<div class="tool-card"><div class="tool-card-header"><h3>' + escapeHtml(name) + '</h3></div>' +
                    '<div class="tool-card-body"><p class="tool-description">' + escapeHtml(description) + '</p>' + paramsHtml + '</div></div>';
            });
            grid.innerHTML = html;
        }).catch(function (err) {
            var grid = document.getElementById("tools-grid");
            if (grid) grid.innerHTML = '<p class="error-text">' + escapeHtml(t("tools.loadFailed") + err.message) + '</p>';
        });
    }

    // ---- 10.5 Config Page (tabbed form) ----

    var CONFIG_TABS = ["agents", "providers", "channels", "gateway", "tools", "security", "experts", "json"];

    // -- Form helpers --

    function formGroup(label, inputHtml, hint) {
        return '<div class="form-group"><label>' + escapeHtml(label) + '</label>' +
            inputHtml + (hint ? '<div class="form-hint">' + escapeHtml(hint) + '</div>' : '') + '</div>';
    }

    function textInput(path, placeholder) {
        var val = getNestedValue(state.configData, path);
        if (val == null) val = "";
        return '<input class="form-input" type="text" data-path="' + escapeHtml(path) + '" value="' + escapeHtml(String(val)) + '"' +
            (placeholder ? ' placeholder="' + escapeHtml(placeholder) + '"' : '') + ' />';
    }

    function numberInput(path, min, max, step) {
        var val = getNestedValue(state.configData, path);
        if (val == null) val = "";
        var attrs = 'class="form-input" type="number" data-path="' + escapeHtml(path) + '" value="' + escapeHtml(String(val)) + '"';
        if (min !== undefined) attrs += ' min="' + min + '"';
        if (max !== undefined) attrs += ' max="' + max + '"';
        if (step !== undefined) attrs += ' step="' + step + '"';
        return '<input ' + attrs + ' />';
    }

    function checkboxField(path, label) {
        var val = getNestedValue(state.configData, path);
        return '<div class="form-checkbox"><input type="checkbox" data-path="' + escapeHtml(path) + '"' +
            (val ? ' checked' : '') + ' /><span>' + escapeHtml(label) + '</span></div>';
    }

    function selectField(path, options) {
        var val = getNestedValue(state.configData, path);
        var html = '<select class="form-input" data-path="' + escapeHtml(path) + '">';
        options.forEach(function (opt) {
            var v = typeof opt === "string" ? opt : opt.value;
            var lab = typeof opt === "string" ? opt : opt.label;
            html += '<option value="' + escapeHtml(v) + '"' + (val === v ? ' selected' : '') + '>' + escapeHtml(lab) + '</option>';
        });
        return html + '</select>';
    }

    // -- Tab renderers --

    function renderAgentsConfig() {
        if (!state.configData) return "";
        return '<div class="form-section"><h3>' + t("config.agents.title") + '</h3>' +
            formGroup(t("config.agents.workspace"), textInput("agents.defaults.workspace"), t("config.agents.workspace.hint")) +
            formGroup(t("config.agents.model"), textInput("agents.defaults.model"), t("config.agents.model.hint")) +
            formGroup(t("config.agents.provider"), textInput("agents.defaults.provider"), t("config.agents.provider.hint")) +
            formGroup(t("config.agents.maxTokens"), numberInput("agents.defaults.maxTokens"), t("config.agents.maxTokens.hint")) +
            formGroup(t("config.agents.contextWindowTokens"), numberInput("agents.defaults.contextWindowTokens"), t("config.agents.contextWindowTokens.hint")) +
            formGroup(t("config.agents.temperature"), numberInput("agents.defaults.temperature", 0, 2, 0.1), t("config.agents.temperature.hint")) +
            formGroup(t("config.agents.maxToolIterations"), numberInput("agents.defaults.maxToolIterations"), t("config.agents.maxToolIterations.hint")) +
            formGroup(t("config.agents.reasoningEffort"), selectField("agents.defaults.reasoningEffort", [
                { value: "", label: "-" }, { value: "low", label: t("option.low") },
                { value: "medium", label: t("option.medium") }, { value: "high", label: t("option.high") }
            ]), t("config.agents.reasoningEffort.hint")) +
            formGroup(t("config.agents.timezone"), textInput("agents.defaults.timezone"), t("config.agents.timezone.hint")) +
            '</div>';
    }

    function renderProvidersConfig() {
        if (!state.configData || !state.configData.providers) return "";
        var providers = state.configData.providers;
        var html = '<h3>' + t("config.providers.title") + '</h3>';
        Object.keys(providers).forEach(function (name) {
            var bp = "providers." + name;
            html += '<div class="form-section"><h4 class="provider-name">' + escapeHtml(name) + '</h4>' +
                '<div class="provider-inline-fields">' +
                    '<div class="inline-field">' + formGroup(t("config.providers.apiKey"), textInput(bp + ".apiKey", "***")) + '</div>' +
                    '<div class="inline-field">' + formGroup(t("config.providers.apiBase"), textInput(bp + ".apiBase")) + '</div>' +
                '</div>' +
                formGroup(t("config.providers.priority"), numberInput(bp + ".priority", 0), t("config.providers.priority.hint")) +
                checkboxField(bp + ".enabled", t("config.providers.enabled")) +
                '</div>';
        });
        return html;
    }

    function renderChannelsConfig() {
        if (!state.configData || !state.configData.channels) return "";
        return '<div class="form-section"><h3>' + t("config.channels.title") + '</h3>' +
            checkboxField("channels.sendProgress", t("config.channels.sendProgress")) +
            checkboxField("channels.sendToolHints", t("config.channels.sendToolHints")) +
            formGroup(t("config.channels.sendMaxRetries"), numberInput("channels.sendMaxRetries", 0)) +
            '</div>';
    }

    function renderGatewayConfig() {
        if (!state.configData || !state.configData.gateway) return "";
        return '<div class="form-section"><h3>' + t("config.gateway.title") + '</h3>' +
            formGroup(t("config.gateway.host"), textInput("gateway.host")) +
            formGroup(t("config.gateway.port"), numberInput("gateway.port", 1, 65535)) +
            '</div>' +
            '<div class="form-section"><h4>' + t("config.gateway.heartbeat") + '</h4>' +
            checkboxField("gateway.heartbeat.enabled", t("config.gateway.heartbeat.enabled")) +
            formGroup(t("config.gateway.heartbeat.intervalS"), numberInput("gateway.heartbeat.intervalS", 1)) +
            formGroup(t("config.gateway.heartbeat.keepRecentMessages"), numberInput("gateway.heartbeat.keepRecentMessages", 0)) +
            '</div>';
    }

    function renderToolsConfig() {
        if (!state.configData || !state.configData.tools) return "";
        var html = '<div class="form-section"><h3>' + t("config.tools.title") + '</h3>' +
            checkboxField("tools.restrictToWorkspace", t("config.tools.restrictToWorkspace")) + '</div>';

        // Web search
        html += '<div class="form-section"><h4>' + t("config.tools.web") + '</h4>' +
            formGroup(t("config.tools.web.proxy"), textInput("tools.web.proxy")) +
            formGroup(t("config.tools.web.search.provider"), textInput("tools.web.search.provider")) +
            formGroup(t("config.tools.web.search.apiKey"), textInput("tools.web.search.apiKey", "***")) +
            formGroup(t("config.tools.web.search.baseUrl"), textInput("tools.web.search.baseUrl")) +
            formGroup(t("config.tools.web.search.maxResults"), numberInput("tools.web.search.maxResults", 1)) +
            '</div>';

        // Exec
        html += '<div class="form-section"><h4>' + t("config.tools.exec") + '</h4>' +
            checkboxField("tools.exec.enable", t("config.tools.exec.enable")) +
            formGroup(t("config.tools.exec.timeout"), numberInput("tools.exec.timeout", 1)) +
            formGroup(t("config.tools.exec.pathAppend"), textInput("tools.exec.pathAppend")) +
            '</div>';

        // MCP Servers
        var mcpServers = (state.configData.tools && state.configData.tools.mcpServers) || {};
        html += '<div class="form-section"><h4>' + t("config.tools.mcpServers") + '</h4>';
        Object.keys(mcpServers).forEach(function (srvName) {
            var bp = "tools.mcpServers." + srvName;
            html += '<div class="mcp-server-section"><h5><span>' + escapeHtml(srvName) + '</span>' +
                '<button class="btn btn-ghost btn-sm mcp-remove-btn" data-server="' + escapeHtml(srvName) + '">' + t("config.tools.mcpServers.remove") + '</button></h5>' +
                formGroup(t("config.tools.mcpServers.command"), textInput(bp + ".command")) +
                formGroup(t("config.tools.mcpServers.args"), textInput(bp + ".args")) +
                formGroup(t("config.tools.mcpServers.env"), textInput(bp + ".env")) +
                '</div>';
        });
        html += '<button class="btn btn-secondary" id="mcp-add-btn">' + t("config.tools.mcpServers.add") + '</button>';
        html += '</div>';
        return html;
    }

    function renderSecurityConfig() {
        if (!state.configData || !state.configData.security) return "";
        return '<div class="form-section"><h3>' + t("config.security.title") + '</h3>' +
            formGroup(t("config.security.rateLimitRpm"), numberInput("security.rateLimitRpm", 0)) +
            formGroup(t("config.security.rateLimitBurst"), numberInput("security.rateLimitBurst", 0)) +
            formGroup(t("config.security.maxInputLength"), numberInput("security.maxInputLength", 0)) +
            formGroup(t("config.security.blockedPatterns"), textInput("security.blockedPatterns")) +
            '</div>';
    }

    function renderExpertsConfig() {
        if (!state.configData || !state.configData.experts) return "";
        return '<div class="form-section"><h3>' + t("config.experts.title") + '</h3>' +
            checkboxField("experts.enabled", t("config.experts.enabled")) +
            formGroup(t("config.experts.directory"), textInput("experts.directory")) +
            checkboxField("experts.autoRoute", t("config.experts.autoRoute")) +
            checkboxField("experts.autoSync", t("config.experts.autoSync")) +
            '</div>';
    }

    function renderJsonConfig() {
        var json = state.configData ? JSON.stringify(state.configData, null, 2) : "";
        return '<div class="config-editor-container">' +
            '<textarea id="config-editor" class="config-editor" spellcheck="false">' + escapeHtml(json) + '</textarea>' +
            '<p id="config-status" class="config-status"></p></div>';
    }

    function renderConfigTabContent(tab) {
        switch (tab) {
            case "agents": return renderAgentsConfig();
            case "providers": return renderProvidersConfig();
            case "channels": return renderChannelsConfig();
            case "gateway": return renderGatewayConfig();
            case "tools": return renderToolsConfig();
            case "security": return renderSecurityConfig();
            case "experts": return renderExpertsConfig();
            case "json": return renderJsonConfig();
            default: return "";
        }
    }

    // -- Main config page --

    function renderConfigPage() {
        var main = document.getElementById("main-content");
        if (!main) return;

        // Build tabs
        var tabsHtml = '<div class="tabs-container">';
        CONFIG_TABS.forEach(function (tab) {
            tabsHtml += '<button class="tab-button' + (tab === state.configTab ? ' active' : '') + '" data-tab="' + tab + '">' +
                escapeHtml(t("config.tab." + tab)) + '</button>';
        });
        tabsHtml += '</div>';

        main.innerHTML =
            '<div class="page" style="display:flex;flex-direction:column;height:100%;">' +
                '<div class="page-header"><h1 class="page-title">' + escapeHtml(t("config.title")) + '</h1>' +
                '<div class="header-actions">' +
                    '<button id="config-reload-btn" class="btn btn-ghost">' + escapeHtml(t("common.reload")) + '</button>' +
                    '<button id="config-save-btn" class="btn btn-primary">' + escapeHtml(t("common.save")) + '</button>' +
                '</div></div>' +
                '<div class="config-page"><div class="config-page-inner">' +
                    tabsHtml +
                    '<div id="config-tab-content">' +
                        (state.configData ? renderConfigTabContent(state.configTab) : '<div class="empty-state">' + escapeHtml(t("common.loading")) + '</div>') +
                    '</div>' +
                '</div></div>' +
            '</div>';

        // Load config if not loaded yet
        if (!state.configData) loadConfig();

        bindConfigEvents();
    }

    function bindConfigEvents() {
        // Tab clicks
        var tabBtns = document.querySelectorAll(".tab-button");
        tabBtns.forEach(function (btn) {
            btn.addEventListener("click", function () {
                // If leaving JSON tab, sync textarea back to configData
                if (state.configTab === "json") syncJsonTabToConfigData();
                state.configTab = btn.dataset.tab;
                // Update tab button styles
                tabBtns.forEach(function (b) { b.classList.toggle("active", b.dataset.tab === state.configTab); });
                // Render tab content
                var contentEl = document.getElementById("config-tab-content");
                if (contentEl) {
                    contentEl.innerHTML = renderConfigTabContent(state.configTab);
                    bindConfigFormListeners();
                }
            });
        });

        // Save / Reload
        var saveBtn = document.getElementById("config-save-btn");
        if (saveBtn) saveBtn.addEventListener("click", saveConfig);
        var reloadBtn = document.getElementById("config-reload-btn");
        if (reloadBtn) reloadBtn.addEventListener("click", function () { state.configData = null; loadConfig(); });

        bindConfigFormListeners();
    }

    function bindConfigFormListeners() {
        var contentEl = document.getElementById("config-tab-content");
        if (!contentEl) return;

        // Delegated input/change events for form fields
        contentEl.addEventListener("input", function (e) {
            var path = e.target.dataset && e.target.dataset.path;
            if (!path || !state.configData) return;
            var val = e.target.value;
            if (e.target.type === "number") val = val === "" ? null : Number(val);
            setNestedValue(state.configData, path, val);
        });

        contentEl.addEventListener("change", function (e) {
            var path = e.target.dataset && e.target.dataset.path;
            if (!path || !state.configData) return;
            if (e.target.type === "checkbox") {
                setNestedValue(state.configData, path, e.target.checked);
            } else if (e.target.tagName === "SELECT") {
                setNestedValue(state.configData, path, e.target.value);
            }
        });

        // MCP add/remove
        var addBtn = document.getElementById("mcp-add-btn");
        if (addBtn) {
            addBtn.addEventListener("click", function () {
                var name = prompt(t("config.tools.mcpServers.command") + " name:");
                if (!name || !name.trim()) return;
                name = name.trim();
                if (!state.configData.tools) state.configData.tools = {};
                if (!state.configData.tools.mcpServers) state.configData.tools.mcpServers = {};
                state.configData.tools.mcpServers[name] = { command: "", args: [], env: {} };
                refreshConfigContent();
            });
        }

        contentEl.querySelectorAll(".mcp-remove-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var srvName = btn.dataset.server;
                if (state.configData && state.configData.tools && state.configData.tools.mcpServers) {
                    delete state.configData.tools.mcpServers[srvName];
                    refreshConfigContent();
                }
            });
        });
    }

    function refreshConfigContent() {
        var contentEl = document.getElementById("config-tab-content");
        if (contentEl) {
            contentEl.innerHTML = renderConfigTabContent(state.configTab);
            bindConfigFormListeners();
        }
    }

    function syncJsonTabToConfigData() {
        var editor = document.getElementById("config-editor");
        if (!editor) return;
        try {
            var parsed = JSON.parse(editor.value.trim());
            state.configData = parsed;
        } catch (e) {
            // Invalid JSON - ignore, keep existing configData
        }
    }

    function loadConfig() {
        apiFetch("/api/config").then(function (data) {
            if (state.currentPage !== "config") return;
            state.configData = data.config || data;
            refreshConfigContent();
            showToast(t("config.loaded"), "info");
        }).catch(function (err) {
            showToast(t("config.loadFailed") + err.message, "error");
        });
    }

    function saveConfig() {
        if (!state.configData) return;

        // If on JSON tab, sync textarea first
        if (state.configTab === "json") {
            var editor = document.getElementById("config-editor");
            if (editor) {
                try {
                    state.configData = JSON.parse(editor.value.trim());
                } catch (e) {
                    showToast(t("config.invalidJson") + e.message, "error");
                    return;
                }
            }
        }

        // Handle array fields that are stored as comma-separated strings
        if (state.configData.tools && state.configData.tools.exec) {
            var pa = state.configData.tools.exec.pathAppend;
            if (typeof pa === "string") {
                state.configData.tools.exec.pathAppend = pa ? pa.split(",").map(function (s) { return s.trim(); }).filter(Boolean) : [];
            }
        }
        if (state.configData.security) {
            var bp = state.configData.security.blockedPatterns;
            if (typeof bp === "string") {
                state.configData.security.blockedPatterns = bp ? bp.split(",").map(function (s) { return s.trim(); }).filter(Boolean) : [];
            }
        }

        // Handle MCP server args/env stored as strings
        if (state.configData.tools && state.configData.tools.mcpServers) {
            var servers = state.configData.tools.mcpServers;
            Object.keys(servers).forEach(function (name) {
                var srv = servers[name];
                if (typeof srv.args === "string") {
                    srv.args = srv.args ? srv.args.split(",").map(function (s) { return s.trim(); }).filter(Boolean) : [];
                }
                if (typeof srv.env === "string") {
                    try { srv.env = JSON.parse(srv.env); } catch (e) { srv.env = {}; }
                }
            });
        }

        var saveBtn = document.getElementById("config-save-btn");
        if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = t("common.saving"); }

        apiFetch("/api/config", { method: "PUT", body: JSON.stringify(state.configData) }).then(function () {
            showToast(t("config.saved"), "success");
        }).catch(function (err) {
            showToast(t("config.saveFailed") + err.message, "error");
        }).finally(function () {
            if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = t("common.save"); }
        });
    }

    // =========================================================================
    // Section 11: Theme & Language Toggle
    // =========================================================================

    function applyTheme(theme) {
        document.documentElement.setAttribute("data-theme", theme);
        localStorage.setItem("ultrabot-theme", theme);
        var sunIcon = document.getElementById("theme-icon-sun");
        var moonIcon = document.getElementById("theme-icon-moon");
        var label = document.getElementById("theme-label");
        if (theme === "dark") {
            if (sunIcon) sunIcon.style.display = "none";
            if (moonIcon) moonIcon.style.display = "";
            if (label) label.textContent = t("theme.dark");
        } else {
            if (sunIcon) sunIcon.style.display = "";
            if (moonIcon) moonIcon.style.display = "none";
            if (label) label.textContent = t("theme.light");
        }
    }

    function toggleTheme() {
        var current = document.documentElement.getAttribute("data-theme") || "light";
        applyTheme(current === "dark" ? "light" : "dark");
    }

    function setLanguage(lang) {
        state.language = lang;
        localStorage.setItem("ultrabot-lang", lang);
        // Rebuild entire UI with new language
        buildAppShell();
        navigateTo(state.currentPage);
    }

    function toggleLanguage() {
        setLanguage(state.language === "zh-CN" ? "en" : "zh-CN");
    }

    // =========================================================================
    // Section 12: Sidebar & Layout Initialisation
    // =========================================================================

    function buildAppShell() {
        var app = document.getElementById("app");
        if (!app) { app = document.createElement("div"); app.id = "app"; document.body.appendChild(app); }

        app.innerHTML =
            '<aside class="sidebar">' +
                '<div class="sidebar-header">' +
                    '<div class="logo"><span class="logo-icon">&#x1F916;</span><span class="logo-text">ultrabot</span></div>' +
                    '<span id="connection-status" class="connection-status" title=""><span class="status-dot disconnected"></span></span>' +
                '</div>' +
                '<nav class="sidebar-nav">' +
                    '<a href="#" class="nav-item' + (state.currentPage === "chat" ? " active" : "") + '" data-page="chat">' +
                        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>' +
                        '<span>' + t("nav.chat") + '</span></a>' +
                    '<a href="#" class="nav-item' + (state.currentPage === "providers" ? " active" : "") + '" data-page="providers">' +
                        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>' +
                        '<span>' + t("nav.providers") + '</span></a>' +
                    '<a href="#" class="nav-item' + (state.currentPage === "sessions" ? " active" : "") + '" data-page="sessions">' +
                        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>' +
                        '<span>' + t("nav.sessions") + '</span></a>' +
                    '<a href="#" class="nav-item' + (state.currentPage === "tools" ? " active" : "") + '" data-page="tools">' +
                        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>' +
                        '<span>' + t("nav.tools") + '</span></a>' +
                    '<a href="#" class="nav-item' + (state.currentPage === "config" ? " active" : "") + '" data-page="config">' +
                        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>' +
                        '<span>' + t("nav.config") + '</span></a>' +
                '</nav>' +
                '<div class="sidebar-footer">' +
                    '<button class="theme-btn" id="theme-toggle-btn" title="Toggle theme">' +
                        '<svg id="theme-icon-sun" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>' +
                        '<svg id="theme-icon-moon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="display:none"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>' +
                        '<span id="theme-label">' + t("theme.light") + '</span>' +
                    '</button>' +
                    '<button class="lang-btn" id="lang-toggle-btn" title="Toggle language">' +
                        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>' +
                        '<span id="lang-label">' + t("lang.label") + '</span>' +
                    '</button>' +
                    '<div class="sidebar-info">' + t("version") + '</div>' +
                '</div>' +
            '</aside>' +
            '<main id="main-content" class="main-content"></main>';

        // Bind navigation
        document.querySelectorAll(".nav-item").forEach(function (item) {
            item.addEventListener("click", function (e) { e.preventDefault(); navigateTo(item.dataset.page); });
        });

        // Bind theme toggle
        var themeBtn = document.getElementById("theme-toggle-btn");
        if (themeBtn) themeBtn.addEventListener("click", toggleTheme);
        applyTheme(localStorage.getItem("ultrabot-theme") || "light");

        // Bind language toggle
        var langBtn = document.getElementById("lang-toggle-btn");
        if (langBtn) langBtn.addEventListener("click", toggleLanguage);
    }

    // =========================================================================
    // Section 13: Initialisation
    // =========================================================================

    function init() {
        buildAppShell();
        connectWebSocket();
        navigateTo("chat");

        apiFetch("/api/health").then(function (data) {
            if (data && data.status === "ok") console.log("[App] Health OK.");
        }).catch(function (err) {
            console.warn("[App] Health check failed:", err.message);
            showToast(t("toast.backendUnreachable") + err.message, "error");
        });
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();

    // =========================================================================
    // Section 14: Public API
    // =========================================================================

    window.UltrabotApp = {
        state: state, navigateTo: navigateTo, sendMessage: sendMessage,
        showToast: showToast, connectWebSocket: connectWebSocket,
        renderMarkdown: renderMarkdown, escapeHtml: escapeHtml,
        formatTimestamp: formatTimestamp, debounce: debounce,
        toggleTheme: toggleTheme, applyTheme: applyTheme,
        setLanguage: setLanguage, toggleLanguage: toggleLanguage, t: t,
    };
})();
