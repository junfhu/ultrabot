"""Tests for the expert persona system (parser, registry, router)."""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import pytest

from ultrabot.experts.parser import (
    ExpertPersona,
    _extract_sections,
    _extract_tags,
    _infer_department,
    _parse_frontmatter,
    parse_persona_file,
    parse_persona_text,
)
from ultrabot.experts.registry import ExpertRegistry
from ultrabot.experts.router import (
    ExpertRouter,
    RouteResult,
    _AT_PATTERN,
    _SLASH_PATTERN,
    _OFF_PATTERNS,
    _LIST_PATTERN,
)


# ===================================================================
# Fixtures
# ===================================================================


SAMPLE_PERSONA_ZH = textwrap.dedent("""\
    ---
    name: 前端开发者
    description: 精通 React/Vue/Angular 的前端工程专家
    color: cyan
    ---
    # 前端开发者

    你是**前端开发者**，一位精通现代前端技术栈的工程专家。

    ## 你的身份与记忆

    - **角色**：前端工程师与 UI 实现专家
    - **个性**：注重细节、追求性能

    ## 核心使命

    ### 现代 Web 应用开发
    - 使用 React/Vue/Angular 构建可维护的前端应用
    - TypeScript 类型安全

    ## 关键规则

    ### 代码质量
    - 组件职责单一，不超过 200 行
    - Props 类型必须明确定义

    ## 工作流程

    ### 第一步：需求分析
    - 理解产品需求和设计稿

    ### 第二步：架构设计
    - 目录结构和模块划分

    ## 沟通风格

    - **技术精确**："用 Intersection Observer 做懒加载"

    ## 成功指标

    - Lighthouse 性能分 > 90
    - 组件测试覆盖率 > 80%
""")

SAMPLE_PERSONA_EN = textwrap.dedent("""\
    ---
    name: Security Engineer
    description: Threat modeling and code audit specialist
    color: red
    ---
    # Security Engineer

    You are the **Security Engineer**.

    ## Your Identity

    - **Role**: Application security engineer

    ## Core Mission

    - STRIDE threat modeling
    - Code audits

    ## Key Rules

    - Never trust user input

    ## Workflow

    1. Threat modeling
    2. Security review

    ## Communication Style

    - Risk quantification

    ## Success Metrics

    - Zero data breaches
""")


@pytest.fixture
def tmp_experts_dir(tmp_path: Path) -> Path:
    """Create a temporary directory with sample persona files."""
    eng_dir = tmp_path / "engineering"
    eng_dir.mkdir()

    # Chinese persona
    (eng_dir / "engineering-frontend-developer.md").write_text(
        SAMPLE_PERSONA_ZH, encoding="utf-8"
    )
    # English persona
    (eng_dir / "engineering-security-engineer.md").write_text(
        SAMPLE_PERSONA_EN, encoding="utf-8"
    )

    # A marketing persona
    mkt_dir = tmp_path / "marketing"
    mkt_dir.mkdir()
    (mkt_dir / "marketing-growth-hacker.md").write_text(
        textwrap.dedent("""\
            ---
            name: 增长黑客
            description: 数据驱动的增长策略专家
            color: green
            ---
            # 增长黑客

            ## 你的身份与记忆
            - **角色**：增长专家

            ## 核心使命
            - 用户获取和留存

            ## 工作流程
            1. 数据分析
            2. 实验设计
        """),
        encoding="utf-8",
    )

    return tmp_path


@pytest.fixture
def registry(tmp_experts_dir: Path) -> ExpertRegistry:
    """Return a loaded ExpertRegistry."""
    reg = ExpertRegistry(tmp_experts_dir)
    reg.load_directory()
    return reg


# ===================================================================
# Parser tests
# ===================================================================


class TestParseFrontmatter:
    """Tests for YAML frontmatter parsing."""

    def test_basic_frontmatter(self) -> None:
        meta, body = _parse_frontmatter(SAMPLE_PERSONA_ZH)
        assert meta["name"] == "前端开发者"
        assert meta["description"] == "精通 React/Vue/Angular 的前端工程专家"
        assert meta["color"] == "cyan"
        assert body.startswith("# 前端开发者")

    def test_no_frontmatter(self) -> None:
        text = "# Just a heading\n\nSome content."
        meta, body = _parse_frontmatter(text)
        assert meta == {}
        assert body == text

    def test_quoted_values(self) -> None:
        text = '---\nname: "Test Agent"\ncolor: \'#FF0000\'\n---\nBody.'
        meta, body = _parse_frontmatter(text)
        assert meta["name"] == "Test Agent"
        assert meta["color"] == "#FF0000"
        assert body.strip() == "Body."


class TestExtractSections:
    """Tests for markdown section extraction."""

    def test_chinese_sections(self) -> None:
        _, body = _parse_frontmatter(SAMPLE_PERSONA_ZH)
        sections = _extract_sections(body)
        assert "identity" in sections
        assert "core_mission" in sections
        assert "key_rules" in sections
        assert "workflow" in sections
        assert "communication_style" in sections
        assert "success_metrics" in sections

    def test_english_sections(self) -> None:
        _, body = _parse_frontmatter(SAMPLE_PERSONA_EN)
        sections = _extract_sections(body)
        assert "identity" in sections
        assert "core_mission" in sections
        assert "key_rules" in sections
        assert "workflow" in sections

    def test_identity_content(self) -> None:
        _, body = _parse_frontmatter(SAMPLE_PERSONA_ZH)
        sections = _extract_sections(body)
        assert "前端工程师" in sections["identity"]

    def test_unknown_section_ignored(self) -> None:
        text = "## 未知章节\nSome content\n## 核心使命\nReal mission"
        sections = _extract_sections(text)
        assert "core_mission" in sections
        assert "Real mission" in sections["core_mission"]


class TestInferDepartment:
    """Tests for department inference from slugs."""

    def test_engineering(self) -> None:
        assert _infer_department("engineering-frontend-developer") == "engineering"

    def test_marketing(self) -> None:
        assert _infer_department("marketing-growth-hacker") == "marketing"

    def test_game_development(self) -> None:
        assert _infer_department("game-development-designer") == "game-development"

    def test_unknown(self) -> None:
        assert _infer_department("random-slug") == "random"


class TestExtractTags:
    """Tests for tag extraction."""

    def test_english_words(self) -> None:
        persona = ExpertPersona(
            slug="test",
            name="React Developer",
            description="Frontend specialist with React and Vue",
            department="engineering",
        )
        tags = _extract_tags(persona)
        assert "react" in tags
        assert "developer" in tags
        assert "vue" in tags

    def test_chinese_bigrams(self) -> None:
        persona = ExpertPersona(
            slug="test",
            name="前端开发者",
            description="前端工程专家",
            department="engineering",
        )
        tags = _extract_tags(persona)
        assert "前端" in tags
        assert "开发" in tags


class TestParsePersonaFile:
    """Tests for full file parsing."""

    def test_parse_chinese_file(self, tmp_experts_dir: Path) -> None:
        path = tmp_experts_dir / "engineering" / "engineering-frontend-developer.md"
        persona = parse_persona_file(path)

        assert persona.slug == "engineering-frontend-developer"
        assert persona.name == "前端开发者"
        assert persona.department == "engineering"
        assert persona.color == "cyan"
        assert persona.identity  # non-empty
        assert persona.core_mission
        assert persona.workflow
        assert persona.raw_body  # full markdown body
        assert len(persona.tags) > 0

    def test_parse_english_file(self, tmp_experts_dir: Path) -> None:
        path = tmp_experts_dir / "engineering" / "engineering-security-engineer.md"
        persona = parse_persona_file(path)

        assert persona.slug == "engineering-security-engineer"
        assert persona.name == "Security Engineer"
        assert persona.department == "engineering"

    def test_system_prompt_is_raw_body(self, tmp_experts_dir: Path) -> None:
        path = tmp_experts_dir / "engineering" / "engineering-frontend-developer.md"
        persona = parse_persona_file(path)
        assert persona.system_prompt == persona.raw_body


class TestParsePersonaText:
    """Tests for in-memory text parsing."""

    def test_basic(self) -> None:
        persona = parse_persona_text(SAMPLE_PERSONA_ZH, slug="engineering-frontend-developer")
        assert persona.name == "前端开发者"
        assert persona.slug == "engineering-frontend-developer"
        assert persona.department == "engineering"

    def test_no_frontmatter(self) -> None:
        persona = parse_persona_text("# Simple\n\n## 核心使命\nDo stuff.", slug="simple")
        assert persona.name == "simple"  # falls back to slug
        assert persona.core_mission == "Do stuff."


# ===================================================================
# Registry tests
# ===================================================================


class TestExpertRegistry:
    """Tests for the ExpertRegistry."""

    def test_load_directory(self, registry: ExpertRegistry) -> None:
        assert len(registry) == 3

    def test_get_by_slug(self, registry: ExpertRegistry) -> None:
        p = registry.get("engineering-frontend-developer")
        assert p is not None
        assert p.name == "前端开发者"

    def test_get_by_name(self, registry: ExpertRegistry) -> None:
        p = registry.get_by_name("前端开发者")
        assert p is not None
        assert p.slug == "engineering-frontend-developer"

    def test_get_by_name_case_insensitive(self, registry: ExpertRegistry) -> None:
        p = registry.get_by_name("security engineer")
        assert p is not None

    def test_get_missing(self, registry: ExpertRegistry) -> None:
        assert registry.get("nonexistent") is None

    def test_departments(self, registry: ExpertRegistry) -> None:
        depts = registry.departments()
        assert "engineering" in depts
        assert "marketing" in depts

    def test_list_department(self, registry: ExpertRegistry) -> None:
        eng = registry.list_department("engineering")
        assert len(eng) == 2
        slugs = {p.slug for p in eng}
        assert "engineering-frontend-developer" in slugs
        assert "engineering-security-engineer" in slugs

    def test_list_all(self, registry: ExpertRegistry) -> None:
        all_experts = registry.list_all()
        assert len(all_experts) == 3

    def test_search_exact_slug(self, registry: ExpertRegistry) -> None:
        results = registry.search("engineering-frontend-developer")
        assert len(results) >= 1
        assert results[0].slug == "engineering-frontend-developer"

    def test_search_keyword(self, registry: ExpertRegistry) -> None:
        results = registry.search("security")
        assert len(results) >= 1
        assert any(p.slug == "engineering-security-engineer" for p in results)

    def test_search_chinese(self, registry: ExpertRegistry) -> None:
        results = registry.search("增长")
        assert len(results) >= 1

    def test_search_no_results(self, registry: ExpertRegistry) -> None:
        results = registry.search("quantum_physics_zzz")
        assert len(results) == 0

    def test_register_unregister(self) -> None:
        reg = ExpertRegistry()
        persona = ExpertPersona(
            slug="test-agent",
            name="Test Agent",
            department="testing",
        )
        reg.register(persona)
        assert "test-agent" in reg
        assert len(reg) == 1

        reg.unregister("test-agent")
        assert "test-agent" not in reg
        assert len(reg) == 0

    def test_build_catalog(self, registry: ExpertRegistry) -> None:
        catalog = registry.build_catalog()
        assert "engineering" in catalog
        assert "marketing" in catalog
        assert "engineering-frontend-developer" in catalog

    def test_contains(self, registry: ExpertRegistry) -> None:
        assert "engineering-frontend-developer" in registry
        assert "nonexistent" not in registry

    def test_repr(self, registry: ExpertRegistry) -> None:
        assert "ExpertRegistry" in repr(registry)
        assert "3" in repr(registry)


# ===================================================================
# Router tests
# ===================================================================


class TestRouterPatterns:
    """Tests for the regex patterns used by the router."""

    def test_at_pattern(self) -> None:
        m = _AT_PATTERN.match("@frontend-dev help me")
        assert m is not None
        assert m.group(1) == "frontend-dev"

    def test_at_pattern_no_space(self) -> None:
        m = _AT_PATTERN.match("@frontend-dev")
        assert m is not None
        assert m.group(1) == "frontend-dev"

    def test_slash_pattern(self) -> None:
        m = _SLASH_PATTERN.match("/expert frontend-dev help me")
        assert m is not None
        assert m.group(1) == "frontend-dev"

    def test_off_pattern_slash(self) -> None:
        m = _OFF_PATTERNS.match("/expert off")
        assert m is not None

    def test_off_pattern_at_default(self) -> None:
        m = _OFF_PATTERNS.match("@default")
        assert m is not None

    def test_list_pattern_bare(self) -> None:
        m = _LIST_PATTERN.match("/experts")
        assert m is not None
        assert m.group(1) is None

    def test_list_pattern_with_query(self) -> None:
        m = _LIST_PATTERN.match("/experts security")
        assert m is not None
        assert m.group(1) == "security"


class TestExpertRouter:
    """Tests for the ExpertRouter."""

    @pytest.fixture
    def router(self, registry: ExpertRegistry) -> ExpertRouter:
        return ExpertRouter(registry=registry, auto_route=False)

    def test_default_route(self, router: ExpertRouter) -> None:
        result = asyncio.get_event_loop().run_until_complete(
            router.route("hello world", session_key="test:1")
        )
        assert result.persona is None
        assert result.source == "default"
        assert result.cleaned_message == "hello world"

    def test_at_command_route(self, router: ExpertRouter) -> None:
        result = asyncio.get_event_loop().run_until_complete(
            router.route(
                "@engineering-frontend-developer build a React component",
                session_key="test:2",
            )
        )
        assert result.persona is not None
        assert result.persona.slug == "engineering-frontend-developer"
        assert result.source == "command"
        assert "build a React component" in result.cleaned_message

    def test_slash_command_route(self, router: ExpertRouter) -> None:
        result = asyncio.get_event_loop().run_until_complete(
            router.route(
                "/expert engineering-security-engineer audit this code",
                session_key="test:3",
            )
        )
        assert result.persona is not None
        assert result.persona.slug == "engineering-security-engineer"
        assert result.source == "command"

    def test_sticky_session(self, router: ExpertRouter) -> None:
        # First message activates expert.
        asyncio.get_event_loop().run_until_complete(
            router.route(
                "@engineering-frontend-developer hello",
                session_key="test:4",
            )
        )
        # Second message should stick with same expert.
        result = asyncio.get_event_loop().run_until_complete(
            router.route("now help me with CSS", session_key="test:4")
        )
        assert result.persona is not None
        assert result.persona.slug == "engineering-frontend-developer"
        assert result.source == "sticky"

    def test_off_command_clears_sticky(self, router: ExpertRouter) -> None:
        # Activate expert.
        asyncio.get_event_loop().run_until_complete(
            router.route("@engineering-frontend-developer hello", session_key="test:5")
        )
        # Deactivate.
        result = asyncio.get_event_loop().run_until_complete(
            router.route("/expert off", session_key="test:5")
        )
        assert result.persona is None
        assert result.source == "command"

        # Next message should be default.
        result = asyncio.get_event_loop().run_until_complete(
            router.route("hello again", session_key="test:5")
        )
        assert result.persona is None
        assert result.source == "default"

    def test_at_default_clears_sticky(self, router: ExpertRouter) -> None:
        asyncio.get_event_loop().run_until_complete(
            router.route("@engineering-frontend-developer hi", session_key="test:6")
        )
        result = asyncio.get_event_loop().run_until_complete(
            router.route("@default", session_key="test:6")
        )
        assert result.persona is None

    def test_list_command(self, router: ExpertRouter) -> None:
        result = asyncio.get_event_loop().run_until_complete(
            router.route("/experts", session_key="test:7")
        )
        assert result.persona is None
        assert result.source == "command"
        assert "3 experts" in result.cleaned_message

    def test_list_command_with_search(self, router: ExpertRouter) -> None:
        result = asyncio.get_event_loop().run_until_complete(
            router.route("/experts security", session_key="test:8")
        )
        assert result.persona is None
        assert "security" in result.cleaned_message.lower()

    def test_unknown_slug_falls_through(self, router: ExpertRouter) -> None:
        result = asyncio.get_event_loop().run_until_complete(
            router.route("@nonexistent-expert hello", session_key="test:9")
        )
        assert result.persona is None
        assert result.source == "default"

    def test_clear_sticky(self, router: ExpertRouter) -> None:
        asyncio.get_event_loop().run_until_complete(
            router.route("@engineering-frontend-developer hi", session_key="test:10")
        )
        assert router.get_sticky("test:10") == "engineering-frontend-developer"
        router.clear_sticky("test:10")
        assert router.get_sticky("test:10") is None


# ===================================================================
# Prompts integration tests
# ===================================================================


class TestExpertPrompts:
    """Tests for expert-aware prompt building."""

    def test_build_expert_system_prompt(self) -> None:
        from ultrabot.agent.prompts import build_expert_system_prompt

        persona = ExpertPersona(
            slug="test-expert",
            name="Test Expert",
            raw_body="# Test Expert\n\nYou are a test expert.",
        )
        prompt = build_expert_system_prompt(persona)
        assert "domain expert agent" in prompt
        assert "Test Expert" in prompt
        assert "test-expert" in prompt
        assert "Runtime Context" in prompt

    def test_build_system_prompt_unchanged(self) -> None:
        from ultrabot.agent.prompts import build_system_prompt

        prompt = build_system_prompt()
        assert "ultrabot" in prompt
        assert "Runtime Context" in prompt

    def test_expert_prompt_includes_tool_instructions(self) -> None:
        from ultrabot.agent.prompts import build_expert_system_prompt

        persona = ExpertPersona(
            slug="test",
            name="Test",
            raw_body="# Test",
        )
        prompt = build_expert_system_prompt(persona)
        assert "web_search" in prompt
        assert "read_file" in prompt
        assert "exec_command" in prompt


# ===================================================================
# Config tests
# ===================================================================


class TestExpertsConfig:
    """Tests for ExpertsConfig schema."""

    def test_default_config(self) -> None:
        from ultrabot.config.schema import ExpertsConfig

        cfg = ExpertsConfig()
        assert cfg.enabled is True
        assert cfg.auto_route is False
        assert cfg.auto_sync is False
        assert cfg.directory == "~/.ultrabot/experts"
        assert cfg.departments == []

    def test_config_in_root(self) -> None:
        from ultrabot.config.schema import Config

        cfg = Config()
        assert hasattr(cfg, "experts")
        assert cfg.experts.enabled is True

    def test_camel_case_alias(self) -> None:
        from ultrabot.config.schema import ExpertsConfig

        cfg = ExpertsConfig.model_validate(
            {"autoRoute": True, "autoSync": True}
        )
        assert cfg.auto_route is True
        assert cfg.auto_sync is True


# ===================================================================
# Sync tests (mock-friendly)
# ===================================================================


class TestSyncHelpers:
    """Tests for sync module helpers (without network calls)."""

    def test_filter_persona_files(self) -> None:
        from ultrabot.experts.sync import _filter_persona_files

        tree = [
            {"type": "blob", "path": "engineering/engineering-frontend-developer.md"},
            {"type": "blob", "path": "engineering/README.md"},
            {"type": "blob", "path": "marketing/marketing-growth-hacker.md"},
            {"type": "blob", "path": "scripts/install.sh"},
            {"type": "blob", "path": "examples/workflow.md"},
            {"type": "tree", "path": "engineering"},
        ]

        files = _filter_persona_files(tree, departments=None)
        assert len(files) == 2
        assert "engineering/engineering-frontend-developer.md" in files
        assert "marketing/marketing-growth-hacker.md" in files

    def test_filter_by_department(self) -> None:
        from ultrabot.experts.sync import _filter_persona_files

        tree = [
            {"type": "blob", "path": "engineering/eng-a.md"},
            {"type": "blob", "path": "marketing/mkt-a.md"},
        ]

        files = _filter_persona_files(tree, departments={"engineering"})
        assert len(files) == 1
        assert "engineering/eng-a.md" in files

    def test_filter_skips_underscore_files(self) -> None:
        from ultrabot.experts.sync import _filter_persona_files

        tree = [
            {"type": "blob", "path": "engineering/_template.md"},
        ]
        files = _filter_persona_files(tree, departments=None)
        assert len(files) == 0
