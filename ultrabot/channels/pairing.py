"""DM pairing system -- secure onboarding for unknown senders.

Generates pairing codes for unknown senders so the bot owner can
approve them before the bot responds to their messages.
"""
from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum
from typing import Any

from loguru import logger


class PairingPolicy(str, Enum):
    """DM policy for handling unknown senders."""
    CLOSED = "closed"     # Reject all unknown senders
    PAIRING = "pairing"   # Send pairing code, require approval
    OPEN = "open"         # Accept all senders


@dataclass
class PairingRequest:
    """A pending pairing request from an unknown sender."""
    sender_id: str
    channel: str
    code: str
    created_at: float = field(default_factory=time.time)
    display_name: str = ""


class PairingManager:
    """Manages DM pairing for unknown senders.

    Parameters:
        data_dir: Directory for persisting approved senders.
        default_policy: Default pairing policy.
        code_length: Length of generated pairing codes.
        code_ttl: Time-to-live for pairing codes in seconds.
    """

    def __init__(
        self,
        data_dir: Path,
        default_policy: PairingPolicy = PairingPolicy.PAIRING,
        code_length: int = 6,
        code_ttl: int = 300,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.default_policy = default_policy
        self.code_length = code_length
        self.code_ttl = code_ttl

        self.data_dir.mkdir(parents=True, exist_ok=True)

        # In-memory state
        self._approved: dict[str, set[str]] = {}  # channel -> set of sender_ids
        self._pending: dict[str, PairingRequest] = {}  # code -> request
        self._channel_policies: dict[str, PairingPolicy] = {}

        self._load_approved()
        logger.info("PairingManager initialised (policy={}, data_dir={})",
                     default_policy.value, data_dir)

    def get_policy(self, channel: str) -> PairingPolicy:
        """Get the pairing policy for a channel."""
        return self._channel_policies.get(channel, self.default_policy)

    def set_policy(self, channel: str, policy: PairingPolicy) -> None:
        """Set the pairing policy for a channel."""
        self._channel_policies[channel] = policy

    def is_approved(self, channel: str, sender_id: str) -> bool:
        """Check if a sender is approved on a channel."""
        policy = self.get_policy(channel)
        if policy == PairingPolicy.OPEN:
            return True
        if policy == PairingPolicy.CLOSED:
            return sender_id in self._approved.get(channel, set())
        # PAIRING policy
        return sender_id in self._approved.get(channel, set())

    def check_sender(self, channel: str, sender_id: str) -> tuple[bool, str | None]:
        """Check a sender and return (approved, pairing_code_or_none).

        If not approved and policy is PAIRING, generates a new code.
        """
        if self.is_approved(channel, sender_id):
            return True, None

        policy = self.get_policy(channel)

        if policy == PairingPolicy.CLOSED:
            return False, None

        if policy == PairingPolicy.OPEN:
            self.approve(channel, sender_id)
            return True, None

        # PAIRING: generate code
        code = self._generate_code(channel, sender_id)
        return False, code

    def approve(self, channel: str, sender_id: str) -> None:
        """Approve a sender on a channel."""
        if channel not in self._approved:
            self._approved[channel] = set()
        self._approved[channel].add(sender_id)
        self._save_approved()

        # Clean up pending requests
        to_remove = [
            code for code, req in self._pending.items()
            if req.channel == channel and req.sender_id == sender_id
        ]
        for code in to_remove:
            del self._pending[code]

        logger.info("Approved sender {} on channel {}", sender_id, channel)

    def approve_by_code(self, code: str) -> PairingRequest | None:
        """Approve a sender using their pairing code. Returns the request or None."""
        request = self._pending.get(code)
        if request is None:
            return None

        # Check TTL
        if time.time() - request.created_at > self.code_ttl:
            del self._pending[code]
            return None

        self.approve(request.channel, request.sender_id)
        return request

    def revoke(self, channel: str, sender_id: str) -> bool:
        """Revoke approval for a sender. Returns True if was approved."""
        approved = self._approved.get(channel, set())
        if sender_id in approved:
            approved.discard(sender_id)
            self._save_approved()
            logger.info("Revoked sender {} on channel {}", sender_id, channel)
            return True
        return False

    def list_approved(self, channel: str | None = None) -> dict[str, list[str]]:
        """List approved senders, optionally filtered by channel."""
        if channel:
            return {channel: sorted(self._approved.get(channel, set()))}
        return {ch: sorted(senders) for ch, senders in self._approved.items()}

    def list_pending(self) -> list[dict[str, Any]]:
        """List pending pairing requests."""
        now = time.time()
        result = []
        expired = []
        for code, req in self._pending.items():
            if now - req.created_at > self.code_ttl:
                expired.append(code)
                continue
            result.append({
                "code": code,
                "sender_id": req.sender_id,
                "channel": req.channel,
                "display_name": req.display_name,
                "age_seconds": int(now - req.created_at),
            })
        for code in expired:
            del self._pending[code]
        return result

    def _generate_code(self, channel: str, sender_id: str) -> str:
        """Generate a pairing code for an unknown sender."""
        # Check for existing code
        for code, req in self._pending.items():
            if req.channel == channel and req.sender_id == sender_id:
                if time.time() - req.created_at <= self.code_ttl:
                    return code

        code = secrets.token_hex(self.code_length // 2).upper()[:self.code_length]
        self._pending[code] = PairingRequest(
            sender_id=sender_id,
            channel=channel,
            code=code,
        )
        return code

    def _save_approved(self) -> None:
        path = self.data_dir / "approved_senders.json"
        data = {ch: sorted(senders) for ch, senders in self._approved.items()}
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_approved(self) -> None:
        path = self.data_dir / "approved_senders.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._approved = {ch: set(senders) for ch, senders in data.items()}
        except Exception:
            logger.exception("Failed to load approved senders")
