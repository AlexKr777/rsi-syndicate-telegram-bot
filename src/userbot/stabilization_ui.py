from __future__ import annotations

from typing import Any

from src.core.utils import escape_html
from src.localization import normalize_language
from src.userbot.personalization import asset_scope_summary


def _footer_rows(
    *,
    language_code: str,
    back_callback_data: str | None = None,
    home_callback_data: str = "main:today",
) -> list[list[dict[str, object]]]:
    language = normalize_language(language_code)
    home_label = "🏠 Home" if language == "en" else "🏠 Главная"
    back_label = "◀️ Back" if language == "en" else "◀️ Назад"
    if back_callback_data:
        return [[
            {"text": home_label, "callback_data": home_callback_data},
            {"text": back_label, "callback_data": back_callback_data},
        ]]
    return [[{"text": home_label, "callback_data": home_callback_data}]]


def format_create_setup_entry_message(*, language_code: str) -> str:
    language = normalize_language(language_code)
    if language == "ru":
        return (
            "<b>🧩 Создать сетап</b>\n\n"
            "Собери новый режим сигналов шаг за шагом.\n\n"
            "Сначала выбери, с чего начать:\n"
            "• пустой режим\n"
            "• текущие настройки\n"
            "• готовый шаблон"
        )
    return (
        "<b>🧩 Create Setup</b>\n\n"
        "Build a new signal mode step by step.\n\n"
        "Start from:\n"
        "• a blank setup\n"
        "• your current state\n"
        "• a ready template"
    )


def build_create_setup_entry_keyboard(
    *,
    language_code: str,
    back_callback_data: str | None = None,
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [
        [
            {
                "text": "🆕 Start Blank" if language == "en" else "🆕 С нуля",
                "callback_data": "ux:setupbuilder:start:blank",
            },
            {
                "text": "♻️ From Current" if language == "en" else "♻️ Из текущего",
                "callback_data": "ux:setupbuilder:start:current",
            },
        ],
        [
            {
                "text": "📚 From Template" if language == "en" else "📚 Из шаблона",
                "callback_data": "ux:setupbuilder:start:template",
            }
        ],
    ]
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data))
    return {"inline_keyboard": rows}


def build_truthful_setups_hub_keyboard(
    *,
    language_code: str,
    back_callback_data: str | None = None,
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [
        [
            {"text": "🧩 Saved Setups" if language == "en" else "🧩 Сохранённые сетапы", "callback_data": "ux:setup:list"},
            {"text": "➕ Create Setup" if language == "en" else "➕ Создать сетап", "callback_data": "ux:setup:create"},
        ],
        [
            {"text": "✨ Custom Filters" if language == "en" else "✨ Детальные фильтры", "callback_data": "ux:filtershub"},
        ],
    ]
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data))
    return {"inline_keyboard": rows}


def format_setup_template_picker_message(*, language_code: str) -> str:
    language = normalize_language(language_code)
    if language == "ru":
        return (
            "<b>📚 Шаблоны сетапов</b>\n\n"
            "Возьми готовую основу и потом спокойно подстрой её под себя."
        )
    return (
        "<b>📚 Setup Templates</b>\n\n"
        "Pick a ready starting point, then tune it to your style."
    )


def build_setup_template_picker_keyboard(
    *,
    language_code: str,
    back_callback_data: str | None = None,
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [
        [
            {
                "text": "🔕 Low Noise Majors" if language == "en" else "🔕 Мало шума • Мейджоры",
                "callback_data": "ux:setupbuilder:template:low_noise_majors",
            }
        ],
        [
            {
                "text": "🥇 Gold London" if language == "en" else "🥇 Gold • Лондон",
                "callback_data": "ux:setupbuilder:template:gold_london",
            }
        ],
        [
            {
                "text": "⚡ Fast Intraday" if language == "en" else "⚡ Быстрый intraday",
                "callback_data": "ux:setupbuilder:template:fast_intraday",
            }
        ],
        [
            {
                "text": "👀 Watchlist Only" if language == "en" else "👀 Только watchlist",
                "callback_data": "ux:setupbuilder:template:watchlist_only",
            }
        ],
        [
            {
                "text": "📊 High Score Only" if language == "en" else "📊 Только высокий score",
                "callback_data": "ux:setupbuilder:template:high_score_only",
            }
        ],
    ]
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data or "ux:setup:create"))
    return {"inline_keyboard": rows}


_SETUP_STRATEGY_LABELS = {
    "breakout": ("💥 Breakout", "💥 Пробой"),
    "trend_pullback": ("🌊 Pullback", "🌊 Откат"),
    "rsi_bollinger_mr": ("↔️ RSI + Bollinger MR", "↔️ RSI + Bollinger MR"),
    "vwap": ("📍 VWAP", "📍 VWAP"),
    "false_breakout": ("🪤 False Breakout", "🪤 Ложный пробой"),
    "rsi": ("📉 RSI", "📉 RSI"),
    "bollinger": ("🎈 Bollinger", "🎈 Боллинджер"),
    "ekek": ("🌊 EKEK", "🌊 EKEK"),
    "gold_breakout": ("🥇 Gold Breakout", "🥇 Gold Breakout"),
    "gold_pullback": ("🥇 Gold Pullback", "🥇 Gold Pullback"),
    "gold_liquidity": ("🥇 Gold Liquidity", "🥇 Gold Liquidity"),
    "rsi_bollinger_touch": ("RSI + Bollinger Touch", "RSI + Bollinger Touch"),
    "rsi_divergence": ("RSI Divergence", "RSI Divergence"),
}

_SETUP_TIMEFRAMES = ("5m", "15m", "30m", "1h", "4h", "1d")


def _setup_step_labels(language_code: str) -> dict[str, str]:
    language = normalize_language(language_code)
    if language == "ru":
        return {
            "name": "Название",
            "scope": "Охват активов",
            "strategies": "Стратегии",
            "timeframes": "Таймфреймы",
            "direction": "Направление",
            "session": "Сессия",
            "selectivity": "Отбор",
            "delivery": "Профиль доставки",
            "review": "Проверка",
        }
    return {
        "name": "Name",
        "scope": "Asset Scope",
        "strategies": "Strategies",
        "timeframes": "Timeframes",
        "direction": "Direction",
        "session": "Session",
        "selectivity": "Selectivity",
        "delivery": "Delivery Profile",
        "review": "Review",
    }


def _draft_name(draft: dict[str, Any]) -> str:
    return str(draft.get("name") or "New Setup").strip() or "New Setup"


def _scope_option_label(scope: str, *, language_code: str) -> str:
    language = normalize_language(language_code)
    mapping = {
        "all": ("🌐 All Coins", "🌐 Все монеты"),
        "watchlist": ("👀 Watchlist", "👀 Watchlist"),
        "favorites": ("⭐ Favorites", "⭐ Избранное"),
        "theme": ("🎨 Theme / Set", "🎨 Тема / сет"),
        "majors": ("🪙 Majors", "🪙 Мейджоры"),
        "gold": ("🥇 Gold Only", "🥇 Только золото"),
        "memes": ("🎭 Memes", "🎭 Мемы"),
        "custom": ("✍️ Custom Selection", "✍️ Свой выбор"),
    }
    english, russian = mapping.get(scope, mapping["all"])
    return russian if language == "ru" else english


def _draft_scope_state(draft: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    scope_type = str(draft.get("asset_scope_type") or draft.get("asset_scope") or "all").strip().lower()
    scope_type = {
        "all_enabled": "all",
        "all_coins": "all",
        "custom_symbols": "custom",
        "theme_set": "theme",
        "saved_set": "theme",
    }.get(scope_type, scope_type)
    if scope_type not in {"all", "watchlist", "favorites", "theme", "majors", "gold", "memes", "custom"}:
        scope_type = "all"
    payload = draft.get("asset_scope_payload")
    if scope_type == "custom" and not isinstance(payload, dict):
        payload = {"symbols": draft.get("custom_symbols", [])}
    elif scope_type == "theme" and not isinstance(payload, dict):
        payload = {
            "theme_name": draft.get("theme_name"),
            "theme_id": draft.get("theme_id"),
            "symbols": draft.get("theme_symbols", []),
        }
    if scope_type == "custom":
        symbols = sorted({str(item).strip().upper() for item in (payload or {}).get("symbols", []) if str(item).strip()})
        return scope_type, {"symbols": symbols}
    if scope_type == "theme":
        theme_name = str((payload or {}).get("theme_name") or "").strip()
        normalized: dict[str, Any] | None = {"theme_name": theme_name} if theme_name else None
        if normalized is not None:
            if (payload or {}).get("theme_id") is not None:
                normalized["theme_id"] = (payload or {}).get("theme_id")
            theme_symbols = sorted({str(item).strip().upper() for item in (payload or {}).get("symbols", []) if str(item).strip()})
            if theme_symbols:
                normalized["symbols"] = theme_symbols
        return scope_type, normalized
    return scope_type, None


def _scope_label(scope: str, *, language_code: str) -> str:
    language = normalize_language(language_code)
    mapping = {
        "watchlist": ("👀 Watchlist", "👀 Watchlist"),
        "favorites": ("⭐ Favorites", "⭐ Избранное"),
        "majors": ("🪙 Majors", "🪙 Мейджоры"),
        "memes": ("🎭 Memes", "🎭 Мемы"),
        "gold": ("🥇 Gold", "🥇 Золото"),
        "custom_symbols": ("✍️ Custom Symbols", "✍️ Свои символы"),
        "all_enabled": ("🌐 All Enabled", "🌐 Всё включённое"),
    }
    english, russian = mapping.get(scope, ("🌐 All Enabled", "🌐 Всё включённое"))
    return russian if language == "ru" else english


def _direction_label(direction: str, *, language_code: str) -> str:
    language = normalize_language(language_code)
    mapping = {
        "long": ("🟢 Long", "🟢 Long"),
        "short": ("🔴 Short", "🔴 Short"),
        "both": ("↔️ Both", "↔️ Оба направления"),
    }
    english, russian = mapping.get(direction, mapping["both"])
    return russian if language == "ru" else english


def _session_label(session: str, *, language_code: str) -> str:
    language = normalize_language(language_code)
    mapping = {
        "asia": ("🌏 Asia", "🌏 Азия"),
        "london": ("🇬🇧 London", "🇬🇧 Лондон"),
        "new_york": ("🇺🇸 New York", "🇺🇸 Нью-Йорк"),
        "overlap": ("🔄 Overlap", "🔄 Перекрытие"),
        "all_day": ("🕓 All Day", "🕓 Весь день"),
    }
    english, russian = mapping.get(session, mapping["all_day"])
    return russian if language == "ru" else english


def _noise_label(noise_level: str, *, language_code: str) -> str:
    language = normalize_language(language_code)
    mapping = {
        "minimal": ("🔕 Minimal", "🔕 Минимум"),
        "balanced": ("⚖️ Balanced", "⚖️ Баланс"),
        "active": ("⚡ Active", "⚡ Активно"),
    }
    english, russian = mapping.get(noise_level, mapping["balanced"])
    return russian if language == "ru" else english


def _score_label(score_filter: str, *, language_code: str) -> str:
    language = normalize_language(language_code)
    mapping = {
        "all": ("All Signals", "Все сигналы"),
        "strong": ("Strong Only", "Только сильные"),
        "high": ("High Score", "Высокий score"),
        "elite": ("Elite Only", "Только elite"),
    }
    english, russian = mapping.get(score_filter, mapping["all"])
    return russian if language == "ru" else english


def _delivery_profile_label(profile_key: str, *, language_code: str) -> str:
    language = normalize_language(language_code)
    mapping = {
        "focused_instant": ("⚡ Focused Instant", "⚡ Точный instant"),
        "balanced": ("⚖️ Balanced", "⚖️ Баланс"),
        "watchlist_priority": ("👀 Watchlist First", "👀 Приоритет watchlist"),
        "quiet_digest": ("🌙 Quiet Digest", "🌙 Тихая сводка"),
    }
    english, russian = mapping.get(profile_key, mapping["balanced"])
    return russian if language == "ru" else english


def _builder_progress(step: str, *, language_code: str) -> str:
    labels = _setup_step_labels(language_code)
    order = ("name", "scope", "strategies", "timeframes", "direction", "session", "selectivity", "delivery", "review")
    index = order.index(step) + 1 if step in order else len(order)
    if normalize_language(language_code) == "ru":
        return f"Шаг {index}/{len(order)} • {labels.get(step, 'Сетап')}"
    return f"Step {index}/{len(order)} • {labels.get(step, 'Setup')}"


def format_setup_builder_message(*, language_code: str, draft: dict[str, Any], step: str) -> str:
    language = normalize_language(language_code)
    name = _draft_name(draft)
    strategies = draft.get("selected_strategies") or []
    timeframes = draft.get("selected_timeframes") or []
    scope = str(draft.get("asset_scope") or "all_enabled")
    direction = str(draft.get("direction") or "both")
    session = str(draft.get("session") or "all_day")
    noise_level = str(draft.get("noise_level") or "balanced")
    score_filter = str(draft.get("score_filter") or "all")
    delivery_profile = str(draft.get("delivery_profile") or "balanced")
    strategy_names = [
        _SETUP_STRATEGY_LABELS.get(item, (item, item))[0 if language == "en" else 1]
        for item in strategies[:3]
    ]
    summary_lines = [
        f"{'Name' if language == 'en' else 'Название'}: <b>{escape_html(name)}</b>",
        f"{'Scope' if language == 'en' else 'Охват'}: <b>{escape_html(_scope_label(scope, language_code=language))}</b>",
        f"{'Strategies' if language == 'en' else 'Стратегии'}: <b>{escape_html(', '.join(strategy_names) or ('Not set' if language == 'en' else 'Не выбрано'))}</b>",
        f"{'Timeframes' if language == 'en' else 'Таймфреймы'}: <b>{escape_html('/'.join(timeframes) or ('Not set' if language == 'en' else 'Не выбрано'))}</b>",
        f"{'Direction' if language == 'en' else 'Направление'}: <b>{escape_html(_direction_label(direction, language_code=language))}</b>",
        f"{'Session' if language == 'en' else 'Сессия'}: <b>{escape_html(_session_label(session, language_code=language))}</b>",
        f"{'Selectivity' if language == 'en' else 'Отбор'}: <b>{escape_html(_noise_label(noise_level, language_code=language))} • {escape_html(_score_label(score_filter, language_code=language))}</b>",
        f"{'Delivery' if language == 'en' else 'Доставка'}: <b>{escape_html(_delivery_profile_label(delivery_profile, language_code=language))}</b>",
    ]
    if language == "ru":
        helper = {
            "name": "Задай имя, чтобы этот режим потом было легко запускать в один тап.",
            "scope": "Выбери, на какой набор активов будет смотреть этот сетап.",
            "strategies": "Отметь стратегии, которые должны войти в этот режим.",
            "timeframes": "Выбери таймфреймы. Остальные будут скрыты для этого сетапа.",
            "direction": "Определи, нужен long, short или оба направления.",
            "session": "Ограничь поток по рыночной сессии, если нужен конкретный ритм.",
            "selectivity": "Уровень шума и порог качества определяют, насколько строгим будет отбор.",
            "delivery": "Это стартовый профиль доставки. Дальше его можно тонко подкрутить в Правилах доставки.",
            "review": "Проверь итог и сохрани сетап. Можно сразу активировать его после сохранения.",
        }.get(step, "Проверь настройки и двигайся дальше.")
    else:
        helper = {
            "name": "Give this mode a name so you can launch it again in one tap.",
            "scope": "Choose which asset universe this setup should focus on.",
            "strategies": "Select the strategies that belong to this mode.",
            "timeframes": "Pick the timeframes you want. The rest will be hidden for this setup.",
            "direction": "Choose long, short, or both directions.",
            "session": "Limit the flow to the market session that fits your rhythm.",
            "selectivity": "Noise level and score floor control how selective this setup becomes.",
            "delivery": "This is the starting delivery profile. You can fine-tune it later in Delivery Rules.",
            "review": "Check the final summary, then save it or save and activate it.",
        }.get(step, "Review the current configuration and continue.")
    lines = [
        f"<b>🧩 {'Create Setup' if language == 'en' else 'Создать сетап'}</b>",
        "",
        _builder_progress(step, language_code=language),
        "",
        helper,
        "",
        *summary_lines,
    ]
    if step == "scope" and scope == "custom_symbols":
        custom_symbols = ", ".join(str(item) for item in draft.get("custom_symbols", []) if str(item))
        lines.extend([
            "",
            f"{'Custom symbols' if language == 'en' else 'Свои символы'}: <b>{escape_html(custom_symbols or ('Not set' if language == 'en' else 'Не заданы'))}</b>",
        ])
    return "\n".join(lines)


def _toggle_label(label: str, active: bool) -> str:
    return f"✅ {label}" if active else label


def build_setup_builder_keyboard(
    *,
    language_code: str,
    draft: dict[str, Any],
    step: str,
    parent_callback_data: str = "main:setups",
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows: list[list[dict[str, object]]] = []
    if step == "name":
        rows = [[
            {
                "text": "✏️ Edit Name" if language == "en" else "✏️ Переименовать",
                "callback_data": "ux:setupbuilder:prompt:name",
            },
            {
                "text": "➡️ Continue" if language == "en" else "➡️ Дальше",
                "callback_data": "ux:setupbuilder:next",
            },
        ]]
    elif step == "scope":
        options = [
            ("watchlist", _scope_label("watchlist", language_code=language)),
            ("favorites", _scope_label("favorites", language_code=language)),
            ("majors", _scope_label("majors", language_code=language)),
            ("memes", _scope_label("memes", language_code=language)),
            ("gold", _scope_label("gold", language_code=language)),
            ("custom_symbols", _scope_label("custom_symbols", language_code=language)),
            ("all_enabled", _scope_label("all_enabled", language_code=language)),
        ]
        selected = str(draft.get("asset_scope") or "all_enabled")
        for idx in range(0, len(options), 2):
            row = []
            for value, label in options[idx:idx + 2]:
                row.append({"text": _toggle_label(label, selected == value), "callback_data": f"ux:setupbuilder:set:scope:{value}"})
            rows.append(row)
        if selected == "custom_symbols":
            rows.append([{"text": "✏️ Edit Symbols" if language == "en" else "✏️ Ввести символы", "callback_data": "ux:setupbuilder:prompt:symbols"}])
        rows.append([{"text": "➡️ Continue" if language == "en" else "➡️ Дальше", "callback_data": "ux:setupbuilder:next"}])
    elif step == "strategies":
        strategies = draft.get("selected_strategies") or []
        items = [
            (key, _SETUP_STRATEGY_LABELS[key][0 if language == "en" else 1])
            for key in (
                "breakout",
                "trend_pullback",
                "rsi_bollinger_mr",
                "rsi_bollinger_touch",
                "vwap",
                "false_breakout",
                "rsi",
                "rsi_divergence",
                "ekek",
                "bollinger",
                "gold_breakout",
                "gold_pullback",
                "gold_liquidity",
            )
        ]
        for idx in range(0, len(items), 2):
            row = []
            for key, label in items[idx:idx + 2]:
                row.append({"text": _toggle_label(label, key in strategies), "callback_data": f"ux:setupbuilder:toggle:strategy:{key}"})
            rows.append(row)
        rows.append([{"text": "➡️ Continue" if language == "en" else "➡️ Дальше", "callback_data": "ux:setupbuilder:next"}])
    elif step == "timeframes":
        selected = set(draft.get("selected_timeframes") or [])
        for idx in range(0, len(_SETUP_TIMEFRAMES), 2):
            row = []
            for timeframe in _SETUP_TIMEFRAMES[idx:idx + 2]:
                row.append({"text": _toggle_label(timeframe, timeframe in selected), "callback_data": f"ux:setupbuilder:toggle:timeframe:{timeframe}"})
            rows.append(row)
        rows.append([{"text": "➡️ Continue" if language == "en" else "➡️ Дальше", "callback_data": "ux:setupbuilder:next"}])
    elif step == "direction":
        rows = [
            [
                {"text": _toggle_label(_direction_label("long", language_code=language), draft.get("direction") == "long"), "callback_data": "ux:setupbuilder:set:direction:long"},
                {"text": _toggle_label(_direction_label("short", language_code=language), draft.get("direction") == "short"), "callback_data": "ux:setupbuilder:set:direction:short"},
            ],
            [
                {"text": _toggle_label(_direction_label("both", language_code=language), draft.get("direction") == "both"), "callback_data": "ux:setupbuilder:set:direction:both"},
            ],
            [{"text": "➡️ Continue" if language == "en" else "➡️ Дальше", "callback_data": "ux:setupbuilder:next"}],
        ]
    elif step == "session":
        options = ("asia", "london", "new_york", "overlap", "all_day")
        selected = str(draft.get("session") or "all_day")
        for idx in range(0, len(options), 2):
            row = []
            for value in options[idx:idx + 2]:
                row.append({"text": _toggle_label(_session_label(value, language_code=language), value == selected), "callback_data": f"ux:setupbuilder:set:session:{value}"})
            rows.append(row)
        rows.append([{"text": "➡️ Continue" if language == "en" else "➡️ Дальше", "callback_data": "ux:setupbuilder:next"}])
    elif step == "selectivity":
        noise = str(draft.get("noise_level") or "balanced")
        score = str(draft.get("score_filter") or "all")
        rows = [
            [
                {"text": _toggle_label(_noise_label("minimal", language_code=language), noise == "minimal"), "callback_data": "ux:setupbuilder:set:noise:minimal"},
                {"text": _toggle_label(_noise_label("balanced", language_code=language), noise == "balanced"), "callback_data": "ux:setupbuilder:set:noise:balanced"},
            ],
            [
                {"text": _toggle_label(_noise_label("active", language_code=language), noise == "active"), "callback_data": "ux:setupbuilder:set:noise:active"},
            ],
            [
                {"text": _toggle_label(_score_label("all", language_code=language), score == "all"), "callback_data": "ux:setupbuilder:set:score:all"},
                {"text": _toggle_label(_score_label("strong", language_code=language), score == "strong"), "callback_data": "ux:setupbuilder:set:score:strong"},
            ],
            [
                {"text": _toggle_label(_score_label("high", language_code=language), score == "high"), "callback_data": "ux:setupbuilder:set:score:high"},
                {"text": _toggle_label(_score_label("elite", language_code=language), score == "elite"), "callback_data": "ux:setupbuilder:set:score:elite"},
            ],
            [{"text": "➡️ Continue" if language == "en" else "➡️ Дальше", "callback_data": "ux:setupbuilder:next"}],
        ]
    elif step == "delivery":
        selected = str(draft.get("delivery_profile") or "balanced")
        for value in ("focused_instant", "balanced", "watchlist_priority", "quiet_digest"):
            rows.append([{"text": _toggle_label(_delivery_profile_label(value, language_code=language), value == selected), "callback_data": f"ux:setupbuilder:set:delivery:{value}"}])
        rows.append([{"text": "➡️ Review" if language == "en" else "➡️ Проверить", "callback_data": "ux:setupbuilder:next"}])
    elif step == "review":
        rows = [[
            {"text": "💾 Save" if language == "en" else "💾 Сохранить", "callback_data": "ux:setupbuilder:save:save"},
            {"text": "▶️ Save & Activate" if language == "en" else "▶️ Сохранить и включить", "callback_data": "ux:setupbuilder:save:activate"},
        ]]
    rows.append([
        {"text": "✖️ Cancel" if language == "en" else "✖️ Отмена", "callback_data": "ux:setupbuilder:cancel"},
        {"text": "◀️ Back" if language == "en" else "◀️ Назад", "callback_data": "ux:setupbuilder:back"},
    ])
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data))
    return {"inline_keyboard": rows}


def format_custom_filters_hub_message(
    *,
    language_code: str,
    current_summary: str,
    active_setup_name: str | None,
) -> str:
    language = normalize_language(language_code)
    if language == "ru":
        return (
            "<b>✨ Детальные фильтры</b>\n\n"
            "Точная настройка текущего потока без путаницы с сохранёнными сетапами.\n\n"
            f"Активный режим: <b>{escape_html(active_setup_name or 'Адаптивный')}</b>\n"
            f"Сейчас: <b>{escape_html(current_summary)}</b>\n\n"
            "Здесь меняется текущий поток. Сохрани его как сетап отдельно, если захочешь использовать снова."
        )
    return (
        "<b>✨ Custom Filters</b>\n\n"
        "Fine-tune your current flow without mixing it up with saved setups.\n\n"
        f"Active mode: <b>{escape_html(active_setup_name or 'Adaptive')}</b>\n"
        f"Current profile: <b>{escape_html(current_summary)}</b>\n\n"
        "Changes here affect your active flow. Save them as a setup separately if you want to reuse them."
    )


def build_custom_filters_hub_keyboard(
    *,
    language_code: str,
    back_callback_data: str | None = None,
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [
        [
            {"text": "🎯 Quick Filters" if language == "en" else "🎯 Быстрые фильтры", "callback_data": "ux:quickfiltershub"},
            {"text": "🔕 Noise Level" if language == "en" else "🔕 Уровень шума", "callback_data": "ux:noisehub"},
        ],
        [
            {"text": "📊 Score Filter" if language == "en" else "📊 Порог качества", "callback_data": "ux:scorehub"},
            {"text": "🕒 Session" if language == "en" else "🕒 Сессия", "callback_data": "ux:sessionhub"},
        ],
        [
            {"text": "📬 Delivery Rules" if language == "en" else "📬 Правила доставки", "callback_data": "ux:deliveryrules"},
            {"text": "🚫 Hide & Mute" if language == "en" else "🚫 Скрыть и приглушить", "callback_data": "ux:hidemute"},
        ],
        [{"text": "💾 Save Current" if language == "en" else "💾 Сохранить текущее", "callback_data": "ux:setup:savecurrent"}],
    ]
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data))
    return {"inline_keyboard": rows}


def format_gold_wizard_message(*, language_code: str, draft: dict[str, Any], step: str) -> str:
    language = normalize_language(language_code)
    mode = str(draft.get("mode") or "balanced")
    direction = str(draft.get("direction") or "both")
    tempo = str(draft.get("tempo") or "balanced")
    session = str(draft.get("session") or "all")
    delivery = str(draft.get("delivery") or "instant")
    followups = bool(draft.get("followups", True))
    mode_label = {"macro": ("🧭 Macro", "🧭 Макро"), "balanced": ("⚖️ Balanced", "⚖️ Баланс"), "reactive": ("⚡ Reactive", "⚡ Реактивно")}
    tempo_label = {"fast": ("⚡ 5m/15m", "⚡ 5м/15м"), "balanced": ("🎯 15m/1h", "🎯 15м/1ч"), "macro": ("🕯 1h/4h", "🕯 1ч/4ч")}
    delivery_label = {"instant": ("⚡ Instant", "⚡ Сразу"), "digest": ("📦 Digest", "📦 Сводкой"), "quiet": ("🌙 Quiet", "🌙 Тихо")}
    current_mode = mode_label.get(mode, mode_label["balanced"])[0 if language == "en" else 1]
    current_tempo = tempo_label.get(tempo, tempo_label["balanced"])[0 if language == "en" else 1]
    current_delivery = delivery_label.get(delivery, delivery_label["instant"])[0 if language == "en" else 1]
    helper_map = {
        "mode": ("Choose how reactive the gold flow should be.", "Выбери, насколько быстрым должен быть поток по золоту."),
        "direction": ("Set the preferred direction for XAUUSD ideas.", "Задай предпочитаемое направление для XAUUSD."),
        "tempo": ("Pick the gold pace and timeframe rhythm.", "Выбери темп и ритм таймфреймов для золота."),
        "session": ("Focus on the session that matters most for your gold desk.", "Сфокусируйся на той сессии, которая важнее всего для Gold Desk."),
        "followups": ("Decide whether gold follow-ups should stay in the flow.", "Реши, нужны ли follow-up по золоту в этом потоке."),
        "delivery": ("Choose how gold setups should reach you.", "Выбери, как золотые сетапы должны доходить до тебя."),
        "review": ("Review the gold flow before applying it.", "Проверь Gold flow перед применением."),
    }
    helper = helper_map.get(step, ("", ""))[0 if language == "en" else 1]
    on_label = "On" if language == "en" else "Вкл"
    off_label = "Off" if language == "en" else "Выкл"
    session_label = _session_label("all_day" if session == "all" else session, language_code=language)
    lines = [
        f"<b>🥇 {'Gold Setup Wizard' if language == 'en' else 'Мастер Gold Setup'}</b>",
        "",
        helper,
        "",
        f"{'Mode' if language == 'en' else 'Режим'}: <b>{escape_html(current_mode)}</b>",
        f"{'Direction' if language == 'en' else 'Направление'}: <b>{escape_html(_direction_label(direction, language_code=language))}</b>",
        f"{'Tempo' if language == 'en' else 'Темп'}: <b>{escape_html(current_tempo)}</b>",
        f"{'Session' if language == 'en' else 'Сессия'}: <b>{escape_html(session_label)}</b>",
        f"{'Follow-ups' if language == 'en' else 'Follow-up'}: <b>{on_label if followups else off_label}</b>",
        f"{'Delivery' if language == 'en' else 'Доставка'}: <b>{escape_html(current_delivery)}</b>",
    ]
    return "\n".join(lines)


def build_gold_wizard_keyboard(
    *,
    language_code: str,
    draft: dict[str, Any],
    step: str,
    back_callback_data: str | None = "ux:goldhub",
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows: list[list[dict[str, object]]] = []
    if step == "mode":
        rows = [[
            {"text": _toggle_label("🧭 Macro" if language == "en" else "🧭 Макро", draft.get("mode") == "macro"), "callback_data": "ux:goldwizard:set:mode:macro"},
            {"text": _toggle_label("⚖️ Balanced" if language == "en" else "⚖️ Баланс", draft.get("mode") == "balanced"), "callback_data": "ux:goldwizard:set:mode:balanced"},
        ], [
            {"text": _toggle_label("⚡ Reactive" if language == "en" else "⚡ Реактивно", draft.get("mode") == "reactive"), "callback_data": "ux:goldwizard:set:mode:reactive"},
        ]]
    elif step == "direction":
        rows = [[
            {"text": _toggle_label(_direction_label("long", language_code=language), draft.get("direction") == "long"), "callback_data": "ux:goldwizard:set:direction:long"},
            {"text": _toggle_label(_direction_label("short", language_code=language), draft.get("direction") == "short"), "callback_data": "ux:goldwizard:set:direction:short"},
        ], [
            {"text": _toggle_label(_direction_label("both", language_code=language), draft.get("direction") == "both"), "callback_data": "ux:goldwizard:set:direction:both"},
        ]]
    elif step == "tempo":
        rows = [[
            {"text": _toggle_label("⚡ 5m/15m", draft.get("tempo") == "fast"), "callback_data": "ux:goldwizard:set:tempo:fast"},
            {"text": _toggle_label("🎯 15m/1h", draft.get("tempo") == "balanced"), "callback_data": "ux:goldwizard:set:tempo:balanced"},
        ], [
            {"text": _toggle_label("🕯 1h/4h", draft.get("tempo") == "macro"), "callback_data": "ux:goldwizard:set:tempo:macro"},
        ]]
    elif step == "session":
        rows = [[
            {"text": _toggle_label("🌍 All Day" if language == "en" else "🌍 Весь день", draft.get("session") == "all"), "callback_data": "ux:goldwizard:set:session:all"},
            {"text": _toggle_label("🇬🇧 London", draft.get("session") == "london"), "callback_data": "ux:goldwizard:set:session:london"},
        ], [
            {"text": _toggle_label("🇺🇸 New York", draft.get("session") == "new_york"), "callback_data": "ux:goldwizard:set:session:new_york"},
        ]]
    elif step == "followups":
        rows = [[
            {"text": _toggle_label("🔄 On" if language == "en" else "🔄 Вкл", bool(draft.get("followups", True))), "callback_data": "ux:goldwizard:set:followups:on"},
            {"text": _toggle_label("🚫 Off" if language == "en" else "🚫 Выкл", not bool(draft.get("followups", True))), "callback_data": "ux:goldwizard:set:followups:off"},
        ]]
    elif step == "delivery":
        rows = [[
            {"text": _toggle_label("⚡ Instant", draft.get("delivery") == "instant"), "callback_data": "ux:goldwizard:set:delivery:instant"},
            {"text": _toggle_label("📦 Digest", draft.get("delivery") == "digest"), "callback_data": "ux:goldwizard:set:delivery:digest"},
        ], [
            {"text": _toggle_label("🌙 Quiet", draft.get("delivery") == "quiet"), "callback_data": "ux:goldwizard:set:delivery:quiet"},
        ]]
    elif step == "review":
        rows = [[{"text": "▶️ Apply Gold Flow" if language == "en" else "▶️ Применить Gold flow", "callback_data": "ux:goldwizard:apply"}]]
    if step != "review":
        rows.append([{"text": "➡️ Continue" if language == "en" else "➡️ Дальше", "callback_data": "ux:goldwizard:next"}])
    rows.append([
        {"text": "✖️ Cancel" if language == "en" else "✖️ Отмена", "callback_data": "ux:goldwizard:cancel"},
        {"text": "◀️ Back" if language == "en" else "◀️ Назад", "callback_data": "ux:goldwizard:back"},
    ])
    rows.extend(_footer_rows(language_code=language))
    return {"inline_keyboard": rows}
