from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from src.localization import is_russian


@dataclass(slots=True)
class RiskOption:
    label: str
    style: str
    stop_loss: float
    take_profit: float
    risk_reward: float
    holding_style: str
    explanation: str


@dataclass(slots=True)
class RiskPlan:
    bias: str
    confidence_label: str
    confidence_score: int
    entry_price: float
    invalidation_level: float
    atr_value: float
    structural_level: float
    options: list[RiskOption]
    capital_management_notes: list[str]
    factor_notes: list[str]

    def as_json(self) -> dict[str, object]:
        return {
            "bias": self.bias,
            "confidence_label": self.confidence_label,
            "confidence_score": self.confidence_score,
            "entry_price": self.entry_price,
            "invalidation_level": self.invalidation_level,
            "atr_value": self.atr_value,
            "structural_level": self.structural_level,
            "options": [asdict(option) for option in self.options],
            "capital_management_notes": list(self.capital_management_notes),
            "factor_notes": list(self.factor_notes),
        }


def compute_risk_plan(
    *,
    frame: pd.DataFrame,
    entry_price: float,
    direction: str,
    score: int,
    timeframe: str,
    trend_note: str,
    volume_note: str,
    language: str = "en",
) -> RiskPlan:
    russian = is_russian(language)
    row = frame.iloc[-1]
    atr_value = float(row["atr"]) if pd.notna(row.get("atr")) and float(row["atr"]) > 0 else entry_price * 0.015
    lows = frame["low"].tail(min(len(frame), 24))
    highs = frame["high"].tail(min(len(frame), 24))
    swing_low = float(lows.min()) if not lows.empty else entry_price * 0.985
    swing_high = float(highs.max()) if not highs.empty else entry_price * 1.015
    bias = "long" if direction == "oversold" else "short" if direction == "overbought" else "watchlist"

    if score >= 85:
        confidence_label = "Высокая уверенность" if russian else "Higher-conviction"
    elif score >= 72:
        confidence_label = "Конструктивно" if russian else "Constructive"
    elif score >= 60:
        confidence_label = "Умеренно" if russian else "Moderate"
    else:
        confidence_label = "Низкая уверенность" if russian else "Low-conviction"

    factor_notes = [
        (
            f"Оценка сигнала {score}/100 на активном таймфрейме {timeframe}."
            if russian
            else f"Signal score is {score}/100 on the active {timeframe} view."
        ),
        trend_note,
        volume_note,
    ]

    if bias == "watchlist":
        invalidation_level = swing_low if float(row["close"]) >= entry_price else swing_high
        options = [
            RiskOption(
                label="Только наблюдение" if russian else "Watchlist only",
                style="neutral",
                stop_loss=invalidation_level,
                take_profit=float(row["close"]),
                risk_reward=0.0,
                holding_style=(
                    f"Ждать следующую реакцию на {timeframe}"
                    if russian
                    else f"Wait for the next {timeframe} reaction"
                ),
                explanation=(
                    "На этом таймфрейме сейчас нет чистого экстремума, поэтому лучшая работа с риском здесь - дождаться, пока структура снова не станет качественнее."
                    if russian
                    else "This timeframe is not in a clean extreme right now, so the better risk choice is patience until structure improves again."
                ),
            )
        ]
        capital_notes = [
            (
                "Держи маленький размер или оставайся вне позиции, пока сетап не вернется в более чистый экстремум или структура цены не станет плотнее."
                if russian
                else "Keep size small or stay flat until the setup returns to a clearer extreme or price structure tightens up."
            ),
            (
                "Если все же входишь, считай это проверкой из наблюдения, а не полноценной позицией."
                if russian
                else "If you do engage, treat it as a watchlist probe rather than a full-size position."
            ),
        ]
        return RiskPlan(
            bias=bias,
            confidence_label=confidence_label,
            confidence_score=score,
            entry_price=entry_price,
            invalidation_level=invalidation_level,
            atr_value=atr_value,
            structural_level=invalidation_level,
            options=options,
            capital_management_notes=capital_notes,
            factor_notes=factor_notes,
        )

    if bias == "long":
        atr_stop = entry_price - (1.15 * atr_value)
        structural_stop = min(swing_low, entry_price - (1.8 * atr_value))
        conservative_stop = max(atr_stop, entry_price - (0.9 * atr_value))
        target_one = max(entry_price + (1.25 * atr_value), entry_price * 1.012)
        target_two = max(entry_price + (2.0 * atr_value), (entry_price + swing_high) / 2)
        target_three = max(entry_price + (2.8 * atr_value), swing_high)
        invalidation_level = structural_stop
    else:
        atr_stop = entry_price + (1.15 * atr_value)
        structural_stop = max(swing_high, entry_price + (1.8 * atr_value))
        conservative_stop = min(atr_stop, entry_price + (0.9 * atr_value))
        target_one = min(entry_price - (1.25 * atr_value), entry_price * 0.988)
        target_two = min(entry_price - (2.0 * atr_value), (entry_price + swing_low) / 2)
        target_three = min(entry_price - (2.8 * atr_value), swing_low)
        invalidation_level = structural_stop

    options = [
        RiskOption(
            label="Консервативный" if russian else "Conservative",
            style="Conservative",
            stop_loss=conservative_stop,
            take_profit=target_one,
            risk_reward=_risk_reward(entry_price, conservative_stop, target_one, bias),
            holding_style=(
                f"Короткая реакция на {timeframe}"
                if russian
                else f"Short-term {timeframe} reaction"
            ),
            explanation=(
                "Более плотная инвалидация и более ранняя фиксация подходят тем, кому нужна быстрая обратная связь и более чистый контроль убытка."
                if russian
                else "Tighter invalidation and earlier profit-taking for traders who want fast feedback and cleaner damage control."
            ),
        ),
        RiskOption(
            label="Сбалансированный" if russian else "Balanced",
            style="Balanced",
            stop_loss=atr_stop,
            take_profit=target_two,
            risk_reward=_risk_reward(entry_price, atr_stop, target_two, bias),
            holding_style=(
                f"Стандартный сценарий на {timeframe}"
                if russian
                else f"Standard {timeframe} swing"
            ),
            explanation=(
                "Риск учитывает ATR, а цель остается более терпеливой и завязана на следующую значимую зону реакции."
                if russian
                else "ATR-aware risk with a more patient target around the next meaningful reaction area."
            ),
        ),
        RiskOption(
            label="Агрессивный" if russian else "Aggressive",
            style="Aggressive",
            stop_loss=structural_stop,
            take_profit=target_three,
            risk_reward=_risk_reward(entry_price, structural_stop, target_three, bias),
            holding_style=(
                "Более долгое удержание, если движение разовьется"
                if russian
                else "Extended hold if the move develops"
            ),
            explanation=(
                "Более широкий структурный запас подходит тем, кто хочет удерживать более крупное движение и готов к более медленной обратной связи."
                if russian
                else "Wider structural room for traders trying to stay with a larger move and accept slower feedback."
            ),
        ),
    ]

    capital_notes = [
        (
            "Можно забрать первую часть возле консервативной цели и сопровождать остаток только если импульс продолжает подтверждаться."
            if russian
            else "Consider taking the first partial near the Conservative target and only trail the remainder if momentum keeps confirming."
        ),
        (
            "На более широкий структурный стоп стоит брать меньший размер. Этот вариант чище по структуре, но ему нужно больше пространства."
            if russian
            else "Risk less size on the wider structural stop. That variant is cleaner structurally, but it needs more room."
        ),
        (
            "Если первая реакция быстро тухнет и RSI быстро теряет силу, часто чище сократить риск раньше, чем насильно держать полный план."
            if russian
            else "If the first reaction stalls and RSI loses energy quickly, reducing exposure early is usually cleaner than forcing the full plan."
        ),
    ]

    return RiskPlan(
        bias=bias,
        confidence_label=confidence_label,
        confidence_score=score,
        entry_price=entry_price,
        invalidation_level=invalidation_level,
        atr_value=atr_value,
        structural_level=structural_stop,
        options=options,
        capital_management_notes=capital_notes,
        factor_notes=factor_notes,
    )


def _risk_reward(entry_price: float, stop_loss: float, take_profit: float, bias: str) -> float:
    if bias == "long":
        risk = max(entry_price - stop_loss, 1e-9)
        reward = max(take_profit - entry_price, 0.0)
    else:
        risk = max(stop_loss - entry_price, 1e-9)
        reward = max(entry_price - take_profit, 0.0)
    return reward / risk if risk > 0 else 0.0
