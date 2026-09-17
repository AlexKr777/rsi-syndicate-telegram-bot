from __future__ import annotations

import pandas as pd

from src.core.models import AlertSignal
from src.market.base_strategy_scanner import BaseStrategyScanner
from src.market.indicators import calculate_live_rsi, enrich_klines
from src.market.symbols import TickerStats


class DailyRSI80Scanner(BaseStrategyScanner):
    strategy_key = "daily_rsi_80"
    scan_interval = "1d"
    rsi_gate = 80.0

    async def _scan_symbol(self, symbol: str, ticker: TickerStats | None) -> AlertSignal | None:
        frame = await self.binance_client.get_klines(
            symbol=symbol,
            interval=self.scan_interval,
            limit=self.settings.klines_limit,
        )
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        if enriched.empty:
            return None

        current_row = enriched.iloc[-1]
        closed_rsi = float(current_row["rsi"])
        if closed_rsi < self.rsi_gate:
            return None

        if await self.repository.alert_exists_for_candle(
            symbol=symbol,
            direction="short",
            strategy_key=self.strategy_key,
            timeframe=self.scan_interval,
            candle_open_time=current_row.name.to_pydatetime(),
        ):
            return None

        return self._build_signal(symbol, enriched, ticker)

    def _build_signal(
        self,
        symbol: str,
        frame: pd.DataFrame,
        ticker: TickerStats | None,
    ) -> AlertSignal:
        row = frame.iloc[-1]
        candle_close_time = row["close_time"].to_pydatetime()
        live_price = float(ticker.last_price) if ticker is not None and ticker.last_price else float(row["close"])
        live_rsi = calculate_live_rsi(frame["close"], live_price, self.settings.rsi_length)
        explanation = self._build_explanation(row)
        score = self._score_signal(row)
        return AlertSignal(
            symbol=symbol,
            direction="short",
            timeframe=self.scan_interval,
            candle_open_time=row.name.to_pydatetime(),
            candle_close_time=candle_close_time,
            price=float(row["close"]),
            rsi=float(row["rsi"]),
            day_change_pct=ticker.price_change_percent if ticker else None,
            day_volume=ticker.quote_volume if ticker and ticker.quote_volume else ticker.volume if ticker else None,
            quote_volume=ticker.quote_volume if ticker else None,
            last_candle_volume=float(row["volume"]),
            avg_volume_20=float(row["avg_volume_20"]) if pd.notna(row["avg_volume_20"]) else 0.0,
            atr=float(row["atr"]) if pd.notna(row["atr"]) else 0.0,
            atr_pct=float(row["atr_pct"]) if pd.notna(row["atr_pct"]) else 0.0,
            ema20=float(row["ema20"]),
            ema50=float(row["ema50"]),
            score=score,
            explanation=explanation,
            metadata={
                "asset_class": "crypto",
                "strategy_key": self.strategy_key,
                "signal_model": "daily_rsi_overbought_80",
                "setup_direction": "short",
                "market_regime_tag": "HTF Extremes",
                "rsi_gate": self.rsi_gate,
                "timeframe_locked": self.scan_interval,
                "closed_rsi": float(row["rsi"]),
                "live_rsi": live_rsi,
                "live_price": live_price,
                "signal_close_price": float(row["close"]),
                "signal_candle_close_time": candle_close_time.isoformat(),
                "volume_ratio": float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else None,
                "interactive_ai_enabled": True,
                "interactive_risk_enabled": True,
                "interactive_reason_enabled": True,
                "context_text": explanation,
            },
        )

    def _build_explanation(self, row: pd.Series) -> str:
        return (
            f"Daily RSI closed above {self.rsi_gate:.0f} on 1d, which marks a high-timeframe overheated move. "
            f"The coin is extended above EMA structure and is better treated as a short-bias exhaustion alert, not an automatic entry by itself. "
            f"Snapshot: RSI {float(row['rsi']):.2f}, volume ratio {float(row['volume_ratio']) if pd.notna(row['volume_ratio']) else 1.0:.2f}."
        )

    def _score_signal(self, row: pd.Series) -> int:
        rsi_distance = max(float(row["rsi"]) - self.rsi_gate, 0.0)
        close_price = max(float(row["close"]), 1e-9)
        stretch = max((float(row["close"]) - float(row["ema20"])) / close_price, 0.0)
        trend_score = 10.0 if float(row["close"]) > float(row["ema20"]) > float(row["ema50"]) else 4.0
        volume_ratio = float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else 1.0
        volume_score = min(max(volume_ratio - 1.0, 0.0) * 12.0, 12.0)
        volatility_score = min(float(row["atr_pct"]) * 420.0, 10.0)
        stretch_score = min(stretch * 5200.0, 16.0)
        total = 58.0 + min(rsi_distance * 8.0, 24.0) + trend_score + volume_score + volatility_score + stretch_score
        return int(max(0, min(round(total), 100)))
