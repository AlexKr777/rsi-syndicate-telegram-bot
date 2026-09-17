from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def prepare_trades_frame(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades
    prepared = trades.copy()
    prepared["entry_time"] = pd.to_datetime(prepared["entry_time"], utc=True)
    prepared["exit_time"] = pd.to_datetime(prepared["exit_time"], utc=True, errors="coerce")
    naive_entry_time = prepared["entry_time"].dt.tz_convert(None)
    prepared["entry_month"] = naive_entry_time.dt.to_period("M").astype(str)
    prepared["entry_week"] = naive_entry_time.dt.to_period("W").astype(str)
    prepared["resolved_flag"] = prepared["outcome"].isin(["TAKE", "STOP"]).astype(int)
    prepared["take_flag"] = (prepared["outcome"] == "TAKE").astype(int)
    prepared["stop_flag"] = (prepared["outcome"] == "STOP").astype(int)
    prepared["open_flag"] = (prepared["outcome"] == "OPEN").astype(int)
    prepared["ambiguous_flag"] = (prepared["outcome"] == "AMBIGUOUS").astype(int)
    prepared["realized_return_pct_filled"] = prepared["realized_return_pct"].fillna(0.0)
    return prepared


def _aggregate_common(frame: pd.DataFrame, group_cols: list[str], total_patterns_found: int) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    def mean_for_outcome(outcome: str, column: str):
        def _inner(series: pd.Series) -> float:
            subset = frame.loc[series.index]
            return subset.loc[subset["outcome"] == outcome, column].mean()

        return _inner

    grouped = frame.groupby(group_cols, dropna=False)
    aggregate_spec: dict[str, tuple[str, object]] = {
        "total_trades_opened": ("trade_id", "size"),
        "total_take": ("take_flag", "sum"),
        "total_stop": ("stop_flag", "sum"),
        "total_open": ("open_flag", "sum"),
        "total_ambiguous": ("ambiguous_flag", "sum"),
        "resolved_trades_count": ("resolved_flag", "sum"),
        "avg_minutes_to_take": ("minutes_to_outcome", mean_for_outcome("TAKE", "minutes_to_outcome")),
        "median_minutes_to_take": (
            "minutes_to_outcome",
            lambda s: frame.loc[s.index].loc[frame.loc[s.index, "outcome"] == "TAKE", "minutes_to_outcome"].median(),
        ),
        "avg_minutes_to_stop": ("minutes_to_outcome", mean_for_outcome("STOP", "minutes_to_outcome")),
        "median_minutes_to_stop": (
            "minutes_to_outcome",
            lambda s: frame.loc[s.index].loc[frame.loc[s.index, "outcome"] == "STOP", "minutes_to_outcome"].median(),
        ),
        "avg_bars_to_take": ("bars_to_outcome", mean_for_outcome("TAKE", "bars_to_outcome")),
        "avg_bars_to_stop": ("bars_to_outcome", mean_for_outcome("STOP", "bars_to_outcome")),
        "avg_return_per_trade_pct": ("realized_return_pct_filled", "mean"),
        "median_return_per_trade_pct": ("realized_return_pct_filled", "median"),
        "average_mfe_pct": ("mfe_pct", "mean"),
        "average_mae_pct": ("mae_pct", "mean"),
    }
    if "stop_pct" not in group_cols:
        aggregate_spec["stop_pct"] = ("stop_pct", "first")
    if "take_pct" not in group_cols:
        aggregate_spec["take_pct"] = ("take_pct", "first")
    summary = grouped.agg(**aggregate_spec).reset_index()
    summary["total_patterns_found"] = total_patterns_found
    summary["win_rate_pct"] = np.where(summary["resolved_trades_count"] > 0, summary["total_take"] / summary["resolved_trades_count"] * 100.0, np.nan)
    summary["loss_rate_pct"] = np.where(summary["resolved_trades_count"] > 0, summary["total_stop"] / summary["resolved_trades_count"] * 100.0, np.nan)
    summary["take_rate_all_pct"] = summary["total_take"] / summary["total_trades_opened"] * 100.0
    summary["stop_rate_all_pct"] = summary["total_stop"] / summary["total_trades_opened"] * 100.0
    summary["open_rate_all_pct"] = summary["total_open"] / summary["total_trades_opened"] * 100.0
    summary["ambiguous_rate_all_pct"] = summary["total_ambiguous"] / summary["total_trades_opened"] * 100.0
    summary["expectancy_pct"] = summary["avg_return_per_trade_pct"]
    summary["profit_factor"] = np.where(
        summary["total_stop"] > 0,
        (summary["total_take"] * summary["take_pct"].astype(float)) / (summary["total_stop"] * summary["stop_pct"].astype(float)),
        np.nan,
    )
    return summary


def build_symbol_summary(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    frame = prepare_trades_frame(trades)
    return _aggregate_common(frame, ["scenario_name", "symbol"], total_patterns_found=0).sort_values(
        ["scenario_name", "win_rate_pct", "expectancy_pct", "total_trades_opened"],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)


def build_scenario_summary(trades: pd.DataFrame, patterns: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    frame = prepare_trades_frame(trades)
    summary = _aggregate_common(frame, ["scenario_name", "stop_pct", "take_pct"], total_patterns_found=len(patterns))
    symbol_summary = build_symbol_summary(trades)
    best = symbol_summary.sort_values(["win_rate_pct", "avg_return_per_trade_pct", "total_trades_opened"], ascending=[False, False, False]).groupby("scenario_name").head(1)
    worst = symbol_summary.sort_values(["win_rate_pct", "avg_return_per_trade_pct", "total_trades_opened"], ascending=[True, True, False]).groupby("scenario_name").head(1)
    summary = summary.merge(best[["scenario_name", "symbol"]].rename(columns={"symbol": "best_symbol"}), on="scenario_name", how="left")
    summary = summary.merge(worst[["scenario_name", "symbol"]].rename(columns={"symbol": "worst_symbol"}), on="scenario_name", how="left")
    return summary.sort_values(["win_rate_pct", "expectancy_pct", "total_trades_opened"], ascending=[False, False, False]).reset_index(drop=True)


def build_time_breakdown(trades: pd.DataFrame, period_col: str) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    frame = prepare_trades_frame(trades)
    return _aggregate_common(frame, ["scenario_name", period_col], total_patterns_found=0).sort_values(
        ["scenario_name", period_col]
    ).reset_index(drop=True)


def build_bucket_summary(trades: pd.DataFrame, bucket_col: str) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    frame = prepare_trades_frame(trades)
    return _aggregate_common(frame, ["scenario_name", bucket_col], total_patterns_found=0).sort_values(
        ["scenario_name", "win_rate_pct", "expectancy_pct", "total_trades_opened"],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)


def build_overall_snapshot(trades: pd.DataFrame, patterns: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {
            "patterns_found": int(len(patterns)),
            "trades_opened": 0,
            "resolved_trades": 0,
            "win_rate_pct": 0.0,
            "open_count": 0,
            "ambiguous_count": 0,
            "avg_minutes_to_take": None,
            "avg_minutes_to_stop": None,
        }
    frame = prepare_trades_frame(trades)
    resolved = frame[frame["outcome"].isin(["TAKE", "STOP"])]
    take_rows = frame[frame["outcome"] == "TAKE"]
    stop_rows = frame[frame["outcome"] == "STOP"]
    return {
        "patterns_found": int(len(patterns)),
        "trades_opened": int(len(frame)),
        "resolved_trades": int(len(resolved)),
        "win_rate_pct": float((len(take_rows) / len(resolved) * 100.0) if len(resolved) else 0.0),
        "open_count": int((frame["outcome"] == "OPEN").sum()),
        "ambiguous_count": int((frame["outcome"] == "AMBIGUOUS").sum()),
        "avg_minutes_to_take": float(take_rows["minutes_to_outcome"].mean()) if not take_rows.empty else None,
        "avg_minutes_to_stop": float(stop_rows["minutes_to_outcome"].mean()) if not stop_rows.empty else None,
    }
