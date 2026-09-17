from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from src.core.utils import escape_html, format_percent, normalize_symbol
from src.localization import is_russian, normalize_language, ui_text
from src.payments.onboarding import EffectiveAccessState
from src.storage.models import AlertRecord, DeliveredSignalRecord, FollowUpResultRecord, UserSettingsRecord
from src.userbot.premium_text import premium_text

BUILTIN_WATCHLIST_THEMES: dict[str, tuple[str, ...]] = {
    "majors": ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"),
    "memes": ("DOGEUSDT", "PEPEUSDT", "WIFUSDT", "BONKUSDT", "SHIBUSDT"),
    "gold": ("XAUUSD",),
}

QUIET_HOUR_PRESETS: dict[str, tuple[int | None, int | None]] = {
    "off": (None, None),
    "late": (23 * 60, 7 * 60),
    "overnight": (0, 8 * 60),
}


@dataclass(slots=True)
class ControlCenterMetrics:
    alerts_today: int
    alerts_7d: int
    alerts_30d: int
    followups_30d: int
    watchlist_hits_30d: int
    strongest_score: int | None
    strongest_symbol: str | None
    top_symbols: list[tuple[str, int]]
    recent_summary: str


def delivery_mode_label(mode: str, *, language_code: str = "en") -> str:
    normalized = (mode or "instant").strip().lower()
    key = f"delivery_mode_{normalized}" if normalized in {"instant", "digest", "quiet"} else "delivery_mode_instant"
    return premium_text(language_code, key)


def display_mode_label(mode: str, *, language_code: str = "en") -> str:
    normalized = str(mode or "pro").strip().lower()
    if normalize_language(language_code) == "ru":
        return "Простой" if normalized == "simple" else "Pro"
    return "Simple" if normalized == "simple" else "Pro"


def watchlist_theme_label(
    theme_key: str,
    *,
    language_code: str = "en",
    custom_theme_name: str | None = None,
) -> str:
    normalized = (theme_key or "custom").strip().lower()
    if normalized == "custom" and custom_theme_name:
        return custom_theme_name
    key = f"theme_{normalized}" if normalized in {"majors", "memes", "gold", "custom"} else "theme_custom"
    return premium_text(language_code, key)


def format_quiet_hours_window(
    start_minute: int | None,
    end_minute: int | None,
    *,
    language_code: str = "en",
) -> str:
    if start_minute is None or end_minute is None:
        return premium_text(language_code, "delivery_state_on")
    window = f"{start_minute // 60:02d}:{start_minute % 60:02d}-{end_minute // 60:02d}:{end_minute % 60:02d}"
    return f"{premium_text(language_code, 'delivery_state_off')} {window}"


def tracking_scope_label(
    settings: UserSettingsRecord,
    *,
    language_code: str = "en",
) -> str:
    if not settings.watchlist_only:
        return premium_text(language_code, "scope_all_coins")
    theme_key = str(settings.active_watchlist_theme or "custom").strip().lower()
    if theme_key in BUILTIN_WATCHLIST_THEMES or settings.active_custom_theme_name:
        return premium_text(
            language_code,
            "scope_set",
            theme=watchlist_theme_label(
                settings.active_watchlist_theme,
                language_code=language_code,
                custom_theme_name=settings.active_custom_theme_name,
            ),
        )
    return premium_text(language_code, "scope_favorites")


def is_within_quiet_hours(
    settings: UserSettingsRecord | None,
    *,
    now: datetime,
    timezone_obj,
) -> bool:
    if settings is None:
        return False
    start = settings.quiet_hours_start_minute
    end = settings.quiet_hours_end_minute
    if start is None or end is None:
        return False
    local_now = now.astimezone(timezone_obj)
    current_minute = local_now.hour * 60 + local_now.minute
    if start < end:
        return start <= current_minute < end
    return current_minute >= start or current_minute < end


def is_snoozed(settings: UserSettingsRecord | None, *, now: datetime) -> bool:
    return bool(settings is not None and settings.snooze_until is not None and settings.snooze_until > now)


def format_section_hub(title: str, body: str) -> str:
    return f"<b>{escape_html(title)}</b>\n\n{escape_html(body)}"


def format_settings_center_message(
    *,
    settings: UserSettingsRecord,
    language_code: str,
    workspace_label: str,
    has_saved_workspace: bool,
) -> str:
    language = normalize_language(language_code)
    quiet_window = format_quiet_hours_window(
        settings.quiet_hours_start_minute,
        settings.quiet_hours_end_minute,
        language_code=language,
    )
    delivery_label = delivery_mode_label(settings.delivery_mode, language_code=language)
    display_label = display_mode_label(settings.display_mode, language_code=language)
    tracking_label = tracking_scope_label(settings, language_code=language)
    if is_russian(language):
        saved_line = "Готово" if has_saved_workspace else "Пока не сохранён"
        return (
            "<b>Settings</b>\n\n"
            "Управляй доставкой, персонализацией и рабочим режимом без лишнего шума.\n\n"
            "<b>Текущее состояние</b>\n"
            f"• Профиль: <b>{escape_html(workspace_label)}</b>\n"
            f"• Режим экрана: <b>{escape_html(display_label)}</b>\n"
            f"• Доставка: <b>{escape_html(delivery_label)}</b>\n"
            f"• Охват: <b>{escape_html(tracking_label)}</b>\n"
            f"• Тихие часы: <b>{escape_html(quiet_window)}</b>\n"
            f"• Gold Desk: <b>{'ВКЛ' if settings.gold_alerts_enabled else 'ВЫКЛ'}</b>\n"
            f"• Сохранённый профиль: <b>{saved_line}</b>\n\n"
            "Ниже можно быстро переключить уведомления, язык, workspace и глубину отображения."
        )
    saved_line = "Ready" if has_saved_workspace else "Not saved yet"
    return (
        "<b>Settings</b>\n\n"
        "Control your delivery, personalization, and default workflow.\n\n"
        "<b>Current State</b>\n"
        f"• Workspace: <b>{escape_html(workspace_label)}</b>\n"
        f"• Display Mode: <b>{escape_html(display_label)}</b>\n"
        f"• Delivery: <b>{escape_html(delivery_label)}</b>\n"
        f"• Tracking: <b>{escape_html(tracking_label)}</b>\n"
        f"• Quiet Hours: <b>{escape_html(quiet_window)}</b>\n"
        f"• Gold Desk: <b>{'ON' if settings.gold_alerts_enabled else 'OFF'}</b>\n"
        f"• Saved Workspace: <b>{saved_line}</b>\n\n"
        "Use the sections below to fine-tune alerts, filters, language, and display depth."
    )


def format_workspace_center_message(
    *,
    settings: UserSettingsRecord,
    language_code: str,
    workspace_label: str,
    has_saved_workspace: bool,
) -> str:
    language = normalize_language(language_code)
    delivery_label = delivery_mode_label(settings.delivery_mode, language_code=language)
    display_label = display_mode_label(settings.display_mode, language_code=language)
    tracking_label = tracking_scope_label(settings, language_code=language)
    theme_label = watchlist_theme_label(
        settings.active_watchlist_theme,
        language_code=language,
        custom_theme_name=settings.active_custom_theme_name,
    )
    if is_russian(language):
        saved_line = "есть" if has_saved_workspace else "нет"
        return (
            "<b>Workspace</b>\n\n"
            "Сохраняй и переключай личные торговые профили с разной плотностью сигналов и режимами доставки.\n\n"
            "<b>Активный профиль</b>\n"
            f"• Сейчас: <b>{escape_html(workspace_label)}</b>\n"
            f"• Доставка: <b>{escape_html(delivery_label)}</b>\n"
            f"• Режим экрана: <b>{escape_html(display_label)}</b>\n"
            f"• Охват: <b>{escape_html(tracking_label)}</b>\n"
            f"• Тема: <b>{escape_html(theme_label)}</b>\n"
            f"• Снимок текущих настроек: <b>{saved_line}</b>\n\n"
            "Выбери готовый workspace ниже, сохрани текущий или открой мастер настройки."
        )
    saved_line = "available" if has_saved_workspace else "not saved"
    return (
        "<b>Workspace</b>\n\n"
        "Save and switch between personalized trading profiles with different signal flow, filters, and delivery styles.\n\n"
        "<b>Active Workspace</b>\n"
        f"• Current: <b>{escape_html(workspace_label)}</b>\n"
        f"• Delivery: <b>{escape_html(delivery_label)}</b>\n"
        f"• Display Mode: <b>{escape_html(display_label)}</b>\n"
        f"• Tracking: <b>{escape_html(tracking_label)}</b>\n"
        f"• Theme: <b>{escape_html(theme_label)}</b>\n"
        f"• Saved Snapshot: <b>{saved_line}</b>\n\n"
        "Choose a preset below, save your current setup, or open the wizard to build a new one."
    )


def format_delivery_center_message(
    *,
    settings: UserSettingsRecord,
    access_state: EffectiveAccessState,
    language_code: str,
    timezone_obj,
    now: datetime,
) -> str:
    quiet_window = format_quiet_hours_window(
        settings.quiet_hours_start_minute,
        settings.quiet_hours_end_minute,
        language_code=language_code,
    )
    lines = [
        f"<b>📬 {escape_html(premium_text(language_code, 'hub_delivery_title'))}</b>",
        "",
        escape_html(premium_text(language_code, "delivery_center_intro")),
        "",
        "⚙️ "
        + escape_html(
            premium_text(
                language_code,
                "delivery_status_mode",
                mode=delivery_mode_label(settings.delivery_mode, language_code=language_code),
            )
        ),
        "🔁 "
        + escape_html(
            premium_text(
                language_code,
                "delivery_status_followups",
                state=premium_text(
                    language_code,
                    "delivery_state_on" if settings.followup_delivery_enabled else "delivery_state_off",
                ),
            )
        ),
    ]
    if access_state.has_premium_access:
        lines.append(
            "🥇 "
            + escape_html(
                premium_text(
                    language_code,
                    "delivery_status_gold",
                    state=premium_text(
                        language_code,
                        "delivery_state_on" if settings.gold_alerts_enabled else "delivery_state_off",
                    ),
                )
            )
        )
    lines.append("🌙 " + escape_html(premium_text(language_code, "delivery_status_quiet", window=quiet_window)))
    if is_snoozed(settings, now=now):
        timestamp = settings.snooze_until.astimezone(timezone_obj).strftime("%d %b %H:%M")
        lines.append("")
        lines.append("⏸ " + escape_html(premium_text(language_code, "delivery_status_paused", timestamp=timestamp)))
    elif is_within_quiet_hours(settings, now=now, timezone_obj=timezone_obj):
        lines.append("")
        lines.append("😴 " + escape_html(premium_text(language_code, "delivery_status_quiet_hours", window=quiet_window)))
    else:
        lines.append("")
        lines.append("✅ " + escape_html(premium_text(language_code, "delivery_status_live")))
    return "\n".join(lines)


def _experience_state(enabled: bool, *, language_code: str) -> str:
    if normalize_language(language_code) == "ru":
        return "Вкл" if enabled else "Выкл"
    return "On" if enabled else "Off"


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
            "Управляй потоком, привычками и режимом отображения без лишнего шума.\n\n"
            f"Профиль: <b>{escape_html(workspace_label)}</b>\n"
            f"Доставка: <b>{escape_html(delivery_label)}</b>\n"
            f"Тихие часы: <b>{escape_html(quiet_window)}</b>\n"
            f"Режим экрана: <b>{escape_html(display_label)}</b>\n"
            f"Тема: <b>{escape_html(theme_label)}</b>\n"
            f"Сохранённый workspace: <b>{saved_line}</b>"
        )
    saved_line = "ready" if has_saved_workspace else "not saved yet"
    return (
        "<b>⚙️ Settings</b>\n\n"
        "Control your flow, preferences, and default experience.\n\n"
        f"Workspace: <b>{escape_html(workspace_label)}</b>\n"
        f"Delivery: <b>{escape_html(delivery_label)}</b>\n"
        f"Quiet Hours: <b>{escape_html(quiet_window)}</b>\n"
        f"Display Mode: <b>{escape_html(display_label)}</b>\n"
        f"Theme: <b>{escape_html(theme_label)}</b>\n"
        f"Saved Workspace: <b>{saved_line}</b>"
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
            "Сохранённый custom-workspace уже готов."
            if has_saved_workspace
            else "Пока нет сохранённого custom-workspace. Сохрани текущую настройку, чтобы переключаться быстрее."
        )
        return (
            "<b>🧩 Workspace</b>\n\n"
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
    quiet_window = format_quiet_hours_window(
        settings.quiet_hours_start_minute,
        settings.quiet_hours_end_minute,
        language_code=language_code,
    )
    is_ru_local = normalize_language(language_code) == "ru"
    lines = [
        "<b>🔔 Уведомления</b>" if is_ru_local else "<b>🔔 Notifications</b>",
        "",
        "Управляй тем, что приходит, и как именно бот это доставляет."
        if is_ru_local
        else "Control what you receive and how it reaches you.",
        "",
    ]
    if strategy_label:
        lines.append(f"{'Стратегия' if is_ru_local else 'Scope'}: <b>{escape_html(strategy_label)}</b>")
    lines.extend(
        [
            f"{'Сигналы' if is_ru_local else 'Alerts'}: <b>{_experience_state(settings.direct_signal_delivery_enabled, language_code=language_code)}</b>",
            f"{'Фоллоу-апы' if is_ru_local else 'Follow-Ups'}: <b>{_experience_state(settings.followup_delivery_enabled, language_code=language_code)}</b>",
            f"Gold Desk: <b>{_experience_state(settings.gold_alerts_enabled, language_code=language_code)}</b>",
            f"{'Режим' if is_ru_local else 'Mode'}: <b>{escape_html(delivery_label)}</b>",
            f"{'Тихие часы' if is_ru_local else 'Quiet Hours'}: <b>{escape_html(quiet_window)}</b>",
        ]
    )
    if is_snoozed(settings, now=now):
        snooze_until = settings.snooze_until.astimezone(timezone_obj).strftime("%d %b %H:%M")
        lines.extend(
            [
                "",
                f"Пауза активна до <b>{escape_html(snooze_until)}</b>."
                if is_ru_local
                else f"Notifications are snoozed until <b>{escape_html(snooze_until)}</b>.",
            ]
        )
    elif is_within_quiet_hours(settings, now=now, timezone_obj=timezone_obj):
        lines.extend(
            [
                "",
                "Тихие часы сейчас активны." if is_ru_local else "Quiet hours are active right now.",
            ]
        )
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
        _experience_state(bool(alerts_enabled), language_code=language_code)
        if alerts_enabled is not None
        else ("Вкл" if normalize_language(language_code) == "ru" else "On")
    )
    if normalize_language(language_code) == "ru":
        return (
            "<b>👀 Watchlist</b>\n\n"
            "Твоё личное рыночное пространство.\n\n"
            "Отслеживай символы, избранное и сохранённые наборы, которые формируют твой поток.\n\n"
            f"Watchlist: <b>{active_count}</b>\n"
            f"Избранное: <b>{favorites_total}</b>\n"
            f"Наборы: <b>{saved_total}</b>\n"
            f"Тема по умолчанию: <b>{escape_html(active_theme_label)}</b>\n"
            f"Охват: <b>{escape_html(tracking_label if watchlist_only else 'весь рынок')}</b>\n"
            f"Алерты: <b>{alerts_label}</b>"
        )
    return (
        "<b>👀 Watchlist</b>\n\n"
        "Your personal market space.\n\n"
        "Track the symbols, favorites, and saved sets that shape your signal flow.\n\n"
        f"Watchlist: <b>{active_count}</b>\n"
        f"Favorites: <b>{favorites_total}</b>\n"
        f"Saved Sets: <b>{saved_total}</b>\n"
        f"Default Set: <b>{escape_html(active_theme_label)}</b>\n"
        f"Tracking: <b>{escape_html(tracking_label if watchlist_only else 'full market')}</b>\n"
        f"Alerts: <b>{alerts_label}</b>"
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
    is_ru_local = normalize_language(language_code) == "ru"
    lines = [
        "<b>📊 Результаты</b>" if is_ru_local else "<b>📊 Results</b>",
        "",
        "Смотри, как развивались сигналы, follow-up и итоговый поток."
        if is_ru_local
        else "Review outcomes, follow-ups, and how signals evolved.",
    ]
    if strategy_label:
        lines.extend(["", f"{'Стратегия' if is_ru_local else 'Strategy'}: <b>{escape_html(strategy_label)}</b>"])
    lines.extend(
        [
            "",
            f"{'Сегодня' if is_ru_local else 'Today'}: <b>{metrics.alerts_today}</b>",
            f"{'7 дней' if is_ru_local else 'Last 7d'}: <b>{metrics.alerts_7d}</b>",
            f"{'Фоллоу-апы' if is_ru_local else 'Follow-Ups'}: <b>{metrics.followups_30d}</b>",
            f"{'Попадания в watchlist' if is_ru_local else 'Watchlist Hits'}: <b>{metrics.watchlist_hits_30d}</b>",
            f"{'Доставка' if is_ru_local else 'Delivery'}: <b>{escape_html(delivery_mode_label(settings.delivery_mode, language_code=language_code))}</b>",
        ]
    )
    if metrics.strongest_symbol and metrics.strongest_score is not None:
        lines.append(
            f"Сильнейший сетап: <b>{escape_html(metrics.strongest_symbol)} {metrics.strongest_score}/100</b>"
            if is_ru_local
            else f"Top setup: <b>{escape_html(metrics.strongest_symbol)} {metrics.strongest_score}/100</b>"
        )
    return "\n".join(lines)


def format_scoped_delivery_center_message(
    *,
    settings: UserSettingsRecord,
    access_state: EffectiveAccessState,
    language_code: str,
    timezone_obj,
    now: datetime,
    strategy_label: str | None = None,
    scope_note: str | None = None,
) -> str:
    quiet_window = format_quiet_hours_window(
        settings.quiet_hours_start_minute,
        settings.quiet_hours_end_minute,
        language_code=language_code,
    )
    lines = [f"<b>📬 {escape_html(premium_text(language_code, 'hub_delivery_title'))}</b>", ""]
    if strategy_label:
        lines.extend(
            [
                (
                    f"Стратегия: <b>{escape_html(strategy_label)}</b>"
                    if is_russian(language_code)
                    else f"Strategy: <b>{escape_html(strategy_label)}</b>"
                ),
                "",
            ]
        )
    lines.append(escape_html(premium_text(language_code, "delivery_center_intro")))
    if scope_note:
        lines.extend(["", escape_html(scope_note)])
    lines.extend(
        [
            "",
            "⚙️ "
            + escape_html(
                premium_text(
                    language_code,
                    "delivery_status_mode",
                    mode=delivery_mode_label(settings.delivery_mode, language_code=language_code),
                )
            ),
            "🔃 "
            + escape_html(
                premium_text(
                    language_code,
                    "delivery_status_followups",
                    state=premium_text(
                        language_code,
                        "delivery_state_on" if settings.followup_delivery_enabled else "delivery_state_off",
                    ),
                )
            ),
        ]
    )
    if access_state.has_premium_access:
        lines.append(
            "🥇 "
            + escape_html(
                premium_text(
                    language_code,
                    "delivery_status_gold",
                    state=premium_text(
                        language_code,
                        "delivery_state_on" if settings.gold_alerts_enabled else "delivery_state_off",
                    ),
                )
            )
        )
    lines.append("🌙 " + escape_html(premium_text(language_code, "delivery_status_quiet", window=quiet_window)))
    if is_snoozed(settings, now=now):
        timestamp = settings.snooze_until.astimezone(timezone_obj).strftime("%d %b %H:%M")
        lines.extend(["", "⏸ " + escape_html(premium_text(language_code, "delivery_status_paused", timestamp=timestamp))])
    elif is_within_quiet_hours(settings, now=now, timezone_obj=timezone_obj):
        lines.extend(["", "😴 " + escape_html(premium_text(language_code, "delivery_status_quiet_hours", window=quiet_window))])
    else:
        lines.extend(["", "✅ " + escape_html(premium_text(language_code, "delivery_status_live"))])
    return "\n".join(lines)


def format_gold_center_message(
    *,
    gold_alerts_enabled: bool,
    language_code: str,
    market_note: str | None = None,
) -> str:
    lines = [
        f"<b>🪙 {escape_html(premium_text(language_code, 'gold_center_title'))}</b>",
        "",
        escape_html(premium_text(language_code, "gold_center_intro")),
        "",
    ]
    if market_note:
        lines.extend(["⚠️ " + escape_html(market_note), ""])
    lines.extend(
        [
            "🔔 "
            + escape_html(
                premium_text(
                    language_code,
                    "gold_center_alerts",
                    state=premium_text(language_code, "delivery_state_on" if gold_alerts_enabled else "delivery_state_off"),
                )
            ),
            "📈 " + escape_html(premium_text(language_code, "gold_center_same_chart")),
            "🌐 " + escape_html(premium_text(language_code, "gold_center_external", label="TradingView")),
            "",
            escape_html(premium_text(language_code, "gold_center_hint")),
        ]
    )
    return "\n".join(lines)


def format_gold_center_message(
    *,
    gold_alerts_enabled: bool,
    language_code: str,
    market_note: str | None = None,
    strategies: list[dict[str, str | bool]] | None = None,
) -> str:
    is_ru = normalize_language(language_code) == "ru"
    title = "Gold / XAUUSD" if not is_ru else "Gold / XAUUSD"
    master_state = premium_text(
        language_code,
        "delivery_state_on" if gold_alerts_enabled else "delivery_state_off",
    )
    intro = (
        "Отдельный центр по золоту: включай общий поток и точечно управляй входами по каждой модели."
        if is_ru
        else "Dedicated gold hub: control the master flow and fine-tune entries with separate models."
    )
    toggle_hint = (
        "Ниже можно отдельно включать пробой, откат по тренду и liquidity-reversal."
        if is_ru
        else "Below you can toggle breakout, pullback, and liquidity-reversal models separately."
    )
    lines = [f"<b>🥇 {escape_html(title)}</b>", "", escape_html(intro)]
    if market_note:
        lines.extend(["", "⚠️ " + escape_html(market_note)])
    lines.extend(
        [
            "",
            f"{'Поток' if is_ru else 'Master flow'}: <b>{escape_html(master_state)}</b>",
            "📈 " + escape_html(toggle_hint),
        ]
    )
    for strategy in strategies or []:
        label = str(strategy.get("label") or "")
        summary = str(strategy.get("summary") or "")
        enabled = bool(strategy.get("enabled"))
        state = "ВКЛ" if enabled and is_ru else "ВЫКЛ" if is_ru else "ON" if enabled else "OFF"
        lines.extend(
            [
                "",
                f"<b>{escape_html(label)}</b> • <b>{state}</b>",
                escape_html(summary),
            ]
        )
    lines.extend(
        [
            "",
            escape_html(
                "Открой карточку XAUUSD для текущего графика или включай только те сценарии, которые тебе реально нужны."
                if is_ru
                else "Open the XAUUSD card for the live chart, or keep only the gold scenarios you actually want."
            ),
        ]
    )
    return "\n".join(lines)


def build_control_center_metrics(
    deliveries: list[DeliveredSignalRecord],
    *,
    now: datetime,
    language_code: str = "en",
) -> ControlCenterMetrics:
    alerts_today = 0
    alerts_7d = 0
    alerts_30d = 0
    followups_30d = 0
    watchlist_hits_30d = 0
    strongest_score: int | None = None
    strongest_symbol: str | None = None
    symbol_counter: Counter[str] = Counter()
    now_ts = now.timestamp()

    for delivery in deliveries:
        age_days = max((now_ts - delivery.delivered_at.timestamp()) / 86400.0, 0.0)
        score = delivery.metadata.get("score")
        symbol = normalize_symbol(str(delivery.metadata.get("symbol") or ""))
        if symbol:
            symbol_counter[symbol] += 1
        if delivery.message_kind == "alert":
            if age_days < 1:
                alerts_today += 1
            if age_days < 7:
                alerts_7d += 1
            if age_days < 30:
                alerts_30d += 1
                if delivery.metadata.get("watchlist_hit"):
                    watchlist_hits_30d += 1
        elif delivery.message_kind.startswith("followup:") and age_days < 30:
            followups_30d += 1
        if isinstance(score, int) and (strongest_score is None or score > strongest_score):
            strongest_score = score
            strongest_symbol = symbol or strongest_symbol

    if alerts_today or alerts_7d or followups_30d:
        if is_russian(language_code):
            recent_summary = f"{alerts_today} сегодня • {alerts_7d} за 7д • {followups_30d} follow-up"
        else:
            recent_summary = f"{alerts_today} today • {alerts_7d} in 7d • {followups_30d} follow-ups"
    else:
        recent_summary = ""

    if alerts_today or alerts_7d or followups_30d:
        recent_summary = (
            f"{alerts_today} сегодня • {alerts_7d} за 7д • {followups_30d} фоллоу-апов"
            if is_russian(language_code)
            else f"{alerts_today} today • {alerts_7d} in 7d • {followups_30d} follow-ups"
        )
    else:
        recent_summary = ""

    return ControlCenterMetrics(
        alerts_today=alerts_today,
        alerts_7d=alerts_7d,
        alerts_30d=alerts_30d,
        followups_30d=followups_30d,
        watchlist_hits_30d=watchlist_hits_30d,
        strongest_score=strongest_score,
        strongest_symbol=strongest_symbol,
        top_symbols=symbol_counter.most_common(4),
        recent_summary=recent_summary,
    )


def format_control_center_message(
    *,
    metrics: ControlCenterMetrics,
    settings: UserSettingsRecord,
    access_state: EffectiveAccessState,
    language_code: str,
) -> str:
    language = normalize_language(language_code)
    is_ru = is_russian(language)
    theme_label = watchlist_theme_label(
        settings.active_watchlist_theme,
        language_code=language,
        custom_theme_name=settings.active_custom_theme_name,
    )
    quiet_window = format_quiet_hours_window(
        settings.quiet_hours_start_minute,
        settings.quiet_hours_end_minute,
        language_code=language,
    )
    tracking_label = tracking_scope_label(settings, language_code=language)
    access_label = "PRO+" if access_state.has_premium_access else ui_text(language, "status_free")
    profile_key = f"profile_{str(settings.signal_profile or 'custom').strip().lower()}"
    profile_label = (
        ui_text(language, profile_key)
        if profile_key in {"profile_conservative", "profile_balanced", "profile_aggressive", "profile_custom"}
        else str(settings.signal_profile or "custom").title()
    )
    lines = [
        f"<b>📊 {escape_html(premium_text(language, 'control_center_title'))}</b>",
        "",
        f"<b>{'Пульс за период' if is_ru else 'Period Pulse'}</b>",
        f"• {escape_html(premium_text(language, 'control_center_today'))}: <b>{metrics.alerts_today}</b>",
        f"• {escape_html(premium_text(language, 'control_center_week'))}: <b>{metrics.alerts_7d}</b>",
        f"• {escape_html(premium_text(language, 'control_center_month'))}: <b>{metrics.alerts_30d}</b>",
        f"• {'Фоллоу-апы' if is_ru else 'Follow-ups'}: <b>{metrics.followups_30d}</b>",
        f"• {'Попадания в список' if is_ru else 'Tracked-list hits'}: <b>{metrics.watchlist_hits_30d}</b>",
        "",
        f"<b>📬 {escape_html(premium_text(language, 'control_center_delivery'))}</b>",
        f"• {'Режим' if is_ru else 'Mode'}: <b>{escape_html(delivery_mode_label(settings.delivery_mode, language_code=language))}</b>",
        f"• {'Ночь' if is_ru else 'Night alerts'}: <b>{escape_html(quiet_window)}</b>",
        f"• {'Доступ' if is_ru else 'Access'}: <b>{escape_html(access_label)}</b>",
        "",
        f"<b>🧩 {escape_html(premium_text(language, 'control_center_setup'))}</b>",
        f"• {'Профиль' if is_ru else 'Profile'}: <b>{escape_html(profile_label)}</b>",
        f"• {'Отслеживание' if is_ru else 'Tracking'}: <b>{escape_html(tracking_label)}</b>",
        f"• {'Текущий набор' if is_ru else 'Current set'}: <b>{escape_html(theme_label)}</b>",
    ]
    if metrics.strongest_score is not None and metrics.strongest_symbol:
        lines.extend(
            [
                "",
                f"<b>🏆 {escape_html(premium_text(language, 'control_center_top'))}</b>",
                f"• {'Сильнейший доставленный' if is_ru else 'Strongest delivered'}: <b>{escape_html(metrics.strongest_symbol)} {metrics.strongest_score}/100</b>",
            ]
        )
    if metrics.top_symbols:
        top_symbols = ", ".join(f"{symbol} x{count}" for symbol, count in metrics.top_symbols)
        lines.append(f"• {'Активные тикеры' if is_ru else 'Most active tickers'}: <b>{escape_html(top_symbols)}</b>")
    if metrics.recent_summary:
        lines.extend(
            [
                "",
                f"<b>📍 {escape_html(premium_text(language, 'control_center_activity'))}</b>",
                escape_html(metrics.recent_summary),
            ]
        )
    elif not metrics.top_symbols:
        lines.extend(["", escape_html(premium_text(language, "control_center_none"))])
    return "\n".join(lines)


def _alert_line(alert: AlertRecord) -> str:
    return f"{normalize_symbol(alert.symbol)} • {alert.score}/100 • {alert.timeframe}"


def _followup_line(result: FollowUpResultRecord) -> str:
    return f"{normalize_symbol(result.symbol)} • {result.stage} • {format_percent(result.move_pct)}"


def _followup_favorable_move(result: FollowUpResultRecord) -> float:
    favorable = result.metadata.get("favorable_move_pct")
    if isinstance(favorable, (int, float)):
        return float(favorable)
    if result.direction in {"oversold", "long"}:
        return max(float(result.move_pct), 0.0)
    if result.direction in {"overbought", "short"}:
        return max(-float(result.move_pct), 0.0)
    return 0.0


def _recap_followup_line(result: FollowUpResultRecord) -> str:
    return f"{normalize_symbol(result.symbol)} • {result.stage} • {format_percent(_followup_favorable_move(result))}"


def format_digest_message(
    *,
    alerts: list[AlertRecord],
    watchlist_alerts: list[AlertRecord],
    followups: list[FollowUpResultRecord],
    language_code: str,
) -> str:
    lines = [f"<b>🕒 {escape_html(premium_text(language_code, 'digest_title'))}</b>"]
    if not alerts and not watchlist_alerts and not followups:
        lines.extend(["", escape_html(premium_text(language_code, "digest_empty"))])
        return "\n".join(lines)
    if alerts:
        lines.extend(["", f"<b>🔥 {escape_html(premium_text(language_code, 'digest_strongest'))}</b>"])
        lines.extend(f"• {escape_html(_alert_line(alert))}" for alert in alerts[:3])
    if watchlist_alerts:
        lines.extend(["", f"<b>⭐ {escape_html(premium_text(language_code, 'digest_watchlist_hits'))}</b>"])
        lines.extend(f"• {escape_html(_alert_line(alert))}" for alert in watchlist_alerts[:2])
    if followups:
        lines.extend(["", f"<b>🔁 {escape_html(premium_text(language_code, 'digest_followups'))}</b>"])
        lines.extend(f"• {escape_html(_followup_line(item))}" for item in followups[:2])
    return "\n".join(lines)


def format_resume_message(
    *,
    alert_count: int,
    strongest_alerts: list[AlertRecord],
    watchlist_alerts: list[AlertRecord],
    followups: list[FollowUpResultRecord],
    language_code: str,
) -> str:
    language = normalize_language(language_code)
    lines = [f"<b>👋 {escape_html(premium_text(language, 'resume_title'))}</b>"]
    if alert_count <= 0 and not followups:
        lines.extend(["", escape_html(premium_text(language, "resume_empty"))])
        return "\n".join(lines)
    lines.append("")
    lines.append(
        "New signals missed: <b>{count}</b>".format(count=alert_count)
        if not is_russian(language)
        else "Новых сигналов пропущено: <b>{count}</b>".format(count=alert_count)
    )
    if strongest_alerts:
        lines.extend(["", f"<b>🔥 {escape_html(premium_text(language, 'digest_strongest'))}</b>"])
        lines.extend(f"• {escape_html(_alert_line(alert))}" for alert in strongest_alerts[:3])
    if watchlist_alerts:
        lines.extend(["", f"<b>⭐ {escape_html(premium_text(language, 'digest_watchlist_hits'))}</b>"])
        lines.extend(f"• {escape_html(_alert_line(alert))}" for alert in watchlist_alerts[:2])
    if followups:
        lines.extend(["", f"<b>🔁 {escape_html(premium_text(language, 'digest_followups'))}</b>"])
        lines.extend(f"• {escape_html(_followup_line(item))}" for item in followups[:2])
    return "\n".join(lines)


def format_recap_message(
    *,
    title: str,
    alerts: list[AlertRecord],
    followups: list[FollowUpResultRecord],
    language_code: str,
    delivered_alerts_count: int = 0,
    followups_title: str | None = None,
    followups_as_winners: bool = False,
    empty_text: str | None = None,
) -> str:
    lines = [f"<b>🗓️ {escape_html(title)}</b>"]
    if delivered_alerts_count > 0:
        lines.extend(
            [
                "",
                f"📦 {escape_html(premium_text(language_code, 'recap_delivered_alerts'))}: <b>{delivered_alerts_count}</b>",
                escape_html(premium_text(language_code, "recap_based_on_delivered")),
            ]
        )
    if not alerts and not followups:
        lines.extend(["", escape_html(empty_text or premium_text(language_code, "recap_empty"))])
        return "\n".join(lines)
    if alerts:
        lines.extend(["", f"<b>🔥 {escape_html(premium_text(language_code, 'digest_strongest'))}</b>"])
        lines.extend(f"• {escape_html(_alert_line(alert))}" for alert in alerts[:4])
    if followups:
        title_text = followups_title or premium_text(language_code, "digest_followups")
        lines.extend(["", f"<b>🔁 {escape_html(title_text)}</b>"])
        line_formatter = _recap_followup_line if followups_as_winners else _followup_line
        lines.extend(f"• {escape_html(line_formatter(item))}" for item in followups[:3])
    return "\n".join(lines)


def format_watchlists_message(
    *,
    active_theme_label: str,
    active_symbols: list[str],
    saved_theme_names: list[str],
    tracking_label: str,
    watchlist_only: bool,
    language_code: str,
) -> str:
    symbols_line = ", ".join(active_symbols[:12]) if active_symbols else ("пока пусто" if is_russian(language_code) else "empty for now")
    saved_line = ", ".join(saved_theme_names[:6]) if saved_theme_names else ("пока нет" if is_russian(language_code) else "none yet")
    language = normalize_language(language_code)
    is_ru = is_russian(language)
    lines = [
        f"<b>⭐ {escape_html(premium_text(language, 'watchlists_title'))}</b>",
        "",
        escape_html(premium_text(language, "watchlists_center_intro")),
        "",
        f"🧺 {'Сейчас в избранном' if is_ru else 'Favorites now'}: <b>{escape_html(symbols_line)}</b>",
        f"🎯 {'Что отслеживается' if is_ru else 'Tracking'}: <b>{escape_html(tracking_label)}</b>",
        "🎨 " + escape_html(premium_text(language, "watchlists_theme_active", theme=active_theme_label)),
        f"💾 {'Сохранённые наборы' if is_ru else 'Saved sets'}: <b>{escape_html(saved_line)}</b>",
        "",
        "✨ " + escape_html(premium_text(language, "watchlists_builtin_note")),
    ]
    return "\n".join(lines)


def build_control_center_metrics(
    deliveries: list[DeliveredSignalRecord],
    *,
    now: datetime,
    language_code: str = "en",
) -> ControlCenterMetrics:
    alerts_today = 0
    alerts_7d = 0
    alerts_30d = 0
    followups_30d = 0
    watchlist_hits_30d = 0
    strongest_score: int | None = None
    strongest_symbol: str | None = None
    symbol_counter: Counter[str] = Counter()
    now_ts = now.timestamp()

    for delivery in deliveries:
        age_days = max((now_ts - delivery.delivered_at.timestamp()) / 86400.0, 0.0)
        score = delivery.metadata.get("score")
        symbol = normalize_symbol(str(delivery.metadata.get("symbol") or ""))
        if symbol:
            symbol_counter[symbol] += 1
        if delivery.message_kind == "alert":
            if age_days < 1:
                alerts_today += 1
            if age_days < 7:
                alerts_7d += 1
            if age_days < 30:
                alerts_30d += 1
                if delivery.metadata.get("watchlist_hit"):
                    watchlist_hits_30d += 1
        elif delivery.message_kind.startswith("followup:") and age_days < 30:
            followups_30d += 1
        if isinstance(score, int) and (strongest_score is None or score > strongest_score):
            strongest_score = score
            strongest_symbol = symbol or strongest_symbol

    recent_summary = ""
    if alerts_today or alerts_7d or followups_30d:
        recent_summary = (
            f"{alerts_today} сегодня • {alerts_7d} за 7д • {followups_30d} follow-up"
            if is_russian(language_code)
            else f"{alerts_today} today • {alerts_7d} in 7d • {followups_30d} follow-ups"
        )

    return ControlCenterMetrics(
        alerts_today=alerts_today,
        alerts_7d=alerts_7d,
        alerts_30d=alerts_30d,
        followups_30d=followups_30d,
        watchlist_hits_30d=watchlist_hits_30d,
        strongest_score=strongest_score,
        strongest_symbol=strongest_symbol,
        top_symbols=symbol_counter.most_common(4),
        recent_summary=recent_summary,
    )


def format_control_center_message(
    *,
    metrics: ControlCenterMetrics,
    settings: UserSettingsRecord,
    access_state: EffectiveAccessState,
    language_code: str,
    strategy_label: str | None = None,
) -> str:
    language = normalize_language(language_code)
    is_ru = is_russian(language)
    theme_label = watchlist_theme_label(
        settings.active_watchlist_theme,
        language_code=language,
        custom_theme_name=settings.active_custom_theme_name,
    )
    quiet_window = format_quiet_hours_window(
        settings.quiet_hours_start_minute,
        settings.quiet_hours_end_minute,
        language_code=language,
    )
    tracking_label = tracking_scope_label(settings, language_code=language)
    access_label = "PRO+" if access_state.has_premium_access else ui_text(language, "status_free")
    profile_key = f"profile_{str(settings.signal_profile or 'custom').strip().lower()}"
    profile_label = (
        ui_text(language, profile_key)
        if profile_key in {"profile_conservative", "profile_balanced", "profile_aggressive", "profile_custom"}
        else str(settings.signal_profile or "custom").title()
    )
    lines = [f"<b>📊 {escape_html(premium_text(language, 'control_center_title'))}</b>"]
    if strategy_label:
        lines.extend(
            [
                "",
                (
                    f"Стратегия: <b>{escape_html(strategy_label)}</b>"
                    if is_ru
                    else f"Strategy: <b>{escape_html(strategy_label)}</b>"
                ),
            ]
        )
    lines.extend(
        [
            "",
            f"<b>{'📦 Пульс потока' if is_ru else '📦 Flow Pulse'}</b>",
            f"• {'Сегодня доставлено' if is_ru else 'Delivered today'}: <b>{metrics.alerts_today}</b>",
            f"• {'За 7 дней' if is_ru else 'In 7 days'}: <b>{metrics.alerts_7d}</b>",
            f"• {'За 30 дней' if is_ru else 'In 30 days'}: <b>{metrics.alerts_30d}</b>",
            f"• {'Follow-up' if is_ru else 'Follow-ups'}: <b>{metrics.followups_30d}</b>",
            f"• {'Попадания в избранные' if is_ru else 'Watchlist hits'}: <b>{metrics.watchlist_hits_30d}</b>",
            "",
            f"<b>{'📬 Уведомления' if is_ru else '📬 Delivery'}</b>",
            f"• {'Режим' if is_ru else 'Mode'}: <b>{escape_html(delivery_mode_label(settings.delivery_mode, language_code=language))}</b>",
            f"• {'Ночь' if is_ru else 'Night'}: <b>{escape_html(quiet_window)}</b>",
            f"• {'Доступ' if is_ru else 'Access'}: <b>{escape_html(access_label)}</b>",
            "",
            f"<b>{'🧩 Текущая настройка' if is_ru else '🧩 Current Setup'}</b>",
            f"• {'Профиль' if is_ru else 'Profile'}: <b>{escape_html(profile_label)}</b>",
            f"• {'Охват' if is_ru else 'Tracking'}: <b>{escape_html(tracking_label)}</b>",
            f"• {'Набор' if is_ru else 'Active set'}: <b>{escape_html(theme_label)}</b>",
        ]
    )
    if metrics.strongest_score is not None and metrics.strongest_symbol:
        lines.extend(
            [
                "",
                f"<b>{'🏆 Лучший доставленный сигнал' if is_ru else '🏆 Strongest Delivered Signal'}</b>",
                f"• <b>{escape_html(metrics.strongest_symbol)} {metrics.strongest_score}/100</b>",
            ]
        )
    if metrics.top_symbols:
        top_symbols = ", ".join(f"{symbol} x{count}" for symbol, count in metrics.top_symbols)
        lines.append(
            f"• {'Активные тикеры' if is_ru else 'Most active tickers'}: <b>{escape_html(top_symbols)}</b>"
        )
    if metrics.recent_summary:
        lines.extend(
            [
                "",
                f"<b>{'📍 Недавняя активность' if is_ru else '📍 Recent Activity'}</b>",
                escape_html(metrics.recent_summary),
            ]
        )
    elif not metrics.top_symbols:
        lines.extend(["", escape_html(premium_text(language, "control_center_none"))])
    return "\n".join(lines)


def format_recap_message(
    *,
    title: str,
    recent_alerts: list[AlertRecord],
    followups: list[FollowUpResultRecord],
    language_code: str,
    delivered_alerts_count: int = 0,
    followups_title: str | None = None,
    recent_alerts_title: str | None = None,
    followups_as_winners: bool = False,
    empty_text: str | None = None,
    no_winners_text: str | None = None,
    strategy_label: str | None = None,
) -> str:
    is_ru = is_russian(language_code)
    lines = [f"<b>🗓️ {escape_html(title)}</b>"]
    if strategy_label:
        lines.extend(
            [
                "",
                (
                    f"Стратегия: <b>{escape_html(strategy_label)}</b>"
                    if is_ru
                    else f"Strategy: <b>{escape_html(strategy_label)}</b>"
                ),
            ]
        )
    lines.extend(
        [
            "",
            f"📦 {escape_html(premium_text(language_code, 'recap_delivered_alerts'))}: <b>{delivered_alerts_count}</b>",
            escape_html(premium_text(language_code, "recap_based_on_delivered")),
        ]
    )
    if delivered_alerts_count <= 0 and not followups and not recent_alerts:
        lines.extend(["", escape_html(empty_text or premium_text(language_code, "recap_no_deliveries"))])
        return "\n".join(lines)
    if followups:
        title_text = followups_title or premium_text(language_code, "digest_followups")
        lines.extend(["", f"<b>🔁 {escape_html(title_text)}</b>"])
        line_formatter = _recap_followup_line if followups_as_winners else _followup_line
        lines.extend(f"• {escape_html(line_formatter(item))}" for item in followups[:3])
    elif delivered_alerts_count > 0 and no_winners_text:
        lines.extend(["", escape_html(no_winners_text)])
    if recent_alerts:
        title_text = recent_alerts_title or premium_text(language_code, "recap_recent_alerts")
        lines.extend(["", f"<b>📍 {escape_html(title_text)}</b>"])
        lines.extend(f"• {escape_html(_alert_line(alert))}" for alert in recent_alerts[:3])
    return "\n".join(lines)


def format_scoped_delivery_center_message(
    *,
    settings: UserSettingsRecord,
    access_state: EffectiveAccessState,
    language_code: str,
    timezone_obj,
    now: datetime,
    strategy_label: str | None = None,
    scope_note: str | None = None,
) -> str:
    quiet_window = format_quiet_hours_window(
        settings.quiet_hours_start_minute,
        settings.quiet_hours_end_minute,
        language_code=language_code,
    )
    is_ru = is_russian(language_code)
    lines = [
        f"<b>{'Уведомления' if is_ru else 'Notifications'}</b>",
        "",
        (
            "Управляй тем, что приходит тебе, и как часто это приходит."
            if is_ru
            else "Choose what reaches you and how often."
        ),
    ]
    if strategy_label:
        lines.extend(["", f"{'Стратегия' if is_ru else 'Strategy'}: <b>{escape_html(strategy_label)}</b>"])
    if scope_note:
        lines.extend(["", escape_html(scope_note)])
    lines.extend(
        [
            "",
            f"<b>{'Текущее состояние' if is_ru else 'Current State'}</b>",
            f"• {'Сигналы' if is_ru else 'Alerts'}: <b>{premium_text(language_code, 'delivery_state_on' if settings.direct_signal_delivery_enabled else 'delivery_state_off')}</b>",
            f"• {'Follow-up' if is_ru else 'Follow-Ups'}: <b>{premium_text(language_code, 'delivery_state_on' if settings.followup_delivery_enabled else 'delivery_state_off')}</b>",
        ]
    )
    if access_state.has_premium_access:
        lines.append(
            f"• Gold Desk: <b>{premium_text(language_code, 'delivery_state_on' if settings.gold_alerts_enabled else 'delivery_state_off')}</b>"
        )
    lines.extend(
        [
            f"• {'Режим доставки' if is_ru else 'Delivery Mode'}: <b>{escape_html(delivery_mode_label(settings.delivery_mode, language_code=language_code))}</b>",
            f"• {'Тихие часы' if is_ru else 'Quiet Hours'}: <b>{escape_html(quiet_window)}</b>",
        ]
    )
    if is_snoozed(settings, now=now):
        timestamp = settings.snooze_until.astimezone(timezone_obj).strftime("%d %b %H:%M")
        lines.extend(
            [
                "",
                (
                    f"Пауза включена до <b>{escape_html(timestamp)}</b>."
                    if is_ru
                    else f"Snooze is active until <b>{escape_html(timestamp)}</b>."
                ),
            ]
        )
    elif is_within_quiet_hours(settings, now=now, timezone_obj=timezone_obj):
        lines.extend(
            [
                "",
                (
                    f"Тихие часы сейчас активны: <b>{escape_html(quiet_window)}</b>."
                    if is_ru
                    else f"Quiet hours are currently active: <b>{escape_html(quiet_window)}</b>."
                ),
            ]
        )
    else:
        lines.extend(
            [
                "",
                (
                    "Уведомления сейчас идут в обычном режиме."
                    if is_ru
                    else "Notifications are live right now."
                ),
            ]
        )
    return "\n".join(lines)


def format_gold_center_message(
    *,
    gold_alerts_enabled: bool,
    language_code: str,
    market_note: str | None = None,
    strategies: list[dict[str, str | bool]] | None = None,
) -> str:
    is_ru = normalize_language(language_code) == "ru"
    master_state = premium_text(language_code, "delivery_state_on" if gold_alerts_enabled else "delivery_state_off")
    active_count = sum(1 for strategy in strategies or [] if bool(strategy.get("enabled")))
    lines = [
        "<b>Gold Desk</b>",
        "",
        (
            "Отдельный XAUUSD desk с собственными сценариями, фильтрами и доставкой."
            if is_ru
            else "Dedicated XAUUSD flow, setups, and delivery controls."
        ),
    ]
    if market_note:
        lines.extend(["", escape_html(market_note)])
    lines.extend(
        [
            "",
            f"<b>{'Текущее состояние' if is_ru else 'Current State'}</b>",
            f"• {'Основной поток' if is_ru else 'Master Flow'}: <b>{escape_html(master_state)}</b>",
            f"• {'Активные gold-модели' if is_ru else 'Active Gold Models'}: <b>{active_count}</b>",
            "",
            (
                "Ниже можно отдельно управлять breakout, pullback и liquidity-сценариями."
                if is_ru
                else "Use the controls below to manage breakout, pullback, and liquidity scenarios separately."
            ),
        ]
    )
    for strategy in strategies or []:
        label = str(strategy.get("label") or "")
        summary = str(strategy.get("summary") or "")
        enabled = bool(strategy.get("enabled"))
        state = "ВКЛ" if enabled and is_ru else "ВЫКЛ" if is_ru else "ON" if enabled else "OFF"
        lines.extend(["", f"<b>{escape_html(label)}</b> • <b>{state}</b>", escape_html(summary)])
    lines.extend(
        [
            "",
            escape_html(
                "Если золото тебе важно не всегда, держи включёнными только нужные модели и свой режим доставки."
                if is_ru
                else "If gold is only part of your workflow, keep only the models and delivery style you actually want."
            ),
        ]
    )
    return "\n".join(lines)


def format_watchlists_message(
    *,
    active_theme_label: str,
    active_symbols: list[str],
    saved_theme_names: list[str],
    tracking_label: str,
    watchlist_only: bool,
    language_code: str,
) -> str:
    is_ru = is_russian(language_code)
    symbols_line = ", ".join(active_symbols[:12]) if active_symbols else ("пока пусто" if is_ru else "empty for now")
    saved_line = ", ".join(saved_theme_names[:6]) if saved_theme_names else ("пока нет" if is_ru else "none yet")
    mode_line = "только watchlist" if watchlist_only and is_ru else "watchlist only" if watchlist_only else "весь рынок" if is_ru else "full universe"
    lines = [
        "<b>Watchlists</b>",
        "",
        (
            "Управляй символами, темами и сохранёнными рыночными наборами, которые для тебя важны."
            if is_ru
            else "Manage the symbols, themes, and saved market views you care about most."
        ),
        "",
        f"<b>{'Текущее состояние' if is_ru else 'Current Snapshot'}</b>",
        f"• {'Список' if is_ru else 'Watchlist'}: <b>{escape_html(symbols_line)}</b>",
        f"• {'Охват' if is_ru else 'Tracking'}: <b>{escape_html(tracking_label)}</b>",
        f"• {'Режим' if is_ru else 'Mode'}: <b>{escape_html(mode_line)}</b>",
        f"• {'Активная тема' if is_ru else 'Active Theme'}: <b>{escape_html(active_theme_label)}</b>",
        f"• {'Сохранённые темы' if is_ru else 'Saved Themes'}: <b>{escape_html(saved_line)}</b>",
        "",
        (
            "Темы работают как сохранённые рыночные линзы: сначала выбери набор, потом уже дотяни фильтрами и алертами."
            if is_ru
            else "Use themes as saved market lenses, then apply filters or alerts on top."
        ),
    ]
    return "\n".join(lines)


def format_control_center_message(
    *,
    metrics: ControlCenterMetrics,
    settings: UserSettingsRecord,
    access_state: EffectiveAccessState,
    language_code: str,
    strategy_label: str | None = None,
) -> str:
    language = normalize_language(language_code)
    is_ru = is_russian(language)
    theme_label = watchlist_theme_label(
        settings.active_watchlist_theme,
        language_code=language,
        custom_theme_name=settings.active_custom_theme_name,
    )
    quiet_window = format_quiet_hours_window(
        settings.quiet_hours_start_minute,
        settings.quiet_hours_end_minute,
        language_code=language,
    )
    tracking_label = tracking_scope_label(settings, language_code=language)
    access_label = "PRO+" if access_state.has_premium_access else ui_text(language, "status_free")
    profile_key = f"profile_{str(settings.signal_profile or 'custom').strip().lower()}"
    profile_label = (
        ui_text(language, profile_key)
        if profile_key in {"profile_conservative", "profile_balanced", "profile_aggressive", "profile_custom"}
        else str(settings.signal_profile or "custom").title()
    )
    lines = [f"<b>{'Результаты' if is_ru else 'Results'}</b>"]
    if strategy_label:
        lines.extend(["", f"{'Стратегия' if is_ru else 'Strategy'}: <b>{escape_html(strategy_label)}</b>"])
    lines.extend(
        [
            "",
            (
                "Следи за доставленными сетапами, follow-up и качеством текущего потока."
                if is_ru
                else "Track delivered setups, follow-ups, and the quality of your current flow."
            ),
            "",
            f"<b>{'Пульс потока' if is_ru else 'Flow Pulse'}</b>",
            f"• {'Сегодня' if is_ru else 'Today'}: <b>{metrics.alerts_today}</b>",
            f"• {'За 7 дней' if is_ru else 'Last 7 Days'}: <b>{metrics.alerts_7d}</b>",
            f"• {'За 30 дней' if is_ru else 'Last 30 Days'}: <b>{metrics.alerts_30d}</b>",
            f"• {'Follow-up' if is_ru else 'Follow-Ups'}: <b>{metrics.followups_30d}</b>",
            f"• {'Попадания в watchlist' if is_ru else 'Watchlist Hits'}: <b>{metrics.watchlist_hits_30d}</b>",
            "",
            f"<b>{'Доставка' if is_ru else 'Delivery'}</b>",
            f"• {'Режим' if is_ru else 'Mode'}: <b>{escape_html(delivery_mode_label(settings.delivery_mode, language_code=language))}</b>",
            f"• {'Тихие часы' if is_ru else 'Quiet Hours'}: <b>{escape_html(quiet_window)}</b>",
            f"• {'Доступ' if is_ru else 'Access'}: <b>{escape_html(access_label)}</b>",
            "",
            f"<b>{'Текущая настройка' if is_ru else 'Current Setup'}</b>",
            f"• {'Профиль' if is_ru else 'Profile'}: <b>{escape_html(profile_label)}</b>",
            f"• {'Охват' if is_ru else 'Tracking'}: <b>{escape_html(tracking_label)}</b>",
            f"• {'Тема' if is_ru else 'Active Theme'}: <b>{escape_html(theme_label)}</b>",
        ]
    )
    if metrics.strongest_score is not None and metrics.strongest_symbol:
        lines.extend(
            [
                "",
                f"<b>{'Сильнейший доставленный сетап' if is_ru else 'Strongest Delivered Setup'}</b>",
                f"• <b>{escape_html(metrics.strongest_symbol)} {metrics.strongest_score}/100</b>",
            ]
        )
    if metrics.top_symbols:
        top_symbols = ", ".join(f"{symbol} x{count}" for symbol, count in metrics.top_symbols)
        lines.append(f"• {'Активные тикеры' if is_ru else 'Most Active Tickers'}: <b>{escape_html(top_symbols)}</b>")
    if metrics.recent_summary:
        lines.extend(["", f"<b>{'Недавняя активность' if is_ru else 'Recent Activity'}</b>", escape_html(metrics.recent_summary)])
    elif not metrics.top_symbols:
        lines.extend(["", escape_html(premium_text(language, "control_center_none"))])
    return "\n".join(lines)
