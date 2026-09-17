from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


MODULE_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = MODULE_ROOT / "output"
REPORTS_DIR = OUTPUT_ROOT / "reports"
CHARTS_DIR = OUTPUT_ROOT / "charts"
EXPORTS_DIR = OUTPUT_ROOT / "exports"


@dataclass(frozen=True)
class Scenario:
    name: str
    stop_pct: float
    take_pct: float


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")


def get_logger(name: str = "double_top_backtest") -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)


def ensure_output_dirs() -> None:
    for path in (OUTPUT_ROOT, REPORTS_DIR, CHARTS_DIR, EXPORTS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def resolve_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (MODULE_ROOT / path).resolve()


def load_config(config_path: str | Path) -> dict[str, Any]:
    path = resolve_path(config_path)
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    config["__config_path__"] = str(path)
    config["__config_dir__"] = str(path.parent)
    sqlite_path = config.get("data_source", {}).get("sqlite_path")
    if sqlite_path:
        config["data_source"]["sqlite_path"] = str(resolve_path(Path(path.parent) / sqlite_path))
    return config


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def interval_to_minutes(interval: str) -> int:
    value = interval.strip().lower()
    if value.endswith("m"):
        return int(value[:-1])
    if value.endswith("h"):
        return int(value[:-1]) * 60
    if value.endswith("d"):
        return int(value[:-1]) * 24 * 60
    raise ValueError(f"Unsupported interval: {interval}")


def format_pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):.2f}%"


def liquidity_bucket(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "No data"
    if value < 1_000_000:
        return "<1M"
    if value < 5_000_000:
        return "1M-5M"
    if value < 20_000_000:
        return "5M-20M"
    if value < 50_000_000:
        return "20M-50M"
    return "50M+"


def volume_ratio_bucket(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "No data"
    if value < 1.0:
        return "<1.0"
    if value < 1.5:
        return "1.0-1.49"
    if value < 2.0:
        return "1.5-1.99"
    if value < 3.0:
        return "2.0-2.99"
    return "3.0+"


def atr_bucket(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "No data"
    if value < 0.8:
        return "<0.8%"
    if value < 1.2:
        return "0.8-1.19%"
    if value < 1.8:
        return "1.2-1.79%"
    if value < 2.5:
        return "1.8-2.49%"
    return "2.5%+"


def short_rsi_bucket(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "No data"
    if value >= 80.0:
        return "80+"
    if value >= 76.0:
        return "76-79.99"
    if value >= 73.0:
        return "73-75.99"
    if value >= 70.0:
        return "70-72.99"
    if value >= 67.0:
        return "67-69.99"
    return "<67"


def safe_pct_diff(a: float, b: float) -> float:
    base = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / base * 100.0


def scenario_objects(config: dict[str, Any]) -> list[Scenario]:
    scenarios: list[Scenario] = []
    for raw in config.get("strategy", {}).get("scenarios", []):
        scenarios.append(
            Scenario(
                name=str(raw["name"]),
                stop_pct=float(raw["stop_pct"]),
                take_pct=float(raw["take_pct"]),
            )
        )
    return scenarios
