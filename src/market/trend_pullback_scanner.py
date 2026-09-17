from __future__ import annotations

import pandas as pd

from src.core.models import AlertSignal
from src.market.base_strategy_scanner import BaseStrategyScanner
from src.market.indicators import calculate_live_rsi, enrich_klines
from src.market.symbols import TickerStats


class TrendPullbackScanner(BaseStrategyScanner):
    strategy_key = "trend_pullback"

    async def _scan_symbol(self, symbol: str, ticker: TickerStats | None) -> AlertSignal | None:
        frame = await self.binance_client.get_klines(
            symbol=symbol,
            interval=self.settings.scan_timeframe,
            limit=self.settings.klines_limit,
        )
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        if len(enriched) < 3:
            return None
        candidate = self._detect_candidate(enriched)
        if candidate is None:
            return None
        direction, touched_ema, trend_direction = candidate
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
            touched_ema=touched_ema,
            trend_direction=trend_direction,
        )

    def _detect_candidate(self, frame: pd.DataFrame) -> tuple[str, int, str] | None:
        current_row = frame.iloc[-1]
        close = float(current_row["close"])
        open_price = float(current_row["open"])
        ema20 = float(current_row["ema20"])
        ema50 = float(current_row["ema50"])
        low = float(current_row["low"])
        high = float(current_row["high"])

        if close > ema20 > ema50:
            touched_ema = None
            if low <= ema50 and close > ema50:
                touched_ema = 50
            elif low <= ema20 and close > ema20:
                touched_ema = 20
            if touched_ema is not None and close > open_price:
                return "long", touched_ema, "bullish"

        if close < ema20 < ema50:
            touched_ema = None
            if high >= ema50 and close < ema50:
                touched_ema = 50
            elif high >= ema20 and close < ema20:
                touched_ema = 20
            if touched_ema is not None and close < open_price:
                return "short", touched_ema, "bearish"
        return None

    def _build_signal(
        self,
        symbol: str,
        frame: pd.DataFrame,
        ticker: TickerStats | None,
        *,
        direction: str,
        touched_ema: int,
        trend_direction: str,
    ) -> AlertSignal:
        current_row = frame.iloc[-1]
        candle_close_time = current_row["close_time"].to_pydatetime()
        live_price = float(ticker.last_price) if ticker is not None and ticker.last_price else float(current_row["close"])
        live_rsi = calculate_live_rsi(frame["close"], live_price, self.settings.rsi_length)
        score = self._score_signal(current_row, touched_ema=touched_ema, direction=direction)
        explanation = self._build_explanation(direction=direction, touched_ema=touched_ema, trend_direction=trend_direction)
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
                "signal_model": "trend_pullback_ema",
                "ema_basis": f"ema{touched_ema}",
                "trend_direction": trend_direction,
                "reaction_close": float(current_row["close"]),
                "touched_ema": touched_ema,
                "trigger_level": float(current_row["ema50"] if touched_ema == 50 else current_row["ema20"]),
                "marker_price": float(current_row["ema50"] if touched_ema == 50 else current_row["ema20"]),
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

    def _build_explanation(self, *, direction: str, touched_ema: int, trend_direction: str) -> str:
        return (
            f"{trend_direction.title()} trend held and price reacted from EMA{touched_ema} on {self.settings.scan_timeframe}. "
            f"The confirmation candle closed back in favor of the {'long' if direction == 'long' else 'short'} continuation."
        )

    def _score_signal(self, row: pd.Series, *, touched_ema: int, direction: str) -> int:
        volume_ratio = float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else 1.0
        volume_score = min(max(volume_ratio - 1.0, 0.0) * 16.0, 16.0)
        volatility_score = min(float(row["atr_pct"]) * 520.0, 12.0)
        basis_bonus = 18.0 if touched_ema == 50 else 12.0
        if direction == "long":
            confirmation_strength = max(float(row["close"]) - float(row["open"]), 0.0) / max(float(row["atr"]), 1e-9)
        else:
            confirmation_strength = max(float(row["open"]) - float(row["close"]), 0.0) / max(float(row["atr"]), 1e-9)
        confirmation_score = min(confirmation_strength * 22.0, 34.0)
        trend_score = 16.0
        total = volume_score + volatility_score + basis_bonus + confirmation_score + trend_score
        return int(max(0, min(round(total), 100)))
