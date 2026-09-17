from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from src.bot.formatters import format_alert_message
from src.core.models import AlertSignal
from src.signals.service import SignalLifecycleService
from src.storage.db import initialize_database
from src.storage.repository import Repository
from src.userbot.access_view import build_access_view_model
from src.userbot.navigation_state import NavigationService
from src.userbot.results_service import ResultsService
from src.userbot.ux_v2 import build_home_keyboard


def _signal(now: datetime) -> AlertSignal:
    return AlertSignal(
        symbol="BTCUSDT", direction="long", timeframe="15m", candle_open_time=now - timedelta(minutes=15), candle_close_time=now,
        price=100.0, rsi=28.0, day_change_pct=3.2, day_volume=500_000_000.0, quote_volume=500_000_000.0,
        last_candle_volume=2_000_000.0, avg_volume_20=1_000_000.0, atr=1.0, atr_pct=0.01, ema20=99.0, ema50=98.0,
        score=89, explanation="Цена сохранила импульс после возврата к уровню.",
        metadata={"strategy_key": "breakout", "entry_zone_low": 99.5, "entry_zone_high": 100.5, "invalidation_price": 97.0, "tp_price_primary": 107.0, "text_layout": "v2_1_compact"},
    )


class UXV21NavigationTests(unittest.TestCase):
    def test_back_uses_history_and_keeps_messages_independent(self) -> None:
        nav = NavigationService()
        nav.open(bot_kind="premium", user_id=7, chat_id="7", message_id=10, route="home_simple", root=True)
        nav.open(bot_kind="premium", user_id=7, chat_id="7", message_id=10, route="strategies")
        nav.open(bot_kind="premium", user_id=7, chat_id="7", message_id=10, route="strategy", params={"strategy_key": "rsi"})
        nav.open(bot_kind="premium", user_id=7, chat_id="7", message_id=11, route="home_pro", root=True)

        previous = nav.back(bot_kind="premium", user_id=7, chat_id="7", message_id=10)
        self.assertEqual(previous.name if previous else None, "strategies")
        self.assertIsNone(nav.back(bot_kind="premium", user_id=7, chat_id="7", message_id=11))

    def test_first_v2_screen_has_a_home_fallback(self) -> None:
        nav = NavigationService()
        nav.open(
            bot_kind="premium",
            user_id=7,
            chat_id="7",
            message_id=10,
            route="watchlist",
            fallback_root="home_pro",
        )
        previous = nav.back(bot_kind="premium", user_id=7, chat_id="7", message_id=10)
        self.assertEqual(previous.name if previous else None, "home_pro")

    def test_home_menus_are_strategy_first_and_do_not_expose_flow_language(self) -> None:
        for is_pro in (False, True):
            keyboard = build_home_keyboard(language_code="ru", is_pro=is_pro, include_gold=True)
            texts = [button["text"] for row in keyboard["inline_keyboard"] for button in row]
            self.assertEqual(texts[0], "📈 Стратегии")
            self.assertFalse(any("поток" in text.lower() for text in texts))


class UXV21ViewTests(unittest.TestCase):
    def test_compact_signal_card_is_localized(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
        russian = format_alert_message(_signal(now), timezone.utc, "", language_code="ru")
        english = format_alert_message(_signal(now), timezone.utc, "", language_code="en")
        self.assertIn("Цена сейчас", russian)
        self.assertNotIn("Price now", russian)
        self.assertIn("Price now", english)
        self.assertNotIn("Цена сейчас", english)

    def test_access_view_has_one_status_block(self) -> None:
        state = SimpleNamespace(is_admin=False, access_status="paid", has_premium_access=True, ends_at=datetime(2026, 8, 12, tzinfo=timezone.utc))
        text = build_access_view_model(access_state=state, is_gold_enabled=False, profile_label="Интрадей", delivery_label="Сразу", language_code="ru").render(language_code="ru")
        self.assertEqual(text.count("PRO+ активен"), 1)
        self.assertEqual(text.count("Доступно сейчас"), 1)


class UXV21ResultsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "results.sqlite3"
        await initialize_database(str(self.path))
        self.repository = Repository(str(self.path))
        await self.repository.connect()

    async def asyncTearDown(self) -> None:
        await self.repository.close()
        self.tempdir.cleanup()

    async def test_results_read_persisted_lifecycle_not_messages(self) -> None:
        now = datetime.now(timezone.utc)
        lifecycle = SignalLifecycleService(self.repository)
        record = await lifecycle.create_signal(signal=_signal(now), alert_id=None, created_at=now)
        await lifecycle.evaluate_signal_state(record, high_price=108.0, low_price=99.0, close_price=107.0, observed_at=now + timedelta(hours=1))

        summary = await ResultsService(self.repository).summary(days=7)
        self.assertEqual(summary.total, 1)
        self.assertEqual(summary.confirmed, 1)
        self.assertEqual(summary.open, 0)

    async def test_diagnostics_exposes_persisted_job_health_without_guessing(self) -> None:
        now = datetime.now(timezone.utc)
        await self.repository.record_telemetry_event(
            event_name="lifecycle_maintenance_completed",
            created_at=now,
            context="test",
            payload={"duration_ms": 12.5},
        )
        diagnostics = await ResultsService(self.repository).diagnostics(now=now)
        self.assertEqual(diagnostics["last_lifecycle_duration_ms"], 12.5)
        self.assertEqual(diagnostics["market_errors_24h"], 0)
        self.assertIsNone(diagnostics["last_market_update_at"])
