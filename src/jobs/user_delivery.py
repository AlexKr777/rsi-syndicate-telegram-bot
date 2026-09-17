from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

LOGGER = logging.getLogger(__name__)


class UserDeliveryScheduler:
    def __init__(
        self,
        *,
        handlers: list[Callable[[], Awaitable[None]]],
        interval_seconds: int = 60,
    ) -> None:
        self.handlers = handlers
        self.interval_seconds = max(int(interval_seconds), 15)
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="user-delivery-scheduler")

    async def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._task is not None:
            await self._task

    def notify(self) -> None:
        self._wake_event.set()

    async def _run(self) -> None:
        LOGGER.info("User delivery scheduler started")
        while not self._stop_event.is_set():
            for handler in self.handlers:
                if self._stop_event.is_set():
                    break
                try:
                    await handler()
                except Exception:
                    LOGGER.exception("User delivery maintenance pass failed")
            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                pass
            finally:
                self._wake_event.clear()
        LOGGER.info("User delivery scheduler stopped")
