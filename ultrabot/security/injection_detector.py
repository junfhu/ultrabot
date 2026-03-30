"""Prompt-injection detection for user-supplied content.

Scans text for common injection patterns:
  * system-prompt override phrases
  * invisible Unicode characters (zero-width spaces, RTL overrides, etc.)
  * HTML comment injection
  * credential exfiltration attempts
  * base64-encoded suspicious payloads

Inspired by hermes-agent's ``agent/prompt_builder.py`` injection scanning.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path


# ------------------------------------------------------------------
# Data types
# ------------------------------------------------------------------

@dataclass(frozen=True)
class InjectionWarning:
    """A single injection-detection finding."""

    category: str
    description: str
    severity: str  # "LOW", "MEDIUM", "HIGH"
    span: tuple[int, int]  # (start, end) character offsets


# ------------------------------------------------------------------
# Invisible Unicode characters
# ------------------------------------------------------------------

_INVISIBLE_CHARS: set[str] = {
    "\u200b",  # ZERO WIDTH SPACE
    "\u200c",  # ZERO WIDTH NON-JOINER
    "\u200d",  # ZERO WIDTH JOINER
    "\u2060",  # WORD JOINER
    "\ufeff",  # ZERO WIDTH NO-BREAK SPACE / BOM
    "\u202a",  # LEFT-TO-RIGHT EMBEDDING
    "\u202b",  # RIGHT-TO-LEFT EMBEDDING
    "\u202c",  # POP DIRECTIONAL FORMATTING
    "\u202d",  # LEFT-TO-RIGHT OVERRIDE
    "\u202e",  # RIGHT-TO-LEFT OVERRIDE
}

_INVISIBLE_RE = re.compile(
    "[" + "".join(re.escape(c) for c in sorted(_INVISIBLE_CHARS)) + "]"
)

# ------------------------------------------------------------------
# Pattern tables
# ------------------------------------------------------------------

# (compiled_regex, category, description, severity)
_OVERRIDE_PATTERNS: list[tuple[re.Pattern[str], str, str, str]] = [
    (
        re.compile(r"ignore\s+previous\s+instructions", re.IGNORECASE),
        "override",
        "System prompt override: 'ignore previous instructions'",
        "HIGH",
    ),
    (
        re.compile(r"you\s+are\s+now", re.IGNORECASE),
        "override",
        "Identity reassignment: 'you are now'",
        "HIGH",
    ),
    (
        re.compile(r"new\s+instructions\s*:", re.IGNORECASE),
        "override",
        "Injected instructions block: 'new instructions:'",
        "HIGH",
    ),
    (
        re.compile(r"(?:^|\s)system\s*:", re.IGNORECASE | re.MULTILINE),
        "override",
        "Fake system role prefix: 'system:'",
        "MEDIUM",
    ),
    (
        re.compile(r"(?:^|\s)ADMIN\s*:", re.MULTILINE),
        "override",
        "Fake admin role prefix: 'ADMIN:'",
        "MEDIUM",
    ),
    (
        re.compile(r"\[SYSTEM\]", re.IGNORECASE),
        "override",
        "Fake system tag: '[SYSTEM]'",
        "MEDIUM",
    ),
]

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

_EXFIL_PATTERNS: list[tuple[re.Pattern[str], str, str, str]] = [
    (
        re.compile(
            r"https?://[^\s]+[?&](?:api_?key|token|secret|password)=", re.IGNORECASE,
        ),
        "exfiltration",
        "URL with API key/token query parameter",
        "HIGH",
    ),
    (
        re.compile(r"curl\s+[^\n]*-H\s+['\"]?Authorization", re.IGNORECASE),
        "exfiltration",
        "curl command with Authorization header",
        "HIGH",
    ),
]

_BASE64_RE = re.compile(r"[A-Za-z0-9+/]{32,}={0,2}")

_BASE64_SUSPICIOUS_PHRASES = [
    "ignore previous",
    "you are now",
    "system:",
    "new instructions",
    "ADMIN:",
    "/bin/sh",
    "exec(",
    "eval(",
]


# ------------------------------------------------------------------
# Detector
# ------------------------------------------------------------------

class InjectionDetector:
    """Scan text for prompt-injection attempts."""

    def scan(self, text: str) -> list[InjectionWarning]:
        """Return all detected injection warnings in *text*."""
        warnings: list[InjectionWarning] = []

        # 1. System-prompt override patterns
        for pat, cat, desc, sev in _OVERRIDE_PATTERNS:
            for m in pat.finditer(text):
                warnings.append(InjectionWarning(cat, desc, sev, m.span()))

        # 2. Invisible Unicode
        for m in _INVISIBLE_RE.finditer(text):
            char = m.group()
            warnings.append(
                InjectionWarning(
                    "unicode",
                    f"Invisible Unicode character U+{ord(char):04X}",
                    "MEDIUM",
                    m.span(),
                )
            )

        # 3. HTML comment injection
        for m in _HTML_COMMENT_RE.finditer(text):
            warnings.append(
                InjectionWarning(
                    "html_comment",
                    "HTML comment injection",
                    "MEDIUM",
                    m.span(),
                )
            )

        # 4. Credential exfiltration
        for pat, cat, desc, sev in _EXFIL_PATTERNS:
            for m in pat.finditer(text):
                warnings.append(InjectionWarning(cat, desc, sev, m.span()))

        # 5. Base64-encoded suspicious payloads
        for m in _BASE64_RE.finditer(text):
            try:
                decoded = base64.b64decode(m.group(), validate=True).decode(
                    "utf-8", errors="ignore"
                )
            except Exception:
                continue
            for phrase in _BASE64_SUSPICIOUS_PHRASES:
                if phrase.lower() in decoded.lower():
                    warnings.append(
                        InjectionWarning(
                            "base64",
                            f"Base64 payload decodes to suspicious content containing '{phrase}'",
                            "HIGH",
                            m.span(),
                        )
                    )
                    break  # one warning per base64 blob is enough

        return warnings

    def is_safe(self, text: str) -> bool:
        """Return ``True`` when *text* contains no HIGH-severity warnings."""
        return all(w.severity != "HIGH" for w in self.scan(text))

    def scan_file(self, path: Path) -> list[InjectionWarning]:
        """Read *path* and scan its contents."""
        content = path.read_text(encoding="utf-8")
        return self.scan(content)

    @staticmethod
    def sanitize(text: str) -> str:
        """Remove invisible Unicode characters from *text*."""
        return _INVISIBLE_RE.sub("", text)
