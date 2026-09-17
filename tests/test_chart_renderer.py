from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np
import pandas as pd

from src.charts.renderer import ChartRenderer


class ChartRendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.renderer = ChartRenderer(
            SimpleNamespace(
                klines_limit=150,
                temp_chart_dir=Path(self.tempdir.name),
            )
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _build_frame(self) -> pd.DataFrame:
        start = datetime(2026, 3, 13, 0, 0, tzinfo=timezone.utc)
        index = pd.date_range(start, periods=40, freq="15min")
        base = np.linspace(100.0, 110.0, 40)
        close = base + 0.35
        return pd.DataFrame(
            {
                "Open": base,
                "High": base + 1.1,
                "Low": base - 1.1,
                "Close": close,
                "Volume": np.full(40, 1_000.0),
                "close": close,
                "rsi": np.linspace(32.0, 68.0, 40),
            },
            index=index,
        )

    def test_resolve_plot_x_uses_visible_candle_offset(self) -> None:
        frame = self._build_frame()

        signal_index = self.renderer._resolve_marker_index(frame.index, frame.index[10])
        signal_x = self.renderer._resolve_plot_x(frame.index, signal_index)

        self.assertEqual(signal_x, 10.0)

    def test_draw_signal_level_keeps_mplfinance_xlim_intact(self) -> None:
        frame = self._build_frame()
        fig, axes = mpf.plot(
            frame,
            type="candle",
            style=self.renderer.style,
            volume=False,
            returnfig=True,
        )
        price_ax = axes[0]
        before = tuple(float(value) for value in price_ax.get_xlim())
        signal_index = self.renderer._resolve_marker_index(frame.index, frame.index[10])
        signal_x = self.renderer._resolve_plot_x(frame.index, signal_index)

        self.renderer._draw_signal_level(
            price_ax,
            signal_x=signal_x,
            signal_price=float(frame["close"].iloc[10]),
            color="#ffd166",
            label="Entry",
        )

        after = tuple(float(value) for value in price_ax.get_xlim())
        self.assertAlmostEqual(before[0], after[0], places=4)
        self.assertAlmostEqual(before[1], after[1], places=4)
        plt.close(fig)

    def test_draw_signal_hint_uses_compact_entry_label(self) -> None:
        frame = self._build_frame()
        fig, axes = mpf.plot(
            frame,
            type="candle",
            style=self.renderer.style,
            volume=False,
            returnfig=True,
        )
        price_ax = axes[0]

        self.renderer._draw_signal_hint(price_ax)

        self.assertEqual(price_ax.texts[-1].get_text(), "Entry candle")
        plt.close(fig)

    def test_draw_signal_level_flips_label_below_marker_near_top_edge(self) -> None:
        frame = self._build_frame()
        fig, axes = mpf.plot(
            frame,
            type="candle",
            style=self.renderer.style,
            volume=False,
            returnfig=True,
        )
        price_ax = axes[0]
        signal_index = self.renderer._resolve_marker_index(frame.index, frame.index[-2])
        signal_x = self.renderer._resolve_plot_x(frame.index, signal_index)
        top_edge_price = float(price_ax.get_ylim()[1]) * 0.998

        self.renderer._draw_signal_level(
            price_ax,
            signal_x=signal_x,
            signal_price=top_edge_price,
            color="#ffd166",
            label="Entry",
        )

        self.assertEqual(price_ax.texts[-1].get_va(), "bottom")
        plt.close(fig)

    def test_expected_timeframe_clipping_is_debug_not_warning(self) -> None:
        frame = self._build_frame()
        target = frame.index[0] - pd.Timedelta(minutes=15)

        with patch("src.charts.renderer.LOGGER") as logger:
            resolved = self.renderer._resolve_marker_index(frame.index, target)

        self.assertEqual(resolved, frame.index[0])
        logger.debug.assert_called()
        logger.warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
