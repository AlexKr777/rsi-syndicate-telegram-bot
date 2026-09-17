from __future__ import annotations

from importlib import import_module
from types import ModuleType


STRATEGY_MODULES = {
    "double_top_short": "app.strategies.double_top_short",
    "double_bottom_long": "app.strategies.double_bottom_long",
    "breakdown_short": "app.strategies.breakdown_short",
    "oversold_reversal_long": "app.strategies.oversold_reversal_long",
    "trend_pullback_long": "app.strategies.trend_pullback_long",
}


def load_strategy_modules() -> dict[str, ModuleType]:
    return {name: import_module(path) for name, path in STRATEGY_MODULES.items()}


def enabled_strategies(config: dict) -> list[tuple[str, ModuleType]]:
    strategy_configs = config.get("strategies", {})
    modules = load_strategy_modules()
    enabled: list[tuple[str, ModuleType]] = []
    for strategy_name, module in modules.items():
        if bool(strategy_configs.get(strategy_name, {}).get("enabled", False)):
            enabled.append((strategy_name, module))
    return enabled
