from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import sqlite3
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import warnings
import zipfile
from collections import deque
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any

try:
    import numpy as np
    import pandas as pd
except ImportError:
    print(
        "This module needs pandas (and numpy, which comes with pandas).\n"
        "Use the project's .venv via test2\\run_futures_research.bat or install:\n"
        "  pip install -r test2\\requirements.txt"
    )
    raise


warnings.filterwarnings("ignore", message="Mean of empty slice", category=RuntimeWarning)


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
CACHE_DB_PATH = DATA_DIR / "futures_research_cache.sqlite"

BINANCE_FAPI_BASE_URL = "https://fapi.binance.com"
BINANCE_DATA_VISION_BASE_URL = "https://data.binance.vision"
EXCHANGE_INFO_PATH = "/fapi/v1/exchangeInfo"
KLINES_PATH = "/fapi/v1/klines"
HTTP_TIMEOUT_SECONDS = 30
HTTP_RETRIES = 5
HTTP_RETRY_BASE_SLEEP = 1.5
HTTP_REQUEST_PAUSE_SECONDS = 0.0
KLINES_LIMIT = 499
DEFAULT_REQUEST_WEIGHT_LIMIT_PER_MINUTE = 2400
REQUEST_WEIGHT_HEADROOM_RATIO = 0.92
DEFAULT_ROUTE_WEIGHT = 1

DEFAULT_INTERVAL = "15m"
DEFAULT_LOOKBACK_DAYS = 90
DEFAULT_HORIZON_HOURS = 8
DEFAULT_RSI_LENGTH = 14
DEFAULT_MAIN_SCENARIO = "tp5_sl5"
DEFAULT_MAX_REPORT_ROWS = 5
DEFAULT_MIN_GROUP_SAMPLE = 40
DEFAULT_MIN_COMBO_SAMPLE = 25
DEFAULT_CACHE_COMPLETENESS = 0.985

OVERBOUGHT_THRESHOLDS = [67.0, 70.0, 73.0, 76.0, 80.0]
OVERSOLD_THRESHOLDS = [33.0, 30.0, 28.0, 25.0, 20.0]


@dataclass(frozen=True)
class Scenario:
    name: str
    label: str
    take_pct: float
    stop_pct: float


class BinanceRequestLimiter:
    def __init__(
        self,
        *,
        request_weight_limit_per_minute: int,
        headroom_ratio: float,
        min_pause_seconds: float,
    ) -> None:
        self.hard_limit = max(1, int(request_weight_limit_per_minute))
        self.headroom_ratio = min(max(headroom_ratio, 0.1), 1.0)
        self.target_limit = max(1, int(self.hard_limit * self.headroom_ratio))
        self.min_pause_seconds = max(0.0, float(min_pause_seconds))
        self.window_seconds = 60.0
        self.events: deque[tuple[float, int]] = deque()
        self.window_weight = 0
        self.last_request_at = 0.0

    def update_limit(self, request_weight_limit_per_minute: int) -> None:
        self.hard_limit = max(1, int(request_weight_limit_per_minute))
        self.target_limit = max(1, int(self.hard_limit * self.headroom_ratio))

    def _prune(self, now_monotonic: float) -> None:
        while self.events and now_monotonic - self.events[0][0] >= self.window_seconds:
            _, weight = self.events.popleft()
            self.window_weight -= weight

    def acquire(self, request_weight: int) -> None:
        request_weight = max(1, int(request_weight))
        while True:
            now_monotonic = time.monotonic()
            self._prune(now_monotonic)

            pause_left = self.min_pause_seconds - (now_monotonic - self.last_request_at)
            if pause_left > 0:
                time.sleep(min(pause_left, 0.5))
                continue

            if self.window_weight + request_weight <= self.target_limit:
                self.events.append((now_monotonic, request_weight))
                self.window_weight += request_weight
                self.last_request_at = now_monotonic
                return

            sleep_for = max(0.05, self.window_seconds - (now_monotonic - self.events[0][0]) + 0.02)
            time.sleep(min(sleep_for, 2.0))

    def backoff(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))


SCENARIOS = [
    Scenario("tp5_sl5", "Тейк 5% / стоп 5%", 0.05, 0.05),
    Scenario("tp10_sl10", "Тейк 10% / стоп 10%", 0.10, 0.10),
    Scenario("tp10_sl5", "Тейк 10% / стоп 5%", 0.10, 0.05),
    Scenario("tp5_sl10", "Тейк 5% / стоп 10%", 0.05, 0.10),
]
SCENARIO_MAP = {scenario.name: scenario for scenario in SCENARIOS}

SCENARIO_COLUMNS = [
    "scenario_label",
    "signal_count",
    "take_count",
    "stop_count",
    "timeout_count",
    "take_rate_pct",
    "stop_rate_pct",
    "resolved_win_rate_pct",
    "edge_score",
]
FACTOR_COLUMNS = [
    "direction",
    "rsi_bucket",
    "liquidity_bucket",
    "volume_ratio_bucket",
    "score_bucket",
    "rejection_wick_bucket",
    "threshold_label",
    "signal_count",
    "take_rate_pct",
    "stop_rate_pct",
    "resolved_win_rate_pct",
    "avg_mfe_pct",
    "avg_mae_pct",
    "edge_score",
]
COMBO_COLUMNS = [
    "direction",
    "rsi_bucket",
    "liquidity_bucket",
    "score_bucket",
    "signal_count",
    "take_rate_pct",
    "stop_rate_pct",
    "resolved_win_rate_pct",
    "avg_mfe_pct",
    "avg_mae_pct",
    "edge_score",
]
OKAK_COLUMNS = [
    "scenario_label",
    "conditions_hit",
    "combo_label",
    "signal_count",
    "take_rate_pct",
    "stop_rate_pct",
    "resolved_win_rate_pct",
    "avg_mfe_pct",
    "avg_mae_pct",
    "edge_score",
]


CSS = """
:root{
  --bg:#f5f0e8;
  --panel:#fffaf2;
  --panel-strong:#fff6ea;
  --ink:#11243d;
  --muted:#5b6b7c;
  --line:#d4c4ae;
  --accent:#bb5f45;
  --accent-2:#0f6d7a;
  --accent-3:#d79b34;
  --good:#2d7d55;
  --bad:#b44e42;
  --warn:#d28b1f;
  --shadow:0 18px 45px rgba(23,33,51,.10);
}
*{box-sizing:border-box}
body{margin:0;font-family:"Segoe UI","Trebuchet MS",sans-serif;background:
radial-gradient(circle at top right, rgba(215,155,52,.18), transparent 24%),
radial-gradient(circle at left 20%, rgba(15,109,122,.12), transparent 26%),
linear-gradient(180deg, #fbf6ef 0%, #f2ecdf 100%);color:var(--ink)}
.page{max-width:1440px;margin:0 auto;padding:36px 24px 64px}
.hero,.section{background:rgba(255,250,242,.94);border:1px solid rgba(212,196,174,.78);border-radius:28px;box-shadow:var(--shadow);padding:28px}
.hero{position:relative;overflow:hidden}
.hero:before{content:"";position:absolute;inset:auto -60px -90px auto;width:240px;height:240px;background:radial-gradient(circle, rgba(187,95,69,.14), transparent 68%)}
.eyebrow{display:inline-block;margin-bottom:14px;padding:6px 12px;border-radius:999px;background:rgba(15,109,122,.10);color:var(--accent-2);font-size:13px;font-weight:700;letter-spacing:.04em;text-transform:uppercase}
h1{margin:0 0 12px;font-size:40px;line-height:1.05}
.lead{margin:0;max-width:960px;font-size:18px;line-height:1.55;color:var(--muted)}
.hero-grid,.chart-grid,.info-grid{display:grid;gap:16px}
.hero-grid{grid-template-columns:repeat(4,minmax(0,1fr));margin-top:24px}
.chart-grid{grid-template-columns:repeat(3,minmax(0,1fr))}
.info-grid{grid-template-columns:repeat(3,minmax(0,1fr))}
.kpi,.note,.chart-card{background:rgba(255,255,255,.72);border:1px solid rgba(212,196,174,.65);border-radius:22px;padding:18px}
.kpi .label{font-size:13px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.kpi .value{margin-top:8px;font-size:32px;line-height:1;font-weight:800}
.kpi .hint,.small,.chart-card .caption,p{color:var(--muted)}
.kpi .hint,.chart-card .caption,p,.bullet-list li{line-height:1.55}
.section{margin-top:26px}
.section h2{margin:0 0 10px;font-size:30px}
.section p{margin:0 0 18px}
.note h3,.chart-card h3{margin:0 0 10px}
.pill-row{display:flex;flex-wrap:wrap;gap:10px}
.pill{padding:9px 14px;border-radius:999px;background:rgba(15,109,122,.09);color:var(--accent-2);font-size:14px;font-weight:700}
.table-wrap{overflow-x:auto;border-radius:22px;border:1px solid rgba(212,196,174,.72);background:white}
table{width:100%;border-collapse:collapse;min-width:920px}
th,td{padding:13px 14px;border-bottom:1px solid rgba(212,196,174,.58);text-align:left;vertical-align:top;font-size:14px}
th{background:#eef3fb;color:var(--ink);font-size:13px;text-transform:uppercase;letter-spacing:.03em}
tr:nth-child(even) td{background:rgba(248,244,236,.55)}
.legend{margin-top:16px;display:grid;gap:10px}
.legend-item{display:flex;align-items:center;justify-content:space-between;gap:14px;font-size:14px}
.legend-left{display:flex;align-items:center;gap:10px}
.swatch{width:12px;height:12px;border-radius:999px;flex:0 0 12px}
.bullet-list{margin:0;padding-left:18px}
.footer{margin-top:26px;font-size:14px;color:var(--muted);text-align:center}
@media (max-width: 1100px){.hero-grid,.chart-grid,.info-grid{grid-template-columns:1fr 1fr}}
@media (max-width: 760px){.page{padding:18px 14px 40px}.hero,.section{padding:20px}h1{font-size:30px}.hero-grid,.chart-grid,.info-grid{grid-template-columns:1fr}}
"""


def log(message: str) -> None:
    timestamp = datetime.now(tz=UTC).astimezone().strftime("%H:%M:%S")
    line = f"[{timestamp}] {message}"
    try:
        print(line)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        safe_line = line.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(safe_line)


def format_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remainder = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes}m {remainder:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone Binance Futures RSI research")
    parser.add_argument("--days", type=int, default=DEFAULT_LOOKBACK_DAYS, help="How many days of history to study")
    parser.add_argument("--interval", default=DEFAULT_INTERVAL, help="Binance kline interval, default 15m")
    parser.add_argument("--horizon-hours", type=int, default=DEFAULT_HORIZON_HOURS, help="How long after signal to check TP/SL")
    parser.add_argument("--rsi-length", type=int, default=DEFAULT_RSI_LENGTH, help="RSI lookback length")
    parser.add_argument("--max-symbols", type=int, default=None, help="Limit symbol count for faster smoke tests")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols to analyze instead of the whole market")
    parser.add_argument("--refresh", action="store_true", help="Force redownload even if cache coverage looks complete")
    parser.add_argument("--cache-only", action="store_true", help="Use only already cached candles and do not call Binance for missing ranges")
    parser.add_argument("--api-only", action="store_true", help="Skip archive downloads and use Binance API only")
    parser.add_argument("--archive-only", action="store_true", help="Use Binance public archive only and skip API tail fill")
    parser.add_argument("--prefetch-only", action="store_true", help="Only warm the local candle cache and skip analytics/report generation")
    parser.add_argument("--no-open", action="store_true", help="Do not auto-open HTML report")
    parser.add_argument("--main-scenario", default=DEFAULT_MAIN_SCENARIO, choices=sorted(SCENARIO_MAP), help="Scenario used for the main factor tables")
    parser.add_argument("--min-group-sample", type=int, default=DEFAULT_MIN_GROUP_SAMPLE, help="Minimum sample for general factor tables")
    parser.add_argument("--min-combo-sample", type=int, default=DEFAULT_MIN_COMBO_SAMPLE, help="Minimum sample for combined setup tables")
    parser.add_argument("--request-pause", type=float, default=HTTP_REQUEST_PAUSE_SECONDS, help="Pause between API requests in seconds")
    args = parser.parse_args()
    if args.api_only and args.archive_only:
        parser.error("--api-only and --archive-only cannot be used together.")
    return args


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat()


def interval_to_minutes(interval: str) -> int:
    unit = interval[-1]
    value = int(interval[:-1])
    if unit == "m":
        return value
    if unit == "h":
        return value * 60
    if unit == "d":
        return value * 1440
    raise ValueError(f"Unsupported interval: {interval}")


def interval_to_milliseconds(interval: str) -> int:
    return interval_to_minutes(interval) * 60 * 1000


def floor_to_interval(ms_value: int, interval_ms: int) -> int:
    return (ms_value // interval_ms) * interval_ms


def ms_to_utc(ms_value: int) -> datetime:
    return datetime.fromtimestamp(ms_value / 1000, tz=UTC)


def build_url(path: str, params: dict[str, Any]) -> str:
    query = urllib.parse.urlencode({key: value for key, value in params.items() if value is not None})
    return f"{BINANCE_FAPI_BASE_URL}{path}?{query}"


def build_archive_url(symbol: str, interval: str, *, cadence: str, label: str) -> str:
    symbol_path = urllib.parse.quote(symbol, safe="")
    file_name = urllib.parse.quote(f"{symbol}-{interval}-{label}.zip", safe="-.")
    return (
        f"{BINANCE_DATA_VISION_BASE_URL}/data/futures/um/{cadence}/klines/"
        f"{symbol_path}/{interval}/{file_name}"
    )


def start_of_day_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def start_of_month_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month_start(dt: datetime) -> datetime:
    dt = start_of_month_utc(dt)
    if dt.month == 12:
        return dt.replace(year=dt.year + 1, month=1)
    return dt.replace(month=dt.month + 1)


def iter_month_starts(start_open_ms: int, end_open_ms: int) -> list[datetime]:
    if start_open_ms > end_open_ms:
        return []
    cursor = start_of_month_utc(ms_to_utc(start_open_ms))
    end_dt = ms_to_utc(end_open_ms)
    months: list[datetime] = []
    while cursor <= end_dt:
        months.append(cursor)
        cursor = next_month_start(cursor)
    return months


def iter_day_starts(start_open_ms: int, end_open_ms: int) -> list[datetime]:
    if start_open_ms > end_open_ms:
        return []
    cursor = start_of_day_utc(ms_to_utc(start_open_ms))
    end_dt = ms_to_utc(end_open_ms)
    days: list[datetime] = []
    while cursor <= end_dt:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def request_weight_for_klines(limit: int) -> int:
    if limit < 100:
        return 1
    if limit < 500:
        return 2
    if limit <= 1000:
        return 5
    return 10


def parse_exchange_request_weight_limit(payload: dict[str, Any]) -> int | None:
    for item in payload.get("rateLimits", []):
        if item.get("rateLimitType") == "REQUEST_WEIGHT" and item.get("interval") == "MINUTE":
            try:
                return int(item.get("limit"))
            except (TypeError, ValueError):
                return None
    return None


def http_get_json(
    path: str,
    params: dict[str, Any],
    *,
    limiter: BinanceRequestLimiter | None = None,
    request_weight: int = DEFAULT_ROUTE_WEIGHT,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, HTTP_RETRIES + 1):
        if limiter is not None:
            limiter.acquire(request_weight)
        url = build_url(path, params)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "RSI-Futures-Research/1.0", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8")
            return json.loads(body)
        except urllib.error.HTTPError as exc:
            last_error = exc
            retry_after_header = exc.headers.get("Retry-After") if exc.headers else None
            if retry_after_header:
                try:
                    retry_after = float(retry_after_header)
                except ValueError:
                    retry_after = 0.0
            else:
                retry_after = 60.0 if exc.code in {418, 429} else HTTP_RETRY_BASE_SLEEP * attempt
            if attempt == HTTP_RETRIES:
                break
            log(f"HTTP {exc.code} on {path}; retry {attempt}/{HTTP_RETRIES} in {retry_after:.1f}s")
            if limiter is not None:
                limiter.backoff(retry_after)
            else:
                time.sleep(retry_after)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == HTTP_RETRIES:
                break
            sleep_seconds = HTTP_RETRY_BASE_SLEEP * attempt
            log(f"Request failed ({exc}); retry {attempt}/{HTTP_RETRIES} in {sleep_seconds:.1f}s")
            time.sleep(sleep_seconds)
    raise RuntimeError(f"Unable to fetch Binance public API after {HTTP_RETRIES} attempts: {last_error}")


def http_get_bytes(url: str) -> bytes | None:
    last_error: Exception | None = None
    for attempt in range(1, HTTP_RETRIES + 1):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "RSI-Futures-Research/1.0", "Accept": "application/zip,application/octet-stream,*/*"},
        )
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 404:
                return None
            if attempt == HTTP_RETRIES:
                break
            sleep_seconds = HTTP_RETRY_BASE_SLEEP * attempt
            log(f"Archive download HTTP {exc.code}; retry {attempt}/{HTTP_RETRIES} in {sleep_seconds:.1f}s")
            time.sleep(sleep_seconds)
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == HTTP_RETRIES:
                break
            sleep_seconds = HTTP_RETRY_BASE_SLEEP * attempt
            log(f"Archive download failed ({exc}); retry {attempt}/{HTTP_RETRIES} in {sleep_seconds:.1f}s")
            time.sleep(sleep_seconds)
    raise RuntimeError(f"Unable to fetch Binance public archive after {HTTP_RETRIES} attempts: {last_error}")


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def open_cache() -> sqlite3.Connection:
    connection = sqlite3.connect(CACHE_DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA temp_store=MEMORY")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialize_cache_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS symbol_catalog (
            symbol TEXT PRIMARY KEY,
            quote_asset TEXT NOT NULL,
            contract_type TEXT NOT NULL,
            status TEXT NOT NULL,
            onboard_date_ms INTEGER,
            raw_json TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS futures_klines (
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            open_time_ms INTEGER NOT NULL,
            open_time_utc TEXT NOT NULL,
            close_time_ms INTEGER NOT NULL,
            close_time_utc TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            quote_volume REAL NOT NULL,
            trades INTEGER NOT NULL,
            taker_base_volume REAL NOT NULL,
            taker_quote_volume REAL NOT NULL,
            is_closed INTEGER NOT NULL DEFAULT 1,
            collected_at_utc TEXT NOT NULL,
            PRIMARY KEY (symbol, interval, open_time_ms)
        );
        CREATE INDEX IF NOT EXISTS idx_futures_klines_symbol_interval_time
        ON futures_klines (symbol, interval, open_time_ms);
        """
    )
    connection.commit()


def fetch_exchange_info() -> dict[str, Any]:
    payload = http_get_json(EXCHANGE_INFO_PATH, {})
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected exchangeInfo payload from Binance Futures.")
    return payload


def fetch_symbol_catalog(exchange_info: dict[str, Any]) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    for item in exchange_info.get("symbols", []):
        if item.get("quoteAsset") != "USDT":
            continue
        if item.get("contractType") != "PERPETUAL":
            continue
        if item.get("status") != "TRADING":
            continue
        symbols.append(item)
    symbols.sort(key=lambda item: item.get("symbol", ""))
    return symbols


def save_symbol_catalog(connection: sqlite3.Connection, symbols: list[dict[str, Any]]) -> None:
    now_iso = to_iso(utc_now())
    rows = [
        (
            item["symbol"],
            item.get("quoteAsset", ""),
            item.get("contractType", ""),
            item.get("status", ""),
            int(item.get("onboardDate") or 0),
            json.dumps(item, ensure_ascii=True, separators=(",", ":")),
            now_iso,
        )
        for item in symbols
    ]
    connection.executemany(
        """
        INSERT INTO symbol_catalog (symbol, quote_asset, contract_type, status, onboard_date_ms, raw_json, updated_at_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET
            quote_asset=excluded.quote_asset,
            contract_type=excluded.contract_type,
            status=excluded.status,
            onboard_date_ms=excluded.onboard_date_ms,
            raw_json=excluded.raw_json,
            updated_at_utc=excluded.updated_at_utc
        """,
        rows,
    )
    connection.commit()


def get_cached_coverage(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    interval: str,
    start_open_ms: int,
    end_open_ms: int,
) -> dict[str, int | None]:
    row = connection.execute(
        """
        SELECT COUNT(*) AS row_count, MIN(open_time_ms) AS min_open_time_ms, MAX(open_time_ms) AS max_open_time_ms
        FROM futures_klines
        WHERE symbol = ? AND interval = ? AND open_time_ms BETWEEN ? AND ?
        """,
        (symbol, interval, start_open_ms, end_open_ms),
    ).fetchone()
    return {
        "row_count": int(row["row_count"]) if row and row["row_count"] is not None else 0,
        "min_open_time_ms": int(row["min_open_time_ms"]) if row and row["min_open_time_ms"] is not None else None,
        "max_open_time_ms": int(row["max_open_time_ms"]) if row and row["max_open_time_ms"] is not None else None,
    }


def should_use_cache(
    coverage: dict[str, int | None],
    *,
    expected_count: int,
    start_open_ms: int,
    end_open_ms: int,
) -> bool:
    row_count = int(coverage["row_count"] or 0)
    min_open = coverage["min_open_time_ms"]
    max_open = coverage["max_open_time_ms"]
    if expected_count <= 0:
        return row_count > 0
    if row_count < max(1, int(expected_count * DEFAULT_CACHE_COMPLETENESS)):
        return False
    if min_open is None or max_open is None:
        return False
    if min_open > start_open_ms:
        return False
    if max_open < end_open_ms:
        return False
    return True


def build_missing_ranges(
    coverage: dict[str, int | None],
    *,
    interval_ms: int,
    start_open_ms: int,
    end_open_ms: int,
    expected_count: int,
) -> list[tuple[int, int]]:
    row_count = int(coverage["row_count"] or 0)
    min_open = coverage["min_open_time_ms"]
    max_open = coverage["max_open_time_ms"]

    if row_count <= 0 or min_open is None or max_open is None:
        return [(start_open_ms, end_open_ms)]

    missing_ranges: list[tuple[int, int]] = []
    if min_open > start_open_ms:
        missing_ranges.append((start_open_ms, min(min_open - interval_ms, end_open_ms)))
    if max_open < end_open_ms:
        missing_ranges.append((max(max_open + interval_ms, start_open_ms), end_open_ms))

    completeness_threshold = max(1, int(expected_count * DEFAULT_CACHE_COMPLETENESS))
    if row_count < completeness_threshold:
        return [(start_open_ms, end_open_ms)]

    return [(range_start, range_end) for range_start, range_end in missing_ranges if range_start <= range_end]


def fetch_klines_range(
    *,
    symbol: str,
    interval: str,
    start_open_ms: int,
    end_open_ms: int,
    limiter: BinanceRequestLimiter,
    pause_seconds: float,
) -> list[tuple[Any, ...]]:
    interval_ms = interval_to_milliseconds(interval)
    collected: list[tuple[Any, ...]] = []
    cursor_open_ms = start_open_ms
    collected_at_utc = to_iso(utc_now())
    kline_request_weight = request_weight_for_klines(KLINES_LIMIT)
    while cursor_open_ms <= end_open_ms:
        chunk_end_open_ms = min(cursor_open_ms + (KLINES_LIMIT - 1) * interval_ms, end_open_ms)
        payload = http_get_json(
            KLINES_PATH,
            {
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor_open_ms,
                "endTime": chunk_end_open_ms + interval_ms - 1,
                "limit": KLINES_LIMIT,
            },
            limiter=limiter,
            request_weight=kline_request_weight,
        )
        if not payload:
            break
        for raw in payload:
            open_time_ms = int(raw[0])
            close_time_ms = int(raw[6])
            collected.append(
                (
                    symbol,
                    interval,
                    open_time_ms,
                    to_iso(ms_to_utc(open_time_ms)),
                    close_time_ms,
                    to_iso(ms_to_utc(close_time_ms)),
                    float(raw[1]),
                    float(raw[2]),
                    float(raw[3]),
                    float(raw[4]),
                    float(raw[5]),
                    float(raw[7]),
                    int(raw[8]),
                    float(raw[9]),
                    float(raw[10]),
                    1,
                    collected_at_utc,
                )
            )
        last_open_ms = int(payload[-1][0])
        if last_open_ms < cursor_open_ms:
            raise RuntimeError(f"Binance returned a non-advancing cursor for {symbol}")
        cursor_open_ms = last_open_ms + interval_ms
        if pause_seconds > 0:
            time.sleep(max(0.0, pause_seconds))
    return collected


def upsert_klines_rows(
    connection: sqlite3.Connection,
    rows: list[tuple[Any, ...]],
) -> None:
    if not rows:
        return
    connection.executemany(
        """
        INSERT INTO futures_klines (
            symbol, interval, open_time_ms, open_time_utc, close_time_ms, close_time_utc,
            open, high, low, close, volume, quote_volume, trades, taker_base_volume,
            taker_quote_volume, is_closed, collected_at_utc
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, interval, open_time_ms) DO UPDATE SET
            open_time_utc=excluded.open_time_utc,
            close_time_ms=excluded.close_time_ms,
            close_time_utc=excluded.close_time_utc,
            open=excluded.open,
            high=excluded.high,
            low=excluded.low,
            close=excluded.close,
            volume=excluded.volume,
            quote_volume=excluded.quote_volume,
            trades=excluded.trades,
            taker_base_volume=excluded.taker_base_volume,
            taker_quote_volume=excluded.taker_quote_volume,
            is_closed=excluded.is_closed,
            collected_at_utc=excluded.collected_at_utc
        """,
        rows,
    )
    connection.commit()


def parse_archive_kline_rows(
    payload: bytes,
    *,
    symbol: str,
    interval: str,
    range_start_open_ms: int,
    range_end_open_ms: int,
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    collected_at_utc = to_iso(utc_now())
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if not csv_names:
            return rows
        with archive.open(csv_names[0], "r") as raw_file:
            text_stream = io.TextIOWrapper(raw_file, encoding="utf-8", newline="")
            reader = csv.reader(text_stream)
            for raw in reader:
                if not raw:
                    continue
                if not raw[0] or not raw[0].strip().lstrip("-").isdigit():
                    continue
                open_time_ms = int(raw[0])
                if open_time_ms < range_start_open_ms or open_time_ms > range_end_open_ms:
                    continue
                close_time_ms = int(raw[6])
                rows.append(
                    (
                        symbol,
                        interval,
                        open_time_ms,
                        to_iso(ms_to_utc(open_time_ms)),
                        close_time_ms,
                        to_iso(ms_to_utc(close_time_ms)),
                        float(raw[1]),
                        float(raw[2]),
                        float(raw[3]),
                        float(raw[4]),
                        float(raw[5]),
                        float(raw[7]),
                        int(raw[8]),
                        float(raw[9]),
                        float(raw[10]),
                        1,
                        collected_at_utc,
                    )
                )
    return rows


def import_archive_period(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    interval: str,
    cadence: str,
    label: str,
    range_start_open_ms: int,
    range_end_open_ms: int,
) -> tuple[bool, int]:
    url = build_archive_url(symbol, interval, cadence=cadence, label=label)
    payload = http_get_bytes(url)
    if payload is None:
        return False, 0
    rows = parse_archive_kline_rows(
        payload,
        symbol=symbol,
        interval=interval,
        range_start_open_ms=range_start_open_ms,
        range_end_open_ms=range_end_open_ms,
    )
    if rows:
        upsert_klines_rows(connection, rows)
    return True, len(rows)


def import_public_archive_history(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    interval: str,
    interval_ms: int,
    start_open_ms: int,
    end_open_ms: int,
    include_daily_tail: bool,
    force_refresh: bool,
) -> dict[str, int]:
    stats = {
        "monthly_files_downloaded": 0,
        "daily_files_downloaded": 0,
        "files_missing": 0,
        "rows_imported": 0,
    }
    current_month_start_ms = floor_to_interval(int(start_of_month_utc(utc_now()).timestamp() * 1000), interval_ms)
    monthly_end_open_ms = min(end_open_ms, current_month_start_ms - interval_ms)

    for month_start in iter_month_starts(start_open_ms, monthly_end_open_ms):
        next_month = next_month_start(month_start)
        period_start_open_ms = max(start_open_ms, floor_to_interval(int(month_start.timestamp() * 1000), interval_ms))
        period_end_open_ms = min(end_open_ms, floor_to_interval(int(next_month.timestamp() * 1000) - interval_ms, interval_ms))
        if period_start_open_ms > period_end_open_ms:
            continue
        expected_count = ((period_end_open_ms - period_start_open_ms) // interval_ms) + 1
        coverage = get_cached_coverage(
            connection,
            symbol=symbol,
            interval=interval,
            start_open_ms=period_start_open_ms,
            end_open_ms=period_end_open_ms,
        )
        if not force_refresh and should_use_cache(
            coverage,
            expected_count=expected_count,
            start_open_ms=period_start_open_ms,
            end_open_ms=period_end_open_ms,
        ):
            continue
        found, imported_rows = import_archive_period(
            connection,
            symbol=symbol,
            interval=interval,
            cadence="monthly",
            label=f"{month_start.year:04d}-{month_start.month:02d}",
            range_start_open_ms=period_start_open_ms,
            range_end_open_ms=period_end_open_ms,
        )
        if found:
            stats["monthly_files_downloaded"] += 1
            stats["rows_imported"] += imported_rows
        else:
            stats["files_missing"] += 1

    if not include_daily_tail:
        return stats

    today_start_open_ms = floor_to_interval(int(start_of_day_utc(utc_now()).timestamp() * 1000), interval_ms)
    daily_start_open_ms = max(start_open_ms, current_month_start_ms)
    daily_end_open_ms = min(end_open_ms, today_start_open_ms - interval_ms)
    for day_start in iter_day_starts(daily_start_open_ms, daily_end_open_ms):
        day_end = day_start + timedelta(days=1)
        period_start_open_ms = max(daily_start_open_ms, floor_to_interval(int(day_start.timestamp() * 1000), interval_ms))
        period_end_open_ms = min(daily_end_open_ms, floor_to_interval(int(day_end.timestamp() * 1000) - interval_ms, interval_ms))
        if period_start_open_ms > period_end_open_ms:
            continue
        expected_count = ((period_end_open_ms - period_start_open_ms) // interval_ms) + 1
        coverage = get_cached_coverage(
            connection,
            symbol=symbol,
            interval=interval,
            start_open_ms=period_start_open_ms,
            end_open_ms=period_end_open_ms,
        )
        if not force_refresh and should_use_cache(
            coverage,
            expected_count=expected_count,
            start_open_ms=period_start_open_ms,
            end_open_ms=period_end_open_ms,
        ):
            continue
        found, imported_rows = import_archive_period(
            connection,
            symbol=symbol,
            interval=interval,
            cadence="daily",
            label=day_start.date().isoformat(),
            range_start_open_ms=period_start_open_ms,
            range_end_open_ms=period_end_open_ms,
        )
        if found:
            stats["daily_files_downloaded"] += 1
            stats["rows_imported"] += imported_rows
        else:
            stats["files_missing"] += 1

    return stats


def load_symbol_frame(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    interval: str,
    start_open_ms: int,
    end_open_ms: int,
) -> pd.DataFrame:
    frame = pd.read_sql_query(
        """
        SELECT symbol, interval, open_time_ms, close_time_ms, open, high, low, close, volume, quote_volume,
               trades, taker_base_volume, taker_quote_volume
        FROM futures_klines
        WHERE symbol = ? AND interval = ? AND open_time_ms BETWEEN ? AND ?
        ORDER BY open_time_ms ASC
        """,
        connection,
        params=(symbol, interval, start_open_ms, end_open_ms),
    )
    if frame.empty:
        return frame
    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "trades",
        "taker_base_volume",
        "taker_quote_volume",
    ]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["open_time"] = pd.to_datetime(frame["open_time_ms"], unit="ms", utc=True)
    frame["close_time"] = pd.to_datetime(frame["close_time_ms"], unit="ms", utc=True)
    return frame


def calculate_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    values = close.astype(float).to_numpy()
    rsi = np.full(len(values), np.nan, dtype=float)
    if len(values) <= length:
        return pd.Series(rsi, index=close.index)
    delta = np.diff(values)
    gains = np.where(delta > 0.0, delta, 0.0)
    losses = np.where(delta < 0.0, -delta, 0.0)
    avg_gain = float(np.mean(gains[:length]))
    avg_loss = float(np.mean(losses[:length]))
    rsi[length] = rsi_from_averages(avg_gain, avg_loss)
    for index in range(length + 1, len(values)):
        gain = float(gains[index - 1])
        loss = float(losses[index - 1])
        avg_gain = ((avg_gain * (length - 1)) + gain) / length
        avg_loss = ((avg_loss * (length - 1)) + loss) / length
        rsi[index] = rsi_from_averages(avg_gain, avg_loss)
    return pd.Series(rsi, index=close.index)


def calculate_atr(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            (frame["high"] - frame["low"]).abs(),
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    values = true_range.astype(float).to_numpy()
    atr = np.full(len(values), np.nan, dtype=float)
    if len(values) < length:
        return pd.Series(atr, index=frame.index)
    avg_tr = float(np.mean(values[:length]))
    atr[length - 1] = avg_tr
    for index in range(length, len(values)):
        avg_tr = ((avg_tr * (length - 1)) + float(values[index])) / length
        atr[index] = avg_tr
    return pd.Series(atr, index=frame.index)


def rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_gain == 0.0 and avg_loss == 0.0:
        return 50.0
    if avg_loss == 0.0:
        return 100.0
    if avg_gain == 0.0:
        return 0.0
    relative_strength = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def build_indicators(frame: pd.DataFrame, *, interval: str, rsi_length: int) -> pd.DataFrame:
    enriched = frame.copy()
    enriched["rsi"] = calculate_rsi(enriched["close"], length=rsi_length)
    enriched["atr"] = calculate_atr(enriched, length=rsi_length)
    enriched["atr_pct"] = (enriched["atr"] / enriched["close"]).replace([np.inf, -np.inf], np.nan)
    enriched["ema20"] = enriched["close"].ewm(span=20, adjust=False).mean()
    enriched["ema50"] = enriched["close"].ewm(span=50, adjust=False).mean()
    enriched["avg_volume_20"] = enriched["volume"].rolling(20).mean()
    enriched["volume_ratio"] = (enriched["volume"] / enriched["avg_volume_20"]).replace([np.inf, -np.inf], np.nan)
    candles_24h = max(1, int((24 * 60) / interval_to_minutes(interval)))
    enriched["rolling_quote_volume_24h"] = enriched["quote_volume"].rolling(candles_24h).sum()
    enriched["body_pct"] = ((enriched["close"] - enriched["open"]).abs() / enriched["open"] * 100.0).replace([np.inf, -np.inf], np.nan)
    enriched["upper_wick_pct"] = (
        (enriched["high"] - enriched[["open", "close"]].max(axis=1)) / enriched["open"] * 100.0
    ).clip(lower=0.0)
    enriched["lower_wick_pct"] = (
        (enriched[["open", "close"]].min(axis=1) - enriched["low"]) / enriched["open"] * 100.0
    ).clip(lower=0.0)
    return enriched


def classify_rsi_bucket(rsi: float) -> tuple[str | None, str | None]:
    if math.isnan(rsi):
        return None, None
    if rsi >= 80.0:
        return "overbought", "80+"
    if rsi >= 76.0:
        return "overbought", "76-79.99"
    if rsi >= 73.0:
        return "overbought", "73-75.99"
    if rsi >= 70.0:
        return "overbought", "70-72.99"
    if rsi >= 67.0:
        return "overbought", "67-69.99"
    if rsi <= 20.0:
        return "oversold", "<=20"
    if rsi <= 24.99:
        return "oversold", "20-24.99"
    if rsi <= 27.99:
        return "oversold", "25-27.99"
    if rsi <= 30.0:
        return "oversold", "28-30.00"
    if rsi <= 33.0:
        return "oversold", "30-33.00"
    return None, None


def liquidity_bucket(value: float | None) -> str:
    if value is None or math.isnan(value):
        return "Нет данных"
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
    if value is None or math.isnan(value):
        return "Нет данных"
    if value < 1.0:
        return "<1.0"
    if value < 1.5:
        return "1.0-1.49"
    if value < 2.0:
        return "1.5-1.99"
    if value < 3.0:
        return "2.0-2.99"
    return "3.0+"


def score_bucket(value: float | None) -> str:
    if value is None or math.isnan(value):
        return "Нет данных"
    if value < 60:
        return "<60"
    if value < 70:
        return "60-69"
    if value < 80:
        return "70-79"
    if value < 90:
        return "80-89"
    return "90+"


def atr_bucket(value: float | None) -> str:
    if value is None or math.isnan(value):
        return "Нет данных"
    if value < 0.008:
        return "<0.8%"
    if value < 0.012:
        return "0.8-1.19%"
    if value < 0.018:
        return "1.2-1.79%"
    if value < 0.025:
        return "1.8-2.49%"
    return "2.5%+"


def rejection_wick_bucket(value: float | None) -> str:
    if value is None or math.isnan(value):
        return "Нет данных"
    if value < 0.3:
        return "<0.3%"
    if value < 0.7:
        return "0.3-0.69%"
    if value < 1.5:
        return "0.7-1.49%"
    return "1.5%+"


def compute_score_from_values(
    *,
    rsi: float,
    close: float,
    ema20: float,
    ema50: float,
    volume_ratio: float | None,
    atr_pct: float | None,
    direction: str,
) -> int:
    if direction == "oversold":
        threshold_distance = max(30.0 - float(rsi), 0.0)
        trend_score = 12 if close < ema20 < ema50 else 5
        stretch = max((ema20 - close) / close, 0.0)
    else:
        threshold_distance = max(float(rsi) - 70.0, 0.0)
        trend_score = 12 if close > ema20 > ema50 else 5
        stretch = max((close - ema20) / close, 0.0)
    extremeness_score = min(threshold_distance * 4.2, 42.0)
    raw_volume_ratio = float(volume_ratio) if volume_ratio is not None and not math.isnan(volume_ratio) else 1.0
    volume_score = min(max(raw_volume_ratio - 1.0, 0.0) * 16.0, 18.0)
    volatility_score = min(float(atr_pct) * 600.0 if atr_pct is not None and not math.isnan(atr_pct) else 0.0, 16.0)
    stretch_score = min(stretch * 4000.0, 14.0)
    total = extremeness_score + volume_score + volatility_score + trend_score + stretch_score
    return int(max(0, min(round(total), 100)))


def compute_score(row: pd.Series, direction: str) -> int:
    return compute_score_from_values(
        rsi=float(row["rsi"]),
        close=float(row["close"]),
        ema20=float(row["ema20"]),
        ema50=float(row["ema50"]),
        volume_ratio=float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else None,
        atr_pct=float(row["atr_pct"]) if pd.notna(row["atr_pct"]) else None,
        direction=direction,
    )


def simulate_outcome_arrays(
    future_highs: np.ndarray,
    future_lows: np.ndarray,
    future_closes: np.ndarray,
    *,
    entry_price: float,
    direction: str,
    scenario: Scenario,
    interval_minutes: int,
) -> dict[str, Any]:
    if future_highs.size == 0:
        return {}
    if direction == "oversold":
        take_price = entry_price * (1.0 + scenario.take_pct)
        stop_price = entry_price * (1.0 - scenario.stop_pct)
        favorable_series = (future_highs / entry_price - 1.0) * 100.0
        adverse_series = (entry_price / future_lows - 1.0) * -100.0
        take_hits = future_highs >= take_price
        stop_hits = future_lows <= stop_price
        final_move_pct = (float(future_closes[-1]) / entry_price - 1.0) * 100.0
    else:
        take_price = entry_price * (1.0 - scenario.take_pct)
        stop_price = entry_price * (1.0 + scenario.stop_pct)
        favorable_series = (entry_price / future_lows - 1.0) * 100.0
        adverse_series = (future_highs / entry_price - 1.0) * -100.0
        take_hits = future_lows <= take_price
        stop_hits = future_highs >= stop_price
        final_move_pct = (entry_price / float(future_closes[-1]) - 1.0) * 100.0

    outcome = "timeout"
    minutes_to_outcome: float | None = None
    exit_candle_offset = int(future_highs.size - 1)
    take_indices = np.flatnonzero(take_hits)
    stop_indices = np.flatnonzero(stop_hits)
    first_take = int(take_indices[0]) if take_indices.size else None
    first_stop = int(stop_indices[0]) if stop_indices.size else None
    if first_take is not None and first_stop is not None:
        if first_take == first_stop:
            outcome = "ambiguous"
            minutes_to_outcome = float((first_take + 1) * interval_minutes)
            exit_candle_offset = first_take
        elif first_take < first_stop:
            outcome = "take"
            minutes_to_outcome = float((first_take + 1) * interval_minutes)
            exit_candle_offset = first_take
        else:
            outcome = "stop"
            minutes_to_outcome = float((first_stop + 1) * interval_minutes)
            exit_candle_offset = first_stop
    elif first_take is not None:
        outcome = "take"
        minutes_to_outcome = float((first_take + 1) * interval_minutes)
        exit_candle_offset = first_take
    elif first_stop is not None:
        outcome = "stop"
        minutes_to_outcome = float((first_stop + 1) * interval_minutes)
        exit_candle_offset = first_stop

    return {
        "outcome": outcome,
        "take_hit": outcome == "take",
        "stop_hit": outcome == "stop",
        "timeout_hit": outcome == "timeout",
        "ambiguous_hit": outcome == "ambiguous",
        "mfe_pct": float(favorable_series.max()),
        "mae_pct": float(abs(adverse_series.min())),
        "final_move_pct": float(final_move_pct),
        "minutes_to_outcome": minutes_to_outcome,
        "exit_candle_offset": exit_candle_offset,
    }


def build_signal_rows(
    frame: pd.DataFrame,
    *,
    interval: str,
    horizon_hours: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bucket_rows: list[dict[str, Any]] = []
    threshold_rows: list[dict[str, Any]] = []
    interval_minutes = interval_to_minutes(interval)
    horizon_candles = max(1, int((horizon_hours * 60) / interval_minutes))
    if len(frame) <= horizon_candles + 5:
        return bucket_rows, threshold_rows

    symbol = str(frame["symbol"].iat[0])
    opens = frame["open"].to_numpy(dtype=float)
    highs = frame["high"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)
    closes = frame["close"].to_numpy(dtype=float)
    rsi_values = frame["rsi"].to_numpy(dtype=float)
    atr_ratio_values = frame["atr_pct"].to_numpy(dtype=float)
    ema20_values = frame["ema20"].to_numpy(dtype=float)
    ema50_values = frame["ema50"].to_numpy(dtype=float)
    volume_ratio_values = frame["volume_ratio"].to_numpy(dtype=float)
    rolling_quote_volume_values = frame["rolling_quote_volume_24h"].to_numpy(dtype=float)
    body_pct_values = frame["body_pct"].to_numpy(dtype=float)
    upper_wick_pct_values = frame["upper_wick_pct"].to_numpy(dtype=float)
    lower_wick_pct_values = frame["lower_wick_pct"].to_numpy(dtype=float)
    open_times = frame["open_time"].tolist()
    close_times = frame["close_time"].tolist()
    bucket_next_index_by_scenario: dict[str, int] = {}
    threshold_next_index_by_rule: dict[tuple[str, str], int] = {}

    for index in range(1, len(frame) - horizon_candles):
        current_rsi = rsi_values[index]
        prev_rsi = rsi_values[index - 1]
        current_atr_ratio = atr_ratio_values[index]
        current_ema20 = ema20_values[index]
        current_ema50 = ema50_values[index]
        current_volume_ratio = volume_ratio_values[index]
        current_rolling_quote_volume = rolling_quote_volume_values[index]
        if (
            np.isnan(current_rsi)
            or np.isnan(prev_rsi)
            or np.isnan(current_atr_ratio)
            or np.isnan(current_ema20)
            or np.isnan(current_ema50)
            or np.isnan(current_volume_ratio)
            or np.isnan(current_rolling_quote_volume)
        ):
            continue
        future_start = index + 1
        future_end = future_start + horizon_candles
        future_highs = highs[future_start:future_end]
        future_lows = lows[future_start:future_end]
        future_closes = closes[future_start:future_end]

        current_direction, current_bucket = classify_rsi_bucket(float(current_rsi))
        _, previous_bucket = classify_rsi_bucket(float(prev_rsi))
        common_base = {
            "symbol": symbol,
            "signal_time_utc": to_iso(close_times[index].to_pydatetime()),
            "signal_open_time_utc": to_iso(open_times[index].to_pydatetime()),
            "entry_price": float(closes[index]),
            "rsi": float(current_rsi),
            "rolling_quote_volume_24h": float(current_rolling_quote_volume),
            "volume_ratio": float(current_volume_ratio),
            "atr_pct": float(current_atr_ratio * 100.0),
            "atr_bucket": atr_bucket(float(current_atr_ratio * 100.0)),
            "body_pct": float(body_pct_values[index]) if not np.isnan(body_pct_values[index]) else np.nan,
            "upper_wick_pct": float(upper_wick_pct_values[index]) if not np.isnan(upper_wick_pct_values[index]) else np.nan,
            "lower_wick_pct": float(lower_wick_pct_values[index]) if not np.isnan(lower_wick_pct_values[index]) else np.nan,
            "interval": interval,
            "horizon_hours": horizon_hours,
        }
        direction_simulations: dict[str, list[dict[str, Any]]] = {}

        def get_direction_simulations(direction: str) -> list[dict[str, Any]]:
            if direction not in direction_simulations:
                direction_simulations[direction] = []
                for scenario in SCENARIOS:
                    simulated = simulate_outcome_arrays(
                        future_highs,
                        future_lows,
                        future_closes,
                        entry_price=float(closes[index]),
                        direction=direction,
                        scenario=scenario,
                        interval_minutes=interval_minutes,
                    )
                    direction_simulations[direction].append(
                        {
                            "scenario_name": scenario.name,
                            "scenario_label": scenario.label,
                            "take_pct": scenario.take_pct * 100.0,
                            "stop_pct": scenario.stop_pct * 100.0,
                            **simulated,
                        }
                    )
            return direction_simulations[direction]

        if current_direction and current_bucket and current_bucket != previous_bucket:
            score_value = compute_score_from_values(
                rsi=float(current_rsi),
                close=float(closes[index]),
                ema20=float(current_ema20),
                ema50=float(current_ema50),
                volume_ratio=float(current_volume_ratio),
                atr_pct=float(current_atr_ratio),
                direction=current_direction,
            )
            rejection_wick_pct = float(lower_wick_pct_values[index]) if current_direction == "oversold" else float(upper_wick_pct_values[index])
            bucket_common = {
                **common_base,
                "direction": current_direction,
                "rsi_bucket": current_bucket,
                "score": score_value,
                "liquidity_bucket": liquidity_bucket(common_base["rolling_quote_volume_24h"]),
                "volume_ratio_bucket": volume_ratio_bucket(common_base["volume_ratio"]),
                "score_bucket": score_bucket(float(score_value)),
                "atr_bucket": common_base["atr_bucket"],
                "rejection_wick_pct": rejection_wick_pct,
                "rejection_wick_bucket": rejection_wick_bucket(rejection_wick_pct),
                "preferred_liquidity_hit": liquidity_bucket(common_base["rolling_quote_volume_24h"]) in {"5M-20M", "50M+"},
                "rsi_76_plus_hit": current_direction == "overbought" and current_rsi >= 76.0,
                "score_90_plus_hit": score_value >= 90,
            }
            for scenario_payload in get_direction_simulations(current_direction):
                scenario_name = str(scenario_payload["scenario_name"])
                if index < bucket_next_index_by_scenario.get(scenario_name, 0):
                    continue
                bucket_rows.append({**bucket_common, **scenario_payload})
                bucket_next_index_by_scenario[scenario_name] = index + int(scenario_payload["exit_candle_offset"]) + 2

        overbought_thresholds_hit = [threshold for threshold in OVERBOUGHT_THRESHOLDS if prev_rsi < threshold <= current_rsi]
        oversold_thresholds_hit = [threshold for threshold in OVERSOLD_THRESHOLDS if prev_rsi > threshold >= current_rsi]
        for direction, threshold_hits, wick_value in [
            ("overbought", overbought_thresholds_hit, float(upper_wick_pct_values[index])),
            ("oversold", oversold_thresholds_hit, float(lower_wick_pct_values[index])),
        ]:
            if not threshold_hits:
                continue
            score_value = compute_score_from_values(
                rsi=float(current_rsi),
                close=float(closes[index]),
                ema20=float(current_ema20),
                ema50=float(current_ema50),
                volume_ratio=float(current_volume_ratio),
                atr_pct=float(current_atr_ratio),
                direction=direction,
            )
            for threshold in threshold_hits:
                threshold_common = {
                    **common_base,
                    "direction": direction,
                    "threshold_label": f"RSI {'>=' if direction == 'overbought' else '<='} {int(threshold) if float(threshold).is_integer() else threshold}",
                    "threshold_value": threshold,
                    "score": score_value,
                    "liquidity_bucket": liquidity_bucket(common_base["rolling_quote_volume_24h"]),
                    "volume_ratio_bucket": volume_ratio_bucket(common_base["volume_ratio"]),
                    "score_bucket": score_bucket(float(score_value)),
                    "atr_bucket": common_base["atr_bucket"],
                    "rejection_wick_pct": wick_value,
                    "rejection_wick_bucket": rejection_wick_bucket(wick_value),
                }
                for scenario_payload in get_direction_simulations(direction):
                    lock_key = (str(scenario_payload["scenario_name"]), str(threshold_common["threshold_label"]))
                    if index < threshold_next_index_by_rule.get(lock_key, 0):
                        continue
                    threshold_rows.append({**threshold_common, **scenario_payload})
                    threshold_next_index_by_rule[lock_key] = index + int(scenario_payload["exit_candle_offset"]) + 2
    return bucket_rows, threshold_rows


def add_outcome_flags(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    enriched = frame.copy()
    enriched["take_count"] = (enriched["outcome"] == "take").astype(int)
    enriched["stop_count"] = (enriched["outcome"] == "stop").astype(int)
    enriched["timeout_count"] = (enriched["outcome"] == "timeout").astype(int)
    enriched["ambiguous_count"] = (enriched["outcome"] == "ambiguous").astype(int)
    enriched["resolved_count"] = enriched["take_count"] + enriched["stop_count"]
    return enriched


def aggregate_stats(frame: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    grouped = frame.groupby(group_columns, dropna=False)
    summary = grouped.agg(
        signal_count=("outcome", "size"),
        take_count=("take_count", "sum"),
        stop_count=("stop_count", "sum"),
        timeout_count=("timeout_count", "sum"),
        ambiguous_count=("ambiguous_count", "sum"),
        resolved_count=("resolved_count", "sum"),
        avg_mfe_pct=("mfe_pct", "mean"),
        median_mfe_pct=("mfe_pct", "median"),
        avg_mae_pct=("mae_pct", "mean"),
        median_mae_pct=("mae_pct", "median"),
        avg_final_move_pct=("final_move_pct", "mean"),
        median_final_move_pct=("final_move_pct", "median"),
        avg_minutes_to_outcome=("minutes_to_outcome", "mean"),
        median_minutes_to_outcome=("minutes_to_outcome", "median"),
        avg_rsi=("rsi", "mean"),
        avg_score=("score", "mean"),
        avg_liquidity_24h=("rolling_quote_volume_24h", "mean"),
        avg_volume_ratio=("volume_ratio", "mean"),
        avg_atr_pct=("atr_pct", "mean"),
        symbol_count=("symbol", "nunique"),
        take_pct_value=("take_pct", "first"),
        stop_pct_value=("stop_pct", "first"),
    ).reset_index()
    summary["take_rate_pct"] = summary["take_count"] / summary["signal_count"] * 100.0
    summary["stop_rate_pct"] = summary["stop_count"] / summary["signal_count"] * 100.0
    summary["timeout_rate_pct"] = summary["timeout_count"] / summary["signal_count"] * 100.0
    summary["ambiguous_rate_pct"] = summary["ambiguous_count"] / summary["signal_count"] * 100.0
    summary["resolved_win_rate_pct"] = np.where(
        summary["resolved_count"] > 0,
        summary["take_count"] / summary["resolved_count"] * 100.0,
        np.nan,
    )
    summary["edge_score"] = (
        (summary["take_rate_pct"] / 100.0) * summary["take_pct_value"]
        - (summary["stop_rate_pct"] / 100.0) * summary["stop_pct_value"]
    )
    return summary


def sort_best(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame.sort_values(
        by=["resolved_win_rate_pct", "edge_score", "take_rate_pct", "signal_count"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)


def round_for_export(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    rounded = frame.copy()
    for column in rounded.columns:
        if pd.api.types.is_float_dtype(rounded[column]):
            rounded[column] = rounded[column].round(2)
    return rounded


def filter_by_sample(frame: pd.DataFrame, min_sample: int) -> pd.DataFrame:
    if frame.empty or "signal_count" not in frame.columns:
        return frame.copy()
    return frame[frame["signal_count"] >= min_sample].reset_index(drop=True)


def rename_columns(frame: pd.DataFrame) -> pd.DataFrame:
    column_map = {
        "scenario_label": "Сценарий",
        "direction": "Направление",
        "threshold_label": "Порог RSI",
        "rsi_bucket": "Диапазон RSI",
        "liquidity_bucket": "Ликвидность 24ч",
        "volume_ratio_bucket": "Относительный объем",
        "score_bucket": "Диапазон score",
        "atr_bucket": "ATR режим",
        "rejection_wick_bucket": "Тень сигнальной свечи",
        "signal_count": "Сделок",
        "take_count": "Закрылось тейком",
        "stop_count": "Закрылось стопом",
        "timeout_count": "Не закрылось за 8ч",
        "ambiguous_count": "Тейк и стоп в одной свече",
        "resolved_count": "Закрылось тейком/стопом",
        "take_rate_pct": "Тейк, %",
        "stop_rate_pct": "Стоп, %",
        "timeout_rate_pct": "Не закрылось за 8ч, %",
        "ambiguous_rate_pct": "Неясно внутри свечи, %",
        "resolved_win_rate_pct": "Win rate среди закрывшихся, %",
        "edge_score": "Edge score",
        "avg_mfe_pct": "Средний лучший ход, %",
        "median_mfe_pct": "Медианный лучший ход, %",
        "avg_mae_pct": "Средний худший ход, %",
        "median_mae_pct": "Медианный худший ход, %",
        "avg_final_move_pct": "Средний итоговый ход, %",
        "median_final_move_pct": "Медианный итоговый ход, %",
        "avg_minutes_to_outcome": "Среднее время до закрытия, мин",
        "median_minutes_to_outcome": "Медианное время до закрытия, мин",
        "avg_rsi": "Средний RSI на входе",
        "avg_score": "Средний score",
        "avg_liquidity_24h": "Средняя ликвидность 24ч, USDT",
        "avg_volume_ratio": "Средний относительный объем",
        "avg_atr_pct": "Средний ATR, %",
        "conditions_hit": "Сколько из 3 условий совпало",
        "combo_label": "Комбинация",
        "symbol_count": "Символов",
    }
    renamed = frame.rename(columns=column_map)
    if "Направление" in renamed.columns:
        renamed["Направление"] = renamed["Направление"].replace(
            {
                "overbought": "Шортовая зона / перекупленность",
                "oversold": "Лонговая зона / перепроданность",
            }
        )
    return renamed


def write_csv(frame: pd.DataFrame, filename: str) -> None:
    round_for_export(rename_columns(frame)).to_csv(OUTPUT_DIR / filename, index=False, encoding="utf-8-sig")


def top_rows(frame: pd.DataFrame, *, rows: int = DEFAULT_MAX_REPORT_ROWS) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame.head(rows).reset_index(drop=True)


def format_value(value: Any) -> str:
    if pd.isna(value):
        return "—"
    if isinstance(value, (float, np.floating)):
        abs_value = abs(float(value))
        if abs_value >= 1_000_000:
            return f"{value:,.0f}".replace(",", " ")
        if abs_value >= 100:
            return f"{value:,.1f}".replace(",", " ")
        return f"{value:,.2f}".replace(",", " ")
    if isinstance(value, (int, np.integer)):
        return f"{int(value):,}".replace(",", " ")
    return escape(str(value))


def select_columns(frame: pd.DataFrame, columns: list[str] | None) -> pd.DataFrame:
    if frame.empty or not columns:
        return frame
    present = [column for column in columns if column in frame.columns]
    return frame[present].copy() if present else frame


def dataframe_to_html(frame: pd.DataFrame, columns: list[str] | None = None) -> str:
    if frame.empty:
        return "<div class='small'>Данных для этой таблицы пока не хватило.</div>"
    visible = round_for_export(rename_columns(select_columns(frame, columns)))
    headers = "".join(f"<th>{escape(str(column))}</th>" for column in visible.columns)
    rows_html = []
    for _, row in visible.iterrows():
        rows_html.append("<tr>" + "".join(f"<td>{format_value(value)}</td>" for value in row.tolist()) + "</tr>")
    return f"<div class='table-wrap'><table><thead><tr>{headers}</tr></thead><tbody>{''.join(rows_html)}</tbody></table></div>"


def dataframe_to_markdown(frame: pd.DataFrame, columns: list[str] | None = None) -> str:
    if frame.empty:
        return "_Недостаточно данных для этой таблицы._"
    visible = round_for_export(rename_columns(select_columns(frame, columns)))
    headers = [str(column) for column in visible.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for _, row in visible.iterrows():
        values = [str(format_value(value)).replace("|", "/") for value in row.tolist()]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def donut_chart(title: str, caption: str, labels: list[str], values: list[float], colors: list[str]) -> str:
    total = sum(values)
    if total <= 0:
        return f"<div class='chart-card'><h3>{escape(title)}</h3><div class='small'>Для диаграммы пока не хватило данных.</div></div>"
    radius = 64
    circumference = 2 * math.pi * radius
    offset = 0.0
    slices = []
    legend_rows = []
    for index, (label, value) in enumerate(zip(labels, values)):
        fraction = value / total
        dash = fraction * circumference
        color = colors[index % len(colors)]
        slices.append(
            f"<circle r='{radius}' cx='90' cy='90' fill='transparent' stroke='{color}' stroke-width='24' "
            f"stroke-dasharray='{dash:.2f} {circumference - dash:.2f}' stroke-dashoffset='{-offset:.2f}' "
            "transform='rotate(-90 90 90)'></circle>"
        )
        legend_rows.append(
            "<div class='legend-item'>"
            f"<div class='legend-left'><span class='swatch' style='background:{color}'></span><span>{escape(label)}</span></div>"
            f"<strong>{value:,.0f}</strong>"
            "</div>"
        )
        offset += dash
    center_value = f"{total:,.0f}".replace(",", " ")
    return (
        "<div class='chart-card'>"
        f"<h3>{escape(title)}</h3>"
        "<svg viewBox='0 0 180 180' width='100%' style='max-width:260px;display:block;margin:0 auto;'>"
        f"<circle r='{radius}' cx='90' cy='90' fill='transparent' stroke='rgba(17,36,61,.08)' stroke-width='24'></circle>"
        + "".join(slices)
        + "<text x='90' y='84' text-anchor='middle' font-size='14' fill='#5b6b7c'>Всего</text>"
        + f"<text x='90' y='106' text-anchor='middle' font-size='24' font-weight='800' fill='#11243d'>{center_value}</text>"
        + "</svg>"
        + f"<div class='legend'>{''.join(legend_rows)}</div>"
        + f"<div class='caption'>{escape(caption)}</div>"
        + "</div>"
    )


def render_section(title: str, intro: str, table: pd.DataFrame, columns: list[str] | None = None) -> str:
    return f"<section class='section'><h2>{escape(title)}</h2><p>{escape(intro)}</p>{dataframe_to_html(table, columns=columns)}</section>"


def build_summary_cards(overall: dict[str, Any]) -> str:
    cards = [
        (
            "Сделок в исследовании",
            overall["bucket_signals"],
            f"{overall['symbols']} фьючерсных монет, {overall['days']} дней, {overall['interval']}, горизонт {overall['horizon_hours']}ч",
        ),
        (
            "Главный сценарий",
            overall["main_scenario_label"],
            "По каждой монете открывается только одна сделка за раз: пока она не закрылась или не истекло 8 часов, новый вход по этой монете не считается.",
        ),
        (
            "Win rate среди закрывшихся",
            f"{overall['main_resolved_win_rate_pct']:.1f}%",
            "Это доля тейков только среди тех сделок, которые реально успели закрыться либо тейком, либо стопом.",
        ),
        (
            "Не закрылось за 8ч",
            f"{overall['main_timeout_rate_pct']:.1f}%",
            "Это сделки, по которым в окне 8 часов цена не тронула ни тейк, ни стоп.",
        ),
    ]
    fragments = []
    for label, value, hint in cards:
        fragments.append(
            "<div class='kpi'>"
            f"<div class='label'>{escape(str(label))}</div>"
            f"<div class='value'>{escape(str(value))}</div>"
            f"<div class='hint'>{escape(str(hint))}</div>"
            "</div>"
        )
    return "".join(fragments)


def direction_label(value: str) -> str:
    return {
        "overbought": "перекупленность / шортовая зона",
        "oversold": "перепроданность / лонговая зона",
    }.get(value, value)


def pick_best_row(frame: pd.DataFrame) -> pd.Series | None:
    if frame.empty:
        return None
    return sort_best(frame).iloc[0]


def build_recommendations(
    *,
    best_thresholds: pd.DataFrame,
    best_rsi_buckets: pd.DataFrame,
    best_liquidity: pd.DataFrame,
    best_relative_volume: pd.DataFrame,
    best_score: pd.DataFrame,
    best_combos: pd.DataFrame,
    score90_focus: pd.DataFrame,
) -> list[str]:
    suggestions: list[str] = []
    best_threshold = pick_best_row(best_thresholds)
    if best_threshold is not None:
        suggestions.append(
            f"По порогам RSI сейчас сильнее всего смотрится {direction_label(str(best_threshold['direction']))} {best_threshold['threshold_label']} "
            f"на выборке {int(best_threshold['signal_count'])} сделок: тейк {best_threshold['take_rate_pct']:.1f}%, "
            f"стоп {best_threshold['stop_rate_pct']:.1f}%, win rate {best_threshold['resolved_win_rate_pct']:.1f}%."
        )
    best_bucket = pick_best_row(best_rsi_buckets)
    if best_bucket is not None:
        suggestions.append(
            f"По фактическому RSI на входе лучше всего выглядела зона {best_bucket['rsi_bucket']} "
            f"({direction_label(str(best_bucket['direction']))}), выборка {int(best_bucket['signal_count'])}, edge {best_bucket['edge_score']:.2f}."
        )
    best_liquidity_row = pick_best_row(best_liquidity)
    if best_liquidity_row is not None:
        suggestions.append(
            f"По 24-часовой ликвидности лучший класс сейчас: {best_liquidity_row['liquidity_bucket']} "
            f"на {int(best_liquidity_row['signal_count'])} сделках."
        )
    best_relative_volume_row = pick_best_row(best_relative_volume)
    if best_relative_volume_row is not None:
        suggestions.append(
            f"Относительный объем лучше всего выглядел в корзине {best_relative_volume_row['volume_ratio_bucket']}: "
            f"тейк {best_relative_volume_row['take_rate_pct']:.1f}% и edge {best_relative_volume_row['edge_score']:.2f}."
        )
    best_score_row = pick_best_row(best_score)
    if best_score_row is not None:
        suggestions.append(
            f"Score-фильтр действительно полезен: лучшая корзина сейчас {best_score_row['score_bucket']} "
            f"с win rate {best_score_row['resolved_win_rate_pct']:.1f}% на {int(best_score_row['signal_count'])} сделках."
        )
    score90_row = pick_best_row(score90_focus)
    if score90_row is not None:
        suggestions.append(
            f"Если смотреть только на score 90+, то сильная точка сейчас: {direction_label(str(score90_row['direction']))} / {score90_row['rsi_bucket']} / "
            f"{score90_row['liquidity_bucket']}, выборка {int(score90_row['signal_count'])}."
        )
    best_combo_row = pick_best_row(best_combos)
    if best_combo_row is not None:
        suggestions.append(
            f"Лучшая совмещенная связка в main scenario: {direction_label(str(best_combo_row['direction']))} + {best_combo_row['rsi_bucket']} + "
            f"{best_combo_row['liquidity_bucket']} + {best_combo_row['score_bucket']} "
            f"на {int(best_combo_row['signal_count'])} сделках."
        )
    suggestions.append("Смотри не только на win rate, но и на размер выборки. Для реальных настроек строки хотя бы с 25-40 сделками надежнее, чем сверхкрасивые 3-7 сделок.")
    suggestions.append("Ликвидность 24ч здесь восстановлена из свечей как rolling 24h quote volume. Это хороший практический прокси, но не идеальная копия live-метрики бота.")
    suggestions.append("Если и тейк, и стоп были задеты в одной свече, такие случаи помечены как неоднозначные. Отчет не притворяется, что знает порядок касаний внутри свечи.")
    return suggestions


def build_html_report(
    *,
    overall: dict[str, Any],
    scenario_overview: pd.DataFrame,
    direction_stats: pd.DataFrame,
    threshold_stats: pd.DataFrame,
    rsi_bucket_stats: pd.DataFrame,
    liquidity_stats: pd.DataFrame,
    relative_volume_stats: pd.DataFrame,
    score_stats: pd.DataFrame,
    wick_stats: pd.DataFrame,
    score90_focus: pd.DataFrame,
    best_combos: pd.DataFrame,
    okak_combos: pd.DataFrame,
    recommendations: list[str],
) -> str:
    direction_mix = direction_stats.groupby("direction", dropna=False)["signal_count"].sum().reset_index()
    outcome_mix = scenario_overview.loc[
        scenario_overview["scenario_name"] == overall["main_scenario_name"],
        ["take_count", "stop_count", "timeout_count", "ambiguous_count"],
    ]
    main_outcome_values = (
        [float(outcome_mix.iloc[0][column]) for column in ["take_count", "stop_count", "timeout_count", "ambiguous_count"]]
        if not outcome_mix.empty
        else [0.0, 0.0, 0.0, 0.0]
    )
    score90_mix = (
        [float(score90_focus[column].sum()) for column in ["take_count", "stop_count", "timeout_count", "ambiguous_count"]]
        if not score90_focus.empty
        else [0.0, 0.0, 0.0, 0.0]
    )
    charts_html = "".join(
        [
            donut_chart(
                "Баланс лонг/шорт зон",
                "Сколько последовательных сделок в исследовании пришло из перепроданности и из перекупленности.",
                ["Лонговая зона / перепроданность", "Шортовая зона / перекупленность"],
                [
                    float(direction_mix.loc[direction_mix["direction"] == "oversold", "signal_count"].sum()),
                    float(direction_mix.loc[direction_mix["direction"] == "overbought", "signal_count"].sum()),
                ],
                ["#0f6d7a", "#bb5f45"],
            ),
            donut_chart(
                f"Исходы {overall['main_scenario_label']}",
                "Главная диаграмма: сколько сделок закрылись тейком, сколько закрылись стопом, сколько так и не закрылись за 8 часов и сколько остались неоднозначными внутри одной свечи.",
                ["Закрылось тейком", "Закрылось стопом", "Не закрылось за 8ч", "Тейк и стоп в одной свече"],
                main_outcome_values,
                ["#2d7d55", "#b44e42", "#d79b34", "#7d5d99"],
            ),
            donut_chart(
                "Срез score 90+",
                "Быстрая визуализация именно по самым сильным сделкам из score 90+ focus-таблицы.",
                ["Закрылось тейком", "Закрылось стопом", "Не закрылось за 8ч", "Неясно"],
                score90_mix,
                ["#2d7d55", "#b44e42", "#d79b34", "#7d5d99"],
            ),
        ]
    )
    notes = f"""
    <div class='info-grid'>
      <div class='note'>
        <h3>Как читать этот отчет</h3>
        <p>Сначала смотри на <strong>тейк, стоп и win rate</strong>, потом на <strong>размер выборки</strong>, и только затем на edge. Красивый процент на 6 сделках слабее, чем умеренный процент на 120.</p>
      </div>
      <div class='note'>
        <h3>Что такое относительный объем</h3>
        <p>Это объем текущей свечи относительно среднего объема прошлых 20 свечей. Значение <strong>1.0</strong> означает обычный режим, <strong>2.0</strong> — примерно вдвое сильнее нормы.</p>
      </div>
      <div class='note'>
        <h3>Как считается одна сделка</h3>
        <p>Как только свеча дала вход по правилу, считаем, что по этой монете открылась одна сделка. Дальше по этой же монете новые входы не считаются, пока старая сделка не закрылась тейком, стопом или пока не истекло <strong>{overall['horizon_hours']} часов</strong>.</p>
      </div>
    </div>
    """
    recommendations_html = "".join(f"<li>{escape(item)}</li>" for item in recommendations)
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Futures RSI Research</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <span class="eyebrow">Standalone Futures Research</span>
      <h1>Какой RSI по фьючерсам выглядел сильнее за последние {overall['days']} дней</h1>
      <p class="lead">Это отдельный исследовательский модуль в <code>test2</code>. Он берет публичные свечи Binance Futures, восстанавливает bot-like score, открывает по монете только одну сделку за раз, затем ждет тейк, стоп или таймаут 8 часов и на этой логике собирает понятный дашборд. В отчете показаны только top-{DEFAULT_MAX_REPORT_ROWS} строк по ключевым таблицам, чтобы не перегружать экран.</p>
      <div class="hero-grid">{build_summary_cards(overall)}</div>
    </section>
    <section class="section">
      <h2>Быстрый контекст</h2>
      <p>Источник данных: Binance USDT perpetual futures, публичные свечи и локальный кэш <code>test2</code>. Ликвидность 24ч тут восстановлена из свечей, а score пересчитан по формуле текущего RSI-бота. Ни один файл основного бота этим модулем не запускается.</p>
      <div class="pill-row">
        <span class="pill">{escape(overall['main_scenario_label'])}</span>
        <span class="pill">{escape(overall['interval'])} candles</span>
        <span class="pill">Горизонт проверки {overall['horizon_hours']}ч</span>
        <span class="pill">RSI length {overall['rsi_length']}</span>
        <span class="pill">{overall['symbols']} symbols</span>
      </div>
      {notes}
    </section>
    <section class="section">
      <h2>Круговые диаграммы</h2>
      <p>Сначала визуально: откуда вообще пришли сделки, сколько из них реально закрылись тейком или стопом и как выглядел срез score 90+.</p>
      <div class="chart-grid">{charts_html}</div>
    </section>
    {render_section("Сценарии тейка и стопа", "Это общая сводка по четырем основным вариантам тейка/стопа. С нее лучше начинать: она сразу показывает, какой режим исторически выглядел практичнее.", top_rows(sort_best(scenario_overview), rows=DEFAULT_MAX_REPORT_ROWS), columns=SCENARIO_COLUMNS)}
    {render_section("Лонговая зона против шортовой зоны", "Здесь видно, где у RSI было больше шансов: в перепроданности или в перекупленности. Таблица уже отсортирована по win rate.", top_rows(sort_best(direction_stats), rows=DEFAULT_MAX_REPORT_ROWS), columns=[column for column in FACTOR_COLUMNS if column != 'rsi_bucket' and column != 'liquidity_bucket' and column != 'volume_ratio_bucket' and column != 'score_bucket' and column != 'rejection_wick_bucket' and column != 'threshold_label'])}
    {render_section("Лучшие пороги RSI", "Таблица отвечает на вопрос, какие именно пороги входа по RSI исторически выглядели сильнее. Это отдельное исследование порогов, а не просто bucket по готовым сигналам.", top_rows(sort_best(threshold_stats), rows=DEFAULT_MAX_REPORT_ROWS), columns=["direction", "threshold_label", "signal_count", "take_rate_pct", "stop_rate_pct", "resolved_win_rate_pct", "avg_mfe_pct", "avg_mae_pct", "edge_score"])}
    {render_section("Где RSI работал лучше", "Это взгляд на фактический RSI сигнальной свечи. Если хочешь понять, в каких именно значениях RSI вход выглядел вкуснее, смотри сюда.", top_rows(sort_best(rsi_bucket_stats), rows=DEFAULT_MAX_REPORT_ROWS), columns=["direction", "rsi_bucket", "signal_count", "take_rate_pct", "stop_rate_pct", "resolved_win_rate_pct", "avg_mfe_pct", "avg_mae_pct", "edge_score"])}
    {render_section("Какая ликвидность выглядела лучше", "Тут ликвидность считается как rolling 24h quote volume, восстановленный из свечей. Именно это ближе всего к фильтрам вида 5M-20M и 50M+.", top_rows(sort_best(liquidity_stats), rows=DEFAULT_MAX_REPORT_ROWS), columns=["liquidity_bucket", "signal_count", "take_rate_pct", "stop_rate_pct", "resolved_win_rate_pct", "avg_mfe_pct", "avg_mae_pct", "edge_score"])}
    {render_section("Что дал относительный объем", "Относительный объем показывает, насколько текущая свеча была сильнее обычного режима торгов. Это хороший фильтр, если ты хочешь отделить живые импульсы от вялых.", top_rows(sort_best(relative_volume_stats), rows=DEFAULT_MAX_REPORT_ROWS), columns=["volume_ratio_bucket", "signal_count", "take_rate_pct", "stop_rate_pct", "resolved_win_rate_pct", "avg_mfe_pct", "avg_mae_pct", "edge_score"])}
    {render_section("Как отработал score", "Score здесь восстановлен по формуле текущего RSI-бота: экстремальность RSI, volume ratio, ATR, тренд EMA20/EMA50 и растяжение от EMA20.", top_rows(sort_best(score_stats), rows=DEFAULT_MAX_REPORT_ROWS), columns=["score_bucket", "signal_count", "take_rate_pct", "stop_rate_pct", "resolved_win_rate_pct", "avg_mfe_pct", "avg_mae_pct", "edge_score"])}
    {render_section("Что дали тени сигнальной свечи", "Поскольку задача была понять внутреннее движение свечи, отдельно показываем rejection wick. Для шортовых идей берется верхняя тень, для лонговых — нижняя.", top_rows(sort_best(wick_stats), rows=DEFAULT_MAX_REPORT_ROWS), columns=["rejection_wick_bucket", "signal_count", "take_rate_pct", "stop_rate_pct", "resolved_win_rate_pct", "avg_mfe_pct", "avg_mae_pct", "edge_score"])}
    {render_section("Score 90+ под увеличительным стеклом", "Это уже узкий срез по сильным score-сигналам. Хорошо подходит, если хочешь проверять логику вроде 'оставлять только очень сильные сетапы'.", top_rows(sort_best(score90_focus), rows=DEFAULT_MAX_REPORT_ROWS), columns=["direction", "rsi_bucket", "liquidity_bucket", "signal_count", "take_rate_pct", "stop_rate_pct", "resolved_win_rate_pct", "avg_mfe_pct", "avg_mae_pct", "edge_score"])}
    {render_section("Лучшие совмещенные фильтры", "Самое полезное место для будущих настроек. Здесь объединены направление, bucket RSI, ликвидность и bucket score. На экран выведен только top-5.", top_rows(sort_best(best_combos), rows=DEFAULT_MAX_REPORT_ROWS), columns=COMBO_COLUMNS)}
    {render_section("OKAK-style логика 2 из 3", "Проверка связки из трех условий: ликвидность 5M-20M или 50M+, RSI 76+, score 90+. Можно быстро увидеть, как вел себя режим '2 из 3' и '3 из 3'.", top_rows(sort_best(okak_combos), rows=DEFAULT_MAX_REPORT_ROWS), columns=OKAK_COLUMNS)}
    <section class="section">
      <h2>Осторожные выводы</h2>
      <p>Это не обещание будущей прибыли, а data-driven подсказки по тому, где исторически было больше шансов. Смотри на них как на идеи для фильтров, а не как на магические кнопки.</p>
      <ul class="bullet-list">{recommendations_html}</ul>
    </section>
    <section class="section">
      <h2>Ограничения</h2>
      <p>Отчет специально честный насчет ограничений. Он не делает вид, что знает больше, чем можно восстановить из OHLCV.</p>
      <ul class="bullet-list">
        <li>Здесь используется последовательная логика сделок: по каждой монете внутри каждого тестируемого сценария одновременно держится только одна сделка. Пока она не закрылась тейком, стопом или таймаутом 8ч, новый вход по этой монете не открывается.</li>
        <li>Сценарии считаются по свечам, а не по тикам. Если тейк и стоп были внутри одной свечи, порядок касаний неизвестен, и такие случаи вынесены в отдельный статус.</li>
        <li>Ликвидность 24ч восстановлена из суммы quote volume свечей, это не исторический live ticker snapshot.</li>
        <li>Исследование показывает, что было бы исторически на публичных свечах Binance Futures, а не то, что реально отправлял основной бот.</li>
        <li>Полные таблицы лежат в CSV рядом с этим HTML. Внутри самого отчета показан только top-{DEFAULT_MAX_REPORT_ROWS}, чтобы экран не превращался в бесконечную простыню.</li>
      </ul>
    </section>
    <div class="footer">Собрано: {escape(overall['generated_at_utc'])} UTC • Cache DB: {escape(str(CACHE_DB_PATH.name))}</div>
  </div>
</body>
</html>"""


def build_markdown_report(
    *,
    overall: dict[str, Any],
    scenario_overview: pd.DataFrame,
    direction_stats: pd.DataFrame,
    threshold_stats: pd.DataFrame,
    rsi_bucket_stats: pd.DataFrame,
    liquidity_stats: pd.DataFrame,
    relative_volume_stats: pd.DataFrame,
    score_stats: pd.DataFrame,
    wick_stats: pd.DataFrame,
    score90_focus: pd.DataFrame,
    best_combos: pd.DataFrame,
    okak_combos: pd.DataFrame,
    recommendations: list[str],
) -> str:
    lines = [
        "# Futures RSI Research",
        "",
        "Изолированный аналитический модуль из `test2`.",
        "",
        "## Executive Summary",
        "",
        f"- Дней в исследовании: `{overall['days']}`",
        f"- Таймфрейм свечи: `{overall['interval']}`",
        f"- Горизонт после входа: `{overall['horizon_hours']}h`",
        f"- Символов: `{overall['symbols']}`",
        f"- Сделок по bucket-логике в исследовании: `{overall['bucket_signals']}`",
        f"- Сделок по threshold-логике в исследовании: `{overall['threshold_signals']}`",
        f"- Main scenario: `{overall['main_scenario_label']}`",
        f"- Main take rate: `{overall['main_take_rate_pct']:.2f}%`",
        f"- Main stop rate: `{overall['main_stop_rate_pct']:.2f}%`",
        f"- Main timeout rate: `{overall['main_timeout_rate_pct']:.2f}%`",
        f"- Main resolved win rate: `{overall['main_resolved_win_rate_pct']:.2f}%`",
        "",
        "## Осторожные выводы",
        "",
    ]
    lines.extend(f"- {item}" for item in recommendations)
    sections = [
        ("Сценарии тейка и стопа", scenario_overview, SCENARIO_COLUMNS),
        ("Лонговая зона против шортовой зоны", direction_stats, ["direction", "signal_count", "take_rate_pct", "stop_rate_pct", "resolved_win_rate_pct", "avg_mfe_pct", "avg_mae_pct", "edge_score"]),
        ("Лучшие пороги RSI", threshold_stats, ["direction", "threshold_label", "signal_count", "take_rate_pct", "stop_rate_pct", "resolved_win_rate_pct", "avg_mfe_pct", "avg_mae_pct", "edge_score"]),
        ("Где RSI работал лучше", rsi_bucket_stats, ["direction", "rsi_bucket", "signal_count", "take_rate_pct", "stop_rate_pct", "resolved_win_rate_pct", "avg_mfe_pct", "avg_mae_pct", "edge_score"]),
        ("Какая ликвидность выглядела лучше", liquidity_stats, ["liquidity_bucket", "signal_count", "take_rate_pct", "stop_rate_pct", "resolved_win_rate_pct", "avg_mfe_pct", "avg_mae_pct", "edge_score"]),
        ("Что дал относительный объем", relative_volume_stats, ["volume_ratio_bucket", "signal_count", "take_rate_pct", "stop_rate_pct", "resolved_win_rate_pct", "avg_mfe_pct", "avg_mae_pct", "edge_score"]),
        ("Как отработал score", score_stats, ["score_bucket", "signal_count", "take_rate_pct", "stop_rate_pct", "resolved_win_rate_pct", "avg_mfe_pct", "avg_mae_pct", "edge_score"]),
        ("Что дали тени сигнальной свечи", wick_stats, ["rejection_wick_bucket", "signal_count", "take_rate_pct", "stop_rate_pct", "resolved_win_rate_pct", "avg_mfe_pct", "avg_mae_pct", "edge_score"]),
        ("Score 90+ под увеличительным стеклом", score90_focus, ["direction", "rsi_bucket", "liquidity_bucket", "signal_count", "take_rate_pct", "stop_rate_pct", "resolved_win_rate_pct", "avg_mfe_pct", "avg_mae_pct", "edge_score"]),
        ("Лучшие совмещенные фильтры", best_combos, COMBO_COLUMNS),
        ("OKAK-style логика 2 из 3", okak_combos, OKAK_COLUMNS),
    ]
    for title, frame, columns in sections:
        lines.extend(["", f"## {title}", "", dataframe_to_markdown(top_rows(sort_best(frame), rows=DEFAULT_MAX_REPORT_ROWS), columns=columns)])
    return "\n".join(lines) + "\n"


def build_okak_combos(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    overbought = frame[frame["direction"] == "overbought"].copy()
    if overbought.empty:
        return pd.DataFrame()

    def combo_label(row: pd.Series) -> str:
        labels = []
        if bool(row["preferred_liquidity_hit"]):
            labels.append("ликвидность 5-20M или 50M+")
        if bool(row["rsi_76_plus_hit"]):
            labels.append("RSI 76+")
        if bool(row["score_90_plus_hit"]):
            labels.append("score 90+")
        return " + ".join(labels) if labels else "ни одно из 3"

    overbought["conditions_hit"] = (
        overbought["preferred_liquidity_hit"].astype(int)
        + overbought["rsi_76_plus_hit"].astype(int)
        + overbought["score_90_plus_hit"].astype(int)
    )
    overbought["combo_label"] = overbought.apply(combo_label, axis=1)
    return aggregate_stats(overbought, ["scenario_name", "scenario_label", "conditions_hit", "combo_label"])


def collect_and_analyze(args: argparse.Namespace) -> dict[str, Any]:
    ensure_directories()
    connection = open_cache()
    initialize_cache_schema(connection)

    log("Loading Binance Futures symbol catalog...")
    exchange_info = fetch_exchange_info()
    request_weight_limit = parse_exchange_request_weight_limit(exchange_info) or DEFAULT_REQUEST_WEIGHT_LIMIT_PER_MINUTE
    limiter = BinanceRequestLimiter(
        request_weight_limit_per_minute=request_weight_limit,
        headroom_ratio=REQUEST_WEIGHT_HEADROOM_RATIO,
        min_pause_seconds=args.request_pause,
    )
    catalog = fetch_symbol_catalog(exchange_info)
    save_symbol_catalog(connection, catalog)
    log(
        "Binance REQUEST_WEIGHT limit detected: "
        f"{request_weight_limit}/min; using ~{limiter.target_limit}/min target with "
        f"kline limit {KLINES_LIMIT} (weight {request_weight_for_klines(KLINES_LIMIT)})."
    )
    archive_enabled = not args.api_only and not args.cache_only
    api_enabled = not args.archive_only and not args.cache_only
    if archive_enabled and api_enabled:
        log("Mode: hybrid. Bulk history will come from Binance public archive; API is only used for small recent gaps.")
    elif archive_enabled:
        log("Mode: archive-only. Using Binance public archive only; API tail fill is disabled.")
    elif api_enabled:
        log("Mode: api-only. Skipping public archive and using Binance API for history fill.")
    else:
        log("Mode: cache-only. Using only already saved local candles.")

    symbol_filter = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    selected_catalog = [item for item in catalog if item["symbol"].upper() in set(symbol_filter)] if symbol_filter else catalog
    if args.max_symbols:
        selected_catalog = selected_catalog[: args.max_symbols]
    if not selected_catalog:
        raise RuntimeError("No futures symbols matched the requested filters.")

    interval_ms = interval_to_milliseconds(args.interval)
    now_ms = int(utc_now().timestamp() * 1000)
    last_completed_open_ms = floor_to_interval(now_ms, interval_ms) - interval_ms
    requested_start_open_ms = floor_to_interval(now_ms - args.days * 24 * 60 * 60 * 1000, interval_ms)

    total_symbols = len(selected_catalog)
    all_bucket_rows: list[dict[str, Any]] = []
    all_threshold_rows: list[dict[str, Any]] = []
    total_cached_rows = 0
    total_downloaded_symbols = 0
    overall_started_at = time.monotonic()

    log(f"Preparing candle cache for {total_symbols} symbols...")
    for index, item in enumerate(selected_catalog, start=1):
        symbol_started_at = time.monotonic()
        symbol = item["symbol"]
        onboard_open_ms = floor_to_interval(int(item.get("onboardDate") or 0), interval_ms)
        start_open_ms = max(requested_start_open_ms, onboard_open_ms)
        if start_open_ms > last_completed_open_ms:
            continue
        expected_count = ((last_completed_open_ms - start_open_ms) // interval_ms) + 1
        coverage = get_cached_coverage(
            connection,
            symbol=symbol,
            interval=args.interval,
            start_open_ms=start_open_ms,
            end_open_ms=last_completed_open_ms,
        )
        use_cache = should_use_cache(
            coverage,
            expected_count=expected_count,
            start_open_ms=start_open_ms,
            end_open_ms=last_completed_open_ms,
        ) and not args.refresh
        missing_ranges = build_missing_ranges(
            coverage,
            interval_ms=interval_ms,
            start_open_ms=start_open_ms,
            end_open_ms=last_completed_open_ms,
            expected_count=expected_count,
        )

        if use_cache:
            log(f"[{index}/{total_symbols}] {symbol}: using cache ({coverage['row_count']}/{expected_count} candles)")
        else:
            if args.cache_only:
                log(
                    f"[{index}/{total_symbols}] {symbol}: cache-only mode, using local candles only "
                    f"({coverage['row_count']}/{expected_count} cached)"
                )
            else:
                archive_stats = None
                if archive_enabled:
                    archive_stats = import_public_archive_history(
                        connection,
                        symbol=symbol,
                        interval=args.interval,
                        interval_ms=interval_ms,
                        start_open_ms=start_open_ms,
                        end_open_ms=last_completed_open_ms,
                        include_daily_tail=args.archive_only,
                        force_refresh=args.refresh,
                    )
                    if archive_stats["monthly_files_downloaded"] or archive_stats["daily_files_downloaded"]:
                        log(
                            f"[{index}/{total_symbols}] {symbol}: archive imported "
                            f"{archive_stats['rows_imported']} candles from "
                            f"{archive_stats['monthly_files_downloaded']} monthly and "
                            f"{archive_stats['daily_files_downloaded']} daily file(s)."
                        )
                    coverage = get_cached_coverage(
                        connection,
                        symbol=symbol,
                        interval=args.interval,
                        start_open_ms=start_open_ms,
                        end_open_ms=last_completed_open_ms,
                    )
                    use_cache = should_use_cache(
                        coverage,
                        expected_count=expected_count,
                        start_open_ms=start_open_ms,
                        end_open_ms=last_completed_open_ms,
                    ) and not args.refresh
                    missing_ranges = build_missing_ranges(
                        coverage,
                        interval_ms=interval_ms,
                        start_open_ms=start_open_ms,
                        end_open_ms=last_completed_open_ms,
                        expected_count=expected_count,
                    )

                api_full_refresh = args.refresh and not archive_enabled
                if api_enabled and (api_full_refresh or missing_ranges):
                    if api_full_refresh:
                        missing_ranges = [(start_open_ms, last_completed_open_ms)]
                    total_missing_candles = sum(((range_end - range_start) // interval_ms) + 1 for range_start, range_end in missing_ranges)
                    estimated_requests = max(1, math.ceil(total_missing_candles / KLINES_LIMIT))
                    range_label = "1 continuous range" if len(missing_ranges) == 1 else f"{len(missing_ranges)} ranges"
                    latest_tail_only = (
                        len(missing_ranges) == 1
                        and missing_ranges[0][1] == last_completed_open_ms
                        and total_missing_candles <= 3
                    )
                    if latest_tail_only:
                        log(
                            f"[{index}/{total_symbols}] {symbol}: topping up {total_missing_candles} freshest closed "
                            f"candle(s) (~{estimated_requests} API call{'s' if estimated_requests != 1 else ''})..."
                        )
                    else:
                        log(
                            f"[{index}/{total_symbols}] {symbol}: downloading {total_missing_candles} missing candles "
                            f"from {range_label} (~{estimated_requests} API calls)..."
                        )
                    downloaded_anything = False
                    for missing_start_ms, missing_end_ms in missing_ranges:
                        rows = fetch_klines_range(
                            symbol=symbol,
                            interval=args.interval,
                            start_open_ms=missing_start_ms,
                            end_open_ms=missing_end_ms,
                            limiter=limiter,
                            pause_seconds=args.request_pause,
                        )
                        upsert_klines_rows(connection, rows)
                        downloaded_anything = downloaded_anything or bool(rows)
                    if downloaded_anything:
                        total_downloaded_symbols += 1

        frame = load_symbol_frame(
            connection,
            symbol=symbol,
            interval=args.interval,
            start_open_ms=start_open_ms,
            end_open_ms=last_completed_open_ms,
        )
        if frame.empty or len(frame) < 120:
            continue
        if args.prefetch_only:
            symbol_elapsed = time.monotonic() - symbol_started_at
            avg_symbol_seconds = (time.monotonic() - overall_started_at) / max(index, 1)
            remaining_symbols = max(0, total_symbols - index)
            eta_seconds = remaining_symbols * avg_symbol_seconds
            log(f"[{index}/{total_symbols}] {symbol}: cache ready in {format_duration(symbol_elapsed)} | ETA ~{format_duration(eta_seconds)}")
            continue
        total_cached_rows += len(frame)
        enriched = build_indicators(frame, interval=args.interval, rsi_length=args.rsi_length)
        bucket_rows, threshold_rows = build_signal_rows(enriched, interval=args.interval, horizon_hours=args.horizon_hours)
        all_bucket_rows.extend(bucket_rows)
        all_threshold_rows.extend(threshold_rows)
        symbol_elapsed = time.monotonic() - symbol_started_at
        avg_symbol_seconds = (time.monotonic() - overall_started_at) / max(index, 1)
        remaining_symbols = max(0, total_symbols - index)
        eta_seconds = remaining_symbols * avg_symbol_seconds
        log(f"[{index}/{total_symbols}] {symbol}: ready in {format_duration(symbol_elapsed)} | ETA ~{format_duration(eta_seconds)}")

    connection.close()

    if args.prefetch_only:
        return {
            "prefetch_only": True,
            "generated_at_utc": to_iso(utc_now()),
            "symbol_count": total_symbols,
            "downloaded_symbol_count": total_downloaded_symbols,
            "cache_db_path": str(CACHE_DB_PATH),
        }

    bucket_frame = add_outcome_flags(pd.DataFrame(all_bucket_rows))
    threshold_frame = add_outcome_flags(pd.DataFrame(all_threshold_rows))
    if bucket_frame.empty:
        raise RuntimeError("No bucket-based RSI signals were generated. Try a longer period or more symbols.")

    main_bucket_frame = bucket_frame[bucket_frame["scenario_name"] == args.main_scenario].copy()
    main_threshold_frame = threshold_frame[threshold_frame["scenario_name"] == args.main_scenario].copy()
    scenario_overview = aggregate_stats(bucket_frame, ["scenario_name", "scenario_label"])
    direction_stats = aggregate_stats(main_bucket_frame, ["direction"])
    threshold_stats = aggregate_stats(
        main_threshold_frame,
        ["direction", "threshold_label", "threshold_value"],
    )
    rsi_bucket_stats = aggregate_stats(main_bucket_frame, ["direction", "rsi_bucket"])
    liquidity_stats = aggregate_stats(main_bucket_frame, ["liquidity_bucket"])
    relative_volume_stats = aggregate_stats(main_bucket_frame, ["volume_ratio_bucket"])
    score_stats = aggregate_stats(main_bucket_frame, ["score_bucket"])
    wick_stats = aggregate_stats(main_bucket_frame, ["rejection_wick_bucket"])
    atr_stats = aggregate_stats(main_bucket_frame, ["atr_bucket"])
    score90_focus = aggregate_stats(main_bucket_frame[main_bucket_frame["score"] >= 90].copy(), ["direction", "rsi_bucket", "liquidity_bucket"])
    best_combos = aggregate_stats(main_bucket_frame, ["direction", "rsi_bucket", "liquidity_bucket", "score_bucket"])
    okak_combos = build_okak_combos(main_bucket_frame)

    threshold_stats = filter_by_sample(threshold_stats, args.min_group_sample)
    rsi_bucket_stats = filter_by_sample(rsi_bucket_stats, args.min_group_sample)
    liquidity_stats = filter_by_sample(liquidity_stats, args.min_group_sample)
    relative_volume_stats = filter_by_sample(relative_volume_stats, args.min_group_sample)
    score_stats = filter_by_sample(score_stats, args.min_group_sample)
    wick_stats = filter_by_sample(wick_stats, args.min_group_sample)
    atr_stats = filter_by_sample(atr_stats, args.min_group_sample)
    score90_focus = filter_by_sample(score90_focus, args.min_combo_sample)
    best_combos = filter_by_sample(best_combos, args.min_combo_sample)
    okak_combos = filter_by_sample(okak_combos, args.min_combo_sample)

    main_scenario_row = scenario_overview.loc[scenario_overview["scenario_name"] == args.main_scenario].iloc[0]
    overall = {
        "generated_at_utc": to_iso(utc_now()),
        "days": args.days,
        "interval": args.interval,
        "horizon_hours": args.horizon_hours,
        "rsi_length": args.rsi_length,
        "symbols": int(main_bucket_frame["symbol"].nunique()),
        "catalog_symbols": total_symbols,
        "cached_candles": int(total_cached_rows),
        "downloaded_symbols": total_downloaded_symbols,
        "bucket_signals": int(len(main_bucket_frame)),
        "threshold_signals": int(len(main_threshold_frame)),
        "main_scenario_name": args.main_scenario,
        "main_scenario_label": SCENARIO_MAP[args.main_scenario].label,
        "main_take_rate_pct": float(main_scenario_row["take_rate_pct"]),
        "main_stop_rate_pct": float(main_scenario_row["stop_rate_pct"]),
        "main_timeout_rate_pct": float(main_scenario_row["timeout_rate_pct"]),
        "main_resolved_win_rate_pct": float(main_scenario_row["resolved_win_rate_pct"]),
    }
    overall_frame = pd.DataFrame(
        [
            {"metric": "generated_at_utc", "value": overall["generated_at_utc"]},
            {"metric": "days", "value": overall["days"]},
            {"metric": "interval", "value": overall["interval"]},
            {"metric": "horizon_hours", "value": overall["horizon_hours"]},
            {"metric": "rsi_length", "value": overall["rsi_length"]},
            {"metric": "catalog_symbols_scanned", "value": overall["catalog_symbols"]},
            {"metric": "symbols_with_signals", "value": overall["symbols"]},
            {"metric": "cached_candles_loaded", "value": overall["cached_candles"]},
            {"metric": "symbols_redownloaded_this_run", "value": overall["downloaded_symbols"]},
            {"metric": "bucket_signals", "value": overall["bucket_signals"]},
            {"metric": "threshold_signals", "value": overall["threshold_signals"]},
            {"metric": "main_scenario", "value": overall["main_scenario_label"]},
            {"metric": "main_take_rate_pct", "value": overall["main_take_rate_pct"]},
            {"metric": "main_stop_rate_pct", "value": overall["main_stop_rate_pct"]},
            {"metric": "main_timeout_rate_pct", "value": overall["main_timeout_rate_pct"]},
            {"metric": "main_resolved_win_rate_pct", "value": overall["main_resolved_win_rate_pct"]},
        ]
    )
    recommendations = build_recommendations(
        best_thresholds=threshold_stats,
        best_rsi_buckets=rsi_bucket_stats,
        best_liquidity=liquidity_stats,
        best_relative_volume=relative_volume_stats,
        best_score=score_stats,
        best_combos=best_combos,
        score90_focus=score90_focus,
    )
    return {
        "overall": overall,
        "overall_frame": overall_frame,
        "scenario_overview": scenario_overview,
        "direction_stats": direction_stats,
        "threshold_stats": threshold_stats,
        "rsi_bucket_stats": rsi_bucket_stats,
        "liquidity_stats": liquidity_stats,
        "relative_volume_stats": relative_volume_stats,
        "score_stats": score_stats,
        "wick_stats": wick_stats,
        "atr_stats": atr_stats,
        "score90_focus": score90_focus,
        "best_combos": best_combos,
        "okak_combos": okak_combos,
        "recommendations": recommendations,
    }


def write_outputs(results: dict[str, Any]) -> None:
    overall = results["overall"]
    scenario_overview = sort_best(results["scenario_overview"])
    direction_stats = sort_best(results["direction_stats"])
    threshold_stats = sort_best(results["threshold_stats"])
    rsi_bucket_stats = sort_best(results["rsi_bucket_stats"])
    liquidity_stats = sort_best(results["liquidity_stats"])
    relative_volume_stats = sort_best(results["relative_volume_stats"])
    score_stats = sort_best(results["score_stats"])
    wick_stats = sort_best(results["wick_stats"])
    atr_stats = sort_best(results["atr_stats"])
    score90_focus = sort_best(results["score90_focus"])
    best_combos = sort_best(results["best_combos"])
    okak_combos = sort_best(results["okak_combos"])
    recommendations = results["recommendations"]

    write_csv(results["overall_frame"], "overall_stats.csv")
    write_csv(scenario_overview, "scenario_overview.csv")
    write_csv(direction_stats, "direction_stats.csv")
    write_csv(threshold_stats, "threshold_stats.csv")
    write_csv(top_rows(threshold_stats, rows=50), "best_thresholds.csv")
    write_csv(rsi_bucket_stats, "rsi_buckets.csv")
    write_csv(liquidity_stats, "volume_buckets.csv")
    write_csv(relative_volume_stats, "relative_volume_buckets.csv")
    write_csv(score_stats, "score_buckets.csv")
    write_csv(wick_stats, "wick_buckets.csv")
    write_csv(atr_stats, "atr_buckets.csv")
    write_csv(score90_focus, "score90_focus.csv")
    write_csv(best_combos, "combined_setups.csv")
    write_csv(okak_combos, "okak_style_combos.csv")

    html = build_html_report(
        overall=overall,
        scenario_overview=scenario_overview,
        direction_stats=direction_stats,
        threshold_stats=threshold_stats,
        rsi_bucket_stats=rsi_bucket_stats,
        liquidity_stats=liquidity_stats,
        relative_volume_stats=relative_volume_stats,
        score_stats=score_stats,
        wick_stats=wick_stats,
        score90_focus=score90_focus,
        best_combos=best_combos,
        okak_combos=okak_combos,
        recommendations=recommendations,
    )
    (OUTPUT_DIR / "report.html").write_text(html, encoding="utf-8")

    markdown = build_markdown_report(
        overall=overall,
        scenario_overview=scenario_overview,
        direction_stats=direction_stats,
        threshold_stats=threshold_stats,
        rsi_bucket_stats=rsi_bucket_stats,
        liquidity_stats=liquidity_stats,
        relative_volume_stats=relative_volume_stats,
        score_stats=score_stats,
        wick_stats=wick_stats,
        score90_focus=score90_focus,
        best_combos=best_combos,
        okak_combos=okak_combos,
        recommendations=recommendations,
    )
    (OUTPUT_DIR / "report.md").write_text(markdown, encoding="utf-8")


def try_open_report(report_path: Path) -> None:
    try:
        if hasattr(os, "startfile"):
            os.startfile(str(report_path))  # type: ignore[attr-defined]
    except Exception as exc:
        log(f"Could not auto-open report: {exc}")


def main() -> int:
    args = parse_args()
    ensure_directories()
    report_path = OUTPUT_DIR / "report.html"
    try:
        log("Starting isolated futures research...")
        results = collect_and_analyze(args)
        if args.prefetch_only:
            log(
                f"Cache warm-up finished. Symbols seen: {results['symbol_count']}. "
                f"Cache DB: {results['cache_db_path']}"
            )
            return 0
        write_outputs(results)
        log(f"Done. HTML report: {report_path}")
        if not args.no_open:
            try_open_report(report_path)
        return 0
    except KeyboardInterrupt:
        log("Interrupted by user.")
        return 130
    except Exception:
        print()
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
