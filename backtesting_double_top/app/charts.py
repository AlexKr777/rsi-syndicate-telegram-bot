from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


THEME = {
    "paper_bgcolor": "#fbf5ea",
    "plot_bgcolor": "#fffdf8",
    "font_color": "#11243d",
}


def style_figure(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        paper_bgcolor=THEME["paper_bgcolor"],
        plot_bgcolor=THEME["plot_bgcolor"],
        font=dict(color=THEME["font_color"]),
        margin=dict(l=24, r=24, t=56, b=24),
    )
    return fig


def outcomes_bar(trades: pd.DataFrame) -> go.Figure:
    counts = trades["outcome"].value_counts().rename_axis("outcome").reset_index(name="count")
    return style_figure(px.bar(counts, x="outcome", y="count", color="outcome", title="Outcomes by count"))


def outcomes_pie(trades: pd.DataFrame) -> go.Figure:
    counts = trades["outcome"].value_counts().rename_axis("outcome").reset_index(name="count")
    return style_figure(px.pie(counts, names="outcome", values="count", hole=0.55, title="Outcomes share"))


def equity_curve(trades: pd.DataFrame) -> go.Figure:
    resolved = trades[trades["realized_return_pct"].notna()].copy()
    if resolved.empty:
        return style_figure(go.Figure())
    resolved = resolved.sort_values(["scenario_name", "exit_time"])
    if "equity_after_trade_usd" in resolved.columns:
        fig = px.line(resolved, x="exit_time", y="equity_after_trade_usd", color="scenario_name", title="Balance curve by scenario")
        fig.update_yaxes(title="Balance, $")
    else:
        resolved["equity_curve_pct"] = resolved.groupby("scenario_name")["realized_return_pct"].cumsum()
        fig = px.line(resolved, x="exit_time", y="equity_curve_pct", color="scenario_name", title="Equity curve by scenario")
        fig.update_yaxes(title="Cumulative realized return, %")
    return style_figure(fig)


def histogram_minutes(trades: pd.DataFrame, outcome: str) -> go.Figure:
    subset = trades[trades["outcome"] == outcome]
    return style_figure(px.histogram(subset, x="minutes_to_outcome", nbins=40, title=f"Minutes to {outcome}"))


def mfe_mae_box(trades: pd.DataFrame) -> go.Figure:
    long = trades.melt(id_vars=["scenario_name"], value_vars=["mfe_pct", "mae_pct"], var_name="metric", value_name="value")
    return style_figure(px.box(long, x="metric", y="value", color="scenario_name", title="MFE / MAE distribution"))


def scatter_by_feature(trades: pd.DataFrame, x_col: str, title: str) -> go.Figure:
    fig = px.scatter(trades, x=x_col, y="realized_return_pct_filled", color="outcome", hover_data=["symbol", "scenario_name", "entry_time"], title=title)
    return style_figure(fig)


def scenario_heatmap(scenario_summary: pd.DataFrame, value_col: str, title: str) -> go.Figure:
    pivot = scenario_summary.pivot_table(index="scenario_name", values=value_col, aggfunc="first")
    return style_figure(px.imshow(pivot, text_auto=".2f", aspect="auto", title=title, color_continuous_scale="RdYlGn"))


def symbol_heatmap(symbol_summary: pd.DataFrame, limit: int) -> go.Figure:
    top = symbol_summary.sort_values("total_trades_opened", ascending=False).head(limit)
    pivot = top.pivot_table(index="symbol", columns="scenario_name", values="win_rate_pct", aggfunc="first")
    return style_figure(px.imshow(pivot, text_auto=".1f", aspect="auto", title=f"Win rate heatmap by symbol (top {limit} by trades)"))


def return_distribution(trades: pd.DataFrame) -> go.Figure:
    return style_figure(px.histogram(trades, x="realized_return_pct_filled", color="scenario_name", nbins=40, barmode="overlay", title="Return distribution per trade"))


def cumulative_return_by_symbol(trades: pd.DataFrame) -> go.Figure:
    value_col = "trade_pnl_usd" if "trade_pnl_usd" in trades.columns else "realized_return_pct_filled"
    grouped = trades.groupby(["scenario_name", "symbol"], dropna=False)[value_col].sum().reset_index()
    fig = px.bar(grouped.sort_values(value_col, ascending=False).head(50), x="symbol", y=value_col, color="scenario_name", title="Top cumulative result by symbol")
    return style_figure(fig)


def patterns_over_time(trades: pd.DataFrame) -> go.Figure:
    counts = trades.groupby(["entry_month", "scenario_name"], dropna=False)["trade_id"].count().reset_index(name="count")
    return style_figure(px.bar(counts, x="entry_month", y="count", color="scenario_name", barmode="group", title="Patterns / trades over time"))


def trade_pattern_chart(candles: pd.DataFrame, trade_row: pd.Series) -> go.Figure:
    fig = go.Figure(
        data=[
            go.Candlestick(
                x=candles["open_time"],
                open=candles["open"],
                high=candles["high"],
                low=candles["low"],
                close=candles["close"],
                name=trade_row["symbol"],
            )
        ]
    )
    fig.add_hline(y=float(trade_row["neckline_price"]), line_dash="dot", line_color="#bb5f45", annotation_text="Neckline")
    fig.add_hline(y=float(trade_row["entry_price"]), line_dash="dash", line_color="#0f6d7a", annotation_text="Entry")
    fig.add_hline(y=float(trade_row["stop_price"]), line_dash="dash", line_color="#b44e42", annotation_text="Stop")
    fig.add_hline(y=float(trade_row["take_price"]), line_dash="dash", line_color="#2d7d55", annotation_text="Take")
    for label, time_col, price_col, color in [
        ("Peak 1", "first_peak_time", "first_peak_price", "#d79b34"),
        ("Peak 2", "second_peak_time", "second_peak_price", "#d79b34"),
        ("Breakout", "breakout_time", "entry_price", "#11243d"),
    ]:
        if price_col not in trade_row.index or pd.isna(trade_row.get(price_col)):
            continue
        if time_col not in trade_row.index or pd.isna(trade_row.get(time_col)):
            continue
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
    fig.update_layout(title=f"{trade_row['symbol']} | {trade_row['scenario_name']} | {trade_row['outcome']}", xaxis_rangeslider_visible=False)
    return style_figure(fig)
