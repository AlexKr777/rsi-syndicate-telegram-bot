from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from app.data_loader import enrich_indicators, iter_symbol_frames, open_read_only_connection
from app.execution_engine import build_trades_for_strategy
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
from app.strategy_registry import enabled_strategies
from app.utils import EXPORTS_DIR, REPORTS_DIR, ensure_output_dirs, get_logger, interval_to_minutes, load_config, parse_scenarios, utc_now_iso


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autonomous multi-strategy research lab")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--max-symbols", type=int, default=None, help="Optional testing override")
    return parser.parse_args()


def write_markdown_summary(path: Path, snapshot: dict, strategy_summary: pd.DataFrame, strategy_scenario_summary: pd.DataFrame) -> None:
    strategy_block = "_No strategy data_"
    scenario_block = "_No scenario data_"
    if not strategy_summary.empty:
        strategy_block = "```text\n" + strategy_summary.head(10).to_string(index=False) + "\n```"
    if not strategy_scenario_summary.empty:
        scenario_block = "```text\n" + strategy_scenario_summary.head(15).to_string(index=False) + "\n```"
    lines = [
        "# Strategy Research Lab",
        "",
        f"- Generated at: `{utc_now_iso()}`",
        f"- Total trades: `{snapshot['total_trades']}`",
        f"- Total net pnl: `${snapshot['total_net_pnl_usd']:,.2f}`",
        f"- Final balance: `${snapshot['final_balance_usd']:,.2f}`",
        f"- Best strategy: `{snapshot['best_strategy']}`",
        f"- Best scenario: `{snapshot['best_scenario']}`",
        f"- Best symbol: `{snapshot['best_symbol']}`",
        f"- Win rate: `{snapshot['win_rate_pct']:.2f}%`",
        f"- Max drawdown: `${snapshot['max_drawdown_usd']:,.2f}` / `{snapshot['max_drawdown_pct']:.2f}%`",
        "",
        "## Strategy summary",
        "",
        strategy_block,
        "",
        "## Strategy x Scenario summary",
        "",
        scenario_block,
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_backtests(config_path: str, max_symbols: int | None = None) -> None:
    config = load_config(config_path)
    if max_symbols is not None:
        config["data_source"]["max_symbols"] = max_symbols
    ensure_output_dirs()
    logger = get_logger()
    logger.info("Starting Strategy Research Lab...")
    logger.info("Read-only data source: %s", config["data_source"]["sqlite_path"])

    scenarios = parse_scenarios(config)
    selected_strategies = enabled_strategies(config)
    interval_minutes = interval_to_minutes(str(config["data_source"]["interval"]))
    starting_capital = float(config["money_model"]["starting_capital_usd"])

    all_signals: list[pd.DataFrame] = []
    all_trades: list[dict] = []
    symbols_processed = 0
    strategy_signal_counts: dict[str, int] = {name: 0 for name, _ in selected_strategies}
    strategy_trade_counts: dict[str, int] = {name: 0 for name, _ in selected_strategies}

    connection = open_read_only_connection(config["data_source"]["sqlite_path"])
    try:
        for metadata, raw_frame in iter_symbol_frames(config, connection):
            if len(raw_frame) < int(config["data_source"]["min_rows_per_symbol"]):
                continue
            symbols_processed += 1
            symbol = str(metadata["symbol"])
            logger.info("Processing %s (%s candles)", symbol, len(raw_frame))
            enriched = enrich_indicators(raw_frame, interval=str(config["data_source"]["interval"]), rsi_length=14)
            for strategy_name, module in selected_strategies:
                try:
                    signals = module.generate_signals(enriched, metadata, config)
                except Exception as exc:
                    logger.exception("Strategy %s failed on %s: %s", strategy_name, symbol, exc)
                    continue
                if signals.empty:
                    continue
                strategy_signal_counts[strategy_name] += len(signals)
                all_signals.append(signals)
                strategy_trades = build_trades_for_strategy(
                    strategy_name=strategy_name,
                    frame=enriched,
                    metadata=metadata,
                    signals=signals,
                    scenarios=scenarios,
                    config=config,
                    interval_minutes=interval_minutes,
                )
                strategy_trade_counts[strategy_name] += len(strategy_trades)
                all_trades.extend(strategy_trades)
    finally:
        connection.close()

    signals_frame = pd.concat(all_signals, ignore_index=True) if all_signals else pd.DataFrame()
    trades_frame = pd.DataFrame(all_trades)
    prepared_trades = prepare_trades_frame(trades_frame, starting_capital) if not trades_frame.empty else trades_frame

    strategy_summary = build_strategy_summary(trades_frame, starting_capital)
    scenario_summary = build_scenario_summary(trades_frame, starting_capital)
    strategy_scenario_summary = build_strategy_scenario_summary(trades_frame, starting_capital)
    symbol_summary = build_symbol_summary(trades_frame, starting_capital)
    month_summary = build_time_summary(trades_frame, "entry_month", starting_capital)
    week_summary = build_time_summary(trades_frame, "entry_week", starting_capital)
    rsi_bucket_summary = build_bucket_summary(trades_frame, "rsi_bucket_at_entry", starting_capital)
    atr_bucket_summary = build_bucket_summary(trades_frame, "atr_bucket_at_entry", starting_capital)
    volume_bucket_summary = build_bucket_summary(trades_frame, "volume_bucket_at_entry", starting_capital)
    liquidity_bucket_summary = build_bucket_summary(trades_frame, "liquidity_bucket_at_entry", starting_capital)
    score_bucket_summary = build_bucket_summary(trades_frame, "score_bucket_at_entry", starting_capital)
    snapshot = build_overall_snapshot(trades_frame, starting_capital)

    encoding = config["export"].get("export_encoding", "utf-8-sig")
    if config["export"].get("write_signals_csv", True):
        signals_frame.to_csv(EXPORTS_DIR / "signals.csv", index=False, encoding=encoding)
    if config["export"].get("write_trades_csv", True):
        prepared_trades.to_csv(EXPORTS_DIR / "trades.csv", index=False, encoding=encoding)
    strategy_summary.to_csv(EXPORTS_DIR / "strategy_summary.csv", index=False, encoding=encoding)
    scenario_summary.to_csv(EXPORTS_DIR / "scenario_summary.csv", index=False, encoding=encoding)
    strategy_scenario_summary.to_csv(EXPORTS_DIR / "strategy_scenario_summary.csv", index=False, encoding=encoding)
    symbol_summary.to_csv(EXPORTS_DIR / "symbol_summary.csv", index=False, encoding=encoding)
    month_summary.to_csv(EXPORTS_DIR / "month_summary.csv", index=False, encoding=encoding)
    week_summary.to_csv(EXPORTS_DIR / "week_summary.csv", index=False, encoding=encoding)
    rsi_bucket_summary.to_csv(EXPORTS_DIR / "rsi_bucket_summary.csv", index=False, encoding=encoding)
    atr_bucket_summary.to_csv(EXPORTS_DIR / "atr_bucket_summary.csv", index=False, encoding=encoding)
    volume_bucket_summary.to_csv(EXPORTS_DIR / "volume_bucket_summary.csv", index=False, encoding=encoding)
    liquidity_bucket_summary.to_csv(EXPORTS_DIR / "liquidity_bucket_summary.csv", index=False, encoding=encoding)
    score_bucket_summary.to_csv(EXPORTS_DIR / "score_bucket_summary.csv", index=False, encoding=encoding)
    (REPORTS_DIR / "run_metadata.json").write_text(
        json.dumps(
            {
                "generated_at_utc": utc_now_iso(),
                "config_path": config["__config_path__"],
                "sqlite_path": config["data_source"]["sqlite_path"],
                "symbols_processed": symbols_processed,
                "enabled_strategies": [name for name, _ in selected_strategies],
                "strategy_signal_counts": strategy_signal_counts,
                "strategy_trade_counts": strategy_trade_counts,
                "total_trades": snapshot["total_trades"],
                "total_net_pnl_usd": snapshot["total_net_pnl_usd"],
                "final_balance_usd": snapshot["final_balance_usd"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if config["export"].get("write_summary_markdown", True):
        write_markdown_summary(REPORTS_DIR / "summary.md", snapshot, strategy_summary, strategy_scenario_summary)

    logger.info("Done. Symbols processed: %s", symbols_processed)
    logger.info("Signals: %s", len(signals_frame))
    logger.info("Trades: %s", len(prepared_trades))
    logger.info("Net PnL: $%s", f"{snapshot['total_net_pnl_usd']:,.2f}")
    logger.info("Exports: %s", EXPORTS_DIR)


def main() -> int:
    args = parse_args()
    try:
        run_backtests(args.config, max_symbols=args.max_symbols)
        return 0
    except Exception as exc:  # pragma: no cover
        get_logger().exception("Strategy Research Lab failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
