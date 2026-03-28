"""Expert registry -- loads, indexes, and searches expert personas."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterable, Sequence

from loguru import logger

from ultrabot.experts.parser import ExpertPersona, parse_persona_file


class ExpertRegistry:
    """In-memory registry of :class:`ExpertPersona` objects.

    Personas are loaded from a directory of ``.md`` files (one per expert).
    The registry supports lookup by slug, department, and free-text search.

    Parameters
    ----------
    experts_dir:
        Root directory containing ``.md`` persona files (may include
        sub-directories per department).
    """

    def __init__(self, experts_dir: Path | None = None) -> None:
        self._experts: dict[str, ExpertPersona] = {}
        self._by_department: dict[str, list[str]] = defaultdict(list)
        self._experts_dir = experts_dir

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_directory(self, directory: Path | None = None) -> int:
        """Scan *directory* for ``.md`` persona files and load them.

        Supports both flat layouts (all ``.md`` in one dir) and nested
        layouts (department sub-directories).

        Returns the number of personas loaded.
        """
        directory = directory or self._experts_dir
        if directory is None:
            raise ValueError("No experts directory specified.")
        directory = Path(directory)
        if not directory.is_dir():
            logger.warning("Experts directory does not exist: {}", directory)
            return 0

        count = 0
        for md_file in sorted(directory.rglob("*.md")):
            if md_file.name.startswith("_") or md_file.name.upper() == "README.MD":
                continue
            try:
                persona = parse_persona_file(md_file)
                self.register(persona)
                count += 1
            except Exception:
                logger.exception("Failed to parse persona from {}", md_file)

        logger.info("Loaded {} expert persona(s) from {}", count, directory)
        return count

    def register(self, persona: ExpertPersona) -> None:
        """Add or replace a persona in the registry."""
        if persona.slug in self._experts:
            # Remove old department index entry.
            old = self._experts[persona.slug]
            if old.department and old.slug in self._by_department.get(old.department, []):
                self._by_department[old.department].remove(old.slug)

        self._experts[persona.slug] = persona
        if persona.department:
            self._by_department[persona.department].append(persona.slug)

    def unregister(self, slug: str) -> None:
        """Remove a persona by slug. No-op if not found."""
        persona = self._experts.pop(slug, None)
        if persona and persona.department:
            dept_list = self._by_department.get(persona.department, [])
            if slug in dept_list:
                dept_list.remove(slug)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, slug: str) -> ExpertPersona | None:
        """Return the persona with the given slug, or ``None``."""
        return self._experts.get(slug)

    def get_by_name(self, name: str) -> ExpertPersona | None:
        """Find a persona by its human-readable name (case-insensitive)."""
        name_lower = name.lower()
        for persona in self._experts.values():
            if persona.name.lower() == name_lower:
                return persona
        return None

    def list_all(self) -> list[ExpertPersona]:
        """Return all personas sorted by department then slug."""
        return sorted(
            self._experts.values(),
            key=lambda p: (p.department, p.slug),
        )

    def list_department(self, department: str) -> list[ExpertPersona]:
        """Return all personas in a department."""
        slugs = self._by_department.get(department, [])
        return [self._experts[s] for s in sorted(slugs) if s in self._experts]

    def departments(self) -> list[str]:
        """Return all department names that have at least one expert."""
        return sorted(d for d, slugs in self._by_department.items() if slugs)

    def search(self, query: str, limit: int = 10) -> list[ExpertPersona]:
        """Full-text search over names, descriptions, tags, and departments.

        Returns up to *limit* results sorted by relevance score (descending).
        """
        query_lower = query.lower()
        query_tokens = set(query_lower.split())

        scored: list[tuple[float, ExpertPersona]] = []
        for persona in self._experts.values():
            score = self._score_match(persona, query_lower, query_tokens)
            if score > 0:
                scored.append((score, persona))

        scored.sort(key=lambda x: -x[0])
        return [p for _, p in scored[:limit]]

    @staticmethod
    def _score_match(
        persona: ExpertPersona,
        query_lower: str,
        query_tokens: set[str],
    ) -> float:
        """Compute a relevance score for a persona against a query."""
        score = 0.0

        # Exact slug match.
        if query_lower == persona.slug:
            score += 100.0

        # Exact name match.
        if query_lower == persona.name.lower():
            score += 100.0

        # Slug contains query.
        if query_lower in persona.slug:
            score += 30.0

        # Name contains query.
        if query_lower in persona.name.lower():
            score += 30.0

        # Description contains query.
        if query_lower in persona.description.lower():
            score += 15.0

        # Department match.
        if query_lower == persona.department:
            score += 20.0

        # Tag matches.
        tag_set = set(persona.tags)
        for token in query_tokens:
            if token in tag_set:
                score += 5.0

        # Partial tag matches.
        for tag in persona.tags:
            for token in query_tokens:
                if token in tag or tag in token:
                    score += 2.0

        return score

    # ------------------------------------------------------------------
    # Catalog generation (for LLM routing)
    # ------------------------------------------------------------------

    def build_catalog(
        self,
        personas: Sequence[ExpertPersona] | None = None,
    ) -> str:
        """Build a concise catalog string listing experts for LLM routing.

        Parameters
        ----------
        personas:
            Subset of personas to include; defaults to all.

        Returns
        -------
        str
            A formatted catalog like::

                ## engineering
                - engineering-frontend-developer: 前端开发者 -- React/Vue 前端工程专家
                - engineering-security-engineer: 安全工程师 -- 威胁建模、代码审计专家
                ...
        """
        items = personas or self.list_all()
        if not items:
            return "(no experts loaded)"

        by_dept: dict[str, list[ExpertPersona]] = defaultdict(list)
        for p in items:
            by_dept[p.department or "other"].append(p)

        lines: list[str] = []
        for dept in sorted(by_dept):
            lines.append(f"## {dept}")
            for p in sorted(by_dept[dept], key=lambda x: x.slug):
                desc = p.description[:80] if p.description else p.name
                lines.append(f"- {p.slug}: {p.name} -- {desc}")
            lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._experts)

    def __contains__(self, slug: str) -> bool:
        return slug in self._experts

    def __repr__(self) -> str:
        return f"<ExpertRegistry experts={len(self._experts)}>"
