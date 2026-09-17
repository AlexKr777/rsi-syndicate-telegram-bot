from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.models import AlertSignal
from src.signals.service import SignalLifecycleService
from src.storage.db import initialize_database
from src.storage.repository import Repository


def _signal(created_at: datetime) -> AlertSignal:
    return AlertSignal(
        symbol="BTCUSDT",
        direction="long",
        timeframe="15m",
        candle_open_time=created_at - timedelta(minutes=15),
        candle_close_time=created_at,
        price=100.0,
        rsi=30.0,
        day_change_pct=1.0,
        day_volume=1_000_000.0,
        quote_volume=1_000_000.0,
        last_candle_volume=10_000.0,
        avg_volume_20=10_000.0,
        atr=1.0,
        atr_pct=0.01,
        ema20=99.0,
        ema50=98.0,
        score=80,
        explanation="maintenance test",
        metadata={"strategy_key": "breakout", "invalidation_price": 95.0},
    )


class OperationalMaintenanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.sqlite_path = Path(self.tempdir.name) / "maintenance.sqlite3"
        await initialize_database(str(self.sqlite_path))
        self.repository = Repository(str(self.sqlite_path))
        await self.repository.connect()

    async def asyncTearDown(self) -> None:
        await self.repository.close()
        self.tempdir.cleanup()

    async def test_prune_operational_history_removes_only_expired_rows(self) -> None:
        now = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)
        service = SignalLifecycleService(self.repository)
        record = await service.create_signal(signal=_signal(now), alert_id=None, created_at=now)
        await self.repository.save_tracked_signal_candles(
            signal_id=record.signal_id,
            alert_id=None,
            symbol=record.symbol,
            timeframe=record.timeframe,
            candles=[
                {
                    "candle_open_time": (now - timedelta(days=4)).isoformat(),
                    "candle_close_time": (now - timedelta(days=4) + timedelta(minutes=15)).isoformat(),
                    "open_price": 100.0,
                    "high_price": 101.0,
                    "low_price": 99.0,
                    "close_price": 100.5,
                    "volume": 1.0,
                    "quote_volume": 100.0,
                    "collected_at": (now - timedelta(days=4)).isoformat(),
                    "processed_at": now.isoformat(),
                },
                {
                    "candle_open_time": (now - timedelta(hours=1)).isoformat(),
                    "candle_close_time": (now - timedelta(minutes=45)).isoformat(),
                    "open_price": 100.0,
                    "high_price": 101.0,
                    "low_price": 99.0,
                    "close_price": 100.5,
                    "volume": 1.0,
                    "quote_volume": 100.0,
                    "collected_at": (now - timedelta(hours=1)).isoformat(),
                    "processed_at": now.isoformat(),
                },
            ],
        )
        await self.repository.record_telemetry_event(event_name="old", created_at=now - timedelta(days=40))
        await self.repository.record_telemetry_event(event_name="new", created_at=now - timedelta(days=1))

        deleted = await self.repository.prune_operational_history(
            candle_before=now - timedelta(days=2),
            telemetry_before=now - timedelta(days=30),
            snapshot_before=now - timedelta(days=2),
            batch_size=100,
        )

        self.assertEqual(deleted["tracked_signal_candles"], 1)
        self.assertEqual(deleted["telemetry_events"], 1)
        candles = await self.repository.list_signal_candles(record.signal_id)
        self.assertEqual(len(candles), 1)

    async def test_expire_due_tracked_signals_closes_only_due_open_records(self) -> None:
        now = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)
        service = SignalLifecycleService(self.repository)
        due = await service.create_signal(
            signal=_signal(now - timedelta(days=2)),
            alert_id=None,
            created_at=now - timedelta(days=2),
        )
        future = await service.create_signal(
            signal=_signal(now),
            alert_id=None,
            created_at=now,
        )

        expired_count = await self.repository.expire_due_tracked_signals(
            now=now,
            batch_size=100,
        )

        self.assertEqual(expired_count, 1)
        updated_due = await self.repository.get_tracked_signal(due.signal_id)
        updated_future = await self.repository.get_tracked_signal(future.signal_id)
        assert updated_due is not None
        assert updated_future is not None
        self.assertEqual(updated_due.status, "expired")
        self.assertEqual(updated_due.result_type, "neutral")
        self.assertEqual(updated_due.closed_at, now)
        self.assertEqual(updated_due.metadata.get("signal_status"), "expired")
        self.assertEqual(updated_future.status, "fresh")
