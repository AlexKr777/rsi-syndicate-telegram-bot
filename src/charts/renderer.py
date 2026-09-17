from __future__ import annotations

import asyncio
import logging
from numbers import Integral
from pathlib import Path
from uuid import uuid4

import matplotlib
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd

from src.core.config import Settings
from src.core.models import AlertSignal, FollowUpResult
from src.core.utils import format_percent, format_price, format_rsi, normalize_symbol

matplotlib.use("Agg")

LOGGER = logging.getLogger(__name__)


class ChartRenderer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._render_lock = asyncio.Lock()
        self.style = mpf.make_mpf_style(
            base_mpf_style="nightclouds",
            facecolor="#09131f",
            figcolor="#09131f",
            edgecolor="#09131f",
            gridstyle=":",
            gridcolor="#304256",
            rc={
                "font.size": 10,
                "axes.labelcolor": "#d6e2ee",
                "xtick.color": "#9db3c8",
                "ytick.color": "#9db3c8",
                "text.color": "#eef5fb",
            },
        )

    async def render_alert_chart(self, frame: pd.DataFrame, signal: AlertSignal, *, preview: bool = False) -> Path:
        async with self._render_lock:
            return await asyncio.to_thread(self._render_alert_chart_sync, frame, signal, preview)

    def _render_alert_chart_sync(self, frame: pd.DataFrame, signal: AlertSignal, preview: bool = False) -> Path:
        display_symbol = normalize_symbol(signal.symbol)
        live_price = signal.metadata.get("live_price")
        live_rsi = signal.metadata.get("live_rsi")
        setup_direction = str(signal.metadata.get("setup_direction") or signal.direction).strip()
        direction_prefix = setup_direction.title()
        if setup_direction and setup_direction != signal.direction:
            direction_prefix = f"Setup {setup_direction.title()} | Status {signal.direction.title()}"
        title = f"{display_symbol} - {signal.timeframe} RSI {'Preview' if preview else 'Alert'}"
        subtitle = (
            f"{direction_prefix} | Closed {format_price(signal.price)}"
            f"{f' | Market {format_price(float(live_price))}' if isinstance(live_price, (int, float)) else ''}"
            f" | Closed RSI {format_rsi(signal.rsi)}"
            f"{f' | Live RSI {format_rsi(float(live_rsi))}' if isinstance(live_rsi, (int, float)) else ''}"
            f" | Score {signal.score}"
        )
        display_price = float(live_price) if isinstance(live_price, (int, float)) else signal.price
        marker_time = (
            signal.metadata.get("marker_candle_close_time")
            or signal.candle_close_time
            or signal.metadata.get("marker_candle_open_time")
            or signal.candle_open_time
        )
        marker_price = signal.metadata.get("marker_price", signal.price)
        return self._render_chart(
            frame,
            title=title,
            subtitle=subtitle,
            last_price=display_price,
            last_rsi=signal.rsi,
            marker_time=marker_time,
            marker_price=float(marker_price),
        )

    async def render_followup_chart(self, frame: pd.DataFrame, result: FollowUpResult) -> Path:
        async with self._render_lock:
            return await asyncio.to_thread(self._render_followup_chart_sync, frame, result)

    def _render_followup_chart_sync(self, frame: pd.DataFrame, result: FollowUpResult) -> Path:
        display_symbol = normalize_symbol(result.symbol)
        latest_close = result.metadata.get("current_candle_close_price")
        live_rsi = result.metadata.get("live_rsi")
        stage = result.stage or str(result.metadata.get("followup_stage") or "2h")
        marker_time = (
            result.metadata.get("marker_candle_close_time")
            or result.metadata.get("signal_marker_close_time")
            or result.metadata.get("marker_candle_open_time")
            or result.metadata.get("signal_marker_open_time")
            or result.metadata.get("signal_candle_close_time")
        )
        marker_price = result.metadata.get("marker_price", result.alert_price)
        close_suffix = (
            f" | {result.timeframe} Close {format_price(float(latest_close))}"
            if isinstance(latest_close, (int, float))
            else ""
        )
        title = f"{display_symbol} - {result.timeframe} {stage} Follow-up"
        subtitle = (
            f"{result.direction.title()} | Alert {format_price(result.alert_price)} "
            f"-> Market {format_price(result.current_price)}{close_suffix} | Closed RSI {format_rsi(result.current_rsi)}"
            f"{f' | Live RSI {format_rsi(float(live_rsi))}' if isinstance(live_rsi, (int, float)) else ''}"
        )
        return self._render_chart(
            frame,
            title=title,
            subtitle=subtitle,
            last_price=result.current_price,
            last_rsi=result.current_rsi,
            marker_time=marker_time,
            marker_price=float(marker_price),
        )

    async def render_result_chart(
        self,
        frame: pd.DataFrame,
        signal: AlertSignal,
        result: FollowUpResult,
        *,
        label: str = "Result",
    ) -> Path:
        async with self._render_lock:
            return await asyncio.to_thread(self._render_result_chart_sync, frame, signal, result, label)

    def _render_result_chart_sync(
        self,
        frame: pd.DataFrame,
        signal: AlertSignal,
        result: FollowUpResult,
        label: str = "Result",
    ) -> Path:
        display_symbol = normalize_symbol(signal.symbol)
        marker_time = (
            signal.metadata.get("marker_candle_close_time")
            or signal.candle_close_time
            or signal.metadata.get("marker_candle_open_time")
            or signal.candle_open_time
        )
        chart_frame = self._select_chart_frame(frame, marker_time=marker_time)
        if "rsi" not in chart_frame.columns:
            raise ValueError("Chart frame must include an 'rsi' column")

        signal_index = self._resolve_marker_index(chart_frame.index, marker_time)
        signal_x = self._resolve_plot_x(chart_frame.index, signal_index)
        current_marker = pd.Series(float("nan"), index=chart_frame.index)
        signal_price = float(signal.metadata.get("marker_price", signal.price))
        current_marker.iloc[-1] = result.current_price

        addplots = [
            mpf.make_addplot(chart_frame["rsi"], panel=1, color="#71ddff", width=1.15, ylabel="RSI"),
            mpf.make_addplot(pd.Series(70, index=chart_frame.index), panel=1, color="#ffb86c", linestyle="--"),
            mpf.make_addplot(pd.Series(30, index=chart_frame.index), panel=1, color="#4ade80", linestyle="--"),
            mpf.make_addplot(
                current_marker,
                panel=0,
                type="scatter",
                marker="o",
                markersize=70,
                color="#4ade80" if result.thesis_result_state == "favorable" else "#fb7185" if result.thesis_result_state == "adverse" else "#facc15",
            ),
        ]

        output_path = self.settings.temp_chart_dir / f"{uuid4().hex}.png"
        fig, axes = mpf.plot(
            chart_frame,
            type="candle",
            style=self.style,
            addplot=addplots,
            panel_ratios=(7, 3),
            volume=False,
            tight_layout=True,
            xrotation=0,
            datetime_format="%m-%d\n%H:%M",
            returnfig=True,
            figsize=(14, 8),
            title=f"{display_symbol} - {signal.timeframe} {label}",
        )

        price_ax = axes[0]
        rsi_ax = axes[-1]
        is_favorable = result.thesis_result_state == "favorable"
        move_color = "#4ade80" if is_favorable else "#fb7185" if result.thesis_result_state == "adverse" else "#facc15"
        move_text = (
            f"Favorable {format_percent(result.favorable_move_pct)}"
            if is_favorable
            else f"Adverse {format_percent(result.adverse_move_pct)}"
            if result.thesis_result_state == "adverse"
            else f"Raw move {format_percent(result.move_pct)}"
        )
        if signal.direction in {"oversold", "long"}:
            outcome_label = "Bounce" if signal.direction == "oversold" else "Long"
        else:
            outcome_label = "Fade" if signal.direction == "overbought" else "Short"
        alert_timeframe = str(signal.metadata.get("origin_timeframe") or signal.timeframe)
        current_timeframe = signal.timeframe
        rsi_transition = (
            f"Alert {alert_timeframe} RSI {format_rsi(signal.rsi)} -> Current {current_timeframe} RSI {format_rsi(result.current_rsi)}"
            if alert_timeframe != current_timeframe
            else f"RSI {format_rsi(signal.rsi)} -> {format_rsi(result.current_rsi)}"
        )
        proof_box = (
            f"{result.stage} {outcome_label}\n"
            f"Entry {format_price(signal.price)}\n"
            f"Now {format_price(result.current_price)}\n"
            f"{move_text}\n"
            f"State {result.thesis_result_state.title()}"
        )
        header = (
            f"{signal.direction.title()} setup | Score {signal.score}/100 | "
            f"{rsi_transition}"
        )

        self._draw_signal_level(
            price_ax,
            signal_x=signal_x,
            signal_price=signal_price,
            color="#ffd166",
            label="Entry",
        )
        self._draw_signal_hint(price_ax)
        price_ax.text(
            0.012,
            0.965,
            header,
            transform=price_ax.transAxes,
            ha="left",
            va="top",
            fontsize=10,
            color="#eef5fb",
            bbox={"facecolor": "#112033", "alpha": 0.84, "edgecolor": "#24405b", "boxstyle": "round,pad=0.35"},
        )
        price_ax.text(
            0.988,
            0.965,
            proof_box,
            transform=price_ax.transAxes,
            ha="right",
            va="top",
            fontsize=10,
            color="#eef5fb",
            bbox={
                "facecolor": "#15331d" if result.thesis_result_state == "favorable" else "#3b1620" if result.thesis_result_state == "adverse" else "#3b3416",
                "alpha": 0.86,
                "edgecolor": move_color,
                "boxstyle": "round,pad=0.35",
            },
        )
        rsi_ax.text(
            0.988,
            0.88,
            f"Closed RSI {format_rsi(result.current_rsi)}",
            transform=rsi_ax.transAxes,
            ha="right",
            va="top",
            fontsize=10,
            color="#eef5fb",
            bbox={"facecolor": "#13273c", "alpha": 0.85, "edgecolor": "#2f587f", "boxstyle": "round,pad=0.30"},
        )
        rsi_ax.set_ylim(0, 100)

        fig.savefig(output_path, dpi=170, bbox_inches="tight", facecolor="#09131f")
        plt.close(fig)
        return output_path

    def cleanup(self, chart_path: Path | None) -> None:
        if chart_path and chart_path.exists():
            chart_path.unlink(missing_ok=True)

    def _resolve_marker_index(self, index: pd.Index, target_time) -> pd.Timestamp:
        if not isinstance(index, pd.DatetimeIndex):
            return index[-1]
        if len(index) == 0:
            raise ValueError("Cannot place marker on an empty chart")

        target_ts = pd.Timestamp(target_time)
        if target_ts.tzinfo is None and index.tz is not None:
            target_ts = target_ts.tz_localize(index.tz)
        elif target_ts.tzinfo is not None and index.tz is None:
            target_ts = target_ts.tz_convert("UTC").tz_localize(None)
        elif target_ts.tzinfo is not None and index.tz is not None:
            target_ts = target_ts.tz_convert(index.tz)

        if target_ts in index:
            LOGGER.debug("Timeframe remap success target=%s exact_match=true", target_ts.isoformat())
            return target_ts

        if target_ts < index[0]:
            resolved = index[0]
            LOGGER.debug(
                "Timeframe remap clipped target=%s before frame start=%s; using first visible candle=%s",
                target_ts.isoformat(),
                index[0].isoformat(),
                resolved.isoformat(),
            )
            return resolved
        if target_ts > index[-1]:
            resolved = index[-1]
            LOGGER.debug(
                "Timeframe remap clipped target=%s after frame end=%s; using last visible candle=%s",
                target_ts.isoformat(),
                index[-1].isoformat(),
                resolved.isoformat(),
            )
            return resolved

        insertion_point = index.searchsorted(target_ts, side="right") - 1
        insertion_point = max(0, min(insertion_point, len(index) - 1))
        resolved = index[insertion_point]
        LOGGER.debug(
            "Timeframe remap success target=%s resolved=%s exact_match=false",
            target_ts.isoformat(),
            resolved.isoformat(),
        )
        return resolved

    def _render_chart(
        self,
        frame: pd.DataFrame,
        *,
        title: str,
        subtitle: str,
        last_price: float,
        last_rsi: float,
        marker_time=None,
        marker_price: float | None = None,
    ) -> Path:
        chart_frame = self._select_chart_frame(frame, marker_time=marker_time)
        if "rsi" not in chart_frame.columns:
            raise ValueError("Chart frame must include an 'rsi' column")

        addplots = [
            mpf.make_addplot(chart_frame["rsi"], panel=1, color="#71ddff", width=1.15, ylabel="RSI"),
            mpf.make_addplot(pd.Series(70, index=chart_frame.index), panel=1, color="#ffb86c", linestyle="--"),
            mpf.make_addplot(pd.Series(30, index=chart_frame.index), panel=1, color="#4ade80", linestyle="--"),
        ]
        signal_index = None
        signal_x = None
        if marker_time is not None and marker_price is not None:
            signal_index = self._resolve_marker_index(chart_frame.index, marker_time)
            signal_x = self._resolve_plot_x(chart_frame.index, signal_index)

        output_path = self.settings.temp_chart_dir / f"{uuid4().hex}.png"
        fig, axes = mpf.plot(
            chart_frame,
            type="candle",
            style=self.style,
            addplot=addplots,
            panel_ratios=(7, 3),
            volume=False,
            tight_layout=True,
            xrotation=0,
            datetime_format="%m-%d\n%H:%M",
            returnfig=True,
            figsize=(14, 8),
            title=title,
        )

        price_ax = axes[0]
        rsi_ax = axes[-1]

        if signal_x is not None and marker_price is not None:
            self._draw_signal_level(
                price_ax,
                signal_x=signal_x,
                signal_price=float(marker_price),
                color="#ffd166",
                label="Entry",
                show_hline=True,
            )
            self._draw_signal_hint(price_ax)
        else:
            price_ax.axhline(last_price, color="#9ae6b4", linestyle=":", linewidth=0.8, alpha=0.85)
        price_ax.text(
            0.012,
            0.965,
            subtitle,
            transform=price_ax.transAxes,
            ha="left",
            va="top",
            fontsize=10,
            color="#eef5fb",
            bbox={"facecolor": "#112033", "alpha": 0.8, "edgecolor": "#24405b", "boxstyle": "round,pad=0.35"},
        )
        price_ax.text(
            0.988,
            0.965,
            f"Last Price\n{format_price(last_price)}",
            transform=price_ax.transAxes,
            ha="right",
            va="top",
            fontsize=10,
            color="#eef5fb",
            bbox={"facecolor": "#15331d", "alpha": 0.82, "edgecolor": "#2f6b3b", "boxstyle": "round,pad=0.35"},
        )
        rsi_ax.text(
            0.988,
            0.88,
            f"RSI {format_rsi(last_rsi)}",
            transform=rsi_ax.transAxes,
            ha="right",
            va="top",
            fontsize=10,
            color="#eef5fb",
            bbox={"facecolor": "#13273c", "alpha": 0.85, "edgecolor": "#2f587f", "boxstyle": "round,pad=0.30"},
        )
        rsi_ax.set_ylim(0, 100)

        fig.savefig(output_path, dpi=160, bbox_inches="tight", facecolor="#09131f")
        plt.close(fig)
        return output_path

    def _select_chart_frame(self, frame: pd.DataFrame, *, marker_time=None) -> pd.DataFrame:
        if len(frame) <= self.settings.klines_limit or marker_time is None:
            return frame.tail(self.settings.klines_limit).copy()

        marker_index = self._resolve_marker_index(frame.index, marker_time)
        marker_loc = frame.index.get_loc(marker_index)
        if not isinstance(marker_loc, int):
            marker_loc = max(0, len(frame) - self.settings.klines_limit)

        bars_after_marker = len(frame) - marker_loc
        required_window = max(self.settings.klines_limit, bars_after_marker + 12)
        required_window = min(required_window, len(frame))
        return frame.tail(required_window).copy()

    def _resolve_plot_x(self, index: pd.Index, resolved_marker) -> float:
        if len(index) == 0:
            raise ValueError("Cannot place marker on an empty chart")

        loc = index.get_loc(resolved_marker)
        if isinstance(loc, slice):
            return float(loc.start)
        if isinstance(loc, Integral):
            return float(loc)
        if hasattr(loc, "tolist"):
            loc = loc.tolist()
        if isinstance(loc, list):
            if loc and isinstance(loc[0], bool):
                first_true = next((idx for idx, matched in enumerate(loc) if matched), None)
                if first_true is None:
                    raise ValueError("Resolved marker is not visible on the chart")
                return float(first_true)
            if loc:
                return float(loc[0])
        return float(loc)

    def _draw_signal_level(
        self,
        price_ax,
        *,
        signal_x: float,
        signal_price: float,
        color: str,
        label: str,
        show_hline: bool = True,
    ) -> None:
        if show_hline:
            price_ax.axhline(
                signal_price,
                color=color,
                linestyle=(0, (3, 4)),
                linewidth=0.8,
                alpha=0.58,
            )
        y_min, y_max = price_ax.get_ylim()
        y_span = max(y_max - y_min, abs(signal_price) * 0.02, 1e-12)
        safe_top = y_max - (y_span * 0.11)
        safe_bottom = y_min + (y_span * 0.08)
        visible_boundary = min(max(signal_price, y_min), y_max)
        marker_y = min(max(signal_price, safe_bottom), safe_top)
        marker_was_clipped = abs(marker_y - signal_price) > (y_span * 0.002)

        if marker_was_clipped:
            LOGGER.info(
                "Signal marker clipped into visible chart area target_price=%s marker_y=%s visible_range=(%s, %s)",
                signal_price,
                marker_y,
                y_min,
                y_max,
            )
            price_ax.plot(
                [signal_x, signal_x],
                [marker_y, visible_boundary],
                linestyle=(0, (2, 3)),
                linewidth=0.8,
                color=color,
                alpha=0.62,
                zorder=6,
            )
        price_ax.scatter(
            [signal_x],
            [marker_y],
            s=118,
            marker="^",
            color=color,
            edgecolors="#f4f8fc",
            linewidths=0.7,
            zorder=7,
            clip_on=False,
        )
        label_offset = -11
        vertical_align = "top"
        if marker_y <= safe_bottom + (y_span * 0.02):
            label_offset = 11
            vertical_align = "bottom"
        elif marker_y >= safe_top - (y_span * 0.02):
            label_offset = 11
            vertical_align = "bottom"
        price_ax.annotate(
            label,
            xy=(signal_x, marker_y),
            xytext=(0, label_offset),
            textcoords="offset points",
            ha="center",
            va=vertical_align,
            fontsize=7.2,
            color="#f9d57a",
            zorder=8,
            bbox={
                "facecolor": "#0d1825",
                "alpha": 0.92,
                "edgecolor": color,
                "linewidth": 0.8,
                "boxstyle": "round,pad=0.18",
            },
            annotation_clip=False,
        )

    def _draw_signal_hint(self, price_ax) -> None:
        price_ax.text(
            0.012,
            0.905,
            "Entry candle",
            transform=price_ax.transAxes,
            ha="left",
            va="top",
            fontsize=8.0,
            color="#f7d780",
            bbox={
                "facecolor": "#0d1825",
                "alpha": 0.9,
                "edgecolor": "#9b7a22",
                "boxstyle": "round,pad=0.22",
            },
        )
        return
