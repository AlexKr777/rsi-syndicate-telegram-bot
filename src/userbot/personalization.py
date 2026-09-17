from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from src.core.utils import normalize_symbol

_NOISE_LEVELS = {"minimal", "balanced", "active"}
_SCORE_FILTERS = {"all", "strong", "high", "elite"}
_SESSION_FILTERS = {"all_day", "asia", "london", "new_york", "overlap"}
_DISPLAY_MODES = {"simple", "pro"}
_DELIVERY_MODES = {"instant", "digest", "quiet", "off", "mixed"}
_ASSET_SCOPE_TYPES = {"all", "watchlist", "favorites", "theme", "majors", "gold", "custom", "memes"}
_STYLE_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "speed_preference": ("fast", "balanced", "patient"),
    "noise_tolerance": ("low", "balanced", "high"),
    "market_preference": ("majors", "broad_crypto", "gold", "mixed"),
    "signal_style": ("breakout", "pullback", "mean_reversion", "mixed"),
    "confirmation_style": ("early", "balanced", "confirmed"),
    "interaction_mode": ("simple", "pro"),
    "trading_rhythm": ("asia", "london", "new_york", "all_day"),
    "delivery_preference": ("instant", "digest", "mixed"),
    "followup_preference": ("yes", "no", "important_only"),
    "risk_style": ("conservative", "balanced", "aggressive"),
}

_TREND_STRATEGIES = {"breakout", "trend_pullback", "vwap", "gold_breakout", "gold_pullback"}
_RANGE_STRATEGIES = {
    "false_breakout",
    "rsi_bollinger_mr",
    "rsi_bollinger_touch",
    "daily_rsi_80",
    "rsi_divergence",
    "ekek",
    "bollinger",
    "gold_liquidity",
    "rsi",
}
_BREAKOUT_STRATEGIES = {"breakout", "false_breakout", "gold_breakout"}
_PULLBACK_STRATEGIES = {"trend_pullback", "gold_pullback"}
_FAST_TIMEFRAMES = {"1m", "5m", "15m"}
_CLEANER_SCORE_FLOOR = 80
_ELITE_SCORE_FLOOR = 90
_HIGH_SCORE_FLOOR = 80
_STRONG_SCORE_FLOOR = 70

_KNOWN_MEME_TICKERS = {
    "DOGE",
    "SHIB",
    "PEPE",
    "WIF",
    "BONK",
    "FLOKI",
    "MEME",
    "TURBO",
    "BRETT",
    "PONKE",
}


@dataclass(frozen=True, slots=True)
class PersonalFilterDecision:
    allowed: bool
    reason: str
    session_label: str
    score_floor: int
    quick_filters: tuple[str, ...]
    watchlist_hit: bool
    favorite_hit: bool


@dataclass(frozen=True, slots=True)
class PersonalSummaryData:
    period_label: str
    setup_name: str
    matched: int
    delivered: int
    strong_delivered: int
    watchlist_matches: int
    filtered_out: int
    top_strategy: str | None
    most_active_asset: str | None
    gold_activity: str
    confirmed: int
    invalidated: int
    filtered_reasons: dict[str, int]
    top_recommendation: str
    quick_read: str
    change_note: str | None


def default_personalization() -> dict[str, Any]:
    return {
        # Presentation migration marker. Legacy accounts retain their current
        # navigation until they complete the V2 onboarding flow.
        "ux_v2_enabled": False,
        "noise_level": "balanced",
        "score_filter": "all",
        "session_filter": "all_day",
        "asset_scope_type": "all",
        "asset_scope_payload": None,
        "quick_filters": [],
        "signal_density": "balanced",
        "hidden": {
            "symbols": [],
            "strategies": [],
            "timeframes": [],
            "hide_weak_followups": False,
            "hide_medium_score": False,
            "hide_memes": False,
            "hide_seen_signals": False,
            "hide_gold_temporarily": False,
            "mute_repeats_hours": 0,
            "one_signal_per_asset_hours": 0,
        },
    }


def default_delivery_rules() -> dict[str, Any]:
    return {
        "strong_signals": "instant",
        "watchlist_matches": "instant",
        "gold_signals": "instant",
        "medium_signals": "digest",
        "followups": "important",
        "overnight": "quiet",
        "repeat_cooldown_hours": 8,
        "digest_frequency_hours": 1,
        "weekend_mode": "normal",
        "one_signal_per_asset_hours": 0,
    }


def default_style_preferences() -> dict[str, Any]:
    return {key: values[1] if len(values) > 1 else values[0] for key, values in _STYLE_DIMENSIONS.items()}


def normalize_personalization(payload: dict[str, Any] | None) -> dict[str, Any]:
    base = default_personalization()
    raw = dict(payload or {})
    noise_level = str(raw.get("noise_level") or base["noise_level"]).strip().lower()
    if noise_level not in _NOISE_LEVELS:
        noise_level = "balanced"
    score_filter = str(raw.get("score_filter") or base["score_filter"]).strip().lower()
    if score_filter not in _SCORE_FILTERS:
        score_filter = "all"
    session_filter = str(raw.get("session_filter") or base["session_filter"]).strip().lower()
    if session_filter not in _SESSION_FILTERS:
        session_filter = "all_day"
    signal_density = str(raw.get("signal_density") or base["signal_density"]).strip().lower()
    if signal_density not in {"lean", "balanced", "broad"}:
        signal_density = "balanced"
    asset_scope_type = normalize_asset_scope_type(raw.get("asset_scope_type"))
    asset_scope_payload = normalize_asset_scope_payload(asset_scope_type, raw.get("asset_scope_payload"))
    quick_filters = [
        str(item or "").strip().lower()
        for item in raw.get("quick_filters", ())
        if str(item or "").strip()
    ]
    quick_filters = list(dict.fromkeys(quick_filters))
    hidden_raw = raw.get("hidden") if isinstance(raw.get("hidden"), dict) else {}
    hidden = {
        "symbols": sorted({normalize_symbol(str(item)) for item in hidden_raw.get("symbols", ()) if str(item).strip()}),
        "strategies": sorted({str(item or "").strip().lower() for item in hidden_raw.get("strategies", ()) if str(item).strip()}),
        "timeframes": sorted({str(item or "").strip().lower() for item in hidden_raw.get("timeframes", ()) if str(item).strip()}),
        "hide_weak_followups": bool(hidden_raw.get("hide_weak_followups", False)),
        "hide_medium_score": bool(hidden_raw.get("hide_medium_score", False)),
        "hide_memes": bool(hidden_raw.get("hide_memes", False)),
        "hide_seen_signals": bool(hidden_raw.get("hide_seen_signals", False)),
        "hide_gold_temporarily": bool(hidden_raw.get("hide_gold_temporarily", False)),
        "mute_repeats_hours": _safe_hours(hidden_raw.get("mute_repeats_hours", 0)),
        "one_signal_per_asset_hours": _safe_hours(hidden_raw.get("one_signal_per_asset_hours", 0)),
    }
    return {
        "ux_v2_enabled": bool(raw.get("ux_v2_enabled", False)),
        "noise_level": noise_level,
        "score_filter": score_filter,
        "session_filter": session_filter,
        "asset_scope_type": asset_scope_type,
        "asset_scope_payload": asset_scope_payload,
        "quick_filters": quick_filters,
        "signal_density": signal_density,
        "hidden": hidden,
    }


def normalize_delivery_rules(payload: dict[str, Any] | None) -> dict[str, Any]:
    base = default_delivery_rules()
    raw = dict(payload or {})
    result = {
        "strong_signals": _normalize_delivery_choice(raw.get("strong_signals"), fallback=base["strong_signals"]),
        "watchlist_matches": _normalize_delivery_choice(raw.get("watchlist_matches"), fallback=base["watchlist_matches"]),
        "gold_signals": _normalize_delivery_choice(raw.get("gold_signals"), fallback=base["gold_signals"]),
        "medium_signals": _normalize_delivery_choice(raw.get("medium_signals"), fallback=base["medium_signals"]),
        "followups": str(raw.get("followups") or base["followups"]).strip().lower(),
        "overnight": "quiet" if str(raw.get("overnight") or base["overnight"]).strip().lower() == "quiet" else "normal",
        "repeat_cooldown_hours": _safe_hours(raw.get("repeat_cooldown_hours", base["repeat_cooldown_hours"])),
        "digest_frequency_hours": max(1, _safe_hours(raw.get("digest_frequency_hours", base["digest_frequency_hours"])) or 1),
        "weekend_mode": "quiet" if str(raw.get("weekend_mode") or base["weekend_mode"]).strip().lower() == "quiet" else "normal",
        "one_signal_per_asset_hours": _safe_hours(raw.get("one_signal_per_asset_hours", base["one_signal_per_asset_hours"])),
    }
    if result["followups"] not in {"all", "important", "off", "digest"}:
        result["followups"] = "important"
    return result


def normalize_style_preferences(payload: dict[str, Any] | None) -> dict[str, Any]:
    base = default_style_preferences()
    raw = dict(payload or {})
    normalized: dict[str, Any] = {}
    for key, values in _STYLE_DIMENSIONS.items():
        value = str(raw.get(key) or base[key]).strip().lower()
        normalized[key] = value if value in values else base[key]
    return normalized


def build_style_title_summary(preferences: dict[str, Any], *, language_code: str = "en") -> tuple[str, str]:
    prefs = normalize_style_preferences(preferences)
    if language_code == "ru":
        speed = {
            "fast": "быстрый",
            "balanced": "сбалансированный",
            "patient": "терпеливый",
        }[prefs["speed_preference"]]
        noise = {
            "low": "малошумный",
            "balanced": "сбалансированный",
            "high": "активный",
        }[prefs["noise_tolerance"]]
        title = f"{noise} {speed} трейдер"
        summary = (
            f"{_market_label(prefs['market_preference'], language_code='ru')} • "
            f"{_signal_style_label(prefs['signal_style'], language_code='ru')} • "
            f"{_delivery_label(prefs['delivery_preference'], language_code='ru')}"
        )
        return title.capitalize(), summary
    speed = {
        "fast": "Fast",
        "balanced": "Balanced",
        "patient": "Patient",
    }[prefs["speed_preference"]]
    noise = {
        "low": "Low-noise",
        "balanced": "Balanced",
        "high": "Active",
    }[prefs["noise_tolerance"]]
    title = f"{noise} {speed.lower()} trader"
    summary = (
        f"{_market_label(prefs['market_preference'])} • "
        f"{_signal_style_label(prefs['signal_style'])} • "
        f"{_delivery_label(prefs['delivery_preference'])}"
    )
    return title, summary


def apply_quick_filter_preset(payload: dict[str, Any] | None, preset: str) -> dict[str, Any]:
    personalization = normalize_personalization(payload)
    preset_key = str(preset or "").strip().lower()
    quick_filters = [item for item in personalization["quick_filters"] if item != preset_key]

    def _replace_group(group: Iterable[str], new_value: str | None = None) -> None:
        nonlocal quick_filters
        blocked = set(group)
        quick_filters = [item for item in quick_filters if item not in blocked]
        if new_value:
            quick_filters.append(new_value)

    if preset_key == "high_conviction":
        personalization["noise_level"] = "minimal"
        personalization["score_filter"] = "high"
    elif preset_key == "low_noise":
        personalization["noise_level"] = "minimal"
    elif preset_key == "trend_only":
        _replace_group({"trend_only", "range_only"}, "trend_only")
    elif preset_key == "range_only":
        _replace_group({"trend_only", "range_only"}, "range_only")
    elif preset_key == "breakout_only":
        _replace_group({"breakout_only", "pullback_only"}, "breakout_only")
    elif preset_key == "pullback_only":
        _replace_group({"breakout_only", "pullback_only"}, "pullback_only")
    elif preset_key == "gold_only":
        _replace_group({"gold_only"}, "gold_only")
    elif preset_key == "watchlist_only":
        _replace_group({"watchlist_only"}, "watchlist_only")
    elif preset_key == "fast_setups":
        _replace_group({"fast_setups", "cleaner_setups"}, "fast_setups")
    elif preset_key == "cleaner_setups":
        _replace_group({"fast_setups", "cleaner_setups"}, "cleaner_setups")
    elif preset_key == "aggressive":
        personalization["noise_level"] = "active"
        personalization["score_filter"] = "all"
        _replace_group({"conservative"}, None)
    elif preset_key == "conservative":
        personalization["noise_level"] = "minimal"
        personalization["score_filter"] = "strong"
        _replace_group({"aggressive"}, None)
    elif preset_key:
        quick_filters.append(preset_key)
    personalization["quick_filters"] = list(dict.fromkeys(quick_filters))
    return personalization


def clear_quick_filters(payload: dict[str, Any] | None) -> dict[str, Any]:
    personalization = normalize_personalization(payload)
    personalization["quick_filters"] = []
    return personalization


def session_label_for_datetime(dt: datetime, *, language_code: str = "en") -> str:
    hour = int(dt.hour)
    key = session_key_for_hour(hour)
    labels = {
        "asia": "Asia" if language_code == "en" else "Азия",
        "london": "London" if language_code == "en" else "Лондон",
        "new_york": "New York" if language_code == "en" else "Нью-Йорк",
        "overlap": "Overlap" if language_code == "en" else "Перекрытие",
        "all_day": "All Day" if language_code == "en" else "Весь день",
    }
    return labels[key]


def session_key_for_hour(hour: int) -> str:
    normalized = max(0, min(int(hour), 23))
    if 12 <= normalized < 16:
        return "overlap"
    if 0 <= normalized < 7:
        return "asia"
    if 7 <= normalized < 12:
        return "london"
    if 16 <= normalized < 21:
        return "new_york"
    return "all_day"


def score_floor_from_personalization(personalization: dict[str, Any], *, base_min_score: int) -> int:
    normalized = normalize_personalization(personalization)
    floor = int(base_min_score)
    noise_level = normalized["noise_level"]
    if noise_level == "minimal":
        floor = max(floor, 84)
    elif noise_level == "active":
        floor = max(min(floor - 6, 100), 0)
    score_filter = normalized["score_filter"]
    if score_filter == "strong":
        floor = max(floor, _STRONG_SCORE_FLOOR)
    elif score_filter == "high":
        floor = max(floor, _HIGH_SCORE_FLOOR)
    elif score_filter == "elite":
        floor = max(floor, _ELITE_SCORE_FLOOR)
    quick_filters = set(normalized["quick_filters"])
    if "high_conviction" in quick_filters:
        floor = max(floor, _HIGH_SCORE_FLOOR)
    if "cleaner_setups" in quick_filters:
        floor = max(floor, _CLEANER_SCORE_FLOOR)
    if "conservative" in quick_filters:
        floor = max(floor, 86)
    if "aggressive" in quick_filters:
        floor = max(min(floor - 4, 100), 0)
    return max(0, min(floor, 100))


def evaluate_personal_filters(
    *,
    symbol: str,
    timeframe: str,
    strategy_key: str,
    score: int,
    occurred_at: datetime,
    base_min_score: int,
    personalization: dict[str, Any] | None,
    watchlist_symbols: set[str],
    favorite_symbols: set[str],
    is_gold: bool = False,
    is_followup: bool = False,
    seen_symbols: set[str] | None = None,
) -> PersonalFilterDecision:
    normalized = normalize_personalization(personalization)
    hidden = normalized["hidden"]
    quick_filters = tuple(normalized["quick_filters"])
    normalized_symbol = normalize_symbol(symbol)
    normalized_timeframe = str(timeframe or "").strip().lower()
    normalized_strategy = str(strategy_key or "").strip().lower()
    watchlist_hit = normalized_symbol in watchlist_symbols
    favorite_hit = normalized_symbol in favorite_symbols
    session_key = session_key_for_hour(occurred_at.hour)
    session_label = session_label_for_datetime(occurred_at)
    if normalized_symbol in hidden["symbols"]:
        return PersonalFilterDecision(False, "hidden_symbol", session_label, 0, quick_filters, watchlist_hit, favorite_hit)
    if normalized_strategy in hidden["strategies"]:
        return PersonalFilterDecision(False, "hidden_strategy", session_label, 0, quick_filters, watchlist_hit, favorite_hit)
    if normalized_timeframe in hidden["timeframes"]:
        return PersonalFilterDecision(False, "hidden_timeframe", session_label, 0, quick_filters, watchlist_hit, favorite_hit)
    if hidden["hide_gold_temporarily"] and is_gold:
        return PersonalFilterDecision(False, "hidden_gold", session_label, 0, quick_filters, watchlist_hit, favorite_hit)
    if hidden["hide_memes"] and _is_meme_symbol(normalized_symbol):
        return PersonalFilterDecision(False, "hidden_memes", session_label, 0, quick_filters, watchlist_hit, favorite_hit)
    if normalized["session_filter"] != "all_day":
        allowed_sessions = {normalized["session_filter"]}
        if normalized["session_filter"] == "overlap":
            allowed_sessions = {"overlap"}
        if session_key not in allowed_sessions:
            return PersonalFilterDecision(False, "session_filter", session_label, 0, quick_filters, watchlist_hit, favorite_hit)
    if "gold_only" in quick_filters and not is_gold:
        return PersonalFilterDecision(False, "quick_filter_gold", session_label, 0, quick_filters, watchlist_hit, favorite_hit)
    if "watchlist_only" in quick_filters and not (watchlist_hit or favorite_hit):
        return PersonalFilterDecision(False, "quick_filter_watchlist", session_label, 0, quick_filters, watchlist_hit, favorite_hit)
    if "trend_only" in quick_filters and normalized_strategy not in _TREND_STRATEGIES:
        return PersonalFilterDecision(False, "quick_filter_trend", session_label, 0, quick_filters, watchlist_hit, favorite_hit)
    if "range_only" in quick_filters and normalized_strategy not in _RANGE_STRATEGIES:
        return PersonalFilterDecision(False, "quick_filter_range", session_label, 0, quick_filters, watchlist_hit, favorite_hit)
    if "breakout_only" in quick_filters and normalized_strategy not in _BREAKOUT_STRATEGIES:
        return PersonalFilterDecision(False, "quick_filter_breakout", session_label, 0, quick_filters, watchlist_hit, favorite_hit)
    if "pullback_only" in quick_filters and normalized_strategy not in _PULLBACK_STRATEGIES:
        return PersonalFilterDecision(False, "quick_filter_pullback", session_label, 0, quick_filters, watchlist_hit, favorite_hit)
    if "fast_setups" in quick_filters and normalized_timeframe not in _FAST_TIMEFRAMES:
        return PersonalFilterDecision(False, "quick_filter_fast", session_label, 0, quick_filters, watchlist_hit, favorite_hit)
    score_floor = score_floor_from_personalization(normalized, base_min_score=base_min_score)
    if hidden["hide_medium_score"] and score < 80:
        return PersonalFilterDecision(False, "hidden_medium_score", session_label, score_floor, quick_filters, watchlist_hit, favorite_hit)
    if "cleaner_setups" in quick_filters and score < _CLEANER_SCORE_FLOOR:
        return PersonalFilterDecision(False, "quick_filter_cleaner", session_label, score_floor, quick_filters, watchlist_hit, favorite_hit)
    if is_followup and hidden["hide_weak_followups"] and score < 82:
        return PersonalFilterDecision(False, "hidden_weak_followup", session_label, score_floor, quick_filters, watchlist_hit, favorite_hit)
    if hidden["hide_seen_signals"] and seen_symbols and normalized_symbol in seen_symbols:
        return PersonalFilterDecision(False, "hidden_seen", session_label, score_floor, quick_filters, watchlist_hit, favorite_hit)
    if score < score_floor:
        return PersonalFilterDecision(False, "score_filter", session_label, score_floor, quick_filters, watchlist_hit, favorite_hit)
    return PersonalFilterDecision(True, "ok", session_label, score_floor, quick_filters, watchlist_hit, favorite_hit)


def resolve_delivery_route(
    *,
    score: int,
    watchlist_hit: bool,
    favorite_hit: bool,
    is_gold: bool,
    is_followup: bool,
    in_quiet_hours: bool,
    snoozed: bool,
    repeat_cooldown_hit: bool,
    delivery_rules: dict[str, Any] | None,
    base_mode: str,
) -> str | None:
    rules = normalize_delivery_rules(delivery_rules)
    base = _normalize_delivery_choice(base_mode, fallback="instant")
    if snoozed:
        return "snooze"
    if repeat_cooldown_hit and rules["repeat_cooldown_hours"] > 0:
        return "repeat_cooldown"
    is_strong = score >= 88
    if is_followup:
        followups = rules["followups"]
        if followups == "off":
            return "followups_off"
        if followups == "digest":
            return "digest"
        if followups == "important" and not (is_strong or watchlist_hit or favorite_hit or is_gold):
            return "followups_important_only"
        if in_quiet_hours and rules["overnight"] == "quiet" and not (is_strong or watchlist_hit or favorite_hit):
            return "quiet_hours"
        return None
    if watchlist_hit or favorite_hit:
        route = rules["watchlist_matches"]
        if route == "instant":
            return None
        if route == "off":
            return "watchlist_off"
        return route
    if is_gold:
        route = rules["gold_signals"]
        if route == "instant" and not (in_quiet_hours and rules["overnight"] == "quiet" and not is_strong):
            return None
        if route == "off":
            return "gold_off"
        if in_quiet_hours and rules["overnight"] == "quiet":
            return "quiet_hours"
        return route
    if is_strong:
        route = rules["strong_signals"]
        if route == "instant" and not (in_quiet_hours and rules["overnight"] == "quiet" and not watchlist_hit):
            return None
        if route == "off":
            return "strong_off"
        if in_quiet_hours and rules["overnight"] == "quiet":
            return "quiet_hours"
        return route
    route = rules["medium_signals"]
    if in_quiet_hours and rules["overnight"] == "quiet":
        return "quiet_hours"
    if route == "off":
        return "medium_off"
    if route == "instant":
        return None
    if route in {"digest", "quiet"}:
        return route
    if base == "instant":
        return None
    return base


def summarize_setup_payload(payload: dict[str, Any], *, language_code: str = "en") -> str:
    shell = payload.get("shell") if isinstance(payload.get("shell"), dict) else payload
    personalization = normalize_personalization(shell.get("personalization") if isinstance(shell, dict) else {})
    enabled_strategy_keys = tuple(shell.get("enabled_strategy_keys") or ())
    strategy_label = " + ".join(_strategy_short_label(key) for key in enabled_strategy_keys[:2])
    if len(enabled_strategy_keys) > 2:
        strategy_label += " +"
    asset_scope_type = normalize_asset_scope_type(
        personalization.get("asset_scope_type") or shell.get("asset_scope_type")
    )
    asset_scope_payload = normalize_asset_scope_payload(
        asset_scope_type,
        personalization.get("asset_scope_payload") if "asset_scope_payload" in personalization else shell.get("asset_scope_payload"),
    )
    if asset_scope_type == "all" and "asset_scope_type" not in personalization and "asset_scope_type" not in shell:
        asset_scope_type, asset_scope_payload = infer_asset_scope_from_payload(payload)
    assets = asset_scope_summary(asset_scope_type, asset_scope_payload, language_code=language_code)
    selected_timeframes = [
        timeframe
        for timeframe in ("5m", "15m", "30m", "1h", "4h", "1d")
        if timeframe not in set(personalization["hidden"].get("timeframes", []))
    ]
    timeframe_label = " / ".join(selected_timeframes[:3]) if selected_timeframes else ("All TF" if language_code == "en" else "Все ТФ")
    delivery_label = delivery_summary_label(
        shell.get("delivery_profile"),
        shell.get("delivery_rules"),
        language_code=language_code,
    )
    return f"{assets} • {strategy_label or 'Mix'} • {timeframe_label} • {delivery_label}"


def normalize_asset_scope_type(value: Any) -> str:
    normalized = str(value or "all").strip().lower()
    aliases = {
        "all_enabled": "all",
        "all_coins": "all",
        "custom_symbols": "custom",
        "theme_set": "theme",
        "saved_set": "theme",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in _ASSET_SCOPE_TYPES else "all"


def normalize_asset_scope_payload(scope_type: str, payload: Any) -> dict[str, Any] | None:
    normalized_scope = normalize_asset_scope_type(scope_type)
    if normalized_scope == "custom":
        if isinstance(payload, dict):
            raw_symbols = payload.get("symbols", ())
        else:
            raw_symbols = payload or ()
        symbols = sorted({normalize_symbol(str(item)) for item in raw_symbols if str(item).strip()})
        return {"symbols": symbols}
    if normalized_scope == "theme":
        theme_name = ""
        theme_id = None
        theme_symbols: list[str] = []
        if isinstance(payload, dict):
            theme_name = str(payload.get("theme_name") or "").strip()
            raw_theme_id = payload.get("theme_id")
            try:
                theme_id = int(raw_theme_id) if raw_theme_id is not None else None
            except (TypeError, ValueError):
                theme_id = None
            theme_symbols = sorted({normalize_symbol(str(item)) for item in payload.get("symbols", ()) if str(item).strip()})
        elif payload is not None:
            theme_name = str(payload).strip()
        if not theme_name:
            return None
        result: dict[str, Any] = {"theme_name": theme_name}
        if theme_id is not None:
            result["theme_id"] = theme_id
        if theme_symbols:
            result["symbols"] = theme_symbols
        return result
    return None


def asset_scope_summary(scope_type: str, payload: dict[str, Any] | None, *, language_code: str = "en") -> str:
    is_ru = language_code == "ru"
    normalized_scope = normalize_asset_scope_type(scope_type)
    if normalized_scope == "all":
        return "Все монеты" if is_ru else "All Coins"
    if normalized_scope == "watchlist":
        return "Watchlist" if not is_ru else "Watchlist"
    if normalized_scope == "favorites":
        return "Избранное" if is_ru else "Favorites"
    if normalized_scope == "majors":
        return "Мейджоры" if is_ru else "Majors"
    if normalized_scope == "gold":
        return "Только золото" if is_ru else "Gold Only"
    if normalized_scope == "memes":
        return "Мемы" if is_ru else "Memes"
    if normalized_scope == "theme":
        theme_name = str((payload or {}).get("theme_name") or "").strip()
        if theme_name:
            return theme_name
        return "Тема / сет" if is_ru else "Theme / Set"
    symbols = [str(item) for item in (payload or {}).get("symbols", []) if str(item).strip()]
    if symbols:
        preview = " / ".join(symbols[:3])
        if len(symbols) > 3:
            preview += " +"
        return preview
    return "Свой выбор" if is_ru else "Custom Selection"


def infer_asset_scope_from_payload(payload: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    shell = payload.get("shell") if isinstance(payload.get("shell"), dict) else payload
    strategies = payload.get("strategies") if isinstance(payload.get("strategies"), dict) else {}
    first_strategy = next((item for item in strategies.values() if isinstance(item, dict)), {})
    active_theme = str(first_strategy.get("active_watchlist_theme") or shell.get("active_watchlist_theme") or "custom").strip().lower()
    active_custom_theme_name = str(first_strategy.get("active_custom_theme_name") or "").strip()
    watchlist_only = bool(first_strategy.get("watchlist_only", shell.get("watchlist_only", False)))
    favorite_symbols = sorted(
        {
            normalize_symbol(str(symbol))
            for symbol in first_strategy.get("favorite_symbols", ())
            if str(symbol).strip()
        }
    )
    if not watchlist_only:
        return "all", None
    if active_theme in {"majors", "gold", "memes"}:
        return active_theme, None
    if active_theme == "favorites":
        return "favorites", None
    if active_theme == "watchlist":
        return "watchlist", None
    if active_custom_theme_name:
        return "theme", {"theme_name": active_custom_theme_name}
    if favorite_symbols:
        return "custom", {"symbols": favorite_symbols}
    return "watchlist", None


def delivery_summary_label(profile: Any, rules_payload: Any, *, language_code: str = "en") -> str:
    is_ru = language_code == "ru"
    profile_key = str(profile or "").strip().lower()
    if profile_key == "focused_instant":
        return "Мгновенно" if is_ru else "Instant"
    if profile_key == "watchlist_priority":
        return "Watchlist first" if not is_ru else "Сначала watchlist"
    if profile_key == "quiet_digest":
        return "Тихая сводка" if is_ru else "Quiet Digest"
    if profile_key == "balanced":
        return "Смешанно" if is_ru else "Mixed"
    rules = normalize_delivery_rules(rules_payload if isinstance(rules_payload, dict) else None)
    if rules["strong_signals"] == "instant" and rules["medium_signals"] == "instant":
        return "Мгновенно" if is_ru else "Instant"
    if rules["strong_signals"] in {"digest", "quiet"} and rules["medium_signals"] in {"digest", "quiet"}:
        return "Сводка" if is_ru else "Digest"
    if rules["overnight"] == "quiet":
        return "Смешанно" if is_ru else "Mixed"
    return "Смешанно" if is_ru else "Mixed"


def humanize_filter_reason(reason: str, *, language_code: str = "en") -> str:
    normalized = str(reason or "other").strip().lower()
    labels = {
        "hidden_symbol": ("Hidden asset", "Скрытый актив"),
        "hidden_strategy": ("Hidden strategy", "Скрытая стратегия"),
        "hidden_timeframe": ("Hidden timeframe", "Скрытый таймфрейм"),
        "hidden_gold": ("Gold hidden", "Золото скрыто"),
        "hidden_memes": ("Meme filter", "Фильтр мемов"),
        "session_filter": ("Session filter", "Фильтр сессии"),
        "quick_filter_gold": ("Gold only", "Только золото"),
        "quick_filter_watchlist": ("Watchlist only", "Только watchlist"),
        "quick_filter_trend": ("Trend only", "Только тренд"),
        "quick_filter_range": ("Range only", "Только диапазон"),
        "quick_filter_breakout": ("Breakout only", "Только пробои"),
        "quick_filter_pullback": ("Pullback only", "Только откаты"),
        "quick_filter_fast": ("Fast setups", "Быстрые сетапы"),
        "quick_filter_cleaner": ("Cleaner setups", "Более чистые сетапы"),
        "hidden_medium_score": ("Medium score hidden", "Средний score скрыт"),
        "hidden_weak_followup": ("Weak follow-ups hidden", "Слабые follow-up скрыты"),
        "hidden_seen": ("Seen already", "Уже просмотрено"),
        "score_filter": ("Score floor", "Порог score"),
        "repeat_cooldown": ("Repeat cooldown", "Кулдаун повторов"),
        "followups_off": ("Follow-ups off", "Follow-up выключены"),
        "followups_important_only": ("Important follow-ups only", "Только важные follow-up"),
        "quiet_hours": ("Quiet hours", "Тихие часы"),
        "watchlist_off": ("Watchlist delivery off", "Доставка watchlist выключена"),
        "gold_off": ("Gold delivery off", "Доставка золота выключена"),
        "strong_off": ("Strong delivery off", "Сильные сигналы выключены"),
        "medium_off": ("Medium delivery off", "Средние сигналы выключены"),
    }
    label = labels.get(normalized, ("Other", "Другое"))
    return label[1] if language_code == "ru" else label[0]


def asset_scope_summary(scope_type: str, payload: dict[str, Any] | None, *, language_code: str = "en") -> str:
    is_ru = language_code == "ru"
    normalized_scope = normalize_asset_scope_type(scope_type)
    if normalized_scope == "all":
        return "Все монеты" if is_ru else "All Coins"
    if normalized_scope == "watchlist":
        return "Вотчлист" if is_ru else "Watchlist"
    if normalized_scope == "favorites":
        return "Избранное" if is_ru else "Favorites"
    if normalized_scope == "majors":
        return "Топ-монеты" if is_ru else "Majors"
    if normalized_scope == "gold":
        return "Только золото" if is_ru else "Gold Only"
    if normalized_scope == "memes":
        return "Мем-монеты" if is_ru else "Memes"
    if normalized_scope == "theme":
        theme_name = str((payload or {}).get("theme_name") or "").strip()
        if theme_name:
            return theme_name
        return "Тема / набор" if is_ru else "Theme / Set"
    symbols = [str(item) for item in (payload or {}).get("symbols", []) if str(item).strip()]
    if symbols:
        preview = " / ".join(symbols[:3])
        if len(symbols) > 3:
            preview += " +"
        return preview
    return "Свой выбор" if is_ru else "Custom Selection"


def delivery_summary_label(profile: Any, rules_payload: Any, *, language_code: str = "en") -> str:
    is_ru = language_code == "ru"
    profile_key = str(profile or "").strip().lower()
    if profile_key == "focused_instant":
        return "Сразу" if is_ru else "Instant"
    if profile_key == "watchlist_priority":
        return "Сначала вотчлист" if is_ru else "Watchlist first"
    if profile_key == "quiet_digest":
        return "Тихая сводка" if is_ru else "Quiet Digest"
    if profile_key == "balanced":
        return "Смешанно" if is_ru else "Mixed"
    rules = normalize_delivery_rules(rules_payload if isinstance(rules_payload, dict) else None)
    if rules["strong_signals"] == "instant" and rules["medium_signals"] == "instant":
        return "Сразу" if is_ru else "Instant"
    if rules["strong_signals"] in {"digest", "quiet"} and rules["medium_signals"] in {"digest", "quiet"}:
        return "Сводка" if is_ru else "Digest"
    return "Смешанно" if is_ru else "Mixed"


def humanize_filter_reason(reason: str, *, language_code: str = "en") -> str:
    normalized = str(reason or "other").strip().lower()
    labels = {
        "hidden_symbol": ("Hidden asset", "Скрытый актив"),
        "hidden_strategy": ("Hidden strategy", "Скрытая стратегия"),
        "hidden_timeframe": ("Hidden timeframe", "Скрытый таймфрейм"),
        "hidden_gold": ("Gold hidden", "Золото скрыто"),
        "hidden_memes": ("Meme filter", "Фильтр мемов"),
        "session_filter": ("Session filter", "Фильтр сессии"),
        "quick_filter_gold": ("Gold only", "Только золото"),
        "quick_filter_watchlist": ("Watchlist only", "Только вотчлист"),
        "quick_filter_trend": ("Trend only", "Только тренд"),
        "quick_filter_range": ("Range only", "Только диапазон"),
        "quick_filter_breakout": ("Breakout only", "Только пробои"),
        "quick_filter_pullback": ("Pullback only", "Только откаты"),
        "quick_filter_fast": ("Fast setups", "Быстрые идеи"),
        "quick_filter_cleaner": ("Cleaner setups", "Чище поток"),
        "hidden_medium_score": ("Medium score hidden", "Средние сигналы скрыты"),
        "hidden_weak_followup": ("Weak follow-ups hidden", "Слабые follow-up скрыты"),
        "hidden_seen": ("Seen already", "Уже просмотрено"),
        "score_filter": ("Score floor", "Порог качества"),
        "repeat_cooldown": ("Repeat cooldown", "Кулдаун повторов"),
        "followups_off": ("Follow-ups off", "Follow-up выключены"),
        "followups_important_only": ("Important follow-ups only", "Только важные follow-up"),
        "quiet_hours": ("Quiet hours", "Тихие часы"),
        "watchlist_off": ("Watchlist delivery off", "Уведомления вотчлиста выключены"),
        "gold_off": ("Gold delivery off", "Уведомления по золоту выключены"),
        "strong_off": ("Strong delivery off", "Сильные сигналы выключены"),
        "medium_off": ("Medium delivery off", "Средние сигналы выключены"),
    }
    label = labels.get(normalized, ("Other", "Другое"))
    return label[1] if language_code == "ru" else label[0]


def _normalize_delivery_choice(value: Any, *, fallback: str) -> str:
    normalized = str(value or fallback).strip().lower()
    return normalized if normalized in _DELIVERY_MODES else fallback


def _safe_hours(value: Any) -> int:
    try:
        return max(0, min(int(value), 168))
    except (TypeError, ValueError):
        return 0


def _is_meme_symbol(symbol: str) -> bool:
    base = normalize_symbol(symbol).replace("USDT", "").replace("USD", "")
    return base in _KNOWN_MEME_TICKERS


def _strategy_short_label(strategy_key: str) -> str:
    mapping = {
        "breakout": "Breakout",
        "trend_pullback": "Pullback",
        "rsi_bollinger_mr": "MR",
        "rsi_bollinger_touch": "BB Touch",
        "daily_rsi_80": "1D RSI 80+",
        "vwap": "VWAP",
        "false_breakout": "False BO",
        "rsi": "RSI",
        "rsi_divergence": "RSI Div",
        "ekek": "EKEK",
        "bollinger": "Bollinger",
        "gold": "Gold",
        "gold_breakout": "Gold BO",
        "gold_pullback": "Gold PB",
        "gold_liquidity": "Gold Liq",
    }
    return mapping.get(str(strategy_key or "").strip().lower(), str(strategy_key or "").strip())


def _market_label(value: str, *, language_code: str = "en") -> str:
    mapping = {
        "majors": ("Majors", "Мейджоры"),
        "broad_crypto": ("Broad Crypto", "Широкий крипторынок"),
        "gold": ("Gold", "Золото"),
        "mixed": ("Mixed", "Смешанный"),
    }
    label = mapping.get(value, mapping["mixed"])
    return label[1] if language_code == "ru" else label[0]


def _signal_style_label(value: str, *, language_code: str = "en") -> str:
    mapping = {
        "breakout": ("Breakout", "Пробои"),
        "pullback": ("Pullback", "Откаты"),
        "mean_reversion": ("Mean Reversion", "Возврат к средней"),
        "mixed": ("Mixed", "Смешанный"),
    }
    label = mapping.get(value, mapping["mixed"])
    return label[1] if language_code == "ru" else label[0]


def _delivery_label(value: str, *, language_code: str = "en") -> str:
    mapping = {
        "instant": ("Instant", "Моментально"),
        "digest": ("Digest", "Дайджест"),
        "mixed": ("Mixed Delivery", "Смешанная доставка"),
    }
    label = mapping.get(value, mapping["mixed"])
    return label[1] if language_code == "ru" else label[0]
