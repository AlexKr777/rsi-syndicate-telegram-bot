from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AlertCallbackAction:
    kind: str
    timeframe: str | None = None
    symbol: str | None = None


def parse_alert_callback_data(callback_data: str | None) -> AlertCallbackAction | None:
    if not callback_data:
        return None
    parts = callback_data.split(":")
    if len(parts) < 2:
        return None
    if parts[0] == "detail" and parts[1] == "delete":
        return AlertCallbackAction(kind="delete_detail")
    if parts[0] != "alert":
        return None
    if parts[1] == "ai":
        symbol = parts[2] if len(parts) >= 3 and parts[2] else None
        return AlertCallbackAction(kind="ai", symbol=symbol)
    if parts[1] == "risk":
        symbol = parts[2] if len(parts) >= 3 and parts[2] else None
        return AlertCallbackAction(kind="risk", symbol=symbol)
    if parts[1] == "reason":
        symbol = parts[2] if len(parts) >= 3 and parts[2] else None
        return AlertCallbackAction(kind="reason", symbol=symbol)
    if parts[1] == "compare":
        symbol = parts[2] if len(parts) >= 3 and parts[2] else None
        return AlertCallbackAction(kind="compare", symbol=symbol)
    if parts[1] == "tf" and len(parts) >= 3 and parts[2]:
        symbol = parts[3] if len(parts) >= 4 and parts[3] else None
        return AlertCallbackAction(kind="timeframe", timeframe=parts[2], symbol=symbol)
    return None
