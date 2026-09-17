from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.bot.routing import MessageRouter
from src.core.config import get_settings
from src.core.models import AlertSignal, FollowUpResult
from src.storage.db import initialize_database
from src.storage.repository import Repository


class _FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []
        self.photos: list[dict[str, object]] = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return {"message_id": len(self.messages), "chat": {"id": kwargs.get("chat_id")}}

    async def send_photo(self, **kwargs):
        self.photos.append(kwargs)
        return {"message_id": len(self.photos), "chat": {"id": kwargs.get("chat_id")}}


class ClassicAlertParityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.sqlite_path = Path(self.tempdir.name) / "test.db"
        self.chart_path = Path(self.tempdir.name) / "chart.png"
        self.chart_path.write_bytes(b"test-chart")
        await initialize_database(str(self.sqlite_path))
        self.repository = Repository(str(self.sqlite_path))
        await self.repository.connect()
        self.telegram = _FakeTelegramClient()
        self.settings = get_settings().model_copy(deep=True)
        self.settings.tunnel_url_file = Path(self.tempdir.name) / "tunnel.txt"
        self.settings.tunnel_url_file.write_text("https://demo.ngrok-free.app\n", encoding="utf-8")
        self.router = MessageRouter(
            settings=self.settings,
            telegram_client=self.telegram,
            repository=self.repository,
        )

    async def asyncTearDown(self) -> None:
        await self.repository.close()
        self.tempdir.cleanup()

    def _alert_signal(self) -> AlertSignal:
        now = datetime.now(timezone.utc)
        return AlertSignal(
            symbol="BTCUSDT",
            direction="oversold",
            timeframe="15m",
            candle_open_time=now - timedelta(minutes=15),
            candle_close_time=now,
            price=100.0,
            rsi=28.0,
            day_change_pct=2.5,
            day_volume=1_500_000.0,
            quote_volume=1_500_000.0,
            last_candle_volume=25_000.0,
            avg_volume_20=20_000.0,
            atr=1.2,
            atr_pct=0.012,
            ema20=101.0,
            ema50=103.0,
            score=88,
            explanation="Test explanation",
            chart_path=self.chart_path,
            metadata={"language_code": "en", "strategy_key": "breakout"},
        )

    def _followup_result(self) -> FollowUpResult:
        now = datetime.now(timezone.utc)
        return FollowUpResult(
            alert_id=1,
            symbol="BTCUSDT",
            direction="oversold",
            timeframe="15m",
            alert_price=100.0,
            current_price=103.5,
            alert_rsi=28.0,
            current_rsi=36.0,
            move_pct=3.5,
            summary="Momentum improved after the alert.",
            score=90,
            observed_at=now,
            chart_path=self.chart_path,
            metadata={"language_code": "en", "strategy_key": "breakout"},
        )

    async def test_classic_alert_uses_photo_and_delay_footer(self) -> None:
        delivery = await self.router.send_raw_alert_to_chat(
            self._alert_signal(),
            chat_id="classic-chat",
            destination_kind="classic",
        )

        self.assertTrue(delivery.sent)
        self.assertEqual(len(self.telegram.photos), 1)
        self.assertIn("[Fresh] [Breakout]", str(self.telegram.photos[0]["caption"]))
        self.assertIn("Price: <b>100</b> • RSI: <b>28.00</b> • Score: <b>88/100</b>", str(self.telegram.photos[0]["caption"]))
        self.assertIn("Classic arrives about", str(self.telegram.photos[0]["caption"]))
        self.assertEqual(self.telegram.photos[0]["chat_id"], "classic-chat")

    async def test_classic_followup_uses_photo_and_delay_footer(self) -> None:
        delivery = await self.router.send_followup_to_chat(
            self._followup_result(),
            chat_id="classic-chat",
            destination_kind="classic",
        )

        self.assertTrue(delivery.sent)
        self.assertEqual(len(self.telegram.photos), 1)
        self.assertIn("[Follow-up] [Breakout]", str(self.telegram.photos[0]["caption"]))
        self.assertIn("Now: <b>103.5</b> • Alert: <b>100</b>", str(self.telegram.photos[0]["caption"]))
        self.assertIn("Result: <b>Favorable</b> • In our favor: <b>+3.50%</b>", str(self.telegram.photos[0]["caption"]))
        self.assertNotIn("What changed", str(self.telegram.photos[0]["caption"]))
        self.assertIn("Classic arrives about", str(self.telegram.photos[0]["caption"]))

    async def test_private_alert_omits_classic_delay_footer(self) -> None:
        delivery = await self.router.send_raw_alert_to_chat(
            self._alert_signal(),
            chat_id="private-chat",
            destination_kind="private",
        )

        self.assertTrue(delivery.sent)
        self.assertEqual(len(self.telegram.photos), 1)
        self.assertNotIn("Classic arrives about", str(self.telegram.photos[0]["caption"]))

    async def test_private_interactive_keyboard_includes_tradingview_link(self) -> None:
        markup = self.router._build_interactive_reply_markup(
            symbol="CLOUSDT",
            timeframe="15m",
            destination_kind="private",
            language_code="ru",
        )

        buttons = [
            button
            for row in markup["inline_keyboard"]
            for button in row
            if isinstance(button, dict)
        ]
        self.assertIn(
            {"text": "TradingView", "url": "https://www.tradingview.com/chart/?symbol=BINANCE%3ACLOUSDT.P"},
            buttons,
        )

    async def test_private_interactive_keyboard_uses_direct_binance_app_button(self) -> None:
        markup = self.router._build_interactive_reply_markup(
            symbol="CLOUSDT",
            timeframe="15m",
            destination_kind="private",
            language_code="ru",
        )

        buttons = [
            button
            for row in markup["inline_keyboard"]
            for button in row
            if isinstance(button, dict)
        ]
        app_buttons = [
            button
            for button in buttons
            if isinstance(button.get("url"), str)
            and str(button["url"]).startswith("https://app.binance.com/en/download?_dp=")
        ]
        self.assertTrue(app_buttons)


if __name__ == "__main__":
    unittest.main()
