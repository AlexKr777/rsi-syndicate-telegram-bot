from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.market.gold_client import YahooGoldClient


def _build_chart_result(*, bars: int, start: datetime, interval_minutes: int = 15) -> dict[str, object]:
    timestamps: list[int] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[float] = []
    price = 2980.0
    for idx in range(bars):
        ts = start + timedelta(minutes=interval_minutes * idx)
        timestamps.append(int(ts.timestamp()))
        open_price = price + (idx * 0.18)
        close_price = open_price + 0.12
        opens.append(open_price)
        highs.append(close_price + 0.35)
        lows.append(open_price - 0.35)
        closes.append(close_price)
        volumes.append(1000.0 + idx)
    return {
        "timestamp": timestamps,
        "indicators": {
            "quote": [
                {
                    "open": opens,
                    "high": highs,
                    "low": lows,
                    "close": closes,
                    "volume": volumes,
                }
            ]
        },
    }


class _FakeYahooGoldClient(YahooGoldClient):
    def __init__(self) -> None:
        super().__init__(
            SimpleNamespace(
                http_timeout_seconds=20,
                gold_data_user_agent="test-agent",
                gold_provider_symbol="GC=F",
                gold_symbol="XAUUSD",
                gold_chart_api_base_url="https://example.com/chart",
                http_max_retries=1,
            )
        )
        self.requested_limits: list[int] = []

    async def _fetch_chart(self, *, interval: str, limit: int, end_time=None) -> dict[str, object]:
        del interval, end_time
        self.requested_limits.append(limit)
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=(max(limit, 220) + 4) * 15)
        if limit <= 150:
            return _build_chart_result(bars=38, start=start)
        return _build_chart_result(bars=240, start=start)


class YahooGoldClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_klines_expands_lookback_when_weekend_window_underfills(self) -> None:
        client = _FakeYahooGoldClient()

        frame = await client.get_klines("XAUUSD", "15m", 150)

        self.assertEqual(len(frame), 150)
        self.assertEqual(client.requested_limits[:2], [150, 450])


if __name__ == "__main__":
    unittest.main()
