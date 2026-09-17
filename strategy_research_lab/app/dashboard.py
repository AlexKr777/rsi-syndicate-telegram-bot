from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pandas as pd
import streamlit as st

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from app.charts import (
    bar_final_balance,
    bar_net_pnl,
    drawdown_curve,
    duration_histogram,
    equity_curve,
    mfe_mae_box,
    monthly_pnl_heatmap,
    outcomes_pie,
    pnl_histogram,
    scatter_return_by_feature,
    strategy_scenario_heatmap,
    style_figure,
    symbol_strategy_heatmap,
    trade_signal_chart,
)
from app.data_loader import load_candles_for_trade, open_read_only_connection
from app.metrics import (
    build_bucket_summary,
    build_overall_snapshot,
    build_scenario_summary,
    build_strategy_scenario_summary,
    build_strategy_summary,
    build_symbol_summary,
    build_time_summary,
    prepare_trades_frame,
)
from app.utils import EXPORTS_DIR, load_config


CONFIG = load_config("config.yaml")


def inject_css() -> None:
    st.markdown(
        """
        <style>
        .stApp { background: #0f1117; color: #f3f5f7; }
        .block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
        [data-testid="stMetric"] {
            background: linear-gradient(180deg, rgba(28,34,46,0.98), rgba(18,22,31,0.98));
            border: 1px solid rgba(121, 170, 255, 0.14);
            padding: 0.9rem 1rem;
            border-radius: 14px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.25);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False)
def load_export(name: str) -> pd.DataFrame:
    path = EXPORTS_DIR / name
    if not path.exists():
        return pd.DataFrame()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=pd.errors.DtypeWarning)
        if name == "trades.csv":
            return pd.read_csv(path, parse_dates=["signal_time", "entry_time", "exit_time", "settlement_time"], low_memory=False)
        return pd.read_csv(path, low_memory=False)


def sample_for_plots(trades: pd.DataFrame, max_points: int) -> pd.DataFrame:
    if trades.empty or len(trades) <= max_points:
        return trades
    group_cols = ["strategy_name"]
    if "outcome" in trades.columns:
        group_cols.append("outcome")
    grouped = list(trades.groupby(group_cols, dropna=False))
    per_group = max(1, max_points // max(1, len(grouped)))
    sampled_parts: list[pd.DataFrame] = []
    for _, group in grouped:
        if len(group) <= per_group:
            sampled_parts.append(group)
        else:
            sampled_parts.append(group.sample(n=per_group, random_state=42))
    sampled = pd.concat(sampled_parts, ignore_index=False)
    if len(sampled) > max_points:
        sampled = sampled.sample(n=max_points, random_state=42)
    return sampled.sort_values(["entry_time", "trade_id"]).reset_index(drop=True)


def apply_filters(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades
    frame = trades.copy()
    frame["entry_time"] = pd.to_datetime(frame["entry_time"], utc=True, errors="coerce")
    frame["exit_time"] = pd.to_datetime(frame["exit_time"], utc=True, errors="coerce")
    frame["settlement_time"] = pd.to_datetime(frame["settlement_time"], utc=True, errors="coerce")

    st.sidebar.header("Filters")
    strategy_names = sorted(frame["strategy_name"].dropna().unique().tolist())
    scenario_names = sorted(frame["scenario_name"].dropna().unique().tolist())
    symbols = sorted(frame["symbol"].dropna().unique().tolist())
    outcomes = sorted(frame["outcome"].dropna().unique().tolist())
    sides = sorted(frame["side"].dropna().unique().tolist())
    rsi_buckets = sorted(frame["rsi_bucket_at_entry"].dropna().unique().tolist())
    atr_buckets = sorted(frame["atr_bucket_at_entry"].dropna().unique().tolist())
    volume_buckets = sorted(frame["volume_bucket_at_entry"].dropna().unique().tolist())
    liquidity_buckets = sorted(frame["liquidity_bucket_at_entry"].dropna().unique().tolist())
    score_buckets = sorted(frame["score_bucket_at_entry"].dropna().unique().tolist())
    ambiguous_policies = sorted(frame["ambiguous_policy"].dropna().unique().tolist()) if "ambiguous_policy" in frame.columns else []

    min_date = frame["entry_time"].min().date()
    max_date = frame["entry_time"].max().date()
    show_all_strategies = st.sidebar.checkbox("Show all strategies", value=bool(CONFIG["dashboard"].get("show_all_strategies_by_default", True)))
    default_strategies = [item for item in CONFIG["dashboard"].get("default_strategy_selection", []) if item in strategy_names]
    selected_strategies = strategy_names if show_all_strategies else st.sidebar.multiselect(
        "Strategy",
        strategy_names,
        default=default_strategies or strategy_names,
    )
    selected_scenarios = st.sidebar.multiselect("Scenario", scenario_names)
    selected_symbols = st.sidebar.multiselect("Symbol", symbols)
    selected_sides = st.sidebar.multiselect("Side", sides)
    selected_outcomes = st.sidebar.multiselect("Outcome", outcomes)
    selected_rsi = st.sidebar.multiselect("RSI bucket", rsi_buckets)
    selected_atr = st.sidebar.multiselect("ATR bucket", atr_buckets)
    selected_volume = st.sidebar.multiselect("Volume bucket", volume_buckets)
    selected_liquidity = st.sidebar.multiselect("Liquidity bucket", liquidity_buckets)
    selected_score = st.sidebar.multiselect("Score bucket", score_buckets)
    selected_ambiguous = st.sidebar.multiselect("Ambiguous policy", ambiguous_policies, default=ambiguous_policies if ambiguous_policies else None)
    date_range = st.sidebar.date_input("Date range", value=(min_date, max_date))

    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
        frame = frame[(frame["entry_time"].dt.date >= start_date) & (frame["entry_time"].dt.date <= end_date)]
    if selected_strategies:
        frame = frame[frame["strategy_name"].isin(selected_strategies)]
    if selected_scenarios:
        frame = frame[frame["scenario_name"].isin(selected_scenarios)]
    if selected_symbols:
        frame = frame[frame["symbol"].isin(selected_symbols)]
    if selected_sides:
        frame = frame[frame["side"].isin(selected_sides)]
    if selected_outcomes:
        frame = frame[frame["outcome"].isin(selected_outcomes)]
    if selected_rsi:
        frame = frame[frame["rsi_bucket_at_entry"].isin(selected_rsi)]
    if selected_atr:
        frame = frame[frame["atr_bucket_at_entry"].isin(selected_atr)]
    if selected_volume:
        frame = frame[frame["volume_bucket_at_entry"].isin(selected_volume)]
    if selected_liquidity:
        frame = frame[frame["liquidity_bucket_at_entry"].isin(selected_liquidity)]
    if selected_score:
        frame = frame[frame["score_bucket_at_entry"].isin(selected_score)]
    if selected_ambiguous:
        frame = frame[frame["ambiguous_policy"].isin(selected_ambiguous)]
    return frame


def compact_table(dataframe: pd.DataFrame, columns: list[str], rename_map: dict[str, str]) -> pd.DataFrame:
    if dataframe.empty:
        return dataframe
    available = [column for column in columns if column in dataframe.columns]
    compact = dataframe[available].copy()
    numeric_columns = compact.select_dtypes(include="number").columns
    if len(numeric_columns):
        compact[numeric_columns] = compact[numeric_columns].round(2)
    return compact.rename(columns=rename_map)


def metric_cards(snapshot: dict) -> None:
    row_one = st.columns(5)
    row_two = st.columns(5)
    cards = [
        ("Trades", snapshot["total_trades"]),
        ("Net PnL, $", f"{snapshot['total_net_pnl_usd']:,.2f}"),
        ("Final balance, $", f"{snapshot['final_balance_usd']:,.2f}"),
        ("Best strategy", snapshot["best_strategy"] or "n/a"),
        ("Best scenario", snapshot["best_scenario"] or "n/a"),
        ("Best symbol", snapshot["best_symbol"] or "n/a"),
        ("Win rate", f"{snapshot['win_rate_pct']:.2f}%"),
        ("Profit factor", f"{snapshot['profit_factor']:.2f}" if snapshot["profit_factor"] is not None else "n/a"),
        ("Max drawdown", f"${snapshot['max_drawdown_usd']:,.2f} / {snapshot['max_drawdown_pct']:.2f}%"),
        ("Resolved / OPEN / AMB", f"{snapshot['resolved_trades']} / {snapshot['open_count']} / {snapshot['ambiguous_count']}"),
    ]
    for column, (label, value) in zip(row_one + row_two, cards, strict=False):
        column.metric(label, value)


def trade_viewer(trades: pd.DataFrame) -> None:
    st.subheader("Pattern / Signal Viewer")
    if trades.empty:
        st.info("No trades match the active filters.")
        return
    if not st.checkbox("Enable trade viewer", value=False, help="Loads the selectable trade list and extra candles only when needed."):
        st.info("Viewer is disabled by default so the dashboard stays fast when all strategies are selected.")
        return
    viewer_limit = int(CONFIG["dashboard"].get("trade_viewer_recent_limit", 500))
    recent_trades = trades.sort_values("entry_time", ascending=False).head(viewer_limit).copy()
    trade_options = recent_trades["trade_id"].tolist()
    selected_trade_id = st.selectbox(
        "Select trade",
        trade_options,
        format_func=lambda trade_id: (
            f"{recent_trades.loc[recent_trades['trade_id'] == trade_id, 'entry_time'].iloc[0]} | "
            f"{recent_trades.loc[recent_trades['trade_id'] == trade_id, 'strategy_name'].iloc[0]} | "
            f"{recent_trades.loc[recent_trades['trade_id'] == trade_id, 'symbol'].iloc[0]} | "
            f"{recent_trades.loc[recent_trades['trade_id'] == trade_id, 'scenario_name'].iloc[0]} | "
            f"{recent_trades.loc[recent_trades['trade_id'] == trade_id, 'outcome'].iloc[0]}"
        ),
    )
    trade_row = trades.loc[trades["trade_id"] == selected_trade_id].iloc[0].copy()
    st.dataframe(pd.DataFrame([trade_row]), width="stretch", hide_index=True)

    connection = open_read_only_connection(CONFIG["data_source"]["sqlite_path"])
    try:
        padding_bars = int(CONFIG["dashboard"].get("trade_chart_padding_bars", 24))
        time_candidates = [
            trade_row.get("first_peak_time"),
            trade_row.get("first_bottom_time"),
            trade_row.get("signal_time"),
            trade_row.get("entry_time"),
        ]
        base_start_time = next((value for value in time_candidates if value is not None and pd.notna(value)), trade_row["entry_time"])
        start_time = pd.to_datetime(base_start_time, utc=True) - pd.Timedelta(minutes=15 * padding_bars)
        end_base = pd.to_datetime(trade_row["exit_time"], utc=True) if pd.notna(trade_row.get("exit_time")) else pd.to_datetime(trade_row["entry_time"], utc=True) + pd.Timedelta(hours=24)
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
    st.plotly_chart(trade_signal_chart(candles, trade_row), width="stretch")


def main() -> None:
    st.set_page_config(page_title=CONFIG["dashboard"]["title"], page_icon=CONFIG["dashboard"]["page_icon"], layout="wide")
    inject_css()
    st.title("Strategy Research Lab")
    st.caption("Autonomous multi-strategy research dashboard. Reads only exported backtest results and the existing futures candle cache in read-only mode.")

    trades = load_export("trades.csv")
    if trades.empty:
        st.warning("No exports found. Run run_backtests.bat first.")
        return

    starting_capital = float(CONFIG["money_model"]["starting_capital_usd"])
    filtered_trades = apply_filters(trades)
    prepared = prepare_trades_frame(filtered_trades, starting_capital)
    if prepared.empty:
        st.info("No trades match the active filters.")
        return
    chart_max_points = int(CONFIG["dashboard"].get("max_plot_points", 15000))
    chart_trades = sample_for_plots(prepared, chart_max_points)

    snapshot = build_overall_snapshot(prepared, starting_capital)
    strategy_summary = build_strategy_summary(prepared, starting_capital)
    scenario_summary = build_scenario_summary(prepared, starting_capital)
    strategy_scenario_summary = build_strategy_scenario_summary(prepared, starting_capital)
    symbol_summary = build_symbol_summary(prepared, starting_capital)
    month_summary = build_time_summary(prepared, "entry_month", starting_capital)
    week_summary = build_time_summary(prepared, "entry_week", starting_capital)
    rsi_bucket_summary = build_bucket_summary(prepared, "rsi_bucket_at_entry", starting_capital)
    atr_bucket_summary = build_bucket_summary(prepared, "atr_bucket_at_entry", starting_capital)
    volume_bucket_summary = build_bucket_summary(prepared, "volume_bucket_at_entry", starting_capital)
    liquidity_bucket_summary = build_bucket_summary(prepared, "liquidity_bucket_at_entry", starting_capital)
    score_bucket_summary = build_bucket_summary(prepared, "score_bucket_at_entry", starting_capital)

    metric_cards(snapshot)

    rename_map = {
        "strategy_name": "Strategy",
        "scenario_name": "Scenario",
        "symbol": "Symbol",
        "entry_month": "Month",
        "entry_week": "Week",
        "rsi_bucket_at_entry": "RSI bucket",
        "atr_bucket_at_entry": "ATR bucket",
        "volume_bucket_at_entry": "Volume bucket",
        "liquidity_bucket_at_entry": "Liquidity bucket",
        "score_bucket_at_entry": "Score bucket",
        "trades": "Trades",
        "resolved_trades": "Resolved",
        "take_count": "TAKE",
        "stop_count": "STOP",
        "open_count": "OPEN",
        "ambiguous_count": "AMB",
        "win_rate_pct": "Win rate, %",
        "loss_rate_pct": "Loss rate, %",
        "avg_pnl_usd": "Avg PnL, $",
        "median_pnl_usd": "Median PnL, $",
        "total_net_pnl_usd": "Net PnL, $",
        "final_balance_usd": "Final balance, $",
        "profit_factor": "Profit factor",
        "expectancy_usd": "Expectancy, $",
        "avg_duration_minutes": "Avg duration, min",
        "max_drawdown_usd": "Max DD, $",
        "max_drawdown_pct": "Max DD, %",
        "best_symbol": "Best symbol",
        "worst_symbol": "Worst symbol",
        "best_month": "Best month",
        "worst_month": "Worst month",
    }

    exec_tab, strategy_tab, scenario_tab, symbol_tab, time_tab, bucket_tab, trades_tab, viewer_tab = st.tabs(
        ["Executive Summary", "Strategy Comparison", "Scenario Comparison", "Symbol Comparison", "Time Analysis", "Buckets Analysis", "Trades Explorer", "Pattern / Signal Viewer"]
    )

    with exec_tab:
        if len(prepared) > len(chart_trades):
            st.caption(f"For speed, heavy charts below use a representative sample of {len(chart_trades):,} trades out of {len(prepared):,}. Tables and money metrics still use the full filtered set.")
        left, right = st.columns(2)
        left.plotly_chart(equity_curve(chart_trades, "strategy_name", starting_capital, "Equity curve by strategy"), width="stretch")
        right.plotly_chart(drawdown_curve(chart_trades, "strategy_name", starting_capital, "Drawdown curve by strategy"), width="stretch")
        left, right = st.columns(2)
        left.plotly_chart(outcomes_pie(prepared), width="stretch")
        right.plotly_chart(pnl_histogram(chart_trades), width="stretch")

    with strategy_tab:
        strategy_view = compact_table(
            strategy_summary,
            [
                "strategy_name",
                "trades",
                "resolved_trades",
                "take_count",
                "stop_count",
                "open_count",
                "win_rate_pct",
                "total_net_pnl_usd",
                "final_balance_usd",
                "profit_factor",
                "expectancy_usd",
                "max_drawdown_usd",
                "max_drawdown_pct",
                "best_symbol",
                "worst_symbol",
            ],
            rename_map,
        )
        st.dataframe(strategy_view, width="stretch", hide_index=True)
        left, right = st.columns(2)
        left.plotly_chart(bar_net_pnl(strategy_summary, "strategy_name", "Net PnL by strategy"), width="stretch")
        right.plotly_chart(bar_final_balance(strategy_summary, "strategy_name", "Final balance by strategy"), width="stretch")

    with scenario_tab:
        scenario_view = compact_table(
            strategy_scenario_summary,
            [
                "strategy_name",
                "scenario_name",
                "trades",
                "resolved_trades",
                "take_count",
                "stop_count",
                "open_count",
                "win_rate_pct",
                "total_net_pnl_usd",
                "final_balance_usd",
                "profit_factor",
                "expectancy_usd",
                "max_drawdown_usd",
                "max_drawdown_pct",
            ],
            rename_map,
        )
        st.dataframe(scenario_view, width="stretch", hide_index=True)
        left, right = st.columns(2)
        left.plotly_chart(strategy_scenario_heatmap(strategy_scenario_summary), width="stretch")
        right.plotly_chart(equity_curve(chart_trades, "scenario_name", starting_capital, "Equity curve by scenario"), width="stretch")

    with symbol_tab:
        symbol_view = compact_table(
            symbol_summary.head(200),
            ["strategy_name", "symbol", "trades", "resolved_trades", "win_rate_pct", "total_net_pnl_usd", "profit_factor", "max_drawdown_usd"],
            rename_map,
        )
        st.dataframe(symbol_view, width="stretch", hide_index=True)
        left, right = st.columns(2)
        left.plotly_chart(bar_net_pnl(symbol_summary, "symbol", "Net PnL by symbol (top 30)", limit=30), width="stretch")
        right.plotly_chart(symbol_strategy_heatmap(symbol_summary, int(CONFIG["dashboard"].get("default_symbol_limit_for_heatmap", 30))), width="stretch")

    with time_tab:
        month_view = compact_table(month_summary, ["strategy_name", "entry_month", "trades", "win_rate_pct", "total_net_pnl_usd", "final_balance_usd"], rename_map)
        week_view = compact_table(week_summary, ["strategy_name", "entry_week", "trades", "win_rate_pct", "total_net_pnl_usd"], rename_map)
        st.dataframe(month_view, width="stretch", hide_index=True)
        st.dataframe(week_view, width="stretch", hide_index=True)
        left, right = st.columns(2)
        left.plotly_chart(monthly_pnl_heatmap(month_summary), width="stretch")
        right.plotly_chart(bar_net_pnl(month_summary, "entry_month", "PnL by month"), width="stretch")

    with bucket_tab:
        bucket_tabs = st.tabs(["RSI", "ATR", "Volume", "Liquidity", "Score"])
        bucket_data = [
            (rsi_bucket_summary, "rsi_bucket_at_entry"),
            (atr_bucket_summary, "atr_bucket_at_entry"),
            (volume_bucket_summary, "volume_bucket_at_entry"),
            (liquidity_bucket_summary, "liquidity_bucket_at_entry"),
            (score_bucket_summary, "score_bucket_at_entry"),
        ]
        for tab, (bucket_frame, bucket_col) in zip(bucket_tabs, bucket_data, strict=False):
            with tab:
                bucket_view = compact_table(bucket_frame, ["strategy_name", bucket_col, "trades", "win_rate_pct", "total_net_pnl_usd", "profit_factor"], rename_map)
                st.dataframe(bucket_view, width="stretch", hide_index=True)

    with trades_tab:
        table_default_rows = int(CONFIG["dashboard"].get("trades_table_default_rows", 1000))
        table_max_rows = int(CONFIG["dashboard"].get("trades_table_max_rows", 5000))
        display_rows = st.slider(
            "Rows shown in trades table",
            min_value=100,
            max_value=max(100, table_max_rows),
            value=min(max(100, table_default_rows), table_max_rows, max(100, len(prepared))),
            step=100,
        )
        st.caption(f"Showing {min(len(prepared), display_rows):,} of {len(prepared):,} filtered trades. Download button below still exports the full filtered set.")
        trade_view = compact_table(
            prepared.sort_values("entry_time", ascending=False).head(display_rows),
            [
                "strategy_name",
                "scenario_name",
                "symbol",
                "side",
                "entry_time",
                "outcome",
                "entry_price",
                "stop_price",
                "take_price",
                "net_pnl_usd",
                "return_pct",
                "cumulative_balance_after_trade",
                "rsi_at_entry",
                "atr_pct_at_entry",
                "volume_ratio_at_entry",
                "bot_like_score_at_entry",
            ],
            {
                "strategy_name": "Strategy",
                "scenario_name": "Scenario",
                "symbol": "Symbol",
                "side": "Side",
                "entry_time": "Entry time",
                "outcome": "Outcome",
                "entry_price": "Entry",
                "stop_price": "Stop",
                "take_price": "Take",
                "net_pnl_usd": "Net PnL, $",
                "return_pct": "Return, %",
                "cumulative_balance_after_trade": "Balance after trade, $",
                "rsi_at_entry": "RSI",
                "atr_pct_at_entry": "ATR, %",
                "volume_ratio_at_entry": "Vol ratio",
                "bot_like_score_at_entry": "Score",
            },
        )
        st.dataframe(trade_view, width="stretch", hide_index=True)
        st.download_button(
            "Export filtered trades to CSV",
            prepared.to_csv(index=False).encode("utf-8-sig"),
            file_name="strategy_research_lab_filtered_trades.csv",
            mime="text/csv",
        )
        left, right = st.columns(2)
        left.plotly_chart(duration_histogram(chart_trades, "TAKE"), width="stretch")
        right.plotly_chart(duration_histogram(chart_trades, "STOP"), width="stretch")
        left, right = st.columns(2)
        left.plotly_chart(mfe_mae_box(chart_trades), width="stretch")
        right.plotly_chart(scatter_return_by_feature(chart_trades, "rsi_at_entry", "RSI vs trade PnL"), width="stretch")
        left, right = st.columns(2)
        left.plotly_chart(scatter_return_by_feature(chart_trades, "atr_pct_at_entry", "ATR% vs trade PnL"), width="stretch")
        right.plotly_chart(scatter_return_by_feature(chart_trades, "volume_ratio_at_entry", "Volume ratio vs trade PnL"), width="stretch")

    with viewer_tab:
        trade_viewer(prepared)


if __name__ == "__main__":
    main()
