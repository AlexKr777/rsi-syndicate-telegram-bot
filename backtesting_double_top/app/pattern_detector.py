from __future__ import annotations

from typing import Any

import pandas as pd

from app.utils import safe_pct_diff


def detect_pivot_highs(frame: pd.DataFrame, left: int, right: int) -> list[int]:
    highs = frame["high"].tolist()
    indices: list[int] = []
    for idx in range(left, len(highs) - right):
        current = highs[idx]
        left_slice = highs[idx - left : idx]
        right_slice = highs[idx + 1 : idx + 1 + right]
        if current >= max(left_slice) and current > max(right_slice):
            indices.append(idx)
    return indices


def detect_pivot_lows(frame: pd.DataFrame, left: int, right: int) -> list[int]:
    lows = frame["low"].tolist()
    indices: list[int] = []
    for idx in range(left, len(lows) - right):
        current = lows[idx]
        left_slice = lows[idx - left : idx]
        right_slice = lows[idx + 1 : idx + 1 + right]
        if current <= min(left_slice) and current < min(right_slice):
            indices.append(idx)
    return indices


def _breakout_index(
    frame: pd.DataFrame,
    *,
    second_peak_index: int,
    neckline_price: float,
    max_breakout_bars_after_second_peak: int,
) -> int | None:
    closes = frame["close"].tolist()
    start = second_peak_index + 1
    end = min(len(frame), second_peak_index + 1 + max_breakout_bars_after_second_peak)
    for idx in range(start, end):
        if closes[idx] < neckline_price:
            return idx
    return None


def detect_double_top_patterns(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    params = config["pattern_detection"]
    left = int(params["pivot_lookback_left"])
    right = int(params["pivot_lookback_right"])
    min_bars_between_peaks = int(params["min_bars_between_peaks"])
    max_bars_between_peaks = int(params["max_bars_between_peaks"])
    max_peak_diff_pct = float(params["max_peak_diff_pct"])
    max_peak_diff_atr_multiple = float(params["max_peak_diff_atr_multiple"])
    min_valley_depth_pct = float(params["min_valley_depth_pct"])
    max_breakout_bars = int(params["max_breakout_bars_after_second_peak"])

    pivot_highs = detect_pivot_highs(frame, left, right)
    pivot_lows = detect_pivot_lows(frame, left, right)
    pivot_lows_set = set(pivot_lows)
    patterns: list[dict[str, Any]] = []
    cursor = 0

    while cursor < len(pivot_highs) - 1:
        first_peak_index = pivot_highs[cursor]
        first_peak_price = float(frame.at[first_peak_index, "high"])
        candidates: list[dict[str, Any]] = []

        for second_peak_index in pivot_highs[cursor + 1 :]:
            bars_between = second_peak_index - first_peak_index
            if bars_between < min_bars_between_peaks:
                continue
            if bars_between > max_bars_between_peaks:
                break
            valley_candidates = [idx for idx in pivot_lows_set if first_peak_index < idx < second_peak_index]
            if not valley_candidates:
                continue
            valley_index = min(valley_candidates, key=lambda idx: float(frame.at[idx, "low"]))
            valley_low = float(frame.at[valley_index, "low"])
            second_peak_price = float(frame.at[second_peak_index, "high"])
            peak_similarity_pct = safe_pct_diff(first_peak_price, second_peak_price)
            peak_diff_abs = abs(first_peak_price - second_peak_price)
            atr_at_second_peak = float(frame.at[second_peak_index, "atr"]) if pd.notna(frame.at[second_peak_index, "atr"]) else None
            if peak_similarity_pct > max_peak_diff_pct:
                continue
            if atr_at_second_peak is not None and peak_diff_abs > atr_at_second_peak * max_peak_diff_atr_multiple:
                continue
            valley_depth_pct = ((min(first_peak_price, second_peak_price) - valley_low) / min(first_peak_price, second_peak_price)) * 100.0
            if valley_depth_pct < min_valley_depth_pct:
                continue
            breakout_index = _breakout_index(
                frame,
                second_peak_index=second_peak_index,
                neckline_price=valley_low,
                max_breakout_bars_after_second_peak=max_breakout_bars,
            )
            if breakout_index is None:
                continue
            candidates.append(
                {
                    "first_peak_index": first_peak_index,
                    "second_peak_index": second_peak_index,
                    "valley_index": valley_index,
                    "breakout_index": breakout_index,
                    "first_peak_price": first_peak_price,
                    "second_peak_price": second_peak_price,
                    "neckline_price": valley_low,
                    "peak_similarity_pct": peak_similarity_pct,
                    "valley_depth_pct": valley_depth_pct,
                    "bars_between_peaks": bars_between,
                    "bars_to_breakout": breakout_index - second_peak_index,
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
                item["bars_to_breakout"],
                item["second_peak_index"],
            ),
        )
        entry_index = int(selected["breakout_index"])
        pattern_id = (
            f"{frame.at[entry_index, 'symbol']}|"
            f"{frame.at[selected['first_peak_index'], 'open_time_utc']}|"
            f"{frame.at[selected['second_peak_index'], 'open_time_utc']}|"
            f"{frame.at[entry_index, 'open_time_utc']}"
        )
        patterns.append(
            {
                "pattern_id": pattern_id,
                "symbol": frame.at[entry_index, "symbol"],
                "first_peak_index": selected["first_peak_index"],
                "second_peak_index": selected["second_peak_index"],
                "valley_index": selected["valley_index"],
                "breakout_index": selected["breakout_index"],
                "entry_index": entry_index,
                "first_peak_time": frame.at[selected["first_peak_index"], "open_time_utc"],
                "second_peak_time": frame.at[selected["second_peak_index"], "open_time_utc"],
                "valley_time": frame.at[selected["valley_index"], "open_time_utc"],
                "breakout_time": frame.at[selected["breakout_index"], "close_time_utc"],
                "entry_time": frame.at[entry_index, "close_time_utc"],
                "first_peak_price": selected["first_peak_price"],
                "second_peak_price": selected["second_peak_price"],
                "neckline_price": selected["neckline_price"],
                "peak_similarity_pct": selected["peak_similarity_pct"],
                "valley_depth_pct": selected["valley_depth_pct"],
                "bars_between_peaks": selected["bars_between_peaks"],
                "bars_to_breakout": selected["bars_to_breakout"],
            }
        )
        cursor = pivot_highs.index(selected["second_peak_index"])
    return pd.DataFrame(patterns)
