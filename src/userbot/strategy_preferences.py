from __future__ import annotations

from typing import Any

from src.localization import normalize_language


def _option(
    value: str,
    *,
    en_label: str,
    ru_label: str,
    en_help: str,
    ru_help: str,
    timeframes: tuple[str, ...] = (),
    atr_min: float | None = None,
    atr_max: float | None = None,
    session_windows: tuple[tuple[int, int], ...] = (),
) -> dict[str, Any]:
    return {
        "value": value,
        "label": {"en": en_label, "ru": ru_label},
        "help": {"en": en_help, "ru": ru_help},
        "timeframes": timeframes,
        "atr_min": atr_min,
        "atr_max": atr_max,
        "session_windows": session_windows,
    }


def _control(
    key: str,
    *,
    default: str,
    en_title: str,
    ru_title: str,
    options: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    return {
        "key": key,
        "default": default,
        "title": {"en": en_title, "ru": ru_title},
        "options": options,
    }


_FOLLOWUP_CONTROL = _control(
    "followup_priority",
    default="move",
    en_title="Evening Follow-ups",
    ru_title="Вечерние Follow-up",
    options=(
        _option(
            "move",
            en_label="📈 Best %",
            ru_label="📈 По плюсу",
            en_help="Rank 18:00 and 21:00 follow-ups by the strongest positive move first.",
            ru_help="В 18:00 и 21:00 наверх поднимаются самые сильные follow-up по плюсу.",
        ),
        _option(
            "score",
            en_label="🧠 Best Score",
            ru_label="🧠 По score",
            en_help="Prioritize the cleanest, highest-score results even if the move is smaller.",
            ru_help="Выше идут самые качественные follow-up по score, даже если плюс чуть меньше.",
        ),
        _option(
            "watchlist",
            en_label="⭐ Favorites",
            ru_label="⭐ Избранные",
            en_help="Prioritize coins from your current favorites or active set for this strategy.",
            ru_help="Выше идут монеты из твоих избранных или активного набора этой стратегии.",
        ),
    ),
)


_STRATEGY_CONTROLS: dict[str, tuple[dict[str, Any], ...]] = {
    "breakout": (
        _control(
            "timeframe_focus",
            default="core",
            en_title="Breakout Pace",
            ru_title="Темп Пробоя",
            options=(
                _option(
                    "fast",
                    en_label="⚡ 1m/5m",
                    ru_label="⚡ 1м/5м",
                    en_help="Catch the earliest intraday breaks and react faster.",
                    ru_help="Ловит самые ранние intraday-пробои и реагирует быстрее.",
                    timeframes=("1m", "5m"),
                ),
                _option(
                    "core",
                    en_label="🎯 5m/15m",
                    ru_label="🎯 5м/15м",
                    en_help="Balanced middle ground for cleaner breakout structure.",
                    ru_help="Середина между скоростью и чистотой структуры пробоя.",
                    timeframes=("5m", "15m"),
                ),
                _option(
                    "swing",
                    en_label="🕯 15m/1h",
                    ru_label="🕯 15м/1ч",
                    en_help="Focus on higher-timeframe breaks and ignore the fast noise.",
                    ru_help="Фокус на более старших пробоях и меньше шума.",
                    timeframes=("15m", "1h"),
                ),
            ),
        ),
        _control(
            "market_mode",
            default="balanced",
            en_title="Impulse Filter",
            ru_title="Фильтр Импульса",
            options=(
                _option(
                    "coiled",
                    en_label="🧱 Coiled",
                    ru_label="🧱 Сжатие",
                    en_help="Prefer tighter markets before expansion and ignore messy spikes.",
                    ru_help="Предпочитает сжатие перед импульсом и режет слишком рваные всплески.",
                    atr_max=0.013,
                ),
                _option(
                    "balanced",
                    en_label="⚖️ Clean",
                    ru_label="⚖️ Чисто",
                    en_help="Keep normal breakout flow without extra ATR pressure.",
                    ru_help="Обычный чистый поток пробоев без дополнительного ATR-фильтра.",
                ),
                _option(
                    "expansion",
                    en_label="🚀 Expansion",
                    ru_label="🚀 Разгон",
                    en_help="Require a more explosive environment before accepting the breakout.",
                    ru_help="Требует более сильный разгон рынка перед пробоем.",
                    atr_min=0.008,
                ),
            ),
        ),
        _FOLLOWUP_CONTROL,
    ),
    "trend_pullback": (
        _control(
            "timeframe_focus",
            default="trend",
            en_title="Trend Window",
            ru_title="Окно Тренда",
            options=(
                _option(
                    "fast",
                    en_label="⚡ 5m/15m",
                    ru_label="⚡ 5м/15м",
                    en_help="Faster pullbacks around the session trend.",
                    ru_help="Более быстрые откаты внутри сессии.",
                    timeframes=("5m", "15m"),
                ),
                _option(
                    "trend",
                    en_label="📈 15m/1h",
                    ru_label="📈 15м/1ч",
                    en_help="Main trend continuation view for calmer entries.",
                    ru_help="Основной трендовый режим для более спокойных входов.",
                    timeframes=("15m", "1h"),
                ),
                _option(
                    "swing",
                    en_label="🕯 1h/4h",
                    ru_label="🕯 1ч/4ч",
                    en_help="Only the larger pullbacks that sit inside a broader trend.",
                    ru_help="Только более крупные откаты внутри широкого тренда.",
                    timeframes=("1h", "4h"),
                ),
            ),
        ),
        _control(
            "market_mode",
            default="balanced",
            en_title="Pullback Texture",
            ru_title="Характер Отката",
            options=(
                _option(
                    "orderly",
                    en_label="🧲 Orderly",
                    ru_label="🧲 Спокойно",
                    en_help="Prefer cleaner trend pullbacks and cut hot volatile taps.",
                    ru_help="Предпочитает аккуратные откаты по тренду и режет слишком горячие касания.",
                    atr_max=0.016,
                ),
                _option(
                    "balanced",
                    en_label="⚖️ Balanced",
                    ru_label="⚖️ Баланс",
                    en_help="Default pullback flow without extra ATR bias.",
                    ru_help="Базовый поток откатов без дополнительного уклона по ATR.",
                ),
                _option(
                    "impulse",
                    en_label="🔥 Hot",
                    ru_label="🔥 Горячо",
                    en_help="Allow only stronger, more active pullbacks.",
                    ru_help="Оставляет более активные и импульсные откаты.",
                    atr_min=0.009,
                ),
            ),
        ),
        _FOLLOWUP_CONTROL,
    ),
    "rsi_bollinger_mr": (
        _control(
            "timeframe_focus",
            default="balanced",
            en_title="Reversion Speed",
            ru_title="Скорость Возврата",
            options=(
                _option(
                    "fast",
                    en_label="⚡ 1m/5m",
                    ru_label="⚡ 1м/5м",
                    en_help="Catch the quickest snapbacks after the stretch.",
                    ru_help="Ловит самые быстрые откаты после выброса.",
                    timeframes=("1m", "5m"),
                ),
                _option(
                    "balanced",
                    en_label="🎯 5m/15m",
                    ru_label="🎯 5м/15м",
                    en_help="Balanced mean-reversion flow with fewer weak whips.",
                    ru_help="Сбалансированный mean reversion с меньшим числом слабых пил.",
                    timeframes=("5m", "15m"),
                ),
                _option(
                    "patient",
                    en_label="🕯 15m/1h",
                    ru_label="🕯 15м/1ч",
                    en_help="Wait for calmer higher-timeframe reversions.",
                    ru_help="Ждёт более спокойные возвраты на старших таймфреймах.",
                    timeframes=("15m", "1h"),
                ),
            ),
        ),
        _control(
            "market_mode",
            default="balanced",
            en_title="Stretch Filter",
            ru_title="Фильтр Выброса",
            options=(
                _option(
                    "tight",
                    en_label="🛡 Tight",
                    ru_label="🛡 Жёстко",
                    en_help="Take cleaner, less chaotic reversion environments.",
                    ru_help="Берёт более чистые и менее хаотичные условия для возврата.",
                    atr_max=0.015,
                ),
                _option(
                    "balanced",
                    en_label="⚖️ Balanced",
                    ru_label="⚖️ Баланс",
                    en_help="Keep the normal reversion universe.",
                    ru_help="Оставляет стандартный пул mean reversion-сигналов.",
                ),
                _option(
                    "wide",
                    en_label="🌪 Wide",
                    ru_label="🌪 Широко",
                    en_help="Allow only wider dislocations before the snapback.",
                    ru_help="Оставляет только более широкие выбросы перед откатом.",
                    atr_min=0.010,
                ),
            ),
        ),
        _FOLLOWUP_CONTROL,
    ),
    "rsi_bollinger_touch": (
        _control(
            "timeframe_focus",
            default="balanced",
            en_title="Touch Speed",
            ru_title="РЎРєРѕСЂРѕСЃС‚СЊ РљР°СЃР°РЅРёСЏ",
            options=(
                _option(
                    "fast",
                    en_label="Fast 1m/5m",
                    ru_label="Fast 1m/5m",
                    en_help="Catch earlier band touches with more speed and more noise.",
                    ru_help="Р›РѕРІРёС‚ Р±РѕР»РµРµ СЂР°РЅРЅРёРµ РєР°СЃР°РЅРёСЏ РїРѕР»РѕСЃС‹ Р±С‹СЃС‚СЂРµРµ, РЅРѕ СЃ Р±РѕР»СЊС€РёРј С€СѓРјРѕРј.",
                    timeframes=("1m", "5m"),
                ),
                _option(
                    "balanced",
                    en_label="Balanced 5m/15m",
                    ru_label="Balanced 5m/15m",
                    en_help="Balanced touch flow for cleaner directional extremes.",
                    ru_help="РЎР±Р°Р»Р°РЅСЃРёСЂРѕРІР°РЅРЅС‹Р№ РїРѕС‚РѕРє РєР°СЃР°РЅРёР№ РґР»СЏ Р±РѕР»РµРµ С‡РёСЃС‚С‹С… СЌРєСЃС‚СЂРµРјСѓРјРѕРІ.",
                    timeframes=("5m", "15m"),
                ),
                _option(
                    "patient",
                    en_label="Patient 15m/1h",
                    ru_label="Patient 15m/1h",
                    en_help="Wait for calmer higher-timeframe touches.",
                    ru_help="Р–РґРµС‚ Р±РѕР»РµРµ СЃРїРѕРєРѕР№РЅС‹Рµ РєР°СЃР°РЅРёСЏ РЅР° СЃС‚Р°СЂС€РёС… С‚Р°Р№РјС„СЂРµР№РјР°С….",
                    timeframes=("15m", "1h"),
                ),
            ),
        ),
        _control(
            "market_mode",
            default="balanced",
            en_title="Anti-Sideways Filter",
            ru_title="Anti-Sideways Filter",
            options=(
                _option(
                    "strict",
                    en_label="Strict",
                    ru_label="Strict",
                    en_help="Prefer clearer directional structure and reject more chop.",
                    ru_help="РџСЂРµРґРїРѕС‡РёС‚Р°РµС‚ Р±РѕР»РµРµ СЏРІРЅСѓСЋ РЅР°РїСЂР°РІР»РµРЅРЅСѓСЋ СЃС‚СЂСѓРєС‚СѓСЂСѓ Рё РѕС‚СЃРµРєР°РµС‚ С‡Р°С‰РµСЃС‚РЅС‹Р№ РїРёР».",
                    atr_min=0.007,
                ),
                _option(
                    "balanced",
                    en_label="Balanced",
                    ru_label="Balanced",
                    en_help="Keep the normal touch flow with the default anti-chop filter.",
                    ru_help="РћСЃС‚Р°РІР»СЏРµС‚ СЃС‚Р°РЅРґР°СЂС‚РЅС‹Р№ РїРѕС‚РѕРє СЃ Р±Р°Р·РѕРІС‹Рј anti-chop С„РёР»СЊС‚СЂРѕРј.",
                ),
                _option(
                    "wide",
                    en_label="Wide",
                    ru_label="Wide",
                    en_help="Allow a wider, hotter environment before the touch alert appears.",
                    ru_help="Р”Р°РµС‚ Р±РѕР»СЊС€Рµ РїСЂРѕСЃС‚СЂР°РЅСЃС‚РІР° РґР»СЏ РіРѕСЂСЏС‡РµР№ СЃСЂРµРґС‹ РїРµСЂРµРґ Р°Р»РµСЂС‚РѕРј.",
                    atr_min=0.010,
                ),
            ),
        ),
        _FOLLOWUP_CONTROL,
    ),
    "vwap": (
        _control(
            "timeframe_focus",
            default="desk",
            en_title="VWAP Rhythm",
            ru_title="Ритм VWAP",
            options=(
                _option(
                    "tape",
                    en_label="⚡ 1m/5m",
                    ru_label="⚡ 1м/5м",
                    en_help="Very fast intraday reclaims and rejections around VWAP.",
                    ru_help="Очень быстрые intraday-возвраты и отбой от VWAP.",
                    timeframes=("1m", "5m"),
                ),
                _option(
                    "desk",
                    en_label="🎯 5m/15m",
                    ru_label="🎯 5м/15м",
                    en_help="Balanced desk flow for normal intraday VWAP setups.",
                    ru_help="Основной desk-режим для нормальных intraday VWAP-сетапов.",
                    timeframes=("5m", "15m"),
                ),
                _option(
                    "session",
                    en_label="🕯 15m/1h",
                    ru_label="🕯 15м/1ч",
                    en_help="Focus on broader session bias instead of the tape.",
                    ru_help="Фокус на более широкой сессионной картине, а не на ленте.",
                    timeframes=("15m", "1h"),
                ),
            ),
        ),
        _control(
            "market_mode",
            default="balanced",
            en_title="VWAP Context",
            ru_title="Контекст VWAP",
            options=(
                _option(
                    "hold",
                    en_label="🧲 Holds",
                    ru_label="🧲 Удержание",
                    en_help="Prefer steadier holds and cleaner acceptance around VWAP.",
                    ru_help="Предпочитает более ровное удержание и чистое принятие вокруг VWAP.",
                    atr_max=0.015,
                ),
                _option(
                    "balanced",
                    en_label="⚖️ Balanced",
                    ru_label="⚖️ Баланс",
                    en_help="Keep the default intraday VWAP mix.",
                    ru_help="Оставляет базовый intraday-микс по VWAP.",
                ),
                _option(
                    "flip",
                    en_label="🔥 Flips",
                    ru_label="🔥 Переворот",
                    en_help="Require a faster tape and stronger session energy.",
                    ru_help="Требует более быстрый tape и более сильную энергию сессии.",
                    atr_min=0.009,
                ),
            ),
        ),
        _FOLLOWUP_CONTROL,
    ),
    "false_breakout": (
        _control(
            "timeframe_focus",
            default="clean",
            en_title="Trap Speed",
            ru_title="Скорость Ложного Пробоя",
            options=(
                _option(
                    "quick",
                    en_label="⚡ 1m/5m",
                    ru_label="⚡ 1м/5м",
                    en_help="Fast stop-sweeps that reverse quickly.",
                    ru_help="Быстрые выносы стопов с резким возвратом.",
                    timeframes=("1m", "5m"),
                ),
                _option(
                    "clean",
                    en_label="🎯 5m/15m",
                    ru_label="🎯 5м/15м",
                    en_help="Cleaner false breaks with a more readable reclaim.",
                    ru_help="Более чистые ложные пробои с понятным возвратом.",
                    timeframes=("5m", "15m"),
                ),
                _option(
                    "higher",
                    en_label="🕯 15m/1h",
                    ru_label="🕯 15м/1ч",
                    en_help="Only the larger liquidity sweeps on higher timeframes.",
                    ru_help="Только более крупные выносы ликвидности на старших ТФ.",
                    timeframes=("15m", "1h"),
                ),
            ),
        ),
        _control(
            "market_mode",
            default="balanced",
            en_title="Sweep Pressure",
            ru_title="Сила Выноса",
            options=(
                _option(
                    "precise",
                    en_label="🪤 Precise",
                    ru_label="🪤 Точно",
                    en_help="Prefer more precise traps and fewer noisy reversals.",
                    ru_help="Предпочитает более точные ловушки и меньше шумных разворотов.",
                    atr_max=0.016,
                ),
                _option(
                    "balanced",
                    en_label="⚖️ Balanced",
                    ru_label="⚖️ Баланс",
                    en_help="Standard false-break flow.",
                    ru_help="Стандартный поток ложных пробоев.",
                ),
                _option(
                    "aggressive",
                    en_label="🔥 Sweep",
                    ru_label="🔥 Вынос",
                    en_help="Allow only harder sweeps with stronger pressure.",
                    ru_help="Оставляет только более жёсткие выносы с сильным давлением.",
                    atr_min=0.009,
                ),
            ),
        ),
        _FOLLOWUP_CONTROL,
    ),
    "rsi": (
        _control(
            "timeframe_focus",
            default="balanced",
            en_title="RSI Window",
            ru_title="Окно RSI",
            options=(
                _option(
                    "fast",
                    en_label="⚡ 1m/5m",
                    ru_label="⚡ 1м/5м",
                    en_help="Catch faster stretched moves before they cool down.",
                    ru_help="Ловит быстрые растяжения до того, как они остынут.",
                    timeframes=("1m", "5m"),
                ),
                _option(
                    "balanced",
                    en_label="🎯 5m/15m",
                    ru_label="🎯 5м/15м",
                    en_help="Balanced view for readable RSI extremes.",
                    ru_help="Сбалансированный режим для читаемых RSI-экстремумов.",
                    timeframes=("5m", "15m"),
                ),
                _option(
                    "swing",
                    en_label="🕯 15m/1h",
                    ru_label="🕯 15м/1ч",
                    en_help="Focus on slower higher-timeframe RSI stretches.",
                    ru_help="Фокус на более медленные растяжения RSI на старших ТФ.",
                    timeframes=("15m", "1h"),
                ),
            ),
        ),
        _control(
            "market_mode",
            default="balanced",
            en_title="Stretch Quality",
            ru_title="Качество Экстремума",
            options=(
                _option(
                    "clean",
                    en_label="🛡 Clean",
                    ru_label="🛡 Чисто",
                    en_help="Cleaner, calmer RSI extremes with less random heat.",
                    ru_help="Более чистые и спокойные RSI-экстремумы без лишней случайной жары.",
                    atr_max=0.014,
                ),
                _option(
                    "balanced",
                    en_label="⚖️ Balanced",
                    ru_label="⚖️ Баланс",
                    en_help="Keep the standard RSI universe.",
                    ru_help="Оставляет стандартный RSI-поток.",
                ),
                _option(
                    "stretch",
                    en_label="🌪 Stretched",
                    ru_label="🌪 Перерастянуто",
                    en_help="Look only at more violent stretched conditions.",
                    ru_help="Смотрит только на более жёстко растянутые состояния рынка.",
                    atr_min=0.008,
                ),
            ),
        ),
        _FOLLOWUP_CONTROL,
    ),
    "rsi_divergence": (
        _control(
            "timeframe_focus",
            default="balanced",
            en_title="Divergence Window",
            ru_title="РћРєРЅРѕ Р”РёРІРµСЂРіРµРЅС†РёРё",
            options=(
                _option(
                    "fast",
                    en_label="Fast 5m",
                    ru_label="Fast 5m",
                    en_help="Catch earlier short-term divergences.",
                    ru_help="Р›РѕРІРёС‚ Р±РѕР»РµРµ СЂР°РЅРЅРёРµ РєРѕСЂРѕС‚РєРёРµ РґРёРІРµСЂРіРµРЅС†РёРё.",
                    timeframes=("5m",),
                ),
                _option(
                    "balanced",
                    en_label="Balanced 5m/15m",
                    ru_label="Balanced 5m/15m",
                    en_help="Balanced divergence flow across the core intraday timeframes.",
                    ru_help="РЎР±Р°Р»Р°РЅСЃРёСЂРѕРІР°РЅРЅС‹Р№ РїРѕС‚РѕРє РґРёРІРµСЂРіРµРЅС†РёР№ РЅР° РѕСЃРЅРѕРІРЅС‹С… intraday ТФ.",
                    timeframes=("5m", "15m"),
                ),
                _option(
                    "patient",
                    en_label="Patient 15m/1h",
                    ru_label="Patient 15m/1h",
                    en_help="Wait for broader, slower divergence structure.",
                    ru_help="Р–РґРµС‚ Р±РѕР»РµРµ С€РёСЂРѕРєСѓСЋ Рё РјРµРґР»РµРЅРЅСѓСЋ СЃС‚СЂСѓРєС‚СѓСЂСѓ РґРёРІРµСЂРіРµРЅС†РёРё.",
                    timeframes=("15m", "1h"),
                ),
            ),
        ),
        _control(
            "market_mode",
            default="balanced",
            en_title="Divergence Quality",
            ru_title="РљР°С‡РµСЃС‚РІРѕ Р”РёРІРµСЂРіРµРЅС†РёРё",
            options=(
                _option(
                    "clean",
                    en_label="Clean",
                    ru_label="Clean",
                    en_help="Prefer clearer two-swing structures and calmer reversals.",
                    ru_help="РџСЂРµРґРїРѕС‡РёС‚Р°РµС‚ Р±РѕР»РµРµ С‡РёСЃС‚СѓСЋ СЃС‚СЂСѓРєС‚СѓСЂСѓ РёР· РґРІСѓС… СЃРІРёРЅРіРѕРІ.",
                    atr_max=0.018,
                ),
                _option(
                    "balanced",
                    en_label="Balanced",
                    ru_label="Balanced",
                    en_help="Keep the default divergence universe.",
                    ru_help="РћСЃС‚Р°РІР»СЏРµС‚ СЃС‚Р°РЅРґР°СЂС‚РЅС‹Р№ РїРѕС‚РѕРє РґРёРІРµСЂРіРµРЅС†РёР№.",
                ),
                _option(
                    "aggressive",
                    en_label="Aggressive",
                    ru_label="Aggressive",
                    en_help="Allow faster and more volatile divergence setups.",
                    ru_help="Р”РѕРїСѓСЃРєР°РµС‚ Р±РѕР»РµРµ Р±С‹СЃС‚СЂС‹Рµ Рё РІРѕР»Р°С‚РёР»СЊРЅС‹Рµ РґРёРІРµСЂРіРµРЅС†РёРё.",
                    atr_min=0.008,
                ),
            ),
        ),
        _FOLLOWUP_CONTROL,
    ),
    "bollinger": (
        _control(
            "timeframe_focus",
            default="balanced",
            en_title="Band Speed",
            ru_title="Скорость Возврата В Канал",
            options=(
                _option(
                    "fast",
                    en_label="⚡ 1m/5m",
                    ru_label="⚡ 1м/5м",
                    en_help="Very quick Bollinger re-entries.",
                    ru_help="Очень быстрые возвраты в Bollinger-канал.",
                    timeframes=("1m", "5m"),
                ),
                _option(
                    "balanced",
                    en_label="🎯 5m/15m",
                    ru_label="🎯 5м/15м",
                    en_help="Balanced band re-entry flow.",
                    ru_help="Сбалансированный поток возвратов в канал.",
                    timeframes=("5m", "15m"),
                ),
                _option(
                    "patient",
                    en_label="🕯 15m/1h",
                    ru_label="🕯 15м/1ч",
                    en_help="Wait for calmer higher-timeframe re-entries.",
                    ru_help="Ждёт более спокойные возвраты на старших таймфреймах.",
                    timeframes=("15m", "1h"),
                ),
            ),
        ),
        _control(
            "market_mode",
            default="balanced",
            en_title="Band Pressure",
            ru_title="Давление На Полосы",
            options=(
                _option(
                    "inside",
                    en_label="🎈 Soft",
                    ru_label="🎈 Мягко",
                    en_help="Prefer softer band extensions and cleaner re-entry.",
                    ru_help="Предпочитает более мягкий выход за полосу и чистый возврат.",
                    atr_max=0.015,
                ),
                _option(
                    "balanced",
                    en_label="⚖️ Balanced",
                    ru_label="⚖️ Баланс",
                    en_help="Standard Bollinger re-entry flow.",
                    ru_help="Стандартный поток Bollinger re-entry.",
                ),
                _option(
                    "wide",
                    en_label="🌪 Wide",
                    ru_label="🌪 Широко",
                    en_help="Require wider dislocations outside the band.",
                    ru_help="Требует более широкий выброс за полосу.",
                    atr_min=0.010,
                ),
            ),
        ),
        _FOLLOWUP_CONTROL,
    ),
    "gold": (
        _control(
            "timeframe_focus",
            default="desk",
            en_title="Gold Tempo",
            ru_title="Темп Золота",
            options=(
                _option(
                    "fast",
                    en_label="⚡ 5m/15m",
                    ru_label="⚡ 5м/15м",
                    en_help="Faster intraday XAUUSD reactions.",
                    ru_help="Более быстрые intraday-реакции по XAUUSD.",
                    timeframes=("5m", "15m"),
                ),
                _option(
                    "desk",
                    en_label="🎯 15m/1h",
                    ru_label="🎯 15м/1ч",
                    en_help="Balanced desk mode for normal gold setups.",
                    ru_help="Основной desk-режим для нормальных gold-сетапов.",
                    timeframes=("15m", "1h"),
                ),
                _option(
                    "macro",
                    en_label="🕯 1h/4h",
                    ru_label="🕯 1ч/4ч",
                    en_help="Only broader gold moves and slower XAUUSD structure.",
                    ru_help="Только более широкие движения по золоту и медленная структура XAUUSD.",
                    timeframes=("1h", "4h"),
                ),
            ),
        ),
        _control(
            "session_focus",
            default="all",
            en_title="Gold Session",
            ru_title="Сессия По Золоту",
            options=(
                _option(
                    "all",
                    en_label="🌍 All Day",
                    ru_label="🌍 Весь День",
                    en_help="Take all gold alerts regardless of session.",
                    ru_help="Берёт все gold-alert независимо от сессии.",
                ),
                _option(
                    "london",
                    en_label="🇬🇧 London",
                    ru_label="🇬🇧 Лондон",
                    en_help="Keep only the London-session gold flow.",
                    ru_help="Оставляет только лондонский поток по золоту.",
                    session_windows=((6, 13),),
                ),
                _option(
                    "newyork",
                    en_label="🇺🇸 New York",
                    ru_label="🇺🇸 Нью-Йорк",
                    en_help="Keep only the New York-session gold flow.",
                    ru_help="Оставляет только нью-йоркский поток по золоту.",
                    session_windows=((13, 21),),
                ),
            ),
        ),
        _FOLLOWUP_CONTROL,
    ),
}

_STRATEGY_CONTROLS["gold_breakout"] = (
    _control(
        "timeframe_focus",
        default="desk",
        en_title="Gold Breakout Pace",
        ru_title="Темп Gold Breakout",
        options=(
            _option(
                "fast",
                en_label="⚡ 5m",
                ru_label="⚡ 5м",
                en_help="Catch the quickest XAUUSD breakout pushes.",
                ru_help="Ловит самые быстрые импульсные пробои по XAUUSD.",
                timeframes=("5m",),
            ),
            _option(
                "desk",
                en_label="🎯 15m",
                ru_label="🎯 15м",
                en_help="Balanced desk mode for cleaner range breaks.",
                ru_help="Сбалансированный режим для более чистых пробоев диапазона.",
                timeframes=("15m",),
            ),
            _option(
                "macro",
                en_label="🕯 1h",
                ru_label="🕯 1ч",
                en_help="Only broader XAUUSD breakout structure.",
                ru_help="Только более широкая breakout-структура по XAUUSD.",
                timeframes=("1h",),
            ),
        ),
    ),
    _control(
        "session_focus",
        default="all",
        en_title="Gold Session",
        ru_title="Сессия По Золоту",
        options=(
            _option(
                "all",
                en_label="🌍 All Day",
                ru_label="🌍 Весь День",
                en_help="Take breakouts from all gold sessions.",
                ru_help="Берёт breakout-сигналы по золоту из всех сессий.",
            ),
            _option(
                "london",
                en_label="🇬🇧 London",
                ru_label="🇬🇧 Лондон",
                en_help="Keep only the London-session breakout flow.",
                ru_help="Оставляет только лондонский breakout-поток.",
                session_windows=((6, 13),),
            ),
            _option(
                "newyork",
                en_label="🇺🇸 New York",
                ru_label="🇺🇸 Нью-Йорк",
                en_help="Keep only the New York-session breakout flow.",
                ru_help="Оставляет только нью-йоркский breakout-поток.",
                session_windows=((13, 21),),
            ),
        ),
    ),
    _FOLLOWUP_CONTROL,
)

_STRATEGY_CONTROLS["gold_pullback"] = (
    _control(
        "timeframe_focus",
        default="trend",
        en_title="Gold Pullback Window",
        ru_title="Окно Gold Pullback",
        options=(
            _option(
                "fast",
                en_label="⚡ 5m/15m",
                ru_label="⚡ 5м/15м",
                en_help="Faster pullbacks inside the current gold session.",
                ru_help="Более быстрые откаты внутри текущей gold-сессии.",
                timeframes=("5m", "15m"),
            ),
            _option(
                "trend",
                en_label="📈 15m/1h",
                ru_label="📈 15м/1ч",
                en_help="Main trend continuation mode for calmer gold entries.",
                ru_help="Основной трендовый режим для более спокойных входов по золоту.",
                timeframes=("15m", "1h"),
            ),
            _option(
                "macro",
                en_label="🕯 1h/4h",
                ru_label="🕯 1ч/4ч",
                en_help="Only broader pullbacks inside the larger gold trend.",
                ru_help="Только более широкие откаты внутри большого тренда по золоту.",
                timeframes=("1h", "4h"),
            ),
        ),
    ),
    _control(
        "session_focus",
        default="all",
        en_title="Gold Session",
        ru_title="Сессия По Золоту",
        options=(
            _option(
                "all",
                en_label="🌍 All Day",
                ru_label="🌍 Весь День",
                en_help="Take pullbacks from all gold sessions.",
                ru_help="Берёт pullback-сигналы по золоту из всех сессий.",
            ),
            _option(
                "london",
                en_label="🇬🇧 London",
                ru_label="🇬🇧 Лондон",
                en_help="Keep only the London-session pullback flow.",
                ru_help="Оставляет только лондонский pullback-поток.",
                session_windows=((6, 13),),
            ),
            _option(
                "newyork",
                en_label="🇺🇸 New York",
                ru_label="🇺🇸 Нью-Йорк",
                en_help="Keep only the New York-session pullback flow.",
                ru_help="Оставляет только нью-йоркский pullback-поток.",
                session_windows=((13, 21),),
            ),
        ),
    ),
    _FOLLOWUP_CONTROL,
)

_STRATEGY_CONTROLS["gold_liquidity"] = (
    _control(
        "timeframe_focus",
        default="balanced",
        en_title="Gold Liquidity Speed",
        ru_title="Скорость Gold Liquidity",
        options=(
            _option(
                "fast",
                en_label="⚡ 5m",
                ru_label="⚡ 5м",
                en_help="Catch the quickest liquidity sweeps on XAUUSD.",
                ru_help="Ловит самые быстрые liquidity sweep по XAUUSD.",
                timeframes=("5m",),
            ),
            _option(
                "balanced",
                en_label="🎯 15m",
                ru_label="🎯 15м",
                en_help="Balanced mode for cleaner false-break reclaim setups.",
                ru_help="Сбалансированный режим для более чистых ложных выносов и возвратов.",
                timeframes=("15m",),
            ),
            _option(
                "patient",
                en_label="🕯 1h",
                ru_label="🕯 1ч",
                en_help="Only broader gold liquidity traps.",
                ru_help="Только более широкие liquidity-ловушки по золоту.",
                timeframes=("1h",),
            ),
        ),
    ),
    _control(
        "session_focus",
        default="all",
        en_title="Gold Session",
        ru_title="Сессия По Золоту",
        options=(
            _option(
                "all",
                en_label="🌍 All Day",
                ru_label="🌍 Весь День",
                en_help="Take liquidity traps from all gold sessions.",
                ru_help="Берёт liquidity-сигналы по золоту из всех сессий.",
            ),
            _option(
                "london",
                en_label="🇬🇧 London",
                ru_label="🇬🇧 Лондон",
                en_help="Keep only the London-session liquidity flow.",
                ru_help="Оставляет только лондонский liquidity-поток.",
                session_windows=((6, 13),),
            ),
            _option(
                "newyork",
                en_label="🇺🇸 New York",
                ru_label="🇺🇸 Нью-Йорк",
                en_help="Keep only the New York-session liquidity flow.",
                ru_help="Оставляет только нью-йоркский liquidity-поток.",
                session_windows=((13, 21),),
            ),
        ),
    ),
    _FOLLOWUP_CONTROL,
)

_STRATEGY_CONTROLS["okak"] = _STRATEGY_CONTROLS["rsi"]
_STRATEGY_CONTROLS["ekek"] = _STRATEGY_CONTROLS["rsi"]


def strategy_preference_defaults(strategy_key: str | None) -> dict[str, str]:
    strategy = str(strategy_key or "rsi").strip().lower()
    controls = _STRATEGY_CONTROLS.get(strategy, _STRATEGY_CONTROLS["rsi"])
    return {str(control["key"]): str(control["default"]) for control in controls}


def normalize_strategy_preferences(strategy_key: str | None, raw: dict[str, Any] | None) -> dict[str, str]:
    controls = _STRATEGY_CONTROLS.get(str(strategy_key or "rsi").strip().lower(), _STRATEGY_CONTROLS["rsi"])
    defaults = strategy_preference_defaults(strategy_key)
    source = raw if isinstance(raw, dict) else {}
    normalized = dict(defaults)
    for control in controls:
        key = str(control["key"])
        allowed_values = {
            str(option["value"])
            for option in control["options"]
            if isinstance(option, dict) and option.get("value")
        }
        candidate = str(source.get(key) or "").strip().lower()
        if candidate in allowed_values:
            normalized[key] = candidate
    return normalized


def strategy_preference_controls(
    strategy_key: str | None,
    preferences: dict[str, Any] | None,
    *,
    language_code: str,
) -> list[dict[str, Any]]:
    language = normalize_language(language_code)
    strategy = str(strategy_key or "rsi").strip().lower()
    controls = _STRATEGY_CONTROLS.get(strategy, _STRATEGY_CONTROLS["rsi"])
    selected = normalize_strategy_preferences(strategy, preferences)
    hydrated: list[dict[str, Any]] = []
    for control in controls:
        options = list(control["options"])
        selected_value = selected[str(control["key"])]
        selected_option = next(
            (option for option in options if str(option["value"]) == selected_value),
            options[0],
        )
        hydrated.append(
            {
                "key": control["key"],
                "title": control["title"][language],
                "selected_value": selected_value,
                "selected_label": selected_option["label"][language],
                "selected_help": selected_option["help"][language],
                "options": [
                    {
                        "value": option["value"],
                        "label": option["label"][language],
                        "help": option["help"][language],
                    }
                    for option in options
                ],
            }
        )
    return hydrated


def strategy_allowed_timeframes(strategy_key: str | None, preferences: dict[str, Any] | None) -> tuple[str, ...]:
    for control in strategy_preference_controls(strategy_key, preferences, language_code="en"):
        if str(control["key"]) != "timeframe_focus":
            continue
        selected_value = str(control["selected_value"])
        for raw_control in _STRATEGY_CONTROLS.get(str(strategy_key or "rsi").strip().lower(), _STRATEGY_CONTROLS["rsi"]):
            if raw_control["key"] != "timeframe_focus":
                continue
            for option in raw_control["options"]:
                if str(option["value"]) == selected_value:
                    return tuple(str(item) for item in option.get("timeframes", ()) if str(item))
    return ()


def strategy_market_filter(strategy_key: str | None, preferences: dict[str, Any] | None) -> dict[str, Any]:
    strategy = str(strategy_key or "rsi").strip().lower()
    selected = normalize_strategy_preferences(strategy, preferences)
    controls = _STRATEGY_CONTROLS.get(strategy, _STRATEGY_CONTROLS["rsi"])
    for control in controls:
        key = str(control["key"])
        if key not in {"market_mode", "session_focus"}:
            continue
        selected_value = selected.get(key)
        for option in control["options"]:
            if str(option["value"]) == selected_value:
                return {
                    "key": key,
                    "value": selected_value,
                    "atr_min": option.get("atr_min"),
                    "atr_max": option.get("atr_max"),
                    "session_windows": tuple(option.get("session_windows", ())),
                }
    return {"key": None, "value": None, "atr_min": None, "atr_max": None, "session_windows": ()}


def strategy_followup_priority(strategy_key: str | None, preferences: dict[str, Any] | None) -> str:
    selected = normalize_strategy_preferences(strategy_key, preferences)
    return str(selected.get("followup_priority") or "move")
