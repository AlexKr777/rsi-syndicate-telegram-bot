from __future__ import annotations

import pandas as pd

from src.core.models import AlertSignal
from src.market.indicators import calculate_live_rsi
from src.market.okak_scanner import OkakScanner
from src.market.symbols import TickerStats


class EkekScanner(OkakScanner):
    strategy_key = "ekek"

    _RECENT_CANDLES = 3
    _BURST_CANDLES = 2
    _BASELINE_CANDLES = 5
    _MIN_CANDLES = _RECENT_CANDLES + _BASELINE_CANDLES
    _RECENT_MOVE_MIN_PCT = 0.012
    _RECENT_MOVE_ATR_MULTIPLIER = 2.4
    _RECENT_RANGE_MIN_PCT = 0.016
    _RECENT_RANGE_ATR_MULTIPLIER = 3.0
    _IMPULSE_SHARE_GATE = 0.5
    _BODY_EXPANSION_GATE = 1.45
    _VOLUME_EXPANSION_GATE = 1.12
    _BASELINE_ACCELERATION_GATE = 1.3
    _IMPULSE_CANDLE_BODY_MIN_PCT = 0.006
    _IMPULSE_CANDLE_BODY_ATR_MULTIPLIER = 1.0
    _IMPULSE_CANDLE_BODY_SHARE_GATE = 0.5
    _IMPULSE_CANDLE_CLOSE_NEAR_HIGH_GATE = 0.38
    _TERMINAL_ACCELERATION_GATE = 1.7

    def _build_signal(
        self,
        symbol: str,
        frame: pd.DataFrame,
        ticker: TickerStats | None,
    ) -> AlertSignal | None:
        if len(frame) < self._MIN_CANDLES:
            return None

        row = frame.iloc[-1]
        candle_close_time = row["close_time"].to_pydatetime()
        quote_volume = float(ticker.quote_volume) if ticker is not None and ticker.quote_volume else None
        day_volume = (
            float(ticker.quote_volume)
            if ticker is not None and ticker.quote_volume
            else float(ticker.volume)
            if ticker is not None and ticker.volume
            else None
        )
        effective_volume = float(quote_volume or day_volume or 0.0)
        score = self._score_signal(row, direction="overbought")
        closed_rsi = float(row["rsi"])

        okak_checks = {
            "preferred_volume_band": self._matches_preferred_volume_band(effective_volume),
            "rsi_76_plus": closed_rsi >= self._RSI_GATE,
            "score_90_plus": score >= self._SCORE_GATE,
        }
        okak_passed = sum(1 for passed in okak_checks.values() if passed)
        if okak_passed < 2:
            return None

        impulse_snapshot = self._impulse_snapshot(frame)
        impulse_checks = self._impulse_checks(
            impulse_snapshot,
            atr_pct=float(row["atr_pct"]) if pd.notna(row["atr_pct"]) else 0.0,
        )
        if not impulse_checks["strong_recent_move"]:
            return None
        if not impulse_checks["impulse_candle_present"]:
            return None
        if not impulse_checks["impulse_is_concentrated"]:
            return None
        if not (impulse_checks["body_expansion"] or impulse_checks["terminal_acceleration"]):
            return None
        optional_impulse_passed = sum(
            1
            for key, passed in impulse_checks.items()
            if key not in {"strong_recent_move", "impulse_candle_present", "impulse_is_concentrated"} and passed
        )
        if optional_impulse_passed < 2:
            return None

        live_price = float(ticker.last_price) if ticker is not None and ticker.last_price else float(row["close"])
        live_rsi = calculate_live_rsi(frame["close"], live_price, self.settings.rsi_length)
        okak_summary = ", ".join(
            label
            for label, passed in (
                ("volume 5-20M / 50M+", okak_checks["preferred_volume_band"]),
                ("RSI 76+", okak_checks["rsi_76_plus"]),
                ("score 90+", okak_checks["score_90_plus"]),
            )
            if passed
        ) or "none"
        impulse_summary = ", ".join(
            label
            for label, passed in (
                ("recent 3-candle burst", impulse_checks["strong_recent_move"]),
                ("impulse candle at the end", impulse_checks["impulse_candle_present"]),
                ("wide impulse range", impulse_checks["wide_recent_range"]),
                ("move concentrated late", impulse_checks["impulse_is_concentrated"]),
                ("recent burst beats baseline", impulse_checks["recent_beats_baseline"]),
                ("body expansion", impulse_checks["body_expansion"]),
                ("terminal acceleration", impulse_checks["terminal_acceleration"]),
                ("volume expansion", impulse_checks["volume_expansion"]),
            )
            if passed
        ) or "none"
        explanation = self._build_explanation(
            closed_rsi=closed_rsi,
            score=score,
            quote_volume=effective_volume,
            checks=okak_checks,
            impulse_snapshot=impulse_snapshot,
            impulse_checks=impulse_checks,
        )
        return AlertSignal(
            symbol=symbol,
            direction="overbought",
            timeframe=self.settings.scan_timeframe,
            candle_open_time=row.name.to_pydatetime(),
            candle_close_time=candle_close_time,
            price=float(row["close"]),
            rsi=closed_rsi,
            day_change_pct=ticker.price_change_percent if ticker else None,
            day_volume=day_volume,
            quote_volume=quote_volume,
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
                "signal_model": "ekek_impulse_overbought",
                "setup_direction": "short",
                "closed_rsi": closed_rsi,
                "live_rsi": live_rsi,
                "live_price": live_price,
                "signal_close_price": float(row["close"]),
                "signal_candle_close_time": candle_close_time.isoformat(),
                "volume_ratio": float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else None,
                "okak_checks": okak_checks,
                "okak_checks_passed": okak_passed,
                "okak_criteria_summary": okak_summary,
                "okak_volume_band_label": self._volume_band_label(effective_volume),
                "ekek_impulse_checks": impulse_checks,
                "ekek_impulse_checks_passed": sum(1 for passed in impulse_checks.values() if passed),
                "ekek_impulse_summary": impulse_summary,
                "ekek_impulse_move_pct": impulse_snapshot["recent_move_pct"],
                "ekek_trend_move_pct": impulse_snapshot["trend_move_pct"],
                "ekek_impulse_share": impulse_snapshot["impulse_share"],
                "ekek_recent_range_pct": impulse_snapshot["recent_range_pct"],
                "ekek_baseline_move_pct": impulse_snapshot["baseline_move_pct"],
                "ekek_body_expansion_ratio": impulse_snapshot["body_expansion_ratio"],
                "ekek_terminal_acceleration_ratio": impulse_snapshot["terminal_acceleration_ratio"],
                "ekek_volume_expansion_ratio": impulse_snapshot["volume_expansion_ratio"],
                "ekek_recent_positive_candles": impulse_snapshot["recent_positive_candles"],
                "ekek_impulse_candle_count": impulse_snapshot["impulse_candle_count"],
                "setup_quality": "EKEK impulse shortlist",
                "explanation_short": f"EKEK impulse shortlist: {impulse_summary}",
                "interactive_ai_enabled": True,
                "interactive_risk_enabled": True,
                "interactive_reason_enabled": True,
                "context_text": explanation,
            },
        )

    def _impulse_snapshot(self, frame: pd.DataFrame) -> dict[str, float]:
        window = frame.tail(self._MIN_CANDLES)
        recent = window.tail(self._RECENT_CANDLES)
        baseline = window.head(self._BASELINE_CANDLES)
        burst = recent.tail(self._BURST_CANDLES)

        recent_start = float(recent.iloc[0]["open"])
        recent_close = float(recent.iloc[-1]["close"])
        trend_start = float(window.iloc[0]["close"])
        baseline_start = float(baseline.iloc[0]["open"])
        baseline_close = float(baseline.iloc[-1]["close"])
        recent_low = float(recent["low"].min())
        recent_high = float(recent["high"].max())

        recent_move_pct = max((recent_close - recent_start) / max(recent_start, 1e-9), 0.0)
        trend_move_pct = max((recent_close - trend_start) / max(trend_start, 1e-9), 0.0)
        baseline_move_pct = max((baseline_close - baseline_start) / max(baseline_start, 1e-9), 0.0)
        recent_range_pct = max((recent_high - recent_low) / max(recent_low, 1e-9), 0.0)
        impulse_share = recent_move_pct / max(trend_move_pct, recent_move_pct, 1e-9)

        recent_bodies = (recent["close"] - recent["open"]).abs()
        baseline_bodies = (baseline["close"] - baseline["open"]).abs()
        baseline_body_max = max(float(baseline_bodies.max()), 1e-9)
        baseline_body_mean = max(float(baseline_bodies.mean()), 1e-9)
        body_expansion_ratio = float(recent_bodies.max()) / baseline_body_max
        terminal_acceleration_ratio = max(float(((burst["close"] - burst["open"]).abs()).mean()), 0.0) / baseline_body_mean

        recent_volume_mean = max(float(recent["volume"].mean()), 0.0)
        baseline_volume_mean = max(float(baseline["volume"].mean()), 1e-9)
        volume_expansion_ratio = recent_volume_mean / baseline_volume_mean
        recent_positive_candles = float((recent["close"] > recent["open"]).sum())
        recent_ranges = (recent["high"] - recent["low"]).clip(lower=1e-9)
        bullish_body_pct = ((recent["close"] - recent["open"]) / recent["open"]).clip(lower=0.0)
        close_near_high = ((recent["high"] - recent["close"]) / recent_ranges).clip(lower=0.0)
        body_share = (recent_bodies / recent_ranges).clip(lower=0.0)
        impulse_candle_count = float(
            (
                (bullish_body_pct >= max(float(frame.iloc[-1]["atr_pct"]) * self._IMPULSE_CANDLE_BODY_ATR_MULTIPLIER, self._IMPULSE_CANDLE_BODY_MIN_PCT))
                & (body_share >= self._IMPULSE_CANDLE_BODY_SHARE_GATE)
                & (close_near_high <= self._IMPULSE_CANDLE_CLOSE_NEAR_HIGH_GATE)
            ).sum()
        )

        return {
            "recent_move_pct": recent_move_pct,
            "trend_move_pct": trend_move_pct,
            "baseline_move_pct": baseline_move_pct,
            "recent_range_pct": recent_range_pct,
            "impulse_share": impulse_share,
            "body_expansion_ratio": body_expansion_ratio,
            "terminal_acceleration_ratio": terminal_acceleration_ratio,
            "volume_expansion_ratio": volume_expansion_ratio,
            "recent_positive_candles": recent_positive_candles,
            "impulse_candle_count": impulse_candle_count,
        }

    def _impulse_checks(self, impulse_snapshot: dict[str, float], *, atr_pct: float) -> dict[str, bool]:
        recent_move_gate = max(atr_pct * self._RECENT_MOVE_ATR_MULTIPLIER, self._RECENT_MOVE_MIN_PCT)
        recent_range_gate = max(atr_pct * self._RECENT_RANGE_ATR_MULTIPLIER, self._RECENT_RANGE_MIN_PCT)
        return {
            "strong_recent_move": impulse_snapshot["recent_move_pct"] >= recent_move_gate,
            "impulse_candle_present": impulse_snapshot["impulse_candle_count"] >= 1.0,
            "wide_recent_range": impulse_snapshot["recent_range_pct"] >= recent_range_gate,
            "impulse_is_concentrated": impulse_snapshot["impulse_share"] >= self._IMPULSE_SHARE_GATE,
            "recent_beats_baseline": impulse_snapshot["recent_move_pct"] >= max(
                impulse_snapshot["baseline_move_pct"] * self._BASELINE_ACCELERATION_GATE,
                recent_move_gate * 0.9,
            ),
            "body_expansion": impulse_snapshot["body_expansion_ratio"] >= self._BODY_EXPANSION_GATE,
            "terminal_acceleration": impulse_snapshot["terminal_acceleration_ratio"] >= self._TERMINAL_ACCELERATION_GATE,
            "volume_expansion": impulse_snapshot["volume_expansion_ratio"] >= self._VOLUME_EXPANSION_GATE,
        }

    def _build_explanation(
        self,
        *,
        closed_rsi: float,
        score: int,
        quote_volume: float,
        checks: dict[str, bool],
        impulse_snapshot: dict[str, float],
        impulse_checks: dict[str, bool],
    ) -> str:
        okak_summary = ", ".join(
            label
            for label, passed in (
                ("preferred volume band", checks["preferred_volume_band"]),
                ("RSI 76+", checks["rsi_76_plus"]),
                ("score 90+", checks["score_90_plus"]),
            )
            if passed
        ) or "none"
        impulse_summary = ", ".join(
            label
            for label, passed in (
                ("recent 3-candle burst", impulse_checks["strong_recent_move"]),
                ("impulse candle at the end", impulse_checks["impulse_candle_present"]),
                ("wide impulse range", impulse_checks["wide_recent_range"]),
                ("move concentrated late", impulse_checks["impulse_is_concentrated"]),
                ("recent burst beats baseline", impulse_checks["recent_beats_baseline"]),
                ("body expansion", impulse_checks["body_expansion"]),
                ("terminal acceleration", impulse_checks["terminal_acceleration"]),
                ("volume expansion", impulse_checks["volume_expansion"]),
            )
            if passed
        ) or "none"
        return (
            f"EKEK is the OKAK impulse variant on {self.settings.scan_timeframe}. "
            f"It keeps the OKAK shortlist logic, then only passes sharp expansions instead of gradual climbs. "
            f"Current snapshot: RSI {closed_rsi:.2f}, score {score}/100, quote volume {quote_volume / 1_000_000:.2f}M, "
            f"OKAK matched: {okak_summary}; impulse matched: {impulse_summary}. "
            f"Recent move {impulse_snapshot['recent_move_pct'] * 100:.2f}%, recent range {impulse_snapshot['recent_range_pct'] * 100:.2f}%, "
            f"impulse share {impulse_snapshot['impulse_share'] * 100:.0f}%, impulse candles {int(impulse_snapshot['impulse_candle_count'])}."
        )
