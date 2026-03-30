# Session 18: Expert Router + Dynamic Switching

**Goal:** Build an intelligent message router that directs user messages to the right expert persona, with explicit commands, sticky sessions, and LLM-based auto-routing.

**What you'll learn:**
- `RouteResult` dataclass for routing outcomes
- Command parsing: `@slug`, `/expert slug`, `/expert off`, `/experts`
- Sticky session tracking per chat session
- LLM-based auto-routing using the expert catalog
- GitHub sync for downloading persona files

**New files:**
- `ultrabot/experts/router.py` — message-to-expert routing engine
- `ultrabot/experts/sync.py` — download personas from GitHub

### Step 1: The RouteResult Dataclass

Every routing decision produces a `RouteResult` that tells the agent which
persona to use and how the decision was made.

```python
# ultrabot/experts/router.py
"""Expert router -- selects the right expert for each inbound message."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from ultrabot.experts.parser import ExpertPersona
    from ultrabot.experts.registry import ExpertRegistry


@dataclass(slots=True)
class RouteResult:
    """The outcome of routing a user message to an expert.

    Attributes:
        persona: The selected ExpertPersona, or None for default agent.
        cleaned_message: User message with routing command stripped.
        source: How selected: "command", "sticky", "auto", or "default".
    """
    persona: ExpertPersona | None
    cleaned_message: str
    source: str = "default"
```

### Step 2: Command Pattern Matching

The router recognises four command patterns. Regex patterns handle both
`@slug` and `/expert slug` syntax.

```python
# @slug ...  or  /expert slug ...
_AT_PATTERN = re.compile(r"^@([\w-]+)\s*", re.UNICODE)
_SLASH_PATTERN = re.compile(
    r"^/expert\s+([\w-]+)\s*", re.UNICODE | re.IGNORECASE
)
# /expert off  or  @default
_OFF_PATTERNS = re.compile(
    r"^(?:/expert\s+off|@default)\b\s*", re.UNICODE | re.IGNORECASE
)
# /experts  (list all) or  /experts query  (search)
_LIST_PATTERN = re.compile(
    r"^/experts(?:\s+(.+))?\s*$", re.UNICODE | re.IGNORECASE
)
```

### Step 3: The ExpertRouter

The router implements a clear precedence chain:
1. Deactivation (`/expert off`)
2. List command (`/experts`)
3. Explicit command (`@slug` or `/expert slug`)
4. Sticky session (previously selected expert persists)
5. LLM auto-route (if enabled)
6. Default agent

```python
class ExpertRouter:
    """Routes inbound messages to expert personas.

    Parameters:
        registry: The ExpertRegistry containing loaded personas.
        auto_route: Whether to use LLM-based auto-routing.
        provider_manager: Optional ProviderManager for auto-routing.
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
        # Session-slug sticky map: session_key -> expert slug
        self._sticky: dict[str, str] = {}

    async def route(
        self,
        message: str,
        session_key: str,
    ) -> RouteResult:
        """Determine which expert should handle *message*."""
        # 1. Deactivation command
        m = _OFF_PATTERNS.match(message)
        if m:
            self._sticky.pop(session_key, None)
            cleaned = message[m.end():].strip() or "OK, switched back to default mode."
            return RouteResult(persona=None, cleaned_message=cleaned, source="command")

        # 2. List command
        m = _LIST_PATTERN.match(message)
        if m:
            query = (m.group(1) or "").strip()
            listing = self._build_listing(query)
            return RouteResult(persona=None, cleaned_message=listing, source="command")

        # 3. Explicit expert command
        slug, cleaned = self._extract_command(message)
        if slug:
            persona = self._resolve_slug(slug)
            if persona:
                self._sticky[session_key] = persona.slug
                logger.info("Routed session {!r} to expert {!r} (command)",
                            session_key, persona.slug)
                return RouteResult(persona=persona, cleaned_message=cleaned,
                                   source="command")
            logger.warning("Unknown expert slug: {!r}", slug)

        # 4. Sticky session
        sticky_slug = self._sticky.get(session_key)
        if sticky_slug:
            persona = self._registry.get(sticky_slug)
            if persona:
                return RouteResult(persona=persona, cleaned_message=message,
                                   source="sticky")
            del self._sticky[sticky_slug]  # Stale — clean up

        # 5. Auto-route (LLM-based)
        if self._auto_route and self._provider and len(self._registry) > 0:
            persona = await self._auto_select(message)
            if persona:
                self._sticky[session_key] = persona.slug
                logger.info("Auto-routed session {!r} to expert {!r}",
                            session_key, persona.slug)
                return RouteResult(persona=persona, cleaned_message=message,
                                   source="auto")

        # 6. Default
        return RouteResult(persona=None, cleaned_message=message, source="default")

    def clear_sticky(self, session_key: str) -> None:
        self._sticky.pop(session_key, None)

    def get_sticky(self, session_key: str) -> str | None:
        return self._sticky.get(session_key)
```

### Step 4: Internal Routing Helpers

```python
    # -- Internals (still inside ExpertRouter) --

    def _extract_command(self, message: str) -> tuple[str | None, str]:
        """Try to extract an explicit expert command from the message."""
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
        return self._registry.get_by_name(slug)

    def _build_listing(self, query: str) -> str:
        """Build a formatted expert listing, optionally filtered."""
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
```

### Step 5: Sync Personas from GitHub

```python
# ultrabot/experts/sync.py
"""Sync expert personas from the agency-agents-zh GitHub repository."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from loguru import logger

REPO_OWNER = "jnMetaCode"
REPO_NAME = "agency-agents-zh"
BRANCH = "main"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{BRANCH}"
API_TREE = (
    f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
    f"/git/trees/{BRANCH}?recursive=1"
)

PERSONA_DIRS = frozenset({
    "academic", "design", "engineering", "finance", "game-development",
    "hr", "integrations", "legal", "marketing", "paid-media", "product",
    "project-management", "sales", "spatial-computing", "specialized",
    "supply-chain", "support", "testing",
})


def sync_personas(
    dest_dir: Path,
    *,
    departments: set[str] | None = None,
    force: bool = False,
    progress_callback: Any = None,
) -> int:
    """Download persona ``.md`` files from GitHub to *dest_dir*.

    Returns the number of files downloaded.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    # 1. Fetch the repository tree
    logger.info("Fetching repository tree from GitHub ...")
    try:
        tree = _fetch_tree()
    except Exception as exc:
        raise RuntimeError(f"Cannot reach GitHub API: {exc}") from exc

    # 2. Filter to persona .md files
    files = _filter_persona_files(tree, departments)
    total = len(files)
    logger.info("Found {} persona files to sync", total)

    if total == 0:
        return 0

    # 3. Download each file
    downloaded = 0
    for idx, file_path in enumerate(files, 1):
        filename = Path(file_path).name
        local_path = dest_dir / filename

        if local_path.exists() and not force:
            if progress_callback:
                progress_callback(idx, total, filename)
            continue

        try:
            content = _fetch_raw_file(file_path)
            local_path.write_text(content, encoding="utf-8")
            downloaded += 1
        except Exception:
            logger.exception("Failed to download {}", file_path)

        if progress_callback:
            progress_callback(idx, total, filename)

    logger.info("Synced {}/{} persona files to {}", downloaded, total, dest_dir)
    return downloaded


async def async_sync_personas(dest_dir: Path, **kwargs: Any) -> int:
    """Async wrapper around sync_personas (runs in executor)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: sync_personas(dest_dir, **kwargs))


def _fetch_tree() -> list[dict[str, Any]]:
    req = Request(API_TREE, headers={"Accept": "application/json"})
    with urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("tree", [])


def _filter_persona_files(tree: list[dict[str, Any]], departments: set[str] | None) -> list[str]:
    files: list[str] = []
    for item in tree:
        if item.get("type") != "blob":
            continue
        path = item.get("path", "")
        if not path.endswith(".md"):
            continue
        parts = path.split("/")
        if len(parts) != 2:
            continue
        dept, filename = parts
        if dept not in PERSONA_DIRS:
            continue
        if departments and dept not in departments:
            continue
        if filename.startswith("_") or filename.upper() == "README.MD":
            continue
        files.append(path)
    return sorted(files)


def _fetch_raw_file(path: str) -> str:
    url = f"{RAW_BASE}/{path}"
    with urlopen(Request(url), timeout=15) as resp:
        return resp.read().decode("utf-8")
```

### Tests

```python
# tests/test_experts_router.py
"""Tests for the expert router and sync modules."""

import pytest

from ultrabot.experts.parser import parse_persona_text
from ultrabot.experts.registry import ExpertRegistry
from ultrabot.experts.router import ExpertRouter, RouteResult


CODER_MD = """\
---
name: "Coder"
description: "Expert Python programmer"
---
## Your identity
You write Python code.
"""

WRITER_MD = """\
---
name: "Writer"
description: "Creative content writer"
---
## Your identity
You write compelling content.
"""


@pytest.fixture
def registry():
    reg = ExpertRegistry()
    reg.register(parse_persona_text(CODER_MD, slug="coder"))
    reg.register(parse_persona_text(WRITER_MD, slug="writer"))
    return reg


@pytest.fixture
def router(registry):
    return ExpertRouter(registry, auto_route=False)


class TestCommandRouting:
    @pytest.mark.asyncio
    async def test_at_command(self, router):
        result = await router.route("@coder Fix this bug", session_key="s1")
        assert result.source == "command"
        assert result.persona is not None
        assert result.persona.slug == "coder"
        assert result.cleaned_message == "Fix this bug"

    @pytest.mark.asyncio
    async def test_slash_command(self, router):
        result = await router.route("/expert writer Draft an email", session_key="s1")
        assert result.persona.slug == "writer"
        assert result.cleaned_message == "Draft an email"

    @pytest.mark.asyncio
    async def test_expert_off(self, router):
        # First activate an expert
        await router.route("@coder hello", session_key="s1")
        assert router.get_sticky("s1") == "coder"

        # Then deactivate
        result = await router.route("/expert off", session_key="s1")
        assert result.persona is None
        assert result.source == "command"
        assert router.get_sticky("s1") is None

    @pytest.mark.asyncio
    async def test_unknown_slug_falls_through(self, router):
        result = await router.route("@nonexistent hello", session_key="s1")
        assert result.source == "default"
        assert result.persona is None


class TestStickySession:
    @pytest.mark.asyncio
    async def test_sticky_persists(self, router):
        await router.route("@coder hello", session_key="s1")
        # Next message without command should stick to coder
        result = await router.route("What about this?", session_key="s1")
        assert result.source == "sticky"
        assert result.persona.slug == "coder"

    @pytest.mark.asyncio
    async def test_different_sessions_independent(self, router):
        await router.route("@coder hello", session_key="s1")
        result = await router.route("Hello", session_key="s2")
        assert result.source == "default"  # s2 has no sticky


class TestListCommand:
    @pytest.mark.asyncio
    async def test_list_all(self, router):
        result = await router.route("/experts", session_key="s1")
        assert result.source == "command"
        assert "2 experts" in result.cleaned_message

    @pytest.mark.asyncio
    async def test_list_search(self, router):
        result = await router.route("/experts Python", session_key="s1")
        assert "coder" in result.cleaned_message.lower()
```

### Checkpoint

```bash
python -c "
import asyncio
from ultrabot.experts.parser import parse_persona_text
from ultrabot.experts.registry import ExpertRegistry
from ultrabot.experts.router import ExpertRouter

reg = ExpertRegistry()
reg.register(parse_persona_text('---\nname: Coder\n---\n## Your identity\nPython expert.', slug='coder'))
reg.register(parse_persona_text('---\nname: Writer\n---\n## Your identity\nCreative writer.', slug='writer'))

router = ExpertRouter(reg)

async def demo():
    r = await router.route('@coder Fix the tests', 's1')
    print(f'1) source={r.source}, expert={r.persona.slug}, msg={r.cleaned_message!r}')

    r = await router.route('What about imports?', 's1')
    print(f'2) source={r.source}, expert={r.persona.slug} (sticky!)')

    r = await router.route('/expert off', 's1')
    print(f'3) source={r.source}, expert={r.persona} (back to default)')

    r = await router.route('/experts', 's1')
    print(f'4) Listing: {r.cleaned_message[:80]}...')

asyncio.run(demo())
"
```

Expected:
```
1) source=command, expert=coder, msg='Fix the tests'
2) source=sticky, expert=coder (sticky!)
3) source=command, expert=None (back to default)
4) Listing: **2 experts across 1 departments:**
...
```

### What we built

An expert router with three routing strategies: explicit commands (`@slug`,
`/expert slug`), sticky sessions that persist the active expert across
messages, and LLM-based auto-routing that picks the best expert from a
catalog. Plus a GitHub sync module that downloads the full persona corpus.

---
