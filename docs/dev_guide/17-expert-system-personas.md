# Session 17: Expert System — Personas

**Goal:** Build a persona-based expert system that parses markdown persona files into structured dataclasses and provides a searchable registry.

**What you'll learn:**
- The `ExpertPersona` dataclass with all structured fields
- YAML frontmatter + markdown section parsing without external YAML libs
- `ExpertRegistry` with department indexing and relevance-scored search
- Tag extraction from CJK + English text
- Loading personas from a directory tree

**New files:**
- `ultrabot/experts/__init__.py` — package exports and bundled personas path
- `ultrabot/experts/parser.py` — markdown persona parser with frontmatter extraction
- `ultrabot/experts/registry.py` — in-memory registry with search and catalog generation

### Step 1: The ExpertPersona Dataclass

Each expert persona is a rich structured object parsed from a markdown file. The
markdown files come from the [agency-agents-zh](https://github.com/jnMetaCode/agency-agents-zh)
repository — 187 domain specialists from frontend developers to legal advisors.

```python
# ultrabot/experts/parser.py
"""Parse agency-agents-zh markdown persona files into structured ExpertPersona objects."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ExpertPersona:
    """Structured representation of an expert persona parsed from markdown.

    Each persona maps to one .md file.  The ``raw_body`` (markdown with
    frontmatter stripped) doubles as the LLM system prompt, while the
    structured fields power search, routing, and UI display.
    """

    slug: str                       # URL-safe id from filename
    name: str                       # Human-readable name (e.g. "前端开发者")
    description: str = ""           # One-liner from YAML frontmatter
    department: str = ""            # Inferred from dir or slug prefix
    color: str = ""                 # Badge/UI colour from frontmatter
    identity: str = ""              # Persona's identity paragraph
    core_mission: str = ""          # What the expert does
    key_rules: str = ""             # Constraints and principles
    workflow: str = ""              # Step-by-step work process
    deliverables: str = ""          # Example outputs
    communication_style: str = ""   # How the expert communicates
    success_metrics: str = ""       # Effectiveness measures
    raw_body: str = ""              # Full markdown body (= system prompt)
    tags: list[str] = field(default_factory=list)  # Searchable keywords
    source_path: Path | None = None

    @property
    def system_prompt(self) -> str:
        """Return the full markdown body suitable for use as a system prompt."""
        return self.raw_body
```

Key design decisions:
- **`slots=True`** keeps memory low when loading hundreds of personas.
- **`raw_body` as system prompt** — the entire markdown body is the LLM instruction.
- **`tags`** are computed post-init for search indexing.

### Step 2: YAML Frontmatter Parser (No PyYAML Required)

We parse frontmatter with a simple regex + line scanner — no external YAML
library needed. This keeps the dependency footprint minimal.

```python
# Still in ultrabot/experts/parser.py

# Matches the --- delimited frontmatter block at the top of a file.
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Extract YAML frontmatter and return ``(meta, body)``.

    Uses a simple line-based parser rather than a full YAML library to
    keep dependencies minimal.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text             # No frontmatter — entire text is body

    raw_yaml = m.group(1)
    body = text[m.end():]           # Everything after the closing ---

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
```

### Step 3: Markdown Section Extraction

Persona files use `## ` headers to delimit sections. We map both Chinese and
English header names to dataclass field names.

```python
# Maps Chinese and English section headers to ExpertPersona field names.
_SECTION_MAP: dict[str, str] = {
    # Chinese headers (agency-agents-zh corpus)
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
    "学习与记忆": "identity",
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
```

### Step 4: Tag Extraction and Department Inference

Tags combine English tokens and CJK bigrams for effective multilingual search.

```python
# Common Chinese stop-words excluded from tags.
_STOP_WORDS = frozenset(
    "的 了 是 在 和 有 不 这 要 你 我 把 被 也 一 都 会 让 从 到 用 于 与 为 之".split()
)


def _extract_tags(persona: ExpertPersona) -> list[str]:
    """Build a list of searchable keyword tags from the persona."""
    tag_source = " ".join(
        filter(None, [persona.name, persona.description, persona.department])
    )
    tokens: set[str] = set()

    # English / alphanumeric tokens
    for word in re.findall(r"[A-Za-z0-9][\w\-]{1,}", tag_source):
        tokens.add(word.lower())

    # CJK character unigrams (minus stop words) + bigrams
    cjk_chars = re.findall(r"[\u4e00-\u9fff]+", tag_source)
    for chunk in cjk_chars:
        for i in range(len(chunk)):
            ch = chunk[i]
            if ch not in _STOP_WORDS:
                tokens.add(ch)
        for i in range(len(chunk) - 1):
            tokens.add(chunk[i:i + 2])

    return sorted(tokens)


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
    return slug.split("-")[0] if "-" in slug else ""
```

### Step 5: The Public Parsing API

Two entry points: file-based for production, text-based for tests.

```python
def parse_persona_file(path: Path) -> ExpertPersona:
    """Parse a single agency-agents-zh markdown file into an ExpertPersona."""
    text = path.read_text(encoding="utf-8")
    slug = path.stem  # e.g. "engineering-frontend-developer"

    meta, body = _parse_frontmatter(text)
    sections = _extract_sections(body)

    # Infer department from parent dir name or slug.
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
    """Parse raw markdown text into an ExpertPersona without a file.

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
```

### Step 6: The ExpertRegistry

The registry loads, indexes, and searches personas. It supports lookup by slug,
by name, by department, and free-text relevance search.

```python
# ultrabot/experts/registry.py
"""Expert registry -- loads, indexes, and searches expert personas."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterable, Sequence

from loguru import logger

from ultrabot.experts.parser import ExpertPersona, parse_persona_file


class ExpertRegistry:
    """In-memory registry of ExpertPersona objects.

    Personas are loaded from a directory of ``.md`` files (one per expert).
    The registry supports lookup by slug, department, and free-text search.
    """

    def __init__(self, experts_dir: Path | None = None) -> None:
        self._experts: dict[str, ExpertPersona] = {}
        self._by_department: dict[str, list[str]] = defaultdict(list)
        self._experts_dir = experts_dir

    # -- Loading ----------------------------------------------------------

    def load_directory(self, directory: Path | None = None) -> int:
        """Scan *directory* for ``.md`` persona files and load them.

        Supports both flat and nested (department sub-dirs) layouts.
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

    # -- Lookup -----------------------------------------------------------

    def get(self, slug: str) -> ExpertPersona | None:
        return self._experts.get(slug)

    def get_by_name(self, name: str) -> ExpertPersona | None:
        """Find a persona by human-readable name (case-insensitive)."""
        name_lower = name.lower()
        for persona in self._experts.values():
            if persona.name.lower() == name_lower:
                return persona
        return None

    def list_all(self) -> list[ExpertPersona]:
        """Return all personas sorted by department then slug."""
        return sorted(self._experts.values(), key=lambda p: (p.department, p.slug))

    def list_department(self, department: str) -> list[ExpertPersona]:
        slugs = self._by_department.get(department, [])
        return [self._experts[s] for s in sorted(slugs) if s in self._experts]

    def departments(self) -> list[str]:
        return sorted(d for d, slugs in self._by_department.items() if slugs)

    # -- Search -----------------------------------------------------------

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
        if query_lower == persona.slug:
            score += 100.0
        if query_lower == persona.name.lower():
            score += 100.0
        if query_lower in persona.slug:
            score += 30.0
        if query_lower in persona.name.lower():
            score += 30.0
        if query_lower in persona.description.lower():
            score += 15.0
        if query_lower == persona.department:
            score += 20.0

        tag_set = set(persona.tags)
        for token in query_tokens:
            if token in tag_set:
                score += 5.0
        for tag in persona.tags:
            for token in query_tokens:
                if token in tag or tag in token:
                    score += 2.0

        return score

    # -- Catalog (for LLM routing) ----------------------------------------

    def build_catalog(
        self,
        personas: Sequence[ExpertPersona] | None = None,
    ) -> str:
        """Build a concise catalog string listing experts for LLM routing."""
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

    def __len__(self) -> int:
        return len(self._experts)

    def __contains__(self, slug: str) -> bool:
        return slug in self._experts

    def __repr__(self) -> str:
        return f"<ExpertRegistry experts={len(self._experts)}>"
```

### Step 7: Package Init

```python
# ultrabot/experts/__init__.py
"""Expert system -- domain-specialist personas with real agent capabilities."""

from pathlib import Path

from ultrabot.experts.parser import ExpertPersona, parse_persona_file, parse_persona_text
from ultrabot.experts.registry import ExpertRegistry
from ultrabot.experts.router import ExpertRouter, RouteResult

#: Path to the bundled persona markdown files shipped with the package.
BUNDLED_PERSONAS_DIR: Path = Path(__file__).parent / "personas"

__all__ = [
    "BUNDLED_PERSONAS_DIR",
    "ExpertPersona",
    "ExpertRegistry",
    "ExpertRouter",
    "RouteResult",
    "parse_persona_file",
    "parse_persona_text",
]
```

### Tests

```python
# tests/test_experts_persona.py
"""Tests for the expert persona parser and registry."""

import tempfile
from pathlib import Path

import pytest

from ultrabot.experts.parser import (
    ExpertPersona,
    parse_persona_file,
    parse_persona_text,
    _parse_frontmatter,
    _extract_sections,
    _extract_tags,
)
from ultrabot.experts.registry import ExpertRegistry


# -- Sample markdown persona for testing --

SAMPLE_PERSONA_MD = """\
---
name: "前端开发者"
description: "React/Vue 前端工程专家"
color: "#61dafb"
---

# 前端开发者

## 你的身份与记忆

你是一位资深的前端开发工程师。

## 核心使命

构建高质量的用户界面。

## 关键规则

- 使用TypeScript
- 编写单元测试
- 遵循无障碍标准

## 工作流程

1. 需求分析
2. 组件设计
3. 编码实现
4. 测试验证
"""


class TestFrontmatterParsing:
    def test_basic_frontmatter(self):
        meta, body = _parse_frontmatter(SAMPLE_PERSONA_MD)
        assert meta["name"] == "前端开发者"
        assert meta["description"] == "React/Vue 前端工程专家"
        assert meta["color"] == "#61dafb"
        assert "# 前端开发者" in body

    def test_no_frontmatter(self):
        meta, body = _parse_frontmatter("Just plain text")
        assert meta == {}
        assert body == "Just plain text"


class TestSectionExtraction:
    def test_chinese_sections(self):
        _, body = _parse_frontmatter(SAMPLE_PERSONA_MD)
        sections = _extract_sections(body)
        assert "identity" in sections
        assert "资深" in sections["identity"]
        assert "core_mission" in sections
        assert "key_rules" in sections
        assert "workflow" in sections


class TestParsePersona:
    def test_parse_text(self):
        persona = parse_persona_text(SAMPLE_PERSONA_MD, slug="engineering-frontend")
        assert persona.slug == "engineering-frontend"
        assert persona.name == "前端开发者"
        assert persona.description == "React/Vue 前端工程专家"
        assert "资深" in persona.identity
        assert "高质量" in persona.core_mission
        assert persona.system_prompt  # raw_body is non-empty

    def test_parse_file(self, tmp_path):
        md_file = tmp_path / "engineering-frontend-developer.md"
        md_file.write_text(SAMPLE_PERSONA_MD, encoding="utf-8")
        persona = parse_persona_file(md_file)
        assert persona.slug == "engineering-frontend-developer"
        assert persona.source_path == md_file

    def test_tags_extracted(self):
        persona = parse_persona_text(SAMPLE_PERSONA_MD, slug="engineering-frontend")
        assert len(persona.tags) > 0
        # Should contain bigrams from Chinese name
        assert "前端" in persona.tags


class TestExpertRegistry:
    def test_register_and_lookup(self):
        registry = ExpertRegistry()
        persona = parse_persona_text(SAMPLE_PERSONA_MD, slug="test-dev")
        registry.register(persona)

        assert len(registry) == 1
        assert "test-dev" in registry
        assert registry.get("test-dev") is persona

    def test_search(self):
        registry = ExpertRegistry()
        registry.register(parse_persona_text(SAMPLE_PERSONA_MD, slug="eng-frontend"))
        results = registry.search("前端")
        assert len(results) >= 1
        assert results[0].slug == "eng-frontend"

    def test_load_directory(self, tmp_path):
        # Write two persona files
        for name in ("dev-a", "dev-b"):
            (tmp_path / f"{name}.md").write_text(
                f"---\nname: {name}\n---\n## Your identity\nI am {name}.",
                encoding="utf-8",
            )
        # README should be skipped
        (tmp_path / "README.md").write_text("# Readme")

        registry = ExpertRegistry(experts_dir=tmp_path)
        count = registry.load_directory()
        assert count == 2
        assert "dev-a" in registry
        assert "dev-b" in registry

    def test_build_catalog(self):
        registry = ExpertRegistry()
        persona = parse_persona_text(SAMPLE_PERSONA_MD, slug="eng-fe")
        registry.register(persona)
        catalog = registry.build_catalog()
        assert "eng-fe" in catalog
        assert "前端开发者" in catalog

    def test_unregister(self):
        registry = ExpertRegistry()
        persona = parse_persona_text(SAMPLE_PERSONA_MD, slug="rm-me")
        registry.register(persona)
        assert len(registry) == 1
        registry.unregister("rm-me")
        assert len(registry) == 0
```

### Checkpoint

```bash
# Create a custom expert YAML, load it, and verify
mkdir -p /tmp/test_experts

cat > /tmp/test_experts/my-coder.md << 'EOF'
---
name: "My Coder"
description: "A custom coding assistant"
---

## Your identity

You are an expert Python programmer.

## Core mission

Write clean, tested Python code.
EOF

python -c "
from ultrabot.experts import ExpertRegistry
reg = ExpertRegistry()
count = reg.load_directory('/tmp/test_experts')
print(f'Loaded {count} expert(s)')
for e in reg.list_all():
    print(f'  - {e.slug}: {e.name} ({e.department})')
    print(f'    Tags: {e.tags[:5]}')
print(f'Search \"coder\": {[e.slug for e in reg.search(\"coder\")]}')
"
```

Expected output:
```
Loaded 1 expert(s)
  - my-coder: My Coder ()
    Tags: ['coder', 'coding', 'custom', 'my']
Search "coder": ['my-coder']
```

### What we built

A complete persona parsing and registry system. Markdown files with YAML
frontmatter are parsed into structured `ExpertPersona` dataclasses with
bilingual section extraction. The `ExpertRegistry` provides O(1) slug lookup,
department grouping, and relevance-scored full-text search across names,
descriptions, and auto-extracted tags.

---
