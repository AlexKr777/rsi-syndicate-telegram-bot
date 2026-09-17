from __future__ import annotations

from src.localization import normalize_language, ui_text
from src.userbot.navigation import (
    compare_callback,
    learn_callback,
    lifecycle_callback,
    main_callback,
    results_callback,
    strategy_callback,
)


def _selected_label(label: str, selected: bool) -> str:
    return f"✓ {label}" if selected else label


def _footer_rows(
    *,
    language_code: str,
    back_callback_data: str | None = None,
    home_callback_data: str = "ux:menu",
) -> list[list[dict[str, object]]]:
    language = normalize_language(language_code)
    if back_callback_data:
        return [[
            {"text": ui_text(language, "menu_back"), "callback_data": back_callback_data},
            {"text": ui_text(language, "menu_home"), "callback_data": home_callback_data},
        ]]
    return [[{"text": ui_text(language, "menu_home"), "callback_data": home_callback_data}]]


def build_help_inline_keyboard(
    *,
    language_code: str,
    back_callback_data: str | None = None,
    home_callback_data: str = "ux:menu",
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [
        [
            {"text": "🚀 Quick Start" if language != "ru" else "🚀 Быстрый старт", "callback_data": "ux:help:quick_start"},
            {"text": "🧾 Example Signal" if language != "ru" else "🧾 Пример сигнала", "callback_data": "ux:welcome:example"},
        ],
        [
            {"text": "📖 Read Signals" if language != "ru" else "📖 Как читать", "callback_data": "ux:welcome:read"},
            {"text": "🌙 No Signals?" if language != "ru" else "🌙 Нет сигналов?", "callback_data": "ux:help:no_signals"},
        ],
        [
            {"text": "⚖️ Classic vs PRO+", "callback_data": "ux:help:compare"},
            {"text": "💎 Access Basics" if language != "ru" else "💎 Доступ и trial", "callback_data": "ux:help:access"},
        ],
        [
            {"text": "🛡 Risk" if language != "ru" else "🛡 Риск", "callback_data": "ux:help:risk"},
            {"text": "🆘 Support" if language != "ru" else "🆘 Поддержка", "callback_data": "ux:help:support"},
        ],
        [
            {"text": "➕ More Topics" if language != "ru" else "➕ Ещё разделы", "callback_data": "ux:help:more"},
        ],
    ]
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data, home_callback_data=home_callback_data))
    return {"inline_keyboard": rows}


def build_help_more_inline_keyboard(
    *,
    language_code: str,
    back_callback_data: str | None = "main:help",
    home_callback_data: str = "ux:menu",
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [
        [
            {"text": "🔔 Notifications" if language != "ru" else "🔔 Уведомления", "callback_data": "ux:help:notifications"},
            {"text": "🤖 AI Explained" if language != "ru" else "🤖 Что делает AI", "callback_data": "ux:help:ai"},
        ],
        [
            {"text": "🥇 Gold Explained" if language != "ru" else "🥇 О золоте", "callback_data": "ux:help:gold"},
            {"text": "⌨️ Commands" if language != "ru" else "⌨️ Команды", "callback_data": "ux:help:commands"},
        ],
        [
            {"text": "📐 Methodology" if language != "ru" else "📐 Методология", "callback_data": "ux:help:results"},
            {"text": "🧾 Example Follow-up" if language != "ru" else "🧾 Пример follow-up", "callback_data": "ux:help:example_followup"},
        ],
    ]
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data, home_callback_data=home_callback_data))
    return {"inline_keyboard": rows}


def build_access_inline_keyboard(
    *,
    can_renew: bool,
    language_code: str,
    renew_label: str = "Renew now",
    back_callback_data: str | None = None,
    home_callback_data: str = "ux:menu",
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows: list[list[dict[str, object]]] = []
    referral_label = "🎁 Referral" if language != "ru" else "🎁 Рефералы"
    included_label = "💎 What's Included" if language != "ru" else "💎 Что входит"
    if can_renew:
        rows.append(
            [
                {"text": renew_label, "callback_data": "ux:renew"},
                {"text": included_label, "callback_data": "ux:help:access"},
            ]
        )
    else:
        rows.append([{"text": included_label, "callback_data": "ux:help:access"}])
    rows.extend(
        [
            [
                {"text": "⚖️ Classic vs PRO+", "callback_data": "ux:help:compare"},
                {"text": "🆘 Support" if language != "ru" else "🆘 Поддержка", "callback_data": "ux:help:support"},
            ],
            [
                {"text": referral_label, "callback_data": "ux:referral"},
                {"text": "❓ Help" if language != "ru" else "❓ Помощь", "callback_data": main_callback("help")},
            ],
        ]
    )
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data, home_callback_data=home_callback_data))
    return {"inline_keyboard": rows}


def build_status_inline_keyboard(
    *,
    language_code: str,
    back_callback_data: str | None = None,
    home_callback_data: str = "ux:menu",
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [
        [
            {"text": "🔔 Notifications" if language != "ru" else "🔔 Уведомления", "callback_data": "ux:deliveryhub"},
            {"text": "📊 Results" if language != "ru" else "📊 Результаты", "callback_data": "results:hub"},
        ],
        [
            {"text": "👀 Watchlist" if language != "ru" else "👀 Вотчлист", "callback_data": "ux:watchhub"},
            {"text": "⚙️ Settings" if language != "ru" else "⚙️ Настройки", "callback_data": "ux:settingshub"},
        ],
    ]
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data, home_callback_data=home_callback_data))
    return {"inline_keyboard": rows}


def build_watchlist_inline_keyboard(
    *,
    language_code: str,
    symbols: list[str],
    allow_remove: bool = True,
    back_callback_data: str | None = None,
    home_callback_data: str = "ux:menu",
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows: list[list[dict[str, object]]] = []
    for symbol in symbols:
        row: list[dict[str, object]] = [{"text": symbol, "callback_data": f"ux:watch:open:{symbol}"}]
        if allow_remove:
            row.append(
                {
                    "text": "➖ Remove" if language != "ru" else "➖ Убрать",
                    "callback_data": f"ux:watch:remove:{symbol}",
                }
            )
        rows.append(row)
    rows.extend(
        [
            [
                {"text": "🎨 Themes" if language != "ru" else "🎨 Темы", "callback_data": "ux:themes"},
                {"text": "💾 Save Set" if language != "ru" else "💾 Сохранить набор", "callback_data": "ux:theme:save"},
            ],
            [
                {"text": "🔎 Analyze" if language != "ru" else "🔎 Разобрать", "callback_data": "ux:analyze"},
            ],
        ]
    )
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data, home_callback_data=home_callback_data))
    return {"inline_keyboard": rows}


def build_analyze_symbol_inline_keyboard(
    *,
    language_code: str,
    symbols: list[str],
    back_callback_data: str | None = None,
    home_callback_data: str = "ux:menu",
) -> dict[str, object]:
    del symbols
    language = normalize_language(language_code)
    rows = [
        [
            {"text": "📘 AI Guide" if language != "ru" else "📘 AI-гайд", "callback_data": "learn:ai_guide"},
            {"text": "📡 Signals" if language != "ru" else "📡 Сигналы", "callback_data": main_callback("signals")},
        ],
        [
            {"text": "🥇 Gold Desk" if language != "ru" else "🥇 Золото", "callback_data": "ux:goldhub"},
        ],
    ]
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data, home_callback_data=home_callback_data))
    return {"inline_keyboard": rows}


def build_menu_hub_inline_keyboard(
    *,
    language_code: str,
    bot_kind: str = "premium",
    include_gold_button: bool = False,
    payment_label: str | None = None,
) -> dict[str, object]:
    del bot_kind, include_gold_button
    language = normalize_language(language_code)
    labels = (
        {
            "strong": "💥 Strong Setups",
            "watchlist": "👀 Watchlist",
            "ai": "🤖 AI Desk",
            "alerts": "🔔 Notifications",
            "strategies": "📈 Strategies",
            "results": "📊 Results",
            "workspace": "🧩 Workspace",
            "filters": "🎯 Filters",
            "settings": "⚙️ Settings",
            "access": "💎 My Access",
            "refresh": "🔄 Refresh",
            "referral": "🎁 Referral",
            "help": "❓ Help",
        }
        if language != "ru"
        else {
            "strong": "💥 Сильные сетапы",
            "watchlist": "👀 Вотчлист",
            "ai": "🤖 AI-разбор",
            "alerts": "🔔 Уведомления",
            "strategies": "📈 Стратегии",
            "results": "📊 Результаты",
            "workspace": "🧩 Профиль",
            "filters": "🎯 Фильтры",
            "settings": "⚙️ Настройки",
            "access": "💎 Мой доступ",
            "refresh": "🔄 Обновить",
            "referral": "🎁 Рефералы",
            "help": "❓ Помощь",
        }
    )
    rows = [
        [
            {"text": labels["strong"], "callback_data": "ux:signals:strong"},
            {"text": labels["watchlist"], "callback_data": "ux:watchhub"},
        ],
        [
            {"text": labels["ai"], "callback_data": main_callback("ai")},
            {"text": labels["alerts"], "callback_data": main_callback("alerts")},
        ],
        [
            {"text": labels["strategies"], "callback_data": main_callback("strategies")},
            {"text": labels["results"], "callback_data": main_callback("results")},
        ],
        [
            {"text": labels["workspace"], "callback_data": "ux:workspacehub"},
            {"text": labels["filters"], "callback_data": "ux:filtershub"},
        ],
        [
            {"text": labels["settings"], "callback_data": main_callback("settings")},
            {"text": labels["access"], "callback_data": main_callback("access")},
        ],
        [
            {"text": labels["refresh"], "callback_data": main_callback("today")},
            {"text": labels["help"], "callback_data": main_callback("help")},
        ],
    ]
    if payment_label:
        rows.append(
            [
                {"text": labels["referral"], "callback_data": "ux:referral"},
                {"text": payment_label, "callback_data": "ux:pay"},
            ]
        )
    else:
        rows.append([{"text": labels["referral"], "callback_data": "ux:referral"}])
    return {"inline_keyboard": rows}


def build_settings_center_keyboard(
    *,
    language_code: str,
    display_mode: str,
    active_workspace: str | None,
    has_saved_workspace: bool,
    back_callback_data: str | None = None,
    home_callback_data: str = "ux:menu",
) -> dict[str, object]:
    del active_workspace
    language = normalize_language(language_code)
    normalized_mode = "simple" if str(display_mode or "").strip().lower() == "simple" else "pro"
    rows = [
        [
            {"text": "🔔 Notifications" if language != "ru" else "🔔 Уведомления", "callback_data": "ux:deliveryhub"},
            {"text": "🎯 Filters" if language != "ru" else "🎯 Фильтры", "callback_data": "ux:filtershub"},
        ],
        [
            {"text": "📬 Delivery" if language != "ru" else "📬 Доставка", "callback_data": "ux:deliveryhub"},
            {"text": "🌙 Quiet Hours" if language != "ru" else "🌙 Тихие часы", "callback_data": "ux:deliveryhub"},
        ],
        [
            {"text": "🧩 Workspace" if language != "ru" else "🧩 Профиль", "callback_data": "ux:workspacehub"},
            {"text": "🌐 Language" if language != "ru" else "🌐 Язык", "callback_data": "ux:language:picker:settings"},
        ],
        [
            {"text": _selected_label("🖥 Simple" if language != "ru" else "🖥 Просто", normalized_mode == "simple"), "callback_data": "ux:display:simple"},
            {"text": _selected_label("🖥 Pro" if language != "ru" else "🖥 Pro", normalized_mode == "pro"), "callback_data": "ux:display:pro"},
        ],
        [
            {"text": "👀 Watchlist" if language != "ru" else "👀 Вотчлист", "callback_data": "ux:watchhub"},
            {"text": "🟢 Bot Status" if language != "ru" else "🟢 Статус бота", "callback_data": "ux:status"},
        ],
        [
            {
                "text": "💾 Save Current" if language != "ru" else "💾 Сохранить текущее",
                "callback_data": "ux:workspace:save" if not has_saved_workspace else "ux:workspace:apply:saved",
            },
            {"text": "🪄 Wizard" if language != "ru" else "🪄 Мастер", "callback_data": "ux:onboard:start"},
        ],
    ]
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data, home_callback_data=home_callback_data))
    return {"inline_keyboard": rows}


def build_workspace_center_keyboard(
    *,
    language_code: str,
    active_workspace: str | None,
    has_saved_workspace: bool,
    back_callback_data: str | None = None,
    home_callback_data: str = "ux:menu",
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [
        [
            {"text": _selected_label("⚡ Scalp" if language != "ru" else "⚡ Скальп", active_workspace == "scalp"), "callback_data": "ux:workspace:apply:scalp"},
            {"text": _selected_label("📈 Intraday" if language != "ru" else "📈 Интрадей", active_workspace == "intraday"), "callback_data": "ux:workspace:apply:intraday"},
        ],
        [
            {"text": _selected_label("🌊 Swing" if language != "ru" else "🌊 Свинг", active_workspace == "swing"), "callback_data": "ux:workspace:apply:swing"},
            {"text": _selected_label("🥇 Gold Focus" if language != "ru" else "🥇 Фокус на золоте", active_workspace == "gold_focus"), "callback_data": "ux:workspace:apply:gold_focus"},
        ],
        [
            {"text": _selected_label("🔕 Low Noise" if language != "ru" else "🔕 Мало шума", active_workspace == "low_noise"), "callback_data": "ux:workspace:apply:low_noise"},
            {"text": _selected_label("🚀 Aggressive" if language != "ru" else "🚀 Агрессивный", active_workspace == "aggressive"), "callback_data": "ux:workspace:apply:aggressive"},
        ],
        [
            {"text": "💾 Save Current" if language != "ru" else "💾 Сохранить текущее", "callback_data": "ux:workspace:save"},
            {"text": "📂 Saved" if language != "ru" else "📂 Сохранённый", "callback_data": "ux:workspace:apply:saved"},
        ],
        [
            {"text": "🪄 Wizard" if language != "ru" else "🪄 Мастер", "callback_data": "ux:onboard:start"},
        ],
    ]
    if not has_saved_workspace:
        rows[3][1]["text"] = "📂 Saved" if language != "ru" else "📂 Сохранённый"
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data, home_callback_data=home_callback_data))
    return {"inline_keyboard": rows}


def build_results_hub_keyboard(
    *,
    is_admin: bool,
    strategy_code: str | None = None,
    language_code: str = "en",
) -> dict[str, object]:
    language = normalize_language(language_code)
    lifecycle_hub_callback = f"strategy:lifecycle:{strategy_code}" if strategy_code else lifecycle_callback("hub")
    back_callback = strategy_callback("open", strategy_code) if strategy_code else main_callback("today")
    rows = [
        [
            {"text": "📅 Daily" if language != "ru" else "📅 День", "callback_data": "ux:recap:daily"},
            {"text": "🗓 Weekly" if language != "ru" else "🗓 Неделя", "callback_data": "ux:recap:weekly"},
        ],
        [
            {"text": "🔄 Lifecycle" if language != "ru" else "🔄 Жизненный цикл", "callback_data": lifecycle_hub_callback},
            {"text": "✨ Fresh Signals" if language != "ru" else "✨ Свежие сигналы", "callback_data": "ux:signals:fresh"},
        ],
        [
            {"text": "📈 Strategy Results" if language != "ru" else "📈 Результаты стратегий", "callback_data": compare_callback("hub")},
            {"text": "🟢 Bot Status" if language != "ru" else "🟢 Статус бота", "callback_data": "ux:status"},
        ],
    ]
    if is_admin:
        rows.append([{"text": "🧾 Admin Stats" if language != "ru" else "🧾 Админ-стата", "callback_data": results_callback("admin")}])
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback, home_callback_data=main_callback("today")))
    return {"inline_keyboard": rows}


def build_compare_hub_keyboard(*, is_admin: bool, language_code: str = "en") -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [
        [
            {"text": "📈 Trend" if language != "ru" else "📈 Тренд", "callback_data": compare_callback("trend")},
            {"text": "↔️ Range" if language != "ru" else "↔️ Диапазон", "callback_data": compare_callback("range")},
        ],
        [
            {"text": "🥇 Gold" if language != "ru" else "🥇 Золото", "callback_data": compare_callback("gold")},
            {"text": "🔕 Low Noise" if language != "ru" else "🔕 Мало шума", "callback_data": compare_callback("lownoise")},
        ],
        [
            {"text": "⏱ Timeframe" if language != "ru" else "⏱ Таймфрейм", "callback_data": compare_callback("timeframe")},
            {"text": "🪙 Asset Type" if language != "ru" else "🪙 Тип актива", "callback_data": compare_callback("assets")},
        ],
        [
            {"text": "🧠 All" if language != "ru" else "🧠 Все", "callback_data": compare_callback("all")},
            {"text": "📊 Results" if language != "ru" else "📊 Результаты", "callback_data": results_callback("hub")},
        ],
    ]
    if is_admin:
        rows.append([{"text": "🧾 Admin Stats" if language != "ru" else "🧾 Админ-стата", "callback_data": "compare:admin"}])
    rows.extend(_footer_rows(language_code=language, back_callback_data=main_callback("strategies"), home_callback_data=main_callback("today")))
    return {"inline_keyboard": rows}


def build_learn_hub_keyboard(*, language_code: str = "en") -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [
        [
            {"text": "📡 Signals Guide" if language != "ru" else "📡 Гид по сигналам", "callback_data": learn_callback("signals")},
            {"text": "🧠 Strategy Guides" if language != "ru" else "🧠 Гиды по стратегиям", "callback_data": learn_callback("guides")},
        ],
        [
            {"text": "🛡 Risk Basics" if language != "ru" else "🛡 Основы риска", "callback_data": learn_callback("risk")},
            {"text": "👀 Read a Signal" if language != "ru" else "👀 Как читать сигнал", "callback_data": learn_callback("read_signal")},
        ],
        [
            {"text": "🤖 AI Guide" if language != "ru" else "🤖 AI-гайд", "callback_data": learn_callback("ai_guide")},
            {"text": "🥇 Gold Guide" if language != "ru" else "🥇 Гид по золоту", "callback_data": learn_callback("gold")},
        ],
        [
            {"text": "🔔 Alerts Guide" if language != "ru" else "🔔 Гид по алертам", "callback_data": "ux:deliveryhub"},
            {"text": "✨ What Changed" if language != "ru" else "✨ Что изменилось", "callback_data": learn_callback("what_changed")},
        ],
    ]
    rows.extend(_footer_rows(language_code=language, back_callback_data=main_callback("today"), home_callback_data=main_callback("today")))
    return {"inline_keyboard": rows}


def build_section_hub_keyboard(
    *,
    language_code: str,
    section: str,
    include_gold_button: bool,
    premium: bool,
    direct_delivery_enabled: bool = False,
    followup_delivery_enabled: bool = False,
    gold_alerts_enabled: bool = False,
    snoozed: bool = False,
    quiet_hours_active: bool = False,
    back_callback_data: str | None = None,
    home_callback_data: str = "ux:menu",
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows: list[list[dict[str, object]]] = []
    if section == "ai":
        rows = [
            [
                {"text": "🔎 Analyze" if language != "ru" else "🔎 Разобрать", "callback_data": "ux:analyze"},
                {"text": "📘 AI Guide" if language != "ru" else "📘 AI-гайд", "callback_data": "learn:ai_guide"},
            ],
            [
                {"text": "📡 Signals" if language != "ru" else "📡 Сигналы", "callback_data": main_callback("signals")},
                {"text": "🥇 Gold Desk" if language != "ru" else "🥇 Золото", "callback_data": "ux:goldhub"},
            ],
        ]
    elif section == "signals":
        rows = [
            [
                {"text": "⚡ Latest Signals" if language != "ru" else "⚡ Последние сигналы", "callback_data": "ux:signals:recent"},
                {"text": "💥 Strong Setups" if language != "ru" else "💥 Сильные сетапы", "callback_data": "ux:signals:strong"},
            ],
            [
                {"text": "🔎 Analyze" if language != "ru" else "🔎 Разобрать", "callback_data": main_callback("ai")},
                {"text": "📅 Daily Recap" if language != "ru" else "📅 Итоги дня", "callback_data": "ux:recap:daily"},
            ],
            [
                {"text": "✨ Fresh Signals" if language != "ru" else "✨ Свежие сигналы", "callback_data": "ux:signals:fresh"},
                {"text": "🔄 Lifecycle" if language != "ru" else "🔄 Жизненный цикл", "callback_data": "lifecycle:hub"},
            ],
            [
                {"text": "⚖️ Compare" if language != "ru" else "⚖️ Сравнить", "callback_data": "compare:hub"},
                {"text": "🎯 Filters" if language != "ru" else "🎯 Фильтры", "callback_data": "ux:filtershub"},
            ],
        ]
    elif section == "watchlists":
        rows = [
            [
                {"text": "⭐ Favorites" if language != "ru" else "⭐ Избранное", "callback_data": "ux:watchlist"},
                {"text": "🎨 Themes" if language != "ru" else "🎨 Темы", "callback_data": "ux:themes"},
            ],
            [
                {"text": "💾 Save Set" if language != "ru" else "💾 Сохранить набор", "callback_data": "ux:theme:save"},
                {
                    "text": "🔔 List Alerts" if language != "ru" else "🔔 Уведомления списка",
                    "callback_data": "ux:deliveryruleview:watchlist_matches",
                },
            ],
        ]
    elif section == "delivery":
        rows = [
            [
                {
                    "text": ("🔔 Alerts On" if direct_delivery_enabled else "🔔 Alerts Off")
                    if language != "ru"
                    else ("🔔 Сигналы вкл" if direct_delivery_enabled else "🔔 Сигналы выкл"),
                    "callback_data": "ux:toggle:alerts",
                },
                {
                    "text": ("🔄 Follow-Ups On" if followup_delivery_enabled else "🔄 Follow-Ups Off")
                    if language != "ru"
                    else ("🔄 Фоллоу-апы вкл" if followup_delivery_enabled else "🔄 Фоллоу-апы выкл"),
                    "callback_data": "ux:toggle:followups",
                },
            ],
            [
                {"text": "⚡ Instant" if language != "ru" else "⚡ Сразу", "callback_data": "ux:delivery:mode:instant"},
                {"text": "📦 Digest" if language != "ru" else "📦 Сводка", "callback_data": "ux:delivery:mode:digest"},
                {"text": "🌙 Quiet" if language != "ru" else "🌙 Тихо", "callback_data": "ux:delivery:mode:quiet"},
            ],
            [
                {"text": "😴 1h", "callback_data": "ux:snooze:1h"},
                {"text": "😴 8h", "callback_data": "ux:snooze:8h"},
            ],
            [
                {
                    "text": ("🌙 Night Off" if quiet_hours_active else "🌙 Night On")
                    if language != "ru"
                    else ("🌙 Ночью выкл" if quiet_hours_active else "🌙 Ночью вкл"),
                    "callback_data": "ux:quiet:toggle",
                },
                {"text": "🌙 23:00-07:00", "callback_data": "ux:quiet:late"},
                {"text": "🌙 00:00-08:00", "callback_data": "ux:quiet:overnight"},
            ],
        ]
        if premium and include_gold_button:
            rows.insert(
                1,
                [
                    {
                        "text": ("🥇 Gold On" if gold_alerts_enabled else "🥇 Gold Off")
                        if language != "ru"
                        else ("🥇 Золото вкл" if gold_alerts_enabled else "🥇 Золото выкл"),
                        "callback_data": "ux:gold:delivery",
                    }
                ],
            )
        if snoozed:
            rows.append([{"text": "▶️ Resume" if language != "ru" else "▶️ Возобновить", "callback_data": "ux:snooze:resume"}])
    elif section == "stats":
        rows = [
            [
                {"text": "📅 Daily" if language != "ru" else "📅 День", "callback_data": "ux:recap:daily"},
                {"text": "🗓 Weekly" if language != "ru" else "🗓 Неделя", "callback_data": "ux:recap:weekly"},
            ],
            [
                {"text": "🔄 Lifecycle" if language != "ru" else "🔄 Жизненный цикл", "callback_data": "lifecycle:hub"},
                {"text": "✨ Fresh Signals" if language != "ru" else "✨ Свежие сигналы", "callback_data": "ux:signals:fresh"},
            ],
            [
                {"text": "📈 Strategy Results" if language != "ru" else "📈 Результаты стратегий", "callback_data": "compare:hub"},
                {"text": "🟢 Bot Status" if language != "ru" else "🟢 Статус бота", "callback_data": "ux:status"},
            ],
        ]
    elif section == "settings":
        rows = [
            [
                {"text": "🔔 Notifications" if language != "ru" else "🔔 Уведомления", "callback_data": "ux:deliveryhub"},
                {"text": "🎯 Filters" if language != "ru" else "🎯 Фильтры", "callback_data": "ux:filtershub"},
            ],
            [
                {"text": "🧩 Workspace" if language != "ru" else "🧩 Профиль", "callback_data": "ux:workspacehub"},
                {"text": "🌐 Language" if language != "ru" else "🌐 Язык", "callback_data": "ux:language:picker:settings"},
            ],
            [
                {"text": "👀 Watchlist" if language != "ru" else "👀 Вотчлист", "callback_data": "ux:watchhub"},
                {"text": "🟢 Bot Status" if language != "ru" else "🟢 Статус бота", "callback_data": "ux:status"},
            ],
        ]
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data, home_callback_data=home_callback_data))
    return {"inline_keyboard": rows}
