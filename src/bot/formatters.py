from __future__ import annotations

import re

from src.core.followup_logic import evaluate_thesis_result
from src.core.models import AlertSignal, FollowUpResult, GeneratedPost, TwitterDraft
from src.core.utils import (
    escape_html,
    format_percent,
    format_price,
    format_rsi,
    format_volume,
    normalize_symbol,
    to_local_timestamp,
)
from src.localization import is_russian, normalize_language
from src.signals import signal_status_badge
from src.signals.domain import resolve_trade_direction
from src.userbot.premium_text import premium_text


def _format_elapsed(seconds: float | int | None) -> str:
    if seconds is None:
        return "n/a"
    total_seconds = max(int(round(float(seconds))), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours}h {minutes:02d}m"


def _alert_context(
    direction: str,
    timeframe: str,
    *,
    language_code: str = "en",
    oversold_threshold: float | None = None,
    overbought_threshold: float | None = None,
) -> str:
    language = normalize_language(language_code)
    oversold_value = format_rsi(float(oversold_threshold if oversold_threshold is not None else 30.0))
    overbought_value = format_rsi(float(overbought_threshold if overbought_threshold is not None else 70.0))
    if direction == "long":
        if is_russian(language):
            return f"Цена закрылась в пользу лонгового сценария на {timeframe}. Это рабочий бычий триггер, но ему еще нужно развитие."
        return f"Price closed in favor of a long setup on {timeframe}. That is a workable bullish trigger, but it still needs follow-through."
    if direction == "short":
        if is_russian(language):
            return f"Цена закрылась в пользу шортового сценария на {timeframe}. Это рабочий медвежий триггер, но ему еще нужно развитие."
        return f"Price closed in favor of a short setup on {timeframe}. That is a workable bearish trigger, but it still needs follow-through."
    if direction == "oversold":
        if is_russian(language):
            return f"RSI ниже {oversold_value} на {timeframe}. Это может указывать на локальное истощение снижения, но ещё не подтверждает разворот."
        return f"RSI is below {oversold_value} on {timeframe}. That can point to downside exhaustion, not a bounce confirmation on its own."
    if direction == "neutral":
        if is_russian(language):
            return f"RSI вернулся внутрь среднего диапазона на {timeframe}. Это скорее watchlist-контекст, чем чистый экстремум."
        return f"RSI is back inside the middle range on {timeframe}. This is watchlist context rather than a clean extreme."
    if is_russian(language):
        return f"RSI выше {overbought_value} на {timeframe}. Это может указывать на локальное истощение роста, но ещё не подтверждает разворот."
    return f"RSI is above {overbought_value} on {timeframe}. That can point to upside exhaustion, not a reversal confirmation on its own."


def _trade_bias(direction: str, *, language_code: str = "en") -> tuple[str, str]:
    language = normalize_language(language_code)
    if direction == "long":
        return ("LONG", "бычий сценарий / лонговый приоритет") if is_russian(language) else ("LONG", "bullish setup / long-side thesis")
    if direction == "short":
        return ("SHORT", "медвежий сценарий / шортовый приоритет") if is_russian(language) else ("SHORT", "bearish setup / short-side thesis")
    if direction == "oversold":
        return ("LONG", "идея на отскок вверх") if is_russian(language) else ("LONG", "bounce / upside reaction thesis")
    if direction == "overbought":
        return ("SHORT", "идея на охлаждение вниз") if is_russian(language) else ("SHORT", "fade / downside reaction thesis")
    return ("WATCHLIST", "пока нет явного преимущества ни в лонг, ни в шорт") if is_russian(language) else ("WATCHLIST", "no clear long/short edge yet")


def _setup_direction(signal: AlertSignal) -> str:
    raw_direction = str(signal.metadata.get("setup_direction") or signal.direction or "").strip().lower()
    return resolve_trade_direction(signal.direction, setup_direction=raw_direction)


def _trade_direction_label(direction: str, *, language_code: str = "en") -> str:
    language = normalize_language(language_code)
    if direction == "long":
        return "Лонг" if is_russian(language) else "Long"
    if direction == "short":
        return "Шорт" if is_russian(language) else "Short"
    if direction == "oversold":
        return "Лонг (перепроданность)" if is_russian(language) else "Long (oversold)"
    if direction == "overbought":
        return "Шорт (перекупленность)" if is_russian(language) else "Short (overbought)"
    return "Наблюдение" if is_russian(language) else "Watchlist"


def _status_chip(kind: str, *, language_code: str = "en") -> str:
    language = normalize_language(language_code)
    mapping = {
        "fresh": ("Fresh", "Свежий"),
        "maturing": ("Maturing", "В развитии"),
        "followup": ("Follow-up", "Фоллоу-ап"),
        "expired": ("Expired", "Истёк"),
    }
    english, russian = mapping.get(kind, mapping["fresh"])
    return russian if is_russian(language) else english


def _direction_label(direction: str, *, language_code: str = "en") -> str:
    language = normalize_language(language_code)
    if direction == "long":
        return "Лонг" if is_russian(language) else "Long"
    if direction == "short":
        return "Шорт" if is_russian(language) else "Short"
    if direction == "oversold":
        return "Перепроданность" if is_russian(language) else "Oversold"
    if direction == "overbought":
        return "Перекупленность" if is_russian(language) else "Overbought"
    return "Нейтрально" if is_russian(language) else "Neutral"


def _strategy_label(strategy_key: str, *, language_code: str = "en") -> str:
    language = normalize_language(language_code)
    labels = {
        "breakout": ("Breakout", "Пробой уровня"),
        "trend_pullback": ("Trend Pullback", "Откат по тренду"),
        "rsi_bollinger_mr": ("RSI + Bollinger MR", "RSI + Bollinger MR"),
        "rsi_bollinger_touch": ("RSI + Bollinger Touch", "RSI + Bollinger Touch"),
        "daily_rsi_80": ("Daily RSI 80+", "Daily RSI 80+"),
        "vwap": ("VWAP", "VWAP"),
        "false_breakout": ("False Breakout", "Ложный пробой"),
        "rsi": ("RSI", "RSI"),
        "rsi_divergence": ("RSI Divergence", "RSI Divergence"),
        "okak": ("OKAK", "OKAK"),
        "ekek": ("EKEK", "EKEK"),
        "bollinger": ("Bollinger", "Боллинджер"),
        "gold": ("Gold / XAUUSD", "Золото / XAUUSD"),
        "gold_breakout": ("Gold Breakout", "Gold Breakout"),
        "gold_pullback": ("Gold Pullback", "Gold Pullback"),
        "gold_liquidity": ("Gold Liquidity", "Gold Liquidity"),
    }
    english, russian = labels.get(strategy_key, labels["rsi"])
    return russian if is_russian(language) else english


def _strategy_line(strategy_key: str | None, *, language_code: str = "en") -> str:
    language = normalize_language(language_code)
    normalized = str(strategy_key or "").strip().lower() or "rsi"
    label = "Стратегия" if is_russian(language) else "Strategy"
    return f"{label}: <b>{escape_html(_strategy_label(normalized, language_code=language))}</b>"


def _followup_state_label(state: str | None, *, language_code: str = "en") -> str:
    language = normalize_language(language_code)
    normalized = str(state or "").strip().lower() or "neutral"
    mapping = {
        "favorable": ("Favorable", "Благоприятно"),
        "adverse": ("Against thesis", "Против сценария"),
        "neutral": ("Mixed", "Нейтрально"),
    }
    english, russian = mapping.get(normalized, mapping["neutral"])
    return russian if is_russian(language) else english


def _followup_outcome(
    status: str | None,
    thesis_state: str,
    *,
    language_code: str = "en",
) -> tuple[str, str]:
    language = normalize_language(language_code)
    normalized = str(status or "").strip().lower()
    outcomes = {
        "hit_tp": ("Target reached", "Цель достигнута", "Target reached", "Цель достигнута"),
        "near_tp": ("Near target", "Рядом с целью", "Moved close to the target", "Цена подошла близко к цели"),
        "invalidated": ("Invalidated", "Сломан", "Setup invalidated", "Сетап сломан"),
        "expired": (
            "Expired",
            "Истёк",
            "Expired without clear continuation",
            "Истёк без ясного продолжения",
        ),
        "fresh": ("Still active", "Активен", "Still developing", "Сетап ещё развивается"),
        "active": ("Still active", "Активен", "Still developing", "Сетап ещё развивается"),
        "confirmed": ("Still active", "Активен", "Still developing", "Сетап ещё развивается"),
    }
    if normalized in outcomes:
        english_label, russian_label, english_note, russian_note = outcomes[normalized]
    elif thesis_state == "favorable":
        english_label, russian_label = "Developing favorably", "Развивается благоприятно"
        english_note, russian_note = "Moved in the direction of the signal", "Движение идёт по сценарию сигнала"
    elif thesis_state == "adverse":
        english_label, russian_label = "Moving against thesis", "Движение против сценария"
        english_note, russian_note = "Moved against the original signal direction", "Движение идёт против исходного сценария"
    else:
        english_label, russian_label = "Still active", "Активен"
        english_note, russian_note = "Still developing without a clear outcome", "Пока развивается без ясного результата"
    if is_russian(language):
        return russian_label, russian_note
    return english_label, english_note


def _status_badge_label(status: str | None, *, language_code: str = "en") -> tuple[str, str]:
    badge_emoji, badge_label = signal_status_badge(status)
    if not is_russian(language_code):
        return badge_emoji, badge_label
    mapping = {
        "Fresh": "Свежий",
        "Active": "Активный",
        "Confirmed": "Подтверждён",
        "Near TP": "Почти TP",
        "Hit TP": "Достиг TP",
        "Invalidated": "Сломан",
        "Expired": "Истёк",
    }
    return badge_emoji, mapping.get(badge_label, badge_label)


def _value_or_na(
    value: object,
    *,
    formatter,
    language_code: str = "en",
) -> str:
    if isinstance(value, (int, float)):
        return formatter(float(value))
    return "н/д" if is_russian(language_code) else "n/a"


def _historical_resistance_quality_label(quality: str | None, *, language_code: str = "en") -> str:
    language = normalize_language(language_code)
    normalized = str(quality or "").strip().lower() or "weak"
    mapping = {
        "strong": ("Strong", "Сильная"),
        "moderate": ("Moderate", "Средняя"),
        "weak": ("Weak", "Слабая"),
    }
    english, russian = mapping.get(normalized, mapping["weak"])
    return russian if is_russian(language) else english


def _format_zone_level(low: object, high: object) -> str | None:
    if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
        return None
    low_value = float(low)
    high_value = float(high)
    if low_value <= 0.0 or high_value <= 0.0:
        return None
    center = (low_value + high_value) / 2.0
    spread_pct = abs(high_value - low_value) / center if center > 0.0 else 0.0
    if spread_pct <= 0.0025:
        return format_price(center)
    return f"{format_price(low_value)} - {format_price(high_value)}"


def _historical_resistance_display(
    metadata: dict[str, object],
    *,
    language_code: str = "en",
) -> tuple[str | None, list[str]]:
    language = normalize_language(language_code)
    variant = str(metadata.get("historical_resistance_variant") or "").strip().lower()
    if variant not in {"detailed", "focus"}:
        return None, []

    available = bool(metadata.get("historical_resistance_available"))
    zone_price = metadata.get("historical_resistance_zone_price")
    zone_text = _format_zone_level(
        metadata.get("historical_resistance_zone_low"),
        metadata.get("historical_resistance_zone_high"),
    )
    highest_peak_price = metadata.get("historical_resistance_highest_peak_price")
    highest_peak_timeframe = str(metadata.get("historical_resistance_highest_peak_timeframe") or "").strip()
    highest_peak_distance_pct = metadata.get("historical_resistance_highest_peak_distance_pct")
    if variant == "focus":
        if available and isinstance(zone_price, (int, float)):
            prefix = "🎯 Стоит смотреть заход у" if is_russian(language) else "🎯 Watch entry near"
            return f"{prefix}: <b>{format_price(float(zone_price))}</b>", []
        fallback = (
            "⚪ Сильная зона 1h/4h рядом не найдена"
            if is_russian(language)
            else "⚪ No strong 1h/4h resistance zone nearby"
        )
        return fallback, []

    history_lines: list[str] = []
    highest_peak_parts: list[str] = []
    if isinstance(highest_peak_price, (int, float)):
        highest_peak_parts.append(f"<b>{format_price(float(highest_peak_price))}</b>")
        if highest_peak_timeframe:
            highest_peak_parts.append(f"<b>{escape_html(highest_peak_timeframe)}</b>")
        if isinstance(highest_peak_distance_pct, (int, float)):
            highest_peak_parts.append(f"<b>{format_percent(float(highest_peak_distance_pct))}</b>")
    highest_peak_line = (
        (
            f"{'🗻 Самый высокий импульсный пик' if is_russian(language) else '🗻 Highest impulse peak'}: "
            + " • ".join(highest_peak_parts)
        )
        if highest_peak_parts
        else None
    )
    if not available:
        history_lines.append(
            "⚪ Сильная зона сопротивления на 1h/4h рядом не найдена."
            if is_russian(language)
            else "⚪ No strong 1h/4h resistance zone is sitting close to price."
        )
        if highest_peak_line:
            history_lines.append(highest_peak_line)
        return None, history_lines

    timeframes = metadata.get("historical_resistance_timeframes")
    timeframe_values = [str(item).strip() for item in timeframes] if isinstance(timeframes, list) else []
    timeframe_text = " / ".join(item for item in timeframe_values if item) or "1h / 4h"
    distance_pct = metadata.get("historical_resistance_distance_pct")
    touch_count = metadata.get("historical_resistance_touch_count")
    avg_rejection_pct = metadata.get("historical_resistance_avg_rejection_pct")
    quality = _historical_resistance_quality_label(
        str(metadata.get("historical_resistance_quality") or ""),
        language_code=language,
    )
    if zone_text:
        history_lines.append(
            f"{'🎯 Историческая зона сопротивления' if is_russian(language) else '🎯 Historical resistance'}: <b>{zone_text}</b>"
        )
    if isinstance(distance_pct, (int, float)):
        history_lines.append(
            f"{'📍 Дистанция до зоны' if is_russian(language) else '📍 Distance to zone'}: <b>{format_percent(float(distance_pct))}</b>"
        )
    if highest_peak_line:
        history_lines.append(highest_peak_line)
    history_lines.append(
        f"{'Подтверждение' if is_russian(language) else 'Confirmed on'}: <b>{escape_html(timeframe_text)}</b>"
    )
    if isinstance(touch_count, (int, float)):
        history_lines.append(
            f"{'Подтвержденных отбоев' if is_russian(language) else 'Confirmed rejections'}: <b>{int(touch_count)}</b>"
        )
    if isinstance(avg_rejection_pct, (int, float)):
        history_lines.append(
            f"{'Средний отбой' if is_russian(language) else 'Average rejection'}: <b>{format_percent(-abs(float(avg_rejection_pct)))}</b>"
        )
    history_lines.append(
        f"{'Сила зоны' if is_russian(language) else 'Zone quality'}: <b>{escape_html(quality)}</b>"
    )
    return None, history_lines


def format_alert_message(
    signal: AlertSignal,
    timezone_obj,
    futures_base_url: str,
    *,
    preview: bool = False,
    language_code: str = "en",
    footer_note: str | None = None,
) -> str:
    del futures_base_url
    language = normalize_language(language_code)
    display_symbol = normalize_symbol(signal.symbol)
    strategy_key = str(signal.metadata.get("strategy_key") or "rsi").strip().lower() or "rsi"
    wave_prefix = "🌊 " if strategy_key == "ekek" else ""
    lifecycle_status = str(
        signal.metadata.get("signal_status")
        or ("fresh" if not signal.metadata.get("latest_followup_stage") else "active")
    ).strip().lower()
    status_badge_emoji, status_badge_label = _status_badge_label(lifecycle_status, language_code=language)
    status = _direction_label(signal.direction, language_code=language)
    setup_direction = _setup_direction(signal)
    setup_label = _trade_direction_label(setup_direction, language_code=language)
    _, bias_note = _trade_bias(setup_direction, language_code=language)
    volume_value = signal.quote_volume if signal.quote_volume is not None else signal.day_volume
    oversold_threshold = signal.metadata.get("rsi_oversold_threshold")
    overbought_threshold = signal.metadata.get("rsi_overbought_threshold")
    context_text = (
        str(signal.metadata.get("context_text") or "").strip()
        or signal.explanation.strip()
        or _alert_context(
            signal.direction,
            signal.timeframe,
            language_code=language,
            oversold_threshold=float(oversold_threshold) if isinstance(oversold_threshold, (int, float)) else None,
            overbought_threshold=float(overbought_threshold) if isinstance(overbought_threshold, (int, float)) else None,
        )
    )
    live_price = signal.metadata.get("live_price")
    live_rsi = signal.metadata.get("live_rsi")
    closed_rsi = signal.metadata.get("closed_rsi", signal.rsi)
    alert_rsi_value = (
        float(signal.metadata["alert_rsi"])
        if isinstance(signal.metadata.get("alert_rsi"), (int, float))
        else float(closed_rsi)
    )
    alert_score_value = (
        int(signal.metadata["alert_score"])
        if isinstance(signal.metadata.get("alert_score"), (int, float))
        else int(signal.score)
    )
    headline_price = float(live_price) if isinstance(live_price, (int, float)) else float(signal.price)
    headline_price_label = (
        "Сейчас" if is_russian(language) and isinstance(live_price, (int, float))
        else "Now" if isinstance(live_price, (int, float))
        else "Цена" if is_russian(language)
        else "Price"
    )
    secondary_parts = [
        f"{'Направление' if is_russian(language) else 'Trade direction'}: <b>{escape_html(setup_label)}</b>",
    ]
    if signal.direction != setup_direction:
        secondary_parts.append(
            f"{'Статус RSI' if is_russian(language) else 'RSI status'}: <b>{escape_html(status)}</b>"
        )
    if signal.day_change_pct is not None:
        secondary_parts.append(f"24h {format_percent(signal.day_change_pct)}")
    if volume_value is not None:
        secondary_parts.append(format_volume(volume_value))
    live_parts: list[str] = []
    if isinstance(live_rsi, (int, float)):
        live_parts.append(f"RSI live: <b>{format_rsi(float(live_rsi))}</b>")
    rsi_window_line = ""
    if isinstance(oversold_threshold, (int, float)) and isinstance(overbought_threshold, (int, float)):
        rsi_window_line = (
            f"{'Окно RSI' if is_russian(language) else 'RSI window'}: "
            f"<b>{format_rsi(float(oversold_threshold))} / {format_rsi(float(overbought_threshold))}</b>\n"
        )
    invalidation_price = signal.metadata.get("invalidation_price")
    tp_price_primary = signal.metadata.get("tp_price_primary")
    benchmark_win_percent = signal.metadata.get("benchmark_win_percent")
    entry_zone_low = signal.metadata.get("entry_zone_low")
    entry_zone_high = signal.metadata.get("entry_zone_high")
    market_regime_tag = str(signal.metadata.get("market_regime_tag") or "").strip()
    why_received_text = str(signal.metadata.get("why_received_text") or "").strip()
    display_mode = str(signal.metadata.get("display_mode") or "pro").strip().lower() or "pro"
    entry_label = "Вход" if is_russian(language) else "Entry"
    invalidation_label = "Инвалидация" if is_russian(language) else "Invalidation"
    target_label = "Цель" if is_russian(language) else "Target zone"
    created_label = "Создан" if is_russian(language) else "Created"
    status_label = "Статус" if is_russian(language) else "Status"
    regime_label = "Режим" if is_russian(language) else "Regime"
    strategy_label = _strategy_label(strategy_key, language_code=language)
    if isinstance(entry_zone_low, (int, float)) and isinstance(entry_zone_high, (int, float)):
        entry_value = f"<b>{format_price(float(entry_zone_low))} - {format_price(float(entry_zone_high))}</b>"
    else:
        entry_value = f"<b>{format_price(signal.price)}</b>"
    if isinstance(tp_price_primary, (int, float)):
        target_value = f"<b>{format_price(float(tp_price_primary))}</b>"
    elif isinstance(benchmark_win_percent, (int, float)):
        target_value = f"<b>+{float(benchmark_win_percent):.1f}% benchmark</b>"
    else:
        target_value = "<b>+7% benchmark</b>"
    why_label = "Почему это важно" if is_russian(language) else "Why it matters"
    received_label = "Почему ты получил этот сигнал" if is_russian(language) else "Why you received this"
    quality_label = (
        str(signal.metadata.get("setup_quality") or "")
        or ("Высокое" if signal.score >= 80 and is_russian(language) else "High" if signal.score >= 80 else "Среднее" if is_russian(language) else "Medium")
    )
    volume_header_label = "Объем" if is_russian(language) else "Volume"
    volume_header_value = format_volume(volume_value) if volume_value is not None else ("н/д" if is_russian(language) else "n/a")
    followup_state = (
        "Включён" if signal.metadata.get("interactive_reason_enabled") and is_russian(language) else
        "Enabled" if signal.metadata.get("interactive_reason_enabled") else
        "Tracked" if not is_russian(language) else "Отслеживается"
    )
    main_line = (
        f"{headline_price_label}: <b>{format_price(headline_price)}</b> • "
        f"RSI: <b>{format_rsi(float(closed_rsi))}</b> • "
        f"Score: <b>{signal.score}/100</b>"
    )
    header_metrics_line = (
        f"{main_line} • {volume_header_label}: <b>{escape_html(volume_header_value)}</b>"
    )
    badge_line = (
        f"[{escape_html(status_badge_label)}] [{escape_html(strategy_label)}] "
        f"[{escape_html(setup_label)}]"
    )
    okak_banner = "<b>СТРАТЕГИЯ OKAK</b>" if is_russian(language) else "<b>OKAK STRATEGY</b>"
    ekek_banner = "<b>🌊 СТРАТЕГИЯ EKEK</b>" if is_russian(language) else "<b>🌊 EKEK STRATEGY</b>"
    okak_checks_summary = str(signal.metadata.get("okak_criteria_summary") or "").strip()
    ekek_impulse_summary = str(signal.metadata.get("ekek_impulse_summary") or "").strip()
    quality_line = (
        f"{'Качество' if is_russian(language) else 'Quality'}: <b>{escape_html(str(quality_label))}</b>"
        f" • {'Режим' if is_russian(language) else 'Regime Fit'}: <b>{escape_html(market_regime_tag or ('Mixed' if not is_russian(language) else 'Смешанный'))}</b>"
        f" • {'Фоллоу-ап' if is_russian(language) else 'Follow-up'}: <b>{escape_html(followup_state)}</b>"
    )
    summary_text = str(signal.metadata.get("explanation_short") or "").strip() or str(context_text or bias_note).strip()
    show_why_block = (
        display_mode != "simple"
        and bool(context_text.strip())
        and context_text.strip() != summary_text
    )
    text_layout = str(signal.metadata.get("text_layout") or "").strip().lower()
    if text_layout == "v2_3_signal":
        price_now = float(live_price) if isinstance(live_price, (int, float)) else float(signal.price)
        zone = (
            f"{format_price(float(entry_zone_low))}–{format_price(float(entry_zone_high))}"
            if isinstance(entry_zone_low, (int, float)) and isinstance(entry_zone_high, (int, float))
            else format_price(float(signal.price))
        )
        invalidation = format_price(float(invalidation_price)) if isinstance(invalidation_price, (int, float)) else ("не задан" if is_russian(language) else "not set")
        target = format_price(float(tp_price_primary)) if isinstance(tp_price_primary, (int, float)) else ("не задана" if is_russian(language) else "not set")
        raw_rsi_status = str(signal.metadata.get("rsi_status") or signal.direction or "").strip().lower()
        is_long = setup_direction == "long"
        direction = "ЛОНГ" if is_long and is_russian(language) else "ШОРТ" if is_russian(language) else "LONG" if is_long else "SHORT"
        rsi_value = format_rsi(float(signal.rsi))
        if is_russian(language):
            rsi_reason = "RSI находится в зоне перепроданности." if raw_rsi_status == "oversold" else "RSI находится в зоне перекупленности." if raw_rsi_status == "overbought" else "Индикаторы и фильтры стратегии подтвердили сценарий."
            localized_reason = escape_html(summary_text[:180]) if re.search(r"[А-Яа-яЁё]", summary_text) else ""
            lines = [
                f"<b>{escape_html(display_symbol)} · {direction} · {escape_html(signal.timeframe)}</b>",
                f"RSI(14): <b>{rsi_value}</b> · Оценка сетапа: <b>{int(signal.score)}/100</b>",
                "",
                f"Текущая цена: <b>{format_price(price_now)}</b>",
                f"Зона входа: <b>{zone}</b>",
                f"Отмена сценария: <b>{invalidation}</b>",
                f"Цель: <b>{target}</b>",
                "",
                "<b>Почему появился сигнал</b>",
                f"{rsi_reason} {localized_reason}".strip(),
                "Мы сообщим, если сценарий изменится.",
            ]
        else:
            rsi_reason = "RSI is in the oversold zone." if raw_rsi_status == "oversold" else "RSI is in the overbought zone." if raw_rsi_status == "overbought" else "The strategy filters confirmed the setup."
            lines = [
                f"<b>{escape_html(display_symbol)} · {direction} · {escape_html(signal.timeframe)}</b>",
                f"RSI(14): <b>{rsi_value}</b> · Setup score: <b>{int(signal.score)}/100</b>",
                "",
                f"Current price: <b>{format_price(price_now)}</b>",
                f"Entry zone: <b>{zone}</b>",
                f"Invalidation: <b>{invalidation}</b>",
                f"Target: <b>{target}</b>",
                "",
                "<b>Why this signal appeared</b>",
                f"{rsi_reason} {escape_html(summary_text[:180])}".strip(),
                "We will update you if the setup changes.",
            ]
        if footer_note:
            lines.extend(["", escape_html(footer_note)])
        return "\n".join(lines)
    if text_layout == "v2_2_compact":
        price_now = float(live_price) if isinstance(live_price, (int, float)) else float(signal.price)
        zone = (
            f"{format_price(float(entry_zone_low))}–{format_price(float(entry_zone_high))}"
            if isinstance(entry_zone_low, (int, float)) and isinstance(entry_zone_high, (int, float))
            else format_price(float(signal.price))
        )
        invalidation = format_price(float(invalidation_price)) if isinstance(invalidation_price, (int, float)) else ("не задан" if is_russian(language) else "not set")
        target = format_price(float(tp_price_primary)) if isinstance(tp_price_primary, (int, float)) else ("не задана" if is_russian(language) else "not set")
        direction = (
            "ЛОНГ" if setup_direction == "long" and is_russian(language)
            else "ШОРТ" if is_russian(language)
            else "LONG" if setup_direction == "long" else "SHORT"
        )
        short_reason = escape_html(summary_text[:180])
        if is_russian(language):
            lines = [
                f"🚨 <b>{escape_html(display_symbol)} · {direction} · {escape_html(signal.timeframe)}</b>",
                f"{status_badge_emoji} {escape_html(strategy_label)} · ⭐ <b>{int(signal.score)}/100</b>",
                "",
                f"💵 Сейчас: <b>{format_price(price_now)}</b>",
                f"🎯 Зона: <b>{zone}</b>",
                f"🛑 Отмена: <b>{invalidation}</b>",
                f"🏁 Цель: <b>{target}</b>",
            ]
            if short_reason:
                lines.extend(["", f"📌 {short_reason}"])
            lines.append("🔄 Обновим, когда сценарий изменится.")
        else:
            lines = [
                f"🚨 <b>{escape_html(display_symbol)} · {direction} · {escape_html(signal.timeframe)}</b>",
                f"{status_badge_emoji} {escape_html(strategy_label)} · ⭐ <b>{int(signal.score)}/100</b>",
                "",
                f"💵 Now: <b>{format_price(price_now)}</b>",
                f"🎯 Entry zone: <b>{zone}</b>",
                f"🛑 Invalidation: <b>{invalidation}</b>",
                f"🏁 Target: <b>{target}</b>",
            ]
            if short_reason:
                lines.extend(["", f"📌 {short_reason}"])
            lines.append("🔄 We will update you when the setup changes.")
        if footer_note:
            lines.extend(["", escape_html(footer_note)])
        return "\n".join(lines)
    if text_layout == "v2_1_compact":
        price_now = float(live_price) if isinstance(live_price, (int, float)) else float(signal.price)
        strategy_line = _strategy_label(strategy_key, language_code=language)
        zone = (
            f"{format_price(float(entry_zone_low))}–{format_price(float(entry_zone_high))}"
            if isinstance(entry_zone_low, (int, float)) and isinstance(entry_zone_high, (int, float))
            else format_price(float(signal.price))
        )
        invalidation = format_price(float(invalidation_price)) if isinstance(invalidation_price, (int, float)) else ("не задана" if is_russian(language) else "not set")
        target = format_price(float(tp_price_primary)) if isinstance(tp_price_primary, (int, float)) else ("не задана" if is_russian(language) else "not set")
        short_reason = escape_html(summary_text[:240])
        direction = "SHORT" if setup_direction == "short" else "LONG"
        date = to_local_timestamp(signal.candle_close_time, timezone_obj)
        if is_russian(language):
            lines = [
                f"🚨 <b>{escape_html(display_symbol)} · {escape_html(signal.timeframe)} · {direction}</b>",
                f"📉 {escape_html(strategy_line)} · {status_badge_emoji} {escape_html(status_badge_label)}",
                f"⭐ Качество: <b>{int(signal.score)}/100</b>",
                "",
                f"💵 Цена сейчас: <b>{format_price(price_now)}</b>",
                f"🎯 Зона: <b>{zone}</b>",
                f"🛑 Отмена идеи: <b>{invalidation}</b>",
                f"🏁 Цель: <b>{target}</b>",
                "",
                "📌 Суть:",
                short_reason,
            ]
            if market_regime_tag:
                lines.append(f"🌐 Контекст: <b>{escape_html(market_regime_tag)}</b>")
            if signal.day_change_pct is not None:
                lines.append(f"📊 Изменение за 24ч: <b>{format_percent(signal.day_change_pct)}</b>")
            if volume_value is not None:
                lines.append(f"💧 Объём за 24ч: <b>{escape_html(format_volume(volume_value))}</b>")
            lines.extend(["", f"🕒 {date}", "🔄 Follow-up: <b>включён</b>", "", "⚠️ Информационный материал, не финансовая рекомендация."])
        else:
            lines = [
                f"🚨 <b>{escape_html(display_symbol)} · {escape_html(signal.timeframe)} · {direction}</b>",
                f"📉 {escape_html(strategy_line)} · {status_badge_emoji} {escape_html(status_badge_label)}",
                f"⭐ Quality: <b>{int(signal.score)}/100</b>",
                "",
                f"💵 Price now: <b>{format_price(price_now)}</b>",
                f"🎯 Zone: <b>{zone}</b>",
                f"🛑 Invalidation: <b>{invalidation}</b>",
                f"🏁 Target: <b>{target}</b>",
                "",
                "📌 Summary:",
                short_reason,
            ]
            if market_regime_tag:
                lines.append(f"🌐 Context: <b>{escape_html(market_regime_tag)}</b>")
            if signal.day_change_pct is not None:
                lines.append(f"📊 24h change: <b>{format_percent(signal.day_change_pct)}</b>")
            if volume_value is not None:
                lines.append(f"💧 24h volume: <b>{escape_html(format_volume(volume_value))}</b>")
            lines.extend(["", f"🕒 {date}", "🔄 Follow-up: <b>enabled</b>", "", "⚠️ Informational material, not financial advice."])
        if footer_note:
            lines.extend(["", escape_html(footer_note)])
        return "\n".join(lines)
    if text_layout == "premium_readable":
        levels_header = "Уровни" if is_russian(language) else "Levels"
        setup_header = "Сетап" if is_russian(language) else "Setup"
        history_header = "🧭 История 1h / 4h" if is_russian(language) else "🧭 1h / 4h History"
        context_header = "Контекст" if is_russian(language) else "Context"
        direction_header = "Направление" if is_russian(language) else "Trade direction"
        strategy_header = "Стратегия" if is_russian(language) else "Strategy"
        rsi_status_header = "Статус RSI" if is_russian(language) else "RSI status"
        current_rsi_score_header = "RSI / Score сейчас" if is_russian(language) else "RSI / Score now"
        alert_rsi_score_header = "RSI / Score на сигнале" if is_russian(language) else "RSI / Score at alert"
        quality_header = "Качество" if is_russian(language) else "Quality"
        followup_header = "Фоллоу-ап" if is_russian(language) else "Follow-up"
        risk_header = "Риск" if is_russian(language) else "Risk"
        market_context_lines: list[str] = []
        if signal.day_change_pct is not None:
            market_context_lines.append(f"24h: <b>{format_percent(signal.day_change_pct)}</b>")
        if volume_value is not None:
            market_context_lines.append(f"{volume_header_label}: <b>{escape_html(volume_header_value)}</b>")
        if market_regime_tag:
            market_context_lines.append(f"{regime_label}: <b>{escape_html(market_regime_tag)}</b>")
        if isinstance(live_rsi, (int, float)):
            market_context_lines.append(f"RSI live: <b>{format_rsi(float(live_rsi))}</b>")
        market_context_lines.append(f"{created_label}: <b>{to_local_timestamp(signal.candle_close_time, timezone_obj)}</b>")
        historical_focus_line, historical_lines = _historical_resistance_display(
            signal.metadata,
            language_code=language,
        )
        lines = [
            f"<b>{escape_html(wave_prefix + display_symbol)} • {escape_html(signal.timeframe)}</b>",
            badge_line,
        ]
        if summary_text:
            lines.extend(["", escape_html(summary_text)])
        if historical_focus_line:
            lines.extend(["", historical_focus_line])
        lines.extend(
            [
                "",
                f"<b>{setup_header}</b>",
                f"{strategy_header}: <b>{escape_html(strategy_label)}</b>",
                f"{headline_price_label}: <b>{format_price(headline_price)}</b>",
                f"{direction_header}: <b>{escape_html(setup_label)}</b>",
                f"{current_rsi_score_header}: <b>{format_rsi(float(closed_rsi))}</b> / <b>{signal.score}/100</b>",
                f"{alert_rsi_score_header}: <b>{format_rsi(alert_rsi_value)}</b> / <b>{alert_score_value}/100</b>",
                f"{quality_header}: <b>{escape_html(str(quality_label))}</b>",
                f"{followup_header}: <b>{escape_html(followup_state)}</b>",
            ]
        )
        if signal.direction != setup_direction:
            lines.append(f"{rsi_status_header}: <b>{escape_html(status)}</b>")
        if historical_lines:
            lines.extend(["", f"<b>{history_header}</b>", *historical_lines])
        lines.extend(
            [
                "",
                f"<b>{levels_header}</b>",
                f"{entry_label}: {entry_value}",
                f"{invalidation_label}: <b>{_value_or_na(invalidation_price, formatter=format_price, language_code=language)}</b>",
                f"{target_label}: {target_value}",
            ]
        )
        if display_mode != "simple" and rsi_window_line:
            lines.append(rsi_window_line.rstrip())
        if display_mode == "simple":
            lines.extend(
                [
                    "",
                    f"<b>{risk_header}</b>",
                    (
                        "Сценарий отменяется при нарушении invalidation. Это аналитический ориентир, не гарантия TP/SL."
                        if is_russian(language)
                        else "The scenario is invalidated if price breaks the invalidation level. This is an analytical reference, not a guaranteed TP/SL."
                    ),
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    f"<b>{context_header}</b>",
                    *market_context_lines,
                ]
            )
            if why_received_text:
                lines.extend(["", f"<b>{received_label}</b>", escape_html(why_received_text)])
            if show_why_block:
                lines.extend(["", f"<b>{why_label}</b>", escape_html(context_text or bias_note)])
        lines.extend(
            [
                "",
                (
                    "Информационный материал, не финансовая рекомендация. Управляй риском самостоятельно."
                    if is_russian(language)
                    else "Informational only, not financial advice. Manage risk independently."
                ),
            ]
        )
        if footer_note:
            lines.extend(["", escape_html(footer_note)])
        if preview:
            lines.insert(0, f"<b>{'Preview' if not is_russian(language) else 'Превью'}</b>")
        return "\n".join(lines)
    lines = []
    if strategy_key in {"okak", "ekek"}:
        strategy_banner = ekek_banner if strategy_key == "ekek" else okak_banner
        lines.extend(
            [
                strategy_banner,
                f"<b>{escape_html(wave_prefix + display_symbol)} • {escape_html(signal.timeframe)}</b>",
                header_metrics_line,
                badge_line,
            ]
        )
        if okak_checks_summary:
            okak_label = "Совпало по OKAK" if is_russian(language) else "OKAK match"
            lines.append(f"{okak_label}: <b>{escape_html(okak_checks_summary)}</b>")
        if strategy_key == "ekek" and ekek_impulse_summary:
            ekek_label = "Импульс EKEK" if is_russian(language) else "EKEK impulse"
            lines.append(f"{ekek_label}: <b>{escape_html(ekek_impulse_summary)}</b>")
    else:
        lines.extend(
            [
                f"<b>{escape_html(wave_prefix + display_symbol)} • {escape_html(signal.timeframe)}</b>",
                main_line,
                badge_line,
            ]
        )
    if summary_text:
        lines.append(escape_html(summary_text))
    lines.extend(
        [
            " • ".join(secondary_parts),
            quality_line,
            f"{'Риск' if is_russian(language) else 'Risk'}: <b>{format_price(float(invalidation_price)) if isinstance(invalidation_price, (int, float)) else ('не задан' if is_russian(language) else 'not set')}</b>",
            f"{created_label}: <b>{to_local_timestamp(signal.candle_close_time, timezone_obj)}</b>",
        ]
    )
    if display_mode != "simple":
        lines.extend(
            [
                f"{entry_label}: {entry_value}",
                f"{invalidation_label}: <b>{format_price(float(invalidation_price)) if isinstance(invalidation_price, (int, float)) else 'n/a'}</b>",
                f"{target_label}: {target_value}",
            ]
        )
        if rsi_window_line:
            lines.append(rsi_window_line.rstrip())
    if live_parts:
        lines.append(" • ".join(live_parts))
    if show_why_block:
        lines.extend(
            [
                "",
                f"<b>{why_label}</b>",
                escape_html(context_text or bias_note),
            ]
        )
    if why_received_text:
        lines.extend(["", f"<b>{received_label}</b>", escape_html(why_received_text)])
    lines.extend(
        [
            "",
            (
                "Информационный материал, не финансовая рекомендация. Управляй риском самостоятельно."
                if is_russian(language)
                else "Informational only, not financial advice. Manage risk independently."
            ),
        ]
    )
    if footer_note:
        lines.extend(["", escape_html(footer_note)])
    if preview:
        lines.insert(0, f"<b>{'Preview' if not is_russian(language) else 'Превью'}</b>")
    return "\n".join(lines)


def format_followup_message(
    result: FollowUpResult,
    timezone_obj,
    *,
    language_code: str = "en",
    footer_note: str | None = None,
) -> str:
    language = normalize_language(language_code)
    display_symbol = normalize_symbol(result.symbol)
    strategy_key = str(result.metadata.get("strategy_key") or "rsi").strip().lower() or "rsi"
    wave_prefix = "🌊 " if strategy_key == "ekek" else ""
    stage = result.stage or str(result.metadata.get("followup_stage") or "2h")
    thesis = evaluate_thesis_result(result.direction, result.move_pct)
    thesis_state = str(result.thesis_result_state or "").strip().lower()
    if thesis_state not in {"favorable", "adverse", "neutral"}:
        thesis_state = thesis.thesis_result_state
    elif thesis_state == "neutral" and thesis.thesis_result_state != "neutral":
        thesis_state = thesis.thesis_result_state
    favorable_move = result.favorable_move_pct
    if favorable_move <= 0.0 and isinstance(result.metadata.get("favorable_move_pct"), (int, float)):
        favorable_move = float(result.metadata.get("favorable_move_pct") or 0.0)
    if favorable_move <= 0.0:
        favorable_move = thesis.favorable_move_pct
    result_label = "Результат" if is_russian(language) else "Result"
    favorable_label = "В нашу сторону" if is_russian(language) else "In our favor"
    observed_label = "Зафиксировано" if is_russian(language) else "Observed"
    stage_label = "Этап" if is_russian(language) else "Stage"
    outcome_label = "Итог" if is_russian(language) else "Outcome"
    lifecycle_status = str(
        result.metadata.get("signal_status")
        or result.metadata.get("lifecycle_status")
        or ""
    ).strip().lower()
    outcome, interpretation = _followup_outcome(
        lifecycle_status,
        thesis_state,
        language_code=language,
    )
    trust_reminder = (
        "Прошлые результаты не гарантируют будущие. Управляй риском самостоятельно."
        if is_russian(language)
        else "Past results do not guarantee future results. Manage risk independently."
    )
    text_layout = str(result.metadata.get("text_layout") or "").strip().lower()
    if text_layout in {"v2_2_compact", "v2_3_signal"}:
        result_direction = resolve_trade_direction(
            result.direction,
            setup_direction=str(result.metadata.get("setup_direction") or ""),
        )
        direction = (
            "ЛОНГ" if result_direction == "long" and is_russian(language)
            else "ШОРТ" if is_russian(language)
            else "LONG" if result_direction == "long" else "SHORT"
        )
        result_state = _followup_state_label(thesis_state, language_code=language)
        if is_russian(language):
            lines = [
                f"🔄 <b>{escape_html(display_symbol)} · {direction} · {escape_html(result.timeframe)}</b>",
                f"📌 Итог: <b>{escape_html(outcome)}</b>",
                f"💵 Сейчас: <b>{format_price(float(result.current_price))}</b> · от сигнала: <b>{format_percent(result.move_pct)}</b>",
                f"📈 В нашу сторону: <b>{format_percent(favorable_move)}</b> · {escape_html(result_state)}",
            ]
            if result.summary:
                lines.extend(["", escape_html(result.summary[:180])])
            lines.append(f"🕒 Этап {escape_html(stage)} · {to_local_timestamp(result.observed_at, timezone_obj)}")
        else:
            lines = [
                f"🔄 <b>{escape_html(display_symbol)} · {direction} · {escape_html(result.timeframe)}</b>",
                f"📌 Outcome: <b>{escape_html(outcome)}</b>",
                f"💵 Now: <b>{format_price(float(result.current_price))}</b> · since alert: <b>{format_percent(result.move_pct)}</b>",
                f"📈 In favor: <b>{format_percent(favorable_move)}</b> · {escape_html(result_state)}",
            ]
            if result.summary:
                lines.extend(["", escape_html(result.summary[:180])])
            lines.append(f"🕒 Stage {escape_html(stage)} · {to_local_timestamp(result.observed_at, timezone_obj)}")
        if footer_note:
            lines.extend(["", escape_html(footer_note)])
        return "\n".join(lines)
    if text_layout == "premium_readable":
        update_header = "Апдейт" if is_russian(language) else "Update"
        timing_header = "Время" if is_russian(language) else "Timing"
        result_status_label = "Статус" if is_russian(language) else "Result"
        alert_label = "На сигнале" if is_russian(language) else "Alert"
        now_label = "Сейчас" if is_russian(language) else "Now"
        move_label = "Движение" if is_russian(language) else "Move since alert"
        lines = [
            (
                f"<b>Фоллоу-ап · {escape_html(wave_prefix + display_symbol)} · {escape_html(result.timeframe)}</b>"
                if is_russian(language)
                else f"<b>Follow-up · {escape_html(wave_prefix + display_symbol)} · {escape_html(result.timeframe)}</b>"
            ),
            f"[{escape_html(_status_chip('followup', language_code=language))}] [{escape_html(_strategy_label(strategy_key, language_code=language))}]",
            f"{outcome_label}: <b>{escape_html(outcome)}</b>",
        ]
        if result.summary:
            lines.extend(["", escape_html(result.summary)])
        lines.extend(
            [
                "",
                f"<b>{update_header}</b>",
                f"{now_label}: <b>{format_price(float(result.current_price))}</b>",
                f"{alert_label}: <b>{format_price(float(result.alert_price))}</b>",
                f"{move_label}: <b>{format_percent(result.move_pct)}</b>",
                f"RSI: <b>{format_rsi(float(result.alert_rsi))} → {format_rsi(float(result.current_rsi))}</b>",
                f"{result_status_label}: <b>{escape_html(_followup_state_label(thesis_state, language_code=language))}</b>",
                escape_html(interpretation),
                f"{favorable_label}: <b>{format_percent(favorable_move)}</b>",
                "",
                f"<b>{timing_header}</b>",
                f"{stage_label}: <b>{escape_html(stage)}</b>",
                f"{observed_label}: <b>{to_local_timestamp(result.observed_at, timezone_obj)}</b>",
                "",
                escape_html(trust_reminder),
            ]
        )
        if footer_note:
            lines.extend(["", escape_html(footer_note)])
        return "\n".join(lines)
    lines = [
        (
            f"<b>Фоллоу-ап · {escape_html(wave_prefix + display_symbol)} · {escape_html(result.timeframe)}</b>"
            if is_russian(language)
            else f"<b>Follow-up · {escape_html(wave_prefix + display_symbol)} · {escape_html(result.timeframe)}</b>"
        ),
        f"[{escape_html(_status_chip('followup', language_code=language))}] [{escape_html(_strategy_label(strategy_key, language_code=language))}]",
        (
            f"{'Сейчас' if is_russian(language) else 'Now'}: <b>{format_price(float(result.current_price))}</b> • "
            f"{'На сигнале' if is_russian(language) else 'Alert'}: <b>{format_price(float(result.alert_price))}</b>"
        ),
        (
            f"{result_label}: <b>{escape_html(_followup_state_label(thesis_state, language_code=language))}</b> • "
            f"{favorable_label}: <b>{format_percent(favorable_move)}</b>"
        ),
        f"{outcome_label}: <b>{escape_html(outcome)}</b> • {escape_html(interpretation)}",
        f"{stage_label}: <b>{escape_html(stage)}</b> • {observed_label}: <b>{to_local_timestamp(result.observed_at, timezone_obj)}</b>",
        "",
        escape_html(trust_reminder),
    ]
    if footer_note:
        lines.extend(["", escape_html(footer_note)])
    return "\n".join(lines)


def format_generated_post_review(
    channel_kind: str,
    content_type: str,
    content: str,
    *,
    status: str,
    destination: str,
) -> str:
    label = status.upper()
    return f"[{channel_kind.upper()} {content_type.upper()} {label}]\nTarget: {destination}\n\n{content}"


def format_lab_batch_message(batch_kind: str, items: list[str], remaining_count: int) -> str:
    title = "LAB Internal Batch" if batch_kind == "internal_summary" else "LAB Review Batch"
    body = "\n\n".join(items)
    suffix = f"\n\nMore queued: {remaining_count}" if remaining_count > 0 else ""
    return f"[{title}]\n\n{body}{suffix}"


def format_lab_review_bundle(
    *,
    symbol: str,
    scope: str,
    posts: list[GeneratedPost],
    twitter_draft: TwitterDraft | None = None,
) -> str:
    title = "Follow-up Review" if scope == "followup" else "Draft Review"
    lines = [f"[{title}] {symbol}"]
    for post in posts:
        status = {
            "sent": "LIVE",
            "batched": "LIVE",
            "scheduled": "DELAYED",
            "bundle_pending": "DRAFT",
            "rate_limited": "DRAFT",
        }.get(post.status, "DRAFT")
        label = {
            "public": "PUBLIC",
            "pro": "PRO+",
            "results": "RESULTS",
            "community": "COMMUNITY",
        }.get(post.channel_kind, post.channel_kind.upper())
        lines.append("")
        lines.append(f"{label} [{status}]")
        lines.append(post.generated_text.strip())
    if twitter_draft is not None and twitter_draft.status != "skipped":
        lines.append("")
        lines.append("X DRAFT")
        lines.append(twitter_draft.main_text.strip())
        if twitter_draft.short_variant:
            lines.append("")
            lines.append("Alt version:")
            lines.append(twitter_draft.short_variant.strip())
    return "\n".join(lines)


def format_twitter_draft_message(draft: TwitterDraft) -> str:
    text = draft.main_text.strip()
    text = re.sub(r"(?is)\n(?:shorter|alt version|reply/comment):\s*\n.*$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def format_interactive_analysis_message(
    *,
    symbol: str,
    timeframe: str,
    analysis_text: str,
    language_code: str = "en",
) -> str:
    language = normalize_language(language_code)
    display_symbol = normalize_symbol(symbol)
    return (
        f"\U0001F9E0 <b>{'AI Analysis' if not is_russian(language) else 'AI анализ'} • {escape_html(display_symbol)} • {escape_html(timeframe)}</b>\n"
        f"{escape_html('What this setup means' if not is_russian(language) else 'Что означает этот сетап')}\n\n"
        f"{escape_html(analysis_text)}"
    )


def format_interactive_risk_message(
    *,
    symbol: str,
    timeframe: str,
    risk_text: str,
    language_code: str = "en",
) -> str:
    language = normalize_language(language_code)
    display_symbol = normalize_symbol(symbol)
    return (
        f"\U0001F4CF <b>{'Risk Plan' if not is_russian(language) else 'План риска'} • {escape_html(display_symbol)} • {escape_html(timeframe)}</b>\n"
        f"{escape_html('Practical plan variants' if not is_russian(language) else 'Практические варианты плана')}\n\n"
        f"{escape_html(risk_text)}"
    )


def format_interactive_rationale_message(
    *,
    symbol: str,
    timeframe: str,
    rationale_text: str,
    language_code: str = "en",
) -> str:
    language = normalize_language(language_code)
    display_symbol = normalize_symbol(symbol)
    return (
        f"\U0001F4D8 <b>{'Signal Reason' if not is_russian(language) else 'Почему сигнал'} • {escape_html(display_symbol)} • {escape_html(timeframe)}</b>\n"
        f"{escape_html('Why this trigger matters' if not is_russian(language) else 'Почему этот триггер важен')}\n\n"
        f"{escape_html(rationale_text)}"
    )


def format_interactive_compare_message(
    *,
    symbol: str,
    timeframe: str,
    reference_label: str,
    strength_text: str,
    changed_lines: list[str],
    passed_lines: list[str],
    language_code: str = "en",
) -> str:
    language = normalize_language(language_code)
    display_symbol = normalize_symbol(symbol)
    summary_title = "Итог сравнения" if is_russian(language) else "Compare Summary"
    changed_title = "Что изменилось" if is_russian(language) else "What changed"
    passed_title = "Что всё ещё проходит" if is_russian(language) else "What still passes"
    lines = [
        f"\U0001F4CA <b>{escape_html(premium_text(language, 'compare_title'))} • {escape_html(display_symbol)} • {escape_html(timeframe)}</b>",
        escape_html(reference_label),
        "",
        f"<b>{escape_html(summary_title)}</b>",
        escape_html(strength_text),
    ]
    if changed_lines:
        lines.extend(["", f"<b>{escape_html(changed_title)}</b>"])
        lines.extend(f"• {escape_html(line)}" for line in changed_lines[:4])
    if passed_lines:
        lines.extend(["", f"<b>{escape_html(passed_title)}</b>"])
        lines.extend(f"• {escape_html(line)}" for line in passed_lines[:4])
    return "\n".join(lines)

