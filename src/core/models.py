from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


Direction = str


@dataclass(slots=True)
class AlertSignal:
    symbol: str
    direction: Direction
    timeframe: str
    candle_open_time: datetime
    candle_close_time: datetime
    price: float
    rsi: float
    day_change_pct: float | None
    day_volume: float | None
    quote_volume: float | None
    last_candle_volume: float
    avg_volume_20: float
    atr: float
    atr_pct: float
    ema20: float
    ema50: float
    score: int
    explanation: str
    chart_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FollowUpResult:
    alert_id: int
    symbol: str
    direction: Direction
    timeframe: str
    alert_price: float
    current_price: float
    alert_rsi: float
    current_rsi: float
    move_pct: float
    summary: str
    score: int
    observed_at: datetime
    stage: str = "2h"
    thesis_direction: str = ""
    favorable_move_pct: float = 0.0
    adverse_move_pct: float = 0.0
    thesis_result_state: str = "neutral"
    chart_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GeneratedPost:
    channel_kind: str
    destination: str
    content_type: str
    generated_text: str
    status: str
    chart_path: Path | None = None
    delivery_text: str | None = None
    ai_model: str | None = None
    source_symbol: str | None = None
    related_alert_id: int | None = None
    force_autopost: bool = False
    send_lab_copy: bool = False
    bundle_in_lab_review: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TwitterDraft:
    destination: str
    content_type: str
    main_text: str
    mode: str = "NORMAL"
    angle: str = ""
    value_types: tuple[str, ...] = ()
    short_variant: str | None = None
    reply_variant: str | None = None
    source_symbol: str | None = None
    related_alert_id: int | None = None
    score: int | None = None
    chart_path: Path | None = None
    writer_model: str | None = None
    analysis_model: str | None = None
    status: str = "generated"
    similarity_score: float | None = None
    rewritten_for_similarity: bool = False
    preview_mode: bool = False
    skipped_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DeliveryResult:
    destination: str
    message_type: str
    sent: bool
    rate_limited: bool
    batched: bool = False
    telegram_message_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
