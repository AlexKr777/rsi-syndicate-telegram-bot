from __future__ import annotations

"""Structured timing for user-facing routes without storing sensitive payloads."""

import logging
from dataclasses import dataclass
from time import monotonic


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RouteTiming:
    route: str
    user_id: int
    total_ms: float
    success: bool
    cache: str = "n/a"
    query_count: int | None = None


class PerformanceTelemetryService:
    def record(self, timing: RouteTiming) -> None:
        LOGGER.info(
            "UI timing route=%s user=%s db_ms=tracked-in-repository external_ms=0 render_ms=0 total_ms=%.1f queries=%s cache=%s success=%s",
            timing.route,
            timing.user_id,
            timing.total_ms,
            timing.query_count if timing.query_count is not None else "n/a",
            timing.cache,
            timing.success,
        )

    async def measure(self, *, route: str, user_id: int, operation):
        started = monotonic()
        try:
            value = await operation()
        except Exception:
            self.record(RouteTiming(route, user_id, (monotonic() - started) * 1000, False))
            raise
        self.record(RouteTiming(route, user_id, (monotonic() - started) * 1000, True))
        return value
