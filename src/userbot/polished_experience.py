from __future__ import annotations

from datetime import datetime

from src.core.utils import escape_html
from src.localization import normalize_language
from src.payments.onboarding import EffectiveAccessState
from src.storage.models import UserSettingsRecord
from src.userbot.experience import (
    ControlCenterMetrics,
    delivery_mode_label,
    display_mode_label,
    format_quiet_hours_window,
    is_snoozed,
    is_within_quiet_hours,
    tracking_scope_label,
    watchlist_theme_label,
)


def _state(enabled: bool, *, language_code: str) -> str:
    if normalize_language(language_code) == "ru":
        return "Вкл" if enabled else "Выкл"
    return "On" if enabled else "Off"


def _quiet_hours_state_label(
    settings: UserSettingsRecord,
    *,
    language_code: str,
) -> str:
    start = settings.quiet_hours_start_minute
    end = settings.quiet_hours_end_minute
    if start is None or end is None:
        return "Вкл" if normalize_language(language_code) == "ru" else "On"
    window = f"{start // 60:02d}:{start % 60:02d}-{end // 60:02d}:{end % 60:02d}"
    return f"{'Выкл' if normalize_language(language_code) == 'ru' else 'Off'} {window}"


def format_section_hub(title: str, body: str) -> str:
    return f"<b>{escape_html(title)}</b>\n\n{escape_html(body)}"


def format_settings_center_message(
    *,
    settings: UserSettingsRecord,
    language_code: str,
    workspace_label: str,
    has_saved_workspace: bool,
) -> str:
    quiet_window = format_quiet_hours_window(
        settings.quiet_hours_start_minute,
        settings.quiet_hours_end_minute,
        language_code=language_code,
    )
    delivery_label = delivery_mode_label(settings.delivery_mode, language_code=language_code)
    display_label = display_mode_label(settings.display_mode, language_code=language_code)
    theme_label = watchlist_theme_label(
        settings.active_watchlist_theme,
        language_code=language_code,
        custom_theme_name=settings.active_custom_theme_name,
    )
    if normalize_language(language_code) == "ru":
        saved_line = "есть" if has_saved_workspace else "пока нет"
        return (
            "<b>⚙️ Настройки</b>\n\n"
            "Управляй потоком, привычками и тем, как бот выглядит для тебя.\n\n"
            "Открой нужный раздел ниже — внутри будет короткое объяснение и понятные кнопки выбора.\n\n"
            f"Режим: <b>{escape_html(workspace_label)}</b>\n"
            f"Доставка: <b>{escape_html(delivery_label)}</b>\n"
            f"Ночь: <b>{escape_html(quiet_window)}</b>\n"
            f"Экран: <b>{escape_html(display_label)}</b>\n"
            f"Тема рынка: <b>{escape_html(theme_label)}</b>\n"
            f"Сохранённый режим: <b>{saved_line}</b>"
        )
    saved_line = "ready" if has_saved_workspace else "not saved yet"
    return (
        "<b>⚙️ Settings</b>\n\n"
        "Control your flow, habits, and how the bot feels day to day.\n\n"
        "Open any section below to see a short explanation first, then clear choices.\n\n"
        f"Mode: <b>{escape_html(workspace_label)}</b>\n"
        f"Delivery: <b>{escape_html(delivery_label)}</b>\n"
        f"Night Hours: <b>{escape_html(quiet_window)}</b>\n"
        f"Display: <b>{escape_html(display_label)}</b>\n"
        f"Market Theme: <b>{escape_html(theme_label)}</b>\n"
        f"Saved Mode: <b>{saved_line}</b>"
    )


def format_workspace_center_message(
    *,
    settings: UserSettingsRecord,
    language_code: str,
    workspace_label: str,
    has_saved_workspace: bool,
) -> str:
    delivery_label = delivery_mode_label(settings.delivery_mode, language_code=language_code)
    summary = f"{workspace_label} • {delivery_label}"
    if normalize_language(language_code) == "ru":
        empty_note = (
            "Сохранённый профиль уже готов."
            if has_saved_workspace
            else "Пока нет сохранённого профиля. Сохрани текущую настройку, чтобы переключаться быстрее."
        )
        return (
            "<b>🧩 Профиль</b>\n\n"
            "Сохраняй и переключай личные торговые режимы без повторной настройки.\n\n"
            f"Текущий: <b>{escape_html(summary)}</b>\n\n"
            f"{escape_html(empty_note)}"
        )
    empty_note = (
        "A saved custom workspace is ready."
        if has_saved_workspace
        else "No saved custom workspace yet. Save your current setup to switch faster later."
    )
    return (
        "<b>🧩 Workspace</b>\n\n"
        "Save and switch between personalized setups.\n\n"
        f"Current: <b>{escape_html(summary)}</b>\n\n"
        f"{escape_html(empty_note)}"
    )


def format_delivery_center_message(
    *,
    settings: UserSettingsRecord,
    access_state: EffectiveAccessState,
    language_code: str,
    timezone_obj,
    now: datetime,
) -> str:
    del access_state
    return format_scoped_delivery_center_message(
        settings=settings,
        access_state=None,
        language_code=language_code,
        timezone_obj=timezone_obj,
        now=now,
        strategy_label=None,
        scope_note=None,
    )


def format_scoped_delivery_center_message(
    *,
    settings: UserSettingsRecord,
    access_state,
    language_code: str,
    timezone_obj,
    now: datetime,
    strategy_label: str | None = None,
    scope_note: str | None = None,
) -> str:
    del access_state
    delivery_label = delivery_mode_label(settings.delivery_mode, language_code=language_code)
    night_label = _quiet_hours_state_label(settings, language_code=language_code)
    is_ru = normalize_language(language_code) == "ru"
    lines = [
        "<b>🔔 Уведомления</b>" if is_ru else "<b>🔔 Notifications</b>",
        "",
        "Управляй тем, что приходит, и как именно бот это доставляет."
        if is_ru
        else "Control what you receive and how it reaches you.",
        "",
    ]
    if strategy_label:
        lines.append(f"{'Стратегия' if is_ru else 'Strategy'}: <b>{escape_html(strategy_label)}</b>")
    lines.extend(
        [
            f"{'Сигналы' if is_ru else 'Alerts'}: <b>{_state(settings.direct_signal_delivery_enabled, language_code=language_code)}</b>",
            f"{'Фоллоу-апы' if is_ru else 'Follow-Ups'}: <b>{_state(settings.followup_delivery_enabled, language_code=language_code)}</b>",
            f"{'Золото' if is_ru else 'Gold'}: <b>{_state(settings.gold_alerts_enabled, language_code=language_code)}</b>",
            f"{'Режим' if is_ru else 'Mode'}: <b>{escape_html(delivery_label)}</b>",
            f"{'Ночные уведомления' if is_ru else 'Night alerts'}: <b>{escape_html(night_label)}</b>",
        ]
    )
    if is_snoozed(settings, now=now):
        snooze_until = settings.snooze_until.astimezone(timezone_obj).strftime("%d %b %H:%M")
        lines.extend(
            [
                "",
                f"Пауза активна до <b>{escape_html(snooze_until)}</b>."
                if is_ru
                else f"Notifications are snoozed until <b>{escape_html(snooze_until)}</b>.",
            ]
        )
    elif is_within_quiet_hours(settings, now=now, timezone_obj=timezone_obj):
        lines.extend(["", "Тихие часы сейчас активны." if is_ru else "Quiet hours are active right now."])
    if scope_note:
        lines.extend(["", escape_html(scope_note)])
    return "\n".join(lines)


def format_watchlists_message(
    *,
    active_theme_label: str,
    active_symbols: list[str],
    saved_theme_names: list[str],
    tracking_label: str,
    watchlist_only: bool,
    language_code: str,
    favorites_count: int | None = None,
    active_watchlist_count: int | None = None,
    alerts_enabled: bool | None = None,
) -> str:
    active_count = active_watchlist_count if active_watchlist_count is not None else len(active_symbols)
    favorites_total = favorites_count if favorites_count is not None else len(active_symbols)
    saved_total = len(saved_theme_names)
    alerts_label = (
        _state(bool(alerts_enabled), language_code=language_code)
        if alerts_enabled is not None
        else ("Вкл" if normalize_language(language_code) == "ru" else "On")
    )
    tracking_line = tracking_label if watchlist_only else ("весь рынок" if normalize_language(language_code) == "ru" else "full market")
    if normalize_language(language_code) == "ru":
        return (
            "<b>👀 Вотчлист</b>\n\n"
            "Твоё личное рыночное пространство.\n\n"
            "Отслеживай символы, избранное и сохранённые наборы, которые формируют твой поток.\n\n"
            f"Вотчлист: <b>{active_count}</b>\n"
            f"Избранное: <b>{favorites_total}</b>\n"
            f"Наборы: <b>{saved_total}</b>\n"
            f"Тема по умолчанию: <b>{escape_html(active_theme_label)}</b>\n"
            f"Охват: <b>{escape_html(tracking_line)}</b>\n"
            f"Уведомления: <b>{alerts_label}</b>"
        )
    return (
        "<b>👀 Watchlist</b>\n\n"
        "Your personal market space.\n\n"
        "Track the symbols, favorites, and saved sets that shape your signal flow.\n\n"
        f"Watchlist: <b>{active_count}</b>\n"
        f"Favorites: <b>{favorites_total}</b>\n"
        f"Saved Sets: <b>{saved_total}</b>\n"
        f"Default Set: <b>{escape_html(active_theme_label)}</b>\n"
        f"Tracking: <b>{escape_html(tracking_line)}</b>\n"
        f"Notifications: <b>{alerts_label}</b>"
    )


def format_control_center_message(
    *,
    metrics: ControlCenterMetrics,
    settings: UserSettingsRecord,
    access_state: EffectiveAccessState,
    language_code: str,
    strategy_label: str | None = None,
) -> str:
    del access_state
    is_ru = normalize_language(language_code) == "ru"
    lines = [
        "<b>📊 Результаты</b>" if is_ru else "<b>📊 Results</b>",
        "",
        "Смотри, как развивались сигналы, фоллоу-апы и итоговый поток."
        if is_ru
        else "Review outcomes, follow-ups, and how signals evolved.",
    ]
    if strategy_label:
        lines.extend(["", f"{'Стратегия' if is_ru else 'Strategy'}: <b>{escape_html(strategy_label)}</b>"])
    lines.extend(
        [
            "",
            f"{'Сегодня' if is_ru else 'Today'}: <b>{metrics.alerts_today}</b>",
            f"{'7 дней' if is_ru else 'Last 7d'}: <b>{metrics.alerts_7d}</b>",
            f"{'Фоллоу-апы' if is_ru else 'Follow-Ups'}: <b>{metrics.followups_30d}</b>",
            f"{'Попадания в вотчлист' if is_ru else 'Watchlist Hits'}: <b>{metrics.watchlist_hits_30d}</b>",
            f"{'Доставка' if is_ru else 'Delivery'}: <b>{escape_html(delivery_mode_label(settings.delivery_mode, language_code=language_code))}</b>",
        ]
    )
    if metrics.strongest_symbol and metrics.strongest_score is not None:
        lines.append(
            f"Сильнейший сетап: <b>{escape_html(metrics.strongest_symbol)} {metrics.strongest_score}/100</b>"
            if is_ru
            else f"Top setup: <b>{escape_html(metrics.strongest_symbol)} {metrics.strongest_score}/100</b>"
        )
    return "\n".join(lines)
