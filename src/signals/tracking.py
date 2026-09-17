from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta
from time import monotonic
from typing import Any

from src.core.config import Settings
from src.core.utils import interval_to_timedelta, normalize_symbol, utc_now
from src.signals.domain import OPEN_SIGNAL_STATUSES
from src.signals.service import SignalLifecycleService
from src.storage.models import SignalLifecycleRecord
from src.storage.repository import Repository

LOGGER = logging.getLogger(__name__)
_QUOTE_ONLY_SYMBOLS = {"USD", "USDT", "BUSD", "USDC", "FDUSD", "TUSD"}


def _is_obviously_untrackable_symbol(symbol: str | None) -> bool:
    normalized = normalize_symbol(symbol)
    if not normalized:
        return True
    if normalized in _QUOTE_ONLY_SYMBOLS:
        return True
    return False


def _is_invalid_symbol_error(exc: Exception) -> bool:
    response_text = str(getattr(exc, "response_text", "") or exc)
    status = getattr(exc, "status", None)
    if status == 400 and "Invalid symbol" in response_text:
        return True
    return '"code":-1121' in response_text or '"code": -1121' in response_text


def _is_rate_limit_error(exc: Exception) -> bool:
    return getattr(exc, "status", None) in {418, 429}


class BackgroundTrackingService:
    def __init__(
        self,
        repository: Repository,
        market_client,
        lifecycle_service: SignalLifecycleService,
        *,
        settings: Settings | None = None,
        batch_size: int | None = None,
    ) -> None:
        self.repository = repository
        self.market_client = market_client
        self.lifecycle_service = lifecycle_service
        configured_batch_size = (
            getattr(settings, "signal_tracking_batch_size", 1_000)
            if batch_size is None and settings is not None
            else batch_size or 24
        )
        self.batch_size = max(int(configured_batch_size), 1)
        self.live_kline_limit = max(int(getattr(settings, "klines_limit", 4)), 4)
        self.settings = settings
        self.archive_enabled = bool(settings.signal_candle_archive_enabled) if settings is not None else False
        self.archive_window = timedelta(seconds=settings.signal_candle_archive_seconds) if settings is not None else timedelta(hours=8)
        self.archive_batch_size = max(int(settings.signal_candle_archive_batch_size), 1) if settings is not None else self.batch_size
        self.archive_max_klines = max(int(settings.signal_candle_archive_max_klines_per_request), 8) if settings is not None else 64
        self.cleanup_enabled = bool(getattr(settings, "operational_cleanup_enabled", False))
        self.cleanup_interval = timedelta(
            hours=max(int(getattr(settings, "operational_cleanup_interval_hours", 6)), 1)
        )
        self.cleanup_batch_size = max(int(getattr(settings, "operational_cleanup_batch_size", 5_000)), 1)
        self.signal_candle_retention = timedelta(
            days=max(int(getattr(settings, "signal_candle_retention_days", 2)), 1)
        )
        self.telemetry_retention = timedelta(
            days=max(int(getattr(settings, "telemetry_retention_days", 30)), 1)
        )
        self.strategy_snapshot_retention = timedelta(
            days=max(int(getattr(settings, "strategy_snapshot_retention_days", 2)), 1)
        )
        self._last_cleanup_at: datetime | None = None

    def _estimate_kline_limit(
        self,
        *,
        timeframe: str,
        earliest_created_at: datetime,
        now: datetime,
    ) -> int:
        try:
            interval_seconds = max(interval_to_timedelta(timeframe).total_seconds(), 60.0)
        except ValueError:
            interval_seconds = 900.0
        window_seconds = max((now - earliest_created_at).total_seconds(), interval_seconds)
        bars_needed = math.ceil(window_seconds / interval_seconds) + 4
        return max(8, min(int(bars_needed), self.archive_max_klines))

    def _select_record_candles(
        self,
        record: SignalLifecycleRecord,
        frame,
        *,
        now: datetime,
    ) -> list[dict[str, Any]]:
        if frame is None or frame.empty:
            return []
        window_end = min(now, record.created_at + self.archive_window)
        selected = frame[
            (frame["close_time"] > record.created_at)
            & (frame["close_time"] <= window_end)
        ].copy()
        if selected.empty:
            return []
        collected_at = now.isoformat()
        rows: list[dict[str, Any]] = []
        for _, row in selected.iterrows():
            rows.append(
                {
                    "candle_open_time": row.name.to_pydatetime().isoformat() if hasattr(row.name, "to_pydatetime") else str(row.name),
                    "candle_close_time": row["close_time"].to_pydatetime().isoformat() if hasattr(row["close_time"], "to_pydatetime") else str(row["close_time"]),
                    "open_price": float(row["open"]),
                    "high_price": float(row["high"]),
                    "low_price": float(row["low"]),
                    "close_price": float(row["close"]),
                    "volume": float(row["volume"]) if row.get("volume") is not None else None,
                    "quote_volume": float(row["quote_asset_volume"]) if row.get("quote_asset_volume") is not None else None,
                    "source": "rest_backfill",
                    "collected_at": collected_at,
                    "processed_at": None,
                }
            )
        return rows

    async def _mark_untrackable(
        self,
        record: SignalLifecycleRecord,
        *,
        observed_at: datetime,
        reason: str,
        details: dict[str, Any],
    ) -> None:
        if record.status not in OPEN_SIGNAL_STATUSES:
            return
        await self.lifecycle_service.mark_signal_untrackable(
            record,
            observed_at=observed_at,
            reason=reason,
            details=details,
        )

    async def _process_archived_candles(
        self,
        record: SignalLifecycleRecord,
        *,
        processed_at: datetime,
    ) -> None:
        if record.status not in OPEN_SIGNAL_STATUSES:
            return
        current = await self.repository.get_tracked_signal(record.signal_id) or record
        candles = await self.repository.list_signal_candles(record.signal_id, only_unprocessed=True, limit=self.archive_max_klines)
        for candle in candles:
            current = await self.lifecycle_service.evaluate_signal_state(
                current,
                high_price=candle.high_price,
                low_price=candle.low_price,
                close_price=candle.close_price,
                observed_at=candle.candle_close_time,
            )
            await self.repository.mark_signal_candle_processed(candle.id, processed_at=processed_at)
            if current.status not in OPEN_SIGNAL_STATUSES:
                break

    async def _collect_recent_candle_archive(self, *, now: datetime) -> tuple[set[int], bool]:
        if not self.archive_enabled:
            return set(), False

        cutoff = now - self.archive_window
        records = await self.repository.list_signals_for_candle_archive(
            since=cutoff,
            limit=self.archive_batch_size,
        )
        if not records:
            return set(), False

        handled_signal_ids: set[int] = set()
        rate_limited = False
        grouped: dict[tuple[str, str], list[SignalLifecycleRecord]] = defaultdict(list)
        for record in records:
            grouped[(record.symbol, record.timeframe)].append(record)

        for (symbol, timeframe), grouped_records in grouped.items():
            grouped_records = sorted(grouped_records, key=lambda item: item.created_at)
            if _is_obviously_untrackable_symbol(symbol):
                for record in grouped_records:
                    await self._mark_untrackable(
                        record,
                        observed_at=now,
                        reason="invalid_symbol",
                        details={"symbol": record.symbol, "source": "candle_archive_precheck"},
                    )
                    LOGGER.warning(
                        "Closed untrackable signal_id=%s symbol=%s before candle archive fetch",
                        record.signal_id,
                        record.symbol,
                    )
                    handled_signal_ids.add(record.signal_id)
                continue

            try:
                limit = self._estimate_kline_limit(
                    timeframe=timeframe,
                    earliest_created_at=grouped_records[0].created_at,
                    now=now,
                )
                frame = await self.market_client.get_klines(symbol, timeframe, limit)
            except Exception as exc:
                if _is_rate_limit_error(exc):
                    rate_limited = True
                    LOGGER.warning(
                        "Stopping candle archive pass after Binance rate limit for symbol=%s timeframe=%s: %s",
                        symbol,
                        timeframe,
                        exc,
                    )
                    break
                if _is_invalid_symbol_error(exc):
                    for record in grouped_records:
                        await self._mark_untrackable(
                            record,
                            observed_at=now,
                            reason="invalid_symbol",
                            details={
                                "symbol": record.symbol,
                                "timeframe": record.timeframe,
                                "source": "candle_archive_api",
                                "error": str(exc),
                            },
                        )
                        LOGGER.warning(
                            "Closed untrackable signal_id=%s symbol=%s after candle archive invalid symbol response",
                            record.signal_id,
                            record.symbol,
                        )
                        handled_signal_ids.add(record.signal_id)
                    continue
                LOGGER.exception("Candle archive fetch failed for symbol=%s timeframe=%s", symbol, timeframe)
                continue

            for record in grouped_records:
                try:
                    candles = self._select_record_candles(record, frame, now=now)
                    await self.repository.save_tracked_signal_candles(
                        signal_id=record.signal_id,
                        alert_id=record.alert_id,
                        symbol=record.symbol,
                        timeframe=record.timeframe,
                        candles=candles,
                    )
                    await self._process_archived_candles(record, processed_at=now)
                    handled_signal_ids.add(record.signal_id)
                except Exception:
                    LOGGER.exception(
                        "Failed to store/process candle archive for signal_id=%s symbol=%s",
                        record.signal_id,
                        record.symbol,
                    )
        return handled_signal_ids, rate_limited

    async def _run_operational_cleanup(self, *, now: datetime) -> None:
        if not self.cleanup_enabled:
            return
        if self._last_cleanup_at is not None and now - self._last_cleanup_at < self.cleanup_interval:
            return
        deleted = await self.repository.prune_operational_history(
            candle_before=now - self.signal_candle_retention,
            telemetry_before=now - self.telemetry_retention,
            snapshot_before=now - self.strategy_snapshot_retention,
            batch_size=self.cleanup_batch_size,
        )
        if any(deleted.values()):
            LOGGER.info("Operational history cleanup deleted=%s", deleted)
        if max(deleted.values(), default=0) < self.cleanup_batch_size:
            self._last_cleanup_at = now

    async def run_maintenance(self, *, now: datetime | None = None) -> None:
        effective_now = now or utc_now()
        started = monotonic()
        expired_count = await self.repository.expire_due_tracked_signals(
            now=effective_now,
            batch_size=self.cleanup_batch_size,
        )
        if expired_count:
            LOGGER.info("Expired %s overdue tracked signals", expired_count)
        archived_signal_ids, archive_rate_limited = await self._collect_recent_candle_archive(now=effective_now)
        if archive_rate_limited:
            await self.lifecycle_service.recompute_strategy_snapshots(now=effective_now)
            await self._run_operational_cleanup(now=effective_now)
            await self.repository.record_telemetry_event(
                event_name="lifecycle_maintenance_completed",
                created_at=effective_now,
                context="background_tracking",
                payload={"duration_ms": round((monotonic() - started) * 1000, 2), "rate_limited": True, "records": 0},
            )
            return
        records = await self.repository.list_tracked_signals_for_maintenance(
            now=effective_now,
            limit=self.batch_size,
        )
        grouped: dict[tuple[str, str], list[SignalLifecycleRecord]] = defaultdict(list)
        for record in records:
            if record.signal_id not in archived_signal_ids:
                grouped[(record.symbol, record.timeframe)].append(record)

        for (symbol, timeframe), grouped_records in grouped.items():
            if _is_obviously_untrackable_symbol(symbol):
                for record in grouped_records:
                    await self.lifecycle_service.mark_signal_untrackable(
                        record,
                        observed_at=effective_now,
                        reason="invalid_symbol",
                        details={"symbol": record.symbol, "source": "background_tracking_precheck"},
                    )
                    LOGGER.warning(
                        "Closed untrackable signal_id=%s symbol=%s before market fetch",
                        record.signal_id,
                        record.symbol,
                    )
                continue
            try:
                frame = await self.market_client.get_klines(symbol, timeframe, self.live_kline_limit)
            except Exception as exc:
                if _is_rate_limit_error(exc):
                    LOGGER.warning(
                        "Stopping background tracking pass after Binance rate limit for symbol=%s timeframe=%s: %s",
                        symbol,
                        timeframe,
                        exc,
                    )
                    break
                if _is_invalid_symbol_error(exc):
                    for record in grouped_records:
                        await self.lifecycle_service.mark_signal_untrackable(
                            record,
                            observed_at=effective_now,
                            reason="invalid_symbol",
                            details={
                                "symbol": record.symbol,
                                "timeframe": record.timeframe,
                                "source": "background_tracking_api",
                                "error": str(exc),
                            },
                        )
                        LOGGER.warning(
                            "Closed untrackable signal_id=%s symbol=%s after invalid symbol response",
                            record.signal_id,
                            record.symbol,
                        )
                    continue
                LOGGER.exception("Background tracking fetch failed for symbol=%s timeframe=%s", symbol, timeframe)
                await self.repository.record_telemetry_event(
                    event_name="lifecycle_market_error",
                    created_at=effective_now,
                    context="background_tracking",
                    payload={"symbol": symbol, "timeframe": timeframe, "error": str(exc)[:300]},
                )
                continue

            if frame is None or frame.empty:
                continue
            row = frame.iloc[-1]
            high_price = float(row["high"])
            low_price = float(row["low"])
            close_price = float(row["close"])
            observed_at = row["close_time"].to_pydatetime() if "close_time" in row else effective_now
            for record in grouped_records:
                try:
                    await self.lifecycle_service.evaluate_signal_state(
                        record,
                        high_price=high_price,
                        low_price=low_price,
                        close_price=close_price,
                        observed_at=observed_at,
                    )
                except Exception:
                    LOGGER.exception(
                        "Background tracking evaluation failed for signal_id=%s symbol=%s",
                        record.signal_id,
                        record.symbol,
                    )
        await self.lifecycle_service.recompute_strategy_snapshots(now=effective_now)
        await self._run_operational_cleanup(now=effective_now)
        await self.repository.record_telemetry_event(
            event_name="lifecycle_maintenance_completed",
            created_at=effective_now,
            context="background_tracking",
            payload={
                "duration_ms": round((monotonic() - started) * 1000, 2),
                "rate_limited": False,
                "records": len(records),
                "expired": expired_count,
            },
        )
