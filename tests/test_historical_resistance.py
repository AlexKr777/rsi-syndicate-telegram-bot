from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from src.analysis.historical_resistance import find_historical_resistance_zone


def _build_frame(closes: list[float], *, step_hours: int) -> pd.DataFrame:
    start = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
    index = [start + timedelta(hours=step_hours * idx) for idx in range(len(closes))]
    opens = [closes[0] - 0.6, *closes[:-1]]
    highs = [max(open_price, close_price) + 0.8 for open_price, close_price in zip(opens, closes, strict=False)]
    lows = [min(open_price, close_price) - 0.8 for open_price, close_price in zip(opens, closes, strict=False)]
    volumes = [1_250_000.0 + (idx % 4) * 80_000.0 for idx in range(len(closes))]
    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
            "close_time": [stamp + timedelta(hours=step_hours) for stamp in index],
        },
        index=index,
    )


class HistoricalResistanceTests(unittest.TestCase):
    def test_find_historical_resistance_zone_prefers_real_multi_touch_zone(self) -> None:
        closes_1h = [
            100.0, 101.1, 103.3, 106.7, 110.2, 112.6, 110.4, 106.1, 104.1, 103.5, 104.2, 106.8,
            109.8, 112.3, 110.1, 106.0, 104.6, 103.9, 104.9, 107.1, 110.0, 112.5, 110.4, 106.2,
            104.8, 104.2, 105.0, 107.2, 109.9, 112.1, 110.2, 106.5, 105.0, 104.7, 105.4, 107.6,
            109.8, 111.9, 110.8, 108.8, 109.6, 110.4, 110.8, 110.7, 110.9, 110.8, 110.7, 110.8,
            110.9, 110.8,
        ]
        closes_4h = [
            100.0, 102.0, 105.2, 109.1, 112.4, 109.3, 105.4, 103.8, 104.6, 107.2, 110.1, 112.2,
            109.5, 105.8, 104.2, 104.9, 107.4, 110.4, 112.7, 109.7, 106.0, 104.5, 105.1, 107.6,
            110.3, 112.5, 110.0, 106.7, 105.2, 105.4, 107.8, 110.1, 112.1, 110.5, 108.0, 109.0,
            110.1, 110.6, 110.8, 110.9, 111.0, 110.8, 110.7, 110.8, 110.9, 110.8, 110.7, 110.8,
            110.9, 110.8,
        ]

        zone = find_historical_resistance_zone(
            {
                "1h": _build_frame(closes_1h, step_hours=1),
                "4h": _build_frame(closes_4h, step_hours=4),
            },
            current_price=110.8,
            rsi_length=14,
        )

        self.assertIsNotNone(zone)
        assert zone is not None
        self.assertIn("4h", zone.timeframes)
        self.assertGreaterEqual(zone.touch_count, 3)
        self.assertGreater(zone.zone_price, 111.0)
        self.assertLess(zone.zone_price, 113.5)
        self.assertGreater(zone.avg_rejection_pct, 3.0)
        self.assertIn(zone.quality, {"strong", "moderate"})
        self.assertIsNotNone(zone.highest_peak_price)
        self.assertGreaterEqual(float(zone.highest_peak_price or 0.0), zone.zone_high)
        self.assertIn(zone.highest_peak_timeframe, {"1h", "4h"})
        self.assertIsNotNone(zone.highest_peak_distance_pct)


if __name__ == "__main__":
    unittest.main()
