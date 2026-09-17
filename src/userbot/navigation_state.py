from __future__ import annotations

"""Small, message-aware navigation stack for the V2 presentation layer.

The stack deliberately lives in memory: a callback from before a process restart
cannot safely reconstruct mutable UI state, so it is treated as stale and sent
to a deterministic section home instead of a guessed destination.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from src.core.utils import utc_now


@dataclass(frozen=True, slots=True)
class NavigationRoute:
    name: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NavigationState:
    current: NavigationRoute
    stack: list[NavigationRoute]
    created_at: datetime
    updated_at: datetime


class NavigationService:
    """Keeps independent histories for independently opened Telegram messages."""

    def __init__(self, *, ttl: timedelta = timedelta(hours=6), max_depth: int = 16) -> None:
        self.ttl = ttl
        self.max_depth = max_depth
        self._states: dict[tuple[str, int, str, int], NavigationState] = {}

    def _key(self, *, bot_kind: str, user_id: int, chat_id: str, message_id: int) -> tuple[str, int, str, int]:
        return (bot_kind, int(user_id), str(chat_id), int(message_id))

    def open(
        self,
        *,
        bot_kind: str,
        user_id: int,
        chat_id: str,
        message_id: int,
        route: str,
        params: dict[str, Any] | None = None,
        root: bool = False,
        fallback_root: str | None = None,
    ) -> None:
        now = utc_now()
        key = self._key(bot_kind=bot_kind, user_id=user_id, chat_id=chat_id, message_id=message_id)
        target = NavigationRoute(route, dict(params or {}))
        state = self._states.get(key)
        if root or state is None or now - state.updated_at > self.ttl:
            stack = [] if root or not fallback_root or fallback_root == route else [NavigationRoute(fallback_root)]
            self._states[key] = NavigationState(target, stack, now, now)
            return
        if state.current == target:
            state.updated_at = now
            return
        state.stack.append(state.current)
        state.stack = state.stack[-self.max_depth :]
        state.current = target
        state.updated_at = now

    def back(
        self,
        *,
        bot_kind: str,
        user_id: int,
        chat_id: str,
        message_id: int,
    ) -> NavigationRoute | None:
        now = utc_now()
        key = self._key(bot_kind=bot_kind, user_id=user_id, chat_id=chat_id, message_id=message_id)
        state = self._states.get(key)
        if state is None or now - state.updated_at > self.ttl or not state.stack:
            self._states.pop(key, None)
            return None
        state.current = state.stack.pop()
        state.updated_at = now
        return state.current

    def clear(self, *, bot_kind: str, user_id: int, chat_id: str, message_id: int) -> None:
        self._states.pop(
            self._key(bot_kind=bot_kind, user_id=user_id, chat_id=chat_id, message_id=message_id),
            None,
        )
