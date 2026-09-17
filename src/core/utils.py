from __future__ import annotations

import asyncio
import html
import logging
import hashlib
import re
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta, timezone
from typing import TypeVar


T = TypeVar("T")
LOGGER = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_local_timestamp(dt: datetime, tzinfo) -> str:
    return dt.astimezone(tzinfo).strftime("%Y-%m-%d %H:%M:%S %Z")


def escape_html(value: str) -> str:
    return html.escape(value, quote=False)


def normalize_symbol(value: str | None) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(value)).upper()
    return cleaned or str(value).strip().upper()


def format_price(value: float) -> str:
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return f"{value:,.6f}".rstrip("0").rstrip(".")


def format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2f}%"


def format_rsi(value: float) -> str:
    return f"{value:.2f}"


def format_volume(value: float | None) -> str:
    if value is None:
        return "n/a"
    thresholds = (
        (1_000_000_000, "B"),
        (1_000_000, "M"),
        (1_000, "K"),
    )
    for threshold, suffix in thresholds:
        if abs(value) >= threshold:
            return f"{value / threshold:.2f}{suffix}"
    return f"{value:.2f}"


def calc_pct_change(base: float, current: float) -> float:
    if base == 0:
        return 0.0
    return ((current - base) / base) * 100


def interval_to_timedelta(interval: str) -> timedelta:
    if interval.endswith("m"):
        return timedelta(minutes=int(interval[:-1]))
    if interval.endswith("h"):
        return timedelta(hours=int(interval[:-1]))
    if interval.endswith("d"):
        return timedelta(days=int(interval[:-1]))
    raise ValueError(f"Unsupported interval: {interval}")


def seconds_until_next_interval(interval: str, offset_seconds: int) -> float:
    now = utc_now()
    delta = interval_to_timedelta(interval)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    elapsed = (now - epoch).total_seconds()
    interval_seconds = delta.total_seconds()
    next_boundary = ((elapsed // interval_seconds) + 1) * interval_seconds
    wait_seconds = (next_boundary - elapsed) + offset_seconds
    return max(wait_seconds, 1.0)


def parse_hhmm(value: str) -> time:
    hour_text, minute_text = value.split(":", maxsplit=1)
    return time(hour=int(hour_text), minute=int(minute_text))


def local_day_bounds(target_date: date, tzinfo) -> tuple[datetime, datetime]:
    start_local = datetime.combine(target_date, time.min, tzinfo=tzinfo)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def stable_ratio(seed: str) -> float:
    digest = hashlib.md5(seed.encode("utf-8"), usedforsecurity=False).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def should_include_soft_promo(seed: str, rate: float) -> bool:
    bounded_rate = max(0.0, min(rate, 1.0))
    return stable_ratio(seed) < bounded_rate


async def retry_async(
    func: Callable[[], Awaitable[T]],
    *,
    retries: int,
    base_delay: float = 1.0,
    operation_name: str = "operation",
) -> T:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return await func()
        except Exception as exc:  # pragma: no cover - network dependent
            last_error = exc
            if getattr(exc, "non_retryable", False):
                raise
            if attempt >= retries:
                break
            retry_after = getattr(exc, "retry_after", None)
            sleep_for = max(float(retry_after), base_delay * attempt) if retry_after is not None else base_delay * attempt
            error_text = str(exc).strip()
            if not error_text:
                error_text = f"{type(exc).__name__}: {exc!r}"
            LOGGER.warning(
                "%s failed on attempt %s/%s: %s. Retrying in %.1fs",
                operation_name,
                attempt,
                retries,
                error_text,
                sleep_for,
            )
            await asyncio.sleep(sleep_for)
    assert last_error is not None
    raise last_error
