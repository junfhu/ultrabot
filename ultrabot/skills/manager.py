"""Skill manager -- discovers, loads, and manages agent skills from disk."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from ultrabot.tools.registry import ToolRegistry


@dataclass
class Skill:
    """A self-contained skill consisting of instructions and optional tools.

    A skill directory on disk has the following layout::

        skills/
          my_skill/
            SKILL.md          # Markdown instructions injected into the prompt
            tools/            # Optional -- Python modules that define Tool objects
              my_tool.py

    Attributes
    ----------
    name:
        Identifier derived from the directory name.
    description:
        Short human-readable summary (first line of ``SKILL.md``).
    instructions:
        Full markdown content of ``SKILL.md``.
    tools:
        List of :class:`Tool` objects discovered in the skill's ``tools/`` dir.
    """

    name: str
    description: str
    instructions: str
    tools: list[Any] = field(default_factory=list)


class SkillManager:
    """Discovers and manages skills stored as directories on disk.

    Parameters
    ----------
    skills_dir:
        Root directory containing skill sub-directories.
    tool_registry:
        The :class:`ToolRegistry` where skill-provided tools are registered.
    """

    def __init__(self, skills_dir: Path, tool_registry: "ToolRegistry") -> None:
        self._skills_dir = skills_dir
        self._tool_registry = tool_registry
        self._skills: dict[str, Skill] = {}

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_skill(self, path: Path) -> Skill:
        """Load a single skill from the directory at *path*.

        The directory must contain a ``SKILL.md`` file.  An optional ``tools/``
        sub-directory may contain Python modules that expose ``Tool`` objects.
        """
        skill_md = path / "SKILL.md"
        if not skill_md.exists():
            raise FileNotFoundError(f"SKILL.md not found in {path}")

        instructions = skill_md.read_text(encoding="utf-8")
        # First non-empty line serves as the description.
        description = ""
        for line in instructions.splitlines():
            stripped = line.strip().lstrip("# ")
            if stripped:
                description = stripped
                break

        tools = self._load_tools(path / "tools")

        skill = Skill(
            name=path.name,
            description=description,
            instructions=instructions,
            tools=tools,
        )

        # Register tools with the central registry.
        for tool in tools:
            self._tool_registry.register(tool)

        self._skills[skill.name] = skill
        logger.info(
            "Loaded skill '{}' ({} tool(s))", skill.name, len(tools)
        )
        return skill

    def load_all(self) -> None:
        """Scan *skills_dir* and load every valid skill directory."""
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for child in sorted(self._skills_dir.iterdir()):
            if child.is_dir() and (child / "SKILL.md").exists():
                try:
                    self.load_skill(child)
                    count += 1
                except Exception:
                    logger.exception("Failed to load skill from {}", child)
        logger.info("Loaded {} skill(s) from {}", count, self._skills_dir)

    def _load_tools(self, tools_dir: Path) -> list[Any]:
        """Import tool modules from *tools_dir* and collect Tool objects.

        Each ``.py`` file in *tools_dir* is expected to define one or more
        objects whose class name is ``Tool`` (duck-typed).  We import the
        module dynamically and collect those objects.
        """
        if not tools_dir.is_dir():
            return []

        import importlib.util

        tools: list[Any] = []
        for py_file in sorted(tools_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"ultrabot.skills._dyn.{py_file.stem}", py_file
                )
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)  # type: ignore[union-attr]

                # Collect anything that looks like a Tool (has 'name' and 'execute').
                for attr_name in dir(module):
                    obj = getattr(module, attr_name)
                    if (
                        hasattr(obj, "name")
                        and hasattr(obj, "execute")
                        and not isinstance(obj, type)
                    ):
                        tools.append(obj)
            except Exception:
                logger.exception("Error loading tool from {}", py_file)

        return tools

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def get_skill(self, name: str) -> Skill | None:
        """Return the skill with the given *name*, or ``None``."""
        return self._skills.get(name)

    def list_skills(self) -> list[Skill]:
        """Return all loaded skills."""
        return list(self._skills.values())

    # ------------------------------------------------------------------
    # Hot-reload
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """Clear all loaded skills and re-scan the skills directory.

        This enables hot-reloading of skills without restarting the process.
        """
        logger.info("Reloading skills from {}", self._skills_dir)
        self._skills.clear()
        self.load_all()
