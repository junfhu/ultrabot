"""Public API for the security package."""

from ultrabot.security.guard import (
    AccessController,
    InputSanitizer,
    RateLimiter,
    SecurityConfig,
    SecurityGuard,
)

__all__ = [
    "AccessController",
    "InputSanitizer",
    "RateLimiter",
    "SecurityConfig",
    "SecurityGuard",
    "ToolPermissionManager",
    "PermissionDecision",
    "AuditEntry",
]


def __getattr__(name: str):
    if name in ("ToolPermissionManager", "PermissionDecision", "AuditEntry"):
        from ultrabot.security.permissions import (
            AuditEntry,
            PermissionDecision,
            ToolPermissionManager,
        )
        return {"ToolPermissionManager": ToolPermissionManager, "PermissionDecision": PermissionDecision, "AuditEntry": AuditEntry}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
