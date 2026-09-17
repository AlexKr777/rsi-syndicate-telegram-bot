from __future__ import annotations

import logging

import pandas as pd

from src.core.config import Settings
from src.market.binance_client import BinanceClient
from src.market.gold_client import YahooGoldClient
from src.market.symbols import TickerStats

LOGGER = logging.getLogger(__name__)


class MarketClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.binance = BinanceClient(settings)
        self.gold = YahooGoldClient(settings) if settings.gold_alerts_enabled else None

    async def close(self) -> None:
        await self.binance.close()
        if self.gold is not None:
            await self.gold.close()

    def is_gold_symbol(self, symbol: str) -> bool:
        return (
            self.settings.gold_alerts_enabled
            and str(symbol or "").strip().upper() == self.settings.gold_symbol.strip().upper()
        )

    async def get_active_usdt_symbols(self, force_refresh: bool = False) -> list[str]:
        symbols = await self.binance.get_active_usdt_symbols(force_refresh=force_refresh)
        if self.settings.gold_alerts_enabled:
            gold_symbol = self.settings.gold_symbol.strip().upper()
            if gold_symbol and gold_symbol not in symbols:
                symbols = [*symbols, gold_symbol]
                LOGGER.info("Added gold scan symbol to market universe: %s", gold_symbol)
        return symbols

    async def get_all_ticker_stats(self, force_refresh: bool = False) -> dict[str, TickerStats]:
        ticker_map = await self.binance.get_all_ticker_stats(force_refresh=force_refresh)
        if self.gold is not None:
            try:
                gold_ticker = await self.gold.get_ticker_stats(force_refresh=force_refresh)
                ticker_map[gold_ticker.symbol] = gold_ticker
            except Exception:
                LOGGER.exception("Failed to refresh gold ticker stats")
        return ticker_map

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int,
        *,
        end_time=None,
    ) -> pd.DataFrame:
        if self.is_gold_symbol(symbol):
            if self.gold is None:
                raise RuntimeError("Gold market client is not configured")
            return await self.gold.get_klines(symbol, interval, limit, end_time=end_time)
        return await self.binance.get_klines(symbol, interval, limit, end_time=end_time)
