"""Tool permission and approval system.

Provides per-tool wildcard permission patterns, interactive approval,
and an audit log of all tool executions.

Inspired by Claude Code's permission system where tools can be:
- Always allowed (via wildcard patterns)
- Always denied
- Require interactive approval
"""
from __future__ import annotations

import fnmatch
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger


# ---------------------------------------------------------------------------
# Permission decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PermissionDecision:
    """Result of a permission check."""

    allowed: bool
    reason: str = ""
    rule: str = ""  # which rule matched


# ---------------------------------------------------------------------------
# Audit log entry
# ---------------------------------------------------------------------------


@dataclass
class AuditEntry:
    """A single tool execution audit record."""

    timestamp: float = field(default_factory=time.time)
    tool_name: str = ""
    arguments_summary: str = ""
    decision: str = ""  # "allowed", "denied", "approved", "rejected"
    rule: str = ""
    session_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "tool_name": self.tool_name,
            "arguments_summary": self.arguments_summary,
            "decision": self.decision,
            "rule": self.rule,
            "session_key": self.session_key,
        }


# ---------------------------------------------------------------------------
# Tool permission manager
# ---------------------------------------------------------------------------


class ToolPermissionManager:
    """Manages tool execution permissions with wildcard patterns and audit logging.

    Parameters
    ----------
    allow_patterns : list[str]
        Glob patterns for tools that are always allowed.
        Example: ``["read_file", "list_*", "web_search"]``
    deny_patterns : list[str]
        Glob patterns for tools that are always denied.
        Example: ``["exec_command", "write_file"]``
    ask_patterns : list[str]
        Glob patterns for tools that require interactive approval.
        If empty and a tool matches neither allow nor deny, it's allowed
        by default.
    default_policy : str
        What to do when no pattern matches: ``"allow"``, ``"deny"``, or ``"ask"``.
    audit_path : Path | None
        Path to audit log file. If None, audit entries are kept in memory only.
    approval_callback : callable | None
        Async or sync callback ``(tool_name, args) -> bool`` used to prompt
        the user for approval when a tool matches an ``ask`` pattern.
    """

    def __init__(
        self,
        allow_patterns: list[str] | None = None,
        deny_patterns: list[str] | None = None,
        ask_patterns: list[str] | None = None,
        default_policy: str = "allow",
        audit_path: Path | None = None,
        approval_callback: Any | None = None,
    ) -> None:
        self._allow = allow_patterns or []
        self._deny = deny_patterns or []
        self._ask = ask_patterns or []
        self._default = default_policy
        self._audit_path = audit_path
        self._approval_cb = approval_callback
        self._audit_log: list[AuditEntry] = []

        if audit_path:
            audit_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Pattern matching
    # ------------------------------------------------------------------

    @staticmethod
    def _matches_any(tool_name: str, patterns: list[str]) -> str | None:
        """Return the first pattern that matches *tool_name*, or None."""
        for pattern in patterns:
            if fnmatch.fnmatch(tool_name, pattern):
                return pattern
        return None

    # ------------------------------------------------------------------
    # Permission check
    # ------------------------------------------------------------------

    async def check(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        session_key: str = "",
    ) -> PermissionDecision:
        """Check whether *tool_name* is allowed to execute.

        Evaluation order:
        1. Deny patterns (highest priority)
        2. Allow patterns
        3. Ask patterns (interactive approval)
        4. Default policy
        """
        args_summary = self._summarize_args(arguments)

        # 1. Deny
        deny_rule = self._matches_any(tool_name, self._deny)
        if deny_rule is not None:
            decision = PermissionDecision(allowed=False, reason="denied by pattern", rule=deny_rule)
            self._record(tool_name, args_summary, "denied", deny_rule, session_key)
            return decision

        # 2. Allow
        allow_rule = self._matches_any(tool_name, self._allow)
        if allow_rule is not None:
            decision = PermissionDecision(allowed=True, reason="allowed by pattern", rule=allow_rule)
            self._record(tool_name, args_summary, "allowed", allow_rule, session_key)
            return decision

        # 3. Ask
        ask_rule = self._matches_any(tool_name, self._ask)
        if ask_rule is not None:
            approved = await self._prompt_approval(tool_name, arguments)
            status = "approved" if approved else "rejected"
            decision = PermissionDecision(
                allowed=approved,
                reason=f"interactive {status}",
                rule=ask_rule,
            )
            self._record(tool_name, args_summary, status, ask_rule, session_key)
            return decision

        # 4. Default
        if self._default == "deny":
            decision = PermissionDecision(allowed=False, reason="denied by default policy", rule="default:deny")
            self._record(tool_name, args_summary, "denied", "default:deny", session_key)
            return decision
        elif self._default == "ask":
            approved = await self._prompt_approval(tool_name, arguments)
            status = "approved" if approved else "rejected"
            decision = PermissionDecision(
                allowed=approved,
                reason=f"interactive {status} (default policy)",
                rule="default:ask",
            )
            self._record(tool_name, args_summary, status, "default:ask", session_key)
            return decision
        else:
            decision = PermissionDecision(allowed=True, reason="allowed by default policy", rule="default:allow")
            self._record(tool_name, args_summary, "allowed", "default:allow", session_key)
            return decision

    # ------------------------------------------------------------------
    # Interactive approval
    # ------------------------------------------------------------------

    async def _prompt_approval(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
    ) -> bool:
        """Prompt the user for approval. Falls back to allow if no callback."""
        if self._approval_cb is None:
            logger.debug("No approval callback; auto-allowing {}", tool_name)
            return True

        import asyncio

        try:
            result = self._approval_cb(tool_name, arguments)
            if asyncio.iscoroutine(result):
                return await result
            return bool(result)
        except Exception as exc:
            logger.warning("Approval callback failed for {}: {}", tool_name, exc)
            return False

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------

    def _record(
        self,
        tool_name: str,
        args_summary: str,
        decision: str,
        rule: str,
        session_key: str,
    ) -> None:
        """Record a permission decision to the audit log."""
        entry = AuditEntry(
            tool_name=tool_name,
            arguments_summary=args_summary,
            decision=decision,
            rule=rule,
            session_key=session_key,
        )
        self._audit_log.append(entry)

        logger.debug(
            "Tool permission: {} {} (rule={}, session={})",
            tool_name,
            decision,
            rule,
            session_key,
        )

        # Persist to file
        if self._audit_path:
            try:
                with open(self._audit_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
            except Exception:
                logger.debug("Failed to write audit entry", exc_info=True)

    @staticmethod
    def _summarize_args(arguments: dict[str, Any] | None) -> str:
        """Create a brief summary of tool arguments for the audit log."""
        if not arguments:
            return ""
        parts = []
        for k, v in arguments.items():
            v_str = str(v)
            if len(v_str) > 80:
                v_str = v_str[:77] + "..."
            parts.append(f"{k}={v_str}")
        return "; ".join(parts)

    # ------------------------------------------------------------------
    # Query audit log
    # ------------------------------------------------------------------

    def get_audit_log(
        self,
        limit: int = 100,
        tool_name: str | None = None,
    ) -> list[AuditEntry]:
        """Return recent audit entries, optionally filtered by tool name."""
        entries = self._audit_log
        if tool_name:
            entries = [e for e in entries if e.tool_name == tool_name]
        return entries[-limit:]

    def get_audit_summary(self) -> dict[str, Any]:
        """Return a summary of the audit log."""
        by_tool: dict[str, dict[str, int]] = {}
        for entry in self._audit_log:
            if entry.tool_name not in by_tool:
                by_tool[entry.tool_name] = {"allowed": 0, "denied": 0, "approved": 0, "rejected": 0}
            if entry.decision in by_tool[entry.tool_name]:
                by_tool[entry.tool_name][entry.decision] += 1

        return {
            "total_checks": len(self._audit_log),
            "by_tool": by_tool,
        }
