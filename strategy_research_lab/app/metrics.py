from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


PREPARED_COLUMNS = {
    "entry_month",
    "entry_week",
    "resolved_flag",
    "take_flag",
    "stop_flag",
    "open_flag",
    "ambiguous_flag",
    "gross_pnl_usd_filled",
    "net_pnl_usd_filled",
    "return_pct_filled",
    "cumulative_net_pnl_usd",
    "cumulative_balance_after_trade",
    "drawdown_usd",
    "drawdown_pct",
}


def prepare_trades_frame(trades: pd.DataFrame, starting_capital: float) -> pd.DataFrame:
    if trades.empty:
        return trades
    if PREPARED_COLUMNS.issubset(trades.columns):
        return trades.copy()
    prepared = trades.copy()
    prepared["entry_time"] = pd.to_datetime(prepared["entry_time"], utc=True)
    prepared["exit_time"] = pd.to_datetime(prepared["exit_time"], utc=True, errors="coerce")
    prepared["settlement_time"] = prepared["exit_time"].fillna(prepared["entry_time"])
    naive_entry = prepared["entry_time"].dt.tz_convert(None)
    prepared["entry_month"] = naive_entry.dt.to_period("M").astype(str)
    prepared["entry_week"] = naive_entry.dt.to_period("W").astype(str)
    prepared["resolved_flag"] = prepared["outcome"].isin(["TAKE", "STOP"]).astype(int)
    prepared["take_flag"] = (prepared["outcome"] == "TAKE").astype(int)
    prepared["stop_flag"] = (prepared["outcome"] == "STOP").astype(int)
    prepared["open_flag"] = (prepared["outcome"] == "OPEN").astype(int)
    prepared["ambiguous_flag"] = (prepared["outcome"] == "AMBIGUOUS").astype(int)
    prepared["gross_pnl_usd_filled"] = prepared["gross_pnl_usd"].fillna(0.0)
    prepared["net_pnl_usd_filled"] = prepared["net_pnl_usd"].fillna(0.0)
    prepared["return_pct_filled"] = prepared["return_pct"].fillna(0.0)
    prepared = prepared.sort_values(["strategy_name", "scenario_name", "settlement_time", "trade_id"]).reset_index(drop=True)
    prepared["cumulative_net_pnl_usd"] = prepared.groupby(["strategy_name", "scenario_name"], dropna=False)["net_pnl_usd_filled"].cumsum()
    prepared["cumulative_balance_after_trade"] = starting_capital + prepared["cumulative_net_pnl_usd"]
    running_max = prepared.groupby(["strategy_name", "scenario_name"], dropna=False)["cumulative_balance_after_trade"].cummax()
    prepared["drawdown_usd"] = running_max - prepared["cumulative_balance_after_trade"]
    prepared["drawdown_pct"] = np.where(running_max > 0, prepared["drawdown_usd"] / running_max * 100.0, 0.0)
    return prepared


def _aggregate_common(frame: pd.DataFrame, group_cols: list[str], starting_capital: float) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    def mean_for_outcome(outcome: str, column: str):
        def _inner(series: pd.Series) -> float:
            subset = frame.loc[series.index]
            return subset.loc[subset["outcome"] == outcome, column].mean()

        return _inner

    grouped = frame.groupby(group_cols, dropna=False)
    summary = grouped.agg(
        trades=("trade_id", "size"),
        resolved_trades=("resolved_flag", "sum"),
        take_count=("take_flag", "sum"),
        stop_count=("stop_flag", "sum"),
        open_count=("open_flag", "sum"),
        ambiguous_count=("ambiguous_flag", "sum"),
        avg_pnl_usd=("net_pnl_usd_filled", "mean"),
        median_pnl_usd=("net_pnl_usd_filled", "median"),
        total_net_pnl_usd=("net_pnl_usd_filled", "sum"),
        total_gross_pnl_usd=("gross_pnl_usd_filled", "sum"),
        avg_return_pct=("return_pct_filled", "mean"),
        median_return_pct=("return_pct_filled", "median"),
        gross_profit_usd=("net_pnl_usd_filled", lambda s: s[s > 0].sum()),
        gross_loss_usd=("net_pnl_usd_filled", lambda s: -s[s < 0].sum()),
        avg_minutes_to_take=("minutes_to_outcome", mean_for_outcome("TAKE", "minutes_to_outcome")),
        median_minutes_to_take=("minutes_to_outcome", lambda s: frame.loc[s.index].loc[frame.loc[s.index, "outcome"] == "TAKE", "minutes_to_outcome"].median()),
        avg_minutes_to_stop=("minutes_to_outcome", mean_for_outcome("STOP", "minutes_to_outcome")),
        median_minutes_to_stop=("minutes_to_outcome", lambda s: frame.loc[s.index].loc[frame.loc[s.index, "outcome"] == "STOP", "minutes_to_outcome"].median()),
        avg_bars_to_take=("bars_to_outcome", mean_for_outcome("TAKE", "bars_to_outcome")),
        avg_bars_to_stop=("bars_to_outcome", mean_for_outcome("STOP", "bars_to_outcome")),
        avg_duration_minutes=("minutes_to_outcome", lambda s: frame.loc[s.index].loc[frame.loc[s.index, "resolved_flag"] == 1, "minutes_to_outcome"].mean()),
        average_mfe_pct=("mfe_pct", "mean"),
        average_mae_pct=("mae_pct", "mean"),
        max_drawdown_usd=("drawdown_usd", "max"),
        max_drawdown_pct=("drawdown_pct", "max"),
    ).reset_index()
    summary["win_rate_pct"] = np.where(summary["resolved_trades"] > 0, summary["take_count"] / summary["resolved_trades"] * 100.0, np.nan)
    summary["loss_rate_pct"] = np.where(summary["resolved_trades"] > 0, summary["stop_count"] / summary["resolved_trades"] * 100.0, np.nan)
    summary["final_balance_usd"] = starting_capital + summary["total_net_pnl_usd"]
    summary["profit_factor"] = np.where(summary["gross_loss_usd"] > 0, summary["gross_profit_usd"] / summary["gross_loss_usd"], np.nan)
    summary["expectancy_usd"] = summary["avg_pnl_usd"]
    return summary


def _extreme_label(frame: pd.DataFrame, group_cols: list[str], target_col: str, value_label: str, ascending: bool) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=group_cols + [value_label])
    grouped = frame.groupby(group_cols + [target_col], dropna=False)["net_pnl_usd_filled"].sum().reset_index()
    ranked = grouped.sort_values(group_cols + ["net_pnl_usd_filled"], ascending=[True] * len(group_cols) + [ascending])
    top = ranked.groupby(group_cols, dropna=False).head(1)
    return top[group_cols + [target_col]].rename(columns={target_col: value_label})


def add_best_worst_dimensions(summary: pd.DataFrame, trades: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if summary.empty or trades.empty:
        return summary
    working = prepare_trades_frame(trades, 0.0)
    if "symbol" not in group_cols:
        best_symbol = _extreme_label(working, group_cols, "symbol", "best_symbol", ascending=False)
        worst_symbol = _extreme_label(working, group_cols, "symbol", "worst_symbol", ascending=True)
        summary = summary.merge(best_symbol, on=group_cols, how="left")
        summary = summary.merge(worst_symbol, on=group_cols, how="left")
    if "entry_month" not in group_cols:
        best_month = _extreme_label(working, group_cols, "entry_month", "best_month", ascending=False)
        worst_month = _extreme_label(working, group_cols, "entry_month", "worst_month", ascending=True)
        summary = summary.merge(best_month, on=group_cols, how="left")
        summary = summary.merge(worst_month, on=group_cols, how="left")
    return summary


def build_strategy_summary(trades: pd.DataFrame, starting_capital: float) -> pd.DataFrame:
    prepared = prepare_trades_frame(trades, starting_capital)
    summary = _aggregate_common(prepared, ["strategy_name"], starting_capital)
    summary = add_best_worst_dimensions(summary, trades, ["strategy_name"])
    return summary.sort_values(["total_net_pnl_usd", "win_rate_pct"], ascending=[False, False]).reset_index(drop=True)


def build_scenario_summary(trades: pd.DataFrame, starting_capital: float) -> pd.DataFrame:
    prepared = prepare_trades_frame(trades, starting_capital)
    summary = _aggregate_common(prepared, ["scenario_name"], starting_capital)
    summary = add_best_worst_dimensions(summary, trades, ["scenario_name"])
    return summary.sort_values(["total_net_pnl_usd", "win_rate_pct"], ascending=[False, False]).reset_index(drop=True)


def build_strategy_scenario_summary(trades: pd.DataFrame, starting_capital: float) -> pd.DataFrame:
    prepared = prepare_trades_frame(trades, starting_capital)
    summary = _aggregate_common(prepared, ["strategy_name", "scenario_name"], starting_capital)
    summary = add_best_worst_dimensions(summary, trades, ["strategy_name", "scenario_name"])
    return summary.sort_values(["total_net_pnl_usd", "win_rate_pct"], ascending=[False, False]).reset_index(drop=True)


def build_symbol_summary(trades: pd.DataFrame, starting_capital: float) -> pd.DataFrame:
    prepared = prepare_trades_frame(trades, starting_capital)
    return _aggregate_common(prepared, ["strategy_name", "symbol"], starting_capital).sort_values(
        ["total_net_pnl_usd", "win_rate_pct", "trades"], ascending=[False, False, False]
    ).reset_index(drop=True)


def build_time_summary(trades: pd.DataFrame, period_col: str, starting_capital: float) -> pd.DataFrame:
    prepared = prepare_trades_frame(trades, starting_capital)
    return _aggregate_common(prepared, ["strategy_name", period_col], starting_capital).sort_values(
        ["strategy_name", period_col]
    ).reset_index(drop=True)


def build_bucket_summary(trades: pd.DataFrame, bucket_col: str, starting_capital: float) -> pd.DataFrame:
    prepared = prepare_trades_frame(trades, starting_capital)
    return _aggregate_common(prepared, ["strategy_name", bucket_col], starting_capital).sort_values(
        ["strategy_name", "total_net_pnl_usd", "win_rate_pct", "trades"],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)


def build_overall_snapshot(trades: pd.DataFrame, starting_capital: float) -> dict[str, Any]:
    prepared = prepare_trades_frame(trades, starting_capital)
    if prepared.empty:
        return {
            "total_trades": 0,
            "total_net_pnl_usd": 0.0,
            "final_balance_usd": starting_capital,
            "best_strategy": None,
            "best_scenario": None,
            "best_symbol": None,
            "win_rate_pct": 0.0,
            "profit_factor": None,
            "max_drawdown_usd": 0.0,
            "max_drawdown_pct": 0.0,
            "resolved_trades": 0,
            "open_count": 0,
            "ambiguous_count": 0,
        }

    resolved = prepared[prepared["resolved_flag"] == 1]
    strategy_summary = build_strategy_summary(prepared, starting_capital)
    scenario_summary = build_scenario_summary(prepared, starting_capital)
    symbol_summary = build_symbol_summary(prepared, starting_capital)
    gross_profit = prepared.loc[prepared["net_pnl_usd_filled"] > 0, "net_pnl_usd_filled"].sum()
    gross_loss = -prepared.loc[prepared["net_pnl_usd_filled"] < 0, "net_pnl_usd_filled"].sum()

    return {
        "total_trades": int(len(prepared)),
        "total_net_pnl_usd": float(prepared["net_pnl_usd_filled"].sum()),
        "final_balance_usd": float(starting_capital + prepared["net_pnl_usd_filled"].sum()),
        "best_strategy": strategy_summary.iloc[0]["strategy_name"] if not strategy_summary.empty else None,
        "best_scenario": scenario_summary.iloc[0]["scenario_name"] if not scenario_summary.empty else None,
        "best_symbol": symbol_summary.iloc[0]["symbol"] if not symbol_summary.empty else None,
        "win_rate_pct": float((resolved["take_flag"].sum() / len(resolved) * 100.0) if len(resolved) else 0.0),
        "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else None,
        "max_drawdown_usd": float(prepared["drawdown_usd"].max()),
        "max_drawdown_pct": float(prepared["drawdown_pct"].max()),
        "resolved_trades": int(prepared["resolved_flag"].sum()),
        "open_count": int(prepared["open_flag"].sum()),
        "ambiguous_count": int(prepared["ambiguous_flag"].sum()),
    }
