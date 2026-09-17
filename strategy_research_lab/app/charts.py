from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


THEME = {
    "paper_bgcolor": "#0f1117",
    "plot_bgcolor": "#171b24",
    "font_color": "#f3f5f7",
    "grid_color": "#2a3040",
}


def style_figure(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        paper_bgcolor=THEME["paper_bgcolor"],
        plot_bgcolor=THEME["plot_bgcolor"],
        font=dict(color=THEME["font_color"]),
        margin=dict(l=24, r=24, t=56, b=24),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(gridcolor=THEME["grid_color"])
    fig.update_yaxes(gridcolor=THEME["grid_color"])
    return fig


def outcomes_pie(trades: pd.DataFrame) -> go.Figure:
    counts = trades["outcome"].value_counts().rename_axis("outcome").reset_index(name="count")
    return style_figure(px.pie(counts, names="outcome", values="count", hole=0.55, title="Outcomes share"))


def pnl_histogram(trades: pd.DataFrame) -> go.Figure:
    return style_figure(px.histogram(trades, x="net_pnl_usd_filled", color="strategy_name", nbins=50, barmode="overlay", title="PnL per trade, $"))


def duration_histogram(trades: pd.DataFrame, outcome: str) -> go.Figure:
    subset = trades[trades["outcome"] == outcome]
    return style_figure(px.histogram(subset, x="minutes_to_outcome", color="strategy_name", nbins=40, title=f"Minutes to {outcome}"))


def mfe_mae_box(trades: pd.DataFrame) -> go.Figure:
    long = trades.melt(id_vars=["strategy_name"], value_vars=["mfe_pct", "mae_pct"], var_name="metric", value_name="value")
    return style_figure(px.box(long, x="metric", y="value", color="strategy_name", title="MFE / MAE by strategy"))


def scatter_return_by_feature(trades: pd.DataFrame, x_col: str, title: str) -> go.Figure:
    fig = px.scatter(
        trades,
        x=x_col,
        y="net_pnl_usd_filled",
        color="outcome",
        hover_data=["strategy_name", "scenario_name", "symbol", "entry_time"],
        title=title,
    )
    return style_figure(fig)


def bar_net_pnl(summary: pd.DataFrame, category_col: str, title: str, value_col: str = "total_net_pnl_usd", limit: int | None = None) -> go.Figure:
    working = summary.copy()
    if limit is not None:
        working = working.sort_values(value_col, ascending=False).head(limit)
    fig = px.bar(working, x=category_col, y=value_col, color=category_col, title=title)
    return style_figure(fig)


def bar_final_balance(summary: pd.DataFrame, category_col: str, title: str) -> go.Figure:
    fig = px.bar(summary.sort_values("final_balance_usd", ascending=False), x=category_col, y="final_balance_usd", color=category_col, title=title)
    return style_figure(fig)


def equity_curve(trades: pd.DataFrame, group_col: str, starting_capital: float, title: str) -> go.Figure:
    if trades.empty:
        return style_figure(go.Figure())
    working = trades.sort_values([group_col, "settlement_time", "trade_id"]).copy()
    working["equity_curve_usd"] = starting_capital + working.groupby(group_col, dropna=False)["net_pnl_usd_filled"].cumsum()
    fig = px.line(working, x="settlement_time", y="equity_curve_usd", color=group_col, title=title)
    fig.update_yaxes(title="Balance, $")
    return style_figure(fig)


def drawdown_curve(trades: pd.DataFrame, group_col: str, starting_capital: float, title: str) -> go.Figure:
    if trades.empty:
        return style_figure(go.Figure())
    working = trades.sort_values([group_col, "settlement_time", "trade_id"]).copy()
    equity = starting_capital + working.groupby(group_col, dropna=False)["net_pnl_usd_filled"].cumsum()
    running_max = equity.groupby(working[group_col]).cummax()
    working["drawdown_pct_local"] = ((running_max - equity) / running_max.replace(0, pd.NA) * 100.0).fillna(0.0)
    fig = px.line(working, x="settlement_time", y="drawdown_pct_local", color=group_col, title=title)
    fig.update_yaxes(title="Drawdown, %")
    return style_figure(fig)


def strategy_scenario_heatmap(summary: pd.DataFrame) -> go.Figure:
    pivot = summary.pivot_table(index="strategy_name", columns="scenario_name", values="total_net_pnl_usd", aggfunc="first")
    return style_figure(px.imshow(pivot, text_auto=".0f", aspect="auto", title="Strategy x Scenario net PnL, $", color_continuous_scale="RdYlGn"))


def symbol_strategy_heatmap(symbol_summary: pd.DataFrame, limit: int) -> go.Figure:
    top_symbols = (
        symbol_summary.groupby("symbol", dropna=False)["total_net_pnl_usd"].sum().sort_values(ascending=False).head(limit).index.tolist()
    )
    working = symbol_summary[symbol_summary["symbol"].isin(top_symbols)]
    pivot = working.pivot_table(index="symbol", columns="strategy_name", values="total_net_pnl_usd", aggfunc="first")
    return style_figure(px.imshow(pivot, text_auto=".0f", aspect="auto", title=f"Symbol x Strategy net PnL (top {limit})", color_continuous_scale="RdYlGn"))


def monthly_pnl_heatmap(month_summary: pd.DataFrame) -> go.Figure:
    pivot = month_summary.pivot_table(index="strategy_name", columns="entry_month", values="total_net_pnl_usd", aggfunc="first")
    return style_figure(px.imshow(pivot, text_auto=".0f", aspect="auto", title="Monthly PnL heatmap", color_continuous_scale="RdYlGn"))


def trade_signal_chart(candles: pd.DataFrame, trade_row: pd.Series) -> go.Figure:
    fig = go.Figure(
        data=[
            go.Candlestick(
                x=candles["open_time"],
                open=candles["open"],
                high=candles["high"],
                low=candles["low"],
                close=candles["close"],
                name=str(trade_row["symbol"]),
            )
        ]
    )
    for y_value, color, label, dash in [
        (trade_row.get("entry_price"), "#4dd0e1", "Entry", "dash"),
        (trade_row.get("stop_price"), "#ef5350", "Stop", "dash"),
        (trade_row.get("take_price"), "#66bb6a", "Take", "dash"),
        (trade_row.get("neckline_price"), "#ffb74d", "Neckline", "dot"),
    ]:
        if y_value is not None and pd.notna(y_value):
            fig.add_hline(y=float(y_value), line_color=color, line_dash=dash, annotation_text=label)

    marker_specs = [
        ("Peak 1", "first_peak_time", "first_peak_price", "#ffd54f"),
        ("Peak 2", "second_peak_time", "second_peak_price", "#ffd54f"),
        ("Bottom 1", "first_bottom_time", "first_bottom_price", "#81c784"),
        ("Bottom 2", "second_bottom_time", "second_bottom_price", "#81c784"),
        ("Signal", "signal_time", "entry_price", "#90caf9"),
    ]
    for label, time_col, price_col, color in marker_specs:
        if time_col in trade_row.index and price_col in trade_row.index and pd.notna(trade_row.get(time_col)) and pd.notna(trade_row.get(price_col)):
            fig.add_trace(
                go.Scatter(
                    x=[pd.to_datetime(trade_row[time_col], utc=True)],
                    y=[float(trade_row[price_col])],
                    mode="markers+text",
                    marker=dict(size=10, color=color),
                    text=[label],
                    textposition="top center",
                    name=label,
                )
            )
    fig.update_layout(title=f"{trade_row['strategy_name']} | {trade_row['symbol']} | {trade_row['scenario_name']} | {trade_row['outcome']}", xaxis_rangeslider_visible=False)
    return style_figure(fig)
