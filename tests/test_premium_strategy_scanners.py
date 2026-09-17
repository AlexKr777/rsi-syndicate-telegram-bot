from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pandas as pd

from src.market.breakout_scanner import BreakoutScanner
from src.market.daily_rsi_80_scanner import DailyRSI80Scanner
from src.market.ekek_scanner import EkekScanner
from src.market.false_breakout_scanner import FalseBreakoutScanner
from src.market.okak_scanner import OkakScanner
from src.market.rsi_bollinger_touch_scanner import RSIBollingerTouchScanner
from src.market.rsi_bollinger_mr_scanner import RSIBollingerMeanReversionScanner
from src.market.rsi_divergence_scanner import RSIDivergenceScanner
from src.market.trend_pullback_scanner import TrendPullbackScanner
from src.market.vwap_scanner import VWAPScanner


def _frame(*rows: dict[str, float | int | str | pd.Timestamp]) -> pd.DataFrame:
    base_time = pd.Timestamp("2026-03-16 00:00:00", tz="UTC")
    index: list[pd.Timestamp] = []
    payload: list[dict[str, object]] = []
    next_time = base_time
    for raw_row in rows:
        row = dict(raw_row)
        timestamp = row.pop("_ts", None)
        candle_time = timestamp if isinstance(timestamp, pd.Timestamp) else next_time
        close_time = candle_time + pd.Timedelta(minutes=15) - pd.Timedelta(milliseconds=1)
        payload.append(
            {
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1_000.0,
                "avg_volume_20": 900.0,
                "atr": 1.0,
                "atr_pct": 0.01,
                "ema20": 100.0,
                "ema50": 99.0,
                "rsi": 50.0,
                "volume_ratio": 1.3,
                "bb_upper": 103.0,
                "bb_lower": 97.0,
                "bb_width": 6.0,
                "close_time": close_time,
                **row,
            }
        )
        index.append(candle_time)
        next_time = candle_time + pd.Timedelta(minutes=15)
    return pd.DataFrame(payload, index=pd.DatetimeIndex(index))


class PremiumStrategyScannerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.settings = SimpleNamespace(
            scan_timeframe="15m",
            klines_limit=120,
            rsi_length=14,
            rsi_oversold=30.0,
            rsi_overbought=70.0,
        )
        self.binance = SimpleNamespace(get_klines=AsyncMock(return_value=pd.DataFrame()))
        self.repository = SimpleNamespace(alert_exists_for_candle=AsyncMock(return_value=False))
        self.ticker = SimpleNamespace(last_price=100.5, price_change_percent=1.2, quote_volume=12_000_000.0, volume=120_000.0)

    async def test_breakout_scanner_prioritizes_daily_over_local(self) -> None:
        scanner = BreakoutScanner(self.settings, self.binance, self.repository)
        rows: list[dict[str, object]] = []
        start = pd.Timestamp("2026-03-15 20:00:00", tz="UTC")
        for index in range(25):
            candle_time = start + pd.Timedelta(minutes=15 * index)
            high = 101.0
            if candle_time.date().isoformat() == "2026-03-15" and index == 6:
                high = 101.8
            rows.append(
                {
                    "_ts": candle_time,
                    "open": 100.2,
                    "high": high,
                    "low": 99.8,
                    "close": 100.4,
                }
            )
        rows.append(
            {
                "_ts": start + pd.Timedelta(minutes=15 * 25),
                "open": 100.7,
                "high": 102.7,
                "low": 100.4,
                "close": 102.4,
            }
        )
        enriched = _frame(*rows)
        with (
            patch("src.market.breakout_scanner.enrich_klines", return_value=enriched),
            patch("src.market.breakout_scanner.calculate_live_rsi", return_value=58.0),
        ):
            signal = await scanner._scan_symbol("BTCUSDT", self.ticker)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.direction, "long")
        self.assertEqual(signal.metadata["breakout_type"], "daily")
        self.assertEqual(signal.metadata["strategy_key"], "breakout")
        self.assertGreaterEqual(signal.score, 0)
        self.assertLessEqual(signal.score, 100)

    async def test_breakout_scanner_keeps_pre_0800_breakout_as_local_not_asia(self) -> None:
        scanner = BreakoutScanner(self.settings, self.binance, self.repository)
        rows: list[dict[str, object]] = []
        start = pd.Timestamp("2026-03-16 01:00:00", tz="UTC")
        for index in range(24):
            rows.append(
                {
                    "_ts": start + pd.Timedelta(minutes=15 * index),
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.8,
                    "close": 100.2,
                    "atr": 0.3,
                }
            )
        rows.append(
            {
                "_ts": pd.Timestamp("2026-03-16 07:00:00", tz="UTC"),
                "open": 100.4,
                "high": 102.3,
                "low": 100.1,
                "close": 102.0,
                "atr": 0.3,
            }
        )
        enriched = _frame(*rows)
        with (
            patch("src.market.breakout_scanner.enrich_klines", return_value=enriched),
            patch("src.market.breakout_scanner.calculate_live_rsi", return_value=56.0),
        ):
            signal = await scanner._scan_symbol("ETHUSDT", self.ticker)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.metadata["breakout_type"], "local")

    async def test_breakout_scanner_detects_consolidation_short(self) -> None:
        scanner = BreakoutScanner(self.settings, self.binance, self.repository)
        rows: list[dict[str, object]] = []
        start = pd.Timestamp("2026-03-16 09:00:00", tz="UTC")
        for index in range(24):
            rows.append(
                {
                    "_ts": start + pd.Timedelta(minutes=15 * index),
                    "open": 100.05,
                    "high": 100.2,
                    "low": 99.8,
                    "close": 100.0,
                    "atr": 0.5,
                }
            )
        rows.append(
            {
                "_ts": start + pd.Timedelta(minutes=15 * 24),
                "open": 99.95,
                "high": 100.0,
                "low": 99.1,
                "close": 99.3,
                "atr": 0.5,
            }
        )
        enriched = _frame(*rows)
        with (
            patch("src.market.breakout_scanner.enrich_klines", return_value=enriched),
            patch("src.market.breakout_scanner.calculate_live_rsi", return_value=43.0),
        ):
            signal = await scanner._scan_symbol("SOLUSDT", self.ticker)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.direction, "short")
        self.assertEqual(signal.metadata["breakout_type"], "consolidation")

    async def test_trend_pullback_scanner_prefers_ema50_touch(self) -> None:
        scanner = TrendPullbackScanner(self.settings, self.binance, self.repository)
        enriched = _frame(
            {"close": 100.0},
            {"close": 101.0},
            {
                "open": 104.0,
                "high": 107.0,
                "low": 100.6,
                "close": 106.0,
                "ema20": 103.0,
                "ema50": 101.0,
            },
        )
        with (
            patch("src.market.trend_pullback_scanner.enrich_klines", return_value=enriched),
            patch("src.market.trend_pullback_scanner.calculate_live_rsi", return_value=60.0),
        ):
            signal = await scanner._scan_symbol("BTCUSDT", self.ticker)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.direction, "long")
        self.assertEqual(signal.metadata["touched_ema"], 50)
        self.assertEqual(signal.metadata["ema_basis"], "ema50")

    async def test_trend_pullback_scanner_requires_confirmation_candle(self) -> None:
        scanner = TrendPullbackScanner(self.settings, self.binance, self.repository)
        enriched = _frame(
            {"close": 100.0},
            {"close": 99.0},
            {
                "open": 96.0,
                "high": 100.4,
                "low": 95.7,
                "close": 97.0,
                "ema20": 98.0,
                "ema50": 99.0,
            },
        )
        with patch("src.market.trend_pullback_scanner.enrich_klines", return_value=enriched):
            signal = await scanner._scan_symbol("ETHUSDT", self.ticker)
        self.assertIsNone(signal)

    async def test_rsi_bollinger_mean_reversion_requires_rsi_gate(self) -> None:
        scanner = RSIBollingerMeanReversionScanner(self.settings, self.binance, self.repository)
        enriched = _frame(
            {"close": 97.2, "bb_lower": 97.5, "bb_upper": 103.0, "rsi": 28.0},
            {
                "close": 98.0,
                "bb_lower": 97.6,
                "bb_upper": 103.0,
                "rsi": 35.0,
                "ema20": 98.5,
                "ema50": 98.0,
            },
        )
        with patch("src.market.rsi_bollinger_mr_scanner.enrich_klines", return_value=enriched):
            signal = await scanner._scan_symbol("BNBUSDT", self.ticker)
        self.assertIsNone(signal)

    async def test_rsi_bollinger_mean_reversion_detects_short_and_bounds_score(self) -> None:
        scanner = RSIBollingerMeanReversionScanner(self.settings, self.binance, self.repository)
        enriched = _frame(
            {"close": 103.4, "bb_upper": 103.0, "bb_lower": 97.0, "rsi": 74.0},
            {
                "close": 102.6,
                "bb_upper": 103.0,
                "bb_lower": 97.2,
                "bb_width": 5.8,
                "rsi": 76.0,
                "ema20": 103.0,
                "ema50": 103.4,
            },
        )
        with (
            patch("src.market.rsi_bollinger_mr_scanner.enrich_klines", return_value=enriched),
            patch("src.market.rsi_bollinger_mr_scanner.calculate_live_rsi", return_value=71.0),
        ):
            signal = await scanner._scan_symbol("XRPUSDT", self.ticker)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.direction, "short")
        self.assertGreaterEqual(signal.score, 0)
        self.assertLessEqual(signal.score, 100)

    async def test_rsi_bollinger_touch_detects_long_with_anti_sideways_filter(self) -> None:
        scanner = RSIBollingerTouchScanner(self.settings, self.binance, self.repository)
        enriched = _frame(
            {"close": 101.4, "low": 100.8, "high": 102.0, "ema20": 101.8, "ema50": 100.6, "rsi": 44.0},
            {"close": 100.3, "low": 99.3, "high": 101.0, "ema20": 101.0, "ema50": 100.0, "rsi": 38.0},
            {"close": 98.2, "low": 97.2, "high": 99.6, "ema20": 100.0, "ema50": 99.2, "rsi": 28.0, "atr_pct": 0.012, "volume_ratio": 1.5},
        )
        bb_mid = pd.Series([100.1, 100.0, 100.0], index=enriched.index)
        bb_upper = pd.Series([103.0, 103.0, 103.0], index=enriched.index)
        bb_lower = pd.Series([97.0, 97.0, 97.4], index=enriched.index)
        with (
            patch("src.market.rsi_bollinger_touch_scanner.enrich_klines", return_value=enriched),
            patch(
                "src.market.rsi_bollinger_touch_scanner.calculate_bollinger_bands",
                return_value=(bb_mid, bb_upper, bb_lower),
            ) as mock_bands,
            patch("src.market.rsi_bollinger_touch_scanner.calculate_live_rsi", return_value=29.1),
        ):
            signal = await scanner._scan_symbol("AVAXUSDT", self.ticker)
        self.assertIsNotNone(signal)
        assert signal is not None
        mock_bands.assert_called_once()
        _, kwargs = mock_bands.call_args
        self.assertEqual(kwargs["length"], 30)
        self.assertEqual(kwargs["num_std"], 2.05)
        self.assertEqual(signal.direction, "long")
        self.assertEqual(signal.metadata["strategy_key"], "rsi_bollinger_touch")
        self.assertEqual(signal.metadata["bb_length"], 30)
        self.assertEqual(signal.metadata["bb_stddev"], 2.05)
        self.assertEqual(signal.metadata["anti_sideways_state"], "directional")
        self.assertGreaterEqual(signal.score, 0)
        self.assertLessEqual(signal.score, 100)

    async def test_rsi_bollinger_touch_rejects_sideways_market(self) -> None:
        scanner = RSIBollingerTouchScanner(self.settings, self.binance, self.repository)
        enriched = _frame(
            {"close": 100.2, "low": 100.0, "high": 100.7, "ema20": 100.14, "ema50": 100.02, "rsi": 41.0},
            {"close": 100.15, "low": 99.98, "high": 100.6, "ema20": 100.12, "ema50": 100.01, "rsi": 36.0},
            {"close": 100.1, "low": 99.85, "high": 100.45, "ema20": 100.11, "ema50": 100.00, "rsi": 28.0, "atr_pct": 0.003, "volume_ratio": 1.05},
        )
        bb_mid = pd.Series([100.0, 100.0, 100.0], index=enriched.index)
        bb_upper = pd.Series([100.8, 100.8, 100.8], index=enriched.index)
        bb_lower = pd.Series([99.2, 99.2, 99.9], index=enriched.index)
        with (
            patch("src.market.rsi_bollinger_touch_scanner.enrich_klines", return_value=enriched),
            patch("src.market.rsi_bollinger_touch_scanner.calculate_bollinger_bands", return_value=(bb_mid, bb_upper, bb_lower)),
        ):
            signal = await scanner._scan_symbol("NEARUSDT", self.ticker)
        self.assertIsNone(signal)

    async def test_rsi_bollinger_touch_detects_prior_touch_with_current_confirmation(self) -> None:
        scanner = RSIBollingerTouchScanner(self.settings, self.binance, self.repository)
        enriched = _frame(
            {"close": 101.4, "low": 100.7, "high": 102.0, "ema20": 101.8, "ema50": 100.6, "rsi": 45.0},
            {"close": 98.1, "low": 96.9, "high": 99.4, "ema20": 100.6, "ema50": 99.8, "rsi": 28.0, "atr_pct": 0.011, "volume_ratio": 1.45},
            {"close": 99.3, "low": 97.4, "high": 100.4, "ema20": 100.0, "ema50": 99.5, "rsi": 33.0, "atr_pct": 0.012, "volume_ratio": 1.4},
        )
        bb_mid = pd.Series([100.2, 100.0, 99.9], index=enriched.index)
        bb_upper = pd.Series([103.2, 103.0, 102.8], index=enriched.index)
        bb_lower = pd.Series([97.4, 97.2, 97.3], index=enriched.index)
        with (
            patch("src.market.rsi_bollinger_touch_scanner.enrich_klines", return_value=enriched),
            patch("src.market.rsi_bollinger_touch_scanner.calculate_bollinger_bands", return_value=(bb_mid, bb_upper, bb_lower)),
            patch("src.market.rsi_bollinger_touch_scanner.calculate_live_rsi", return_value=34.0),
        ):
            signal = await scanner._scan_symbol("ARBUSDT", self.ticker)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.direction, "long")
        self.assertFalse(signal.metadata["touch_is_current_candle"])

    async def test_daily_rsi_80_scanner_detects_closed_daily_overheat(self) -> None:
        scanner = DailyRSI80Scanner(self.settings, self.binance, self.repository)
        enriched = _frame(
            {"close": 100.0, "ema20": 98.0, "ema50": 95.0, "rsi": 74.0, "atr_pct": 0.01, "volume_ratio": 1.1},
            {"close": 108.0, "ema20": 101.0, "ema50": 97.0, "rsi": 82.4, "atr_pct": 0.018, "volume_ratio": 1.6},
        )
        with (
            patch("src.market.daily_rsi_80_scanner.enrich_klines", return_value=enriched),
            patch("src.market.daily_rsi_80_scanner.calculate_live_rsi", return_value=81.9),
        ):
            signal = await scanner._scan_symbol("BTCUSDT", self.ticker)

        self.assertIsNotNone(signal)
        assert signal is not None
        self.binance.get_klines.assert_awaited_once_with(symbol="BTCUSDT", interval="1d", limit=self.settings.klines_limit)
        self.assertEqual(signal.timeframe, "1d")
        self.assertEqual(signal.direction, "short")
        self.assertEqual(signal.metadata["strategy_key"], "daily_rsi_80")
        self.assertEqual(signal.metadata["rsi_gate"], 80.0)
        self.assertGreaterEqual(signal.score, 0)
        self.assertLessEqual(signal.score, 100)

    async def test_rsi_divergence_detects_bullish_setup(self) -> None:
        scanner = RSIDivergenceScanner(self.settings, self.binance, self.repository)
        enriched = _frame(
            {"close": 102.0, "low": 101.0, "high": 103.0, "rsi": 45.0},
            {"close": 100.0, "low": 99.5, "high": 101.0, "rsi": 36.0},
            {"close": 98.0, "low": 97.0, "high": 99.0, "rsi": 27.0, "atr": 1.0},
            {"close": 100.4, "low": 99.6, "high": 101.6, "rsi": 40.0},
            {"close": 99.4, "low": 99.0, "high": 100.3, "rsi": 35.0},
            {"close": 101.0, "low": 100.4, "high": 102.2, "rsi": 42.0},
            {"close": 98.8, "low": 98.0, "high": 99.4, "rsi": 34.0},
            {"close": 98.2, "low": 96.6, "high": 99.0, "rsi": 32.0, "atr_pct": 0.012, "volume_ratio": 1.4},
        )
        with (
            patch("src.market.rsi_divergence_scanner.enrich_klines", return_value=enriched),
            patch("src.market.rsi_divergence_scanner.calculate_live_rsi", return_value=33.0),
        ):
            signal = await scanner._scan_symbol("BTCUSDT", self.ticker)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.direction, "long")
        self.assertEqual(signal.metadata["strategy_key"], "rsi_divergence")
        self.assertEqual(signal.metadata["divergence_type"], "bullish")
        self.assertGreater(float(signal.metadata["second_swing_rsi"]), float(signal.metadata["first_swing_rsi"]))

    async def test_rsi_divergence_detects_bearish_setup(self) -> None:
        scanner = RSIDivergenceScanner(self.settings, self.binance, self.repository)
        enriched = _frame(
            {"close": 99.5, "low": 98.8, "high": 100.2, "rsi": 55.0},
            {"close": 101.5, "low": 100.9, "high": 102.1, "rsi": 64.0},
            {"close": 103.2, "low": 102.7, "high": 104.0, "rsi": 74.0, "atr": 1.0},
            {"close": 101.1, "low": 100.2, "high": 101.7, "rsi": 61.0},
            {"close": 102.4, "low": 101.8, "high": 103.0, "rsi": 67.0},
            {"close": 100.8, "low": 100.0, "high": 101.4, "rsi": 59.0},
            {"close": 103.1, "low": 102.2, "high": 103.6, "rsi": 65.0},
            {"close": 102.7, "low": 102.0, "high": 104.6, "rsi": 66.0, "atr_pct": 0.011, "volume_ratio": 1.35},
        )
        with (
            patch("src.market.rsi_divergence_scanner.enrich_klines", return_value=enriched),
            patch("src.market.rsi_divergence_scanner.calculate_live_rsi", return_value=65.4),
        ):
            signal = await scanner._scan_symbol("ETHUSDT", self.ticker)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.direction, "short")
        self.assertEqual(signal.metadata["divergence_type"], "bearish")
        self.assertLess(float(signal.metadata["second_swing_rsi"]), float(signal.metadata["first_swing_rsi"]))

    async def test_rsi_divergence_detects_recent_confirmed_pivot_before_current_candle(self) -> None:
        scanner = RSIDivergenceScanner(self.settings, self.binance, self.repository)
        enriched = _frame(
            {"close": 98.7, "low": 98.0, "high": 99.5, "rsi": 52.0},
            {"close": 100.8, "low": 100.1, "high": 101.6, "rsi": 64.0},
            {"close": 103.1, "low": 102.4, "high": 104.0, "rsi": 75.0, "atr": 1.0},
            {"close": 101.0, "low": 100.2, "high": 101.5, "rsi": 61.0},
            {"close": 102.0, "low": 101.3, "high": 102.8, "rsi": 65.0},
            {"close": 104.0, "low": 103.2, "high": 104.9, "rsi": 67.0, "atr": 1.0},
            {"close": 102.3, "low": 101.6, "high": 103.0, "rsi": 58.0},
            {"close": 101.2, "low": 100.8, "high": 101.9, "rsi": 54.0, "atr_pct": 0.012, "volume_ratio": 1.45},
        )
        with (
            patch("src.market.rsi_divergence_scanner.enrich_klines", return_value=enriched),
            patch("src.market.rsi_divergence_scanner.calculate_live_rsi", return_value=53.0),
        ):
            signal = await scanner._scan_symbol("SUIUSDT", self.ticker)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.direction, "short")
        self.assertEqual(signal.metadata["second_swing_age_candles"], 2)
        self.assertLess(float(signal.metadata["second_swing_rsi"]), float(signal.metadata["first_swing_rsi"]))

    async def test_rsi_divergence_detects_provisional_recent_second_high(self) -> None:
        scanner = RSIDivergenceScanner(self.settings, self.binance, self.repository)
        enriched = _frame(
            {"close": 98.3, "low": 97.9, "high": 98.9, "rsi": 51.0},
            {"close": 99.0, "low": 98.4, "high": 99.8, "rsi": 54.0},
            {"close": 101.2, "low": 100.6, "high": 102.0, "rsi": 65.0},
            {"close": 103.4, "low": 102.8, "high": 104.3, "rsi": 76.0, "atr": 1.0},
            {"close": 101.4, "low": 100.8, "high": 101.9, "rsi": 61.0},
            {"close": 102.2, "low": 101.6, "high": 103.0, "rsi": 66.0},
            {"close": 104.3, "low": 103.7, "high": 105.0, "rsi": 67.0, "atr": 1.0},
            {"close": 102.6, "low": 101.9, "high": 103.3, "rsi": 59.0},
        )
        with (
            patch("src.market.rsi_divergence_scanner.enrich_klines", return_value=enriched),
            patch("src.market.rsi_divergence_scanner.calculate_live_rsi", return_value=58.0),
        ):
            signal = await scanner._scan_symbol("TIAUSDT", self.ticker)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.direction, "short")
        self.assertEqual(signal.metadata["second_swing_age_candles"], 1)

    async def test_okak_scanner_accepts_two_of_three_rule(self) -> None:
        scanner = OkakScanner(self.settings, self.binance, self.repository)
        ticker = SimpleNamespace(last_price=105.5, price_change_percent=4.2, quote_volume=55_000_000.0, volume=440_000.0)
        enriched = _frame(
            {
                "close": 104.2,
                "ema20": 102.4,
                "ema50": 100.8,
                "rsi": 77.4,
                "atr_pct": 0.006,
                "volume_ratio": 1.2,
            },
        )
        with (
            patch("src.market.okak_scanner.enrich_klines", return_value=enriched),
            patch("src.market.okak_scanner.calculate_live_rsi", return_value=77.1),
        ):
            signal = await scanner._scan_symbol("LINKUSDT", ticker)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.metadata["strategy_key"], "okak")
        self.assertEqual(signal.direction, "overbought")
        self.assertTrue(signal.metadata["okak_checks"]["preferred_volume_band"])
        self.assertFalse(signal.metadata["okak_checks"]["score_90_plus"])
        self.assertTrue(signal.metadata["okak_checks"]["rsi_76_plus"])
        self.assertEqual(signal.metadata["okak_checks_passed"], 2)

    async def test_okak_scanner_rejects_when_only_one_condition_matches(self) -> None:
        scanner = OkakScanner(self.settings, self.binance, self.repository)
        ticker = SimpleNamespace(last_price=103.4, price_change_percent=2.1, quote_volume=12_000_000.0, volume=180_000.0)
        enriched = _frame(
            {
                "close": 101.2,
                "ema20": 100.9,
                "ema50": 100.7,
                "rsi": 72.0,
                "atr_pct": 0.002,
                "volume_ratio": 1.05,
            },
        )
        with patch("src.market.okak_scanner.enrich_klines", return_value=enriched):
            signal = await scanner._scan_symbol("ATOMUSDT", ticker)
        self.assertIsNone(signal)

    async def test_ekek_scanner_accepts_sharp_impulse_variant(self) -> None:
        scanner = EkekScanner(self.settings, self.binance, self.repository)
        ticker = SimpleNamespace(last_price=109.6, price_change_percent=7.2, quote_volume=12_000_000.0, volume=240_000.0)
        enriched = _frame(
            {"open": 100.0, "close": 100.3, "high": 100.6, "low": 99.8, "volume": 900.0, "ema20": 99.8, "ema50": 99.1, "rsi": 58.0},
            {"open": 100.2, "close": 100.4, "high": 100.7, "low": 100.0, "volume": 920.0, "ema20": 99.9, "ema50": 99.2, "rsi": 60.0},
            {"open": 100.4, "close": 100.6, "high": 100.9, "low": 100.2, "volume": 950.0, "ema20": 100.0, "ema50": 99.3, "rsi": 61.0},
            {"open": 100.5, "close": 100.8, "high": 101.1, "low": 100.3, "volume": 980.0, "ema20": 100.1, "ema50": 99.4, "rsi": 63.0},
            {"open": 100.8, "close": 101.1, "high": 101.4, "low": 100.6, "volume": 1_000.0, "ema20": 100.2, "ema50": 99.5, "rsi": 65.0},
            {"open": 101.2, "close": 103.0, "high": 103.4, "low": 100.9, "volume": 1_800.0, "ema20": 100.9, "ema50": 99.9, "rsi": 72.0, "atr_pct": 0.006, "volume_ratio": 1.25},
            {"open": 103.0, "close": 105.8, "high": 106.3, "low": 102.8, "volume": 2_200.0, "ema20": 101.8, "ema50": 100.5, "rsi": 76.8, "atr_pct": 0.007, "volume_ratio": 1.45},
            {"open": 105.9, "close": 108.9, "high": 109.4, "low": 105.6, "volume": 2_600.0, "ema20": 103.0, "ema50": 101.2, "rsi": 79.4, "atr_pct": 0.008, "volume_ratio": 1.7},
        )
        with (
            patch("src.market.okak_scanner.enrich_klines", return_value=enriched),
            patch("src.market.ekek_scanner.calculate_live_rsi", return_value=79.0),
        ):
            signal = await scanner._scan_symbol("LINKUSDT", ticker)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.metadata["strategy_key"], "ekek")
        self.assertEqual(signal.direction, "overbought")
        self.assertTrue(signal.metadata["ekek_impulse_checks"]["strong_recent_move"])
        self.assertTrue(signal.metadata["ekek_impulse_checks"]["impulse_candle_present"])
        self.assertTrue(signal.metadata["ekek_impulse_checks"]["impulse_is_concentrated"])
        self.assertTrue(signal.metadata["ekek_impulse_checks"]["terminal_acceleration"])
        self.assertIn("sharp", signal.explanation.lower())

    async def test_ekek_scanner_rejects_gradual_climb_without_burst(self) -> None:
        scanner = EkekScanner(self.settings, self.binance, self.repository)
        ticker = SimpleNamespace(last_price=105.4, price_change_percent=3.2, quote_volume=12_000_000.0, volume=210_000.0)
        enriched = _frame(
            {"open": 100.0, "close": 100.6, "high": 100.8, "low": 99.9, "volume": 1_000.0, "ema20": 99.8, "ema50": 99.0, "rsi": 60.0},
            {"open": 100.6, "close": 101.0, "high": 101.2, "low": 100.4, "volume": 1_020.0, "ema20": 100.0, "ema50": 99.2, "rsi": 63.0},
            {"open": 101.0, "close": 101.5, "high": 101.7, "low": 100.8, "volume": 1_030.0, "ema20": 100.2, "ema50": 99.4, "rsi": 66.0},
            {"open": 101.5, "close": 102.0, "high": 102.2, "low": 101.3, "volume": 1_040.0, "ema20": 100.5, "ema50": 99.7, "rsi": 69.0},
            {"open": 102.0, "close": 102.6, "high": 102.8, "low": 101.8, "volume": 1_050.0, "ema20": 100.8, "ema50": 100.0, "rsi": 72.0, "atr_pct": 0.004, "volume_ratio": 1.08},
            {"open": 102.6, "close": 103.1, "high": 103.3, "low": 102.4, "volume": 1_060.0, "ema20": 101.1, "ema50": 100.3, "rsi": 74.0, "atr_pct": 0.004, "volume_ratio": 1.1},
            {"open": 103.1, "close": 103.8, "high": 104.0, "low": 102.9, "volume": 1_070.0, "ema20": 101.5, "ema50": 100.7, "rsi": 76.2, "atr_pct": 0.004, "volume_ratio": 1.12},
            {"open": 103.8, "close": 104.4, "high": 104.6, "low": 103.6, "volume": 1_080.0, "ema20": 101.9, "ema50": 101.0, "rsi": 78.1, "atr_pct": 0.004, "volume_ratio": 1.14},
        )
        with patch("src.market.okak_scanner.enrich_klines", return_value=enriched):
            signal = await scanner._scan_symbol("ATOMUSDT", ticker)
        self.assertIsNone(signal)

    async def test_ekek_scanner_rejects_staircase_run_without_terminal_expansion(self) -> None:
        scanner = EkekScanner(self.settings, self.binance, self.repository)
        ticker = SimpleNamespace(last_price=104.3, price_change_percent=4.8, quote_volume=12_000_000.0, volume=230_000.0)
        enriched = _frame(
            {"open": 100.0, "close": 100.8, "high": 101.0, "low": 99.8, "volume": 1_120.0, "ema20": 99.8, "ema50": 99.1, "rsi": 61.0},
            {"open": 100.8, "close": 100.2, "high": 101.0, "low": 100.0, "volume": 1_080.0, "ema20": 99.9, "ema50": 99.2, "rsi": 60.0},
            {"open": 100.2, "close": 101.1, "high": 101.4, "low": 100.0, "volume": 1_140.0, "ema20": 100.1, "ema50": 99.4, "rsi": 64.0},
            {"open": 101.1, "close": 100.6, "high": 101.3, "low": 100.4, "volume": 1_060.0, "ema20": 100.2, "ema50": 99.6, "rsi": 63.0},
            {"open": 100.6, "close": 101.6, "high": 101.9, "low": 100.4, "volume": 1_150.0, "ema20": 100.4, "ema50": 99.8, "rsi": 69.0, "atr_pct": 0.004, "volume_ratio": 1.12},
            {"open": 101.6, "close": 102.5, "high": 102.8, "low": 101.4, "volume": 1_170.0, "ema20": 100.8, "ema50": 100.1, "rsi": 73.0, "atr_pct": 0.004, "volume_ratio": 1.14},
            {"open": 102.5, "close": 103.4, "high": 103.7, "low": 102.2, "volume": 1_190.0, "ema20": 101.3, "ema50": 100.5, "rsi": 76.4, "atr_pct": 0.004, "volume_ratio": 1.16},
            {"open": 103.4, "close": 104.3, "high": 104.6, "low": 103.2, "volume": 1_210.0, "ema20": 101.9, "ema50": 101.0, "rsi": 78.2, "atr_pct": 0.004, "volume_ratio": 1.18},
        )
        with patch("src.market.okak_scanner.enrich_klines", return_value=enriched):
            signal = await scanner._scan_symbol("BIOUSDT", ticker)
        self.assertIsNone(signal)

    async def test_ekek_scanner_accepts_late_burst_after_prior_grind(self) -> None:
        scanner = EkekScanner(self.settings, self.binance, self.repository)
        ticker = SimpleNamespace(last_price=0.0664, price_change_percent=11.4, quote_volume=18_000_000.0, volume=480_000.0)
        enriched = _frame(
            {"open": 0.0520, "close": 0.0525, "high": 0.0527, "low": 0.0518, "volume": 1_200.0, "ema20": 0.0518, "ema50": 0.0512, "rsi": 56.0},
            {"open": 0.0525, "close": 0.0530, "high": 0.0532, "low": 0.0523, "volume": 1_240.0, "ema20": 0.0520, "ema50": 0.0514, "rsi": 58.0},
            {"open": 0.0530, "close": 0.0538, "high": 0.0540, "low": 0.0528, "volume": 1_280.0, "ema20": 0.0523, "ema50": 0.0516, "rsi": 61.0},
            {"open": 0.0538, "close": 0.0546, "high": 0.0549, "low": 0.0535, "volume": 1_320.0, "ema20": 0.0527, "ema50": 0.0519, "rsi": 64.0},
            {"open": 0.0546, "close": 0.0554, "high": 0.0558, "low": 0.0544, "volume": 1_360.0, "ema20": 0.0531, "ema50": 0.0522, "rsi": 67.0},
            {"open": 0.0554, "close": 0.0566, "high": 0.0570, "low": 0.0552, "volume": 1_420.0, "ema20": 0.0537, "ema50": 0.0527, "rsi": 70.0, "atr_pct": 0.010, "volume_ratio": 1.18},
            {"open": 0.0566, "close": 0.0602, "high": 0.0612, "low": 0.0562, "volume": 2_400.0, "ema20": 0.0550, "ema50": 0.0537, "rsi": 76.5, "atr_pct": 0.013, "volume_ratio": 1.55},
            {"open": 0.0602, "close": 0.0664, "high": 0.0676, "low": 0.0597, "volume": 3_200.0, "ema20": 0.0572, "ema50": 0.0549, "rsi": 81.0, "atr_pct": 0.016, "volume_ratio": 1.95},
        )
        with (
            patch("src.market.okak_scanner.enrich_klines", return_value=enriched),
            patch("src.market.ekek_scanner.calculate_live_rsi", return_value=80.3),
        ):
            signal = await scanner._scan_symbol("PRLUSDT", ticker)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertTrue(signal.metadata["ekek_impulse_checks"]["impulse_candle_present"])
        self.assertTrue(signal.metadata["ekek_impulse_checks"]["wide_recent_range"])
        self.assertTrue(signal.metadata["ekek_impulse_checks"]["terminal_acceleration"])
        self.assertGreaterEqual(float(signal.metadata["ekek_impulse_candle_count"]), 1.0)

    async def test_vwap_scanner_detects_long_reclaim_from_current_utc_day(self) -> None:
        scanner = VWAPScanner(self.settings, self.binance, self.repository)
        enriched = _frame(
            {"_ts": pd.Timestamp("2026-03-15 23:00:00", tz="UTC"), "close": 120.0, "volume": 10_000.0},
            {"_ts": pd.Timestamp("2026-03-15 23:15:00", tz="UTC"), "close": 118.0, "volume": 8_000.0},
            {"_ts": pd.Timestamp("2026-03-16 00:00:00", tz="UTC"), "close": 100.0, "volume": 2_000.0},
            {"_ts": pd.Timestamp("2026-03-16 00:15:00", tz="UTC"), "close": 99.0, "volume": 2_000.0},
            {"_ts": pd.Timestamp("2026-03-16 00:30:00", tz="UTC"), "close": 101.2, "volume": 2_200.0},
        )
        with (
            patch("src.market.vwap_scanner.enrich_klines", return_value=enriched),
            patch("src.market.vwap_scanner.calculate_live_rsi", return_value=57.0),
        ):
            signal = await scanner._scan_symbol("ADAUSDT", self.ticker)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.direction, "long")
        self.assertEqual(signal.metadata["session_anchor"], "utc_day")

    async def test_vwap_scanner_detects_short_reject(self) -> None:
        scanner = VWAPScanner(self.settings, self.binance, self.repository)
        enriched = _frame(
            {"_ts": pd.Timestamp("2026-03-16 00:00:00", tz="UTC"), "close": 100.0, "volume": 2_000.0},
            {"_ts": pd.Timestamp("2026-03-16 00:15:00", tz="UTC"), "close": 101.4, "volume": 2_100.0},
            {"_ts": pd.Timestamp("2026-03-16 00:30:00", tz="UTC"), "close": 99.4, "volume": 2_400.0},
        )
        with (
            patch("src.market.vwap_scanner.enrich_klines", return_value=enriched),
            patch("src.market.vwap_scanner.calculate_live_rsi", return_value=44.0),
        ):
            signal = await scanner._scan_symbol("DOGEUSDT", self.ticker)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.direction, "short")

    async def test_false_breakout_scanner_detects_long_reclaim(self) -> None:
        scanner = FalseBreakoutScanner(self.settings, self.binance, self.repository)
        rows = [
            {"close": 100.4, "high": 101.0, "low": 100.0}
            for _ in range(20)
        ]
        rows.extend(
            [
                {"close": 100.2, "high": 100.8, "low": 100.0},
                {"close": 100.5, "high": 100.9, "low": 99.3},
            ]
        )
        enriched = _frame(*rows)
        with (
            patch("src.market.false_breakout_scanner.enrich_klines", return_value=enriched),
            patch("src.market.false_breakout_scanner.calculate_live_rsi", return_value=52.0),
        ):
            signal = await scanner._scan_symbol("PEPEUSDT", self.ticker)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.direction, "long")
        self.assertEqual(signal.metadata["sweep_side"], "low")

    async def test_false_breakout_scanner_rejects_wick_without_close_back_inside(self) -> None:
        scanner = FalseBreakoutScanner(self.settings, self.binance, self.repository)
        rows = [
            {"close": 100.3, "high": 101.0, "low": 100.0}
            for _ in range(20)
        ]
        rows.extend(
            [
                {"close": 100.2, "high": 100.8, "low": 100.0},
                {"close": 99.8, "high": 100.7, "low": 99.2},
            ]
        )
        enriched = _frame(*rows)
        with patch("src.market.false_breakout_scanner.enrich_klines", return_value=enriched):
            signal = await scanner._scan_symbol("FETUSDT", self.ticker)
        self.assertIsNone(signal)


if __name__ == "__main__":
    unittest.main()
