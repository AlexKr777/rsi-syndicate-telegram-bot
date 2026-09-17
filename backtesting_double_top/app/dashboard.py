from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from app.charts import (
    cumulative_return_by_symbol,
    equity_curve,
    histogram_minutes,
    mfe_mae_box,
    outcomes_bar,
    outcomes_pie,
    patterns_over_time,
    return_distribution,
    scatter_by_feature,
    scenario_heatmap,
    symbol_heatmap,
    trade_pattern_chart,
)
from app.data_loader import load_candles_for_trade, open_read_only_connection
from app.metrics import build_bucket_summary, build_scenario_summary, build_symbol_summary, build_time_breakdown
from app.utils import EXPORTS_DIR, load_config


CONFIG = load_config("config.yaml")


@st.cache_data(show_spinner=False)
def load_export(name: str) -> pd.DataFrame:
    path = EXPORTS_DIR / name
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def apply_filters(trades: pd.DataFrame) -> tuple[pd.DataFrame, float, float]:
    if trades.empty:
        return trades, 0.0, 0.0
    st.sidebar.header("Money model")
    starting_capital = st.sidebar.number_input(
        "Start capital, $",
        min_value=0.0,
        value=float(CONFIG["dashboard"].get("starting_capital_usd", 100000.0)),
        step=1000.0,
    )
    stake_per_trade = st.sidebar.number_input(
        "Fixed stake per trade, $",
        min_value=0.0,
        value=float(CONFIG["dashboard"].get("stake_per_trade_usd", 200.0)),
        step=10.0,
    )
    st.sidebar.caption("PnL here is fixed-stake math without fees, funding, slippage or leverage compounding.")
    st.sidebar.markdown("---")
    st.sidebar.header("Filters")
    frame = trades.copy()
    frame["entry_time"] = pd.to_datetime(frame["entry_time"], utc=True)
    symbols = sorted(trades["symbol"].dropna().unique().tolist())
    scenarios = sorted(trades["scenario_name"].dropna().unique().tolist())
    outcomes = sorted(trades["outcome"].dropna().unique().tolist())
    rsi_buckets = sorted(trades["rsi_bucket"].dropna().unique().tolist())
    atr_buckets = sorted(trades["atr_bucket"].dropna().unique().tolist())
    volume_buckets = sorted(trades["volume_bucket"].dropna().unique().tolist())
    liquidity_buckets = sorted(trades["liquidity_bucket"].dropna().unique().tolist())
    ambiguous_policies = sorted(trades["ambiguous_policy"].dropna().unique().tolist()) if "ambiguous_policy" in trades.columns else []
    min_date = frame["entry_time"].min().date()
    max_date = frame["entry_time"].max().date()

    selected_symbols = st.sidebar.multiselect("Symbol", symbols)
    default_scenario = str(CONFIG["dashboard"].get("default_scenario", ""))
    default_selection = [default_scenario] if default_scenario in scenarios else (scenarios[:1] if scenarios else None)
    selected_scenarios = st.sidebar.multiselect("Scenario", scenarios, default=default_selection)
    selected_outcomes = st.sidebar.multiselect("Outcome", outcomes)
    selected_rsi = st.sidebar.multiselect("RSI bucket", rsi_buckets)
    selected_atr = st.sidebar.multiselect("ATR bucket", atr_buckets)
    selected_volume = st.sidebar.multiselect("Volume bucket", volume_buckets)
    selected_liquidity = st.sidebar.multiselect("Liquidity bucket", liquidity_buckets)
    selected_policy = st.sidebar.multiselect("Ambiguous policy", ambiguous_policies, default=ambiguous_policies if ambiguous_policies else None)
    date_range = st.sidebar.date_input("Date range", value=(min_date, max_date))
    min_liquidity = st.sidebar.number_input("Minimum liquidity 24h at entry", min_value=0.0, value=0.0, step=1_000_000.0)
    frame["exit_time"] = pd.to_datetime(frame["exit_time"], utc=True, errors="coerce")
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
        frame = frame[(frame["entry_time"].dt.date >= start_date) & (frame["entry_time"].dt.date <= end_date)]
    if selected_symbols:
        frame = frame[frame["symbol"].isin(selected_symbols)]
    if selected_scenarios:
        frame = frame[frame["scenario_name"].isin(selected_scenarios)]
    if selected_outcomes:
        frame = frame[frame["outcome"].isin(selected_outcomes)]
    if selected_rsi:
        frame = frame[frame["rsi_bucket"].isin(selected_rsi)]
    if selected_atr:
        frame = frame[frame["atr_bucket"].isin(selected_atr)]
    if selected_volume:
        frame = frame[frame["volume_bucket"].isin(selected_volume)]
    if selected_liquidity:
        frame = frame[frame["liquidity_bucket"].isin(selected_liquidity)]
    if selected_policy:
        frame = frame[frame["ambiguous_policy"].isin(selected_policy)]
    frame = frame[frame["quote_volume_24h_at_entry"].fillna(0.0) >= min_liquidity]
    frame["realized_return_pct_filled"] = frame["realized_return_pct"].fillna(0.0)
    naive_entry_time = pd.to_datetime(frame["entry_time"], utc=True).dt.tz_convert(None)
    frame["entry_month"] = naive_entry_time.dt.to_period("M").astype(str)
    frame["entry_week"] = naive_entry_time.dt.to_period("W").astype(str)
    return frame, starting_capital, stake_per_trade


def enrich_money_model(trades: pd.DataFrame, *, starting_capital: float, stake_per_trade: float) -> pd.DataFrame:
    if trades.empty:
        return trades
    enriched = trades.copy()
    enriched["trade_pnl_usd"] = enriched["realized_return_pct_filled"].fillna(0.0).astype(float) / 100.0 * float(stake_per_trade)
    enriched["stake_usd"] = float(stake_per_trade)
    sort_time = pd.to_datetime(enriched["exit_time"], utc=True, errors="coerce").fillna(pd.to_datetime(enriched["entry_time"], utc=True))
    enriched = enriched.assign(_sort_time=sort_time).sort_values(["scenario_name", "_sort_time", "entry_time", "trade_id"]).reset_index(drop=True)
    enriched["running_pnl_usd"] = enriched.groupby("scenario_name", dropna=False)["trade_pnl_usd"].cumsum()
    enriched["equity_after_trade_usd"] = float(starting_capital) + enriched["running_pnl_usd"]
    return enriched.drop(columns=["_sort_time"])


def add_money_columns(summary: pd.DataFrame, trades: pd.DataFrame, group_cols: list[str], *, starting_capital: float, add_balance: bool = False) -> pd.DataFrame:
    if summary.empty or trades.empty:
        return summary
    working = trades.copy()
    if ("entry_month" in group_cols or "entry_week" in group_cols) and "entry_time" in working.columns:
        naive_entry_time = pd.to_datetime(working["entry_time"], utc=True).dt.tz_convert(None)
        if "entry_month" in group_cols and "entry_month" not in working.columns:
            working["entry_month"] = naive_entry_time.dt.to_period("M").astype(str)
        if "entry_week" in group_cols and "entry_week" not in working.columns:
            working["entry_week"] = naive_entry_time.dt.to_period("W").astype(str)
    money = (
        working.groupby(group_cols, dropna=False)
        .agg(
            net_profit_usd=("trade_pnl_usd", "sum"),
            avg_trade_pnl_usd=("trade_pnl_usd", "mean"),
            gross_profit_usd=("trade_pnl_usd", lambda s: s[s > 0].sum()),
            gross_loss_usd=("trade_pnl_usd", lambda s: -s[s < 0].sum()),
        )
        .reset_index()
    )
    merged = summary.merge(money, on=group_cols, how="left")
    if add_balance:
        merged["ending_capital_usd"] = float(starting_capital) + merged["net_profit_usd"].fillna(0.0)
    return merged


def compact_table(dataframe: pd.DataFrame, columns: list[str], rename_map: dict[str, str]) -> pd.DataFrame:
    if dataframe.empty:
        return dataframe
    available = [column for column in columns if column in dataframe.columns]
    compact = dataframe[available].copy()
    numeric_columns = compact.select_dtypes(include="number").columns
    if len(numeric_columns):
        compact[numeric_columns] = compact[numeric_columns].round(2)
    return compact.rename(columns=rename_map)


def metric_row(trades: pd.DataFrame, patterns: pd.DataFrame, *, starting_capital: float) -> None:
    resolved = trades[trades["outcome"].isin(["TAKE", "STOP"])]
    take_rows = trades[trades["outcome"] == "TAKE"]
    stop_rows = trades[trades["outcome"] == "STOP"]
    net_profit = float(trades["trade_pnl_usd"].sum()) if "trade_pnl_usd" in trades.columns else 0.0
    final_balance = float(starting_capital) + net_profit
    row_one = st.columns(5)
    row_two = st.columns(5)
    cards = [
        ("Patterns", len(patterns)),
        ("Trades", len(trades)),
        ("Resolved", len(resolved)),
        ("Win rate", f"{(len(take_rows) / len(resolved) * 100.0) if len(resolved) else 0.0:.2f}%"),
        ("Net PnL, $", f"{net_profit:,.2f}"),
        ("Final balance, $", f"{final_balance:,.2f}"),
        ("Avg min to TAKE", f"{take_rows['minutes_to_outcome'].mean():.1f}" if not take_rows.empty else "n/a"),
        ("Avg min to STOP", f"{stop_rows['minutes_to_outcome'].mean():.1f}" if not stop_rows.empty else "n/a"),
        ("OPEN", int((trades["outcome"] == "OPEN").sum()) if not trades.empty else 0),
        ("AMBIGUOUS", int((trades["outcome"] == "AMBIGUOUS").sum()) if not trades.empty else 0),
    ]
    for col, (label, value) in zip(row_one + row_two, cards, strict=False):
        col.metric(label, value)


def trade_detail_section(filtered_trades: pd.DataFrame, filtered_patterns: pd.DataFrame) -> None:
    st.subheader("Trade explorer")
    if filtered_trades.empty:
        st.info("No trades match the active filters.")
        return
    trade_choices = filtered_trades.sort_values("entry_time", ascending=False)["trade_id"].tolist()
    selected_trade_id = st.selectbox("Select trade", trade_choices)
    trade_row = filtered_trades.loc[filtered_trades["trade_id"] == selected_trade_id].iloc[0].copy()
    if not filtered_patterns.empty and "pattern_id" in trade_row.index:
        pattern_match = filtered_patterns.loc[filtered_patterns["pattern_id"] == trade_row["pattern_id"]]
        if not pattern_match.empty:
            pattern_row = pattern_match.iloc[0]
            for column in ["first_peak_price", "second_peak_price", "first_peak_time", "second_peak_time", "neckline_price", "breakout_time"]:
                if column not in trade_row.index or pd.isna(trade_row.get(column)):
                    trade_row.loc[column] = pattern_row.get(column)
    st.dataframe(pd.DataFrame([trade_row]), use_container_width=True, hide_index=True)

    connection = open_read_only_connection(CONFIG["data_source"]["sqlite_path"])
    try:
        padding_bars = int(CONFIG["dashboard"].get("trade_chart_padding_bars", 24))
        start_time = pd.to_datetime(trade_row["first_peak_time"], utc=True) - pd.Timedelta(minutes=15 * padding_bars)
        if pd.notna(trade_row.get("exit_time")):
            end_base = pd.to_datetime(trade_row["exit_time"], utc=True)
        else:
            end_base = pd.to_datetime(trade_row["entry_time"], utc=True) + pd.Timedelta(hours=24)
        end_time = end_base + pd.Timedelta(minutes=15 * padding_bars)
        candles = load_candles_for_trade(
            connection,
            symbol=str(trade_row["symbol"]),
            interval=str(trade_row["interval"]),
            start_time_utc=start_time.isoformat(),
            end_time_utc=end_time.isoformat(),
        )
    finally:
        connection.close()
    if candles.empty:
        st.warning("Could not load candles for the selected trade.")
        return
    st.plotly_chart(trade_pattern_chart(candles, trade_row), use_container_width=True)


def main() -> None:
    st.set_page_config(page_title=CONFIG["dashboard"]["title"], page_icon=CONFIG["dashboard"]["page_icon"], layout="wide")
    st.title("Double Top Short Backtest Dashboard")
    st.caption("Autonomous local dashboard. Reads only exported backtest results and the existing futures candle cache in read-only mode.")

    patterns = load_export("patterns.csv")
    trades = load_export("trades.csv")
    if trades.empty:
        st.warning("No backtest exports were found. Run run_backtest.bat first.")
        return

    filtered_trades, starting_capital, stake_per_trade = apply_filters(trades)
    filtered_trades = enrich_money_model(filtered_trades, starting_capital=starting_capital, stake_per_trade=stake_per_trade)
    filtered_patterns = patterns[patterns["pattern_id"].isin(filtered_trades["pattern_id"])] if not patterns.empty else patterns
    scenario_summary = build_scenario_summary(filtered_trades, filtered_patterns)
    symbol_summary = build_symbol_summary(filtered_trades)
    month_summary = build_time_breakdown(filtered_trades, "entry_month")
    week_summary = build_time_breakdown(filtered_trades, "entry_week")
    rsi_bucket_summary = build_bucket_summary(filtered_trades, "rsi_bucket")
    atr_bucket_summary = build_bucket_summary(filtered_trades, "atr_bucket")
    volume_bucket_summary = build_bucket_summary(filtered_trades, "volume_bucket")
    liquidity_bucket_summary = build_bucket_summary(filtered_trades, "liquidity_bucket")
    scenario_summary = add_money_columns(scenario_summary, filtered_trades, ["scenario_name", "stop_pct", "take_pct"], starting_capital=starting_capital, add_balance=True)
    symbol_summary = add_money_columns(symbol_summary, filtered_trades, ["scenario_name", "symbol"], starting_capital=starting_capital)
    month_summary = add_money_columns(month_summary, filtered_trades, ["scenario_name", "entry_month"], starting_capital=starting_capital)
    week_summary = add_money_columns(week_summary, filtered_trades, ["scenario_name", "entry_week"], starting_capital=starting_capital)
    rsi_bucket_summary = add_money_columns(rsi_bucket_summary, filtered_trades, ["scenario_name", "rsi_bucket"], starting_capital=starting_capital)
    atr_bucket_summary = add_money_columns(atr_bucket_summary, filtered_trades, ["scenario_name", "atr_bucket"], starting_capital=starting_capital)
    volume_bucket_summary = add_money_columns(volume_bucket_summary, filtered_trades, ["scenario_name", "volume_bucket"], starting_capital=starting_capital)
    liquidity_bucket_summary = add_money_columns(liquidity_bucket_summary, filtered_trades, ["scenario_name", "liquidity_bucket"], starting_capital=starting_capital)

    st.info(
        f"Money model: start `${starting_capital:,.0f}`, fixed stake `${stake_per_trade:,.0f}` per trade, no fees/funding/slippage. "
        f"`Net PnL` and `Final balance` are calculated from filtered trades only."
    )
    metric_row(filtered_trades, filtered_patterns, starting_capital=starting_capital)
    if filtered_trades.empty:
        st.info("No trades match the active filters.")
        return

    st.subheader("Scenario and aggregation tables")
    rename_map = {
        "scenario_name": "Scenario",
        "symbol": "Symbol",
        "entry_month": "Month",
        "entry_week": "Week",
        "rsi_bucket": "RSI bucket",
        "atr_bucket": "ATR bucket",
        "volume_bucket": "Volume bucket",
        "liquidity_bucket": "Liquidity bucket",
        "take_pct": "TP, %",
        "stop_pct": "SL, %",
        "total_trades_opened": "Trades",
        "resolved_trades_count": "Resolved",
        "total_take": "TP hits",
        "total_stop": "SL hits",
        "total_open": "OPEN",
        "win_rate_pct": "Win rate, %",
        "loss_rate_pct": "Loss rate, %",
        "avg_return_per_trade_pct": "Avg return, %",
        "avg_minutes_to_take": "Avg min to TP",
        "avg_minutes_to_stop": "Avg min to SL",
        "profit_factor": "Profit factor",
        "net_profit_usd": "Net PnL, $",
        "ending_capital_usd": "Final balance, $",
    }
    scenario_view = compact_table(
        scenario_summary.sort_values(["win_rate_pct", "net_profit_usd", "total_trades_opened"], ascending=[False, False, False]),
        [
            "scenario_name",
            "take_pct",
            "stop_pct",
            "total_trades_opened",
            "resolved_trades_count",
            "total_take",
            "total_stop",
            "total_open",
            "win_rate_pct",
            "loss_rate_pct",
            "avg_return_per_trade_pct",
            "profit_factor",
            "net_profit_usd",
            "ending_capital_usd",
        ],
        rename_map,
    )
    symbol_view = compact_table(
        symbol_summary.sort_values(["win_rate_pct", "net_profit_usd", "total_trades_opened"], ascending=[False, False, False]).head(100),
        [
            "scenario_name",
            "symbol",
            "total_trades_opened",
            "resolved_trades_count",
            "total_take",
            "total_stop",
            "total_open",
            "win_rate_pct",
            "avg_return_per_trade_pct",
            "net_profit_usd",
        ],
        rename_map,
    )
    month_view = compact_table(
        month_summary.sort_values(["entry_month", "scenario_name"]),
        [
            "scenario_name",
            "entry_month",
            "total_trades_opened",
            "resolved_trades_count",
            "total_take",
            "total_stop",
            "total_open",
            "win_rate_pct",
            "net_profit_usd",
        ],
        rename_map,
    )
    week_view = compact_table(
        week_summary.sort_values(["entry_week", "scenario_name"]),
        [
            "scenario_name",
            "entry_week",
            "total_trades_opened",
            "resolved_trades_count",
            "total_take",
            "total_stop",
            "total_open",
            "win_rate_pct",
            "net_profit_usd",
        ],
        rename_map,
    )
    rsi_view = compact_table(
        rsi_bucket_summary.sort_values(["win_rate_pct", "net_profit_usd", "total_trades_opened"], ascending=[False, False, False]),
        [
            "scenario_name",
            "rsi_bucket",
            "total_trades_opened",
            "resolved_trades_count",
            "total_take",
            "total_stop",
            "total_open",
            "win_rate_pct",
            "net_profit_usd",
        ],
        rename_map,
    )
    atr_view = compact_table(
        atr_bucket_summary.sort_values(["win_rate_pct", "net_profit_usd", "total_trades_opened"], ascending=[False, False, False]),
        [
            "scenario_name",
            "atr_bucket",
            "total_trades_opened",
            "resolved_trades_count",
            "total_take",
            "total_stop",
            "total_open",
            "win_rate_pct",
            "net_profit_usd",
        ],
        rename_map,
    )
    volume_view = compact_table(
        volume_bucket_summary.sort_values(["win_rate_pct", "net_profit_usd", "total_trades_opened"], ascending=[False, False, False]),
        [
            "scenario_name",
            "volume_bucket",
            "total_trades_opened",
            "resolved_trades_count",
            "total_take",
            "total_stop",
            "total_open",
            "win_rate_pct",
            "net_profit_usd",
        ],
        rename_map,
    )
    liquidity_view = compact_table(
        liquidity_bucket_summary.sort_values(["win_rate_pct", "net_profit_usd", "total_trades_opened"], ascending=[False, False, False]),
        [
            "scenario_name",
            "liquidity_bucket",
            "total_trades_opened",
            "resolved_trades_count",
            "total_take",
            "total_stop",
            "total_open",
            "win_rate_pct",
            "net_profit_usd",
        ],
        rename_map,
    )

    tab_scenarios, tab_symbols, tab_time, tab_buckets = st.tabs(["Scenarios", "Symbols", "Time", "Buckets"])
    with tab_scenarios:
        st.dataframe(scenario_view, use_container_width=True, hide_index=True)
    with tab_symbols:
        st.dataframe(symbol_view, use_container_width=True, hide_index=True)
    with tab_time:
        st.dataframe(month_view, use_container_width=True, hide_index=True)
        st.dataframe(week_view, use_container_width=True, hide_index=True)
    with tab_buckets:
        st.dataframe(rsi_view, use_container_width=True, hide_index=True)
        st.dataframe(atr_view, use_container_width=True, hide_index=True)
        st.dataframe(volume_view, use_container_width=True, hide_index=True)
        st.dataframe(liquidity_view, use_container_width=True, hide_index=True)

    st.subheader("Charts")
    charts = [
        equity_curve(filtered_trades),
        outcomes_bar(filtered_trades),
        outcomes_pie(filtered_trades),
        histogram_minutes(filtered_trades, "TAKE"),
        histogram_minutes(filtered_trades, "STOP"),
        mfe_mae_box(filtered_trades),
        scatter_by_feature(filtered_trades, "atr_pct_at_entry", "ATR % vs realized return"),
        scatter_by_feature(filtered_trades, "rsi_at_entry", "RSI at entry vs realized return"),
        scenario_heatmap(scenario_summary, "win_rate_pct", "Win rate heatmap by scenario"),
        symbol_heatmap(symbol_summary, int(CONFIG["dashboard"].get("default_symbol_limit_for_heatmap", 30))),
        return_distribution(filtered_trades),
        cumulative_return_by_symbol(filtered_trades),
        patterns_over_time(filtered_trades),
    ]
    for idx in range(0, len(charts), 2):
        left_col, right_col = st.columns(2)
        left_col.plotly_chart(charts[idx], use_container_width=True)
        if idx + 1 < len(charts):
            right_col.plotly_chart(charts[idx + 1], use_container_width=True)

    st.subheader("Trade table")
    trade_view = compact_table(
        filtered_trades,
        [
            "scenario_name",
            "symbol",
            "entry_time",
            "outcome",
            "entry_price",
            "take_price",
            "stop_price",
            "realized_return_pct",
            "trade_pnl_usd",
            "equity_after_trade_usd",
            "minutes_to_outcome",
            "rsi_at_entry",
            "atr_pct_at_entry",
            "volume_ratio_at_entry",
            "quote_volume_24h_at_entry",
        ],
        {
            "scenario_name": "Scenario",
            "symbol": "Symbol",
            "entry_time": "Entry time",
            "outcome": "Outcome",
            "entry_price": "Entry",
            "take_price": "TP price",
            "stop_price": "SL price",
            "realized_return_pct": "Return, %",
            "trade_pnl_usd": "PnL, $",
            "equity_after_trade_usd": "Balance after trade, $",
            "minutes_to_outcome": "Minutes to result",
            "rsi_at_entry": "RSI",
            "atr_pct_at_entry": "ATR, %",
            "volume_ratio_at_entry": "Volume ratio",
            "quote_volume_24h_at_entry": "Liquidity 24h, $",
        },
    )
    st.dataframe(trade_view, use_container_width=True, hide_index=True)
    st.download_button(
        "Export filtered trades to CSV",
        filtered_trades.to_csv(index=False).encode("utf-8-sig"),
        file_name="filtered_double_top_trades.csv",
        mime="text/csv",
    )

    trade_detail_section(filtered_trades, filtered_patterns)


if __name__ == "__main__":
    main()
