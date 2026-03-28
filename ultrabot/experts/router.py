"""Expert router -- selects the right expert for each inbound message.

Supports three routing modes:

1. **Command**: User explicitly requests an expert via ``@slug`` or
   ``/expert slug`` syntax.
2. **Sticky**: Once an expert is chosen for a session it stays active until
   the user switches (``/expert off`` or ``@default``).
3. **Auto**: An LLM call picks the best expert from the loaded catalog.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from ultrabot.experts.parser import ExpertPersona
    from ultrabot.experts.registry import ExpertRegistry


# ---------------------------------------------------------------------------
# Routing result
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RouteResult:
    """The outcome of routing a user message to an expert.

    Attributes
    ----------
    persona:
        The selected :class:`ExpertPersona`, or ``None`` to use the default
        ultrabot agent.
    cleaned_message:
        The user message with the routing command stripped out (if any).
    source:
        How the expert was selected: ``"command"``, ``"sticky"``,
        ``"auto"``, or ``"default"``.
    """

    persona: ExpertPersona | None
    cleaned_message: str
    source: str = "default"


# ---------------------------------------------------------------------------
# Command patterns
# ---------------------------------------------------------------------------

# @slug ...  or  /expert slug ...
_AT_PATTERN = re.compile(
    r"^@([\w-]+)\s*", re.UNICODE
)
_SLASH_PATTERN = re.compile(
    r"^/expert\s+([\w-]+)\s*", re.UNICODE | re.IGNORECASE
)
# /expert off  or  @default
_OFF_PATTERNS = re.compile(
    r"^(?:/expert\s+off|@default)\b\s*", re.UNICODE | re.IGNORECASE
)
# /experts  (list)
_LIST_PATTERN = re.compile(
    r"^/experts(?:\s+(.+))?\s*$", re.UNICODE | re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class ExpertRouter:
    """Routes inbound messages to expert personas.

    Parameters
    ----------
    registry:
        The :class:`ExpertRegistry` containing loaded personas.
    auto_route:
        Whether to use LLM-based auto-routing when no explicit command
        is given.  Requires a provider manager.
    provider_manager:
        An optional :class:`ProviderManager` used for auto-routing.
    """

    def __init__(
        self,
        registry: "ExpertRegistry",
        auto_route: bool = False,
        provider_manager: Any | None = None,
    ) -> None:
        self._registry = registry
        self._auto_route = auto_route
        self._provider = provider_manager
        # Session-slug sticky map: session_key -> expert slug.
        self._sticky: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def route(
        self,
        message: str,
        session_key: str,
    ) -> RouteResult:
        """Determine which expert should handle *message*.

        Routing precedence:
        1. Explicit ``/expert off`` or ``@default`` -> clear sticky, use default.
        2. ``/experts`` or ``/experts query`` -> return expert list (special).
        3. ``@slug`` or ``/expert slug`` -> set sticky, route to that expert.
        4. Sticky session -> reuse previously selected expert.
        5. Auto-route via LLM (if enabled).
        6. Default ultrabot agent.
        """
        # 1. Deactivation command.
        m = _OFF_PATTERNS.match(message)
        if m:
            self._sticky.pop(session_key, None)
            cleaned = message[m.end():].strip() or "OK, switched back to default mode."
            return RouteResult(persona=None, cleaned_message=cleaned, source="command")

        # 2. List command.
        m = _LIST_PATTERN.match(message)
        if m:
            query = (m.group(1) or "").strip()
            listing = self._build_listing(query)
            return RouteResult(persona=None, cleaned_message=listing, source="command")

        # 3. Explicit expert command.
        slug, cleaned = self._extract_command(message)
        if slug:
            persona = self._resolve_slug(slug)
            if persona:
                self._sticky[session_key] = persona.slug
                logger.info(
                    "Routed session {!r} to expert {!r} (command)",
                    session_key, persona.slug,
                )
                return RouteResult(
                    persona=persona,
                    cleaned_message=cleaned,
                    source="command",
                )
            # Unknown slug -- fall through with a hint.
            logger.warning("Unknown expert slug: {!r}", slug)

        # 4. Sticky session.
        sticky_slug = self._sticky.get(session_key)
        if sticky_slug:
            persona = self._registry.get(sticky_slug)
            if persona:
                return RouteResult(
                    persona=persona,
                    cleaned_message=message,
                    source="sticky",
                )
            # Stale sticky entry -- clean up.
            del self._sticky[sticky_slug]

        # 5. Auto-route (LLM-based).
        if self._auto_route and self._provider and len(self._registry) > 0:
            persona = await self._auto_select(message)
            if persona:
                self._sticky[session_key] = persona.slug
                logger.info(
                    "Auto-routed session {!r} to expert {!r}",
                    session_key, persona.slug,
                )
                return RouteResult(
                    persona=persona,
                    cleaned_message=message,
                    source="auto",
                )

        # 6. Default.
        return RouteResult(persona=None, cleaned_message=message, source="default")

    def clear_sticky(self, session_key: str) -> None:
        """Explicitly clear the sticky expert for a session."""
        self._sticky.pop(session_key, None)

    def get_sticky(self, session_key: str) -> str | None:
        """Return the sticky expert slug for a session, if any."""
        return self._sticky.get(session_key)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _extract_command(self, message: str) -> tuple[str | None, str]:
        """Try to extract an explicit expert command from the message.

        Returns ``(slug, cleaned_message)`` or ``(None, original_message)``.
        """
        m = _AT_PATTERN.match(message)
        if m:
            return m.group(1), message[m.end():].strip() or message

        m = _SLASH_PATTERN.match(message)
        if m:
            return m.group(1), message[m.end():].strip() or message

        return None, message

    def _resolve_slug(self, slug: str) -> "ExpertPersona | None":
        """Look up a slug in the registry, trying exact then name match."""
        persona = self._registry.get(slug)
        if persona:
            return persona
        # Try name-based lookup.
        return self._registry.get_by_name(slug)

    def _build_listing(self, query: str) -> str:
        """Build a formatted expert listing, optionally filtered by query."""
        if query:
            results = self._registry.search(query, limit=20)
            if not results:
                return f"No experts found for '{query}'."
            lines = [f"**Experts matching '{query}':**\n"]
            for p in results:
                lines.append(f"- `@{p.slug}` -- {p.name}: {p.description[:60]}")
            return "\n".join(lines)

        departments = self._registry.departments()
        if not departments:
            return "No experts loaded. Run `ultrabot experts sync` to download."

        lines = [f"**{len(self._registry)} experts across {len(departments)} departments:**\n"]
        for dept in departments:
            experts = self._registry.list_department(dept)
            names = ", ".join(f"`{p.slug}`" for p in experts[:5])
            suffix = f" ... +{len(experts) - 5} more" if len(experts) > 5 else ""
            lines.append(f"- **{dept}** ({len(experts)}): {names}{suffix}")
        lines.append("\nUse `@slug` to activate an expert, `/experts query` to search.")
        return "\n".join(lines)

    async def _auto_select(self, message: str) -> "ExpertPersona | None":
        """Use an LLM call to pick the best expert for the message."""
        catalog = self._registry.build_catalog()

        system = (
            "You are an expert routing assistant. Given the user's message, "
            "pick the single best expert from the catalog below. "
            "Return ONLY the expert slug (e.g. 'engineering-frontend-developer') "
            "or 'none' if no expert is a good match.\n\n"
            f"EXPERT CATALOG:\n{catalog}"
        )

        try:
            response = await self._provider.chat_with_failover(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": message},
                ],
                max_tokens=60,
                temperature=0.0,
            )
            slug = (response.content or "").strip().lower().strip("`'\"")
            if slug and slug != "none":
                return self._registry.get(slug)
        except Exception:
            logger.exception("Auto-route LLM call failed")

        return None
