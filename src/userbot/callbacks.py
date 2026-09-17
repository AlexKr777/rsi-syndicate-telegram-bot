from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UserBotCallbackAction:
    kind: str
    value: str | None = None
    extra: str | None = None


_V2_CALLBACK_OPERATIONS: dict[str, frozenset[str]] = {
    "home": frozenset({"simple", "pro"}),
    "onboarding": frozenset({"style", "market", "quality", "delivery", "back", "confirm", "cancel"}),
    "signals": frozenset({"best", "new", "watchlist", "all", "strategy"}),
    "signal": frozenset({"open"}),
    "strategies": frozenset({"hub", "open", "toggle", "compare", "guide", "settings", "delivery", "quality"}),
    "flow": frozenset({"hub", "style", "style_preview", "style_apply", "assets", "assets_apply", "assets_manual", "quality", "quality_apply", "reset"}),
    "flows": frozenset({"hub", "list"}),
    "notifications": frozenset({"hub", "toggle", "delivery", "snooze"}),
    "settings": frozenset({"hub"}),
    "results": frozenset({"hub", "today", "week", "strategies", "lifecycle", "recent", "methodology", "diagnostics"}),
    "watchlist": frozenset({"hub", "manage"}),
    "access": frozenset({"hub"}),
    "help": frozenset({"hub"}),
    "analytics": frozenset({"hub", "analyze"}),
    "market": frozenset({"hub", "sets", "set"}),
    "gold": frozenset({"hub"}),
    "nav": frozenset({"back"}),
}


def parse_userbot_callback_data(callback_data: str | None) -> UserBotCallbackAction | None:
    if not callback_data:
        return None
    if callback_data.startswith("v2:"):
        parts = callback_data.split(":")
        if len(parts) < 3:
            return None
        domain, operation = parts[1], parts[2]
        if operation not in _V2_CALLBACK_OPERATIONS.get(domain, frozenset()):
            return None
        value = parts[3] if len(parts) >= 4 and parts[3] else None
        extra = ":".join(parts[4:]) if len(parts) >= 5 else None
        return UserBotCallbackAction(kind=f"v2_{domain}_{operation}", value=value, extra=extra)
    if callback_data.startswith("main:"):
        _, section, *rest = callback_data.split(":")
        mapping = {
            "hub": "menu",
            "today": "menu",
            "signals": "signalshub",
            "strategies": "strategies",
            "setups": "setupshub",
            "alerts": "deliveryhub",
            "favorites": "watchhub",
            "watchlists": "watchhub",
            "results": "results_hub",
            "compare": "compare_hub",
            "learn": "learn_hub",
            "ai": "analyze",
            "settings": "settingshub",
            "access": "access",
            "help": "help",
        }
        return UserBotCallbackAction(kind=mapping.get(section, section), extra=rest[0] if rest else None)
    if callback_data.startswith("strategy:"):
        parts = callback_data.split(":")
        if len(parts) >= 3 and parts[1] in {
            "open",
            "toggle",
            "signals",
            "filters",
            "alerts",
            "favorites",
            "quicksetup",
            "results",
            "guide",
            "settings",
            "compare",
        }:
            return UserBotCallbackAction(kind=f"strategy_{parts[1]}", value=parts[2])
        if len(parts) >= 3 and parts[1] == "lifecycle":
            return UserBotCallbackAction(
                kind="strategy_lifecycle",
                value=parts[2],
                extra=parts[3] if len(parts) >= 4 and parts[3] else "hub",
            )
        return None
    if callback_data.startswith("compare:"):
        parts = callback_data.split(":")
        if len(parts) >= 2 and parts[1] == "hub":
            return UserBotCallbackAction(kind="compare_hub")
        if len(parts) >= 3 and parts[1] == "view":
            return UserBotCallbackAction(kind="compare_view", value=parts[2])
        if len(parts) >= 2 and parts[1] == "admin":
            return UserBotCallbackAction(kind="compare_admin")
        return None
    if callback_data.startswith("learn:"):
        parts = callback_data.split(":")
        if len(parts) >= 2 and parts[1] == "hub":
            return UserBotCallbackAction(kind="learn_hub")
        if len(parts) >= 3 and parts[1] == "guide":
            return UserBotCallbackAction(kind="learn_guide", value=parts[2])
        if len(parts) >= 2:
            return UserBotCallbackAction(kind="learn_page", value=parts[1])
        return None
    if callback_data.startswith("results:"):
        parts = callback_data.split(":")
        if len(parts) >= 2 and parts[1] == "hub":
            return UserBotCallbackAction(kind="results_hub")
        if len(parts) >= 2 and parts[1] == "admin":
            return UserBotCallbackAction(kind="results_admin", value=parts[2] if len(parts) >= 3 else "7d")
        if len(parts) >= 3 and parts[1] == "personal":
            return UserBotCallbackAction(kind="personal_summary", value=parts[2])
        if len(parts) >= 2:
            return UserBotCallbackAction(kind="results_view", value=parts[1])
        return None
    if callback_data.startswith("lifecycle:"):
        parts = callback_data.split(":")
        if len(parts) >= 2 and parts[1] == "hub":
            return UserBotCallbackAction(kind="lifecycle_hub")
        if len(parts) >= 2:
            return UserBotCallbackAction(kind="lifecycle_view", value=parts[1])
        return None
    if not callback_data.startswith("ux:"):
        return None
    parts = callback_data.split(":")
    if len(parts) < 2:
        return None

    kind = parts[1]
    contextual_hub_kinds = {
        "signalshub",
        "watchhub",
        "deliveryhub",
        "statshub",
        "aihub",
        "settingshub",
    }
    if kind in contextual_hub_kinds:
        return UserBotCallbackAction(
            kind=kind,
            extra=parts[2] if len(parts) >= 3 and parts[2] else None,
        )
    if kind == "prohub" and len(parts) >= 3 and parts[2]:
        return UserBotCallbackAction(kind="pro_hub", value=parts[2])
    if kind == "setupshub":
        return UserBotCallbackAction(kind="setupshub")
    if kind == "quickfiltershub":
        return UserBotCallbackAction(kind="quickfiltershub")
    if kind == "filtershub":
        return UserBotCallbackAction(kind="custom_filters_hub")
    if kind == "noisehub":
        return UserBotCallbackAction(kind="noisehub")
    if kind == "scorehub":
        return UserBotCallbackAction(kind="scorehub")
    if kind == "sessionhub":
        return UserBotCallbackAction(kind="sessionhub")
    if kind == "deliveryrules":
        return UserBotCallbackAction(kind="delivery_rules_hub")
    if kind == "hidemute":
        if len(parts) == 2:
            return UserBotCallbackAction(kind="hide_mute_hub")
        if len(parts) >= 4 and parts[2] == "asset" and parts[3] == "prompt":
            return UserBotCallbackAction(kind="hide_asset_prompt")
        if len(parts) >= 4 and parts[2] == "view":
            return UserBotCallbackAction(kind="hide_mute_view", value=parts[3])
        if len(parts) >= 4 and parts[2] == "toggle":
            return UserBotCallbackAction(kind="hide_mute_toggle", value=parts[3])
        if len(parts) >= 4 and parts[2] == "strategy":
            return UserBotCallbackAction(kind="hide_strategy", value=parts[3])
        if len(parts) >= 4 and parts[2] == "timeframe":
            return UserBotCallbackAction(kind="hide_timeframe", value=parts[3])
        if len(parts) >= 4 and parts[2] == "repeats":
            return UserBotCallbackAction(kind="hide_repeats", value=parts[3])
        if len(parts) >= 3 and parts[2] == "resume":
            return UserBotCallbackAction(kind="hide_mute_resume")
    if kind == "stylehub":
        return UserBotCallbackAction(kind="style_hub")
    if kind == "summary" and len(parts) >= 3 and parts[2]:
        return UserBotCallbackAction(kind="personal_summary", value=parts[2])
    if kind == "setup":
        if len(parts) == 2:
            return UserBotCallbackAction(kind="setup")
        if len(parts) >= 3:
            if parts[2] in {"list", "create", "savecurrent", "pinned"}:
                return UserBotCallbackAction(kind=f"setup_{parts[2]}")
            if parts[2] in {"detail", "activate", "edit", "update", "rename", "duplicate", "delete", "default", "pin"} and len(parts) >= 4 and parts[3]:
                return UserBotCallbackAction(kind=f"setup_{parts[2]}", value=parts[3])
        return UserBotCallbackAction(kind="setup")
    if kind == "help" and len(parts) >= 3 and parts[2]:
        return UserBotCallbackAction(kind="help_page", value=parts[2])
    if kind in {
        "watchlist",
        "access",
        "referral",
        "renew",
        "analyze",
        "menu",
        "strategies",
        "status",
        "health",
        "help",
        "ai",
        "pro",
        "pay",
        "goldview",
        "goldhub",
        "themes",
        "control",
        "workspacehub",
    }:
        return UserBotCallbackAction(kind=kind)
    if kind == "display" and len(parts) >= 3 and parts[2]:
        return UserBotCallbackAction(kind="display_mode_view", value=parts[2])
    if kind == "workspace" and len(parts) >= 3:
        if parts[2] == "save":
            return UserBotCallbackAction(kind="workspace_save")
        if len(parts) >= 5 and parts[2] == "apply" and parts[3] and parts[4]:
            return UserBotCallbackAction(kind="workspace_apply", value=parts[4], extra=parts[3])
        if len(parts) >= 4 and parts[2] == "apply" and parts[3]:
            return UserBotCallbackAction(kind="workspace_apply", value=parts[3], extra="default")
    if kind == "setupbuilder" and len(parts) >= 3:
        if parts[2] == "back":
            return UserBotCallbackAction(kind="setup_builder_back")
        if parts[2] == "cancel":
            return UserBotCallbackAction(kind="setup_builder_cancel")
        if parts[2] == "next":
            return UserBotCallbackAction(kind="setup_builder_next")
        if parts[2] == "prompt" and len(parts) >= 4 and parts[3]:
            return UserBotCallbackAction(kind="setup_builder_prompt", value=parts[3])
        if parts[2] == "start" and len(parts) >= 4 and parts[3]:
            return UserBotCallbackAction(kind="setup_builder_start", value=parts[3])
        if parts[2] == "template" and len(parts) >= 4 and parts[3]:
            return UserBotCallbackAction(kind="setup_builder_template", value=parts[3])
        if parts[2] == "save" and len(parts) >= 4 and parts[3]:
            return UserBotCallbackAction(kind="setup_builder_save", value=parts[3])
        if parts[2] == "set" and len(parts) >= 5 and parts[3] and parts[4]:
            return UserBotCallbackAction(kind="setup_builder_set", value=parts[3], extra=parts[4])
        if parts[2] == "toggle" and len(parts) >= 5 and parts[3] and parts[4]:
            return UserBotCallbackAction(kind="setup_builder_toggle", value=parts[3], extra=parts[4])
    if kind == "goldwizard" and len(parts) >= 3:
        if parts[2] == "start":
            return UserBotCallbackAction(kind="gold_wizard_start")
        if parts[2] == "back":
            return UserBotCallbackAction(kind="gold_wizard_back")
        if parts[2] == "cancel":
            return UserBotCallbackAction(kind="gold_wizard_cancel")
        if parts[2] == "next":
            return UserBotCallbackAction(kind="gold_wizard_next")
        if parts[2] == "apply":
            return UserBotCallbackAction(kind="gold_wizard_apply")
        if parts[2] == "set" and len(parts) >= 5 and parts[3] and parts[4]:
            return UserBotCallbackAction(kind="gold_wizard_set", value=parts[3], extra=parts[4])
    if kind == "guide" and len(parts) >= 3 and parts[2] == "close":
        return UserBotCallbackAction(kind="guide", value="close")
    if kind == "guide":
        return UserBotCallbackAction(kind="guide")
    if kind == "welcome" and len(parts) >= 3:
        if parts[2] == "example":
            return UserBotCallbackAction(kind="onboarding_example")
        if parts[2] == "read":
            return UserBotCallbackAction(kind="onboarding_read")
    if kind == "custom" and len(parts) >= 3 and parts[2] in {"start", "cancel"}:
        return UserBotCallbackAction(kind="custom", value=parts[2])
    if kind == "signals" and len(parts) >= 3:
        if parts[2] in {"recent", "strong", "fresh"}:
            return UserBotCallbackAction(kind="signals", value=parts[2])
        if parts[2] == "open" and len(parts) >= 4 and parts[3]:
            return UserBotCallbackAction(kind="open_signal", value=parts[3])
    if kind == "profile" and len(parts) >= 3 and parts[2]:
        return UserBotCallbackAction(kind="profile", value=parts[2])
    if kind == "pref" and len(parts) >= 4 and parts[2] and parts[3]:
        return UserBotCallbackAction(kind="strategy_pref", value=parts[2], extra=parts[3])
    if kind == "rsi" and len(parts) >= 3 and parts[2]:
        return UserBotCallbackAction(kind="rsi", value=parts[2])
    if kind == "volume" and len(parts) >= 3 and parts[2]:
        return UserBotCallbackAction(kind="volume", value=parts[2])
    if kind == "direction" and len(parts) >= 3 and parts[2]:
        return UserBotCallbackAction(kind="direction", value=parts[2])
    if kind == "universe" and len(parts) >= 3 and parts[2]:
        return UserBotCallbackAction(kind="universe", value=parts[2])
    if kind == "gold" and len(parts) >= 3 and parts[2]:
        return UserBotCallbackAction(kind="gold", value=parts[2])
    if kind == "watch" and len(parts) >= 4 and parts[3]:
        if parts[2] in {"open", "remove"}:
            return UserBotCallbackAction(kind=f"watch_{parts[2]}", value=parts[3])
    if kind == "theme" and len(parts) >= 3:
        if parts[2] == "all":
            return UserBotCallbackAction(kind="theme_all")
        if parts[2] == "save":
            return UserBotCallbackAction(kind="theme_save")
        if parts[2] == "builtin" and len(parts) >= 4:
            return UserBotCallbackAction(kind="theme_builtin", value=parts[3])
        if parts[2] in {"open", "rename", "delete", "add"} and len(parts) >= 4 and parts[3]:
            return UserBotCallbackAction(kind=f"theme_{parts[2]}", value=parts[3])
    if kind == "delivery" and len(parts) >= 4 and parts[2] == "mode":
        return UserBotCallbackAction(kind="delivery_mode", value=parts[3])
    if kind == "deliveryruleview" and len(parts) >= 3 and parts[2]:
        return UserBotCallbackAction(kind="delivery_rule_view", value=parts[2])
    if kind == "deliveryrule" and len(parts) >= 4 and parts[2] and parts[3]:
        return UserBotCallbackAction(kind="delivery_rule_set", value=parts[2], extra=parts[3])
    if kind == "qf" and len(parts) >= 3:
        if parts[2] == "reset":
            return UserBotCallbackAction(kind="quickfilter_reset")
        if len(parts) >= 4 and parts[2] == "apply" and parts[3]:
            return UserBotCallbackAction(kind="quickfilter_apply", value=parts[3])
    if kind == "noise" and len(parts) >= 3 and parts[2]:
        return UserBotCallbackAction(kind="noise_set", value=parts[2])
    if kind == "score" and len(parts) >= 3 and parts[2]:
        return UserBotCallbackAction(kind="score_set", value=parts[2])
    if kind == "session" and len(parts) >= 3 and parts[2]:
        return UserBotCallbackAction(kind="session_set", value=parts[2])
    if kind == "snooze" and len(parts) >= 3 and parts[2]:
        return UserBotCallbackAction(kind="snooze", value=parts[2])
    if kind == "quiet" and len(parts) >= 3 and parts[2]:
        return UserBotCallbackAction(kind="quiet_hours", value=parts[2])
    if kind == "toggle" and len(parts) >= 3 and parts[2]:
        return UserBotCallbackAction(kind="toggle", value=parts[2])
    if kind == "recap" and len(parts) >= 3 and parts[2]:
        return UserBotCallbackAction(kind="recap", value=parts[2])
    if kind == "onboard" and len(parts) >= 3:
        if parts[2] == "start":
            return UserBotCallbackAction(kind="onboard", value="start")
        if len(parts) >= 5:
            return UserBotCallbackAction(kind="onboard", value=parts[2], extra=parts[3] + ":" + parts[4] if len(parts) > 5 else parts[4])
        if len(parts) >= 4:
            return UserBotCallbackAction(kind="onboard", value=parts[2], extra=parts[3])
    if kind == "language" and len(parts) >= 3:
        if parts[2] == "picker":
            return UserBotCallbackAction(kind="language_picker", value=parts[3] if len(parts) >= 4 and parts[3] else "settings")
        if parts[2] == "set" and len(parts) >= 4 and parts[3]:
            return UserBotCallbackAction(
                kind="language_set",
                value=parts[3],
                extra=parts[4] if len(parts) >= 5 and parts[4] else None,
            )
    if kind == "style" and len(parts) >= 3:
        if parts[2] == "save":
            return UserBotCallbackAction(kind="style_save")
        if len(parts) >= 4 and parts[2] == "view" and parts[3]:
            return UserBotCallbackAction(kind="style_view", value=parts[3])
        if len(parts) >= 5 and parts[2] == "set" and parts[3] and parts[4]:
            return UserBotCallbackAction(kind="style_set", value=parts[3], extra=parts[4])
    if kind == "strategy" and len(parts) >= 4 and parts[2] in {"open", "toggle"} and parts[3]:
        return UserBotCallbackAction(kind=f"strategy_{parts[2]}", value=parts[3])
    return None
