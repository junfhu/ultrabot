"""Tests for ultrabot.config.migrations and ultrabot.config.doctor."""
from __future__ import annotations

import json

import pytest

from ultrabot.config.migrations import (
    CONFIG_VERSION_KEY,
    CURRENT_VERSION,
    MigrationResult,
    _add_version,
    _normalize_channels,
    _normalize_providers,
    apply_migrations,
    get_config_version,
    needs_migration,
)
from ultrabot.config.doctor import (
    DoctorReport,
    HealthCheck,
    check_config_file,
    check_providers,
    check_security,
    run_doctor,
)


# ===================================================================
# Migration unit tests
# ===================================================================


class TestGetConfigVersion:
    def test_empty_config_returns_zero(self):
        assert get_config_version({}) == 0

    def test_returns_stored_version(self):
        assert get_config_version({CONFIG_VERSION_KEY: 2}) == 2


class TestNeedsMigration:
    def test_true_for_version_zero(self):
        assert needs_migration({}) is True

    def test_false_for_current_version(self):
        assert needs_migration({CONFIG_VERSION_KEY: CURRENT_VERSION}) is False

    def test_true_for_old_version(self):
        assert needs_migration({CONFIG_VERSION_KEY: 1}) is True


class TestAddVersionMigration:
    def test_adds_config_version(self):
        config = {"agents": {}}
        result_config, changes = _add_version(config)
        assert result_config[CONFIG_VERSION_KEY] == 1
        assert len(changes) == 1
        assert "Added _configVersion" in changes[0]

    def test_skips_if_already_present(self):
        config = {CONFIG_VERSION_KEY: 1}
        result_config, changes = _add_version(config)
        assert result_config[CONFIG_VERSION_KEY] == 1
        assert changes == []


class TestNormalizeProviders:
    def test_moves_top_level_api_keys(self):
        config = {
            "openai_api_key": "sk-test-openai",
            "anthropic_api_key": "sk-test-anthropic",
            "providers": {},
        }
        result_config, changes = _normalize_providers(config)

        # Top-level keys should be removed
        assert "openai_api_key" not in result_config
        assert "anthropic_api_key" not in result_config

        # Keys should be in provider sections
        assert result_config["providers"]["openai"]["apiKey"] == "sk-test-openai"
        assert result_config["providers"]["anthropic"]["apiKey"] == "sk-test-anthropic"
        assert len(changes) == 2

    def test_does_not_overwrite_existing_api_key(self):
        config = {
            "openai_api_key": "sk-old",
            "providers": {"openai": {"apiKey": "sk-existing"}},
        }
        result_config, changes = _normalize_providers(config)
        # Existing key should be preserved; top-level key stays because apiKey
        # was already present.
        assert result_config["providers"]["openai"]["apiKey"] == "sk-existing"

    def test_snake_case_to_camel_case(self):
        config = {
            "providers": {
                "openai": {"api_key": "sk-test", "api_base": "https://example.com"},
            },
        }
        result_config, changes = _normalize_providers(config)
        assert result_config["providers"]["openai"]["apiKey"] == "sk-test"
        assert result_config["providers"]["openai"]["apiBase"] == "https://example.com"
        assert "api_key" not in result_config["providers"]["openai"]
        assert "api_base" not in result_config["providers"]["openai"]
        assert len(changes) == 2

    def test_creates_providers_section_if_missing(self):
        config = {"openai_api_key": "sk-test"}
        result_config, changes = _normalize_providers(config)
        assert "providers" in result_config
        assert result_config["providers"]["openai"]["apiKey"] == "sk-test"


class TestNormalizeChannels:
    def test_moves_top_level_channel_configs(self):
        config = {
            "telegram": {"token": "bot-token", "allow_from": ["123"]},
            "discord": {"token": "disc-token"},
            "channels": {},
        }
        result_config, changes = _normalize_channels(config)

        # Top-level keys should be removed
        assert "telegram" not in result_config
        assert "discord" not in result_config

        # Should be nested under channels
        assert result_config["channels"]["telegram"]["token"] == "bot-token"
        assert result_config["channels"]["discord"]["token"] == "disc-token"
        assert any("telegram" in c for c in changes)

    def test_normalizes_allow_from(self):
        config = {
            "channels": {
                "telegram": {"allow_from": ["123", "456"]},
            },
        }
        result_config, changes = _normalize_channels(config)
        assert result_config["channels"]["telegram"]["allowFrom"] == ["123", "456"]
        assert "allow_from" not in result_config["channels"]["telegram"]

    def test_does_not_overwrite_existing_channel_in_channels(self):
        config = {
            "telegram": {"token": "old-token"},
            "channels": {"telegram": {"token": "existing-token"}},
        }
        result_config, changes = _normalize_channels(config)
        # Existing channel config should be preserved
        assert result_config["channels"]["telegram"]["token"] == "existing-token"


class TestApplyMigrations:
    def test_runs_all_pending(self):
        config = {"openai_api_key": "sk-test", "telegram": {"token": "tg-token"}}
        result = apply_migrations(config)

        assert result.from_version == 0
        assert result.to_version == CURRENT_VERSION
        assert len(result.applied) == 3
        assert "add-config-version" in result.applied
        assert "normalize-provider-keys" in result.applied
        assert "normalize-channel-config" in result.applied
        assert result.config[CONFIG_VERSION_KEY] == CURRENT_VERSION

    def test_skips_already_applied(self):
        config = {CONFIG_VERSION_KEY: CURRENT_VERSION, "providers": {}}
        result = apply_migrations(config)

        assert result.from_version == CURRENT_VERSION
        assert result.to_version == CURRENT_VERSION
        assert result.applied == []
        assert result.changes == []

    def test_partial_migration_to_target(self):
        config = {}
        result = apply_migrations(config, target_version=2)

        assert result.to_version == 2
        assert "add-config-version" in result.applied
        assert "normalize-provider-keys" in result.applied
        assert "normalize-channel-config" not in result.applied

    def test_resumes_from_intermediate_version(self):
        config = {CONFIG_VERSION_KEY: 1}
        result = apply_migrations(config)

        assert result.from_version == 1
        assert result.to_version == CURRENT_VERSION
        assert "add-config-version" not in result.applied
        assert "normalize-provider-keys" in result.applied

    def test_migration_result_has_changes(self):
        config = {"openai_api_key": "sk-test"}
        result = apply_migrations(config)
        assert len(result.changes) > 0


# ===================================================================
# Doctor unit tests
# ===================================================================


class TestCheckConfigFile:
    def test_valid_json(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text('{"providers": {}}', encoding="utf-8")
        check = check_config_file(cfg)
        assert check.ok is True
        assert "Valid JSON" in check.message

    def test_missing_file(self, tmp_path):
        cfg = tmp_path / "nonexistent.json"
        check = check_config_file(cfg)
        assert check.ok is False
        assert "not found" in check.message

    def test_invalid_json(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text("{broken json}", encoding="utf-8")
        check = check_config_file(cfg)
        assert check.ok is False
        assert "Invalid JSON" in check.message

    def test_non_object_json(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text('["not", "an", "object"]', encoding="utf-8")
        check = check_config_file(cfg)
        assert check.ok is False
        assert "not a JSON object" in check.message


class TestCheckProviders:
    def test_with_api_key(self):
        config = {"providers": {"openai": {"apiKey": "sk-test"}}}
        check = check_providers(config)
        assert check.ok is True
        assert "openai" in check.message

    def test_without_api_keys(self):
        config = {"providers": {"openai": {}}}
        check = check_providers(config)
        assert check.ok is False
        assert "No providers" in check.message

    def test_empty_providers(self):
        config = {"providers": {}}
        check = check_providers(config)
        assert check.ok is False

    def test_no_providers_section(self):
        config = {}
        check = check_providers(config)
        assert check.ok is False

    def test_multiple_configured(self):
        config = {
            "providers": {
                "openai": {"apiKey": "sk-openai"},
                "anthropic": {"apiKey": "sk-anthropic"},
            }
        }
        check = check_providers(config)
        assert check.ok is True
        assert "openai" in check.message
        assert "anthropic" in check.message


class TestCheckSecurity:
    def test_detects_plain_text_keys(self):
        config = {
            "providers": {
                "openai": {"apiKey": "sk-this-is-a-real-api-key-12345"},
            }
        }
        warnings = check_security(config)
        assert len(warnings) == 1
        assert "plain-text API key" in warnings[0]

    def test_ignores_env_var_references(self):
        config = {
            "providers": {
                "openai": {"apiKey": "${OPENAI_API_KEY}"},
            }
        }
        warnings = check_security(config)
        assert len(warnings) == 0

    def test_ignores_short_keys(self):
        config = {"providers": {"openai": {"apiKey": "short"}}}
        warnings = check_security(config)
        assert len(warnings) == 0

    def test_detects_wildcard_access(self):
        config = {
            "channels": {
                "telegram": {"allowFrom": ["*"]},
            }
        }
        warnings = check_security(config)
        assert len(warnings) == 1
        assert "ALL senders" in warnings[0]

    def test_no_warnings_for_safe_config(self):
        config = {
            "providers": {"openai": {"apiKey": "${OPENAI_KEY}"}},
            "channels": {"telegram": {"allowFrom": ["12345"]}},
        }
        warnings = check_security(config)
        assert warnings == []

    def test_combined_warnings(self):
        config = {
            "providers": {"openai": {"apiKey": "sk-this-is-a-long-api-key-value"}},
            "channels": {"telegram": {"allowFrom": ["*"]}},
        }
        warnings = check_security(config)
        assert len(warnings) == 2


# ===================================================================
# DoctorReport tests
# ===================================================================


class TestDoctorReport:
    def test_summary_all_passed(self):
        report = DoctorReport(
            checks=[
                HealthCheck(name="A", ok=True, message="ok"),
                HealthCheck(name="B", ok=True, message="ok"),
            ]
        )
        assert report.healthy is True
        assert "2 passed, 0 failed" in report.summary

    def test_summary_with_failures(self):
        report = DoctorReport(
            checks=[
                HealthCheck(name="A", ok=True, message="ok"),
                HealthCheck(name="B", ok=False, message="bad"),
            ],
            warnings=["watch out"],
        )
        assert report.healthy is False
        assert "1 passed, 1 failed, 1 warning(s)" in report.summary

    def test_format_report_includes_sections(self):
        report = DoctorReport(
            checks=[
                HealthCheck(name="Config", ok=True, message="Valid"),
                HealthCheck(name="Provider", ok=False, message="Missing", suggestion="Add key"),
            ],
            warnings=["Insecure key"],
            migrations_applied=["add-config-version"],
        )
        output = report.format_report()
        assert "=== Ultrabot Doctor Report ===" in output
        assert "[OK] Config: Valid" in output
        assert "[FAIL] Provider: Missing" in output
        assert "-> Add key" in output
        assert "Warnings:" in output
        assert "! Insecure key" in output
        assert "Migrations applied:" in output
        assert "+ add-config-version" in output
        assert "Summary:" in output

    def test_format_report_empty(self):
        report = DoctorReport()
        output = report.format_report()
        assert "=== Ultrabot Doctor Report ===" in output
        assert "0 passed, 0 failed, 0 warning(s)" in output


# ===================================================================
# Integration: run_doctor
# ===================================================================


class TestRunDoctor:
    def test_missing_config(self, tmp_path):
        report = run_doctor(tmp_path / "config.json")
        assert report.healthy is False
        assert len(report.checks) == 1
        assert report.checks[0].name == "Config file"

    def test_valid_config_no_providers(self, tmp_path):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(
            json.dumps({CONFIG_VERSION_KEY: CURRENT_VERSION}),
            encoding="utf-8",
        )
        report = run_doctor(cfg_path)
        # Should have multiple checks
        assert len(report.checks) >= 4
        # Config file check should pass
        assert report.checks[0].ok is True
        # Config version should pass
        assert report.checks[1].ok is True
        # Providers should fail (no keys)
        provider_check = next(c for c in report.checks if c.name == "Provider API keys")
        assert provider_check.ok is False

    def test_full_healthy_config(self, tmp_path):
        cfg_path = tmp_path / "config.json"
        config = {
            CONFIG_VERSION_KEY: CURRENT_VERSION,
            "providers": {"openai": {"apiKey": "${OPENAI_KEY}"}},
            "agents": {"defaults": {"workspace": str(tmp_path / "workspace")}},
        }
        cfg_path.write_text(json.dumps(config), encoding="utf-8")
        report = run_doctor(cfg_path, data_dir=tmp_path)
        assert report.checks[0].ok is True  # Config file
        assert report.checks[1].ok is True  # Config version
        assert report.checks[2].ok is True  # Providers

    def test_repair_applies_migrations(self, tmp_path):
        cfg_path = tmp_path / "config.json"
        config = {"openai_api_key": "sk-test-key-value-here"}
        cfg_path.write_text(json.dumps(config), encoding="utf-8")

        report = run_doctor(cfg_path, data_dir=tmp_path, repair=True)
        assert len(report.migrations_applied) > 0
        assert "add-config-version" in report.migrations_applied

        # Check that the file was updated
        saved = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert saved[CONFIG_VERSION_KEY] == CURRENT_VERSION

        # Check that a backup was created
        backup = cfg_path.with_suffix(".json.bak")
        assert backup.exists()

    def test_repair_creates_backup_only_once(self, tmp_path):
        cfg_path = tmp_path / "config.json"
        backup_path = cfg_path.with_suffix(".json.bak")

        # First run: create backup
        config = {"openai_api_key": "sk-first-key-value-here"}
        cfg_path.write_text(json.dumps(config), encoding="utf-8")
        run_doctor(cfg_path, data_dir=tmp_path, repair=True)
        assert backup_path.exists()
        first_backup = backup_path.read_text(encoding="utf-8")

        # Second run: reset config, repair again -- backup should NOT be overwritten
        config2 = {"anthropic_api_key": "sk-second-key-value-here"}
        cfg_path.write_text(json.dumps(config2), encoding="utf-8")
        run_doctor(cfg_path, data_dir=tmp_path, repair=True)
        assert backup_path.read_text(encoding="utf-8") == first_backup

    def test_security_warnings_in_report(self, tmp_path):
        cfg_path = tmp_path / "config.json"
        config = {
            CONFIG_VERSION_KEY: CURRENT_VERSION,
            "providers": {"openai": {"apiKey": "sk-this-is-a-long-plaintext-key"}},
            "channels": {"telegram": {"allowFrom": ["*"]}},
        }
        cfg_path.write_text(json.dumps(config), encoding="utf-8")
        report = run_doctor(cfg_path, data_dir=tmp_path)
        assert len(report.warnings) == 2
