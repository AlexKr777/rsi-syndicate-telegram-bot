from __future__ import annotations

"""V2 Telegram-native copy and keyboards.

This module deliberately contains user-facing text and keyboard composition.
Handlers supply real data and choose a screen; they do not build strings or
invent callback payloads themselves.
"""

from html import escape
from typing import Iterable

from src.localization import normalize_language


_STYLE_LABELS = {
    "scalp": ("⚡ Быстрые сделки", "⚡ Fast trades"),
    "intraday": ("📈 Внутри дня", "📈 Intraday"),
    "swing": ("🌊 Несколько дней", "🌊 Several days"),
    "balanced": ("🧭 Сбалансированный", "🧭 Balanced"),
}
_MARKET_LABELS = {
    "btc_eth": ("₿ BTC и ETH", "₿ BTC and ETH"),
    "majors": ("🏆 Крупные монеты", "🏆 Major coins"),
    "all": ("🌍 Весь рынок", "🌍 Whole market"),
    "manual": ("✍️ Ручной список", "✍️ Manual list"),
}
_QUALITY_LABELS = {
    "best": ("🔥 Только лучшие", "🔥 Best only"),
    "balanced": ("⚖️ Сбалансированный", "⚖️ Balanced"),
    "more": ("🚀 Больше идей", "🚀 More ideas"),
}
_DELIVERY_LABELS = {
    "instant": ("⚡ Сразу", "⚡ Instantly"),
    "digest": ("📦 Сводкой", "📦 Digest"),
    "quiet": ("🌙 Без ночных уведомлений", "🌙 No night alerts"),
}


def _is_ru(language_code: str) -> bool:
    return normalize_language(language_code) == "ru"


def _button(text: str, callback_data: str) -> dict[str, str]:
    return {"text": text, "callback_data": callback_data}


def _markup(rows: Iterable[Iterable[dict[str, str]]]) -> dict[str, object]:
    return {"inline_keyboard": [list(row) for row in rows]}


def _home_row(language_code: str) -> list[dict[str, str]]:
    return [_button("🏠 Главная" if _is_ru(language_code) else "🏠 Home", "v2:home:simple")]


def _back_home_row(language_code: str) -> list[dict[str, str]]:
    return [
        _button("◀️ Назад" if _is_ru(language_code) else "◀️ Back", "v2:nav:back"),
        *_home_row(language_code),
    ]


def choice_label(category: str, value: str, *, language_code: str) -> str:
    tables = {
        "style": _STYLE_LABELS,
        "market": _MARKET_LABELS,
        "quality": _QUALITY_LABELS,
        "delivery": _DELIVERY_LABELS,
    }
    labels = tables.get(category, {}).get(value)
    if labels is None:
        return str(value)
    return labels[0] if _is_ru(language_code) else labels[1]


def style_preview_summary(style_key: str, *, language_code: str) -> str:
    ru = _is_ru(language_code)
    summaries = {
        "scalp": ("Больше коротких сетапов и быстрых реакций рынка.", "More short-horizon setups and fast market reactions."),
        "intraday": ("Баланс внутридневных идей и фильтрации шума.", "A balance of intraday ideas and noise filtering."),
        "swing": ("Меньше сигналов, больше времени на развитие идеи.", "Fewer signals with more time for an idea to develop."),
        "balanced": ("Универсальный режим без перекоса в скорость или редкость.", "A general-purpose mode without bias toward speed or rarity."),
    }
    labels = summaries.get(style_key, summaries["balanced"])
    return labels[0] if ru else labels[1]


def format_hub_message(section: str, *, language_code: str) -> str:
    ru = _is_ru(language_code)
    copy = {
        "results": ("<b>📊 Результаты</b>\n\nСтатистика строится по реально сохранённым сигналам и их последующему движению.", "<b>📊 Results</b>\n\nStatistics are based on stored signals and their subsequent movement."),
        "watchlist": ("<b>👀 Избранное</b>\n\nВыделяйте важные активы и используйте сохранённые наборы рынка.", "<b>👀 Watchlist</b>\n\nKeep important assets close and work with saved market sets."),
        "help": ("<b>❓ Помощь</b>\n\nКороткие объяснения основаны на текущей логике бота, а не на пустых заглушках.", "<b>❓ Help</b>\n\nConcise explanations follow the bot's current behaviour, not empty placeholders."),
        "analytics": ("<b>🧠 Аналитика</b>\n\nAI-разбор отделяет факты, интерпретацию, неизвестные данные и риски.", "<b>🧠 Analytics</b>\n\nAI analysis separates facts, interpretation, unknowns and risk."),
        "market": ("<b>🌐 Рынок и избранное</b>\n\nСледите за выбранными активами, открывайте анализ и используйте готовые наборы монет.", "<b>🌐 Market & watchlist</b>\n\nFollow selected assets, open analysis and use ready-made coin sets."),
        "flows": ("<b>🧩 Профили сигналов</b>\n\nПрофиль объединяет стратегии, монеты, таймфреймы, фильтры и способ доставки.", "<b>🧩 Signal profiles</b>\n\nA profile combines strategies, assets, timeframes, filters and delivery."),
        "gold": ("<b>🥇 Gold Desk</b>\n\nОтдельный рабочий раздел для XAUUSD и Gold-уведомлений.", "<b>🥇 Gold Desk</b>\n\nA dedicated workspace for XAUUSD and Gold notifications."),
    }
    selected = copy.get(section, copy["help"])
    return selected[0] if ru else selected[1]


def format_home_message(
    *,
    language_code: str,
    first_name: str | None,
    is_pro: bool,
) -> str:
    del is_pro
    safe_name = escape((first_name or "").strip())
    if _is_ru(language_code):
        greeting = f"Привет, {safe_name}! 👋" if safe_name else "Привет! 👋"
        return "🏠 <b>Главное меню</b>\n\n" + greeting + "\n\nВыберите раздел, с которого хотите начать."
    greeting = f"Hi, {safe_name}! 👋" if safe_name else "Hi! 👋"
    return "🏠 <b>Main menu</b>\n\n" + greeting + "\n\nChoose where you want to start."


def build_home_keyboard(*, language_code: str, is_pro: bool, include_gold: bool) -> dict[str, object]:
    ru = _is_ru(language_code)
    if not is_pro:
        return _markup(
            [
                [_button("📈 Стратегии" if ru else "📈 Strategies", "v2:strategies:hub")],
                [_button("🎛 Настроить сигналы" if ru else "🎛 Set up signals", "v2:flow:hub")],
                [_button("📊 Результаты" if ru else "📊 Results", "v2:results:hub"), _button("👀 Избранное" if ru else "👀 Watchlist", "v2:watchlist:hub")],
                [_button("💎 Мой доступ" if ru else "💎 My access", "v2:access:hub"), _button("⚙️ Настройки" if ru else "⚙️ Settings", "v2:settings:hub")],
                [_button("🔧 Pro-режим" if ru else "🔧 Pro mode", "v2:home:pro"), _button("❓ Помощь" if ru else "❓ Help", "v2:help:hub")],
            ]
        )
    rows: list[list[dict[str, str]]] = [
        [_button("📈 Стратегии" if ru else "📈 Strategies", "v2:strategies:hub")],
        [_button("🎛 Настроить сигналы" if ru else "🎛 Set up signals", "v2:flow:hub")],
        [_button("🧠 Аналитика" if ru else "🧠 Analytics", "v2:analytics:hub"), _button("🌐 Рынок и избранное" if ru else "🌐 Market & watchlist", "v2:market:hub")],
        [_button("📊 Результаты" if ru else "📊 Results", "v2:results:hub"), _button("💎 Мой доступ" if ru else "💎 My access", "v2:access:hub")],
    ]
    if include_gold:
        rows.append([_button("🥇 Gold Desk", "v2:gold:hub"), _button("⚙️ Настройки" if ru else "⚙️ Settings", "v2:settings:hub")])
        rows.append([_button("❓ Помощь" if ru else "❓ Help", "v2:help:hub")])
    else:
        rows.append([_button("⚙️ Настройки" if ru else "⚙️ Settings", "v2:settings:hub"), _button("❓ Помощь" if ru else "❓ Help", "v2:help:hub")])
    rows.append([_button("⬅️ Простой режим" if ru else "⬅️ Simple mode", "v2:home:simple")])
    return _markup(rows)


def format_strategies_message(*, language_code: str, active_count: int, total_count: int, signals_count: int = 0) -> str:
    del signals_count
    if _is_ru(language_code):
        return (
            "<b>📈 Стратегии</b>\n\nВыберите стратегию и настройте её отдельно.\n\n"
            f"Активно: <b>{active_count}</b> из <b>{total_count}</b>"
        )
    return (
        "<b>📈 Strategies</b>\n\nChoose a strategy and configure it separately.\n\n"
        f"Active: <b>{active_count}</b> of <b>{total_count}</b>"
    )


def build_strategies_keyboard(*, language_code: str, strategies: Iterable[tuple[str, str, bool, bool]]) -> dict[str, object]:
    ru = _is_ru(language_code)
    rows: list[list[dict[str, str]]] = []
    for key, label, enabled, locked in strategies:
        prefix = "🔒" if locked else "🟢" if enabled else "⚪"
        rows.append([_button(f"{prefix} {label}", f"v2:strategies:open:{key}")])
    rows.append(_back_home_row(language_code))
    return _markup(rows)


def format_strategy_message(
    *,
    language_code: str,
    label: str,
    summary: str,
    enabled: bool,
    signals_7d: int,
    active_now: int,
    timeframes: str,
    is_pro: bool,
) -> str:
    ru = _is_ru(language_code)
    state = "🟢 Включена" if enabled and ru else "⚪ Выключена" if ru else "🟢 Enabled" if enabled else "⚪ Disabled"
    lines = [f"<b>📈 {label}</b>", "", summary, "", f"{'Статус' if ru else 'Status'}: <b>{state}</b>", f"{'Сигналов за 7 дней' if ru else 'Signals in 7 days'}: <b>{signals_7d}</b>", f"{'Активных сейчас' if ru else 'Active now'}: <b>{active_now}</b>", f"{'Доступные ТФ' if ru else 'Available TF'}: <b>{timeframes}</b>"]
    if not is_pro:
        lines.extend(["", "Изменяйте только включение стратегии и основные параметры. Расширенные фильтры доступны в Pro-режиме." if ru else "Change only the strategy state and essentials here. Advanced filters are available in Pro mode."])
    return "\n".join(lines)


def build_strategy_keyboard(*, language_code: str, strategy_key: str, enabled: bool, is_pro: bool) -> dict[str, object]:
    del is_pro
    ru = _is_ru(language_code)
    state = "🟢 Включена" if enabled and ru else "⚪ Включить" if ru else "🟢 Enabled" if enabled else "⚪ Enable"
    rows = [
        [_button(state, f"v2:strategies:toggle:{strategy_key}")],
        [_button("🎛 Настройки стратегии" if ru else "🎛 Strategy settings", f"v2:strategies:settings:{strategy_key}")],
        [_button("📊 Результаты стратегии" if ru else "📊 Strategy results", f"v2:results:strategies:{strategy_key}")],
        [_button("◀️ Назад" if ru else "◀️ Back", "v2:nav:back"), *_home_row(language_code)],
    ]
    return _markup(rows)


def format_strategy_settings_message(
    *,
    language_code: str,
    label: str,
    direct_delivery_enabled: bool,
    followup_delivery_enabled: bool,
    preferred_min_score: int,
) -> str:
    ru = _is_ru(language_code)
    state = lambda enabled: ("включены" if enabled else "выключены") if ru else ("enabled" if enabled else "disabled")
    if ru:
        return (
            f"<b>🎛 Настройки · {escape(label)}</b>\n\n"
            "Изменения действуют только на эту стратегию и сразу сохраняются.\n\n"
            f"🔔 Новые сигналы: <b>{state(direct_delivery_enabled)}</b>\n"
            f"🔄 Обновления результата: <b>{state(followup_delivery_enabled)}</b>\n"
            f"⭐ Минимальный score: <b>{preferred_min_score}</b>"
        )
    return (
        f"<b>🎛 Settings · {escape(label)}</b>\n\n"
        "Changes apply only to this strategy and are saved immediately.\n\n"
        f"🔔 New signals: <b>{state(direct_delivery_enabled)}</b>\n"
        f"🔄 Result updates: <b>{state(followup_delivery_enabled)}</b>\n"
        f"⭐ Minimum score: <b>{preferred_min_score}</b>"
    )


def build_strategy_settings_keyboard(
    *,
    language_code: str,
    strategy_key: str,
    direct_delivery_enabled: bool,
    followup_delivery_enabled: bool,
    preferred_min_score: int,
) -> dict[str, object]:
    ru = _is_ru(language_code)
    direct_label = "вкл" if direct_delivery_enabled and ru else "выкл" if ru else "on" if direct_delivery_enabled else "off"
    followup_label = "вкл" if followup_delivery_enabled and ru else "выкл" if ru else "on" if followup_delivery_enabled else "off"
    strict = preferred_min_score >= 80
    quality_label = "строгий" if strict and ru else "обычный" if ru else "strict" if strict else "standard"
    return _markup(
        [
            [_button(f"🔔 Сигналы: {direct_label}" if ru else f"🔔 Signals: {direct_label}", f"v2:strategies:delivery:{strategy_key}:signals")],
            [_button(f"🔄 Follow-up: {followup_label}" if ru else f"🔄 Follow-up: {followup_label}", f"v2:strategies:delivery:{strategy_key}:followups")],
            [_button(f"⭐ Качество: {quality_label}" if ru else f"⭐ Quality: {quality_label}", f"v2:strategies:quality:{strategy_key}:{'standard' if strict else 'strict'}")],
            [_button("◀️ Назад" if ru else "◀️ Back", "v2:nav:back"), *_home_row(language_code)],
        ]
    )


def format_market_sets_message(
    *,
    language_code: str,
    active_label: str,
    symbols: Iterable[str],
) -> str:
    ru = _is_ru(language_code)
    visible_symbols = list(symbols)
    symbols_line = ", ".join(escape(symbol) for symbol in visible_symbols[:12]) or ("пока нет" if ru else "none yet")
    extra = len(visible_symbols) - 12
    if extra > 0:
        symbols_line += f" +{extra}"
    if ru:
        return (
            "<b>🎨 Наборы монет</b>\n\n"
            "Набор определяет, какие монеты стратегия отслеживает. Избранное — это ваш личный список быстрого доступа.\n\n"
            f"Активный набор: <b>{escape(active_label)}</b>\n"
            f"Отслеживаются: <code>{symbols_line}</code>"
        )
    return (
        "<b>🎨 Coin sets</b>\n\n"
        "A set defines the coins this strategy tracks. Watchlist is your personal quick-access list.\n\n"
        f"Active set: <b>{escape(active_label)}</b>\n"
        f"Tracked: <code>{symbols_line}</code>"
    )


def build_market_sets_keyboard(
    *,
    language_code: str,
    builtin_sets: Iterable[tuple[str, str]],
    saved_sets: Iterable[tuple[int, str]],
) -> dict[str, object]:
    ru = _is_ru(language_code)
    rows: list[list[dict[str, str]]] = [
        [_button("📍 Все отслеживаемые монеты" if ru else "📍 All tracked coins", "v2:market:set:tracked")],
    ]
    for key, label in builtin_sets:
        rows.append([_button(f"🎯 {label}", f"v2:market:set:builtin:{key}")])
    for theme_id, name in saved_sets:
        rows.append([_button(f"💾 {name}", f"v2:market:set:saved:{theme_id}")])
    rows.extend(
        [
            [_button("◀️ Назад" if ru else "◀️ Back", "v2:nav:back"), *_home_row(language_code)],
        ]
    )
    return _markup(rows)


def format_results_message(
    *,
    language_code: str,
    total: int,
    confirmed: int,
    broken: int,
    open_count: int,
    insufficient: int,
    followups: int = 0,
    updated_at: str | None,
    days: int = 7,
) -> str:
    ru = _is_ru(language_code)
    if total == 0:
        return (
            "<b>📊 Результаты пока не собраны</b>\n\nВ выбранном периоде нет завершённых сигналов. Открытые сигналы продолжают отслеживаться через follow-up."
            if ru else "<b>📊 Results are not collected yet</b>\n\nThere are no completed signals in this period. Open signals continue to be tracked through follow-ups."
        )
    label = "Обновлено" if ru else "Updated"
    period = "Период: сегодня" if ru and days <= 1 else f"Период: последние {days} дней" if ru else "Period: today" if days <= 1 else f"Period: last {days} days"
    return (
        f"<b>📊 {'Результаты' if ru else 'Results'}</b>\n\n{period}\n"
        f"{'Всего сигналов' if ru else 'Total signals'}: <b>{total}</b>\n"
        f"✅ {'Подтверждено' if ru else 'Confirmed'}: <b>{confirmed}</b>\n"
        f"❌ {'Сломано' if ru else 'Broken'}: <b>{broken}</b>\n"
        f"🟢 {'Открыто' if ru else 'Open'}: <b>{open_count}</b>\n"
        f"🔄 {'Follow-up записей' if ru else 'Follow-up records'}: <b>{followups}</b>\n"
        f"⚪ {'Недостаточно данных' if ru else 'Insufficient data'}: <b>{insufficient}</b>\n\n{label}: <b>{updated_at or ('нет данных' if ru else 'no data')}</b>"
    )


def format_onboarding_message(*, language_code: str, step: str, draft: dict[str, object]) -> str:
    ru = _is_ru(language_code)
    if step == "style":
        return "<b>Какой стиль вам ближе?</b>\n\nВыберем понятный стартовый режим. Детали можно изменить позже." if ru else "<b>Which trading style fits you?</b>\n\nChoose a clear starting mode. You can refine it later."
    if step == "market":
        return "<b>Какие активы отслеживать?</b>\n\nЭто определяет, где бот будет искать подходящие идеи." if ru else "<b>Which assets should we watch?</b>\n\nThis determines where the bot looks for matching ideas."
    if step == "symbols":
        return "<b>Отправьте активы одним сообщением</b>\n\nНапример: <code>BTC ETH SOL</code>" if ru else "<b>Send the assets in one message</b>\n\nFor example: <code>BTC ETH SOL</code>"
    if step == "quality":
        return "<b>Какой поток вы хотите?</b>\n\nЭто регулирует баланс между строгостью отбора и количеством идей." if ru else "<b>What kind of feed do you want?</b>\n\nThis balances strict selection against the number of ideas."
    if step == "delivery":
        return "<b>Как присылать сигналы?</b>\n\nУведомления и тихие часы можно поменять в любой момент." if ru else "<b>How should signals arrive?</b>\n\nYou can change notifications and quiet hours any time."
    style = str(draft.get("style_label") or ("Сбалансированный" if ru else "Balanced"))
    market = str(draft.get("market_label") or ("Весь рынок" if ru else "Whole market"))
    quality = str(draft.get("quality_label") or ("Сбалансированный" if ru else "Balanced"))
    delivery = str(draft.get("delivery_label") or ("Сразу" if ru else "Instant"))
    heading = "<b>Готово. Проверьте ваш поток</b>" if ru else "<b>Ready. Review your flow</b>"
    labels = ("Стиль", "Активы", "Сигналы", "Доставка") if ru else ("Style", "Assets", "Signals", "Delivery")
    return f"{heading}\n\n{labels[0]}: <b>{style}</b>\n{labels[1]}: <b>{market}</b>\n{labels[2]}: <b>{quality}</b>\n{labels[3]}: <b>{delivery}</b>"


def build_onboarding_keyboard(*, language_code: str, step: str) -> dict[str, object]:
    ru = _is_ru(language_code)
    back = "◀️ Назад" if ru else "◀️ Back"
    cancel = "✖️ Отмена" if ru else "✖️ Cancel"
    if step == "style":
        return _markup(
            [
                [_button("⚡ Быстрые сделки" if ru else "⚡ Fast trades", "v2:onboarding:style:scalp"), _button("📈 Внутри дня" if ru else "📈 Intraday", "v2:onboarding:style:intraday")],
                [_button("🌊 Несколько дней" if ru else "🌊 Several days", "v2:onboarding:style:swing"), _button("🧭 Пока не знаю" if ru else "🧭 Not sure yet", "v2:onboarding:style:balanced")],
                [_button(cancel, "v2:onboarding:cancel")],
            ]
        )
    if step == "market":
        return _markup(
            [
                [_button("₿ BTC и ETH" if ru else "₿ BTC and ETH", "v2:onboarding:market:btc_eth"), _button("🏆 Крупные монеты" if ru else "🏆 Major coins", "v2:onboarding:market:majors")],
                [_button("🌍 Весь рынок" if ru else "🌍 Whole market", "v2:onboarding:market:all"), _button("✍️ Выбрать вручную" if ru else "✍️ Choose manually", "v2:onboarding:market:manual")],
                [_button(back, "v2:onboarding:back:style"), _button(cancel, "v2:onboarding:cancel")],
            ]
        )
    if step == "quality":
        return _markup(
            [
                [_button("🔥 Только лучшие" if ru else "🔥 Best only", "v2:onboarding:quality:best"), _button("⚖️ Сбалансированный" if ru else "⚖️ Balanced", "v2:onboarding:quality:balanced")],
                [_button("🚀 Больше идей" if ru else "🚀 More ideas", "v2:onboarding:quality:more")],
                [_button(back, "v2:onboarding:back:market"), _button(cancel, "v2:onboarding:cancel")],
            ]
        )
    if step == "delivery":
        return _markup(
            [
                [_button("⚡ Сразу" if ru else "⚡ Instantly", "v2:onboarding:delivery:instant"), _button("📦 Сводкой" if ru else "📦 Digest", "v2:onboarding:delivery:digest")],
                [_button("🌙 Без ночных уведомлений" if ru else "🌙 No night alerts", "v2:onboarding:delivery:quiet")],
                [_button(back, "v2:onboarding:back:quality"), _button(cancel, "v2:onboarding:cancel")],
            ]
        )
    return _markup(
        [
            [_button("🔥 Посмотреть сигналы" if ru else "🔥 View signals", "v2:onboarding:confirm:signals"), _button("📖 Как читать сигнал" if ru else "📖 How to read a signal", "ux:welcome:read")],
            [_button("🏠 Открыть главное меню" if ru else "🏠 Open main menu", "v2:onboarding:confirm:home")],
            [_button(back, "v2:onboarding:back:delivery"), _button(cancel, "v2:onboarding:cancel")],
        ]
    )


def format_signal_list_message(*, language_code: str, view: str, count: int) -> str:
    ru = _is_ru(language_code)
    labels = {
        "best": "Лучшие" if ru else "Best",
        "new": "Новые" if ru else "New",
        "watchlist": "Избранное" if ru else "Watchlist",
        "all": "Все" if ru else "All",
    }
    title = labels.get(view, labels["all"])
    suffix = "Показываются идеи, соответствующие вашему активному профилю." if ru else "These ideas match your active profile."
    count_text = f"Найдено: <b>{count}</b>" if ru else f"Found: <b>{count}</b>"
    return f"<b>📡 Актуальные сигналы · {title}</b>\n\n{suffix}\n{count_text}"


def format_signal_empty_message(*, language_code: str) -> str:
    if _is_ru(language_code):
        return "<b>📈 Актуальные сигналы</b>\n\nСейчас нет сигналов, подходящих под активный профиль. Бот продолжает наблюдение; можно изменить настройку или посмотреть результаты."
    return "<b>📈 Active signals</b>\n\nThere are no signals matching the active profile right now. The bot is still watching; you can adjust it or review results."


def build_signal_list_keyboard(
    *,
    language_code: str,
    entries: Iterable[tuple[int, str]],
) -> dict[str, object]:
    ru = _is_ru(language_code)
    rows: list[list[dict[str, str]]] = [
        [_button("🔥 Лучшие" if ru else "🔥 Best", "v2:signals:best"), _button("🆕 Новые" if ru else "🆕 New", "v2:signals:new")],
        [_button("👀 Избранное" if ru else "👀 Watchlist", "v2:signals:watchlist"), _button("🧠 По стратегии" if ru else "🧠 By strategy", "v2:strategies:hub")],
        [_button("🔄 Обновить" if ru else "🔄 Refresh", "v2:signals:all")],
    ]
    for alert_id, label in entries:
        rows.append([_button(label, f"v2:signal:open:{alert_id}")])
    rows.extend(
        [
            [_button("🎛 Настроить сигналы" if ru else "🎛 Set up signals", "v2:flow:hub"), _button("📖 Как читать" if ru else "📖 How to read", "ux:welcome:read")],
            _back_home_row(language_code),
        ]
    )
    return _markup(rows)


def build_signal_empty_keyboard(*, language_code: str) -> dict[str, object]:
    ru = _is_ru(language_code)
    return _markup(
        [
            [_button("🎛 Изменить настройку" if ru else "🎛 Change setup", "v2:flow:assets"), _button("📊 Результаты" if ru else "📊 Results", "v2:results:hub")],
            [_button("🔄 Проверить снова" if ru else "🔄 Check again", "v2:signals:all")],
            _back_home_row(language_code),
        ]
    )


def format_flow_message(*, language_code: str, flow_name: str, summary: str) -> str:
    del flow_name
    if _is_ru(language_code):
        return f"<b>🎛 Настройка сигналов</b>\n\nВыберите, какие торговые ситуации отслеживать и как получать уведомления.\n\n<b>Текущие настройки</b>\n{summary}"
    return f"<b>🎛 Signal setup</b>\n\nChoose which trading situations to watch and how to receive notifications.\n\n<b>Current settings</b>\n{summary}"


def format_style_choice_message(*, language_code: str) -> str:
    return "<b>Выберите стиль</b>" if _is_ru(language_code) else "<b>Choose a style</b>"


def format_assets_choice_message(*, language_code: str) -> str:
    return "<b>Какие активы отслеживать?</b>" if _is_ru(language_code) else "<b>Which assets should we watch?</b>"


def format_quality_choice_message(*, language_code: str) -> str:
    return "<b>Качество сигналов</b>" if _is_ru(language_code) else "<b>Signal quality</b>"


def format_settings_message(*, language_code: str) -> str:
    if _is_ru(language_code):
        return "<b>⚙️ Настройки</b>\n\nУправляйте уведомлениями, языком и режимом интерфейса."
    return "<b>⚙️ Settings</b>\n\nManage notifications, language and interface mode."


def format_invalid_symbols_message(*, language_code: str) -> str:
    if _is_ru(language_code):
        return "Не нашёл доступных USDT-фьючерсов среди этих тикеров. Проверьте символы и отправьте их ещё раз: <code>BTC ETH SOL</code>."
    return "I could not find active USDT futures for those tickers. Check them and send the list again: <code>BTC ETH SOL</code>."


def build_flow_keyboard(*, language_code: str) -> dict[str, object]:
    ru = _is_ru(language_code)
    return _markup(
        [
            [_button("📈 Выбрать стратегии" if ru else "📈 Choose strategies", "v2:strategies:hub")],
            [_button("✏️ Изменить стиль" if ru else "✏️ Change style", "v2:flow:style"), _button("🪙 Изменить активы" if ru else "🪙 Change assets", "v2:flow:assets")],
            [_button("🔥 Качество сигналов" if ru else "🔥 Signal quality", "v2:flow:quality"), _button("🔔 Уведомления" if ru else "🔔 Notifications", "v2:notifications:hub")],
            [_button("🧩 Сохранённые профили" if ru else "🧩 Saved profiles", "v2:flows:list"), _button("♻️ Сбросить" if ru else "♻️ Reset", "v2:flow:reset")],
            _back_home_row(language_code),
        ]
    )


def build_style_keyboard(*, language_code: str) -> dict[str, object]:
    ru = _is_ru(language_code)
    return _markup(
        [
            [_button("⚡ Быстрые сделки" if ru else "⚡ Fast trades", "v2:flow:style_preview:scalp"), _button("📈 Внутри дня" if ru else "📈 Intraday", "v2:flow:style_preview:intraday")],
            [_button("🌊 Несколько дней" if ru else "🌊 Several days", "v2:flow:style_preview:swing"), _button("🧭 Сбалансированный" if ru else "🧭 Balanced", "v2:flow:style_preview:balanced")],
            [_button("◀️ Назад" if ru else "◀️ Back", "v2:flow:hub")],
        ]
    )


def format_style_preview(*, language_code: str, style_label: str, summary: str) -> str:
    prefix = "<b>Предпросмотр изменений</b>" if _is_ru(language_code) else "<b>Change preview</b>"
    note = "Изменятся стиль, качество и подходящие стратегии. Остальные настройки сохранятся." if _is_ru(language_code) else "Style, quality and suitable strategies will change. Your other settings stay intact."
    return f"{prefix}\n\n🎯 {style_label}\n{summary}\n\n{note}"


def build_style_preview_keyboard(*, language_code: str, style_key: str) -> dict[str, object]:
    ru = _is_ru(language_code)
    return _markup(
        [
            [_button("▶️ Применить" if ru else "▶️ Apply", f"v2:flow:style_apply:{style_key}"), _button("◀️ Назад" if ru else "◀️ Back", "v2:flow:style")],
            _home_row(language_code),
        ]
    )


def build_assets_keyboard(*, language_code: str) -> dict[str, object]:
    ru = _is_ru(language_code)
    return _markup(
        [
            [_button("₿ BTC и ETH" if ru else "₿ BTC and ETH", "v2:flow:assets_apply:btc_eth"), _button("🏆 Крупные монеты" if ru else "🏆 Major coins", "v2:flow:assets_apply:majors")],
            [_button("🌍 Весь рынок" if ru else "🌍 Whole market", "v2:flow:assets_apply:all"), _button("✍️ Выбрать вручную" if ru else "✍️ Choose manually", "v2:flow:assets_manual")],
            [_button("◀️ Назад" if ru else "◀️ Back", "v2:flow:hub")],
        ]
    )


def build_quality_keyboard(*, language_code: str) -> dict[str, object]:
    ru = _is_ru(language_code)
    return _markup(
        [
            [_button("🔥 Только лучшие" if ru else "🔥 Best only", "v2:flow:quality_apply:best"), _button("⚖️ Сбалансированный" if ru else "⚖️ Balanced", "v2:flow:quality_apply:balanced")],
            [_button("🚀 Больше идей" if ru else "🚀 More ideas", "v2:flow:quality_apply:more")],
            [_button("◀️ Назад" if ru else "◀️ Back", "v2:flow:hub")],
        ]
    )


def format_notifications_message(*, language_code: str, signals_on: bool, followups_on: bool, gold_on: bool, delivery: str) -> str:
    ru = _is_ru(language_code)
    state = lambda value: ("Вкл" if value else "Выкл") if ru else ("On" if value else "Off")
    title = "<b>🔔 Уведомления</b>" if ru else "<b>🔔 Notifications</b>"
    labels = ("Сигналы", "Follow-up", "Gold", "Доставка") if ru else ("Signals", "Follow-up", "Gold", "Delivery")
    return f"{title}\n\n{labels[0]}: <b>{state(signals_on)}</b>\n{labels[1]}: <b>{state(followups_on)}</b>\n{labels[2]}: <b>{state(gold_on)}</b>\n{labels[3]}: <b>{delivery}</b>"


def build_notifications_keyboard(*, language_code: str, gold_available: bool) -> dict[str, object]:
    ru = _is_ru(language_code)
    rows = [
        [_button("🔔 Сигналы: Вкл / Выкл" if ru else "🔔 Signals: On / Off", "v2:notifications:toggle:signals"), _button("🔄 Follow-up" if ru else "🔄 Follow-up", "v2:notifications:toggle:followups")],
        [_button("⚡ Доставка сразу" if ru else "⚡ Instant delivery", "v2:notifications:delivery:instant"), _button("📦 Сводка" if ru else "📦 Digest", "v2:notifications:delivery:digest")],
        [_button("😴 Пауза на 1 час" if ru else "😴 Pause 1 hour", "v2:notifications:snooze:1h"), _button("😴 Пауза на 8 часов" if ru else "😴 Pause 8 hours", "v2:notifications:snooze:8h")],
        [_button("▶️ Возобновить" if ru else "▶️ Resume", "v2:notifications:snooze:resume")],
    ]
    if gold_available:
        rows.insert(1, [_button("🥇 Gold: Вкл / Выкл" if ru else "🥇 Gold: On / Off", "v2:notifications:toggle:gold")])
    rows.append(_back_home_row(language_code))
    return _markup(rows)


def build_settings_keyboard(*, language_code: str) -> dict[str, object]:
    ru = _is_ru(language_code)
    return _markup(
        [
            [_button("🔔 Уведомления" if ru else "🔔 Notifications", "v2:notifications:hub"), _button("🌙 Тихие часы" if ru else "🌙 Quiet hours", "ux:deliveryhub")],
            [_button("🚫 Исключения" if ru else "🚫 Exclusions", "ux:hidemute"), _button("🌐 Язык" if ru else "🌐 Language", "ux:language:picker:settings")],
            [_button("🖥 Режим интерфейса" if ru else "🖥 Interface mode", "v2:home:pro"), _button("🟢 Статус бота" if ru else "🟢 Bot status", "ux:status")],
            [_button("⌨️ Команды" if ru else "⌨️ Commands", "ux:help:commands"), _button("🆘 Поддержка" if ru else "🆘 Support", "ux:help:support")],
            _back_home_row(language_code),
        ]
    )


def build_results_keyboard(*, language_code: str, include_diagnostics: bool = False) -> dict[str, object]:
    ru = _is_ru(language_code)
    rows = [
            [_button("📅 Сегодня" if ru else "📅 Today", "v2:results:today"), _button("🗓 7 дней" if ru else "🗓 7 days", "v2:results:week")],
            [_button("📈 По стратегиям" if ru else "📈 By strategy", "v2:results:strategies"), _button("🔄 Жизненный цикл" if ru else "🔄 Lifecycle", "v2:results:lifecycle")],
            [_button("🧾 Последние результаты" if ru else "🧾 Latest results", "v2:results:recent"), _button("📐 Методология" if ru else "📐 Methodology", "v2:results:methodology")],
            _back_home_row(language_code),
    ]
    if include_diagnostics:
        rows.insert(-1, [_button("🩺 Диагностика Results" if ru else "🩺 Results diagnostics", "v2:results:diagnostics")])
    return _markup(rows)


def build_watchlist_keyboard(*, language_code: str) -> dict[str, object]:
    ru = _is_ru(language_code)
    return _markup(
        [
            [_button("👀 Управлять избранным" if ru else "👀 Manage watchlist", "v2:watchlist:manage")],
            [_button("🎨 Наборы монет" if ru else "🎨 Coin sets", "v2:market:sets"), _button("🔎 Анализ актива" if ru else "🔎 Analyse asset", "v2:analytics:analyze")],
            _back_home_row(language_code),
        ]
    )


def build_help_keyboard(*, language_code: str) -> dict[str, object]:
    ru = _is_ru(language_code)
    return _markup(
        [
            [_button("🚀 Быстрый старт" if ru else "🚀 Quick start", "ux:help:quick_start"), _button("📖 Как читать сигнал" if ru else "📖 Read a signal", "ux:welcome:read")],
            [_button("🧾 Пример сигнала" if ru else "🧾 Signal example", "ux:welcome:example"), _button("🌙 Почему нет сигналов" if ru else "🌙 Why no signals", "ux:help:no_signals")],
            [_button("🛡 Управление риском" if ru else "🛡 Risk management", "ux:help:risk"), _button("🤖 Что делает AI" if ru else "🤖 What AI does", "ux:help:ai")],
            [_button("⚖️ Classic и PRO+", "ux:help:compare"), _button("💎 Доступ и trial" if ru else "💎 Access and trial", "ux:help:access")],
            [_button("➕ Ещё темы" if ru else "➕ More topics", "ux:help:more"), _button("🆘 Поддержка" if ru else "🆘 Support", "ux:help:support")],
            _back_home_row(language_code),
        ]
    )


def build_analytics_keyboard(*, language_code: str, include_gold: bool) -> dict[str, object]:
    ru = _is_ru(language_code)
    rows = [
        [_button("🤖 AI-разбор" if ru else "🤖 AI analysis", "v2:analytics:analyze"), _button("📊 Результаты по стратегиям" if ru else "📊 Results by strategy", "v2:results:strategies")],
        [_button("📐 Методология Results" if ru else "📐 Results methodology", "v2:results:methodology")],
    ]
    if include_gold:
        rows[-1].append(_button("🥇 Gold Desk", "v2:gold:hub"))
    rows.append(_back_home_row(language_code))
    return _markup(rows)


def build_market_keyboard(*, language_code: str, include_gold: bool) -> dict[str, object]:
    ru = _is_ru(language_code)
    rows = [
        [_button("👀 Управлять избранным" if ru else "👀 Manage watchlist", "v2:watchlist:manage"), _button("🔎 Анализ актива" if ru else "🔎 Analyse asset", "v2:analytics:analyze")],
        [_button("🎨 Наборы монет" if ru else "🎨 Coin sets", "v2:market:sets")],
    ]
    if include_gold:
        rows.append([_button("🥇 Золото" if ru else "🥇 Gold", "v2:gold:hub")])
    rows.append(_back_home_row(language_code))
    return _markup(rows)


def build_flows_keyboard(*, language_code: str) -> dict[str, object]:
    ru = _is_ru(language_code)
    return _markup(
        [
            [_button("▶️ Активный профиль" if ru else "▶️ Active profile", "v2:flow:hub"), _button("📂 Сохранённые профили" if ru else "📂 Saved profiles", "ux:setup:list")],
            [_button("➕ Создать профиль" if ru else "➕ Create profile", "ux:setup:create"), _button("⚡ Готовые профили" if ru else "⚡ Ready profiles", "ux:setupbuilder:start:template")],
            [_button("🎛 Расширенная настройка" if ru else "🎛 Advanced setup", "ux:filtershub"), _button("🔔 Уведомления" if ru else "🔔 Notifications", "v2:notifications:hub")],
            [_button("🚫 Исключения" if ru else "🚫 Exclusions", "ux:hidemute")],
            _back_home_row(language_code),
        ]
    )


def build_gold_keyboard(*, language_code: str) -> dict[str, object]:
    ru = _is_ru(language_code)
    return _markup(
        [
            [_button("🥇 Текущая ситуация" if ru else "🥇 Current situation", "ux:goldview"), _button("🎯 Настроить Gold-поток" if ru else "🎯 Set up Gold flow", "ux:goldwizard:start")],
            [_button("📊 Результаты Gold" if ru else "📊 Gold results", "results:hub"), _button("📖 Как работает Gold" if ru else "📖 How Gold works", "ux:help:gold")],
            [_button("🔔 Уведомления Gold" if ru else "🔔 Gold notifications", "v2:notifications:hub")],
            _back_home_row(language_code),
        ]
    )
