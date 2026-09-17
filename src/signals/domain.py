from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.core.models import AlertSignal
from src.core.utils import normalize_symbol

DEFAULT_BENCHMARK_WIN_PERCENT = 7.0
DEFAULT_CONFIRM_PROGRESS = 0.3
DEFAULT_NEAR_TP_PROGRESS = 0.8

OPEN_SIGNAL_STATUSES = ("fresh", "active", "confirmed", "near_tp")
TERMINAL_SIGNAL_STATUSES = ("hit_tp", "invalidated", "expired")

ALLOWED_SIGNAL_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "fresh": ("active", "invalidated", "expired"),
    "active": ("confirmed", "near_tp", "invalidated", "expired"),
    "confirmed": ("near_tp", "hit_tp", "invalidated", "expired"),
    "near_tp": ("hit_tp", "invalidated", "expired"),
    "hit_tp": (),
    "invalidated": (),
    "expired": (),
}

SIGNAL_STATUS_BADGES: dict[str, tuple[str, str]] = {
    "fresh": ("Fresh", "green"),
    "active": ("Active", "blue"),
    "confirmed": ("Confirmed", "check"),
    "near_tp": ("Near TP", "target"),
    "hit_tp": ("Hit TP", "trophy"),
    "invalidated": ("Invalidated", "invalid"),
    "expired": ("Expired", "clock"),
}

STATUS_EMOJIS: dict[str, str] = {
    "fresh": "🟢",
    "active": "🔵",
    "confirmed": "✅",
    "near_tp": "🎯",
    "hit_tp": "🏆",
    "invalidated": "❌",
    "expired": "⏳",
}

_MAJOR_SYMBOLS = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"}
_MEME_SYMBOL_MARKERS = ("DOGE", "PEPE", "WIF", "BONK", "SHIB", "FLOKI")


@dataclass(frozen=True, slots=True)
class EvaluationSnapshot:
    status: str
    result_type: str
    target_price: float
    benchmark_win_percent: float
    favorable_move_percent: float
    adverse_move_percent: float
    mfe_percent: float
    mae_percent: float
    progress_to_target: float
    hit_target: bool
    hit_invalidation: bool
    ambiguous_resolution: bool = False


def normalize_signal_status(status: str | None) -> str:
    normalized = str(status or "fresh").strip().lower()
    return normalized if normalized in SIGNAL_STATUS_BADGES else "fresh"


def is_terminal_signal_status(status: str | None) -> bool:
    return normalize_signal_status(status) in TERMINAL_SIGNAL_STATUSES


def is_open_signal_status(status: str | None) -> bool:
    return normalize_signal_status(status) in OPEN_SIGNAL_STATUSES


def is_transition_allowed(old_status: str | None, new_status: str | None) -> bool:
    current = normalize_signal_status(old_status)
    candidate = normalize_signal_status(new_status)
    return candidate in ALLOWED_SIGNAL_TRANSITIONS.get(current, ())


def signal_status_badge(status: str | None) -> tuple[str, str]:
    normalized = normalize_signal_status(status)
    label, _ = SIGNAL_STATUS_BADGES[normalized]
    return STATUS_EMOJIS[normalized], label


def default_expiry_for_timeframe(
    timeframe: str | None,
    *,
    created_at: datetime,
) -> datetime:
    mapping = {
        "1m": timedelta(hours=4),
        "3m": timedelta(hours=6),
        "5m": timedelta(hours=12),
        "15m": timedelta(hours=24),
        "30m": timedelta(hours=36),
        "1h": timedelta(hours=72),
        "4h": timedelta(days=7),
    }
    return created_at + mapping.get(str(timeframe or "").strip().lower(), timedelta(hours=24))


def build_source_signal_key(
    *,
    strategy_code: str,
    symbol: str,
    timeframe: str,
    direction: str,
    candle_open_time: datetime,
) -> str:
    return "|".join(
        (
            str(strategy_code or "rsi").strip().lower() or "rsi",
            normalize_symbol(symbol),
            str(timeframe or "15m").strip().lower() or "15m",
            str(direction or "neutral").strip().lower() or "neutral",
            candle_open_time.isoformat(),
        )
    )


def resolve_trade_direction(
    direction: str | None,
    *,
    setup_direction: str | None = None,
) -> str:
    """Return the executable side of a signal without losing its RSI status.

    The base RSI scanner emits ``oversold`` / ``overbought`` as an indicator
    state.  Lifecycle and price levels, however, need an unambiguous trade
    side.  Keep that conversion in one place so the formatter, persistence and
    follow-up evaluator cannot disagree.
    """

    raw = str(setup_direction or direction or "").strip().lower()
    aliases = {
        "long": "long",
        "oversold": "long",
        "short": "short",
        "overbought": "short",
    }
    return aliases.get(raw, "neutral")


def resolve_strategy_code(signal: AlertSignal | dict[str, Any] | None) -> str:
    if signal is None:
        return "rsi"
    metadata = signal.metadata if isinstance(signal, AlertSignal) else signal
    raw = str((metadata or {}).get("strategy_key") or (metadata or {}).get("strategy_code") or "rsi").strip().lower()
    return raw or "rsi"


def resolve_asset_type(signal: AlertSignal | dict[str, Any] | None) -> str:
    if signal is None:
        return "crypto"
    metadata = signal.metadata if isinstance(signal, AlertSignal) else signal
    asset_class = str((metadata or {}).get("asset_class") or "").strip().lower()
    return "gold" if asset_class == "gold" else "crypto"


def resolve_asset_cluster_tag(symbol: str, *, is_gold: bool = False) -> str:
    normalized = normalize_symbol(symbol)
    if is_gold or normalized == "XAUUSD":
        return "gold"
    if normalized in _MAJOR_SYMBOLS:
        return "majors"
    if any(marker in normalized for marker in _MEME_SYMBOL_MARKERS):
        return "memes"
    return "altcoins"


def market_regime_from_metadata(metadata: dict[str, Any] | None, *, strategy_code: str | None = None) -> str:
    source = metadata or {}
    explicit = str(source.get("market_regime_tag") or "").strip()
    if explicit:
        return explicit
    strategy = str(strategy_code or source.get("strategy_key") or "rsi").strip().lower()
    if strategy in {"breakout", "trend_pullback", "vwap"}:
        return "Trend"
    if strategy in {"rsi_bollinger_mr", "rsi_bollinger_touch", "bollinger"}:
        return "Range"
    if strategy in {"false_breakout", "rsi_divergence"}:
        return "Reversal"
    if strategy == "gold":
        return "Gold"
    return "Mixed"
