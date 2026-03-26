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
    from croniter import croniter

    _CRONITER_AVAILABLE = True
except ImportError:
    _CRONITER_AVAILABLE = False

if TYPE_CHECKING:
    from ultrabot.bus.queue import MessageBus


def _require_croniter() -> None:
    if not _CRONITER_AVAILABLE:
        raise ImportError(
            "croniter is required for cron scheduling. "
            "Install it with:  pip install croniter"
        )


@dataclass
class CronJob:
    """Represents a single scheduled cron job."""

    name: str
    schedule: str  # standard cron expression (e.g. "0 9 * * *")
    message: str  # text to publish on the bus when the job fires
    channel: str  # target channel name
    chat_id: str  # target chat/channel id
    enabled: bool = True
    _next_run: datetime | None = field(default=None, repr=False, compare=False)

    def compute_next(self, now: datetime | None = None) -> datetime:
        """Compute and cache the next run time from *now*."""
        _require_croniter()
        now = now or datetime.now(timezone.utc)
        cron = croniter(self.schedule, now)
        self._next_run = cron.get_next(datetime).replace(tzinfo=timezone.utc)
        return self._next_run


class CronScheduler:
    """Loads cron jobs from JSON files and fires them on schedule.

    Each ``*.json`` file in *cron_dir* describes a single :class:`CronJob`.
    The scheduler checks once per second whether any job is due and, if so,
    publishes the job's message to the :class:`MessageBus`.

    Parameters
    ----------
    cron_dir:
        Directory containing cron job JSON files.
    bus:
        The message bus used to publish triggered messages.
    """

    def __init__(self, cron_dir: Path, bus: "MessageBus") -> None:
        self._cron_dir = cron_dir
        self._bus = bus
        self._jobs: dict[str, CronJob] = {}
        self._task: asyncio.Task[None] | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Job management
    # ------------------------------------------------------------------

    def load_jobs(self) -> None:
        """Scan *cron_dir* for ``*.json`` files and load each as a CronJob."""
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
        """Register *job* and persist it to disk."""
        job.compute_next()
        self._jobs[job.name] = job
        self._persist_job(job)
        logger.info("Cron job '{}' added (schedule={})", job.name, job.schedule)

    def remove_job(self, name: str) -> None:
        """Remove the job with *name* from the scheduler and disk."""
        if name in self._jobs:
            del self._jobs[name]
        path = self._cron_dir / f"{name}.json"
        if path.exists():
            path.unlink()
        logger.info("Cron job '{}' removed", name)

    def _persist_job(self, job: CronJob) -> None:
        """Write *job* to a JSON file in the cron directory."""
        path = self._cron_dir / f"{job.name}.json"
        data = {
            "name": job.name,
            "schedule": job.schedule,
            "message": job.message,
            "channel": job.channel,
            "chat_id": job.chat_id,
            "enabled": job.enabled,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

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
