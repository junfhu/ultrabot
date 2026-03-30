"""Tests for ultrabot.providers.auth_rotation module."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ultrabot.providers.auth_rotation import (
    AuthProfile,
    AuthRotator,
    CredentialState,
    execute_with_rotation,
)


# ---------------------------------------------------------------------------
# AuthProfile – state transitions
# ---------------------------------------------------------------------------


class TestAuthProfile:
    """Unit tests for AuthProfile dataclass."""

    def test_initial_state_is_active(self) -> None:
        p = AuthProfile(key="sk-abc")
        assert p.state == CredentialState.ACTIVE
        assert p.is_available is True
        assert p.consecutive_failures == 0
        assert p.total_uses == 0

    def test_record_success(self) -> None:
        p = AuthProfile(key="sk-abc", consecutive_failures=2, state=CredentialState.COOLDOWN)
        p.record_success()
        assert p.state == CredentialState.ACTIVE
        assert p.consecutive_failures == 0
        assert p.total_uses == 1

    def test_record_success_increments_total_uses(self) -> None:
        p = AuthProfile(key="sk-abc")
        p.record_success()
        p.record_success()
        p.record_success()
        assert p.total_uses == 3

    def test_single_failure_enters_cooldown(self) -> None:
        p = AuthProfile(key="sk-abc")
        p.record_failure(cooldown_seconds=30.0)
        assert p.state == CredentialState.COOLDOWN
        assert p.consecutive_failures == 1

    def test_three_failures_enters_failed(self) -> None:
        p = AuthProfile(key="sk-abc")
        p.record_failure(cooldown_seconds=10.0)
        assert p.state == CredentialState.COOLDOWN

        p.record_failure(cooldown_seconds=10.0)
        assert p.state == CredentialState.COOLDOWN
        assert p.consecutive_failures == 2

        p.record_failure(cooldown_seconds=10.0)
        assert p.state == CredentialState.FAILED
        assert p.consecutive_failures == 3

    def test_failed_is_not_available(self) -> None:
        p = AuthProfile(key="sk-abc", state=CredentialState.FAILED)
        assert p.is_available is False

    def test_cooldown_not_available_until_elapsed(self) -> None:
        """Profile in COOLDOWN is unavailable until cooldown_until is reached."""
        import time

        now = time.monotonic()
        p = AuthProfile(
            key="sk-abc",
            state=CredentialState.COOLDOWN,
            cooldown_until=now + 9999,  # far in the future
        )
        assert p.is_available is False

    def test_cooldown_becomes_available_after_elapsed(self) -> None:
        """Profile in COOLDOWN becomes available once cooldown_until has passed."""
        import time

        now = time.monotonic()
        p = AuthProfile(
            key="sk-abc",
            state=CredentialState.COOLDOWN,
            cooldown_until=now - 1,  # already in the past
        )
        assert p.is_available is True

    def test_is_available_with_mocked_time(self) -> None:
        """Use time.monotonic patching for deterministic cooldown testing."""
        p = AuthProfile(
            key="sk-abc",
            state=CredentialState.COOLDOWN,
            cooldown_until=100.0,
        )

        with patch("ultrabot.providers.auth_rotation.time") as mock_time:
            mock_time.monotonic.return_value = 50.0  # before cooldown_until
            assert p.is_available is False

            mock_time.monotonic.return_value = 100.0  # exactly at cooldown_until
            assert p.is_available is True

            mock_time.monotonic.return_value = 200.0  # after cooldown_until
            assert p.is_available is True

    def test_reset(self) -> None:
        p = AuthProfile(
            key="sk-abc",
            state=CredentialState.FAILED,
            consecutive_failures=5,
            cooldown_until=999.9,
        )
        p.reset()
        assert p.state == CredentialState.ACTIVE
        assert p.consecutive_failures == 0
        assert p.cooldown_until == 0.0


# ---------------------------------------------------------------------------
# AuthRotator – construction & deduplication
# ---------------------------------------------------------------------------


class TestAuthRotatorConstruction:
    """Tests for AuthRotator initialization."""

    def test_deduplicates_keys(self) -> None:
        r = AuthRotator(keys=["k1", "k2", "k1", "k3", "k2"])
        assert r.profile_count == 3

    def test_removes_empty_keys(self) -> None:
        r = AuthRotator(keys=["k1", "", "k2", ""])
        assert r.profile_count == 2

    def test_empty_keys_list(self) -> None:
        r = AuthRotator(keys=[])
        assert r.profile_count == 0
        assert r.available_count == 0
        assert r.get_next_key() is None

    def test_single_key(self) -> None:
        r = AuthRotator(keys=["only-one"])
        assert r.profile_count == 1
        assert r.get_next_key() == "only-one"
        assert r.get_next_key() == "only-one"  # wraps around


# ---------------------------------------------------------------------------
# AuthRotator – round-robin & failover
# ---------------------------------------------------------------------------


class TestAuthRotatorRoundRobin:
    """Tests for round-robin key selection and failover."""

    def test_round_robin_cycling(self) -> None:
        r = AuthRotator(keys=["k1", "k2", "k3"])
        assert r.get_next_key() == "k1"
        assert r.get_next_key() == "k2"
        assert r.get_next_key() == "k3"
        assert r.get_next_key() == "k1"  # wraps

    def test_skips_cooldown_key(self) -> None:
        """When a key is in cooldown (not yet elapsed), round-robin skips it."""
        r = AuthRotator(keys=["k1", "k2", "k3"], cooldown_seconds=9999.0)

        # Fail k1 to put it in cooldown
        r.record_failure("k1")

        # Round robin starts at index 1 (since k1 was just fetched implicitly),
        # but let's reset and verify skipping
        r._current_index = 0
        key = r.get_next_key()
        # k1 is in cooldown (9999s), so should skip to k2
        assert key == "k2"

    def test_returns_none_when_all_in_cooldown(self) -> None:
        """When all keys are in cooldown and none elapsed, returns None only
        if none are FAILED (last-resort recovery picks up FAILED keys)."""
        r = AuthRotator(keys=["k1", "k2"], cooldown_seconds=9999.0)

        # Put both in cooldown (1 failure each = COOLDOWN, not FAILED)
        r.record_failure("k1")
        r.record_failure("k2")

        # Both in COOLDOWN with long timeout -> not available
        # get_next_key will try round robin, find nothing, then try FAILED recovery
        # but neither is FAILED, so should return None
        assert r.get_next_key() is None

    def test_recovery_from_failed_state(self) -> None:
        """When all keys are exhausted, FAILED keys are reset as last resort."""
        r = AuthRotator(keys=["k1", "k2"], cooldown_seconds=9999.0)

        # Push k1 all the way to FAILED (3 failures)
        for _ in range(3):
            r.record_failure("k1")

        # Push k2 to COOLDOWN (1 failure, long timeout)
        r.record_failure("k2")

        # k1 is FAILED, k2 is in COOLDOWN (not elapsed)
        # get_next_key should reset k1 as last resort
        key = r.get_next_key()
        assert key == "k1"

    def test_available_count(self) -> None:
        r = AuthRotator(keys=["k1", "k2", "k3"], cooldown_seconds=9999.0)
        assert r.available_count == 3

        r.record_failure("k1")  # -> COOLDOWN
        assert r.available_count == 2

        for _ in range(3):
            r.record_failure("k2")  # -> FAILED
        assert r.available_count == 1


# ---------------------------------------------------------------------------
# AuthRotator – record_success / record_failure
# ---------------------------------------------------------------------------


class TestAuthRotatorRecording:
    """Tests for record_success and record_failure methods."""

    def test_record_success_resets_profile(self) -> None:
        r = AuthRotator(keys=["k1", "k2"])
        r.record_failure("k1")  # puts k1 in COOLDOWN
        r.record_success("k1")  # should reset it

        status = r.get_status()
        k1_status = [s for s in status if s["state"] == "active"]
        assert len(k1_status) == 2  # both should be active

    def test_record_failure_unknown_key_is_noop(self) -> None:
        r = AuthRotator(keys=["k1"])
        # Should not raise
        r.record_failure("nonexistent")
        r.record_success("nonexistent")
        assert r.profile_count == 1

    def test_get_status_masks_keys(self) -> None:
        r = AuthRotator(keys=["sk-1234567890abcdef"])
        status = r.get_status()
        assert len(status) == 1
        # Key should be masked: first 4 + "..." + last 4
        assert status[0]["key"] == "sk-1...cdef"
        assert "1234567890" not in status[0]["key"]

    def test_get_status_short_key_fully_masked(self) -> None:
        r = AuthRotator(keys=["short"])
        status = r.get_status()
        assert status[0]["key"] == "****"

    def test_reset_all(self) -> None:
        r = AuthRotator(keys=["k1", "k2", "k3"], cooldown_seconds=9999.0)
        r.record_failure("k1")
        for _ in range(3):
            r.record_failure("k2")

        r.reset_all()
        assert r.available_count == 3
        for s in r.get_status():
            assert s["state"] == "active"
            assert s["consecutive_failures"] == 0


# ---------------------------------------------------------------------------
# execute_with_rotation – async integration
# ---------------------------------------------------------------------------


class TestExecuteWithRotation:
    """Tests for the execute_with_rotation async helper."""

    async def test_happy_path(self) -> None:
        """First key succeeds -- no rotation needed."""
        r = AuthRotator(keys=["k1", "k2"])
        calls: list[str] = []

        async def execute(key: str) -> str:
            calls.append(key)
            return f"result-{key}"

        result = await execute_with_rotation(r, execute)
        assert result == "result-k1"
        assert calls == ["k1"]

    async def test_rate_limit_rotates_to_next_key(self) -> None:
        """Rate-limit on first key triggers rotation to second key."""
        r = AuthRotator(keys=["k1", "k2", "k3"])
        calls: list[str] = []

        class RateLimitError(Exception):
            status_code = 429

        async def execute(key: str) -> str:
            calls.append(key)
            if key == "k1":
                raise RateLimitError("rate limited")
            return f"result-{key}"

        result = await execute_with_rotation(r, execute)
        assert result == "result-k2"
        assert calls == ["k1", "k2"]

    async def test_non_rate_limit_raises_immediately(self) -> None:
        """Non-rate-limit errors are not caught -- they propagate immediately."""
        r = AuthRotator(keys=["k1", "k2"])
        calls: list[str] = []

        async def execute(key: str) -> str:
            calls.append(key)
            raise ValueError("bad request")

        with pytest.raises(ValueError, match="bad request"):
            await execute_with_rotation(r, execute)

        # Should NOT have tried k2
        assert calls == ["k1"]

    async def test_all_keys_rate_limited(self) -> None:
        """When every key is rate-limited, raises RuntimeError."""
        r = AuthRotator(keys=["k1", "k2"])
        calls: list[str] = []

        async def execute(key: str) -> str:
            calls.append(key)
            raise Exception("rate limit exceeded")

        with pytest.raises(RuntimeError, match="All 2 API keys exhausted"):
            await execute_with_rotation(r, execute)

        assert len(calls) == 2

    async def test_custom_is_rate_limit_predicate(self) -> None:
        """Custom is_rate_limit callable is respected."""
        r = AuthRotator(keys=["k1", "k2"])
        calls: list[str] = []

        class CustomError(Exception):
            pass

        async def execute(key: str) -> str:
            calls.append(key)
            if key == "k1":
                raise CustomError("custom throttle")
            return f"result-{key}"

        def custom_check(exc: Exception) -> bool:
            return isinstance(exc, CustomError)

        result = await execute_with_rotation(r, execute, is_rate_limit=custom_check)
        assert result == "result-k2"
        assert calls == ["k1", "k2"]

    async def test_rotate_through_multiple_failures(self) -> None:
        """Rate-limit on k1 and k2, success on k3."""
        r = AuthRotator(keys=["k1", "k2", "k3"])
        calls: list[str] = []

        async def execute(key: str) -> str:
            calls.append(key)
            if key in ("k1", "k2"):
                raise Exception("too many requests")
            return f"result-{key}"

        result = await execute_with_rotation(r, execute)
        assert result == "result-k3"
        assert calls == ["k1", "k2", "k3"]

    async def test_empty_rotator_raises(self) -> None:
        """An empty rotator raises RuntimeError immediately."""
        r = AuthRotator(keys=[])

        async def execute(key: str) -> str:
            return "unreachable"

        with pytest.raises(RuntimeError, match="All 0 API keys exhausted"):
            await execute_with_rotation(r, execute)

    async def test_success_resets_failure_count(self) -> None:
        """After a successful rotation, the winning key has 0 failures."""
        r = AuthRotator(keys=["k1", "k2"])

        async def execute(key: str) -> str:
            if key == "k1":
                raise Exception("rate limit")
            return "ok"

        await execute_with_rotation(r, execute)

        status = r.get_status()
        k2_status = [s for s in status if s["state"] == "active" and s["total_uses"] == 1]
        assert len(k2_status) == 1


# ---------------------------------------------------------------------------
# Default rate-limit detection heuristics
# ---------------------------------------------------------------------------


class TestDefaultRateLimitDetection:
    """Test the built-in rate-limit detection used by execute_with_rotation."""

    async def _check_detected(self, exc: Exception, expected: bool) -> None:
        """Helper: check if exc is detected as a rate-limit error."""
        r = AuthRotator(keys=["k1", "k2"])
        calls: list[str] = []

        async def execute(key: str) -> str:
            calls.append(key)
            if key == "k1":
                raise exc
            return "ok"

        if expected:
            # Should rotate to k2
            result = await execute_with_rotation(r, execute)
            assert result == "ok"
            assert len(calls) == 2
        else:
            # Should raise immediately
            with pytest.raises(type(exc)):
                await execute_with_rotation(r, execute)
            assert len(calls) == 1

    async def test_status_code_429(self) -> None:
        exc = Exception("error")
        exc.status_code = 429  # type: ignore[attr-defined]
        await self._check_detected(exc, expected=True)

    async def test_status_attribute_429(self) -> None:
        exc = Exception("error")
        exc.status = 429  # type: ignore[attr-defined]
        await self._check_detected(exc, expected=True)

    async def test_rate_limit_in_message(self) -> None:
        await self._check_detected(Exception("Rate limit exceeded"), expected=True)

    async def test_rate_limit_underscore_in_message(self) -> None:
        await self._check_detected(Exception("rate_limit_error"), expected=True)

    async def test_too_many_requests_in_message(self) -> None:
        await self._check_detected(Exception("Too Many Requests"), expected=True)

    async def test_unrelated_error_not_detected(self) -> None:
        await self._check_detected(ValueError("invalid input"), expected=False)

    async def test_status_500_not_detected(self) -> None:
        exc = Exception("server error")
        exc.status_code = 500  # type: ignore[attr-defined]
        await self._check_detected(exc, expected=False)
