"""Public API for the message bus package."""

from ultrabot.bus.events import InboundMessage, OutboundMessage
from ultrabot.bus.queue import MessageBus

__all__ = [
    "InboundMessage",
    "MessageBus",
    "OutboundMessage",
]
