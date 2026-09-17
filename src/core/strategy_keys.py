from __future__ import annotations

GOLD_MASTER_STRATEGY_KEY = "gold"
OKAK_STRATEGY_KEY = "okak"
EKEK_STRATEGY_KEY = "ekek"
GOLD_SUBSTRATEGY_KEYS = (
    "gold_breakout",
    "gold_pullback",
    "gold_liquidity",
)
VISIBLE_PREMIUM_STRATEGY_KEYS = (
    "breakout",
    "trend_pullback",
    "rsi_bollinger_mr",
    "rsi_bollinger_touch",
    "daily_rsi_80",
    "vwap",
    "false_breakout",
    "rsi",
    "rsi_divergence",
    "bollinger",
    EKEK_STRATEGY_KEY,
    GOLD_MASTER_STRATEGY_KEY,
)

PREMIUM_STRATEGY_KEYS = (
    *VISIBLE_PREMIUM_STRATEGY_KEYS,
    OKAK_STRATEGY_KEY,
    *GOLD_SUBSTRATEGY_KEYS,
)

PREMIUM_STRATEGY_KEY_SET = frozenset(PREMIUM_STRATEGY_KEYS)
VISIBLE_PREMIUM_STRATEGY_KEY_SET = frozenset(VISIBLE_PREMIUM_STRATEGY_KEYS)
GOLD_SUBSTRATEGY_KEY_SET = frozenset(GOLD_SUBSTRATEGY_KEYS)
