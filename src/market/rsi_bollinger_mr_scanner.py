from __future__ import annotations

import pandas as pd

from src.core.models import AlertSignal
from src.market.base_strategy_scanner import BaseStrategyScanner
from src.market.indicators import calculate_live_rsi, enrich_klines
from src.market.symbols import TickerStats


class RSIBollingerMeanReversionScanner(BaseStrategyScanner):
    strategy_key = "rsi_bollinger_mr"

    async def _scan_symbol(self, symbol: str, ticker: TickerStats | None) -> AlertSignal | None:
        frame = await self.binance_client.get_klines(
            symbol=symbol,
            interval=self.settings.scan_timeframe,
            limit=self.settings.klines_limit,
        )
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        if len(enriched) < 2:
            return None
        candidate = self._detect_candidate(enriched)
        if candidate is None:
            return None
        direction, trend_filter_state = candidate
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
            trend_filter_state=trend_filter_state,
        )

    def _detect_candidate(self, frame: pd.DataFrame) -> tuple[str, str] | None:
        previous_row = frame.iloc[-2]
        current_row = frame.iloc[-1]
        previous_close = float(previous_row["close"])
        current_close = float(current_row["close"])
        current_rsi = float(current_row["rsi"])

        bullish_trend = current_close > float(current_row["ema20"]) > float(current_row["ema50"])
        bearish_trend = current_close < float(current_row["ema20"]) < float(current_row["ema50"])

        if (
            previous_close < float(previous_row["bb_lower"])
            and current_close > float(current_row["bb_lower"])
            and current_rsi <= self.settings.rsi_oversold
        ):
            if bearish_trend:
                return None
            return "long", "trend_ok"

        if (
            previous_close > float(previous_row["bb_upper"])
            and current_close < float(current_row["bb_upper"])
            and current_rsi >= self.settings.rsi_overbought
        ):
            if bullish_trend:
                return None
            return "short", "trend_ok"
        return None

    def _build_signal(
        self,
        symbol: str,
        frame: pd.DataFrame,
        ticker: TickerStats | None,
        *,
        direction: str,
        trend_filter_state: str,
    ) -> AlertSignal:
        previous_row = frame.iloc[-2]
        current_row = frame.iloc[-1]
        candle_close_time = current_row["close_time"].to_pydatetime()
        live_price = float(ticker.last_price) if ticker is not None and ticker.last_price else float(current_row["close"])
        live_rsi = calculate_live_rsi(frame["close"], live_price, self.settings.rsi_length)
        score = self._score_signal(previous_row, current_row, direction=direction)
        explanation = self._build_explanation(direction=direction)
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
                "signal_model": "rsi_bollinger_mean_reversion",
                "bb_upper": float(current_row["bb_upper"]),
                "bb_lower": float(current_row["bb_lower"]),
                "rsi_gate": self.settings.rsi_oversold if direction == "long" else self.settings.rsi_overbought,
                "trend_filter_state": trend_filter_state,
                "marker_price": float(current_row["bb_lower"] if direction == "long" else current_row["bb_upper"]),
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

    def _build_explanation(self, *, direction: str) -> str:
        if direction == "long":
            return (
                f"Price re-entered above the lower Bollinger Band on {self.settings.scan_timeframe} while RSI stayed in oversold territory. "
                "This is a stricter mean-reversion long than the legacy Bollinger signal."
            )
        return (
            f"Price re-entered below the upper Bollinger Band on {self.settings.scan_timeframe} while RSI stayed in overbought territory. "
            "This is a stricter mean-reversion short than the legacy Bollinger signal."
        )

    def _score_signal(self, previous_row: pd.Series, current_row: pd.Series, *, direction: str) -> int:
        band_width = max(float(current_row["bb_width"]), float(current_row["close"]) * 0.006, 1e-9)
        if direction == "long":
            exit_severity = max(float(previous_row["bb_lower"]) - float(previous_row["close"]), 0.0) / band_width
            reentry_strength = max(float(current_row["close"]) - float(current_row["bb_lower"]), 0.0) / band_width
            rsi_distance = max(self.settings.rsi_oversold - float(current_row["rsi"]), 0.0)
        else:
            exit_severity = max(float(previous_row["close"]) - float(previous_row["bb_upper"]), 0.0) / band_width
            reentry_strength = max(float(current_row["bb_upper"]) - float(current_row["close"]), 0.0) / band_width
            rsi_distance = max(float(current_row["rsi"]) - self.settings.rsi_overbought, 0.0)
        exit_score = min(exit_severity * 20.0, 28.0)
        reentry_score = min(reentry_strength * 18.0, 22.0)
        rsi_score = min(rsi_distance * 3.5, 22.0)
        volume_ratio = float(current_row["volume_ratio"]) if pd.notna(current_row["volume_ratio"]) else 1.0
        volume_score = min(max(volume_ratio - 1.0, 0.0) * 14.0, 14.0)
        volatility_score = min(float(current_row["atr_pct"]) * 520.0, 14.0)
        total = exit_score + reentry_score + rsi_score + volume_score + volatility_score
        return int(max(0, min(round(total), 100)))
