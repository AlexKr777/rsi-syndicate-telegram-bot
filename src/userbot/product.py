from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Iterable

from src.core.utils import escape_html, format_price, normalize_symbol
from src.localization import normalize_language
from src.signals import signal_status_badge
from src.storage.models import SignalLifecycleRecord, StrategyStatsSnapshotRecord


@dataclass(frozen=True, slots=True)
class StrategyProfile:
    code: str
    name: str
    best_for: str
    regime: str
    timeframes: tuple[str, ...]
    assets: tuple[str, ...]
    signal_frequency: str
    noise_level: str
    style: str
    short_explanation: str
    recommended_when: str
    avoid_when: str
    tags: tuple[str, ...]


_STRATEGY_PROFILES: tuple[StrategyProfile, ...] = (
    StrategyProfile("breakout", "Breakout", "trending market continuation", "strong directional moves", ("5m", "15m", "1h"), ("BTC", "ETH", "liquid majors"), "Medium", "Medium", "Balanced", "Breakout focuses on continuation after a level gives way with acceptance.", "levels are breaking with momentum and volume", "the market is choppy and faking breaks", ("trend", "timeframe:5m", "timeframe:15m", "timeframe:1h", "assets:majors", "noise:medium")),
    StrategyProfile("trend_pullback", "Trend Pullback", "trend continuation after pullback", "clean trend structure", ("5m", "15m", "1h"), ("BTC", "ETH", "majors"), "Low", "Low", "Conservative", "Trend Pullback waits for a cleaner return into EMA support or resistance before continuation.", "trend structure is already visible and entries need patience", "the market has no structure or keeps chopping around averages", ("trend", "lownoise", "timeframe:5m", "timeframe:15m", "timeframe:1h", "assets:majors", "noise:low")),
    StrategyProfile("rsi_bollinger_mr", "RSI + Bollinger MR", "mean reversion after strong stretch", "range or exhaustion pockets", ("5m", "15m"), ("majors", "liquid alts"), "Medium", "Medium", "Balanced", "This is a stricter reversion setup after price stretches and starts returning into range.", "price looks overstretched and the move is losing force", "a one-sided trend is still accelerating", ("range", "timeframe:5m", "timeframe:15m", "assets:altcoins", "noise:medium")),
    StrategyProfile("rsi_bollinger_touch", "RSI + Bollinger Touch", "extreme touch with directional context", "non-sideways stretched moves", ("5m", "15m"), ("majors", "liquid alts"), "Medium", "Medium", "Balanced", "RSI + Bollinger Touch waits for RSI extremes to tag a 30-period Bollinger Band while filtering out flat sideways chop.", "price is stretched into the band and the market still has directional structure", "price is moving sideways and ping-ponging around the mean", ("reversal", "timeframe:5m", "timeframe:15m", "assets:altcoins", "noise:medium")),
    StrategyProfile("daily_rsi_80", "Daily RSI 80+", "higher-timeframe overheated shortlist", "1d overextension scan", ("1d",), ("majors", "altcoins"), "Low", "Low", "Selective", "Daily RSI 80+ scans for coins that already closed the daily candle in an extreme overbought state.", "you want a cleaner higher-timeframe list of overheated names", "you want a fast intraday stream or mixed two-sided ideas", ("reversal", "lownoise", "timeframe:1d", "assets:majors", "assets:altcoins", "noise:low")),
    StrategyProfile("vwap", "VWAP", "intraday bias and session reclaims", "intraday directional sessions", ("1m", "5m", "15m"), ("BTC", "ETH", "majors"), "Medium", "Medium", "Active", "VWAP is best when session context matters more than pure oscillator extremes.", "the intraday session has a clean reclaim or rejection around VWAP", "the market is too slow or too random intraday", ("trend", "timeframe:1m", "timeframe:5m", "timeframe:15m", "assets:majors", "noise:medium")),
    StrategyProfile("false_breakout", "False Breakout", "reversal after liquidity sweep", "reversal after failed break", ("5m", "15m", "1h"), ("BTC", "ETH", "volatile majors"), "Low", "Medium", "Balanced", "False Breakout looks for failed pushes beyond highs or lows that snap back into range.", "a liquidity sweep is obvious and price quickly reclaims back", "there is no real sweep and price keeps accepting outside the range", ("range", "reversal", "lownoise", "timeframe:5m", "timeframe:15m", "timeframe:1h", "assets:majors", "noise:medium")),
    StrategyProfile("rsi", "RSI", "early overbought / oversold filter", "mixed", ("1m", "5m", "15m", "1h"), ("majors", "altcoins", "memes"), "High", "High", "Active", "RSI is an early context filter that surfaces stretched names quickly.", "you want a fast first-pass filter for stretched markets", "you want low-noise confirmation by itself", ("trend", "range", "timeframe:1m", "timeframe:5m", "timeframe:15m", "timeframe:1h", "assets:majors", "assets:altcoins", "assets:memes", "noise:high")),
    StrategyProfile("rsi_divergence", "RSI Divergence", "momentum divergence at a new price extreme", "reversal after a failed momentum confirmation", ("5m", "15m", "1h"), ("BTC", "ETH", "majors"), "Low", "Medium", "Balanced", "RSI Divergence looks for price making a fresh high or low while RSI fails to confirm the extension.", "price prints a new extreme but momentum is already weakening", "there is no clear first swing or no real pullback between pushes", ("reversal", "timeframe:5m", "timeframe:15m", "timeframe:1h", "assets:majors", "noise:medium")),
    StrategyProfile("ekek", "EKEK", "sharp overbought impulse shortlist for short ideas", "fast squeeze-style bursts with overheating", ("15m",), ("liquid alts", "majors"), "Low", "Low", "Selective", "EKEK is the impulse version of OKAK: it keeps the strict overbought shortlist, then only keeps sharp bursts instead of gradual climbs.", "you want only the sharper acceleration moves before a possible short reaction", "price is climbing slowly without a clear burst", ("reversal", "impulse", "lownoise", "timeframe:15m", "assets:majors", "assets:altcoins", "noise:low")),
    StrategyProfile("bollinger", "Bollinger", "softer reversion to range", "calmer range behavior", ("5m", "15m"), ("majors", "liquid alts"), "Medium", "Low", "Conservative", "Bollinger is the calmer mean-reversion option when price is returning into the band channel.", "the market is stretched but not fully disorderly", "impulse continuation is still very strong", ("range", "lownoise", "timeframe:5m", "timeframe:15m", "assets:altcoins", "noise:low")),
    StrategyProfile("gold", "Gold / XAUUSD", "dedicated gold workflow", "gold-specific flow", ("5m", "15m", "1h"), ("gold",), "Low", "Low", "Balanced", "Gold runs as a dedicated XAUUSD mode with its own alerts and filters.", "gold is being traded separately from crypto", "you want a mixed crypto-only flow", ("gold", "lownoise", "timeframe:5m", "timeframe:15m", "timeframe:1h", "assets:gold", "noise:low")),
)

_STRATEGY_BY_CODE = {profile.code: profile for profile in _STRATEGY_PROFILES}
_STRATEGY_BY_CODE.update(
    {
        "okak": StrategyProfile(
            "okak",
            "OKAK",
            "selective overbought shortlist for short ideas",
            "overheated market pockets with real liquidity",
            ("15m",),
            ("liquid alts", "majors"),
            "Low",
            "Low",
            "Selective",
            "OKAK is a stricter overbought-only shortlist that requires at least 2 of 3 filters: preferred liquidity, RSI 76+, and score 90+.",
            "you want only the cleaner overheated names instead of the full RSI stream",
            "you want broad market coverage or oversold bounce alerts",
            ("reversal", "lownoise", "timeframe:15m", "assets:majors", "assets:altcoins", "noise:low"),
        ),
        "ekek": StrategyProfile(
            "ekek",
            "EKEK",
            "sharp overbought impulse shortlist for short ideas",
            "fast squeeze-style bursts with overheating",
            ("15m",),
            ("liquid alts", "majors"),
            "Low",
            "Low",
            "Selective",
            "EKEK is the impulse version of OKAK: it keeps the strict overbought shortlist, then only keeps sharp bursts instead of gradual climbs.",
            "you want only the sharper acceleration moves before a possible short reaction",
            "price is climbing slowly without a clear burst",
            ("reversal", "impulse", "lownoise", "timeframe:15m", "assets:majors", "assets:altcoins", "noise:low"),
        ),
        "gold_breakout": StrategyProfile(
            "gold_breakout",
            "Gold Breakout",
            "XAUUSD range extension after compression",
            "directional gold session",
            ("5m", "15m", "1h"),
            ("gold",),
            "Low",
            "Low",
            "Balanced",
            "Gold Breakout tracks acceptance beyond a key XAUUSD range.",
            "gold is coiling and ready to expand",
            "price is still rejecting the level",
            ("gold", "trend", "assets:gold", "noise:low"),
        ),
        "gold_pullback": StrategyProfile(
            "gold_pullback",
            "Gold Pullback",
            "trend continuation after EMA retrace",
            "clean gold trend",
            ("5m", "15m", "1h"),
            ("gold",),
            "Low",
            "Low",
            "Conservative",
            "Gold Pullback waits for XAUUSD to react from EMA structure and continue with trend.",
            "gold trend is established and the pullback is controlled",
            "market has no directional structure",
            ("gold", "trend", "assets:gold", "noise:low"),
        ),
        "gold_liquidity": StrategyProfile(
            "gold_liquidity",
            "Gold Liquidity",
            "reversal after sweep and reclaim",
            "failed gold breakout",
            ("5m", "15m", "1h"),
            ("gold",),
            "Low",
            "Medium",
            "Balanced",
            "Gold Liquidity looks for a sweep of extremes and reclaim back into range.",
            "gold just trapped one side and reclaimed fast",
            "the breakout is still being accepted",
            ("gold", "reversal", "assets:gold", "noise:medium"),
        ),
    }
)

_RUSSIAN_PROFILE_OVERRIDES: dict[str, dict[str, object]] = {
    "breakout": {
        "name": "Пробой уровня",
        "best_for": "продолжения тренда после пробоя уровня",
        "regime": "сильных направленных движений",
        "assets": ("BTC", "ETH", "ликвидные мейджоры"),
        "signal_frequency": "Средняя",
        "noise_level": "Средний",
        "style": "Сбалансированный",
        "short_explanation": "Пробой ищет продолжение движения после уверенного выхода за уровень и принятия цены выше или ниже него.",
        "recommended_when": "уровни пробиваются с импульсом и объёмом",
        "avoid_when": "рынок рваный и постоянно делает ложные выносы",
    },
    "trend_pullback": {
        "name": "Откат по тренду",
        "best_for": "продолжения тренда после отката",
        "regime": "чистой трендовой структуры",
        "assets": ("BTC", "ETH", "мейджоры"),
        "signal_frequency": "Низкая",
        "noise_level": "Низкий",
        "style": "Консервативный",
        "short_explanation": "Откат по тренду ждёт более чистого возврата к EMA-поддержке или сопротивлению перед продолжением движения.",
        "recommended_when": "тренд уже читается и входу нужна терпеливая точка",
        "avoid_when": "у рынка нет структуры или он пилит вокруг средних",
    },
    "rsi_bollinger_mr": {
        "best_for": "возврата к среднему после сильного растяжения",
        "regime": "диапазона или зон истощения",
        "assets": ("мейджоры", "ликвидные альты"),
        "signal_frequency": "Средняя",
        "noise_level": "Средний",
        "style": "Сбалансированный",
        "short_explanation": "Это более строгий mean reversion сетап после растяжения цены и начала возврата в диапазон.",
        "recommended_when": "цена уже сильно растянулась и импульс теряет силу",
        "avoid_when": "односторонний тренд всё ещё ускоряется",
    },
    "rsi_bollinger_touch": {
        "name": "RSI + Bollinger Touch",
        "best_for": "касания крайних полос после RSI-экстремума",
        "regime": "направленного движения без бокового шума",
        "assets": ("мейджоры", "ликвидные альты"),
        "signal_frequency": "Средняя",
        "noise_level": "Средний",
        "style": "Сбалансированный",
        "short_explanation": "Стратегия ждёт RSI ниже 30 или выше 70 и одновременное касание 30-периодной полосы Боллинджера, но отсекает flat / sideways участки.",
        "recommended_when": "цена уже растянута к краю полосы и рынок всё ещё имеет структуру, а не просто пилу",
        "avoid_when": "рынок ходит боком и постоянно возвращается к средней без импульса",
    },
    "vwap": {
        "best_for": "внутридневного смещения и возвратов к VWAP",
        "regime": "направленных внутридневных сессий",
        "assets": ("BTC", "ETH", "мейджоры"),
        "signal_frequency": "Средняя",
        "noise_level": "Средний",
        "style": "Активный",
        "short_explanation": "VWAP лучше всего работает там, где контекст сессии важнее, чем голые экстремумы осциллятора.",
        "recommended_when": "внутри дня есть чистый возврат или отбой вокруг VWAP",
        "avoid_when": "рынок слишком медленный или хаотичный внутри дня",
    },
    "false_breakout": {
        "name": "Ложный пробой",
        "best_for": "разворота после выноса ликвидности",
        "regime": "разворота после неудачного пробоя",
        "assets": ("BTC", "ETH", "волатильные мейджоры"),
        "signal_frequency": "Низкая",
        "noise_level": "Средний",
        "style": "Сбалансированный",
        "short_explanation": "Ложный пробой ищет неудачные выносы за экстремумы с быстрым возвратом обратно в диапазон.",
        "recommended_when": "вынос ликвидности очевиден и цена быстро возвращается назад",
        "avoid_when": "настоящего выноса нет и цена продолжает закрепляться вне диапазона",
    },
    "rsi": {
        "best_for": "раннего фильтра перекупленности и перепроданности",
        "regime": "смешанного рынка",
        "assets": ("мейджоры", "альткоины", "мемы"),
        "signal_frequency": "Высокая",
        "noise_level": "Высокий",
        "style": "Активный",
        "short_explanation": "RSI — это ранний контекстный фильтр, который быстро подсвечивает растянутые инструменты.",
        "recommended_when": "нужен быстрый первый фильтр по растянутому рынку",
        "avoid_when": "нужно малошумное подтверждение само по себе",
    },
    "rsi_divergence": {
        "name": "RSI Divergence",
        "best_for": "разворота после нового экстремума цены без подтверждения RSI",
        "regime": "разворотных участков после ослабления импульса",
        "assets": ("BTC", "ETH", "мейджоры"),
        "signal_frequency": "Низкая",
        "noise_level": "Средний",
        "style": "Сбалансированный",
        "short_explanation": "Стратегия ищет новый хай или лоу цены, когда RSI уже не подтверждает это движение, то есть появляется дивергенция.",
        "recommended_when": "есть понятный первый экстремум, затем откат, а второй push делает новый экстремум по цене без подтверждения импульса",
        "avoid_when": "структура рваная, нет нормального отката между двумя экстремумами или рынок просто шумит",
    },
    "daily_rsi_80": {
        "name": "Daily RSI 80+",
        "best_for": "старшего списка перегретых монет",
        "regime": "дневного перегрева и перекоса вверх",
        "assets": ("мейджоры", "альткоины"),
        "signal_frequency": "Низкая",
        "noise_level": "Низкий",
        "style": "Селективный",
        "short_explanation": "Daily RSI 80+ ищет монеты, где дневная свеча уже закрылась с RSI выше 80 и рынок выглядит перегретым на старшем таймфрейме.",
        "recommended_when": "нужен более чистый 1d shortlist перегретых монет вместо быстрого intraday-потока",
        "avoid_when": "нужен быстрый поток на младших ТФ или одновременно long- и short-идеи",
    },
    "okak": {
        "name": "OKAK",
        "best_for": "СЃРµР»РµРєС‚РёРІРЅРѕРіРѕ overbought-shortlist РїРѕ РїРµСЂРµРіСЂРµС‚С‹Рј РјРѕРЅРµС‚Р°Рј",
        "regime": "РїРµСЂРµРіСЂРµС‚С‹С… Р·РѕРЅ СЂС‹РЅРєР° СЃ Р»РёРєРІРёРґРЅРѕСЃС‚СЊСЋ",
        "assets": ("Р»РёРєРІРёРґРЅС‹Рµ Р°Р»СЊС‚С‹", "РјРµР№РґР¶РѕСЂС‹"),
        "signal_frequency": "РќРёР·РєР°СЏ",
        "noise_level": "РќРёР·РєРёР№",
        "style": "РЎРµР»РµРєС‚РёРІРЅС‹Р№",
        "short_explanation": "OKAK вЂ” СЃС‚СЂРѕРіРёР№ overbought-only shortlist: РЅСѓР¶РЅС‹ РјРёРЅРёРјСѓРј 2 РёР· 3 С„РёР»СЊС‚СЂРѕРІ вЂ” РЅСѓР¶РЅР°СЏ Р»РёРєРІРёРґРЅРѕСЃС‚СЊ, RSI 76+ Рё score 90+.",
        "recommended_when": "РЅСѓР¶РµРЅ СѓР·РєРёР№ shortlist РїРѕ РїРµСЂРµРіСЂРµС‚С‹Рј РјРѕРЅРµС‚Р°Рј, Р° РЅРµ РІРµСЃСЊ RSI-РїРѕС‚РѕРє",
        "avoid_when": "РЅСѓР¶РЅРѕ РјРЅРѕРіРѕ РѕР±С‰РёС… RSI-СЃРёРіРЅР°Р»РѕРІ РёР»Рё oversold-РёРґРµРё",
    },
    "bollinger": {
        "name": "Боллинджер",
        "best_for": "более мягкого возврата в диапазон",
        "regime": "спокойного диапазонного поведения",
        "assets": ("мейджоры", "ликвидные альты"),
        "signal_frequency": "Средняя",
        "noise_level": "Низкий",
        "style": "Консервативный",
        "short_explanation": "Bollinger — это более спокойный mean reversion вариант, когда цена возвращается внутрь канала полос.",
        "recommended_when": "рынок растянут, но ещё не полностью хаотичен",
        "avoid_when": "импульсное продолжение всё ещё очень сильное",
    },
    "gold": {
        "name": "Золото / XAUUSD",
        "best_for": "отдельного gold-потока",
        "regime": "специализированного режима для золота",
        "assets": ("золото",),
        "signal_frequency": "Низкая",
        "noise_level": "Низкий",
        "style": "Сбалансированный",
        "short_explanation": "Золото работает как отдельный режим XAUUSD со своими алертами и фильтрами.",
        "recommended_when": "золото торгуется отдельно от крипты",
        "avoid_when": "нужен только смешанный крипто-поток",
    },
}

_STATUS_LABELS_RU = {
    "fresh": "Свежий",
    "active": "Активный",
    "confirmed": "Подтверждён",
    "near_tp": "Почти TP",
    "hit_tp": "Достиг TP",
    "invalidated": "Сломан",
    "expired": "Истёк",
}

_DIRECTION_LABELS_RU = {
    "long": "Лонг",
    "short": "Шорт",
    "oversold": "Перепроданность",
    "overbought": "Перекупленность",
    "neutral": "Нейтрально",
}


def _localized_profile(profile: StrategyProfile, *, language_code: str) -> StrategyProfile:
    if normalize_language(language_code) != "ru":
        return profile
    overrides = _RUSSIAN_PROFILE_OVERRIDES.get(profile.code)
    if not overrides:
        return profile
    return replace(profile, **overrides)


def _localized_profiles(*, language_code: str) -> tuple[StrategyProfile, ...]:
    return tuple(_localized_profile(profile, language_code=language_code) for profile in _STRATEGY_PROFILES)


def _status_label(status: str | None, *, language_code: str) -> str:
    normalized = str(status or "fresh").strip().lower() or "fresh"
    if normalize_language(language_code) == "ru":
        return _STATUS_LABELS_RU.get(normalized, _STATUS_LABELS_RU["fresh"])
    _, label = signal_status_badge(normalized)
    return label


def _direction_label(direction: str | None, *, language_code: str) -> str:
    normalized = str(direction or "neutral").strip().lower() or "neutral"
    if normalize_language(language_code) == "ru":
        return _DIRECTION_LABELS_RU.get(normalized, _DIRECTION_LABELS_RU["neutral"])
    mapping = {
        "long": "Long",
        "short": "Short",
        "oversold": "Oversold",
        "overbought": "Overbought",
        "neutral": "Neutral",
    }
    return mapping.get(normalized, mapping["neutral"])


def _na(language_code: str) -> str:
    return "н/д" if normalize_language(language_code) == "ru" else "n/a"


def _period_label(period_label: str, *, language_code: str) -> str:
    normalized = str(period_label or "7d").strip().lower()
    if normalize_language(language_code) == "ru":
        mapping = {
            "7d": "Последние 7д",
            "30d": "Последние 30д",
            "all_time": "За всё время",
        }
    else:
        mapping = {
            "7d": "Last 7d",
            "30d": "Last 30d",
            "all_time": "All-time",
        }
    return mapping.get(normalized, period_label.replace("_", " "))


def _period_label(period_label: str, *, language_code: str) -> str:
    normalized = str(period_label or "7d").strip().lower()
    if normalize_language(language_code) == "ru":
        mapping = {
            "1d": "24ч",
            "7d": "Последние 7д",
            "30d": "Последние 30д",
            "all_time": "За всё время",
        }
    else:
        mapping = {
            "1d": "Last 24h",
            "7d": "Last 7d",
            "30d": "Last 30d",
            "all_time": "All-time",
        }
    return mapping.get(normalized, period_label.replace("_", " "))


def _snapshot_win_rate(snapshot: StrategyStatsSnapshotRecord) -> float:
    decided = int(snapshot.wins or 0) + int(snapshot.losses or 0)
    if decided <= 0:
        return 0.0
    return round(int(snapshot.wins or 0) / decided * 100.0, 1)


def _snapshot_sent_win_rate(snapshot: StrategyStatsSnapshotRecord) -> float:
    decided = int(snapshot.sent_wins or 0) + int(snapshot.sent_losses or 0)
    if decided <= 0:
        return 0.0
    return round(int(snapshot.sent_wins or 0) / decided * 100.0, 1)


def _snapshot_open_count(snapshot: StrategyStatsSnapshotRecord) -> int:
    resolved = (
        int(snapshot.wins or 0)
        + int(snapshot.losses or 0)
        + int(snapshot.ambiguous_count or 0)
        + int(snapshot.expired_neutral or 0)
    )
    return max(int(snapshot.total_signals or 0) - resolved, 0)


def _snapshot_sent_open_count(snapshot: StrategyStatsSnapshotRecord) -> int:
    resolved = (
        int(snapshot.sent_wins or 0)
        + int(snapshot.sent_losses or 0)
        + int(snapshot.sent_ambiguous_count or 0)
        + int(snapshot.sent_expired_neutral or 0)
    )
    return max(int(snapshot.delivered_count or 0) - resolved, 0)


class RoleGuardService:
    def is_admin(self, user) -> bool:
        return bool(getattr(user, "is_admin", False) or str(getattr(user, "access_level", "")).strip().lower() == "admin")

    def has_paid_access(self, user) -> bool:
        status = str(getattr(user, "access_status", "") or "").strip().lower()
        return self.is_admin(user) or status in {"trial", "paid", "admin"}

    def restricted_message(self, *, admin_only: bool) -> str:
        if admin_only:
            return (
                "<b>🔒 Restricted Section</b>\n\n"
                "This section is currently available only for admin access."
            )
        return (
            "<b>🔒 Premium Section</b>\n\n"
            "This feature is available with active access."
        )


    def restricted_message(self, *, admin_only: bool, language_code: str = "en") -> str:
        if normalize_language(language_code) == "ru":
            if admin_only:
                return (
                    "<b>🔒 Закрытый раздел</b>\n\n"
                    "Этот раздел сейчас доступен только для admin-доступа."
                )
            return (
                "<b>🔒 Premium-раздел</b>\n\n"
                "Эта функция доступна только при активном доступе."
            )
        if admin_only:
            return (
                "<b>🔒 Restricted Section</b>\n\n"
                "This section is currently available only for admin access."
            )
        return (
            "<b>🔒 Premium Section</b>\n\n"
            "This feature is available with active access."
        )


class CompareService:
    def strategy_profiles(self) -> tuple[StrategyProfile, ...]:
        return _STRATEGY_PROFILES

    def get_profile(self, strategy_code: str) -> StrategyProfile:
        return _STRATEGY_BY_CODE[strategy_code]

    def get_user_compare_cards(self, view: str) -> tuple[str, tuple[StrategyProfile, ...]]:
        normalized = str(view or "all").strip().lower() or "all"
        if normalized == "trend":
            return (
                "Best for Trend\n\n1. Breakout\n2. Trend Pullback\n3. VWAP\n\nUse these when the market is directional and continuation setups are cleaner than reversal entries.",
                tuple(profile for profile in _STRATEGY_PROFILES if "trend" in profile.tags and profile.code != "rsi"),
            )
        if normalized == "range":
            return (
                "Best for Range\n\n1. RSI + Bollinger MR\n2. Bollinger\n3. False Breakout\n\nThese are better when the market is stretching and rotating back instead of trending cleanly.",
                tuple(profile for profile in _STRATEGY_PROFILES if "range" in profile.tags),
            )
        if normalized == "gold":
            return (
                "Best for Gold\n\nUse the dedicated Gold / XAUUSD workflow when gold needs its own delivery, filters and context.",
                tuple(profile for profile in _STRATEGY_PROFILES if "gold" in profile.tags),
            )
        if normalized == "lownoise":
            return (
                "Low-Noise Picks\n\nTrend Pullback, Bollinger and Gold are the calmest picks when you want fewer but more readable setups.",
                tuple(profile for profile in _STRATEGY_PROFILES if "lownoise" in profile.tags),
            )
        if normalized == "timeframe":
            return (
                "Best by Timeframe\n\n1m: VWAP, RSI\n5m: Breakout, Trend Pullback, VWAP\n15m: Breakout, Trend Pullback, RSI + Bollinger MR, Gold\n1h: Breakout, Trend Pullback, False Breakout, Gold",
                _STRATEGY_PROFILES,
            )
        if normalized == "assets":
            return (
                "Best by Asset Type\n\nMajors: Breakout, Trend Pullback, VWAP\nAltcoins: RSI + Bollinger MR, Bollinger\nMemes: RSI\nGold: Gold / XAUUSD",
                _STRATEGY_PROFILES,
            )
        return (
            "All Strategies\n\nCompare each strategy by regime, timeframe, asset fit, noise and trading style.",
            _STRATEGY_PROFILES,
        )

    def strategy_profiles(self, *, language_code: str = "en") -> tuple[StrategyProfile, ...]:
        return _localized_profiles(language_code=language_code)

    def get_profile(self, strategy_code: str, *, language_code: str = "en") -> StrategyProfile:
        return _localized_profile(_STRATEGY_BY_CODE[strategy_code], language_code=language_code)

    def get_user_compare_cards(self, view: str, *, language_code: str = "en") -> tuple[str, tuple[StrategyProfile, ...]]:
        profiles = _localized_profiles(language_code=language_code)
        normalized = str(view or "all").strip().lower() or "all"
        is_ru = normalize_language(language_code) == "ru"
        if normalized == "trend":
            intro = (
                "Лучше для тренда\n\n1. Пробой уровня\n2. Откат по тренду\n3. VWAP\n\nИспользуй их, когда рынок направленный, а сценарии продолжения читаются чище, чем разворотные входы."
                if is_ru
                else "Best for Trend\n\n1. Breakout\n2. Trend Pullback\n3. VWAP\n\nUse these when the market is directional and continuation setups are cleaner than reversal entries."
            )
            return intro, tuple(profile for profile in profiles if "trend" in profile.tags and profile.code != "rsi")
        if normalized == "range":
            intro = (
                "Лучше для диапазона\n\n1. RSI + Bollinger MR\n2. Боллинджер\n3. Ложный пробой\n\nОни лучше подходят, когда рынок растягивается и возвращается назад, а не идёт чистым трендом."
                if is_ru
                else "Best for Range\n\n1. RSI + Bollinger MR\n2. Bollinger\n3. False Breakout\n\nThese are better when the market is stretching and rotating back instead of trending cleanly."
            )
            return intro, tuple(profile for profile in profiles if "range" in profile.tags)
        if normalized == "gold":
            intro = (
                "Лучше для золота\n\nИспользуй отдельный поток Gold / XAUUSD, когда золоту нужны свои уведомления, фильтры и контекст."
                if is_ru
                else "Best for Gold\n\nUse the dedicated Gold / XAUUSD workflow when gold needs its own delivery, filters and context."
            )
            return intro, tuple(profile for profile in profiles if "gold" in profile.tags)
        if normalized == "lownoise":
            intro = (
                "Меньше шума\n\nОткат по тренду, Боллинджер и Золото — самые спокойные варианты, когда нужно меньше, но чище сигналов."
                if is_ru
                else "Low-Noise Picks\n\nTrend Pullback, Bollinger and Gold are the calmest picks when you want fewer but more readable setups."
            )
            return intro, tuple(profile for profile in profiles if "lownoise" in profile.tags)
        if normalized == "timeframe":
            intro = (
                "Лучше по таймфрейму\n\n1m: VWAP, RSI\n5m: Пробой уровня, Откат по тренду, VWAP\n15m: Пробой уровня, Откат по тренду, RSI + Bollinger MR, Золото\n1h: Пробой уровня, Откат по тренду, Ложный пробой, Золото"
                if is_ru
                else "Best by Timeframe\n\n1m: VWAP, RSI\n5m: Breakout, Trend Pullback, VWAP\n15m: Breakout, Trend Pullback, RSI + Bollinger MR, Gold\n1h: Breakout, Trend Pullback, False Breakout, Gold"
            )
            return intro, profiles
        if normalized == "assets":
            intro = (
                "Лучше по типу актива\n\nМейджоры: Пробой уровня, Откат по тренду, VWAP\nАльткоины: RSI + Bollinger MR, Боллинджер\nМемы: RSI\nЗолото: Gold / XAUUSD"
                if is_ru
                else "Best by Asset Type\n\nMajors: Breakout, Trend Pullback, VWAP\nAltcoins: RSI + Bollinger MR, Bollinger\nMemes: RSI\nGold: Gold / XAUUSD"
            )
            return intro, profiles
        intro = (
            "Все стратегии\n\nСравни стратегии по режиму рынка, таймфрейму, типу актива, шуму и стилю торговли."
            if is_ru
            else "All Strategies\n\nCompare each strategy by regime, timeframe, asset fit, noise and trading style."
        )
        return intro, profiles


class LearnService:
    def learn_page(self, page: str, *, strategy_code: str | None = None) -> str:
        normalized = str(page or "hub").strip().lower()
        if normalized == "signals":
            return (
                "<b>📡 How Signals Work</b>\n\n"
                "A signal is a structured market setup, not a guaranteed outcome.\n\n"
                "It appears when a strategy sees a pattern that matches its rules, context and thresholds.\n\n"
                "Signals can be Fresh, Active, Confirmed, Near TP, Hit TP, Invalidated or Expired.\n\n"
                "Target shows the benchmark win objective. Invalidation shows where the original idea breaks. Some signals simply expire because the market never reached either side."
            )
        if normalized == "risk":
            return (
                "<b>🛡️ Risk Basics</b>\n\n"
                "Not every signal should use the same size.\n\n"
                "Invalidation matters because it defines where the setup is wrong. Without that, risk has no real boundary.\n\n"
                "Risk per trade matters more than any single alert. Several correlated coins are not true diversification, and alerts never mean guaranteed wins."
            )
        if normalized == "read_signal":
            return (
                "<b>👀 How to Read a Signal</b>\n\n"
                "Status shows where the setup is in its lifecycle.\n\n"
                "Symbol and timeframe define the market and chart speed. Direction shows the trade thesis. Entry, invalidation and target define the working framework.\n\n"
                "AI Analysis, Risk Management, Signal Reason and What Changed are there to inspect the setup from different angles without trading it blindly."
            )
        if normalized == "what_changed":
            return (
                "<b>🔄 What Changed Guide</b>\n\n"
                "What Changed compares the current market state with the original signal state.\n\n"
                "It helps you see whether the setup strengthened or weakened after waiting.\n\n"
                "This is especially useful when some time passed and you need context before acting."
            )
        if normalized == "ai_guide":
            return (
                "<b>🧠 AI Analysis Guide</b>\n\n"
                "<b>/ai</b> is the automatic mode. The system chooses the strongest current setup by itself.\n\n"
                "<b>AI Coin Analysis</b> in the menu is manual mode. You choose the ticker, for example <code>BTC</code>, <code>ETH 1h</code> or <code>XAUUSD</code>.\n\n"
                "<b>AI Analysis</b> on a signal card analyzes that exact alert. It does not search for a new setup and does not ask for a new ticker."
            )
        if normalized == "gold":
            return (
                "<b>🥇 Gold Guide</b>\n\n"
                "Gold / XAUUSD is a dedicated flow.\n\n"
                "Gold behaves differently from crypto, so it has separate alerts, filters and delivery controls.\n\n"
                "It is best treated as its own trading mode, not just another ticker inside the crypto stream."
            )
        if normalized == "guides" and strategy_code:
            profile = _STRATEGY_BY_CODE[strategy_code]
            return (
                f"<b>📘 {escape_html(profile.name)}</b>\n\n"
                f"Main idea:\n{escape_html(profile.short_explanation)}\n\n"
                f"Best market type:\n{escape_html(profile.regime)}\n\n"
                f"What to avoid:\n{escape_html(profile.avoid_when)}\n\n"
                f"Who it is for:\n{escape_html(profile.style)} traders who want {escape_html(profile.best_for)}."
            )
        return (
            "<b>📚 Learn</b>\n\n"
            "Use this section to understand how signals work, how to read cards, how AI analysis helps, and how each strategy behaves in different markets.\n\n"
            "This hub is designed to reduce confusion and make the bot easier to trust and use."
        )


    def learn_page(self, page: str, *, strategy_code: str | None = None, language_code: str = "en") -> str:
        normalized = str(page or "hub").strip().lower()
        is_ru = normalize_language(language_code) == "ru"
        if normalized == "signals":
            return (
                "<b>📡 Как работают сигналы</b>\n\n"
                "Сигнал — это структурированный рыночный сценарий, а не обещанный результат.\n\n"
                "Он появляется, когда стратегия видит паттерн, который подходит под её правила, контекст и пороги.\n\n"
                "Сигнал может быть в статусе Fresh, Active, Confirmed, Near TP, Hit TP, Invalidated или Expired.\n\n"
                "Target показывает целевой ориентир. Invalidation показывает, где исходная идея ломается. Часть сигналов просто истекает, потому что рынок так и не дошёл ни до цели, ни до инвалидации."
            ) if is_ru else (
                "<b>📡 How Signals Work</b>\n\n"
                "A signal is a structured market setup, not a guaranteed outcome.\n\n"
                "It appears when a strategy sees a pattern that matches its rules, context and thresholds.\n\n"
                "Signals can be Fresh, Active, Confirmed, Near TP, Hit TP, Invalidated or Expired.\n\n"
                "Target shows the benchmark win objective. Invalidation shows where the original idea breaks. Some signals simply expire because the market never reached either side."
            )
        if normalized == "risk":
            return (
                "<b>🛡️ Основы риска</b>\n\n"
                "Не каждый сигнал должен торговаться одним и тем же объёмом.\n\n"
                "Инвалидация важна, потому что именно она показывает, где сетап перестаёт быть актуальным. Без неё у риска нет чёткой границы.\n\n"
                "Риск на сделку важнее любого одного алерта. Несколько сильно коррелирующих монет — это не диверсификация, а сигналы никогда не означают гарантированную победу."
            ) if is_ru else (
                "<b>🛡️ Risk Basics</b>\n\n"
                "Not every signal should use the same size.\n\n"
                "Invalidation matters because it defines where the setup is wrong. Without that, risk has no real boundary.\n\n"
                "Risk per trade matters more than any single alert. Several correlated coins are not true diversification, and alerts never mean guaranteed wins."
            )
        if normalized == "read_signal":
            return (
                "<b>👀 Как читать сигнал</b>\n\n"
                "Status показывает, где сетап находится в своём жизненном цикле.\n\n"
                "Symbol и timeframe задают рынок и скорость графика. Direction показывает идею сделки. Entry, invalidation и target формируют рабочую рамку сценария.\n\n"
                "AI Analysis, Risk Management, Signal Reason и What Changed помогают посмотреть на сетап с разных сторон и не торговать карточку вслепую."
            ) if is_ru else (
                "<b>👀 How to Read a Signal</b>\n\n"
                "Status shows where the setup is in its lifecycle.\n\n"
                "Symbol and timeframe define the market and chart speed. Direction shows the trade thesis. Entry, invalidation and target define the working framework.\n\n"
                "AI Analysis, Risk Management, Signal Reason and What Changed are there to inspect the setup from different angles without trading it blindly."
            )
        if normalized == "what_changed":
            return (
                "<b>🔄 Гайд по What Changed</b>\n\n"
                "What Changed сравнивает текущее состояние рынка с исходным состоянием сигнала.\n\n"
                "Он помогает быстро понять, усилился сетап или ослаб после ожидания.\n\n"
                "Это особенно полезно, когда прошло время и нужен контекст перед решением."
            ) if is_ru else (
                "<b>🔄 What Changed Guide</b>\n\n"
                "What Changed compares the current market state with the original signal state.\n\n"
                "It helps you see whether the setup strengthened or weakened after waiting.\n\n"
                "This is especially useful when some time passed and you need context before acting."
            )
        if normalized == "ai_guide":
            return (
                "<b>🧠 Гайд по AI Analysis</b>\n\n"
                "<b>/ai</b> — это автоматический режим. Система сама выбирает самый сильный текущий сетап.\n\n"
                "<b>AI Coin Analysis</b> в меню — это ручной режим. Ты сам выбираешь тикер, например <code>BTC</code>, <code>ETH 1h</code> или <code>XAUUSD</code>.\n\n"
                "<b>AI Analysis</b> на карточке сигнала анализирует именно этот конкретный alert. Он не ищет новый сетап и не просит новый тикер."
            ) if is_ru else (
                "<b>🧠 AI Analysis Guide</b>\n\n"
                "<b>/ai</b> is the automatic mode. The system chooses the strongest current setup by itself.\n\n"
                "<b>AI Coin Analysis</b> in the menu is manual mode. You choose the ticker, for example <code>BTC</code>, <code>ETH 1h</code> or <code>XAUUSD</code>.\n\n"
                "<b>AI Analysis</b> on a signal card analyzes that exact alert. It does not search for a new setup and does not ask for a new ticker."
            )
        if normalized == "gold":
            return (
                "<b>🥇 Гайд по золоту</b>\n\n"
                "Gold / XAUUSD — это отдельный поток.\n\n"
                "Золото ведёт себя иначе, чем крипта, поэтому у него свои алерты, фильтры и настройки доставки.\n\n"
                "Лучше воспринимать его как отдельный торговый режим, а не просто ещё один тикер внутри крипто-ленты."
            ) if is_ru else (
                "<b>🥇 Gold Guide</b>\n\n"
                "Gold / XAUUSD is a dedicated flow.\n\n"
                "Gold behaves differently from crypto, so it has separate alerts, filters and delivery controls.\n\n"
                "It is best treated as its own trading mode, not just another ticker inside the crypto stream."
            )
        if normalized == "guides" and strategy_code:
            profile = _localized_profile(_STRATEGY_BY_CODE[strategy_code], language_code=language_code)
            return (
                f"<b>📘 {escape_html(profile.name)}</b>\n\n"
                f"Главная идея:\n{escape_html(profile.short_explanation)}\n\n"
                f"Лучший тип рынка:\n{escape_html(profile.regime)}\n\n"
                f"Когда избегать:\n{escape_html(profile.avoid_when)}\n\n"
                f"Кому подходит:\n{escape_html(profile.style)} стиль торговли, когда нужен подход для {escape_html(profile.best_for)}."
            ) if is_ru else (
                f"<b>📘 {escape_html(profile.name)}</b>\n\n"
                f"Main idea:\n{escape_html(profile.short_explanation)}\n\n"
                f"Best market type:\n{escape_html(profile.regime)}\n\n"
                f"What to avoid:\n{escape_html(profile.avoid_when)}\n\n"
                f"Who it is for:\n{escape_html(profile.style)} traders who want {escape_html(profile.best_for)}."
            )
        return (
            "<b>📚 Обучение</b>\n\n"
            "Этот раздел помогает понять, как работают сигналы, как читать карточки, как помогает AI-анализ и как разные стратегии ведут себя в разных рыночных условиях.\n\n"
            "Хаб сделан так, чтобы снижать путаницу и помогать пользоваться ботом увереннее."
        ) if is_ru else (
            "<b>📚 Learn</b>\n\n"
            "Use this section to understand how signals work, how to read cards, how AI analysis helps, and how each strategy behaves in different markets.\n\n"
            "This hub is designed to reduce confusion and make the bot easier to trust and use."
        )


class MessageRenderService:
    def render_main_hub(self, *, language_code: str = "en") -> str:
        language = normalize_language(language_code)
        if language == "ru":
            return (
                "<b>🏠 Главное меню</b>\n\n"
                "Добро пожаловать в ваш центр управления торговым потоком.\n\n"
                "Здесь можно открыть сигналы, стратегии, уведомления, результаты, AI-инструменты и настройки доступа.\n\n"
                "Выберите нужный раздел ниже."
            )
        return (
            "<b>🏠 Main Hub</b>\n\n"
            "Welcome to your trading control center.\n\n"
            "Use this menu to access signals, strategies, alerts, results, AI tools and account controls.\n\n"
            "Choose a section below."
        )

    def render_strategy_hub(self, profile: StrategyProfile, *, enabled: bool) -> str:
        toggle = "Enabled" if enabled else "Disabled"
        return (
            f"<b>📐 {escape_html(profile.name)}</b>\n\n"
            "This workspace contains everything related to this strategy.\n\n"
            "Here you can review fresh signals, fine-tune filters, configure alerts, manage favorites, open results and use AI tools for manual analysis.\n\n"
            f"{escape_html(profile.name)}:\n{escape_html(profile.short_explanation)}\n\n"
            f"Status: <b>{escape_html(toggle)}</b>"
        )

    def render_results_hub(self, *, strategy_label: str | None = None, is_admin: bool = False) -> str:
        header = "📊 Results"
        if strategy_label:
            header = f"📊 Results • {strategy_label}"
        lines = [
            f"<b>{escape_html(header)}</b>",
            "",
            "Review daily and weekly outcomes, monitor active signal flow and inspect lifecycle status across the system.",
            "",
            "Use this section to understand performance, freshness and current bot activity.",
        ]
        if is_admin:
            lines.extend(["", "👑 Admin metrics are available in this scope."])
        return "\n".join(lines)

    def render_compare_hub(self, *, is_admin: bool) -> str:
        text = (
            "<b>🆚 Compare Strategies</b>\n\n"
            "Use this section to understand which strategy fits the current market and your trading style.\n\n"
            "Compare strategies by market regime, asset type, noise level and timeframe."
        )
        if is_admin:
            text += "\n\n👑 Admin view includes live performance metrics."
        return text

    def render_compare_view(self, intro: str, profiles: Iterable[StrategyProfile]) -> str:
        lines = [f"<b>🆚 Compare Strategies</b>", "", escape_html(intro)]
        for profile in profiles:
            lines.extend(
                [
                    "",
                    f"<b>📊 {escape_html(profile.name)}</b>",
                    "",
                    f"Best for:\n{escape_html(profile.best_for)}.",
                    "",
                    f"Best market regime:\n{escape_html(profile.regime)}.",
                    "",
                    f"Best timeframes:\n{escape_html(', '.join(profile.timeframes))}.",
                    "",
                    f"Best assets:\n{escape_html(', '.join(profile.assets))}.",
                    "",
                    f"Signal frequency: <b>{escape_html(profile.signal_frequency)}</b>",
                    f"Noise level: <b>{escape_html(profile.noise_level)}</b>",
                    f"Typical style: <b>{escape_html(profile.style)}</b>",
                    "",
                    f"Recommended when:\n{escape_html(profile.recommended_when)}.",
                    "",
                    f"Avoid when:\n{escape_html(profile.avoid_when)}.",
                ]
            )
        return "\n".join(lines)

    def render_lifecycle_hub(self, *, strategy_label: str | None = None) -> str:
        title = "📡 Signal Lifecycle" if strategy_label is None else f"📡 Signal Lifecycle • {strategy_label}"
        return (
            f"<b>{escape_html(title)}</b>\n\n"
            "Track signals through their full lifecycle, from fresh setup to confirmation, target hit, invalidation or expiry.\n\n"
            "Use this section to understand what is still active, what has already confirmed, and what has closed."
        )

    def render_learn_hub(self) -> str:
        return LearnService().learn_page("hub")

    def render_admin_stats(self, snapshots: Iterable[StrategyStatsSnapshotRecord], *, period_label: str) -> str:
        lines = [f"<b>👑 Admin Stats • {escape_html(period_label)}</b>"]
        for snapshot in snapshots:
            win_rate = (
                round(snapshot.wins / max(snapshot.wins + snapshot.losses, 1) * 100.0, 1)
                if snapshot.wins or snapshot.losses
                else 0.0
            )
            lines.extend(
                [
                    "",
                    f"<b>{escape_html(snapshot.strategy_code.title())}</b>",
                    f"Total signals: <b>{snapshot.total_signals}</b>",
                    f"Wins: <b>{snapshot.wins}</b>",
                    f"Losses: <b>{snapshot.losses}</b>",
                    f"Expired neutral: <b>{snapshot.expired_neutral}</b>",
                    f"Win rate: <b>{win_rate:.1f}%</b>",
                    f"Avg RR: <b>{snapshot.avg_rr if snapshot.avg_rr is not None else 'n/a'}</b>",
                    f"Signals/day: <b>{snapshot.signals_per_day if snapshot.signals_per_day is not None else 'n/a'}</b>",
                    f"Best TF: <b>{escape_html(snapshot.best_tf or 'n/a')}</b>",
                    f"Best regime: <b>{escape_html(snapshot.best_regime or 'n/a')}</b>",
                    f"Best assets: <b>{escape_html(snapshot.best_assets or 'n/a')}</b>",
                    f"Drawdown profile: <b>{escape_html(snapshot.drawdown_profile or 'n/a')}</b>",
                ]
            )
        return "\n".join(lines)

    def render_admin_stats(
        self,
        snapshots: Iterable[StrategyStatsSnapshotRecord],
        *,
        period_label: str,
        compare_snapshots: Iterable[StrategyStatsSnapshotRecord] | None = None,
        extra_snapshots: Iterable[StrategyStatsSnapshotRecord] | None = None,
        extra_period_label: str | None = None,
        language_code: str = "en",
    ) -> str:
        is_ru = normalize_language(language_code) == "ru"
        primary_by_code = {snapshot.strategy_code: snapshot for snapshot in snapshots}
        compare_by_code = {
            snapshot.strategy_code: snapshot for snapshot in (compare_snapshots or ())
        }
        extra_by_code = {
            snapshot.strategy_code: snapshot for snapshot in (extra_snapshots or ())
        }
        compare_label = _period_label(period_label, language_code=language_code)
        baseline_label = _period_label("7d" if period_label == "1d" else "1d", language_code=language_code)
        if extra_period_label:
            title_suffix = f"{compare_label} vs {baseline_label} + {_period_label(extra_period_label, language_code=language_code)}"
        else:
            title_suffix = f"{compare_label} vs {baseline_label}"
        title = "Админ-дашборд" if is_ru else "Admin Dashboard"
        intro = (
            "Сверху быстрый срез, ниже реальные итоги по стратегиям: создано, отправлено, скрыто, тейки, стопы и спорные исходы."
            if is_ru
            else "Quick comparison first, then real per-strategy totals: created, sent, hidden, take-profits, stop-outs and ambiguous outcomes."
        )
        lines = [f"<b>{escape_html(title)} • {escape_html(title_suffix)}</b>", "", escape_html(intro)]

        def _period_lines(snapshot: StrategyStatsSnapshotRecord, label: str) -> list[str]:
            wins = int(snapshot.wins or 0)
            losses = int(snapshot.losses or 0)
            ambiguous = int(snapshot.ambiguous_count or 0)
            expired = int(snapshot.expired_neutral or 0)
            delivered = int(snapshot.delivered_count or 0)
            suppressed = int(snapshot.suppressed_count or 0)
            return [
                (
                    f"<b>{escape_html(label)}</b>: "
                    f"{'создано' if is_ru else 'created'} <b>{snapshot.total_signals}</b> | "
                    f"{'отправлено' if is_ru else 'sent'} <b>{delivered}</b> | "
                    f"{'скрыто' if is_ru else 'hidden'} <b>{suppressed}</b>"
                ),
                (
                    f"{'TP' if is_ru else 'TP'} <b>{wins}</b> | "
                    f"{'SL' if is_ru else 'SL'} <b>{losses}</b> | "
                    f"{'amb' if is_ru else 'amb'} <b>{ambiguous}</b> | "
                    f"{'expired' if is_ru else 'expired'} <b>{expired}</b> | "
                    f"{'WR' if is_ru else 'WR'} <b>{_snapshot_win_rate(snapshot):.1f}%</b>"
                ),
            ]

        for strategy_code, primary in primary_by_code.items():
            strategy_name = _localized_profile(
                _STRATEGY_BY_CODE.get(strategy_code, _STRATEGY_BY_CODE["rsi"]),
                language_code=language_code,
            ).name
            compare = compare_by_code.get(strategy_code)
            extra = extra_by_code.get(strategy_code)
            rr_label = f"{primary.avg_rr:.2f}" if primary.avg_rr is not None else _na(language_code)
            flow_label = (
                f"{primary.signals_per_day:.2f}" if primary.signals_per_day is not None else _na(language_code)
            )
            lines.extend(["", f"<b>{escape_html(strategy_name)}</b>"])
            lines.extend(_period_lines(primary, compare_label))
            if compare is not None:
                lines.extend(_period_lines(compare, baseline_label))
            if extra is not None and extra_period_label:
                lines.extend(_period_lines(extra, _period_label(extra_period_label, language_code=language_code)))
            if is_ru:
                lines.append(
                    f"Поток <b>{flow_label}/день</b> | Лучший ТФ <b>{escape_html(primary.best_tf or _na(language_code))}</b> | RR <b>{rr_label}</b>"
                )
                lines.append(
                    f"Лучший режим <b>{escape_html(primary.best_regime or _na(language_code))}</b> | Лучшие активы <b>{escape_html(primary.best_assets or _na(language_code))}</b>"
                )
            else:
                lines.append(
                    f"Flow <b>{flow_label}/day</b> | Best TF <b>{escape_html(primary.best_tf or _na(language_code))}</b> | RR <b>{rr_label}</b>"
                )
                lines.append(
                    f"Best regime <b>{escape_html(primary.best_regime or _na(language_code))}</b> | Best assets <b>{escape_html(primary.best_assets or _na(language_code))}</b>"
                )
        return "\n".join(lines)

    def render_admin_stats(
        self,
        snapshots: Iterable[StrategyStatsSnapshotRecord],
        *,
        period_label: str,
        compare_snapshots: Iterable[StrategyStatsSnapshotRecord] | None = None,
        extra_snapshots: Iterable[StrategyStatsSnapshotRecord] | None = None,
        extra_period_label: str | None = None,
        language_code: str = "en",
    ) -> str:
        is_ru = normalize_language(language_code) == "ru"
        primary_by_code = {snapshot.strategy_code: snapshot for snapshot in snapshots}
        compare_by_code = {
            snapshot.strategy_code: snapshot for snapshot in (compare_snapshots or ())
        }
        extra_by_code = {
            snapshot.strategy_code: snapshot for snapshot in (extra_snapshots or ())
        }
        compare_label = _period_label(period_label, language_code=language_code)
        baseline_label = _period_label("7d" if period_label == "1d" else "1d", language_code=language_code)
        title_suffix = f"{compare_label} vs {baseline_label}"
        if extra_period_label:
            title_suffix = f"{title_suffix} + {_period_label(extra_period_label, language_code=language_code)}"
        title = "Админ-дашборд" if is_ru else "Admin Dashboard"
        intro = (
            "Быстрый срез по стратегиям: что создано, что реально отправлено, что скрыто и как закрылись сигналы."
            if is_ru
            else "Quick strategy audit: what was created, what was really sent, what stayed hidden, and how signals resolved."
        )
        lines = [f"<b>{escape_html(title)} • {escape_html(title_suffix)}</b>", "", escape_html(intro)]

        def _period_lines(snapshot: StrategyStatsSnapshotRecord, label: str) -> list[str]:
            return [
                (
                    f"<b>{escape_html(label)}</b>: "
                    f"{'создано' if is_ru else 'created'} <b>{snapshot.total_signals}</b> | "
                    f"{'отправлено' if is_ru else 'sent'} <b>{snapshot.delivered_count}</b> | "
                    f"{'скрыто' if is_ru else 'hidden'} <b>{snapshot.suppressed_count}</b>"
                ),
                (
                    f"TP <b>{snapshot.wins}</b> | "
                    f"SL <b>{snapshot.losses}</b> | "
                    f"amb <b>{snapshot.ambiguous_count}</b> | "
                    f"{'expired' if is_ru else 'expired'} <b>{snapshot.expired_neutral}</b> | "
                    f"WR <b>{_snapshot_win_rate(snapshot):.1f}%</b>"
                ),
            ]

        for strategy_code, primary in primary_by_code.items():
            strategy_name = _localized_profile(
                _STRATEGY_BY_CODE.get(strategy_code, _STRATEGY_BY_CODE["rsi"]),
                language_code=language_code,
            ).name
            lines.extend(["", f"<b>{escape_html(strategy_name)}</b>"])
            lines.extend(_period_lines(primary, compare_label))
            compare = compare_by_code.get(strategy_code)
            if compare is not None:
                lines.extend(_period_lines(compare, baseline_label))
            extra = extra_by_code.get(strategy_code)
            if extra is not None and extra_period_label:
                lines.extend(_period_lines(extra, _period_label(extra_period_label, language_code=language_code)))
            rr_label = f"{primary.avg_rr:.2f}" if primary.avg_rr is not None else _na(language_code)
            flow_label = f"{primary.signals_per_day:.2f}" if primary.signals_per_day is not None else _na(language_code)
            if is_ru:
                lines.append(
                    f"Поток <b>{flow_label}/день</b> | Лучший ТФ <b>{escape_html(primary.best_tf or _na(language_code))}</b> | RR <b>{rr_label}</b>"
                )
                lines.append(
                    f"Лучший режим <b>{escape_html(primary.best_regime or _na(language_code))}</b> | Лучшие активы <b>{escape_html(primary.best_assets or _na(language_code))}</b>"
                )
            else:
                lines.append(
                    f"Flow <b>{flow_label}/day</b> | Best TF <b>{escape_html(primary.best_tf or _na(language_code))}</b> | RR <b>{rr_label}</b>"
                )
                lines.append(
                    f"Best regime <b>{escape_html(primary.best_regime or _na(language_code))}</b> | Best assets <b>{escape_html(primary.best_assets or _na(language_code))}</b>"
                )
        return "\n".join(lines)

    def render_admin_stats(
        self,
        snapshots: Iterable[StrategyStatsSnapshotRecord],
        *,
        period_label: str,
        compare_snapshots: Iterable[StrategyStatsSnapshotRecord] | None = None,
        extra_snapshots: Iterable[StrategyStatsSnapshotRecord] | None = None,
        extra_period_label: str | None = None,
        language_code: str = "en",
    ) -> str:
        is_ru = normalize_language(language_code) == "ru"
        primary_by_code = {snapshot.strategy_code: snapshot for snapshot in snapshots}
        compare_by_code = {
            snapshot.strategy_code: snapshot for snapshot in (compare_snapshots or ())
        }
        extra_by_code = {
            snapshot.strategy_code: snapshot for snapshot in (extra_snapshots or ())
        }
        compare_label = _period_label(period_label, language_code=language_code)
        baseline_label = _period_label("7d" if period_label == "1d" else "1d", language_code=language_code)
        title_suffix = f"{compare_label} vs {baseline_label}"
        if extra_period_label:
            title_suffix = f"{title_suffix} + {_period_label(extra_period_label, language_code=language_code)}"
        title = "Админ-дашборд" if is_ru else "Admin Dashboard"
        intro = (
            "Быстрый срез по стратегиям: что создано, что реально отправлено, что скрыто и как закрылись сигналы."
            if is_ru
            else "Quick strategy audit: what was created, what was really sent, what stayed hidden, and how signals resolved."
        )
        lines = [f"<b>{escape_html(title)} • {escape_html(title_suffix)}</b>", "", escape_html(intro)]

        def _period_lines(snapshot: StrategyStatsSnapshotRecord, label: str) -> list[str]:
            return [
                (
                    f"<b>{escape_html(label)}</b>: "
                    f"{'создано' if is_ru else 'created'} <b>{snapshot.total_signals}</b> | "
                    f"{'отправлено' if is_ru else 'sent'} <b>{snapshot.delivered_count}</b> | "
                    f"{'скрыто' if is_ru else 'hidden'} <b>{snapshot.suppressed_count}</b>"
                ),
                (
                    f"TP <b>{snapshot.wins}</b> | "
                    f"SL <b>{snapshot.losses}</b> | "
                    f"amb <b>{snapshot.ambiguous_count}</b> | "
                    f"{'expired' if is_ru else 'expired'} <b>{snapshot.expired_neutral}</b> | "
                    f"WR <b>{_snapshot_win_rate(snapshot):.1f}%</b>"
                ),
            ]

        for strategy_code, primary in primary_by_code.items():
            strategy_name = _localized_profile(
                _STRATEGY_BY_CODE.get(strategy_code, _STRATEGY_BY_CODE["rsi"]),
                language_code=language_code,
            ).name
            lines.extend(["", f"<b>{escape_html(strategy_name)}</b>"])
            lines.extend(_period_lines(primary, compare_label))
            compare = compare_by_code.get(strategy_code)
            if compare is not None:
                lines.extend(_period_lines(compare, baseline_label))
            extra = extra_by_code.get(strategy_code)
            if extra is not None and extra_period_label:
                lines.extend(_period_lines(extra, _period_label(extra_period_label, language_code=language_code)))
            rr_label = f"{primary.avg_rr:.2f}" if primary.avg_rr is not None else _na(language_code)
            flow_label = f"{primary.signals_per_day:.2f}" if primary.signals_per_day is not None else _na(language_code)
            if is_ru:
                lines.append(
                    f"Поток <b>{flow_label}/день</b> | Лучший ТФ <b>{escape_html(primary.best_tf or _na(language_code))}</b> | RR <b>{rr_label}</b>"
                )
                lines.append(
                    f"Лучший режим <b>{escape_html(primary.best_regime or _na(language_code))}</b> | Лучшие активы <b>{escape_html(primary.best_assets or _na(language_code))}</b>"
                )
            else:
                lines.append(
                    f"Flow <b>{flow_label}/day</b> | Best TF <b>{escape_html(primary.best_tf or _na(language_code))}</b> | RR <b>{rr_label}</b>"
                )
                lines.append(
                    f"Best regime <b>{escape_html(primary.best_regime or _na(language_code))}</b> | Best assets <b>{escape_html(primary.best_assets or _na(language_code))}</b>"
                )
        return "\n".join(lines)

    def render_lifecycle_list(
        self,
        *,
        title: str,
        records: Iterable[SignalLifecycleRecord],
        empty_title: str,
        empty_body: str,
    ) -> str:
        items = list(records)
        if not items:
            return f"<b>{escape_html(empty_title)}</b>\n\n{escape_html(empty_body)}"
        lines = [f"<b>{escape_html(title)}</b>"]
        for record in items:
            badge_emoji, badge_label = signal_status_badge(record.status)
            lines.extend(
                [
                    "",
                    f"<b>{badge_emoji} {escape_html(badge_label)} | {escape_html(record.strategy_code)} | {escape_html(normalize_symbol(record.symbol))} | {escape_html(record.timeframe)}</b>",
                    f"Direction: <b>{escape_html(record.direction.title())}</b>",
                    f"Entry: <b>{format_price(record.entry_price)}</b>",
                    f"Invalidation: <b>{format_price(record.invalidation_price) if record.invalidation_price is not None else 'n/a'}</b>",
                    f"Target: <b>{format_price(record.tp_price_primary) if record.tp_price_primary is not None else 'n/a'}</b>",
                    f"Created: <b>{escape_html(record.created_at.strftime('%Y-%m-%d %H:%M UTC'))}</b>",
                ]
            )
            if record.market_regime_tag:
                lines.append(f"Regime: <b>{escape_html(record.market_regime_tag)}</b>")
        return "\n".join(lines)

    def render_strategy_hub(self, profile: StrategyProfile, *, enabled: bool, language_code: str = "en") -> str:
        is_ru = normalize_language(language_code) == "ru"
        toggle = "Включена" if enabled and is_ru else "Выключена" if is_ru else "Enabled" if enabled else "Disabled"
        timeframes = ", ".join(profile.timeframes)
        if is_ru:
            return (
                f"<b>{escape_html(profile.name)}</b>\n\n"
                f"{escape_html(profile.short_explanation)}\n\n"
                "<b>Текущее состояние</b>\n"
                f"• Статус: <b>{escape_html(toggle)}</b>\n"
                f"• Режим рынка: <b>{escape_html(profile.regime)}</b>\n"
                f"• Лучший сценарий: <b>{escape_html(profile.best_for)}</b>\n"
                f"• Таймфреймы: <b>{escape_html(timeframes)}</b>\n\n"
                "Открой Signals для live-потока, Results для итогов или Quick Setup, чтобы быстро настроить стратегию под себя."
            )
        return (
            f"<b>{escape_html(profile.name)}</b>\n\n"
            f"{escape_html(profile.short_explanation)}\n\n"
            "<b>Current State</b>\n"
            f"• Status: <b>{escape_html(toggle)}</b>\n"
            f"• Regime Fit: <b>{escape_html(profile.regime)}</b>\n"
            f"• Best For: <b>{escape_html(profile.best_for)}</b>\n"
            f"• Timeframes: <b>{escape_html(timeframes)}</b>\n\n"
            "Open Signals for the live flow, Results for review, or Quick Setup to tune the strategy around your style."
        )

    def render_results_hub(self, *, strategy_label: str | None = None, is_admin: bool = False, language_code: str = "en") -> str:
        is_ru = normalize_language(language_code) == "ru"
        header = "Результаты" if is_ru else "Results"
        if strategy_label:
            header = f"{header} • {strategy_label}"
        lines = [
            f"<b>{escape_html(header)}</b>",
            "",
            (
                "Прозрачный обзор доставленных сетапов, follow-up и жизненного цикла сигнала."
                if is_ru
                else "A transparent view of delivered setups, follow-ups, and signal lifecycle outcomes."
            ),
            "",
            (
                "Начни с дневных и недельных итогов, затем спустись в lifecycle и статус потока."
                if is_ru
                else "Start with daily and weekly review, then move into lifecycle and flow status."
            ),
        ]
        if is_admin:
            lines.extend(["", "Admin Stats доступны в этом разделе." if is_ru else "Admin Stats are available in this scope."])
        return "\n".join(lines)

    def render_compare_hub(self, *, is_admin: bool, language_code: str = "en") -> str:
        is_ru = normalize_language(language_code) == "ru"
        text = (
            "<b>Сравнение стратегий</b>\n\n"
            "Смотри, какие движки лучше подходят под твой рынок, таймфрейм и уровень шума.\n\n"
            "Здесь удобно понять, что сейчас использовать: trend, mean reversion, gold-фокус или более селективный поток."
            if is_ru
            else "<b>Compare Strategies</b>\n\n"
            "See which engines fit your market, timeframe, and noise tolerance best.\n\n"
            "Use this section to decide whether trend, mean reversion, gold focus, or a more selective flow makes more sense right now."
        )
        if is_admin:
            text += "\n\nЗдесь также доступны admin-срезы по эффективности." if is_ru else "\n\nAdmin performance views are also available."
        return text

    def render_compare_view(self, intro: str, profiles: Iterable[StrategyProfile], *, language_code: str = "en") -> str:
        is_ru = normalize_language(language_code) == "ru"
        lines = [f"<b>{'🆚 Сравнение стратегий' if is_ru else '🆚 Compare Strategies'}</b>", "", escape_html(intro)]
        for profile in profiles:
            lines.extend(
                [
                    "",
                    f"<b>📊 {escape_html(profile.name)}</b>",
                    "",
                    f"{'Лучше для' if is_ru else 'Best for'}:\n{escape_html(profile.best_for)}.",
                    "",
                    f"{'Лучший режим рынка' if is_ru else 'Best market regime'}:\n{escape_html(profile.regime)}.",
                    "",
                    f"{'Лучшие таймфреймы' if is_ru else 'Best timeframes'}:\n{escape_html(', '.join(profile.timeframes))}.",
                    "",
                    f"{'Лучшие активы' if is_ru else 'Best assets'}:\n{escape_html(', '.join(profile.assets))}.",
                    "",
                    f"{'Частота сигналов' if is_ru else 'Signal frequency'}: <b>{escape_html(profile.signal_frequency)}</b>",
                    f"{'Уровень шума' if is_ru else 'Noise level'}: <b>{escape_html(profile.noise_level)}</b>",
                    f"{'Типичный стиль' if is_ru else 'Typical style'}: <b>{escape_html(profile.style)}</b>",
                    "",
                    f"{'Когда подходит' if is_ru else 'Recommended when'}:\n{escape_html(profile.recommended_when)}.",
                    "",
                    f"{'Когда избегать' if is_ru else 'Avoid when'}:\n{escape_html(profile.avoid_when)}.",
                ]
            )
        return "\n".join(lines)

    def render_lifecycle_hub(self, *, strategy_label: str | None = None, language_code: str = "en") -> str:
        is_ru = normalize_language(language_code) == "ru"
        title = "Жизненный цикл сигнала" if is_ru else "Signal Lifecycle"
        if strategy_label:
            title = f"{title} • {strategy_label}"
        return (
            f"<b>{escape_html(title)}</b>\n\n"
            + (
                "Следи за тем, как сигнал двигался после доставки: остаётся ли он активным, подтвердился ли тезис и чем всё закончилось."
                if is_ru
                else "Track what happened after delivery: whether the setup stayed active, confirmed, or moved into a finished outcome."
            )
            + "\n\n"
            + (
                "Open — ещё в работе. Confirmed — идея развивается. Invalidated — сценарий сломан. Closed — история завершена."
                if is_ru
                else "Open means still working. Confirmed means the thesis is progressing. Invalidated means the setup broke. Closed means the history is resolved."
            )
        )

    def render_learn_hub(self, *, language_code: str = "en") -> str:
        return LearnService().learn_page("hub", language_code=language_code)

    def render_admin_stats(self, snapshots: Iterable[StrategyStatsSnapshotRecord], *, period_label: str, language_code: str = "en") -> str:
        is_ru = normalize_language(language_code) == "ru"
        lines = [f"<b>{'👑 Статистика админа' if is_ru else '👑 Admin Stats'} • {escape_html(_period_label(period_label, language_code=language_code))}</b>"]
        for snapshot in snapshots:
            win_rate = (
                round(snapshot.wins / max(snapshot.wins + snapshot.losses, 1) * 100.0, 1)
                if snapshot.wins or snapshot.losses
                else 0.0
            )
            strategy_name = _localized_profile(_STRATEGY_BY_CODE.get(snapshot.strategy_code, _STRATEGY_BY_CODE["rsi"]), language_code=language_code).name
            lines.extend(
                [
                    "",
                    f"<b>{escape_html(strategy_name)}</b>",
                    f"{'Всего сигналов' if is_ru else 'Total signals'}: <b>{snapshot.total_signals}</b>",
                    f"{'Побед' if is_ru else 'Wins'}: <b>{snapshot.wins}</b>",
                    f"{'Поражений' if is_ru else 'Losses'}: <b>{snapshot.losses}</b>",
                    f"{'Истекло нейтрально' if is_ru else 'Expired neutral'}: <b>{snapshot.expired_neutral}</b>",
                    f"{'Винрейт' if is_ru else 'Win rate'}: <b>{win_rate:.1f}%</b>",
                    f"{'Средний RR' if is_ru else 'Avg RR'}: <b>{snapshot.avg_rr if snapshot.avg_rr is not None else _na(language_code)}</b>",
                    f"{'Сигналов в день' if is_ru else 'Signals/day'}: <b>{snapshot.signals_per_day if snapshot.signals_per_day is not None else _na(language_code)}</b>",
                    f"{'Лучший ТФ' if is_ru else 'Best TF'}: <b>{escape_html(snapshot.best_tf or _na(language_code))}</b>",
                    f"{'Лучший режим' if is_ru else 'Best regime'}: <b>{escape_html(snapshot.best_regime or _na(language_code))}</b>",
                    f"{'Лучшие активы' if is_ru else 'Best assets'}: <b>{escape_html(snapshot.best_assets or _na(language_code))}</b>",
                    f"{'Профиль просадки' if is_ru else 'Drawdown profile'}: <b>{escape_html(snapshot.drawdown_profile or _na(language_code))}</b>",
                ]
            )
        return "\n".join(lines)

    def render_lifecycle_list(
        self,
        *,
        title: str,
        records: Iterable[SignalLifecycleRecord],
        empty_title: str,
        empty_body: str,
        language_code: str = "en",
    ) -> str:
        items = list(records)
        if not items:
            return f"<b>{escape_html(empty_title)}</b>\n\n{escape_html(empty_body)}"
        is_ru = normalize_language(language_code) == "ru"
        lines = [f"<b>{escape_html(title)}</b>"]
        for record in items:
            badge_emoji, _ = signal_status_badge(record.status)
            badge_label = _status_label(record.status, language_code=language_code)
            strategy_name = _localized_profile(_STRATEGY_BY_CODE.get(record.strategy_code, _STRATEGY_BY_CODE['rsi']), language_code=language_code).name
            lines.extend(
                [
                    "",
                    f"<b>{badge_emoji} {escape_html(badge_label)} | {escape_html(strategy_name)} | {escape_html(normalize_symbol(record.symbol))} | {escape_html(record.timeframe)}</b>",
                    f"{'Направление' if is_ru else 'Direction'}: <b>{escape_html(_direction_label(record.direction, language_code=language_code))}</b>",
                    f"{'Вход' if is_ru else 'Entry'}: <b>{format_price(record.entry_price)}</b>",
                    f"{'Инвалидация' if is_ru else 'Invalidation'}: <b>{format_price(record.invalidation_price) if record.invalidation_price is not None else _na(language_code)}</b>",
                    f"{'Цель' if is_ru else 'Target'}: <b>{format_price(record.tp_price_primary) if record.tp_price_primary is not None else _na(language_code)}</b>",
                    f"{'Создан' if is_ru else 'Created'}: <b>{escape_html(record.created_at.strftime('%Y-%m-%d %H:%M UTC'))}</b>",
                ]
            )
            if record.market_regime_tag:
                lines.append(f"{'Режим' if is_ru else 'Regime'}: <b>{escape_html(record.market_regime_tag)}</b>")
        return "\n".join(lines)
def _message_render_admin_stats_override(
    self,
    snapshots: Iterable[StrategyStatsSnapshotRecord],
    *,
    period_label: str,
    compare_snapshots: Iterable[StrategyStatsSnapshotRecord] | None = None,
    extra_snapshots: Iterable[StrategyStatsSnapshotRecord] | None = None,
    extra_period_label: str | None = None,
    language_code: str = "en",
) -> str:
    is_ru = normalize_language(language_code) == "ru"
    primary_by_code = {snapshot.strategy_code: snapshot for snapshot in snapshots}
    compare_by_code = {
        snapshot.strategy_code: snapshot for snapshot in (compare_snapshots or ())
    }
    extra_by_code = {
        snapshot.strategy_code: snapshot for snapshot in (extra_snapshots or ())
    }
    compare_label = _period_label(period_label, language_code=language_code)
    baseline_label = _period_label("7d" if period_label == "1d" else "1d", language_code=language_code)
    title_suffix = f"{compare_label} vs {baseline_label}"
    if extra_period_label:
        title_suffix = f"{title_suffix} + {_period_label(extra_period_label, language_code=language_code)}"
    title = "Admin Stats" if not is_ru else "Админ-дашборд"
    intro = (
        "Быстрый срез по стратегиям: что создано, что реально отправлено, что скрыто и как закрылись сигналы."
        if is_ru
        else "Quick strategy audit: what was created, what was really sent, what stayed hidden, and how signals resolved."
    )
    lines = [f"<b>{escape_html(title)} • {escape_html(title_suffix)}</b>", "", escape_html(intro)]

    def _period_lines(snapshot: StrategyStatsSnapshotRecord, label: str) -> list[str]:
        return [
            (
                f"<b>{escape_html(label)}</b>: "
                f"{'создано' if is_ru else 'created'} <b>{snapshot.total_signals}</b> | "
                f"{'отправлено' if is_ru else 'sent'} <b>{snapshot.delivered_count}</b> | "
                f"{'скрыто' if is_ru else 'hidden'} <b>{snapshot.suppressed_count}</b>"
            ),
            (
                f"TP <b>{snapshot.wins}</b> | "
                f"SL <b>{snapshot.losses}</b> | "
                f"amb <b>{snapshot.ambiguous_count}</b> | "
                f"{'expired' if is_ru else 'expired'} <b>{snapshot.expired_neutral}</b> | "
                f"WR <b>{_snapshot_win_rate(snapshot):.1f}%</b>"
            ),
        ]

    for strategy_code, primary in primary_by_code.items():
        strategy_name = _localized_profile(
            _STRATEGY_BY_CODE.get(strategy_code, _STRATEGY_BY_CODE["rsi"]),
            language_code=language_code,
        ).name
        lines.extend(["", f"<b>{escape_html(strategy_name)}</b>"])
        lines.extend(_period_lines(primary, compare_label))
        compare = compare_by_code.get(strategy_code)
        if compare is not None:
            lines.extend(_period_lines(compare, baseline_label))
        extra = extra_by_code.get(strategy_code)
        if extra is not None and extra_period_label:
            lines.extend(_period_lines(extra, _period_label(extra_period_label, language_code=language_code)))
        rr_label = f"{primary.avg_rr:.2f}" if primary.avg_rr is not None else _na(language_code)
        flow_label = f"{primary.signals_per_day:.2f}" if primary.signals_per_day is not None else _na(language_code)
        lines.append(
            f"{'Винрейт' if is_ru else 'Win rate'}: <b>{_snapshot_win_rate(primary):.1f}%</b>"
        )
        if is_ru:
            lines.append(
                f"Поток <b>{flow_label}/день</b> | Лучший ТФ <b>{escape_html(primary.best_tf or _na(language_code))}</b> | RR <b>{rr_label}</b>"
            )
            lines.append(
                f"Лучший режим <b>{escape_html(primary.best_regime or _na(language_code))}</b> | Лучшие активы <b>{escape_html(primary.best_assets or _na(language_code))}</b>"
            )
        else:
            lines.append(
                f"Flow <b>{flow_label}/day</b> | Best TF <b>{escape_html(primary.best_tf or _na(language_code))}</b> | RR <b>{rr_label}</b>"
            )
            lines.append(
                f"Best regime <b>{escape_html(primary.best_regime or _na(language_code))}</b> | Best assets <b>{escape_html(primary.best_assets or _na(language_code))}</b>"
            )
    return "\n".join(lines)


MessageRenderService.render_admin_stats = _message_render_admin_stats_override


def _message_render_admin_stats_truthful(
    self,
    snapshots: Iterable[StrategyStatsSnapshotRecord],
    *,
    period_label: str,
    compare_snapshots: Iterable[StrategyStatsSnapshotRecord] | None = None,
    extra_snapshots: Iterable[StrategyStatsSnapshotRecord] | None = None,
    extra_period_label: str | None = None,
    language_code: str = "en",
) -> str:
    is_ru = normalize_language(language_code) == "ru"
    primary_by_code = {snapshot.strategy_code: snapshot for snapshot in snapshots}
    compare_by_code = {snapshot.strategy_code: snapshot for snapshot in (compare_snapshots or ())}
    compare_label = _period_label(period_label, language_code=language_code)
    baseline_label = _period_label("7d" if period_label == "1d" else "1d", language_code=language_code)
    title_suffix = f"{compare_label} vs {baseline_label}"
    title = "Админ-дашборд" if is_ru else "Admin Dashboard"
    intro = (
        "Только топ-4 стратегии по винрейту уведомлений. Главный WR считается по реально отправленным уведомлениям."
        if is_ru
        else "Only the top 4 strategies by notification win rate. Primary WR is based on alerts that were actually delivered."
    )
    lines = [f"<b>{escape_html(title)} • {escape_html(title_suffix)}</b>", "", escape_html(intro)]

    def _rank(snapshot: StrategyStatsSnapshotRecord) -> tuple[float, int, int, int]:
        sent_decisions = snapshot.sent_wins + snapshot.sent_losses
        primary_wr = _snapshot_sent_win_rate(snapshot) if sent_decisions > 0 else _snapshot_win_rate(snapshot)
        return (
            primary_wr,
            sent_decisions,
            snapshot.delivered_count,
            snapshot.total_signals,
        )

    ordered_primary = sorted(primary_by_code.values(), key=_rank, reverse=True)[:4]

    def _compact_period(snapshot: StrategyStatsSnapshotRecord, label: str) -> list[str]:
        sent_decisions = snapshot.sent_wins + snapshot.sent_losses
        sent_wr = _snapshot_sent_win_rate(snapshot) if sent_decisions > 0 else 0.0
        line_one = (
            f"{label}: {'созд' if is_ru else 'gen'} <b>{snapshot.total_signals}</b> | "
            f"{'увед' if is_ru else 'sent'} <b>{snapshot.delivered_count}</b> | "
            f"{'скрыто' if is_ru else 'hidden'} <b>{snapshot.suppressed_count}</b>"
        )
        if sent_decisions > 0 or snapshot.delivered_count > 0:
            line_two = (
                f"{'уведы' if is_ru else 'notifs'} • "
                f"TP <b>{snapshot.sent_wins}</b> | SL <b>{snapshot.sent_losses}</b> | "
                f"WR <b>{sent_wr:.1f}%</b>"
            )
        else:
            line_two = (
                "уведы • пока нет закрытых доставленных уведомлений"
                if is_ru
                else "notifs • no closed delivered alerts yet"
            )
        return [line_one, line_two]

    for primary in ordered_primary:
        strategy_code = primary.strategy_code
        strategy_name = _localized_profile(
            _STRATEGY_BY_CODE.get(strategy_code, _STRATEGY_BY_CODE["rsi"]),
            language_code=language_code,
        ).name
        lines.extend(["", f"<b>{escape_html(strategy_name)}</b>"])
        lines.extend(_compact_period(primary, compare_label))
        compare = compare_by_code.get(strategy_code)
        if compare is not None:
            lines.extend(_compact_period(compare, baseline_label))
        rr_value = primary.sent_avg_rr if primary.sent_avg_rr is not None else primary.avg_rr
        rr_label = f"{rr_value:.2f}" if rr_value is not None else _na(language_code)
        best_tf = primary.sent_best_tf or primary.best_tf or _na(language_code)
        best_regime = primary.sent_best_regime or primary.best_regime or _na(language_code)
        best_assets = primary.sent_best_assets or primary.best_assets or _na(language_code)
        if is_ru:
            lines.append(
                f"ТФ <b>{escape_html(best_tf)}</b> | RR <b>{rr_label}</b> | режим <b>{escape_html(best_regime)}</b>"
            )
            lines.append(
                f"Активы: <b>{escape_html(best_assets)}</b>"
            )
        else:
            lines.append(
                f"TF <b>{escape_html(best_tf)}</b> | RR <b>{rr_label}</b> | regime <b>{escape_html(best_regime)}</b>"
            )
            lines.append(
                f"Assets: <b>{escape_html(best_assets)}</b>"
            )
    return "\n".join(lines)


MessageRenderService.render_admin_stats = _message_render_admin_stats_truthful


def _message_render_results_hub_polished(
    self,
    *,
    strategy_label: str | None = None,
    is_admin: bool = False,
    language_code: str = "en",
) -> str:
    is_ru = normalize_language(language_code) == "ru"
    title = "📊 Результаты" if is_ru else "📊 Results"
    subtitle = (
        "Смотри итоги, follow-up и то, как сигналы дошли до результата."
        if is_ru
        else "Review outcomes, follow-ups, and how signals evolved."
    )
    methodology = (
        "<b>Как считаются результаты</b>\n"
        "Lifecycle показывает фактические статусы: активен, подтверждён, рядом с целью, достиг цели, "
        "сломался или истёк. Invalidated и expired не скрываются и не считаются успехом.\n\n"
        "Прошлые результаты не гарантируют будущие."
        if is_ru
        else "<b>How results are calculated</b>\n"
        "Lifecycle uses recorded statuses: active, confirmed, near target, target reached, invalidated, "
        "or expired. Invalidated and expired outcomes stay visible and are not counted as success.\n\n"
        "Past results do not guarantee future results."
    )
    lines = [f"<b>{title}</b>", "", subtitle, "", methodology]
    if strategy_label:
        lines.extend(["", f"{'Стратегия' if is_ru else 'Strategy'}: <b>{escape_html(strategy_label)}</b>"])
    if is_admin:
        lines.extend(["", "👑 Admin stats are available below." if not is_ru else "👑 Ниже доступна админ-стата."])
    return "\n".join(lines)


def _message_render_compare_hub_polished(self, *, is_admin: bool, language_code: str = "en") -> str:
    is_ru = normalize_language(language_code) == "ru"
    lines = [
        "<b>⚖️ Сравнение стратегий</b>" if is_ru else "<b>⚖️ Compare Strategies</b>",
        "",
        "Быстрые различия по стилю, скорости, шуму и рыночному режиму."
        if is_ru
        else "Quick differences in style, speed, noise, and market fit.",
    ]
    if is_admin:
        lines.extend(["", "👑 Admin performance view is also available." if not is_ru else "👑 Ниже доступен и админский срез."])
    return "\n".join(lines)


def _message_render_compare_view_polished(
    self,
    intro: str,
    profiles: Iterable[StrategyProfile],
    *,
    language_code: str = "en",
) -> str:
    is_ru = normalize_language(language_code) == "ru"
    speed_label = "Скорость" if is_ru else "Speed"
    noise_label = "Шум" if is_ru else "Noise"
    fit_label = "Рыночный режим" if is_ru else "Market Fit"
    good_label = "Хорошо для" if is_ru else "Good for"
    weak_label = "Менее удобно" if is_ru else "Less ideal"
    lines = [
        "<b>⚖️ Сравнение стратегий</b>" if is_ru else "<b>⚖️ Compare Strategies</b>",
        "",
        escape_html(intro),
    ]
    for profile in profiles:
        lines.extend(
            [
                "",
                f"<b>{escape_html(profile.name)}</b>",
                f"⚡ {speed_label}: <b>{escape_html(profile.signal_frequency)}</b>",
                f"🔊 {noise_label}: <b>{escape_html(profile.noise_level)}</b>",
                f"📈 {fit_label}: <b>{escape_html(profile.regime)}</b>",
                f"✅ {good_label}: {escape_html(profile.best_for)}",
                f"⚠️ {weak_label}: {escape_html(profile.avoid_when)}",
            ]
        )
    return "\n".join(lines)


def _message_render_lifecycle_hub_polished(
    self,
    *,
    strategy_label: str | None = None,
    language_code: str = "en",
) -> str:
    is_ru = normalize_language(language_code) == "ru"
    title = "🔄 Signal Lifecycle" if not is_ru else "🔄 Жизненный цикл сигнала"
    lines = [f"<b>{title}</b>", ""]
    if strategy_label:
        lines.append(f"{'Strategy' if not is_ru else 'Стратегия'}: <b>{escape_html(strategy_label)}</b>")
        lines.append("")
    lines.append(
        "Track how delivered setups stayed open, confirmed, invalidated, or fully closed."
        if not is_ru
        else "Смотри, какие сигналы остались в работе, подтвердились, сломались или полностью закрылись."
    )
    return "\n".join(lines)


def _message_render_learn_hub_polished(self, *, language_code: str = "en") -> str:
    is_ru = normalize_language(language_code) == "ru"
    return (
        "<b>📚 Learn</b>\n\nUnderstand the logic behind signals, setups, risk, and AI analysis."
        if not is_ru
        else "<b>📚 Обучение</b>\n\nРазберись, как устроены сигналы, сетапы, риск и AI-разбор."
    )


MessageRenderService.render_results_hub = _message_render_results_hub_polished
MessageRenderService.render_compare_hub = _message_render_compare_hub_polished
MessageRenderService.render_compare_view = _message_render_compare_view_polished
MessageRenderService.render_lifecycle_hub = _message_render_lifecycle_hub_polished
MessageRenderService.render_learn_hub = _message_render_learn_hub_polished


def _message_render_admin_stats_personalized(
    self,
    snapshots: Iterable[StrategyStatsSnapshotRecord],
    *,
    period_label: str,
    compare_snapshots: Iterable[StrategyStatsSnapshotRecord] | None = None,
    extra_snapshots: Iterable[StrategyStatsSnapshotRecord] | None = None,
    extra_period_label: str | None = None,
    language_code: str = "en",
) -> str:
    del extra_snapshots, extra_period_label
    is_ru = normalize_language(language_code) == "ru"
    primary_by_code = {snapshot.strategy_code: snapshot for snapshot in snapshots}
    compare_by_code = {snapshot.strategy_code: snapshot for snapshot in (compare_snapshots or ())}
    compare_label = _period_label(period_label, language_code=language_code)
    baseline_label = _period_label("7d" if period_label == "1d" else "1d", language_code=language_code)
    title = f"<b>{escape_html('Админ-дашборд' if is_ru else 'Admin Dashboard')} • {escape_html(compare_label)} vs {escape_html(baseline_label)}</b>"
    intro = (
        "Только топ-4 стратегии по твоему реальному потоку: отправлено именно тебе и скрыто только из-за выключенной стратегии."
        if is_ru
        else "Only the top 4 strategies for your real flow: sent to you plus alerts hidden only because the strategy was off."
    )
    lines = [title, "", escape_html(intro)]

    def _rank(snapshot: StrategyStatsSnapshotRecord) -> tuple[float, int, int, int]:
        return (
            _snapshot_win_rate(snapshot),
            int(snapshot.delivered_count or 0),
            int(snapshot.total_signals or 0),
            int(snapshot.wins or 0),
        )

    def _compact_period(snapshot: StrategyStatsSnapshotRecord, label: str) -> list[str]:
        line_one = (
            f"{label}: {'созд' if is_ru else 'gen'} <b>{snapshot.total_signals}</b> | "
            f"{'увед' if is_ru else 'sent'} <b>{snapshot.delivered_count}</b> | "
            f"{'скрыто' if is_ru else 'hidden'} <b>{snapshot.suppressed_count}</b>"
        )
        line_two = (
            f"{'поток' if is_ru else 'flow'} • "
            f"TP <b>{snapshot.wins}</b> | SL <b>{snapshot.losses}</b> | "
            f"amb <b>{snapshot.ambiguous_count}</b> | exp <b>{snapshot.expired_neutral}</b> | "
            f"WR <b>{_snapshot_win_rate(snapshot):.1f}%</b>"
        )
        return [line_one, line_two]

    ordered_primary = sorted(primary_by_code.values(), key=_rank, reverse=True)[:4]
    for primary in ordered_primary:
        strategy_name = _localized_profile(
            _STRATEGY_BY_CODE.get(primary.strategy_code, _STRATEGY_BY_CODE["rsi"]),
            language_code=language_code,
        ).name
        lines.extend(["", f"<b>{escape_html(strategy_name)}</b>"])
        lines.extend(_compact_period(primary, compare_label))
        compare = compare_by_code.get(primary.strategy_code)
        if compare is not None:
            lines.extend(_compact_period(compare, baseline_label))
        rr_value = primary.avg_rr if primary.avg_rr is not None else primary.sent_avg_rr
        rr_label = f"{rr_value:.2f}" if rr_value is not None else _na(language_code)
        best_tf = primary.best_tf or primary.sent_best_tf or _na(language_code)
        best_regime = primary.best_regime or primary.sent_best_regime or _na(language_code)
        best_assets = primary.best_assets or primary.sent_best_assets or _na(language_code)
        if is_ru:
            lines.append(f"ТФ <b>{escape_html(best_tf)}</b> | RR <b>{rr_label}</b> | режим <b>{escape_html(best_regime)}</b>")
            lines.append(f"Активы: <b>{escape_html(best_assets)}</b>")
        else:
            lines.append(f"TF <b>{escape_html(best_tf)}</b> | RR <b>{rr_label}</b> | regime <b>{escape_html(best_regime)}</b>")
            lines.append(f"Assets: <b>{escape_html(best_assets)}</b>")
    return "\n".join(lines)


MessageRenderService.render_admin_stats = _message_render_admin_stats_personalized
