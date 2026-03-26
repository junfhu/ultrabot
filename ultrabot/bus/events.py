"""Dataclass definitions for inbound and outbound messages on the bus."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class InboundMessage:
    """A message received from any channel heading into the processing pipeline.

    Attributes:
        channel: Originating channel identifier (e.g. "telegram", "discord").
        sender_id: Unique identifier of the message sender.
        chat_id: Conversation / chat identifier within the channel.
        content: Raw text content of the message.
        timestamp: UTC timestamp of when the message was created.
        media: List of media URLs or file references attached to the message.
        metadata: Arbitrary key-value pairs carrying channel-specific extras.
        session_key_override: If set, forces a specific session key instead of
            the default ``{channel}:{chat_id}`` derivation.
        priority: Priority level.  0 is normal; higher integers are processed
            first.
    """

    channel: str
    sender_id: str
    chat_id: str
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    media: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    session_key_override: str | None = None
    priority: int = 0

    @property
    def session_key(self) -> str:
        """Return the session key for this message.

        Uses ``session_key_override`` when provided; otherwise falls back to
        the canonical ``{channel}:{chat_id}`` format.
        """
        if self.session_key_override is not None:
            return self.session_key_override
        return f"{self.channel}:{self.chat_id}"

    def __lt__(self, other: InboundMessage) -> bool:
        """Compare by *descending* priority so higher values are dequeued first.

        ``asyncio.PriorityQueue`` is a min-heap, so we invert the comparison:
        a message with a *higher* priority integer compares as *less than* one
        with a lower priority, causing it to be popped sooner.
        """
        if not isinstance(other, InboundMessage):
            return NotImplemented
        return self.priority > other.priority


@dataclass
class OutboundMessage:
    """A message to be sent out through a channel adapter.

    Attributes:
        channel: Target channel identifier.
        chat_id: Target conversation / chat identifier.
        content: Text content to send.
        reply_to: Optional message ID this is a reply to.
        media: List of media URLs or file references to attach.
        metadata: Arbitrary key-value pairs for channel-specific options.
    """

    channel: str
    chat_id: str
    content: str
    reply_to: str | None = None
    media: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
