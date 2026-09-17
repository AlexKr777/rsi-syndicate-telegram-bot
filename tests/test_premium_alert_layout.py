from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd

from src.bot.formatters import format_alert_message, format_followup_message
from src.bot.interactive_alerts import InteractiveAlertService
from src.core.config import get_settings
from src.core.models import AlertSignal, FollowUpResult
from src.storage.models import AlertRecord


class PremiumAlertLayoutTests(unittest.TestCase):
    def test_premium_alert_layout_uses_clear_sections(self) -> None:
        closed_at = datetime(2026, 3, 30, 9, 15, tzinfo=timezone.utc)
        signal = AlertSignal(
            symbol="BTCUSDT",
            direction="oversold",
            timeframe="15m",
            candle_open_time=closed_at - timedelta(minutes=15),
            candle_close_time=closed_at,
            price=24120.0,
            rsi=31.4,
            day_change_pct=2.8,
            day_volume=54_000_000.0,
            quote_volume=54_000_000.0,
            last_candle_volume=0.0,
            avg_volume_20=0.0,
            atr=0.0,
            atr_pct=0.0,
            ema20=0.0,
            ema50=0.0,
            score=86,
            explanation="Momentum is trying to turn back up after a sharp flush.",
            metadata={
                "text_layout": "premium_readable",
                "strategy_key": "breakout",
                "setup_direction": "long",
                "signal_status": "fresh",
                "live_price": 24205.0,
                "live_rsi": 35.1,
                "closed_rsi": 31.4,
                "entry_zone_low": 24100.0,
                "entry_zone_high": 24250.0,
                "invalidation_price": 23840.0,
                "tp_price_primary": 24880.0,
                "market_regime_tag": "Trend Up",
                "setup_quality": "High",
                "interactive_reason_enabled": True,
                "explanation_short": "Momentum is stabilizing and buyers are defending the reclaim.",
                "why_received_text": "It matched your watchlist, direction filter, and score floor.",
            },
        )

        text = format_alert_message(signal, timezone.utc, "", language_code="en")
        lines = text.splitlines()

        self.assertIn("[Fresh] [Breakout]", text)
        self.assertIn("[Long]", text)
        self.assertIn("<b>Setup</b>", lines)
        self.assertIn("<b>Levels</b>", lines)
        self.assertIn("<b>Context</b>", lines)
        self.assertIn("<b>Why you received this</b>", lines)
        self.assertIn("Now: <b>", text)
        self.assertIn("Strategy: <b>Breakout</b>", text)
        self.assertIn("Trade direction: <b>Long</b>", text)
        self.assertIn("RSI / Score now: <b>31.40</b> / <b>86/100</b>", text)
        self.assertIn("RSI / Score at alert: <b>31.40</b> / <b>86/100</b>", text)
        self.assertIn("Quality: <b>High</b>", text)
        self.assertIn("Follow-up: <b>Enabled</b>", text)
        self.assertIn("Entry: <b>", text)
        self.assertIn("Invalidation: <b>", text)
        self.assertIn("Target zone: <b>", text)
        self.assertIn("24h: <b>+2.80%</b>", text)
        self.assertIn("Volume: <b>54.00M</b>", text)
        self.assertIn("Regime: <b>Trend Up</b>", text)
        self.assertIn("RSI live: <b>35.10</b>", text)
        self.assertLess(lines.index("<b>Setup</b>"), lines.index("<b>Levels</b>"))
        self.assertLess(lines.index("<b>Levels</b>"), lines.index("<b>Context</b>"))
        self.assertIn("not financial advice", text)
        self.assertIn("Manage risk independently", text)

    def test_simple_premium_alert_still_shows_levels_without_deep_context(self) -> None:
        closed_at = datetime(2026, 3, 30, 9, 15, tzinfo=timezone.utc)
        signal = AlertSignal(
            symbol="BTCUSDT",
            direction="oversold",
            timeframe="15m",
            candle_open_time=closed_at - timedelta(minutes=15),
            candle_close_time=closed_at,
            price=24120.0,
            rsi=31.4,
            day_change_pct=2.8,
            day_volume=54_000_000.0,
            quote_volume=54_000_000.0,
            last_candle_volume=0.0,
            avg_volume_20=0.0,
            atr=0.0,
            atr_pct=0.0,
            ema20=0.0,
            ema50=0.0,
            score=86,
            explanation="Momentum is trying to turn back up after a sharp flush.",
            metadata={
                "text_layout": "premium_readable",
                "display_mode": "simple",
                "strategy_key": "breakout",
                "setup_direction": "long",
                "signal_status": "fresh",
                "entry_zone_low": 24100.0,
                "entry_zone_high": 24250.0,
                "invalidation_price": 23840.0,
                "tp_price_primary": 24880.0,
                "market_regime_tag": "Trend Up",
                "why_received_text": "It matched your watchlist, direction filter, and score floor.",
            },
        )

        text = format_alert_message(signal, timezone.utc, "", language_code="en")

        self.assertIn("<b>Levels</b>", text)
        self.assertIn("Entry: <b>", text)
        self.assertIn("Invalidation: <b>", text)
        self.assertIn("Target zone: <b>", text)
        self.assertIn("<b>Risk</b>", text)
        self.assertNotIn("<b>Context</b>", text)
        self.assertNotIn("<b>Why you received this</b>", text)
        self.assertNotIn("Volume: <b>", text)

    def test_premium_followup_layout_stays_compact_and_readable(self) -> None:
        observed_at = datetime(2026, 3, 30, 11, 30, tzinfo=timezone.utc)
        result = FollowUpResult(
            alert_id=42,
            symbol="ETHUSDT",
            direction="overbought",
            timeframe="1h",
            alert_price=1880.0,
            current_price=1827.3,
            alert_rsi=74.6,
            current_rsi=61.2,
            move_pct=-2.8,
            summary="Price cooled off after the signal and the thesis is developing as expected.",
            score=84,
            observed_at=observed_at,
            stage="2h",
            favorable_move_pct=2.8,
            adverse_move_pct=0.0,
            thesis_result_state="favorable",
            metadata={
                "text_layout": "premium_readable",
                "strategy_key": "breakout",
            },
        )

        text = format_followup_message(result, timezone.utc, language_code="en")
        lines = text.splitlines()

        self.assertIn("[Follow-up] [Breakout]", text)
        self.assertIn("Follow-up · ETHUSDT · 1h", text)
        self.assertIn("<b>Update</b>", lines)
        self.assertIn("<b>Timing</b>", lines)
        self.assertIn("Now: <b>", text)
        self.assertIn("Alert: <b>", text)
        self.assertIn("Move since alert: <b>-2.80%</b>", text)
        self.assertIn("RSI: <b>74.60", text)
        self.assertIn("Result: <b>Favorable</b>", text)
        self.assertIn("In our favor: <b>+2.80%</b>", text)
        self.assertIn("Stage: <b>2h</b>", text)
        self.assertLess(lines.index("<b>Update</b>"), lines.index("<b>Timing</b>"))
        self.assertIn("Moved in the direction of the signal", text)
        self.assertIn("Past results do not guarantee future results", text)

    def test_followup_prefers_explicit_lifecycle_outcome_over_ambiguous_move_label(self) -> None:
        observed_at = datetime(2026, 3, 30, 11, 30, tzinfo=timezone.utc)
        result = FollowUpResult(
            alert_id=43,
            symbol="BTCUSDT",
            direction="oversold",
            timeframe="1h",
            alert_price=100.0,
            current_price=101.0,
            alert_rsi=29.0,
            current_rsi=34.0,
            move_pct=1.0,
            summary="The setup no longer meets its original invalidation rule.",
            score=78,
            observed_at=observed_at,
            stage="4h",
            favorable_move_pct=1.0,
            adverse_move_pct=0.0,
            thesis_result_state="favorable",
            metadata={
                "text_layout": "premium_readable",
                "strategy_key": "breakout",
                "signal_status": "invalidated",
            },
        )

        text = format_followup_message(result, timezone.utc, language_code="en")

        self.assertIn("Outcome: <b>Invalidated</b>", text)
        self.assertLess(text.index("Outcome: <b>Invalidated</b>"), text.index("<b>Update</b>"))
        self.assertIn("Setup invalidated", text)
        self.assertNotIn("Outcome: <b>Target reached</b>", text)

    def test_premium_okak_layout_can_show_historical_resistance_block(self) -> None:
        closed_at = datetime(2026, 4, 1, 10, 15, tzinfo=timezone.utc)
        signal = AlertSignal(
            symbol="QTUMUSDT",
            direction="overbought",
            timeframe="15m",
            candle_open_time=closed_at - timedelta(minutes=15),
            candle_close_time=closed_at,
            price=5.05,
            rsi=82.6,
            day_change_pct=7.8,
            day_volume=7_250_000.0,
            quote_volume=7_250_000.0,
            last_candle_volume=0.0,
            avg_volume_20=0.0,
            atr=0.0,
            atr_pct=0.0,
            ema20=0.0,
            ema50=0.0,
            score=93,
            explanation="OKAK shortlist with strong score and momentum.",
            metadata={
                "text_layout": "premium_readable",
                "strategy_key": "okak",
                "setup_direction": "short",
                "signal_status": "fresh",
                "live_price": 5.06,
                "closed_rsi": 82.6,
                "okak_criteria_summary": "RSI 76+, score 90+",
                "explanation_short": "OKAK shortlist: RSI 76+, score 90+",
                "historical_resistance_variant": "detailed",
                "historical_resistance_available": True,
                "historical_resistance_zone_low": 5.18,
                "historical_resistance_zone_high": 5.24,
                "historical_resistance_zone_price": 5.21,
                "historical_resistance_distance_pct": 2.96,
                "historical_resistance_touch_count": 3,
                "historical_resistance_avg_rejection_pct": 5.8,
                "historical_resistance_quality": "strong",
                "historical_resistance_timeframes": ["4h", "1h"],
                "historical_resistance_highest_peak_price": 5.58,
                "historical_resistance_highest_peak_timeframe": "4h",
                "historical_resistance_highest_peak_distance_pct": 10.5,
            },
        )

        text = format_alert_message(signal, timezone.utc, "", language_code="ru")

        self.assertIn("<b>🧭 История 1h / 4h</b>", text)
        self.assertIn("🎯 Историческая зона сопротивления: <b>5.18 - 5.24</b>", text)
        self.assertIn("📍 Дистанция до зоны: <b>+2.96%</b>", text)
        self.assertIn("🗻 Самый высокий импульсный пик", text)
        self.assertIn("<b>5.58</b>", text)
        self.assertIn("Подтверждение: <b>4h / 1h</b>", text)
        self.assertIn("Подтвержденных отбоев: <b>3</b>", text)
        self.assertIn("Средний отбой: <b>-5.80%</b>", text)
        self.assertIn("Сила зоны: <b>Сильная</b>", text)

    def test_premium_okak_layout_keeps_history_accent_when_zone_is_missing(self) -> None:
        closed_at = datetime(2026, 4, 1, 10, 15, tzinfo=timezone.utc)
        signal = AlertSignal(
            symbol="QTUMUSDT",
            direction="overbought",
            timeframe="15m",
            candle_open_time=closed_at - timedelta(minutes=15),
            candle_close_time=closed_at,
            price=5.05,
            rsi=82.6,
            day_change_pct=7.8,
            day_volume=7_250_000.0,
            quote_volume=7_250_000.0,
            last_candle_volume=0.0,
            avg_volume_20=0.0,
            atr=0.0,
            atr_pct=0.0,
            ema20=0.0,
            ema50=0.0,
            score=93,
            explanation="OKAK shortlist with strong score and momentum.",
            metadata={
                "text_layout": "premium_readable",
                "strategy_key": "okak",
                "setup_direction": "short",
                "signal_status": "fresh",
                "live_price": 5.06,
                "closed_rsi": 82.6,
                "explanation_short": "OKAK shortlist: RSI 76+, score 90+",
                "historical_resistance_variant": "detailed",
                "historical_resistance_available": False,
                "historical_resistance_highest_peak_price": 5.58,
                "historical_resistance_highest_peak_timeframe": "4h",
                "historical_resistance_highest_peak_distance_pct": 10.5,
            },
        )

        text = format_alert_message(signal, timezone.utc, "", language_code="ru")

        self.assertIn("<b>🧭 История 1h / 4h</b>", text)
        self.assertIn("⚪ Сильная зона сопротивления на 1h/4h рядом не найдена.", text)
        self.assertIn("🗻 Самый высокий импульсный пик", text)

    def test_premium_okak_layout_can_highlight_focus_entry_line(self) -> None:
        closed_at = datetime(2026, 4, 1, 10, 15, tzinfo=timezone.utc)
        signal = AlertSignal(
            symbol="QTUMUSDT",
            direction="overbought",
            timeframe="15m",
            candle_open_time=closed_at - timedelta(minutes=15),
            candle_close_time=closed_at,
            price=5.05,
            rsi=82.6,
            day_change_pct=7.8,
            day_volume=7_250_000.0,
            quote_volume=7_250_000.0,
            last_candle_volume=0.0,
            avg_volume_20=0.0,
            atr=0.0,
            atr_pct=0.0,
            ema20=0.0,
            ema50=0.0,
            score=93,
            explanation="OKAK shortlist with strong score and momentum.",
            metadata={
                "text_layout": "premium_readable",
                "strategy_key": "okak",
                "setup_direction": "short",
                "signal_status": "fresh",
                "live_price": 5.06,
                "closed_rsi": 82.6,
                "explanation_short": "OKAK shortlist: RSI 76+, score 90+",
                "historical_resistance_variant": "focus",
                "historical_resistance_available": True,
                "historical_resistance_zone_price": 5.21,
            },
        )

        text = format_alert_message(signal, timezone.utc, "", language_code="ru")

        self.assertIn("🎯 Стоит смотреть заход у: <b>5.21</b>", text)

    def test_premium_ekek_layout_starts_with_wave_header(self) -> None:
        closed_at = datetime(2026, 4, 3, 10, 15, tzinfo=timezone.utc)
        signal = AlertSignal(
            symbol="SOLUSDT",
            direction="overbought",
            timeframe="15m",
            candle_open_time=closed_at - timedelta(minutes=15),
            candle_close_time=closed_at,
            price=182.4,
            rsi=79.4,
            day_change_pct=8.4,
            day_volume=75_000_000.0,
            quote_volume=75_000_000.0,
            last_candle_volume=2_800_000.0,
            avg_volume_20=1_400_000.0,
            atr=2.4,
            atr_pct=0.008,
            ema20=176.1,
            ema50=170.4,
            score=91,
            explanation="EKEK impulse shortlist with a sharp burst.",
            metadata={
                "text_layout": "premium_readable",
                "strategy_key": "ekek",
                "setup_direction": "short",
                "signal_status": "fresh",
                "live_price": 182.8,
                "closed_rsi": 79.4,
                "live_rsi": 78.9,
                "explanation_short": "EKEK impulse shortlist: recent 3-candle burst, move concentrated late",
            },
        )

        text = format_alert_message(signal, timezone.utc, "", language_code="en")

        self.assertIn("<b>🌊 SOLUSDT • 15m</b>", text)
        self.assertIn("[Fresh] [EKEK]", text)
        self.assertNotIn("<b>История 1h / 4h</b>", text)

    def test_interactive_snapshot_build_preserves_premium_layout_flag(self) -> None:
        service = InteractiveAlertService(
            settings=get_settings(),
            repository=SimpleNamespace(),
            telegram_client=SimpleNamespace(),
            binance_client=SimpleNamespace(),
            chart_renderer=SimpleNamespace(),
            prepared_feature_service=SimpleNamespace(),
        )
        open_time = datetime(2026, 3, 30, 9, 0, tzinfo=timezone.utc)
        frame = pd.DataFrame(
            {
                "close_time": [open_time + timedelta(minutes=15)],
                "close": [24205.0],
                "volume": [1_800_000.0],
                "avg_volume_20": [1_500_000.0],
                "atr": [32.0],
                "atr_pct": [0.013],
                "ema20": [24160.0],
                "ema50": [24090.0],
                "rsi": [35.1],
                "volume_ratio": [1.2],
            },
            index=[open_time],
        )
        alert_record = AlertRecord(
            id=7,
            symbol="BTCUSDT",
            direction="long",
            timeframe="15m",
            candle_open_time=open_time,
            candle_close_time=open_time + timedelta(minutes=15),
            alert_price=24120.0,
            alert_rsi=31.4,
            day_change_pct=2.8,
            day_volume=54_000_000.0,
            score=86,
            alert_sent_at=open_time + timedelta(minutes=16),
            followup_due_at=open_time + timedelta(hours=2),
            followup_sent_at=None,
            lab_message_id=None,
            metadata={"strategy_key": "breakout", "language_code": "en"},
            strategy_key="breakout",
        )
        ticker = SimpleNamespace(
            last_price=24205.0,
            price_change_percent=2.8,
            quote_volume=54_000_000.0,
            volume=54_000_000.0,
        )

        signal = service._build_signal(
            symbol="BTCUSDT",
            timeframe="15m",
            frame=frame,
            ticker=ticker,
            alert_record=alert_record,
            origin_metadata={
                "text_layout": "premium_readable",
                "setup_direction": "long",
                "context_text": "Buyers defended the level and the reclaim is still valid.",
            },
        )

        self.assertEqual(signal.metadata["text_layout"], "premium_readable")
        self.assertEqual(signal.metadata["setup_direction"], "long")
        self.assertEqual(signal.metadata["alert_rsi"], 31.4)
        self.assertEqual(signal.metadata["alert_score"], 86)
        text = format_alert_message(signal, timezone.utc, "", language_code="en")
        self.assertIn("RSI / Score now: <b>35.10</b>", text)
        self.assertIn("RSI / Score at alert: <b>31.40</b> / <b>86/100</b>", text)

    def test_interactive_snapshot_preserves_historical_resistance_metadata(self) -> None:
        service = InteractiveAlertService(
            settings=get_settings(),
            repository=SimpleNamespace(),
            telegram_client=SimpleNamespace(),
            binance_client=SimpleNamespace(),
            chart_renderer=SimpleNamespace(),
            prepared_feature_service=SimpleNamespace(),
        )
        open_time = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
        frame = pd.DataFrame(
            {
                "close_time": [open_time + timedelta(minutes=15)],
                "close": [5.06],
                "volume": [850_000.0],
                "avg_volume_20": [700_000.0],
                "atr": [0.12],
                "atr_pct": [0.023],
                "ema20": [4.98],
                "ema50": [4.82],
                "rsi": [82.6],
                "volume_ratio": [1.2],
            },
            index=[open_time],
        )
        alert_record = AlertRecord(
            id=21,
            symbol="QTUMUSDT",
            direction="overbought",
            timeframe="15m",
            candle_open_time=open_time,
            candle_close_time=open_time + timedelta(minutes=15),
            alert_price=5.05,
            alert_rsi=82.6,
            day_change_pct=7.8,
            day_volume=7_250_000.0,
            score=93,
            alert_sent_at=open_time + timedelta(minutes=16),
            followup_due_at=open_time + timedelta(hours=2),
            followup_sent_at=None,
            lab_message_id=None,
            metadata={"strategy_key": "okak", "language_code": "ru"},
            strategy_key="okak",
        )
        ticker = SimpleNamespace(
            last_price=5.06,
            price_change_percent=7.8,
            quote_volume=7_250_000.0,
            volume=7_250_000.0,
        )

        signal = service._build_signal(
            symbol="QTUMUSDT",
            timeframe="15m",
            frame=frame,
            ticker=ticker,
            alert_record=alert_record,
            origin_metadata={
                "text_layout": "premium_readable",
                "historical_resistance_variant": "detailed",
                "historical_resistance_available": True,
                "historical_resistance_zone_low": 5.18,
                "historical_resistance_zone_high": 5.24,
                "historical_resistance_zone_price": 5.21,
                "historical_resistance_distance_pct": 2.96,
                "historical_resistance_touch_count": 3,
                "historical_resistance_avg_rejection_pct": 5.8,
                "historical_resistance_quality": "strong",
                "historical_resistance_timeframes": ["4h", "1h"],
                "historical_resistance_highest_peak_price": 5.58,
                "historical_resistance_highest_peak_timeframe": "4h",
                "historical_resistance_highest_peak_distance_pct": 10.5,
            },
        )

        self.assertEqual(signal.metadata["historical_resistance_variant"], "detailed")
        self.assertEqual(signal.metadata["historical_resistance_zone_price"], 5.21)
        self.assertEqual(signal.metadata["historical_resistance_timeframes"], ["4h", "1h"])
        self.assertEqual(signal.metadata["historical_resistance_highest_peak_price"], 5.58)

    def test_interactive_private_keyboard_includes_tradingview_button(self) -> None:
        service = InteractiveAlertService(
            settings=get_settings(),
            repository=SimpleNamespace(),
            telegram_client=SimpleNamespace(),
            binance_client=SimpleNamespace(),
            chart_renderer=SimpleNamespace(),
            prepared_feature_service=SimpleNamespace(),
        )

        markup = service._build_alert_keyboard(
            symbol="CLOUSDT",
            selected_timeframe="15m",
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


if __name__ == "__main__":
    unittest.main()
