from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from src.core.utils import utc_now
from src.storage.models import OnboardingCampaignRecord
from src.storage.repository import Repository

LOGGER = logging.getLogger(__name__)


class OnboardingPaymentScheduler:
    def __init__(
        self,
        repository: Repository,
        handler: Callable[[OnboardingCampaignRecord], Awaitable[None]],
        *,
        idle_check_seconds: int = 60,
    ) -> None:
        self.repository = repository
        self.handler = handler
        self.idle_check_seconds = max(int(idle_check_seconds), 5)
        self._wake_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="onboarding-payment-scheduler")

    async def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._task is not None:
            await self._task

    def notify(self) -> None:
        self._wake_event.set()

    async def _run(self) -> None:
        LOGGER.info("Onboarding payment scheduler started")
        while not self._stop_event.is_set():
            next_campaign = await self.repository.get_next_due_onboarding_payment_campaign()
            if next_campaign is None:
                await self._wait_for_signal(timeout=self.idle_check_seconds)
                continue

            due_at = next_campaign.next_retry_at or next_campaign.trial_ends_at
            if due_at is None:
                await self._wait_for_signal(timeout=self.idle_check_seconds)
                continue

            wait_seconds = (due_at - utc_now()).total_seconds()
            if wait_seconds > 0:
                await self._wait_for_signal(timeout=min(wait_seconds, self.idle_check_seconds))
                continue

            due_campaigns = await self.repository.get_due_onboarding_payment_campaigns(limit=50)
            for campaign in due_campaigns:
                if self._stop_event.is_set():
                    break
                await self.handler(campaign)
        LOGGER.info("Onboarding payment scheduler stopped")

    async def _wait_for_signal(self, timeout: float) -> None:
        if self._wake_event.is_set():
            self._wake_event.clear()
            return
        try:
            await asyncio.wait_for(self._wake_event.wait(), timeout=max(timeout, 0.0))
        except asyncio.TimeoutError:
            return
        finally:
            self._wake_event.clear()
