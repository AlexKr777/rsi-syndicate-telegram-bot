from __future__ import annotations

from src.core.models import AlertSignal
from src.market.breakout_scanner import BreakoutScanner
from src.market.symbols import TickerStats


class GoldBreakoutScanner(BreakoutScanner):
    strategy_key = "gold_breakout"
    include_gold = True

    async def scan_once(self) -> list[AlertSignal]:
        symbol = self.settings.gold_symbol.strip().upper()
        if not symbol:
            return []
        ticker_map = await self.binance_client.get_all_ticker_stats()
        signal = await self._scan_symbol(symbol, ticker_map.get(symbol))
        return [signal] if signal is not None else []

    def _build_signal(self, *args, **kwargs) -> AlertSignal:
        signal = super()._build_signal(*args, **kwargs)
        signal.metadata.update(
            {
                "asset_class": "gold",
                "strategy_key": self.strategy_key,
                "signal_model": "gold_breakout_confirmed",
            }
        )
        return signal
