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
CACHE_DIR = OUTPUT_ROOT / "cache"


@dataclass(frozen=True)
class ScenarioDefinition:
    name: str
    mode: str
    stop_pct: float | None = None
    take_pct: float | None = None
    stop_atr_multiple: float | None = None
    take_r_multiple: float | None = None
    atr_buffer: float | None = None
    fallback_take_r_multiple: float | None = None


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")


def get_logger(name: str = "strategy_research_lab") -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)


def ensure_output_dirs() -> None:
    for path in (OUTPUT_ROOT, REPORTS_DIR, CHARTS_DIR, EXPORTS_DIR, CACHE_DIR):
        path.mkdir(parents=True, exist_ok=True)


def resolve_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (MODULE_ROOT / path).resolve()


def resolve_config_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    cwd_candidate = Path.cwd() / path
    if cwd_candidate.exists():
        return cwd_candidate.resolve()
    return resolve_path(path)


def load_config(config_path: str | Path) -> dict[str, Any]:
    path = resolve_config_path(config_path)
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


def safe_pct_diff(a: float, b: float) -> float:
    base = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / base * 100.0


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


def score_bucket(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "No data"
    if value < 40:
        return "<40"
    if value < 60:
        return "40-59"
    if value < 80:
        return "60-79"
    if value < 90:
        return "80-89"
    return "90+"


def rsi_bucket(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "No data"
    if value < 25:
        return "<25"
    if value < 30:
        return "25-29.99"
    if value < 40:
        return "30-39.99"
    if value < 50:
        return "40-49.99"
    if value < 60:
        return "50-59.99"
    if value < 70:
        return "60-69.99"
    if value < 80:
        return "70-79.99"
    return "80+"


def parse_scenarios(config: dict[str, Any]) -> dict[str, ScenarioDefinition]:
    scenarios: dict[str, ScenarioDefinition] = {}
    for raw in config.get("scenarios", []):
        scenario = ScenarioDefinition(
            name=str(raw["name"]),
            mode=str(raw["mode"]),
            stop_pct=float(raw["stop_pct"]) if raw.get("stop_pct") is not None else None,
            take_pct=float(raw["take_pct"]) if raw.get("take_pct") is not None else None,
            stop_atr_multiple=float(raw["stop_atr_multiple"]) if raw.get("stop_atr_multiple") is not None else None,
            take_r_multiple=float(raw["take_r_multiple"]) if raw.get("take_r_multiple") is not None else None,
            atr_buffer=float(raw["atr_buffer"]) if raw.get("atr_buffer") is not None else None,
            fallback_take_r_multiple=float(raw["fallback_take_r_multiple"]) if raw.get("fallback_take_r_multiple") is not None else None,
        )
        scenarios[scenario.name] = scenario
    return scenarios


def detect_pivot_highs(frame: pd.DataFrame, left: int, right: int) -> list[int]:
    highs = frame["high"].tolist()
    indices: list[int] = []
    for idx in range(left, len(highs) - right):
        current = highs[idx]
        if current >= max(highs[idx - left : idx]) and current > max(highs[idx + 1 : idx + 1 + right]):
            indices.append(idx)
    return indices


def detect_pivot_lows(frame: pd.DataFrame, left: int, right: int) -> list[int]:
    lows = frame["low"].tolist()
    indices: list[int] = []
    for idx in range(left, len(lows) - right):
        current = lows[idx]
        if current <= min(lows[idx - left : idx]) and current < min(lows[idx + 1 : idx + 1 + right]):
            indices.append(idx)
    return indices


def realized_side_return_pct(side: str, entry_price: float, exit_price: float) -> float:
    if side == "LONG":
        return (exit_price - entry_price) / entry_price * 100.0
    return (entry_price - exit_price) / entry_price * 100.0
