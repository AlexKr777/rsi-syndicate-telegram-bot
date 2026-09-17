from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from src.localization import is_russian


@dataclass(slots=True)
class RationaleFactor:
    title: str
    detail: str


@dataclass(slots=True)
class SignalRationale:
    summary: str
    setup_quality: str
    factors: list[RationaleFactor]
    watch_next: list[str]

    def as_json(self) -> dict[str, object]:
        return {
            "summary": self.summary,
            "setup_quality": self.setup_quality,
            "factors": [asdict(factor) for factor in self.factors],
            "watch_next": list(self.watch_next),
        }


def compute_signal_rationale(
    *,
    frame: pd.DataFrame,
    direction: str,
    timeframe: str,
    score: int,
    closed_rsi: float,
    live_rsi: float | None,
    volume_ratio: float | None,
    language: str = "en",
) -> SignalRationale:
    russian = is_russian(language)
    row = frame.iloc[-1]
    close_price = float(row["close"])
    ema20 = float(row["ema20"]) if pd.notna(row.get("ema20")) else close_price
    ema50 = float(row["ema50"]) if pd.notna(row.get("ema50")) else close_price
    atr_pct = float(row["atr_pct"]) if pd.notna(row.get("atr_pct")) else 0.0
    lows = frame["low"].tail(min(len(frame), 20))
    highs = frame["high"].tail(min(len(frame), 20))
    recent_low = float(lows.min()) if not lows.empty else close_price
    recent_high = float(highs.max()) if not highs.empty else close_price

    if russian:
        if direction == "oversold":
            summary = (
                f"Сигнал появился потому, что RSI на таймфрейме {timeframe} заметно растянут вниз. "
                "Обычно это зона, где краткосрочные продажи могут начать выдыхаться."
            )
            quality = (
                "Выше среднего по чистоте"
                if score >= 75
                else "Рабочий, но с примесью шума"
                if score >= 60
                else "Скорее для наблюдения"
            )
            first_watch = "Смотри, удерживает ли цена локальный минимум и продолжает ли RSI выходить из экстремальной зоны."
        elif direction == "overbought":
            summary = (
                f"Сигнал появился потому, что RSI на таймфрейме {timeframe} заметно растянут вверх. "
                "Обычно это зона, где краткосрочный апсайд может начать остывать."
            )
            quality = (
                "Выше среднего по чистоте"
                if score >= 75
                else "Рабочий, но с примесью шума"
                if score >= 60
                else "Скорее для наблюдения"
            )
            first_watch = "Смотри, перестает ли цена расширяться вверх и возвращается ли RSI из экстремальной зоны."
        else:
            summary = (
                f"На таймфрейме {timeframe} экстремум уже ослаб. "
                "Главная ценность сейчас в контексте, а не в чистом триггере."
            )
            quality = "Только контекст"
            first_watch = "Смотри, вернется ли рынок в экстремум или структура станет чище для нового сетапа."

        trend_note = (
            "Цена все еще ниже EMA20 и EMA50, поэтому сетап идет против ближайшего тренда."
            if close_price < ema20 < ema50
            else "Цена выше EMA20 и EMA50, поэтому структура тренда помогает сценарию."
            if close_price > ema20 > ema50
            else "Структура тренда смешанная, поэтому сетапу нужна более качественная реакция цены."
        )
        volume_note = (
            f"Объем сейчас около {volume_ratio:.2f}x от среднего за 20 свечей, это добавляет контекста движению."
            if volume_ratio is not None
            else "По объему нет достаточно сильного расширения, чтобы делать на него главную ставку."
        )
        location_note = (
            f"Цена реагирует недалеко от недавнего локального минимума около {recent_low:.6g}."
            if direction == "oversold"
            else f"Цена реагирует недалеко от недавнего локального максимума около {recent_high:.6g}."
            if direction == "overbought"
            else f"Цена сейчас между недавним минимумом {recent_low:.6g} и максимумом {recent_high:.6g}."
        )
        live_note = (
            f"Текущий RSI около {live_rsi:.2f}, это показывает, как наклонена незакрытая свеча."
            if isinstance(live_rsi, (int, float))
            else "Текущий RSI недоступен, поэтому сейчас больше веса у закрытой свечи."
        )
        factors = [
            RationaleFactor("Состояние RSI", f"Закрытый RSI сейчас {closed_rsi:.2f} на активном таймфрейме {timeframe}."),
            RationaleFactor("Контекст тренда", trend_note),
            RationaleFactor("Контекст объема", volume_note),
            RationaleFactor("Локация", location_note),
            RationaleFactor("Волатильность", f"ATR сейчас около {atr_pct * 100:.2f}% от цены, это помогает понять, сколько пространства может понадобиться сетапу."),
            RationaleFactor("Подтверждение по текущей свече", live_note),
        ]
        watch_next = [
            first_watch,
            "Если объем быстро сдуется, а структура начнет ломаться, качество сетапа быстро ухудшится.",
            "Если цена продолжит уважать зону реакции, сетапом станет проще управлять через более понятную инвалидацию.",
        ]
    else:
        if direction == "oversold":
            summary = f"The signal exists because RSI is stretched lower on the {timeframe}, which often marks an area where short-term selling can start to exhaust."
            quality = "Cleaner than average" if score >= 75 else "Tradable but mixed" if score >= 60 else "Watchlist quality"
            first_watch = "Watch for price to hold above the local low while RSI lifts out of the extreme zone."
        elif direction == "overbought":
            summary = f"The signal exists because RSI is stretched higher on the {timeframe}, which often marks an area where short-term upside can start to cool off."
            quality = "Cleaner than average" if score >= 75 else "Tradable but mixed" if score >= 60 else "Watchlist quality"
            first_watch = "Watch for price to stop expanding while RSI fades back under the extreme zone."
        else:
            summary = f"This is no longer an extreme on the {timeframe}; the main value now is contextual rather than trigger-based."
            quality = "Context only"
            first_watch = "Watch whether the market stretches again or whether structure improves enough to justify a fresh setup."

        trend_note = (
            "Price is still trading under EMA20 and EMA50, so the move is working against the near-term trend."
            if close_price < ema20 < ema50
            else "Price is above EMA20 and EMA50, so trend support is helping the move."
            if close_price > ema20 > ema50
            else "Trend structure is mixed, so the signal needs more help from price reaction."
        )
        volume_note = (
            f"Volume is running at roughly {volume_ratio:.2f}x the 20-bar average, which gives the move more context."
            if volume_ratio is not None
            else "Volume expansion is not clear enough to be a primary reason on its own."
        )
        location_note = (
            f"Price is reacting close to the recent swing low around {recent_low:.6g}."
            if direction == "oversold"
            else f"Price is reacting close to the recent swing high around {recent_high:.6g}."
            if direction == "overbought"
            else f"Price is sitting between the recent low {recent_low:.6g} and recent high {recent_high:.6g}."
        )
        live_note = (
            f"Live RSI is around {live_rsi:.2f}, which helps show how the current candle is leaning."
            if isinstance(live_rsi, (int, float))
            else "Live RSI is not available, so the closed candle carries more weight right now."
        )
        factors = [
            RationaleFactor("RSI condition", f"Closed RSI is {closed_rsi:.2f} on the active {timeframe} view."),
            RationaleFactor("Trend context", trend_note),
            RationaleFactor("Volume context", volume_note),
            RationaleFactor("Location", location_note),
            RationaleFactor("Volatility", f"ATR is running at about {atr_pct * 100:.2f}% of price, which helps frame how much room the setup may need."),
            RationaleFactor("Live confirmation", live_note),
        ]
        watch_next = [
            first_watch,
            "If volume fades and structure weakens quickly, this setup loses quality fast.",
            "If price keeps respecting the reaction area, the setup becomes easier to manage with clearer invalidation.",
        ]

    return SignalRationale(
        summary=summary,
        setup_quality=quality,
        factors=factors,
        watch_next=watch_next,
    )
