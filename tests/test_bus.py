"""Tests for ultrabot.bus -- event dataclasses and the async MessageBus."""

from __future__ import annotations

import asyncio

import pytest

from ultrabot.bus.events import InboundMessage, OutboundMessage
from ultrabot.bus.queue import MessageBus


# ===================================================================
# InboundMessage / OutboundMessage
# ===================================================================


def test_inbound_message_session_key():
    """InboundMessage.session_key should default to '{channel}:{chat_id}'
    and respect session_key_override when set."""
    msg = InboundMessage(
        channel="telegram",
        sender_id="user1",
        chat_id="12345",
        content="hello",
    )
    assert msg.session_key == "telegram:12345"

    # Override
    msg_override = InboundMessage(
        channel="telegram",
        sender_id="user1",
        chat_id="12345",
        content="hello",
        session_key_override="custom-key",
    )
    assert msg_override.session_key == "custom-key"


def test_inbound_message_priority():
    """Higher-priority InboundMessages should compare as *less than* lower ones
    (for min-heap behaviour in asyncio.PriorityQueue)."""
    low = InboundMessage(channel="t", sender_id="u", chat_id="c", content="lo", priority=0)
    high = InboundMessage(channel="t", sender_id="u", chat_id="c", content="hi", priority=10)

    # high < low because we want high-priority dequeued first from a min-heap.
    assert high < low
    assert not (low < high)


def test_outbound_message_creation():
    """OutboundMessage should store all its fields correctly."""
    msg = OutboundMessage(
        channel="discord",
        chat_id="ch-001",
        content="Reply text",
        reply_to="msg-42",
        media=["https://example.com/img.png"],
        metadata={"foo": "bar"},
    )
    assert msg.channel == "discord"
    assert msg.chat_id == "ch-001"
    assert msg.content == "Reply text"
    assert msg.reply_to == "msg-42"
    assert msg.media == ["https://example.com/img.png"]
    assert msg.metadata == {"foo": "bar"}


# ===================================================================
# MessageBus -- async tests
# ===================================================================


@pytest.mark.asyncio
async def test_message_bus_publish_subscribe():
    """Publishing an inbound message and subscribing to outbound messages
    should work end-to-end."""
    bus = MessageBus(max_retries=1)
    received: list[OutboundMessage] = []

    async def handler(msg: InboundMessage) -> OutboundMessage | None:
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=f"echo: {msg.content}",
        )

    async def subscriber(msg: OutboundMessage) -> None:
        received.append(msg)

    bus.set_inbound_handler(handler)
    bus.subscribe(subscriber)

    # Start the dispatch loop in the background.
    dispatch_task = asyncio.create_task(bus.dispatch_inbound())

    # Publish a test message.
    await bus.publish(
        InboundMessage(
            channel="test",
            sender_id="s1",
            chat_id="c1",
            content="ping",
        )
    )

    # Wait for processing.
    await asyncio.sleep(0.2)
    bus.shutdown()
    await dispatch_task

    assert len(received) == 1
    assert received[0].content == "echo: ping"
    assert received[0].channel == "test"


@pytest.mark.asyncio
async def test_message_bus_dead_letter_queue():
    """Messages that fail all retry attempts should land in the dead-letter
    queue."""
    bus = MessageBus(max_retries=2)

    async def failing_handler(msg: InboundMessage) -> OutboundMessage | None:
        raise RuntimeError("intentional failure")

    bus.set_inbound_handler(failing_handler)

    dispatch_task = asyncio.create_task(bus.dispatch_inbound())

    await bus.publish(
        InboundMessage(
            channel="test",
            sender_id="s1",
            chat_id="c1",
            content="will fail",
        )
    )

    # Give time for retries to exhaust.
    await asyncio.sleep(0.5)
    bus.shutdown()
    await dispatch_task

    assert bus.dead_letter_count == 1
    assert bus.dead_letter_queue[0].content == "will fail"
