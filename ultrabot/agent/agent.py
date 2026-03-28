"""Core agent loop -- orchestrates LLM calls, tool execution, and sessions."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from loguru import logger

from ultrabot.agent.prompts import build_expert_system_prompt, build_system_prompt
from ultrabot.tools.base import ToolRegistry

if TYPE_CHECKING:
    from ultrabot.experts.parser import ExpertPersona


# ------------------------------------------------------------------
# Lightweight data classes used by the agent loop
# ------------------------------------------------------------------


@dataclass(slots=True)
class ToolCallRequest:
    """Represents a single tool-call requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


# Type aliases for the optional callbacks.
ContentDeltaCB = Callable[[str], None] | Callable[[str], Coroutine[Any, Any, None]] | None
ToolHintCB = Callable[[str, str], None] | Callable[[str, str], Coroutine[Any, Any, None]] | None


class Agent:
    """High-level agent that ties together an LLM provider, a session store,
    a tool registry, and an optional security guard.

    The main entry point is :meth:`run`, which accepts a user message and
    drives the conversation-tool loop until the model produces a final text
    response or the iteration limit is reached.
    """

    def __init__(
        self,
        config: Any,
        provider_manager: Any,
        session_manager: Any,
        tool_registry: ToolRegistry,
        security_guard: Any | None = None,
    ) -> None:
        self._config = config
        self._provider = provider_manager
        self._sessions = session_manager
        self._tools = tool_registry
        self._security = security_guard

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        user_message: str,
        session_key: str,
        media: list[str] | None = None,
        on_content_delta: ContentDeltaCB = None,
        on_tool_hint: ToolHintCB = None,
        expert_persona: "ExpertPersona | None" = None,
    ) -> str:
        """Process a single user turn and return the assistant's text reply.

        Parameters
        ----------
        user_message:
            The latest message from the user.
        session_key:
            Identifier for the conversation session.
        media:
            Optional list of media URLs / paths attached to the message.
        on_content_delta:
            Streaming callback invoked with each text chunk as it arrives.
        on_tool_hint:
            Callback invoked with ``(tool_name, tool_call_id)`` when the
            agent begins executing a tool so the front-end can show progress.
        expert_persona:
            Optional :class:`ExpertPersona` to activate for this turn.
            When provided the system prompt is replaced with the expert's
            persona definition combined with tool-use instructions.

        Returns
        -------
        str
            The final assistant text response.
        """
        max_iterations: int = getattr(self._config, "max_tool_iterations", 10)

        # 1. Retrieve or create the session, then append the user message.
        session = await self._sessions.get_or_create(session_key)
        user_msg = self._build_user_message(user_message, media)
        session.add_message(user_msg)

        # 2. Prepare tool definitions.
        tool_defs = self._get_tool_definitions()

        # 3. Enter the tool loop.
        final_content = ""
        for iteration in range(1, max_iterations + 1):
            logger.debug(
                "Agent loop iteration {}/{} for session {!r}",
                iteration,
                max_iterations,
                session_key,
            )

            messages = self._prepare_messages(session, expert_persona=expert_persona)

            # Call the LLM provider.
            response = await self._provider.chat_stream_with_retry(
                messages=messages,
                tools=tool_defs if tool_defs else None,
                on_content_delta=on_content_delta,
            )

            # The provider should return an object with .content and .tool_calls.
            assistant_content: str = getattr(response, "content", "") or ""
            tool_calls_raw: list[Any] = getattr(response, "tool_calls", None) or []

            # Persist the assistant message in the session.
            assistant_msg = self._build_assistant_message(assistant_content, tool_calls_raw)
            session.add_message(assistant_msg)

            if not tool_calls_raw:
                # No tool calls -- we have the final answer.
                final_content = assistant_content
                break

            # Parse tool calls.
            tool_requests = self._parse_tool_calls(tool_calls_raw)
            logger.info(
                "LLM requested {} tool call(s): {}",
                len(tool_requests),
                ", ".join(tc.name for tc in tool_requests),
            )

            # Notify the front-end.
            for tc in tool_requests:
                await self._invoke_callback(on_tool_hint, tc.name, tc.id)

            # Execute tools concurrently and append results.
            tool_results = await self._execute_tools(tool_requests)
            for result_msg in tool_results:
                session.add_message(result_msg)
        else:
            # Exhausted iterations without a final response.
            logger.warning(
                "Agent hit max_tool_iterations ({}) for session {!r}",
                max_iterations,
                session_key,
            )
            if not final_content:
                final_content = (
                    "I have reached the maximum number of tool iterations without "
                    "producing a final answer.  Please try simplifying your request."
                )

        # 4. Trim session to stay within the context window.
        context_window: int = getattr(self._config, "context_window", 128_000)
        session.trim(max_tokens=context_window)

        return final_content

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def _execute_tools(
        self, tool_calls: list[ToolCallRequest]
    ) -> list[dict[str, Any]]:
        """Execute one or more tool calls concurrently.

        Each result is a message dict with role ``"tool"``.
        """

        async def _run_one(tc: ToolCallRequest) -> dict[str, Any]:
            tool = self._tools.get(tc.name)
            if tool is None:
                logger.error("Unknown tool requested: {!r}", tc.name)
                return {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": f"Error: unknown tool '{tc.name}'.",
                }

            # Optional security check.
            if self._security is not None:
                try:
                    allowed = await self._security.check(tc.name, tc.arguments)
                    if not allowed:
                        return {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": f"Error: tool '{tc.name}' was blocked by the security guard.",
                        }
                except Exception as exc:
                    logger.error("Security check failed for {!r}: {}", tc.name, exc)
                    return {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": f"Error: security check failed -- {exc}",
                    }

            try:
                logger.info("Executing tool {!r} (call_id={})", tc.name, tc.id)
                result = await tool.execute(tc.arguments)
                return {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(result),
                }
            except Exception as exc:
                logger.exception("Tool {!r} raised an exception", tc.name)
                return {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": f"Error executing tool '{tc.name}': {type(exc).__name__}: {exc}",
                }

        results = await asyncio.gather(*[_run_one(tc) for tc in tool_calls])
        return list(results)

    # ------------------------------------------------------------------
    # Prompt / message construction
    # ------------------------------------------------------------------

    def _build_system_prompt(
        self,
        expert_persona: "ExpertPersona | None" = None,
    ) -> str:
        workspace = getattr(self._config, "workspace_path", None)
        tz = getattr(self._config, "timezone", None)
        if expert_persona is not None:
            return build_expert_system_prompt(
                persona=expert_persona,
                config=self._config,
                workspace_path=workspace,
                tz=tz,
            )
        return build_system_prompt(config=self._config, workspace_path=workspace, tz=tz)

    def _get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return the list of OpenAI-format tool schemas from the registry."""
        return self._tools.get_definitions()

    def _prepare_messages(
        self,
        session: Any,
        expert_persona: "ExpertPersona | None" = None,
    ) -> list[dict[str, Any]]:
        """Build the full message list to send to the LLM, including the
        system prompt as the first message."""
        system_msg = {
            "role": "system",
            "content": self._build_system_prompt(expert_persona=expert_persona),
        }
        return [system_msg] + session.get_messages()

    @staticmethod
    def _build_user_message(
        text: str, media: list[str] | None = None
    ) -> dict[str, Any]:
        """Construct the user message dict."""
        if media:
            # Multi-modal: include media as content parts.
            parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
            for url in media:
                parts.append({"type": "image_url", "image_url": {"url": url}})
            return {"role": "user", "content": parts}
        return {"role": "user", "content": text}

    @staticmethod
    def _build_assistant_message(
        content: str, tool_calls_raw: list[Any]
    ) -> dict[str, Any]:
        """Construct the assistant message dict, including tool_calls if any."""
        msg: dict[str, Any] = {"role": "assistant"}
        if content:
            msg["content"] = content
        if tool_calls_raw:
            msg["tool_calls"] = tool_calls_raw
        if not content and not tool_calls_raw:
            msg["content"] = ""
        return msg

    # ------------------------------------------------------------------
    # Tool-call parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_tool_calls(raw: list[Any]) -> list[ToolCallRequest]:
        """Convert raw tool-call objects (dicts or provider-specific objects)
        into a uniform list of :class:`ToolCallRequest`."""
        requests: list[ToolCallRequest] = []
        for item in raw:
            if isinstance(item, dict):
                tc_id = item.get("id", "")
                func = item.get("function", {})
                name = func.get("name", "")
                args_raw = func.get("arguments", "{}")
            else:
                # Assume an object with .id, .function.name, .function.arguments
                tc_id = getattr(item, "id", "")
                func_obj = getattr(item, "function", None)
                name = getattr(func_obj, "name", "") if func_obj else ""
                args_raw = getattr(func_obj, "arguments", "{}") if func_obj else "{}"

            # Parse arguments JSON.
            if isinstance(args_raw, str):
                try:
                    arguments = json.loads(args_raw)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(
                        "Failed to parse tool arguments for {!r}: {!r}",
                        name,
                        args_raw,
                    )
                    arguments = {}
            elif isinstance(args_raw, dict):
                arguments = args_raw
            else:
                arguments = {}

            requests.append(ToolCallRequest(id=tc_id, name=name, arguments=arguments))
        return requests

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _invoke_callback(cb: Any, *args: Any) -> None:
        """Safely invoke a callback that may be sync or async."""
        if cb is None:
            return
        try:
            result = cb(*args)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.warning("Callback raised an exception: {}", exc)
