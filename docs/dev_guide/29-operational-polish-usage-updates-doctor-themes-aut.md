# Session 29: Operational Polish — Usage, Updates, Doctor, Themes, Auth Rotation

**Goal:** Add the remaining operational features that make ultrabot production-ready: usage tracking, self-update, config diagnostics, themes, API key rotation, group activation, device pairing, skills, MCP, and title generation.

**What you'll learn:**
- Per-model token/cost tracking with pricing tables
- Self-update system (git-based and pip-based)
- Config health checks and auto-repair
- Schema versioning with migration functions
- CLI themes with YAML customization
- Round-robin API key rotation with cooldown
- Group chat activation modes and DM pairing
- Skill discovery, MCP client, and title generation (overview)

**New files:**
- `ultrabot/usage/tracker.py` — `UsageTracker`, `UsageRecord`, pricing tables
- `ultrabot/updater/update.py` — `UpdateChecker`, `check_update()`, `run_update()`
- `ultrabot/config/doctor.py` — `run_doctor()`, 8 health checks
- `ultrabot/config/migrations.py` — `apply_migrations()`, migration registry
- `ultrabot/cli/themes.py` — `ThemeManager`, 4 built-in themes
- `ultrabot/providers/auth_rotation.py` — `AuthRotator`, `AuthProfile`
- `ultrabot/channels/group_activation.py` — `check_activation()`, mention detection
- `ultrabot/channels/pairing.py` — `PairingManager`, approval codes
- `ultrabot/skills/manager.py` — `SkillManager`, skill discovery
- `ultrabot/mcp/client.py` — `MCPClient`, stdio/HTTP transports
- `ultrabot/agent/title_generator.py` — `generate_title()`

### Step 1: Usage Tracking

Track every API call's token usage and cost. The pricing table covers major providers.

```python
# ultrabot/usage/tracker.py  (key excerpts — full file is ~310 lines)
"""Usage and cost tracking for LLM API calls."""

from __future__ import annotations
import json, time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from loguru import logger

# ── Pricing tables (USD per 1M tokens) ──────────────────────────
PRICING: dict[str, dict[str, dict[str, float]]] = {
    "anthropic": {
        "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0,
                                       "cache_read": 0.3, "cache_write": 3.75},
        "claude-opus-4-20250514": {"input": 15.0, "output": 75.0,
                                     "cache_read": 1.5, "cache_write": 18.75},
        "claude-3-5-haiku-20241022": {"input": 0.8, "output": 4.0,
                                       "cache_read": 0.08, "cache_write": 1.0},
    },
    "openai": {
        "gpt-4o": {"input": 2.5, "output": 10.0},
        "gpt-4o-mini": {"input": 0.15, "output": 0.6},
    },
    "deepseek": {
        "deepseek-chat": {"input": 0.14, "output": 0.28, "cache_read": 0.014},
    },
}


@dataclass
class UsageRecord:
    """A single API call usage record."""
    timestamp: float = field(default_factory=time.time)
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    session_key: str = ""
    tool_calls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: dict) -> UsageRecord:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def calculate_cost(provider: str, model: str, input_tokens: int = 0,
                   output_tokens: int = 0, **kwargs) -> float:
    """Calculate cost in USD for a given usage."""
    provider_pricing = PRICING.get(provider, {})
    model_pricing = provider_pricing.get(model)
    if model_pricing is None:
        # Try prefix match
        for known, pricing in provider_pricing.items():
            if known in model.lower() or model.lower() in known:
                model_pricing = pricing
                break
    if model_pricing is None:
        return 0.0
    cost = input_tokens * model_pricing.get("input", 0) / 1_000_000
    cost += output_tokens * model_pricing.get("output", 0) / 1_000_000
    cost += kwargs.get("cache_read_tokens", 0) * model_pricing.get("cache_read", 0) / 1_000_000
    cost += kwargs.get("cache_write_tokens", 0) * model_pricing.get("cache_write", 0) / 1_000_000
    return cost


class UsageTracker:
    """Tracks and persists LLM API usage and costs."""

    def __init__(self, data_dir: Path | None = None, max_records: int = 10000):
        self._data_dir = data_dir
        self._max_records = max_records
        self._records: list[UsageRecord] = []
        self._total_tokens = 0
        self._total_cost = 0.0
        self._by_model: dict[str, dict[str, float]] = defaultdict(
            lambda: {"tokens": 0, "cost": 0.0})
        self._daily: dict[str, dict[str, float]] = defaultdict(
            lambda: {"tokens": 0, "cost": 0.0, "calls": 0})

    def record(self, provider: str, model: str, raw_usage: dict,
               session_key: str = "", tool_names: list[str] | None = None) -> UsageRecord:
        """Record a single API call's usage."""
        cost = calculate_cost(provider, model,
                              raw_usage.get("input_tokens", 0),
                              raw_usage.get("output_tokens", 0))
        rec = UsageRecord(provider=provider, model=model, cost_usd=cost,
                          input_tokens=raw_usage.get("input_tokens", 0),
                          output_tokens=raw_usage.get("output_tokens", 0),
                          total_tokens=raw_usage.get("total_tokens", 0),
                          session_key=session_key, tool_calls=tool_names or [])
        self._records.append(rec)
        self._total_tokens += rec.total_tokens
        self._total_cost += rec.cost_usd
        today = date.today().isoformat()
        self._daily[today]["tokens"] += rec.total_tokens
        self._daily[today]["cost"] += rec.cost_usd
        self._daily[today]["calls"] += 1
        while len(self._records) > self._max_records:
            self._records.pop(0)
        return rec

    def get_summary(self) -> dict[str, Any]:
        return {"total_tokens": self._total_tokens,
                "total_cost_usd": round(self._total_cost, 6),
                "total_calls": len(self._records),
                "daily": dict(self._daily)}
```

### Step 2: Config Migrations

Versioned migrations upgrade old config formats automatically.

```python
# ultrabot/config/migrations.py  (key excerpts)
"""Config migration system -- versioned schema migrations."""

CONFIG_VERSION_KEY = "_configVersion"
CURRENT_VERSION = 3

# Migration registry
_MIGRATIONS: list[Migration] = []

def register_migration(version: int, name: str, description: str = ""):
    """Decorator to register a migration function."""
    def decorator(fn):
        _MIGRATIONS.append(Migration(version=version, name=name,
                                      description=description, migrate=fn))
        _MIGRATIONS.sort(key=lambda m: m.version)
        return fn
    return decorator

@register_migration(1, "add-config-version")
def _add_version(config: dict) -> tuple[dict, list[str]]:
    if CONFIG_VERSION_KEY not in config:
        config[CONFIG_VERSION_KEY] = 1
        return config, ["Added _configVersion field"]
    return config, []

@register_migration(2, "normalize-provider-keys")
def _normalize_providers(config: dict) -> tuple[dict, list[str]]:
    # Move top-level API keys (openai_api_key) into providers section
    # Normalize camelCase vs snake_case
    ...

@register_migration(3, "normalize-channel-config")
def _normalize_channels(config: dict) -> tuple[dict, list[str]]:
    # Move top-level channel configs into channels section
    ...

def apply_migrations(config: dict, target_version: int | None = None) -> MigrationResult:
    """Apply all pending migrations to a config dict."""
    ...
```

### Step 3: Config Doctor

Eight health checks diagnose common issues.

```python
# ultrabot/config/doctor.py  (key excerpts)

def run_doctor(config_path: Path, data_dir: Path | None = None,
               repair: bool = False) -> DoctorReport:
    """Run all health checks and return a report."""
    report = DoctorReport()
    report.checks.append(check_config_file(config_path))    # 1. Valid JSON?
    report.checks.append(check_config_version(config))       # 2. Needs migration?
    report.checks.append(check_providers(config))            # 3. API keys set?
    report.checks.append(check_workspace(config))            # 4. Workspace exists?
    report.checks.append(check_sessions_dir(data_dir))       # 5. Sessions dir OK?
    report.warnings = check_security(config)                 # 6-8. Security warnings
    if repair:
        apply_migrations(config)  # Auto-fix what we can
    return report
```

### Step 4: Theme Manager

Four built-in themes plus YAML custom themes.

```python
# ultrabot/cli/themes.py  (key excerpts)

@dataclass
class ThemeColors:
    primary: str = "blue"
    secondary: str = "cyan"
    success: str = "green"
    warning: str = "yellow"
    error: str = "red"

@dataclass
class Theme:
    name: str
    description: str = ""
    colors: ThemeColors = field(default_factory=ThemeColors)
    spinner: ThemeSpinner = field(default_factory=ThemeSpinner)
    branding: ThemeBranding = field(default_factory=ThemeBranding)

# Built-in themes: default (blue/cyan), dark (green), light (bright), mono (grayscale)
_BUILTIN_THEMES = {"default": THEME_DEFAULT, "dark": THEME_DARK,
                    "light": THEME_LIGHT, "mono": THEME_MONO}

class ThemeManager:
    def __init__(self, themes_dir: Path | None = None):
        self._builtin = dict(_BUILTIN_THEMES)
        self._user: dict[str, Theme] = {}
        self._active = self._builtin["default"]
        if themes_dir:
            self.load_user_themes()

    def set_active(self, name: str) -> bool:
        theme = self.get(name)
        if theme is None:
            return False
        self._active = theme
        return True
```

### Step 5: Auth Rotation

Round-robin API key rotation with automatic cooldown on rate limits.

```python
# ultrabot/providers/auth_rotation.py  (key excerpts)

class AuthProfile:
    """A single API credential with state tracking.
    
    ACTIVE → COOLDOWN (on rate limit) → ACTIVE (after cooldown elapsed)
    ACTIVE → FAILED (after 3 consecutive failures)
    """
    key: str
    state: CredentialState = CredentialState.ACTIVE
    cooldown_until: float = 0.0
    consecutive_failures: int = 0

class AuthRotator:
    """Round-robin rotation across multiple API keys."""
    
    def get_next_key(self) -> str | None:
        """Get next available key. Returns None if all exhausted."""
        for _ in range(len(self._profiles)):
            profile = self._profiles[self._current_index]
            self._current_index = (self._current_index + 1) % len(self._profiles)
            if profile.is_available:
                return profile.key
        # Last resort: reset failed keys
        for profile in self._profiles:
            if profile.state == CredentialState.FAILED:
                profile.reset()
                return profile.key
        return None

async def execute_with_rotation(rotator, execute, is_rate_limit=None):
    """Execute an async function with automatic key rotation on failure."""
    ...
```

### Step 6: Group Activation + Pairing (Brief)

```python
# ultrabot/channels/group_activation.py
# Controls when bot responds in group chats: "mention" mode (only @mentioned)
# or "always" mode. check_activation() is the entry point.

# ultrabot/channels/pairing.py
# PairingManager generates approval codes for unknown DM senders.
# Supports OPEN, PAIRING, and CLOSED policies per channel.
```

### Step 7: Skills, MCP, Title Generation (Brief)

```python
# ultrabot/skills/manager.py
# SkillManager discovers skills from disk (SKILL.md + optional tools/).
# Supports hot-reload via reload() method.

# ultrabot/mcp/client.py
# MCPClient connects to MCP servers via stdio or HTTP transport.
# Wraps each server tool as a local MCPToolWrapper(Tool).

# ultrabot/agent/title_generator.py
# generate_title() uses the AuxiliaryClient to create 3-7 word titles
# for conversations. Falls back to first 50 chars of first user message.
```

### Tests

```python
# tests/test_operational.py
"""Tests for operational features: usage, updates, doctor, themes, auth rotation."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from ultrabot.usage.tracker import UsageTracker, calculate_cost, UsageRecord
from ultrabot.config.doctor import (
    check_config_file, check_providers, DoctorReport, HealthCheck,
)
from ultrabot.config.migrations import (
    apply_migrations, get_config_version, needs_migration, CURRENT_VERSION,
)
from ultrabot.cli.themes import ThemeManager, Theme, ThemeColors
from ultrabot.providers.auth_rotation import AuthRotator, AuthProfile, CredentialState
from ultrabot.channels.group_activation import (
    check_activation, ActivationMode, set_bot_names,
)
from ultrabot.channels.pairing import PairingManager, PairingPolicy


class TestUsageTracker:
    def test_record_and_summary(self):
        tracker = UsageTracker()
        tracker.record("anthropic", "claude-sonnet-4-20250514",
                       {"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500})
        summary = tracker.get_summary()
        assert summary["total_tokens"] == 1500
        assert summary["total_cost_usd"] > 0

    def test_calculate_cost_known_model(self):
        cost = calculate_cost("anthropic", "claude-sonnet-4-20250514",
                              input_tokens=1000, output_tokens=500)
        # 1000 * 3.0/1M + 500 * 15.0/1M = 0.003 + 0.0075 = 0.0105
        assert abs(cost - 0.0105) < 0.001

    def test_calculate_cost_unknown_model(self):
        assert calculate_cost("unknown", "unknown-model", 1000, 500) == 0.0

    def test_fifo_eviction(self):
        tracker = UsageTracker(max_records=5)
        for i in range(10):
            tracker.record("openai", "gpt-4o",
                           {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150})
        assert tracker.get_summary()["total_calls"] == 5


class TestConfigMigrations:
    def test_needs_migration_fresh_config(self):
        config = {}
        assert needs_migration(config) is True

    def test_apply_all_migrations(self):
        config = {"openai_api_key": "sk-test123456789"}
        result = apply_migrations(config)
        assert result.to_version == CURRENT_VERSION
        assert len(result.applied) > 0

    def test_already_current(self):
        config = {"_configVersion": CURRENT_VERSION}
        result = apply_migrations(config)
        assert len(result.applied) == 0


class TestConfigDoctor:
    def test_check_config_file_missing(self, tmp_path):
        result = check_config_file(tmp_path / "nope.json")
        assert result.ok is False
        assert result.auto_fixable is True

    def test_check_config_file_valid(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text('{"providers": {}}')
        result = check_config_file(cfg)
        assert result.ok is True

    def test_check_providers_none_configured(self):
        result = check_providers({})
        assert result.ok is False

    def test_check_providers_configured(self):
        config = {"providers": {"anthropic": {"apiKey": "sk-test"}}}
        result = check_providers(config)
        assert result.ok is True


class TestThemeManager:
    def test_builtin_themes_loaded(self):
        mgr = ThemeManager()
        themes = mgr.list_themes()
        names = [t.name for t in themes]
        assert "default" in names
        assert "dark" in names
        assert "mono" in names

    def test_set_active(self):
        mgr = ThemeManager()
        assert mgr.set_active("dark") is True
        assert mgr.active.name == "dark"

    def test_set_unknown_theme_fails(self):
        mgr = ThemeManager()
        assert mgr.set_active("nonexistent") is False
        assert mgr.active.name == "default"  # unchanged


class TestAuthRotation:
    def test_single_key(self):
        rotator = AuthRotator(["key1"])
        assert rotator.get_next_key() == "key1"

    def test_round_robin(self):
        rotator = AuthRotator(["k1", "k2", "k3"])
        keys = [rotator.get_next_key() for _ in range(6)]
        assert keys == ["k1", "k2", "k3", "k1", "k2", "k3"]

    def test_cooldown_on_failure(self):
        rotator = AuthRotator(["k1", "k2"], cooldown_seconds=0.01)
        rotator.record_failure("k1")
        # k1 is in cooldown, so next key should be k2
        assert rotator.get_next_key() == "k2"

    def test_dedup_keys(self):
        rotator = AuthRotator(["k1", "k1", "k2", ""])
        assert rotator.profile_count == 2

    def test_all_keys_exhausted(self):
        rotator = AuthRotator([])
        assert rotator.get_next_key() is None


class TestGroupActivation:
    def test_dm_always_responds(self):
        result = check_activation("hello", "session1", is_group=False)
        assert result.should_respond is True

    def test_group_mention_mode(self):
        set_bot_names(["ultrabot"])
        result = check_activation("hey there", "grp1", is_group=True)
        assert result.should_respond is False

        result = check_activation("@ultrabot help me", "grp1", is_group=True)
        assert result.should_respond is True


class TestPairing:
    def test_open_policy_approves_all(self, tmp_path):
        mgr = PairingManager(tmp_path, default_policy=PairingPolicy.OPEN)
        approved, code = mgr.check_sender("telegram", "user123")
        assert approved is True
        assert code is None

    def test_pairing_generates_code(self, tmp_path):
        mgr = PairingManager(tmp_path, default_policy=PairingPolicy.PAIRING)
        approved, code = mgr.check_sender("telegram", "user456")
        assert approved is False
        assert code is not None
        assert len(code) == 6

    def test_approve_by_code(self, tmp_path):
        mgr = PairingManager(tmp_path, default_policy=PairingPolicy.PAIRING)
        _, code = mgr.check_sender("telegram", "user789")
        request = mgr.approve_by_code(code)
        assert request is not None
        assert request.sender_id == "user789"
        # Now approved
        assert mgr.is_approved("telegram", "user789") is True
```

### Checkpoint

```bash
python -m pytest tests/test_operational.py -v
```

Expected: all tests pass covering usage tracking, config migrations, doctor checks, themes, auth rotation, group activation, and DM pairing.

### What we built

The full operational layer: usage tracking with per-model pricing, self-update (git + pip), config doctor with 8 health checks and auto-repair, schema migrations, 4 CLI themes with YAML customization, round-robin API key rotation, group chat activation modes, DM pairing with approval codes, skill discovery, MCP client, and title generation. ultrabot is now production-ready.

---
