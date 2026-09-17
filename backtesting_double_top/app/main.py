from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from app.data_loader import enrich_indicators, iter_symbol_frames, open_read_only_connection
from app.metrics import (
    build_bucket_summary,
    build_overall_snapshot,
    build_scenario_summary,
    build_symbol_summary,
    build_time_breakdown,
)
from app.pattern_detector import detect_double_top_patterns
from app.strategy import build_trade_rows
from app.utils import (
    EXPORTS_DIR,
    REPORTS_DIR,
    ensure_output_dirs,
    get_logger,
    interval_to_minutes,
    load_config,
    scenario_objects,
    utc_now_iso,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autonomous double top short backtest")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    return parser.parse_args()


def write_markdown_summary(path: Path, snapshot: dict, scenario_summary: pd.DataFrame) -> None:
    if scenario_summary.empty:
        summary_block = "_No data_"
    else:
        summary_block = "```text\n" + scenario_summary.to_string(index=False) + "\n```"
    lines = [
        "# Double Top Short Backtest",
        "",
        f"- Generated at: `{utc_now_iso()}`",
        f"- Patterns found: `{snapshot['patterns_found']}`",
        f"- Trades opened: `{snapshot['trades_opened']}`",
        f"- Resolved trades: `{snapshot['resolved_trades']}`",
        f"- Win rate: `{snapshot['win_rate_pct']:.2f}%`",
        f"- OPEN count: `{snapshot['open_count']}`",
        f"- AMBIGUOUS count: `{snapshot['ambiguous_count']}`",
        "",
        "## Scenario summary",
        "",
        summary_block,
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_backtest(config_path: str) -> None:
    config = load_config(config_path)
    logger = get_logger()
    ensure_output_dirs()
    logger.info("Starting autonomous double top backtest...")
    sqlite_path = config["data_source"]["sqlite_path"]
    logger.info("Read-only data source: %s", sqlite_path)
    connection = open_read_only_connection(sqlite_path)

    all_patterns: list[pd.DataFrame] = []
    all_trades: list[dict] = []
    scenarios = scenario_objects(config)
    interval_minutes = interval_to_minutes(str(config["data_source"]["interval"]))
    processed_symbols = 0

    try:
        for metadata, raw_frame in iter_symbol_frames(config, connection):
            if len(raw_frame) < int(config["data_source"]["min_rows_per_symbol"]):
                continue
            processed_symbols += 1
            symbol = str(metadata["symbol"])
            logger.info("Processing %s (%s candles)", symbol, len(raw_frame))
            enriched = enrich_indicators(raw_frame, interval=str(config["data_source"]["interval"]), rsi_length=14)
            patterns = detect_double_top_patterns(enriched, config)
            if patterns.empty:
                continue
            all_patterns.append(patterns)
            for scenario in scenarios:
                all_trades.extend(
                    build_trade_rows(
                        frame=enriched,
                        symbol_metadata=metadata,
                        patterns=patterns,
                        scenario_name=scenario.name,
                        stop_pct=scenario.stop_pct,
                        take_pct=scenario.take_pct,
                        config=config,
                        interval_minutes=interval_minutes,
                    )
                )
    finally:
        connection.close()

    patterns_frame = pd.concat(all_patterns, ignore_index=True) if all_patterns else pd.DataFrame()
    trades_frame = pd.DataFrame(all_trades)

    scenario_summary = build_scenario_summary(trades_frame, patterns_frame)
    symbol_summary = build_symbol_summary(trades_frame)
    month_summary = build_time_breakdown(trades_frame, "entry_month")
    week_summary = build_time_breakdown(trades_frame, "entry_week")
    rsi_bucket_summary = build_bucket_summary(trades_frame, "rsi_bucket")
    atr_bucket_summary = build_bucket_summary(trades_frame, "atr_bucket")
    volume_bucket_summary = build_bucket_summary(trades_frame, "volume_bucket")
    liquidity_bucket_summary = build_bucket_summary(trades_frame, "liquidity_bucket")
    snapshot = build_overall_snapshot(trades_frame, patterns_frame)

    encoding = config["export"].get("export_encoding", "utf-8-sig")
    if config["export"].get("write_patterns_csv", True):
        patterns_frame.to_csv(EXPORTS_DIR / "patterns.csv", index=False, encoding=encoding)
    if config["export"].get("write_trades_csv", True):
        trades_frame.to_csv(EXPORTS_DIR / "trades.csv", index=False, encoding=encoding)
    scenario_summary.to_csv(EXPORTS_DIR / "scenario_summary.csv", index=False, encoding=encoding)
    symbol_summary.to_csv(EXPORTS_DIR / "symbol_summary.csv", index=False, encoding=encoding)
    month_summary.to_csv(EXPORTS_DIR / "month_summary.csv", index=False, encoding=encoding)
    week_summary.to_csv(EXPORTS_DIR / "week_summary.csv", index=False, encoding=encoding)
    rsi_bucket_summary.to_csv(EXPORTS_DIR / "rsi_bucket_summary.csv", index=False, encoding=encoding)
    atr_bucket_summary.to_csv(EXPORTS_DIR / "atr_bucket_summary.csv", index=False, encoding=encoding)
    volume_bucket_summary.to_csv(EXPORTS_DIR / "volume_bucket_summary.csv", index=False, encoding=encoding)
    liquidity_bucket_summary.to_csv(EXPORTS_DIR / "liquidity_bucket_summary.csv", index=False, encoding=encoding)
    (REPORTS_DIR / "run_metadata.json").write_text(
        json.dumps(
            {
                "generated_at_utc": utc_now_iso(),
                "config_path": config["__config_path__"],
                "sqlite_path": sqlite_path,
                "symbols_processed": processed_symbols,
                "patterns_found": int(len(patterns_frame)),
                "trades_opened": int(len(trades_frame)),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if config["export"].get("write_summary_markdown", True):
        write_markdown_summary(REPORTS_DIR / "summary.md", snapshot, scenario_summary)

    logger.info("Done. Symbols processed: %s", processed_symbols)
    logger.info("Patterns found: %s", snapshot["patterns_found"])
    logger.info("Trades opened: %s", snapshot["trades_opened"])
    logger.info("Exports: %s", EXPORTS_DIR)


def main() -> int:
    args = parse_args()
    try:
        run_backtest(args.config)
        return 0
    except Exception as exc:  # pragma: no cover
        get_logger().exception("Backtest failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
