from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd

from src.bot.formatters import format_alert_message
from src.bot.interactive_alerts import InteractiveAlertService
from src.core.config import get_settings
from src.core.models import AlertSignal
from src.storage.models import AlertRecord


class SignalDirectionDisplayTests(unittest.TestCase):
    def test_format_alert_message_shows_setup_direction_and_current_rsi_status(self) -> None:
        closed_at = datetime(2026, 3, 17, 17, 29, 59, tzinfo=timezone.utc)
        signal = AlertSignal(
            symbol="BABYUSDT",
            direction="neutral",
            timeframe="15m",
            candle_open_time=closed_at - timedelta(minutes=15),
            candle_close_time=closed_at,
            price=0.01404,
            rsi=64.62,
            day_change_pct=4.88,
            day_volume=12_050_000.0,
            quote_volume=12_050_000.0,
            last_candle_volume=0.0,
            avg_volume_20=0.0,
            atr=0.0,
            atr_pct=0.0,
            ema20=0.0,
            ema50=0.0,
            score=44,
            explanation="Bullish trend held and price reacted from EMA50 on 15m.",
            metadata={
                "setup_direction": "long",
                "strategy_key": "trend_pullback",
                "live_price": 0.01408,
                "live_rsi": 64.63,
                "closed_rsi": 64.62,
                "context_text": "Bullish trend held and price reacted from EMA50 on 15m. The confirmation candle closed back in favor of the long continuation.",
            },
        )

        text = format_alert_message(signal, timezone.utc, "", language_code="ru")
        lines = text.splitlines()

        self.assertIn("Направление: <b>Лонг</b>", text)
        self.assertIn("Статус RSI: <b>Нейтрально</b>", text)
        self.assertIn("<b>0.01408</b> • RSI: <b>64.62</b> • Score: <b>44/100</b>", lines[1])
        self.assertNotIn("Bias:", text)

    def test_interactive_build_signal_preserves_original_setup_direction(self) -> None:
        settings = get_settings()
        service = InteractiveAlertService(
            settings=settings,
            repository=SimpleNamespace(),
            telegram_client=SimpleNamespace(),
            binance_client=SimpleNamespace(),
            chart_renderer=SimpleNamespace(),
            prepared_feature_service=SimpleNamespace(),
        )
        open_time = datetime(2026, 3, 17, 17, 15, tzinfo=timezone.utc)
        frame = pd.DataFrame(
            {
                "close_time": [open_time + timedelta(minutes=15)],
                "close": [0.01404],
                "volume": [1_200_000.0],
                "avg_volume_20": [1_100_000.0],
                "atr": [0.0002],
                "atr_pct": [0.014],
                "ema20": [0.01390],
                "ema50": [0.01370],
                "rsi": [64.62],
                "volume_ratio": [1.09],
            },
            index=[open_time],
        )
        alert_record = AlertRecord(
            id=11,
            symbol="BABYUSDT",
            direction="long",
            timeframe="15m",
            candle_open_time=open_time,
            candle_close_time=open_time + timedelta(minutes=15),
            alert_price=0.01404,
            alert_rsi=64.62,
            day_change_pct=4.88,
            day_volume=12_050_000.0,
            score=44,
            alert_sent_at=open_time + timedelta(minutes=16),
            followup_due_at=open_time + timedelta(hours=2),
            followup_sent_at=None,
            lab_message_id=None,
            metadata={"strategy_key": "trend_pullback", "language_code": "ru"},
            strategy_key="trend_pullback",
        )
        ticker = SimpleNamespace(
            last_price=0.01408,
            price_change_percent=4.88,
            quote_volume=12_050_000.0,
            volume=12_050_000.0,
        )

        signal = service._build_signal(
            symbol="BABYUSDT",
            timeframe="15m",
            frame=frame,
            ticker=ticker,
            alert_record=alert_record,
            origin_metadata={
                "setup_direction": "long",
                "context_text": "Bullish trend held and price reacted from EMA50 on 15m. The confirmation candle closed back in favor of the long continuation.",
            },
        )

        self.assertEqual(signal.direction, "neutral")
        self.assertEqual(signal.metadata["setup_direction"], "long")
        self.assertEqual(signal.metadata["strategy_key"], "trend_pullback")
        self.assertIn("long continuation", str(signal.metadata["context_text"]))

    def test_format_alert_message_highlights_okak_header_metrics(self) -> None:
        closed_at = datetime(2026, 3, 17, 17, 29, 59, tzinfo=timezone.utc)
        signal = AlertSignal(
            symbol="SOLUSDT",
            direction="overbought",
            timeframe="15m",
            candle_open_time=closed_at - timedelta(minutes=15),
            candle_close_time=closed_at,
            price=178.4,
            rsi=79.8,
            day_change_pct=6.2,
            day_volume=58_000_000.0,
            quote_volume=58_000_000.0,
            last_candle_volume=0.0,
            avg_volume_20=0.0,
            atr=0.0,
            atr_pct=0.0,
            ema20=0.0,
            ema50=0.0,
            score=93,
            explanation="OKAK shortlist.",
            metadata={
                "strategy_key": "okak",
                "setup_direction": "short",
                "closed_rsi": 79.8,
                "okak_criteria_summary": "volume 5-20M / 50M+, RSI 76+, score 90+",
                "context_text": "OKAK shortlist with high RSI, strong score, and preferred liquidity.",
            },
        )

        text = format_alert_message(signal, timezone.utc, "", language_code="ru")
        lines = text.splitlines()

        self.assertIn("СТРАТЕГИЯ OKAK", text)
        self.assertIn("<b>178.4</b> • RSI: <b>79.80</b> • Score: <b>93/100</b> •", lines[2])
        self.assertIn("58.00M", lines[2])
        self.assertIn("RSI: <b>79.80</b>", text)
        self.assertIn("Score: <b>93/100</b>", text)
        self.assertIn("Объем: <b>58.00M</b>", text)
        self.assertIn("Совпало по OKAK", text)


if __name__ == "__main__":
    unittest.main()
