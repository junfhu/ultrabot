# Session 20: Cron Scheduler — Automated Tasks

**Goal:** Build a time-based task scheduler that fires messages on cron schedules via the message bus.

**What you'll learn:**
- `CronJob` dataclass with standard cron expressions
- `CronScheduler` with per-second tick loop
- JSON-based job persistence to disk
- Integration with `croniter` for next-run computation
- Publishing scheduled messages through the `MessageBus`

**New files:**
- `ultrabot/cron/__init__.py` — package exports
- `ultrabot/cron/scheduler.py` — cron job management and scheduling loop

### Step 1: The CronJob Dataclass

Each job has a cron expression, a message to send, and a target channel.

```python
# ultrabot/cron/scheduler.py
"""Cron scheduler -- time-based automated message dispatch."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

try:
    from croniter import croniter          # pip install croniter
    _CRONITER_AVAILABLE = True
except ImportError:
    _CRONITER_AVAILABLE = False

if TYPE_CHECKING:
    from ultrabot.bus.queue import MessageBus


def _require_croniter() -> None:
    """Guard: raise helpful error if croniter not installed."""
    if not _CRONITER_AVAILABLE:
        raise ImportError(
            "croniter is required for cron scheduling. "
            "Install it with:  pip install croniter"
        )


@dataclass
class CronJob:
    """Represents a single scheduled cron job.

    Attributes:
        name: Unique job identifier.
        schedule: Standard cron expression (e.g. "0 9 * * *" = daily 9am).
        message: Text to publish on the bus when the job fires.
        channel: Target channel name (e.g. "telegram", "discord").
        chat_id: Target chat/channel ID.
        enabled: Whether the job is active.
    """
    name: str
    schedule: str           # "0 9 * * *"  = every day at 09:00 UTC
    message: str            # text to send when job fires
    channel: str            # target channel
    chat_id: str            # target chat ID
    enabled: bool = True
    _next_run: datetime | None = field(default=None, repr=False, compare=False)

    def compute_next(self, now: datetime | None = None) -> datetime:
        """Compute and cache the next run time from *now*."""
        _require_croniter()
        now = now or datetime.now(timezone.utc)
        cron = croniter(self.schedule, now)
        self._next_run = cron.get_next(datetime).replace(tzinfo=timezone.utc)
        return self._next_run
```

### Step 2: The CronScheduler

The scheduler loads jobs from JSON files, runs a per-second check loop, and
publishes messages to the bus when jobs are due.

```python
class CronScheduler:
    """Loads cron jobs from JSON files and fires them on schedule.

    Each ``*.json`` file in *cron_dir* describes a single CronJob.
    The scheduler checks once per second whether any job is due and,
    if so, publishes the job's message to the MessageBus.
    """

    def __init__(self, cron_dir: Path, bus: "MessageBus") -> None:
        self._cron_dir = cron_dir
        self._bus = bus
        self._jobs: dict[str, CronJob] = {}
        self._task: asyncio.Task[None] | None = None
        self._running = False

    # -- Job management ---------------------------------------------------

    def load_jobs(self) -> None:
        """Scan cron_dir for *.json files and load each as a CronJob."""
        self._cron_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for path in sorted(self._cron_dir.glob("*.json")):
            try:
                job = self._load_job_file(path)
                self._jobs[job.name] = job
                count += 1
            except Exception:
                logger.exception("Failed to load cron job from {}", path)
        logger.info("Loaded {} cron job(s) from {}", count, self._cron_dir)

    @staticmethod
    def _load_job_file(path: Path) -> CronJob:
        data = json.loads(path.read_text(encoding="utf-8"))
        job = CronJob(
            name=data["name"],
            schedule=data["schedule"],
            message=data["message"],
            channel=data["channel"],
            chat_id=str(data["chat_id"]),
            enabled=data.get("enabled", True),
        )
        job.compute_next()
        return job

    def add_job(self, job: CronJob) -> None:
        """Register a job and persist it to disk."""
        job.compute_next()
        self._jobs[job.name] = job
        self._persist_job(job)
        logger.info("Cron job '{}' added (schedule={})", job.name, job.schedule)

    def remove_job(self, name: str) -> None:
        """Remove job from scheduler and disk."""
        if name in self._jobs:
            del self._jobs[name]
        path = self._cron_dir / f"{name}.json"
        if path.exists():
            path.unlink()
        logger.info("Cron job '{}' removed", name)

    def _persist_job(self, job: CronJob) -> None:
        path = self._cron_dir / f"{job.name}.json"
        data = {
            "name": job.name, "schedule": job.schedule, "message": job.message,
            "channel": job.channel, "chat_id": job.chat_id, "enabled": job.enabled,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # -- Lifecycle --------------------------------------------------------

    async def start(self) -> None:
        """Start the background scheduling loop."""
        if not self._jobs:
            logger.debug("No cron jobs loaded -- scheduler idle")
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="cron-scheduler")
        logger.info("Cron scheduler started ({} job(s))", len(self._jobs))

    async def stop(self) -> None:
        """Cancel the background task."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Cron scheduler stopped")

    # -- Internal loop ----------------------------------------------------

    async def _loop(self) -> None:
        """Check every second if any job is due."""
        while self._running:
            now = datetime.now(timezone.utc)
            for job in list(self._jobs.values()):
                if not job.enabled:
                    continue
                if job._next_run is None:
                    job.compute_next(now)
                    continue
                if now >= job._next_run:
                    await self._fire(job)
                    job.compute_next(now)
            await asyncio.sleep(1)

    async def _fire(self, job: CronJob) -> None:
        """Publish the job's message to the bus."""
        from ultrabot.bus.events import InboundMessage

        logger.info("Cron job '{}' fired", job.name)
        msg = InboundMessage(
            channel=job.channel,
            sender_id="cron",
            chat_id=job.chat_id,
            content=job.message,
            metadata={"cron_job": job.name},
        )
        await self._bus.publish(msg)
```

### Tests

```python
# tests/test_cron_scheduler.py
"""Tests for the cron scheduler."""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from ultrabot.cron.scheduler import CronJob, CronScheduler


class TestCronJob:
    def test_create_job(self):
        job = CronJob(
            name="daily-summary",
            schedule="0 9 * * *",
            message="Generate daily summary",
            channel="telegram",
            chat_id="123456",
        )
        assert job.name == "daily-summary"
        assert job.enabled is True

    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("croniter"),
        reason="croniter not installed",
    )
    def test_compute_next(self):
        job = CronJob(
            name="test", schedule="0 * * * *",  # every hour
            message="ping", channel="test", chat_id="1",
        )
        now = datetime(2025, 1, 15, 10, 30, tzinfo=timezone.utc)
        next_run = job.compute_next(now)
        assert next_run.hour == 11
        assert next_run.minute == 0


class TestCronScheduler:
    def test_load_jobs_from_dir(self, tmp_path):
        # Write a job JSON file
        job_data = {
            "name": "test-job",
            "schedule": "*/5 * * * *",
            "message": "Hello from cron",
            "channel": "telegram",
            "chat_id": "12345",
            "enabled": True,
        }
        (tmp_path / "test-job.json").write_text(json.dumps(job_data))

        bus = MagicMock()
        scheduler = CronScheduler(cron_dir=tmp_path, bus=bus)
        scheduler.load_jobs()
        assert "test-job" in scheduler._jobs

    def test_add_and_remove_job(self, tmp_path):
        bus = MagicMock()
        scheduler = CronScheduler(cron_dir=tmp_path, bus=bus)

        job = CronJob(
            name="new-job", schedule="0 12 * * *",
            message="Noon check", channel="slack", chat_id="C123",
        )
        scheduler.add_job(job)
        assert "new-job" in scheduler._jobs
        assert (tmp_path / "new-job.json").exists()

        scheduler.remove_job("new-job")
        assert "new-job" not in scheduler._jobs
        assert not (tmp_path / "new-job.json").exists()

    @pytest.mark.asyncio
    async def test_fire_publishes_to_bus(self, tmp_path):
        bus = AsyncMock()
        scheduler = CronScheduler(cron_dir=tmp_path, bus=bus)

        job = CronJob(
            name="fire-test", schedule="* * * * *",
            message="Test fire", channel="test", chat_id="1",
        )
        await scheduler._fire(job)
        bus.publish.assert_called_once()
        msg = bus.publish.call_args[0][0]
        assert msg.content == "Test fire"
        assert msg.metadata == {"cron_job": "fire-test"}

    @pytest.mark.asyncio
    async def test_start_stop(self, tmp_path):
        bus = AsyncMock()
        scheduler = CronScheduler(cron_dir=tmp_path, bus=bus)
        await scheduler.start()
        assert scheduler._running is True
        await scheduler.stop()
        assert scheduler._running is False
```

### Checkpoint

```bash
python -c "
import json, tempfile
from pathlib import Path
from unittest.mock import MagicMock

from ultrabot.cron.scheduler import CronJob, CronScheduler

# Create a temp cron directory with a job
cron_dir = Path(tempfile.mkdtemp())
job = {
    'name': 'morning-greeting',
    'schedule': '0 8 * * *',
    'message': 'Good morning! Time for your daily briefing.',
    'channel': 'telegram',
    'chat_id': '123456',
}
(cron_dir / 'morning-greeting.json').write_text(json.dumps(job))

bus = MagicMock()
scheduler = CronScheduler(cron_dir=cron_dir, bus=bus)
scheduler.load_jobs()

for name, j in scheduler._jobs.items():
    print(f'Job: {name}')
    print(f'  Schedule: {j.schedule}')
    print(f'  Message: {j.message}')
    print(f'  Next run: {j._next_run}')
    print(f'  Enabled: {j.enabled}')
"
```

Expected:
```
Job: morning-greeting
  Schedule: 0 8 * * *
  Message: Good morning! Time for your daily briefing.
  Next run: 2025-XX-XX 08:00:00+00:00
  Enabled: True
```

### What we built

A cron scheduler that loads job definitions from JSON files, computes next-run
times using `croniter`, and publishes messages to the message bus on schedule.
Jobs persist to disk and survive restarts. The scheduler runs as an asyncio
background task checking once per second.

---
