from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from src.core.utils import utc_now
from src.storage.models import FollowUpResultRecord, SignalLifecycleRecord
from src.storage.repository import Repository


@dataclass(frozen=True, slots=True)
class ResultsSummary:
    total: int
    confirmed: int
    broken: int
    open: int
    insufficient: int
    followups: int
    updated_at: datetime | None
    records: tuple[SignalLifecycleRecord, ...]
    followup_records: tuple[FollowUpResultRecord, ...]


class ResultsService:
    """Reads only persisted lifecycle rows; it never derives results from Telegram history."""

    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    async def summary(
        self,
        *,
        days: int = 7,
        strategy_code: str | None = None,
        now: datetime | None = None,
        include_records: bool = True,
    ) -> ResultsSummary:
        effective_now = now or utc_now()
        since = effective_now - timedelta(days=max(int(days), 1))
        if not include_records:
            aggregate = await self.repository.summarize_recent_tracked_signals(
                since=since,
                strategy_code=strategy_code,
            )
            updated_at_raw = aggregate.get("updated_at")
            updated_at = datetime.fromisoformat(updated_at_raw) if isinstance(updated_at_raw, str) else None
            return ResultsSummary(
                int(aggregate["total"] or 0),
                int(aggregate["confirmed"] or 0),
                int(aggregate["broken"] or 0),
                int(aggregate["open"] or 0),
                int(aggregate["insufficient"] or 0),
                int(aggregate["followups"] or 0),
                updated_at,
                (),
                (),
            )
        records = await self.repository.list_results_tracked_signals(
            since=since,
            strategy_code=strategy_code,
            limit=500,
        )
        confirmed = sum(record.status in {"confirmed", "near_tp", "hit_tp"} for record in records)
        broken = sum(record.status == "invalidated" for record in records)
        open_count = sum(record.status in {"fresh", "active", "confirmed", "near_tp"} for record in records)
        insufficient = sum(record.status == "expired" and bool(record.metadata.get("tracking_unavailable")) for record in records)
        followups = await self.repository.list_latest_followup_results_for_alert_ids(
            [record.alert_id for record in records if record.alert_id is not None]
        )
        updated = max(
            (
                *(record.last_price_at or record.closed_at or record.created_at for record in records),
                *(record.observed_at for record in followups),
            ),
            default=None,
        )
        return ResultsSummary(
            len(records),
            confirmed,
            broken,
            open_count,
            insufficient,
            len(followups),
            updated,
            tuple(records),
            tuple(followups),
        )

    async def diagnostics(self, *, now: datetime | None = None) -> dict[str, int | float | str | None]:
        effective_now = now or utc_now()
        return await self.repository.get_results_diagnostics(
            stale_before=effective_now - timedelta(days=7),
            error_since=effective_now - timedelta(hours=24),
        )
