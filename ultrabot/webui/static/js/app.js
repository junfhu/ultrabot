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

    /**
     * Escape HTML special characters to prevent XSS.
     * @param {string} str - Raw string.
     * @returns {string} Escaped string safe for innerHTML.
     */
    function escapeHtml(str) {
        if (typeof str !== "string") return "";
        var map = {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#039;",
        };
        return str.replace(/[&<>"']/g, function (ch) {
            return map[ch];
        });
    }

    /**
     * Format a Date object (or ISO string) into a human-readable timestamp.
     * @param {Date|string} date
     * @returns {string}
     */
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
        } catch (e) {
            return "";
        }
    }

    /**
     * Debounce a function call.
     * @param {Function} fn
     * @param {number} delay - Milliseconds.
     * @returns {Function}
     */
    function debounce(fn, delay) {
        var timer = null;
        return function () {
            var ctx = this;
            var args = arguments;
            clearTimeout(timer);
            timer = setTimeout(function () {
                fn.apply(ctx, args);
            }, delay);
        };
    }

    /**
     * Simple markdown-to-HTML converter.
     *
     * Handles: code blocks, inline code, bold, italic, headings,
     * unordered/ordered lists, links, tables, and line breaks.
     *
     * @param {string} text - Raw markdown string.
     * @returns {string} HTML string.
     */
    function renderMarkdown(text) {
        if (typeof text !== "string" || text.length === 0) return "";

        // Stash code blocks and inline code to protect them from other rules.
        var codeStash = [];

        function stash(content) {
            var idx = codeStash.length;
            codeStash.push(content);
            return "\x00CODE" + idx + "\x00";
        }

        // Fenced code blocks: ```lang\n...\n```
        text = text.replace(/```(\w*)\n([\s\S]*?)```/g, function (_, lang, code) {
            var cls = lang ? ' class="language-' + escapeHtml(lang) + '"' : "";
            return stash(
                "<pre><code" + cls + ">" + escapeHtml(code.replace(/\n$/, "")) + "</code></pre>"
            );
        });

        // Inline code: `...`
        text = text.replace(/`([^`\n]+)`/g, function (_, code) {
            return stash("<code>" + escapeHtml(code) + "</code>");
        });

        // Split into lines for block-level processing.
        var lines = text.split("\n");
        var html = [];
        var i = 0;

        while (i < lines.length) {
            var line = lines[i];

            // --- Tables ---
            // Detect table: current line has pipes, next line is a separator row.
            if (
                line.indexOf("|") !== -1 &&
                i + 1 < lines.length &&
                /^\|?[\s\-:|]+\|/.test(lines[i + 1])
            ) {
                var tableRows = [];
                // Gather all contiguous lines that contain a pipe.
                while (i < lines.length && lines[i].indexOf("|") !== -1) {
                    tableRows.push(lines[i]);
                    i++;
                }
                html.push(buildTable(tableRows));
                continue;
            }

            // --- Headings ---
            var headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
            if (headingMatch) {
                var level = headingMatch[1].length;
                html.push(
                    "<h" + level + ">" + inlineFormat(headingMatch[2]) + "</h" + level + ">"
                );
                i++;
                continue;
            }

            // --- Unordered lists ---
            if (/^[\s]*[-*+]\s+/.test(line)) {
                var listItems = [];
                while (i < lines.length && /^[\s]*[-*+]\s+/.test(lines[i])) {
                    listItems.push(lines[i].replace(/^[\s]*[-*+]\s+/, ""));
                    i++;
                }
                html.push(
                    "<ul>" +
                        listItems
                            .map(function (li) {
                                return "<li>" + inlineFormat(li) + "</li>";
                            })
                            .join("") +
                        "</ul>"
                );
                continue;
            }

            // --- Ordered lists ---
            if (/^[\s]*\d+\.\s+/.test(line)) {
                var olItems = [];
                while (i < lines.length && /^[\s]*\d+\.\s+/.test(lines[i])) {
                    olItems.push(lines[i].replace(/^[\s]*\d+\.\s+/, ""));
                    i++;
                }
                html.push(
                    "<ol>" +
                        olItems
                            .map(function (li) {
                                return "<li>" + inlineFormat(li) + "</li>";
                            })
                            .join("") +
                        "</ol>"
                );
                continue;
            }

            // --- Horizontal rule ---
            if (/^[-*_]{3,}\s*$/.test(line)) {
                html.push("<hr>");
                i++;
                continue;
            }

            // --- Blank line ---
            if (line.trim() === "") {
                html.push("");
                i++;
                continue;
            }

            // --- Paragraph ---
            // Collect contiguous non-blank, non-special lines into a paragraph.
            var paraLines = [];
            while (
                i < lines.length &&
                lines[i].trim() !== "" &&
                !/^#{1,6}\s+/.test(lines[i]) &&
                !/^[\s]*[-*+]\s+/.test(lines[i]) &&
                !/^[\s]*\d+\.\s+/.test(lines[i]) &&
                !/^[-*_]{3,}\s*$/.test(lines[i]) &&
                !(lines[i].indexOf("|") !== -1 && i + 1 < lines.length && /^\|?[\s\-:|]+\|/.test(lines[i + 1]))
            ) {
                paraLines.push(lines[i]);
                i++;
            }
            if (paraLines.length > 0) {
                html.push("<p>" + inlineFormat(paraLines.join("\n")) + "</p>");
            }
        }

        var result = html.join("\n");

        // Restore stashed code.
        result = result.replace(/\x00CODE(\d+)\x00/g, function (_, idx) {
            return codeStash[parseInt(idx, 10)];
        });

        return result;

        // --- Helper: inline formatting ---
        function inlineFormat(s) {
            // Bold: **text** or __text__
            s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
            s = s.replace(/__(.+?)__/g, "<strong>$1</strong>");
            // Italic: *text* or _text_
            s = s.replace(/\*(.+?)\*/g, "<em>$1</em>");
            s = s.replace(/(?<!\w)_(.+?)_(?!\w)/g, "<em>$1</em>");
            // Links: [text](url)
            s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function (_, txt, url) {
                return '<a href="' + escapeHtml(url) + '" target="_blank" rel="noopener">' + txt + "</a>";
            });
            // Line breaks within paragraphs (two trailing spaces or explicit \n).
            s = s.replace(/  \n/g, "<br>");
            s = s.replace(/\n/g, "<br>");
            return s;
        }

        // --- Helper: build an HTML table from raw lines ---
        function buildTable(rows) {
            function parseCells(row) {
                // Strip leading/trailing pipes and split.
                var trimmed = row.replace(/^\|/, "").replace(/\|$/, "");
                return trimmed.split("|").map(function (c) {
                    return c.trim();
                });
            }
            if (rows.length < 2) return escapeHtml(rows.join("\n"));

            var headerCells = parseCells(rows[0]);
            // rows[1] is the separator; skip it.
            var bodyRows = rows.slice(2);

            var out = "<table><thead><tr>";
            headerCells.forEach(function (cell) {
                out += "<th>" + inlineFormat(cell) + "</th>";
            });
            out += "</tr></thead><tbody>";
            bodyRows.forEach(function (row) {
                // Skip separator-like rows that may appear.
                if (/^\|?[\s\-:|]+\|?$/.test(row)) return;
                var cells = parseCells(row);
                out += "<tr>";
                cells.forEach(function (cell) {
                    out += "<td>" + inlineFormat(cell) + "</td>";
                });
                out += "</tr>";
            });
            out += "</tbody></table>";
            return out;
        }
    }

    // =========================================================================
    // Section 2: Toast Notification System
    // =========================================================================

    var toastContainer = null;

    /**
     * Ensure the toast container element exists in the DOM.
     */
    function ensureToastContainer() {
        if (toastContainer) return;
        toastContainer = document.getElementById("toast-container");
        if (!toastContainer) {
            toastContainer = document.createElement("div");
            toastContainer.id = "toast-container";
            toastContainer.setAttribute(
                "style",
                "position:fixed;top:16px;right:16px;z-index:10000;display:flex;flex-direction:column;gap:8px;"
            );
            document.body.appendChild(toastContainer);
        }
    }

    /**
     * Show a toast notification.
     * @param {string} message
     * @param {"success"|"error"|"info"} type
     */
    function showToast(message, type) {
        type = type || "info";
        ensureToastContainer();

        var toast = document.createElement("div");
        toast.className = "toast toast-" + type;
        toast.textContent = message;

        toastContainer.appendChild(toast);

        // Trigger reflow then add visible class for animation.
        toast.offsetHeight; // eslint-disable-line no-unused-expressions
        toast.classList.add("toast-visible");

        setTimeout(function () {
            toast.classList.remove("toast-visible");
            toast.classList.add("toast-hiding");
            setTimeout(function () {
                if (toast.parentNode) toast.parentNode.removeChild(toast);
            }, 300);
        }, 3000);
    }

    // =========================================================================
    // Section 3: Application State
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
    };

    // =========================================================================
    // Section 4: API Helpers
    // =========================================================================

    var API_BASE = "";

    /**
     * Perform a fetch request with standard error handling.
     * @param {string} url
     * @param {object} [options]
     * @returns {Promise<any>}
     */
    function apiFetch(url, options) {
        options = options || {};
        options.headers = options.headers || {};
        if (options.body && typeof options.body === "string") {
            options.headers["Content-Type"] = options.headers["Content-Type"] || "application/json";
        }
        return fetch(API_BASE + url, options)
            .then(function (res) {
                if (!res.ok) {
                    return res.text().then(function (body) {
                        var errMsg = "API error " + res.status;
                        try {
                            var parsed = JSON.parse(body);
                            if (parsed.detail) errMsg = parsed.detail;
                            else if (parsed.message) errMsg = parsed.message;
                        } catch (e) {
                            if (body) errMsg = body;
                        }
                        throw new Error(errMsg);
                    });
                }
                return res.json();
            });
    }

    // =========================================================================
    // Section 5: WebSocket Management
    // =========================================================================

    var MAX_RECONNECT_DELAY = 30000;

    /**
     * Connect to the chat WebSocket. Automatically reconnects with
     * exponential backoff on close/error.
     */
    function connectWebSocket() {
        if (state.ws && (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)) {
            return;
        }

        var protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        var wsUrl = protocol + "//" + window.location.host + "/ws/chat";

        try {
            state.ws = new WebSocket(wsUrl);
        } catch (err) {
            console.error("[WS] Failed to create WebSocket:", err);
            scheduleReconnect();
            return;
        }

        state.ws.onopen = function () {
            console.log("[WS] Connected");
            state.reconnectAttempts = 0;
            showToast("Connected to server", "success");
            updateConnectionIndicator(true);
        };

        state.ws.onmessage = function (event) {
            try {
                var data = JSON.parse(event.data);
                handleWsMessage(data);
            } catch (err) {
                console.error("[WS] Failed to parse message:", err);
            }
        };

        state.ws.onclose = function (event) {
            console.log("[WS] Closed:", event.code, event.reason);
            state.ws = null;
            updateConnectionIndicator(false);
            if (state.isStreaming) {
                state.isStreaming = false;
                removeStreamingCursor();
                enableInput();
            }
            scheduleReconnect();
        };

        state.ws.onerror = function (err) {
            console.error("[WS] Error:", err);
            // onclose will fire after this, which triggers reconnect.
        };
    }

    /**
     * Schedule a reconnect attempt with exponential backoff.
     */
    function scheduleReconnect() {
        if (state.reconnectTimer) return;
        var delay = Math.min(1000 * Math.pow(2, state.reconnectAttempts), MAX_RECONNECT_DELAY);
        state.reconnectAttempts++;
        console.log("[WS] Reconnecting in " + delay + "ms (attempt " + state.reconnectAttempts + ")");
        state.reconnectTimer = setTimeout(function () {
            state.reconnectTimer = null;
            connectWebSocket();
        }, delay);
    }

    /**
     * Send a chat message via WebSocket.
     * @param {string} content
     */
    function sendMessage(content) {
        if (!content || !content.trim()) return;
        content = content.trim();

        if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
            showToast("Not connected to server. Reconnecting...", "error");
            connectWebSocket();
            return;
        }

        if (state.isStreaming) {
            showToast("Please wait for the current response to finish.", "info");
            return;
        }

        // Add user message to state and UI.
        var userMsg = { role: "user", content: content };
        state.messages.push(userMsg);
        appendMessageToChat(userMsg);

        // Send to server.
        var payload = JSON.stringify({
            type: "message",
            content: content,
            session_key: state.currentSessionKey,
        });

        try {
            state.ws.send(payload);
        } catch (err) {
            showToast("Failed to send message: " + err.message, "error");
            return;
        }

        // Prepare for streaming response.
        state.isStreaming = true;
        disableInput();

        // Add empty assistant message placeholder.
        var assistantMsg = { role: "assistant", content: "" };
        state.messages.push(assistantMsg);
        appendMessageToChat(assistantMsg, true);
    }

    /**
     * Handle an incoming WebSocket message from the server.
     * @param {object} data - Parsed JSON message.
     */
    function handleWsMessage(data) {
        switch (data.type) {
            case "content_delta":
                handleContentDelta(data.content || "");
                break;

            case "tool_start":
                handleToolStart(data.tool_name || "unknown", data.tool_call_id || "");
                break;

            case "content_done":
                handleContentDone(data.content || "");
                break;

            case "error":
                handleStreamError(data.message || "Unknown error");
                break;

            default:
                console.warn("[WS] Unknown message type:", data.type);
        }
    }

    /**
     * Append a content chunk to the current streaming assistant message.
     * @param {string} chunk
     */
    function handleContentDelta(chunk) {
        if (state.messages.length === 0) return;
        var lastMsg = state.messages[state.messages.length - 1];
        if (lastMsg.role !== "assistant") return;

        lastMsg.content += chunk;
        updateStreamingMessage(lastMsg.content);
    }

    /**
     * Show a tool execution indicator in the chat.
     * @param {string} toolName
     * @param {string} toolCallId
     */
    function handleToolStart(toolName, toolCallId) {
        var container = document.getElementById("chat-messages");
        if (!container) return;

        // Remove any existing tool indicator for this call.
        var existingIndicator = document.getElementById("tool-indicator-" + toolCallId);
        if (existingIndicator) existingIndicator.parentNode.removeChild(existingIndicator);

        var indicator = document.createElement("div");
        indicator.className = "tool-indicator";
        indicator.id = "tool-indicator-" + escapeHtml(toolCallId);
        indicator.innerHTML =
            '<span class="tool-indicator-dot"></span> Running <strong>' +
            escapeHtml(toolName) +
            "</strong>...";

        // Insert before the streaming cursor if present, otherwise at end.
        var streamingMsg = container.querySelector(".message-streaming");
        if (streamingMsg) {
            container.insertBefore(indicator, streamingMsg);
        } else {
            container.appendChild(indicator);
        }

        scrollChatToBottom();
    }

    /**
     * Finalise the streamed assistant message.
     * @param {string} fullContent
     */
    function handleContentDone(fullContent) {
        if (state.messages.length > 0) {
            var lastMsg = state.messages[state.messages.length - 1];
            if (lastMsg.role === "assistant") {
                lastMsg.content = fullContent;
            }
        }

        state.isStreaming = false;
        finaliseStreamingMessage(fullContent);
        removeToolIndicators();
        removeStreamingCursor();
        enableInput();
        scrollChatToBottom();
    }

    /**
     * Handle a streaming error from the server.
     * @param {string} message
     */
    function handleStreamError(message) {
        state.isStreaming = false;
        removeStreamingCursor();
        removeToolIndicators();
        enableInput();
        showToast("Error: " + message, "error");

        // Add error to chat display.
        var container = document.getElementById("chat-messages");
        if (container) {
            var errorDiv = document.createElement("div");
            errorDiv.className = "message message-error";
            errorDiv.innerHTML =
                '<div class="message-content"><p class="error-text">' +
                escapeHtml(message) +
                "</p></div>";
            container.appendChild(errorDiv);
            scrollChatToBottom();
        }
    }

    // =========================================================================
    // Section 6: Chat UI Helpers
    // =========================================================================

    /**
     * Append a message object to the chat display.
     * @param {object} msg - {role, content}
     * @param {boolean} [isStreaming] - If true, mark as streaming placeholder.
     */
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

        if (isStreaming) {
            markdownDiv.innerHTML = '<span class="streaming-cursor"></span>';
        } else {
            markdownDiv.innerHTML = renderMarkdown(msg.content);
        }

        contentDiv.appendChild(markdownDiv);
        msgDiv.appendChild(avatarDiv);
        msgDiv.appendChild(contentDiv);
        container.appendChild(msgDiv);

        scrollChatToBottom();
    }

    /**
     * Update the content of the currently streaming message.
     * @param {string} content
     */
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

    /**
     * Finalise the streaming message with the complete content.
     * @param {string} fullContent
     */
    function finaliseStreamingMessage(fullContent) {
        var container = document.getElementById("chat-messages");
        if (!container) return;

        var streamingMsg = container.querySelector(".message-streaming");
        if (!streamingMsg) return;

        streamingMsg.classList.remove("message-streaming");
        var markdownDiv = streamingMsg.querySelector(".markdown-content");
        if (markdownDiv) {
            markdownDiv.innerHTML = renderMarkdown(fullContent);
        }
    }

    /**
     * Remove the blinking streaming cursor from the chat.
     */
    function removeStreamingCursor() {
        var cursors = document.querySelectorAll(".streaming-cursor");
        for (var i = 0; i < cursors.length; i++) {
            cursors[i].parentNode.removeChild(cursors[i]);
        }
    }

    /**
     * Remove all tool execution indicators from the chat.
     */
    function removeToolIndicators() {
        var indicators = document.querySelectorAll(".tool-indicator");
        for (var i = 0; i < indicators.length; i++) {
            indicators[i].parentNode.removeChild(indicators[i]);
        }
    }

    /**
     * Scroll the chat container to the bottom.
     */
    function scrollChatToBottom() {
        var container = document.getElementById("chat-messages");
        if (container) {
            container.scrollTop = container.scrollHeight;
        }
    }

    /**
     * Disable the chat input and send button during streaming.
     */
    function disableInput() {
        var input = document.getElementById("chat-input");
        var btn = document.getElementById("send-btn");
        if (input) input.disabled = true;
        if (btn) btn.disabled = true;
    }

    /**
     * Enable the chat input and send button.
     */
    function enableInput() {
        var input = document.getElementById("chat-input");
        var btn = document.getElementById("send-btn");
        if (input) {
            input.disabled = false;
            input.focus();
        }
        if (btn) btn.disabled = false;
    }

    /**
     * Update the connection status indicator in the sidebar.
     * @param {boolean} connected
     */
    function updateConnectionIndicator(connected) {
        var wrapper = document.getElementById("connection-status");
        if (!wrapper) return;
        var dot = wrapper.querySelector(".status-dot");
        if (!dot) {
            // Fallback: indicator IS the dot.
            dot = wrapper;
        }
        dot.className = "status-dot " + (connected ? "connected" : "disconnected");
        wrapper.title = connected ? "Connected" : "Disconnected";
    }

    // =========================================================================
    // Section 7: Router / Navigation
    // =========================================================================

    /**
     * Navigate to a page.
     * @param {string} page - One of: chat, providers, sessions, tools, config
     */
    function navigateTo(page) {
        var validPages = ["chat", "providers", "sessions", "tools", "config"];
        if (validPages.indexOf(page) === -1) {
            console.warn("Invalid page:", page);
            page = "chat";
        }

        state.currentPage = page;

        // Update sidebar active state.
        var navItems = document.querySelectorAll(".nav-item");
        for (var i = 0; i < navItems.length; i++) {
            var item = navItems[i];
            if (item.dataset.page === page) {
                item.classList.add("active");
            } else {
                item.classList.remove("active");
            }
        }

        // Render the page content.
        renderPage(page);

        // Clear provider refresh if leaving providers page.
        if (page !== "providers" && state.providersRefreshTimer) {
            clearInterval(state.providersRefreshTimer);
            state.providersRefreshTimer = null;
        }
    }

    /**
     * Render the appropriate page into the main content area.
     * @param {string} page
     */
    function renderPage(page) {
        switch (page) {
            case "chat":
                renderChatPage();
                break;
            case "providers":
                renderProvidersPage();
                break;
            case "sessions":
                renderSessionsPage();
                break;
            case "tools":
                renderToolsPage();
                break;
            case "config":
                renderConfigPage();
                break;
        }
    }

    // =========================================================================
    // Section 8: Page Renderers
    // =========================================================================

    // ---- 8.1 Chat Page ----

    function renderChatPage() {
        var main = document.getElementById("main-content");
        if (!main) return;

        main.innerHTML =
            '<div class="page" style="display:flex;flex-direction:column;height:100%;">' +
                '<div class="page-header">' +
                    '<h1 class="page-title">Chat</h1>' +
                    '<div class="header-actions">' +
                        '<span class="session-selector">' +
                            '<span id="current-session-label" class="session-label">' +
                                escapeHtml(state.currentSessionKey) +
                            '</span>' +
                        '</span>' +
                    '</div>' +
                '</div>' +
                '<div id="chat-messages" class="chat-container"></div>' +
                '<div class="input-area">' +
                    '<div class="input-wrapper">' +
                        '<textarea id="chat-input" class="chat-input" ' +
                            'placeholder="Message ultrabot..." ' +
                            'rows="1"></textarea>' +
                        '<button id="send-btn" class="send-btn" title="Send">' +
                            '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>' +
                        '</button>' +
                    '</div>' +
                '</div>' +
            '</div>';

        // Re-render existing messages.
        var container = document.getElementById("chat-messages");
        if (container) {
            state.messages.forEach(function (msg) {
                appendMessageToChat(msg);
            });

            // If currently streaming, mark the last message.
            if (state.isStreaming && state.messages.length > 0) {
                var lastChild = container.lastElementChild;
                if (lastChild) {
                    lastChild.classList.add("message-streaming");
                    var md = lastChild.querySelector(".markdown-content");
                    if (md) {
                        md.innerHTML =
                            renderMarkdown(state.messages[state.messages.length - 1].content) +
                            '<span class="streaming-cursor"></span>';
                    }
                }
                disableInput();
            }
        }

        // Bind events.
        var input = document.getElementById("chat-input");
        var sendBtn = document.getElementById("send-btn");

        if (input) {
            input.addEventListener("keydown", function (e) {
                if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    var content = input.value;
                    if (content.trim()) {
                        sendMessage(content);
                        input.value = "";
                        autoResizeTextarea(input);
                    }
                }
            });

            input.addEventListener("input", function () {
                autoResizeTextarea(input);
            });

            if (!state.isStreaming) {
                input.focus();
            }
        }

        if (sendBtn) {
            sendBtn.addEventListener("click", function () {
                if (!input) return;
                var content = input.value;
                if (content.trim()) {
                    sendMessage(content);
                    input.value = "";
                    autoResizeTextarea(input);
                }
            });
        }

        scrollChatToBottom();
    }

    /**
     * Auto-resize textarea to fit content.
     * @param {HTMLTextAreaElement} textarea
     */
    function autoResizeTextarea(textarea) {
        textarea.style.height = "auto";
        var maxHeight = 200;
        textarea.style.height = Math.min(textarea.scrollHeight, maxHeight) + "px";
    }

    // ---- 8.2 Providers Page ----

    function renderProvidersPage() {
        var main = document.getElementById("main-content");
        if (!main) return;

        main.innerHTML =
            '<div class="page" style="display:flex;flex-direction:column;height:100%;">' +
                '<div class="page-header">' +
                    '<h1 class="page-title">Providers</h1>' +
                    '<div class="header-actions">' +
                        '<button id="providers-refresh-btn" class="btn btn-ghost">Refresh</button>' +
                    '</div>' +
                '</div>' +
                '<div class="page-content">' +
                    '<div id="providers-grid" class="providers-grid">' +
                        '<div class="loading-spinner"></div>' +
                    '</div>' +
                '</div>' +
            '</div>';

        loadProviders();

        var refreshBtn = document.getElementById("providers-refresh-btn");
        if (refreshBtn) {
            refreshBtn.addEventListener("click", loadProviders);
        }

        // Auto-refresh every 30 seconds.
        if (state.providersRefreshTimer) clearInterval(state.providersRefreshTimer);
        state.providersRefreshTimer = setInterval(function () {
            if (state.currentPage === "providers") {
                loadProviders();
            }
        }, 30000);
    }

    function loadProviders() {
        apiFetch("/api/providers")
            .then(function (data) {
                var grid = document.getElementById("providers-grid");
                if (!grid || state.currentPage !== "providers") return;

                var providers = data.providers || {};
                var keys = Object.keys(providers);

                if (keys.length === 0) {
                    grid.innerHTML = '<p class="empty-state">No providers configured.</p>';
                    return;
                }

                var html = "";
                keys.forEach(function (name) {
                    var healthy = providers[name];
                    var statusClass = healthy ? "healthy" : "unhealthy";
                    var statusText = healthy ? "Healthy" : "Unhealthy";

                    html +=
                        '<div class="provider-card">' +
                            '<div class="provider-card-header">' +
                                '<span class="status-dot ' + statusClass + '"></span>' +
                                '<h3>' + escapeHtml(name) + '</h3>' +
                            '</div>' +
                            '<div class="provider-card-body">' +
                                '<p class="provider-status">Status: ' + statusText + '</p>' +
                            '</div>' +
                        '</div>';
                });

                grid.innerHTML = html;
            })
            .catch(function (err) {
                var grid = document.getElementById("providers-grid");
                if (grid) {
                    grid.innerHTML =
                        '<p class="error-text">Failed to load providers: ' +
                        escapeHtml(err.message) +
                        "</p>";
                }
                showToast("Failed to load providers: " + err.message, "error");
            });
    }

    // ---- 8.3 Sessions Page ----

    function renderSessionsPage() {
        var main = document.getElementById("main-content");
        if (!main) return;

        main.innerHTML =
            '<div class="page" style="display:flex;flex-direction:column;height:100%;">' +
                '<div class="page-header">' +
                    '<h1 class="page-title">Sessions</h1>' +
                    '<div class="header-actions">' +
                        '<button id="sessions-refresh-btn" class="btn btn-ghost">Refresh</button>' +
                    '</div>' +
                '</div>' +
                '<div class="page-content">' +
                    '<div id="sessions-list" class="sessions-list">' +
                        '<div class="loading-spinner"></div>' +
                    '</div>' +
                    '<div id="session-messages-panel" class="session-messages-panel" style="display:none;">' +
                        '<div class="page-header" style="height:auto;padding:12px 16px;">' +
                            '<h3 id="session-messages-title" class="page-title" style="font-size:0.9375rem;">Messages</h3>' +
                            '<div class="header-actions">' +
                                '<button id="session-messages-close" class="btn btn-ghost">Close</button>' +
                            '</div>' +
                        '</div>' +
                        '<div id="session-messages-content" class="session-messages-content"></div>' +
                    '</div>' +
                '</div>' +
            '</div>';

        loadSessions();

        var refreshBtn = document.getElementById("sessions-refresh-btn");
        if (refreshBtn) {
            refreshBtn.addEventListener("click", loadSessions);
        }

        var closeBtn = document.getElementById("session-messages-close");
        if (closeBtn) {
            closeBtn.addEventListener("click", function () {
                var panel = document.getElementById("session-messages-panel");
                if (panel) panel.style.display = "none";
            });
        }
    }

    function loadSessions() {
        apiFetch("/api/sessions")
            .then(function (data) {
                var list = document.getElementById("sessions-list");
                if (!list || state.currentPage !== "sessions") return;

                var sessions = data.sessions || [];

                if (sessions.length === 0) {
                    list.innerHTML = '<p class="empty-state">No active sessions.</p>';
                    return;
                }

                var html = "";
                sessions.forEach(function (sessionKey) {
                    var isActive = sessionKey === state.currentSessionKey;
                    html +=
                        '<div class="session-item' + (isActive ? " active" : "") + '" data-session="' +
                        escapeHtml(sessionKey) + '">' +
                            '<div class="session-item-info">' +
                                '<span class="session-item-name">' + escapeHtml(sessionKey) + '</span>' +
                                (isActive ? '<span class="session-item-badge">Current</span>' : '') +
                            '</div>' +
                            '<div class="session-item-actions">' +
                                '<button class="btn btn-ghost session-view-btn" data-session="' +
                                    escapeHtml(sessionKey) + '">View</button>' +
                                '<button class="btn btn-ghost session-switch-btn" data-session="' +
                                    escapeHtml(sessionKey) + '">Switch</button>' +
                                '<button class="btn btn-danger session-delete-btn" data-session="' +
                                    escapeHtml(sessionKey) + '">Delete</button>' +
                            '</div>' +
                        '</div>';
                });

                list.innerHTML = html;

                // Bind session action events.
                list.querySelectorAll(".session-view-btn").forEach(function (btn) {
                    btn.addEventListener("click", function (e) {
                        e.stopPropagation();
                        viewSessionMessages(btn.dataset.session);
                    });
                });

                list.querySelectorAll(".session-switch-btn").forEach(function (btn) {
                    btn.addEventListener("click", function (e) {
                        e.stopPropagation();
                        switchSession(btn.dataset.session);
                    });
                });

                list.querySelectorAll(".session-delete-btn").forEach(function (btn) {
                    btn.addEventListener("click", function (e) {
                        e.stopPropagation();
                        deleteSession(btn.dataset.session);
                    });
                });
            })
            .catch(function (err) {
                var list = document.getElementById("sessions-list");
                if (list) {
                    list.innerHTML =
                        '<p class="error-text">Failed to load sessions: ' +
                        escapeHtml(err.message) +
                        "</p>";
                }
                showToast("Failed to load sessions: " + err.message, "error");
            });
    }

    function viewSessionMessages(sessionKey) {
        var panel = document.getElementById("session-messages-panel");
        var title = document.getElementById("session-messages-title");
        var content = document.getElementById("session-messages-content");
        if (!panel || !content) return;

        title.textContent = "Messages: " + sessionKey;
        content.innerHTML = '<div class="loading-spinner">Loading messages...</div>';
        panel.style.display = "block";

        apiFetch("/api/sessions/" + encodeURIComponent(sessionKey) + "/messages")
            .then(function (data) {
                var messages = data.messages || [];

                if (messages.length === 0) {
                    content.innerHTML = '<p class="empty-state">No messages in this session.</p>';
                    return;
                }

                var html = "";
                messages.forEach(function (msg) {
                    html +=
                        '<div class="message message-' + escapeHtml(msg.role) + '">' +
                            '<div class="message-avatar">' + (msg.role === "user" ? "U" : "A") + '</div>' +
                            '<div class="message-content">' +
                                '<div class="markdown-content">' + renderMarkdown(msg.content) + '</div>' +
                            '</div>' +
                        '</div>';
                });

                content.innerHTML = html;
            })
            .catch(function (err) {
                content.innerHTML =
                    '<p class="error-text">Failed to load messages: ' +
                    escapeHtml(err.message) +
                    "</p>";
            });
    }

    function switchSession(sessionKey) {
        state.currentSessionKey = sessionKey;
        state.messages = [];
        showToast("Switched to session: " + sessionKey, "info");
        loadSessions(); // Re-render to update active indicator.

        // Update session label if on chat page.
        var label = document.getElementById("current-session-label");
        if (label) label.textContent = sessionKey;
    }

    function deleteSession(sessionKey) {
        if (sessionKey === state.currentSessionKey) {
            showToast("Cannot delete the active session. Switch to another session first.", "error");
            return;
        }

        apiFetch("/api/sessions/" + encodeURIComponent(sessionKey), { method: "DELETE" })
            .then(function () {
                showToast("Session deleted: " + sessionKey, "success");
                loadSessions();
            })
            .catch(function (err) {
                showToast("Failed to delete session: " + err.message, "error");
            });
    }

    // ---- 8.4 Tools Page ----

    function renderToolsPage() {
        var main = document.getElementById("main-content");
        if (!main) return;

        main.innerHTML =
            '<div class="page" style="display:flex;flex-direction:column;height:100%;">' +
                '<div class="page-header">' +
                    '<h1 class="page-title">Tools</h1>' +
                    '<div class="header-actions">' +
                        '<button id="tools-refresh-btn" class="btn btn-ghost">Refresh</button>' +
                    '</div>' +
                '</div>' +
                '<div class="page-content">' +
                    '<div id="tools-grid" class="tools-grid">' +
                        '<div class="loading-spinner"></div>' +
                    '</div>' +
                '</div>' +
            '</div>';

        loadTools();

        var refreshBtn = document.getElementById("tools-refresh-btn");
        if (refreshBtn) {
            refreshBtn.addEventListener("click", loadTools);
        }
    }

    function loadTools() {
        apiFetch("/api/tools")
            .then(function (data) {
                var grid = document.getElementById("tools-grid");
                if (!grid || state.currentPage !== "tools") return;

                var tools = data.tools || [];

                if (tools.length === 0) {
                    grid.innerHTML = '<p class="empty-state">No tools available.</p>';
                    return;
                }

                var html = "";
                tools.forEach(function (tool) {
                    var fn = tool.function || tool || {};
                    var name = fn.name || "unknown";
                    var description = fn.description || "No description available.";
                    var parameters = fn.parameters || null;

                    var paramsHtml = "";
                    if (parameters && parameters.properties) {
                        var props = parameters.properties;
                        var required = parameters.required || [];
                        var paramKeys = Object.keys(props);

                        paramsHtml = '<div class="tool-params"><h4>Parameters</h4><ul>';
                        paramKeys.forEach(function (key) {
                            var prop = props[key];
                            var isRequired = required.indexOf(key) !== -1;
                            var typeStr = prop.type || "any";
                            var desc = prop.description || "";

                            paramsHtml +=
                                "<li>" +
                                    '<span class="param-name">' + escapeHtml(key) + "</span>" +
                                    '<span class="param-type">' + escapeHtml(typeStr) + "</span>" +
                                    (isRequired ? '<span class="param-required">required</span>' : "") +
                                    (desc ? '<span class="param-desc"> - ' + escapeHtml(desc) + "</span>" : "") +
                                "</li>";
                        });
                        paramsHtml += "</ul></div>";
                    }

                    html +=
                        '<div class="tool-card">' +
                            '<div class="tool-card-header">' +
                                '<h3>' + escapeHtml(name) + '</h3>' +
                            '</div>' +
                            '<div class="tool-card-body">' +
                                '<p class="tool-description">' + escapeHtml(description) + '</p>' +
                                paramsHtml +
                            '</div>' +
                        '</div>';
                });

                grid.innerHTML = html;
            })
            .catch(function (err) {
                var grid = document.getElementById("tools-grid");
                if (grid) {
                    grid.innerHTML =
                        '<p class="error-text">Failed to load tools: ' +
                        escapeHtml(err.message) +
                        "</p>";
                }
                showToast("Failed to load tools: " + err.message, "error");
            });
    }

    // ---- 8.5 Config Page ----

    function renderConfigPage() {
        var main = document.getElementById("main-content");
        if (!main) return;

        main.innerHTML =
            '<div class="page" style="display:flex;flex-direction:column;height:100%;">' +
                '<div class="page-header">' +
                    '<h1 class="page-title">Configuration</h1>' +
                    '<div class="header-actions">' +
                        '<button id="config-reload-btn" class="btn btn-ghost">Reload</button>' +
                        '<button id="config-save-btn" class="btn btn-primary">Save</button>' +
                    '</div>' +
                '</div>' +
                '<div class="page-content">' +
                    '<div class="config-editor-container">' +
                        '<textarea id="config-editor" class="config-editor" ' +
                            'spellcheck="false" placeholder="Loading configuration..."></textarea>' +
                        '<p id="config-status" class="config-status"></p>' +
                    '</div>' +
                '</div>' +
            '</div>';

        loadConfig();

        var saveBtn = document.getElementById("config-save-btn");
        if (saveBtn) {
            saveBtn.addEventListener("click", saveConfig);
        }

        var reloadBtn = document.getElementById("config-reload-btn");
        if (reloadBtn) {
            reloadBtn.addEventListener("click", loadConfig);
        }
    }

    function loadConfig() {
        var editor = document.getElementById("config-editor");
        var status = document.getElementById("config-status");
        if (!editor) return;

        editor.value = "Loading...";
        editor.disabled = true;

        apiFetch("/api/config")
            .then(function (data) {
                if (state.currentPage !== "config") return;
                var config = data.config || data;
                editor.value = JSON.stringify(config, null, 2);
                editor.disabled = false;
                if (status) {
                    status.textContent = "Configuration loaded.";
                    status.className = "config-status";
                }
            })
            .catch(function (err) {
                editor.value = "";
                editor.disabled = false;
                if (status) {
                    status.textContent = "Failed to load: " + err.message;
                    status.className = "config-status config-status-error";
                }
                showToast("Failed to load config: " + err.message, "error");
            });
    }

    function saveConfig() {
        var editor = document.getElementById("config-editor");
        var status = document.getElementById("config-status");
        if (!editor) return;

        var raw = editor.value.trim();
        var parsed;

        try {
            parsed = JSON.parse(raw);
        } catch (e) {
            showToast("Invalid JSON: " + e.message, "error");
            if (status) {
                status.textContent = "Invalid JSON: " + e.message;
                status.className = "config-status config-status-error";
            }
            return;
        }

        var saveBtn = document.getElementById("config-save-btn");
        if (saveBtn) {
            saveBtn.disabled = true;
            saveBtn.textContent = "Saving...";
        }

        apiFetch("/api/config", {
            method: "PUT",
            body: JSON.stringify({ config: parsed }),
        })
            .then(function () {
                showToast("Configuration saved successfully.", "success");
                if (status) {
                    status.textContent = "Saved successfully.";
                    status.className = "config-status config-status-success";
                }
            })
            .catch(function (err) {
                showToast("Failed to save config: " + err.message, "error");
                if (status) {
                    status.textContent = "Save failed: " + err.message;
                    status.className = "config-status config-status-error";
                }
            })
            .finally(function () {
                if (saveBtn) {
                    saveBtn.disabled = false;
                    saveBtn.textContent = "Save";
                }
            });
    }

    // =========================================================================
    // Section 9: Theme Toggle
    // =========================================================================

    /**
     * Apply a theme ('light' or 'dark') to the document.
     * @param {string} theme
     */
    function applyTheme(theme) {
        document.documentElement.setAttribute("data-theme", theme);
        localStorage.setItem("ultrabot-theme", theme);

        var sunIcon = document.getElementById("theme-icon-sun");
        var moonIcon = document.getElementById("theme-icon-moon");
        var label = document.getElementById("theme-label");

        if (theme === "dark") {
            if (sunIcon) sunIcon.style.display = "none";
            if (moonIcon) moonIcon.style.display = "";
            if (label) label.textContent = "Dark";
        } else {
            if (sunIcon) sunIcon.style.display = "";
            if (moonIcon) moonIcon.style.display = "none";
            if (label) label.textContent = "Light";
        }
    }

    /**
     * Toggle between light and dark themes.
     */
    function toggleTheme() {
        var current = document.documentElement.getAttribute("data-theme") || "light";
        applyTheme(current === "dark" ? "light" : "dark");
    }

    // =========================================================================
    // Section 10: Sidebar & Layout Initialisation
    // =========================================================================

    /**
     * Build the application shell (sidebar + main content area).
     */
    function buildAppShell() {
        var app = document.getElementById("app");
        if (!app) {
            app = document.createElement("div");
            app.id = "app";
            document.body.appendChild(app);
        }

        app.innerHTML =
            '<aside class="sidebar">' +
                '<div class="sidebar-header">' +
                    '<div class="logo">' +
                        '<span class="logo-icon">&#x1F916;</span>' +
                        '<span class="logo-text">ultrabot</span>' +
                    '</div>' +
                    '<span id="connection-status" class="status-dot disconnected" title="Disconnected"></span>' +
                '</div>' +
                '<nav class="sidebar-nav">' +
                    '<a href="#" class="nav-item active" data-page="chat">' +
                        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>' +
                        '<span>Chat</span>' +
                    '</a>' +
                    '<a href="#" class="nav-item" data-page="providers">' +
                        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>' +
                        '<span>Providers</span>' +
                    '</a>' +
                    '<a href="#" class="nav-item" data-page="sessions">' +
                        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>' +
                        '<span>Sessions</span>' +
                    '</a>' +
                    '<a href="#" class="nav-item" data-page="tools">' +
                        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>' +
                        '<span>Tools</span>' +
                    '</a>' +
                    '<a href="#" class="nav-item" data-page="config">' +
                        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>' +
                        '<span>Config</span>' +
                    '</a>' +
                '</nav>' +
                '<div class="sidebar-footer">' +
                    '<button class="theme-btn" id="theme-toggle-btn" title="Toggle theme">' +
                        '<svg id="theme-icon-sun" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>' +
                        '<svg id="theme-icon-moon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="display:none"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>' +
                        '<span id="theme-label">Light</span>' +
                    '</button>' +
                    '<div class="sidebar-info">ultrabot v0.1.0</div>' +
                '</div>' +
            '</aside>' +
            '<main id="main-content" class="main-content"></main>';

        // Bind navigation events.
        var navItems = document.querySelectorAll(".nav-item");
        navItems.forEach(function (item) {
            item.addEventListener("click", function () {
                navigateTo(item.dataset.page);
            });
        });

        // Bind theme toggle.
        var themeBtn = document.getElementById("theme-toggle-btn");
        if (themeBtn) {
            themeBtn.addEventListener("click", toggleTheme);
        }

        // Restore persisted theme.
        applyTheme(localStorage.getItem("ultrabot-theme") || "light");
    }

    // =========================================================================
    // Section 11: Initialisation
    // =========================================================================

    /**
     * Boot the application when the DOM is ready.
     */
    function init() {
        buildAppShell();
        connectWebSocket();
        navigateTo("chat");

        // Verify backend health.
        apiFetch("/api/health")
            .then(function (data) {
                if (data && data.status === "ok") {
                    console.log("[App] Backend health check passed.");
                }
            })
            .catch(function (err) {
                console.warn("[App] Backend health check failed:", err.message);
                showToast("Backend unreachable: " + err.message, "error");
            });
    }

    // Boot on DOM ready.
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    // =========================================================================
    // Section 12: Public API (attach to window for debugging / external use)
    // =========================================================================

    window.UltrabotApp = {
        state: state,
        navigateTo: navigateTo,
        sendMessage: sendMessage,
        showToast: showToast,
        connectWebSocket: connectWebSocket,
        renderMarkdown: renderMarkdown,
        escapeHtml: escapeHtml,
        formatTimestamp: formatTimestamp,
        debounce: debounce,
        toggleTheme: toggleTheme,
        applyTheme: applyTheme,
    };
})();
