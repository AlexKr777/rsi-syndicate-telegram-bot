from __future__ import annotations

import unittest
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.bot.formatters import format_alert_message, format_followup_message
from src.core.models import AlertSignal, FollowUpResult
from src.signals.service import SignalLifecycleService
from src.storage.db import initialize_database
from src.storage.repository import Repository
from src.userbot.callbacks import parse_userbot_callback_data
from src.userbot.results_service import ResultsService
from src.userbot.ux_v2 import (
    build_market_keyboard,
    build_strategy_keyboard,
    format_home_message,
)


def _callbacks(markup: dict[str, object]) -> list[str]:
    return [
        str(button["callback_data"])
        for row in markup["inline_keyboard"]
        for button in row
    ]


def _signal(now: datetime) -> AlertSignal:
    return AlertSignal(
        symbol="BTCUSDT",
        direction="long",
        timeframe="15m",
        candle_open_time=now - timedelta(minutes=15),
        candle_close_time=now,
        price=100.0,
        rsi=28.0,
        day_change_pct=3.2,
        day_volume=500_000_000.0,
        quote_volume=500_000_000.0,
        last_candle_volume=2_000_000.0,
        avg_volume_20=1_000_000.0,
        atr=1.0,
        atr_pct=0.01,
        ema20=99.0,
        ema50=98.0,
        score=89,
        explanation="Пробой уровня подтверждён объёмом.",
        metadata={
            "strategy_key": "breakout",
            "entry_zone_low": 99.5,
            "entry_zone_high": 100.5,
            "invalidation_price": 97.0,
            "tp_price_primary": 107.0,
            "text_layout": "v2_2_compact",
        },
    )


class UXV22SurfaceTests(unittest.TestCase):
    def test_home_is_a_greeting_not_a_technical_status_panel(self) -> None:
        text = format_home_message(
            language_code="ru",
            first_name="Алина",
            is_pro=False,
        )
        self.assertIn("🏠 <b>Главное меню</b>", text)
        self.assertIn("Привет, Алина! 👋", text)
        self.assertNotIn("Активный профиль", text)
        self.assertNotIn("актуальных сигналов", text)

    def test_strategy_card_has_only_core_actions_and_real_v2_settings(self) -> None:
        callbacks = _callbacks(
            build_strategy_keyboard(language_code="ru", strategy_key="rsi", enabled=True, is_pro=True)
        )
        self.assertIn("v2:strategies:settings:rsi", callbacks)
        self.assertIn("v2:results:strategies:rsi", callbacks)
        self.assertFalse(any("signals:strategy" in callback for callback in callbacks))
        self.assertFalse(any("strategies:guide" in callback for callback in callbacks))
        self.assertFalse(any(callback.startswith("ux:analyze") for callback in callbacks))
        self.assertTrue(all(parse_userbot_callback_data(callback) is not None for callback in callbacks))

    def test_market_has_one_analysis_entry_and_v2_market_sets(self) -> None:
        callbacks = _callbacks(build_market_keyboard(language_code="ru", include_gold=False))
        self.assertEqual(callbacks.count("v2:analytics:analyze"), 1)
        self.assertIn("v2:market:sets", callbacks)
        self.assertFalse(any(callback == "ux:themes" for callback in callbacks))

    def test_live_alert_and_followup_use_compact_russian_layout(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
        alert = format_alert_message(_signal(now), timezone.utc, "", language_code="ru")
        followup = format_followup_message(
            FollowUpResult(
                alert_id=1,
                symbol="BTCUSDT",
                direction="long",
                timeframe="15m",
                alert_price=100.0,
                current_price=104.0,
                alert_rsi=28.0,
                current_rsi=49.0,
                move_pct=4.0,
                score=89,
                observed_at=now + timedelta(hours=2),
                stage="2ч",
                summary="Цена удерживается выше зоны входа.",
                metadata={"strategy_key": "breakout", "text_layout": "v2_2_compact"},
            ),
            timezone.utc,
            language_code="ru",
        )
        self.assertIn("🎯 Зона", alert)
        self.assertNotIn("Follow-up", alert)
        self.assertIn("📌 Итог", followup)
        self.assertNotIn("Follow-up", followup)


class UXV22ResultsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "results.sqlite3"
        await initialize_database(str(self.path))
        self.repository = Repository(str(self.path))
        await self.repository.connect()

    async def asyncTearDown(self) -> None:
        await self.repository.close()
        self.tempdir.cleanup()

    async def test_results_reads_persisted_lifecycle_and_followup_rows(self) -> None:
        now = datetime.now(timezone.utc)
        signal = _signal(now)
        alert_id = await self.repository.create_alert(
            signal,
            sent_at=now,
            followup_due_at=now + timedelta(hours=2),
            lab_message_id=None,
        )
        lifecycle = SignalLifecycleService(self.repository)
        await lifecycle.create_signal(signal=signal, alert_id=alert_id, created_at=now)
        await self.repository.save_followup_result(
            FollowUpResult(
                alert_id=alert_id,
                symbol="BTCUSDT",
                direction="long",
                timeframe="15m",
                alert_price=100.0,
                current_price=104.0,
                alert_rsi=28.0,
                current_rsi=49.0,
                move_pct=4.0,
                score=89,
                observed_at=now + timedelta(hours=2),
                stage="2h",
                summary="Persisted follow-up.",
            )
        )

        summary = await ResultsService(self.repository).summary(days=7, now=now + timedelta(hours=3))
        self.assertEqual(summary.total, 1)
        self.assertEqual(summary.followups, 1)
        self.assertEqual(summary.followup_records[0].alert_id, alert_id)
