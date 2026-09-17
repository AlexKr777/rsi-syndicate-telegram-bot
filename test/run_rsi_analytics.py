from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from html import escape
from mimetypes import guess_type
from pathlib import Path
from typing import Any

try:
    import pandas as pd
except ImportError as exc:  # pragma: no cover - environment-dependent
    print(
        "pandas is required for this analytics tool.\n"
        "Use the project's .venv via test\\run_rsi_analytics.bat or install:\n"
        "  pip install -r test\\requirements.txt"
    )
    raise

try:
    from src.core.config import Settings
except Exception:  # pragma: no cover - optional for isolated runs
    Settings = None  # type: ignore[assignment]


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DB_PATH = PROJECT_ROOT / "data" / "rsi_alerts.db"
OUTPUT_DIR = BASE_DIR / "output"
MIN_SAMPLE_SIZE = 30
JOINT_COMBO_MIN_SAMPLE_SIZE = 10
DORDO_COMBO_MIN_SAMPLE_SIZE = 5
OVERDUE_GRACE_MINUTES = 15
NEUTRAL_TOLERANCE_PCT = 0.15
BIG_MOVE_THRESHOLD_PCT = 5.0
TARGET_DELIVERY_USERNAME = "dordo_dordo"
RECENT_WINDOWS_DAYS = [30, 90]
REPORT_TOP_ROWS = 7
REPORT_COMPACT_ROWS = 5
REPORT_DIAGNOSTIC_ROWS = 7
REPORT_METADATA_ROWS = 7
VALIDATION_FLOAT_TOLERANCE = 1e-9
TELEGRAM_REPORT_ENV = "RSI_ANALYTICS_SEND_TELEGRAM"
TELEGRAM_REPORT_TIMEOUT_SECONDS = 60
DEFAULT_STAGE_DEFINITIONS: dict[str, timedelta] = {
    "2h": timedelta(hours=2),
    "4h": timedelta(hours=4),
    "8h": timedelta(hours=8),
}
REPORT_TITLE = "RSI Signal Analytics"
REPORT_TITLE_RU = "Панель аналитики RSI-сигналов"

DISPLAY_METRIC_LABELS = {
    "analysis_run_utc": "Время запуска анализа (UTC)",
    "total_rsi_alerts": "Всего RSI-сигналов",
    "oversold_alerts": "Сигналов на перепроданность",
    "overbought_alerts": "Сигналов на перекупленность",
    "unique_symbols": "Уникальных тикеров",
    "data_start_utc": "Начало исторических данных (UTC)",
    "data_end_utc": "Конец исторических данных (UTC)",
    "stage_followup_rows": "Всего stage follow-up записей",
    "latest_followup_rows_raw": "Записей в latest/final follow-up",
    "latest_followup_rows_available": "Сигналов с доступным последним follow-up",
    "alerts_with_any_stage_followup": "Сигналов с хотя бы одним follow-up",
    "alerts_without_any_stage_followup": "Сигналов без follow-up",
    "alerts_without_latest_followup": "Сигналов без последнего follow-up",
    "alerts_too_fresh_for_first_followup": "Слишком свежих для 1-го follow-up",
    "alerts_missing_first_followup_overdue": "Просроченных без 1-го follow-up",
    "alert_stage_pending_pairs": "Пар alert-stage со статусом pending",
    "alert_stage_missing_overdue_pairs": "Пар alert-stage со статусом missing overdue",
    "alerts_with_any_missing_overdue_stage": "Сигналов, где есть хотя бы один missing overdue stage",
    "latest_followups_big_move_5p_count": "Последних follow-up с результатом 5%+",
    "latest_followups_big_move_5p_rate_of_latest": "Доля 5%+ от всех последних follow-up, %",
    "latest_followups_big_move_5p_rate_of_all_alerts": "Доля 5%+ от всех RSI-сигналов, %",
    "stage_rows_big_move_5p_count": "Stage follow-up строк с результатом 5%+",
    "unique_symbols_big_move_5p": "Уникальных тикеров с результатом 5%+",
    "dordo_user_id": "Telegram user id для @dordo_dordo",
    "dordo_sent_alert_deliveries": "Отправленных live alerts @dordo_dordo",
    "dordo_sent_alert_unique_alerts": "Уникальных live alerts у @dordo_dordo",
    "dordo_sent_alerts_with_latest_followup": "Отправленных live alerts с уже доступным итогом",
    "dordo_sent_alerts_big_move_5p_count": "Отправленных live alerts, дошедших до 5%+",
    "dordo_sent_alerts_big_move_5p_rate": "Доля 5%+ от отправленных live alerts, %",
    "dordo_sent_alerts_big_move_5p_rate_ready": "Доля 5%+ среди отправленных live alerts с доступным итогом, %",
    "dordo_sent_followup_messages": "Реально отправленных follow-up @dordo_dordo",
    "dordo_sent_followup_big_move_5p_count": "Отправленных follow-up с результатом 5%+",
    "dordo_sent_followup_big_move_5p_rate": "Доля 5%+ от отправленных follow-up, %",
}

DISPLAY_COLUMN_LABELS = {
    "metric": "Метрика",
    "value": "Значение",
    "followup_stage": "Когда проверили сигнал",
    "alerts_total": "Всего сигналов",
    "available_results": "Есть результат",
    "pending_count": "Еще рано",
    "missing_overdue_count": "Просрочен и отсутствует",
    "coverage_pct": "Покрытие, %",
    "signal_count": "Сигналов",
    "favorable_count": "Сработало",
    "adverse_count": "Пошло против идеи",
    "neutral_count": "Без явного движения",
    "favorable_rate_pct": "Win rate, %",
    "adverse_rate_pct": "Против идеи, %",
    "neutral_rate_pct": "Нейтрально, %",
    "avg_move_pct": "Средний рыночный ход, %",
    "median_move_pct": "Медианный рыночный ход, %",
    "avg_favorable_move_pct": "Средний ход в плюс, %",
    "avg_adverse_move_pct": "Средний ход против, %",
    "avg_current_rsi": "Средний текущий RSI",
    "median_current_rsi": "Медианный текущий RSI",
    "avg_rsi_delta": "Средний сдвиг RSI",
    "avg_abs_rsi_delta": "Средний модуль сдвига RSI",
    "expectancy": "Edge score",
    "alert_direction": "Тип сигнала",
    "rsi_bucket": "Диапазон RSI",
    "bucket": "Корзина",
    "volume_metric": "Какой фильтр объема",
    "score_bucket": "Диапазон score",
    "metadata_key": "Ключ metadata",
    "row_count": "Строк с ключом",
    "coverage_pct": "Покрытие, %",
    "quote_volume_bucket": "Объем рынка в USDT",
    "volume_ratio_bucket": "Относительный объем",
    "alert_id": "Alert ID",
    "alert_symbol": "Тикер",
    "alert_direction": "Тип сигнала",
    "alert_sent_at": "Время сигнала",
    "stage_due_at": "Когда должен был прийти",
    "stage_overdue_after": "После чего считаем missing",
    "alert_age_hours": "Возраст сигнала, ч",
    "overdue_minutes": "Просрочка, мин",
    "alert_rsi": "RSI в сигнале",
    "alert_score": "Score сигнала",
    "quote_volume": "Объем рынка в USDT",
    "volume_ratio": "Относительный объем",
    "bot_kind": "Бот",
    "content_kind": "Тип доставки",
    "message_kind": "Тип сообщения",
    "delivery_stage": "Стадия follow-up",
    "sent_count": "Реально отправлено",
    "unique_alert_count": "Уникальных сигналов",
    "latest_ready_count": "Есть итоговый follow-up",
    "ready_coverage_pct": "Покрытие итогом, %",
    "take5_hit_count": "Касались +5%, шт",
    "take5_rate_pct": "Касались +5%, %",
    "take5_rate_ready_pct": "Касались +5% среди тех, где уже есть итог, %",
    "stop5_hit_count": "Уходили против идеи на 5%, шт",
    "stop5_rate_pct": "Уходили против идеи на 5%, %",
    "stop5_rate_ready_pct": "Уходили против идеи на 5% среди тех, где уже есть итог, %",
    "take_only_5_hit_count": "Только +5 без -5, шт",
    "take_only_5_hit_rate_pct": "Только +5 без -5, %",
    "stop_only_5_hit_count": "Только -5 против идеи, шт",
    "stop_only_5_hit_rate_pct": "Только -5 против идеи, %",
    "both_5_hit_count": "И +5 и -5 были, шт",
    "both_5_hit_rate_pct": "И +5 и -5 были, %",
    "neither_5_hit_count": "Не дошли ни до +5, ни до -5, шт",
    "neither_5_hit_rate_pct": "Не дошли ни до +5, ни до -5, %",
    "big_move_count": "Дали 5%+ в плюс",
    "big_move_rate_pct": "5%+ в плюс, %",
    "ready_big_move_rate_pct": "5%+ среди тех, где уже есть итог, %",
    "avg_big_move_pct": "Средний плюс среди 5%+, %",
    "median_big_move_pct": "Медианный плюс среди 5%+, %",
    "max_big_move_pct": "Макс. плюс, %",
    "period_label": "Период",
    "path_5_status": "Путь относительно порога 5%",
    "delivered_at": "Когда реально отправили",
    "latest_followup_stage": "Последняя проверка",
    "latest_thesis_result_state": "Чем закончилось",
    "latest_favorable_move_pct": "Макс. ход в плюс, %",
    "latest_adverse_move_pct": "Макс. ход против идеи, %",
    "latest_move_pct": "Финальный move, %",
    "delivery_age_days": "Сколько дней назад отправили",
    "status": "Статус",
    "check_name": "Проверка",
    "details": "Комментарий",
}

DISPLAY_VALUE_LABELS = {
    "oversold": "Перепроданность",
    "overbought": "Перекупленность",
    "favorable": "Успешно",
    "adverse": "Пошло против идеи",
    "neutral": "Без явного движения",
    "quote_volume": "Объем рынка в USDT",
    "volume_ratio": "Относительный объем",
    "pending": "Еще рано",
    "available": "Есть результат",
    "missing_overdue": "Должен быть, но отсутствует",
    "latest_only": "Последний доступный",
    "2h": "Через 2 часа",
    "4h": "Через 4 часа",
    "8h": "Через 8 часов",
    "low": "Низкая",
    "medium": "Средняя",
    "high": "Высокая",
    "mixed": "Смешанный",
    "balanced": "Сбалансированный",
    "active": "Активный",
    "conservative": "Консервативный",
    "majors": "Крупные монеты",
    "altcoins": "Альткоины",
    "memes": "Мем-монеты",
    "closed_trigger": "По закрытой свече",
    "closed_with_live_secondary": "Закрытая свеча + live RSI",
    "ticker_last_price": "Текущий last price",
    "crypto": "Крипто",
    "open": "Открыт",
    "fresh": "Свежий",
    "fallback": "Fallback",
    "premium": "Premium",
    "classic": "Classic",
    "private_pro": "Private Pro",
    "classic_basic": "Classic Basic",
    "all_time": "Вся история",
    "last_30d": "Последние 30 дней",
    "last_90d": "Последние 90 дней",
    "take_only": "Дошли до +5 и не уходили на -5",
    "stop_only": "Уходили на -5 против идеи и не дошли до +5",
    "both_5_hit": "И +5, и -5 были в окно наблюдения",
    "neither_5_hit": "Не дошли ни до +5, ни до -5",
    "true": "Да",
    "false": "Нет",
    "PASS": "OK",
    "WARN": "Внимание",
    "FAIL": "Ошибка",
    "followup_unspecified": "Follow-up без явной стадии",
}

CHART_COLORS = {
    "positive": "#10b981",
    "negative": "#ef4444",
    "neutral": "#94a3b8",
    "blue": "#2563eb",
    "amber": "#f59e0b",
    "indigo": "#6366f1",
    "teal": "#14b8a6",
    "rose": "#f43f5e",
    "cyan": "#06b6d4",
}


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def load_dotenv_values(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith(("\"", "'")) and value.endswith(("\"", "'")) and len(value) >= 2:
            value = value[1:-1]
        values[key] = value
    return values


def resolve_setting_value(name: str) -> str:
    direct = str(os.getenv(name, "")).strip()
    if direct:
        return direct

    dotenv_values = load_dotenv_values(PROJECT_ROOT / ".env")
    from_dotenv = str(dotenv_values.get(name, "")).strip()
    if from_dotenv:
        return from_dotenv

    if Settings is not None:
        try:
            settings = Settings()
            if name == "TELEGRAM_BOT_TOKEN":
                return str(settings.telegram_bot_token).strip()
        except Exception:
            return ""
    return ""


def resolve_premium_bot_token() -> str:
    return resolve_setting_value("TELEGRAM_BOT_TOKEN")


def connect_read_only(db_path: Path) -> sqlite3.Connection:
    resolved = db_path.resolve()
    uri = f"file:{resolved.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only = 1")
    return connection


def read_sql(connection: sqlite3.Connection, query: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    return pd.read_sql_query(query, connection, params=params or {})


def discover_table_columns(connection: sqlite3.Connection, table_name: str) -> list[str]:
    cursor = connection.execute(f"PRAGMA table_info({table_name})")
    return [str(row[1]) for row in cursor.fetchall()]


def safe_json_loads(raw_value: Any) -> dict[str, Any]:
    if raw_value in (None, "", b""):
        return {}
    try:
        parsed = json.loads(raw_value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def expand_json_column(
    frame: pd.DataFrame,
    source_column: str,
    *,
    prefix: str,
) -> tuple[pd.DataFrame, Counter[str]]:
    if source_column not in frame.columns:
        return frame.copy(), Counter()

    parsed_series = frame[source_column].map(safe_json_loads)
    key_counts: Counter[str] = Counter()
    for item in parsed_series:
        key_counts.update(item.keys())

    if parsed_series.empty:
        return frame.copy(), key_counts

    expanded = pd.json_normalize(parsed_series)
    if expanded.empty:
        result = frame.copy()
        result[source_column] = parsed_series
        return result, key_counts

    expanded = expanded.rename(columns={column: f"{prefix}{column}" for column in expanded.columns})
    result = pd.concat([frame.reset_index(drop=True), expanded.reset_index(drop=True)], axis=1)
    return result, key_counts


def coerce_datetime_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column in result.columns:
            result[column] = pd.to_datetime(result[column], utc=True, errors="coerce")
    return result


def coerce_numeric_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def clean_text_series(series: pd.Series | None) -> pd.Series:
    if series is None:
        return pd.Series(dtype="object")
    normalized = series.astype("string").str.strip()
    normalized = normalized.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "<NA>": pd.NA})
    return normalized


def evaluate_thesis(direction: str, move_pct: float, neutral_tolerance: float = NEUTRAL_TOLERANCE_PCT) -> tuple[str, float, float]:
    normalized_direction = str(direction or "").strip().lower()
    safe_move = float(move_pct) if pd.notna(move_pct) else 0.0

    if normalized_direction in {"oversold", "long"}:
        favorable = max(safe_move, 0.0)
        adverse = max(-safe_move, 0.0)
    elif normalized_direction in {"overbought", "short"}:
        favorable = max(-safe_move, 0.0)
        adverse = max(safe_move, 0.0)
    else:
        favorable = 0.0
        adverse = 0.0

    if favorable > neutral_tolerance and favorable >= adverse:
        state = "favorable"
    elif adverse > neutral_tolerance and adverse > favorable:
        state = "adverse"
    else:
        state = "neutral"
    return state, favorable, adverse


def stage_sort_key(stage_name: str, stage_definitions: dict[str, timedelta]) -> tuple[float, str]:
    if stage_name in stage_definitions:
        return (stage_definitions[stage_name].total_seconds(), stage_name)
    match = re.match(r"^\s*(\d+)\s*h\s*$", str(stage_name or ""), flags=re.IGNORECASE)
    if match:
        return (float(match.group(1)) * 3600.0, str(stage_name))
    return (float("inf"), str(stage_name))


def detect_stage_definitions(distinct_stages: list[str]) -> dict[str, timedelta]:
    definitions = dict(DEFAULT_STAGE_DEFINITIONS)
    for stage_name in distinct_stages:
        if stage_name in definitions:
            continue
        match = re.match(r"^\s*(\d+)\s*h\s*$", str(stage_name or ""), flags=re.IGNORECASE)
        if match:
            definitions[stage_name] = timedelta(hours=int(match.group(1)))
    return definitions


def bucket_rsi(direction: str, rsi_value: float) -> str | None:
    if pd.isna(rsi_value):
        return None
    value = float(rsi_value)
    normalized_direction = str(direction or "").strip().lower()
    if normalized_direction == "oversold":
        if value <= 20:
            return "<=20"
        if value < 25:
            return "20-24.99"
        if value < 28:
            return "25-27.99"
        if value <= 30:
            return "28-30.00"
        if value <= 33:
            return "30-33.00"
        return ">33"
    if normalized_direction == "overbought":
        if value < 67:
            return "<67"
        if value < 70:
            return "67-69.99"
        if value < 73:
            return "70-72.99"
        if value < 76:
            return "73-75.99"
        if value < 80:
            return "76-79.99"
        return "80+"
    return None


def bucket_quote_volume(volume_value: float) -> str | None:
    if pd.isna(volume_value):
        return None
    value = float(volume_value)
    if value < 1_000_000:
        return "<1M"
    if value < 5_000_000:
        return "1M-5M"
    if value < 20_000_000:
        return "5M-20M"
    if value < 50_000_000:
        return "20M-50M"
    return "50M+"


def bucket_volume_ratio(volume_ratio_value: float) -> str | None:
    if pd.isna(volume_ratio_value):
        return None
    value = float(volume_ratio_value)
    if value < 1.0:
        return "<1.0"
    if value < 1.5:
        return "1.0-1.49"
    if value < 2.0:
        return "1.5-1.99"
    if value < 3.0:
        return "2.0-2.99"
    return "3.0+"


def bucket_score(score_value: float) -> str | None:
    if pd.isna(score_value):
        return None
    value = float(score_value)
    if value < 60:
        return "<60"
    if value < 70:
        return "60-69"
    if value < 80:
        return "70-79"
    if value < 90:
        return "80-89"
    return "90+"


def bucket_confidence(score_value: float) -> str | None:
    if pd.isna(score_value):
        return None
    value = float(score_value)
    if value < 40:
        return "<40"
    if value < 60:
        return "40-59"
    if value < 80:
        return "60-79"
    return "80+"


def quantile_bucket(series: pd.Series, q: int = 4) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    valid = numeric.dropna()
    if valid.empty or valid.nunique() < 2:
        return pd.Series(pd.NA, index=series.index, dtype="string")

    bucket_count = min(q, int(valid.nunique()))
    if bucket_count < 2:
        return pd.Series(pd.NA, index=series.index, dtype="string")

    try:
        bucketed = pd.qcut(valid, q=bucket_count, duplicates="drop")
    except ValueError:
        return pd.Series(pd.NA, index=series.index, dtype="string")

    as_text = bucketed.astype("string")
    result = pd.Series(pd.NA, index=series.index, dtype="string")
    result.loc[valid.index] = as_text
    return result


def build_metric_rows(pairs: list[tuple[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(pairs, columns=["metric", "value"])


def summarize_outcomes(
    frame: pd.DataFrame,
    group_columns: list[str],
    *,
    count_label: str = "signal_count",
) -> pd.DataFrame:
    if frame.empty:
        columns = [
            *group_columns,
            count_label,
            "favorable_count",
            "adverse_count",
            "neutral_count",
            "favorable_rate_pct",
            "adverse_rate_pct",
            "neutral_rate_pct",
            "avg_move_pct",
            "median_move_pct",
            "avg_favorable_move_pct",
            "avg_adverse_move_pct",
            "avg_current_rsi",
            "median_current_rsi",
            "avg_rsi_delta",
            "avg_abs_rsi_delta",
            "expectancy",
        ]
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    grouped = frame.groupby(group_columns, dropna=False, sort=False)
    for group_key, group_frame in grouped:
        if not isinstance(group_key, tuple):
            group_key = (group_key,)
        row = {column: value for column, value in zip(group_columns, group_key)}
        total = int(len(group_frame))
        favorable_count = int((group_frame["thesis_result_state"] == "favorable").sum())
        adverse_count = int((group_frame["thesis_result_state"] == "adverse").sum())
        neutral_count = int((group_frame["thesis_result_state"] == "neutral").sum())
        favorable_rate = (favorable_count / total * 100.0) if total else 0.0
        adverse_rate = (adverse_count / total * 100.0) if total else 0.0
        neutral_rate = (neutral_count / total * 100.0) if total else 0.0
        avg_favorable_move = float(group_frame["favorable_move_pct"].mean()) if "favorable_move_pct" in group_frame.columns else float("nan")
        avg_adverse_move = float(group_frame["adverse_move_pct"].mean()) if "adverse_move_pct" in group_frame.columns else float("nan")
        expectancy = (favorable_rate / 100.0) * avg_favorable_move - (adverse_rate / 100.0) * avg_adverse_move
        row.update(
            {
                count_label: total,
                "favorable_count": favorable_count,
                "adverse_count": adverse_count,
                "neutral_count": neutral_count,
                "favorable_rate_pct": favorable_rate,
                "adverse_rate_pct": adverse_rate,
                "neutral_rate_pct": neutral_rate,
                "avg_move_pct": float(group_frame["followup_move_pct"].mean()),
                "median_move_pct": float(group_frame["followup_move_pct"].median()),
                "avg_favorable_move_pct": avg_favorable_move,
                "avg_adverse_move_pct": avg_adverse_move,
                "avg_current_rsi": float(group_frame["followup_current_rsi"].mean()) if "followup_current_rsi" in group_frame.columns else float("nan"),
                "median_current_rsi": float(group_frame["followup_current_rsi"].median()) if "followup_current_rsi" in group_frame.columns else float("nan"),
                "avg_rsi_delta": float(group_frame["rsi_delta"].mean()) if "rsi_delta" in group_frame.columns else float("nan"),
                "avg_abs_rsi_delta": float(group_frame["abs_rsi_delta"].mean()) if "abs_rsi_delta" in group_frame.columns else float("nan"),
                "expectancy": expectancy,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def add_bucket_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["rsi_bucket"] = [
        bucket_rsi(direction, rsi_value)
        for direction, rsi_value in zip(result["alert_direction"], result["alert_rsi"], strict=False)
    ]
    result["quote_volume_bucket"] = result["quote_volume"].map(bucket_quote_volume) if "quote_volume" in result.columns else None
    result["volume_ratio_bucket"] = result["volume_ratio"].map(bucket_volume_ratio) if "volume_ratio" in result.columns else None
    result["score_bucket"] = result["alert_score"].map(bucket_score) if "alert_score" in result.columns else None
    result["confidence_bucket"] = result["confidence_score"].map(bucket_confidence) if "confidence_score" in result.columns else None
    return result


def prepare_alerts(connection: sqlite3.Connection) -> tuple[pd.DataFrame, Counter[str]]:
    alerts = read_sql(
        connection,
        """
        SELECT
            id AS alert_id,
            symbol AS alert_symbol,
            direction AS alert_direction,
            timeframe AS alert_timeframe,
            candle_open_time AS alert_candle_open_time,
            candle_close_time AS alert_candle_close_time,
            alert_price,
            alert_rsi,
            day_change_pct AS alert_day_change_pct,
            day_volume AS alert_day_volume,
            score AS alert_score,
            alert_sent_at,
            followup_due_at AS alert_followup_due_at,
            followup_sent_at AS alert_followup_sent_at,
            metadata_json AS alert_metadata_json
        FROM alerts
        WHERE strategy_key = 'rsi'
        ORDER BY id ASC
        """,
    )
    alerts, metadata_keys = expand_json_column(alerts, "alert_metadata_json", prefix="alert_meta_")
    alerts = coerce_datetime_columns(
        alerts,
        [
            "alert_candle_open_time",
            "alert_candle_close_time",
            "alert_sent_at",
            "alert_followup_due_at",
            "alert_followup_sent_at",
            "alert_meta_signal_candle_close_time",
            "alert_meta_expiry_at",
        ],
    )
    alerts = coerce_numeric_columns(
        alerts,
        [
            "alert_price",
            "alert_rsi",
            "alert_day_change_pct",
            "alert_day_volume",
            "alert_score",
            "alert_meta_quote_volume",
            "alert_meta_volume_ratio",
            "alert_meta_atr_pct",
            "alert_meta_closed_rsi",
            "alert_meta_live_rsi",
            "alert_meta_live_price",
            "alert_meta_signal_close_price",
            "alert_meta_benchmark_win_percent",
            "alert_meta_invalidation_price",
            "alert_meta_tp_price_primary",
            "alert_meta_tp_price_secondary",
            "alert_meta_entry_zone_low",
            "alert_meta_entry_zone_high",
            "alert_meta_confidence_score",
            "alert_meta_target_rr",
            "alert_meta_near_tp_progress",
        ],
    )
    alerts["quote_volume"] = alerts.get("alert_meta_quote_volume")
    alerts["volume_ratio"] = alerts.get("alert_meta_volume_ratio")
    alerts["atr_pct"] = alerts.get("alert_meta_atr_pct")
    alerts["signal_live_rsi"] = alerts.get("alert_meta_live_rsi")
    alerts["signal_closed_rsi"] = alerts.get("alert_meta_closed_rsi")
    alerts["market_regime_tag"] = clean_text_series(alerts.get("alert_meta_market_regime_tag"))
    alerts["liquidity_tag"] = clean_text_series(alerts.get("alert_meta_liquidity_tag"))
    alerts["setup_quality"] = clean_text_series(alerts.get("alert_meta_setup_quality"))
    alerts["asset_cluster_tag"] = clean_text_series(alerts.get("alert_meta_asset_cluster_tag"))
    alerts["signal_status"] = clean_text_series(alerts.get("alert_meta_signal_status"))
    alerts["signal_rsi_mode"] = clean_text_series(alerts.get("alert_meta_rsi_mode"))
    alerts["asset_class"] = clean_text_series(alerts.get("alert_meta_asset_class"))
    alerts["result_type"] = clean_text_series(alerts.get("alert_meta_result_type"))
    alerts["lifecycle_source_type"] = clean_text_series(alerts.get("alert_meta_lifecycle_source_type"))
    alerts["invalidation_source"] = clean_text_series(alerts.get("alert_meta_invalidation_source"))
    alerts["target_model"] = clean_text_series(alerts.get("alert_meta_target_model"))
    alerts["benchmark_win_percent"] = alerts.get("alert_meta_benchmark_win_percent")
    alerts["confidence_score"] = alerts.get("alert_meta_confidence_score")
    alerts["target_rr"] = alerts.get("alert_meta_target_rr")
    alerts["near_tp_progress"] = alerts.get("alert_meta_near_tp_progress")
    alerts["preview_flag"] = alerts.get("alert_meta_preview")
    return alerts, metadata_keys


def prepare_followups(
    connection: sqlite3.Connection,
    *,
    source_table: str,
) -> tuple[pd.DataFrame, Counter[str]]:
    if source_table == "followup_stage_results":
        query = """
            SELECT
                fs.id AS followup_row_id,
                fs.alert_id,
                fs.stage AS followup_stage,
                fs.symbol AS followup_symbol,
                fs.direction AS followup_direction,
                fs.timeframe AS followup_timeframe,
                fs.alert_price AS followup_alert_price,
                fs.alert_rsi AS followup_alert_rsi,
                fs.score AS followup_score,
                fs.current_price AS followup_current_price,
                fs.current_rsi AS followup_current_rsi,
                fs.move_pct AS followup_move_pct,
                fs.summary AS followup_summary,
                fs.observed_at AS followup_observed_at,
                fs.metadata_json AS followup_metadata_json
            FROM followup_stage_results fs
            JOIN alerts a ON a.id = fs.alert_id
            WHERE a.strategy_key = 'rsi'
            ORDER BY fs.id ASC
        """
    elif source_table == "followup_results":
        query = """
            SELECT
                NULL AS followup_row_id,
                fr.alert_id,
                NULL AS followup_stage,
                fr.symbol AS followup_symbol,
                fr.direction AS followup_direction,
                fr.timeframe AS followup_timeframe,
                fr.alert_price AS followup_alert_price,
                fr.alert_rsi AS followup_alert_rsi,
                fr.score AS followup_score,
                fr.current_price AS followup_current_price,
                fr.current_rsi AS followup_current_rsi,
                fr.move_pct AS followup_move_pct,
                fr.summary AS followup_summary,
                fr.observed_at AS followup_observed_at,
                fr.metadata_json AS followup_metadata_json
            FROM followup_results fr
            JOIN alerts a ON a.id = fr.alert_id
            WHERE a.strategy_key = 'rsi'
            ORDER BY fr.alert_id ASC
        """
    else:
        raise ValueError(f"Unsupported source table: {source_table}")

    followups = read_sql(connection, query)
    followups["followup_source_table"] = source_table
    followups, metadata_keys = expand_json_column(followups, "followup_metadata_json", prefix="followup_meta_")
    followups = coerce_datetime_columns(
        followups,
        [
            "followup_observed_at",
            "followup_meta_marker_candle_open_time",
            "followup_meta_marker_candle_close_time",
            "followup_meta_signal_candle_close_time",
        ],
    )
    followups = coerce_numeric_columns(
        followups,
        [
            "followup_alert_price",
            "followup_alert_rsi",
            "followup_score",
            "followup_current_price",
            "followup_current_rsi",
            "followup_move_pct",
            "followup_meta_favorable_move_pct",
            "followup_meta_adverse_move_pct",
            "followup_meta_24h_change_pct",
            "followup_meta_current_candle_close_price",
            "followup_meta_candle_move_pct",
            "followup_meta_live_rsi",
            "followup_meta_elapsed_seconds",
            "followup_meta_marker_price",
        ],
    )

    followups["followup_stage"] = clean_text_series(followups.get("followup_stage"))
    followups["followup_stage"] = followups["followup_stage"].fillna(clean_text_series(followups.get("followup_meta_followup_stage")))
    followups["followup_stage"] = followups["followup_stage"].fillna(clean_text_series(followups.get("followup_meta_stage")))
    followups["followup_stage"] = followups["followup_stage"].fillna("latest_only")

    fallback_values = followups.apply(
        lambda row: evaluate_thesis(str(row.get("followup_direction") or ""), float(row.get("followup_move_pct") or 0.0)),
        axis=1,
    )
    followups["thesis_result_state"] = clean_text_series(followups.get("followup_meta_thesis_result_state"))
    followups["thesis_result_state"] = followups["thesis_result_state"].fillna(fallback_values.map(lambda item: item[0]))
    followups["favorable_move_pct"] = pd.to_numeric(followups.get("followup_meta_favorable_move_pct"), errors="coerce")
    followups["adverse_move_pct"] = pd.to_numeric(followups.get("followup_meta_adverse_move_pct"), errors="coerce")
    followups["favorable_move_pct"] = followups["favorable_move_pct"].fillna(fallback_values.map(lambda item: item[1]))
    followups["adverse_move_pct"] = followups["adverse_move_pct"].fillna(fallback_values.map(lambda item: item[2]))
    followups["followup_candle_move_pct"] = pd.to_numeric(followups.get("followup_meta_candle_move_pct"), errors="coerce")
    followups["followup_live_rsi_meta"] = pd.to_numeric(followups.get("followup_meta_live_rsi"), errors="coerce")
    followups["followup_market_price_source"] = clean_text_series(followups.get("followup_meta_current_market_price_source"))
    followups["followup_rsi_mode"] = clean_text_series(followups.get("followup_meta_rsi_mode"))
    followups["followup_24h_change_pct"] = pd.to_numeric(followups.get("followup_meta_24h_change_pct"), errors="coerce")
    followups["followup_elapsed_seconds_meta"] = pd.to_numeric(followups.get("followup_meta_elapsed_seconds"), errors="coerce")
    return followups, metadata_keys


def prepare_delivered_bot_signals(connection: sqlite3.Connection) -> tuple[pd.DataFrame, Counter[str]]:
    query = """
        SELECT
            d.id AS delivery_id,
            d.telegram_user_id,
            u.username AS delivery_username,
            d.bot_kind,
            d.alert_id,
            d.content_kind,
            d.message_kind,
            d.telegram_message_id,
            d.delivered_at,
            d.metadata_json AS delivery_metadata_json
        FROM delivered_bot_signals d
        JOIN alerts a ON a.id = d.alert_id
        LEFT JOIN bot_users u ON u.telegram_user_id = d.telegram_user_id
        WHERE a.strategy_key = 'rsi'
        ORDER BY d.id ASC
    """
    deliveries = read_sql(connection, query)
    deliveries, metadata_keys = expand_json_column(deliveries, "delivery_metadata_json", prefix="delivery_meta_")
    deliveries = coerce_datetime_columns(deliveries, ["delivered_at"])
    deliveries = coerce_numeric_columns(
        deliveries,
        [
            "telegram_user_id",
            "alert_id",
            "telegram_message_id",
            "delivery_meta_score",
            "delivery_meta_favorable_move_pct",
            "delivery_meta_adverse_move_pct",
            "delivery_meta_move_pct",
        ],
    )
    deliveries["delivery_username"] = clean_text_series(deliveries.get("delivery_username"))
    deliveries["content_kind"] = clean_text_series(deliveries.get("content_kind"))
    deliveries["message_kind"] = clean_text_series(deliveries.get("message_kind"))
    deliveries["delivery_stage"] = clean_text_series(deliveries.get("delivery_meta_stage"))
    deliveries["delivery_stage"] = deliveries["delivery_stage"].fillna(
        deliveries["message_kind"].map(extract_stage_from_message_kind)
    )
    deliveries["delivery_thesis_result_state"] = clean_text_series(deliveries.get("delivery_meta_thesis_result_state"))
    deliveries["delivery_favorable_move_pct"] = pd.to_numeric(deliveries.get("delivery_meta_favorable_move_pct"), errors="coerce")
    deliveries["delivery_adverse_move_pct"] = pd.to_numeric(deliveries.get("delivery_meta_adverse_move_pct"), errors="coerce")
    deliveries["delivery_move_pct"] = pd.to_numeric(deliveries.get("delivery_meta_move_pct"), errors="coerce")
    deliveries["delivery_sent"] = deliveries.get("delivery_meta_sent").map(normalize_bool)
    deliveries["delivery_sent"] = deliveries["delivery_sent"].fillna(False).astype(bool)
    deliveries["delivery_is_followup"] = deliveries["message_kind"].map(
        lambda value: str(value or "").strip().lower().startswith("followup")
    )
    deliveries["delivery_is_alert"] = deliveries["message_kind"].map(
        lambda value: str(value or "").strip().lower() == "alert"
    )
    deliveries.loc[
        deliveries["delivery_is_followup"] & deliveries["delivery_stage"].isna(),
        "delivery_stage",
    ] = "followup_unspecified"
    return deliveries, metadata_keys


def extract_stage_from_message_kind(message_kind: Any) -> str | None:
    normalized = str(message_kind or "").strip().lower()
    if normalized.startswith("followup:"):
        suffix = normalized.split(":", 1)[1].strip()
        return suffix or None
    return None


def normalize_bool(value: Any) -> bool | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def attach_alert_context(followups: pd.DataFrame, alerts: pd.DataFrame) -> pd.DataFrame:
    join_columns = [
        "alert_id",
        "alert_symbol",
        "alert_direction",
        "alert_timeframe",
        "alert_price",
        "alert_rsi",
        "alert_score",
        "alert_sent_at",
        "alert_day_change_pct",
        "alert_day_volume",
        "quote_volume",
        "volume_ratio",
        "atr_pct",
        "signal_live_rsi",
        "signal_closed_rsi",
        "market_regime_tag",
        "liquidity_tag",
        "setup_quality",
        "asset_cluster_tag",
        "signal_status",
        "signal_rsi_mode",
        "asset_class",
        "result_type",
        "lifecycle_source_type",
        "invalidation_source",
        "target_model",
        "benchmark_win_percent",
        "confidence_score",
        "target_rr",
        "near_tp_progress",
        "preview_flag",
    ]
    available_columns = [column for column in join_columns if column in alerts.columns]
    merged = followups.merge(alerts[available_columns], on="alert_id", how="left", copy=False)
    merged["rsi_delta"] = merged["followup_current_rsi"] - merged["alert_rsi"]
    merged["abs_rsi_delta"] = merged["rsi_delta"].abs()
    return merged


def attach_delivery_context(
    deliveries: pd.DataFrame,
    alerts: pd.DataFrame,
    latest_followups: pd.DataFrame,
) -> pd.DataFrame:
    if deliveries.empty:
        return deliveries.copy()

    alert_columns = [
        "alert_id",
        "alert_symbol",
        "alert_direction",
        "alert_sent_at",
        "alert_score",
        "alert_rsi",
        "quote_volume",
        "volume_ratio",
    ]
    available_alert_columns = [column for column in alert_columns if column in alerts.columns]
    merged = deliveries.merge(alerts[available_alert_columns], on="alert_id", how="left", copy=False)

    latest_columns = [
        "alert_id",
        "followup_stage",
        "followup_observed_at",
        "thesis_result_state",
        "favorable_move_pct",
        "adverse_move_pct",
        "followup_move_pct",
    ]
    available_latest_columns = [column for column in latest_columns if column in latest_followups.columns]
    merged = merged.merge(
        latest_followups[available_latest_columns].rename(
            columns={
                "followup_stage": "latest_followup_stage",
                "followup_observed_at": "latest_followup_observed_at",
                "thesis_result_state": "latest_thesis_result_state",
                "favorable_move_pct": "latest_favorable_move_pct",
                "adverse_move_pct": "latest_adverse_move_pct",
                "followup_move_pct": "latest_move_pct",
            }
        ),
        on="alert_id",
        how="left",
        copy=False,
    )
    return merged


def resolve_delivery_target_user_id(connection: sqlite3.Connection, username: str) -> int | None:
    query = """
        SELECT telegram_user_id
        FROM bot_users
        WHERE lower(coalesce(username, '')) = lower(:username)
        ORDER BY last_seen_at DESC
        LIMIT 1
    """
    rows = read_sql(connection, query, {"username": username})
    if rows.empty:
        return None
    value = rows.iloc[0]["telegram_user_id"]
    if pd.isna(value):
        return None
    return int(value)


def build_big_move_flags(frame: pd.DataFrame, *, state_column: str, favorable_column: str) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype="bool")
    favorable = pd.to_numeric(frame.get(favorable_column), errors="coerce")
    state = clean_text_series(frame.get(state_column))
    return state.eq("favorable") & favorable.ge(BIG_MOVE_THRESHOLD_PCT)


def add_take_stop_proxy_columns(
    frame: pd.DataFrame,
    *,
    favorable_column: str,
    adverse_column: str,
) -> pd.DataFrame:
    result = frame.copy()
    favorable = pd.to_numeric(result.get(favorable_column), errors="coerce")
    adverse = pd.to_numeric(result.get(adverse_column), errors="coerce")
    take_hit = favorable.ge(BIG_MOVE_THRESHOLD_PCT).fillna(False)
    stop_hit = adverse.ge(BIG_MOVE_THRESHOLD_PCT).fillna(False)
    result["take5_hit"] = take_hit
    result["stop5_hit"] = stop_hit
    result["take_only_5_hit"] = take_hit & ~stop_hit
    result["stop_only_5_hit"] = stop_hit & ~take_hit
    result["both_5_hit"] = take_hit & stop_hit
    result["neither_5_hit"] = ~(take_hit | stop_hit)
    result["path_5_status"] = "neither_5_hit"
    result.loc[result["take_only_5_hit"], "path_5_status"] = "take_only"
    result.loc[result["stop_only_5_hit"], "path_5_status"] = "stop_only"
    result.loc[result["both_5_hit"], "path_5_status"] = "both_5_hit"
    return result


def iter_group_rows(frame: pd.DataFrame, group_columns: list[str]) -> list[tuple[tuple[Any, ...], pd.DataFrame]]:
    if not group_columns:
        return [(tuple(), frame)]
    grouped = frame.groupby(group_columns, dropna=False, sort=False)
    rows: list[tuple[tuple[Any, ...], pd.DataFrame]] = []
    for group_key, group_frame in grouped:
        if not isinstance(group_key, tuple):
            group_key = (group_key,)
        rows.append((group_key, group_frame))
    return rows


def build_outcome_path_stats(
    frame: pd.DataFrame,
    group_columns: list[str],
    *,
    count_label: str = "signal_count",
) -> pd.DataFrame:
    columns = [
        *group_columns,
        count_label,
        "favorable_count",
        "adverse_count",
        "neutral_count",
        "favorable_rate_pct",
        "adverse_rate_pct",
        "neutral_rate_pct",
        "take5_hit_count",
        "take5_rate_pct",
        "stop5_hit_count",
        "stop5_rate_pct",
        "take_only_5_hit_count",
        "take_only_5_hit_rate_pct",
        "stop_only_5_hit_count",
        "stop_only_5_hit_rate_pct",
        "both_5_hit_count",
        "both_5_hit_rate_pct",
        "neither_5_hit_count",
        "neither_5_hit_rate_pct",
        "avg_move_pct",
        "median_move_pct",
        "avg_favorable_move_pct",
        "avg_adverse_move_pct",
        "expectancy",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    for group_key, group_frame in iter_group_rows(frame, group_columns):
        row = {column: value for column, value in zip(group_columns, group_key)}
        state = clean_text_series(group_frame.get("thesis_result_state"))
        total = int(len(group_frame))
        favorable_count = int(state.eq("favorable").sum())
        adverse_count = int(state.eq("adverse").sum())
        neutral_count = int(state.eq("neutral").sum())
        take5_count = int(group_frame["take5_hit"].sum()) if "take5_hit" in group_frame.columns else 0
        stop5_count = int(group_frame["stop5_hit"].sum()) if "stop5_hit" in group_frame.columns else 0
        take_only_count = int(group_frame["take_only_5_hit"].sum()) if "take_only_5_hit" in group_frame.columns else 0
        stop_only_count = int(group_frame["stop_only_5_hit"].sum()) if "stop_only_5_hit" in group_frame.columns else 0
        both_count = int(group_frame["both_5_hit"].sum()) if "both_5_hit" in group_frame.columns else 0
        neither_count = int(group_frame["neither_5_hit"].sum()) if "neither_5_hit" in group_frame.columns else 0
        favorable_rate = (favorable_count / total * 100.0) if total else 0.0
        adverse_rate = (adverse_count / total * 100.0) if total else 0.0
        neutral_rate = (neutral_count / total * 100.0) if total else 0.0
        avg_favorable_move = float(pd.to_numeric(group_frame.get("favorable_move_pct"), errors="coerce").mean())
        avg_adverse_move = float(pd.to_numeric(group_frame.get("adverse_move_pct"), errors="coerce").mean())
        expectancy = (favorable_rate / 100.0) * avg_favorable_move - (adverse_rate / 100.0) * avg_adverse_move
        row.update(
            {
                count_label: total,
                "favorable_count": favorable_count,
                "adverse_count": adverse_count,
                "neutral_count": neutral_count,
                "favorable_rate_pct": favorable_rate,
                "adverse_rate_pct": adverse_rate,
                "neutral_rate_pct": neutral_rate,
                "take5_hit_count": take5_count,
                "take5_rate_pct": (take5_count / total * 100.0) if total else 0.0,
                "stop5_hit_count": stop5_count,
                "stop5_rate_pct": (stop5_count / total * 100.0) if total else 0.0,
                "take_only_5_hit_count": take_only_count,
                "take_only_5_hit_rate_pct": (take_only_count / total * 100.0) if total else 0.0,
                "stop_only_5_hit_count": stop_only_count,
                "stop_only_5_hit_rate_pct": (stop_only_count / total * 100.0) if total else 0.0,
                "both_5_hit_count": both_count,
                "both_5_hit_rate_pct": (both_count / total * 100.0) if total else 0.0,
                "neither_5_hit_count": neither_count,
                "neither_5_hit_rate_pct": (neither_count / total * 100.0) if total else 0.0,
                "avg_move_pct": float(pd.to_numeric(group_frame.get("followup_move_pct"), errors="coerce").mean()),
                "median_move_pct": float(pd.to_numeric(group_frame.get("followup_move_pct"), errors="coerce").median()),
                "avg_favorable_move_pct": avg_favorable_move,
                "avg_adverse_move_pct": avg_adverse_move,
                "expectancy": expectancy,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def build_joint_condition_stats(
    frame: pd.DataFrame,
    group_columns: list[str],
    *,
    min_sample_size: int = JOINT_COMBO_MIN_SAMPLE_SIZE,
) -> pd.DataFrame:
    filtered = frame.copy()
    for column in group_columns:
        filtered = filtered[filtered[column].notna()]
    stats = build_outcome_path_stats(filtered, group_columns)
    if not stats.empty and min_sample_size > 1 and "signal_count" in stats.columns:
        stats = stats[stats["signal_count"] >= min_sample_size].copy()
    return stats.sort_values(
        ["favorable_rate_pct", "take5_rate_pct", "expectancy", "signal_count"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)


def build_big_move_group_stats(
    frame: pd.DataFrame,
    group_columns: list[str],
) -> pd.DataFrame:
    columns = [
        *group_columns,
        "signal_count",
        "big_move_count",
        "big_move_rate_pct",
        "avg_big_move_pct",
        "median_big_move_pct",
        "max_big_move_pct",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    grouped = frame.groupby(group_columns, dropna=False, sort=False)
    for group_key, group_frame in grouped:
        if not isinstance(group_key, tuple):
            group_key = (group_key,)
        row = {column: value for column, value in zip(group_columns, group_key)}
        qualified = group_frame[group_frame["is_big_move"]].copy()
        signal_count = int(len(group_frame))
        big_move_count = int(len(qualified))
        row.update(
            {
                "signal_count": signal_count,
                "big_move_count": big_move_count,
                "big_move_rate_pct": (big_move_count / signal_count * 100.0) if signal_count else 0.0,
                "avg_big_move_pct": float(qualified["big_move_value"].mean()) if big_move_count else float("nan"),
                "median_big_move_pct": float(qualified["big_move_value"].median()) if big_move_count else float("nan"),
                "max_big_move_pct": float(qualified["big_move_value"].max()) if big_move_count else float("nan"),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def build_sent_alert_big_move_stats(
    frame: pd.DataFrame,
    group_columns: list[str],
) -> pd.DataFrame:
    columns = [
        *group_columns,
        "sent_count",
        "unique_alert_count",
        "latest_ready_count",
        "big_move_count",
        "big_move_rate_pct",
        "ready_big_move_rate_pct",
        "avg_big_move_pct",
        "median_big_move_pct",
        "max_big_move_pct",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    grouped = frame.groupby(group_columns, dropna=False, sort=False)
    for group_key, group_frame in grouped:
        if not isinstance(group_key, tuple):
            group_key = (group_key,)
        row = {column: value for column, value in zip(group_columns, group_key)}
        ready = group_frame[group_frame["latest_followup_observed_at"].notna()].copy()
        qualified = ready[ready["is_big_move"]].copy()
        sent_count = int(len(group_frame))
        latest_ready_count = int(len(ready))
        big_move_count = int(len(qualified))
        row.update(
            {
                "sent_count": sent_count,
                "unique_alert_count": int(group_frame["alert_id"].nunique()),
                "latest_ready_count": latest_ready_count,
                "big_move_count": big_move_count,
                "big_move_rate_pct": (big_move_count / sent_count * 100.0) if sent_count else 0.0,
                "ready_big_move_rate_pct": (big_move_count / latest_ready_count * 100.0) if latest_ready_count else 0.0,
                "avg_big_move_pct": float(qualified["latest_favorable_move_pct"].mean()) if big_move_count else float("nan"),
                "median_big_move_pct": float(qualified["latest_favorable_move_pct"].median()) if big_move_count else float("nan"),
                "max_big_move_pct": float(qualified["latest_favorable_move_pct"].max()) if big_move_count else float("nan"),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def build_sent_alert_outcome_stats(
    frame: pd.DataFrame,
    group_columns: list[str],
    *,
    min_sample_size: int = 1,
) -> pd.DataFrame:
    columns = [
        *group_columns,
        "sent_count",
        "unique_alert_count",
        "latest_ready_count",
        "ready_coverage_pct",
        "favorable_count",
        "adverse_count",
        "neutral_count",
        "favorable_rate_pct",
        "adverse_rate_pct",
        "neutral_rate_pct",
        "take5_hit_count",
        "take5_rate_ready_pct",
        "stop5_hit_count",
        "stop5_rate_ready_pct",
        "take_only_5_hit_count",
        "take_only_5_hit_rate_pct",
        "stop_only_5_hit_count",
        "stop_only_5_hit_rate_pct",
        "both_5_hit_count",
        "both_5_hit_rate_pct",
        "neither_5_hit_count",
        "neither_5_hit_rate_pct",
        "avg_move_pct",
        "avg_favorable_move_pct",
        "avg_adverse_move_pct",
        "expectancy",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    for group_key, group_frame in iter_group_rows(frame, group_columns):
        row = {column: value for column, value in zip(group_columns, group_key)}
        ready = group_frame[group_frame["latest_followup_observed_at"].notna()].copy()
        ready_count = int(len(ready))
        state = clean_text_series(ready.get("latest_thesis_result_state"))
        favorable_count = int(state.eq("favorable").sum())
        adverse_count = int(state.eq("adverse").sum())
        neutral_count = int(state.eq("neutral").sum())
        take5_count = int(ready["take5_hit"].sum()) if "take5_hit" in ready.columns else 0
        stop5_count = int(ready["stop5_hit"].sum()) if "stop5_hit" in ready.columns else 0
        take_only_count = int(ready["take_only_5_hit"].sum()) if "take_only_5_hit" in ready.columns else 0
        stop_only_count = int(ready["stop_only_5_hit"].sum()) if "stop_only_5_hit" in ready.columns else 0
        both_count = int(ready["both_5_hit"].sum()) if "both_5_hit" in ready.columns else 0
        neither_count = int(ready["neither_5_hit"].sum()) if "neither_5_hit" in ready.columns else 0
        favorable_rate = (favorable_count / ready_count * 100.0) if ready_count else 0.0
        adverse_rate = (adverse_count / ready_count * 100.0) if ready_count else 0.0
        neutral_rate = (neutral_count / ready_count * 100.0) if ready_count else 0.0
        avg_favorable_move = float(pd.to_numeric(ready.get("latest_favorable_move_pct"), errors="coerce").mean())
        avg_adverse_move = float(pd.to_numeric(ready.get("latest_adverse_move_pct"), errors="coerce").mean())
        expectancy = (favorable_rate / 100.0) * avg_favorable_move - (adverse_rate / 100.0) * avg_adverse_move
        row.update(
            {
                "sent_count": int(len(group_frame)),
                "unique_alert_count": int(group_frame["alert_id"].nunique()),
                "latest_ready_count": ready_count,
                "ready_coverage_pct": (ready_count / len(group_frame) * 100.0) if len(group_frame) else 0.0,
                "favorable_count": favorable_count,
                "adverse_count": adverse_count,
                "neutral_count": neutral_count,
                "favorable_rate_pct": favorable_rate,
                "adverse_rate_pct": adverse_rate,
                "neutral_rate_pct": neutral_rate,
                "take5_hit_count": take5_count,
                "take5_rate_ready_pct": (take5_count / ready_count * 100.0) if ready_count else 0.0,
                "stop5_hit_count": stop5_count,
                "stop5_rate_ready_pct": (stop5_count / ready_count * 100.0) if ready_count else 0.0,
                "take_only_5_hit_count": take_only_count,
                "take_only_5_hit_rate_pct": (take_only_count / ready_count * 100.0) if ready_count else 0.0,
                "stop_only_5_hit_count": stop_only_count,
                "stop_only_5_hit_rate_pct": (stop_only_count / ready_count * 100.0) if ready_count else 0.0,
                "both_5_hit_count": both_count,
                "both_5_hit_rate_pct": (both_count / ready_count * 100.0) if ready_count else 0.0,
                "neither_5_hit_count": neither_count,
                "neither_5_hit_rate_pct": (neither_count / ready_count * 100.0) if ready_count else 0.0,
                "avg_move_pct": float(pd.to_numeric(ready.get("latest_move_pct"), errors="coerce").mean()),
                "avg_favorable_move_pct": avg_favorable_move,
                "avg_adverse_move_pct": avg_adverse_move,
                "expectancy": expectancy,
            }
        )
        rows.append(row)

    result = pd.DataFrame(rows)
    if not result.empty and min_sample_size > 1:
        result = result[result["latest_ready_count"] >= min_sample_size].copy()
    return result.sort_values(
        ["favorable_rate_pct", "take5_rate_ready_pct", "expectancy", "latest_ready_count"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)


def build_recent_sent_alert_window_stats(
    frame: pd.DataFrame,
    *,
    now_utc: datetime,
    windows_days: list[int],
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    ordered_windows: list[tuple[str, int | None]] = [(f"last_{days}d", days) for days in windows_days]
    ordered_windows.append(("all_time", None))
    now_ts = pd.Timestamp(now_utc)
    for label, days in ordered_windows:
        subset = frame.copy()
        if days is not None:
            cutoff = now_ts - pd.Timedelta(days=days)
            subset = subset[subset["delivered_at"].notna() & subset["delivered_at"].ge(cutoff)].copy()
        stats = build_sent_alert_outcome_stats(subset, [])
        if stats.empty:
            stats = pd.DataFrame([{"period_label": label}])
        else:
            stats.insert(0, "period_label", label)
        rows.append(stats)
    result = pd.concat(rows, ignore_index=True, sort=False) if rows else pd.DataFrame()
    order_map = {label: index for index, (label, _) in enumerate(ordered_windows)}
    if not result.empty:
        result["_period_order"] = result["period_label"].map(order_map)
        result = result.sort_values("_period_order").drop(columns=["_period_order"]).reset_index(drop=True)
    return result


def build_sent_alert_detail_rows(
    frame: pd.DataFrame,
    *,
    now_utc: datetime,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    result = frame.copy()
    result["delivery_age_days"] = (
        (pd.Timestamp(now_utc) - result["delivered_at"]).dt.total_seconds() / 86400.0
    ).round(2)
    return result[
        [
            "delivered_at",
            "bot_kind",
            "alert_symbol",
            "alert_direction",
            "alert_rsi",
            "alert_score",
            "quote_volume_bucket",
            "volume_ratio_bucket",
            "latest_followup_stage",
            "latest_thesis_result_state",
            "latest_favorable_move_pct",
            "latest_adverse_move_pct",
            "latest_move_pct",
            "path_5_status",
            "delivery_age_days",
        ]
    ].sort_values("delivered_at", ascending=False).reset_index(drop=True)


def build_validation_checks(
    *,
    alerts: pd.DataFrame,
    stage_results: pd.DataFrame,
    final_results: pd.DataFrame,
    latest_followups: pd.DataFrame,
    stage_stats: pd.DataFrame,
    overall_stats: pd.DataFrame,
    dordo_sent_alerts: pd.DataFrame,
    dordo_sent_followups: pd.DataFrame,
    dordo_sent_outcome_stats: pd.DataFrame,
    dordo_recent_window_stats: pd.DataFrame,
) -> pd.DataFrame:
    metrics = {str(row["metric"]): row["value"] for _, row in overall_stats.iterrows()}
    rows: list[dict[str, Any]] = []

    def add_check(status: str, check_name: str, details: str) -> None:
        rows.append({"status": status, "check_name": check_name, "details": details})

    total_alerts = int(len(alerts))
    oversold_count = int((alerts["alert_direction"] == "oversold").sum())
    overbought_count = int((alerts["alert_direction"] == "overbought").sum())
    metric_total = int(metrics.get("total_rsi_alerts", 0) or 0)
    metric_oversold = int(metrics.get("oversold_alerts", 0) or 0)
    metric_overbought = int(metrics.get("overbought_alerts", 0) or 0)
    add_check(
        "PASS" if metric_total == total_alerts else "FAIL",
        "Общее число RSI-сигналов сходится с raw alerts",
        f"В отчете {metric_total}, в raw SQLite {total_alerts}.",
    )
    add_check(
        "PASS" if (metric_oversold == oversold_count and metric_overbought == overbought_count and metric_total == metric_oversold + metric_overbought) else "FAIL",
        "Перепроданность и перекупленность сходятся с raw alerts",
        f"Oversold {metric_oversold}/{oversold_count}, overbought {metric_overbought}/{overbought_count}, сумма {metric_oversold + metric_overbought}.",
    )

    latest_expected = int(len(set(stage_results["alert_id"].tolist()) | set(final_results["alert_id"].tolist())))
    add_check(
        "PASS" if len(latest_followups) == latest_expected else "FAIL",
        "Количество latest follow-up сходится с union raw follow-up таблиц",
        f"В отчете {len(latest_followups)}, ожидалось {latest_expected} уникальных alert_id.",
    )

    if not stage_stats.empty:
        available_match = stage_stats["available_results"].fillna(0).astype(int).eq(stage_stats["signal_count"].fillna(0).astype(int)).all()
        add_check(
            "PASS" if available_match else "FAIL",
            "Stage-таблица не теряет available результаты",
            "Для каждой стадии available_results совпадает с числом строк raw stage follow-up.",
        )
        stage_balance = (
            stage_stats["available_results"].fillna(0).astype(int)
            + stage_stats["pending_count"].fillna(0).astype(int)
            + stage_stats["missing_overdue_count"].fillna(0).astype(int)
        ).eq(stage_stats["alerts_total"].fillna(0).astype(int)).all()
        add_check(
            "PASS" if stage_balance else "FAIL",
            "Pending / available / missing по стадиям балансируются",
            "Для каждой стадии сумма available + pending + missing_overdue равна общему числу alerts.",
        )

    if not stage_results.empty and not final_results.empty:
        stage_latest = (
            stage_results.sort_values(["alert_id", "followup_observed_at", "followup_row_id"], ascending=[True, True, True])
            .groupby("alert_id", as_index=False, sort=False)
            .tail(1)[
                [
                    "alert_id",
                    "followup_observed_at",
                    "followup_move_pct",
                    "thesis_result_state",
                    "favorable_move_pct",
                    "adverse_move_pct",
                ]
            ]
            .rename(
                columns={
                    "followup_observed_at": "stage_observed_at",
                    "followup_move_pct": "stage_move_pct",
                    "thesis_result_state": "stage_state",
                    "favorable_move_pct": "stage_favorable_move_pct",
                    "adverse_move_pct": "stage_adverse_move_pct",
                }
            )
        )
        final_latest = final_results[
            [
                "alert_id",
                "followup_observed_at",
                "followup_move_pct",
                "thesis_result_state",
                "favorable_move_pct",
                "adverse_move_pct",
            ]
        ].rename(
            columns={
                "followup_observed_at": "final_observed_at",
                "followup_move_pct": "final_move_pct",
                "thesis_result_state": "final_state",
                "favorable_move_pct": "final_favorable_move_pct",
                "adverse_move_pct": "final_adverse_move_pct",
            }
        )
        latest_compare = stage_latest.merge(final_latest, on="alert_id", how="inner")
        if latest_compare.empty:
            add_check(
                "WARN",
                "Сравнение final follow-up с последней stage записью",
                "Не нашлось alert_id, у которых одновременно есть final и stage follow-up.",
            )
        else:
            stage_observed = latest_compare["stage_observed_at"]
            final_observed = latest_compare["final_observed_at"]
            observed_match = stage_observed.eq(final_observed) | (stage_observed.isna() & final_observed.isna())

            stage_state = latest_compare["stage_state"]
            final_state = latest_compare["final_state"]
            state_match = stage_state.eq(final_state) | (stage_state.isna() & final_state.isna())

            stage_move = pd.to_numeric(latest_compare["stage_move_pct"], errors="coerce")
            final_move = pd.to_numeric(latest_compare["final_move_pct"], errors="coerce")
            move_match = stage_move.sub(final_move).abs().le(VALIDATION_FLOAT_TOLERANCE) | (stage_move.isna() & final_move.isna())

            stage_favorable = pd.to_numeric(latest_compare["stage_favorable_move_pct"], errors="coerce")
            final_favorable = pd.to_numeric(latest_compare["final_favorable_move_pct"], errors="coerce")
            favorable_match = stage_favorable.sub(final_favorable).abs().le(VALIDATION_FLOAT_TOLERANCE) | (
                stage_favorable.isna() & final_favorable.isna()
            )

            stage_adverse = pd.to_numeric(latest_compare["stage_adverse_move_pct"], errors="coerce")
            final_adverse = pd.to_numeric(latest_compare["final_adverse_move_pct"], errors="coerce")
            adverse_match = stage_adverse.sub(final_adverse).abs().le(VALIDATION_FLOAT_TOLERANCE) | (
                stage_adverse.isna() & final_adverse.isna()
            )
            diff_count = int((~(observed_match & state_match & move_match & favorable_match & adverse_match)).sum())
            add_check(
                "PASS" if diff_count == 0 else "WARN",
                "Final follow-up совпадает с последней stage записью",
                f"Проверено {len(latest_compare)} alerts, различий найдено {diff_count}.",
            )

    dordo_sent_total = int(len(dordo_sent_alerts))
    dordo_followup_total = int(len(dordo_sent_followups))
    outcome_sent_total = int(dordo_sent_outcome_stats["sent_count"].sum()) if not dordo_sent_outcome_stats.empty else 0
    outcome_ready_total = int(dordo_sent_outcome_stats["latest_ready_count"].sum()) if not dordo_sent_outcome_stats.empty else 0
    all_time_window = dordo_recent_window_stats[dordo_recent_window_stats["period_label"] == "all_time"].head(1)
    window_sent_total = int(all_time_window.iloc[0]["sent_count"]) if not all_time_window.empty else 0
    window_ready_total = int(all_time_window.iloc[0]["latest_ready_count"]) if not all_time_window.empty else 0
    add_check(
        "PASS" if dordo_sent_total == outcome_sent_total == window_sent_total else "FAIL",
        f"Личные отправки @{TARGET_DELIVERY_USERNAME} сходятся между raw и отчетом",
        f"Raw deliveries {dordo_sent_total}, в outcome-таблице {outcome_sent_total}, в all_time окне {window_sent_total}.",
    )
    add_check(
        "PASS" if outcome_ready_total == window_ready_total else "FAIL",
        f"Личные ready follow-up @{TARGET_DELIVERY_USERNAME} сходятся между таблицами",
        f"В outcome-таблице {outcome_ready_total}, в all_time окне {window_ready_total}.",
    )
    add_check(
        "PASS" if dordo_followup_total >= 0 else "FAIL",
        f"Личные follow-up доставки @{TARGET_DELIVERY_USERNAME} считаны без ошибок",
        f"Найдено {dordo_followup_total} реально отправленных follow-up сообщений.",
    )

    if not dordo_sent_outcome_stats.empty:
        path_partition_total = (
            dordo_sent_outcome_stats["take_only_5_hit_count"].fillna(0).astype(int)
            + dordo_sent_outcome_stats["stop_only_5_hit_count"].fillna(0).astype(int)
            + dordo_sent_outcome_stats["both_5_hit_count"].fillna(0).astype(int)
            + dordo_sent_outcome_stats["neither_5_hit_count"].fillna(0).astype(int)
        )
        ready_counts = dordo_sent_outcome_stats["latest_ready_count"].fillna(0).astype(int)
        add_check(
            "PASS" if path_partition_total.eq(ready_counts).all() else "FAIL",
            "Разбиение по +5 / -5 путям не теряет личные сигналы",
            "Для каждой личной группы take_only + stop_only + both + neither равно latest_ready_count.",
        )

    duplicate_personal_alerts = 0
    if not dordo_sent_alerts.empty:
        duplicate_personal_alerts = int((dordo_sent_alerts.groupby("alert_id").size() > 1).sum())
    add_check(
        "WARN" if duplicate_personal_alerts else "PASS",
        f"Повторные личные доставки одного alert_id @{TARGET_DELIVERY_USERNAME}",
        f"Найдено {duplicate_personal_alerts} alert_id, которые были отправлены больше одного раза (обычно classic + premium).",
    )

    unspecified_followup_stage_count = (
        int(dordo_sent_followups["delivery_stage"].eq("followup_unspecified").sum())
        if not dordo_sent_followups.empty and "delivery_stage" in dordo_sent_followups.columns
        else 0
    )
    add_check(
        "WARN" if unspecified_followup_stage_count else "PASS",
        "Follow-up сообщения без явной стадии в delivery history",
        f"Найдено {unspecified_followup_stage_count} follow-up доставок без 2h/4h/8h в metadata/message_kind.",
    )

    validation = pd.DataFrame(rows)
    if validation.empty:
        return validation
    status_order = {"FAIL": 0, "WARN": 1, "PASS": 2}
    validation["_status_order"] = validation["status"].map(status_order).fillna(9)
    validation = validation.sort_values(["_status_order", "check_name"]).drop(columns=["_status_order"]).reset_index(drop=True)
    return validation


def build_latest_available_followups(
    stage_results: pd.DataFrame,
    final_results: pd.DataFrame,
) -> pd.DataFrame:
    latest_from_stage = (
        stage_results.sort_values(["alert_id", "followup_observed_at", "followup_row_id"], ascending=[True, True, True])
        .groupby("alert_id", as_index=False, sort=False)
        .tail(1)
    )
    covered_alert_ids = set(latest_from_stage["alert_id"].tolist())
    final_only = final_results[~final_results["alert_id"].isin(covered_alert_ids)].copy()
    latest = pd.concat([latest_from_stage, final_only], ignore_index=True, sort=False)
    if latest.empty:
        return latest
    latest = latest.sort_values(["alert_id", "followup_observed_at"], ascending=[True, True]).drop_duplicates(
        subset=["alert_id"],
        keep="last",
    )
    return latest.reset_index(drop=True)


def build_stage_expectations(
    alerts: pd.DataFrame,
    stage_results: pd.DataFrame,
    *,
    stage_definitions: dict[str, timedelta],
    now_utc: datetime,
) -> pd.DataFrame:
    if alerts.empty:
        return pd.DataFrame()

    grace_delta = timedelta(minutes=OVERDUE_GRACE_MINUTES)
    present_results = (
        stage_results[["alert_id", "followup_stage", "followup_observed_at"]]
        .sort_values(["alert_id", "followup_stage", "followup_observed_at"])
        .drop_duplicates(subset=["alert_id", "followup_stage"], keep="last")
    )

    expectation_frames: list[pd.DataFrame] = []
    for stage_name, stage_delta in sorted(stage_definitions.items(), key=lambda item: stage_sort_key(item[0], stage_definitions)):
        stage_frame = alerts[["alert_id", "alert_symbol", "alert_direction", "alert_sent_at", "alert_rsi", "alert_score", "quote_volume", "volume_ratio"]].copy()
        stage_frame["followup_stage"] = stage_name
        stage_frame["stage_due_at"] = stage_frame["alert_sent_at"] + stage_delta
        stage_frame["stage_overdue_after"] = stage_frame["stage_due_at"] + grace_delta
        stage_frame = stage_frame.merge(
            present_results.rename(columns={"followup_observed_at": "result_observed_at"}),
            on=["alert_id", "followup_stage"],
            how="left",
        )
        stage_frame["alert_age_hours"] = (pd.Timestamp(now_utc) - stage_frame["alert_sent_at"]).dt.total_seconds() / 3600.0
        stage_frame["stage_status"] = "pending"
        stage_frame.loc[stage_frame["result_observed_at"].notna(), "stage_status"] = "available"
        overdue_mask = stage_frame["result_observed_at"].isna() & (pd.Timestamp(now_utc) >= stage_frame["stage_overdue_after"])
        stage_frame.loc[overdue_mask, "stage_status"] = "missing_overdue"
        stage_frame["overdue_minutes"] = (
            (pd.Timestamp(now_utc) - stage_frame["stage_overdue_after"]).dt.total_seconds() / 60.0
        ).clip(lower=0.0)
        expectation_frames.append(stage_frame)

    return pd.concat(expectation_frames, ignore_index=True, sort=False)


def build_overall_stats(
    alerts: pd.DataFrame,
    stage_results: pd.DataFrame,
    final_results: pd.DataFrame,
    latest_followups: pd.DataFrame,
    stage_expectations: pd.DataFrame,
    *,
    now_utc: datetime,
    stage_definitions: dict[str, timedelta],
) -> pd.DataFrame:
    any_stage_followup_ids = set(stage_results["alert_id"].tolist())
    latest_followup_ids = set(latest_followups["alert_id"].tolist())
    first_stage_name = min(stage_definitions, key=lambda stage_name: stage_definitions[stage_name].total_seconds())
    first_stage_expectations = stage_expectations[stage_expectations["followup_stage"] == first_stage_name].copy()

    metrics = [
        ("analysis_run_utc", now_utc.isoformat()),
        ("total_rsi_alerts", int(len(alerts))),
        ("oversold_alerts", int((alerts["alert_direction"] == "oversold").sum())),
        ("overbought_alerts", int((alerts["alert_direction"] == "overbought").sum())),
        ("unique_symbols", int(alerts["alert_symbol"].nunique())),
        ("data_start_utc", alerts["alert_sent_at"].min().isoformat() if not alerts.empty else None),
        ("data_end_utc", alerts["alert_sent_at"].max().isoformat() if not alerts.empty else None),
        ("stage_followup_rows", int(len(stage_results))),
        ("latest_followup_rows_raw", int(len(final_results))),
        ("latest_followup_rows_available", int(len(latest_followups))),
        ("alerts_with_any_stage_followup", int(len(any_stage_followup_ids))),
        ("alerts_without_any_stage_followup", int(len(alerts) - len(any_stage_followup_ids))),
        ("alerts_without_latest_followup", int(len(alerts) - len(latest_followup_ids))),
        (
            "alerts_too_fresh_for_first_followup",
            int(((first_stage_expectations["stage_status"] == "pending") & first_stage_expectations["result_observed_at"].isna()).sum()),
        ),
        (
            "alerts_missing_first_followup_overdue",
            int((first_stage_expectations["stage_status"] == "missing_overdue").sum()),
        ),
        (
            "alert_stage_pending_pairs",
            int((stage_expectations["stage_status"] == "pending").sum()),
        ),
        (
            "alert_stage_missing_overdue_pairs",
            int((stage_expectations["stage_status"] == "missing_overdue").sum()),
        ),
        (
            "alerts_with_any_missing_overdue_stage",
            int(stage_expectations.loc[stage_expectations["stage_status"] == "missing_overdue", "alert_id"].nunique()),
        ),
    ]
    return build_metric_rows(metrics)


def build_big_move_overview_stats(
    alerts: pd.DataFrame,
    latest_followups: pd.DataFrame,
    stage_results: pd.DataFrame,
    dordo_sent_alerts: pd.DataFrame,
    dordo_sent_followups: pd.DataFrame,
    *,
    target_user_id: int | None,
) -> pd.DataFrame:
    latest_big_moves = latest_followups[latest_followups["is_big_move"]].copy()
    stage_big_moves = stage_results[stage_results["is_big_move"]].copy()
    dordo_ready_alerts = dordo_sent_alerts[dordo_sent_alerts["latest_followup_observed_at"].notna()].copy()
    dordo_big_alerts = dordo_sent_alerts[dordo_sent_alerts["is_big_move"]].copy()
    dordo_big_followups = dordo_sent_followups[dordo_sent_followups["is_big_move"]].copy()

    metrics = [
        ("latest_followups_big_move_5p_count", int(len(latest_big_moves))),
        (
            "latest_followups_big_move_5p_rate_of_latest",
            (len(latest_big_moves) / len(latest_followups) * 100.0) if len(latest_followups) else 0.0,
        ),
        (
            "latest_followups_big_move_5p_rate_of_all_alerts",
            (len(latest_big_moves) / len(alerts) * 100.0) if len(alerts) else 0.0,
        ),
        ("stage_rows_big_move_5p_count", int(len(stage_big_moves))),
        ("unique_symbols_big_move_5p", int(latest_big_moves["alert_symbol"].nunique()) if not latest_big_moves.empty else 0),
        ("dordo_user_id", str(target_user_id) if target_user_id is not None else None),
        ("dordo_sent_alert_deliveries", int(len(dordo_sent_alerts))),
        ("dordo_sent_alert_unique_alerts", int(dordo_sent_alerts["alert_id"].nunique()) if not dordo_sent_alerts.empty else 0),
        ("dordo_sent_alerts_with_latest_followup", int(len(dordo_ready_alerts))),
        ("dordo_sent_alerts_big_move_5p_count", int(len(dordo_big_alerts))),
        (
            "dordo_sent_alerts_big_move_5p_rate",
            (len(dordo_big_alerts) / len(dordo_sent_alerts) * 100.0) if len(dordo_sent_alerts) else 0.0,
        ),
        (
            "dordo_sent_alerts_big_move_5p_rate_ready",
            (len(dordo_big_alerts) / len(dordo_ready_alerts) * 100.0) if len(dordo_ready_alerts) else 0.0,
        ),
        ("dordo_sent_followup_messages", int(len(dordo_sent_followups))),
        ("dordo_sent_followup_big_move_5p_count", int(len(dordo_big_followups))),
        (
            "dordo_sent_followup_big_move_5p_rate",
            (len(dordo_big_followups) / len(dordo_sent_followups) * 100.0) if len(dordo_sent_followups) else 0.0,
        ),
    ]
    return build_metric_rows(metrics)


def build_dordo_sent_alerts(
    deliveries: pd.DataFrame,
    *,
    target_user_id: int | None,
) -> pd.DataFrame:
    if target_user_id is None or deliveries.empty:
        return pd.DataFrame()
    result = deliveries[
        deliveries["telegram_user_id"].eq(target_user_id)
        & deliveries["delivery_sent"]
        & deliveries["delivery_is_alert"]
    ].copy()
    result["is_big_move"] = build_big_move_flags(
        result,
        state_column="latest_thesis_result_state",
        favorable_column="latest_favorable_move_pct",
    )
    result = add_take_stop_proxy_columns(
        result,
        favorable_column="latest_favorable_move_pct",
        adverse_column="latest_adverse_move_pct",
    )
    return result


def build_dordo_sent_followups(
    deliveries: pd.DataFrame,
    *,
    target_user_id: int | None,
) -> pd.DataFrame:
    if target_user_id is None or deliveries.empty:
        return pd.DataFrame()
    result = deliveries[
        deliveries["telegram_user_id"].eq(target_user_id)
        & deliveries["delivery_sent"]
        & deliveries["delivery_is_followup"]
    ].copy()
    result["is_big_move"] = build_big_move_flags(
        result,
        state_column="delivery_thesis_result_state",
        favorable_column="delivery_favorable_move_pct",
    )
    result = add_take_stop_proxy_columns(
        result,
        favorable_column="delivery_favorable_move_pct",
        adverse_column="delivery_adverse_move_pct",
    )
    return result


def build_stage_stats(
    stage_results: pd.DataFrame,
    stage_expectations: pd.DataFrame,
    *,
    stage_definitions: dict[str, timedelta],
) -> pd.DataFrame:
    stats = summarize_outcomes(stage_results, ["followup_stage"])
    diagnostics = (
        stage_expectations.groupby("followup_stage", dropna=False)
        .agg(
            alerts_total=("alert_id", "size"),
            available_results=("stage_status", lambda values: int((values == "available").sum())),
            pending_count=("stage_status", lambda values: int((values == "pending").sum())),
            missing_overdue_count=("stage_status", lambda values: int((values == "missing_overdue").sum())),
        )
        .reset_index()
    )
    diagnostics["coverage_pct"] = diagnostics["available_results"] / diagnostics["alerts_total"] * 100.0
    merged = diagnostics.merge(stats, on="followup_stage", how="left")
    merged["signal_count"] = merged["signal_count"].fillna(0).astype(int)
    merged["favorable_count"] = merged["favorable_count"].fillna(0).astype(int)
    merged["adverse_count"] = merged["adverse_count"].fillna(0).astype(int)
    merged["neutral_count"] = merged["neutral_count"].fillna(0).astype(int)
    return merged.sort_values(
        "followup_stage",
        key=lambda series: series.map(lambda value: stage_sort_key(str(value), stage_definitions)),
    ).reset_index(drop=True)


def build_direction_stats(latest_followups: pd.DataFrame) -> pd.DataFrame:
    return summarize_outcomes(latest_followups, ["alert_direction"]).sort_values(
        ["favorable_rate_pct", "expectancy", "signal_count"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def build_direction_stage_stats(stage_results: pd.DataFrame, *, stage_definitions: dict[str, timedelta]) -> pd.DataFrame:
    stats = summarize_outcomes(stage_results, ["followup_stage", "alert_direction"])
    stats["_stage_order"] = stats["followup_stage"].map(lambda value: stage_sort_key(str(value), stage_definitions)[0])
    return stats.sort_values(
        ["favorable_rate_pct", "expectancy", "signal_count", "_stage_order"],
        ascending=[False, False, False, True],
    ).drop(columns=["_stage_order"]).reset_index(drop=True)


def build_rsi_bucket_stats(latest_followups: pd.DataFrame) -> pd.DataFrame:
    filtered = latest_followups[latest_followups["rsi_bucket"].notna()].copy()
    return summarize_outcomes(filtered, ["alert_direction", "rsi_bucket"]).sort_values(
        ["favorable_rate_pct", "expectancy", "signal_count"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def build_volume_bucket_stats(latest_followups: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for metric_name, bucket_column in (("quote_volume", "quote_volume_bucket"), ("volume_ratio", "volume_ratio_bucket")):
        available = latest_followups[latest_followups[bucket_column].notna()].copy()
        if available.empty:
            continue
        stats = summarize_outcomes(available, ["alert_direction", bucket_column]).rename(columns={bucket_column: "bucket"})
        stats.insert(1, "volume_metric", metric_name)
        frames.append(stats)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False).sort_values(
        ["volume_metric", "favorable_rate_pct", "expectancy", "signal_count"],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)


def build_score_bucket_stats(latest_followups: pd.DataFrame) -> pd.DataFrame:
    filtered = latest_followups[latest_followups["score_bucket"].notna()].copy()
    return summarize_outcomes(filtered, ["alert_direction", "score_bucket"]).sort_values(
        ["favorable_rate_pct", "expectancy", "signal_count"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def build_best_setups(stage_results: pd.DataFrame) -> pd.DataFrame:
    required_columns = ["rsi_bucket", "score_bucket", "quote_volume_bucket", "volume_ratio_bucket", "followup_stage", "alert_direction"]
    filtered = stage_results.copy()
    for column in required_columns:
        filtered = filtered[filtered[column].notna()]
    if filtered.empty:
        return pd.DataFrame()
    stats = summarize_outcomes(
        filtered,
        ["alert_direction", "followup_stage", "rsi_bucket", "score_bucket", "quote_volume_bucket", "volume_ratio_bucket"],
    )
    stats = stats[stats["signal_count"] >= MIN_SAMPLE_SIZE].copy()
    return stats.sort_values(
        ["favorable_rate_pct", "expectancy", "signal_count"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def metadata_key_table(metadata_counts: Counter[str], total_rows: int) -> pd.DataFrame:
    if not metadata_counts:
        return pd.DataFrame(columns=["metadata_key", "row_count", "coverage_pct"])
    rows = [
        {
            "metadata_key": key,
            "row_count": count,
            "coverage_pct": (count / total_rows * 100.0) if total_rows else 0.0,
        }
        for key, count in metadata_counts.most_common()
    ]
    return pd.DataFrame(rows)


def build_context_feature_tables(latest_followups: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    context_tables: list[tuple[str, pd.DataFrame]] = []
    latest = latest_followups.copy()

    categorical_features = [
        ("market_regime_tag", "Режим рынка"),
        ("liquidity_tag", "Ликвидность актива"),
        ("setup_quality", "Стиль сетапа"),
        ("asset_cluster_tag", "Тип актива"),
        ("signal_status", "Статус сигнала"),
        ("signal_rsi_mode", "Как считался RSI в сигнале"),
        ("followup_rsi_mode", "Как считался RSI в follow-up"),
        ("followup_market_price_source", "Откуда брали цену для follow-up"),
        ("asset_class", "Класс актива"),
        ("result_type", "Тип результата"),
        ("lifecycle_source_type", "Источник результата"),
        ("invalidation_source", "Источник invalidation"),
        ("target_model", "Модель target"),
    ]
    for column, label in categorical_features:
        if column not in latest.columns:
            continue
        working = latest[latest[column].notna()].copy()
        if working.empty:
            continue
        unique_count = int(working[column].nunique(dropna=True))
        if unique_count < 2 or unique_count > 20:
            continue
        stats = summarize_outcomes(working, [column]).rename(columns={column: "value"})
        if stats.empty:
            continue
        stats = stats.sort_values(["favorable_rate_pct", "expectancy", "signal_count"], ascending=[False, False, False]).reset_index(drop=True)
        coverage_pct = len(working) / len(latest) * 100.0 if len(latest) else 0.0
        context_tables.append((f"{label} ({coverage_pct:.1f}% сигналов)", stats))

    numeric_bucket_features: list[tuple[str, str, str]] = [
        ("confidence_score", "Внутренняя confidence-оценка", "confidence"),
        ("atr_pct", "ATR %", "quantile"),
        ("benchmark_win_percent", "Справочный win rate", "quantile"),
        ("followup_24h_change_pct", "Изменение цены за 24ч к моменту follow-up", "quantile"),
    ]
    for column, label, strategy in numeric_bucket_features:
        if column not in latest.columns:
            continue
        working = latest[latest[column].notna()].copy()
        if working.empty or working[column].nunique(dropna=True) < 2:
            continue
        if strategy == "confidence":
            working["bucket"] = working[column].map(bucket_confidence)
        else:
            working["bucket"] = quantile_bucket(working[column], q=4)
        working = working[working["bucket"].notna()].copy()
        if working.empty:
            continue
        stats = summarize_outcomes(working, ["bucket"])
        stats = stats.sort_values(["favorable_rate_pct", "expectancy", "signal_count"], ascending=[False, False, False]).reset_index(drop=True)
        coverage_pct = len(working) / len(latest) * 100.0 if len(latest) else 0.0
        context_tables.append((f"{label} ({coverage_pct:.1f}% сигналов)", stats))

    return context_tables


def summarize_subset(frame: pd.DataFrame) -> dict[str, float | int]:
    if frame.empty:
        return {
            "signal_count": 0,
            "favorable_rate_pct": 0.0,
            "adverse_rate_pct": 0.0,
            "neutral_rate_pct": 0.0,
            "avg_favorable_move_pct": 0.0,
            "avg_adverse_move_pct": 0.0,
            "expectancy": 0.0,
        }
    favorable_count = int((frame["thesis_result_state"] == "favorable").sum())
    adverse_count = int((frame["thesis_result_state"] == "adverse").sum())
    neutral_count = int((frame["thesis_result_state"] == "neutral").sum())
    total = int(len(frame))
    favorable_rate = favorable_count / total * 100.0
    adverse_rate = adverse_count / total * 100.0
    neutral_rate = neutral_count / total * 100.0
    avg_favorable_move = float(frame["favorable_move_pct"].mean())
    avg_adverse_move = float(frame["adverse_move_pct"].mean())
    expectancy = (favorable_rate / 100.0) * avg_favorable_move - (adverse_rate / 100.0) * avg_adverse_move
    return {
        "signal_count": total,
        "favorable_rate_pct": favorable_rate,
        "adverse_rate_pct": adverse_rate,
        "neutral_rate_pct": neutral_rate,
        "avg_favorable_move_pct": avg_favorable_move,
        "avg_adverse_move_pct": avg_adverse_move,
        "expectancy": expectancy,
    }


def build_recommendations(
    latest_followups: pd.DataFrame,
    best_setups: pd.DataFrame,
) -> list[str]:
    recommendations: list[str] = []
    overall = summarize_subset(latest_followups)

    if not best_setups.empty:
        top_setup = best_setups.iloc[0]
        recommendations.append(
            "Лучшая комбинация по текущим данным: "
            f"{humanize_known_value(top_setup['alert_direction'])} | {humanize_known_value(top_setup['followup_stage'])} | "
            f"RSI {top_setup['rsi_bucket']} | score {top_setup['score_bucket']} | "
            f"объем {top_setup['quote_volume_bucket']} | относительный объем {top_setup['volume_ratio_bucket']} "
            f"(выборка={int(top_setup['signal_count'])}, edge={float(top_setup['expectancy']):.2f}). "
            "Это исторический паттерн, а не гарантия."
        )
        weak_setup = best_setups.sort_values(["expectancy", "signal_count"], ascending=[True, False]).iloc[0]
        recommendations.append(
            "Слабое место среди крупных выборок сейчас выглядит так: "
            f"{humanize_known_value(weak_setup['alert_direction'])} | {humanize_known_value(weak_setup['followup_stage'])} | "
            f"RSI {weak_setup['rsi_bucket']} | score {weak_setup['score_bucket']} "
            f"(выборка={int(weak_setup['signal_count'])}, edge={float(weak_setup['expectancy']):.2f})."
        )

    def compare_and_note(
        label: str,
        strong_mask: pd.Series,
        weak_mask: pd.Series,
        *,
        stronger_message: str,
        weaker_message: str,
    ) -> None:
        strong_subset = latest_followups[strong_mask].copy()
        weak_subset = latest_followups[weak_mask].copy()
        if len(strong_subset) < MIN_SAMPLE_SIZE or len(weak_subset) < MIN_SAMPLE_SIZE:
            return
        strong_stats = summarize_subset(strong_subset)
        weak_stats = summarize_subset(weak_subset)
        delta = float(strong_stats["expectancy"]) - float(weak_stats["expectancy"])
        if abs(delta) < 0.25:
            return
        if delta > 0:
            recommendations.append(
                f"{label}: {stronger_message} "
                f"(сильнее: n={int(strong_stats['signal_count'])}, edge={float(strong_stats['expectancy']):.2f}; "
                f"слабее: n={int(weak_stats['signal_count'])}, edge={float(weak_stats['expectancy']):.2f})."
            )
        else:
            recommendations.append(
                f"{label}: {weaker_message} "
                f"(база: n={int(weak_stats['signal_count'])}, edge={float(weak_stats['expectancy']):.2f}; "
                f"сравнение: n={int(strong_stats['signal_count'])}, edge={float(strong_stats['expectancy']):.2f})."
            )

    compare_and_note(
        "Подсказка по RSI-порогам",
        strong_mask=((latest_followups["alert_direction"] == "oversold") & (latest_followups["alert_rsi"] <= 27))
        | ((latest_followups["alert_direction"] == "overbought") & (latest_followups["alert_rsi"] >= 73)),
        weak_mask=((latest_followups["alert_direction"] == "oversold") & (latest_followups["alert_rsi"] > 27))
        | ((latest_followups["alert_direction"] == "overbought") & (latest_followups["alert_rsi"] < 73)),
        stronger_message="более экстремальные значения RSI сейчас выглядят сильнее, чем сигналы у самой границы, поэтому можно протестировать более жесткие пороги",
        weaker_message="сигналы у границы RSI сейчас не выглядят явно хуже глубоких экстремумов, поэтому чрезмерно ужесточать пороги может быть невыгодно",
    )
    compare_and_note(
        "Подсказка по фильтру объема",
        strong_mask=latest_followups["quote_volume"].ge(5_000_000),
        weak_mask=latest_followups["quote_volume"].lt(5_000_000),
        stronger_message="сигналы с более высоким объемом в USDT сейчас выглядят чище, поэтому фильтр 5M+ стоит протестировать",
        weaker_message="сигналы ниже 5M по объему сейчас не выглядят явно хуже, поэтому слишком жесткий фильтр по ликвидности может зря урезать выборку",
    )
    compare_and_note(
        "Подсказка по score-фильтру",
        strong_mask=latest_followups["alert_score"].ge(80),
        weak_mask=latest_followups["alert_score"].lt(80),
        stronger_message="сигналы со score 80+ сейчас дают лучшую ожидаемость, поэтому более строгий score-фильтр стоит проверить",
        weaker_message="сигналы ниже score 80 сейчас не выглядят заметно хуже, поэтому поднимать порог может быть не так полезно, как кажется",
    )

    recommendations.append(
        "Базовый ориентир по всем последним доступным follow-up: "
        f"выборка={int(overall['signal_count'])}, успешных={float(overall['favorable_rate_pct']):.2f}%, "
        f"против идеи={float(overall['adverse_rate_pct']):.2f}%, edge={float(overall['expectancy']):.2f}. "
        "Это нейтральная точка отсчета, с которой стоит сравнивать любые дополнительные фильтры."
    )
    return recommendations


def collect_unavailable_fields(alert_columns: list[str], alert_metadata_keys: set[str], followup_metadata_keys: set[str]) -> list[str]:
    unavailable: list[str] = []
    wanted_checks = [
        ("ema20", {"ema20", "alert_meta_ema20"}),
        ("ema50", {"ema50", "alert_meta_ema50"}),
        ("ema20 / ema50 alignment", {"ema_alignment", "trend_alignment", "alert_meta_ema_alignment"}),
        ("distance from ema20", {"distance_from_ema20", "alert_meta_distance_from_ema20"}),
        ("raw candle volume", {"last_candle_volume", "candle_volume", "alert_meta_last_candle_volume"}),
    ]
    available_names = set(alert_columns) | {f"alert_meta_{key}" for key in alert_metadata_keys} | {f"followup_meta_{key}" for key in followup_metadata_keys}
    for label, options in wanted_checks:
        if available_names.isdisjoint(options):
            unavailable.append(label)
    return unavailable


def save_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def format_scalar_for_report(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if abs(value) >= 100:
            return f"{value:,.2f}"
        return f"{value:.2f}"
    return str(value)


def format_dataframe_for_report(frame: pd.DataFrame, *, max_rows: int | None = None) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    display = frame.copy()
    if max_rows is not None:
        display = display.head(max_rows).copy()
    for column in display.columns:
        if pd.api.types.is_datetime64_any_dtype(display[column]):
            display[column] = display[column].map(lambda value: value.isoformat() if pd.notna(value) else "")
        elif pd.api.types.is_float_dtype(display[column]) or pd.api.types.is_integer_dtype(display[column]):
            display[column] = display[column].map(format_scalar_for_report)
        else:
            display[column] = display[column].map(lambda value: "" if pd.isna(value) else str(value))
    return display


def humanize_identifier(value: str) -> str:
    text = str(value or "").strip().replace("_", " ")
    if not text:
        return ""
    return text[:1].upper() + text[1:]


def humanize_known_value(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return DISPLAY_VALUE_LABELS.get(text, text)


def prettify_report_frame(frame: pd.DataFrame, *, max_rows: int | None = None) -> pd.DataFrame:
    display = format_dataframe_for_report(frame, max_rows=max_rows)
    if display.empty:
        return display

    original_columns = list(display.columns)
    for column in original_columns:
        if column == "metric":
            display[column] = display[column].map(
                lambda value: DISPLAY_METRIC_LABELS.get(str(value), humanize_identifier(str(value)))
            )
        else:
            display[column] = display[column].map(
                lambda value: humanize_known_value(value) if isinstance(value, str) else value
            )

    display = display.rename(columns={column: DISPLAY_COLUMN_LABELS.get(column, humanize_identifier(column)) for column in original_columns})
    return display


def dataframe_to_markdown(frame: pd.DataFrame, *, max_rows: int | None = None, humanize: bool = False) -> str:
    if frame.empty:
        return "_No data._"
    display = prettify_report_frame(frame, max_rows=max_rows) if humanize else format_dataframe_for_report(frame, max_rows=max_rows)
    headers = [str(column) for column in display.columns]
    rows = [[str(value) for value in row] for row in display.to_numpy().tolist()]
    widths = []
    for index, header in enumerate(headers):
        values = [header, *[row[index] for row in rows]]
        widths.append(max(len(value) for value in values))
    header_line = "| " + " | ".join(header.ljust(widths[index]) for index, header in enumerate(headers)) + " |"
    divider_line = "| " + " | ".join("-" * widths[index] for index in range(len(headers))) + " |"
    row_lines = [
        "| " + " | ".join(row[index].ljust(widths[index]) for index in range(len(headers))) + " |"
        for row in rows
    ]
    return "\n".join([header_line, divider_line, *row_lines])


def dataframe_to_html(frame: pd.DataFrame, *, max_rows: int | None = None, humanize: bool = False) -> str:
    if frame.empty:
        return "<p><em>No data.</em></p>"
    display = prettify_report_frame(frame, max_rows=max_rows) if humanize else format_dataframe_for_report(frame, max_rows=max_rows)
    table_html = display.to_html(index=False, escape=True, border=0, classes=["report-table"])
    return f'<div class="table-scroll">{table_html}</div>'


def select_existing_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    selected = [column for column in columns if column in frame.columns]
    return frame[selected].copy()


def sort_for_dashboard(
    frame: pd.DataFrame,
    *,
    stage_definitions: dict[str, timedelta] | None = None,
    keep_stage_order: bool = False,
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    result = frame.copy()
    helper_columns: list[str] = []
    sort_columns: list[str] = []
    ascending: list[bool] = []

    if "signal_count" in result.columns:
        result["_enough_sample"] = result["signal_count"].fillna(0).ge(MIN_SAMPLE_SIZE)
        helper_columns.append("_enough_sample")
        sort_columns.append("_enough_sample")
        ascending.append(False)

    if keep_stage_order and "followup_stage" in result.columns and stage_definitions is not None:
        result["_stage_order"] = result["followup_stage"].map(lambda value: stage_sort_key(str(value), stage_definitions)[0])
        helper_columns.append("_stage_order")
        sort_columns.append("_stage_order")
        ascending.append(True)

    if "favorable_rate_pct" in result.columns:
        sort_columns.append("favorable_rate_pct")
        ascending.append(False)
    if "expectancy" in result.columns:
        sort_columns.append("expectancy")
        ascending.append(False)
    if "signal_count" in result.columns:
        sort_columns.append("signal_count")
        ascending.append(False)

    if sort_columns:
        result = result.sort_values(sort_columns, ascending=ascending)

    if helper_columns:
        result = result.drop(columns=helper_columns)
    return result.reset_index(drop=True)


def prepare_dashboard_table(
    frame: pd.DataFrame,
    columns: list[str],
    *,
    stage_definitions: dict[str, timedelta] | None = None,
    keep_stage_order: bool = False,
    max_rows: int | None = None,
) -> pd.DataFrame:
    prepared = sort_for_dashboard(frame, stage_definitions=stage_definitions, keep_stage_order=keep_stage_order)
    prepared = select_existing_columns(prepared, columns)
    if max_rows is not None:
        prepared = prepared.head(max_rows).copy()
    return prepared


def metric_lookup(overall_stats: pd.DataFrame) -> dict[str, Any]:
    return {str(row["metric"]): row["value"] for _, row in overall_stats.iterrows()}


def format_compact_number(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        numeric = float(value)
        if abs(numeric) >= 1_000_000_000:
            return f"{numeric / 1_000_000_000:.2f}B"
        if abs(numeric) >= 1_000_000:
            return f"{numeric / 1_000_000:.2f}M"
        if abs(numeric) >= 1_000:
            return f"{numeric / 1_000:.1f}K"
        if abs(numeric - round(numeric)) < 0.001:
            return str(int(round(numeric)))
        return f"{numeric:.2f}"
    return str(value)


def format_percent(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    return f"{float(value):.1f}%"


def render_stat_card(title: str, value: str, subtitle: str, *, accent: str = "blue") -> str:
    color = CHART_COLORS.get(accent, CHART_COLORS["blue"])
    return (
        f'<div class="stat-card" style="--accent:{color}">'
        f'<div class="stat-card__title">{escape(title)}</div>'
        f'<div class="stat-card__value">{escape(value)}</div>'
        f'<div class="stat-card__subtitle">{escape(subtitle)}</div>'
        "</div>"
    )


def render_donut_chart(title: str, items: list[tuple[str, float, str]], *, center_value: str, center_label: str) -> str:
    total = sum(max(float(value), 0.0) for _, value, _ in items)
    if total <= 0:
        return f'<div class="viz-card"><h3>{escape(title)}</h3><p>Нет данных.</p></div>'

    radius = 54.0
    circumference = 2 * math.pi * radius
    offset = 0.0
    circles: list[str] = []
    legends: list[str] = []
    for label, value, color in items:
        safe_value = max(float(value), 0.0)
        if safe_value <= 0:
            continue
        dash = circumference * (safe_value / total)
        circles.append(
            f'<circle cx="80" cy="80" r="{radius}" fill="none" stroke="{color}" stroke-width="18" '
            f'stroke-linecap="butt" transform="rotate(-90 80 80)" '
            f'stroke-dasharray="{dash:.3f} {circumference - dash:.3f}" stroke-dashoffset="-{offset:.3f}"></circle>'
        )
        offset += dash
        legends.append(
            f'<div class="legend-item"><span class="legend-swatch" style="background:{color}"></span>'
            f'<span>{escape(label)}</span><strong>{format_compact_number(safe_value)}</strong></div>'
        )

    return (
        f'<div class="viz-card"><h3>{escape(title)}</h3>'
        '<div class="donut-wrap">'
        '<div class="donut-chart">'
        '<svg viewBox="0 0 160 160" aria-hidden="true">'
        f'<circle cx="80" cy="80" r="{radius}" fill="none" stroke="#e2e8f0" stroke-width="18"></circle>'
        f'{"".join(circles)}'
        '</svg>'
        f'<div class="donut-center"><div class="donut-value">{escape(center_value)}</div><div class="donut-label">{escape(center_label)}</div></div>'
        '</div>'
        f'<div class="legend-list">{"".join(legends)}</div>'
        '</div></div>'
    )


def render_stacked_bar(items: list[tuple[str, float, str]]) -> str:
    total = sum(max(float(value), 0.0) for _, value, _ in items)
    if total <= 0:
        return '<div class="stacked-bar stacked-bar--empty"></div>'
    segments = []
    for label, value, color in items:
        safe_value = max(float(value), 0.0)
        if safe_value <= 0:
            continue
        width = safe_value / total * 100.0
        segments.append(
            f'<span class="stacked-bar__segment" title="{escape(label)}: {safe_value:.1f}" '
            f'style="width:{width:.2f}%;background:{color}"></span>'
        )
    return f'<div class="stacked-bar">{"".join(segments)}</div>'


def render_stage_cards(stage_stats: pd.DataFrame) -> str:
    cards: list[str] = []
    for _, row in stage_stats.iterrows():
        stage_label = humanize_known_value(str(row["followup_stage"]))
        outcome_bar = render_stacked_bar(
            [
                ("Успешно", row["favorable_rate_pct"], CHART_COLORS["positive"]),
                ("Пошло против идеи", row["adverse_rate_pct"], CHART_COLORS["negative"]),
                ("Без явного движения", row["neutral_rate_pct"], CHART_COLORS["neutral"]),
            ]
        )
        coverage_bar = render_stacked_bar(
            [
                ("Есть результат", row["available_results"], CHART_COLORS["positive"]),
                ("Еще рано", row["pending_count"], CHART_COLORS["amber"]),
                ("Missing overdue", row["missing_overdue_count"], CHART_COLORS["negative"]),
            ]
        )
        cards.append(
            '<div class="mini-card">'
            f'<div class="mini-card__title">{escape(stage_label)}</div>'
            f'<div class="mini-card__meta">Это проверка результата спустя это время после сигнала. Покрытие {format_percent(row["coverage_pct"])} | Edge {float(row["expectancy"]):.2f}</div>'
            '<div class="mini-card__block"><div class="mini-card__label">Как часто идея работала к этому моменту</div>'
            f'{outcome_bar}'
            f'<div class="mini-card__numbers">Win rate {format_percent(row["favorable_rate_pct"])} · Против идеи {format_percent(row["adverse_rate_pct"])} · Нейтрально {format_percent(row["neutral_rate_pct"])}</div>'
            '</div>'
            '<div class="mini-card__block"><div class="mini-card__label">Насколько эта проверка вообще заполнена в истории</div>'
            f'{coverage_bar}'
            f'<div class="mini-card__numbers">Есть {format_compact_number(row["available_results"])} · Pending {format_compact_number(row["pending_count"])} · Missing {format_compact_number(row["missing_overdue_count"])}</div>'
            '</div>'
            '</div>'
        )
    return "".join(cards)


def render_direction_cards(direction_stats: pd.DataFrame) -> str:
    cards: list[str] = []
    accent_by_direction = {
        "oversold": CHART_COLORS["blue"],
        "overbought": CHART_COLORS["rose"],
    }
    for _, row in direction_stats.iterrows():
        direction_key = str(row["alert_direction"])
        direction_label = humanize_known_value(direction_key)
        outcome_bar = render_stacked_bar(
            [
                ("Успешно", row["favorable_rate_pct"], CHART_COLORS["positive"]),
                ("Пошло против идеи", row["adverse_rate_pct"], CHART_COLORS["negative"]),
                ("Без явного движения", row["neutral_rate_pct"], CHART_COLORS["neutral"]),
            ]
        )
        cards.append(
            f'<div class="mini-card mini-card--accent" style="--mini-accent:{accent_by_direction.get(direction_key, CHART_COLORS["indigo"])}">'
            f'<div class="mini-card__title">{escape(direction_label)}</div>'
            f'<div class="mini-card__meta">Сигналов {format_compact_number(row["signal_count"])} | Edge {float(row["expectancy"]):.2f}</div>'
            f'{outcome_bar}'
            f'<div class="mini-card__numbers">Win rate {format_percent(row["favorable_rate_pct"])} · Против идеи {format_percent(row["adverse_rate_pct"])} · Нейтрально {format_percent(row["neutral_rate_pct"])}</div>'
            f'<div class="mini-card__numbers">Средний ход в плюс {float(row["avg_favorable_move_pct"]):.2f}% · Средний ход против {float(row["avg_adverse_move_pct"]):.2f}%</div>'
            '</div>'
        )
    return "".join(cards)


def build_quick_highlights(
    stage_stats: pd.DataFrame,
    direction_stats: pd.DataFrame,
    rsi_bucket_stats: pd.DataFrame,
    volume_bucket_stats: pd.DataFrame,
    score_bucket_stats: pd.DataFrame,
    best_setups: pd.DataFrame,
) -> str:
    cards: list[str] = []

    def add_row(title: str, text: str, accent: str) -> None:
        cards.append(
            f'<div class="stat-card" style="--accent:{CHART_COLORS.get(accent, CHART_COLORS["indigo"])}">'
            f'<div class="stat-card__title">{escape(title)}</div>'
            f'<div class="stat-card__subtitle stat-card__subtitle--rich">{escape(text)}</div>'
            '</div>'
        )

    best_side = direction_stats[direction_stats["signal_count"] >= MIN_SAMPLE_SIZE]
    if not best_side.empty:
        row = best_side.sort_values(["favorable_rate_pct", "expectancy", "signal_count"], ascending=[False, False, False]).iloc[0]
        add_row(
            "Что чаще срабатывало",
            f"{humanize_known_value(row['alert_direction'])}: win rate {float(row['favorable_rate_pct']):.1f}% | выборка {int(row['signal_count'])}",
            "positive",
        )

    best_stage = stage_stats[stage_stats["signal_count"] >= MIN_SAMPLE_SIZE]
    if not best_stage.empty:
        row = best_stage.sort_values(["favorable_rate_pct", "expectancy", "signal_count"], ascending=[False, False, False]).iloc[0]
        add_row(
            "Когда результат уже чаще был понятен",
            f"{humanize_known_value(row['followup_stage'])}: win rate {float(row['favorable_rate_pct']):.1f}% | это просто проверка спустя это время после сигнала",
            "amber",
        )

    best_rsi = rsi_bucket_stats[rsi_bucket_stats["signal_count"] >= MIN_SAMPLE_SIZE]
    if not best_rsi.empty:
        row = best_rsi.sort_values(["favorable_rate_pct", "expectancy", "signal_count"], ascending=[False, False, False]).iloc[0]
        add_row(
            "Лучший RSI-диапазон",
            f"{humanize_known_value(row['alert_direction'])}: {row['rsi_bucket']} | win rate {float(row['favorable_rate_pct']):.1f}% | выборка {int(row['signal_count'])}",
            "indigo",
        )

    best_volume = volume_bucket_stats[
        (volume_bucket_stats["signal_count"] >= MIN_SAMPLE_SIZE) & (volume_bucket_stats["volume_metric"] == "quote_volume")
    ]
    if not best_volume.empty:
        row = best_volume.sort_values(["favorable_rate_pct", "expectancy", "signal_count"], ascending=[False, False, False]).iloc[0]
        add_row(
            "Лучший фильтр по объему рынка",
            f"{humanize_known_value(row['alert_direction'])}: {row['bucket']} | win rate {float(row['favorable_rate_pct']):.1f}% | выборка {int(row['signal_count'])}",
            "teal",
        )

    best_volume_ratio = volume_bucket_stats[
        (volume_bucket_stats["signal_count"] >= MIN_SAMPLE_SIZE) & (volume_bucket_stats["volume_metric"] == "volume_ratio")
    ]
    if not best_volume_ratio.empty:
        row = best_volume_ratio.sort_values(["favorable_rate_pct", "expectancy", "signal_count"], ascending=[False, False, False]).iloc[0]
        add_row(
            "Лучший фильтр по относительному объему",
            f"{humanize_known_value(row['alert_direction'])}: {row['bucket']} | win rate {float(row['favorable_rate_pct']):.1f}% | выборка {int(row['signal_count'])}",
            "cyan",
        )

    best_score = score_bucket_stats[score_bucket_stats["signal_count"] >= MIN_SAMPLE_SIZE]
    if not best_score.empty:
        row = best_score.sort_values(["favorable_rate_pct", "expectancy", "signal_count"], ascending=[False, False, False]).iloc[0]
        add_row(
            "Лучший score-фильтр",
            f"{humanize_known_value(row['alert_direction'])}: score {row['score_bucket']} | win rate {float(row['favorable_rate_pct']):.1f}% | выборка {int(row['signal_count'])}",
            "blue",
        )

    if not best_setups.empty:
        row = best_setups.iloc[0]
        add_row(
            "Лучшее сочетание условий",
            f"{humanize_known_value(row['alert_direction'])}, {humanize_known_value(row['followup_stage'])}, RSI {row['rsi_bucket']}, score {row['score_bucket']}, объем {row['quote_volume_bucket']}, отн. объем {row['volume_ratio_bucket']}",
            "rose",
        )

    return "".join(cards)


def render_explainer_cards() -> str:
    items = [
        (
            "Что значит «пошло против идеи»",
            "После RSI-сигнала цена пошла не туда, куда предполагала идея. Для перепроданности это падение дальше вниз, для перекупленности это рост дальше вверх.",
            "negative",
        ),
        (
            "Что такое 2ч / 4ч / 8ч",
            "Это не индикаторы. Это просто момент времени после сигнала, когда мы перепроверили, как он себя показал.",
            "amber",
        ),
        (
            "Что такое относительный объем",
            "Это текущий объем относительно среднего объема за последние 20 свечей. 1.0 = как обычно, 2.0 = объем в 2 раза выше нормы.",
            "teal",
        ),
        (
            "Как читать таблицы",
            "Сначала смотри на win rate и размер выборки. Потом на средний ход в плюс и средний ход против. Edge score нужен как дополнительная подсказка, а не как главный критерий.",
            "indigo",
        ),
    ]
    cards: list[str] = []
    for title, text, accent in items:
        cards.append(
            f'<div class="stat-card" style="--accent:{CHART_COLORS.get(accent, CHART_COLORS["blue"])}">'
            f'<div class="stat-card__title">{escape(title)}</div>'
            f'<div class="stat-card__subtitle stat-card__subtitle--rich">{escape(text)}</div>'
            "</div>"
        )
    return "".join(cards)


def build_user_conclusions(
    direction_stats: pd.DataFrame,
    rsi_bucket_stats: pd.DataFrame,
    volume_bucket_stats: pd.DataFrame,
    score_bucket_stats: pd.DataFrame,
    best_setups: pd.DataFrame,
) -> list[str]:
    conclusions: list[str] = []

    if not direction_stats.empty:
        row = direction_stats.iloc[0]
        conclusions.append(
            f"Сильнее всего сейчас выглядит {humanize_known_value(row['alert_direction']).lower()}: win rate {float(row['favorable_rate_pct']):.1f}% при выборке {int(row['signal_count'])}."
        )

    strong_rsi = rsi_bucket_stats[rsi_bucket_stats["signal_count"] >= MIN_SAMPLE_SIZE]
    if not strong_rsi.empty:
        row = strong_rsi.iloc[0]
        conclusions.append(
            f"Лучший RSI-диапазон сейчас: {humanize_known_value(row['alert_direction']).lower()} и зона {row['rsi_bucket']} с win rate {float(row['favorable_rate_pct']):.1f}%."
        )

    strong_volume = volume_bucket_stats[
        (volume_bucket_stats["signal_count"] >= MIN_SAMPLE_SIZE) & (volume_bucket_stats["volume_metric"] == "quote_volume")
    ]
    if not strong_volume.empty:
        row = strong_volume.iloc[0]
        conclusions.append(
            f"По объему рынка лучше всего выглядела корзина {row['bucket']} для сценария {humanize_known_value(row['alert_direction']).lower()}."
        )

    strong_volume_ratio = volume_bucket_stats[
        (volume_bucket_stats["signal_count"] >= MIN_SAMPLE_SIZE) & (volume_bucket_stats["volume_metric"] == "volume_ratio")
    ]
    if not strong_volume_ratio.empty:
        row = strong_volume_ratio.iloc[0]
        conclusions.append(
            f"По относительному объему сильнее всего выглядела корзина {row['bucket']}. Напоминание: это отношение текущего объема к обычному среднему объему."
        )

    strong_score = score_bucket_stats[score_bucket_stats["signal_count"] >= MIN_SAMPLE_SIZE]
    if not strong_score.empty:
        row = strong_score.iloc[0]
        conclusions.append(
            f"Если ужесточать фильтр по качеству, первым делом имеет смысл смотреть на score {row['score_bucket']}."
        )

    if not best_setups.empty:
        row = best_setups.iloc[0]
        conclusions.append(
            f"Лучшее сочетание условий в текущей истории: {humanize_known_value(row['alert_direction']).lower()}, {humanize_known_value(row['followup_stage']).lower()}, RSI {row['rsi_bucket']}, score {row['score_bucket']}, объем {row['quote_volume_bucket']} и относительный объем {row['volume_ratio_bucket']}."
        )

    return conclusions


def build_telegram_summary_message(
    *,
    overall_stats: pd.DataFrame,
    validation_checks: pd.DataFrame,
    dordo_sent_outcome_stats: pd.DataFrame,
    dordo_recent_window_stats: pd.DataFrame,
    dordo_rsi_bucket_stats: pd.DataFrame,
    dordo_score_bucket_stats: pd.DataFrame,
) -> str:
    metrics = metric_lookup(overall_stats)
    total_alerts = int(metrics.get("total_rsi_alerts", 0) or 0)
    latest_followups = int(metrics.get("latest_followup_rows_available", 0) or 0)
    dordo_sent_total = int(dordo_sent_outcome_stats["sent_count"].sum()) if not dordo_sent_outcome_stats.empty else 0
    dordo_ready_total = int(dordo_sent_outcome_stats["latest_ready_count"].sum()) if not dordo_sent_outcome_stats.empty else 0
    dordo_take5_total = int(dordo_sent_outcome_stats["take5_hit_count"].sum()) if not dordo_sent_outcome_stats.empty else 0
    dordo_stop5_total = int(dordo_sent_outcome_stats["stop5_hit_count"].sum()) if not dordo_sent_outcome_stats.empty else 0

    all_time_row = dordo_recent_window_stats[dordo_recent_window_stats.get("period_label", pd.Series(dtype="object")).eq("all_time")].head(1)
    if all_time_row.empty:
        ready_rate = (dordo_ready_total / dordo_sent_total * 100.0) if dordo_sent_total else 0.0
        win_rate = 0.0
        take5_rate = (dordo_take5_total / dordo_ready_total * 100.0) if dordo_ready_total else 0.0
    else:
        ready_rate = float(all_time_row.iloc[0].get("ready_coverage_pct") or 0.0)
        win_rate = float(all_time_row.iloc[0].get("favorable_rate_pct") or 0.0)
        take5_rate = float(all_time_row.iloc[0].get("take5_rate_ready_pct") or 0.0)

    top_rsi_text = "Пока не хватает выборки."
    if not dordo_rsi_bucket_stats.empty:
        top_rsi = dordo_rsi_bucket_stats.iloc[0]
        top_rsi_text = (
            f"{humanize_known_value(top_rsi.get('bot_kind'))} | "
            f"{humanize_known_value(top_rsi.get('alert_direction'))} | "
            f"RSI {top_rsi.get('rsi_bucket')} | "
            f"win rate {float(top_rsi.get('favorable_rate_pct') or 0.0):.1f}% | "
            f"готовых итогов {int(top_rsi.get('latest_ready_count') or 0)}"
        )

    top_score_text = "Пока не хватает выборки."
    if not dordo_score_bucket_stats.empty:
        top_score = dordo_score_bucket_stats.iloc[0]
        top_score_text = (
            f"{humanize_known_value(top_score.get('bot_kind'))} | "
            f"{humanize_known_value(top_score.get('alert_direction'))} | "
            f"score {top_score.get('score_bucket')} | "
            f"win rate {float(top_score.get('favorable_rate_pct') or 0.0):.1f}% | "
            f"готовых итогов {int(top_score.get('latest_ready_count') or 0)}"
        )

    fail_count = int(validation_checks["status"].eq("FAIL").sum()) if not validation_checks.empty else 0
    warn_count = int(validation_checks["status"].eq("WARN").sum()) if not validation_checks.empty else 0
    ok_count = int(validation_checks["status"].eq("PASS").sum()) if not validation_checks.empty else 0

    lines = [
        "<b>RSI-отчет готов</b>",
        "",
        f"<b>Общая база:</b> {escape(format_compact_number(total_alerts))} RSI-сигналов, {escape(format_compact_number(latest_followups))} с доступным итогом.",
        f"<b>Лично тебе:</b> отправлено {escape(format_compact_number(dordo_sent_total))}, итог уже есть по {escape(format_compact_number(dordo_ready_total))} ({escape(format_percent(ready_rate))}).",
        f"<b>Твой win rate:</b> {escape(format_percent(win_rate))}.",
        f"<b>Касались +5%:</b> {escape(format_percent(take5_rate))} среди тех, где итог уже известен ({escape(format_compact_number(dordo_take5_total))} случаев).",
        f"<b>Уходили на -5% против идеи:</b> {escape(format_compact_number(dordo_stop5_total))} случаев.",
        "",
        f"<b>Лучший RSI у тебя:</b> {escape(top_rsi_text)}",
        f"<b>Лучший score у тебя:</b> {escape(top_score_text)}",
        "",
        f"<b>Проверка данных:</b> OK {ok_count} | Внимание {warn_count} | Ошибки {fail_count}",
        "Ниже прикреплен полный HTML-отчет для телефона.",
    ]
    return "\n".join(lines)


def telegram_api_request(
    *,
    bot_token: str,
    method: str,
    fields: dict[str, Any],
    file_field_name: str | None = None,
    file_path: Path | None = None,
) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{bot_token.strip()}/{method}"
    timeout = TELEGRAM_REPORT_TIMEOUT_SECONDS

    if file_field_name and file_path is not None:
        boundary = f"----RSIAnalytics{uuid.uuid4().hex}"
        body = bytearray()
        for key, value in fields.items():
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")

        content_type = guess_type(file_path.name)[0] or "application/octet-stream"
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{file_field_name}"; filename="{file_path.name}"\r\n'.encode("utf-8")
        )
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        body.extend(file_path.read_bytes())
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode("utf-8"))

        request = urllib.request.Request(
            url,
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
    else:
        encoded = urllib.parse.urlencode({key: str(value) for key, value in fields.items()}).encode("utf-8")
        request = urllib.request.Request(url, data=encoded, method="POST")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # pragma: no cover - network-dependent
        response_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram {method} failed with HTTP {exc.code}: {response_body}") from exc
    except urllib.error.URLError as exc:  # pragma: no cover - network-dependent
        raise RuntimeError(f"Telegram {method} request failed: {exc}") from exc

    if not payload.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {payload}")
    return payload["result"]


def send_telegram_report(
    *,
    bot_token: str,
    chat_id: int,
    report_html_path: Path,
    summary_text: str,
) -> None:
    telegram_api_request(
        bot_token=bot_token,
        method="sendMessage",
        fields={
            "chat_id": chat_id,
            "text": summary_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        },
    )
    telegram_api_request(
        bot_token=bot_token,
        method="sendDocument",
        fields={
            "chat_id": chat_id,
            "caption": "Полный HTML-отчет по RSI-аналитике готов. Открой файл в браузере на телефоне.",
        },
        file_field_name="document",
        file_path=report_html_path,
    )


def build_markdown_report(
    *,
    overall_stats: pd.DataFrame,
    validation_checks: pd.DataFrame,
    stage_stats: pd.DataFrame,
    direction_stats: pd.DataFrame,
    direction_stage_stats: pd.DataFrame,
    rsi_bucket_stats: pd.DataFrame,
    volume_bucket_stats: pd.DataFrame,
    score_bucket_stats: pd.DataFrame,
    best_setups: pd.DataFrame,
    missing_followups: pd.DataFrame,
    pending_stage_counts: pd.DataFrame,
    alert_metadata_table: pd.DataFrame,
    followup_metadata_table: pd.DataFrame,
    context_tables: list[tuple[str, pd.DataFrame]],
    recommendations: list[str],
    unavailable_fields: list[str],
    big_move_overview: pd.DataFrame,
    big_move_direction_stats: pd.DataFrame,
    big_move_stage_stats: pd.DataFrame,
    dordo_sent_alert_stats: pd.DataFrame,
    dordo_sent_followup_stats: pd.DataFrame,
    liquidity_rsi_combo_stats: pd.DataFrame,
    score_liquidity_combo_stats: pd.DataFrame,
    ultra_liquid_high_score_stats: pd.DataFrame,
    dordo_sent_outcome_stats: pd.DataFrame,
    dordo_recent_window_stats: pd.DataFrame,
    dordo_rsi_bucket_stats: pd.DataFrame,
    dordo_score_bucket_stats: pd.DataFrame,
    dordo_combo_stats: pd.DataFrame,
    dordo_sent_alert_details: pd.DataFrame,
) -> str:
    lines: list[str] = []
    lines.append(f"# {REPORT_TITLE}")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    lines.append("- This report uses only local SQLite data in read-only mode and does not touch the live bot runtime.")
    lines.append("- Strategy scope is limited to `alerts.strategy_key = 'rsi'`.")
    lines.append("- Bucket and metadata analyses use the latest available follow-up per alert to avoid triple-counting the same signal across 2h / 4h / 8h.")
    lines.append("- Stage-specific performance uses raw `followup_stage_results` rows.")
    lines.append(f"- HTML/Markdown keeps only top {REPORT_TOP_ROWS} rows per main table for readability; CSV files keep the full slices.")
    lines.append("")

    lines.append(f"## @{TARGET_DELIVERY_USERNAME} Personal Delivery Stats")
    lines.append("")
    lines.append("Personal outcome view for live alerts actually delivered to this user.")
    lines.append("")
    lines.append(dataframe_to_markdown(dordo_sent_outcome_stats, humanize=True))
    lines.append("")
    lines.append("Freshness / recency view:")
    lines.append("")
    lines.append(dataframe_to_markdown(dordo_recent_window_stats, humanize=True))
    lines.append("")
    lines.append("Where RSI zones worked better specifically among alerts actually delivered to this user:")
    lines.append("")
    lines.append(dataframe_to_markdown(dordo_rsi_bucket_stats, max_rows=REPORT_TOP_ROWS, humanize=True))
    lines.append("")
    lines.append("Where score worked better specifically among alerts actually delivered to this user:")
    lines.append("")
    lines.append(dataframe_to_markdown(dordo_score_bucket_stats, max_rows=REPORT_TOP_ROWS, humanize=True))
    lines.append("")
    lines.append("Which combinations worked better specifically among alerts actually delivered to this user:")
    lines.append("")
    lines.append(dataframe_to_markdown(dordo_combo_stats, max_rows=REPORT_TOP_ROWS, humanize=True))
    lines.append("")
    lines.append("Latest delivered live alerts:")
    lines.append("")
    lines.append(dataframe_to_markdown(dordo_sent_alert_details, max_rows=REPORT_COMPACT_ROWS, humanize=True))
    lines.append("")

    lines.append("## Data Quality Checks")
    lines.append("")
    lines.append("These checks compare the report against raw SQLite slices. `WARN` means important context to keep in mind, not necessarily a broken number.")
    lines.append("")
    lines.append(dataframe_to_markdown(validation_checks, humanize=True))
    lines.append("")

    lines.append("## Overall Statistics")
    lines.append("")
    lines.append(dataframe_to_markdown(overall_stats))
    lines.append("")

    lines.append("## Stage Statistics")
    lines.append("")
    lines.append(dataframe_to_markdown(stage_stats))
    lines.append("")

    lines.append("## Direction Statistics")
    lines.append("")
    lines.append("Latest available follow-up per alert:")
    lines.append("")
    lines.append(dataframe_to_markdown(direction_stats, max_rows=REPORT_TOP_ROWS))
    lines.append("")
    lines.append("Stage rows by direction:")
    lines.append("")
    lines.append(dataframe_to_markdown(direction_stage_stats, max_rows=REPORT_TOP_ROWS))
    lines.append("")

    lines.append("## RSI Buckets")
    lines.append("")
    lines.append(dataframe_to_markdown(rsi_bucket_stats, max_rows=REPORT_TOP_ROWS))
    lines.append("")

    lines.append("## Volume Buckets")
    lines.append("")
    lines.append(dataframe_to_markdown(volume_bucket_stats, max_rows=REPORT_TOP_ROWS))
    lines.append("")

    lines.append("## Score Buckets")
    lines.append("")
    lines.append(dataframe_to_markdown(score_bucket_stats, max_rows=REPORT_TOP_ROWS))
    lines.append("")

    lines.append(f"## Strong Results {BIG_MOVE_THRESHOLD_PCT:.0f}%+")
    lines.append("")
    lines.append("Overall 5%+ summary:")
    lines.append("")
    lines.append(dataframe_to_markdown(big_move_overview, humanize=True))
    lines.append("")
    lines.append("Across all latest available follow-ups:")
    lines.append("")
    lines.append(dataframe_to_markdown(big_move_direction_stats, max_rows=REPORT_TOP_ROWS, humanize=True))
    lines.append("")
    lines.append("Across stage rows:")
    lines.append("")
    lines.append(dataframe_to_markdown(big_move_stage_stats, max_rows=REPORT_TOP_ROWS, humanize=True))
    lines.append("")
    lines.append(f"@{TARGET_DELIVERY_USERNAME} sent live alerts -> later 5%+ outcomes:")
    lines.append("")
    lines.append(dataframe_to_markdown(dordo_sent_alert_stats, max_rows=REPORT_TOP_ROWS, humanize=True))
    lines.append("")
    lines.append(f"@{TARGET_DELIVERY_USERNAME} sent follow-up messages already showing 5%+:")
    lines.append("")
    lines.append(dataframe_to_markdown(dordo_sent_followup_stats, max_rows=REPORT_TOP_ROWS, humanize=True))
    lines.append("")

    lines.append("## Joint Filters: Liquidity + RSI + Score")
    lines.append("")
    lines.append("Where liquidity, RSI zone and score worked best together:")
    lines.append("")
    lines.append(dataframe_to_markdown(liquidity_rsi_combo_stats, max_rows=REPORT_TOP_ROWS, humanize=True))
    lines.append("")
    lines.append("Where liquidity and score worked best together:")
    lines.append("")
    lines.append(dataframe_to_markdown(score_liquidity_combo_stats, max_rows=REPORT_TOP_ROWS, humanize=True))
    lines.append("")
    lines.append("Very liquid coins (50M+) with score 90+ -> best RSI zones:")
    lines.append("")
    lines.append(dataframe_to_markdown(ultra_liquid_high_score_stats, max_rows=REPORT_COMPACT_ROWS, humanize=True))
    lines.append("")

    lines.append("## Market Context / Metadata Features")
    lines.append("")
    lines.append("Detected alert metadata keys:")
    lines.append("")
    lines.append(dataframe_to_markdown(alert_metadata_table, max_rows=REPORT_METADATA_ROWS))
    lines.append("")
    lines.append("Detected follow-up metadata keys:")
    lines.append("")
    lines.append(dataframe_to_markdown(followup_metadata_table, max_rows=REPORT_METADATA_ROWS))
    lines.append("")
    for title, table in context_tables:
        lines.append(f"### {title}")
        lines.append("")
        lines.append(dataframe_to_markdown(table, max_rows=REPORT_COMPACT_ROWS))
        lines.append("")

    lines.append("## Best Setups")
    lines.append("")
    lines.append(
        f"Only combinations with at least `{MIN_SAMPLE_SIZE}` stage observations are shown. "
        "Rows are sorted by favorable rate, then expectancy, then sample size."
    )
    lines.append("")
    lines.append(dataframe_to_markdown(best_setups, max_rows=REPORT_TOP_ROWS))
    lines.append("")

    lines.append("## Follow-up Diagnostics")
    lines.append("")
    lines.append("Pending stage counts:")
    lines.append("")
    lines.append(dataframe_to_markdown(pending_stage_counts))
    lines.append("")
    lines.append("Missing overdue stage rows:")
    lines.append("")
    lines.append(dataframe_to_markdown(missing_followups, max_rows=REPORT_DIAGNOSTIC_ROWS))
    lines.append("")

    lines.append("## Recommendations")
    lines.append("")
    for item in recommendations:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## Limitations")
    lines.append("")
    lines.append("- Historical analytics uses only fields that were actually stored in SQLite at signal / follow-up time.")
    if unavailable_fields:
        lines.append(f"- Explicitly unavailable in current historical data: {', '.join(unavailable_fields)}.")
    else:
        lines.append("- No major requested field group was found completely unavailable.")
    lines.append("- `strategy_stats_snapshots` was not used as a source of truth; raw tables drive the report.")
    lines.append("- Missing-overdue logic uses configured stage durations plus a grace window to avoid borderline false positives.")
    lines.append("")
    return "\n".join(lines)


def build_html_report(
    *,
    overall_stats: pd.DataFrame,
    validation_checks: pd.DataFrame,
    stage_stats: pd.DataFrame,
    direction_stats: pd.DataFrame,
    direction_stage_stats: pd.DataFrame,
    rsi_bucket_stats: pd.DataFrame,
    volume_bucket_stats: pd.DataFrame,
    score_bucket_stats: pd.DataFrame,
    best_setups: pd.DataFrame,
    missing_followups: pd.DataFrame,
    pending_stage_counts: pd.DataFrame,
    alert_metadata_table: pd.DataFrame,
    followup_metadata_table: pd.DataFrame,
    context_tables: list[tuple[str, pd.DataFrame]],
    recommendations: list[str],
    unavailable_fields: list[str],
    stage_definitions: dict[str, timedelta],
    big_move_overview: pd.DataFrame,
    big_move_direction_stats: pd.DataFrame,
    big_move_stage_stats: pd.DataFrame,
    dordo_sent_alert_stats: pd.DataFrame,
    dordo_sent_followup_stats: pd.DataFrame,
    liquidity_rsi_combo_stats: pd.DataFrame,
    score_liquidity_combo_stats: pd.DataFrame,
    ultra_liquid_high_score_stats: pd.DataFrame,
    dordo_sent_outcome_stats: pd.DataFrame,
    dordo_recent_window_stats: pd.DataFrame,
    dordo_rsi_bucket_stats: pd.DataFrame,
    dordo_score_bucket_stats: pd.DataFrame,
    dordo_combo_stats: pd.DataFrame,
    dordo_sent_alert_details: pd.DataFrame,
) -> str:
    metrics = metric_lookup(overall_stats)
    total_alerts = int(metrics.get("total_rsi_alerts", 0) or 0)
    followup_ready = int(metrics.get("alerts_with_any_stage_followup", 0) or 0)
    first_pending = int(metrics.get("alerts_too_fresh_for_first_followup", 0) or 0)
    first_missing = int(metrics.get("alerts_missing_first_followup_overdue", 0) or 0)
    oversold_total = int(metrics.get("oversold_alerts", 0) or 0)
    overbought_total = int(metrics.get("overbought_alerts", 0) or 0)
    latest_total = int(direction_stats["signal_count"].sum()) if not direction_stats.empty else 0
    latest_favorable = int(direction_stats["favorable_count"].sum()) if not direction_stats.empty else 0
    latest_adverse = int(direction_stats["adverse_count"].sum()) if not direction_stats.empty else 0
    latest_neutral = int(direction_stats["neutral_count"].sum()) if not direction_stats.empty else 0
    latest_win_rate = (latest_favorable / latest_total * 100.0) if latest_total else 0.0

    best_side_name = "Недостаточно данных"
    best_side_detail = "Пока не хватает данных для уверенного сравнения сторон."
    if not direction_stats.empty:
        best_side = direction_stats.iloc[0]
        best_side_name = humanize_known_value(best_side["alert_direction"])
        best_side_detail = f"win rate {float(best_side['favorable_rate_pct']):.1f}% | edge {float(best_side['expectancy']):.2f}"

    best_stage_text = "Недостаточно данных"
    candidate_stage_stats = stage_stats[stage_stats["signal_count"] >= MIN_SAMPLE_SIZE].copy()
    if not candidate_stage_stats.empty:
        candidate_stage_stats = candidate_stage_stats.sort_values(["favorable_rate_pct", "expectancy", "signal_count"], ascending=[False, False, False])
        best_stage = candidate_stage_stats.iloc[0]
        best_stage_text = (
            f"{humanize_known_value(best_stage['followup_stage'])}: "
            f"win rate {float(best_stage['favorable_rate_pct']):.1f}% | "
            f"покрытие {float(best_stage['coverage_pct']):.1f}%"
        )

    summary_cards = "".join(
        [
            render_stat_card("Всего RSI-сигналов", format_compact_number(total_alerts), "Все исторические RSI-сигналы из SQLite", accent="blue"),
            render_stat_card("Сигналов уже с follow-up", format_compact_number(followup_ready), "Есть хотя бы один рассчитанный follow-up", accent="teal"),
            render_stat_card("Win rate последнего follow-up", format_percent(latest_win_rate), f"Сработало {format_compact_number(latest_favorable)} из {format_compact_number(latest_total)}", accent="positive"),
            render_stat_card("Еще слишком рано", format_compact_number(first_pending), "Для первой проверки follow-up еще не истекло время", accent="amber"),
            render_stat_card("Missing overdue по 1-й проверке", format_compact_number(first_missing), "Follow-up уже должен был быть, но записи нет", accent="negative"),
            render_stat_card("Сильнейшая сторона сейчас", best_side_name, f"{best_side_detail} | лучшая проверка: {best_stage_text}", accent="indigo"),
        ]
    )

    donut_signals = render_donut_chart(
        "Структура сигналов",
        [("Перепроданность", oversold_total, CHART_COLORS["blue"]), ("Перекупленность", overbought_total, CHART_COLORS["rose"])],
        center_value=format_compact_number(total_alerts),
        center_label="всего сигналов",
    )
    donut_outcomes = render_donut_chart(
        "Как закончились последние follow-up",
        [("Успешно", latest_favorable, CHART_COLORS["positive"]), ("Пошло против идеи", latest_adverse, CHART_COLORS["negative"]), ("Без явного движения", latest_neutral, CHART_COLORS["neutral"])],
        center_value=format_percent(latest_win_rate),
        center_label="win rate",
    )
    first_stage_row = stage_stats.iloc[0] if not stage_stats.empty else None
    donut_coverage = render_donut_chart(
        "Покрытие первой проверки",
        [
            ("Есть результат", float(first_stage_row["available_results"]) if first_stage_row is not None else 0.0, CHART_COLORS["positive"]),
            ("Еще рано", float(first_stage_row["pending_count"]) if first_stage_row is not None else 0.0, CHART_COLORS["amber"]),
            ("Missing overdue", float(first_stage_row["missing_overdue_count"]) if first_stage_row is not None else 0.0, CHART_COLORS["negative"]),
        ],
        center_value=format_percent(float(first_stage_row["coverage_pct"]) if first_stage_row is not None else 0.0),
        center_label="покрытие",
    )

    explainer_cards_html = render_explainer_cards()
    highlights_html = build_quick_highlights(stage_stats, direction_stats, rsi_bucket_stats, volume_bucket_stats, score_bucket_stats, best_setups)
    stage_cards_html = render_stage_cards(stage_stats)
    direction_cards_html = render_direction_cards(direction_stats)
    user_conclusions = build_user_conclusions(direction_stats, rsi_bucket_stats, volume_bucket_stats, score_bucket_stats, best_setups)
    recommendation_items = "".join(f"<li>{escape(item)}</li>" for item in [*user_conclusions, *recommendations])

    stage_table = prepare_dashboard_table(
        stage_stats,
        ["followup_stage", "signal_count", "favorable_rate_pct", "adverse_rate_pct", "neutral_rate_pct", "avg_favorable_move_pct", "avg_adverse_move_pct", "coverage_pct", "available_results", "pending_count", "missing_overdue_count", "expectancy"],
        stage_definitions=stage_definitions,
        keep_stage_order=True,
    )
    direction_table = prepare_dashboard_table(
        direction_stats,
        ["alert_direction", "signal_count", "favorable_rate_pct", "adverse_rate_pct", "neutral_rate_pct", "avg_favorable_move_pct", "avg_adverse_move_pct", "expectancy"],
    )
    direction_stage_table = prepare_dashboard_table(
        direction_stage_stats,
        ["alert_direction", "followup_stage", "signal_count", "favorable_rate_pct", "adverse_rate_pct", "neutral_rate_pct", "avg_favorable_move_pct", "avg_adverse_move_pct", "expectancy"],
        max_rows=REPORT_TOP_ROWS,
    )
    rsi_table = prepare_dashboard_table(
        rsi_bucket_stats,
        ["alert_direction", "rsi_bucket", "signal_count", "favorable_rate_pct", "adverse_rate_pct", "neutral_rate_pct", "avg_favorable_move_pct", "avg_adverse_move_pct", "expectancy"],
        max_rows=REPORT_TOP_ROWS,
    )
    volume_usdt_table = prepare_dashboard_table(
        volume_bucket_stats[volume_bucket_stats["volume_metric"] == "quote_volume"].copy(),
        ["alert_direction", "bucket", "signal_count", "favorable_rate_pct", "adverse_rate_pct", "neutral_rate_pct", "avg_favorable_move_pct", "avg_adverse_move_pct", "expectancy"],
        max_rows=REPORT_TOP_ROWS,
    )
    volume_ratio_table = prepare_dashboard_table(
        volume_bucket_stats[volume_bucket_stats["volume_metric"] == "volume_ratio"].copy(),
        ["alert_direction", "bucket", "signal_count", "favorable_rate_pct", "adverse_rate_pct", "neutral_rate_pct", "avg_favorable_move_pct", "avg_adverse_move_pct", "expectancy"],
        max_rows=REPORT_TOP_ROWS,
    )
    score_table = prepare_dashboard_table(
        score_bucket_stats,
        ["alert_direction", "score_bucket", "signal_count", "favorable_rate_pct", "adverse_rate_pct", "neutral_rate_pct", "avg_favorable_move_pct", "avg_adverse_move_pct", "expectancy"],
        max_rows=REPORT_TOP_ROWS,
    )
    best_setups_table = prepare_dashboard_table(
        best_setups,
        ["alert_direction", "followup_stage", "rsi_bucket", "score_bucket", "quote_volume_bucket", "volume_ratio_bucket", "signal_count", "favorable_rate_pct", "adverse_rate_pct", "avg_favorable_move_pct", "avg_adverse_move_pct", "expectancy"],
        max_rows=REPORT_TOP_ROWS,
    )
    pending_table = prepare_dashboard_table(
        pending_stage_counts,
        ["followup_stage", "pending_count"],
        stage_definitions=stage_definitions,
        keep_stage_order=True,
    )
    missing_table = prepare_dashboard_table(
        missing_followups,
        ["followup_stage", "alert_symbol", "alert_direction", "alert_sent_at", "overdue_minutes", "alert_rsi", "alert_score", "quote_volume", "volume_ratio"],
        max_rows=REPORT_DIAGNOSTIC_ROWS,
    )
    big_move_metrics = metric_lookup(big_move_overview)
    big_move_overall_count = int(big_move_metrics.get("latest_followups_big_move_5p_count", 0) or 0)
    big_move_overall_rate = float(big_move_metrics.get("latest_followups_big_move_5p_rate_of_latest", 0.0) or 0.0)
    dordo_sent_alert_big_move_count = int(big_move_metrics.get("dordo_sent_alerts_big_move_5p_count", 0) or 0)
    dordo_sent_alert_big_move_rate = float(big_move_metrics.get("dordo_sent_alerts_big_move_5p_rate", 0.0) or 0.0)
    dordo_sent_followup_big_move_count = int(big_move_metrics.get("dordo_sent_followup_big_move_5p_count", 0) or 0)
    dordo_sent_followup_big_move_rate = float(big_move_metrics.get("dordo_sent_followup_big_move_5p_rate", 0.0) or 0.0)
    big_move_cards = "".join(
        [
            render_stat_card(
                f"Во всей истории {BIG_MOVE_THRESHOLD_PCT:.0f}%+ в плюс",
                format_compact_number(big_move_overall_count),
                f"Это {format_percent(big_move_overall_rate)} от всех последних доступных follow-up",
                accent="positive",
            ),
            render_stat_card(
                f"У @{TARGET_DELIVERY_USERNAME}: live alerts -> потом {BIG_MOVE_THRESHOLD_PCT:.0f}%+",
                format_compact_number(dordo_sent_alert_big_move_count),
                f"Это {format_percent(dordo_sent_alert_big_move_rate)} от реально отправленных ему live alerts",
                accent="blue",
            ),
            render_stat_card(
                f"У @{TARGET_DELIVERY_USERNAME}: follow-up уже с {BIG_MOVE_THRESHOLD_PCT:.0f}%+",
                format_compact_number(dordo_sent_followup_big_move_count),
                f"Это {format_percent(dordo_sent_followup_big_move_rate)} от реально отправленных ему follow-up",
                accent="teal",
            ),
        ]
    )
    big_move_overview_table = prepare_dashboard_table(big_move_overview, ["metric", "value"])
    big_move_direction_table = prepare_dashboard_table(
        big_move_direction_stats,
        ["alert_direction", "signal_count", "big_move_count", "big_move_rate_pct", "avg_big_move_pct", "median_big_move_pct", "max_big_move_pct"],
        max_rows=REPORT_TOP_ROWS,
    )
    big_move_stage_table = prepare_dashboard_table(
        big_move_stage_stats,
        ["followup_stage", "alert_direction", "signal_count", "big_move_count", "big_move_rate_pct", "avg_big_move_pct", "median_big_move_pct", "max_big_move_pct"],
        max_rows=REPORT_TOP_ROWS,
    )
    dordo_sent_alert_table = prepare_dashboard_table(
        dordo_sent_alert_stats,
        ["bot_kind", "alert_direction", "sent_count", "unique_alert_count", "latest_ready_count", "big_move_count", "big_move_rate_pct", "ready_big_move_rate_pct", "avg_big_move_pct", "median_big_move_pct", "max_big_move_pct"],
        max_rows=REPORT_TOP_ROWS,
    )
    dordo_sent_followup_table = prepare_dashboard_table(
        dordo_sent_followup_stats,
        ["bot_kind", "delivery_stage", "alert_direction", "signal_count", "big_move_count", "big_move_rate_pct", "avg_big_move_pct", "median_big_move_pct", "max_big_move_pct"],
        max_rows=REPORT_TOP_ROWS,
    )
    liquidity_rsi_combo_table = prepare_dashboard_table(
        liquidity_rsi_combo_stats,
        ["alert_direction", "quote_volume_bucket", "rsi_bucket", "signal_count", "favorable_rate_pct", "take5_rate_pct", "stop5_rate_pct", "both_5_hit_rate_pct", "avg_favorable_move_pct", "avg_adverse_move_pct", "expectancy"],
        max_rows=REPORT_TOP_ROWS,
    )
    score_liquidity_combo_table = prepare_dashboard_table(
        score_liquidity_combo_stats,
        ["alert_direction", "quote_volume_bucket", "score_bucket", "signal_count", "favorable_rate_pct", "take5_rate_pct", "stop5_rate_pct", "both_5_hit_rate_pct", "avg_favorable_move_pct", "avg_adverse_move_pct", "expectancy"],
        max_rows=REPORT_TOP_ROWS,
    )
    ultra_liquid_high_score_table = prepare_dashboard_table(
        ultra_liquid_high_score_stats,
        ["alert_direction", "rsi_bucket", "signal_count", "favorable_rate_pct", "take5_rate_pct", "stop5_rate_pct", "both_5_hit_rate_pct", "avg_favorable_move_pct", "avg_adverse_move_pct", "expectancy"],
        max_rows=REPORT_COMPACT_ROWS,
    )
    dordo_sent_outcome_table = prepare_dashboard_table(
        dordo_sent_outcome_stats,
        ["bot_kind", "alert_direction", "sent_count", "latest_ready_count", "ready_coverage_pct", "favorable_rate_pct", "take5_rate_ready_pct", "stop5_rate_ready_pct", "both_5_hit_rate_pct", "avg_favorable_move_pct", "avg_adverse_move_pct", "expectancy"],
    )
    dordo_recent_window_table = select_existing_columns(
        dordo_recent_window_stats,
        ["period_label", "sent_count", "latest_ready_count", "ready_coverage_pct", "favorable_rate_pct", "take5_rate_ready_pct", "stop5_rate_ready_pct", "both_5_hit_rate_pct", "avg_favorable_move_pct", "avg_adverse_move_pct", "expectancy"],
    )
    dordo_rsi_bucket_table = prepare_dashboard_table(
        dordo_rsi_bucket_stats,
        ["bot_kind", "alert_direction", "rsi_bucket", "sent_count", "latest_ready_count", "favorable_rate_pct", "adverse_rate_pct", "neutral_rate_pct", "avg_favorable_move_pct", "avg_adverse_move_pct", "expectancy"],
        max_rows=REPORT_TOP_ROWS,
    )
    dordo_score_bucket_table = prepare_dashboard_table(
        dordo_score_bucket_stats,
        ["bot_kind", "alert_direction", "score_bucket", "sent_count", "latest_ready_count", "favorable_rate_pct", "adverse_rate_pct", "neutral_rate_pct", "avg_favorable_move_pct", "avg_adverse_move_pct", "expectancy"],
        max_rows=REPORT_TOP_ROWS,
    )
    dordo_combo_table = prepare_dashboard_table(
        dordo_combo_stats,
        ["bot_kind", "alert_direction", "quote_volume_bucket", "score_bucket", "rsi_bucket", "sent_count", "latest_ready_count", "favorable_rate_pct", "take5_rate_ready_pct", "stop5_rate_ready_pct", "both_5_hit_rate_pct", "avg_favorable_move_pct", "avg_adverse_move_pct", "expectancy"],
        max_rows=REPORT_TOP_ROWS,
    )
    dordo_recent_details_table = prepare_dashboard_table(
        dordo_sent_alert_details,
        ["delivered_at", "bot_kind", "alert_symbol", "alert_direction", "alert_rsi", "alert_score", "quote_volume_bucket", "latest_followup_stage", "latest_thesis_result_state", "latest_favorable_move_pct", "latest_adverse_move_pct", "path_5_status", "delivery_age_days"],
        max_rows=REPORT_COMPACT_ROWS,
    )
    validation_table = prepare_dashboard_table(
        validation_checks,
        ["status", "check_name", "details"],
    )
    validation_fail_count = int(validation_checks["status"].eq("FAIL").sum()) if not validation_checks.empty else 0
    validation_warn_count = int(validation_checks["status"].eq("WARN").sum()) if not validation_checks.empty else 0
    validation_pass_count = int(validation_checks["status"].eq("PASS").sum()) if not validation_checks.empty else 0
    validation_callout = (
        f"Проверок OK: {validation_pass_count}. "
        f"Вниманий: {validation_warn_count}. "
        f"Критичных ошибок: {validation_fail_count}."
    )

    dordo_ready_total = int(dordo_sent_outcome_stats["latest_ready_count"].sum()) if not dordo_sent_outcome_stats.empty else 0
    dordo_sent_total = int(dordo_sent_outcome_stats["sent_count"].sum()) if not dordo_sent_outcome_stats.empty else 0
    dordo_take5_total = int(dordo_sent_outcome_stats["take5_hit_count"].sum()) if not dordo_sent_outcome_stats.empty else 0
    dordo_stop5_total = int(dordo_sent_outcome_stats["stop5_hit_count"].sum()) if not dordo_sent_outcome_stats.empty else 0
    dordo_take5_rate_ready = (dordo_take5_total / dordo_ready_total * 100.0) if dordo_ready_total else 0.0
    dordo_stop5_rate_ready = (dordo_stop5_total / dordo_ready_total * 100.0) if dordo_ready_total else 0.0
    dordo_recent_30 = dordo_recent_window_stats[dordo_recent_window_stats["period_label"] == "last_30d"].head(1)
    dordo_recent_30_take5 = float(dordo_recent_30.iloc[0]["take5_rate_ready_pct"]) if not dordo_recent_30.empty and "take5_rate_ready_pct" in dordo_recent_30.columns else 0.0
    dordo_recent_30_win = float(dordo_recent_30.iloc[0]["favorable_rate_pct"]) if not dordo_recent_30.empty and "favorable_rate_pct" in dordo_recent_30.columns else 0.0
    dordo_cards = "".join(
        [
            render_stat_card(
                f"@{TARGET_DELIVERY_USERNAME}: реально отправлено live alerts",
                format_compact_number(dordo_sent_total),
                f"Из них уже есть итог по {format_compact_number(dordo_ready_total)} сигналам",
                accent="blue",
            ),
            render_stat_card(
                f"@{TARGET_DELIVERY_USERNAME}: касались +{BIG_MOVE_THRESHOLD_PCT:.0f}% после алерта",
                format_compact_number(dordo_take5_total),
                f"Это {format_percent(dordo_take5_rate_ready)} среди тех, где итог уже известен",
                accent="positive",
            ),
            render_stat_card(
                f"@{TARGET_DELIVERY_USERNAME}: уходили на {BIG_MOVE_THRESHOLD_PCT:.0f}% против идеи",
                format_compact_number(dordo_stop5_total),
                f"Это {format_percent(dordo_stop5_rate_ready)} среди тех, где итог уже известен",
                accent="negative",
            ),
            render_stat_card(
                "Насколько это актуально сейчас",
                format_percent(dordo_recent_30_take5),
                f"За последние 30 дней у тебя +5% касались в {format_percent(dordo_recent_30_take5)} случаев, win rate {format_percent(dordo_recent_30_win)}",
                accent="teal",
            ),
        ]
    )

    context_sections = []
    for title, table in context_tables:
        prepared_context = prepare_dashboard_table(
            table,
            ["value", "signal_count", "favorable_rate_pct", "adverse_rate_pct", "neutral_rate_pct", "avg_favorable_move_pct", "avg_adverse_move_pct", "expectancy"],
            max_rows=REPORT_COMPACT_ROWS,
        )
        context_sections.append(
            f'<div class="sub-card"><h3>{escape(title)}</h3>'
            '<p class="section-note">Строки отсортированы по win rate по убыванию. Смотри на верхние строки, но всегда держи в голове размер выборки.</p>'
            f'{dataframe_to_html(prepared_context, humanize=True)}</div>'
        )
    context_html = "\n".join(context_sections) if context_sections else "<p>Подходящих контекстных признаков с внятным покрытием в истории не нашлось.</p>"

    unavailable_html = (
        f"<p><strong>Чего реально нет в истории:</strong> {escape(', '.join(unavailable_fields))}</p>"
        if unavailable_fields
        else "<p><strong>Чего реально нет в истории:</strong> критически важных запрошенных блоков не обнаружено.</p>"
    )

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>{escape(REPORT_TITLE_RU)}</title>
  <style>
    :root {{
      --bg: #f3f7fb;
      --card: #ffffff;
      --text: #162033;
      --muted: #5b6579;
      --line: #d8e2ef;
      --blue: #2563eb;
      --green: #10b981;
      --red: #ef4444;
      --amber: #f59e0b;
      --shadow: 0 10px 30px rgba(15, 23, 42, 0.07);
    }}
    body {{
      font-family: "Segoe UI", Tahoma, Arial, sans-serif;
      margin: 0 auto;
      max-width: 1400px;
      padding: 24px 18px 60px;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(37, 99, 235, 0.10), transparent 28%),
        radial-gradient(circle at top right, rgba(20, 184, 166, 0.10), transparent 24%),
        var(--bg);
      line-height: 1.5;
    }}
    h1, h2, h3 {{ color: #0f172a; margin-top: 0; }}
    p {{ color: var(--muted); }}
    .hero {{
      background: linear-gradient(135deg, #0f172a, #1d4ed8);
      color: white;
      border-radius: 20px;
      padding: 28px 30px;
      box-shadow: var(--shadow);
      margin-bottom: 18px;
    }}
    .hero p {{ color: rgba(255,255,255,0.84); max-width: 980px; margin-bottom: 0; }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 20px 22px;
      margin: 16px 0;
      box-shadow: var(--shadow);
    }}
    .sub-card {{
      background: #f8fbff;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px 16px;
      margin-top: 16px;
    }}
    .grid-3, .stats-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }}
    .grid-2 {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
    .stat-card {{
      background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(246,250,255,0.98));
      border: 1px solid var(--line);
      border-left: 6px solid var(--accent, var(--blue));
      border-radius: 16px;
      padding: 16px 18px;
      box-shadow: var(--shadow);
    }}
    .stat-card__title {{ font-size: 13px; color: var(--muted); margin-bottom: 8px; }}
    .stat-card__value {{ font-size: 30px; font-weight: 700; line-height: 1.1; color: #0f172a; margin-bottom: 8px; }}
    .stat-card__subtitle {{ font-size: 13px; color: var(--muted); }}
    .stat-card__subtitle--rich {{ font-size: 14px; line-height: 1.45; color: var(--text); }}
    .viz-card {{ background: #f8fbff; border: 1px solid var(--line); border-radius: 16px; padding: 16px 18px; }}
    .donut-wrap {{ display: flex; gap: 18px; align-items: center; flex-wrap: wrap; }}
    .donut-chart {{ position: relative; width: 180px; height: 180px; flex: 0 0 auto; }}
    .donut-chart svg {{ width: 180px; height: 180px; display: block; }}
    .donut-center {{ position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; flex-direction: column; text-align: center; pointer-events: none; }}
    .donut-value {{ font-size: 24px; font-weight: 700; color: #0f172a; }}
    .donut-label {{ font-size: 12px; color: var(--muted); }}
    .legend-list {{ min-width: 220px; flex: 1 1 220px; }}
    .legend-item {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 6px 0; border-bottom: 1px dashed #d9e4f2; font-size: 14px; }}
    .legend-swatch {{ width: 12px; height: 12px; border-radius: 999px; display: inline-block; margin-right: 8px; }}
    .mini-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }}
    .mini-card {{ background: #fcfdff; border: 1px solid var(--line); border-radius: 16px; padding: 16px; }}
    .mini-card--accent {{ border-top: 5px solid var(--mini-accent, var(--blue)); }}
    .mini-card__title {{ font-size: 17px; font-weight: 700; color: #0f172a; margin-bottom: 6px; }}
    .mini-card__meta {{ font-size: 13px; color: var(--muted); margin-bottom: 14px; }}
    .mini-card__block {{ margin-top: 12px; }}
    .mini-card__label {{ font-size: 12px; color: var(--muted); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.04em; }}
    .mini-card__numbers {{ font-size: 13px; color: var(--text); margin-top: 8px; }}
    .stacked-bar {{ width: 100%; height: 12px; display: flex; overflow: hidden; border-radius: 999px; background: #e5edf6; }}
    .stacked-bar--empty {{ background: #edf2f7; }}
    .stacked-bar__segment {{ display: block; height: 100%; }}
    .table-scroll {{ overflow-x: auto; padding-bottom: 4px; }}
    .report-table {{ width: 100%; min-width: 720px; border-collapse: collapse; font-size: 13px; margin: 8px 0 0; }}
    .report-table th, .report-table td {{ border: 1px solid var(--line); padding: 8px 10px; text-align: left; vertical-align: top; }}
    .report-table th {{ background: #eaf2ff; }}
    .report-table tr:nth-child(even) td {{ background: #f9fbff; }}
    .lead {{ font-size: 14px; color: var(--muted); margin-top: -2px; margin-bottom: 16px; }}
    .section-note {{ font-size: 13px; color: var(--muted); margin: 4px 0 12px; }}
    .callout {{ background: #eef6ff; border: 1px solid #cfe0ff; border-radius: 14px; padding: 14px 16px; color: #274472; margin: 14px 0 0; }}
    details summary {{ cursor: pointer; font-weight: 700; color: #16335f; }}
    code {{ background: #eef2ff; padding: 2px 6px; border-radius: 4px; }}
    @media (max-width: 1100px) {{ .stats-grid, .grid-3, .mini-grid {{ grid-template-columns: 1fr 1fr; }} }}
    @media (max-width: 760px) {{ .stats-grid, .grid-3, .grid-2, .mini-grid {{ grid-template-columns: 1fr; }} .hero {{ padding: 22px 20px; }} .donut-wrap {{ flex-direction: column; align-items: flex-start; }} }}
  </style>
</head>
<body>
<section class="hero">
    <h1>{escape(REPORT_TITLE_RU)}</h1>
    <p>Это уже не сырой техлог, а понятный дашборд по историческим RSI-сигналам. Главная цель: быстро увидеть, где win rate выше, какие фильтры выглядели сильнее и в каких условиях идея чаще шла в нужную сторону.</p>
    <p class="section-note" style="color: rgba(255,255,255,0.86); margin-top: 10px;">Для удобства на экране показываются только лучшие строки: обычно топ {REPORT_TOP_ROWS}, а в самых широких таблицах топ {REPORT_COMPACT_ROWS}. Полные выгрузки без обрезки лежат в <code>test/output</code> в CSV.</p>
  </section>

  <div class="card">
    <h2>Краткий итог</h2>
    <p class="lead">Главные цифры, чтобы сразу понять масштаб истории, покрытие follow-up и общий уровень качества сигналов.</p>
    <div class="stats-grid">{summary_cards}</div>
  </div>

  <div class="card">
    <h2>Как это читать без боли</h2>
    <p class="lead">Короткая расшифровка самых важных терминов. Здесь как раз ответы на вопросы «что значит пошло против идеи», «что такое volume ratio» и «что означают 2ч / 4ч / 8ч».</p>
    <div class="stats-grid">{explainer_cards_html}</div>
  </div>

  <div class="card">
    <h2>Сначала лично по @{TARGET_DELIVERY_USERNAME}</h2>
    <p class="lead">Эта секция идет раньше общей статы, чтобы сначала понять именно твою реальную историю доставок. Здесь считаются только реально отправленные тебе live alerts, а не просто сигналы в базе. Для честности это <code>metadata.sent = true</code>.</p>
    <div class="stats-grid">{dordo_cards}</div>
    <div class="callout">Без отдельной базы свечей нельзя узнать, что произошло раньше внутри движения: условный тейк +5% или условный стоп -5%. Поэтому ниже это показано честно как четыре варианта: дошли до +5, уходили на -5 против идеи, успели сделать и то и другое или не дошли ни до одного порога.</div>
    <div class="sub-card">
      <h3>Как закончились реально отправленные тебе live alerts</h3>
      <p class="section-note">Это главная персональная таблица. Она показывает, что реально прилетало тебе, сколько уже имеет итог и как часто такие сигналы потом доходили до +5 или уходили на -5 против идеи.</p>
      {dataframe_to_html(dordo_sent_outcome_table, humanize=True)}
    </div>
    <div class="sub-card">
      <h3>Насколько это актуально сейчас</h3>
      <p class="section-note">Здесь идет сравнение всей истории против последних 30 и 90 дней. Это самый прямой ответ на вопрос, не устарело ли уже то, что тебе присылалось.</p>
      {dataframe_to_html(dordo_recent_window_table, humanize=True)}
    </div>
    <div class="sub-card">
      <h3>Где RSI работал лучше именно среди отправленного тебе</h3>
      <p class="section-note">Это такой же разрез, как в общей таблице по RSI, но только по реально отправленным тебе сигналам. Чтобы не шуметь, здесь оставлены только группы с хотя бы <code>{DORDO_COMBO_MIN_SAMPLE_SIZE}</code> готовыми итогами.</p>
      {dataframe_to_html(dordo_rsi_bucket_table, humanize=True)}
    </div>
    <div class="sub-card">
      <h3>Где score работал лучше именно среди отправленного тебе</h3>
      <p class="section-note">Тут видно, какие диапазоны score были сильнее именно в твоей истории доставок, а не по рынку в целом.</p>
      {dataframe_to_html(dordo_score_bucket_table, humanize=True)}
    </div>
    <div class="sub-card">
      <h3>Какие сочетания работали лучше именно среди отправленного тебе</h3>
      <p class="section-note">Тут уже совместная персональная статистика: бот, тип сигнала, ликвидность, score и зона RSI. Сверху комбинации с лучшим win rate и более сильным профилем по +5 / -5.</p>
      {dataframe_to_html(dordo_combo_table, humanize=True)}
    </div>
    <div class="sub-card">
      <h3>Последние реально отправленные тебе live alerts</h3>
      <p class="section-note">Полезно, если хочешь глазами проверить самые свежие случаи: что именно прилетало, чем закончилось и по какому сценарию ходило относительно порога 5%.</p>
      {dataframe_to_html(dordo_recent_details_table, humanize=True)}
    </div>
  </div>

  <div class="card">
    <h2>Проверка точности данных</h2>
    <p class="lead">Эта секция автоматически сверяет отчет с raw SQLite. `Внимание` здесь не всегда значит ошибка: иногда это просто важный контекст, который может влиять на чтение таблиц.</p>
    <div class="callout">{escape(validation_callout)}</div>
    {dataframe_to_html(validation_table, humanize=True)}
  </div>

  <div class="card">
    <h2>Быстрый взгляд на картину</h2>
    <p class="lead">Три самые важные диаграммы: из чего состоят сигналы, как часто последний follow-up закрывался в плюс и насколько хорошо покрыта первая проверка.</p>
    <div class="grid-3">{donut_signals}{donut_outcomes}{donut_coverage}</div>
    <div class="callout">Если читать отчет по-простому, то смотри в таком порядке: <strong>win rate</strong>, потом <strong>размер выборки</strong>, потом <strong>средний ход в плюс</strong> и <strong>средний ход против</strong>. Числа 2ч / 4ч / 8ч ниже означают просто момент проверки сигнала спустя это время, а не отдельный индикатор.</div>
  </div>

  <div class="card">
    <h2>Если нужен короткий ответ</h2>
    <p class="lead">Самые полезные выводы из истории в одном месте: что чаще срабатывало, где RSI был сильнее и какие фильтры по объему и score выглядели лучше.</p>
    <div class="stats-grid">{highlights_html}</div>
  </div>

  <div class="card">
    <h2>Через сколько часов сигнал обычно уже был понятен</h2>
    <p class="lead">2ч / 4ч / 8ч здесь означают только время после сигнала, когда мы перепроверили результат. Это не индикатор. Сначала карточки, затем таблица по тем же данным.</p>
    <div class="mini-grid">{stage_cards_html}</div>
    <h3>Таблица по времени проверки</h3>
    <p class="section-note">Эта таблица специально идет по времени: сначала проверка через 2 часа, потом через 4 и 8 часов.</p>
    {dataframe_to_html(stage_table, humanize=True)}
  </div>

  <div class="card">
    <h2>Что чаще работало: перепроданность или перекупленность</h2>
    <p class="lead">Здесь видно, какая сторона RSI исторически вела себя сильнее. В карточках короткая сводка, в таблицах точные цифры.</p>
    <div class="grid-2">{direction_cards_html}</div>
    <h3>Сводка по сторонам</h3>
    <p class="section-note">Строки ниже отсортированы по win rate по убыванию.</p>
    {dataframe_to_html(direction_table, humanize=True)}
    <h3>Лучшие сочетания «сторона + время проверки»</h3>
    <p class="section-note">Тоже отсортировано по win rate, чтобы сверху были самые сильные сочетания.</p>
    {dataframe_to_html(direction_stage_table, humanize=True)}
  </div>

  <div class="card">
    <h2>Где RSI работал лучше</h2>
    <p class="lead">Эта таблица отвечает на вопрос: в каких именно зонах RSI сигналы выглядели сильнее. Сначала идут строки с лучшим win rate и нормальной выборкой.</p>
    <p class="section-note">Сначала смотри на win rate и размер выборки. Потом уже на средний ход в плюс и средний ход против.</p>
    {dataframe_to_html(rsi_table, humanize=True)}
  </div>

  <div class="card">
    <h2>Что дает фильтр по объему</h2>
    <p class="lead">Тут две разные вещи. <strong>Объем рынка в USDT</strong> показывает, насколько сам актив ликвидный. <strong>Относительный объем</strong> показывает, насколько текущий объем выше или ниже своей обычной нормы.</p>
    <div class="grid-2">
      <div class="sub-card">
        <h3>Объем рынка в USDT</h3>
        <p class="section-note">Подходит, если хочешь отсеивать совсем неликвидные монеты.</p>
        {dataframe_to_html(volume_usdt_table, humanize=True)}
      </div>
      <div class="sub-card">
        <h3>Относительный объем</h3>
        <p class="section-note">1.0 = объем примерно как обычно. 2.0 = объем примерно в 2 раза выше обычного.</p>
        {dataframe_to_html(volume_ratio_table, humanize=True)}
      </div>
    </div>
  </div>

  <div class="card">
    <h2>Где помогает score</h2>
    <p class="lead">Если хочешь ужесточать фильтр качества сигнала, это основной блок. Вверху оказываются диапазоны score с лучшим win rate.</p>
    {dataframe_to_html(score_table, humanize=True)}
  </div>

  <div class="card">
    <h2>Сильные результаты {BIG_MOVE_THRESHOLD_PCT:.0f}%+</h2>
    <p class="lead">Это отдельный блок про по-настоящему сильные исходы. Здесь считаются только те случаи, где идея была favorable и движение в плюс достигало хотя бы {BIG_MOVE_THRESHOLD_PCT:.0f}%.</p>
    <div class="stats-grid">{big_move_cards}</div>
    <div class="sub-card">
      <h3>Краткая сводка 5%+</h3>
      <p class="section-note">Ниже сразу видно, сколько таких сильных результатов было вообще по всей истории и отдельно по реально отправленным сообщениям пользователю @{TARGET_DELIVERY_USERNAME}.</p>
      {dataframe_to_html(big_move_overview_table, humanize=True)}
    </div>
    <div class="sub-card">
      <h3>Во всей истории: где 5%+ встречалось чаще</h3>
      <p class="section-note">Сначала идет срез по стороне сигнала, затем более детальный срез по времени проверки и стороне.</p>
      {dataframe_to_html(big_move_direction_table, humanize=True)}
      {dataframe_to_html(big_move_stage_table, humanize=True)}
    </div>
    <div class="sub-card">
      <h3>@{TARGET_DELIVERY_USERNAME}: из реально отправленных live alerts сколько потом дали 5%+</h3>
      <p class="section-note">Считаются только записи доставки, где отправка реально состоялась: <code>metadata.sent = true</code>. Это не просто кандидаты, а именно дошедшие алерты.</p>
      {dataframe_to_html(dordo_sent_alert_table, humanize=True)}
    </div>
    <div class="sub-card">
      <h3>@{TARGET_DELIVERY_USERNAME}: из реально отправленных follow-up сколько уже были 5%+</h3>
      <p class="section-note">Это отдельный взгляд: не live alert, а уже follow-up сообщения, которые пользователь реально получил и которые сами по себе показывали сильный итог 5%+.</p>
      {dataframe_to_html(dordo_sent_followup_table, humanize=True)}
    </div>
  </div>

  <div class="card">
    <h2>Совместные фильтры: ликвидность, RSI и score</h2>
    <p class="lead">Это уже блок не про один фильтр, а про их сочетания. Здесь можно быстро проверить идею про <strong>50M+</strong>, <strong>score 90+</strong> и понять, в каких RSI-зонах это реально выглядело сильнее.</p>
    <div class="sub-card">
      <h3>Ликвидность + RSI</h3>
      <p class="section-note">Строки отсортированы по win rate. Здесь сразу видно, на какой ликвидности и в какой зоне RSI сигнал выглядел сильнее. Плюс отдельно показано, как часто сигнал хотя бы касался +5% и как часто уходил на -5% против идеи.</p>
      {dataframe_to_html(liquidity_rsi_combo_table, humanize=True)}
    </div>
    <div class="sub-card">
      <h3>Ликвидность + score</h3>
      <p class="section-note">Это полезно, если хочешь понять, стоит ли ужесточать одновременно фильтр по ликвидности и по качеству сетапа. Тут видно, где score реально помогал, а где нет.</p>
      {dataframe_to_html(score_liquidity_combo_table, humanize=True)}
    </div>
    <div class="sub-card">
      <h3>Отдельно: очень ликвидные монеты 50M+ и score 90+</h3>
      <p class="section-note">Это узкий срез именно под твой вопрос. Тут показано, какие RSI-зоны были сильнее, если монета уже была очень ликвидной, а score был 90+.</p>
      {dataframe_to_html(ultra_liquid_high_score_table, humanize=True)}
    </div>
  </div>

  <div class="card">
    <h2>Что еще влияло на качество сигнала</h2>
    <p class="lead">Здесь только те признаки, которые реально нашлись в historical metadata. Это дополнительные подсказки, а не базовые правила входа.</p>
    {context_html}
    <details class="sub-card">
      <summary>Показать служебные ключи metadata</summary>
      <div class="sub-card">
        <h3>Ключи в metadata сигналов</h3>
        {dataframe_to_html(alert_metadata_table, max_rows=REPORT_METADATA_ROWS, humanize=True)}
      </div>
      <div class="sub-card">
        <h3>Ключи в metadata follow-up</h3>
        {dataframe_to_html(followup_metadata_table, max_rows=REPORT_METADATA_ROWS, humanize=True)}
      </div>
    </details>
  </div>

  <div class="card">
    <h2>Лучшие сочетания условий</h2>
    <p class="lead">Это уже готовые комбинации: сторона сигнала, время проверки, зона RSI, score и объем. В отчет попадают только группы с выборкой не меньше <code>{MIN_SAMPLE_SIZE}</code>.</p>
    <p class="section-note">Таблица отсортирована по win rate по убыванию, затем по edge score и размеру выборки.</p>
    {dataframe_to_html(best_setups_table, humanize=True)}
  </div>

  <div class="card">
    <h2>Диагностика missing / pending follow-up</h2>
    <p class="lead">Этот блок нужен, чтобы не путать «данных пока нет, потому что еще рано» и «данных нет, хотя уже должны были быть».</p>
    <div class="grid-2">
      <div class="sub-card">
        <h3>Что еще в pending</h3>
        {dataframe_to_html(pending_table, humanize=True)}
      </div>
      <div class="sub-card">
        <h3>Что уже missing overdue</h3>
        {dataframe_to_html(missing_table, humanize=True)}
      </div>
    </div>
  </div>

  <div class="card">
    <h2>Что можно попробовать в фильтрах входа</h2>
    <p class="lead">Это data-driven suggestions по текущей истории, а не гарантия результата. Используй их как идеи для теста, а не как жесткие обещания.</p>
    <ul>{recommendation_items}</ul>
  </div>

  <div class="card">
    <h2>Ограничения и честные оговорки</h2>
    <p>Вся аналитика построена только на том, что реально было сохранено в SQLite на момент сигнала и follow-up. Недостающие признаки не восстанавливались «по догадке».</p>
    {unavailable_html}
    <p><code>strategy_stats_snapshots</code> использовалась только как возможная справка и не является источником истины в этом отчете.</p>
    <p>Логика missing overdue использует длительности стадий плюс небольшой grace window, чтобы не помечать пограничные сигналы как missing слишком рано.</p>
    <div class="sub-card">
      <h3>Техническая сводка</h3>
      {dataframe_to_html(overall_stats, humanize=True)}
    </div>
  </div>
</body>
</html>"""

def main() -> int:
    now_utc = datetime.now(UTC)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not DB_PATH.exists():
        raise FileNotFoundError(f"SQLite database was not found: {DB_PATH}")

    log(f"Using database: {DB_PATH}")
    log("Opening SQLite in read-only mode")
    with connect_read_only(DB_PATH) as connection:
        alert_columns = discover_table_columns(connection, "alerts")
        stage_columns = discover_table_columns(connection, "followup_stage_results")
        final_columns = discover_table_columns(connection, "followup_results")
        delivery_columns = discover_table_columns(connection, "delivered_bot_signals")
        log(f"Discovered alerts columns: {len(alert_columns)}")
        log(f"Discovered followup_stage_results columns: {len(stage_columns)}")
        log(f"Discovered followup_results columns: {len(final_columns)}")
        log(f"Discovered delivered_bot_signals columns: {len(delivery_columns)}")

        log("Loading RSI alerts")
        alerts, alert_metadata_keys = prepare_alerts(connection)
        if alerts.empty:
            raise RuntimeError("No RSI alerts were found in the database.")

        log("Loading stage follow-up rows")
        stage_results_raw, stage_metadata_keys = prepare_followups(connection, source_table="followup_stage_results")
        log("Loading latest/final follow-up rows")
        final_results_raw, final_metadata_keys = prepare_followups(connection, source_table="followup_results")
        log("Resolving delivery target user")
        target_user_id = resolve_delivery_target_user_id(connection, TARGET_DELIVERY_USERNAME)
        log(
            f"Delivery target @{TARGET_DELIVERY_USERNAME} resolved to telegram_user_id={target_user_id}"
            if target_user_id is not None
            else f"Delivery target @{TARGET_DELIVERY_USERNAME} was not found in bot_users"
        )
        log("Loading delivered bot signal history")
        delivered_signals_raw, delivered_metadata_keys = prepare_delivered_bot_signals(connection)

    distinct_stages = sorted(
        {str(value) for value in stage_results_raw["followup_stage"].dropna().astype(str).tolist() if str(value).strip()}
    )
    stage_definitions = detect_stage_definitions(distinct_stages)
    log(f"Configured / discovered stages: {', '.join(sorted(stage_definitions, key=lambda name: stage_sort_key(name, stage_definitions)))}")

    log("Joining alert context into follow-up rows")
    stage_results = attach_alert_context(stage_results_raw, alerts)
    final_results = attach_alert_context(final_results_raw, alerts)

    log("Building latest available follow-up view")
    latest_followups = build_latest_available_followups(stage_results, final_results)
    log("Joining delivery history with alert / follow-up context")
    delivered_signals = attach_delivery_context(delivered_signals_raw, alerts, latest_followups)

    log("Computing bucket columns")
    alerts = add_bucket_columns(alerts)
    stage_results = add_bucket_columns(stage_results)
    final_results = add_bucket_columns(final_results)
    latest_followups = add_bucket_columns(latest_followups)
    delivered_signals = add_bucket_columns(delivered_signals)

    latest_followups["is_big_move"] = build_big_move_flags(
        latest_followups,
        state_column="thesis_result_state",
        favorable_column="favorable_move_pct",
    )
    latest_followups["big_move_value"] = latest_followups["favorable_move_pct"]
    latest_followups = add_take_stop_proxy_columns(
        latest_followups,
        favorable_column="favorable_move_pct",
        adverse_column="adverse_move_pct",
    )
    stage_results["is_big_move"] = build_big_move_flags(
        stage_results,
        state_column="thesis_result_state",
        favorable_column="favorable_move_pct",
    )
    stage_results["big_move_value"] = stage_results["favorable_move_pct"]
    stage_results = add_take_stop_proxy_columns(
        stage_results,
        favorable_column="favorable_move_pct",
        adverse_column="adverse_move_pct",
    )

    log("Computing stage expectation diagnostics")
    stage_expectations = build_stage_expectations(
        alerts,
        stage_results,
        stage_definitions=stage_definitions,
        now_utc=now_utc,
    )

    log("Building core statistics")
    overall_stats = build_overall_stats(
        alerts,
        stage_results,
        final_results_raw,
        latest_followups,
        stage_expectations,
        now_utc=now_utc,
        stage_definitions=stage_definitions,
    )
    stage_stats = build_stage_stats(stage_results, stage_expectations, stage_definitions=stage_definitions)
    direction_stats = build_direction_stats(latest_followups)
    direction_stage_stats = build_direction_stage_stats(stage_results, stage_definitions=stage_definitions)
    rsi_bucket_stats = build_rsi_bucket_stats(latest_followups)
    volume_bucket_stats = build_volume_bucket_stats(latest_followups)
    score_bucket_stats = build_score_bucket_stats(latest_followups)
    best_setups = build_best_setups(stage_results)
    dordo_sent_alerts = build_dordo_sent_alerts(delivered_signals, target_user_id=target_user_id)
    dordo_sent_followups = build_dordo_sent_followups(delivered_signals, target_user_id=target_user_id)
    if not dordo_sent_followups.empty:
        dordo_sent_followups["big_move_value"] = dordo_sent_followups["delivery_favorable_move_pct"]
    big_move_overview = build_big_move_overview_stats(
        alerts,
        latest_followups,
        stage_results,
        dordo_sent_alerts,
        dordo_sent_followups,
        target_user_id=target_user_id,
    )
    big_move_direction_stats = build_big_move_group_stats(latest_followups, ["alert_direction"]).sort_values(
        ["big_move_rate_pct", "big_move_count", "signal_count"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    big_move_stage_stats = build_big_move_group_stats(stage_results, ["followup_stage", "alert_direction"]).sort_values(
        ["big_move_rate_pct", "big_move_count", "signal_count"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    dordo_sent_alert_stats = build_sent_alert_big_move_stats(dordo_sent_alerts, ["bot_kind", "alert_direction"]).sort_values(
        ["big_move_rate_pct", "big_move_count", "sent_count"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    dordo_sent_followup_stats = build_big_move_group_stats(dordo_sent_followups, ["bot_kind", "delivery_stage", "alert_direction"]).sort_values(
        ["big_move_rate_pct", "big_move_count", "signal_count"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    liquidity_rsi_combo_stats = build_joint_condition_stats(
        latest_followups,
        ["alert_direction", "quote_volume_bucket", "rsi_bucket"],
        min_sample_size=JOINT_COMBO_MIN_SAMPLE_SIZE,
    )
    score_liquidity_combo_stats = build_joint_condition_stats(
        latest_followups,
        ["alert_direction", "quote_volume_bucket", "score_bucket"],
        min_sample_size=JOINT_COMBO_MIN_SAMPLE_SIZE,
    )
    ultra_liquid_high_score_stats = build_joint_condition_stats(
        latest_followups[
            latest_followups["quote_volume_bucket"].eq("50M+")
            & latest_followups["score_bucket"].eq("90+")
        ].copy(),
        ["alert_direction", "rsi_bucket"],
        min_sample_size=1,
    )
    dordo_sent_outcome_stats = build_sent_alert_outcome_stats(
        dordo_sent_alerts,
        ["bot_kind", "alert_direction"],
    )
    dordo_recent_window_stats = build_recent_sent_alert_window_stats(
        dordo_sent_alerts,
        now_utc=now_utc,
        windows_days=RECENT_WINDOWS_DAYS,
    )
    dordo_rsi_bucket_stats = build_sent_alert_outcome_stats(
        dordo_sent_alerts,
        ["bot_kind", "alert_direction", "rsi_bucket"],
        min_sample_size=DORDO_COMBO_MIN_SAMPLE_SIZE,
    )
    dordo_score_bucket_stats = build_sent_alert_outcome_stats(
        dordo_sent_alerts,
        ["bot_kind", "alert_direction", "score_bucket"],
        min_sample_size=DORDO_COMBO_MIN_SAMPLE_SIZE,
    )
    dordo_combo_stats = build_sent_alert_outcome_stats(
        dordo_sent_alerts,
        ["bot_kind", "alert_direction", "quote_volume_bucket", "score_bucket", "rsi_bucket"],
        min_sample_size=DORDO_COMBO_MIN_SAMPLE_SIZE,
    )
    dordo_sent_alert_details = build_sent_alert_detail_rows(
        dordo_sent_alerts,
        now_utc=now_utc,
    )
    missing_followups = stage_expectations[stage_expectations["stage_status"] == "missing_overdue"].copy()
    pending_stage_counts = (
        stage_expectations[stage_expectations["stage_status"] == "pending"]
        .groupby("followup_stage", dropna=False)
        .agg(pending_count=("alert_id", "size"))
        .reset_index()
        .sort_values("followup_stage", key=lambda series: series.map(lambda value: stage_sort_key(str(value), stage_definitions)))
    )

    missing_followups = missing_followups[
        [
            "alert_id",
            "alert_symbol",
            "alert_direction",
            "followup_stage",
            "alert_sent_at",
            "stage_due_at",
            "stage_overdue_after",
            "alert_age_hours",
            "overdue_minutes",
            "alert_rsi",
            "alert_score",
            "quote_volume",
            "volume_ratio",
        ]
    ].sort_values(["followup_stage", "overdue_minutes"], ascending=[True, False]).reset_index(drop=True)

    alert_metadata_table = metadata_key_table(alert_metadata_keys, len(alerts))
    followup_metadata_table = metadata_key_table(
        stage_metadata_keys + final_metadata_keys + delivered_metadata_keys,
        len(stage_results) + len(final_results) + len(delivered_signals),
    )
    context_tables = build_context_feature_tables(latest_followups)
    unavailable_fields = collect_unavailable_fields(alert_columns, set(alert_metadata_keys), set(stage_metadata_keys) | set(final_metadata_keys))
    recommendations = build_recommendations(latest_followups, best_setups)
    validation_checks = build_validation_checks(
        alerts=alerts,
        stage_results=stage_results,
        final_results=final_results,
        latest_followups=latest_followups,
        stage_stats=stage_stats,
        overall_stats=overall_stats,
        dordo_sent_alerts=dordo_sent_alerts,
        dordo_sent_followups=dordo_sent_followups,
        dordo_sent_outcome_stats=dordo_sent_outcome_stats,
        dordo_recent_window_stats=dordo_recent_window_stats,
    )

    log("Writing CSV outputs")
    save_csv(overall_stats, OUTPUT_DIR / "overall_stats.csv")
    save_csv(validation_checks, OUTPUT_DIR / "validation_checks.csv")
    save_csv(stage_stats, OUTPUT_DIR / "stage_stats.csv")
    save_csv(best_setups, OUTPUT_DIR / "best_setups.csv")
    save_csv(rsi_bucket_stats, OUTPUT_DIR / "rsi_buckets.csv")
    save_csv(volume_bucket_stats, OUTPUT_DIR / "volume_buckets.csv")
    save_csv(score_bucket_stats, OUTPUT_DIR / "score_buckets.csv")
    save_csv(missing_followups, OUTPUT_DIR / "missing_followups.csv")
    save_csv(big_move_overview, OUTPUT_DIR / "big_moves_overview.csv")
    save_csv(big_move_direction_stats, OUTPUT_DIR / "big_moves_by_direction.csv")
    save_csv(big_move_stage_stats, OUTPUT_DIR / "big_moves_by_stage.csv")
    save_csv(dordo_sent_alert_stats, OUTPUT_DIR / "dordo_sent_alert_big_moves.csv")
    save_csv(dordo_sent_followup_stats, OUTPUT_DIR / "dordo_sent_followup_big_moves.csv")
    save_csv(liquidity_rsi_combo_stats, OUTPUT_DIR / "liquidity_rsi_combos.csv")
    save_csv(score_liquidity_combo_stats, OUTPUT_DIR / "score_liquidity_combos.csv")
    save_csv(ultra_liquid_high_score_stats, OUTPUT_DIR / "ultra_liquid_score90_rsi.csv")
    save_csv(dordo_sent_outcome_stats, OUTPUT_DIR / "dordo_sent_alert_outcomes.csv")
    save_csv(dordo_recent_window_stats, OUTPUT_DIR / "dordo_recent_windows.csv")
    save_csv(dordo_rsi_bucket_stats, OUTPUT_DIR / "dordo_rsi_buckets.csv")
    save_csv(dordo_score_bucket_stats, OUTPUT_DIR / "dordo_score_buckets.csv")
    save_csv(dordo_combo_stats, OUTPUT_DIR / "dordo_sent_alert_combos.csv")
    save_csv(dordo_sent_alert_details, OUTPUT_DIR / "dordo_sent_alert_details.csv")

    log("Rendering report files")
    markdown_report = build_markdown_report(
        overall_stats=overall_stats,
        validation_checks=validation_checks,
        stage_stats=stage_stats,
        direction_stats=direction_stats,
        direction_stage_stats=direction_stage_stats,
        rsi_bucket_stats=rsi_bucket_stats,
        volume_bucket_stats=volume_bucket_stats,
        score_bucket_stats=score_bucket_stats,
        best_setups=best_setups,
        missing_followups=missing_followups,
        pending_stage_counts=pending_stage_counts,
        alert_metadata_table=alert_metadata_table,
        followup_metadata_table=followup_metadata_table,
        context_tables=context_tables,
        recommendations=recommendations,
        unavailable_fields=unavailable_fields,
        big_move_overview=big_move_overview,
        big_move_direction_stats=big_move_direction_stats,
        big_move_stage_stats=big_move_stage_stats,
        dordo_sent_alert_stats=dordo_sent_alert_stats,
        dordo_sent_followup_stats=dordo_sent_followup_stats,
        liquidity_rsi_combo_stats=liquidity_rsi_combo_stats,
        score_liquidity_combo_stats=score_liquidity_combo_stats,
        ultra_liquid_high_score_stats=ultra_liquid_high_score_stats,
        dordo_sent_outcome_stats=dordo_sent_outcome_stats,
        dordo_recent_window_stats=dordo_recent_window_stats,
        dordo_rsi_bucket_stats=dordo_rsi_bucket_stats,
        dordo_score_bucket_stats=dordo_score_bucket_stats,
        dordo_combo_stats=dordo_combo_stats,
        dordo_sent_alert_details=dordo_sent_alert_details,
    )
    html_report = build_html_report(
        overall_stats=overall_stats,
        validation_checks=validation_checks,
        stage_stats=stage_stats,
        direction_stats=direction_stats,
        direction_stage_stats=direction_stage_stats,
        rsi_bucket_stats=rsi_bucket_stats,
        volume_bucket_stats=volume_bucket_stats,
        score_bucket_stats=score_bucket_stats,
        best_setups=best_setups,
        missing_followups=missing_followups,
        pending_stage_counts=pending_stage_counts,
        alert_metadata_table=alert_metadata_table,
        followup_metadata_table=followup_metadata_table,
        context_tables=context_tables,
        recommendations=recommendations,
        unavailable_fields=unavailable_fields,
        stage_definitions=stage_definitions,
        big_move_overview=big_move_overview,
        big_move_direction_stats=big_move_direction_stats,
        big_move_stage_stats=big_move_stage_stats,
        dordo_sent_alert_stats=dordo_sent_alert_stats,
        dordo_sent_followup_stats=dordo_sent_followup_stats,
        liquidity_rsi_combo_stats=liquidity_rsi_combo_stats,
        score_liquidity_combo_stats=score_liquidity_combo_stats,
        ultra_liquid_high_score_stats=ultra_liquid_high_score_stats,
        dordo_sent_outcome_stats=dordo_sent_outcome_stats,
        dordo_recent_window_stats=dordo_recent_window_stats,
        dordo_rsi_bucket_stats=dordo_rsi_bucket_stats,
        dordo_score_bucket_stats=dordo_score_bucket_stats,
        dordo_combo_stats=dordo_combo_stats,
        dordo_sent_alert_details=dordo_sent_alert_details,
    )
    report_md_path = OUTPUT_DIR / "report.md"
    report_html_path = OUTPUT_DIR / "report.html"
    report_md_path.write_text(markdown_report, encoding="utf-8")
    report_html_path.write_text(html_report, encoding="utf-8")

    if env_flag(TELEGRAM_REPORT_ENV):
        if target_user_id is None:
            raise RuntimeError(
                f"Telegram delivery target @{TARGET_DELIVERY_USERNAME} was not found in the database; report was not sent."
            )
        bot_token = resolve_premium_bot_token()
        if not bot_token:
            raise RuntimeError(
                "Premium bot token was not found in environment or .env; report was not sent."
            )
        log(f"Sending Telegram report to @{TARGET_DELIVERY_USERNAME} via premium bot")
        summary_text = build_telegram_summary_message(
            overall_stats=overall_stats,
            validation_checks=validation_checks,
            dordo_sent_outcome_stats=dordo_sent_outcome_stats,
            dordo_recent_window_stats=dordo_recent_window_stats,
            dordo_rsi_bucket_stats=dordo_rsi_bucket_stats,
            dordo_score_bucket_stats=dordo_score_bucket_stats,
        )
        send_telegram_report(
            bot_token=bot_token,
            chat_id=target_user_id,
            report_html_path=report_html_path,
            summary_text=summary_text,
        )
        log(f"Telegram report sent successfully to @{TARGET_DELIVERY_USERNAME}")

    log("RSI analytics completed successfully")
    print()
    print(f"Reports saved to: {OUTPUT_DIR}")
    print(f"Markdown report: {report_md_path}")
    print(f"HTML report: {report_html_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # pragma: no cover - CLI guard
        print()
        traceback.print_exc()
        print()
        print("RSI analytics failed.")
        raise SystemExit(1)
