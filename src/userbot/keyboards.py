from __future__ import annotations

from src.localization import normalize_language, ui_text
from src.userbot.onboarding_flow import (
    onboarding_steps,
    previous_onboarding_step,
    resolve_quick_setup_strategy_key,
    strategy_preset_label,
    strategy_symbol_suggestions,
    strategy_supports_rsi_mode,
    strategy_supports_universe,
    strategy_supports_volume,
)
from src.userbot.premium_text import premium_text
from src.userbot.navigation import (
    compare_callback,
    external_label,
    learn_callback,
    lifecycle_callback,
    main_callback,
    results_callback,
    standard_nav_rows,
    strategy_alerts_callback,
    strategy_callback,
    strategy_compare_callback,
    strategy_favorites_callback,
    strategy_filters_callback,
    strategy_guide_callback,
    strategy_quicksetup_callback,
    strategy_results_callback,
    strategy_settings_callback,
    strategy_signals_callback,
    strategy_toggle_callback,
)
from src.userbot.strategy_preferences import strategy_preference_controls


def _language_toggle_label(language_code: str) -> str:
    language = normalize_language(language_code)
    target_language = ui_text(language, "language_switch_to")
    return ui_text(language, "menu_language").format(
        language=target_language,
        language_name=target_language,
    )


def _strategies_label(language_code: str) -> str:
    return "Стратегии" if normalize_language(language_code) == "ru" else "Strategies"


def _coin_alerts_label(language_code: str) -> str:
    return "Уведомления по монетам" if normalize_language(language_code) == "ru" else "Coin Alerts"


def _strategy_guide_label(language_code: str) -> str:
    return "🧭 Гайд по стратегии" if normalize_language(language_code) == "ru" else "🧭 Strategy Guide"


def _referral_label(language_code: str) -> str:
    return ui_text(normalize_language(language_code), "menu_referral")


def _telegram_target_url(target: str) -> str:
    cleaned = str(target or "").strip()
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return cleaned
    if cleaned.startswith("@"):
        return f"https://t.me/{cleaned.lstrip('@')}"
    return cleaned


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


def _strategy_profile_options(
    *,
    strategy_key: str | None,
    language_code: str,
) -> tuple[tuple[str, str], tuple[str, str], tuple[str, str]]:
    language = normalize_language(language_code)
    labels = {
        "breakout": {
            "en": (
                ("conservative", "🧱 Confirmed"),
                ("balanced", "⚖ Clean"),
                ("aggressive", "⚡ Early"),
            ),
            "ru": (
                ("conservative", "🧱 Подтвержденный"),
                ("balanced", "⚖ Чистый"),
                ("aggressive", "⚡ Ранний"),
            ),
        },
        "trend_pullback": {
            "en": (
                ("conservative", "📈 Deep Trend"),
                ("balanced", "⚖ EMA Touch"),
                ("aggressive", "⚡ Fast Bounce"),
            ),
            "ru": (
                ("conservative", "📈 Сильный тренд"),
                ("balanced", "⚖ От EMA"),
                ("aggressive", "⚡ Быстрый отскок"),
            ),
        },
        "rsi_bollinger_mr": {
            "en": (
                ("conservative", "🎯 Clean Revert"),
                ("balanced", "⚖ Balanced MR"),
                ("aggressive", "⚡ Fast Snapback"),
            ),
            "ru": (
                ("conservative", "🎯 Чистый возврат"),
                ("balanced", "⚖ Баланс MR"),
                ("aggressive", "⚡ Быстрый откат"),
            ),
        },
        "rsi_bollinger_touch": {
            "en": (
                ("conservative", "Clean Touch"),
                ("balanced", "Directional Touch"),
                ("aggressive", "Early Tag"),
            ),
            "ru": (
                ("conservative", "Р§РёСЃС‚РѕРµ РєР°СЃР°РЅРёРµ"),
                ("balanced", "Directional Touch"),
                ("aggressive", "Р Р°РЅРЅРёР№ С‚РµРі"),
            ),
        },
        "daily_rsi_80": {
            "en": (
                ("conservative", "Very Selective"),
                ("balanced", "Daily Heat"),
                ("aggressive", "Wide Watchlist"),
            ),
            "ru": (
                ("conservative", "Очень выборочно"),
                ("balanced", "Дневной перегрев"),
                ("aggressive", "Шире список"),
            ),
        },
        "vwap": {
            "en": (
                ("conservative", "⚖ Hold VWAP"),
                ("balanced", "📍 Reclaim"),
                ("aggressive", "⚡ Quick Flip"),
            ),
            "ru": (
                ("conservative", "⚖ Держать VWAP"),
                ("balanced", "📍 Возврат над VWAP"),
                ("aggressive", "⚡ Быстрый переворот"),
            ),
        },
        "false_breakout": {
            "en": (
                ("conservative", "🪤 Confirmed Trap"),
                ("balanced", "⚖ Clean Sweep"),
                ("aggressive", "⚡ Early Reversal"),
            ),
            "ru": (
                ("conservative", "🪤 Подтвержденный вынос"),
                ("balanced", "⚖ Чистый sweep"),
                ("aggressive", "⚡ Ранний разворот"),
            ),
        },
        "rsi": {
            "en": (
                ("conservative", "🛡 Cleaner"),
                ("balanced", "⚖ Balanced"),
                ("aggressive", "⚡ Earlier"),
            ),
            "ru": (
                ("conservative", "🛡 Чище"),
                ("balanced", "⚖ Баланс"),
                ("aggressive", "⚡ Раньше"),
            ),
        },
        "rsi_divergence": {
            "en": (
                ("conservative", "Clear Divergence"),
                ("balanced", "Balanced Divergence"),
                ("aggressive", "Early Divergence"),
            ),
            "ru": (
                ("conservative", "Р§РёСЃС‚Р°СЏ РґРёРІРµСЂРіРµРЅС†РёСЏ"),
                ("balanced", "Balanced Divergence"),
                ("aggressive", "Р Р°РЅРЅСЏСЏ РґРёРІРµСЂРіРµРЅС†РёСЏ"),
            ),
        },
        "bollinger": {
            "en": (
                ("conservative", "🎈 Cleaner Re-entry"),
                ("balanced", "⚖ Balanced Bands"),
                ("aggressive", "⚡ Faster Return"),
            ),
            "ru": (
                ("conservative", "🎈 Чистый возврат"),
                ("balanced", "⚖ Баланс Bands"),
                ("aggressive", "⚡ Быстрый возврат"),
            ),
        },
        "gold": {
            "en": (
                ("conservative", "🪙 Macro"),
                ("balanced", "⚖ Balanced"),
                ("aggressive", "⚡ Reactive"),
            ),
            "ru": (
                ("conservative", "🪙 Макро"),
                ("balanced", "⚖ Баланс"),
                ("aggressive", "⚡ Реактивно"),
            ),
        },
    }
    strategy_labels = labels.get((strategy_key or "rsi").strip().lower(), labels["rsi"])
    return strategy_labels["ru" if language == "ru" else "en"]


def _strategy_supports_rsi_mode(strategy_key: str | None) -> bool:
    return (strategy_key or "rsi").strip().lower() in {"rsi", "okak", "ekek", "rsi_bollinger_mr"}


def _strategy_supports_volume(strategy_key: str | None) -> bool:
    return (strategy_key or "rsi").strip().lower() != "gold"


def _strategy_supports_universe(strategy_key: str | None) -> bool:
    return (strategy_key or "rsi").strip().lower() != "gold"


def _selected_label(label: str, selected: bool) -> str:
    return f"✓ {label}" if selected else label


def build_main_menu_keyboard(
    *,
    direct_delivery_enabled: bool,
    followup_delivery_enabled: bool,
    include_community_button: bool,
    include_gold_button: bool,
    language_code: str,
    payment_label: str | None = None,
) -> dict[str, object]:
    language = normalize_language(language_code)
    keyboard = [[{"text": premium_text(language, "menu_signals")}, {"text": premium_text(language, "menu_watchlists")}]]
    if include_gold_button:
        keyboard.extend(
            [
                [{"text": premium_text(language, "menu_delivery")}, {"text": ui_text(language, "menu_gold_snapshot")}],
                [{"text": premium_text(language, "menu_stats")}, {"text": premium_text(language, "menu_ai_tools")}],
                [{"text": ui_text(language, "menu_my_access")}, {"text": premium_text(language, "menu_settings_premium")}],
            ]
        )
    else:
        keyboard.extend(
            [
                [{"text": premium_text(language, "menu_delivery")}, {"text": premium_text(language, "menu_stats")}],
                [{"text": ui_text(language, "menu_my_access")}, {"text": premium_text(language, "menu_ai_tools")}],
                [{"text": premium_text(language, "menu_settings_premium")}],
            ]
        )
    keyboard.append([{"text": _referral_label(language)}])
    keyboard.append([{"text": _language_toggle_label(language)}])
    if payment_label:
        keyboard.append([{"text": payment_label}])
    keyboard.append([{"text": ui_text(language, "menu_results_channel")}, {"text": ui_text(language, "menu_public_channel")}])
    if include_community_button:
        keyboard.append([{"text": ui_text(language, "menu_community_chat")}, {"text": ui_text(language, "menu_help")}])
    else:
        keyboard.append([{"text": ui_text(language, "menu_help")}])
    keyboard.append([{"text": ui_text(language, "menu_hide")}])
    return {
        "keyboard": keyboard,
        "resize_keyboard": True,
        "is_persistent": True,
    }


def build_classic_main_menu_keyboard(
    *,
    direct_delivery_enabled: bool,
    followup_delivery_enabled: bool,
    include_community_button: bool,
    include_gold_button: bool,
    language_code: str,
) -> dict[str, object]:
    language = normalize_language(language_code)
    del direct_delivery_enabled, followup_delivery_enabled, include_community_button, include_gold_button
    # Classic deliberately stays a separate, compact product.  More advanced
    # tools remain reachable inside the relevant screens and in Premium.
    keyboard = [
        [{"text": ui_text(language, "classic_menu_signals")}, {"text": ui_text(language, "classic_menu_setup")}],
        [{"text": ui_text(language, "menu_watchlist")}, {"text": ui_text(language, "classic_menu_premium")}],
        [{"text": ui_text(language, "menu_help")}],
    ]
    return {
        "keyboard": keyboard,
        "resize_keyboard": True,
        "is_persistent": True,
    }


def build_collapsed_menu_keyboard(*, language_code: str = "en") -> dict[str, object]:
    language = normalize_language(language_code)
    return {
        "keyboard": [[{"text": ui_text(language, "menu_open")}]],
        "resize_keyboard": True,
        "is_persistent": False,
        "one_time_keyboard": False,
    }


def build_hidden_menu_keyboard() -> dict[str, object]:
    return {
        "remove_keyboard": True,
    }


def build_onboarding_inline_keyboard(
    *,
    public_channel: str,
    results_channel: str,
    language_code: str = "en",
    community_target: str | None = None,
    bot_target: str | None = None,
    bot_label: str | None = None,
    channels_folder_target: str | None = None,
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows: list[list[dict[str, object]]] = [
        [
            {"text": ui_text(language, "menu_public_channel"), "url": _telegram_target_url(public_channel)},
            {"text": ui_text(language, "menu_results_channel"), "url": _telegram_target_url(results_channel)},
        ]
    ]
    second_row: list[dict[str, object]] = []
    if community_target:
        second_row.append({"text": ui_text(language, "menu_community_chat"), "url": _telegram_target_url(community_target)})
    if bot_target:
        second_row.append({"text": bot_label or ui_text(language, "open_bot"), "url": _telegram_target_url(bot_target)})
    if second_row:
        rows.append(second_row)
    if channels_folder_target:
        rows.append([{"text": ui_text(language, "channels_folder"), "url": _telegram_target_url(channels_folder_target)}])
    return {"inline_keyboard": rows}


def build_guided_start_keyboard(
    *,
    language_code: str = "en",
    bot_kind: str = "premium",
) -> dict[str, object]:
    language = normalize_language(language_code)
    classic = str(bot_kind or "").strip().lower() == "classic"
    if language == "ru":
        labels = {
            "strong": "📡 Последние Classic-сигналы" if classic else "💥 Сильные сетапы",
            "example": "🧾 Пример сигнала",
            "read": "📖 Как читать сигналы",
            "access": "💎 Мой доступ" if classic else "💎 Мой PRO+ доступ",
            "notifications": "🔔 Настроить уведомления",
            "compare": "⚖️ Classic vs PRO+",
            "help": "❓ Помощь",
            "menu": "🧭 Все разделы",
        }
    else:
        labels = {
            "strong": "📡 Latest Classic Signals" if classic else "💥 Strong Setups",
            "example": "🧾 Example Signal",
            "read": "📖 How to Read Signals",
            "access": "💎 My Access" if classic else "💎 My PRO+ Access",
            "notifications": "🔔 Notification Settings",
            "compare": "⚖️ Classic vs PRO+",
            "help": "❓ Help",
            "menu": "🧭 All Sections",
        }
    if classic:
        rows = [
            [
                {
                    "text": labels["strong"],
                    "callback_data": "ux:signals:recent",
                }
            ],
            [
                {"text": labels["example"], "callback_data": "ux:welcome:example"},
                {"text": labels["read"], "callback_data": "ux:welcome:read"},
            ],
        ]
    else:
        rows = [
            [
                {"text": labels["example"], "callback_data": "ux:welcome:example"},
                {"text": labels["read"], "callback_data": "ux:welcome:read"},
            ],
            [
                {
                    "text": labels["strong"],
                    "callback_data": "ux:signals:strong",
                }
            ],
        ]
    if classic:
        rows.append(
            [
                {"text": labels["compare"], "callback_data": "ux:help:compare"},
                {"text": labels["access"], "callback_data": "ux:access"},
            ]
        )
    else:
        rows.append(
            [
                {"text": labels["access"], "callback_data": "ux:access"},
                {"text": labels["notifications"], "callback_data": "ux:deliveryhub"},
            ]
        )
    rows.append(
        [
            {"text": labels["help"], "callback_data": "main:help"},
            {"text": labels["menu"], "callback_data": "ux:menu"},
        ]
    )
    return {"inline_keyboard": rows}


def build_example_signal_keyboard(*, language_code: str = "en") -> dict[str, object]:
    language = normalize_language(language_code)
    labels = {
        "read": "📖 Как читать" if language == "ru" else "📖 How to Read",
        "strong": "💥 Сильные сетапы" if language == "ru" else "💥 Strong Setups",
        "results": "📊 Результаты" if language == "ru" else "📊 Results",
        "access": "💎 Мой доступ" if language == "ru" else "💎 My Access",
        "home": "🏠 Главная" if language == "ru" else "🏠 Home",
    }
    return {
        "inline_keyboard": [
            [
                {"text": labels["read"], "callback_data": "ux:welcome:read"},
                {"text": labels["strong"], "callback_data": "ux:signals:strong"},
            ],
            [
                {"text": labels["results"], "callback_data": "main:results"},
                {"text": labels["access"], "callback_data": "ux:access"},
            ],
            [{"text": labels["home"], "callback_data": "ux:menu"}],
        ]
    }


def build_signal_reading_keyboard(*, language_code: str = "en") -> dict[str, object]:
    language = normalize_language(language_code)
    labels = {
        "example": "🧾 Пример сигнала" if language == "ru" else "🧾 Example Signal",
        "strong": "💥 Сильные сетапы" if language == "ru" else "💥 Strong Setups",
        "results": "📊 Результаты" if language == "ru" else "📊 Results",
        "access": "💎 Мой доступ" if language == "ru" else "💎 My Access",
        "home": "🏠 Главная" if language == "ru" else "🏠 Home",
    }
    return {
        "inline_keyboard": [
            [
                {"text": labels["example"], "callback_data": "ux:welcome:example"},
                {"text": labels["strong"], "callback_data": "ux:signals:strong"},
            ],
            [
                {"text": labels["results"], "callback_data": "main:results"},
                {"text": labels["access"], "callback_data": "ux:access"},
            ],
            [{"text": labels["home"], "callback_data": "ux:menu"}],
        ]
    }


def build_empty_signals_keyboard(*, language_code: str = "en") -> dict[str, object]:
    language = normalize_language(language_code)
    return {
        "inline_keyboard": [
            [
                {
                    "text": "🧾 Пример сигнала" if language == "ru" else "🧾 Example Signal",
                    "callback_data": "ux:welcome:example",
                },
                {
                    "text": "📊 Результаты" if language == "ru" else "📊 Results",
                    "callback_data": "main:results",
                },
            ],
            [
                {
                    "text": "🎯 Фильтры" if language == "ru" else "🎯 Filters",
                    "callback_data": "ux:filtershub",
                },
                {
                    "text": "❓ Помощь" if language == "ru" else "❓ Help",
                    "callback_data": "main:help",
                },
            ],
            [
                {
                    "text": "🏠 Главное меню" if language == "ru" else "🏠 Main Menu",
                    "callback_data": "ux:menu",
                }
            ],
        ]
    }


def build_language_picker_inline_keyboard(
    *,
    language_code: str,
    selected_language: str | None = None,
    context: str = "settings",
    back_callback_data: str | None = "ux:settingshub",
) -> dict[str, object]:
    language = normalize_language(language_code)
    selected = normalize_language(selected_language or language)
    rows: list[list[dict[str, object]]] = [
        [
            {
                "text": _selected_label("🇬🇧 English", selected == "en"),
                "callback_data": f"ux:language:set:en:{context}",
            },
            {
                "text": _selected_label("🇷🇺 Русский", selected == "ru"),
                "callback_data": f"ux:language:set:ru:{context}",
            },
        ]
    ]
    if context != "welcome":
        rows.extend(
            _footer_rows(
                language_code=language,
                back_callback_data=back_callback_data,
                home_callback_data="ux:menu",
            )
        )
    return {"inline_keyboard": rows}


def build_channel_inline_keyboard(*, label: str, target: str) -> dict[str, object]:
    return {
        "inline_keyboard": [
            [
                {
                    "text": label,
                    "url": _telegram_target_url(target),
                }
            ]
        ]
    }


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
    if can_renew:
        rows.append(
            [
                {"text": renew_label, "callback_data": "ux:renew"},
                {"text": ui_text(language, "menu_referral"), "callback_data": "ux:referral"},
            ]
        )
    else:
        rows.append([{"text": ui_text(language, "menu_referral"), "callback_data": "ux:referral"}])
    rows.extend(
        [
            [
                {"text": "Workspace" if language == "en" else "Профиль", "callback_data": "ux:workspacehub"},
                {"text": ui_text(language, "menu_signal_setup"), "callback_data": "ux:setup"},
            ],
            [
                {"text": ui_text(language, "menu_watchlist"), "callback_data": "ux:watchhub"},
                {"text": ui_text(language, "menu_help"), "callback_data": "main:help"},
            ],
        ]
    )
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback_data,
            home_callback_data=home_callback_data,
        )
    )
    return {"inline_keyboard": rows}


def build_status_inline_keyboard(
    *,
    language_code: str,
    back_callback_data: str | None = None,
    home_callback_data: str = "ux:menu",
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows: list[list[dict[str, object]]] = [
        [
            {"text": "Alerts" if language == "en" else "Уведомления", "callback_data": "ux:deliveryhub"},
            {"text": "Results" if language == "en" else "Результаты", "callback_data": "results:hub"},
        ],
        [
            {"text": ui_text(language, "menu_watchlist"), "callback_data": "ux:watchhub"},
            {"text": "Settings" if language == "en" else "Настройки", "callback_data": "ux:settingshub"},
        ],
    ]
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback_data,
            home_callback_data=home_callback_data,
        )
    )
    return {"inline_keyboard": rows}


def build_signal_setup_inline_keyboard(
    *,
    language_code: str,
    strategy_key: str | None,
    profile: str,
    rsi_mode: str,
    min_quote_volume: float | None,
    direction_filter: str,
    watchlist_only: bool,
    strategy_preferences: dict[str, object] | None = None,
    set_scope_active: bool = False,
    set_button_label: str | None = None,
    include_gold_toggle: bool,
    gold_alerts_enabled: bool,
    show_reset_button: bool = False,
    back_callback_data: str | None = None,
    home_callback_data: str = "ux:menu",
) -> dict[str, object]:
    language = normalize_language(language_code)
    strategy = (strategy_key or "rsi").strip().lower()
    volume_rows = (
        (("1M+", "1000000"), ("3M+", "3000000"), ("5M+", "5000000")),
        (("8M+", "8000000"), ("10M+", "10000000"), ("12M+", "12000000")),
    )
    profile_options = _strategy_profile_options(strategy_key=strategy, language_code=language)
    profile_row = [
        {
            "text": _selected_label(label, profile == key),
            "callback_data": f"ux:profile:{key}",
        }
        for key, label in profile_options
    ]
    rsi_row = [
        {"text": _selected_label(ui_text(language, "setup_rsi_tight"), rsi_mode == "tight"), "callback_data": "ux:rsi:tight"},
        {"text": _selected_label(ui_text(language, "setup_rsi_balanced"), rsi_mode == "balanced"), "callback_data": "ux:rsi:balanced"},
        {"text": _selected_label(ui_text(language, "setup_rsi_early"), rsi_mode == "early"), "callback_data": "ux:rsi:early"},
    ]
    volume_block = [
        [
            {
                "text": _selected_label(label, int(float(min_quote_volume or 0.0)) == int(raw)),
                "callback_data": f"ux:volume:{raw}",
            }
            for label, raw in volume_options
        ]
        for volume_options in volume_rows
    ]
    direction_row = [
        {"text": _selected_label(ui_text(language, "setup_both"), direction_filter == "both"), "callback_data": "ux:direction:both"},
        {"text": _selected_label(ui_text(language, "setup_long_only"), direction_filter == "long"), "callback_data": "ux:direction:long"},
        {"text": _selected_label(ui_text(language, "setup_short_only"), direction_filter == "short"), "callback_data": "ux:direction:short"},
    ]
    universe_row = [
        {"text": _selected_label(ui_text(language, "setup_all_symbols"), not watchlist_only), "callback_data": "ux:universe:all"},
        {"text": _selected_label(ui_text(language, "setup_watchlist_only"), watchlist_only and not set_scope_active), "callback_data": "ux:universe:favorites"},
        {
            "text": _selected_label(set_button_label or ui_text(language, "setup_set_only"), watchlist_only and set_scope_active),
            "callback_data": "ux:universe:set",
        },
    ]
    rows: list[list[dict[str, object]]] = [profile_row]
    if show_reset_button:
        rows.append([{"text": ui_text(language, "setup_reset_to_base"), "callback_data": "ux:profile:reset"}])
    if strategy in {"rsi", "rsi_bollinger_mr"}:
        rows.append(rsi_row)
    if strategy in {"breakout", "bollinger"} and _strategy_supports_volume(strategy):
        rows.extend(volume_block)
    if strategy in {"trend_pullback", "vwap", "false_breakout", "gold", "rsi"}:
        rows.append(direction_row)
    if strategy in {"trend_pullback", "vwap", "false_breakout"} and _strategy_supports_volume(strategy):
        rows.extend(volume_block)
    if strategy == "rsi_bollinger_mr" and _strategy_supports_volume(strategy):
        rows.extend(volume_block)
        rows.append(direction_row)
    if strategy == "breakout":
        rows.append(direction_row)
    if strategy == "bollinger":
        rows.append(direction_row)
    if strategy_supports_universe(strategy):
        rows.append(universe_row)
    for control in strategy_preference_controls(strategy, strategy_preferences, language_code=language):
        rows.append(
            [
                {
                    "text": _selected_label(str(option["label"]), str(control["selected_value"]) == str(option["value"])),
                    "callback_data": f"ux:pref:{control['key']}:{option['value']}",
                }
                for option in control["options"]
            ]
        )
    rows.append(
        [
            {"text": "⚡ Quick Setup" if language == "en" else "⚡ Быстрая настройка", "callback_data": "ux:onboard:start"},
            {"text": "🎛 Manual Setup" if language == "en" else "🎛 Ручная настройка", "callback_data": "ux:custom:start"},
        ]
    )
    if include_gold_toggle:
        rows.append(
            [
                {
                    "text": ui_text(language, "setup_gold_alerts", state=ui_text(language, "status_on" if gold_alerts_enabled else "status_off")),
                    "callback_data": "ux:gold:toggle",
                }
            ]
        )
    if _strategy_supports_universe(strategy):
        rows.append(
            [
                {"text": ui_text(language, "setup_open_watchlist"), "callback_data": "ux:watchlist"},
                {"text": ui_text(language, "setup_choose_set"), "callback_data": "ux:themes"},
            ]
        )
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback_data,
            home_callback_data=home_callback_data,
        )
    )
    return {"inline_keyboard": rows}


def build_custom_setup_inline_keyboard(*, language_code: str, direction_step: bool) -> dict[str, object]:
    language = normalize_language(language_code)
    rows: list[list[dict[str, object]]] = []
    if direction_step:
        rows.append(
            [
                {"text": ui_text(language, "setup_both"), "callback_data": "ux:direction:both"},
                {"text": ui_text(language, "setup_long_only"), "callback_data": "ux:direction:long"},
                {"text": ui_text(language, "setup_short_only"), "callback_data": "ux:direction:short"},
            ]
        )
    rows.append([{"text": ui_text(language, "custom_back_to_filters"), "callback_data": "ux:custom:cancel"}])
    return {"inline_keyboard": rows}


def build_compact_signals_inline_keyboard(
    *,
    language_code: str,
    entries: list[tuple[int, str]],
    strong_only: bool,
    back_callback_data: str | None = None,
    home_callback_data: str = "ux:menu",
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows: list[list[dict[str, object]]] = [
        [
            {"text": _selected_label(ui_text(language, "signals_latest_tab"), not strong_only), "callback_data": "ux:signals:recent"},
            {"text": _selected_label(ui_text(language, "signals_strongest_tab"), strong_only), "callback_data": "ux:signals:strong"},
        ]
    ]
    for alert_id, label in entries:
        rows.append([{"text": label, "callback_data": f"ux:signals:open:{alert_id}"}])
    rows.append([{"text": ui_text(language, "menu_signal_setup"), "callback_data": "ux:setup"}])
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback_data,
            home_callback_data=home_callback_data,
        )
    )
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
        row: list[dict[str, object]] = [
            {"text": symbol, "callback_data": f"ux:watch:open:{symbol}"},
        ]
        if allow_remove:
            row.append({"text": ui_text(language, "watchlist_remove"), "callback_data": f"ux:watch:remove:{symbol}"})
        rows.append(row)
    rows.append(
        [
            {"text": premium_text(language, "menu_themes"), "callback_data": "ux:themes"},
            {"text": premium_text(language, "menu_save_theme"), "callback_data": "ux:theme:save"},
        ]
    )
    rows.append(
        [
            {"text": ui_text(language, "menu_analyze_symbol"), "callback_data": "ux:analyze"},
            {"text": ui_text(language, "menu_signal_setup"), "callback_data": "ux:setup"},
        ]
    )
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback_data,
            home_callback_data=home_callback_data,
        )
    )
    return {"inline_keyboard": rows}


def build_analyze_symbol_inline_keyboard(
    *,
    language_code: str,
    symbols: list[str],
    back_callback_data: str | None = None,
    home_callback_data: str = "ux:menu",
) -> dict[str, object]:
    language = normalize_language(language_code)
    del symbols
    rows: list[list[dict[str, object]]] = [
        [
            {"text": "BTC", "copy_text": {"text": "BTC"}},
            {"text": "ETH 1h", "copy_text": {"text": "ETH 1h"}},
        ],
        [
            {"text": "XAUUSD", "copy_text": {"text": "XAUUSD"}},
            {"text": "SOL 4h", "copy_text": {"text": "SOL 4h"}},
        ],
        [
            {"text": "AI Guide" if language == "en" else "AI-гайд", "callback_data": "learn:ai_guide"},
            {"text": ui_text(language, "setup_open_watchlist"), "callback_data": "ux:watchlist"},
        ],
        [
            {"text": "Signals" if language == "en" else "Сигналы", "callback_data": "main:signals"},
            {"text": "Gold Desk" if language == "en" else "Золото / XAUUSD", "callback_data": "ux:goldhub"},
        ],
    ]
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback_data,
            home_callback_data=home_callback_data,
        )
    )
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
            "strong": "🎯 Сильные сетапы",
            "watchlist": "⭐ Мой вотчлист",
            "ai": "🧠 AI Desk",
            "alerts": "🔔 Уведомления",
            "strategies": "📚 Стратегии",
            "results": "📊 Результаты",
            "workspace": "🧩 Профиль",
            "filters": "🎛 Фильтры",
            "settings": "⚙️ Настройки",
            "access": "👤 Мой доступ",
            "refresh": "🔄 Обновить",
            "referral": "🤝 Рефералы",
            "help": "❓ Помощь",
        }
        if language == "ru"
        else {
            "strong": "🎯 Strong Setups",
            "watchlist": "⭐ My Watchlist",
            "ai": "🧠 AI Desk",
            "alerts": "🔔 Alerts",
            "strategies": "📚 Strategies",
            "results": "📊 Results",
            "workspace": "🧩 Workspace",
            "filters": "🎛 Filters",
            "settings": "⚙️ Settings",
            "access": "👤 My Access",
            "refresh": "🔄 Refresh",
            "referral": "🤝 Referral",
            "help": "❓ Help",
        }
    )
    localized_rows = [
        [
            {"text": labels["strong"], "callback_data": "ux:signals:strong"},
            {"text": labels["watchlist"], "callback_data": "ux:watchlist"},
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
            {"text": labels["filters"], "callback_data": "ux:setup"},
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
        localized_rows.append(
            [
                {"text": labels["referral"], "callback_data": "ux:referral"},
                {"text": payment_label, "callback_data": "ux:pay"},
            ]
        )
    else:
        localized_rows.append([{"text": labels["referral"], "callback_data": "ux:referral"}])
    return {"inline_keyboard": localized_rows}


def build_referral_inline_keyboard(
    *,
    language_code: str,
    referral_link: str,
    share_url: str,
    back_callback_data: str | None = None,
    home_callback_data: str = "ux:menu",
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [
        [
            {"text": ui_text(language, "referral_open_link"), "url": referral_link},
            {"text": ui_text(language, "referral_share_link"), "url": share_url},
        ],
        [
            {
                "text": "Copy Link" if language == "en" else "Скопировать ссылку",
                "copy_text": {"text": referral_link},
            },
            {
                "text": "My Access" if language == "en" else "Мой доступ",
                "callback_data": "main:access",
            },
        ],
        [
            {"text": ui_text(language, "referral_refresh"), "callback_data": "ux:referral"},
        ],
    ]
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback_data,
            home_callback_data=home_callback_data,
        )
    )
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
    language = normalize_language(language_code)
    normalized_mode = "simple" if str(display_mode or "").strip().lower() == "simple" else "pro"
    rows: list[list[dict[str, object]]] = [
        [
            {"text": "Notifications" if language == "en" else "Уведомления", "callback_data": "ux:deliveryhub"},
            {"text": "Filters" if language == "en" else "Фильтры", "callback_data": "ux:setup"},
        ],
        [
            {"text": "Delivery Mode" if language == "en" else "Режим доставки", "callback_data": "ux:deliveryhub"},
            {"text": "Quiet Hours" if language == "en" else "Тихие часы", "callback_data": "ux:deliveryhub"},
        ],
        [
            {"text": "Workspace" if language == "en" else "Профиль", "callback_data": "ux:workspacehub"},
            {"text": ui_text(language, "menu_change_language"), "callback_data": "ux:language:picker:settings"},
        ],
        [
            {"text": _selected_label("Simple", normalized_mode == "simple"), "callback_data": "ux:display:simple"},
            {"text": _selected_label("Pro", normalized_mode == "pro"), "callback_data": "ux:display:pro"},
        ],
        [
            {"text": "Watchlists" if language == "en" else "Вотчлисты", "callback_data": "ux:watchhub"},
            {"text": "Bot Status" if language == "en" else "Статус бота", "callback_data": "ux:status"},
        ],
        [
            {
                "text": (
                    ("Saved Workspace" if language == "en" else "Сохранённый профиль")
                    if has_saved_workspace
                    else ("Save Current" if language == "en" else "Сохранить текущее")
                ),
                "callback_data": "ux:workspace:apply:saved"
                if has_saved_workspace
                else "ux:workspace:save",
            },
            {"text": premium_text(language, "menu_setup_wizard"), "callback_data": "ux:onboard:start"},
        ],
    ]
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback_data,
            home_callback_data=home_callback_data,
        )
    )
    return {"inline_keyboard": rows}


from src.userbot.polished_keyboards import (
    build_access_inline_keyboard as _polished_build_access_inline_keyboard,
    build_analyze_symbol_inline_keyboard as _polished_build_analyze_symbol_inline_keyboard,
    build_compare_hub_keyboard as _polished_build_compare_hub_keyboard,
    build_help_inline_keyboard as _polished_build_help_inline_keyboard,
    build_learn_hub_keyboard as _polished_build_learn_hub_keyboard,
    build_menu_hub_inline_keyboard as _polished_build_menu_hub_inline_keyboard,
    build_results_hub_keyboard as _polished_build_results_hub_keyboard,
    build_section_hub_keyboard as _polished_build_section_hub_keyboard,
    build_settings_center_keyboard as _polished_build_settings_center_keyboard,
    build_status_inline_keyboard as _polished_build_status_inline_keyboard,
    build_watchlist_inline_keyboard as _polished_build_watchlist_inline_keyboard,
    build_workspace_center_keyboard as _polished_build_workspace_center_keyboard,
)

build_help_inline_keyboard = _polished_build_help_inline_keyboard
build_access_inline_keyboard = _polished_build_access_inline_keyboard
build_status_inline_keyboard = _polished_build_status_inline_keyboard
build_watchlist_inline_keyboard = _polished_build_watchlist_inline_keyboard
build_analyze_symbol_inline_keyboard = _polished_build_analyze_symbol_inline_keyboard
build_menu_hub_inline_keyboard = _polished_build_menu_hub_inline_keyboard
build_settings_center_keyboard = _polished_build_settings_center_keyboard
build_workspace_center_keyboard = _polished_build_workspace_center_keyboard
build_results_hub_keyboard = _polished_build_results_hub_keyboard
build_compare_hub_keyboard = _polished_build_compare_hub_keyboard
build_learn_hub_keyboard = _polished_build_learn_hub_keyboard
build_section_hub_keyboard = _polished_build_section_hub_keyboard


def build_help_inline_keyboard(
    *,
    language_code: str,
    back_callback_data: str | None = None,
    home_callback_data: str = "ux:menu",
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [
        [
            {"text": "🧾 Example Signal" if language != "ru" else "🧾 Пример сигнала", "callback_data": "ux:welcome:example"},
            {"text": "📖 Read Signals" if language != "ru" else "📖 Как читать", "callback_data": "ux:welcome:read"},
        ],
        [
            {"text": "🚀 Getting Started" if language != "ru" else "🚀 Быстрый старт", "callback_data": learn_callback("signals")},
            {"text": "⚙️ Setup Help" if language != "ru" else "⚙️ Помощь с настройкой", "callback_data": "ux:setup"},
        ],
        [
            {"text": "🔔 Alerts Help" if language != "ru" else "🔔 Помощь по алертам", "callback_data": "ux:deliveryhub"},
            {"text": "💳 Billing Help" if language != "ru" else "💳 Помощь с оплатой", "callback_data": main_callback("access")},
        ],
        [
            {"text": "📚 Learn" if language != "ru" else "📚 Обучение", "callback_data": main_callback("learn")},
            {"text": "💎 My Access" if language != "ru" else "💎 Мой доступ", "callback_data": main_callback("access")},
        ],
    ]
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback_data,
            home_callback_data=home_callback_data,
        )
    )
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
    if can_renew:
        rows.append(
            [
                {"text": renew_label, "callback_data": "ux:renew"},
                {"text": "🎁 Referral" if language != "ru" else "🎁 Рефералы", "callback_data": "ux:referral"},
            ]
        )
    else:
        rows.append([{"text": "🎁 Referral" if language != "ru" else "🎁 Рефералы", "callback_data": "ux:referral"}])
    rows.extend(
        [
            [
                {"text": "🧩 Workspace" if language != "ru" else "🧩 Workspace", "callback_data": "ux:workspacehub"},
                {"text": "🎯 Filters" if language != "ru" else "🎯 Фильтры", "callback_data": "ux:setup"},
            ],
            [
                {"text": "👀 Watchlist" if language != "ru" else "👀 Watchlist", "callback_data": "ux:watchhub"},
                {"text": "❓ Help" if language != "ru" else "❓ Помощь", "callback_data": main_callback("help")},
            ],
        ]
    )
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback_data,
            home_callback_data=home_callback_data,
        )
    )
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
            {"text": "👀 Watchlist" if language != "ru" else "👀 Watchlist", "callback_data": "ux:watchhub"},
            {"text": "⚙️ Settings" if language != "ru" else "⚙️ Настройки", "callback_data": "ux:settingshub"},
        ],
    ]
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback_data,
            home_callback_data=home_callback_data,
        )
    )
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
                {"text": "🎯 Filters" if language != "ru" else "🎯 Фильтры", "callback_data": "ux:setup"},
            ],
        ]
    )
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback_data,
            home_callback_data=home_callback_data,
        )
    )
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
            {"text": "👀 Watchlist" if language != "ru" else "👀 Watchlist", "callback_data": "ux:watchhub"},
        ],
        [
            {"text": "📡 Signals" if language != "ru" else "📡 Сигналы", "callback_data": main_callback("signals")},
            {"text": "🥇 Gold Desk" if language != "ru" else "🥇 Gold Desk", "callback_data": "ux:goldhub"},
        ],
        [
            {"text": "⚙️ Settings" if language != "ru" else "⚙️ Настройки", "callback_data": "ux:settingshub"},
            {"text": "🎯 Filters" if language != "ru" else "🎯 Фильтры", "callback_data": "ux:setup"},
        ],
    ]
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback_data,
            home_callback_data=home_callback_data,
        )
    )
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
            "alerts": "🔔 Alerts",
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
            "watchlist": "👀 Watchlist",
            "ai": "🤖 AI Desk",
            "alerts": "🔔 Алерты",
            "strategies": "📈 Стратегии",
            "results": "📊 Результаты",
            "workspace": "🧩 Workspace",
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
            {"text": labels["filters"], "callback_data": "ux:setup"},
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
            {"text": "🎯 Filters" if language != "ru" else "🎯 Фильтры", "callback_data": "ux:setup"},
        ],
        [
            {"text": "📬 Delivery" if language != "ru" else "📬 Доставка", "callback_data": "ux:deliveryhub"},
            {"text": "🌙 Quiet Hours" if language != "ru" else "🌙 Тихие часы", "callback_data": "ux:deliveryhub"},
        ],
        [
            {"text": "🧩 Workspace" if language != "ru" else "🧩 Workspace", "callback_data": "ux:workspacehub"},
            {"text": "🌐 Language" if language != "ru" else "🌐 Язык", "callback_data": "ux:language:picker:settings"},
        ],
        [
            {"text": _selected_label("🖥 Simple" if language != "ru" else "🖥 Просто", normalized_mode == "simple"), "callback_data": "ux:display:simple"},
            {"text": _selected_label("🖥 Pro", normalized_mode == "pro"), "callback_data": "ux:display:pro"},
        ],
        [
            {"text": "👀 Watchlist" if language != "ru" else "👀 Watchlist", "callback_data": "ux:watchhub"},
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
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback_data,
            home_callback_data=home_callback_data,
        )
    )
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
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback_data,
            home_callback_data=home_callback_data,
        )
    )
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
            {"text": "🔄 Lifecycle" if language != "ru" else "🔄 Lifecycle", "callback_data": lifecycle_hub_callback},
            {"text": "✨ Fresh Signals" if language != "ru" else "✨ Свежие сигналы", "callback_data": "ux:signals:fresh"},
        ],
        [
            {"text": "📈 Strategy Results" if language != "ru" else "📈 Результаты стратегий", "callback_data": compare_callback("hub")},
            {"text": "🟢 Bot Status" if language != "ru" else "🟢 Статус бота", "callback_data": "ux:status"},
        ],
    ]
    if is_admin:
        rows.append(
            [
                {"text": "⚖️ Compare Periods" if language != "ru" else "⚖️ Сравнить периоды", "callback_data": results_callback("admin")},
                {"text": "👑 Admin Stats" if language != "ru" else "👑 Админ-стата", "callback_data": results_callback("admin")},
            ]
        )
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback,
            home_callback_data=main_callback("today"),
        )
    )
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
        rows.append([{"text": "👑 Admin Stats" if language != "ru" else "👑 Админ-стата", "callback_data": "compare:admin"}])
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=main_callback("strategies"),
            home_callback_data=main_callback("today"),
        )
    )
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
            {"text": "✨ What Changed" if language != "ru" else "✨ What Changed", "callback_data": learn_callback("what_changed")},
        ],
    ]
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=main_callback("today"),
            home_callback_data=main_callback("today"),
        )
    )
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
                {"text": "👀 Watchlist" if language != "ru" else "👀 Watchlist", "callback_data": "ux:watchhub"},
                {"text": "⚙️ Settings" if language != "ru" else "⚙️ Настройки", "callback_data": "ux:settingshub"},
            ],
            [
                {"text": "📡 Signals" if language != "ru" else "📡 Сигналы", "callback_data": main_callback("signals")},
                {"text": "🥇 Gold Desk" if language != "ru" else "🥇 Gold Desk", "callback_data": "ux:goldhub"},
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
                {"text": "🔄 Lifecycle" if language != "ru" else "🔄 Lifecycle", "callback_data": "lifecycle:hub"},
            ],
            [
                {"text": "⚖️ Compare" if language != "ru" else "⚖️ Сравнить", "callback_data": "compare:hub"},
                {"text": "🎯 Filters" if language != "ru" else "🎯 Фильтры", "callback_data": "ux:setup"},
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
                {"text": "➕ Add / Remove" if language != "ru" else "➕ Добавить / убрать", "callback_data": "ux:watchlist"},
            ],
            [
                {"text": "🎯 Filters" if language != "ru" else "🎯 Фильтры", "callback_data": "ux:setup"},
                {"text": "🔔 Alerts" if language != "ru" else "🔔 Алерты", "callback_data": "ux:deliveryhub"},
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
                {"text": "⚡ Instant", "callback_data": "ux:delivery:mode:instant"},
                {"text": "🗂 Digest" if language != "ru" else "🗂 Сводка", "callback_data": "ux:delivery:mode:digest"},
                {"text": "🌙 Quiet" if language != "ru" else "🌙 Тихо", "callback_data": "ux:delivery:mode:quiet"},
            ],
            [
                {"text": "😴 1h", "callback_data": "ux:snooze:1h"},
                {"text": "😴 8h", "callback_data": "ux:snooze:8h"},
            ],
            [
                {"text": "🌙 Off" if language != "ru" else "🌙 Выкл", "callback_data": "ux:quiet:off"},
                {"text": "🌙 Late", "callback_data": "ux:quiet:late"},
                {"text": "🌙 Overnight" if language != "ru" else "🌙 Ночь", "callback_data": "ux:quiet:overnight"},
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
                {"text": "🔄 Lifecycle" if language != "ru" else "🔄 Lifecycle", "callback_data": "lifecycle:hub"},
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
                {"text": "🎯 Filters" if language != "ru" else "🎯 Фильтры", "callback_data": "ux:setup"},
            ],
            [
                {"text": "🧩 Workspace" if language != "ru" else "🧩 Workspace", "callback_data": "ux:workspacehub"},
                {"text": "🌐 Language" if language != "ru" else "🌐 Язык", "callback_data": "ux:language:picker:settings"},
            ],
            [
                {"text": "👀 Watchlist" if language != "ru" else "👀 Watchlist", "callback_data": "ux:watchhub"},
                {"text": "🟢 Bot Status" if language != "ru" else "🟢 Статус бота", "callback_data": "ux:status"},
            ],
        ]
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback_data,
            home_callback_data=home_callback_data,
        )
    )
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
    labels = (
        {
            "scalp": "Scalp",
            "intraday": "Intraday",
            "swing": "Swing",
            "gold_focus": "Gold Focus",
            "low_noise": "Low Noise",
            "aggressive": "Aggressive",
            "custom": "Custom",
            "save_current": "Save Current",
            "saved": "Saved",
            "saved_workspace": "Saved Workspace",
            "wizard": "Wizard",
        }
        if language == "en"
        else {
            "scalp": "Скальп",
            "intraday": "Интрадей",
            "swing": "Свинг",
            "gold_focus": "Фокус на золоте",
            "low_noise": "Мало шума",
            "aggressive": "Агрессивный",
            "custom": "Кастом",
            "save_current": "Сохранить текущее",
            "saved": "Сохранённый",
            "saved_workspace": "Сохранённый профиль",
            "wizard": "Мастер",
        }
    )
    rows: list[list[dict[str, object]]] = [
        [
            {"text": _selected_label(labels["scalp"], active_workspace == "scalp"), "callback_data": "ux:workspace:apply:scalp"},
            {"text": _selected_label(labels["intraday"], active_workspace == "intraday"), "callback_data": "ux:workspace:apply:intraday"},
        ],
        [
            {"text": _selected_label(labels["swing"], active_workspace == "swing"), "callback_data": "ux:workspace:apply:swing"},
            {"text": _selected_label(labels["gold_focus"], active_workspace == "gold_focus"), "callback_data": "ux:workspace:apply:gold_focus"},
        ],
        [
            {"text": _selected_label(labels["low_noise"], active_workspace == "low_noise"), "callback_data": "ux:workspace:apply:low_noise"},
            {"text": _selected_label(labels["aggressive"], active_workspace == "aggressive"), "callback_data": "ux:workspace:apply:aggressive"},
        ],
        [
            {"text": labels["custom"], "callback_data": "ux:setup"},
            {"text": labels["save_current"], "callback_data": "ux:workspace:save"},
        ],
        [
            {
                "text": _selected_label(labels["saved"], active_workspace == "saved")
                if has_saved_workspace
                else labels["saved_workspace"],
                "callback_data": "ux:workspace:apply:saved",
            },
            {"text": labels["wizard"], "callback_data": "ux:onboard:start"},
        ],
    ]
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback_data,
            home_callback_data=home_callback_data,
        )
    )
    return {"inline_keyboard": rows}


def build_strategy_guide_inline_keyboard(
    *,
    language_code: str,
    home_callback_data: str = "ux:menu",
) -> dict[str, object]:
    language = normalize_language(language_code)
    return {
        "inline_keyboard": [
            [
                {"text": ui_text(language, "menu_back"), "callback_data": "ux:guide:close"},
                {"text": ui_text(language, "menu_home"), "callback_data": home_callback_data},
            ]
        ]
    }


def build_strategy_hub_keyboard(
    *,
    language_code: str,
    strategy_key: str,
    strategy_enabled: bool,
    include_gold_shortcut: bool,
) -> dict[str, object]:
    return build_product_strategy_hub_keyboard(
        strategy_key=strategy_key,
        strategy_enabled=strategy_enabled,
        include_gold_shortcut=include_gold_shortcut,
        language_code=language_code,
    )
    language = normalize_language(language_code)
    if language == "ru":
        toggle_label = "Выключить стратегию" if strategy_enabled else "Включить стратегию"
        back_label = "← К стратегиям"
    else:
        toggle_label = "Disable Strategy" if strategy_enabled else "Enable Strategy"
        back_label = "← Back to Strategies"
    rows: list[list[dict[str, object]]] = [
        [
            {"text": premium_text(language, "menu_signals"), "callback_data": "ux:signalshub:strategy"},
            {"text": ui_text(language, "menu_signal_setup"), "callback_data": "ux:setup"},
        ],
        [
            {"text": premium_text(language, "menu_delivery"), "callback_data": "ux:deliveryhub:strategy"},
            {"text": premium_text(language, "menu_watchlists"), "callback_data": "ux:watchhub:strategy"},
        ],
    ]
    rows.append(
        [
            {"text": premium_text(language, "menu_setup_wizard"), "callback_data": "ux:onboard:start"},
            {"text": premium_text(language, "menu_settings_premium"), "callback_data": "ux:settingshub:strategy"},
        ]
    )
    rows.append(
        [
            {"text": ui_text(language, "menu_analyze_symbol"), "callback_data": "ux:analyze"},
            {"text": premium_text(language, "menu_stats"), "callback_data": "ux:statshub:strategy"},
        ]
    )
    if include_gold_shortcut:
        rows.append([{"text": ui_text(language, "menu_gold_snapshot"), "callback_data": "ux:goldhub"}])
    rows.append([{"text": _strategy_guide_label(language), "callback_data": "ux:guide"}])
    rows.append([{"text": toggle_label, "callback_data": f"ux:strategy:toggle:{strategy_key}"}])
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data="ux:strategies",
            home_callback_data="ux:menu",
        )
    )
    return {"inline_keyboard": rows}


def build_strategy_selector_inline_keyboard(
    *,
    rows: list[tuple[str, str, str | None, str | None]],
    include_home_button: bool,
    language_code: str,
) -> dict[str, object]:
    language = normalize_language(language_code)
    keyboard_rows: list[list[dict[str, object]]] = []
    for primary_label, primary_callback, secondary_label, secondary_callback in rows:
        row = [{"text": primary_label, "callback_data": primary_callback}]
        if secondary_label and secondary_callback:
            row.append({"text": secondary_label, "callback_data": secondary_callback})
        keyboard_rows.append(row)
    if include_home_button:
        keyboard_rows.append([{"text": ui_text(language, "menu_home"), "callback_data": "ux:menu"}])
    return {"inline_keyboard": keyboard_rows}


def _product_strategy_label(strategy_key: str, *, language_code: str = "en") -> str:
    language = normalize_language(language_code)
    labels = {
        "breakout": ("Breakout", "Пробой уровня"),
        "trend_pullback": ("Trend Pullback", "Откат по тренду"),
        "rsi_bollinger_mr": ("RSI + Bollinger MR", "RSI + Bollinger MR"),
        "vwap": ("VWAP", "VWAP"),
        "false_breakout": ("False Breakout", "Ложный пробой"),
        "rsi": ("RSI", "RSI"),
        "bollinger": ("Bollinger", "Боллинджер"),
        "gold": ("Gold / XAUUSD", "Золото / XAUUSD"),
        "gold_breakout": ("Gold Breakout", "Gold Breakout"),
        "gold_pullback": ("Gold Pullback", "Gold Pullback"),
        "gold_liquidity": ("Gold Liquidity", "Gold Liquidity"),
    }
    english, russian = labels.get(strategy_key, labels["rsi"])
    return russian if language == "ru" else english


def build_product_strategy_hub_keyboard(
    *,
    strategy_key: str,
    strategy_enabled: bool,
    include_gold_shortcut: bool,
) -> dict[str, object]:
    toggle_label = "🟢 Disable Strategy" if strategy_enabled else "🟢 Enable Strategy"
    rows: list[list[dict[str, object]]] = [
        [
            {"text": "📡 Signals", "callback_data": strategy_signals_callback(strategy_key)},
            {"text": "🎛 Signal Filters", "callback_data": strategy_filters_callback(strategy_key)},
        ],
        [
            {"text": "🔔 Alerts", "callback_data": strategy_alerts_callback(strategy_key)},
            {"text": "⭐ Favorites", "callback_data": strategy_favorites_callback(strategy_key)},
        ],
        [
            {"text": "⚡ Quick Setup", "callback_data": strategy_quicksetup_callback(strategy_key)},
            {"text": "📊 Results", "callback_data": strategy_results_callback(strategy_key)},
        ],
        [
            {"text": "🧠 AI Analyze Coin", "callback_data": "main:ai"},
            {"text": "📘 Strategy Guide", "callback_data": strategy_guide_callback(strategy_key)},
        ],
        [
            {"text": "⚙️ Settings", "callback_data": strategy_settings_callback(strategy_key)},
            {"text": toggle_label, "callback_data": strategy_toggle_callback(strategy_key)},
        ],
        [
            {"text": "🆚 Compare This Strategy", "callback_data": strategy_compare_callback(strategy_key)},
        ],
    ]
    if include_gold_shortcut:
        rows.append([{"text": "🥇 Gold / XAUUSD", "callback_data": "ux:goldhub"}])
    rows.extend(
        standard_nav_rows(
            back_callback_data=main_callback("strategies"),
            main_callback_data=main_callback("hub"),
            third_callback_data=main_callback("help"),
        )
    )
    return {"inline_keyboard": rows}


def build_strategies_hub_keyboard(*, is_admin: bool = False) -> dict[str, object]:
    del is_admin
    rows: list[list[dict[str, object]]] = [
        [
            {"text": "Breakout", "callback_data": strategy_callback("open", "breakout")},
            {"text": "Trend Pullback", "callback_data": strategy_callback("open", "trend_pullback")},
        ],
        [
            {"text": "RSI + Bollinger MR", "callback_data": strategy_callback("open", "rsi_bollinger_mr")},
            {"text": "VWAP", "callback_data": strategy_callback("open", "vwap")},
        ],
        [
            {"text": "False Breakout", "callback_data": strategy_callback("open", "false_breakout")},
            {"text": "RSI", "callback_data": strategy_callback("open", "rsi")},
        ],
        [
            {"text": "Bollinger", "callback_data": strategy_callback("open", "bollinger")},
            {"text": "Gold / XAUUSD", "callback_data": strategy_callback("open", "gold")},
        ],
        [
            {"text": "🆚 Compare Strategies", "callback_data": compare_callback("hub")},
        ],
    ]
    rows.extend(
        standard_nav_rows(
            back_callback_data=main_callback("hub"),
            main_callback_data=main_callback("hub"),
            third_callback_data=main_callback("help"),
        )
    )
    return {"inline_keyboard": rows}


def build_results_hub_keyboard(
    *,
    is_admin: bool,
    strategy_code: str | None = None,
) -> dict[str, object]:
    lifecycle_hub_callback = (
        f"strategy:lifecycle:{strategy_code}" if strategy_code else lifecycle_callback("hub")
    )
    back_callback = (
        strategy_callback("open", strategy_code) if strategy_code else main_callback("hub")
    )
    rows: list[list[dict[str, object]]] = [
        [
            {"text": "📅 Day Results", "callback_data": "ux:recap:daily"},
            {"text": "🗓 Week Results", "callback_data": "ux:recap:weekly"},
        ],
        [
            {"text": "📡 Signal Lifecycle", "callback_data": lifecycle_hub_callback},
            {"text": "🟢 Fresh Signals", "callback_data": "ux:signals:recent"},
        ],
        [
            {"text": "📈 Bot Status", "callback_data": "ux:status"},
        ],
    ]
    if is_admin:
        rows.append([{"text": "👑 Admin Stats", "callback_data": results_callback("admin")}])
    rows.extend(
        standard_nav_rows(
            back_callback_data=back_callback,
            main_callback_data=main_callback("hub"),
            third_callback_data=main_callback("help"),
        )
    )
    return {"inline_keyboard": rows}


def build_compare_hub_keyboard(*, is_admin: bool) -> dict[str, object]:
    rows: list[list[dict[str, object]]] = [
        [
            {"text": "🧩 All Strategies", "callback_data": compare_callback("all")},
            {"text": "📈 Best for Trend", "callback_data": compare_callback("trend")},
        ],
        [
            {"text": "↔️ Best for Range", "callback_data": compare_callback("range")},
            {"text": "🥇 Best for Gold", "callback_data": compare_callback("gold")},
        ],
        [
            {"text": "🔕 Low-Noise Picks", "callback_data": compare_callback("lownoise")},
            {"text": "⏱ Best by Timeframe", "callback_data": compare_callback("timeframe")},
        ],
        [
            {"text": "🪙 Best by Asset Type", "callback_data": compare_callback("assets")},
        ],
    ]
    if is_admin:
        rows.append([{"text": "👑 Admin Stats", "callback_data": "compare:admin"}])
    rows.extend(
        standard_nav_rows(
            back_callback_data=main_callback("strategies"),
            main_callback_data=main_callback("hub"),
            third_callback_data=main_callback("help"),
        )
    )
    return {"inline_keyboard": rows}


def build_learn_hub_keyboard() -> dict[str, object]:
    rows = [
        [
            {"text": "📡 How Signals Work", "callback_data": learn_callback("signals")},
            {"text": "📘 Strategy Guides", "callback_data": learn_callback("guides")},
        ],
        [
            {"text": "🛡️ Risk Basics", "callback_data": learn_callback("risk")},
            {"text": "👀 How to Read a Signal", "callback_data": learn_callback("read_signal")},
        ],
        [
            {"text": "🔄 What Changed Guide", "callback_data": learn_callback("what_changed")},
            {"text": "🧠 AI Analysis Guide", "callback_data": learn_callback("ai_guide")},
        ],
        [
            {"text": "🥇 Gold Guide", "callback_data": learn_callback("gold")},
        ],
    ]
    rows.extend(
        standard_nav_rows(
            back_callback_data=main_callback("hub"),
            main_callback_data=main_callback("hub"),
            third_callback_data=main_callback("help"),
        )
    )
    return {"inline_keyboard": rows}


def build_strategy_guides_keyboard() -> dict[str, object]:
    rows = [
        [
            {"text": "Breakout", "callback_data": "learn:guide:breakout"},
            {"text": "Trend Pullback", "callback_data": "learn:guide:trend_pullback"},
        ],
        [
            {"text": "RSI + Bollinger MR", "callback_data": "learn:guide:rsi_bollinger_mr"},
            {"text": "VWAP", "callback_data": "learn:guide:vwap"},
        ],
        [
            {"text": "False Breakout", "callback_data": "learn:guide:false_breakout"},
            {"text": "RSI", "callback_data": "learn:guide:rsi"},
        ],
        [
            {"text": "Bollinger", "callback_data": "learn:guide:bollinger"},
            {"text": "Gold / XAUUSD", "callback_data": "learn:guide:gold"},
        ],
    ]
    rows.extend(
        standard_nav_rows(
            back_callback_data=learn_callback("hub"),
            main_callback_data=main_callback("hub"),
            third_callback_data=main_callback("help"),
        )
    )
    return {"inline_keyboard": rows}


def build_lifecycle_hub_keyboard(*, strategy_code: str | None = None) -> dict[str, object]:
    if strategy_code:
        open_callback = f"strategy:lifecycle:{strategy_code}:open"
        confirmed_callback = f"strategy:lifecycle:{strategy_code}:confirmed"
        invalidated_callback = f"strategy:lifecycle:{strategy_code}:invalidated"
        closed_callback = f"strategy:lifecycle:{strategy_code}:closed"
        back_callback = strategy_results_callback(strategy_code)
    else:
        open_callback = lifecycle_callback("open")
        confirmed_callback = lifecycle_callback("confirmed")
        invalidated_callback = lifecycle_callback("invalidated")
        closed_callback = lifecycle_callback("closed")
        back_callback = results_callback("hub")
    rows = [
        [
            {"text": "🟢 Open Signals", "callback_data": open_callback},
            {"text": "✅ Confirmed Signals", "callback_data": confirmed_callback},
        ],
        [
            {"text": "❌ Invalidated", "callback_data": invalidated_callback},
            {"text": "🏁 Closed Results", "callback_data": closed_callback},
        ],
    ]
    rows.extend(
        standard_nav_rows(
            back_callback_data=back_callback,
            main_callback_data=main_callback("hub"),
            third_callback_data=main_callback("help"),
        )
    )
    return {"inline_keyboard": rows}


def build_admin_stats_keyboard(*, back_callback_data: str) -> dict[str, object]:
    rows = [
        [
            {"text": "Last 7d", "callback_data": "results:admin:7d"},
            {"text": "Last 30d", "callback_data": "results:admin:30d"},
            {"text": "All-time", "callback_data": "results:admin:all_time"},
        ]
    ]
    rows.extend(
        standard_nav_rows(
            back_callback_data=back_callback_data,
            main_callback_data=main_callback("hub"),
            third_callback_data=main_callback("help"),
        )
    )
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
    back_callback_data: str | None = None,
    home_callback_data: str = "ux:menu",
) -> dict[str, object]:
    language = normalize_language(language_code)
    if section == "ai":
        rows = [
            [
                {"text": "BTC", "copy_text": {"text": "BTC"}},
                {"text": "ETH 1h", "copy_text": {"text": "ETH 1h"}},
            ],
            [
                {"text": "XAUUSD", "copy_text": {"text": "XAUUSD"}},
                {"text": "SOL 4h", "copy_text": {"text": "SOL 4h"}},
            ],
            [
                {"text": "AI Guide" if language == "en" else "AI-гайд", "callback_data": "learn:ai_guide"},
                {"text": ui_text(language, "menu_current_watchlist"), "callback_data": "ux:watchlist"},
            ],
            [
                {"text": "Signals" if language == "en" else "Сигналы", "callback_data": "main:signals"},
                {"text": "Gold Desk" if language == "en" else "Золото / XAUUSD", "callback_data": "ux:goldhub"},
            ],
        ]
        rows.extend(
            _footer_rows(
                language_code=language,
                back_callback_data=back_callback_data,
                home_callback_data=home_callback_data,
            )
        )
        return {"inline_keyboard": rows}
    rows: list[list[dict[str, object]]] = []
    if section == "signals":
        rows = [
            [
                {"text": ui_text(language, "menu_latest_signals"), "callback_data": "ux:signals:recent"},
                {"text": premium_text(language, "menu_open_strongest"), "callback_data": "ux:signals:strong"},
            ],
            [
                {"text": ui_text(language, "menu_analyze_symbol"), "callback_data": "main:ai"},
                {"text": premium_text(language, "menu_daily_recap"), "callback_data": "ux:recap:daily"},
            ],
            [
                {"text": "Fresh Signals" if language == "en" else "Свежие сигналы", "callback_data": "ux:signals:fresh"},
                {"text": "Lifecycle" if language == "en" else "Жизненный цикл", "callback_data": "lifecycle:hub"},
            ],
            [
                {"text": "Compare" if language == "en" else "Сравнение", "callback_data": "compare:hub"},
                {"text": "Filters" if language == "en" else "Фильтры", "callback_data": "ux:setup"},
            ],
        ]
    elif section == "watchlists":
        rows = [
            [
                {"text": ui_text(language, "menu_current_watchlist"), "callback_data": "ux:watchlist"},
                {"text": premium_text(language, "menu_themes"), "callback_data": "ux:themes"},
            ],
            [
                {"text": "Saved Themes" if language == "en" else "Сохранённые темы", "callback_data": "ux:themes"},
                {"text": "Create Theme" if language == "en" else "Создать тему", "callback_data": "ux:theme:save"},
            ],
            [
                {"text": "Quick Add/Remove" if language == "en" else "Быстрое + / -", "callback_data": "ux:watchlist"},
                {"text": "Open Filters" if language == "en" else "Открыть фильтры", "callback_data": "ux:setup"},
            ],
            [
                {"text": "Presets" if language == "en" else "Пресеты", "callback_data": "ux:themes"},
                {"text": "Default Theme" if language == "en" else "Тема по умолчанию", "callback_data": "ux:themes"},
            ],
        ]
    elif section == "delivery":
        rows = [
            [
                {"text": ui_text(language, "menu_alerts_on" if direct_delivery_enabled else "menu_alerts_off"), "callback_data": "ux:toggle:alerts"},
                {"text": ui_text(language, "menu_followups_on" if followup_delivery_enabled else "menu_followups_off"), "callback_data": "ux:toggle:followups"},
            ],
            [
                {"text": premium_text(language, "delivery_mode_instant"), "callback_data": "ux:delivery:mode:instant"},
                {"text": premium_text(language, "delivery_mode_digest"), "callback_data": "ux:delivery:mode:digest"},
                {"text": premium_text(language, "delivery_mode_quiet"), "callback_data": "ux:delivery:mode:quiet"},
            ],
        ]
        if premium and include_gold_button:
            rows.append(
                [
                    {
                        "text": premium_text(language, "menu_gold_alerts_on" if gold_alerts_enabled else "menu_gold_alerts_off"),
                        "callback_data": "ux:gold:delivery",
                    }
                ]
            )
        if snoozed:
            rows.append([{"text": premium_text(language, "menu_resume_now"), "callback_data": "ux:snooze:resume"}])
        rows.extend(
            [
                [
                    {"text": premium_text(language, "snooze_1h"), "callback_data": "ux:snooze:1h"},
                    {"text": premium_text(language, "snooze_8h"), "callback_data": "ux:snooze:8h"},
                ],
                [
                    {"text": premium_text(language, "snooze_tomorrow"), "callback_data": "ux:snooze:tomorrow"},
                    {"text": premium_text(language, "snooze_today"), "callback_data": "ux:snooze:today"},
                ],
                [
                    {"text": premium_text(language, "quiet_hours_off"), "callback_data": "ux:quiet:off"},
                    {"text": premium_text(language, "quiet_hours_late"), "callback_data": "ux:quiet:late"},
                    {"text": premium_text(language, "quiet_hours_overnight"), "callback_data": "ux:quiet:overnight"},
                ],
            ]
        )
    elif section == "stats":
        rows = [
            [
                {"text": premium_text(language, "menu_daily_recap"), "callback_data": "ux:recap:daily"},
                {"text": premium_text(language, "menu_weekly_recap"), "callback_data": "ux:recap:weekly"},
            ],
            [
                {"text": "Signal Lifecycle" if language == "en" else "Жизненный цикл", "callback_data": "lifecycle:hub"},
                {"text": "Fresh Signals" if language == "en" else "Свежие сигналы", "callback_data": "ux:signals:fresh"},
            ],
            [
                {"text": "Strategy Performance" if language == "en" else "Стратегии", "callback_data": "compare:hub"},
                {"text": ui_text(language, "menu_market_status"), "callback_data": "ux:status"},
            ],
        ]
    elif section == "settings":
        rows = [
            [
                {"text": "Notifications" if language == "en" else "Уведомления", "callback_data": "ux:deliveryhub"},
                {"text": "Filters" if language == "en" else "Фильтры", "callback_data": "ux:setup"},
            ],
            [
                {"text": "Workspace" if language == "en" else "Профиль", "callback_data": "ux:workspacehub"},
                {"text": ui_text(language, "menu_change_language"), "callback_data": "ux:language:picker:settings"},
            ],
            [
                {"text": "Watchlists" if language == "en" else "Вотчлисты", "callback_data": "ux:watchhub"},
                {"text": ui_text(language, "menu_market_status"), "callback_data": "ux:status"},
            ],
        ]
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback_data,
            home_callback_data=home_callback_data,
        )
    )
    return {"inline_keyboard": rows}


def build_gold_hub_keyboard(
    *,
    language_code: str,
    gold_alerts_enabled: bool,
    gold_web_url: str,
    strategy_states: list[tuple[str, bool]] | None = None,
    back_callback_data: str | None = None,
    home_callback_data: str = "ux:menu",
) -> dict[str, object]:
    language = normalize_language(language_code)
    states = {key: enabled for key, enabled in (strategy_states or [])}
    rows: list[list[dict[str, object]]] = [
        [
            {"text": premium_text(language, "menu_gold_card"), "callback_data": "ux:goldview"},
            {
                "text": premium_text(language, "menu_gold_alerts_on" if gold_alerts_enabled else "menu_gold_alerts_off"),
                "callback_data": "ux:gold:hub",
            },
        ],
        [
            {
                "text": _selected_label(_product_strategy_label("gold_breakout", language_code=language), states.get("gold_breakout", False)),
                "callback_data": "ux:strategy:toggle:gold_breakout",
            },
            {
                "text": _selected_label(_product_strategy_label("gold_pullback", language_code=language), states.get("gold_pullback", False)),
                "callback_data": "ux:strategy:toggle:gold_pullback",
            },
        ],
        [
            {
                "text": _selected_label(_product_strategy_label("gold_liquidity", language_code=language), states.get("gold_liquidity", False)),
                "callback_data": "ux:strategy:toggle:gold_liquidity",
            },
            {"text": "📬 Delivery Rules" if language == "en" else "📬 Правила доставки", "callback_data": "ux:deliveryrules"},
        ],
        [
            {"text": "🥇 Gold Setup Wizard" if language == "en" else "🥇 Мастер Gold Setup", "callback_data": "ux:goldwizard:start"},
            {"text": "Gold Results" if language == "en" else "Результаты Gold", "callback_data": "strategy:results:gold"},
        ],
        [
            {"text": "Gold Guide" if language == "en" else "Гайд по Gold", "callback_data": "learn:gold"},
            {"text": premium_text(language, "menu_gold_link"), "url": gold_web_url},
        ],
    ]
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback_data,
            home_callback_data=home_callback_data,
        )
    )
    return {"inline_keyboard": rows}


def build_watchlist_themes_keyboard(
    *,
    language_code: str,
    saved_themes: list[tuple[int, str]],
    back_callback_data: str | None = None,
    home_callback_data: str = "ux:menu",
) -> dict[str, object]:
    language = normalize_language(language_code)
    primary_theme_id = saved_themes[0][0] if saved_themes else None
    rows: list[list[dict[str, object]]] = [
        [
            {"text": premium_text(language, "theme_majors"), "callback_data": "ux:theme:builtin:majors"},
            {"text": premium_text(language, "theme_memes"), "callback_data": "ux:theme:builtin:memes"},
        ],
        [
            {"text": premium_text(language, "theme_gold"), "callback_data": "ux:theme:builtin:gold"},
            {"text": premium_text(language, "theme_custom"), "callback_data": "ux:theme:builtin:custom"},
        ],
        [
            {"text": "Saved Themes" if language == "en" else "Сохранённые темы", "callback_data": "ux:themes"},
            {"text": premium_text(language, "menu_save_theme"), "callback_data": "ux:theme:save"},
        ],
    ]
    for theme_id, theme_name in saved_themes[:4]:
        rows.append([{"text": theme_name, "callback_data": f"ux:theme:open:{theme_id}"}])
    if primary_theme_id is not None:
        rows.extend(
            [
                [
                    {"text": premium_text(language, "menu_rename_theme"), "callback_data": f"ux:theme:rename:{primary_theme_id}"},
                    {"text": premium_text(language, "menu_delete_theme"), "callback_data": f"ux:theme:delete:{primary_theme_id}"},
                ],
                [
                    {"text": premium_text(language, "menu_add_to_theme"), "callback_data": f"ux:theme:add:{primary_theme_id}"},
                    {"text": "Open Theme" if language == "en" else "Открыть тему", "callback_data": f"ux:theme:open:{primary_theme_id}"},
                ],
            ]
        )
    rows.append(
        [
            {"text": ui_text(language, "menu_current_watchlist"), "callback_data": "ux:watchlist"},
            {"text": "Open Filters" if language == "en" else "Открыть фильтры", "callback_data": "ux:setup"},
        ]
    )
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback_data,
            home_callback_data=home_callback_data,
        )
    )
    return {"inline_keyboard": rows}


def build_onboarding_step_keyboard(
    *,
    language_code: str,
    step: str,
    include_gold: bool,
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows: list[list[dict[str, object]]] = []
    if step == "language":
        rows = [
            [
                {"text": "English", "callback_data": "ux:onboard:language:en"},
                {"text": "Русский", "callback_data": "ux:onboard:language:ru"},
            ]
        ]
    elif step == "style":
        rows = [
            [
                {"text": ui_text(language, "setup_conservative"), "callback_data": "ux:onboard:style:conservative"},
                {"text": ui_text(language, "setup_balanced"), "callback_data": "ux:onboard:style:balanced"},
                {"text": ui_text(language, "setup_aggressive"), "callback_data": "ux:onboard:style:aggressive"},
            ]
        ]
    elif step == "direction":
        rows = [
            [
                {"text": ui_text(language, "setup_both"), "callback_data": "ux:onboard:direction:both"},
                {"text": ui_text(language, "setup_long_only"), "callback_data": "ux:onboard:direction:long"},
                {"text": ui_text(language, "setup_short_only"), "callback_data": "ux:onboard:direction:short"},
            ]
        ]
    elif step == "symbols":
        rows = [
            [
                {"text": "BTC", "callback_data": "ux:onboard:symbols:BTC"},
                {"text": "ETH", "callback_data": "ux:onboard:symbols:ETH"},
                {"text": "SOL", "callback_data": "ux:onboard:symbols:SOL"},
            ],
            [
                {"text": "XAUUSD", "callback_data": "ux:onboard:symbols:XAUUSD"},
                {"text": premium_text(language, "onboarding_use_suggestions"), "callback_data": "ux:onboard:symbols:use-defaults"},
            ],
            [
                {"text": premium_text(language, "onboarding_skip"), "callback_data": "ux:onboard:symbols:skip"},
                {"text": premium_text(language, "onboarding_clear"), "callback_data": "ux:onboard:symbols:clear"},
            ],
        ]
    elif step == "universe":
        rows = [
            [
                {"text": ui_text(language, "setup_all_symbols"), "callback_data": "ux:onboard:universe:all"},
                {"text": ui_text(language, "setup_watchlist_only"), "callback_data": "ux:onboard:universe:watchlist"},
            ]
        ]
    elif step == "delivery":
        rows = [
            [
                {"text": premium_text(language, "delivery_mode_instant"), "callback_data": "ux:onboard:delivery:instant"},
                {"text": premium_text(language, "delivery_mode_digest"), "callback_data": "ux:onboard:delivery:digest"},
                {"text": premium_text(language, "delivery_mode_quiet"), "callback_data": "ux:onboard:delivery:quiet"},
            ]
        ]
    elif step == "followups":
        rows = [
            [
                {"text": ui_text(language, "status_on"), "callback_data": "ux:onboard:followups:on"},
                {"text": ui_text(language, "status_off"), "callback_data": "ux:onboard:followups:off"},
            ]
        ]
    elif step == "gold" and include_gold:
        rows = [
            [
                {"text": ui_text(language, "status_on"), "callback_data": "ux:onboard:gold:on"},
                {"text": ui_text(language, "status_off"), "callback_data": "ux:onboard:gold:off"},
            ]
        ]
    elif step == "quiet_hours":
        rows = [
            [
                {"text": premium_text(language, "quiet_hours_off"), "callback_data": "ux:onboard:quiet_hours:off"},
                {"text": premium_text(language, "quiet_hours_late"), "callback_data": "ux:onboard:quiet_hours:late"},
                {"text": premium_text(language, "quiet_hours_overnight"), "callback_data": "ux:onboard:quiet_hours:overnight"},
            ]
        ]
    elif step == "summary":
        rows = [
            [
                {"text": premium_text(language, "menu_start_signals"), "callback_data": "ux:onboard:done:start"},
            ],
            [
                {"text": premium_text(language, "menu_delivery_edit"), "callback_data": "ux:deliveryhub"},
                {"text": premium_text(language, "menu_edit_watchlist"), "callback_data": "ux:watchhub"},
            ],
            [
                {"text": ui_text(language, "menu_home"), "callback_data": "ux:menu"},
            ],
        ]
    if step != "summary":
        rows.append([{"text": premium_text(language, "onboarding_skip"), "callback_data": f"ux:onboard:{step}:skip"}])
    return {"inline_keyboard": rows}


def build_onboarding_step_keyboard(
    *,
    language_code: str,
    step: str,
    include_gold: bool,
    strategy_key: str | None = None,
    draft: dict[str, object] | None = None,
) -> dict[str, object]:
    language = normalize_language(language_code)
    strategy = resolve_quick_setup_strategy_key(strategy_key)
    current_draft = {**(draft or {})}
    rows: list[list[dict[str, object]]] = []
    current_steps = onboarding_steps(include_gold=include_gold, strategy_key=strategy)
    previous_step = previous_onboarding_step(step, include_gold=include_gold, strategy_key=strategy)
    selected_profile = str(current_draft.get("signal_profile") or "balanced")
    selected_rsi_mode = str(current_draft.get("rsi_mode") or "balanced")
    selected_volume = (
        int(float(current_draft.get("min_quote_volume") or 0.0))
        if isinstance(current_draft.get("min_quote_volume"), (int, float))
        else 0
    )
    selected_direction = str(current_draft.get("direction_filter") or "both")
    watchlist_only = bool(current_draft.get("watchlist_only", False))

    if step == "preset":
        rows = [[
            {
                "text": _selected_label(strategy_preset_label(strategy, profile_key, language_code=language), selected_profile == profile_key),
                "callback_data": f"ux:onboard:preset:{profile_key}",
            }
            for profile_key in ("conservative", "balanced", "aggressive")
        ]]
    elif step == "rsi_mode" and strategy_supports_rsi_mode(strategy):
        rows = [[
            {"text": _selected_label(ui_text(language, "setup_rsi_tight"), selected_rsi_mode == "tight"), "callback_data": "ux:onboard:rsi_mode:tight"},
            {"text": _selected_label(ui_text(language, "setup_rsi_balanced"), selected_rsi_mode == "balanced"), "callback_data": "ux:onboard:rsi_mode:balanced"},
            {"text": _selected_label(ui_text(language, "setup_rsi_early"), selected_rsi_mode == "early"), "callback_data": "ux:onboard:rsi_mode:early"},
        ]]
    elif step == "volume" and strategy_supports_volume(strategy):
        rows = [
            [
                {
                    "text": _selected_label(label, selected_volume == int(raw)),
                    "callback_data": f"ux:onboard:volume:{raw}",
                }
                for label, raw in volume_row
            ]
            for volume_row in (
                (("1M+", "1000000"), ("3M+", "3000000"), ("5M+", "5000000")),
                (("8M+", "8000000"), ("10M+", "10000000"), ("12M+", "12000000")),
            )
        ]
    elif step == "direction":
        rows = [[
            {"text": _selected_label(ui_text(language, "setup_both"), selected_direction == "both"), "callback_data": "ux:onboard:direction:both"},
            {"text": _selected_label(ui_text(language, "setup_long_only"), selected_direction == "long"), "callback_data": "ux:onboard:direction:long"},
            {"text": _selected_label(ui_text(language, "setup_short_only"), selected_direction == "short"), "callback_data": "ux:onboard:direction:short"},
        ]]
    elif step == "symbols":
        rows = [
            [
                {"text": "BTC", "callback_data": "ux:onboard:symbols:BTC"},
                {"text": "ETH", "callback_data": "ux:onboard:symbols:ETH"},
                {"text": "SOL", "callback_data": "ux:onboard:symbols:SOL"},
            ],
            [
                {"text": premium_text(language, "onboarding_use_suggestions"), "callback_data": "ux:onboard:symbols:use-defaults"},
                {"text": premium_text(language, "onboarding_clear"), "callback_data": "ux:onboard:symbols:clear"},
            ],
            [
                {"text": premium_text(language, "onboarding_done"), "callback_data": "ux:onboard:symbols:done"},
                {"text": premium_text(language, "onboarding_skip"), "callback_data": "ux:onboard:symbols:skip"},
            ],
        ]
    elif step == "universe" and strategy_supports_universe(strategy):
        rows = [[
            {"text": _selected_label(ui_text(language, "setup_all_symbols"), not watchlist_only), "callback_data": "ux:onboard:universe:all"},
            {"text": _selected_label(ui_text(language, "setup_watchlist_only"), watchlist_only), "callback_data": "ux:onboard:universe:watchlist"},
        ]]
    elif step == "delivery":
        rows = [[
            {"text": premium_text(language, "delivery_mode_instant"), "callback_data": "ux:onboard:delivery:instant"},
            {"text": premium_text(language, "delivery_mode_digest"), "callback_data": "ux:onboard:delivery:digest"},
            {"text": premium_text(language, "delivery_mode_quiet"), "callback_data": "ux:onboard:delivery:quiet"},
        ]]
    elif step == "followups":
        rows = [[
            {"text": ui_text(language, "status_on"), "callback_data": "ux:onboard:followups:on"},
            {"text": ui_text(language, "status_off"), "callback_data": "ux:onboard:followups:off"},
        ]]
    elif step == "summary":
        rows = [
            [{"text": premium_text(language, "menu_start_signals"), "callback_data": "ux:onboard:summary:start"}],
            [
                {"text": premium_text(language, "menu_delivery_edit"), "callback_data": "ux:deliveryhub"},
                {"text": premium_text(language, "menu_edit_watchlist"), "callback_data": "ux:watchhub"},
            ],
        ]

    if step not in {"summary", "symbols"}:
        rows.append([{"text": premium_text(language, "onboarding_skip"), "callback_data": f"ux:onboard:{step}:skip"}])
    if step in current_steps and step != current_steps[0]:
        rows.append([{"text": ui_text(language, "menu_back"), "callback_data": f"ux:onboard:back:{previous_step}"}])
    if step == "summary":
        rows.extend(
            _footer_rows(
                language_code=language,
                back_callback_data=f"ux:onboard:back:{previous_step}",
                home_callback_data="ux:menu",
            )
        )
    return {"inline_keyboard": rows}


def build_onboarding_step_keyboard(
    *,
    language_code: str,
    step: str,
    include_gold: bool,
    strategy_key: str | None = None,
    draft: dict[str, object] | None = None,
) -> dict[str, object]:
    language = normalize_language(language_code)
    strategy = resolve_quick_setup_strategy_key(strategy_key)
    current_draft = {**(draft or {})}
    current_steps = onboarding_steps(include_gold=include_gold, strategy_key=strategy)
    first_step = current_steps[0] if current_steps else step
    previous_step = previous_onboarding_step(step, include_gold=include_gold, strategy_key=strategy)
    selected_profile = str(current_draft.get("signal_profile") or "balanced")
    selected_rsi_mode = str(current_draft.get("rsi_mode") or "balanced")
    selected_volume = (
        int(float(current_draft.get("min_quote_volume") or 0.0))
        if isinstance(current_draft.get("min_quote_volume"), (int, float))
        else 0
    )
    selected_direction = str(current_draft.get("direction_filter") or "both")
    watchlist_only = bool(current_draft.get("watchlist_only", False))
    suggested_symbols = strategy_symbol_suggestions(strategy)
    rows: list[list[dict[str, object]]] = []

    if step == "preset":
        rows = [[
            {
                "text": _selected_label(strategy_preset_label(strategy, profile_key, language_code=language), selected_profile == profile_key),
                "callback_data": f"ux:onboard:preset:{profile_key}",
            }
            for profile_key in ("conservative", "balanced", "aggressive")
        ]]
    elif step == "rsi_mode" and strategy_supports_rsi_mode(strategy):
        rows = [[
            {"text": _selected_label(ui_text(language, "setup_rsi_tight"), selected_rsi_mode == "tight"), "callback_data": "ux:onboard:rsi_mode:tight"},
            {"text": _selected_label(ui_text(language, "setup_rsi_balanced"), selected_rsi_mode == "balanced"), "callback_data": "ux:onboard:rsi_mode:balanced"},
            {"text": _selected_label(ui_text(language, "setup_rsi_early"), selected_rsi_mode == "early"), "callback_data": "ux:onboard:rsi_mode:early"},
        ]]
    elif step == "volume" and strategy_supports_volume(strategy):
        rows = [
            [
                {
                    "text": _selected_label(label, selected_volume == int(raw)),
                    "callback_data": f"ux:onboard:volume:{raw}",
                }
                for label, raw in volume_row
            ]
            for volume_row in (
                (("1M+", "1000000"), ("3M+", "3000000"), ("5M+", "5000000")),
                (("8M+", "8000000"), ("10M+", "10000000"), ("12M+", "12000000")),
            )
        ]
    elif step == "direction":
        rows = [[
            {"text": _selected_label(ui_text(language, "setup_both"), selected_direction == "both"), "callback_data": "ux:onboard:direction:both"},
            {"text": _selected_label(ui_text(language, "setup_long_only"), selected_direction == "long"), "callback_data": "ux:onboard:direction:long"},
            {"text": _selected_label(ui_text(language, "setup_short_only"), selected_direction == "short"), "callback_data": "ux:onboard:direction:short"},
        ]]
    elif step == "symbols":
        rows = [[{"text": symbol, "callback_data": f"ux:onboard:symbols:{symbol}"} for symbol in suggested_symbols[:3]]]
        if len(suggested_symbols) > 3:
            rows.append([{"text": suggested_symbols[3], "callback_data": f"ux:onboard:symbols:{suggested_symbols[3]}"}])
        rows.extend(
            [
                [
                    {"text": premium_text(language, "onboarding_use_suggestions"), "callback_data": "ux:onboard:symbols:use-defaults"},
                    {"text": premium_text(language, "onboarding_clear"), "callback_data": "ux:onboard:symbols:clear"},
                ],
                [
                    {"text": premium_text(language, "onboarding_done"), "callback_data": "ux:onboard:symbols:done"},
                    {"text": premium_text(language, "onboarding_skip"), "callback_data": "ux:onboard:symbols:skip"},
                ],
            ]
        )
    elif step == "universe" and strategy_supports_universe(strategy):
        rows = [[
            {"text": _selected_label(ui_text(language, "setup_all_symbols"), not watchlist_only), "callback_data": "ux:onboard:universe:all"},
            {"text": _selected_label(ui_text(language, "setup_watchlist_only"), watchlist_only), "callback_data": "ux:onboard:universe:watchlist"},
        ]]
    elif step == "delivery":
        rows = [[
            {"text": premium_text(language, "delivery_mode_instant"), "callback_data": "ux:onboard:delivery:instant"},
            {"text": premium_text(language, "delivery_mode_digest"), "callback_data": "ux:onboard:delivery:digest"},
            {"text": premium_text(language, "delivery_mode_quiet"), "callback_data": "ux:onboard:delivery:quiet"},
        ]]
    elif step == "followups":
        rows = [[
            {"text": ui_text(language, "status_on"), "callback_data": "ux:onboard:followups:on"},
            {"text": ui_text(language, "status_off"), "callback_data": "ux:onboard:followups:off"},
        ]]
    elif step == "summary":
        rows = [
            [{"text": premium_text(language, "menu_start_signals"), "callback_data": "ux:onboard:summary:start"}],
            [
                {"text": premium_text(language, "menu_delivery_edit"), "callback_data": "ux:deliveryhub"},
                {"text": premium_text(language, "menu_edit_watchlist"), "callback_data": "ux:watchhub"},
            ],
        ]

    if step not in {"summary", "symbols"}:
        rows.append([{"text": premium_text(language, "onboarding_skip"), "callback_data": f"ux:onboard:{step}:skip"}])
    back_callback = f"ux:onboard:back:{previous_step}" if step != first_step else "ux:setup"
    rows.extend(
        _footer_rows(
            language_code=language,
            back_callback_data=back_callback,
            home_callback_data="ux:menu",
        )
    )
    return {"inline_keyboard": rows}


def _product_strategy_label(strategy_key: str, *, language_code: str = "en") -> str:
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
        "gold_breakout": ("Gold Breakout", "Пробой золота"),
        "gold_pullback": ("Gold Pullback", "Откат по золоту"),
        "gold_liquidity": ("Gold Liquidity", "Ликвидность золота"),
    }
    english, russian = labels.get(strategy_key, labels["rsi"])
    return russian if language == "ru" else english


def build_product_strategy_hub_keyboard(
    *,
    strategy_key: str,
    strategy_enabled: bool,
    include_gold_shortcut: bool,
    language_code: str = "en",
) -> dict[str, object]:
    language = normalize_language(language_code)
    toggle_label = "🟢 Выключить стратегию" if strategy_enabled else "🟢 Включить стратегию"
    if language == "en":
        toggle_label = "🟢 Disable Strategy" if strategy_enabled else "🟢 Enable Strategy"
    if strategy_key == "gold":
        rows = [
            [
                {"text": "📡 Сигналы" if language == "ru" else "📡 Signals", "callback_data": strategy_signals_callback(strategy_key)},
                {"text": "🎛 Фильтры сигналов" if language == "ru" else "🎛 Signal Filters", "callback_data": strategy_filters_callback(strategy_key)},
            ],
            [
                {"text": "🔔 Уведомления" if language == "ru" else "🔔 Notifications", "callback_data": strategy_alerts_callback(strategy_key)},
                {"text": "⚡ Быстрая настройка" if language == "ru" else "⚡ Quick Setup", "callback_data": strategy_quicksetup_callback(strategy_key)},
            ],
            [
                {"text": "📊 Результаты" if language == "ru" else "📊 Results", "callback_data": strategy_results_callback(strategy_key)},
                {"text": "📘 Гайд по стратегии" if language == "ru" else "📘 Strategy Guide", "callback_data": strategy_guide_callback(strategy_key)},
            ],
            [
                {"text": "⚙️ Настройки" if language == "ru" else "⚙️ Settings", "callback_data": strategy_settings_callback(strategy_key)},
            ],
            [
                {"text": toggle_label, "callback_data": strategy_toggle_callback(strategy_key)},
            ],
        ]
    else:
        rows = [
            [
                {"text": "📡 Сигналы" if language == "ru" else "📡 Signals", "callback_data": strategy_signals_callback(strategy_key)},
                {"text": "🎛 Фильтры сигналов" if language == "ru" else "🎛 Signal Filters", "callback_data": strategy_filters_callback(strategy_key)},
            ],
            [
                {"text": "🔔 Уведомления" if language == "ru" else "🔔 Notifications", "callback_data": strategy_alerts_callback(strategy_key)},
                {"text": "⭐ Избранное" if language == "ru" else "⭐ Favorites", "callback_data": strategy_favorites_callback(strategy_key)},
            ],
            [
                {"text": "⚡ Быстрая настройка" if language == "ru" else "⚡ Quick Setup", "callback_data": strategy_quicksetup_callback(strategy_key)},
                {"text": "📊 Результаты" if language == "ru" else "📊 Results", "callback_data": strategy_results_callback(strategy_key)},
            ],
            [
                {"text": "🧠 AI анализ монеты" if language == "ru" else "🧠 AI Analyze Coin", "callback_data": "main:ai"},
                {"text": "📘 Гайд по стратегии" if language == "ru" else "📘 Strategy Guide", "callback_data": strategy_guide_callback(strategy_key)},
            ],
            [
                {"text": "⚙️ Настройки" if language == "ru" else "⚙️ Settings", "callback_data": strategy_settings_callback(strategy_key)},
            ],
            [
                {"text": toggle_label, "callback_data": strategy_toggle_callback(strategy_key)},
            ],
        ]
    if include_gold_shortcut:
        rows.append([{"text": "🥇 Золото / XAUUSD" if language == "ru" else "🥇 Gold / XAUUSD", "callback_data": "ux:goldhub"}])
    rows.extend(
        standard_nav_rows(
            back_callback_data=main_callback("strategies"),
            main_callback_data=main_callback("today"),
            language_code=language,
        )
    )
    return {"inline_keyboard": rows}


def build_strategies_hub_keyboard(
    *,
    is_admin: bool = False,
    language_code: str = "en",
    visible_strategy_keys: tuple[str, ...] | list[str] | None = None,
) -> dict[str, object]:
    del is_admin
    language = normalize_language(language_code)
    strategy_keys = list(
        visible_strategy_keys
        if visible_strategy_keys is not None
        else (
            "breakout",
            "trend_pullback",
            "rsi_bollinger_mr",
            "rsi_bollinger_touch",
            "daily_rsi_80",
            "vwap",
            "false_breakout",
            "rsi",
            "rsi_divergence",
            "ekek",
            "bollinger",
            "gold",
        )
    )
    dynamic_rows: list[list[dict[str, object]]] = []
    for index in range(0, len(strategy_keys), 2):
        row_items = strategy_keys[index:index + 2]
        dynamic_rows.append(
            [
                {"text": _product_strategy_label(strategy_key, language_code=language), "callback_data": strategy_callback("open", strategy_key)}
                for strategy_key in row_items
            ]
        )
    dynamic_rows.append(
        [
            {"text": "🆚 Сравнение стратегий" if language == "ru" else "🆚 Compare Strategies", "callback_data": compare_callback("hub")},
            {"text": "🧩 Профиль" if language == "ru" else "🧩 Workspace", "callback_data": "ux:workspacehub"},
        ]
    )
    dynamic_rows.extend(
        standard_nav_rows(
            back_callback_data=main_callback("today"),
            main_callback_data=main_callback("today"),
            third_callback_data=main_callback("help"),
            language_code=language,
        )
    )
    return {"inline_keyboard": dynamic_rows}
    rows: list[list[dict[str, object]]] = [
        [
            {"text": _product_strategy_label("breakout", language_code=language), "callback_data": strategy_callback("open", "breakout")},
            {"text": _product_strategy_label("trend_pullback", language_code=language), "callback_data": strategy_callback("open", "trend_pullback")},
        ],
        [
            {"text": _product_strategy_label("rsi_bollinger_mr", language_code=language), "callback_data": strategy_callback("open", "rsi_bollinger_mr")},
            {"text": _product_strategy_label("vwap", language_code=language), "callback_data": strategy_callback("open", "vwap")},
        ],
        [
            {"text": _product_strategy_label("false_breakout", language_code=language), "callback_data": strategy_callback("open", "false_breakout")},
            {"text": _product_strategy_label("rsi", language_code=language), "callback_data": strategy_callback("open", "rsi")},
        ],
        [
            {"text": _product_strategy_label("bollinger", language_code=language), "callback_data": strategy_callback("open", "bollinger")},
            {"text": _product_strategy_label("gold", language_code=language), "callback_data": strategy_callback("open", "gold")},
        ],
        [
            {"text": "🆚 Сравнение стратегий" if language == "ru" else "🆚 Compare Strategies", "callback_data": compare_callback("hub")},
            {"text": "🧩 Профиль" if language == "ru" else "🧩 Workspace", "callback_data": "ux:workspacehub"},
        ],
    ]
    rows.extend(
        standard_nav_rows(
            back_callback_data=main_callback("today"),
            main_callback_data=main_callback("today"),
            third_callback_data=main_callback("help"),
            language_code=language,
        )
    )
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
    rows: list[list[dict[str, object]]] = [
        [
            {"text": "📅 Итоги дня" if language == "ru" else "📅 Day Results", "callback_data": "ux:recap:daily"},
            {"text": "🗓 Итоги недели" if language == "ru" else "🗓 Week Results", "callback_data": "ux:recap:weekly"},
        ],
        [
            {"text": "📡 Жизненный цикл" if language == "ru" else "📡 Signal Lifecycle", "callback_data": lifecycle_hub_callback},
            {"text": "🟢 Свежие сигналы" if language == "ru" else "🟢 Fresh Signals", "callback_data": "ux:signals:fresh"},
        ],
        [
            {"text": "🧩 Стратегии" if language == "ru" else "🧩 Strategy Performance", "callback_data": compare_callback("hub")},
            {"text": "📈 Статус бота" if language == "ru" else "📈 Bot Status", "callback_data": "ux:status"},
        ],
    ]
    if is_admin:
        rows.append(
            [
                {"text": "🆚 Сравнить периоды" if language == "ru" else "🆚 Compare Periods", "callback_data": results_callback("admin")},
                {"text": "👑 Статистика админа" if language == "ru" else "👑 Admin Stats", "callback_data": results_callback("admin")},
            ]
        )
    rows.extend(
        standard_nav_rows(
            back_callback_data=back_callback,
            main_callback_data=main_callback("today"),
            third_callback_data=main_callback("help"),
            language_code=language,
        )
    )
    return {"inline_keyboard": rows}


def build_compare_hub_keyboard(*, is_admin: bool, language_code: str = "en") -> dict[str, object]:
    language = normalize_language(language_code)
    rows: list[list[dict[str, object]]] = [
        [
            {"text": "🧩 Все стратегии" if language == "ru" else "🧩 All Strategies", "callback_data": compare_callback("all")},
            {"text": "📈 Лучше для тренда" if language == "ru" else "📈 Best for Trend", "callback_data": compare_callback("trend")},
        ],
        [
            {"text": "↔️ Лучше для диапазона" if language == "ru" else "↔️ Best for Range", "callback_data": compare_callback("range")},
            {"text": "🥇 Лучше для золота" if language == "ru" else "🥇 Best for Gold", "callback_data": compare_callback("gold")},
        ],
        [
            {"text": "🔕 Меньше шума" if language == "ru" else "🔕 Low-Noise Picks", "callback_data": compare_callback("lownoise")},
            {"text": "⏱ Лучше по ТФ" if language == "ru" else "⏱ Best by Timeframe", "callback_data": compare_callback("timeframe")},
        ],
        [
            {"text": "🪙 Лучше по типу актива" if language == "ru" else "🪙 Best by Asset Type", "callback_data": compare_callback("assets")},
        ],
    ]
    if is_admin:
        rows.append([{"text": "👑 Статистика админа" if language == "ru" else "👑 Admin Stats", "callback_data": "compare:admin"}])
    rows.extend(
        standard_nav_rows(
            back_callback_data=main_callback("strategies"),
            main_callback_data=main_callback("today"),
            third_callback_data=main_callback("help"),
            language_code=language,
        )
    )
    return {"inline_keyboard": rows}


def build_learn_hub_keyboard(*, language_code: str = "en") -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [
        [
            {"text": "📡 Как работают сигналы" if language == "ru" else "📡 How Signals Work", "callback_data": learn_callback("signals")},
            {"text": "📘 Гайды по стратегиям" if language == "ru" else "📘 Strategy Guides", "callback_data": learn_callback("guides")},
        ],
        [
            {"text": "🛡️ Основы риска" if language == "ru" else "🛡️ Risk Basics", "callback_data": learn_callback("risk")},
            {"text": "👀 Как читать сигнал" if language == "ru" else "👀 How to Read a Signal", "callback_data": learn_callback("read_signal")},
        ],
        [
            {"text": "🔄 Гайд по What Changed" if language == "ru" else "🔄 What Changed Guide", "callback_data": learn_callback("what_changed")},
            {"text": "🧠 Гайд по AI Analysis" if language == "ru" else "🧠 AI Analysis Guide", "callback_data": learn_callback("ai_guide")},
        ],
        [
            {"text": "🥇 Гайд по золоту" if language == "ru" else "🥇 Gold Guide", "callback_data": learn_callback("gold")},
            {"text": "❓ FAQ", "callback_data": main_callback("help")},
        ],
    ]
    rows.extend(
        standard_nav_rows(
            back_callback_data=main_callback("today"),
            main_callback_data=main_callback("today"),
            third_callback_data=main_callback("help"),
            language_code=language,
        )
    )
    return {"inline_keyboard": rows}


def build_strategy_guides_keyboard(*, language_code: str = "en") -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [
        [
            {"text": _product_strategy_label("breakout", language_code=language), "callback_data": "learn:guide:breakout"},
            {"text": _product_strategy_label("trend_pullback", language_code=language), "callback_data": "learn:guide:trend_pullback"},
        ],
        [
            {"text": _product_strategy_label("rsi_bollinger_mr", language_code=language), "callback_data": "learn:guide:rsi_bollinger_mr"},
            {"text": _product_strategy_label("rsi_bollinger_touch", language_code=language), "callback_data": "learn:guide:rsi_bollinger_touch"},
        ],
        [
            {"text": _product_strategy_label("daily_rsi_80", language_code=language), "callback_data": "learn:guide:daily_rsi_80"},
            {"text": _product_strategy_label("vwap", language_code=language), "callback_data": "learn:guide:vwap"},
        ],
        [
            {"text": _product_strategy_label("false_breakout", language_code=language), "callback_data": "learn:guide:false_breakout"},
            {"text": _product_strategy_label("rsi", language_code=language), "callback_data": "learn:guide:rsi"},
            {"text": _product_strategy_label("rsi_divergence", language_code=language), "callback_data": "learn:guide:rsi_divergence"},
        ],
        [
            {"text": _product_strategy_label("ekek", language_code=language), "callback_data": "learn:guide:ekek"},
            {"text": _product_strategy_label("bollinger", language_code=language), "callback_data": "learn:guide:bollinger"},
            {"text": _product_strategy_label("gold", language_code=language), "callback_data": "learn:guide:gold"},
        ],
    ]
    rows.extend(
        standard_nav_rows(
            back_callback_data=learn_callback("hub"),
            main_callback_data=main_callback("today"),
            third_callback_data=main_callback("help"),
            language_code=language,
        )
    )
    return {"inline_keyboard": rows}


def build_lifecycle_hub_keyboard(*, strategy_code: str | None = None, language_code: str = "en") -> dict[str, object]:
    language = normalize_language(language_code)
    if strategy_code:
        open_callback = f"strategy:lifecycle:{strategy_code}:open"
        confirmed_callback = f"strategy:lifecycle:{strategy_code}:confirmed"
        invalidated_callback = f"strategy:lifecycle:{strategy_code}:invalidated"
        closed_callback = f"strategy:lifecycle:{strategy_code}:closed"
        back_callback = strategy_results_callback(strategy_code)
    else:
        open_callback = lifecycle_callback("open")
        confirmed_callback = lifecycle_callback("confirmed")
        invalidated_callback = lifecycle_callback("invalidated")
        closed_callback = lifecycle_callback("closed")
        back_callback = results_callback("hub")
    rows = [
        [
            {"text": "🟢 Открытые сигналы" if language == "ru" else "🟢 Open Signals", "callback_data": open_callback},
            {"text": "✅ Подтверждённые" if language == "ru" else "✅ Confirmed Signals", "callback_data": confirmed_callback},
        ],
        [
            {"text": "❌ Сломанные" if language == "ru" else "❌ Invalidated", "callback_data": invalidated_callback},
            {"text": "🏁 Закрытые результаты" if language == "ru" else "🏁 Closed Results", "callback_data": closed_callback},
        ],
        [
            {"text": "🟢 Свежие сигналы" if language == "ru" else "🟢 Fresh Signals", "callback_data": "ux:signals:fresh"},
            {"text": "📅 Итоги дня" if language == "ru" else "📅 Day Results", "callback_data": "ux:recap:daily"},
        ],
    ]
    rows.extend(
        standard_nav_rows(
            back_callback_data=back_callback,
            main_callback_data=main_callback("today"),
            third_callback_data=main_callback("help"),
            language_code=language,
        )
    )
    return {"inline_keyboard": rows}


def build_admin_stats_keyboard(*, back_callback_data: str, language_code: str = "en") -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [
        [
            {"text": "24ч" if language == "ru" else "Last 24h", "callback_data": "results:admin:1d"},
            {"text": "Последние 7д" if language == "ru" else "Last 7d", "callback_data": "results:admin:7d"},
        ],
        [
            {"text": "Последние 30д" if language == "ru" else "Last 30d", "callback_data": "results:admin:30d"},
            {"text": "За всё время" if language == "ru" else "All-time", "callback_data": "results:admin:all_time"},
        ]
    ]
    rows.extend(
        standard_nav_rows(
            back_callback_data=back_callback_data,
            main_callback_data=main_callback("today"),
            third_callback_data=main_callback("help"),
            language_code=language,
        )
    )
    return {"inline_keyboard": rows}


from src.userbot.polished_keyboards import (
    build_access_inline_keyboard as _final_build_access_inline_keyboard,
    build_analyze_symbol_inline_keyboard as _final_build_analyze_symbol_inline_keyboard,
    build_compare_hub_keyboard as _final_build_compare_hub_keyboard,
    build_help_more_inline_keyboard as _final_build_help_more_inline_keyboard,
    build_help_inline_keyboard as _final_build_help_inline_keyboard,
    build_learn_hub_keyboard as _final_build_learn_hub_keyboard,
    build_menu_hub_inline_keyboard as _final_build_menu_hub_inline_keyboard,
    build_results_hub_keyboard as _final_build_results_hub_keyboard,
    build_section_hub_keyboard as _final_build_section_hub_keyboard,
    build_settings_center_keyboard as _final_build_settings_center_keyboard,
    build_status_inline_keyboard as _final_build_status_inline_keyboard,
    build_watchlist_inline_keyboard as _final_build_watchlist_inline_keyboard,
    build_workspace_center_keyboard as _final_build_workspace_center_keyboard,
)

build_help_inline_keyboard = _final_build_help_inline_keyboard
build_help_more_inline_keyboard = _final_build_help_more_inline_keyboard
build_access_inline_keyboard = _final_build_access_inline_keyboard
build_status_inline_keyboard = _final_build_status_inline_keyboard
build_watchlist_inline_keyboard = _final_build_watchlist_inline_keyboard
build_analyze_symbol_inline_keyboard = _final_build_analyze_symbol_inline_keyboard
build_menu_hub_inline_keyboard = _final_build_menu_hub_inline_keyboard
build_settings_center_keyboard = _final_build_settings_center_keyboard
build_workspace_center_keyboard = _final_build_workspace_center_keyboard
build_results_hub_keyboard = _final_build_results_hub_keyboard
build_compare_hub_keyboard = _final_build_compare_hub_keyboard
build_learn_hub_keyboard = _final_build_learn_hub_keyboard
build_section_hub_keyboard = _final_build_section_hub_keyboard
