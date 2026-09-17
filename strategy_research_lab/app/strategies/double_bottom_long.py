from __future__ import annotations

from typing import Any

import pandas as pd

from app.utils import detect_pivot_highs, detect_pivot_lows, safe_pct_diff


STRATEGY_NAME = "double_bottom_long"


def _breakout_index(frame: pd.DataFrame, *, second_bottom_index: int, neckline_price: float, max_breakout_bars: int) -> int | None:
    closes = frame["close"].tolist()
    for idx in range(second_bottom_index + 1, min(len(frame), second_bottom_index + 1 + max_breakout_bars)):
        if closes[idx] > neckline_price:
            return idx
    return None


def generate_signals(frame: pd.DataFrame, metadata: pd.Series, config: dict[str, Any]) -> pd.DataFrame:
    params = config["strategies"][STRATEGY_NAME]
    left = int(params["pivot_lookback_left"])
    right = int(params["pivot_lookback_right"])
    min_gap = int(params["min_bars_between_bottoms"])
    max_gap = int(params["max_bars_between_bottoms"])
    max_bottom_diff_pct = float(params["max_bottom_diff_pct"])
    max_bottom_diff_atr_multiple = float(params["max_bottom_diff_atr_multiple"])
    min_bounce_height_pct = float(params["min_bounce_height_pct"])
    max_breakout_bars = int(params["max_breakout_bars_after_second_bottom"])

    pivot_lows = detect_pivot_lows(frame, left, right)
    pivot_highs = set(detect_pivot_highs(frame, left, right))
    signals: list[dict[str, Any]] = []
    cursor = 0

    while cursor < len(pivot_lows) - 1:
        first_bottom_index = pivot_lows[cursor]
        first_bottom_price = float(frame.at[first_bottom_index, "low"])
        candidates: list[dict[str, Any]] = []

        for second_bottom_index in pivot_lows[cursor + 1 :]:
            bars_between = second_bottom_index - first_bottom_index
            if bars_between < min_gap:
                continue
            if bars_between > max_gap:
                break
            bounce_candidates = [idx for idx in pivot_highs if first_bottom_index < idx < second_bottom_index]
            if not bounce_candidates:
                continue
            neckline_index = max(bounce_candidates, key=lambda idx: float(frame.at[idx, "high"]))
            neckline_price = float(frame.at[neckline_index, "high"])
            second_bottom_price = float(frame.at[second_bottom_index, "low"])
            similarity_pct = safe_pct_diff(first_bottom_price, second_bottom_price)
            atr_at_second_bottom = float(frame.at[second_bottom_index, "atr"]) if pd.notna(frame.at[second_bottom_index, "atr"]) else None
            bottom_diff_abs = abs(first_bottom_price - second_bottom_price)
            if similarity_pct > max_bottom_diff_pct:
                continue
            if atr_at_second_bottom is not None and bottom_diff_abs > atr_at_second_bottom * max_bottom_diff_atr_multiple:
                continue
            bounce_height_pct = ((neckline_price - max(first_bottom_price, second_bottom_price)) / max(first_bottom_price, second_bottom_price)) * 100.0
            if bounce_height_pct < min_bounce_height_pct:
                continue
            breakout_index = _breakout_index(frame, second_bottom_index=second_bottom_index, neckline_price=neckline_price, max_breakout_bars=max_breakout_bars)
            if breakout_index is None:
                continue

            entry_row = frame.iloc[breakout_index]
            second_bottom_rsi = float(frame.at[second_bottom_index, "rsi"]) if pd.notna(frame.at[second_bottom_index, "rsi"]) else None
            first_bottom_rsi = float(frame.at[first_bottom_index, "rsi"]) if pd.notna(frame.at[first_bottom_index, "rsi"]) else None
            if bool(params.get("use_ema_filter")) and not (float(entry_row["ema20"]) > float(entry_row["ema50"])):
                continue
            if bool(params.get("use_volume_ratio_filter")) and float(entry_row.get("volume_ratio", 0.0) or 0.0) < float(params["min_volume_ratio"]):
                continue
            if bool(params.get("use_rsi_strength_filter")):
                if second_bottom_rsi is None or second_bottom_rsi > float(params["max_rsi_second_bottom"]):
                    continue
                if bool(params.get("require_rsi_bullish_divergence")) and first_bottom_rsi is not None and second_bottom_rsi < first_bottom_rsi:
                    continue
            if float(entry_row.get("rolling_quote_volume_24h", 0.0) or 0.0) < float(params.get("min_liquidity_24h", 0.0)):
                continue
            if float(entry_row.get("atr_pct", 0.0) or 0.0) < float(params.get("min_atr_pct", 0.0)):
                continue

            average_bottom = (first_bottom_price + second_bottom_price) / 2.0
            measured_move_abs = max(neckline_price - average_bottom, 0.0)
            measured_move_price = float(entry_row["close"]) + measured_move_abs
            pattern_id = (
                f"{entry_row['symbol']}|"
                f"{frame.at[first_bottom_index, 'open_time_utc']}|"
                f"{frame.at[second_bottom_index, 'open_time_utc']}|"
                f"{frame.at[breakout_index, 'open_time_utc']}"
            )
            candidates.append(
                {
                    "strategy_name": STRATEGY_NAME,
                    "pattern_id": pattern_id,
                    "signal_id": pattern_id,
                    "symbol": entry_row["symbol"],
                    "side": "LONG",
                    "signal_index": breakout_index,
                    "entry_index": breakout_index,
                    "signal_time": frame.at[breakout_index, "close_time_utc"],
                    "entry_time": frame.at[breakout_index, "close_time_utc"],
                    "entry_price": float(entry_row["close"]),
                    "neckline_price": neckline_price,
                    "first_bottom_index": first_bottom_index,
                    "second_bottom_index": second_bottom_index,
                    "neckline_index": neckline_index,
                    "first_bottom_time": frame.at[first_bottom_index, "open_time_utc"],
                    "second_bottom_time": frame.at[second_bottom_index, "open_time_utc"],
                    "neckline_time": frame.at[neckline_index, "open_time_utc"],
                    "first_bottom_price": first_bottom_price,
                    "second_bottom_price": second_bottom_price,
                    "bottom_similarity_pct": similarity_pct,
                    "bounce_height_pct": bounce_height_pct,
                    "bars_between_points": bars_between,
                    "bars_to_confirmation": breakout_index - second_bottom_index,
                    "structural_stop_anchor_price": second_bottom_price,
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
                item["bottom_similarity_pct"],
                -item["bounce_height_pct"],
                item["bars_to_confirmation"],
            ),
        )
        signals.append(selected)
        cursor = pivot_lows.index(selected["second_bottom_index"])

    return pd.DataFrame(signals)
