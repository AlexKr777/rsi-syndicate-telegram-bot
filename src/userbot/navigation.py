from __future__ import annotations

from src.localization import normalize_language


def main_callback(section: str = "hub") -> str:
    return f"main:{section}"


def strategy_callback(action: str, strategy_code: str) -> str:
    return f"strategy:{action}:{strategy_code}"


def compare_callback(view: str = "hub") -> str:
    return "compare:hub" if view == "hub" else f"compare:view:{view}"


def learn_callback(page: str = "hub") -> str:
    return "learn:hub" if page == "hub" else f"learn:{page}"


def lifecycle_callback(view: str = "hub") -> str:
    return "lifecycle:hub" if view == "hub" else f"lifecycle:{view}"


def results_callback(view: str = "hub") -> str:
    return "results:hub" if view == "hub" else f"results:{view}"


def strategy_results_callback(strategy_code: str) -> str:
    return f"strategy:results:{strategy_code}"


def strategy_signals_callback(strategy_code: str) -> str:
    return f"strategy:signals:{strategy_code}"


def strategy_filters_callback(strategy_code: str) -> str:
    return f"strategy:filters:{strategy_code}"


def strategy_alerts_callback(strategy_code: str) -> str:
    return f"strategy:alerts:{strategy_code}"


def strategy_favorites_callback(strategy_code: str) -> str:
    return f"strategy:favorites:{strategy_code}"


def strategy_quicksetup_callback(strategy_code: str) -> str:
    return f"strategy:quicksetup:{strategy_code}"


def strategy_guide_callback(strategy_code: str) -> str:
    return f"strategy:guide:{strategy_code}"


def strategy_settings_callback(strategy_code: str) -> str:
    return f"strategy:settings:{strategy_code}"


def strategy_compare_callback(strategy_code: str) -> str:
    return f"strategy:compare:{strategy_code}"


def strategy_toggle_callback(strategy_code: str) -> str:
    return f"strategy:toggle:{strategy_code}"


def external_label(label: str, *, language_code: str = "en") -> str:
    del language_code
    return f"{label} ↗"


def standard_nav_rows(
    *,
    back_callback_data: str | None,
    language_code: str = "en",
    main_label: str | None = None,
    main_callback_data: str | None = None,
    third_label: str | None = None,
    third_callback_data: str | None = None,
) -> list[list[dict[str, object]]]:
    language = normalize_language(language_code)
    resolved_main_label = main_label or ("🏠 Сегодня" if language == "ru" else "🏠 Home")
    resolved_third_label = third_label or ("❓ Помощь" if language == "ru" else "❓ Help")
    back_label = "⬅️ Назад" if language == "ru" else "⬅️ Back"
    row: list[dict[str, object]] = []
    if back_callback_data:
        row.append({"text": back_label, "callback_data": back_callback_data})
    if main_callback_data:
        row.append({"text": resolved_main_label, "callback_data": main_callback_data})
    if third_callback_data:
        row.append({"text": resolved_third_label, "callback_data": third_callback_data})
    return [row] if row else []


def role_label(language_code: str, *, is_admin: bool, has_paid: bool) -> str:
    language = normalize_language(language_code)
    if is_admin:
        return "Admin" if language == "en" else "Админ"
    if has_paid:
        return "Paid" if language == "en" else "Платный"
    return "User" if language == "en" else "Пользователь"
