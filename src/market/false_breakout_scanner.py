from __future__ import annotations

import pandas as pd

from src.core.models import AlertSignal
from src.market.base_strategy_scanner import BaseStrategyScanner
from src.market.indicators import calculate_live_rsi, enrich_klines
from src.market.symbols import TickerStats


class FalseBreakoutScanner(BaseStrategyScanner):
    strategy_key = "false_breakout"

    async def _scan_symbol(self, symbol: str, ticker: TickerStats | None) -> AlertSignal | None:
        frame = await self.binance_client.get_klines(
            symbol=symbol,
            interval=self.settings.scan_timeframe,
            limit=self.settings.klines_limit,
        )
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        if len(enriched) < 21:
            return None
        candidate = self._detect_candidate(enriched)
        if candidate is None:
            return None
        direction, sweep_level, sweep_side, local_high, local_low = candidate
        current_row = enriched.iloc[-1]
        if await self.repository.alert_exists_for_candle(
            symbol=symbol,
            direction=direction,
            strategy_key=self.strategy_key,
            timeframe=self.settings.scan_timeframe,
            candle_open_time=current_row.name.to_pydatetime(),
        ):
            return None
        return self._build_signal(
            symbol,
            enriched,
            ticker,
            direction=direction,
            sweep_level=sweep_level,
            sweep_side=sweep_side,
            local_high=local_high,
            local_low=local_low,
        )

    def _detect_candidate(self, frame: pd.DataFrame) -> tuple[str, float, str, float, float] | None:
        current_row = frame.iloc[-1]
        previous_row = frame.iloc[-2]
        local_rows = frame.iloc[:-1].tail(20)
        if len(local_rows) < 20:
            return None
        local_high = float(local_rows["high"].max())
        local_low = float(local_rows["low"].min())
        current_close = float(current_row["close"])
        previous_close = float(previous_row["close"])
        if float(current_row["low"]) < local_low and current_close > local_low and previous_close >= local_low:
            return "long", local_low, "low", local_high, local_low
        if float(current_row["high"]) > local_high and current_close < local_high and previous_close <= local_high:
            return "short", local_high, "high", local_high, local_low
        return None

    def _build_signal(
        self,
        symbol: str,
        frame: pd.DataFrame,
        ticker: TickerStats | None,
        *,
        direction: str,
        sweep_level: float,
        sweep_side: str,
        local_high: float,
        local_low: float,
    ) -> AlertSignal:
        current_row = frame.iloc[-1]
        candle_close_time = current_row["close_time"].to_pydatetime()
        live_price = float(ticker.last_price) if ticker is not None and ticker.last_price else float(current_row["close"])
        live_rsi = calculate_live_rsi(frame["close"], live_price, self.settings.rsi_length)
        score = self._score_signal(current_row, direction=direction, sweep_level=sweep_level)
        explanation = self._build_explanation(direction=direction, sweep_level=sweep_level, sweep_side=sweep_side)
        return AlertSignal(
            symbol=symbol,
            direction=direction,
            timeframe=self.settings.scan_timeframe,
            candle_open_time=current_row.name.to_pydatetime(),
            candle_close_time=candle_close_time,
            price=float(current_row["close"]),
            rsi=float(current_row["rsi"]),
            day_change_pct=ticker.price_change_percent if ticker else None,
            day_volume=ticker.quote_volume if ticker and ticker.quote_volume else ticker.volume if ticker else None,
            quote_volume=ticker.quote_volume if ticker else None,
            last_candle_volume=float(current_row["volume"]),
            avg_volume_20=float(current_row["avg_volume_20"]) if pd.notna(current_row["avg_volume_20"]) else 0.0,
            atr=float(current_row["atr"]) if pd.notna(current_row["atr"]) else 0.0,
            atr_pct=float(current_row["atr_pct"]) if pd.notna(current_row["atr_pct"]) else 0.0,
            ema20=float(current_row["ema20"]),
            ema50=float(current_row["ema50"]),
            score=score,
            explanation=explanation,
            metadata={
                "asset_class": "crypto",
                "strategy_key": self.strategy_key,
                "signal_model": "false_breakout_reclaim",
                "sweep_level": sweep_level,
                "sweep_side": sweep_side,
                "reclaim_close": float(current_row["close"]),
                "range_high": local_high,
                "range_low": local_low,
                "trigger_level": sweep_level,
                "marker_price": sweep_level,
                "marker_candle_close_time": candle_close_time.isoformat(),
                "volume_ratio": float(current_row["volume_ratio"]) if pd.notna(current_row["volume_ratio"]) else None,
                "live_price": live_price,
                "live_rsi": live_rsi,
                "signal_close_price": float(current_row["close"]),
                "signal_candle_close_time": candle_close_time.isoformat(),
                "interactive_ai_enabled": True,
                "interactive_risk_enabled": True,
                "interactive_reason_enabled": True,
                "context_text": explanation,
            },
        )

    def _build_explanation(self, *, direction: str, sweep_level: float, sweep_side: str) -> str:
        return (
            f"Liquidity sweep confirmed on {self.settings.scan_timeframe}: price ran the local {sweep_side} near {sweep_level:.4f} "
            f"and closed back {'above' if direction == 'long' else 'below'} it. This keeps the {'long' if direction == 'long' else 'short'} reversal scenario active."
        )

    def _score_signal(self, row: pd.Series, *, direction: str, sweep_level: float) -> int:
        atr_anchor = max(float(row["atr"]), float(row["close"]) * 0.003, 1e-9)
        reclaim_strength = abs(float(row["close"]) - sweep_level) / atr_anchor
        reclaim_score = min(reclaim_strength * 24.0, 36.0)
        volume_ratio = float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else 1.0
        volume_score = min(max(volume_ratio - 1.0, 0.0) * 16.0, 16.0)
        volatility_score = min(float(row["atr_pct"]) * 540.0, 12.0)
        if direction == "long":
            reaction_score = 14.0 if float(row["close"]) > float(row["ema20"]) else 8.0
        else:
            reaction_score = 14.0 if float(row["close"]) < float(row["ema20"]) else 8.0
        total = reclaim_score + volume_score + volatility_score + reaction_score + 10.0
        return int(max(0, min(round(total), 100)))
