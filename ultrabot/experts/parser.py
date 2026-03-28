"""Parse agency-agents-zh markdown persona files into structured ExpertPersona objects."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ExpertPersona:
    """Structured representation of an expert persona parsed from markdown.

    Attributes
    ----------
    slug:
        URL-safe identifier derived from the filename
        (e.g. ``"engineering-frontend-developer"``).
    name:
        Human-readable name from YAML frontmatter (e.g. ``"前端开发者"``).
    description:
        One-line description from YAML frontmatter.
    department:
        Department inferred from the directory or slug prefix
        (e.g. ``"engineering"``).
    color:
        Badge / UI colour from YAML frontmatter.
    identity:
        The persona's identity and personality paragraph.
    core_mission:
        Detailed description of what the expert does.
    key_rules:
        Constraints and principles the expert follows.
    workflow:
        Step-by-step work process.
    deliverables:
        Example outputs / technical deliverables.
    communication_style:
        How the expert communicates.
    success_metrics:
        How to measure the expert's effectiveness.
    raw_body:
        Full markdown body with frontmatter stripped (used as system prompt).
    tags:
        Searchable keyword tags extracted from all sections.
    source_path:
        Filesystem path the persona was loaded from (``None`` if synthetic).
    """

    slug: str
    name: str
    description: str = ""
    department: str = ""
    color: str = ""
    identity: str = ""
    core_mission: str = ""
    key_rules: str = ""
    workflow: str = ""
    deliverables: str = ""
    communication_style: str = ""
    success_metrics: str = ""
    raw_body: str = ""
    tags: list[str] = field(default_factory=list)
    source_path: Path | None = None

    @property
    def system_prompt(self) -> str:
        """Return the full markdown body suitable for use as a system prompt."""
        return self.raw_body


# ---------------------------------------------------------------------------
# YAML Frontmatter helpers
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Extract YAML frontmatter and return ``(meta, body)``.

    Uses a simple line-based parser rather than a full YAML library to
    keep dependencies minimal.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text

    raw_yaml = m.group(1)
    body = text[m.end():]

    meta: dict[str, str] = {}
    for line in raw_yaml.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        colon = line.find(":")
        if colon < 1:
            continue
        key = line[:colon].strip()
        val = line[colon + 1:].strip().strip('"').strip("'")
        meta[key] = val

    return meta, body


# ---------------------------------------------------------------------------
# Markdown section extraction
# ---------------------------------------------------------------------------

# Maps Chinese and English section headers to ExpertPersona field names.
_SECTION_MAP: dict[str, str] = {
    # Chinese headers (agency-agents-zh)
    "你的身份与记忆": "identity",
    "身份与记忆": "identity",
    "角色": "identity",
    "核心使命": "core_mission",
    "关键规则": "key_rules",
    "技术交付物": "deliverables",
    "交付物": "deliverables",
    "工作流程": "workflow",
    "沟通风格": "communication_style",
    "成功指标": "success_metrics",
    "学习与记忆": "identity",  # appended to identity
    # English headers (upstream)
    "your identity": "identity",
    "identity & memory": "identity",
    "core mission": "core_mission",
    "key rules": "key_rules",
    "technical deliverables": "deliverables",
    "deliverables": "deliverables",
    "workflow": "workflow",
    "communication style": "communication_style",
    "success metrics": "success_metrics",
    "learning & memory": "identity",
}


def _extract_sections(body: str) -> dict[str, str]:
    """Split the markdown body on ``## `` headers and map to field names."""
    sections: dict[str, list[str]] = {}
    current_field: str | None = None

    for line in body.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            # Normalise heading to a field name.
            normalised = heading.lower()
            field_name = _SECTION_MAP.get(normalised)
            if field_name is None:
                # Try substring matching for partial headers.
                for key, fname in _SECTION_MAP.items():
                    if key in normalised:
                        field_name = fname
                        break
            current_field = field_name
            if current_field:
                sections.setdefault(current_field, [])
        elif current_field and current_field in sections:
            sections[current_field].append(line)

    return {k: "\n".join(v).strip() for k, v in sections.items()}


# ---------------------------------------------------------------------------
# Tag extraction
# ---------------------------------------------------------------------------

# Common stop-words excluded from tags.
_STOP_WORDS = frozenset(
    "的 了 是 在 和 有 不 这 要 你 我 把 被 也 一 都 会 让 从 到 用 于 与 为 之".split()
)


def _extract_tags(persona: ExpertPersona) -> list[str]:
    """Build a list of searchable keyword tags from the persona."""
    tag_source = " ".join(
        filter(None, [
            persona.name,
            persona.description,
            persona.department,
        ])
    )
    # Extract English words and CJK character bigrams.
    tokens: set[str] = set()

    # English / alphanumeric tokens.
    for word in re.findall(r"[A-Za-z0-9][\w\-]{1,}", tag_source):
        tokens.add(word.lower())

    # Single Chinese characters that appear multiple times are less useful;
    # instead, extract 2-char Chinese sub-strings as tags.
    cjk_chars = re.findall(r"[\u4e00-\u9fff]+", tag_source)
    for chunk in cjk_chars:
        for i in range(len(chunk)):
            ch = chunk[i]
            if ch not in _STOP_WORDS:
                tokens.add(ch)
        for i in range(len(chunk) - 1):
            bigram = chunk[i:i + 2]
            tokens.add(bigram)

    return sorted(tokens)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_DEPARTMENT_PREFIXES = {
    "engineering", "design", "marketing", "product", "finance",
    "game-development", "hr", "legal", "paid-media", "sales",
    "project-management", "testing", "support", "academic",
    "supply-chain", "spatial-computing", "specialized", "integrations",
}


def _infer_department(slug: str) -> str:
    """Infer department from the slug prefix."""
    for prefix in _DEPARTMENT_PREFIXES:
        tag = prefix.replace("-", "")
        slug_clean = slug.replace("-", "")
        if slug_clean.startswith(tag):
            return prefix
    # Fallback: first segment before the first hyphen.
    return slug.split("-")[0] if "-" in slug else ""


def parse_persona_file(path: Path) -> ExpertPersona:
    """Parse a single agency-agents-zh markdown file into an :class:`ExpertPersona`.

    Parameters
    ----------
    path:
        Path to the ``.md`` file.

    Returns
    -------
    ExpertPersona
        A fully populated persona object.
    """
    text = path.read_text(encoding="utf-8")
    slug = path.stem  # e.g. "engineering-frontend-developer"

    meta, body = _parse_frontmatter(text)
    sections = _extract_sections(body)

    # Infer department from parent directory name or slug.
    department = path.parent.name if path.parent.name in _DEPARTMENT_PREFIXES else ""
    if not department:
        department = _infer_department(slug)

    persona = ExpertPersona(
        slug=slug,
        name=meta.get("name", slug),
        description=meta.get("description", ""),
        department=department,
        color=meta.get("color", ""),
        identity=sections.get("identity", ""),
        core_mission=sections.get("core_mission", ""),
        key_rules=sections.get("key_rules", ""),
        workflow=sections.get("workflow", ""),
        deliverables=sections.get("deliverables", ""),
        communication_style=sections.get("communication_style", ""),
        success_metrics=sections.get("success_metrics", ""),
        raw_body=body.strip(),
        source_path=path,
    )
    persona.tags = _extract_tags(persona)
    return persona


def parse_persona_text(text: str, slug: str = "custom") -> ExpertPersona:
    """Parse raw markdown text into an :class:`ExpertPersona` without a file.

    Useful for testing or dynamically created personas.
    """
    meta, body = _parse_frontmatter(text)
    sections = _extract_sections(body)
    department = _infer_department(slug)

    persona = ExpertPersona(
        slug=slug,
        name=meta.get("name", slug),
        description=meta.get("description", ""),
        department=department,
        color=meta.get("color", ""),
        identity=sections.get("identity", ""),
        core_mission=sections.get("core_mission", ""),
        key_rules=sections.get("key_rules", ""),
        workflow=sections.get("workflow", ""),
        deliverables=sections.get("deliverables", ""),
        communication_style=sections.get("communication_style", ""),
        success_metrics=sections.get("success_metrics", ""),
        raw_body=body.strip(),
    )
    persona.tags = _extract_tags(persona)
    return persona
