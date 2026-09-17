from __future__ import annotations

import pandas as pd

from src.core.models import AlertSignal
from src.market.base_strategy_scanner import BaseStrategyScanner
from src.market.indicators import calculate_live_rsi, enrich_klines
from src.market.symbols import TickerStats


class RSIDivergenceScanner(BaseStrategyScanner):
    strategy_key = "rsi_divergence"
    lookback_candles = 28
    pivot_window = 2
    max_second_swing_age_candles = 3

    async def _scan_symbol(self, symbol: str, ticker: TickerStats | None) -> AlertSignal | None:
        frame = await self.binance_client.get_klines(
            symbol=symbol,
            interval=self.settings.scan_timeframe,
            limit=self.settings.klines_limit,
        )
        enriched = enrich_klines(frame, self.settings.rsi_length).dropna()
        if len(enriched) < 8:
            return None

        candidate = self._detect_candidate(enriched)
        if candidate is None:
            return None
        direction, first_idx, second_idx = candidate
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
            first_idx=first_idx,
            second_idx=second_idx,
        )

    def _detect_candidate(self, frame: pd.DataFrame) -> tuple[str, int, int] | None:
        start = max(len(frame) - self.lookback_candles, 0)
        current_idx = len(frame) - 1
        confirmed_pivot_lows = [
            idx
            for idx in range(max(start, self.pivot_window), max(current_idx - self.pivot_window + 1, self.pivot_window))
            if self._is_pivot_low(frame, idx)
        ]
        bullish_candidate = self._detect_bullish_candidate(frame, confirmed_pivot_lows, current_idx)
        if bullish_candidate is not None:
            return bullish_candidate

        confirmed_pivot_highs = [
            idx
            for idx in range(max(start, self.pivot_window), max(current_idx - self.pivot_window + 1, self.pivot_window))
            if self._is_pivot_high(frame, idx)
        ]
        bearish_candidate = self._detect_bearish_candidate(frame, confirmed_pivot_highs, current_idx)
        if bearish_candidate is not None:
            return bearish_candidate
        return None

    def _detect_bullish_candidate(
        self,
        frame: pd.DataFrame,
        pivot_lows: list[int],
        current_idx: int,
    ) -> tuple[str, int, int] | None:
        second_candidates = self._recent_second_swing_candidates(frame, pivot_lows, current_idx, direction="long")
        for second_idx in second_candidates:
            first_candidates = [idx for idx in pivot_lows if idx < second_idx - 1]
            for first_idx in reversed(first_candidates):
                if self._is_valid_bullish_divergence(frame, first_idx, second_idx, current_idx):
                    return "long", first_idx, second_idx
        return None

    def _detect_bearish_candidate(
        self,
        frame: pd.DataFrame,
        pivot_highs: list[int],
        current_idx: int,
    ) -> tuple[str, int, int] | None:
        second_candidates = self._recent_second_swing_candidates(frame, pivot_highs, current_idx, direction="short")
        for second_idx in second_candidates:
            first_candidates = [idx for idx in pivot_highs if idx < second_idx - 1]
            for first_idx in reversed(first_candidates):
                if self._is_valid_bearish_divergence(frame, first_idx, second_idx, current_idx):
                    return "short", first_idx, second_idx
        return None

    def _recent_second_swing_candidates(
        self,
        frame: pd.DataFrame,
        confirmed_pivots: list[int],
        current_idx: int,
        *,
        direction: str,
    ) -> list[int]:
        lower_bound = max(current_idx - self.max_second_swing_age_candles, 0)
        candidates = [idx for idx in confirmed_pivots if idx >= lower_bound]
        previous_idx = current_idx - 1
        if previous_idx >= max(self.pivot_window, 1):
            if direction == "long" and self._is_provisional_recent_low_candidate(frame, previous_idx):
                candidates.append(previous_idx)
            if direction == "short" and self._is_provisional_recent_high_candidate(frame, previous_idx):
                candidates.append(previous_idx)
        if direction == "long" and self._is_current_swing_low_candidate(frame, current_idx):
            candidates.append(current_idx)
        if direction == "short" and self._is_current_swing_high_candidate(frame, current_idx):
            candidates.append(current_idx)
        # Keep only the most recent unique candidates so we do not spam stale structures.
        return list(dict.fromkeys(sorted(candidates, reverse=True)))

    def _is_pivot_low(self, frame: pd.DataFrame, idx: int) -> bool:
        low = float(frame.iloc[idx]["low"])
        left_window = frame.iloc[idx - self.pivot_window : idx]
        right_window = frame.iloc[idx + 1 : idx + self.pivot_window + 1]
        if left_window.empty or right_window.empty:
            return False
        return low <= float(left_window["low"].min()) and low < float(right_window["low"].min())

    def _is_pivot_high(self, frame: pd.DataFrame, idx: int) -> bool:
        high = float(frame.iloc[idx]["high"])
        left_window = frame.iloc[idx - self.pivot_window : idx]
        right_window = frame.iloc[idx + 1 : idx + self.pivot_window + 1]
        if left_window.empty or right_window.empty:
            return False
        return high >= float(left_window["high"].max()) and high > float(right_window["high"].max())

    def _is_current_swing_low_candidate(self, frame: pd.DataFrame, current_idx: int) -> bool:
        if current_idx < 2:
            return False
        current_row = frame.iloc[current_idx]
        lookback_window = frame.iloc[max(current_idx - 2, 0) : current_idx]
        if lookback_window.empty:
            return False
        current_low = float(current_row["low"])
        if current_low > float(lookback_window["low"].min()):
            return False
        candle_range = max(float(current_row["high"]) - current_low, float(current_row["close"]) * 0.003, 1e-9)
        rejection_ratio = (float(current_row["close"]) - current_low) / candle_range
        return rejection_ratio >= 0.4 or float(current_row["close"]) > float(frame.iloc[current_idx - 1]["close"])

    def _is_provisional_recent_low_candidate(self, frame: pd.DataFrame, idx: int) -> bool:
        if idx < 2 or idx >= len(frame) - 1:
            return False
        row = frame.iloc[idx]
        left_window = frame.iloc[idx - 2 : idx]
        right_row = frame.iloc[idx + 1]
        low = float(row["low"])
        return low <= float(left_window["low"].min()) and low < float(right_row["low"])

    def _is_current_swing_high_candidate(self, frame: pd.DataFrame, current_idx: int) -> bool:
        if current_idx < 2:
            return False
        current_row = frame.iloc[current_idx]
        lookback_window = frame.iloc[max(current_idx - 2, 0) : current_idx]
        if lookback_window.empty:
            return False
        current_high = float(current_row["high"])
        if current_high < float(lookback_window["high"].max()):
            return False
        candle_range = max(current_high - float(current_row["low"]), float(current_row["close"]) * 0.003, 1e-9)
        rejection_ratio = (current_high - float(current_row["close"])) / candle_range
        return rejection_ratio >= 0.4 or float(current_row["close"]) < float(frame.iloc[current_idx - 1]["close"])

    def _is_provisional_recent_high_candidate(self, frame: pd.DataFrame, idx: int) -> bool:
        if idx < 2 or idx >= len(frame) - 1:
            return False
        row = frame.iloc[idx]
        left_window = frame.iloc[idx - 2 : idx]
        right_row = frame.iloc[idx + 1]
        high = float(row["high"])
        return high >= float(left_window["high"].max()) and high > float(right_row["high"])

    def _is_valid_bullish_divergence(
        self,
        frame: pd.DataFrame,
        first_idx: int,
        second_idx: int,
        current_idx: int,
    ) -> bool:
        first_row = frame.iloc[first_idx]
        second_row = frame.iloc[second_idx]
        if float(first_row["rsi"]) > self.settings.rsi_oversold:
            return False
        if float(second_row["rsi"]) > 45.0:
            return False
        price_extension = (float(first_row["low"]) - float(second_row["low"])) / max(float(first_row["low"]), 1e-9)
        min_extension = max(float(first_row["atr"]) / max(float(first_row["close"]), 1e-9) * 0.25, 0.0015)
        if price_extension <= min_extension:
            return False
        if float(second_row["rsi"]) <= float(first_row["rsi"]) + 2.0:
            return False
        if not self._has_bullish_rebound(frame, first_idx, second_idx):
            return False
        if not self._has_confirmation(frame, second_idx, current_idx, direction="long"):
            return False
        return True

    def _is_valid_bearish_divergence(
        self,
        frame: pd.DataFrame,
        first_idx: int,
        second_idx: int,
        current_idx: int,
    ) -> bool:
        first_row = frame.iloc[first_idx]
        second_row = frame.iloc[second_idx]
        if float(first_row["rsi"]) < self.settings.rsi_overbought:
            return False
        if float(second_row["rsi"]) < 55.0:
            return False
        price_extension = (float(second_row["high"]) - float(first_row["high"])) / max(float(first_row["high"]), 1e-9)
        min_extension = max(float(first_row["atr"]) / max(float(first_row["close"]), 1e-9) * 0.25, 0.0015)
        if price_extension <= min_extension:
            return False
        if float(second_row["rsi"]) >= float(first_row["rsi"]) - 2.0:
            return False
        if not self._has_bearish_pullback(frame, first_idx, second_idx):
            return False
        if not self._has_confirmation(frame, second_idx, current_idx, direction="short"):
            return False
        return True

    def _has_bullish_rebound(self, frame: pd.DataFrame, first_idx: int, second_idx: int) -> bool:
        first_row = frame.iloc[first_idx]
        window = frame.iloc[first_idx + 1 : second_idx]
        if window.empty:
            return False
        rebound_high = float(window["high"].max())
        rebound_size = (rebound_high - float(first_row["low"])) / max(float(first_row["low"]), 1e-9)
        atr_ratio = max(
            float(first_row["atr"]) / max(float(first_row["close"]), 1e-9),
            float(frame.iloc[second_idx]["atr"]) / max(float(frame.iloc[second_idx]["close"]), 1e-9),
        )
        return rebound_size >= max(atr_ratio * 0.8, 0.005)

    def _has_bearish_pullback(self, frame: pd.DataFrame, first_idx: int, second_idx: int) -> bool:
        first_row = frame.iloc[first_idx]
        window = frame.iloc[first_idx + 1 : second_idx]
        if window.empty:
            return False
        pullback_low = float(window["low"].min())
        pullback_size = (float(first_row["high"]) - pullback_low) / max(float(first_row["high"]), 1e-9)
        atr_ratio = max(
            float(first_row["atr"]) / max(float(first_row["close"]), 1e-9),
            float(frame.iloc[second_idx]["atr"]) / max(float(frame.iloc[second_idx]["close"]), 1e-9),
        )
        return pullback_size >= max(atr_ratio * 0.8, 0.005)

    def _has_confirmation(self, frame: pd.DataFrame, second_idx: int, current_idx: int, *, direction: str) -> bool:
        second_row = frame.iloc[second_idx]
        if second_idx == current_idx:
            if direction == "long":
                candle_range = max(float(second_row["high"]) - float(second_row["low"]), float(second_row["close"]) * 0.003, 1e-9)
                return (float(second_row["close"]) - float(second_row["low"])) / candle_range >= 0.4
            candle_range = max(float(second_row["high"]) - float(second_row["low"]), float(second_row["close"]) * 0.003, 1e-9)
            return (float(second_row["high"]) - float(second_row["close"])) / candle_range >= 0.4

        confirmation_window = frame.iloc[second_idx + 1 : current_idx + 1]
        if confirmation_window.empty:
            return False
        current_row = frame.iloc[current_idx]
        second_price = float(second_row["low"] if direction == "long" else second_row["high"])
        current_close = float(current_row["close"])
        confirmation_move = (
            (current_close - second_price) / max(second_price, 1e-9)
            if direction == "long"
            else (second_price - current_close) / max(second_price, 1e-9)
        )
        atr_ratio = float(second_row["atr"]) / max(float(second_row["close"]), 1e-9)
        if direction == "long":
            return (
                float(confirmation_window["close"].max()) >= float(second_row["close"])
                and float(current_row["low"]) >= float(second_row["low"])
                and confirmation_move >= max(atr_ratio * 0.3, 0.002)
            )
        return (
            float(confirmation_window["close"].min()) <= float(second_row["close"])
            and float(current_row["high"]) <= float(second_row["high"])
            and confirmation_move >= max(atr_ratio * 0.3, 0.002)
        )

    def _build_signal(
        self,
        symbol: str,
        frame: pd.DataFrame,
        ticker: TickerStats | None,
        *,
        direction: str,
        first_idx: int,
        second_idx: int,
    ) -> AlertSignal:
        first_row = frame.iloc[first_idx]
        second_row = frame.iloc[second_idx]
        current_row = frame.iloc[-1]
        second_swing_age_candles = max(len(frame) - 1 - second_idx, 0)
        candle_close_time = current_row["close_time"].to_pydatetime()
        live_price = float(ticker.last_price) if ticker is not None and ticker.last_price else float(current_row["close"])
        live_rsi = calculate_live_rsi(frame["close"], live_price, self.settings.rsi_length)
        score = self._score_signal(first_row, second_row, current_row, direction=direction)
        explanation = self._build_explanation(direction=direction, first_row=first_row, second_row=second_row, current_row=current_row)
        marker_price = float(second_row["low"] if direction == "long" else second_row["high"])
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
                "signal_model": "rsi_divergence",
                "divergence_type": "bullish" if direction == "long" else "bearish",
                "first_swing_price": float(first_row["low"] if direction == "long" else first_row["high"]),
                "second_swing_price": float(second_row["low"] if direction == "long" else second_row["high"]),
                "first_swing_rsi": float(first_row["rsi"]),
                "second_swing_rsi": float(second_row["rsi"]),
                "second_swing_age_candles": second_swing_age_candles,
                "rsi_gate_primary": self.settings.rsi_oversold if direction == "long" else self.settings.rsi_overbought,
                "market_regime_tag": "Reversal",
                "marker_price": marker_price,
                "marker_candle_close_time": second_row["close_time"].to_pydatetime().isoformat(),
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

    def _build_explanation(
        self,
        *,
        direction: str,
        first_row: pd.Series,
        second_row: pd.Series,
        current_row: pd.Series,
    ) -> str:
        if direction == "long":
            return (
                f"Price printed a second swing low on {self.settings.scan_timeframe} below the first low, but RSI improved from {float(first_row['rsi']):.2f} to {float(second_row['rsi']):.2f} after the first swing broke below {self.settings.rsi_oversold:.0f}. "
                f"Price is now reacting away from that second low with the latest close at {float(current_row['close']):.4f}, which keeps the bullish divergence active."
            )
        return (
            f"Price printed a second swing high on {self.settings.scan_timeframe} above the first high, but RSI faded from {float(first_row['rsi']):.2f} to {float(second_row['rsi']):.2f} after the first swing broke above {self.settings.rsi_overbought:.0f}. "
            f"Price is now reacting away from that second high with the latest close at {float(current_row['close']):.4f}, which keeps the bearish divergence active."
        )

    def _score_signal(
        self,
        first_row: pd.Series,
        second_row: pd.Series,
        current_row: pd.Series,
        *,
        direction: str,
    ) -> int:
        if direction == "long":
            price_extension = max(float(first_row["low"]) - float(second_row["low"]), 0.0) / max(float(first_row["low"]), 1e-9)
            rsi_divergence = max(float(second_row["rsi"]) - float(first_row["rsi"]), 0.0)
            confirmation_move = max(float(current_row["close"]) - float(second_row["low"]), 0.0) / max(float(second_row["low"]), 1e-9)
        else:
            price_extension = max(float(second_row["high"]) - float(first_row["high"]), 0.0) / max(float(first_row["high"]), 1e-9)
            rsi_divergence = max(float(first_row["rsi"]) - float(second_row["rsi"]), 0.0)
            confirmation_move = max(float(second_row["high"]) - float(current_row["close"]), 0.0) / max(float(second_row["high"]), 1e-9)
        volume_ratio = float(current_row["volume_ratio"]) if pd.notna(current_row["volume_ratio"]) else 1.0
        price_score = min(price_extension * 2800.0, 24.0)
        rsi_score = min(rsi_divergence * 3.4, 30.0)
        confirmation_score = min(confirmation_move * 2400.0, 16.0)
        volume_score = min(max(volume_ratio - 1.0, 0.0) * 14.0, 14.0)
        volatility_score = min(float(current_row["atr_pct"]) * 420.0, 18.0)
        structure_score = (
            8.0
            if direction == "long" and float(current_row["close"]) >= float(second_row["close"])
            else 8.0
            if direction == "short" and float(current_row["close"]) <= float(second_row["close"])
            else 4.0
        )
        total = price_score + rsi_score + confirmation_score + volume_score + volatility_score + structure_score
        return int(max(0, min(round(total), 100)))
