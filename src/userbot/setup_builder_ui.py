from __future__ import annotations

from typing import Any

from src.core.utils import escape_html
from src.localization import normalize_language
from src.userbot.personalization import asset_scope_summary, normalize_asset_scope_payload, normalize_asset_scope_type


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
        "custom": ("✍️ Custom Selection", "✍️ Свой выбор"),
    }
    english, russian = mapping.get(scope, mapping["all"])
    return russian if language == "ru" else english


def _draft_scope_state(draft: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    scope_type = normalize_asset_scope_type(draft.get("asset_scope_type") or draft.get("asset_scope"))
    raw_payload = draft.get("asset_scope_payload")
    if scope_type == "custom" and not raw_payload:
        raw_payload = {"symbols": draft.get("custom_symbols", [])}
    elif scope_type == "theme" and not raw_payload:
        raw_payload = {
            "theme_name": draft.get("theme_name"),
            "theme_id": draft.get("theme_id"),
            "symbols": draft.get("theme_symbols", []),
        }
    return scope_type, normalize_asset_scope_payload(scope_type, raw_payload)


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
        "high": ("High Score", "Высокий порог"),
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
    scope_type, scope_payload = _draft_scope_state(draft)
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
        f"{'Scope' if language == 'en' else 'Охват'}: <b>{escape_html(asset_scope_summary(scope_type, scope_payload, language_code=language))}</b>",
        f"{'Strategies' if language == 'en' else 'Стратегии'}: <b>{escape_html(', '.join(strategy_names) or ('Not set' if language == 'en' else 'Не выбрано'))}</b>",
        f"{'Timeframes' if language == 'en' else 'Таймфреймы'}: <b>{escape_html('/'.join(timeframes) or ('Not set' if language == 'en' else 'Не выбрано'))}</b>",
        f"{'Direction' if language == 'en' else 'Направление'}: <b>{escape_html(_direction_label(direction, language_code=language))}</b>",
        f"{'Session' if language == 'en' else 'Сессия'}: <b>{escape_html(_session_label(session, language_code=language))}</b>",
        f"{'Selectivity' if language == 'en' else 'Отбор'}: <b>{escape_html(_noise_label(noise_level, language_code=language))} • {escape_html(_score_label(score_filter, language_code=language))}</b>",
        f"{'Delivery' if language == 'en' else 'Доставка'}: <b>{escape_html(_delivery_profile_label(delivery_profile, language_code=language))}</b>",
    ]
    if language == "ru":
        helper = {
            "name": "Дай этому режиму понятное имя, чтобы потом запускать его в один тап.",
            "scope": "Выбери рынок для этого сетапа: все монеты, watchlist, избранное, тема или свой список.",
            "strategies": "Отметь стратегии, которые должны войти в этот режим.",
            "timeframes": "Выбери таймфреймы. Остальные будут скрыты для этого сетапа.",
            "direction": "Определи направление: long, short или оба.",
            "session": "Ограничь поток по торговой сессии, если нужен конкретный ритм.",
            "selectivity": "Уровень шума и порог качества определяют, насколько строгим будет отбор.",
            "delivery": "Это стартовый профиль доставки. Потом его можно подкрутить в правилах доставки.",
            "review": "Проверь итог и сохрани сетап. При желании можно сразу активировать его.",
        }.get(step, "Проверь настройки и двигайся дальше.")
    else:
        helper = {
            "name": "Give this mode a clear name so you can launch it again in one tap.",
            "scope": "Choose whether this setup tracks all coins, your watchlist, favorites, a saved set, or a custom list.",
            "strategies": "Select the strategies that belong to this mode.",
            "timeframes": "Pick the timeframes you want. The rest will stay hidden for this setup.",
            "direction": "Choose long, short, or both directions.",
            "session": "Limit the flow to the market session that fits your rhythm.",
            "selectivity": "Noise level and score floor control how selective this setup becomes.",
            "delivery": "This is the starting delivery profile. You can fine-tune it later in Delivery Rules.",
            "review": "Check the final summary, then save it or save and activate it.",
        }.get(step, "Review the current configuration and continue.")
    lines = [
        f"<b>🧩 {'Edit Setup' if draft.get('editing_setup_id') and language == 'en' else 'Create Setup' if language == 'en' else 'Изменить сетап' if draft.get('editing_setup_id') else 'Создать сетап'}</b>",
        "",
        _builder_progress(step, language_code=language),
        "",
        helper,
        "",
        *summary_lines,
    ]
    if step == "scope" and scope_type == "custom":
        custom_symbols = ", ".join(str(item) for item in (scope_payload or {}).get("symbols", []) if str(item))
        lines.extend([
            "",
            f"{'Custom symbols' if language == 'en' else 'Свои символы'}: <b>{escape_html(custom_symbols or ('Not set' if language == 'en' else 'Не заданы'))}</b>",
        ])
    if step == "scope" and scope_type == "theme":
        theme_name = str((scope_payload or {}).get("theme_name") or "").strip()
        lines.extend([
            "",
            f"{'Theme / Set' if language == 'en' else 'Тема / сет'}: <b>{escape_html(theme_name or ('Not selected' if language == 'en' else 'Не выбрано'))}</b>",
        ])
        if not draft.get("available_themes"):
            lines.append("No saved sets yet. Use All Coins, Watchlist, or Custom Selection for now." if language == "en" else "Сохранённых сетов пока нет. Пока можно выбрать все монеты, watchlist или свой набор.")
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
    scope_type, scope_payload = _draft_scope_state(draft)
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
            ("all", _scope_option_label("all", language_code=language)),
            ("watchlist", _scope_option_label("watchlist", language_code=language)),
            ("favorites", _scope_option_label("favorites", language_code=language)),
            ("theme", _scope_option_label("theme", language_code=language)),
            ("majors", _scope_option_label("majors", language_code=language)),
            ("gold", _scope_option_label("gold", language_code=language)),
            ("custom", _scope_option_label("custom", language_code=language)),
        ]
        for idx in range(0, len(options), 2):
            row = []
            for value, label in options[idx:idx + 2]:
                row.append({"text": _toggle_label(label, scope_type == value), "callback_data": f"ux:setupbuilder:set:scope:{value}"})
            rows.append(row)
        if scope_type == "theme":
            available_themes = [
                item for item in draft.get("available_themes", [])
                if isinstance(item, dict) and item.get("id") is not None and item.get("name")
            ]
            for idx in range(0, len(available_themes), 2):
                row = []
                for item in available_themes[idx:idx + 2]:
                    theme_id = int(item["id"])
                    theme_name = str(item["name"])
                    is_active = int((scope_payload or {}).get("theme_id") or 0) == theme_id
                    row.append(
                        {
                            "text": _toggle_label(theme_name, is_active),
                            "callback_data": f"ux:setupbuilder:set:theme:{theme_id}",
                        }
                    )
                rows.append(row)
        if scope_type == "custom":
            rows.append([
                {"text": "➕ Add Symbols" if language == "en" else "➕ Добавить", "callback_data": "ux:setupbuilder:prompt:symbols_add"},
                {"text": "➖ Remove Symbols" if language == "en" else "➖ Убрать", "callback_data": "ux:setupbuilder:prompt:symbols_remove"},
            ])
            rows.append([
                {"text": "🌐 Select All" if language == "en" else "🌐 Все монеты", "callback_data": "ux:setupbuilder:set:scope:all"},
                {"text": "🧹 Clear Selection" if language == "en" else "🧹 Очистить", "callback_data": "ux:setupbuilder:set:custom:clear"},
            ])
        if scope_type != "all":
            rows.append([{"text": "♻️ Reset to All" if language == "en" else "♻️ Сбросить на все", "callback_data": "ux:setupbuilder:set:scope:all"}])
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
        profile = str(draft.get("delivery_profile") or "balanced")
        rows = [
            [
                {"text": _toggle_label(_delivery_profile_label("focused_instant", language_code=language), profile == "focused_instant"), "callback_data": "ux:setupbuilder:set:delivery:focused_instant"},
                {"text": _toggle_label(_delivery_profile_label("balanced", language_code=language), profile == "balanced"), "callback_data": "ux:setupbuilder:set:delivery:balanced"},
            ],
            [
                {"text": _toggle_label(_delivery_profile_label("watchlist_priority", language_code=language), profile == "watchlist_priority"), "callback_data": "ux:setupbuilder:set:delivery:watchlist_priority"},
                {"text": _toggle_label(_delivery_profile_label("quiet_digest", language_code=language), profile == "quiet_digest"), "callback_data": "ux:setupbuilder:set:delivery:quiet_digest"},
            ],
            [{"text": "➡️ Continue" if language == "en" else "➡️ Дальше", "callback_data": "ux:setupbuilder:next"}],
        ]
    elif step == "review":
        rows = [
            [
                {"text": "💾 Save" if language == "en" else "💾 Сохранить", "callback_data": "ux:setupbuilder:save:keep"},
                {"text": "▶️ Save & Activate" if language == "en" else "▶️ Сохранить и включить", "callback_data": "ux:setupbuilder:save:activate"},
            ]
        ]
    rows.extend([
        [{"text": "◀️ Back" if language == "en" else "◀️ Назад", "callback_data": "ux:setupbuilder:back"}],
        [{"text": "✖️ Cancel" if language == "en" else "✖️ Отмена", "callback_data": "ux:setupbuilder:cancel"}],
    ])
    rows.extend(_footer_rows(language_code=language, back_callback_data=None))
    return {"inline_keyboard": rows}


def _scope_option_label(scope: str, *, language_code: str) -> str:
    language = normalize_language(language_code)
    mapping = {
        "all": ("🌐 All Coins", "🌐 Все монеты"),
        "watchlist": ("👀 Watchlist", "👀 Вотчлист"),
        "favorites": ("⭐ Favorites", "⭐ Избранное"),
        "theme": ("🎨 Theme / Set", "🎨 Тема / набор"),
        "majors": ("🪙 Majors", "🪙 Топ-монеты"),
        "gold": ("🥇 Gold Only", "🥇 Только золото"),
        "custom": ("✍️ Custom Selection", "✍️ Свой выбор"),
    }
    english, russian = mapping.get(scope, mapping["all"])
    return russian if language == "ru" else english


def _delivery_profile_label(profile_key: str, *, language_code: str) -> str:
    language = normalize_language(language_code)
    mapping = {
        "focused_instant": ("⚡ Focused Instant", "⚡ Точный instant"),
        "balanced": ("⚖️ Balanced", "⚖️ Баланс"),
        "watchlist_priority": ("👀 Watchlist First", "👀 Сначала вотчлист"),
        "quiet_digest": ("🌙 Quiet Digest", "🌙 Тихая сводка"),
    }
    english, russian = mapping.get(profile_key, mapping["balanced"])
    return russian if language == "ru" else english
