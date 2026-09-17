from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from src.core.utils import utc_now
from src.storage.models import FollowUpTaskRecord
from src.storage.repository import Repository

LOGGER = logging.getLogger(__name__)


class FollowUpScheduler:
    def __init__(
        self,
        repository: Repository,
        handler: Callable[[FollowUpTaskRecord], Awaitable[None]],
    ) -> None:
        self.repository = repository
        self.handler = handler
        self._wake_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="followup-scheduler")

    async def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._task is not None:
            await self._task

    def notify(self) -> None:
        self._wake_event.set()

    async def _run(self) -> None:
        LOGGER.info("Follow-up scheduler started")
        while not self._stop_event.is_set():
            next_task = await self.repository.get_next_due_followup()
            if next_task is None:
                await self._wait_for_signal(timeout=900)
                continue

            wait_seconds = (next_task.due_at - utc_now()).total_seconds()
            if wait_seconds > 0:
                await self._wait_for_signal(timeout=wait_seconds)
                continue

            due_tasks = await self.repository.get_due_followups()
            for task in due_tasks:
                if self._stop_event.is_set():
                    break
                await self.handler(task)
        LOGGER.info("Follow-up scheduler stopped")

    async def _wait_for_signal(self, timeout: float) -> None:
        if self._wake_event.is_set():
            self._wake_event.clear()
            return
        try:
            await asyncio.wait_for(self._wake_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return
        finally:
            self._wake_event.clear()
