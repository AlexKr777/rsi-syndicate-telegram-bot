from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.core.utils import escape_html
from src.localization import normalize_language
from src.storage.models import UserSavedSetupRecord, UserStyleProfileRecord


def _footer_rows(
    *,
    language_code: str,
    back_callback_data: str | None = None,
    home_callback_data: str = "ux:menu",
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


def _state(enabled: bool, *, language_code: str) -> str:
    if normalize_language(language_code) == "ru":
        return "Вкл" if enabled else "Выкл"
    return "On" if enabled else "Off"


def _translate_quick_filter_label(label: str, *, language_code: str) -> str:
    if normalize_language(language_code) != "ru":
        return label
    mapping = {
        "High Conviction": "Высокая уверенность",
        "Low Noise": "Мало шума",
        "Trend Only": "Только тренд",
        "Range Only": "Только диапазон",
        "Breakout Only": "Только пробой",
        "Pullback Only": "Только откат",
        "Gold Only": "Только золото",
        "Watchlist Only": "Только вотчлист",
        "Fast Setups": "Быстрые сетапы",
        "Cleaner": "Чище",
        "Cleaner Flow": "Чище поток",
        "Aggressive": "Агрессивно",
        "Conservative": "Консервативно",
    }
    return mapping.get(label, label)


def format_personal_summary_message(*, language_code: str, summary) -> str:
    language = normalize_language(language_code)
    if language == "ru":
        lines = [
            "<b>📅 Дневная сводка</b>" if summary.period_label == "daily" else "<b>🗓 Недельная сводка</b>",
            "",
            "Твой реальный поток уведомлений за выбранный период.",
            "",
            f"Сетап: <b>{escape_html(summary.setup_name)}</b>",
            f"Подошло по текущим фильтрам: <b>{summary.matched}</b>",
            f"Доставлено тебе: <b>{summary.delivered}</b>",
            f"Сильных доставок: <b>{summary.strong_delivered}</b>",
            f"Вотчлист / избранное: <b>{summary.watchlist_matches}</b>",
            f"Отсеяно фильтрами: <b>{summary.filtered_out}</b>",
            f"Топ-стратегия: <b>{escape_html(summary.top_strategy or '—')}</b>",
            f"Топ-актив: <b>{escape_html(summary.most_active_asset or '—')}</b>",
            f"Золото: <b>{escape_html(summary.gold_activity)}</b>",
            "",
            f"<b>Коротко</b>\n{escape_html(summary.quick_read)}",
            "",
            f"<b>Что делать</b>\n{escape_html(summary.top_recommendation)}",
        ]
        if summary.change_note:
            lines.extend(["", f"<b>Что изменилось</b>\n{escape_html(summary.change_note)}"])
        return "\n".join(lines)

    lines = [
        "<b>📅 Daily Summary</b>" if summary.period_label == "daily" else "<b>🗓 Weekly Summary</b>",
        "",
        "Your real notification flow for the selected period.",
        "",
        f"Setup: <b>{escape_html(summary.setup_name)}</b>",
        f"Matched by current filters: <b>{summary.matched}</b>",
        f"Delivered to you: <b>{summary.delivered}</b>",
        f"Strong deliveries: <b>{summary.strong_delivered}</b>",
        f"Watchlist / favorites: <b>{summary.watchlist_matches}</b>",
        f"Filtered out: <b>{summary.filtered_out}</b>",
        f"Top strategy: <b>{escape_html(summary.top_strategy or '—')}</b>",
        f"Top asset: <b>{escape_html(summary.most_active_asset or '—')}</b>",
        f"Gold activity: <b>{escape_html(summary.gold_activity)}</b>",
        "",
        f"<b>Quick read</b>\n{escape_html(summary.quick_read)}",
        "",
        f"<b>Suggested action</b>\n{escape_html(summary.top_recommendation)}",
    ]
    if summary.change_note:
        lines.extend(["", f"<b>What changed</b>\n{escape_html(summary.change_note)}"])
    return "\n".join(lines)


def _delivery_value_label(value: str, *, language_code: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalize_language(language_code) == "ru":
        return {
            "instant": "Сразу",
            "digest": "Сводка",
            "off": "Выкл",
            "all": "Все",
            "important": "Только важные",
            "quiet": "Тихо",
            "normal": "Обычно",
            "morning_digest": "Утренняя сводка",
        }.get(normalized, str(value))
    return {
        "instant": "Instant",
        "digest": "Digest",
        "off": "Off",
        "all": "All",
        "important": "Important",
        "quiet": "Quiet",
        "normal": "Normal",
        "morning_digest": "Morning Digest",
    }.get(normalized, str(value))


def _delivery_rule_title(rule_key: str, *, language_code: str) -> str:
    if normalize_language(language_code) == "ru":
        return {
            "strong_signals": "🔥 Сильные сигналы",
            "watchlist_matches": "👀 Вотчлист",
            "medium_signals": "📉 Средние сигналы",
            "followups": "🔄 Фоллоу-апы",
            "gold_signals": "🥇 Золото",
            "overnight": "🌙 Ночной режим",
            "repeat_cooldown_hours": "🔁 Пауза повторов",
            "digest_frequency_hours": "📦 Частота сводки",
        }.get(rule_key, "📬 Правило доставки")
    return {
        "strong_signals": "🔥 Strong Signals",
        "watchlist_matches": "👀 Watchlist Matches",
        "medium_signals": "📉 Medium Signals",
        "followups": "🔄 Follow-Ups",
        "gold_signals": "🥇 Gold Signals",
        "overnight": "🌙 Overnight Logic",
        "repeat_cooldown_hours": "🔁 Repeat Cooldown",
        "digest_frequency_hours": "📦 Digest Frequency",
    }.get(rule_key, "📬 Delivery Rule")


def build_personalized_menu_hub_keyboard(
    *,
    language_code: str,
    display_mode: str = "pro",
    payment_label: str | None = None,
    quick_launch_label: str | None = None,
    quick_launch_callback_data: str | None = None,
) -> dict[str, object]:
    language = normalize_language(language_code)
    normalized_mode = "simple" if str(display_mode or "").strip().lower() == "simple" else "pro"
    labels = {
        "strong": "💥 Strong Setups" if language == "en" else "💥 Сильные сетапы",
        "fresh": "📡 Fresh Signals" if language == "en" else "📡 Свежие сигналы",
        "example": "🧾 Example Signal" if language == "en" else "🧾 Пример сигнала",
        "read": "📖 How to Read" if language == "en" else "📖 Как читать",
        "watchlist": "👀 Watchlist" if language == "en" else "👀 Вотчлист",
        "ai": "🤖 AI Desk" if language == "en" else "🤖 AI-разбор",
        "alerts": "🔔 Notifications" if language == "en" else "🔔 Уведомления",
        "setups": "🧩 Setups" if language == "en" else "🧩 Сетапы",
        "strategies": "📈 Strategies" if language == "en" else "📈 Стратегии",
        "results": "📊 Results" if language == "en" else "📊 Результаты",
        "filters": "🎯 Filters" if language == "en" else "🎯 Фильтры",
        "settings": "⚙️ Settings" if language == "en" else "⚙️ Настройки",
        "access": "💎 My Access" if language == "en" else "💎 Мой доступ",
        "refresh": "🔄 Refresh" if language == "en" else "🔄 Обновить",
        "help": "❓ Help" if language == "en" else "❓ Помощь",
        "referral": "🎁 Referral" if language == "en" else "🎁 Рефералы",
        "pro_mode": "🔧 Pro Mode" if language == "en" else "🔧 Pro-режим",
        "simple_mode": "⬅️ Back to Simple" if language == "en" else "⬅️ В простой режим",
        "delivery_rules": "📬 Delivery Rules" if language == "en" else "📬 Правила доставки",
        "lifecycle": "🔄 Lifecycle" if language == "en" else "🔄 Жизненный цикл",
        "compare": "⚖️ Compare" if language == "en" else "⚖️ Сравнение",
        "hide_mute": "🚫 Hide & Mute" if language == "en" else "🚫 Скрыть и заглушить",
        "signal_flow": "📡 Signal Flow" if language == "en" else "📡 Поток сигналов",
        "analytics": "🧠 Analytics" if language == "en" else "🧠 Аналитика",
        "flow_setup": "🧩 Flow Setup" if language == "en" else "🧩 Настройка потока",
        "system": "⚙️ System" if language == "en" else "⚙️ Система",
    }
    if normalized_mode == "simple":
        return {
            "inline_keyboard": [
                [
                    {"text": labels["strong"], "callback_data": "ux:signals:strong"},
                    {"text": labels["fresh"], "callback_data": "ux:signals:fresh"},
                ],
                [
                    {"text": labels["example"], "callback_data": "ux:welcome:example"},
                    {"text": labels["read"], "callback_data": "ux:welcome:read"},
                ],
                [
                    {"text": labels["results"], "callback_data": "main:results"},
                    {"text": labels["access"], "callback_data": "main:access"},
                ],
                [
                    {"text": labels["alerts"], "callback_data": "main:alerts"},
                    {"text": labels["help"], "callback_data": "main:help"},
                ],
                [
                    {"text": labels["pro_mode"], "callback_data": "ux:display:pro"},
                ],
            ]
        }
    rows: list[list[dict[str, object]]] = [
        [
            {"text": labels["signal_flow"], "callback_data": "ux:prohub:signals"},
            {"text": labels["analytics"], "callback_data": "ux:prohub:analytics"},
        ],
        [
            {"text": labels["flow_setup"], "callback_data": "ux:prohub:flow"},
            {"text": labels["watchlist"], "callback_data": "ux:prohub:watchlist"},
        ],
        [
            {"text": labels["results"], "callback_data": "ux:prohub:results"},
            {"text": labels["access"], "callback_data": "ux:prohub:access"},
        ],
        [
            {"text": labels["system"], "callback_data": "ux:prohub:system"},
            {"text": labels["simple_mode"], "callback_data": "ux:display:simple"},
        ],
    ]
    if quick_launch_label and quick_launch_callback_data:
        rows.append([{"text": quick_launch_label, "callback_data": quick_launch_callback_data}])
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


def format_pro_submenu_message(*, hub: str, language_code: str) -> str:
    language = normalize_language(language_code)
    normalized = str(hub or "").strip().lower()
    if language == "ru":
        content = {
            "signals": ("<b>📡 Поток сигналов</b>", "Свежие карточки, сильные сетапы и жизненный цикл сигнала."),
            "analytics": ("<b>🧠 Аналитика</b>", "AI-разбор, сравнение стратегий и обучающие экраны без лишнего шума."),
            "flow": ("<b>🧩 Настройка потока</b>", "Стратегии, фильтры, сохранённые сетапы и правила доставки."),
            "watchlist": ("<b>👀 Watchlist</b>", "Списки наблюдения, темы и ручный разбор тикера."),
            "results": ("<b>📊 Результаты</b>", "Итоги, follow-up, lifecycle и методология подсчёта."),
            "access": ("<b>💎 Доступ</b>", "Статус PRO+, сравнение Classic/PRO+, referral и помощь с доступом."),
            "system": ("<b>⚙️ Система</b>", "Настройки, уведомления, язык, статус бота и справка."),
        }.get(normalized, ("<b>🔧 Pro-раздел</b>", "Выбери следующий экран."))
        return f"{content[0]}\n\n{content[1]}"
    content = {
        "signals": ("<b>📡 Signal Flow</b>", "Fresh cards, strong setups, and the signal lifecycle in one place."),
        "analytics": ("<b>🧠 Analytics</b>", "AI review, strategy comparison, and learning screens without crowding the home screen."),
        "flow": ("<b>🧩 Flow Setup</b>", "Strategies, filters, saved setups, workspaces, and delivery rules."),
        "watchlist": ("<b>👀 Watchlist</b>", "Watchlists, themes, and manual ticker analysis."),
        "results": ("<b>📊 Results</b>", "Outcomes, follow-ups, lifecycle views, and result methodology."),
        "access": ("<b>💎 Access</b>", "PRO+ status, Classic/PRO+ comparison, referral, and access help."),
        "system": ("<b>⚙️ System</b>", "Settings, notifications, language, bot status, and support."),
    }.get(normalized, ("<b>🔧 Pro Section</b>", "Choose the next screen."))
    return f"{content[0]}\n\n{content[1]}"


def build_pro_submenu_keyboard(
    *,
    hub: str,
    language_code: str,
    payment_label: str | None = None,
    is_admin: bool = False,
) -> dict[str, object]:
    language = normalize_language(language_code)
    normalized = str(hub or "").strip().lower()
    labels = {
        "strong": "💥 Strong Setups" if language == "en" else "💥 Сильные сетапы",
        "fresh": "📡 Fresh Signals" if language == "en" else "📡 Свежие сигналы",
        "recent": "🕘 Recent Signals" if language == "en" else "🕘 Последние сигналы",
        "lifecycle": "🔄 Lifecycle" if language == "en" else "🔄 Жизненный цикл",
        "example": "🧾 Example Signal" if language == "en" else "🧾 Пример сигнала",
        "read": "📖 How to Read" if language == "en" else "📖 Как читать",
        "ai": "🤖 AI Desk" if language == "en" else "🤖 AI-разбор",
        "compare": "⚖️ Compare" if language == "en" else "⚖️ Сравнение",
        "strategies": "📈 Strategies" if language == "en" else "📈 Стратегии",
        "setups": "🧩 Setups" if language == "en" else "🧩 Сетапы",
        "filters": "🎯 Filters" if language == "en" else "🎯 Фильтры",
        "workspace": "🧩 Workspaces" if language == "en" else "🧩 Рабочие режимы",
        "delivery_rules": "📬 Delivery Rules" if language == "en" else "📬 Правила доставки",
        "hide_mute": "🚫 Hide & Mute" if language == "en" else "🚫 Скрыть и заглушить",
        "watchlist": "👀 Watchlist" if language == "en" else "👀 Вотчлист",
        "themes": "🎨 Themes" if language == "en" else "🎨 Темы",
        "results": "📊 Results" if language == "en" else "📊 Результаты",
        "daily": "📅 Daily Summary" if language == "en" else "📅 Дневная сводка",
        "weekly": "🗓 Weekly Summary" if language == "en" else "🗓 Недельная сводка",
        "method": "📐 Methodology" if language == "en" else "📐 Методология",
        "followup": "🧾 Example Follow-up" if language == "en" else "🧾 Пример follow-up",
        "access": "💎 My Access" if language == "en" else "💎 Мой доступ",
        "included": "💎 What's Included" if language == "en" else "💎 Что входит",
        "support": "🆘 Support" if language == "en" else "🆘 Поддержка",
        "referral": "🎁 Referral" if language == "en" else "🎁 Рефералы",
        "alerts": "🔔 Notifications" if language == "en" else "🔔 Уведомления",
        "settings": "⚙️ Settings" if language == "en" else "⚙️ Настройки",
        "commands": "⌨️ Commands" if language == "en" else "⌨️ Команды",
        "language": "🌍 Language" if language == "en" else "🌍 Язык",
        "status": "🟢 Bot Status" if language == "en" else "🟢 Статус бота",
        "health": "🩺 Health" if language == "en" else "🩺 Состояние",
        "back": "◀️ Pro Home" if language == "en" else "◀️ Pro-главная",
        "home": "🏠 Home" if language == "en" else "🏠 Главная",
    }
    if normalized == "signals":
        rows = [
            [
                {"text": labels["strong"], "callback_data": "ux:signals:strong"},
                {"text": labels["fresh"], "callback_data": "ux:signals:fresh"},
            ],
            [
                {"text": labels["recent"], "callback_data": "ux:signals:recent"},
                {"text": labels["lifecycle"], "callback_data": "lifecycle:hub"},
            ],
            [
                {"text": labels["example"], "callback_data": "ux:welcome:example"},
                {"text": labels["read"], "callback_data": "ux:welcome:read"},
            ],
        ]
    elif normalized == "analytics":
        rows = [
            [
                {"text": labels["ai"], "callback_data": "main:ai"},
                {"text": labels["compare"], "callback_data": "compare:hub"},
            ],
            [
                {"text": labels["read"], "callback_data": "ux:welcome:read"},
                {"text": labels["example"], "callback_data": "ux:welcome:example"},
            ],
        ]
    elif normalized == "flow":
        rows = [
            [
                {"text": labels["strategies"], "callback_data": "main:strategies"},
                {"text": labels["setups"], "callback_data": "main:setups"},
            ],
            [
                {"text": labels["filters"], "callback_data": "ux:filtershub"},
                {"text": labels["workspace"], "callback_data": "ux:workspacehub"},
            ],
            [
                {"text": labels["delivery_rules"], "callback_data": "ux:deliveryrules"},
                {"text": labels["hide_mute"], "callback_data": "ux:hidemute"},
            ],
        ]
    elif normalized == "watchlist":
        rows = [
            [
                {"text": labels["watchlist"], "callback_data": "ux:watchhub"},
                {"text": labels["themes"], "callback_data": "ux:themes"},
            ],
            [{"text": labels["ai"], "callback_data": "main:ai"}],
        ]
    elif normalized == "results":
        rows = [
            [
                {"text": labels["results"], "callback_data": "main:results"},
                {"text": labels["lifecycle"], "callback_data": "lifecycle:hub"},
            ],
            [
                {"text": labels["daily"], "callback_data": "ux:summary:daily"},
                {"text": labels["weekly"], "callback_data": "ux:summary:weekly"},
            ],
            [
                {"text": labels["compare"], "callback_data": "compare:hub"},
                {"text": labels["method"], "callback_data": "ux:help:results"},
            ],
            [{"text": labels["followup"], "callback_data": "ux:help:example_followup"}],
        ]
    elif normalized == "access":
        rows = [
            [
                {"text": labels["access"], "callback_data": "main:access"},
                {"text": labels["included"], "callback_data": "ux:help:access"},
            ],
            [
                {"text": "⚖️ Classic vs PRO+", "callback_data": "ux:help:compare"},
                {"text": labels["support"], "callback_data": "ux:help:support"},
            ],
            [{"text": labels["referral"], "callback_data": "ux:referral"}],
        ]
        if payment_label:
            rows.insert(0, [{"text": payment_label, "callback_data": "ux:pay"}])
    elif normalized == "system":
        rows = [
            [
                {"text": labels["settings"], "callback_data": "main:settings"},
                {"text": labels["alerts"], "callback_data": "main:alerts"},
            ],
            [
                {"text": labels["language"], "callback_data": "ux:language:picker:menu"},
                {"text": labels["status"], "callback_data": "ux:status"},
            ],
            [
                {"text": labels["commands"], "callback_data": "ux:help:commands"},
                {"text": labels["support"], "callback_data": "ux:help:support"},
            ],
        ]
        if is_admin:
            rows.append([{"text": labels["health"], "callback_data": "ux:health"}])
    else:
        rows = [[{"text": labels["home"], "callback_data": "ux:menu"}]]
    rows.extend(
        [
            [
                {"text": labels["back"], "callback_data": "ux:menu"},
                {"text": labels["home"], "callback_data": "main:today"},
            ]
        ]
    )
    return {"inline_keyboard": rows}


def format_setups_hub_message(
    *,
    language_code: str,
    active_setup_name: str | None,
    active_summary: str | None,
    setups_count: int,
    pinned_count: int,
    default_setup_name: str | None,
) -> str:
    language = normalize_language(language_code)
    if language == "ru":
        lines = [
            "<b>🧩 Сетапы</b>",
            "",
            "Твои сохранённые режимы сигнального потока.",
            "",
            f"Активный: <b>{escape_html(active_setup_name or 'Адаптивный')}</b>",
        ]
        if active_summary:
            lines.append(f"Профиль: <b>{escape_html(active_summary)}</b>")
        lines.extend(
            [
                f"Сохранено: <b>{setups_count}</b>",
                f"По умолчанию: <b>{escape_html(default_setup_name or 'Нет')}</b>",
                "",
                "Сохраняй текущий режим, запускай нужный в один тап и держи разные стили отдельно.",
            ]
        )
        return "\n".join(lines)
    lines = [
        "<b>🧩 Setups</b>",
        "",
        "Your saved signal modes.",
        "",
        f"Active: <b>{escape_html(active_setup_name or 'Adaptive')}</b>",
    ]
    if active_summary:
        lines.append(f"Profile: <b>{escape_html(active_summary)}</b>")
    lines.extend(
        [
            f"Saved: <b>{setups_count}</b>",
            f"Default: <b>{escape_html(default_setup_name or 'None')}</b>",
            "",
            "Save your current flow, relaunch it in one tap, and keep different trading styles separate.",
        ]
    )
    return "\n".join(lines)


def build_setups_hub_keyboard(
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
            {"text": "🪄 Setup Wizard" if language == "en" else "🪄 Мастер", "callback_data": "ux:onboard:start"},
        ],
    ]
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data))
    return {"inline_keyboard": rows}


def format_saved_setups_message(
    *,
    language_code: str,
    setups: Sequence[UserSavedSetupRecord],
    active_setup_id: int | None,
) -> str:
    language = normalize_language(language_code)
    if not setups:
        if language == "ru":
            return (
                "<b>🧩 Сохранённые сетапы</b>\n\n"
                "Пока пусто.\n\n"
                "Сохрани текущие фильтры и правила доставки, чтобы запускать свой режим в один тап."
            )
        return (
            "<b>🧩 Saved Setups</b>\n\n"
            "Nothing saved yet.\n\n"
            "Save your current filters and delivery rules to relaunch your flow in one tap."
        )
    title = "<b>🧩 Saved Setups</b>" if language == "en" else "<b>🧩 Сохранённые сетапы</b>"
    subtitle = (
        "Launch your preferred market mode in one tap."
        if language == "en"
        else "Запускай нужный рыночный режим в один тап."
    )
    lines = [title, "", subtitle, ""]
    for setup in setups[:10]:
        prefix = "🟢 " if active_setup_id == setup.id else "⭐ " if setup.is_pinned else "• "
        lines.append(f"{prefix}<b>{escape_html(setup.name)}</b>")
    return "\n".join(lines)


def build_saved_setups_keyboard(
    *,
    language_code: str,
    setups: Sequence[UserSavedSetupRecord],
    back_callback_data: str | None = None,
    only_pinned: bool = False,
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows: list[list[dict[str, object]]] = []
    if not setups:
        rows.append(
            [
                {
                    "text": "➕ Create Setup" if language == "en" else "➕ Создать сетап",
                    "callback_data": "ux:setup:create",
                },
            ]
        )
    for setup in setups[:12]:
        icon = "🟢" if setup.is_default else "⭐" if setup.is_pinned else "🧩"
        rows.append([{"text": f"{icon} {setup.name}", "callback_data": f"ux:setup:detail:{setup.id}"}])
    if not only_pinned:
        rows.append([{"text": "➕ Create" if language == "en" else "➕ Создать", "callback_data": "ux:setup:create"}])
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data))
    return {"inline_keyboard": rows}


def format_setup_detail_message(
    *,
    language_code: str,
    setup: UserSavedSetupRecord,
    summary: str,
    is_active: bool,
) -> str:
    language = normalize_language(language_code)
    status = "Active" if language == "en" else "Активен"
    if language == "ru":
        return (
            "<b>🧩 Сетап</b>\n\n"
            f"<b>{escape_html(setup.name)}</b>\n"
            f"Статус: <b>{status if is_active else 'Сохранён'}</b>\n"
            f"Сводка: <b>{escape_html(summary)}</b>\n"
            f"По умолчанию: <b>{'Да' if setup.is_default else 'Нет'}</b>\n"
            f"Закреплён: <b>{'Да' if setup.is_pinned else 'Нет'}</b>\n\n"
            "Активируй, обнови из текущих настроек или используй как базу для нового режима."
        )
    return (
        "<b>🧩 Setup Detail</b>\n\n"
        f"<b>{escape_html(setup.name)}</b>\n"
        f"Status: <b>{status if is_active else 'Saved'}</b>\n"
        f"Summary: <b>{escape_html(summary)}</b>\n"
        f"Default: <b>{'Yes' if setup.is_default else 'No'}</b>\n"
        f"Pinned: <b>{'Yes' if setup.is_pinned else 'No'}</b>\n\n"
        "Activate it, update it from your current settings, or use it as the base for another mode."
    )


def build_setup_detail_keyboard(
    *,
    language_code: str,
    setup_id: int,
    is_active: bool,
    is_pinned: bool,
    back_callback_data: str | None = None,
) -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [
        [
            {
                "text": "🟢 Active" if (language == "en" and is_active) else ("🟢 Активен" if is_active else ("▶️ Activate" if language == "en" else "▶️ Активировать")),
                "callback_data": f"ux:setup:activate:{setup_id}",
            },
            {
                "text": "✏️ Edit" if language == "en" else "✏️ Изменить",
                "callback_data": f"ux:setup:edit:{setup_id}",
            },
        ],
        [
            {
                "text": "✏️ Rename" if language == "en" else "✏️ Переименовать",
                "callback_data": f"ux:setup:rename:{setup_id}",
            },
            {
                "text": "📄 Duplicate" if language == "en" else "📄 Дублировать",
                "callback_data": f"ux:setup:duplicate:{setup_id}",
            },
        ],
        [
            {
                "text": "📌 Default" if language == "en" else "📌 По умолчанию",
                "callback_data": f"ux:setup:default:{setup_id}",
            },
            {
                "text": ("⭐ Unpin" if language == "en" else "⭐ Открепить") if is_pinned else ("⭐ Pin" if language == "en" else "⭐ Закрепить"),
                "callback_data": f"ux:setup:pin:{setup_id}",
            },
        ],
        [{"text": "🗑 Delete" if language == "en" else "🗑 Удалить", "callback_data": f"ux:setup:delete:{setup_id}"}],
    ]
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data or "ux:setup:list"))
    return {"inline_keyboard": rows}


def format_quick_filters_message(
    *,
    language_code: str,
    active_filters: Sequence[str],
    summary: str,
) -> str:
    language = normalize_language(language_code)
    localized_filters = [_translate_quick_filter_label(item, language_code=language) for item in active_filters]
    active_line = ", ".join(localized_filters) if localized_filters else ("None" if language == "en" else "Нет")
    if language == "ru":
        return (
            "<b>🎯 Быстрые фильтры</b>\n\n"
            "Быстро меняй характер потока без глубокой настройки.\n\n"
            f"Активно: <b>{escape_html(active_line)}</b>\n"
            f"Текущий профиль: <b>{escape_html(summary)}</b>\n\n"
            "Пресеты меняют реальные правила отбора, а не только вид кнопок."
        )
    return (
        "<b>🎯 Quick Filters</b>\n\n"
        "Fast ways to reshape your signal flow.\n\n"
        f"Active: <b>{escape_html(active_line)}</b>\n"
        f"Current profile: <b>{escape_html(summary)}</b>\n\n"
        "These presets change real filtering rules, not just labels."
    )


def build_quick_filters_keyboard(
    *,
    language_code: str,
    back_callback_data: str | None = None,
) -> dict[str, object]:
    language = normalize_language(language_code)
    labels = {
        "high_conviction": "🔥 High Conviction" if language == "en" else "🔥 Только сильные",
        "low_noise": "🔕 Low Noise" if language == "en" else "🔕 Меньше шума",
        "trend_only": "📈 Trend Only" if language == "en" else "📈 Только трендовые",
        "range_only": "↔️ Range Only" if language == "en" else "↔️ Только диапазонные",
        "breakout_only": "💥 Breakout Only" if language == "en" else "💥 Только пробои",
        "pullback_only": "🌊 Pullback Only" if language == "en" else "🌊 Только откаты",
        "gold_only": "🥇 Gold Only" if language == "en" else "🥇 Только золото",
        "watchlist_only": "👀 Watchlist Only" if language == "en" else "👀 Только вотчлист",
        "fast_setups": "⚡ Fast Setups" if language == "en" else "⚡ Быстрые идеи",
        "cleaner_setups": "🧘 Cleaner Flow" if language == "en" else "🧘 Чище поток",
        "aggressive": "🚀 Aggressive" if language == "en" else "🚀 Больше сигналов",
        "conservative": "🛡 Conservative" if language == "en" else "🛡 Осторожный режим",
        "noisehub": "🔕 Noise" if language == "en" else "🔕 Уровень шума",
        "scorehub": "📊 Score" if language == "en" else "📊 Порог качества",
        "sessionhub": "🕒 Session" if language == "en" else "🕒 Сессия",
        "save": "💾 Save as Setup" if language == "en" else "💾 Сохранить как сетап",
        "reset": "♻️ Reset" if language == "en" else "♻️ Сбросить",
    }
    rows = [
        [
            {"text": labels["high_conviction"], "callback_data": "ux:qf:apply:high_conviction"},
            {"text": labels["low_noise"], "callback_data": "ux:qf:apply:low_noise"},
        ],
        [
            {"text": labels["trend_only"], "callback_data": "ux:qf:apply:trend_only"},
            {"text": labels["range_only"], "callback_data": "ux:qf:apply:range_only"},
        ],
        [
            {"text": labels["breakout_only"], "callback_data": "ux:qf:apply:breakout_only"},
            {"text": labels["pullback_only"], "callback_data": "ux:qf:apply:pullback_only"},
        ],
        [
            {"text": labels["gold_only"], "callback_data": "ux:qf:apply:gold_only"},
            {"text": labels["watchlist_only"], "callback_data": "ux:qf:apply:watchlist_only"},
        ],
        [
            {"text": labels["fast_setups"], "callback_data": "ux:qf:apply:fast_setups"},
            {"text": labels["cleaner_setups"], "callback_data": "ux:qf:apply:cleaner_setups"},
        ],
        [
            {"text": labels["aggressive"], "callback_data": "ux:qf:apply:aggressive"},
            {"text": labels["conservative"], "callback_data": "ux:qf:apply:conservative"},
        ],
        [
            {"text": labels["noisehub"], "callback_data": "ux:noisehub"},
            {"text": labels["scorehub"], "callback_data": "ux:scorehub"},
        ],
        [
            {"text": labels["sessionhub"], "callback_data": "ux:sessionhub"},
            {"text": labels["save"], "callback_data": "ux:setup:savecurrent"},
        ],
        [{"text": labels["reset"], "callback_data": "ux:qf:reset"}],
    ]
    rows.extend(_footer_rows(language_code=language_code, back_callback_data=back_callback_data))
    return {"inline_keyboard": rows}


def format_noise_level_message(*, language_code: str, selected: str) -> str:
    language = normalize_language(language_code)
    selected_label = {
        "minimal": "Minimal" if language == "en" else "Минимум",
        "balanced": "Balanced" if language == "en" else "Баланс",
        "active": "Active" if language == "en" else "Активно",
    }.get(selected, selected)
    if language == "ru":
        return (
            "<b>🔕 Уровень шума</b>\n\n"
            "Выбери, насколько избирательным должен быть поток сигналов.\n\n"
            f"Сейчас: <b>{escape_html(selected_label)}</b>\n\n"
            "Минимум — только самые чистые идеи.\nБаланс — рабочий режим по умолчанию.\nАктивно — больше идей и больше шума."
        )
    return (
        "<b>🔕 Noise Level</b>\n\n"
        "Choose how selective your signal flow should be.\n\n"
        f"Current: <b>{escape_html(selected_label)}</b>\n\n"
        "Minimal keeps only the cleanest ideas.\nBalanced is the default working flow.\nActive gives you more setups and more noise."
    )


def build_noise_level_keyboard(*, language_code: str, selected: str, back_callback_data: str | None = None) -> dict[str, object]:
    language = normalize_language(language_code)
    options = [
        ("minimal", "🔕 Minimal" if language == "en" else "🔕 Минимум"),
        ("balanced", "⚖️ Balanced" if language == "en" else "⚖️ Баланс"),
        ("active", "⚡ Active" if language == "en" else "⚡ Активно"),
    ]
    rows = [
        [{"text": f"✅ {label}" if key == selected else label, "callback_data": f"ux:noise:{key}"}]
        for key, label in options
    ]
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data))
    return {"inline_keyboard": rows}


def format_score_filter_message(*, language_code: str, selected: str) -> str:
    language = normalize_language(language_code)
    labels = {
        "all": "All Signals" if language == "en" else "Все сигналы",
        "strong": "Strong Only" if language == "en" else "Только сильные",
        "high": "High Score" if language == "en" else "Высокий порог",
        "elite": "Elite Only" if language == "en" else "Только элитные",
    }
    if language == "ru":
        return (
            "<b>📊 Порог качества</b>\n\n"
            "Выбери, насколько сильным должен быть сетап до доставки.\n\n"
            f"Сейчас: <b>{escape_html(labels.get(selected, selected))}</b>"
        )
    return (
        "<b>📊 Score Filter</b>\n\n"
        "Choose how strong a setup must be before it reaches you.\n\n"
        f"Current: <b>{escape_html(labels.get(selected, selected))}</b>"
    )


def build_score_filter_keyboard(*, language_code: str, selected: str, back_callback_data: str | None = None) -> dict[str, object]:
    language = normalize_language(language_code)
    options = [
        ("all", "All Signals" if language == "en" else "Все сигналы"),
        ("strong", "Strong Only" if language == "en" else "Только сильные"),
        ("high", "High Score" if language == "en" else "Высокий порог"),
        ("elite", "Elite Only" if language == "en" else "Только элитные"),
    ]
    rows = [
        [{"text": f"✅ {label}" if key == selected else label, "callback_data": f"ux:score:{key}"}]
        for key, label in options
    ]
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data))
    return {"inline_keyboard": rows}


def format_session_filter_message(*, language_code: str, selected: str) -> str:
    language = normalize_language(language_code)
    labels = {
        "asia": "Asia" if language == "en" else "Азия",
        "london": "London" if language == "en" else "Лондон",
        "new_york": "New York" if language == "en" else "Нью-Йорк",
        "overlap": "Overlap" if language == "en" else "Перекрытие",
        "all_day": "All Day" if language == "en" else "Весь день",
    }
    if language == "ru":
        return (
            "<b>🕒 Сессия</b>\n\n"
            "Выбери, когда сетап должен фокусироваться на рыночной активности.\n\n"
            f"Сейчас: <b>{escape_html(labels.get(selected, selected))}</b>"
        )
    return (
        "<b>🕒 Session Filter</b>\n\n"
        "Choose when your setup should focus on market activity.\n\n"
        f"Current: <b>{escape_html(labels.get(selected, selected))}</b>"
    )


def build_session_filter_keyboard(*, language_code: str, selected: str, back_callback_data: str | None = None) -> dict[str, object]:
    language = normalize_language(language_code)
    options = [
        ("asia", "🌏 Asia" if language == "en" else "🌏 Азия"),
        ("london", "🇬🇧 London" if language == "en" else "🇬🇧 Лондон"),
        ("new_york", "🇺🇸 New York" if language == "en" else "🇺🇸 Нью-Йорк"),
        ("overlap", "🔄 Overlap" if language == "en" else "🔄 Перекрытие"),
        ("all_day", "🕓 All Day" if language == "en" else "🕓 Весь день"),
    ]
    rows = []
    for idx in range(0, len(options), 2):
        row = []
        for key, label in options[idx:idx + 2]:
            row.append({"text": f"✅ {label}" if key == selected else label, "callback_data": f"ux:session:{key}"})
        rows.append(row)
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data))
    return {"inline_keyboard": rows}


def format_delivery_rules_message(*, language_code: str, rules: dict[str, Any]) -> str:
    language = normalize_language(language_code)
    overnight = "Quiet" if str(rules.get("overnight")) == "quiet" else "Normal"
    if language == "ru":
        return (
            "<b>📬 Правила доставки</b>\n\n"
            "Здесь ты сможешь настроить, как к тебе будут приходить разные типы сигналов.\n\n"
            f"Сильные: <b>{escape_html(_delivery_value_label(str(rules.get('strong_signals', 'instant')), language_code=language))}</b>\n"
            f"Вотчлист: <b>{escape_html(_delivery_value_label(str(rules.get('watchlist_matches', 'instant')), language_code=language))}</b>\n"
            f"Средние: <b>{escape_html(_delivery_value_label(str(rules.get('medium_signals', 'digest')), language_code=language))}</b>\n"
            f"Фоллоу-апы: <b>{escape_html(_delivery_value_label(str(rules.get('followups', 'important')), language_code=language))}</b>\n"
            f"Золото: <b>{escape_html(_delivery_value_label(str(rules.get('gold_signals', 'instant')), language_code=language))}</b>\n"
            f"Ночь: <b>{'Тихо' if overnight == 'Quiet' else 'Обычно'}</b>\n"
            f"Повторы: <b>{int(rules.get('repeat_cooldown_hours', 8) or 0)}h</b>\n"
            f"Сводка: <b>{int(rules.get('digest_frequency_hours', 1) or 1)}h</b>"
        )
    return (
        "<b>📬 Delivery Rules</b>\n\n"
        "Decide how different types of signals reach you.\n\n"
        f"Strong: <b>{escape_html(str(rules.get('strong_signals', 'instant')).title())}</b>\n"
        f"Watchlist: <b>{escape_html(str(rules.get('watchlist_matches', 'instant')).title())}</b>\n"
        f"Medium: <b>{escape_html(str(rules.get('medium_signals', 'digest')).title())}</b>\n"
        f"Follow-Ups: <b>{escape_html(str(rules.get('followups', 'important')).title())}</b>\n"
        f"Gold: <b>{escape_html(str(rules.get('gold_signals', 'instant')).title())}</b>\n"
        f"Overnight: <b>{overnight}</b>\n"
        f"Repeat Cooldown: <b>{int(rules.get('repeat_cooldown_hours', 8) or 0)}h</b>\n"
        f"Digest: <b>{int(rules.get('digest_frequency_hours', 1) or 1)}h</b>"
    )


def build_delivery_rules_keyboard(*, language_code: str, back_callback_data: str | None = None) -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [
        [
            {"text": "🔥 Strong" if language == "en" else "🔥 Сильные", "callback_data": "ux:deliveryruleview:strong_signals"},
            {"text": "👀 Watchlist" if language == "en" else "👀 Вотчлист", "callback_data": "ux:deliveryruleview:watchlist_matches"},
        ],
        [
            {"text": "📉 Medium" if language == "en" else "📉 Средние", "callback_data": "ux:deliveryruleview:medium_signals"},
            {"text": "🔄 Follow-Ups" if language == "en" else "🔄 Фоллоу-апы", "callback_data": "ux:deliveryruleview:followups"},
        ],
        [
            {"text": "🥇 Gold" if language == "en" else "🥇 Золото", "callback_data": "ux:deliveryruleview:gold_signals"},
            {"text": "🌙 Overnight" if language == "en" else "🌙 Ночь", "callback_data": "ux:deliveryruleview:overnight"},
        ],
        [
            {"text": "🔁 Cooldown" if language == "en" else "🔁 Повторы", "callback_data": "ux:deliveryruleview:repeat_cooldown_hours"},
            {"text": "📦 Digest" if language == "en" else "📦 Сводка", "callback_data": "ux:deliveryruleview:digest_frequency_hours"},
        ],
    ]
    rows.extend(_footer_rows(language_code=language_code, back_callback_data=back_callback_data))
    return {"inline_keyboard": rows}


def format_delivery_rule_options_message(*, language_code: str, rule_key: str, current_value: str) -> str:
    title = _delivery_rule_title(rule_key, language_code=language_code)
    helper_map_ru = {
        "strong_signals": "Выбери, как доставлять самые сильные сетапы.",
        "watchlist_matches": "Это правила для совпадений по твоему вотчлисту и избранному.",
        "medium_signals": "Эти сигналы слабее, поэтому их можно отправлять мягче.",
        "followups": "Реши, сколько follow-up обновлений получать по уже открытым идеям.",
        "gold_signals": "Отдельные правила для сигналов по золоту.",
        "overnight": "Определи, что делать ночью: обычный поток или тише.",
        "repeat_cooldown_hours": "Ограничь, как часто бот может повторять один и тот же актив.",
        "digest_frequency_hours": "Как часто собирать и присылать сводку.",
    }
    helper_map_en = {
        "strong_signals": "Choose how your strongest setups should reach you.",
        "watchlist_matches": "These rules apply to watchlist and favorites matches.",
        "medium_signals": "These setups are softer, so delivery can be gentler too.",
        "followups": "Choose how many follow-up updates you want after the first alert.",
        "gold_signals": "Separate delivery rules for gold signals.",
        "overnight": "Decide what happens overnight: normal flow or quieter routing.",
        "repeat_cooldown_hours": "Limit how often the bot can repeat the same asset.",
        "digest_frequency_hours": "Choose how often grouped digests should arrive.",
    }
    if normalize_language(language_code) == "ru":
        helper = helper_map_ru.get(rule_key, "Выбери понятный режим для этого типа сигнала.")
        return (
            f"<b>{title}</b>\n\n"
            f"{escape_html(helper)}\n\n"
            f"Сейчас: <b>{escape_html(_delivery_value_label(current_value, language_code=language_code))}</b>"
        )
    helper = helper_map_en.get(rule_key, "Choose the clearest routing mode for this signal type.")
    return (
        f"<b>{title}</b>\n\n"
        f"{escape_html(helper)}\n\n"
        f"Current: <b>{escape_html(_delivery_value_label(current_value, language_code=language_code))}</b>"
    )


def build_delivery_rule_options_keyboard(
    *,
    language_code: str,
    rule_key: str,
    back_callback_data: str | None = None,
) -> dict[str, object]:
    language = normalize_language(language_code)
    options_map: dict[str, list[tuple[str, str]]] = {
        "strong_signals": [("instant", "⚡ Instant" if language == "en" else "⚡ Сразу"), ("digest", "📦 Digest" if language == "en" else "📦 Сводка"), ("off", "🚫 Off" if language == "en" else "🚫 Выкл")],
        "watchlist_matches": [("instant", "⚡ Instant" if language == "en" else "⚡ Сразу"), ("digest", "📦 Digest" if language == "en" else "📦 Сводка"), ("off", "🚫 Off" if language == "en" else "🚫 Выкл")],
        "medium_signals": [("instant", "⚡ Instant" if language == "en" else "⚡ Сразу"), ("digest", "📦 Digest" if language == "en" else "📦 Сводка"), ("off", "🚫 Off" if language == "en" else "🚫 Выкл")],
        "gold_signals": [("instant", "⚡ Instant" if language == "en" else "⚡ Сразу"), ("digest", "📦 Digest" if language == "en" else "📦 Сводка"), ("off", "🚫 Off" if language == "en" else "🚫 Выкл")],
        "followups": [("all", "🟢 All" if language == "en" else "🟢 Все"), ("important", "⭐ Important" if language == "en" else "⭐ Важные"), ("digest", "📦 Digest" if language == "en" else "📦 Сводка"), ("off", "🚫 Off" if language == "en" else "🚫 Выкл")],
        "overnight": [("quiet", "🌙 Quiet" if language == "en" else "🌙 Тихо"), ("normal", "☀️ Normal" if language == "en" else "☀️ Обычно")],
        "repeat_cooldown_hours": [("0", "Off" if language == "en" else "Выкл"), ("4", "4h"), ("8", "8h"), ("24", "24h")],
        "digest_frequency_hours": [("1", "1h"), ("4", "4h"), ("8", "8h")],
    }
    options = options_map.get(rule_key, [])
    rows: list[list[dict[str, object]]] = []
    for idx in range(0, len(options), 2):
        row = []
        for value, label in options[idx:idx + 2]:
            row.append({"text": label, "callback_data": f"ux:deliveryrule:{rule_key}:{value}"})
        rows.append(row)
    rows.extend(_footer_rows(language_code=language_code, back_callback_data=back_callback_data or "ux:deliveryrules"))
    return {"inline_keyboard": rows}


def format_hide_mute_message(*, language_code: str, personalization: dict[str, Any]) -> str:
    language = normalize_language(language_code)
    hidden = personalization.get("hidden") if isinstance(personalization.get("hidden"), dict) else {}
    if language == "ru":
        return (
            "<b>🚫 Скрыть и приглушить</b>\n\n"
            "Убирай лишний шум без удаления данных.\n\n"
            f"Скрытые активы: <b>{len(hidden.get('symbols', []))}</b>\n"
            f"Скрытые стратегии: <b>{len(hidden.get('strategies', []))}</b>\n"
            f"Скрытые ТФ: <b>{len(hidden.get('timeframes', []))}</b>\n"
            f"Слабые фоллоу-апы: <b>{_state(bool(hidden.get('hide_weak_followups')), language_code=language)}</b>\n"
            f"Средние сигналы: <b>{_state(bool(hidden.get('hide_medium_score')), language_code=language)}</b>\n"
            f"Повторы: <b>{int(hidden.get('mute_repeats_hours', 0) or 0)}h</b>"
        )
    return (
        "<b>🚫 Hide & Mute</b>\n\n"
        "Reduce noise by hiding what you do not want to see.\n\n"
        f"Hidden assets: <b>{len(hidden.get('symbols', []))}</b>\n"
        f"Hidden strategies: <b>{len(hidden.get('strategies', []))}</b>\n"
        f"Hidden timeframes: <b>{len(hidden.get('timeframes', []))}</b>\n"
        f"Weak follow-ups: <b>{_state(bool(hidden.get('hide_weak_followups')), language_code=language)}</b>\n"
        f"Medium score: <b>{_state(bool(hidden.get('hide_medium_score')), language_code=language)}</b>\n"
        f"Repeat mute: <b>{int(hidden.get('mute_repeats_hours', 0) or 0)}h</b>"
    )


def build_hide_mute_keyboard(*, language_code: str, back_callback_data: str | None = None) -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [
        [
            {"text": "🪙 Hide Asset" if language == "en" else "🪙 Скрыть актив", "callback_data": "ux:hidemute:asset:prompt"},
            {"text": "🧠 Hide Strategy" if language == "en" else "🧠 Скрыть стратегию", "callback_data": "ux:hidemute:view:strategies"},
        ],
        [
            {"text": "⏱ Hide Timeframe" if language == "en" else "⏱ Скрыть ТФ", "callback_data": "ux:hidemute:view:timeframes"},
            {"text": "🔁 Mute Repeats" if language == "en" else "🔁 Повторы", "callback_data": "ux:hidemute:view:repeats"},
        ],
        [
            {"text": "📉 Hide Weak Setups" if language == "en" else "📉 Слабые сетапы", "callback_data": "ux:hidemute:toggle:hide_medium_score"},
            {"text": "🔕 Weak Follow-Ups" if language == "en" else "🔕 Слабые фоллоу-апы", "callback_data": "ux:hidemute:toggle:hide_weak_followups"},
        ],
        [
            {"text": "🎭 Hide Memes" if language == "en" else "🎭 Скрыть мемы", "callback_data": "ux:hidemute:toggle:hide_memes"},
            {"text": "🥇 Hide Gold" if language == "en" else "🥇 Скрыть золото", "callback_data": "ux:hidemute:toggle:hide_gold_temporarily"},
        ],
        [
            {"text": "♻️ Resume All" if language == "en" else "♻️ Сбросить всё", "callback_data": "ux:hidemute:resume"},
        ],
    ]
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data))
    return {"inline_keyboard": rows}


def build_hide_strategy_keyboard(*, language_code: str, strategy_keys: Sequence[str], back_callback_data: str | None = None) -> dict[str, object]:
    language = normalize_language(language_code)
    labels = (
        {
            "breakout": "Breakout",
            "trend_pullback": "Pullback",
            "rsi_bollinger_mr": "RSI + Bollinger MR",
            "rsi_bollinger_touch": "RSI + Bollinger Touch",
            "daily_rsi_80": "Daily RSI 80+",
            "vwap": "VWAP",
            "false_breakout": "False Breakout",
            "rsi": "RSI",
            "rsi_divergence": "RSI Divergence",
            "ekek": "EKEK",
            "bollinger": "Bollinger",
            "gold": "Gold",
            "gold_breakout": "Gold Breakout",
            "gold_pullback": "Gold Pullback",
            "gold_liquidity": "Gold Liquidity",
        }
        if language == "en"
        else {
            "breakout": "Пробой",
            "trend_pullback": "Откат по тренду",
            "rsi_bollinger_mr": "RSI + Bollinger MR",
            "rsi_bollinger_touch": "RSI + Bollinger Touch",
            "daily_rsi_80": "Daily RSI 80+",
            "vwap": "VWAP",
            "false_breakout": "Ложный пробой",
            "rsi": "RSI",
            "rsi_divergence": "RSI Divergence",
            "ekek": "EKEK",
            "bollinger": "Боллинджер",
            "gold": "Золото",
            "gold_breakout": "Пробой золота",
            "gold_pullback": "Откат по золоту",
            "gold_liquidity": "Ликвидность золота",
        }
    )
    rows = [[{"text": f"🚫 {labels.get(key, key)}", "callback_data": f"ux:hidemute:strategy:{key}"}] for key in strategy_keys]
    rows.extend(_footer_rows(language_code=language_code, back_callback_data=back_callback_data or "ux:hidemute"))
    return {"inline_keyboard": rows}


def build_hide_timeframe_keyboard(*, language_code: str, back_callback_data: str | None = None) -> dict[str, object]:
    timeframes = ("5m", "15m", "30m", "1h", "4h", "1d")
    rows = []
    for idx in range(0, len(timeframes), 2):
        rows.append([
            {"text": f"🚫 {tf}", "callback_data": f"ux:hidemute:timeframe:{tf}"}
            for tf in timeframes[idx:idx + 2]
        ])
    rows.extend(_footer_rows(language_code=language_code, back_callback_data=back_callback_data or "ux:hidemute"))
    return {"inline_keyboard": rows}


def build_repeat_mute_keyboard(*, language_code: str, back_callback_data: str | None = None) -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [[
        {"text": "Off" if language == "en" else "Выкл", "callback_data": "ux:hidemute:repeats:0"},
        {"text": "1h", "callback_data": "ux:hidemute:repeats:1"},
        {"text": "8h", "callback_data": "ux:hidemute:repeats:8"},
        {"text": "24h", "callback_data": "ux:hidemute:repeats:24"},
    ]]
    rows.extend(_footer_rows(language_code=language_code, back_callback_data=back_callback_data or "ux:hidemute"))
    return {"inline_keyboard": rows}


def format_style_profile_message(
    *,
    language_code: str,
    profile: UserStyleProfileRecord | None,
    title: str,
    summary: str,
) -> str:
    if normalize_language(language_code) == "ru":
        return (
            "<b>🪞 My Style</b>\n\n"
            "Короткий профиль того, как бот должен адаптироваться под тебя.\n\n"
            f"Профиль: <b>{escape_html(title)}</b>\n"
            f"Summary: <b>{escape_html(summary)}</b>\n"
            f"Сохранено: <b>{'Да' if profile is not None else 'Пока нет'}</b>"
        )
    return (
        "<b>🪞 My Style</b>\n\n"
        "A short profile for how the bot should adapt to you.\n\n"
        f"Profile: <b>{escape_html(title)}</b>\n"
        f"Summary: <b>{escape_html(summary)}</b>\n"
        f"Saved: <b>{'Yes' if profile is not None else 'Not yet'}</b>"
    )


def build_style_profile_keyboard(*, language_code: str, back_callback_data: str | None = None) -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [
        [
            {"text": "⚡ Speed" if language == "en" else "⚡ Скорость", "callback_data": "ux:style:view:speed_preference"},
            {"text": "🔕 Noise" if language == "en" else "🔕 Шум", "callback_data": "ux:style:view:noise_tolerance"},
        ],
        [
            {"text": "🪙 Market" if language == "en" else "🪙 Рынок", "callback_data": "ux:style:view:market_preference"},
            {"text": "📈 Signal Style" if language == "en" else "📈 Тип сигнала", "callback_data": "ux:style:view:signal_style"},
        ],
        [
            {"text": "✅ Confirmation" if language == "en" else "✅ Подтверждение", "callback_data": "ux:style:view:confirmation_style"},
            {"text": "📬 Delivery" if language == "en" else "📬 Доставка", "callback_data": "ux:style:view:delivery_preference"},
        ],
        [
            {"text": "🌍 Rhythm" if language == "en" else "🌍 Ритм", "callback_data": "ux:style:view:trading_rhythm"},
            {"text": "🛡 Risk" if language == "en" else "🛡 Риск", "callback_data": "ux:style:view:risk_style"},
        ],
        [
            {"text": "💾 Save Profile" if language == "en" else "💾 Сохранить профиль", "callback_data": "ux:style:save"},
            {"text": "🧩 Save as Setup" if language == "en" else "🧩 Сохранить как сетап", "callback_data": "ux:setup:savecurrent"},
        ],
    ]
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data))
    return {"inline_keyboard": rows}


def format_style_dimension_message(*, language_code: str, dimension_label: str, current_value: str) -> str:
    if normalize_language(language_code) == "ru":
        return f"<b>🪄 {escape_html(dimension_label)}</b>\n\nТекущее значение: <b>{escape_html(current_value)}</b>"
    return f"<b>🪄 {escape_html(dimension_label)}</b>\n\nCurrent value: <b>{escape_html(current_value)}</b>"


def build_style_dimension_keyboard(
    *,
    language_code: str,
    dimension: str,
    options: Sequence[tuple[str, str]],
    back_callback_data: str | None = None,
) -> dict[str, object]:
    rows: list[list[dict[str, object]]] = []
    for idx in range(0, len(options), 2):
        row = []
        for value, label in options[idx:idx + 2]:
            row.append({"text": label, "callback_data": f"ux:style:set:{dimension}:{value}"})
        rows.append(row)
    rows.extend(_footer_rows(language_code=language_code, back_callback_data=back_callback_data or "ux:stylehub"))
    return {"inline_keyboard": rows}


def format_personal_summary_message(*, language_code: str, summary) -> str:
    language = normalize_language(language_code)
    period_title = "📅 Daily Summary" if summary.period_label == "daily" else "🗓 Weekly Summary"
    if language == "ru":
        period_title = "📅 Дневная сводка" if summary.period_label == "daily" else "🗓 Недельная сводка"
        lines = [
            f"<b>{period_title}</b>",
            "",
            "Твой персональный рыночный поток.",
            "",
            f"Setup: <b>{escape_html(summary.setup_name)}</b>",
            f"Matched: <b>{summary.matched}</b>",
            f"Delivered: <b>{summary.delivered}</b>",
            f"Strong: <b>{summary.strong_delivered}</b>",
            f"Watchlist: <b>{summary.watchlist_matches}</b>",
            f"Filtered Out: <b>{summary.filtered_out}</b>",
            f"Top Strategy: <b>{escape_html(summary.top_strategy or '—')}</b>",
            f"Most Active Asset: <b>{escape_html(summary.most_active_asset or '—')}</b>",
            f"Gold Activity: <b>{escape_html(summary.gold_activity)}</b>",
            "",
            f"<b>Quick read</b>\n{escape_html(summary.quick_read)}",
            "",
            f"<b>Suggested action</b>\n{escape_html(summary.top_recommendation)}",
        ]
        if summary.change_note:
            lines.extend(["", f"<b>What changed</b>\n{escape_html(summary.change_note)}"])
        return "\n".join(lines)
    lines = [
        f"<b>{period_title}</b>",
        "",
        "Your market flow for this period.",
        "",
        f"Setup: <b>{escape_html(summary.setup_name)}</b>",
        f"Matched: <b>{summary.matched}</b>",
        f"Delivered: <b>{summary.delivered}</b>",
        f"Strong: <b>{summary.strong_delivered}</b>",
        f"Watchlist Matches: <b>{summary.watchlist_matches}</b>",
        f"Filtered Out: <b>{summary.filtered_out}</b>",
        f"Top Strategy: <b>{escape_html(summary.top_strategy or '—')}</b>",
        f"Most Active Asset: <b>{escape_html(summary.most_active_asset or '—')}</b>",
        f"Gold Activity: <b>{escape_html(summary.gold_activity)}</b>",
        "",
        f"<b>Quick read</b>\n{escape_html(summary.quick_read)}",
        "",
        f"<b>Suggested action</b>\n{escape_html(summary.top_recommendation)}",
    ]
    if summary.change_note:
        lines.extend(["", f"<b>What changed</b>\n{escape_html(summary.change_note)}"])
    return "\n".join(lines)


def build_personal_summary_keyboard(*, language_code: str, back_callback_data: str | None = None) -> dict[str, object]:
    language = normalize_language(language_code)
    rows = [
        [
            {"text": "📅 Daily" if language == "en" else "📅 День", "callback_data": "ux:summary:daily"},
            {"text": "🗓 Weekly" if language == "en" else "🗓 Неделя", "callback_data": "ux:summary:weekly"},
        ],
        [
            {"text": "🧩 Setups" if language == "en" else "🧩 Сетапы", "callback_data": "main:setups"},
            {"text": "🎯 Filters" if language == "en" else "🎯 Фильтры", "callback_data": "ux:filtershub"},
        ],
    ]
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data or "results:hub"))
    return {"inline_keyboard": rows}


def build_personalized_settings_keyboard(
    *,
    language_code: str,
    display_mode: str,
    back_callback_data: str | None = None,
) -> dict[str, object]:
    language = normalize_language(language_code)
    normalized_mode = str(display_mode or "").strip().lower()
    rows = [
        [
            {"text": "🔔 Notifications" if language == "en" else "🔔 Уведомления", "callback_data": "ux:deliveryhub"},
            {"text": "📬 Delivery Rules" if language == "en" else "📬 Как доставлять", "callback_data": "ux:deliveryrules"},
        ],
        [
            {"text": "🔕 Noise Level" if language == "en" else "🔕 Уровень шума", "callback_data": "ux:noisehub"},
            {"text": "📊 Signal Quality" if language == "en" else "📊 Качество сигналов", "callback_data": "ux:scorehub"},
        ],
        [
            {"text": "🕒 Market Session" if language == "en" else "🕒 Время рынка", "callback_data": "ux:sessionhub"},
            {"text": "🚫 Hide & Mute" if language == "en" else "🚫 Что скрыть", "callback_data": "ux:hidemute"},
        ],
        [
            {"text": "🪞 My Style" if language == "en" else "🪞 Стиль торговли", "callback_data": "ux:stylehub"},
            {"text": "🧩 Workspaces" if language == "en" else "🧩 Рабочие режимы", "callback_data": "ux:workspacehub"},
        ],
        [
            {"text": "🌐 Language" if language == "en" else "🌐 Язык", "callback_data": "ux:language:picker:settings"},
            {"text": "📊 Results" if language == "en" else "📊 Результаты", "callback_data": "results:hub"},
        ],
        [
            {
                "text": (
                    "🖥 Switch to Simple"
                    if language == "en" and normalized_mode != "simple"
                    else "🖥 Switch to Pro"
                    if language == "en"
                    else "🖥 Сделать проще"
                    if normalized_mode != "simple"
                    else "🖥 Включить Pro"
                ),
                "callback_data": "ux:display:simple" if normalized_mode != "simple" else "ux:display:pro",
            },
            {"text": "🟢 Bot Status" if language == "en" else "🟢 Статус бота", "callback_data": "ux:status"},
        ],
    ]
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback_data))
    return {"inline_keyboard": rows}


def build_personalized_results_keyboard(
    *,
    language_code: str,
    is_admin: bool,
    strategy_code: str | None = None,
) -> dict[str, object]:
    language = normalize_language(language_code)
    lifecycle_callback = f"strategy:lifecycle:{strategy_code}" if strategy_code else "lifecycle:hub"
    back_callback = f"strategy:open:{strategy_code}" if strategy_code else "main:today"
    rows = [
        [
            {"text": "📅 Daily Summary" if language == "en" else "📅 Дневная сводка", "callback_data": "ux:summary:daily"},
            {"text": "🗓 Weekly Summary" if language == "en" else "🗓 Недельная сводка", "callback_data": "ux:summary:weekly"},
        ],
        [
            {"text": "🔄 Lifecycle" if language == "en" else "🔄 Жизненный цикл", "callback_data": lifecycle_callback},
            {"text": "✨ Fresh Signals" if language == "en" else "✨ Свежие сигналы", "callback_data": "ux:signals:fresh"},
        ],
        [
            {"text": "📈 Strategy Results" if language == "en" else "📈 Результаты стратегий", "callback_data": "compare:hub"},
            {"text": "🟢 Bot Status" if language == "en" else "🟢 Статус бота", "callback_data": "ux:status"},
        ],
        [
            {"text": "📐 Methodology" if language == "en" else "📐 Методология", "callback_data": "ux:help:results"},
            {"text": "🧾 Example Follow-up" if language == "en" else "🧾 Пример follow-up", "callback_data": "ux:help:example_followup"},
        ],
    ]
    if is_admin:
        rows.append(
            [
                {"text": "🧾 Admin Stats" if language == "en" else "🧾 Админ-стата", "callback_data": "results:admin:7d"},
                {"text": "🩺 Health" if language == "en" else "🩺 Состояние", "callback_data": "ux:health"},
            ]
        )
    rows.extend(_footer_rows(language_code=language, back_callback_data=back_callback, home_callback_data="main:today"))
    return {"inline_keyboard": rows}


def build_admin_health_keyboard(*, language_code: str) -> dict[str, object]:
    language = normalize_language(language_code)
    return {
        "inline_keyboard": [
            [
                {"text": "🔄 Refresh" if language == "en" else "🔄 Обновить", "callback_data": "ux:health"},
                {"text": "🧾 Admin Stats" if language == "en" else "🧾 Админ-стата", "callback_data": "results:admin:7d"},
            ],
            *_footer_rows(
                language_code=language,
                back_callback_data="results:hub",
                home_callback_data="main:today",
            ),
        ]
    }


def _translate_quick_filter_label(label: str, *, language_code: str) -> str:
    if normalize_language(language_code) != "ru":
        return label
    mapping = {
        "High Conviction": "Только сильные",
        "Low Noise": "Меньше шума",
        "Trend Only": "Только трендовые",
        "Range Only": "Только диапазонные",
        "Breakout Only": "Только пробои",
        "Pullback Only": "Только откаты",
        "Gold Only": "Только золото",
        "Watchlist Only": "Только вотчлист",
        "Fast Setups": "Быстрые идеи",
        "Cleaner": "Чище",
        "Cleaner Flow": "Чище поток",
        "Aggressive": "Больше сигналов",
        "Conservative": "Осторожный режим",
    }
    return mapping.get(label, label)
