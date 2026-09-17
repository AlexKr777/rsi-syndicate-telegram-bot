from __future__ import annotations

import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.core.utils import utc_now
from src.market.binance_client import BinanceApiError, BinanceClient


def _build_kline_payload(*, bars: int = 5, interval_minutes: int = 15) -> list[list[object]]:
    start = utc_now() - timedelta(minutes=interval_minutes * (bars + 4))
    rows: list[list[object]] = []
    for idx in range(bars):
        open_time = start + timedelta(minutes=interval_minutes * idx)
        close_time = open_time + timedelta(minutes=interval_minutes) - timedelta(milliseconds=1)
        open_price = 100.0 + idx
        close_price = open_price + 0.4
        rows.append(
            [
                int(open_time.timestamp() * 1000),
                f"{open_price:.4f}",
                f"{open_price + 0.8:.4f}",
                f"{open_price - 0.6:.4f}",
                f"{close_price:.4f}",
                f"{1000 + idx:.4f}",
                int(close_time.timestamp() * 1000),
                f"{2000 + idx:.4f}",
                100 + idx,
                f"{300 + idx:.4f}",
                f"{400 + idx:.4f}",
                "0",
            ]
        )
    return rows


class BinanceClientRateLimitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.settings = SimpleNamespace(
            http_timeout_seconds=20,
            http_max_retries=1,
            binance_rest_base_url="https://example.com",
            symbols_refresh_minutes=240,
        )

    async def test_get_klines_reuses_short_lived_cache_for_identical_requests(self) -> None:
        client = BinanceClient(self.settings)
        client._get_json = AsyncMock(return_value=_build_kline_payload())

        first = await client.get_klines("BTCUSDT", "15m", 5)
        second = await client.get_klines("BTCUSDT", "15m", 5)

        self.assertEqual(client._get_json.await_count, 1)
        self.assertEqual(len(first), len(second))
        self.assertIsNot(first, second)

    async def test_get_all_ticker_stats_throttles_force_refresh_bursts(self) -> None:
        client = BinanceClient(self.settings)
        client._get_json = AsyncMock(
            return_value=[
                {
                    "symbol": "BTCUSDT",
                    "lastPrice": "64000.0",
                    "priceChangePercent": "1.23",
                    "volume": "1000",
                    "quoteVolume": "64000000",
                }
            ]
        )

        first = await client.get_all_ticker_stats(force_refresh=False)
        second = await client.get_all_ticker_stats(force_refresh=True)

        self.assertEqual(client._get_json.await_count, 1)
        self.assertEqual(first["BTCUSDT"].last_price, second["BTCUSDT"].last_price)

    async def test_get_klines_uses_stale_cache_when_binance_is_rate_limited(self) -> None:
        client = BinanceClient(self.settings)
        client._get_json = AsyncMock(return_value=_build_kline_payload())

        fresh = await client.get_klines("BTCUSDT", "15m", 5)
        cache_key = ("BTCUSDT", "15m", 5, None)
        cached_frame, _, refreshed_at = client._klines_cache[cache_key]
        client._klines_cache[cache_key] = (
            cached_frame,
            utc_now() - timedelta(seconds=1),
            refreshed_at,
        )
        client._get_json = AsyncMock(
            side_effect=BinanceApiError(
                418,
                '{"code":-1003,"msg":"Way too many requests; IP banned until 1773669345646."}',
                non_retryable=True,
            )
        )

        fallback = await client.get_klines("BTCUSDT", "15m", 5)

        self.assertEqual(client._get_json.await_count, 1)
        self.assertEqual(len(fresh), len(fallback))

    async def test_get_all_ticker_stats_uses_stale_cache_when_binance_is_rate_limited(self) -> None:
        client = BinanceClient(self.settings)
        client._get_json = AsyncMock(
            return_value=[
                {
                    "symbol": "ETHUSDT",
                    "lastPrice": "3400.0",
                    "priceChangePercent": "-0.75",
                    "volume": "500",
                    "quoteVolume": "1700000",
                }
            ]
        )

        fresh = await client.get_all_ticker_stats()
        ticker_map, _, refreshed_at = client._ticker_cache
        client._ticker_cache = (
            ticker_map,
            utc_now() - timedelta(seconds=1),
            refreshed_at,
        )
        client._get_json = AsyncMock(
            side_effect=BinanceApiError(
                429,
                '{"code":-1003,"msg":"Too many requests."}',
            )
        )

        fallback = await client.get_all_ticker_stats(force_refresh=False)

        self.assertEqual(client._get_json.await_count, 1)
        self.assertEqual(fresh["ETHUSDT"].last_price, fallback["ETHUSDT"].last_price)

    async def test_get_active_usdt_symbols_filters_out_stablecoin_and_quote_only_contracts(self) -> None:
        client = BinanceClient(self.settings)
        client._get_json = AsyncMock(
            return_value={
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "contractType": "PERPETUAL",
                        "quoteAsset": "USDT",
                        "baseAsset": "BTC",
                    },
                    {
                        "symbol": "USDCUSDT",
                        "status": "TRADING",
                        "contractType": "PERPETUAL",
                        "quoteAsset": "USDT",
                        "baseAsset": "USDC",
                    },
                    {
                        "symbol": "USDT",
                        "status": "TRADING",
                        "contractType": "PERPETUAL",
                        "quoteAsset": "USDT",
                        "baseAsset": "USDT",
                    },
                    {
                        "symbol": "FDUSDUSDT",
                        "status": "TRADING",
                        "contractType": "PERPETUAL",
                        "quoteAsset": "USDT",
                        "baseAsset": "FDUSD",
                    },
                ]
            }
        )

        symbols = await client.get_active_usdt_symbols()

        self.assertEqual(symbols, ["BTCUSDT"])


if __name__ == "__main__":
    unittest.main()
