from __future__ import annotations

from src.core.utils import normalize_symbol
from src.localization import normalize_language, ui_text
from src.market.symbols import (
    build_futures_app_link,
    build_futures_link,
    build_tradingview_futures_link,
    is_supported_futures_symbol,
)
from src.userbot.premium_text import premium_text


def build_alert_inline_keyboard(
    *,
    symbol: str,
    selected_timeframe: str,
    supported_timeframes: tuple[str, ...],
    futures_base_url: str,
    futures_app_base_url: str | None = None,
    language_code: str = "en",
    external_link_label: str | None = None,
    external_link_url: str | None = None,
    include_ai_analysis: bool = True,
    include_risk_management: bool = False,
    include_signal_reason: bool = False,
    include_compare: bool = False,
    include_copy_symbol: bool = True,
    include_binance_app_link: bool = False,
    include_tradingview_link: bool = False,
    include_home_button: bool = False,
) -> dict[str, object]:
    language = normalize_language(language_code)
    display_symbol = normalize_symbol(symbol)
    symbol_link_actions_enabled = bool(external_link_url) or is_supported_futures_symbol(display_symbol)
    effective_timeframes = list(supported_timeframes)
    if selected_timeframe not in effective_timeframes:
        effective_timeframes.insert(0, selected_timeframe)
    timeframe_row: list[dict[str, object]] = []
    for timeframe in effective_timeframes:
        label = f"[{timeframe}]" if timeframe == selected_timeframe else timeframe
        timeframe_row.append(
            {
                "text": label,
                "callback_data": f"alert:tf:{timeframe}:{display_symbol}",
            }
        )

    link_url = (external_link_url or build_futures_link(futures_base_url, display_symbol)) if symbol_link_actions_enabled else None
    link_label = external_link_label or ui_text(language, "open_binance")
    app_link_url = (
        build_futures_app_link(futures_app_base_url, display_symbol)
        if symbol_link_actions_enabled and include_binance_app_link and futures_app_base_url and not external_link_url
        else None
    )
    tradingview_link_url = (
        build_tradingview_futures_link(display_symbol)
        if symbol_link_actions_enabled and include_tradingview_link and not external_link_url
        else None
    )
    app_link_label = ui_text(language, "open_binance_app")
    tradingview_link_label = ui_text(language, "open_tradingview")
    keyboard_rows: list[list[dict[str, object]]] = []
    keyboard_rows.append(timeframe_row)

    primary_row: list[dict[str, object]] = []
    if include_ai_analysis:
        primary_row.append(
            {
                "text": ui_text(language, "button_ai_analysis"),
                "callback_data": f"alert:ai:{display_symbol}",
            }
        )
    if include_risk_management:
        primary_row.append(
            {
                "text": ui_text(language, "button_risk_management"),
                "callback_data": f"alert:risk:{display_symbol}",
            }
        )
    if primary_row:
        keyboard_rows.append(primary_row)

    secondary_row: list[dict[str, object]] = []
    if include_signal_reason:
        secondary_row.append(
            {
                "text": ui_text(language, "button_signal_reason"),
                "callback_data": f"alert:reason:{display_symbol}",
            }
        )
    if include_compare:
        secondary_row.append(
            {
                "text": premium_text(language, "menu_compare"),
                "callback_data": f"alert:compare:{display_symbol}",
            }
        )
    if secondary_row:
        keyboard_rows.append(secondary_row)

    utility_row: list[dict[str, object]] = []
    if include_copy_symbol and symbol_link_actions_enabled:
        utility_row.append(
            {
                "text": ui_text(language, "copy_symbol", symbol=display_symbol),
                "copy_text": {"text": display_symbol},
            }
        )
    if utility_row:
        keyboard_rows.append(utility_row)
    if app_link_url and link_url:
        link_row: list[dict[str, object]] = []
        if tradingview_link_url:
            link_row.append({"text": tradingview_link_label, "url": tradingview_link_url})
        link_row.append({"text": app_link_label, "url": app_link_url})
        keyboard_rows.append(link_row)
        keyboard_rows.append([{"text": link_label, "url": link_url}])
    elif link_url:
        link_row = []
        if tradingview_link_url:
            link_row.append({"text": tradingview_link_label, "url": tradingview_link_url})
        link_row.append({"text": link_label, "url": link_url})
        keyboard_rows.append(link_row)

    if include_home_button:
        keyboard_rows.append(
            [
                {
                    "text": "🏠 Main Menu" if language == "en" else "🏠 Главное меню",
                    "callback_data": "main:today",
                }
            ]
        )

    return {"inline_keyboard": keyboard_rows}


def build_detail_card_keyboard(*, include_delete: bool, language_code: str = "en") -> dict[str, object] | None:
    return build_detail_card_keyboard_with_action(include_delete=include_delete, language_code=language_code)


def build_detail_card_keyboard_with_action(
    *,
    include_delete: bool,
    language_code: str = "en",
    action_label: str | None = None,
    action_url: str | None = None,
    back_label: str | None = None,
    back_callback_data: str | None = None,
) -> dict[str, object] | None:
    language = normalize_language(language_code)
    rows: list[list[dict[str, object]]] = []
    if action_label and action_url:
        rows.append([{"text": action_label, "url": action_url}])
    if back_label and back_callback_data:
        rows.append([{"text": back_label, "callback_data": back_callback_data}])
    if include_delete:
        rows.append([{"text": ui_text(language, "button_delete"), "callback_data": "detail:delete"}])
    if not rows:
        return None
    return {"inline_keyboard": rows}
