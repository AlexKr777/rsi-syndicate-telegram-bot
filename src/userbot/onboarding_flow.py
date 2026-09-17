from __future__ import annotations

from typing import Any

from src.core.utils import escape_html, normalize_symbol
from src.localization import normalize_language, ui_text
from src.userbot.experience import QUIET_HOUR_PRESETS, delivery_mode_label, format_quiet_hours_window
from src.userbot.premium_text import premium_text

DEFAULT_STRATEGY_KEY = "rsi"

_STRATEGY_LABELS = {
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
}

_STRATEGY_FLOWS = {
    "breakout": ["preset", "volume", "direction", "symbols", "universe", "delivery", "followups", "summary"],
    "trend_pullback": ["preset", "direction", "volume", "symbols", "universe", "delivery", "followups", "summary"],
    "rsi_bollinger_mr": ["preset", "rsi_mode", "volume", "direction", "symbols", "universe", "delivery", "followups", "summary"],
    "rsi_bollinger_touch": ["preset", "volume", "direction", "symbols", "universe", "delivery", "followups", "summary"],
    "daily_rsi_80": ["preset", "symbols", "universe", "delivery", "followups", "summary"],
    "vwap": ["preset", "direction", "volume", "symbols", "universe", "delivery", "followups", "summary"],
    "false_breakout": ["preset", "direction", "volume", "symbols", "universe", "delivery", "followups", "summary"],
    "rsi": ["preset", "rsi_mode", "direction", "symbols", "universe", "delivery", "followups", "summary"],
    "rsi_divergence": ["preset", "volume", "direction", "symbols", "universe", "delivery", "followups", "summary"],
    "okak": ["preset", "rsi_mode", "direction", "symbols", "universe", "delivery", "followups", "summary"],
    "ekek": ["preset", "rsi_mode", "direction", "symbols", "universe", "delivery", "followups", "summary"],
    "bollinger": ["preset", "volume", "direction", "symbols", "universe", "delivery", "followups", "summary"],
    "gold": ["preset", "direction", "delivery", "followups", "summary"],
}

_STRATEGY_SYMBOL_SUGGESTIONS = {
    "breakout": ("BTC", "ETH", "SOL", "XRP"),
    "trend_pullback": ("BTC", "ETH", "BNB", "SOL"),
    "rsi_bollinger_mr": ("BTC", "ETH", "SOL", "DOGE"),
    "rsi_bollinger_touch": ("BTC", "ETH", "SOL", "XRP"),
    "daily_rsi_80": ("BTC", "ETH", "SOL", "XRP"),
    "vwap": ("BTC", "ETH", "SOL", "BNB"),
    "false_breakout": ("BTC", "ETH", "XRP", "ADA"),
    "rsi": ("BTC", "ETH", "SOL", "XRP"),
    "rsi_divergence": ("BTC", "ETH", "SOL", "XRP"),
    "okak": ("BTC", "ETH", "SOL", "XRP"),
    "ekek": ("BTC", "ETH", "SOL", "XRP"),
    "bollinger": ("BTC", "ETH", "LINK", "SOL"),
    "gold": ("XAUUSD",),
}

_PRESET_LABELS = {
    "breakout": {
        "en": {"conservative": "🧱 Confirmed", "balanced": "⚖ Clean", "aggressive": "⚡ Early"},
        "ru": {"conservative": "🧱 Подтвержденный", "balanced": "⚖ Чистый", "aggressive": "⚡ Ранний"},
    },
    "trend_pullback": {
        "en": {"conservative": "📈 Deep Trend", "balanced": "⚖ EMA Touch", "aggressive": "⚡ Fast Bounce"},
        "ru": {"conservative": "📈 Сильный тренд", "balanced": "⚖ От EMA", "aggressive": "⚡ Быстрый отскок"},
    },
    "rsi_bollinger_mr": {
        "en": {"conservative": "🎯 Clean Revert", "balanced": "⚖ Balanced MR", "aggressive": "⚡ Fast Snapback"},
        "ru": {"conservative": "🎯 Чистый возврат", "balanced": "⚖ Баланс MR", "aggressive": "⚡ Быстрый откат"},
    },
    "rsi_bollinger_touch": {
        "en": {"conservative": "рџЋЇ Clean Touch", "balanced": "вљ– Directional Touch", "aggressive": "вљЎ Early Tag"},
        "ru": {"conservative": "рџЋЇ Р§РёСЃС‚РѕРµ РєР°СЃР°РЅРёРµ", "balanced": "вљ– Directional Touch", "aggressive": "вљЎ Р Р°РЅРЅРёР№ С‚РµРі"},
    },
    "daily_rsi_80": {
        "en": {"conservative": "Very Selective", "balanced": "Daily Heat", "aggressive": "Wide Watchlist"},
        "ru": {"conservative": "Очень выборочно", "balanced": "Дневной перегрев", "aggressive": "Шире список"},
    },
    "vwap": {
        "en": {"conservative": "⚖ Hold VWAP", "balanced": "📍 Reclaim", "aggressive": "⚡ Quick Flip"},
        "ru": {"conservative": "⚖ Удержание VWAP", "balanced": "📍 Возврат над VWAP", "aggressive": "⚡ Быстрый переворот"},
    },
    "false_breakout": {
        "en": {"conservative": "🪤 Confirmed Trap", "balanced": "⚖ Clean Sweep", "aggressive": "⚡ Early Reversal"},
        "ru": {"conservative": "🪤 Подтвержденный вынос", "balanced": "⚖ Чистый sweep", "aggressive": "⚡ Ранний разворот"},
    },
    "rsi": {
        "en": {"conservative": "🛡 Cleaner", "balanced": "⚖ Balanced", "aggressive": "⚡ Earlier"},
        "ru": {"conservative": "🛡 Чище", "balanced": "⚖ Баланс", "aggressive": "⚡ Раньше"},
    },
    "rsi_divergence": {
        "en": {"conservative": "рџЋЇ Clear Divergence", "balanced": "вљ– Balanced Divergence", "aggressive": "вљЎ Early Divergence"},
        "ru": {"conservative": "рџЋЇ Р§РёСЃС‚Р°СЏ РґРёРІРµСЂРіРµРЅС†РёСЏ", "balanced": "вљ– Balanced Divergence", "aggressive": "вљЎ Р Р°РЅРЅСЏСЏ РґРёРІРµСЂРіРµРЅС†РёСЏ"},
    },
    "okak": {
        "en": {"conservative": "Strict", "balanced": "Core", "aggressive": "Wider"},
        "ru": {"conservative": "Строго", "balanced": "Основной", "aggressive": "Шире"},
    },
    "ekek": {
        "en": {"conservative": "Sharp Only", "balanced": "Impulse Core", "aggressive": "Faster Burst"},
        "ru": {"conservative": "Только резкий", "balanced": "Импульс Core", "aggressive": "Быстрее burst"},
    },
    "bollinger": {
        "en": {"conservative": "🎈 Clean Re-entry", "balanced": "⚖ Balanced Bands", "aggressive": "⚡ Faster Return"},
        "ru": {"conservative": "🎈 Чистый возврат", "balanced": "⚖ Баланс Bands", "aggressive": "⚡ Быстрый возврат"},
    },
    "gold": {
        "en": {"conservative": "🪙 Macro", "balanced": "⚖ Balanced", "aggressive": "⚡ Reactive"},
        "ru": {"conservative": "🪙 Макро", "balanced": "⚖ Баланс", "aggressive": "⚡ Реактивно"},
    },
}


def resolve_quick_setup_strategy_key(strategy_key: str | None) -> str:
    candidate = str(strategy_key or DEFAULT_STRATEGY_KEY).strip().lower()
    return candidate if candidate in _STRATEGY_FLOWS else DEFAULT_STRATEGY_KEY


def strategy_quick_setup_label(strategy_key: str | None, *, language_code: str) -> str:
    language = normalize_language(language_code)
    english, russian = _STRATEGY_LABELS[resolve_quick_setup_strategy_key(strategy_key)]
    return russian if language == "ru" else english


def strategy_preset_label(strategy_key: str | None, profile: str, *, language_code: str) -> str:
    language = normalize_language(language_code)
    strategy = resolve_quick_setup_strategy_key(strategy_key)
    labels = _PRESET_LABELS[strategy]["ru" if language == "ru" else "en"]
    return labels.get(profile, labels["balanced"])


def strategy_supports_rsi_mode(strategy_key: str | None) -> bool:
    return resolve_quick_setup_strategy_key(strategy_key) in {"rsi", "okak", "ekek", "rsi_bollinger_mr"}


def strategy_supports_volume(strategy_key: str | None) -> bool:
    return resolve_quick_setup_strategy_key(strategy_key) != "gold"


def strategy_supports_universe(strategy_key: str | None) -> bool:
    return resolve_quick_setup_strategy_key(strategy_key) != "gold"


def strategy_symbol_suggestions(strategy_key: str | None) -> tuple[str, ...]:
    return _STRATEGY_SYMBOL_SUGGESTIONS[resolve_quick_setup_strategy_key(strategy_key)]


def onboarding_steps(*, include_gold: bool, strategy_key: str | None = None) -> list[str]:
    del include_gold
    return _STRATEGY_FLOWS[resolve_quick_setup_strategy_key(strategy_key)][:]


def onboarding_total_steps(*, include_gold: bool, strategy_key: str | None = None) -> int:
    return len(onboarding_steps(include_gold=include_gold, strategy_key=strategy_key))


def empty_onboarding_draft(language_code: str = "en", strategy_key: str | None = None) -> dict[str, Any]:
    return {
        "language_code": normalize_language(language_code),
        "strategy_key": resolve_quick_setup_strategy_key(strategy_key),
        "signal_profile": "balanced",
        "rsi_mode": "balanced",
        "min_quote_volume": None,
        "direction_filter": "both",
        "favorite_symbols": [],
        "watchlist_only": False,
        "delivery_mode": "instant",
        "followup_delivery_enabled": True,
        "gold_alerts_enabled": False,
        "quiet_hours_key": "off",
        "quiet_hours_start_minute": None,
        "quiet_hours_end_minute": None,
    }


def next_onboarding_step(current_step: str, *, include_gold: bool, strategy_key: str | None = None) -> str:
    steps = onboarding_steps(include_gold=include_gold, strategy_key=strategy_key)
    if current_step not in steps:
        return steps[0]
    index = steps.index(current_step)
    return steps[min(index + 1, len(steps) - 1)]


def previous_onboarding_step(current_step: str, *, include_gold: bool, strategy_key: str | None = None) -> str:
    steps = onboarding_steps(include_gold=include_gold, strategy_key=strategy_key)
    if current_step not in steps:
        return steps[0]
    index = steps.index(current_step)
    return steps[max(index - 1, 0)]


def onboarding_step_index(step: str, *, include_gold: bool, strategy_key: str | None = None) -> int:
    steps = onboarding_steps(include_gold=include_gold, strategy_key=strategy_key)
    if step not in steps:
        return 1
    return steps.index(step) + 1


def parse_favorite_symbols_input(text: str) -> list[str]:
    raw_parts = [part.strip() for chunk in text.replace("\n", ",").split(",") for part in chunk.split()]
    symbols: list[str] = []
    for part in raw_parts:
        normalized = normalize_symbol(part)
        if len(normalized) < 2:
            continue
        if normalized not in symbols:
            symbols.append(normalized)
    return symbols[:12]


def apply_quiet_hours_preset(draft: dict[str, Any], preset_key: str) -> dict[str, Any]:
    start, end = QUIET_HOUR_PRESETS.get(preset_key, QUIET_HOUR_PRESETS["off"])
    updated = {**draft}
    updated["quiet_hours_key"] = preset_key
    updated["quiet_hours_start_minute"] = start
    updated["quiet_hours_end_minute"] = end
    return updated


def _direction_label(direction: str, language_code: str) -> str:
    key = {
        "long": "setup_long_only",
        "short": "setup_short_only",
    }.get(direction, "setup_both")
    return ui_text(language_code, key)


def _favorites_preview(symbols: list[str], *, language_code: str) -> str:
    if symbols:
        return ", ".join(symbols[:6])
    return premium_text(language_code, "onboarding_symbols_empty")


def _step_copy(strategy_key: str, step: str, *, language_code: str) -> tuple[str, str]:
    language = normalize_language(language_code)
    strategy = resolve_quick_setup_strategy_key(strategy_key)
    if language == "ru":
        copy = {
            "breakout": {
                "preset": ("Режим пробоя", "Насколько рано ловить выход из диапазона: только подтвержденный, баланс или ранний вход."),
                "volume": ("Ликвидность", "Оставь только те монеты, где пробой не развалится на пустом рынке."),
            },
            "trend_pullback": {
                "preset": ("Режим отката", "Насколько аккуратно ждать реакцию от EMA и продолжение тренда."),
                "volume": ("Ликвидность", "Фильтр по объему, чтобы откаты приходили там, где есть нормальный поток."),
            },
            "rsi_bollinger_mr": {
                "preset": ("Режим возврата", "Насколько чистым должен быть возврат после выброса цены."),
                "rsi_mode": ("RSI-гейт", "Насколько рано разрешать mean reversion: жестко, балансно или раньше."),
                "volume": ("Ликвидность", "Отсей пустые монеты, где возврат чаще оказывается шумом."),
            },
            "rsi_bollinger_touch": {
                "preset": ("Р РµР¶РёРј РєР°СЃР°РЅРёСЏ", "Р‘РѕС‚ РёС‰РµС‚ РѕРґРЅРѕРІСЂРµРјРµРЅРЅРѕ RSI-РєСЂР°Р№РЅРѕСЃС‚СЊ Рё РєР°СЃР°РЅРёРµ 30-РїРµСЂРёРѕРґРЅРѕР№ РїРѕР»РѕСЃС‹ Р‘РѕР»Р»РёРЅРґР¶РµСЂР° Р±РµР· sideways-С€СѓРјР°."),
                "volume": ("Р›РёРєРІРёРґРЅРѕСЃС‚СЊ", "РћСЃС‚Р°РІСЊ РјРѕРЅРµС‚С‹, РіРґРµ РєР°СЃР°РЅРёРµ РїРѕР»РѕСЃС‹ РЅРµ Р»РѕРјР°РµС‚СЃСЏ РёР·-Р·Р° С‚РѕРЅРєРѕРіРѕ СЂС‹РЅРєР°."),
            },
            "vwap": {
                "preset": ("Режим VWAP", "Выбери, ждать ли более чистое удержание VWAP или брать быстрый intraday-переворот."),
                "volume": ("Ликвидность", "VWAP лучше работает там, где в сессии есть поток и реакция на объем."),
            },
            "false_breakout": {
                "preset": ("Режим выноса", "Насколько подтвержденным должен быть ложный пробой перед алертом."),
                "volume": ("Ликвидность", "Оставь рынки, где sweep и возврат не происходят на пустых свечах."),
            },
            "rsi": {
                "preset": ("Режим качества", "Насколько чистыми должны быть экстремумы, прежде чем бот отправит сигнал."),
                "rsi_mode": ("Скорость RSI", "Жестко для крайних зон, балансно для середины, раньше для более ранних алертов."),
            },
            "rsi_divergence": {
                "preset": ("Р РµР¶РёРј РґРёРІРµСЂРіРµРЅС†РёРё", "Р‘РѕС‚ РёС‰РµС‚ РЅРѕРІС‹Р№ Р»РѕСѓ / С…Р°Р№ РїРѕ С†РµРЅРµ, РЅРѕ Р±РµР· РїРѕРґС‚РІРµСЂР¶РґРµРЅРёСЏ РѕС‚ RSI."),
                "volume": ("Р›РёРєРІРёРґРЅРѕСЃС‚СЊ", "РћСЃС‚Р°РІСЊ РґРёРІРµСЂРіРµРЅС†РёРё РЅР° РјРѕРЅРµС‚Р°С…, РіРґРµ РЅРѕРІС‹Р№ СЌРєСЃС‚СЂРµРјСѓРј РЅРµ СЏРІР»СЏРµС‚СЃСЏ СЃР»СѓС‡Р°Р№РЅС‹Рј С‚РёРєРѕРј."),
            },
            "bollinger": {
                "preset": ("Режим возврата", "Насколько чистым должен быть возврат цены обратно в канал Боллинджера."),
                "volume": ("Ликвидность", "Убери слишком тонкие монеты, где возвраты чаще случайны."),
            },
            "gold": {
                "preset": ("Режим золота", "Выбери более спокойный, балансный или быстрый стиль алертов по XAUUSD."),
            },
        }
        common = {
            "direction": ("Направление", "Оставь обе стороны или сфокусируйся только на long либо short."),
            "symbols": ("Избранные монеты", "Добавь ключевые тикеры, если хочешь быстрый список именно под эту стратегию."),
            "universe": ("Охват рынка", "Бот должен смотреть весь рынок или только твои избранные по этой стратегии?"),
            "delivery": ("Доставка", "Выбери, как должны приходить алерты: сразу, сводкой или тихим режимом."),
            "followups": ("Follow-up", "Нужны ли тебе карточки с результатом после отправленного сигнала?"),
            "summary": ("Готово", "Проверь итог и запусти поток уже с этой стратегией."),
        }
    else:
        copy = {
            "breakout": {
                "preset": ("Breakout Mode", "Choose how strict the breakout should be before the bot alerts you."),
                "volume": ("Liquidity", "Keep breakouts on markets that have enough real flow behind the move."),
            },
            "trend_pullback": {
                "preset": ("Pullback Mode", "Choose how patient the bot should be around the EMA reaction and trend continuation."),
                "volume": ("Liquidity", "Keep pullbacks on markets with enough flow for clean continuation."),
            },
            "rsi_bollinger_mr": {
                "preset": ("Reversion Mode", "Choose how clean the snapback should look before the bot sends it."),
                "rsi_mode": ("RSI Gate", "Pick how early the RSI filter is allowed to unlock a mean-reversion alert."),
                "volume": ("Liquidity", "Filter out thin markets where reversions are mostly noise."),
            },
            "rsi_bollinger_touch": {
                "preset": ("Touch Mode", "Look for RSI extremes that tag the 30-period Bollinger Band without flat sideways chop."),
                "volume": ("Liquidity", "Keep the touch setup on markets where the band tag is backed by real participation."),
            },
            "vwap": {
                "preset": ("VWAP Mode", "Choose between cleaner VWAP holds and faster intraday flips."),
                "volume": ("Liquidity", "VWAP works better where the session actually has flow."),
            },
            "false_breakout": {
                "preset": ("Trap Mode", "Choose how confirmed the liquidity sweep should be before the alert."),
                "volume": ("Liquidity", "Keep false breaks on markets where the sweep is backed by real participation."),
            },
            "rsi": {
                "preset": ("Quality Mode", "Choose how selective the bot should be about stretched RSI alerts."),
                "rsi_mode": ("RSI Speed", "Tight is stricter, balanced is neutral, early is faster but noisier."),
            },
            "rsi_divergence": {
                "preset": ("Divergence Mode", "Look for price making a new extreme while RSI fails to confirm it."),
                "volume": ("Liquidity", "Keep divergence alerts on markets where the new high or low is not just a random tick."),
            },
            "bollinger": {
                "preset": ("Band Re-entry Mode", "Choose how clean the move back into Bollinger Bands should look."),
                "volume": ("Liquidity", "Remove thinner markets where re-entries are less reliable."),
            },
            "gold": {
                "preset": ("Gold Mode", "Choose a calmer, balanced, or faster alert style for XAUUSD."),
            },
        }
        common = {
            "direction": ("Direction", "Keep both sides or focus only on long or short."),
            "symbols": ("Favorite Symbols", "Add key tickers if you want a faster strategy-specific list."),
            "universe": ("Universe", "Should this strategy scan the whole market or only your favorites?"),
            "delivery": ("Delivery", "Choose whether alerts should arrive live, in digest, or in quiet mode."),
            "followups": ("Follow-ups", "Decide whether you want result cards after delivered alerts."),
            "summary": ("Ready", "Check the final setup and start this strategy flow."),
        }
    strategy_copy = copy.get(strategy, copy[DEFAULT_STRATEGY_KEY])
    return strategy_copy.get(step) or common.get(step) or common["summary"]

def _summary_lines(
    *,
    draft: dict[str, Any],
    language_code: str,
) -> list[str]:
    language = normalize_language(language_code)
    strategy_key = resolve_quick_setup_strategy_key(draft.get("strategy_key"))
    symbols = [str(symbol) for symbol in draft.get("favorite_symbols", []) if str(symbol)]
    universe_label = ui_text(language, "setup_watchlist_only") if draft.get("watchlist_only") else ui_text(language, "setup_all_symbols")
    lines = [
        f"• {'Стратегия' if language == 'ru' else 'Strategy'}: <b>{escape_html(strategy_quick_setup_label(strategy_key, language_code=language))}</b>",
        f"• {'Режим' if language == 'ru' else 'Mode'}: <b>{escape_html(strategy_preset_label(strategy_key, str(draft.get('signal_profile') or 'balanced'), language_code=language))}</b>",
    ]
    if strategy_supports_rsi_mode(strategy_key):
        rsi_label = {
            "tight": ui_text(language, "setup_rsi_tight"),
            "early": ui_text(language, "setup_rsi_early"),
        }.get(str(draft.get("rsi_mode") or "balanced"), ui_text(language, "setup_rsi_balanced"))
        lines.append(f"• RSI: <b>{escape_html(rsi_label)}</b>")
    if strategy_supports_volume(strategy_key):
        volume_value = draft.get("min_quote_volume")
        volume_label = (
            f"{int(float(volume_value) / 1_000_000)}M+"
            if isinstance(volume_value, (int, float)) and float(volume_value) > 0
            else ("По базе" if language == "ru" else "Default")
        )
        lines.append(f"• {'Ликвидность' if language == 'ru' else 'Liquidity'}: <b>{escape_html(volume_label)}</b>")
    lines.append(f"• {'Направление' if language == 'ru' else 'Direction'}: <b>{escape_html(_direction_label(str(draft.get('direction_filter') or 'both'), language))}</b>")
    if strategy_supports_universe(strategy_key):
        lines.append(f"• {'Избранные' if language == 'ru' else 'Favorites'}: <b>{escape_html(_favorites_preview(symbols, language_code=language))}</b>")
        lines.append(f"• {'Охват' if language == 'ru' else 'Universe'}: <b>{escape_html(universe_label)}</b>")
    lines.append(
        f"• {'Доставка' if language == 'ru' else 'Delivery'}: <b>{escape_html(delivery_mode_label(str(draft.get('delivery_mode') or 'instant'), language_code=language))}</b>"
    )
    lines.append(
        f"• {'Follow-up' if language == 'ru' else 'Follow-ups'}: <b>{escape_html(ui_text(language, 'status_on' if draft.get('followup_delivery_enabled') else 'status_off'))}</b>"
    )
    if draft.get("quiet_hours_start_minute") is not None and draft.get("quiet_hours_end_minute") is not None:
        quiet_window = format_quiet_hours_window(
            draft.get("quiet_hours_start_minute"),
            draft.get("quiet_hours_end_minute"),
            language_code=language,
        )
        lines.append(f"• {'Тихие часы' if language == 'ru' else 'Quiet hours'}: <b>{escape_html(quiet_window)}</b>")
    return lines


def format_onboarding_message(
    *,
    step: str,
    draft: dict[str, Any],
    language_code: str,
    include_gold: bool,
) -> str:
    language = normalize_language(language_code)
    strategy_key = resolve_quick_setup_strategy_key(draft.get("strategy_key"))
    progress = premium_text(
        language,
        "onboarding_progress",
        current=onboarding_step_index(step, include_gold=include_gold, strategy_key=strategy_key),
        total=onboarding_total_steps(include_gold=include_gold, strategy_key=strategy_key),
    )
    title, body = _step_copy(strategy_key, step, language_code=language)
    current_setup_label = "📊 <b>Сейчас выбрано</b>" if language == "ru" else "📊 <b>Current setup</b>"
    lines = [
        f"<b>⚡ {escape_html(premium_text(language, 'menu_setup_wizard'))} • {escape_html(strategy_quick_setup_label(strategy_key, language_code=language))}</b>",
        "",
        f"<b>{escape_html(progress)}</b>",
        f"🧠 <b>{escape_html(title)}</b>",
        escape_html(body),
        "",
        current_setup_label,
        *(_summary_lines(draft=draft, language_code=language)),
    ]
    if step == "symbols":
        suggestion_label = "Подсказки" if language == "ru" else "Suggestions"
        suggestions = ", ".join(strategy_symbol_suggestions(strategy_key))
        lines.extend(["", escape_html(f"{suggestion_label}: {suggestions}")])
    if step == "summary":
        lines.append("")
        lines.append(
            "Запускай поток: сохранится именно эта быстрая настройка для текущей стратегии."
            if language == "ru"
            else "Start the flow: this exact quick setup will be saved for the current strategy."
        )
        lines.append(
            "Дальше на странице стратегии можно отдельно докрутить темп, контекст рынка и приоритет вечерних follow-up."
            if language == "ru"
            else "After that, the strategy page still lets you fine-tune pace, market context, and evening follow-up priority."
        )
    return "\n".join(lines)


def format_onboarding_summary_message(
    *,
    draft: dict[str, Any],
    language_code: str,
    include_gold: bool,
) -> str:
    del include_gold
    language = normalize_language(language_code)
    strategy_key = resolve_quick_setup_strategy_key(draft.get("strategy_key"))
    title = (
        f"✅ Быстрая настройка • {strategy_quick_setup_label(strategy_key, language_code=language)}"
        if language == "ru"
        else f"✅ Quick Setup • {strategy_quick_setup_label(strategy_key, language_code=language)}"
    )
    footer = (
        "Следом можно открыть страницу стратегии и отдельно докрутить тонкие strategy-specific фильтры."
        if language == "ru"
        else "Next you can open the strategy page and fine-tune the strategy-specific filters."
    )
    return "\n".join([f"<b>{escape_html(title)}</b>", "", *(_summary_lines(draft=draft, language_code=language)), "", escape_html(footer)])
