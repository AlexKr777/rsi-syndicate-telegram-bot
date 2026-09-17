from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from src.core.config import Settings
from src.core.models import AlertSignal
from src.market.binance_client import BinanceClient
from src.market.symbols import TickerStats
from src.storage.repository import Repository


class BaseStrategyScanner(ABC):
    strategy_key = "rsi"
    include_gold = False

    def __init__(
        self,
        settings: Settings,
        binance_client: BinanceClient,
        repository: Repository,
    ) -> None:
        self.settings = settings
        self.binance_client = binance_client
        self.repository = repository

    async def scan_once(self) -> list[AlertSignal]:
        symbols = await self.binance_client.get_active_usdt_symbols()
        if not self.include_gold:
            gold_symbol = self.settings.gold_symbol.strip().upper()
            symbols = [symbol for symbol in symbols if str(symbol or "").strip().upper() != gold_symbol]
        ticker_map = await self.binance_client.get_all_ticker_stats()
        semaphore = asyncio.Semaphore(self.settings.scan_concurrency)

        async def _bounded_scan(symbol: str) -> AlertSignal | None:
            async with semaphore:
                return await self._scan_symbol(symbol, ticker_map.get(symbol))

        results = await asyncio.gather(
            *(_bounded_scan(symbol) for symbol in symbols),
            return_exceptions=True,
        )
        alerts: list[AlertSignal] = []
        for result in results:
            if isinstance(result, Exception):
                continue
            if result is not None:
                alerts.append(result)
        return alerts

    @abstractmethod
    async def _scan_symbol(self, symbol: str, ticker: TickerStats | None) -> AlertSignal | None:
        raise NotImplementedError
