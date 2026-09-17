from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.core.models import AlertSignal
from src.market.binance_client import BinanceApiError
from src.signals.service import SignalLifecycleService
from src.signals.tracking import BackgroundTrackingService
from src.storage.db import initialize_database
from src.storage.repository import Repository


def _build_signal(
    *,
    symbol: str,
    created_at: datetime,
    timeframe: str = "15m",
    direction: str = "long",
) -> AlertSignal:
    return AlertSignal(
        symbol=symbol,
        direction=direction,
        timeframe=timeframe,
        candle_open_time=created_at - timedelta(minutes=15),
        candle_close_time=created_at,
        price=100.0,
        rsi=32.0,
        day_change_pct=1.5,
        day_volume=10_000_000.0,
        quote_volume=10_000_000.0,
        last_candle_volume=450_000.0,
        avg_volume_20=400_000.0,
        atr=2.0,
        atr_pct=0.02,
        ema20=99.0,
        ema50=97.0,
        score=80,
        explanation="Tracking test signal.",
        metadata={
            "strategy_key": "breakout",
            "invalidation_price": 95.0,
            "setup_direction": direction,
            "interactive_ai_enabled": True,
            "market_regime_tag": "Trend",
        },
    )


class _RejectingMarketClient:
    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc
        self.calls: list[tuple[str, str, int]] = []

    async def get_klines(self, symbol: str, timeframe: str, limit: int):
        self.calls.append((symbol, timeframe, limit))
        if self.exc is not None:
            raise self.exc
        raise AssertionError("get_klines should not have been called")


class _InvalidSymbolError(RuntimeError):
    def __init__(self) -> None:
        self.status = 400
        self.response_text = '{"code":-1121,"msg":"Invalid symbol."}'
        super().__init__(self.response_text)


class _FrameMarketClient:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.calls: list[tuple[str, str, int]] = []

    async def get_klines(self, symbol: str, timeframe: str, limit: int):
        self.calls.append((symbol, timeframe, limit))
        return self.frame.copy()


def _build_kline_frame(
    *,
    start_open: datetime,
    interval_minutes: int,
    candles: list[tuple[float, float, float, float, float, float]],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    current_open = start_open
    for open_price, high_price, low_price, close_price, volume, quote_volume in candles:
        close_time = current_open + timedelta(minutes=interval_minutes)
        rows.append(
            {
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume,
                "quote_asset_volume": quote_volume,
                "close_time": pd.Timestamp(close_time),
            }
        )
        current_open = close_time
    frame = pd.DataFrame(rows, index=pd.to_datetime([start_open + timedelta(minutes=interval_minutes * index) for index in range(len(rows))], utc=True))
    frame.index.name = "open_time"
    return frame


class BackgroundTrackingServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.sqlite_path = Path(self.tempdir.name) / "tracking.sqlite3"
        await initialize_database(str(self.sqlite_path))
        self.repository = Repository(str(self.sqlite_path))
        await self.repository.connect()
        self.lifecycle_service = SignalLifecycleService(self.repository)

    async def asyncTearDown(self) -> None:
        await self.repository.close()
        self.tempdir.cleanup()

    async def test_quote_only_symbol_is_closed_without_market_fetch(self) -> None:
        created_at = datetime(2026, 3, 19, 18, 0, tzinfo=timezone.utc)
        record = await self.lifecycle_service.create_signal(
            signal=_build_signal(symbol="龙虾USDT", created_at=created_at),
            alert_id=None,
            created_at=created_at,
        )
        self.assertEqual(record.symbol, "USDT")

        market_client = _RejectingMarketClient()
        tracker = BackgroundTrackingService(self.repository, market_client, self.lifecycle_service)
        await tracker.run_maintenance(now=created_at + timedelta(minutes=1))

        updated = await self.repository.get_tracked_signal(record.signal_id)
        assert updated is not None
        self.assertEqual(updated.status, "expired")
        self.assertEqual(updated.result_type, "neutral")
        self.assertEqual(updated.metadata.get("tracking_unavailable_reason"), "invalid_symbol")
        self.assertEqual(market_client.calls, [])

    async def test_invalid_symbol_response_expires_signal_cleanly(self) -> None:
        created_at = datetime(2026, 3, 19, 18, 5, tzinfo=timezone.utc)
        record = await self.lifecycle_service.create_signal(
            signal=_build_signal(symbol="XAUUSD", created_at=created_at),
            alert_id=None,
            created_at=created_at,
        )

        market_client = _RejectingMarketClient(exc=_InvalidSymbolError())
        tracker = BackgroundTrackingService(self.repository, market_client, self.lifecycle_service)
        await tracker.run_maintenance(now=created_at + timedelta(minutes=1))

        updated = await self.repository.get_tracked_signal(record.signal_id)
        assert updated is not None
        self.assertEqual(updated.status, "expired")
        self.assertEqual(updated.result_type, "neutral")
        self.assertEqual(updated.metadata.get("tracking_unavailable_reason"), "invalid_symbol")
        self.assertEqual(market_client.calls, [("XAUUSD", "15m", 4)])

    async def test_recent_candle_archive_replays_missed_stop_touch(self) -> None:
        created_at = datetime(2026, 3, 19, 18, 0, tzinfo=timezone.utc)
        record = await self.lifecycle_service.create_signal(
            signal=_build_signal(symbol="BTCUSDT", created_at=created_at, direction="long"),
            alert_id=None,
            created_at=created_at,
        )
        frame = _build_kline_frame(
            start_open=created_at,
            interval_minutes=15,
            candles=[
                (100.0, 101.2, 99.4, 100.8, 1200.0, 120_000.0),
                (100.8, 101.0, 94.8, 95.6, 1800.0, 170_000.0),
                (95.6, 100.9, 95.2, 100.1, 1600.0, 150_000.0),
            ],
        )
        market_client = _FrameMarketClient(frame)
        settings = SimpleNamespace(
            signal_candle_archive_enabled=True,
            signal_candle_archive_seconds=8 * 3600,
            signal_candle_archive_batch_size=24,
            signal_candle_archive_max_klines_per_request=64,
        )
        tracker = BackgroundTrackingService(
            self.repository,
            market_client,
            self.lifecycle_service,
            settings=settings,
        )

        await tracker.run_maintenance(now=created_at + timedelta(minutes=46))

        updated = await self.repository.get_tracked_signal(record.signal_id)
        assert updated is not None
        self.assertEqual(updated.status, "invalidated")
        self.assertEqual(updated.result_type, "loss")
        candles = await self.repository.list_signal_candles(record.signal_id)
        self.assertEqual(len(candles), 3)
        self.assertEqual(market_client.calls[0][:2], ("BTCUSDT", "15m"))

    async def test_candle_archive_stops_after_binance_rate_limit_cooldown(self) -> None:
        created_at = datetime(2026, 3, 19, 18, 0, tzinfo=timezone.utc)
        for index, symbol in enumerate(("BTCUSDT", "ETHUSDT")):
            await self.lifecycle_service.create_signal(
                signal=_build_signal(symbol=symbol, created_at=created_at + timedelta(seconds=index)),
                alert_id=None,
                created_at=created_at + timedelta(seconds=index),
            )
        market_client = _RejectingMarketClient(
            BinanceApiError(418, "Rate limit cooldown active", non_retryable=True)
        )
        settings = SimpleNamespace(
            signal_candle_archive_enabled=True,
            signal_candle_archive_seconds=8 * 3600,
            signal_candle_archive_batch_size=24,
            signal_candle_archive_max_klines_per_request=64,
            operational_cleanup_enabled=False,
        )
        tracker = BackgroundTrackingService(
            self.repository,
            market_client,
            self.lifecycle_service,
            settings=settings,
        )

        await tracker.run_maintenance(now=created_at + timedelta(minutes=1))

        self.assertEqual(len(market_client.calls), 1)

    async def test_maintenance_expires_due_signal_without_market_fetch(self) -> None:
        created_at = datetime(2026, 3, 17, 18, 0, tzinfo=timezone.utc)
        record = await self.lifecycle_service.create_signal(
            signal=_build_signal(symbol="BTCUSDT", created_at=created_at),
            alert_id=None,
            created_at=created_at,
        )
        market_client = _RejectingMarketClient()
        tracker = BackgroundTrackingService(
            self.repository,
            market_client,
            self.lifecycle_service,
            batch_size=1,
        )

        await tracker.run_maintenance(now=created_at + timedelta(days=2))

        updated = await self.repository.get_tracked_signal(record.signal_id)
        assert updated is not None
        self.assertEqual(updated.status, "expired")
        self.assertEqual(updated.result_type, "neutral")
        self.assertEqual(market_client.calls, [])

    async def test_maintenance_checks_oldest_unchecked_open_signal_first(self) -> None:
        created_at = datetime(2026, 3, 19, 18, 0, tzinfo=timezone.utc)
        older = await self.lifecycle_service.create_signal(
            signal=_build_signal(symbol="BTCUSDT", created_at=created_at, timeframe="4h"),
            alert_id=None,
            created_at=created_at,
        )
        await self.lifecycle_service.create_signal(
            signal=_build_signal(symbol="ETHUSDT", created_at=created_at + timedelta(minutes=1), timeframe="4h"),
            alert_id=None,
            created_at=created_at + timedelta(minutes=1),
        )
        frame = _build_kline_frame(
            start_open=created_at + timedelta(hours=1),
            interval_minutes=240,
            candles=[(100.0, 101.0, 99.0, 100.5, 1200.0, 120_000.0)],
        )
        market_client = _FrameMarketClient(frame)
        tracker = BackgroundTrackingService(
            self.repository,
            market_client,
            self.lifecycle_service,
            batch_size=1,
        )

        await tracker.run_maintenance(now=created_at + timedelta(hours=2))

        updated_older = await self.repository.get_tracked_signal(older.signal_id)
        assert updated_older is not None
        self.assertEqual(market_client.calls, [("BTCUSDT", "4h", 4)])
        self.assertGreater(updated_older.last_price_at, created_at)
