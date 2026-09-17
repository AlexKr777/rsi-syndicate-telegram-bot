from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

import pandas as pd

from src.core.config import get_settings
from src.market.bollinger_scanner import BollingerScanner


class BollingerScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scanner = BollingerScanner(
            settings=get_settings(),
            binance_client=SimpleNamespace(),
            repository=SimpleNamespace(),
        )

    def test_classify_reentry_detects_long_short_and_no_signal(self) -> None:
        long_previous = pd.Series({"close": 95.0, "bb_lower": 96.0, "bb_upper": 104.0})
        long_current = pd.Series({"close": 97.0, "bb_lower": 96.5, "bb_upper": 104.5})
        short_previous = pd.Series({"close": 106.0, "bb_lower": 96.0, "bb_upper": 105.0})
        short_current = pd.Series({"close": 104.0, "bb_lower": 95.5, "bb_upper": 105.0})
        neutral_previous = pd.Series({"close": 100.0, "bb_lower": 96.0, "bb_upper": 104.0})
        neutral_current = pd.Series({"close": 101.0, "bb_lower": 96.5, "bb_upper": 104.5})

        self.assertEqual(self.scanner._classify_reentry(long_previous, long_current), "long")
        self.assertEqual(self.scanner._classify_reentry(short_previous, short_current), "short")
        self.assertIsNone(self.scanner._classify_reentry(neutral_previous, neutral_current))

    def test_classify_reentry_accepts_current_wick_rejection_back_inside_band(self) -> None:
        long_previous = pd.Series({"close": 99.6, "low": 99.4, "high": 100.2, "bb_lower": 99.2, "bb_upper": 104.0})
        long_current = pd.Series({"close": 100.1, "low": 98.7, "high": 100.4, "bb_lower": 99.0, "bb_upper": 104.0})
        short_previous = pd.Series({"close": 100.5, "low": 99.8, "high": 100.8, "bb_lower": 96.0, "bb_upper": 101.0})
        short_current = pd.Series({"close": 100.2, "low": 100.0, "high": 101.7, "bb_lower": 96.0, "bb_upper": 101.1})

        self.assertEqual(self.scanner._classify_reentry(long_previous, long_current), "long")
        self.assertEqual(self.scanner._classify_reentry(short_previous, short_current), "short")

    def test_build_signal_marks_bollinger_strategy_and_clamps_score(self) -> None:
        now = datetime.now(timezone.utc)
        frame = pd.DataFrame(
            [
                {
                    "close": 95.0,
                    "close_time": pd.Timestamp(now - timedelta(minutes=15)),
                    "rsi": 25.0,
                    "volume": 22_000.0,
                    "avg_volume_20": 18_000.0,
                    "atr": 1.4,
                    "atr_pct": 0.018,
                    "ema20": 98.0,
                    "ema50": 101.0,
                    "bb_mid": 100.0,
                    "bb_upper": 104.0,
                    "bb_lower": 96.0,
                    "volume_ratio": 1.4,
                    "bb_width": 8.0,
                },
                {
                    "close": 97.0,
                    "close_time": pd.Timestamp(now),
                    "rsi": 31.0,
                    "volume": 28_000.0,
                    "avg_volume_20": 18_500.0,
                    "atr": 1.5,
                    "atr_pct": 0.02,
                    "ema20": 98.5,
                    "ema50": 101.5,
                    "bb_mid": 100.0,
                    "bb_upper": 104.5,
                    "bb_lower": 96.5,
                    "volume_ratio": 1.6,
                    "bb_width": 8.0,
                },
            ],
            index=[pd.Timestamp(now - timedelta(minutes=30)), pd.Timestamp(now - timedelta(minutes=15))],
        )

        signal = self.scanner._build_signal(
            "BTCUSDT",
            frame,
            ticker=SimpleNamespace(
                last_price=97.4,
                price_change_percent=2.1,
                quote_volume=1_800_000.0,
                volume=0.0,
            ),
            direction="long",
        )

        assert signal is not None
        self.assertEqual(signal.direction, "long")
        self.assertEqual(signal.metadata["strategy_key"], "bollinger")
        self.assertEqual(signal.metadata["signal_model"], "bollinger_reentry")
        self.assertGreaterEqual(signal.score, 0)
        self.assertLessEqual(signal.score, 100)


if __name__ == "__main__":
    unittest.main()
