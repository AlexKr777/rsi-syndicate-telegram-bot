from __future__ import annotations

import pandas as pd

from src.core.models import AlertSignal
from src.market.base_strategy_scanner import BaseStrategyScanner
from src.market.indicators import calculate_intraday_vwap, calculate_live_rsi, enrich_klines
from src.market.symbols import TickerStats


class VWAPScanner(BaseStrategyScanner):
    strategy_key = "vwap"

    async def _scan_symbol(self, symbol: str, ticker: TickerStats | None) -> AlertSignal | None:
        frame = await self.binance_client.get_klines(
            symbol=symbol,
            interval=self.settings.scan_timeframe,
            limit=self.settings.klines_limit,
        )
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        if len(enriched) < 2:
            return None
        day_frame = self._current_day_frame(enriched)
        if len(day_frame) < 2:
            return None
        vwap_series = calculate_intraday_vwap(day_frame)
        previous_row = day_frame.iloc[-2]
        current_row = day_frame.iloc[-1]
        previous_vwap = float(vwap_series.iloc[-2])
        current_vwap = float(vwap_series.iloc[-1])
        direction = None
        if float(previous_row["close"]) < previous_vwap and float(current_row["close"]) > current_vwap:
            direction = "long"
        elif float(previous_row["close"]) > previous_vwap and float(current_row["close"]) < current_vwap:
            direction = "short"
        if direction is None:
            return None
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
            current_row=current_row,
            direction=direction,
            current_vwap=current_vwap,
        )

    def _current_day_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        close_times = frame["close_time"].dt.tz_convert("UTC")
        current_day = pd.Timestamp(frame.iloc[-1]["close_time"]).tz_convert("UTC").date()
        return frame.loc[close_times.dt.date == current_day].copy()

    def _build_signal(
        self,
        symbol: str,
        frame: pd.DataFrame,
        ticker: TickerStats | None,
        *,
        current_row: pd.Series,
        direction: str,
        current_vwap: float,
    ) -> AlertSignal:
        candle_close_time = current_row["close_time"].to_pydatetime()
        live_price = float(ticker.last_price) if ticker is not None and ticker.last_price else float(current_row["close"])
        live_rsi = calculate_live_rsi(frame["close"], live_price, self.settings.rsi_length)
        score = self._score_signal(current_row, direction=direction, current_vwap=current_vwap)
        explanation = self._build_explanation(direction=direction, current_vwap=current_vwap)
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
                "signal_model": "vwap_reclaim_reject",
                "vwap_value": current_vwap,
                "session_anchor": "utc_day",
                "trigger_level": current_vwap,
                "marker_price": current_vwap,
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

    def _build_explanation(self, *, direction: str, current_vwap: float) -> str:
        return (
            f"Price {'reclaimed' if direction == 'long' else 'lost'} the daily VWAP ({current_vwap:.4f}) on {self.settings.scan_timeframe}. "
            f"This keeps the {'long' if direction == 'long' else 'short'} intraday bias active while VWAP is respected."
        )

    def _score_signal(self, row: pd.Series, *, direction: str, current_vwap: float) -> int:
        atr_anchor = max(float(row["atr"]), float(row["close"]) * 0.003, 1e-9)
        reclaim_distance = abs(float(row["close"]) - current_vwap) / atr_anchor
        reclaim_score = min(reclaim_distance * 24.0, 34.0)
        volume_ratio = float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else 1.0
        volume_score = min(max(volume_ratio - 1.0, 0.0) * 16.0, 16.0)
        volatility_score = min(float(row["atr_pct"]) * 520.0, 12.0)
        if direction == "long":
            trend_score = 16.0 if float(row["close"]) > float(row["ema20"]) > float(row["ema50"]) else 8.0
        else:
            trend_score = 16.0 if float(row["close"]) < float(row["ema20"]) < float(row["ema50"]) else 8.0
        total = reclaim_score + volume_score + volatility_score + trend_score + 12.0
        return int(max(0, min(round(total), 100)))
