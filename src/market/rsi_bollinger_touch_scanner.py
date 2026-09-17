from __future__ import annotations

import pandas as pd

from src.core.models import AlertSignal
from src.market.base_strategy_scanner import BaseStrategyScanner
from src.market.indicators import calculate_bollinger_bands, calculate_live_rsi, enrich_klines
from src.market.symbols import TickerStats


class RSIBollingerTouchScanner(BaseStrategyScanner):
    strategy_key = "rsi_bollinger_touch"
    bollinger_length = 30
    bollinger_stddev = 2.05

    async def _scan_symbol(self, symbol: str, ticker: TickerStats | None) -> AlertSignal | None:
        frame = await self.binance_client.get_klines(
            symbol=symbol,
            interval=self.settings.scan_timeframe,
            limit=self.settings.klines_limit,
        )
        enriched = enrich_klines(frame, self.settings.rsi_length).copy()
        bb_mid, bb_upper, bb_lower = calculate_bollinger_bands(
            enriched["close"],
            length=self.bollinger_length,
            num_std=self.bollinger_stddev,
        )
        enriched["bb30_mid"] = bb_mid
        enriched["bb30_upper"] = bb_upper
        enriched["bb30_lower"] = bb_lower
        enriched["bb30_width"] = (bb_upper - bb_lower).fillna(0.0)
        enriched = enriched.dropna()
        if len(enriched) < 3:
            return None

        candidate = self._detect_candidate(enriched)
        if candidate is None:
            return None
        direction, market_state, touch_idx = candidate
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
            market_state=market_state,
            touch_idx=touch_idx,
        )

    def _detect_candidate(self, frame: pd.DataFrame) -> tuple[str, str, int] | None:
        previous_row = frame.iloc[-2]
        current_row = frame.iloc[-1]
        market_state = "sideways" if self._is_sideways(previous_row, current_row) else "directional"
        if market_state == "sideways":
            return None

        touch_idx = self._select_touch_candidate(frame, direction="long")
        if touch_idx is not None:
            return "long", market_state, touch_idx
        touch_idx = self._select_touch_candidate(frame, direction="short")
        if touch_idx is not None:
            return "short", market_state, touch_idx
        return None

    def _is_sideways(self, previous_row: pd.Series, current_row: pd.Series) -> bool:
        close_price = max(float(current_row["close"]), 1e-9)
        bb_width_ratio = float(current_row["bb30_width"]) / close_price
        ema_gap_ratio = abs(float(current_row["ema20"]) - float(current_row["ema50"])) / close_price
        ema20_slope_ratio = abs(float(current_row["ema20"]) - float(previous_row["ema20"])) / close_price
        mean_distance_ratio = abs(float(current_row["close"]) - float(current_row["bb30_mid"])) / max(
            float(current_row["bb30_width"]),
            close_price * 0.004,
            1e-9,
        )
        volume_ratio = float(current_row["volume_ratio"]) if pd.notna(current_row["volume_ratio"]) else 1.0
        atr_ratio = float(current_row["atr_pct"]) if pd.notna(current_row["atr_pct"]) else 0.0
        quiet_checks = 0
        quiet_checks += 1 if bb_width_ratio < 0.022 else 0
        quiet_checks += 1 if ema_gap_ratio < 0.0028 else 0
        quiet_checks += 1 if ema20_slope_ratio < 0.0012 else 0
        quiet_checks += 1 if mean_distance_ratio < 0.38 else 0
        quiet_checks += 1 if volume_ratio < 1.08 else 0
        quiet_checks += 1 if atr_ratio < 0.0045 else 0
        return quiet_checks >= 5

    def _select_touch_candidate(self, frame: pd.DataFrame, *, direction: str) -> int | None:
        current_idx = len(frame) - 1
        previous_idx = current_idx - 1
        current_row = frame.iloc[current_idx]
        previous_row = frame.iloc[previous_idx]
        if self._touches_band(current_row, direction=direction) and self._touch_rsi_ok(current_row, direction=direction):
            if self._current_touch_is_confirmed(current_row, direction=direction):
                return current_idx
        if self._touches_band(previous_row, direction=direction) and self._touch_rsi_ok(previous_row, direction=direction):
            if self._follow_through_after_touch(previous_row, current_row, direction=direction):
                return previous_idx
        return None

    def _touches_band(self, row: pd.Series, *, direction: str) -> bool:
        if direction == "long":
            return float(row["low"]) <= float(row["bb30_lower"])
        return float(row["high"]) >= float(row["bb30_upper"])

    def _touch_rsi_ok(self, row: pd.Series, *, direction: str) -> bool:
        rsi = float(row["rsi"])
        if direction == "long":
            return rsi <= self.settings.rsi_oversold
        return rsi >= self.settings.rsi_overbought

    def _current_touch_is_confirmed(self, row: pd.Series, *, direction: str) -> bool:
        candle_high = float(row["high"])
        candle_low = float(row["low"])
        close_price = float(row["close"])
        candle_range = max(candle_high - candle_low, close_price * 0.003, 1e-9)
        if direction == "long":
            return close_price >= float(row["bb30_lower"]) or (close_price - candle_low) / candle_range >= 0.5
        return close_price <= float(row["bb30_upper"]) or (candle_high - close_price) / candle_range >= 0.5

    def _follow_through_after_touch(self, touch_row: pd.Series, current_row: pd.Series, *, direction: str) -> bool:
        touch_price = float(touch_row["low"] if direction == "long" else touch_row["high"])
        current_close = float(current_row["close"])
        atr_ratio = float(touch_row["atr"]) / max(float(touch_row["close"]), 1e-9)
        move_away = (
            (current_close - touch_price) / max(touch_price, 1e-9)
            if direction == "long"
            else (touch_price - current_close) / max(touch_price, 1e-9)
        )
        if direction == "long":
            return (
                current_close > float(touch_row["close"])
                and float(current_row["low"]) >= float(touch_row["low"])
                and (current_close >= float(current_row["bb30_lower"]) or float(current_row["close"]) > float(touch_row["close"]))
                and move_away >= max(atr_ratio * 0.25, 0.002)
            )
        return (
            current_close < float(touch_row["close"])
            and float(current_row["high"]) <= float(touch_row["high"])
            and (current_close <= float(current_row["bb30_upper"]) or float(current_row["close"]) < float(touch_row["close"]))
            and move_away >= max(atr_ratio * 0.25, 0.002)
        )

    def _build_signal(
        self,
        symbol: str,
        frame: pd.DataFrame,
        ticker: TickerStats | None,
        *,
        direction: str,
        market_state: str,
        touch_idx: int,
    ) -> AlertSignal:
        previous_row = frame.iloc[-2]
        current_row = frame.iloc[-1]
        touch_row = frame.iloc[touch_idx]
        candle_close_time = current_row["close_time"].to_pydatetime()
        live_price = float(ticker.last_price) if ticker is not None and ticker.last_price else float(current_row["close"])
        live_rsi = calculate_live_rsi(frame["close"], live_price, self.settings.rsi_length)
        score = self._score_signal(touch_row, previous_row, current_row, direction=direction)
        explanation = self._build_explanation(direction=direction, touch_idx=touch_idx, current_idx=len(frame) - 1)
        marker_price = float(touch_row["low"] if direction == "long" else touch_row["high"])
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
                "signal_model": "rsi_bollinger_touch",
                "bb_length": self.bollinger_length,
                "bb_stddev": self.bollinger_stddev,
                "bb_mid": float(current_row["bb30_mid"]),
                "bb_upper": float(current_row["bb30_upper"]),
                "bb_lower": float(current_row["bb30_lower"]),
                "rsi_gate": self.settings.rsi_oversold if direction == "long" else self.settings.rsi_overbought,
                "anti_sideways_state": market_state,
                "market_regime_tag": "Directional",
                "marker_price": marker_price,
                "marker_candle_close_time": touch_row["close_time"].to_pydatetime().isoformat(),
                "touch_candle_close_time": touch_row["close_time"].to_pydatetime().isoformat(),
                "touch_is_current_candle": touch_idx == len(frame) - 1,
                "volume_ratio": float(current_row["volume_ratio"]) if pd.notna(current_row["volume_ratio"]) else None,
                "live_price": live_price,
                "live_rsi": live_rsi,
                "signal_close_price": float(current_row["close"]),
                "signal_candle_close_time": candle_close_time.isoformat(),
                "setup_direction": direction,
                "interactive_ai_enabled": True,
                "interactive_risk_enabled": True,
                "interactive_reason_enabled": True,
                "context_text": explanation,
            },
        )

    def _build_explanation(self, *, direction: str, touch_idx: int, current_idx: int) -> str:
        touch_context = "on the current candle" if touch_idx == current_idx else "on the prior candle with confirmation right after it"
        if direction == "long":
            return (
                f"RSI stayed below {self.settings.rsi_oversold:.0f} while price tagged the lower 30-period Bollinger Band on {self.settings.scan_timeframe} {touch_context}. "
                "The anti-sideways filter kept this out of flat chop, and the latest candle confirmed a move away from the lower band instead of a random range bounce."
            )
        return (
            f"RSI stayed above {self.settings.rsi_overbought:.0f} while price tagged the upper 30-period Bollinger Band on {self.settings.scan_timeframe} {touch_context}. "
            "The anti-sideways filter kept this out of flat chop, and the latest candle confirmed a move away from the upper band instead of a random range fade."
        )

    def _score_signal(
        self,
        touch_row: pd.Series,
        previous_row: pd.Series,
        current_row: pd.Series,
        *,
        direction: str,
    ) -> int:
        close_price = max(float(current_row["close"]), 1e-9)
        band_width = max(float(current_row["bb30_width"]), close_price * 0.008, 1e-9)
        if direction == "long":
            touch_depth = max(float(touch_row["bb30_lower"]) - float(touch_row["low"]), 0.0) / band_width
            rsi_distance = max(self.settings.rsi_oversold - float(touch_row["rsi"]), 0.0)
            confirmation_move = max(float(current_row["close"]) - float(touch_row["low"]), 0.0) / max(float(touch_row["low"]), 1e-9)
        else:
            touch_depth = max(float(touch_row["high"]) - float(touch_row["bb30_upper"]), 0.0) / band_width
            rsi_distance = max(float(touch_row["rsi"]) - self.settings.rsi_overbought, 0.0)
            confirmation_move = max(float(touch_row["high"]) - float(current_row["close"]), 0.0) / max(float(touch_row["high"]), 1e-9)
        ema_gap_ratio = abs(float(current_row["ema20"]) - float(current_row["ema50"])) / close_price
        ema20_slope_ratio = abs(float(current_row["ema20"]) - float(previous_row["ema20"])) / close_price
        touch_score = min(touch_depth * 28.0, 28.0)
        rsi_score = min(rsi_distance * 3.2, 22.0)
        confirmation_score = min(confirmation_move * 2200.0, 18.0)
        regime_score = min((ema_gap_ratio * 3800.0) + (ema20_slope_ratio * 8200.0), 16.0)
        volume_ratio = max(
            float(current_row["volume_ratio"]) if pd.notna(current_row["volume_ratio"]) else 1.0,
            float(touch_row["volume_ratio"]) if pd.notna(touch_row["volume_ratio"]) else 1.0,
        )
        volume_score = min(max(volume_ratio - 1.0, 0.0) * 14.0, 14.0)
        volatility_score = min(float(current_row["atr_pct"]) * 360.0, 14.0)
        total = touch_score + rsi_score + confirmation_score + regime_score + volume_score + volatility_score
        return int(max(0, min(round(total), 100)))
