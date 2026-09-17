from __future__ import annotations

from typing import Any

import pandas as pd

from app.utils import detect_pivot_highs, detect_pivot_lows, safe_pct_diff


STRATEGY_NAME = "double_top_short"


def _breakout_index(frame: pd.DataFrame, *, second_peak_index: int, neckline_price: float, max_breakout_bars: int) -> int | None:
    closes = frame["close"].tolist()
    for idx in range(second_peak_index + 1, min(len(frame), second_peak_index + 1 + max_breakout_bars)):
        if closes[idx] < neckline_price:
            return idx
    return None


def generate_signals(frame: pd.DataFrame, metadata: pd.Series, config: dict[str, Any]) -> pd.DataFrame:
    params = config["strategies"][STRATEGY_NAME]
    left = int(params["pivot_lookback_left"])
    right = int(params["pivot_lookback_right"])
    min_gap = int(params["min_bars_between_peaks"])
    max_gap = int(params["max_bars_between_peaks"])
    max_peak_diff_pct = float(params["max_peak_diff_pct"])
    max_peak_diff_atr_multiple = float(params["max_peak_diff_atr_multiple"])
    min_valley_depth_pct = float(params["min_valley_depth_pct"])
    max_breakout_bars = int(params["max_breakout_bars_after_second_peak"])

    pivot_highs = detect_pivot_highs(frame, left, right)
    pivot_lows = set(detect_pivot_lows(frame, left, right))
    signals: list[dict[str, Any]] = []
    cursor = 0

    while cursor < len(pivot_highs) - 1:
        first_peak_index = pivot_highs[cursor]
        first_peak_price = float(frame.at[first_peak_index, "high"])
        candidates: list[dict[str, Any]] = []

        for second_peak_index in pivot_highs[cursor + 1 :]:
            bars_between = second_peak_index - first_peak_index
            if bars_between < min_gap:
                continue
            if bars_between > max_gap:
                break
            valley_candidates = [idx for idx in pivot_lows if first_peak_index < idx < second_peak_index]
            if not valley_candidates:
                continue
            valley_index = min(valley_candidates, key=lambda idx: float(frame.at[idx, "low"]))
            valley_price = float(frame.at[valley_index, "low"])
            second_peak_price = float(frame.at[second_peak_index, "high"])
            similarity_pct = safe_pct_diff(first_peak_price, second_peak_price)
            atr_at_second_peak = float(frame.at[second_peak_index, "atr"]) if pd.notna(frame.at[second_peak_index, "atr"]) else None
            peak_diff_abs = abs(first_peak_price - second_peak_price)
            if similarity_pct > max_peak_diff_pct:
                continue
            if atr_at_second_peak is not None and peak_diff_abs > atr_at_second_peak * max_peak_diff_atr_multiple:
                continue
            valley_depth_pct = ((min(first_peak_price, second_peak_price) - valley_price) / min(first_peak_price, second_peak_price)) * 100.0
            if valley_depth_pct < min_valley_depth_pct:
                continue
            breakout_index = _breakout_index(frame, second_peak_index=second_peak_index, neckline_price=valley_price, max_breakout_bars=max_breakout_bars)
            if breakout_index is None:
                continue

            entry_row = frame.iloc[breakout_index]
            second_peak_rsi = float(frame.at[second_peak_index, "rsi"]) if pd.notna(frame.at[second_peak_index, "rsi"]) else None
            first_peak_rsi = float(frame.at[first_peak_index, "rsi"]) if pd.notna(frame.at[first_peak_index, "rsi"]) else None
            if bool(params.get("use_ema_filter")) and not (float(entry_row["ema20"]) < float(entry_row["ema50"])):
                continue
            if bool(params.get("use_volume_ratio_filter")) and float(entry_row.get("volume_ratio", 0.0) or 0.0) < float(params["min_volume_ratio"]):
                continue
            if bool(params.get("use_rsi_weakness_filter")):
                if second_peak_rsi is None or second_peak_rsi < float(params["min_rsi_second_peak"]):
                    continue
                if bool(params.get("require_rsi_divergence")) and first_peak_rsi is not None and second_peak_rsi > first_peak_rsi:
                    continue
            if float(entry_row.get("rolling_quote_volume_24h", 0.0) or 0.0) < float(params.get("min_liquidity_24h", 0.0)):
                continue
            if float(entry_row.get("atr_pct", 0.0) or 0.0) < float(params.get("min_atr_pct", 0.0)):
                continue

            average_peak = (first_peak_price + second_peak_price) / 2.0
            measured_move_abs = max(average_peak - valley_price, 0.0)
            measured_move_price = max(float(entry_row["close"]) - measured_move_abs, 0.0)
            pattern_id = (
                f"{entry_row['symbol']}|"
                f"{frame.at[first_peak_index, 'open_time_utc']}|"
                f"{frame.at[second_peak_index, 'open_time_utc']}|"
                f"{frame.at[breakout_index, 'open_time_utc']}"
            )
            candidates.append(
                {
                    "strategy_name": STRATEGY_NAME,
                    "pattern_id": pattern_id,
                    "signal_id": pattern_id,
                    "symbol": entry_row["symbol"],
                    "side": "SHORT",
                    "signal_index": breakout_index,
                    "entry_index": breakout_index,
                    "signal_time": frame.at[breakout_index, "close_time_utc"],
                    "entry_time": frame.at[breakout_index, "close_time_utc"],
                    "entry_price": float(entry_row["close"]),
                    "neckline_price": valley_price,
                    "first_peak_index": first_peak_index,
                    "second_peak_index": second_peak_index,
                    "valley_index": valley_index,
                    "first_peak_time": frame.at[first_peak_index, "open_time_utc"],
                    "second_peak_time": frame.at[second_peak_index, "open_time_utc"],
                    "valley_time": frame.at[valley_index, "open_time_utc"],
                    "first_peak_price": first_peak_price,
                    "second_peak_price": second_peak_price,
                    "peak_similarity_pct": similarity_pct,
                    "valley_depth_pct": valley_depth_pct,
                    "bars_between_points": bars_between,
                    "bars_to_confirmation": breakout_index - second_peak_index,
                    "structural_stop_anchor_price": second_peak_price,
                    "measured_move_price": measured_move_price,
                    "signal_high": float(entry_row["high"]),
                    "signal_low": float(entry_row["low"]),
                }
            )

        if not candidates:
            cursor += 1
            continue

        selected = min(
            candidates,
            key=lambda item: (
                item["peak_similarity_pct"],
                -item["valley_depth_pct"],
                item["bars_to_confirmation"],
            ),
        )
        signals.append(selected)
        cursor = pivot_highs.index(selected["second_peak_index"])

    return pd.DataFrame(signals)
